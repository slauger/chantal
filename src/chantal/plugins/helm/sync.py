from __future__ import annotations

"""
Helm chart repository syncer.

This module implements syncing for Helm chart repositories.
"""

import logging
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import yaml
from sqlalchemy.orm import Session

from chantal.core.config import ProxyConfig, RepositoryConfig, SSLConfig
from chantal.core.downloader import DownloadManager
from chantal.core.storage import StorageManager
from chantal.db.models import ContentItem, Repository, RepositoryFile
from chantal.plugins.helm.models import HelmMetadata

logger = logging.getLogger(__name__)


class HelmSyncer:
    """Syncer for Helm chart repositories.

    Syncs charts from Helm repositories by:
    1. Fetching index.yaml
    2. Parsing chart metadata
    3. Filtering charts based on repository config
    4. Downloading chart .tgz files to content-addressed pool
    5. Storing metadata in database as ContentItems
    """

    def __init__(
        self,
        storage: StorageManager,
        config: RepositoryConfig,
        proxy_config: ProxyConfig | None = None,
        ssl_config: SSLConfig | None = None,
    ):
        """Initialize Helm syncer.

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

        # Backward compatibility
        self.session = self.downloader.session

    def sync_repository(
        self,
        session: Session,
        repository: Repository,
        config: RepositoryConfig,
    ) -> dict:
        """Sync Helm repository.

        Args:
            session: Database session
            repository: Repository model instance
            config: Repository configuration

        Returns:
            dict: Sync statistics
        """
        logger.info(f"Syncing Helm repository: {repository.repo_id}")

        # Fetch and parse index.yaml
        # Ensure feed URL ends with / for proper urljoin behavior
        feed_url = config.feed if config.feed.endswith("/") else config.feed + "/"
        index_url = urljoin(feed_url, "index.yaml")
        index_data = self._fetch_index(index_url, config)

        # Store index.yaml as RepositoryFile for mirror mode
        self._store_index_file(index_url, config, session, repository)

        # Parse charts from index
        all_charts = self._parse_index(index_data)
        logger.info(f"Found {len(all_charts)} chart versions in index.yaml")

        # Apply filters
        filtered_charts = self._apply_filters(all_charts, config)
        logger.info(f"After filtering: {len(filtered_charts)} chart versions")

        # Download and store charts
        stats = {
            "charts_added": 0,
            "charts_updated": 0,
            "charts_skipped": 0,
            "bytes_downloaded": 0,
        }

        for chart_entry in filtered_charts:
            try:
                # Check if chart already exists
                existing = (
                    session.query(ContentItem)
                    .filter_by(
                        content_type="helm",
                        sha256=chart_entry["digest"] if chart_entry.get("digest") else None,
                    )
                    .first()
                )

                if existing:
                    # Chart already exists - link to repository if not already linked
                    if repository not in existing.repositories:
                        existing.repositories.append(repository)
                        stats["charts_updated"] += 1
                    else:
                        stats["charts_skipped"] += 1
                    continue

                # Download chart
                chart_url = chart_entry["urls"][0]  # Use first URL
                if not chart_url.startswith(("http://", "https://")):
                    # Relative URL - make absolute
                    # Ensure feed URL ends with / for proper urljoin behavior
                    feed_url = config.feed if config.feed.endswith("/") else config.feed + "/"
                    chart_url = urljoin(feed_url, chart_url)

                pool_path, sha256, size = self._download_chart(chart_url, config)

                # Create metadata
                metadata = HelmMetadata(**chart_entry)

                # Create ContentItem
                content_item = ContentItem(
                    name=metadata.name,
                    version=metadata.version,
                    sha256=sha256,
                    filename=Path(chart_url).name,
                    size_bytes=size,
                    pool_path=pool_path,
                    content_type="helm",
                    content_metadata=metadata.model_dump(mode="json"),
                )
                content_item.repositories.append(repository)

                session.add(content_item)
                stats["charts_added"] += 1
                stats["bytes_downloaded"] += size

                logger.debug(f"Added chart: {metadata.name}-{metadata.version}")

            except Exception as e:
                logger.error(f"Error syncing chart {chart_entry.get('name')}: {e}")
                continue

        session.commit()
        logger.info(f"Sync complete: {stats}")

        return stats

    def _fetch_index(self, url: str, config: RepositoryConfig) -> dict[str, Any]:
        """Fetch and parse index.yaml.

        Args:
            url: Index URL
            config: Repository configuration (for credentials)

        Returns:
            dict: Parsed index.yaml data
        """
        logger.info(f"Fetching index.yaml from {url}")

        response = self.session.get(url, timeout=30)
        response.raise_for_status()

        # Handle encoding - response.content is bytes, decode as UTF-8
        # Some index.yaml files may have special chars, ignore errors
        try:
            content = response.content.decode("utf-8")
        except UnicodeDecodeError:
            # Fallback to latin-1 if UTF-8 fails
            content = response.content.decode("latin-1")

        # Remove control characters that YAML doesn't allow
        # Keep tab (\x09), newline (\x0A), carriage return (\x0D)
        import re

        content = re.sub(r"[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F-\x9F]", "", content)

        result: dict[str, Any] = yaml.safe_load(content)
        return result

    def _parse_index(self, index_data: dict) -> list[dict]:
        """Parse chart entries from index.yaml.

        Args:
            index_data: Parsed index.yaml data

        Returns:
            list: List of chart entry dictionaries
        """
        all_charts = []

        entries = index_data.get("entries", {})
        for _chart_name, versions in entries.items():
            for version_entry in versions:
                all_charts.append(version_entry)

        return all_charts

    def _store_index_file(
        self,
        index_url: str,
        config: RepositoryConfig,
        session: Session,
        repository: Repository,
    ) -> None:
        """Download and store index.yaml as RepositoryFile for mirror mode.

        Args:
            index_url: URL to index.yaml
            config: Repository configuration
            session: Database session
            repository: Repository model instance
        """
        logger.info("Storing index.yaml as RepositoryFile")

        # Download index.yaml
        response = self.session.get(index_url, timeout=30)
        response.raise_for_status()

        # Write to temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".yaml") as tmp:
            tmp.write(response.content)
            tmp_path = Path(tmp.name)

        try:
            # Add to storage pool
            sha256, pool_path, size_bytes = self.storage.add_repository_file(
                tmp_path, "index.yaml", verify_checksum=True
            )

            # Check if this RepositoryFile already exists
            existing_file = session.query(RepositoryFile).filter_by(sha256=sha256).first()

            if existing_file:
                # File already exists - just link to repository if not already linked
                if repository not in existing_file.repositories:
                    existing_file.repositories.append(repository)
                    session.commit()
                logger.debug(f"index.yaml already exists in pool: {sha256[:16]}...")
            else:
                # Create new RepositoryFile record
                repo_file = RepositoryFile(
                    file_category="metadata",
                    file_type="index",
                    sha256=sha256,
                    pool_path=pool_path,
                    size_bytes=size_bytes,
                    original_path="index.yaml",
                    file_metadata={
                        "checksum_type": "sha256",
                    },
                )
                session.add(repo_file)
                session.commit()

                # Link to repository
                repo_file.repositories.append(repository)
                session.commit()

                logger.info(f"Stored index.yaml in pool: {sha256[:16]}... ({size_bytes} bytes)")

        finally:
            # Clean up temp file
            tmp_path.unlink(missing_ok=True)

    def _apply_filters(self, charts: list[dict], config: RepositoryConfig) -> list[dict]:
        """Apply filters to chart list.

        Args:
            charts: List of chart entries
            config: Repository configuration

        Returns:
            list: Filtered chart list
        """
        filtered = charts

        # Pattern filters
        if config.filters and config.filters.patterns:
            if config.filters.patterns.include:
                import re

                include_patterns = [re.compile(p) for p in config.filters.patterns.include]
                filtered = [
                    c
                    for c in filtered
                    if any(pattern.match(c["name"]) for pattern in include_patterns)
                ]

            if config.filters.patterns.exclude:
                import re

                exclude_patterns = [re.compile(p) for p in config.filters.patterns.exclude]
                filtered = [
                    c
                    for c in filtered
                    if not any(pattern.match(c["name"]) for pattern in exclude_patterns)
                ]

        # Post-processing: only_latest_version
        if config.filters and config.filters.post_processing:
            if config.filters.post_processing.only_latest_version:
                # Group by chart name and keep only latest version
                from packaging import version as pkg_version

                by_name = {}
                for chart in filtered:
                    name = chart["name"]
                    ver = chart["version"]

                    if name not in by_name:
                        by_name[name] = chart
                    else:
                        # Compare versions
                        try:
                            if pkg_version.parse(ver) > pkg_version.parse(by_name[name]["version"]):
                                by_name[name] = chart
                        except Exception:
                            # Version parsing failed - keep first one
                            pass

                filtered = list(by_name.values())

        return filtered

    def _download_chart(self, url: str, config: RepositoryConfig) -> tuple[Path, str, int]:
        """Download chart .tgz file to pool.

        Args:
            url: Chart URL
            config: Repository configuration (for credentials)

        Returns:
            tuple: (pool_path, sha256, size_bytes)
        """
        logger.debug(f"Downloading chart from {url}")

        response = self.session.get(url, timeout=300, stream=True)
        response.raise_for_status()

        # Download to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".tgz") as tmp:
            for chunk in response.iter_content(chunk_size=8192):
                tmp.write(chunk)
            tmp_path = Path(tmp.name)

        filename = Path(url).name

        # Add to pool (this calculates SHA256, deduplicates, and moves file)
        sha256, pool_path, size = self.storage.add_package(tmp_path, filename)

        # Clean up temp file
        tmp_path.unlink(missing_ok=True)

        logger.debug(f"Stored chart in pool: {pool_path}")

        return Path(pool_path), sha256, size
