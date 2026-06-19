from __future__ import annotations

"""
RPM repository sync plugin.

This module implements syncing RPM repositories from upstream sources.
"""

import hashlib
import os
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import requests
from packaging import version
from sqlalchemy.orm import Session

from chantal.core.cache import MetadataCache
from chantal.core.config import ProxyConfig, RepositoryConfig, SSLConfig
from chantal.core.downloader import DownloadManager
from chantal.core.gpg_verify import SignatureVerificationError
from chantal.core.output import OutputLevel, SyncOutputter
from chantal.core.storage import StorageManager
from chantal.db.models import ContentItem, Repository, RepositoryFile
from chantal.plugins.rpm import filters, parsers
from chantal.plugins.rpm.models import RpmMetadata


@dataclass
class PackageMetadata:
    """Package metadata from primary.xml."""

    # Basic package info
    name: str
    version: str
    release: str
    epoch: str | None
    arch: str
    sha256: str
    size_bytes: int
    location: str  # Relative URL to package file

    # Optional metadata
    summary: str | None = None
    description: str | None = None

    # Extended metadata for filtering
    build_time: int | None = None  # Unix timestamp (when built)
    file_time: int | None = None  # Unix timestamp (file modification)
    group: str | None = None  # RPM group (e.g., "Applications/Internet")
    license: str | None = None  # License string
    vendor: str | None = None  # Vendor/Packager
    sourcerpm: str | None = None  # Source RPM filename (to identify .src.rpm)


@dataclass
class MetadataFileInfo:
    """Information about a metadata file from repomd.xml."""

    file_type: str  # e.g., "primary", "updateinfo", "filelists", "other", "comps", "modules"
    location: str  # Relative path (e.g., "repodata/abc123-updateinfo.xml.gz")
    checksum: str  # Checksum value from repomd.xml
    size: int  # File size in bytes
    open_checksum: str | None = None  # Checksum of uncompressed file
    open_size: int | None = None  # Size of uncompressed file
    checksum_type: str | None = None  # Checksum algorithm (sha256/sha512/sha1)


@dataclass
class SyncResult:
    """Result of a repository sync operation."""

    packages_downloaded: int
    packages_skipped: int  # Already in pool
    packages_total: int
    bytes_downloaded: int
    metadata_files_downloaded: int  # Number of metadata files downloaded
    success: bool
    error_message: str | None = None


@dataclass
class PackageUpdate:
    """Information about an available package update."""

    name: str
    arch: str
    local_version: str | None  # None if package is new
    local_release: str | None
    remote_version: str
    remote_release: str
    remote_epoch: str | None
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

    updates_available: list[PackageUpdate]
    total_packages: int  # Total packages in upstream
    total_size_bytes: int  # Total size of updates
    success: bool
    error_message: str | None = None


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
        proxy_config: ProxyConfig | None = None,
        ssl_config: SSLConfig | None = None,
        cache: MetadataCache | None = None,
        output_level: OutputLevel = OutputLevel.NORMAL,
    ):
        """Initialize RPM sync plugin.

        Args:
            storage: Storage manager instance
            config: Repository configuration
            proxy_config: Optional proxy configuration
            ssl_config: Optional SSL/TLS configuration
            cache: Optional metadata cache instance
            output_level: Output verbosity level
        """
        self.storage = storage
        self.config = config
        self.proxy_config = proxy_config
        self.ssl_config = ssl_config
        self.cache = cache
        self.output = SyncOutputter(output_level)

        # Setup download manager with all authentication and SSL/TLS configuration
        self.downloader = DownloadManager(
            config=config, proxy_config=proxy_config, ssl_config=ssl_config
        )

        # Backward compatibility for parsers module
        self.session = self.downloader.session

        # Lazily created during sync when package signature verification is on.
        self._package_verifier: object | None = None

    def sync_repository(self, session: Session, repository: Repository) -> SyncResult:
        """Sync repository from upstream.

        Args:
            session: Database session
            repository: Repository model instance

        Returns:
            SyncResult with sync statistics
        """
        try:
            self.output.header(repository.repo_id, "rpm", self.config.feed)

            # Step 1: Fetch repomd.xml ONCE (raw bytes), verify the signature on
            # exactly those bytes, then parse the same bytes. repomd.xml carries
            # the checksums of all other metadata, so a valid signature here
            # transitively authenticates the whole repository - but only if the
            # verified bytes are the bytes we actually parse (no re-fetch).
            self.output.phase("Fetching package list", number=1)
            self.output.info("Fetching repomd.xml...")
            repomd_content = parsers.fetch_repomd_content(self.session, self.config.feed)
            self._verify_repomd_signature(repomd_content)
            repomd_root = ET.fromstring(repomd_content)

            # Set up the reusable package-signature verifier (gpgcheck).
            self._setup_package_verifier()

            # Step 2: Extract ALL metadata info (including primary.xml.gz)
            metadata_files = parsers.extract_all_metadata(repomd_root)

            # Find primary.xml metadata
            primary_metadata = next(
                (m for m in metadata_files if m["file_type"] == "primary"), None
            )
            if not primary_metadata:
                raise ValueError("Primary metadata not found in repomd.xml")

            primary_location = primary_metadata["location"]
            primary_checksum = primary_metadata["checksum"]
            self.output.verbose(
                f"Primary metadata: {primary_location} (SHA256: {primary_checksum[:16]}...)"
            )

            # Step 3: Download and parse primary.xml.gz (with parsed data cache support)
            # Try parsed cache first (fastest - avoids XML parsing)
            packages = self.cache.get_parsed(primary_checksum, "primary") if self.cache else None

            if packages:
                self.output.verbose("  → primary packages loaded from parsed cache (fast path)")
                self.output.info(f"Found {len(packages)} packages in repository")
            else:
                # Parsed cache miss - fetch XML and parse it
                xml_content, from_cache = parsers.fetch_metadata_with_cache(
                    session=self.session,
                    base_url=self.config.feed,
                    location=primary_location,
                    checksum=primary_checksum,
                    cache=self.cache,
                    file_type="primary",
                    checksum_type=primary_metadata.get("checksum_type"),
                )
                if from_cache:
                    self.output.verbose("  → primary.xml.gz loaded from cache")
                else:
                    self.output.verbose("  → primary.xml.gz downloaded from upstream")

                # Parse XML (slow operation)
                self.output.verbose("  → parsing primary.xml...")
                packages = parsers.parse_primary_xml(xml_content)
                self.output.info(f"Found {len(packages)} packages in repository")

                # Cache parsed data for next time
                if self.cache:
                    try:
                        self.cache.put_parsed(primary_checksum, packages, "primary")
                        self.output.verbose("  → cached parsed packages for next sync")
                    except Exception as e:
                        self.output.verbose(f"  → warning: failed to cache parsed data: {e}")

            # Step 4: Apply filters if configured
            if self.config.filters:
                original_count = len(packages)
                packages = filters.apply_filters(packages, self.config.filters)
                filtered_out = original_count - len(packages)
                if filtered_out > 0:
                    self.output.info(
                        f"Filtered out {filtered_out} packages, {len(packages)} remaining"
                    )

            # Step 5: Get existing packages from database
            existing_packages = self._get_existing_packages(session)
            self.output.info(f"Already have {len(existing_packages)} packages in pool")

            # Step 6: Download new packages
            self.output.phase("Downloading packages", number=2)
            packages_downloaded = 0
            packages_skipped = 0
            bytes_downloaded = 0

            # Start progress bar for normal mode
            self.output.start_progress(len(packages), "Downloading packages", "packages")

            for i, pkg_meta in enumerate(packages, 1):
                pkg_name = pkg_meta["name"]
                pkg_version = pkg_meta["version"]
                pkg_release = pkg_meta["release"]
                pkg_arch = pkg_meta["arch"]
                pkg_sha256 = pkg_meta["sha256"]
                pkg_location = pkg_meta["location"]
                pkg_size = pkg_meta.get("size_bytes", 0)

                nvra = f"{pkg_name}-{pkg_version}-{pkg_release}.{pkg_arch}"

                # Check if package already exists by SHA256
                if pkg_sha256 in existing_packages:
                    self.output.already_in_pool(nvra, pkg_sha256)
                    packages_skipped += 1

                    # Link existing package to this repository if not already linked
                    existing_pkg = existing_packages[pkg_sha256]
                    if repository not in existing_pkg.repositories:
                        existing_pkg.repositories.append(repository)
                        session.commit()
                        self.output.verbose("  → Linked to repository")

                    self.output.update_progress()
                    continue

                # Download package
                pkg_url = urljoin(self.config.feed + "/", pkg_location)
                self.output.downloading(nvra, pkg_size / 1024 / 1024, i, len(packages))
                self.output.verbose(f"  → URL: {pkg_url}")

                try:
                    downloaded_bytes = self._download_package(
                        pkg_url, pkg_meta, session, repository
                    )
                    packages_downloaded += 1
                    bytes_downloaded += downloaded_bytes
                    self.output.downloaded(downloaded_bytes / 1024 / 1024)
                except SignatureVerificationError:
                    # A 'fail' signature policy must abort the whole sync rather
                    # than silently skipping the offending package.
                    raise
                except Exception as e:
                    self.output.error(f"Failed to download {nvra}: {e}")
                    # Continue with next package

                self.output.update_progress()

            self.output.finish_progress()

            # Step 7: Download metadata files
            self.output.phase("Downloading metadata files", number=3)
            metadata_files = parsers.extract_all_metadata(repomd_root)
            metadata_downloaded = 0

            for metadata_info in metadata_files:
                # Skip primary (already used for package sync)
                if metadata_info["file_type"] == "primary":
                    continue

                try:
                    # Convert dict to MetadataFileInfo for compatibility
                    mfi = MetadataFileInfo(
                        file_type=metadata_info["file_type"],
                        location=metadata_info["location"],
                        checksum=metadata_info["checksum"],
                        size=metadata_info["size"],
                        open_checksum=metadata_info.get("open_checksum"),
                        open_size=metadata_info.get("open_size"),
                        checksum_type=metadata_info.get("checksum_type"),
                    )
                    from_cache = self._download_metadata_file(
                        mfi, session, repository, self.config.feed
                    )
                    metadata_downloaded += 1
                    if from_cache:
                        self.output.verbose(f"  → {metadata_info['file_type']}.xml.gz (cached)")
                    else:
                        self.output.verbose(f"  → {metadata_info['file_type']}.xml.gz (downloaded)")
                except Exception as e:
                    self.output.warning(f"Failed to download {metadata_info['file_type']}: {e}")
                    # Continue with next metadata file

            # Step 8: Check for .treeinfo and download installer files
            self.output.phase("Checking for installer files (.treeinfo)", number=4)
            treeinfo_url = urljoin(self.config.feed, ".treeinfo")
            try:
                response = self.session.get(treeinfo_url, timeout=30)
                response.raise_for_status()

                treeinfo_content = response.text
                installer_files = parsers.parse_treeinfo(treeinfo_content)

                if installer_files:
                    self.output.info(f"Found {len(installer_files)} installer files")
                    installer_downloaded = 0

                    for file_info in installer_files:
                        try:
                            self._download_installer_file(
                                session=session,
                                repository=repository,
                                base_url=self.config.feed,
                                file_info=file_info,
                            )
                            installer_downloaded += 1
                        except Exception as e:
                            self.output.warning(f"Failed to download {file_info['file_type']}: {e}")
                            # Continue with next installer file

                    # Store .treeinfo itself
                    self._store_treeinfo(session, repository, treeinfo_content)

                    self.output.info(
                        f"Installer files downloaded: {installer_downloaded}/{len(installer_files)}"
                    )

            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    self.output.verbose("No .treeinfo found (not an installer repository)")
                else:
                    self.output.warning(f"Failed to fetch .treeinfo: {e}")
            except Exception as e:
                self.output.warning(f"Failed to process .treeinfo: {e}")

            self.output.summary(
                packages_downloaded=packages_downloaded,
                packages_skipped=packages_skipped,
                metadata_files_downloaded=metadata_downloaded,
                total_size_mb=f"{bytes_downloaded / 1024 / 1024:.2f} MB",
            )

            return SyncResult(
                packages_downloaded=packages_downloaded,
                packages_skipped=packages_skipped,
                packages_total=len(packages),
                bytes_downloaded=bytes_downloaded,
                metadata_files_downloaded=metadata_downloaded,
                success=True,
            )

        except Exception as e:
            self.output.error(f"Sync failed: {e}")
            return SyncResult(
                packages_downloaded=0,
                packages_skipped=0,
                packages_total=0,
                bytes_downloaded=0,
                metadata_files_downloaded=0,
                success=False,
                error_message=str(e),
            )
        finally:
            self._teardown_package_verifier()

    def check_updates(self, session: Session, repository: Repository) -> CheckUpdatesResult:
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
            repomd_root = parsers.fetch_repomd_xml(self.session, self.config.feed)

            # Step 2: Extract ALL metadata info (including primary.xml.gz)
            metadata_files = parsers.extract_all_metadata(repomd_root)

            # Find primary.xml metadata
            primary_metadata = next(
                (m for m in metadata_files if m["file_type"] == "primary"), None
            )
            if not primary_metadata:
                raise ValueError("Primary metadata not found in repomd.xml")

            primary_location = primary_metadata["location"]
            primary_checksum = primary_metadata["checksum"]

            # Step 3: Download and parse primary.xml.gz (with parsed data cache support)
            # Try parsed cache first (fastest - avoids XML parsing)
            packages = self.cache.get_parsed(primary_checksum, "primary") if self.cache else None

            if packages:
                print("  → primary packages loaded from parsed cache (fast path)")
                print(f"Found {len(packages)} packages in upstream repository")
            else:
                # Parsed cache miss - fetch XML and parse it
                xml_content, from_cache = parsers.fetch_metadata_with_cache(
                    session=self.session,
                    base_url=self.config.feed,
                    location=primary_location,
                    checksum=primary_checksum,
                    cache=self.cache,
                    file_type="primary",
                    checksum_type=primary_metadata.get("checksum_type"),
                )
                if from_cache:
                    print("  → primary.xml.gz loaded from cache")
                else:
                    print("  → primary.xml.gz downloaded from upstream")

                # Parse XML (slow operation)
                print("  → parsing primary.xml...")
                packages = parsers.parse_primary_xml(xml_content)
                print(f"Found {len(packages)} packages in upstream repository")

                # Cache parsed data for next time
                if self.cache:
                    try:
                        self.cache.put_parsed(primary_checksum, packages, "primary")
                        print("  → cached parsed packages for next check")
                    except Exception as e:
                        print(f"  → warning: failed to cache parsed data: {e}")

            # Step 4: Apply filters if configured
            if self.config.filters:
                original_count = len(packages)
                packages = filters.apply_filters(packages, self.config.filters)
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
                pkg_name = pkg_meta["name"]
                pkg_arch = pkg_meta["arch"]
                key = f"{pkg_name}#{pkg_arch}"
                existing_pkg = existing_packages.get(key)

                if existing_pkg is None:
                    # New package not in our repository
                    update = PackageUpdate(
                        name=pkg_name,
                        arch=pkg_arch,
                        local_version=None,
                        local_release=None,
                        remote_version=pkg_meta["version"],
                        remote_release=pkg_meta["release"],
                        remote_epoch=pkg_meta["epoch"],
                        size_bytes=pkg_meta["size_bytes"],
                        sha256=pkg_meta["sha256"],
                        location=pkg_meta["location"],
                    )
                    updates.append(update)
                    total_update_size += pkg_meta["size_bytes"]
                else:
                    # Package exists - check if remote version is newer
                    remote_epoch = int(pkg_meta.get("epoch") or "0")
                    local_epoch = int(existing_pkg.content_metadata.get("epoch") or "0")

                    # EPOCH-style version comparison: compare epoch, then version, then release
                    is_newer = False

                    if remote_epoch > local_epoch:
                        is_newer = True
                    elif remote_epoch == local_epoch:
                        # Compare version (use packaging library for proper version comparison)
                        try:
                            remote_ver = version.parse(pkg_meta["version"])
                            local_ver = version.parse(existing_pkg.version)

                            if remote_ver > local_ver:
                                is_newer = True
                            elif remote_ver == local_ver:
                                # Compare release
                                remote_rel = version.parse(pkg_meta["release"])
                                local_rel = version.parse(
                                    existing_pkg.content_metadata.get("release", "")
                                )

                                if remote_rel > local_rel:
                                    is_newer = True
                        except Exception:
                            # Fallback to string comparison if packaging fails
                            if pkg_meta["version"] > existing_pkg.version:
                                is_newer = True
                            elif pkg_meta["version"] == existing_pkg.version:
                                if pkg_meta["release"] > existing_pkg.content_metadata.get(
                                    "release", ""
                                ):
                                    is_newer = True

                    if is_newer:
                        # Update available
                        update = PackageUpdate(
                            name=pkg_name,
                            arch=pkg_arch,
                            local_version=existing_pkg.version,
                            local_release=existing_pkg.release,
                            remote_version=pkg_meta["version"],
                            remote_release=pkg_meta["release"],
                            remote_epoch=pkg_meta["epoch"],
                            size_bytes=pkg_meta["size_bytes"],
                            sha256=pkg_meta["sha256"],
                            location=pkg_meta["location"],
                        )
                        updates.append(update)
                        total_update_size += pkg_meta["size_bytes"]

            print("\nCheck complete!")
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

    def _verify_repomd_signature(self, repomd_content: bytes) -> None:
        """Verify the upstream ``repomd.xml`` signature (repo_gpgcheck).

        No-op unless verification is enabled for this repository. Verifies the
        detached ``repomd.xml.asc`` against ``repomd_content`` (the exact bytes
        that will be parsed) using the configured trusted keys, then applies the
        configured behavior policy.

        Args:
            repomd_content: The raw ``repomd.xml`` bytes that will be parsed.
        """
        verify = self.config.verify
        if not verify or not verify.enabled or not verify.repo_gpgcheck:
            return

        from chantal.core.gpg_verify import GpgVerifier

        asc_url = urljoin(self.config.feed + "/", "repodata/repomd.xml.asc")
        asc_response = self.session.get(asc_url, timeout=30)
        if not asc_response.ok:
            self._handle_verify_policy(
                verify.on_missing_signature,
                f"upstream repomd.xml.asc not found ({asc_response.status_code})",
            )
            return

        with GpgVerifier(verify) as verifier:
            valid = verifier.verify_detached(repomd_content, asc_response.content)

        if valid:
            self.output.info("✓ Verified upstream repomd.xml signature")
        else:
            self._handle_verify_policy(
                verify.on_invalid_signature,
                "upstream repomd.xml signature is invalid or not from a trusted key",
            )

    def _handle_verify_policy(self, policy: str, message: str) -> None:
        """Apply a signature-verification behavior policy (fail/warn/skip)."""
        if policy == "fail":
            from chantal.core.gpg_verify import SignatureVerificationError

            raise SignatureVerificationError(f"Signature verification failed: {message}")
        if policy == "warn":
            self.output.warning(f"Signature verification: {message}")
        # "skip": silently continue

    def _setup_package_verifier(self) -> None:
        """Create the reusable package verifier if gpgcheck is enabled."""
        verify = self.config.verify
        if verify and verify.enabled and verify.gpgcheck:
            from chantal.core.gpg_verify import GpgVerifier

            verifier = GpgVerifier(verify)
            verifier.import_trusted_keys()
            self._package_verifier = verifier

    def _teardown_package_verifier(self) -> None:
        """Release the package verifier's keyring, if any."""
        verifier = self._package_verifier
        if verifier is not None:
            verifier.close()  # type: ignore[attr-defined]
            self._package_verifier = None

    def _verify_package_signature(self, rpm_path: Path, nvra: str) -> None:
        """Verify a downloaded package's header signature (gpgcheck).

        No-op unless a package verifier was set up. Reads the ``.rpm``, extracts
        its header-only OpenPGP signature, verifies it against the trusted keys,
        and applies the configured policy.
        """
        verifier = self._package_verifier
        if verifier is None:
            return

        import mmap

        from chantal.core.gpg_verify import GpgVerifier
        from chantal.plugins.rpm.rpm_header import RpmFormatError, extract_header_signature

        assert isinstance(verifier, GpgVerifier)
        verify = self.config.verify
        assert verify is not None

        # mmap the file so only the header region (near the start) is read,
        # not the whole - potentially multi-GB - package. Slicing an mmap yields
        # real bytes, so the extracted blob/packet stay valid after it closes.
        try:
            with (
                open(rpm_path, "rb") as fh,
                mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm,
            ):
                extracted = extract_header_signature(mm)
        except RpmFormatError as exc:
            self._handle_verify_policy(verify.on_invalid_signature, f"{nvra}: {exc}")
            return

        if extracted is None:
            self._handle_verify_policy(
                verify.on_missing_signature, f"{nvra}: package has no GPG signature"
            )
            return

        signature_packet, header_blob = extracted
        if not verifier.verify_detached(header_blob, signature_packet):
            self._handle_verify_policy(
                verify.on_invalid_signature,
                f"{nvra}: invalid or untrusted package signature",
            )

    def _get_existing_packages(self, session: Session) -> dict[str, ContentItem]:
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
        pkg_meta: dict,
        session: Session,
        repository: Repository,
    ) -> int:
        """Download package and add to storage pool.

        Args:
            url: Package download URL
            pkg_meta: Package metadata dict
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

                # Verify the package's GPG signature (gpgcheck) before trusting it.
                nvra = (
                    f"{pkg_meta['name']}-{pkg_meta['version']}-"
                    f"{pkg_meta['release']}.{pkg_meta['arch']}"
                )
                self._verify_package_signature(tmp_path, nvra)

                # Verify the package against the checksum declared in primary.xml,
                # honoring its algorithm (sha256/sha512/sha1) rather than assuming
                # sha256. The pool itself is always addressed by sha256.
                if not parsers.verify_file_checksum(
                    tmp_path, pkg_meta.get("checksum_type"), pkg_meta["sha256"]
                ):
                    algo = parsers.normalize_checksum_type(pkg_meta.get("checksum_type"))
                    raise ValueError(f"{algo} checksum mismatch for {nvra}")

                # Extract filename from location
                filename = Path(pkg_meta["location"]).name

                # Add to storage pool (computes the sha256 used for addressing)
                sha256, pool_path, size_bytes = self.storage.add_package(
                    tmp_path, filename, verify_checksum=True
                )

                # Build RPM metadata
                rpm_metadata = RpmMetadata(
                    epoch=pkg_meta.get("epoch"),
                    release=pkg_meta["release"],
                    arch=pkg_meta["arch"],
                    summary=pkg_meta.get("summary"),
                    description=pkg_meta.get("description"),
                    provides=pkg_meta.get("provides"),
                    requires=pkg_meta.get("requires"),
                    conflicts=pkg_meta.get("conflicts"),
                    obsoletes=pkg_meta.get("obsoletes"),
                )

                # Add to database as ContentItem
                content_item = ContentItem(
                    content_type="rpm",
                    name=pkg_meta["name"],
                    version=pkg_meta["version"],
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

    def _download_metadata_file(
        self,
        metadata_info: MetadataFileInfo,
        session: Session,
        repository: Repository,
        base_url: str,
    ) -> bool:
        """Download metadata file and store as RepositoryFile.

        Uses metadata cache if enabled to avoid redundant downloads.

        Args:
            metadata_info: Metadata file information
            session: Database session
            repository: Repository model instance
            base_url: Base URL of repository

        Returns:
            True if loaded from cache, False if downloaded

        Raises:
            requests.RequestException: On HTTP errors
            ValueError: On checksum mismatch
        """
        from_cache = False

        # Try cache first (if enabled)
        if self.cache:
            cached_file = self.cache.get(metadata_info.checksum, metadata_info.file_type)
            if cached_file:
                # Use cached file directly - it's already compressed
                tmp_path = cached_file
                cleanup_temp = False  # Don't delete cached file
                from_cache = True
            else:
                # Cache miss - download and cache
                metadata_url = urljoin(base_url + "/", metadata_info.location)
                response = self.session.get(metadata_url, timeout=60)
                response.raise_for_status()

                # Cache the compressed file
                try:
                    cached_file = self.cache.put(
                        metadata_info.checksum,
                        response.content,
                        metadata_info.file_type,
                        algorithm=parsers.normalize_checksum_type(metadata_info.checksum_type),
                    )
                    tmp_path = cached_file
                    cleanup_temp = False
                except Exception as e:
                    # Cache failed - use temp file
                    self.output.warning(f"Failed to cache {metadata_info.file_type}: {e}")
                    tmp_file = tempfile.NamedTemporaryFile(
                        delete=False, suffix=f".{metadata_info.file_type}"
                    )
                    tmp_file.write(response.content)
                    tmp_file.flush()
                    tmp_file.close()
                    tmp_path = Path(tmp_file.name)
                    cleanup_temp = True
        else:
            # Cache disabled - download to temp file
            metadata_url = urljoin(base_url + "/", metadata_info.location)

            tmp_file = tempfile.NamedTemporaryFile(
                delete=False, suffix=f".{metadata_info.file_type}"
            )
            tmp_path = Path(tmp_file.name)
            cleanup_temp = True

            try:
                # Download file
                response = self.session.get(metadata_url, timeout=60)
                response.raise_for_status()

                # Write to temp file
                tmp_file.write(response.content)
                tmp_file.flush()
                tmp_file.close()
            except Exception:
                tmp_file.close()
                tmp_path.unlink(missing_ok=True)
                raise

        # Store in pool (using cached or downloaded file)
        try:
            # Extract filename from location
            filename = Path(metadata_info.location).name

            # Verify the file against repomd.xml using the declared algorithm
            # (sha256/sha512/sha1) before adding it to the pool.
            if metadata_info.checksum and not parsers.verify_file_checksum(
                tmp_path, metadata_info.checksum_type, metadata_info.checksum
            ):
                algo = parsers.normalize_checksum_type(metadata_info.checksum_type)
                raise ValueError(
                    f"{algo} checksum mismatch for {metadata_info.file_type}: "
                    f"{metadata_info.location}"
                )

            # Add to storage pool using add_repository_file (sha256-addressed)
            sha256, pool_path, size_bytes = self.storage.add_repository_file(
                tmp_path, filename, verify_checksum=True
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
                        "checksum_type": metadata_info.checksum_type or "sha256",
                        "open_checksum": metadata_info.open_checksum,
                        "open_size": metadata_info.open_size,
                    },
                )
                session.add(repo_file)
                session.commit()

                # Link to repository
                repo_file.repositories.append(repository)
                session.commit()

            return from_cache

        finally:
            # Clean up temp file (only if not from cache)
            if cleanup_temp and tmp_path.exists():
                tmp_path.unlink()

    def _download_installer_file(
        self,
        session: Session,
        repository: Repository,
        base_url: str,
        file_info: dict[str, str | None],
    ) -> None:
        """Download and store installer file.

        Args:
            session: Database session
            repository: Repository instance
            base_url: Repository base URL
            file_info: Dict with path, file_type, sha256
        """
        file_path = file_info["path"]
        if file_path is None:
            raise ValueError("file_info['path'] cannot be None")
        file_type = file_info["file_type"]
        if file_type is None:
            raise ValueError("file_info['file_type'] cannot be None")
        expected_sha256 = file_info.get("sha256")

        file_url = urljoin(base_url, file_path)

        self.output.verbose(f"  → Downloading {file_type}: {file_path}")

        # Download to temp file
        tmp_file = tempfile.NamedTemporaryFile(delete=False)
        try:
            response = self.session.get(file_url, stream=True, timeout=300)
            response.raise_for_status()

            # Download with progress for large files
            for chunk in response.iter_content(chunk_size=8192):
                tmp_file.write(chunk)

            tmp_file.close()
            tmp_file_path = tmp_file.name

            # Calculate SHA256
            sha256_hash = hashlib.sha256()
            with open(tmp_file_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
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
            stored_sha256, pool_path, _ = self.storage.add_repository_file(
                Path(tmp_file_path), filename=Path(file_path).name
            )

            # Create RepositoryFile record
            repo_file = RepositoryFile(
                file_category="kickstart",
                file_type=file_type,
                original_path=file_path,
                pool_path=pool_path,
                sha256=actual_sha256,
                size_bytes=os.path.getsize(tmp_file_path),
            )

            session.add(repo_file)
            repository.repository_files.append(repo_file)
            session.commit()

            # Clean up temp file
            os.unlink(tmp_file_path)

            self.output.verbose(f"    ✓ Stored {file_type} ({actual_sha256[:8]}...)")

        except Exception:
            # Clean up on error
            if os.path.exists(tmp_file.name):
                os.unlink(tmp_file.name)
            raise

    def _store_treeinfo(
        self, session: Session, repository: Repository, treeinfo_content: str
    ) -> None:
        """Store .treeinfo file itself as RepositoryFile.

        Args:
            session: Database session
            repository: Repository instance
            treeinfo_content: .treeinfo file content
        """
        # Write to temp file
        tmp_file = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".treeinfo")
        tmp_file.write(treeinfo_content)
        tmp_file.close()
        tmp_path = tmp_file.name

        try:
            # Calculate SHA256
            sha256_hash = hashlib.sha256(treeinfo_content.encode()).hexdigest()

            # Store in pool
            stored_sha256, pool_path, _ = self.storage.add_repository_file(
                Path(tmp_path), filename=".treeinfo"
            )

            # Create RepositoryFile record
            repo_file = RepositoryFile(
                file_category="kickstart",
                file_type="treeinfo",
                original_path=".treeinfo",
                pool_path=pool_path,
                sha256=sha256_hash,
                size_bytes=len(treeinfo_content),
            )

            session.add(repo_file)
            repository.repository_files.append(repo_file)
            session.commit()

            self.output.verbose("  ✓ Stored .treeinfo")

        finally:
            # Clean up temp file
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
