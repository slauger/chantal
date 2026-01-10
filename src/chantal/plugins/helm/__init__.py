"""
Helm chart repository plugin.

This module implements syncing and publishing for Helm chart repositories.
"""

import gzip
import hashlib
import logging
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from urllib.parse import urljoin

import requests
import yaml
from sqlalchemy.orm import Session

from chantal.core.config import RepositoryConfig
from chantal.core.storage import StorageManager
from chantal.db.models import ContentItem, Repository, Snapshot
from chantal.plugins.base import PublisherPlugin
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

    def __init__(self, storage: StorageManager):
        """Initialize Helm syncer.

        Args:
            storage: Storage manager instance
        """
        self.storage = storage

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
        feed_url = config.feed if config.feed.endswith('/') else config.feed + '/'
        index_url = urljoin(feed_url, "index.yaml")
        index_data = self._fetch_index(index_url, config)

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
                existing = session.query(ContentItem).filter_by(
                    content_type="helm",
                    sha256=chart_entry["digest"] if chart_entry.get("digest") else None
                ).first()

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
                    feed_url = config.feed if config.feed.endswith('/') else config.feed + '/'
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

    def _fetch_index(self, url: str, config: RepositoryConfig) -> dict:
        """Fetch and parse index.yaml.

        Args:
            url: Index URL
            config: Repository configuration (for credentials)

        Returns:
            dict: Parsed index.yaml data
        """
        logger.info(f"Fetching index.yaml from {url}")

        # Build request kwargs
        kwargs = {}
        if config.ssl and config.ssl.client_cert:
            kwargs["cert"] = (config.ssl.client_cert, config.ssl.client_key)
        if config.ssl and config.ssl.ca_cert:
            kwargs["verify"] = config.ssl.ca_cert

        response = requests.get(url, **kwargs, timeout=30)
        response.raise_for_status()

        # Handle encoding - response.content is bytes, decode as UTF-8
        # Some index.yaml files may have special chars, ignore errors
        try:
            content = response.content.decode('utf-8')
        except UnicodeDecodeError:
            # Fallback to latin-1 if UTF-8 fails
            content = response.content.decode('latin-1')

        # Remove control characters that YAML doesn't allow
        # Keep tab (\x09), newline (\x0A), carriage return (\x0D)
        import re
        content = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F-\x9F]', '', content)

        return yaml.safe_load(content)

    def _parse_index(self, index_data: dict) -> List[dict]:
        """Parse chart entries from index.yaml.

        Args:
            index_data: Parsed index.yaml data

        Returns:
            list: List of chart entry dictionaries
        """
        all_charts = []

        entries = index_data.get("entries", {})
        for chart_name, versions in entries.items():
            for version_entry in versions:
                all_charts.append(version_entry)

        return all_charts

    def _apply_filters(
        self,
        charts: List[dict],
        config: RepositoryConfig
    ) -> List[dict]:
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
                    c for c in filtered
                    if any(pattern.match(c["name"]) for pattern in include_patterns)
                ]

            if config.filters.patterns.exclude:
                import re
                exclude_patterns = [re.compile(p) for p in config.filters.patterns.exclude]
                filtered = [
                    c for c in filtered
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

    def _download_chart(
        self,
        url: str,
        config: RepositoryConfig
    ) -> tuple[Path, str, int]:
        """Download chart .tgz file to pool.

        Args:
            url: Chart URL
            config: Repository configuration (for credentials)

        Returns:
            tuple: (pool_path, sha256, size_bytes)
        """
        logger.debug(f"Downloading chart from {url}")

        # Build request kwargs
        kwargs = {}
        if config.ssl and config.ssl.client_cert:
            kwargs["cert"] = (config.ssl.client_cert, config.ssl.client_key)
        if config.ssl and config.ssl.ca_cert:
            kwargs["verify"] = config.ssl.ca_cert

        response = requests.get(url, **kwargs, timeout=300, stream=True)
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

        return pool_path, sha256, size


class HelmPublisher(PublisherPlugin):
    """Publisher for Helm chart repositories.

    Creates standard Helm repository structure:
    - index.yaml - Repository metadata
    - *.tgz - Chart tarballs (hardlinks to pool)
    """

    def __init__(self, storage: StorageManager):
        """Initialize Helm publisher.

        Args:
            storage: Storage manager instance
        """
        super().__init__(storage)

    def publish_repository(
        self,
        session: Session,
        repository: Repository,
        config: RepositoryConfig,
        target_path: Path,
    ) -> None:
        """Publish Helm repository to target directory.

        Args:
            session: Database session
            repository: Repository model instance
            config: Repository configuration
            target_path: Target directory for publishing
        """
        # Get charts
        charts = self._get_repository_charts(session, repository)

        # Publish charts and metadata
        self._publish_charts(charts, target_path, config)

    def publish_snapshot(
        self,
        session: Session,
        snapshot: Snapshot,
        repository: Repository,
        config: RepositoryConfig,
        target_path: Path,
    ) -> None:
        """Publish Helm snapshot to target directory.

        Args:
            session: Database session
            snapshot: Snapshot model instance
            repository: Repository model instance
            config: Repository configuration
            target_path: Target directory for publishing
        """
        # Get charts from snapshot
        charts = self._get_snapshot_charts(session, snapshot)

        # Publish charts and metadata
        self._publish_charts(charts, target_path, config)

    def unpublish(self, target_path: Path) -> None:
        """Remove published Helm repository.

        Args:
            target_path: Target directory to unpublish
        """
        if target_path.exists():
            shutil.rmtree(target_path)

    def _publish_charts(
        self,
        charts: List[ContentItem],
        target_path: Path,
        config: RepositoryConfig
    ) -> None:
        """Publish charts and generate index.yaml.

        Args:
            charts: List of ContentItem instances (type=helm)
            target_path: Target directory
            config: Repository configuration
        """
        target_path.mkdir(parents=True, exist_ok=True)

        # Hardlink chart files to target directory
        for chart in charts:
            pool_path = self.storage.get_pool_path(chart.sha256, chart.filename)
            target_file = target_path / chart.filename

            # Create hardlink
            if target_file.exists():
                target_file.unlink()
            pool_path.hardlink_to(target_file)

        # Generate index.yaml
        self._generate_index_yaml(charts, target_path, config)

        logger.info(f"Published {len(charts)} charts to {target_path}")

    def _generate_index_yaml(
        self,
        charts: List[ContentItem],
        target_path: Path,
        config: RepositoryConfig
    ) -> None:
        """Generate Helm index.yaml file.

        Args:
            charts: List of ContentItem instances
            target_path: Target directory
            config: Repository configuration
        """
        # Build index structure
        index = {
            "apiVersion": "v1",
            "entries": {},
            "generated": datetime.utcnow().isoformat() + "Z"
        }

        # Group charts by name
        for chart in charts:
            metadata = HelmMetadata(**chart.content_metadata)
            name = metadata.name

            if name not in index["entries"]:
                index["entries"][name] = []

            # Convert metadata to index entry
            entry = metadata.to_index_entry()

            # Update URLs to point to published location
            if config.publish and config.publish.base_url:
                entry["urls"] = [f"{config.publish.base_url}/{chart.filename}"]
            else:
                entry["urls"] = [chart.filename]

            # Update digest with actual SHA256
            entry["digest"] = f"sha256:{chart.sha256}"

            index["entries"][name].append(entry)

        # Write index.yaml
        index_path = target_path / "index.yaml"
        with open(index_path, "w") as f:
            yaml.dump(index, f, default_flow_style=False, sort_keys=False)

        logger.debug(f"Generated index.yaml with {len(index['entries'])} chart names")

    def _get_repository_charts(
        self,
        session: Session,
        repository: Repository
    ) -> List[ContentItem]:
        """Get all Helm charts from repository.

        Args:
            session: Database session
            repository: Repository model instance

        Returns:
            list: ContentItem instances (type=helm)
        """
        return [
            item for item in repository.content_items
            if item.content_type == "helm"
        ]

    def _get_snapshot_charts(
        self,
        session: Session,
        snapshot: Snapshot
    ) -> List[ContentItem]:
        """Get all Helm charts from snapshot.

        Args:
            session: Database session
            snapshot: Snapshot model instance

        Returns:
            list: ContentItem instances (type=helm)
        """
        return [
            item for item in snapshot.content_items
            if item.content_type == "helm"
        ]
