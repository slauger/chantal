from __future__ import annotations

"""
Helm chart repository publisher.

This module implements publishing for Helm chart repositories.
"""

import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from chantal.core.config import RepositoryConfig
from chantal.core.storage import StorageManager
from chantal.db.models import ContentItem, Repository, Snapshot
from chantal.plugins.base import PublisherPlugin
from chantal.plugins.helm.models import HelmMetadata

logger = logging.getLogger(__name__)


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
        self, charts: list[ContentItem], target_path: Path, config: RepositoryConfig
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
            pool_path = self.storage.get_absolute_pool_path(chart.sha256, chart.filename)
            target_file = target_path / chart.filename

            # Create hardlink
            if target_file.exists():
                target_file.unlink()
            os.link(pool_path, target_file)

        # Generate index.yaml
        self._generate_index_yaml(charts, target_path, config)

        logger.info(f"Published {len(charts)} charts to {target_path}")

    def _generate_index_yaml(
        self, charts: list[ContentItem], target_path: Path, config: RepositoryConfig
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
            "generated": datetime.utcnow().isoformat() + "Z",
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
            publish_config = getattr(config, "publish", None)
            if publish_config and getattr(publish_config, "base_url", None):
                entry["urls"] = [f"{publish_config.base_url}/{chart.filename}"]
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

    def _get_repository_charts(self, session: Session, repository: Repository) -> list[ContentItem]:
        """Get all Helm charts from repository.

        Args:
            session: Database session
            repository: Repository model instance

        Returns:
            list: ContentItem instances (type=helm)
        """
        return [item for item in repository.content_items if item.content_type == "helm"]

    def _get_snapshot_charts(self, session: Session, snapshot: Snapshot) -> list[ContentItem]:
        """Get all Helm charts from snapshot.

        Args:
            session: Database session
            snapshot: Snapshot model instance

        Returns:
            list: ContentItem instances (type=helm)
        """
        return [item for item in snapshot.content_items if item.content_type == "helm"]
