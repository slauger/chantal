from __future__ import annotations

"""
RPM repository sync plugin.

This module implements syncing RPM repositories from upstream sources.
"""

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import requests
from packaging import version
from sqlalchemy.orm import Session

from chantal.core.config import ProxyConfig, RepositoryConfig, SSLConfig
from chantal.core.downloader import DownloadManager
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
    checksum: str  # SHA256 checksum
    size: int  # File size in bytes
    open_checksum: str | None = None  # Checksum of uncompressed file
    open_size: int | None = None  # Size of uncompressed file


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

        # Setup download manager with all authentication and SSL/TLS configuration
        self.downloader = DownloadManager(
            config=config, proxy_config=proxy_config, ssl_config=ssl_config
        )

        # Backward compatibility for parsers module
        self.session = self.downloader.session

    def sync_repository(self, session: Session, repository: Repository) -> SyncResult:
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
            repomd_root = parsers.fetch_repomd_xml(self.session, self.config.feed)

            # Step 2: Extract primary.xml.gz location
            primary_location = parsers.extract_primary_location(repomd_root)
            print(f"Primary metadata location: {primary_location}")

            # Step 3: Download and parse primary.xml.gz
            print("Fetching primary.xml.gz...")
            xml_content = parsers.fetch_primary_xml(
                self.session, self.config.feed, primary_location
            )
            packages = parsers.parse_primary_xml(xml_content)
            print(f"Found {len(packages)} packages in repository")

            # Step 4: Apply filters if configured
            if self.config.filters:
                original_count = len(packages)
                packages = filters.apply_filters(packages, self.config.filters)
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
                pkg_name = pkg_meta["name"]
                pkg_version = pkg_meta["version"]
                pkg_release = pkg_meta["release"]
                pkg_arch = pkg_meta["arch"]
                pkg_sha256 = pkg_meta["sha256"]
                pkg_location = pkg_meta["location"]

                print(
                    f"[{i}/{len(packages)}] Processing {pkg_name}-{pkg_version}-{pkg_release}.{pkg_arch}"
                )

                # Check if package already exists by SHA256
                if pkg_sha256 in existing_packages:
                    print(f"  → Already in pool (SHA256: {pkg_sha256[:16]}...)")
                    packages_skipped += 1

                    # Link existing package to this repository if not already linked
                    existing_pkg = existing_packages[pkg_sha256]
                    if repository not in existing_pkg.repositories:
                        existing_pkg.repositories.append(repository)
                        session.commit()
                        print("  → Linked to repository")

                    continue

                # Download package
                pkg_url = urljoin(self.config.feed + "/", pkg_location)
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
            print("\nDownloading metadata files...")
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
                    )
                    self._download_metadata_file(mfi, session, repository, self.config.feed)
                    metadata_downloaded += 1
                    print(f"  → Downloaded {metadata_info['file_type']}.xml.gz")
                except Exception as e:
                    print(f"  → Warning: Failed to download {metadata_info['file_type']}: {e}")
                    # Continue with next metadata file

            # Step 8: Check for .treeinfo and download installer files
            print("\nChecking for installer files (.treeinfo)...")
            treeinfo_url = urljoin(self.config.feed, ".treeinfo")
            try:
                response = self.session.get(treeinfo_url, timeout=30)
                response.raise_for_status()

                treeinfo_content = response.text
                installer_files = parsers.parse_treeinfo(treeinfo_content)

                if installer_files:
                    print(f"Found {len(installer_files)} installer files")
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
                            print(f"  → Warning: Failed to download {file_info['file_type']}: {e}")
                            # Continue with next installer file

                    # Store .treeinfo itself
                    self._store_treeinfo(session, repository, treeinfo_content)

                    print(
                        f"Installer files downloaded: {installer_downloaded}/{len(installer_files)}"
                    )

            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    print("  No .treeinfo found (not an installer repository)")
                else:
                    print(f"  → Warning: Failed to fetch .treeinfo: {e}")
            except Exception as e:
                print(f"  → Warning: Failed to process .treeinfo: {e}")

            print("\nSync complete!")
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

            # Step 2: Extract primary.xml location
            primary_location = parsers.extract_primary_location(repomd_root)

            # Step 3: Download and parse primary.xml
            print("Fetching primary.xml...")
            xml_content = parsers.fetch_primary_xml(
                self.session, self.config.feed, primary_location
            )
            packages = parsers.parse_primary_xml(xml_content)
            print(f"Found {len(packages)} packages in upstream repository")

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

                # Extract filename from location
                filename = Path(pkg_meta["location"]).name

                # Add to storage pool (will verify SHA256)
                sha256, pool_path, size_bytes = self.storage.add_package(
                    tmp_path, filename, verify_checksum=True
                )

                # Verify SHA256 matches metadata
                if sha256 != pkg_meta["sha256"]:
                    raise ValueError(
                        f"SHA256 mismatch: expected {pkg_meta['sha256']}, got {sha256}"
                    )

                # Build RPM metadata
                rpm_metadata = RpmMetadata(
                    epoch=pkg_meta.get("epoch"),
                    release=pkg_meta["release"],
                    arch=pkg_meta["arch"],
                    summary=pkg_meta.get("summary"),
                    description=pkg_meta.get("description"),
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

        with tempfile.NamedTemporaryFile(
            delete=False, suffix=f".{metadata_info.file_type}"
        ) as tmp_file:
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

    def _download_installer_file(
        self, session: Session, repository: Repository, base_url: str, file_info: dict[str, str]
    ) -> None:
        """Download and store installer file.

        Args:
            session: Database session
            repository: Repository instance
            base_url: Repository base URL
            file_info: Dict with path, file_type, sha256
        """
        file_path = file_info["path"]
        file_type = file_info["file_type"]
        expected_sha256 = file_info.get("sha256")

        file_url = urljoin(base_url, file_path)

        print(f"  → Downloading {file_type}: {file_path}")

        # Download to temp file
        tmp_file = tempfile.NamedTemporaryFile(delete=False)
        try:
            response = self.session.get(file_url, stream=True, timeout=300)
            response.raise_for_status()

            # Download with progress for large files
            total_size = int(response.headers.get("content-length", 0))
            downloaded = 0

            for chunk in response.iter_content(chunk_size=8192):
                tmp_file.write(chunk)
                downloaded += len(chunk)

                # Show progress for large files (> 10MB)
                if total_size > 10 * 1024 * 1024:
                    mb_downloaded = downloaded / 1024 / 1024
                    mb_total = total_size / 1024 / 1024
                    print(
                        f"\r    {mb_downloaded:.1f} MB / {mb_total:.1f} MB ({mb_downloaded/mb_total*100:.0f}%)",
                        end="",
                        flush=True,
                    )

            if total_size > 10 * 1024 * 1024:
                print()  # Newline after progress

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
            pool_path = self.storage.add_repository_file(
                Path(tmp_file_path), filename=Path(file_path).name, sha256=actual_sha256
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

            print(f"    ✓ Stored {file_type} ({actual_sha256[:8]}...)")

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
            pool_path = self.storage.add_repository_file(
                Path(tmp_path), filename=".treeinfo", sha256=sha256_hash
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

            print("  ✓ Stored .treeinfo")

        finally:
            # Clean up temp file
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
