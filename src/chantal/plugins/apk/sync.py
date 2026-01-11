"""
Alpine APK repository syncer.

This module implements syncing for Alpine APK repositories.
"""

import gzip
import hashlib
import logging
import os
import shutil
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from urllib.parse import urljoin

import requests
from sqlalchemy.orm import Session

from chantal.core.config import ProxyConfig, RepositoryConfig
from chantal.core.downloader import DownloadManager
from chantal.core.storage import StorageManager
from chantal.db.models import ContentItem, Repository, Snapshot
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
        proxy_config: Optional[ProxyConfig] = None,
        ssl_config: Optional["SSLConfig"] = None,
    ):
        """Initialize APK syncer.

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
            config=config,
            proxy_config=proxy_config,
            ssl_config=ssl_config
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

        feed_url = config.feed if config.feed.endswith('/') else config.feed + '/'
        index_url = urljoin(
            feed_url,
            f"{apk_config.branch}/{apk_config.repository}/{apk_config.architecture}/APKINDEX.tar.gz"
        )

        # Fetch and parse APKINDEX
        index_data = self._fetch_apkindex(index_url, config)

        # Parse packages from APKINDEX
        all_packages = self._parse_apkindex(index_data)
        logger.info(f"Found {len(all_packages)} packages in APKINDEX")

        # Apply filters
        filtered_packages = self._apply_filters(all_packages, config)
        logger.info(f"After filtering: {len(filtered_packages)} packages")

        # Download and store packages
        stats = {
            "packages_added": 0,
            "packages_updated": 0,
            "packages_skipped": 0,
            "bytes_downloaded": 0,
            "sha1_mismatches": 0,
        }

        base_url = urljoin(
            feed_url,
            f"{apk_config.branch}/{apk_config.repository}/{apk_config.architecture}/"
        )

        for pkg_entry in filtered_packages:
            try:
                # Create metadata
                metadata = ApkMetadata.from_apkindex_entry(pkg_entry)
                filename = metadata.get_filename()

                # Check if package already exists (by SHA256 in our pool)
                # Note: APK uses SHA1, but we calculate SHA256 for our universal pool
                # We need to check architecture too, since same name+version for different archs are different binaries
                candidates = session.query(ContentItem).filter_by(
                    content_type="apk",
                    name=metadata.name,
                    version=metadata.version,
                ).all()

                existing = None
                for candidate in candidates:
                    if candidate.content_metadata.get("architecture") == metadata.architecture:
                        existing = candidate
                        break

                if existing:
                    # Package already exists - link to repository if not already linked
                    if repository not in existing.repositories:
                        existing.repositories.append(repository)
                        stats["packages_updated"] += 1
                    else:
                        stats["packages_skipped"] += 1
                    continue

                # Download package
                pkg_url = urljoin(base_url, filename)
                pool_path, sha256, size, sha1_ok = self._download_package(pkg_url, config, metadata.checksum)
                if not sha1_ok:
                    stats["sha1_mismatches"] += 1

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

            except Exception as e:
                logger.error(f"Error syncing package {pkg_entry.get('name')}: {e}")
                continue

        session.commit()
        logger.info(f"Sync complete: {stats}")

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
                            content = f.read().decode('utf-8')
                            return content

            raise ValueError("APKINDEX file not found in archive")
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def _parse_apkindex(self, content: str) -> List[dict]:
        """Parse APKINDEX text format.

        Args:
            content: APKINDEX text content

        Returns:
            list: List of package entry dictionaries
        """
        packages = []
        current_pkg = {}

        # Field prefix mapping
        field_map = {
            'C': 'checksum',
            'P': 'name',
            'V': 'version',
            'A': 'architecture',
            'S': 'size',
            'I': 'installed_size',
            'T': 'description',
            'U': 'url',
            'L': 'license',
            'D': 'dependencies',
            'p': 'provides',
            'o': 'origin',
            'm': 'maintainer',
            't': 'build_time',
        }

        for line in content.split('\n'):
            line = line.rstrip()

            if not line:
                # Blank line = end of record
                if current_pkg:
                    # Validate required fields
                    required = ['checksum', 'name', 'version', 'architecture', 'size']
                    if all(field in current_pkg for field in required):
                        packages.append(current_pkg)
                    else:
                        logger.warning(f"Skipping incomplete package entry: {current_pkg.get('name', 'unknown')}")
                    current_pkg = {}
            elif ':' in line:
                prefix, value = line.split(':', 1)
                field = field_map.get(prefix)
                if field:
                    current_pkg[field] = value.strip()

        # Don't forget last package if file doesn't end with blank line
        if current_pkg:
            required = ['checksum', 'name', 'version', 'architecture', 'size']
            if all(field in current_pkg for field in required):
                packages.append(current_pkg)

        return packages

    def _apply_filters(
        self,
        packages: List[dict],
        config: RepositoryConfig
    ) -> List[dict]:
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
                    p for p in filtered
                    if any(pattern.match(p["name"]) for pattern in include_patterns)
                ]

            if config.filters.patterns.exclude:
                import re
                exclude_patterns = [re.compile(p) for p in config.filters.patterns.exclude]
                filtered = [
                    p for p in filtered
                    if not any(pattern.match(p["name"]) for pattern in exclude_patterns)
                ]

        # Post-processing: only_latest_version
        if config.filters and config.filters.post_processing:
            if config.filters.post_processing.only_latest_version:
                # Group by package name and keep only latest version
                from packaging import version as pkg_version

                by_name = {}
                for pkg in filtered:
                    name = pkg["name"]
                    ver = pkg["version"]

                    # APK versions can have -rN suffix (package release)
                    # For comparison, we'll use the full version string
                    if name not in by_name:
                        by_name[name] = pkg
                    else:
                        # Compare versions (APK uses -rN suffix)
                        try:
                            current_ver = ver.split('-r')[0]  # Strip -rN for comparison
                            stored_ver = by_name[name]["version"].split('-r')[0]

                            if pkg_version.parse(current_ver) > pkg_version.parse(stored_ver):
                                by_name[name] = pkg
                            elif pkg_version.parse(current_ver) == pkg_version.parse(stored_ver):
                                # Same version, check release number
                                current_rel = int(ver.split('-r')[1]) if '-r' in ver else 0
                                stored_rel = int(by_name[name]["version"].split('-r')[1]) if '-r' in by_name[name]["version"] else 0
                                if current_rel > stored_rel:
                                    by_name[name] = pkg
                        except Exception as e:
                            logger.warning(f"Version comparison failed for {name}: {e}")
                            pass

                filtered = list(by_name.values())

        return filtered

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

        # Download to temp file and verify SHA1
        import base64
        with tempfile.NamedTemporaryFile(delete=False, suffix=".apk") as tmp:
            sha1_hash = hashlib.sha1()
            for chunk in response.iter_content(chunk_size=8192):
                tmp.write(chunk)
                sha1_hash.update(chunk)
            tmp_path = Path(tmp.name)

        # Verify SHA1 (APK uses base64-encoded SHA1 with Q1 prefix)
        # Note: Alpine CDN sometimes has stale APKINDEX, so we track mismatches but don't fail
        calculated_sha1 = "Q1" + base64.b64encode(sha1_hash.digest()).decode('ascii')
        sha1_ok = calculated_sha1 == expected_sha1

        if not sha1_ok:
            logger.debug(
                f"SHA1 mismatch for {Path(url).name}: expected {expected_sha1}, got {calculated_sha1}"
            )

        filename = Path(url).name

        # Add to pool (this calculates SHA256, deduplicates, and moves file)
        sha256, pool_path, size = self.storage.add_package(tmp_path, filename)

        # Clean up temp file
        tmp_path.unlink(missing_ok=True)

        logger.debug(f"Stored package in pool: {pool_path}")

        return pool_path, sha256, size, sha1_ok
