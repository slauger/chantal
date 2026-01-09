"""
Base publisher plugin interface for Chantal.

This module defines the abstract base class for repository publisher plugins.
Each repository type (RPM, APT, etc.) implements its own publisher.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List

from sqlalchemy.orm import Session

from chantal.core.config import RepositoryConfig
from chantal.core.storage import StorageManager
from chantal.db.models import Package, Repository, Snapshot


class PublisherPlugin(ABC):
    """Abstract base class for repository publishers.

    Each repository type (RPM, DEB, etc.) must implement this interface
    to handle publishing packages with the correct metadata format.
    """

    def __init__(self, storage: StorageManager):
        """Initialize publisher plugin.

        Args:
            storage: Storage manager instance
        """
        self.storage = storage

    @abstractmethod
    def publish_repository(
        self,
        session: Session,
        repository: Repository,
        config: RepositoryConfig,
        target_path: Path,
    ) -> None:
        """Publish repository to target directory.

        Creates hardlinks from pool to target directory and generates
        repository metadata specific to the repository type.

        Args:
            session: Database session
            repository: Repository model instance
            config: Repository configuration
            target_path: Target directory for publishing

        Raises:
            NotImplementedError: Must be implemented by subclass
        """
        raise NotImplementedError

    @abstractmethod
    def publish_snapshot(
        self,
        session: Session,
        snapshot: Snapshot,
        repository: Repository,
        config: RepositoryConfig,
        target_path: Path,
    ) -> None:
        """Publish snapshot to target directory.

        Similar to publish_repository but for a specific snapshot.

        Args:
            session: Database session
            snapshot: Snapshot model instance
            repository: Repository model instance
            config: Repository configuration
            target_path: Target directory for publishing

        Raises:
            NotImplementedError: Must be implemented by subclass
        """
        raise NotImplementedError

    @abstractmethod
    def unpublish(self, target_path: Path) -> None:
        """Remove published repository/snapshot.

        Args:
            target_path: Target directory to unpublish

        Raises:
            NotImplementedError: Must be implemented by subclass
        """
        raise NotImplementedError

    def _create_hardlinks(
        self,
        packages: List[Package],
        target_dir: Path,
        subdir: str = "Packages"
    ) -> None:
        """Helper: Create hardlinks for packages.

        Args:
            packages: List of packages to link
            target_dir: Target base directory
            subdir: Subdirectory for packages (default: "Packages")
        """
        packages_dir = target_dir / subdir
        packages_dir.mkdir(parents=True, exist_ok=True)

        for package in packages:
            target_path = packages_dir / package.filename
            self.storage.create_hardlink(
                package.sha256,
                package.filename,
                target_path
            )

    def _get_repository_packages(
        self,
        session: Session,
        repository: Repository
    ) -> List[Package]:
        """Helper: Get all packages for a repository.

        This is a simplified implementation. In reality, you'd query
        a repository_packages association table or the latest snapshot.

        Args:
            session: Database session
            repository: Repository instance

        Returns:
            List of packages in repository
        """
        # TODO: Implement proper repository-package relationship
        # For now, return empty list (will be populated during sync)
        return []

    def _get_snapshot_packages(
        self,
        session: Session,
        snapshot: Snapshot
    ) -> List[Package]:
        """Helper: Get all packages for a snapshot.

        Args:
            session: Database session
            snapshot: Snapshot instance

        Returns:
            List of packages in snapshot
        """
        return snapshot.packages
