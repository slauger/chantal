from __future__ import annotations

"""
Alpine APK repository publisher.

This module implements publishing for Alpine APK repositories.
"""

import logging
import os
import shutil
import tarfile
import tempfile
from pathlib import Path

from sqlalchemy.orm import Session

from chantal.core.config import RepositoryConfig
from chantal.core.storage import StorageManager
from chantal.db.models import ContentItem, Repository, RepositoryFile, Snapshot
from chantal.plugins.apk.models import ApkMetadata
from chantal.plugins.base import PublisherPlugin

logger = logging.getLogger(__name__)


class ApkPublisher(PublisherPlugin):
    """Publisher for Alpine APK repositories.

    Creates standard Alpine repository structure:
    - {branch}/{repository}/{architecture}/APKINDEX.tar.gz - Package metadata
    - {branch}/{repository}/{architecture}/*.apk - Package files (hardlinks to pool)
    """

    def __init__(self, storage: StorageManager):
        """Initialize APK publisher.

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
        """Publish APK repository to target directory.

        Args:
            session: Database session
            repository: Repository model instance
            config: Repository configuration
            target_path: Target directory for publishing
        """
        # Get packages
        packages = self._get_repository_packages(session, repository)

        # Publish packages and metadata
        self._publish_packages(packages, target_path, config, session, repository)

    def publish_snapshot(
        self,
        session: Session,
        snapshot: Snapshot,
        repository: Repository,
        config: RepositoryConfig,
        target_path: Path,
    ) -> None:
        """Publish APK snapshot to target directory.

        Args:
            session: Database session
            snapshot: Snapshot model instance
            repository: Repository model instance
            config: Repository configuration
            target_path: Target directory for publishing
        """
        # Get packages from snapshot
        packages = self._get_snapshot_packages(session, snapshot)

        # Publish packages and metadata
        # For snapshots, we use repository_files from the snapshot
        self._publish_packages(packages, target_path, config, session, repository, snapshot=snapshot)

    def unpublish(self, target_path: Path) -> None:
        """Remove published APK repository.

        Args:
            target_path: Target directory to unpublish
        """
        if target_path.exists():
            shutil.rmtree(target_path)

    def _publish_packages(
        self,
        packages: list[ContentItem],
        target_path: Path,
        config: RepositoryConfig,
        session: Session,
        repository: Repository,
        snapshot: Snapshot | None = None,
    ) -> None:
        """Publish packages and APKINDEX.tar.gz.

        Args:
            packages: List of ContentItem instances (type=apk)
            target_path: Target directory
            config: Repository configuration
            session: Database session
            repository: Repository model instance
            snapshot: Optional snapshot model instance (for snapshot publishing)
        """
        # Create directory structure: {branch}/{repository}/{architecture}/
        apk_config = config.apk
        if not apk_config:
            raise ValueError("APK configuration missing")

        arch_path = (
            target_path / apk_config.branch / apk_config.repository / apk_config.architecture
        )
        arch_path.mkdir(parents=True, exist_ok=True)

        # Hardlink package files to target directory
        for pkg in packages:
            pool_path = self.storage.get_absolute_pool_path(pkg.sha256, pkg.filename)
            target_file = arch_path / pkg.filename

            # Create hardlink
            if target_file.exists():
                target_file.unlink()
            os.link(pool_path, target_file)

        # Publish metadata files (APKINDEX.tar.gz) from RepositoryFile or generate
        self._publish_metadata_files(
            session, repository, arch_path, config, packages, snapshot=snapshot
        )

        logger.info(f"Published {len(packages)} packages to {arch_path}")

    def _publish_metadata_files(
        self,
        session: Session,
        repository: Repository,
        arch_path: Path,
        config: RepositoryConfig,
        packages: list[ContentItem],
        snapshot: Snapshot | None = None,
    ) -> None:
        """Publish APKINDEX.tar.gz from RepositoryFile or generate it.

        For mirror mode, this hardlinks the APKINDEX.tar.gz from pool.
        If not found, falls back to generating APKINDEX.tar.gz.

        Args:
            session: Database session
            repository: Repository model instance
            arch_path: Target directory for APKINDEX.tar.gz
            config: Repository configuration
            packages: List of packages (for fallback generation)
            snapshot: Optional snapshot model instance
        """
        # Build expected original_path for APKINDEX.tar.gz
        apk_config = config.apk
        if apk_config:
            expected_path = f"{apk_config.branch}/{apk_config.repository}/{apk_config.architecture}/APKINDEX.tar.gz"
        else:
            expected_path = "APKINDEX.tar.gz"

        # Find APKINDEX.tar.gz RepositoryFile
        apkindex_file = None

        if snapshot:
            # For snapshots, get repository_files from snapshot
            for repo_file in snapshot.repository_files:
                if repo_file.file_type == "apkindex" and repo_file.file_category == "metadata":
                    apkindex_file = repo_file
                    break
        else:
            # For repositories, get repository_files from repository
            for repo_file in repository.repository_files:
                if repo_file.file_type == "apkindex" and repo_file.file_category == "metadata":
                    apkindex_file = repo_file
                    break

        if apkindex_file:
            # Mirror mode: Hardlink APKINDEX.tar.gz from pool
            pool_path = self.storage.pool_root / apkindex_file.pool_path
            target_file = arch_path / "APKINDEX.tar.gz"

            if target_file.exists():
                target_file.unlink()

            os.link(pool_path, target_file)
            logger.info(f"Published APKINDEX.tar.gz from pool (mirror mode): {apkindex_file.sha256[:16]}...")
        else:
            # Fallback: Generate APKINDEX.tar.gz from packages
            logger.info("No APKINDEX.tar.gz in pool, generating from packages")
            self._generate_apkindex(packages, arch_path)

    def _generate_apkindex(
        self,
        packages: list[ContentItem],
        target_path: Path,
    ) -> None:
        """Generate APKINDEX.tar.gz file.

        Args:
            packages: List of ContentItem instances
            target_path: Target directory
        """
        # Build APKINDEX content
        index_lines = []

        for pkg in packages:
            metadata = ApkMetadata(**pkg.content_metadata)
            # Convert metadata to APKINDEX entry format
            entry = metadata.to_apkindex_entry()
            index_lines.append(entry)

        # Join with blank lines between entries
        index_content = "\n\n".join(index_lines) + "\n"

        # Create tar.gz archive with APKINDEX
        index_path = target_path / "APKINDEX.tar.gz"

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as tmp:
            tmp.write(index_content)
            tmp_path = tmp.name

        try:
            with tarfile.open(index_path, "w:gz") as tar:
                tar.add(tmp_path, arcname="APKINDEX")
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        logger.debug(f"Generated APKINDEX.tar.gz with {len(packages)} packages")

    def _get_repository_packages(
        self, session: Session, repository: Repository
    ) -> list[ContentItem]:
        """Get all APK packages from repository.

        Args:
            session: Database session
            repository: Repository model instance

        Returns:
            list: ContentItem instances (type=apk)
        """
        return [item for item in repository.content_items if item.content_type == "apk"]

    def _get_snapshot_packages(self, session: Session, snapshot: Snapshot) -> list[ContentItem]:
        """Get all APK packages from snapshot.

        Args:
            session: Database session
            snapshot: Snapshot model instance

        Returns:
            list: ContentItem instances (type=apk)
        """
        return [item for item in snapshot.content_items if item.content_type == "apk"]
