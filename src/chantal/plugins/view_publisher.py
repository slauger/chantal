from __future__ import annotations

"""
View publisher plugin for Chantal.

This module implements publishing for views - virtual repositories that combine
multiple repositories into a single published repository.
"""

from pathlib import Path

from sqlalchemy.orm import Session

from chantal.core.storage import StorageManager
from chantal.db.models import ContentItem, Repository, View, ViewSnapshot
from chantal.plugins.rpm.publisher import RpmPublisher


class ViewPublisher(RpmPublisher):
    """Publisher for Views (multi-repository virtual repositories).

    Views combine multiple repositories into a single virtual repository.
    All packages from all repositories are included (NO deduplication).
    The client (yum/dnf) decides which package version to use in case of conflicts.
    """

    def __init__(self, storage: StorageManager):
        """Initialize view publisher.

        Args:
            storage: Storage manager instance
        """
        super().__init__(storage)

    def publish_view_from_config(
        self,
        session: Session,
        repo_ids: list[str],
        target_path: Path,
    ) -> int:
        """Publish view directly from config (no DB view object needed).

        This allows publishing views directly from the configuration file
        without requiring them to be synced to the database first.

        Args:
            session: Database session
            repo_ids: List of repository IDs to include in view
            target_path: Target directory for publishing

        Returns:
            Number of packages published

        Raises:
            ValueError: If any repository is not found in database
        """
        # Get all repositories from database
        repositories = []
        for repo_id in repo_ids:
            repo = session.query(Repository).filter_by(repo_id=repo_id).first()
            if not repo:
                raise ValueError(f"Repository '{repo_id}' not found in database")
            repositories.append(repo)

        # Get all packages from all repositories
        packages = self._get_packages_from_repositories(session, repositories)

        # Publish packages and metadata (reuses RpmPublisher logic)
        self._publish_packages(packages, target_path)

        return len(packages)

    def publish_view(
        self,
        session: Session,
        view: View,
        target_path: Path,
    ) -> None:
        """Publish view to target directory (combines latest from all repos).

        Args:
            session: Database session
            view: View model instance
            target_path: Target directory for publishing
        """
        # Get all packages from all repositories in view
        packages = self._get_view_packages(session, view)

        # Publish packages and metadata (reuses RpmPublisher logic)
        self._publish_packages(packages, target_path)

    def publish_view_snapshot(
        self,
        session: Session,
        view_snapshot: ViewSnapshot,
        target_path: Path,
    ) -> None:
        """Publish view snapshot to target directory (combines specific snapshots).

        Args:
            session: Database session
            view_snapshot: ViewSnapshot model instance
            target_path: Target directory for publishing
        """
        # Get all packages from all snapshots in view snapshot
        packages = self._get_view_snapshot_packages(session, view_snapshot)

        # Publish packages and metadata (reuses RpmPublisher logic)
        self._publish_packages(packages, target_path)

    def _get_packages_from_repositories(
        self, session: Session, repositories: list[Repository]
    ) -> list[ContentItem]:
        """Get all content items from a list of repositories.

        IMPORTANT: NO deduplication! All content items from all repos are included.
        If multiple repos have the same package (different versions), ALL are included.
        The client (yum/dnf) will decide which version to use based on repo priority.

        Args:
            session: Database session
            repositories: List of Repository instances

        Returns:
            List of ALL content items from ALL repositories
        """
        all_packages = []

        for repo in repositories:
            # Refresh to ensure we have latest content items
            session.refresh(repo)

            # Add ALL content items from this repository
            all_packages.extend(repo.content_items)

        return all_packages

    def _get_view_packages(self, session: Session, view: View) -> list[ContentItem]:
        """Get all content items from all repositories in view.

        IMPORTANT: NO deduplication! All content items from all repos are included.
        If multiple repos have the same package (different versions), ALL are included.
        The client (yum/dnf) will decide which version to use based on repo priority.

        Args:
            session: Database session
            view: View instance

        Returns:
            List of ALL content items from ALL repositories in view
        """
        # Refresh view to get latest relationships
        session.refresh(view)

        # Get repositories from view in order
        repositories = [
            vr.repository for vr in sorted(view.view_repositories, key=lambda vr: vr.order)
        ]

        # Reuse the helper method
        return self._get_packages_from_repositories(session, repositories)

    def _get_view_snapshot_packages(
        self, session: Session, view_snapshot: ViewSnapshot
    ) -> list[ContentItem]:
        """Get all content items from all snapshots in a view snapshot.

        Args:
            session: Database session
            view_snapshot: ViewSnapshot instance

        Returns:
            List of ALL content items from ALL snapshots in view snapshot
        """
        from chantal.db.models import Snapshot

        all_packages = []

        # Get all snapshot IDs from view snapshot
        for snapshot_id in view_snapshot.snapshot_ids:
            snapshot = session.query(Snapshot).filter_by(id=snapshot_id).first()
            if snapshot:
                # Add all content items from this snapshot
                all_packages.extend(snapshot.content_items)

        return all_packages
