from __future__ import annotations

"""
Helm chart repository publisher.

This module implements publishing for Helm chart repositories.
"""

import logging
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.orm import Session

from chantal.core.config import RepositoryConfig
from chantal.core.storage import StorageManager
from chantal.db.models import ContentItem, Repository, RepositoryMode, Snapshot
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
        self._publish_charts(charts, target_path, config, session, repository)

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
        self._publish_charts(charts, target_path, config, session, repository, snapshot=snapshot)

    def unpublish(self, target_path: Path) -> None:
        """Remove published Helm repository.

        Args:
            target_path: Target directory to unpublish
        """
        if target_path.exists():
            shutil.rmtree(target_path)

    def _publish_charts(
        self,
        charts: list[ContentItem],
        target_path: Path,
        config: RepositoryConfig,
        session: Session,
        repository: Repository,
        snapshot: Snapshot | None = None,
    ) -> None:
        """Publish charts and index.yaml.

        Args:
            charts: List of ContentItem instances (type=helm)
            target_path: Target directory
            config: Repository configuration
            session: Database session
            repository: Repository model instance
            snapshot: Optional snapshot model instance (for snapshot publishing)
        """
        target_path.mkdir(parents=True, exist_ok=True)

        # A repackaged chart (same name+version, hence same filename, but new
        # bytes) leaves two ContentItems linked. Publishing both hardlinks the
        # same filename twice (last wins on disk) and emits two index entries with
        # conflicting digests pointing at the one file - a client resolving the
        # wrong digest then fails verification. Keep one chart per filename (the
        # most recently synced, i.e. highest id) so disk and index agree.
        charts = self._dedup_charts_by_filename(charts)

        # Hardlink chart files to target directory
        for chart in charts:
            # Use the authoritative stored pool_path, not a path reconstructed
            # from sha256+filename (which diverges for oci:// / query-string
            # filenames).
            pool_path = self.storage.pool_path / chart.pool_path
            target_file = target_path / chart.filename

            # Create hardlink
            if target_file.exists():
                target_file.unlink()
            os.link(pool_path, target_file)

        # Publish metadata files (index.yaml) from RepositoryFile or generate
        self._publish_metadata_files(
            session, repository, target_path, config, charts, snapshot=snapshot
        )

        logger.info(f"Published {len(charts)} charts to {target_path}")

    @staticmethod
    def _dedup_charts_by_filename(charts: list[ContentItem]) -> list[ContentItem]:
        """Keep a single chart per published filename (the highest-id one).

        Two ContentItems can share a filename when upstream repackages a chart
        (same name+version, new bytes). They map to one tarball on disk, so the
        published index must reference exactly one of them; keep the most recently
        synced (highest id) so the index digest matches the file that wins on disk.
        """
        by_filename: dict[str, ContentItem] = {}
        for chart in charts:
            existing = by_filename.get(chart.filename)
            if existing is None or (chart.id or 0) > (existing.id or 0):
                by_filename[chart.filename] = chart
        return list(by_filename.values())

    def _publish_metadata_files(
        self,
        session: Session,
        repository: Repository,
        target_path: Path,
        config: RepositoryConfig,
        charts: list[ContentItem],
        snapshot: Snapshot | None = None,
    ) -> None:
        """Publish index.yaml: regenerate it (filtered/hosted) or rewrite it.

        Filtered mode always regenerates index.yaml from the published charts.
        Mirror mode republishes the upstream index.yaml but rewrites its chart
        URLs to point at this mirror, falling back to generation when none was
        stored.

        Args:
            session: Database session
            repository: Repository model instance
            target_path: Target directory for index.yaml
            config: Repository configuration
            charts: List of charts (for fallback generation)
            snapshot: Optional snapshot model instance
        """
        # In filtered mode the published chart set differs from upstream, so
        # always regenerate index.yaml from the published charts. Republishing
        # the upstream index (stored unconditionally during sync) would still
        # list charts that were filtered out. Mirror mode republishes the
        # upstream index with its chart URLs rewritten to this mirror.
        if repository.mode == RepositoryMode.FILTERED:
            self._generate_index_yaml(charts, target_path, config)
            return

        # Find index.yaml RepositoryFile
        index_file = None

        if snapshot:
            # For snapshots, get repository_files from snapshot
            for repo_file in snapshot.repository_files:
                if repo_file.file_type == "index" and repo_file.file_category == "metadata":
                    index_file = repo_file
                    break
        else:
            # For repositories, get repository_files from repository
            for repo_file in repository.repository_files:
                if repo_file.file_type == "index" and repo_file.file_category == "metadata":
                    index_file = repo_file
                    break

        if index_file:
            # Mirror mode: republish the upstream index.yaml, but rewrite the
            # chart URLs to point at this mirror. Upstream indexes (e.g. Bitnami)
            # often use absolute URLs back to the upstream server; hardlinking
            # them verbatim would send clients upstream, defeating the mirror.
            pool_path = self.storage.pool_path / index_file.pool_path
            self._publish_mirror_index(pool_path, target_path, charts, config)
            logger.info(
                f"Published index.yaml from pool (mirror mode): {index_file.sha256[:16]}..."
            )
        else:
            # Fallback: Generate index.yaml from charts
            logger.info("No index.yaml in pool, generating from charts")
            self._generate_index_yaml(charts, target_path, config)

    def _publish_mirror_index(
        self,
        index_pool_path: Path,
        target_path: Path,
        charts: list[ContentItem],
        config: RepositoryConfig,
    ) -> None:
        """Republish the upstream index.yaml with chart URLs rewritten.

        Each version entry's ``urls`` are rewritten to the bare published
        filename (relative to the repo root, matching the regenerated/filtered
        path and where the charts are actually published). Versions whose chart
        was not published (download failed / digest mismatch) are dropped so the
        index never references a missing tarball. On any parse error the index is
        regenerated from the published charts rather than served unrewritten.
        """
        from chantal.plugins.helm.sync import normalize_digest

        target_file = target_path / "index.yaml"
        # Resolve each index version to the chart actually published for it. Match
        # by content digest first (robust to cross-repo dedup, where the stored
        # filename can differ from this index's basename) and fall back to the
        # tarball basename. The value is the published filename to serve.
        by_digest = {
            normalize_digest(chart.sha256): chart.filename
            for chart in charts
            if normalize_digest(chart.sha256)
        }
        by_name = {chart.filename for chart in charts}

        try:
            data = yaml.safe_load(index_pool_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("entries"), dict):
                raise ValueError("index.yaml has no entries mapping")
        except Exception as exc:  # noqa: BLE001 - any malformed index -> regenerate
            logger.warning(f"Could not parse upstream index.yaml ({exc}); regenerating from charts")
            self._generate_index_yaml(charts, target_path, config)
            return

        for name, versions in list(data["entries"].items()):
            if not isinstance(versions, list):
                continue
            kept = []
            for entry in versions:
                if not isinstance(entry, dict):
                    continue
                urls = entry.get("urls")
                if not isinstance(urls, list) or not urls:
                    continue
                basename = Path(str(urls[0])).name
                published_name = by_digest.get(normalize_digest(entry.get("digest")))
                if published_name is None and basename in by_name:
                    published_name = basename
                if published_name is None:
                    # Not mirrored (filtered out / download failed) -> drop it so
                    # the index never references a missing tarball.
                    continue
                entry["urls"] = [published_name]
                kept.append(entry)
            if kept:
                data["entries"][name] = kept
            else:
                del data["entries"][name]

        if target_file.exists():
            target_file.unlink()
        with open(target_file, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

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
        index: dict[str, Any] = {
            "apiVersion": "v1",
            "entries": {},
            "generated": datetime.now(UTC).replace(tzinfo=None).isoformat() + "Z",
        }
        entries: dict[str, list[dict[str, Any]]] = index["entries"]

        # Group charts by name
        for chart in charts:
            metadata = HelmMetadata(**chart.content_metadata)
            name = metadata.name

            if name not in entries:
                entries[name] = []

            # Convert metadata to index entry
            entry = metadata.to_index_entry()

            # Update URLs to point to published location
            publish_config = getattr(config, "publish", None)
            if publish_config and getattr(publish_config, "base_url", None):
                entry["urls"] = [f"{publish_config.base_url}/{chart.filename}"]
            else:
                entry["urls"] = [chart.filename]

            # Set the digest to the actual chart SHA256. Helm index.yaml digests
            # are bare hex (no "sha256:" prefix); emitting the prefix breaks
            # digest-consuming tooling and self-mirror dedup.
            entry["digest"] = chart.sha256

            entries[name].append(entry)

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
