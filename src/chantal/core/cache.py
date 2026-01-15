from __future__ import annotations

"""
Metadata cache manager for Chantal.

This module provides caching for repository metadata files (e.g., primary.xml.gz)
to avoid repeated downloads of large metadata files.
"""

import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class CacheStats:
    """Cache statistics."""

    total_files: int
    total_size_bytes: int
    oldest_file_age_hours: float | None
    newest_file_age_hours: float | None


class MetadataCache:
    """Manages metadata file caching with SHA256-based deduplication.

    Cache structure: {cache_path}/{checksum}.xml.gz
    - Files are stored by their SHA256 checksum for deduplication
    - Files are stored compressed (.xml.gz) to save space
    - Optional TTL-based invalidation via max_age_hours
    """

    def __init__(
        self,
        cache_path: Path | None,
        max_age_hours: int | None = None,
        enabled: bool = False,
    ):
        """Initialize metadata cache.

        Args:
            cache_path: Directory for cache storage (None = disabled)
            max_age_hours: Max age for cache entries (None = no TTL)
            enabled: Whether caching is enabled globally
        """
        self.cache_path = cache_path
        self.max_age_hours = max_age_hours
        self.enabled = enabled and cache_path is not None

        # Create cache directory if enabled
        if self.enabled and self.cache_path:
            self.cache_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Metadata cache enabled: {self.cache_path}")

    def get(self, checksum: str, file_type: str = "metadata") -> Path | None:
        """Get cached file by checksum.

        Args:
            checksum: SHA256 checksum of the file
            file_type: Type hint for logging (not used in lookup)

        Returns:
            Path to cached file, or None if not found/invalid
        """
        if not self.enabled or not self.cache_path:
            return None

        # Build cache file path
        cache_file = self.cache_path / f"{checksum}.xml.gz"

        if not cache_file.exists():
            logger.debug(f"Cache miss for {file_type}: {checksum[:16]}...")
            return None

        # Check TTL if configured
        if not self.is_valid(cache_file):
            logger.debug(f"Cache expired for {file_type}: {checksum[:16]}...")
            cache_file.unlink(missing_ok=True)
            return None

        logger.info(f"Cache hit for {file_type}: {checksum[:16]}...")
        return cache_file

    def put(self, checksum: str, content: bytes, file_type: str = "metadata") -> Path:
        """Store file in cache.

        Args:
            checksum: SHA256 checksum of the file
            content: File content (compressed .xml.gz)
            file_type: Type hint for logging

        Returns:
            Path to cached file

        Raises:
            IOError: If cache write fails
        """
        if not self.enabled or not self.cache_path:
            # Cache disabled, return dummy path
            return Path("/dev/null")

        cache_file = self.cache_path / f"{checksum}.xml.gz"

        # Verify checksum matches content
        actual_checksum = hashlib.sha256(content).hexdigest()
        if actual_checksum != checksum:
            logger.warning(
                f"Checksum mismatch: expected {checksum[:16]}..., got {actual_checksum[:16]}..."
            )
            raise ValueError(f"Checksum mismatch for {file_type}")

        # Write to cache (atomic via temp file + rename)
        temp_file = cache_file.with_suffix(".tmp")
        try:
            temp_file.write_bytes(content)
            temp_file.rename(cache_file)
            logger.info(
                f"Cached {file_type}: {checksum[:16]}... ({len(content) / 1024 / 1024:.2f} MB)"
            )
        finally:
            temp_file.unlink(missing_ok=True)

        return cache_file

    def is_valid(self, file_path: Path) -> bool:
        """Check if cached file is still valid (TTL check).

        Args:
            file_path: Path to cached file

        Returns:
            True if file is valid, False if expired
        """
        if not self.max_age_hours:
            return True  # No TTL configured

        # Get file modification time
        mtime = file_path.stat().st_mtime
        age_seconds = time.time() - mtime
        age_hours = age_seconds / 3600

        if age_hours > self.max_age_hours:
            logger.debug(f"Cache entry expired: {age_hours:.1f}h > {self.max_age_hours}h")
            return False

        return True

    def clear(self, pattern: str | None = None) -> int:
        """Clear cache entries.

        Args:
            pattern: Optional glob pattern to match files (e.g., "abc*.xml.gz")
                    If None, clears all cache entries

        Returns:
            Number of files deleted
        """
        if not self.enabled or not self.cache_path:
            return 0

        files_deleted = 0

        if pattern:
            # Delete matching files
            for cache_file in self.cache_path.glob(pattern):
                if cache_file.is_file():
                    cache_file.unlink()
                    files_deleted += 1
                    logger.debug(f"Deleted cache file: {cache_file.name}")
        else:
            # Delete all cache files
            for cache_file in self.cache_path.glob("*.xml.gz"):
                if cache_file.is_file():
                    cache_file.unlink()
                    files_deleted += 1

        logger.info(f"Cleared {files_deleted} cache file(s)")
        return files_deleted

    def stats(self) -> CacheStats:
        """Get cache statistics.

        Returns:
            CacheStats with cache information
        """
        if not self.enabled or not self.cache_path:
            return CacheStats(
                total_files=0,
                total_size_bytes=0,
                oldest_file_age_hours=None,
                newest_file_age_hours=None,
            )

        total_files = 0
        total_size_bytes = 0
        oldest_mtime: float | None = None
        newest_mtime: float | None = None

        for cache_file in self.cache_path.glob("*.xml.gz"):
            if not cache_file.is_file():
                continue

            total_files += 1
            total_size_bytes += cache_file.stat().st_size
            mtime = cache_file.stat().st_mtime

            if oldest_mtime is None or mtime < oldest_mtime:
                oldest_mtime = mtime
            if newest_mtime is None or mtime > newest_mtime:
                newest_mtime = mtime

        # Calculate ages
        now = time.time()
        oldest_age = (now - oldest_mtime) / 3600 if oldest_mtime else None
        newest_age = (now - newest_mtime) / 3600 if newest_mtime else None

        return CacheStats(
            total_files=total_files,
            total_size_bytes=total_size_bytes,
            oldest_file_age_hours=oldest_age,
            newest_file_age_hours=newest_age,
        )
