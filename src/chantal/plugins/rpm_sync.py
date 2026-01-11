"""
RPM repository sync plugin.

This module implements syncing RPM repositories from upstream sources.
"""

import configparser
import gzip
import hashlib
import lzma
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from packaging import version
from sqlalchemy.orm import Session

from chantal.core.config import (
    FilterConfig,
    GenericMetadataFilterConfig,
    ListFilterConfig,
    PatternFilterConfig,
    ProxyConfig,
    RepositoryConfig,
    RpmFilterConfig,
    SizeFilterConfig,
    TimeFilterConfig,
)
from chantal.core.storage import StorageManager
from chantal.db.models import ContentItem, Repository, RepositoryFile
from chantal.plugins.rpm.models import RpmMetadata


@dataclass
class PackageMetadata:
    """Package metadata from primary.xml."""

    # Basic package info
    name: str
    version: str
    release: str
    epoch: Optional[str]
    arch: str
    sha256: str
    size_bytes: int
    location: str  # Relative URL to package file

    # Optional metadata
    summary: Optional[str] = None
    description: Optional[str] = None

    # Extended metadata for filtering
    build_time: Optional[int] = None      # Unix timestamp (when built)
    file_time: Optional[int] = None       # Unix timestamp (file modification)
    group: Optional[str] = None           # RPM group (e.g., "Applications/Internet")
    license: Optional[str] = None         # License string
    vendor: Optional[str] = None          # Vendor/Packager
    sourcerpm: Optional[str] = None       # Source RPM filename (to identify .src.rpm)


@dataclass
class MetadataFileInfo:
    """Information about a metadata file from repomd.xml."""

    file_type: str  # e.g., "primary", "updateinfo", "filelists", "other", "comps", "modules"
    location: str  # Relative path (e.g., "repodata/abc123-updateinfo.xml.gz")
    checksum: str  # SHA256 checksum
    size: int  # File size in bytes
    open_checksum: Optional[str] = None  # Checksum of uncompressed file
    open_size: Optional[int] = None  # Size of uncompressed file


@dataclass
class SyncResult:
    """Result of a repository sync operation."""

    packages_downloaded: int
    packages_skipped: int  # Already in pool
    packages_total: int
    bytes_downloaded: int
    metadata_files_downloaded: int  # Number of metadata files downloaded
    success: bool
    error_message: Optional[str] = None


@dataclass
class PackageUpdate:
    """Information about an available package update."""

    name: str
    arch: str
    local_version: Optional[str]  # None if package is new
    local_release: Optional[str]
    remote_version: str
    remote_release: str
    remote_epoch: Optional[str]
    size_bytes: int
    sha256: str
    location: str

    @property
    def is_new(self) -> bool:
        """Check if this is a new package (not currently installed)."""
        return self.local_version is None

    @property
    def nvra(self) -> str:
        """Get name-version-release.arch string."""
        epoch_str = f"{self.remote_epoch}:" if self.remote_epoch else ""
        return f"{self.name}-{epoch_str}{self.remote_version}-{self.remote_release}.{self.arch}"


@dataclass
class CheckUpdatesResult:
    """Result of a check-updates operation."""

    updates_available: List[PackageUpdate]
    total_packages: int  # Total packages in upstream
    total_size_bytes: int  # Total size of updates
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
        ssl_config: Optional["SSLConfig"] = None,
    ):
        """Initialize RPM sync plugin.

        Args:
            storage: Storage manager instance
            config: Repository configuration
            proxy_config: Optional proxy configuration
            ssl_config: Optional SSL/TLS configuration
        """
        self.storage = storage
        self.config = config
        self.proxy_config = proxy_config
        self.ssl_config = ssl_config

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

        # Setup SSL/TLS verification
        if ssl_config:
            if not ssl_config.verify:
                # Disable SSL verification (not recommended)
                self.session.verify = False
            elif ssl_config.ca_cert:
                # Use inline CA certificate - write to temp file
                import tempfile
                ca_file = tempfile.NamedTemporaryFile(mode='w', suffix='.pem', delete=False)
                ca_file.write(ssl_config.ca_cert)
                ca_file.flush()
                ca_file.close()
                self.session.verify = ca_file.name
                self._temp_ca_file = ca_file.name  # Store for cleanup
            elif ssl_config.ca_bundle:
                # Use CA bundle file path
                self.session.verify = ssl_config.ca_bundle

            # Setup client certificate for mTLS if configured
            if ssl_config.client_cert:
                if ssl_config.client_key:
                    self.session.cert = (ssl_config.client_cert, ssl_config.client_key)
                else:
                    self.session.cert = ssl_config.client_cert

        # Setup repository authentication
        if config.auth:
            if config.auth.type == "client_cert":
                # Client certificate authentication (RHEL CDN)
                if config.auth.cert_file and config.auth.key_file:
                    # Specific cert/key files provided
                    self.session.cert = (config.auth.cert_file, config.auth.key_file)
                    print(f"Using client certificate authentication")
                elif config.auth.cert_dir:
                    # Find cert/key in directory (RHEL entitlement pattern)
                    cert_dir = Path(config.auth.cert_dir)
                    if cert_dir.exists():
                        # Find first .pem certificate (not -key.pem)
                        certs = [f for f in cert_dir.glob("*.pem") if not f.name.endswith("-key.pem")]
                        if certs:
                            cert_file = certs[0]
                            # Look for corresponding key file
                            key_file = cert_dir / cert_file.name.replace(".pem", "-key.pem")
                            if key_file.exists():
                                self.session.cert = (str(cert_file), str(key_file))
                                print(f"Using client certificate: {cert_file.name}")
                            else:
                                print(f"Warning: Key file not found for {cert_file.name}")

            elif config.auth.type == "basic":
                # HTTP Basic authentication
                if config.auth.username and config.auth.password:
                    self.session.auth = (config.auth.username, config.auth.password)
                    print(f"Using HTTP Basic authentication (user: {config.auth.username})")

            elif config.auth.type == "bearer":
                # Bearer token authentication
                if config.auth.token:
                    self.session.headers.update({
                        "Authorization": f"Bearer {config.auth.token}"
                    })
                    print(f"Using Bearer token authentication")

            elif config.auth.type == "custom":
                # Custom HTTP headers
                if config.auth.headers:
                    self.session.headers.update(config.auth.headers)
                    print(f"Using custom headers: {list(config.auth.headers.keys())}")

            # SSL/TLS verification settings
            if not config.auth.verify_ssl:
                self.session.verify = False
                print("Warning: SSL certificate verification disabled")
            elif config.auth.ca_bundle:
                self.session.verify = config.auth.ca_bundle
                print(f"Using custom CA bundle: {config.auth.ca_bundle}")

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

            # Step 4: Apply filters if configured
            if self.config.filters:
                original_count = len(packages)
                packages = self._apply_filters(packages, self.config.filters)
                filtered_out = original_count - len(packages)
                if filtered_out > 0:
                    print(f"Filtered out {filtered_out} packages, {len(packages)} remaining")

            # Step 5: Get existing packages from database
            existing_packages = self._get_existing_packages(session)
            print(f"Already have {len(existing_packages)} packages in pool")

            # Step 6: Download new packages
            packages_downloaded = 0
            packages_skipped = 0
            bytes_downloaded = 0

            for i, pkg_meta in enumerate(packages, 1):
                print(f"[{i}/{len(packages)}] Processing {pkg_meta.name}-{pkg_meta.version}-{pkg_meta.release}.{pkg_meta.arch}")

                # Check if package already exists by SHA256
                if pkg_meta.sha256 in existing_packages:
                    print(f"  → Already in pool (SHA256: {pkg_meta.sha256[:16]}...)")
                    packages_skipped += 1

                    # Link existing package to this repository if not already linked
                    existing_pkg = existing_packages[pkg_meta.sha256]
                    if repository not in existing_pkg.repositories:
                        existing_pkg.repositories.append(repository)
                        session.commit()
                        print(f"  → Linked to repository")

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

            # Step 7: Download metadata files
            print(f"\nDownloading metadata files...")
            metadata_files = self._extract_all_metadata(repomd_root)
            metadata_downloaded = 0

            for metadata_info in metadata_files:
                # Skip primary (already used for package sync)
                if metadata_info.file_type == "primary":
                    continue

                try:
                    self._download_metadata_file(
                        metadata_info, session, repository, self.config.feed
                    )
                    metadata_downloaded += 1
                    print(f"  → Downloaded {metadata_info.file_type}.xml.gz")
                except Exception as e:
                    print(f"  → Warning: Failed to download {metadata_info.file_type}: {e}")
                    # Continue with next metadata file

            # Step 8: Check for .treeinfo and download installer files
            print(f"\nChecking for installer files (.treeinfo)...")
            treeinfo_url = urljoin(self.config.feed, ".treeinfo")
            try:
                response = self.session.get(treeinfo_url, timeout=30)
                response.raise_for_status()

                treeinfo_content = response.text
                installer_files = self._parse_treeinfo(treeinfo_content)

                if installer_files:
                    print(f"Found {len(installer_files)} installer files")
                    installer_downloaded = 0

                    for file_info in installer_files:
                        try:
                            self._download_installer_file(
                                session=session,
                                repository=repository,
                                base_url=self.config.feed,
                                file_info=file_info
                            )
                            installer_downloaded += 1
                        except Exception as e:
                            print(f"  → Warning: Failed to download {file_info['file_type']}: {e}")
                            # Continue with next installer file

                    # Store .treeinfo itself
                    self._store_treeinfo(session, repository, treeinfo_content)

                    print(f"Installer files downloaded: {installer_downloaded}/{len(installer_files)}")

            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    print("  No .treeinfo found (not an installer repository)")
                else:
                    print(f"  → Warning: Failed to fetch .treeinfo: {e}")
            except Exception as e:
                print(f"  → Warning: Failed to process .treeinfo: {e}")

            print(f"\nSync complete!")
            print(f"  Packages downloaded: {packages_downloaded}")
            print(f"  Packages skipped: {packages_skipped}")
            print(f"  Metadata files downloaded: {metadata_downloaded}")
            print(f"  Total size: {bytes_downloaded / 1024 / 1024:.2f} MB")

            return SyncResult(
                packages_downloaded=packages_downloaded,
                packages_skipped=packages_skipped,
                packages_total=len(packages),
                bytes_downloaded=bytes_downloaded,
                metadata_files_downloaded=metadata_downloaded,
                success=True,
            )

        except Exception as e:
            print(f"Sync failed: {e}")
            return SyncResult(
                packages_downloaded=0,
                packages_skipped=0,
                packages_total=0,
                bytes_downloaded=0,
                metadata_files_downloaded=0,
                success=False,
                error_message=str(e),
            )

    def check_updates(
        self, session: Session, repository: Repository
    ) -> CheckUpdatesResult:
        """Check for available package updates without downloading.

        Args:
            session: Database session
            repository: Repository model instance

        Returns:
            CheckUpdatesResult with list of available updates
        """
        try:
            print(f"Checking for updates: {repository.repo_id}")
            print(f"Feed URL: {self.config.feed}")

            # Step 1: Fetch repomd.xml
            print("Fetching repomd.xml...")
            repomd_root = self._fetch_repomd_xml(self.config.feed)

            # Step 2: Extract primary.xml location
            primary_location = self._extract_primary_location(repomd_root)

            # Step 3: Download and parse primary.xml
            print("Fetching primary.xml...")
            packages = self._fetch_primary_xml(self.config.feed, primary_location)
            print(f"Found {len(packages)} packages in upstream repository")

            # Step 4: Apply filters if configured
            if self.config.filters:
                original_count = len(packages)
                packages = self._apply_filters(packages, self.config.filters)
                filtered_out = original_count - len(packages)
                if filtered_out > 0:
                    print(f"Filtered out {filtered_out} packages, {len(packages)} remaining")

            # Step 5: Get existing packages from database for this repository
            existing_packages = {}
            for pkg in repository.content_items:
                # Build a key based on name and arch
                key = f"{pkg.name}#{pkg.arch}"
                existing_packages[key] = pkg

            print(f"Currently have {len(existing_packages)} unique packages (by name-arch)")

            # Step 6: Compare and find updates/new packages
            updates = []
            total_update_size = 0

            for pkg_meta in packages:
                key = f"{pkg_meta.name}#{pkg_meta.arch}"
                existing_pkg = existing_packages.get(key)

                if existing_pkg is None:
                    # New package not in our repository
                    update = PackageUpdate(
                        name=pkg_meta.name,
                        arch=pkg_meta.arch,
                        local_version=None,
                        local_release=None,
                        remote_version=pkg_meta.version,
                        remote_release=pkg_meta.release,
                        remote_epoch=pkg_meta.epoch,
                        size_bytes=pkg_meta.size_bytes,
                        sha256=pkg_meta.sha256,
                        location=pkg_meta.location,
                    )
                    updates.append(update)
                    total_update_size += pkg_meta.size_bytes
                else:
                    # Package exists - check if remote version is newer
                    remote_epoch = int(pkg_meta.epoch or "0")
                    local_epoch = int(existing_pkg.content_metadata.get("epoch") or "0")

                    # EPO CH-style version comparison: compare epoch, then version, then release
                    is_newer = False

                    if remote_epoch > local_epoch:
                        is_newer = True
                    elif remote_epoch == local_epoch:
                        # Compare version (use packaging library for proper version comparison)
                        try:
                            remote_ver = version.parse(pkg_meta.version)
                            local_ver = version.parse(existing_pkg.version)

                            if remote_ver > local_ver:
                                is_newer = True
                            elif remote_ver == local_ver:
                                # Compare release
                                remote_rel = version.parse(pkg_meta.release)
                                local_rel = version.parse(existing_pkg.content_metadata.get("release", ""))

                                if remote_rel > local_rel:
                                    is_newer = True
                        except Exception:
                            # Fallback to string comparison if packaging fails
                            if pkg_meta.version > existing_pkg.version:
                                is_newer = True
                            elif pkg_meta.version == existing_pkg.version:
                                if pkg_meta.release > existing_pkg.content_metadata.get("release", ""):
                                    is_newer = True

                    if is_newer:
                        # Update available
                        update = PackageUpdate(
                            name=pkg_meta.name,
                            arch=pkg_meta.arch,
                            local_version=existing_pkg.version,
                            local_release=existing_pkg.release,
                            remote_version=pkg_meta.version,
                            remote_release=pkg_meta.release,
                            remote_epoch=pkg_meta.epoch,
                            size_bytes=pkg_meta.size_bytes,
                            sha256=pkg_meta.sha256,
                            location=pkg_meta.location,
                        )
                        updates.append(update)
                        total_update_size += pkg_meta.size_bytes

            print(f"\nCheck complete!")
            print(f"  Updates available: {len(updates)}")
            print(f"  Total size: {total_update_size / 1024 / 1024:.2f} MB")

            return CheckUpdatesResult(
                updates_available=updates,
                total_packages=len(packages),
                total_size_bytes=total_update_size,
                success=True,
            )

        except Exception as e:
            print(f"Check failed: {e}")
            return CheckUpdatesResult(
                updates_available=[],
                total_packages=0,
                total_size_bytes=0,
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

    def _extract_all_metadata(self, repomd_root: ET.Element) -> List[MetadataFileInfo]:
        """Extract all metadata file information from repomd.xml.

        Args:
            repomd_root: Parsed repomd.xml root element

        Returns:
            List of metadata file information

        Raises:
            ValueError: If metadata parsing fails
        """
        # Handle XML namespaces
        ns = {"repo": "http://linux.duke.edu/metadata/repo"}

        metadata_files = []

        # Find all data elements
        data_elems = repomd_root.findall("repo:data", ns)
        if not data_elems:
            # Try without namespace
            data_elems = repomd_root.findall("data")

        for data_elem in data_elems:
            try:
                # Get type attribute
                file_type = data_elem.get("type")
                if not file_type:
                    continue

                # Find location element
                location_elem = data_elem.find("repo:location", ns)
                if location_elem is None:
                    location_elem = data_elem.find("location")
                if location_elem is None:
                    continue

                location = location_elem.get("href")
                if not location:
                    continue

                # Find checksum element
                checksum_elem = data_elem.find("repo:checksum", ns)
                if checksum_elem is None:
                    checksum_elem = data_elem.find("checksum")
                if checksum_elem is None or not checksum_elem.text:
                    continue

                # Find size element
                size_elem = data_elem.find("repo:size", ns)
                if size_elem is None:
                    size_elem = data_elem.find("size")
                size = int(size_elem.text) if size_elem is not None and size_elem.text else 0

                # Optional: open-checksum and open-size
                open_checksum_elem = data_elem.find("repo:open-checksum", ns)
                if open_checksum_elem is None:
                    open_checksum_elem = data_elem.find("open-checksum")
                open_checksum = open_checksum_elem.text if open_checksum_elem is not None else None

                open_size_elem = data_elem.find("repo:open-size", ns)
                if open_size_elem is None:
                    open_size_elem = data_elem.find("open-size")
                open_size = int(open_size_elem.text) if open_size_elem is not None and open_size_elem.text else None

                # Create metadata file info
                metadata_info = MetadataFileInfo(
                    file_type=file_type,
                    location=location,
                    checksum=checksum_elem.text,
                    size=size,
                    open_checksum=open_checksum,
                    open_size=open_size,
                )
                metadata_files.append(metadata_info)

            except Exception as e:
                # Skip malformed entries
                print(f"Warning: Failed to parse metadata entry: {e}")
                continue

        return metadata_files

    def _download_metadata_file(
        self,
        metadata_info: MetadataFileInfo,
        session: Session,
        repository: Repository,
        base_url: str,
    ) -> None:
        """Download metadata file and store as RepositoryFile.

        Args:
            metadata_info: Metadata file information
            session: Database session
            repository: Repository model instance
            base_url: Base URL of repository

        Raises:
            requests.RequestException: On HTTP errors
            ValueError: On checksum mismatch
        """
        # Download metadata file to temporary location
        metadata_url = urljoin(base_url + "/", metadata_info.location)

        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{metadata_info.file_type}") as tmp_file:
            tmp_path = Path(tmp_file.name)

            try:
                # Download file
                response = self.session.get(metadata_url, timeout=60)
                response.raise_for_status()

                # Write to temp file
                tmp_file.write(response.content)
                tmp_file.flush()

                # Extract filename from location
                filename = Path(metadata_info.location).name

                # Add to storage pool using add_repository_file
                sha256, pool_path, size_bytes = self.storage.add_repository_file(
                    tmp_path, filename, verify_checksum=True
                )

                # Verify SHA256 matches metadata (if provided)
                if metadata_info.checksum and sha256 != metadata_info.checksum:
                    raise ValueError(
                        f"SHA256 mismatch for {metadata_info.file_type}: "
                        f"expected {metadata_info.checksum}, got {sha256}"
                    )

                # Check if this RepositoryFile already exists
                existing_file = session.query(RepositoryFile).filter_by(sha256=sha256).first()

                if existing_file:
                    # File already exists - just link to repository if not already linked
                    if repository not in existing_file.repositories:
                        existing_file.repositories.append(repository)
                        session.commit()
                else:
                    # Create new RepositoryFile record
                    repo_file = RepositoryFile(
                        file_category="metadata",
                        file_type=metadata_info.file_type,
                        sha256=sha256,
                        pool_path=pool_path,
                        size_bytes=size_bytes,
                        original_path=metadata_info.location,
                        file_metadata={
                            "checksum_type": "sha256",
                            "open_checksum": metadata_info.open_checksum,
                            "open_size": metadata_info.open_size,
                        },
                    )
                    session.add(repo_file)
                    session.commit()

                    # Link to repository
                    repo_file.repositories.append(repository)
                    session.commit()

            finally:
                # Clean up temp file
                if tmp_path.exists():
                    tmp_path.unlink()

    def _fetch_primary_xml(
        self, base_url: str, primary_location: str
    ) -> List[PackageMetadata]:
        """Download and parse primary.xml.gz or primary.xml.xz.

        Args:
            base_url: Base URL of repository
            primary_location: Relative path to primary.xml.gz or primary.xml.xz

        Returns:
            List of package metadata

        Raises:
            requests.RequestException: On HTTP errors
        """
        primary_url = urljoin(base_url + "/", primary_location)
        response = self.session.get(primary_url, timeout=60)
        response.raise_for_status()

        # Decompress based on file extension
        if primary_location.endswith('.xz'):
            xml_content = lzma.decompress(response.content)
        elif primary_location.endswith('.gz'):
            xml_content = gzip.decompress(response.content)
        else:
            # Try to auto-detect based on magic bytes
            if response.content[:2] == b'\x1f\x8b':  # gzip magic
                xml_content = gzip.decompress(response.content)
            elif response.content[:6] == b'\xfd7zXZ\x00':  # xz magic
                xml_content = lzma.decompress(response.content)
            else:
                raise ValueError(f"Unknown compression format for {primary_location}")

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
                # Namespace URI for common elements
                ns_uri = "{http://linux.duke.edu/metadata/common}"
                rpm_ns = "{http://linux.duke.edu/metadata/rpm}"

                # Extract basic info
                name_elem = pkg_elem.find(f"{ns_uri}name")
                arch_elem = pkg_elem.find(f"{ns_uri}arch")
                version_elem = pkg_elem.find(f"{ns_uri}version")
                checksum_elem = pkg_elem.find(f"{ns_uri}checksum")
                size_elem = pkg_elem.find(f"{ns_uri}size")
                location_elem = pkg_elem.find(f"{ns_uri}location")
                summary_elem = pkg_elem.find(f"{ns_uri}summary")
                desc_elem = pkg_elem.find(f"{ns_uri}description")

                # Extract extended metadata
                time_elem = pkg_elem.find(f"{ns_uri}time")
                format_elem = pkg_elem.find(f"{ns_uri}format")

                # Extract RPM-specific metadata from <format> element
                group = None
                license_str = None
                vendor = None
                sourcerpm = None
                if format_elem is not None:
                    group_elem = format_elem.find(f"{rpm_ns}group")
                    license_elem = format_elem.find(f"{rpm_ns}license")
                    vendor_elem = format_elem.find(f"{rpm_ns}vendor")
                    sourcerpm_elem = format_elem.find(f"{rpm_ns}sourcerpm")

                    group = group_elem.text if group_elem is not None else None
                    license_str = license_elem.text if license_elem is not None else None
                    vendor = vendor_elem.text if vendor_elem is not None else None
                    sourcerpm = sourcerpm_elem.text if sourcerpm_elem is not None else None

                # Extract time metadata
                build_time = None
                file_time = None
                if time_elem is not None:
                    build_time_str = time_elem.get("build")
                    file_time_str = time_elem.get("file")
                    build_time = int(build_time_str) if build_time_str else None
                    file_time = int(file_time_str) if file_time_str else None

                # ElementTree elements can be falsy even if not None, so check explicitly
                if name_elem is None or arch_elem is None or version_elem is None or checksum_elem is None or location_elem is None:
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
                    build_time=build_time,
                    file_time=file_time,
                    group=group,
                    license=license_str,
                    vendor=vendor,
                    sourcerpm=sourcerpm,
                )
                packages.append(pkg_meta)

            except Exception as e:
                # Skip packages with parsing errors
                print(f"Warning: Failed to parse package: {e}")
                continue

        return packages

    def _apply_filters(
        self, packages: List[PackageMetadata], filters: FilterConfig
    ) -> List[PackageMetadata]:
        """Apply package filters using generic filter engine.

        Args:
            packages: List of package metadata
            filters: Filter configuration

        Returns:
            Filtered list of packages
        """
        # Normalize legacy config to new structure
        filters = filters.normalize()

        # Validate filter config for RPM repository
        filters.validate_for_repo_type("rpm")

        filtered_packages = []

        for pkg in packages:
            # Apply generic metadata filters
            if filters.metadata:
                if not self._check_generic_metadata_filters(pkg, filters.metadata):
                    continue

            # Apply RPM-specific filters
            if filters.rpm:
                if not self._check_rpm_filters(pkg, filters.rpm):
                    continue

            # Apply pattern filters
            if filters.patterns:
                if not self._check_pattern_filters(pkg, filters.patterns):
                    continue

            # Package passed all filters
            filtered_packages.append(pkg)

        # Apply post-processing (after all filters)
        if filters.post_processing:
            filtered_packages = self._apply_post_processing(
                filtered_packages, filters.post_processing
            )

        return filtered_packages

    def _check_generic_metadata_filters(
        self, pkg: PackageMetadata, metadata: GenericMetadataFilterConfig
    ) -> bool:
        """Check if package passes generic metadata filters.

        Args:
            pkg: Package metadata
            metadata: Generic metadata filter config

        Returns:
            True if package passes all generic metadata filters
        """
        # Size filter
        if metadata.size_bytes:
            if metadata.size_bytes.min and pkg.size_bytes < metadata.size_bytes.min:
                return False
            if metadata.size_bytes.max and pkg.size_bytes > metadata.size_bytes.max:
                return False

        # Build time filter
        if metadata.build_time and pkg.build_time:
            from datetime import datetime, timedelta

            # Convert package build_time (Unix timestamp) to datetime
            pkg_build_dt = datetime.fromtimestamp(pkg.build_time)

            if metadata.build_time.newer_than:
                newer_than_dt = datetime.fromisoformat(metadata.build_time.newer_than)
                if pkg_build_dt < newer_than_dt:
                    return False

            if metadata.build_time.older_than:
                older_than_dt = datetime.fromisoformat(metadata.build_time.older_than)
                if pkg_build_dt > older_than_dt:
                    return False

            if metadata.build_time.last_n_days:
                cutoff_dt = datetime.now() - timedelta(days=metadata.build_time.last_n_days)
                if pkg_build_dt < cutoff_dt:
                    return False

        # Architecture filter
        if metadata.architectures:
            if not self._check_list_filter(pkg.arch, metadata.architectures):
                return False

        return True

    def _check_rpm_filters(
        self, pkg: PackageMetadata, rpm_filters: RpmFilterConfig
    ) -> bool:
        """Check if package passes RPM-specific filters.

        Args:
            pkg: Package metadata
            rpm_filters: RPM filter config

        Returns:
            True if package passes all RPM filters
        """
        # Source RPM filter
        if rpm_filters.exclude_source_rpms:
            if pkg.arch == "src":
                return False
            # Also check if this is a source RPM by looking at sourcerpm field
            # (Note: binary RPMs have sourcerpm pointing to the .src.rpm they were built from)
            # We only want to exclude actual source RPMs (arch == "src")

        # Group filter
        if rpm_filters.groups and pkg.group:
            if not self._check_list_filter(pkg.group, rpm_filters.groups):
                return False

        # License filter
        if rpm_filters.licenses and pkg.license:
            if not self._check_list_filter(pkg.license, rpm_filters.licenses):
                return False

        # Vendor filter
        if rpm_filters.vendors and pkg.vendor:
            if not self._check_list_filter(pkg.vendor, rpm_filters.vendors):
                return False

        # Epoch filter
        if rpm_filters.epochs and pkg.epoch:
            if not self._check_list_filter(pkg.epoch, rpm_filters.epochs):
                return False

        return True

    def _check_list_filter(self, value: str, list_filter: ListFilterConfig) -> bool:
        """Check if value passes list filter (include/exclude).

        Args:
            value: Value to check
            list_filter: List filter config

        Returns:
            True if value passes filter
        """
        # Check include list
        if list_filter.include:
            if value not in list_filter.include:
                return False

        # Check exclude list
        if list_filter.exclude:
            if value in list_filter.exclude:
                return False

        return True

    def _check_pattern_filters(
        self, pkg: PackageMetadata, patterns: PatternFilterConfig
    ) -> bool:
        """Check if package passes pattern filters.

        Args:
            pkg: Package metadata
            patterns: Pattern filter config

        Returns:
            True if package passes all pattern filters
        """
        pkg_name_full = f"{pkg.name}-{pkg.version}-{pkg.release}.{pkg.arch}"

        # Include patterns - at least one must match
        if patterns.include:
            matched = False
            for pattern in patterns.include:
                if re.search(pattern, pkg.name) or re.search(pattern, pkg_name_full):
                    matched = True
                    break
            if not matched:
                return False

        # Exclude patterns - none must match
        if patterns.exclude:
            for pattern in patterns.exclude:
                if re.search(pattern, pkg.name) or re.search(pattern, pkg_name_full):
                    return False

        return True

    def _apply_post_processing(
        self, packages: List[PackageMetadata], post_proc: "PostProcessingConfig"
    ) -> List[PackageMetadata]:
        """Apply post-processing to filtered packages.

        Args:
            packages: Filtered packages
            post_proc: Post-processing config

        Returns:
            Post-processed packages
        """
        from chantal.core.config import PostProcessingConfig

        if post_proc.only_latest_version:
            return self._keep_only_latest_versions(packages, n=1)
        elif post_proc.only_latest_n_versions:
            return self._keep_only_latest_versions(packages, n=post_proc.only_latest_n_versions)

        return packages

    def _keep_only_latest_versions(
        self, packages: List[PackageMetadata], n: int = 1
    ) -> List[PackageMetadata]:
        """Keep only the latest N versions of each package (by name and arch).

        Args:
            packages: List of packages
            n: Number of versions to keep (default: 1)

        Returns:
            Filtered list with only latest N versions per (name, arch)
        """
        # Group packages by (name, arch)
        grouped: Dict[Tuple[str, str], List[PackageMetadata]] = defaultdict(list)
        for pkg in packages:
            key = (pkg.name, pkg.arch)
            grouped[key].append(pkg)

        # For each group, keep only latest N versions
        result = []
        for (name, arch), pkg_list in grouped.items():
            # Sort by version (newest first)
            # Use tuple comparison: (epoch, version, release) for RPM version semantics
            try:
                sorted_pkgs = sorted(
                    pkg_list,
                    key=lambda p: (
                        int(p.epoch) if p.epoch else 0,  # Epoch as int
                        version.parse(p.version),  # Parse version (without epoch/release)
                        p.release,  # Release as string
                    ),
                    reverse=True,
                )
            except Exception as e:
                # If version parsing fails, fall back to simple tuple comparison
                print(f"Warning: Version parsing failed for {name}.{arch}: {e}")
                sorted_pkgs = sorted(
                    pkg_list,
                    key=lambda p: (
                        int(p.epoch) if p.epoch else 0,
                        p.version,
                        p.release,
                    ),
                    reverse=True,
                )

            # Keep only latest N versions
            result.extend(sorted_pkgs[:n])

        return result

    def _get_existing_packages(self, session: Session) -> Dict[str, ContentItem]:
        """Get existing content items from database.

        Args:
            session: Database session

        Returns:
            Dict mapping SHA256 -> ContentItem
        """
        content_items = session.query(ContentItem).filter(ContentItem.content_type == "rpm").all()
        return {item.sha256: item for item in content_items}

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

                # Build RPM metadata
                rpm_metadata = RpmMetadata(
                    epoch=pkg_meta.epoch,
                    release=pkg_meta.release,
                    arch=pkg_meta.arch,
                    summary=pkg_meta.summary,
                    description=pkg_meta.description,
                )

                # Add to database as ContentItem
                content_item = ContentItem(
                    content_type="rpm",
                    name=pkg_meta.name,
                    version=pkg_meta.version,
                    sha256=sha256,
                    size_bytes=size_bytes,
                    pool_path=pool_path,
                    filename=filename,
                    content_metadata=rpm_metadata.model_dump(exclude_none=False),
                )
                session.add(content_item)
                session.commit()

                # Link content item to repository
                content_item.repositories.append(repository)
                session.commit()

                return bytes_downloaded

            finally:
                # Clean up temp file
                if tmp_path.exists():
                    tmp_path.unlink()

    def _parse_treeinfo(self, content: str) -> List[Dict[str, str]]:
        """Parse .treeinfo and extract installer file metadata.

        Args:
            content: .treeinfo file content (INI format)

        Returns:
            List of dicts with keys: path, file_type, sha256
        """
        parser = configparser.ConfigParser()
        parser.read_string(content)

        installer_files = []

        # Parse checksums section
        checksums = {}
        if parser.has_section('checksums'):
            for key, value in parser.items('checksums'):
                # Format: "images/boot.iso = sha256:abc123..."
                if 'sha256:' in value:
                    checksum = value.split('sha256:')[1].strip()
                    checksums[key] = checksum

        # Parse images section for current arch
        arch = parser.get('general', 'arch', fallback='x86_64')
        images_section = f'images-{arch}'

        if parser.has_section(images_section):
            for file_type, file_path in parser.items(images_section):
                # file_type: boot.iso, kernel, initrd, etc.
                # file_path: images/boot.iso, images/pxeboot/vmlinuz

                sha256 = checksums.get(file_path)

                installer_files.append({
                    'path': file_path,
                    'file_type': file_type,
                    'sha256': sha256
                })

        return installer_files

    def _download_installer_file(
        self,
        session: Session,
        repository: Repository,
        base_url: str,
        file_info: Dict[str, str]
    ) -> None:
        """Download and store installer file.

        Args:
            session: Database session
            repository: Repository instance
            base_url: Repository base URL
            file_info: Dict with path, file_type, sha256
        """
        file_path = file_info['path']
        file_type = file_info['file_type']
        expected_sha256 = file_info.get('sha256')

        file_url = urljoin(base_url, file_path)

        print(f"  → Downloading {file_type}: {file_path}")

        # Download to temp file
        tmp_file = tempfile.NamedTemporaryFile(delete=False)
        try:
            response = self.session.get(file_url, stream=True, timeout=300)
            response.raise_for_status()

            # Download with progress for large files
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0

            for chunk in response.iter_content(chunk_size=8192):
                tmp_file.write(chunk)
                downloaded += len(chunk)

                # Show progress for large files (> 10MB)
                if total_size > 10 * 1024 * 1024:
                    mb_downloaded = downloaded / 1024 / 1024
                    mb_total = total_size / 1024 / 1024
                    print(f"\r    {mb_downloaded:.1f} MB / {mb_total:.1f} MB ({mb_downloaded/mb_total*100:.0f}%)", end='', flush=True)

            if total_size > 10 * 1024 * 1024:
                print()  # Newline after progress

            tmp_file.close()
            tmp_file_path = tmp_file.name

            # Calculate SHA256
            sha256_hash = hashlib.sha256()
            with open(tmp_file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    sha256_hash.update(chunk)

            actual_sha256 = sha256_hash.hexdigest()

            # Verify checksum if provided
            if expected_sha256 and actual_sha256 != expected_sha256:
                os.unlink(tmp_file_path)
                raise ValueError(
                    f"Checksum mismatch for {file_path}: "
                    f"expected {expected_sha256}, got {actual_sha256}"
                )

            # Store in pool via StorageManager
            pool_path = self.storage.add_repository_file(
                Path(tmp_file_path),
                filename=Path(file_path).name,
                sha256=actual_sha256
            )

            # Create RepositoryFile record
            repo_file = RepositoryFile(
                file_category="kickstart",
                file_type=file_type,
                original_path=file_path,
                pool_path=pool_path,
                sha256=actual_sha256,
                size_bytes=os.path.getsize(tmp_file_path)
            )

            session.add(repo_file)
            repository.repository_files.append(repo_file)
            session.commit()

            # Clean up temp file
            os.unlink(tmp_file_path)

            print(f"    ✓ Stored {file_type} ({actual_sha256[:8]}...)")

        except Exception as e:
            # Clean up on error
            if os.path.exists(tmp_file.name):
                os.unlink(tmp_file.name)
            raise

    def _store_treeinfo(
        self,
        session: Session,
        repository: Repository,
        treeinfo_content: str
    ) -> None:
        """Store .treeinfo file itself as RepositoryFile.

        Args:
            session: Database session
            repository: Repository instance
            treeinfo_content: .treeinfo file content
        """
        # Write to temp file
        tmp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.treeinfo')
        tmp_file.write(treeinfo_content)
        tmp_file.close()
        tmp_path = tmp_file.name

        try:
            # Calculate SHA256
            sha256_hash = hashlib.sha256(treeinfo_content.encode()).hexdigest()

            # Store in pool
            pool_path = self.storage.add_repository_file(
                Path(tmp_path),
                filename=".treeinfo",
                sha256=sha256_hash
            )

            # Create RepositoryFile record
            repo_file = RepositoryFile(
                file_category="kickstart",
                file_type="treeinfo",
                original_path=".treeinfo",
                pool_path=pool_path,
                sha256=sha256_hash,
                size_bytes=len(treeinfo_content)
            )

            session.add(repo_file)
            repository.repository_files.append(repo_file)
            session.commit()

            print("  ✓ Stored .treeinfo")

        finally:
            # Clean up temp file
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
