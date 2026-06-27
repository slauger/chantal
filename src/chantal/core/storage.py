from __future__ import annotations

"""
Universal content-addressed storage manager for Chantal.

This module provides SHA256-based deduplication storage that works
for all package types (RPM, DEB, etc.).
"""

import errno
import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from chantal.core.config import StorageConfig
from chantal.db.models import ContentItem


class StorageManager:
    """Universal content-addressed storage manager.

    Uses SHA256 hashing for deduplication. All package types (RPM, DEB, etc.)
    are stored in a unified pool with a 2-level directory structure:

    pool/ab/cd/abc123...def456_filename.rpm

    This allows for efficient storage and instant deduplication.
    """

    def __init__(self, config: StorageConfig):
        """Initialize storage manager.

        Args:
            config: Storage configuration
        """
        self.config = config
        self.pool_path = config.get_pool_path()
        self.content_pool = self.pool_path / "content"  # ContentItem (packages)
        self.file_pool = self.pool_path / "files"  # RepositoryFile (metadata/installer)
        self.temp_path = config.get_temp_path()
        self.published_path = Path(config.published_path)

        # Ensure all storage directories exist
        self.ensure_directories()

    def calculate_sha256(self, file_path: Path) -> str:
        """Calculate SHA256 hash of a file.

        Args:
            file_path: Path to file

        Returns:
            Hex-encoded SHA256 hash
        """
        sha256_hash = hashlib.sha256()

        with open(file_path, "rb") as f:
            # Read in 64kb chunks for memory efficiency
            for chunk in iter(lambda: f.read(65536), b""):
                sha256_hash.update(chunk)

        return sha256_hash.hexdigest()

    def get_pool_path(self, sha256: str, filename: str, pool_type: str = "content") -> str:
        """Get relative pool path for a file.

        Uses 2-level directory structure for better filesystem performance:
        - Pool type subdirectory (content/ or files/)
        - First 2 chars of SHA256
        - Next 2 chars of SHA256
        - Full SHA256 + filename

        Example: content/ab/cd/abc123...def456_nginx-1.20.1.rpm
        Example: files/56/78/5678abc_updateinfo.xml.gz

        Args:
            sha256: SHA256 hash (64 hex chars)
            filename: Original filename
            pool_type: Pool type - "content" for packages, "files" for metadata/installer

        Returns:
            Relative pool path (e.g., "content/ab/cd/abc123_file.rpm")
        """
        level1 = sha256[:2]
        level2 = sha256[2:4]
        pool_filename = f"{sha256}_{filename}"

        return f"{pool_type}/{level1}/{level2}/{pool_filename}"

    def get_absolute_pool_path(
        self, sha256: str, filename: str, pool_type: str = "content"
    ) -> Path:
        """Get absolute pool path for a file.

        Args:
            sha256: SHA256 hash
            filename: Original filename
            pool_type: Pool type - "content" for packages, "files" for metadata/installer

        Returns:
            Absolute path in pool
        """
        relative_path = self.get_pool_path(sha256, filename, pool_type)
        return self.pool_path / relative_path

    def package_exists(self, sha256: str, filename: str) -> bool:
        """Check if package already exists in pool.

        Args:
            sha256: SHA256 hash
            filename: Original filename

        Returns:
            True if package exists in pool
        """
        pool_file = self.get_absolute_pool_path(sha256, filename)
        return pool_file.exists()

    def add_package(
        self, source_path: Path, filename: str, verify_checksum: bool = True
    ) -> tuple[str, str, int]:
        """Add package to content-addressed pool.

        If package with same SHA256 already exists, it won't be copied again
        (instant deduplication).

        Args:
            source_path: Path to source package file
            filename: Original filename (without path)
            verify_checksum: If True, verify SHA256 matches after copy

        Returns:
            Tuple of (sha256, pool_path, size_bytes)

        Raises:
            ValueError: If checksum verification fails
            FileNotFoundError: If source file doesn't exist
        """
        if not source_path.exists():
            raise FileNotFoundError(f"Source file not found: {source_path}")

        # Calculate SHA256
        sha256 = self.calculate_sha256(source_path)

        # Get pool path
        pool_path_rel = self.get_pool_path(sha256, filename)
        pool_path_abs = self.pool_path / pool_path_rel

        # Get file size
        size_bytes = source_path.stat().st_size

        # Check if already exists (deduplication)
        if pool_path_abs.exists():
            # Already in pool, verify checksum matches
            existing_sha256 = self.calculate_sha256(pool_path_abs)
            if existing_sha256 != sha256:
                raise ValueError(f"Pool file exists but checksum mismatch: {pool_path_abs}")
            return sha256, pool_path_rel, size_bytes

        # Copy into the pool atomically (temp file + rename), so a crash never
        # leaves a truncated blob at the canonical path that would then fail the
        # checksum on every later run.
        self._atomic_store(source_path, pool_path_abs, sha256, verify_checksum)

        return sha256, pool_path_rel, size_bytes

    def add_repository_file(
        self, source_path: Path, filename: str, verify_checksum: bool = True
    ) -> tuple[str, str, int]:
        """Add repository file (metadata/installer) to content-addressed pool.

        Similar to add_package() but stores files in pool/files/ subdirectory.
        If file with same SHA256 already exists, it won't be copied again
        (instant deduplication).

        Args:
            source_path: Path to source file
            filename: Original filename (without path)
            verify_checksum: If True, verify SHA256 matches after copy

        Returns:
            Tuple of (sha256, pool_path, size_bytes)

        Raises:
            ValueError: If checksum verification fails
            FileNotFoundError: If source file doesn't exist
        """
        if not source_path.exists():
            raise FileNotFoundError(f"Source file not found: {source_path}")

        # Calculate SHA256
        sha256 = self.calculate_sha256(source_path)

        # Get pool path (in files/ subdirectory)
        pool_path_rel = self.get_pool_path(sha256, filename, pool_type="files")
        pool_path_abs = self.pool_path / pool_path_rel

        # Get file size
        size_bytes = source_path.stat().st_size

        # Check if already exists (deduplication)
        if pool_path_abs.exists():
            # Already in pool, verify checksum matches
            existing_sha256 = self.calculate_sha256(pool_path_abs)
            if existing_sha256 != sha256:
                raise ValueError(f"Pool file exists but checksum mismatch: {pool_path_abs}")
            return sha256, pool_path_rel, size_bytes

        # Copy into the pool atomically (temp file + rename) - see add_package.
        self._atomic_store(source_path, pool_path_abs, sha256, verify_checksum)

        return sha256, pool_path_rel, size_bytes

    def _atomic_store(
        self, source_path: Path, pool_path_abs: Path, sha256: str, verify_checksum: bool
    ) -> None:
        """Copy ``source_path`` into the pool atomically.

        Writes to a temp file in the destination directory, verifies it, then
        ``os.replace``s it onto the canonical path. A crash or checksum failure
        therefore never leaves a partial/corrupt blob at the final path.
        """
        pool_path_abs.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=pool_path_abs.parent, suffix=".tmp")
        os.close(fd)
        tmp_path = Path(tmp_name)
        try:
            shutil.copy2(source_path, tmp_path)
            if verify_checksum:
                copied_sha256 = self.calculate_sha256(tmp_path)
                if copied_sha256 != sha256:
                    raise ValueError(
                        f"Checksum verification failed after copy: "
                        f"expected {sha256}, got {copied_sha256}"
                    )
            os.replace(tmp_path, pool_path_abs)
        finally:
            # No-op once the file has been renamed into place.
            tmp_path.unlink(missing_ok=True)

    def link_or_copy(self, source_path: Path, target_path: Path) -> None:
        """Hardlink ``source_path`` to ``target_path``, copying across filesystems.

        Publishing uses hardlinks (zero-copy) into the published tree, but the
        pool and the published tree are often on different filesystems, where
        ``os.link`` raises ``EXDEV``. Fall back to a copy in that case.
        """
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists():
            target_path.unlink()
        try:
            os.link(source_path, target_path)
        except OSError as e:
            if e.errno != errno.EXDEV:
                raise
            # Pool and target are on different filesystems: copy instead.
            shutil.copy2(source_path, target_path)

    def create_hardlink(self, sha256: str, filename: str, target_path: Path) -> None:
        """Create hardlink from pool to target location.

        This is used for publishing - creates zero-copy references to pool files
        (falling back to a copy across filesystems).

        Args:
            sha256: SHA256 hash of package
            filename: Original filename
            target_path: Target path for hardlink

        Raises:
            FileNotFoundError: If source file not in pool
        """
        source_path = self.get_absolute_pool_path(sha256, filename)

        if not source_path.exists():
            raise FileNotFoundError(f"Source file not in pool: {source_path}")

        self.link_or_copy(source_path, target_path)

    def get_orphaned_files(self, session: Session) -> list[Path]:
        """Find files in pool that are not referenced in database.

        Checks both ContentItem (packages) and RepositoryFile (metadata/installer)
        tables to find orphaned files in both pool subdirectories.

        Args:
            session: Database session

        Returns:
            List of orphaned file paths
        """
        from chantal.db.models import RepositoryFile

        orphaned = []

        # Get all SHA256s from BOTH tables
        content_sha256s = {item.sha256 for item in session.query(ContentItem.sha256).all()}
        file_sha256s = {item.sha256 for item in session.query(RepositoryFile.sha256).all()}
        db_sha256s = content_sha256s | file_sha256s  # Union

        # Scan pool directory (both content/ and files/ subdirectories)
        if self.pool_path.exists():
            for pool_file in self.pool_path.rglob("*"):
                if pool_file.is_file():
                    # Extract SHA256 from filename (format: sha256_filename)
                    filename = pool_file.name
                    if "_" in filename:
                        file_sha256 = filename.split("_", 1)[0]
                        if len(file_sha256) == 64 and file_sha256 not in db_sha256s:
                            orphaned.append(pool_file)

        return orphaned

    def cleanup_orphaned_files(self, session: Session, dry_run: bool = True) -> tuple[int, int]:
        """Remove files from pool that are not referenced in database.

        Args:
            session: Database session
            dry_run: If True, only report what would be deleted

        Returns:
            Tuple of (files_removed, bytes_freed)
        """
        orphaned_files = self.get_orphaned_files(session)

        files_removed = 0
        bytes_freed = 0

        for file_path in orphaned_files:
            file_size = file_path.stat().st_size

            if not dry_run:
                file_path.unlink()

            files_removed += 1
            bytes_freed += file_size

        return files_removed, bytes_freed

    def get_pool_statistics(self, session: Session) -> dict[str, Any]:
        """Get storage pool statistics.

        Args:
            session: Database session

        Returns:
            Dictionary with statistics
        """
        stats = {
            "pool_path": str(self.pool_path),
            "total_packages_db": 0,
            "total_size_db": 0,
            "total_files_pool": 0,
            "total_size_pool": 0,
            "orphaned_files": 0,
            "deduplication_savings": 0,
        }

        # Database statistics
        content_items = session.query(ContentItem).all()
        stats["total_packages_db"] = len(content_items)
        stats["total_size_db"] = sum(item.size_bytes for item in content_items)

        # Pool statistics
        if self.pool_path.exists():
            pool_files = list(self.pool_path.rglob("*"))
            pool_files = [f for f in pool_files if f.is_file()]
            stats["total_files_pool"] = len(pool_files)
            stats["total_size_pool"] = sum(f.stat().st_size for f in pool_files)

        # Orphaned files
        orphaned = self.get_orphaned_files(session)
        stats["orphaned_files"] = len(orphaned)

        # Deduplication savings
        # If we have more packages in DB than files in pool, we saved space
        total_files_pool: int = stats["total_files_pool"]  # type: ignore[assignment]
        if total_files_pool > 0:
            potential_size: int = stats["total_size_db"]  # type: ignore[assignment]
            actual_size: int = stats["total_size_pool"]  # type: ignore[assignment]
            stats["deduplication_savings"] = potential_size - actual_size

        return stats

    def ensure_directories(self) -> None:
        """Ensure all required storage directories exist."""
        self.pool_path.mkdir(parents=True, exist_ok=True)
        self.content_pool.mkdir(parents=True, exist_ok=True)  # pool/content/
        self.file_pool.mkdir(parents=True, exist_ok=True)  # pool/files/
        self.temp_path.mkdir(parents=True, exist_ok=True)
        self.published_path.mkdir(parents=True, exist_ok=True)
