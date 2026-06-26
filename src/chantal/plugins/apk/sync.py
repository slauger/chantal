from __future__ import annotations

"""
Alpine APK repository syncer.

This module implements syncing for Alpine APK repositories.
"""

import logging
import tarfile
import tempfile
from pathlib import Path
from urllib.parse import urljoin

from sqlalchemy.orm import Session

from chantal.core.config import ProxyConfig, RepositoryConfig, SSLConfig
from chantal.core.downloader import DownloadManager
from chantal.core.output import OutputLevel, SyncOutputter
from chantal.core.storage import StorageManager
from chantal.db.models import ContentItem, Repository, RepositoryFile
from chantal.plugins.apk.checksum import compute_apk_control_checksum
from chantal.plugins.apk.models import ApkMetadata

logger = logging.getLogger(__name__)


class ApkSyncer:
    """Syncer for Alpine APK repositories.

    Syncs packages from Alpine repositories by:
    1. Fetching APKINDEX.tar.gz
    2. Parsing package metadata
    3. Filtering packages based on repository config
    4. Downloading .apk files to content-addressed pool
    5. Storing metadata in database as ContentItems
    """

    def __init__(
        self,
        storage: StorageManager,
        config: RepositoryConfig,
        proxy_config: ProxyConfig | None = None,
        ssl_config: SSLConfig | None = None,
        output_level: OutputLevel = OutputLevel.NORMAL,
    ):
        """Initialize APK syncer.

        Args:
            storage: Storage manager instance
            config: Repository configuration
            proxy_config: Optional proxy configuration
            ssl_config: Optional SSL/TLS configuration
            output_level: Output verbosity level
        """
        self.storage = storage
        self.config = config
        self.proxy_config = proxy_config
        self.ssl_config = ssl_config
        self.output = SyncOutputter(output_level)

        # Setup download manager with all authentication and SSL/TLS configuration
        self.downloader = DownloadManager(
            config=config, proxy_config=proxy_config, ssl_config=ssl_config
        )

        # Backward compatibility
        self.session = self.downloader.session

    def sync_repository(
        self,
        session: Session,
        repository: Repository,
        config: RepositoryConfig,
    ) -> dict:
        """Sync APK repository.

        Args:
            session: Database session
            repository: Repository model instance
            config: Repository configuration

        Returns:
            dict: Sync statistics
        """
        logger.info(f"Syncing APK repository: {repository.repo_id}")

        # Build APKINDEX URL
        # Format: {feed}/{branch}/{repo}/{arch}/APKINDEX.tar.gz
        # Example: https://dl-cdn.alpinelinux.org/alpine/v3.19/main/x86_64/APKINDEX.tar.gz
        apk_config = config.apk
        if not apk_config:
            raise ValueError(f"APK configuration missing for repository {repository.repo_id}")

        self.output.header(
            repository.repo_id,
            "apk",
            config.feed,
            branch=apk_config.branch,
            repository=apk_config.repository,
            architecture=apk_config.architecture,
        )

        feed_url = config.feed if config.feed.endswith("/") else config.feed + "/"
        index_url = urljoin(
            feed_url,
            f"{apk_config.branch}/{apk_config.repository}/{apk_config.architecture}/APKINDEX.tar.gz",
        )

        # Fetch and parse APKINDEX
        self.output.phase("Downloading APKINDEX.tar.gz", number=1)
        index_data = self._fetch_apkindex(index_url, config)

        # Store APKINDEX.tar.gz as RepositoryFile for mirror mode
        self._store_apkindex_file(index_url, config, session, repository)

        # Parse packages from APKINDEX
        all_packages = self._parse_apkindex(index_data)
        logger.info(f"Found {len(all_packages)} packages in APKINDEX")
        self.output.info(f"Found {len(all_packages)} packages in APKINDEX")

        # Apply filters
        filtered_packages = self._apply_filters(all_packages, config)
        logger.info(f"After filtering: {len(filtered_packages)} packages")
        self.output.info(f"After filtering: {len(filtered_packages)} packages")

        # Download and store packages
        self.output.phase("Downloading packages", number=2)
        stats = {
            "packages_added": 0,
            "packages_updated": 0,
            "packages_skipped": 0,
            "bytes_downloaded": 0,
            "sha1_mismatches": 0,
        }

        base_url = urljoin(
            feed_url, f"{apk_config.branch}/{apk_config.repository}/{apk_config.architecture}/"
        )

        self.output.start_progress(len(filtered_packages), "Downloading packages", "packages")

        for i, pkg_entry in enumerate(filtered_packages, 1):
            try:
                # Create metadata
                metadata = ApkMetadata.from_apkindex_entry(pkg_entry)
                filename = metadata.get_filename()

                # Check if package already exists (by SHA256 in our pool)
                # Note: APK uses SHA1, but we calculate SHA256 for our universal pool
                # We need to check architecture too, since same name+version for different archs are different binaries
                candidates = (
                    session.query(ContentItem)
                    .filter_by(
                        content_type="apk",
                        name=metadata.name,
                        version=metadata.version,
                    )
                    .all()
                )

                existing = None
                for candidate in candidates:
                    if candidate.content_metadata.get("architecture") == metadata.architecture:
                        existing = candidate
                        break

                if existing:
                    # Package already exists - link to repository if not already linked
                    pkg_name = f"{metadata.name}-{metadata.version}"
                    self.output.already_in_pool(pkg_name)
                    if repository not in existing.repositories:
                        existing.repositories.append(repository)
                        stats["packages_updated"] += 1
                    else:
                        stats["packages_skipped"] += 1
                    self.output.update_progress()
                    continue

                # Download package
                pkg_url = urljoin(base_url, filename)
                pkg_name = f"{metadata.name}-{metadata.version}"
                pkg_size_mb = metadata.size / 1024 / 1024 if metadata.size else 0
                self.output.downloading(pkg_name, pkg_size_mb, i, len(filtered_packages))

                pool_path, sha256, size, sha1_ok = self._download_package(
                    pkg_url, config, metadata.checksum
                )
                if not sha1_ok:
                    # The downloaded bytes do not match the signed APKINDEX
                    # checksum: reject the package (it is not pooled or linked).
                    stats["sha1_mismatches"] += 1
                    raise ValueError(
                        f"checksum mismatch for {pkg_name} (expected {metadata.checksum}); "
                        "possible tampering or a stale upstream APKINDEX"
                    )

                # Create ContentItem
                content_item = ContentItem(
                    name=metadata.name,
                    version=metadata.version,
                    sha256=sha256,
                    filename=filename,
                    size_bytes=size,
                    pool_path=pool_path,
                    content_type="apk",
                    content_metadata=metadata.model_dump(mode="json"),
                )
                content_item.repositories.append(repository)

                session.add(content_item)
                stats["packages_added"] += 1
                stats["bytes_downloaded"] += size

                logger.debug(f"Added package: {metadata.name}-{metadata.version}")
                self.output.downloaded(size / 1024 / 1024)

            except Exception as e:
                logger.error(f"Error syncing package {pkg_entry.get('name')}: {e}")
                self.output.error(f"Error syncing package {pkg_entry.get('name')}: {e}")
                continue
            finally:
                self.output.update_progress()

        self.output.finish_progress()

        session.commit()
        logger.info(f"Sync complete: {stats}")

        self.output.summary(
            packages_added=stats["packages_added"],
            packages_updated=stats["packages_updated"],
            packages_skipped=stats["packages_skipped"],
            total_size_mb=f"{stats['bytes_downloaded'] / 1024 / 1024:.2f} MB",
            sha1_mismatches=stats["sha1_mismatches"],
        )

        return stats

    def _fetch_apkindex(self, url: str, config: RepositoryConfig) -> str:
        """Fetch and parse APKINDEX.tar.gz.

        Args:
            url: APKINDEX.tar.gz URL
            config: Repository configuration (for credentials)

        Returns:
            str: Parsed APKINDEX text content
        """
        logger.info(f"Fetching APKINDEX from {url}")

        response = self.session.get(url, timeout=30)
        response.raise_for_status()

        # Extract APKINDEX from tar.gz
        with tempfile.NamedTemporaryFile(delete=False, suffix=".tar.gz") as tmp:
            tmp.write(response.content)
            tmp_path = tmp.name

        try:
            with tarfile.open(tmp_path, "r:gz") as tar:
                # APKINDEX is the only file in the archive
                for member in tar.getmembers():
                    if member.name == "APKINDEX" or member.name.endswith("/APKINDEX"):
                        f = tar.extractfile(member)
                        if f:
                            content = f.read().decode("utf-8")
                            return content

            raise ValueError("APKINDEX file not found in archive")
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def _parse_apkindex(self, content: str) -> list[dict]:
        """Parse APKINDEX text format.

        Args:
            content: APKINDEX text content

        Returns:
            list: List of package entry dictionaries
        """
        packages = []
        current_pkg: dict[str, str] = {}

        # Field prefix mapping
        field_map = {
            "C": "checksum",
            "P": "name",
            "V": "version",
            "A": "architecture",
            "S": "size",
            "I": "installed_size",
            "T": "description",
            "U": "url",
            "L": "license",
            "D": "dependencies",
            "p": "provides",
            "o": "origin",
            "m": "maintainer",
            "t": "build_time",
        }

        for line in content.split("\n"):
            line = line.rstrip()

            if not line:
                # Blank line = end of record
                if current_pkg:
                    # Validate required fields
                    required = ["checksum", "name", "version", "architecture", "size"]
                    if all(field in current_pkg for field in required):
                        packages.append(current_pkg)
                    else:
                        logger.warning(
                            f"Skipping incomplete package entry: {current_pkg.get('name', 'unknown')}"
                        )
                    current_pkg = {}
            elif ":" in line:
                prefix, value = line.split(":", 1)
                field = field_map.get(prefix)
                if field:
                    current_pkg[field] = value.strip()

        # Don't forget last package if file doesn't end with blank line
        if current_pkg:
            required = ["checksum", "name", "version", "architecture", "size"]
            if all(field in current_pkg for field in required):
                packages.append(current_pkg)

        return packages

    def _apply_filters(self, packages: list[dict], config: RepositoryConfig) -> list[dict]:
        """Apply filters to package list.

        Args:
            packages: List of package entries
            config: Repository configuration

        Returns:
            list: Filtered package list
        """
        filtered = packages

        # Pattern filters
        if config.filters and config.filters.patterns:
            if config.filters.patterns.include:
                import re

                include_patterns = [re.compile(p) for p in config.filters.patterns.include]
                filtered = [
                    p
                    for p in filtered
                    if any(pattern.match(p["name"]) for pattern in include_patterns)
                ]

            if config.filters.patterns.exclude:
                import re

                exclude_patterns = [re.compile(p) for p in config.filters.patterns.exclude]
                filtered = [
                    p
                    for p in filtered
                    if not any(pattern.match(p["name"]) for pattern in exclude_patterns)
                ]

        # Post-processing: only_latest_version
        if config.filters and config.filters.post_processing:
            if config.filters.post_processing.only_latest_version:
                # Keep only the newest version of each (name, arch), using apk's
                # own version ordering (PEP 440 disagrees on _pre/_p/_rc suffixes
                # and on numeric -rN ordering).
                from chantal.plugins.apk.version import apk_version_compare

                by_key: dict[tuple[str, str], dict] = {}
                for pkg in filtered:
                    key = (pkg["name"], pkg.get("architecture", ""))
                    current = by_key.get(key)
                    if current is None:
                        by_key[key] = pkg
                        continue
                    try:
                        if apk_version_compare(pkg["version"], current["version"]) > 0:
                            by_key[key] = pkg
                    except ValueError as e:
                        # Unparseable version: keep the already-stored package so
                        # the result is deterministic rather than crashing a sync.
                        logger.warning(
                            f"APK version comparison failed for {pkg['name']} "
                            f"({pkg['version']} vs {current['version']}): {e}"
                        )

                filtered = list(by_key.values())

        return filtered

    def _store_apkindex_file(
        self,
        index_url: str,
        config: RepositoryConfig,
        session: Session,
        repository: Repository,
    ) -> None:
        """Download and store APKINDEX.tar.gz as RepositoryFile for mirror mode.

        Args:
            index_url: URL to APKINDEX.tar.gz
            config: Repository configuration
            session: Database session
            repository: Repository model instance
        """
        logger.info("Storing APKINDEX.tar.gz as RepositoryFile")

        # Download APKINDEX.tar.gz
        response = self.session.get(index_url, timeout=30)
        response.raise_for_status()

        # Write to temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".tar.gz") as tmp:
            tmp.write(response.content)
            tmp_path = Path(tmp.name)

        try:
            # Add to storage pool
            sha256, pool_path, size_bytes = self.storage.add_repository_file(
                tmp_path, "APKINDEX.tar.gz", verify_checksum=True
            )

            # Check if this RepositoryFile already exists
            existing_file = session.query(RepositoryFile).filter_by(sha256=sha256).first()

            if existing_file:
                # File already exists - just link to repository if not already linked
                if repository not in existing_file.repositories:
                    existing_file.repositories.append(repository)
                    session.commit()
                logger.debug(f"APKINDEX.tar.gz already exists in pool: {sha256[:16]}...")
            else:
                # Extract relative path from URL for original_path
                # Format: {branch}/{repository}/{architecture}/APKINDEX.tar.gz
                apk_config = config.apk
                if apk_config:
                    original_path = f"{apk_config.branch}/{apk_config.repository}/{apk_config.architecture}/APKINDEX.tar.gz"
                else:
                    original_path = "APKINDEX.tar.gz"

                # Create new RepositoryFile record
                repo_file = RepositoryFile(
                    file_category="metadata",
                    file_type="apkindex",
                    sha256=sha256,
                    pool_path=pool_path,
                    size_bytes=size_bytes,
                    original_path=original_path,
                    file_metadata={
                        "checksum_type": "sha256",
                    },
                )
                session.add(repo_file)
                session.commit()

                # Link to repository
                repo_file.repositories.append(repository)
                session.commit()

                logger.info(
                    f"Stored APKINDEX.tar.gz in pool: {sha256[:16]}... ({size_bytes} bytes)"
                )

        finally:
            # Clean up temp file
            tmp_path.unlink(missing_ok=True)

    def _download_package(
        self,
        url: str,
        config: RepositoryConfig,
        expected_sha1: str,
    ) -> tuple:
        """Download .apk file to pool.

        Args:
            url: Package URL
            config: Repository configuration (for credentials)
            expected_sha1: Expected SHA1 checksum from APKINDEX (base64, Q1-prefixed)

        Returns:
            tuple: (pool_path, sha256, size_bytes, sha1_ok)
        """
        logger.debug(f"Downloading package from {url}")

        response = self.session.get(url, timeout=300, stream=True)
        response.raise_for_status()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".apk") as tmp:
            for chunk in response.iter_content(chunk_size=8192):
                tmp.write(chunk)
            tmp_path = Path(tmp.name)

        # Verify the package against the APKINDEX C: checksum (Q1 + base64(SHA1)
        # of the control segment). Verify BEFORE pooling so a tampered/corrupt
        # package never enters the content pool.
        calculated_sha1 = compute_apk_control_checksum(tmp_path.read_bytes())
        sha1_ok = calculated_sha1 is not None and calculated_sha1 == expected_sha1

        if not sha1_ok:
            logger.warning(
                f"APK checksum mismatch for {Path(url).name}: "
                f"expected {expected_sha1}, got {calculated_sha1}"
            )
            tmp_path.unlink(missing_ok=True)
            return None, None, None, False

        filename = Path(url).name

        # Add to pool (this calculates SHA256, deduplicates, and moves file)
        sha256, pool_path, size = self.storage.add_package(tmp_path, filename)

        # Clean up temp file
        tmp_path.unlink(missing_ok=True)

        logger.debug(f"Stored package in pool: {pool_path}")

        return pool_path, sha256, size, sha1_ok
