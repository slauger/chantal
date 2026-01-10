"""
RPM repository sync plugin.

This module implements syncing RPM repositories from upstream sources.
"""

import gzip
import hashlib
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
from chantal.db.models import Package, Repository


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
