from __future__ import annotations

"""
APT/DEB repository sync plugin.

This module implements syncing APT repositories from upstream sources (Ubuntu, Debian, etc.).
Supports mirror mode (1:1 copy with all metadata and GPG signatures preserved).
"""

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

from sqlalchemy.orm import Session

from chantal.core.config import ProxyConfig, RepositoryConfig, SSLConfig
from chantal.core.downloader import DownloadManager
from chantal.core.storage import StorageManager
from chantal.db.models import ContentItem, Repository, RepositoryFile
from chantal.plugins.apt.models import DebMetadata
from chantal.plugins.apt.parsers import parse_packages_from_bytes, parse_release_file

logger = logging.getLogger(__name__)


@dataclass
class MetadataFileInfo:
    """Information about a metadata file from Release."""

    file_type: str  # "Packages", "Sources", "Release", "InRelease", etc.
    relative_path: str  # e.g., "main/binary-amd64/Packages.gz"
    checksum: str  # SHA256 checksum
    size: int  # File size in bytes
    component: str | None = None  # e.g., "main", "contrib"
    architecture: str | None = None  # e.g., "amd64", "arm64", "all"


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


class AptSyncPlugin:
    """Plugin for syncing APT/DEB repositories.

    Handles:
    - Fetching upstream Release/InRelease files
    - Downloading GPG signatures
    - Parsing Packages.gz files for package lists
    - Downloading .deb packages to storage pool
    - Storing metadata files as RepositoryFile
    - Updating database with ContentItem records
    """

    def __init__(
        self,
        storage: StorageManager,
        config: RepositoryConfig,
        proxy_config: ProxyConfig | None = None,
        ssl_config: SSLConfig | None = None,
    ):
        """Initialize APT sync plugin.

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

        # Validate APT-specific config
        if not config.apt:
            raise ValueError(
                f"Repository '{config.id}' is type 'apt' but missing 'apt' configuration"
            )

        self.apt_config = config.apt

        # Setup download manager with all authentication and SSL/TLS configuration
        self.downloader = DownloadManager(
            config=config, proxy_config=proxy_config, ssl_config=ssl_config
        )

        # Backward compatibility for direct session access
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
            print(f"Syncing APT repository: {repository.repo_id}")
            print(f"Feed URL: {self.config.feed}")
            print(f"Distribution: {self.apt_config.distribution}")
            print(f"Components: {', '.join(self.apt_config.components)}")
            print(f"Architectures: {', '.join(self.apt_config.architectures)}")

            # Build dists URL (feed should point to repository root, not dists/)
            dists_url = urljoin(self.config.feed + "/", f"dists/{self.apt_config.distribution}/")

            # Phase 1: Download Release/InRelease files
            print("\n=== Phase 1: Downloading Release metadata ===")
            release_metadata = self._fetch_and_store_release(session, repository, dists_url)

            # Phase 2: Download Packages.gz/Sources.gz for all components/architectures
            print("\n=== Phase 2: Downloading repository metadata ===")
            metadata_files = self._build_metadata_file_list(release_metadata)
            print(f"Found {len(metadata_files)} metadata files to download")

            metadata_downloaded = 0
            for metadata_info in metadata_files:
                try:
                    self._download_metadata_file(session, repository, dists_url, metadata_info)
                    metadata_downloaded += 1
                    print(f"  → Downloaded {metadata_info.relative_path}")
                except Exception as e:
                    logger.warning(f"Failed to download {metadata_info.relative_path}: {e}")
                    print(f"  → Warning: Failed to download {metadata_info.relative_path}: {e}")

            # Phase 3: Parse Packages files and download .deb packages
            print("\n=== Phase 3: Downloading packages ===")
            packages_total = 0
            packages_downloaded = 0
            packages_skipped = 0
            bytes_downloaded = 0

            # Get existing packages from database (for deduplication)
            existing_packages = self._get_existing_packages(session)
            print(f"Already have {len(existing_packages)} packages in pool")

            # Collect all packages from Packages files
            all_packages = []
            for metadata_info in metadata_files:
                # Only process Packages files (not Sources)
                if metadata_info.file_type != "Packages":
                    continue

                print(f"\nProcessing {metadata_info.component}/{metadata_info.architecture}...")

                # Get the Packages.gz file from storage
                packages_gz_path = self._get_metadata_file_path(session, metadata_info, repository)

                if not packages_gz_path or not packages_gz_path.exists():
                    logger.warning(
                        f"Packages file not found in storage: {metadata_info.relative_path}"
                    )
                    continue

                # Parse Packages file
                with open(packages_gz_path, "rb") as f:
                    packages_data = f.read()

                # Parse (file is already decompressed in storage as .gz)
                try:
                    import gzip

                    packages_content = gzip.decompress(packages_data)
                    packages = parse_packages_from_bytes(packages_content, compressed=False)
                except Exception as e:
                    logger.error(f"Failed to parse Packages file: {e}")
                    continue

                print(f"  Found {len(packages)} packages")
                all_packages.extend(packages)

            packages_total = len(all_packages)
            print(f"\nTotal packages found: {packages_total}")

            # Apply filters if repository mode is filtered
            if repository.mode == "filtered":
                print("\n=== Applying Filters (Filtered Mode) ===")
                all_packages = self._apply_filters(all_packages, self.config)
                print(f"After filtering: {len(all_packages)} packages")
                print("⚠️  WARNING: Filtered mode will regenerate metadata without GPG signatures!")
                print("    Clients must use [trusted=yes] or Acquire::AllowInsecureRepositories=1")

            # Download filtered packages
            for pkg in all_packages:
                pkg_name = f"{pkg.package}_{pkg.version}_{pkg.architecture}"

                # Check if already in pool
                if pkg.sha256 in existing_packages:
                    print(f"  → {pkg_name}: already in pool")
                    packages_skipped += 1

                    # Link existing package to this repository if not already linked
                    existing_pkg = existing_packages[pkg.sha256]
                    if repository not in existing_pkg.repositories:
                        existing_pkg.repositories.append(repository)
                        session.commit()
                    continue

                # Download package
                try:
                    pkg_url = urljoin(self.config.feed + "/", pkg.filename)
                    downloaded_bytes = self._download_package(pkg_url, pkg, session, repository)
                    packages_downloaded += 1
                    bytes_downloaded += downloaded_bytes
                    print(f"  → {pkg_name}: downloaded {downloaded_bytes / 1024 / 1024:.2f} MB")
                except Exception as e:
                    logger.error(f"Failed to download {pkg_name}: {e}")
                    print(f"  → {pkg_name}: ERROR - {e}")

            # Sync complete
            print("\n=== Sync Complete ===")
            print(f"Packages downloaded: {packages_downloaded}")
            print(f"Packages skipped: {packages_skipped}")
            print(f"Packages total: {packages_total}")
            print(f"Bytes downloaded: {bytes_downloaded / 1024 / 1024:.2f} MB")
            print(f"Metadata files: {metadata_downloaded}")

            return SyncResult(
                packages_downloaded=packages_downloaded,
                packages_skipped=packages_skipped,
                packages_total=packages_total,
                bytes_downloaded=bytes_downloaded,
                metadata_files_downloaded=metadata_downloaded,
                success=True,
            )

        except Exception as e:
            logger.exception(f"Sync failed: {e}")
            print(f"ERROR: Sync failed: {e}")
            return SyncResult(
                packages_downloaded=0,
                packages_skipped=0,
                packages_total=0,
                bytes_downloaded=0,
                metadata_files_downloaded=0,
                success=False,
                error_message=str(e),
            )

    def _fetch_and_store_release(
        self, session: Session, repository: Repository, dists_url: str
    ) -> dict:
        """Download and store Release/InRelease files.

        Args:
            session: Database session
            repository: Repository instance
            dists_url: URL to dists/SUITE/ directory

        Returns:
            Parsed release metadata dict

        Raises:
            Exception: On download or parse errors
        """
        # Try InRelease first (contains GPG signature inline)
        inrelease_url = urljoin(dists_url, "InRelease")
        release_url = urljoin(dists_url, "Release")
        release_gpg_url = urljoin(dists_url, "Release.gpg")

        release_content = None
        inrelease_downloaded = False

        # Try InRelease (preferred)
        try:
            print(f"Fetching {inrelease_url}...")
            response = self.session.get(inrelease_url, timeout=60)
            response.raise_for_status()
            release_content = response.text
            inrelease_downloaded = True

            # Store InRelease as RepositoryFile
            self._store_file_as_repository_file(
                session=session,
                repository=repository,
                content=response.content,
                filename="InRelease",
                file_type="InRelease",
                file_category="metadata",
                original_path="InRelease",
            )
            print("  → Downloaded InRelease")

        except Exception as e:
            logger.warning(f"Failed to download InRelease: {e}")
            print(f"  → InRelease not available: {e}")

        # Fallback to Release + Release.gpg
        if not inrelease_downloaded:
            try:
                print(f"Fetching {release_url}...")
                response = self.session.get(release_url, timeout=60)
                response.raise_for_status()
                release_content = response.text

                # Store Release file
                self._store_file_as_repository_file(
                    session=session,
                    repository=repository,
                    content=response.content,
                    filename="Release",
                    file_type="Release",
                    file_category="metadata",
                    original_path="Release",
                )
                print("  → Downloaded Release")

                # Try to download Release.gpg
                try:
                    gpg_response = self.session.get(release_gpg_url, timeout=60)
                    gpg_response.raise_for_status()

                    self._store_file_as_repository_file(
                        session=session,
                        repository=repository,
                        content=gpg_response.content,
                        filename="Release.gpg",
                        file_type="Release.gpg",
                        file_category="signature",
                        original_path="Release.gpg",
                    )
                    print("  → Downloaded Release.gpg")
                except Exception as gpg_error:
                    logger.warning(f"Failed to download Release.gpg: {gpg_error}")
                    print(f"  → Warning: Release.gpg not available: {gpg_error}")

            except Exception as e:
                raise Exception(f"Failed to download Release file: {e}") from e

        if not release_content:
            raise Exception("Failed to download Release metadata")

        # Parse Release file
        try:
            # Remove GPG signature if present (from InRelease)
            release_text = release_content
            if "-----BEGIN PGP SIGNED MESSAGE-----" in release_content:
                # Extract content between headers and signature
                lines = release_content.split("\n")
                content_lines = []
                in_content = False
                for line in lines:
                    if line.startswith("Hash:"):
                        in_content = True
                        continue
                    if in_content and line.startswith("-----BEGIN PGP SIGNATURE-----"):
                        break
                    if in_content:
                        content_lines.append(line)
                release_text = "\n".join(content_lines)

            release_metadata = parse_release_file(release_text)
            print(f"  → Parsed Release: {release_metadata.suite}/{release_metadata.codename}")
            print(f"  → Components: {', '.join(release_metadata.components)}")
            print(f"  → Architectures: {', '.join(release_metadata.architectures)}")

            # Return release metadata as dict for compatibility
            return {
                "suite": release_metadata.suite,
                "codename": release_metadata.codename,
                "components": release_metadata.components,
                "architectures": release_metadata.architectures,
                "sha256": release_metadata.sha256,
            }

        except Exception as e:
            raise Exception(f"Failed to parse Release file: {e}") from e

    def _build_metadata_file_list(self, release_metadata: dict) -> list[MetadataFileInfo]:
        """Build list of metadata files to download based on configuration.

        Args:
            release_metadata: Parsed Release metadata

        Returns:
            List of MetadataFileInfo objects
        """
        metadata_files = []

        # Get configured components and architectures
        components = self.apt_config.components
        architectures = self.apt_config.architectures

        # Validate components are available
        available_components = release_metadata.get("components", [])
        for component in components:
            if component not in available_components:
                logger.warning(
                    f"Component '{component}' not available in Release "
                    f"(available: {', '.join(available_components)})"
                )

        # Validate architectures are available
        available_architectures = release_metadata.get("architectures", [])
        for arch in architectures:
            if arch not in available_architectures:
                logger.warning(
                    f"Architecture '{arch}' not available in Release "
                    f"(available: {', '.join(available_architectures)})"
                )

        # Build metadata file list
        sha256_checksums = release_metadata.get("sha256", {})

        for component in components:
            for arch in architectures:
                # Binary packages (Packages.gz)
                packages_path = f"{component}/binary-{arch}/Packages.gz"
                if packages_path in sha256_checksums:
                    checksum, size = sha256_checksums[packages_path]
                    metadata_files.append(
                        MetadataFileInfo(
                            file_type="Packages",
                            relative_path=packages_path,
                            checksum=checksum,
                            size=size,
                            component=component,
                            architecture=arch,
                        )
                    )

            # Source packages (Sources.gz) - if configured
            if self.apt_config.include_source_packages:
                sources_path = f"{component}/source/Sources.gz"
                if sources_path in sha256_checksums:
                    checksum, size = sha256_checksums[sources_path]
                    metadata_files.append(
                        MetadataFileInfo(
                            file_type="Sources",
                            relative_path=sources_path,
                            checksum=checksum,
                            size=size,
                            component=component,
                            architecture=None,
                        )
                    )

        return metadata_files

    def _download_metadata_file(
        self,
        session: Session,
        repository: Repository,
        dists_url: str,
        metadata_info: MetadataFileInfo,
    ) -> None:
        """Download metadata file and store as RepositoryFile.

        Args:
            session: Database session
            repository: Repository instance
            dists_url: Base URL to dists/SUITE/ directory
            metadata_info: Metadata file information

        Raises:
            Exception: On download or storage errors
        """
        metadata_url = urljoin(dists_url, metadata_info.relative_path)

        with tempfile.NamedTemporaryFile(
            delete=False, suffix=f".{metadata_info.file_type}.gz"
        ) as tmp_file:
            tmp_path = Path(tmp_file.name)

            try:
                # Download file
                response = self.session.get(metadata_url, timeout=120)
                response.raise_for_status()

                # Write to temp file
                tmp_file.write(response.content)
                tmp_file.flush()

                # Extract filename from relative path
                filename = Path(metadata_info.relative_path).name

                # Add to storage pool using add_repository_file
                sha256, pool_path, size_bytes = self.storage.add_repository_file(
                    tmp_path, filename, verify_checksum=True
                )

                # Verify SHA256 matches Release metadata
                if sha256 != metadata_info.checksum:
                    raise ValueError(
                        f"SHA256 mismatch for {metadata_info.relative_path}: "
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
                        original_path=metadata_info.relative_path,
                        file_metadata={
                            "component": metadata_info.component,
                            "architecture": metadata_info.architecture,
                            "checksum_type": "sha256",
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

    def _download_package(
        self,
        url: str,
        pkg_meta: DebMetadata,
        session: Session,
        repository: Repository,
    ) -> int:
        """Download .deb package and add to storage pool.

        Args:
            url: Package download URL
            pkg_meta: Package metadata from Packages file
            session: Database session
            repository: Repository model instance

        Returns:
            Number of bytes downloaded

        Raises:
            Exception: On download or storage errors
        """
        # Download to temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".deb") as tmp_file:
            tmp_path = Path(tmp_file.name)

            try:
                # Stream download
                response = self.session.get(url, stream=True, timeout=300)
                response.raise_for_status()

                # Download with chunking
                bytes_downloaded = 0
                for chunk in response.iter_content(chunk_size=65536):
                    tmp_file.write(chunk)
                    bytes_downloaded += len(chunk)

                tmp_file.flush()

                # Extract filename from metadata
                filename = Path(pkg_meta.filename).name

                # Add to storage pool (will verify SHA256)
                sha256, pool_path, size_bytes = self.storage.add_package(
                    tmp_path, filename, verify_checksum=True
                )

                # Verify SHA256 matches metadata
                if sha256 != pkg_meta.sha256:
                    raise ValueError(f"SHA256 mismatch: expected {pkg_meta.sha256}, got {sha256}")

                # Create ContentItem with DebMetadata
                content_item = ContentItem(
                    content_type="deb",
                    name=pkg_meta.package,
                    version=pkg_meta.version,
                    sha256=sha256,
                    size_bytes=size_bytes,
                    pool_path=pool_path,
                    filename=filename,
                    content_metadata=pkg_meta.model_dump(exclude_none=False),
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

    def _store_file_as_repository_file(
        self,
        session: Session,
        repository: Repository,
        content: bytes,
        filename: str,
        file_type: str,
        file_category: str,
        original_path: str,
    ) -> None:
        """Store arbitrary file as RepositoryFile.

        Args:
            session: Database session
            repository: Repository instance
            content: File content (bytes)
            filename: Filename to use
            file_type: File type (InRelease, Release, Release.gpg)
            file_category: Category (metadata, signature)
            original_path: Original path in repository
        """
        # Write to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_type}") as tmp_file:
            tmp_path = Path(tmp_file.name)
            tmp_file.write(content)
            tmp_file.flush()

            try:
                # Add to storage pool
                sha256, pool_path, size_bytes = self.storage.add_repository_file(
                    tmp_path, filename, verify_checksum=False
                )

                # Check if already exists
                existing_file = session.query(RepositoryFile).filter_by(sha256=sha256).first()

                if existing_file:
                    # Link to repository if not already linked
                    if repository not in existing_file.repositories:
                        existing_file.repositories.append(repository)
                        session.commit()
                else:
                    # Create new RepositoryFile
                    repo_file = RepositoryFile(
                        file_category=file_category,
                        file_type=file_type,
                        sha256=sha256,
                        pool_path=pool_path,
                        size_bytes=size_bytes,
                        original_path=original_path,
                        file_metadata={"checksum_type": "sha256"},
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

    def _get_existing_packages(self, session: Session) -> dict[str, ContentItem]:
        """Get existing content items from database.

        Args:
            session: Database session

        Returns:
            Dict mapping SHA256 -> ContentItem
        """
        content_items = session.query(ContentItem).filter(ContentItem.content_type == "deb").all()
        return {item.sha256: item for item in content_items}

    def _get_metadata_file_path(
        self, session: Session, metadata_info: MetadataFileInfo, repository: Repository
    ) -> Path | None:
        """Get path to metadata file in storage pool.

        Args:
            session: Database session
            metadata_info: Metadata file information
            repository: Repository instance

        Returns:
            Path to file in pool, or None if not found
        """
        # Find RepositoryFile by checksum
        repo_file = session.query(RepositoryFile).filter_by(sha256=metadata_info.checksum).first()

        if not repo_file:
            return None

        # Return full path to file in pool
        return self.storage.pool_path / repo_file.pool_path

    def _apply_filters(
        self, packages: list[DebMetadata], config: RepositoryConfig
    ) -> list[DebMetadata]:
        """Apply filters to package list.

        Args:
            packages: List of package metadata entries
            config: Repository configuration with filters

        Returns:
            Filtered package list
        """
        if not config.filters:
            return packages

        filtered = packages

        # Component filters (DebFilterConfig)
        if config.filters.deb and config.filters.deb.components:
            if config.filters.deb.components.include:
                filtered = [
                    p
                    for p in filtered
                    if p.component and p.component in config.filters.deb.components.include
                ]
            if config.filters.deb.components.exclude:
                filtered = [
                    p
                    for p in filtered
                    if not (p.component and p.component in config.filters.deb.components.exclude)
                ]

        # Priority filters (DebFilterConfig)
        if config.filters.deb and config.filters.deb.priorities:
            if config.filters.deb.priorities.include:
                filtered = [
                    p
                    for p in filtered
                    if p.priority and p.priority in config.filters.deb.priorities.include
                ]
            if config.filters.deb.priorities.exclude:
                filtered = [
                    p
                    for p in filtered
                    if not (p.priority and p.priority in config.filters.deb.priorities.exclude)
                ]

        # Pattern filters (include/exclude by package name)
        if config.filters.patterns:
            if config.filters.patterns.include:
                import re

                include_patterns = [re.compile(p) for p in config.filters.patterns.include]
                filtered = [
                    p
                    for p in filtered
                    if any(pattern.match(p.package) for pattern in include_patterns)
                ]

            if config.filters.patterns.exclude:
                import re

                exclude_patterns = [re.compile(p) for p in config.filters.patterns.exclude]
                filtered = [
                    p
                    for p in filtered
                    if not any(pattern.match(p.package) for pattern in exclude_patterns)
                ]

        # Post-processing: only_latest_version
        if config.filters.post_processing and config.filters.post_processing.only_latest_version:
            from packaging import version as pkg_version

            # Group by (package name, architecture)
            by_name_arch = {}
            for pkg in filtered:
                key = (pkg.package, pkg.architecture)
                if key not in by_name_arch:
                    by_name_arch[key] = pkg
                else:
                    # Compare versions
                    try:
                        if pkg_version.parse(pkg.version) > pkg_version.parse(
                            by_name_arch[key].version
                        ):
                            by_name_arch[key] = pkg
                    except Exception:
                        # Version parsing failed - keep first one
                        pass

            filtered = list(by_name_arch.values())

        return filtered
