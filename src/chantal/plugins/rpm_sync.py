"""
RPM repository sync plugin.

This module implements syncing RPM repositories from upstream sources.
"""

import gzip
import hashlib
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from sqlalchemy.orm import Session

from chantal.core.config import ProxyConfig, RepositoryConfig
from chantal.core.storage import StorageManager
from chantal.db.models import Package, Repository


@dataclass
class PackageMetadata:
    """Package metadata from primary.xml."""

    name: str
    version: str
    release: str
    epoch: Optional[str]
    arch: str
    sha256: str
    size_bytes: int
    location: str  # Relative URL to package file
    summary: Optional[str] = None
    description: Optional[str] = None


@dataclass
class SyncResult:
    """Result of a repository sync operation."""

    packages_downloaded: int
    packages_skipped: int  # Already in pool
    packages_total: int
    bytes_downloaded: int
    success: bool
    error_message: Optional[str] = None


class RpmSyncPlugin:
    """Plugin for syncing RPM repositories.

    Handles:
    - Fetching upstream repomd.xml
    - Parsing primary.xml.gz for package list
    - Downloading packages to storage pool
    - Updating database
    """

    def __init__(
        self,
        storage: StorageManager,
        config: RepositoryConfig,
        proxy_config: Optional[ProxyConfig] = None,
    ):
        """Initialize RPM sync plugin.

        Args:
            storage: Storage manager instance
            config: Repository configuration
            proxy_config: Optional proxy configuration
        """
        self.storage = storage
        self.config = config
        self.proxy_config = proxy_config

        # Setup HTTP session with proxy
        self.session = requests.Session()
        if proxy_config:
            proxies = {}
            if proxy_config.http_proxy:
                proxies["http"] = proxy_config.http_proxy
            if proxy_config.https_proxy:
                proxies["https"] = proxy_config.https_proxy
            self.session.proxies.update(proxies)

            # Basic auth for proxy if needed
            if proxy_config.username and proxy_config.password:
                self.session.auth = (proxy_config.username, proxy_config.password)

    def sync_repository(
        self, session: Session, repository: Repository
    ) -> SyncResult:
        """Sync repository from upstream.

        Args:
            session: Database session
            repository: Repository model instance

        Returns:
            SyncResult with sync statistics
        """
        try:
            print(f"Syncing repository: {repository.repo_id}")
            print(f"Feed URL: {self.config.feed}")

            # Step 1: Fetch repomd.xml
            print("Fetching repomd.xml...")
            repomd_root = self._fetch_repomd_xml(self.config.feed)

            # Step 2: Extract primary.xml.gz location
            primary_location = self._extract_primary_location(repomd_root)
            print(f"Primary metadata location: {primary_location}")

            # Step 3: Download and parse primary.xml.gz
            print("Fetching primary.xml.gz...")
            packages = self._fetch_primary_xml(self.config.feed, primary_location)
            print(f"Found {len(packages)} packages in repository")

            # Step 4: Get existing packages from database
            existing_packages = self._get_existing_packages(session)
            print(f"Already have {len(existing_packages)} packages in pool")

            # Step 5: Download new packages
            packages_downloaded = 0
            packages_skipped = 0
            bytes_downloaded = 0

            for i, pkg_meta in enumerate(packages, 1):
                print(f"[{i}/{len(packages)}] Processing {pkg_meta.name}-{pkg_meta.version}-{pkg_meta.release}.{pkg_meta.arch}")

                # Check if package already exists by SHA256
                if pkg_meta.sha256 in existing_packages:
                    print(f"  → Already in pool (SHA256: {pkg_meta.sha256[:16]}...)")
                    packages_skipped += 1
                    continue

                # Download package
                pkg_url = urljoin(self.config.feed + "/", pkg_meta.location)
                print(f"  → Downloading from {pkg_url}")

                try:
                    downloaded_bytes = self._download_package(
                        pkg_url, pkg_meta, session, repository
                    )
                    packages_downloaded += 1
                    bytes_downloaded += downloaded_bytes
                    print(f"  → Downloaded {downloaded_bytes / 1024 / 1024:.2f} MB")
                except Exception as e:
                    print(f"  → ERROR: Failed to download: {e}")
                    # Continue with next package

            print(f"\nSync complete!")
            print(f"  Downloaded: {packages_downloaded}")
            print(f"  Skipped: {packages_skipped}")
            print(f"  Total size: {bytes_downloaded / 1024 / 1024:.2f} MB")

            return SyncResult(
                packages_downloaded=packages_downloaded,
                packages_skipped=packages_skipped,
                packages_total=len(packages),
                bytes_downloaded=bytes_downloaded,
                success=True,
            )

        except Exception as e:
            print(f"Sync failed: {e}")
            return SyncResult(
                packages_downloaded=0,
                packages_skipped=0,
                packages_total=0,
                bytes_downloaded=0,
                success=False,
                error_message=str(e),
            )

    def _fetch_repomd_xml(self, base_url: str) -> ET.Element:
        """Fetch and parse repomd.xml.

        Args:
            base_url: Base URL of repository

        Returns:
            XML root element

        Raises:
            requests.RequestException: On HTTP errors
            ET.ParseError: On XML parse errors
        """
        repomd_url = urljoin(base_url + "/", "repodata/repomd.xml")
        response = self.session.get(repomd_url, timeout=30)
        response.raise_for_status()
        return ET.fromstring(response.content)

    def _extract_primary_location(self, repomd_root: ET.Element) -> str:
        """Extract primary.xml.gz location from repomd.xml.

        Args:
            repomd_root: Parsed repomd.xml root element

        Returns:
            Relative path to primary.xml.gz

        Raises:
            ValueError: If primary location not found
        """
        # Handle XML namespaces
        ns = {"repo": "http://linux.duke.edu/metadata/repo"}

        # Find data element with type="primary"
        data_elem = repomd_root.find("repo:data[@type='primary']", ns)
        if data_elem is None:
            # Try without namespace
            data_elem = repomd_root.find("data[@type='primary']")
            if data_elem is None:
                raise ValueError("Primary metadata location not found in repomd.xml")

        location_elem = data_elem.find("repo:location", ns)
        if location_elem is None:
            location_elem = data_elem.find("location")
            if location_elem is None:
                raise ValueError("Primary location element not found")

        location = location_elem.get("href")
        if not location:
            raise ValueError("Primary location href attribute missing")

        return location

    def _fetch_primary_xml(
        self, base_url: str, primary_location: str
    ) -> List[PackageMetadata]:
        """Download and parse primary.xml.gz.

        Args:
            base_url: Base URL of repository
            primary_location: Relative path to primary.xml.gz

        Returns:
            List of package metadata

        Raises:
            requests.RequestException: On HTTP errors
        """
        primary_url = urljoin(base_url + "/", primary_location)
        response = self.session.get(primary_url, timeout=60)
        response.raise_for_status()

        # Decompress gzip
        xml_content = gzip.decompress(response.content)

        # Parse XML
        root = ET.fromstring(xml_content)

        # Extract package metadata
        return self._parse_primary_xml(root)

    def _parse_primary_xml(self, root: ET.Element) -> List[PackageMetadata]:
        """Parse primary.xml root element.

        Args:
            root: Parsed primary.xml root element

        Returns:
            List of package metadata
        """
        packages = []

        # Handle namespace
        ns = {"common": "http://linux.duke.edu/metadata/common"}

        # Find all package elements
        package_elems = root.findall("common:package", ns)
        if not package_elems:
            # Try without namespace
            package_elems = root.findall("package")

        for pkg_elem in package_elems:
            try:
                # Extract basic info
                name_elem = pkg_elem.find("common:name", ns) or pkg_elem.find("name")
                arch_elem = pkg_elem.find("common:arch", ns) or pkg_elem.find("arch")
                version_elem = pkg_elem.find("common:version", ns) or pkg_elem.find("version")
                checksum_elem = pkg_elem.find("common:checksum", ns) or pkg_elem.find("checksum")
                size_elem = pkg_elem.find("common:size", ns) or pkg_elem.find("size")
                location_elem = pkg_elem.find("common:location", ns) or pkg_elem.find("location")
                summary_elem = pkg_elem.find("common:summary", ns) or pkg_elem.find("summary")
                desc_elem = pkg_elem.find("common:description", ns) or pkg_elem.find("description")

                if not all([name_elem, arch_elem, version_elem, checksum_elem, location_elem]):
                    continue  # Skip incomplete packages

                pkg_meta = PackageMetadata(
                    name=name_elem.text,
                    version=version_elem.get("ver"),
                    release=version_elem.get("rel") or "",
                    epoch=version_elem.get("epoch"),
                    arch=arch_elem.text,
                    sha256=checksum_elem.text,
                    size_bytes=int(size_elem.get("package")) if size_elem is not None else 0,
                    location=location_elem.get("href"),
                    summary=summary_elem.text if summary_elem is not None else None,
                    description=desc_elem.text if desc_elem is not None else None,
                )
                packages.append(pkg_meta)

            except (AttributeError, ValueError) as e:
                # Skip packages with parsing errors
                print(f"Warning: Failed to parse package: {e}")
                continue

        return packages

    def _get_existing_packages(self, session: Session) -> Dict[str, Package]:
        """Get existing packages from database.

        Args:
            session: Database session

        Returns:
            Dict mapping SHA256 -> Package
        """
        packages = session.query(Package).all()
        return {pkg.sha256: pkg for pkg in packages}

    def _download_package(
        self,
        url: str,
        pkg_meta: PackageMetadata,
        session: Session,
        repository: Repository,
    ) -> int:
        """Download package and add to storage pool.

        Args:
            url: Package download URL
            pkg_meta: Package metadata
            session: Database session
            repository: Repository model instance

        Returns:
            Number of bytes downloaded

        Raises:
            requests.RequestException: On download errors
            ValueError: On checksum mismatch
        """
        # Download to temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".rpm") as tmp_file:
            tmp_path = Path(tmp_file.name)

            try:
                # Stream download
                response = self.session.get(url, stream=True, timeout=300)
                response.raise_for_status()

                # Download with progress
                bytes_downloaded = 0
                for chunk in response.iter_content(chunk_size=65536):
                    tmp_file.write(chunk)
                    bytes_downloaded += len(chunk)

                tmp_file.flush()

                # Extract filename from location
                filename = Path(pkg_meta.location).name

                # Add to storage pool (will verify SHA256)
                sha256, pool_path, size_bytes = self.storage.add_package(
                    tmp_path, filename, verify_checksum=True
                )

                # Verify SHA256 matches metadata
                if sha256 != pkg_meta.sha256:
                    raise ValueError(
                        f"SHA256 mismatch: expected {pkg_meta.sha256}, got {sha256}"
                    )

                # Add to database
                package = Package(
                    name=pkg_meta.name,
                    version=pkg_meta.version,
                    release=pkg_meta.release,
                    epoch=pkg_meta.epoch,
                    arch=pkg_meta.arch,
                    sha256=sha256,
                    size_bytes=size_bytes,
                    pool_path=pool_path,
                    package_type="rpm",
                    filename=filename,
                    summary=pkg_meta.summary,
                    description=pkg_meta.description,
                )
                session.add(package)
                session.commit()

                return bytes_downloaded

            finally:
                # Clean up temp file
                if tmp_path.exists():
                    tmp_path.unlink()
