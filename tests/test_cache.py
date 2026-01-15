"""Tests for metadata cache."""

import hashlib
import tempfile
import time
from pathlib import Path

import pytest

from chantal.core.cache import CacheStats, MetadataCache


@pytest.fixture
def temp_cache_dir():
    """Create temporary cache directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def cache(temp_cache_dir):
    """Create MetadataCache instance with temp directory."""
    return MetadataCache(
        cache_path=temp_cache_dir,
        max_age_hours=None,  # No TTL for most tests
        enabled=True,
    )


def test_cache_initialization(temp_cache_dir):
    """Test cache initialization creates directory."""
    cache = MetadataCache(cache_path=temp_cache_dir, enabled=True)
    assert cache.enabled is True
    assert cache.cache_path == temp_cache_dir
    assert temp_cache_dir.exists()


def test_cache_disabled():
    """Test cache disabled when cache_path is None."""
    cache = MetadataCache(cache_path=None, enabled=False)
    assert cache.enabled is False

    # get() should return None when disabled
    result = cache.get("abc123", "primary")
    assert result is None


def test_cache_put_and_get(cache):
    """Test storing and retrieving from cache."""
    # Create test content
    content = b"This is test metadata content"
    checksum = hashlib.sha256(content).hexdigest()

    # Store in cache
    cache_file = cache.put(checksum, content, "primary")
    assert cache_file.exists()
    assert cache_file.name == f"{checksum}.xml.gz"

    # Retrieve from cache
    retrieved_file = cache.get(checksum, "primary")
    assert retrieved_file is not None
    assert retrieved_file == cache_file
    assert retrieved_file.read_bytes() == content


def test_cache_get_miss(cache):
    """Test cache miss returns None."""
    result = cache.get("nonexistent_checksum", "primary")
    assert result is None


def test_cache_put_checksum_mismatch(cache):
    """Test that put() validates checksum."""
    content = b"Test content"
    wrong_checksum = "abc123_wrong_checksum"

    with pytest.raises(ValueError, match="Checksum mismatch"):
        cache.put(wrong_checksum, content, "primary")


def test_cache_ttl_validation(temp_cache_dir):
    """Test TTL-based cache invalidation."""
    # Create cache with very short TTL (0.001 hours = ~3.6 seconds)
    cache = MetadataCache(cache_path=temp_cache_dir, max_age_hours=0.001, enabled=True)

    # Add file to cache
    content = b"Test content"
    checksum = hashlib.sha256(content).hexdigest()
    cache_file = cache.put(checksum, content, "primary")

    # Immediately, file should be valid
    assert cache.is_valid(cache_file) is True
    retrieved = cache.get(checksum, "primary")
    assert retrieved is not None

    # Wait for TTL to expire (4 seconds to be safe)
    time.sleep(4)

    # Now file should be invalid
    assert cache.is_valid(cache_file) is False

    # get() should return None for expired file
    retrieved = cache.get(checksum, "primary")
    assert retrieved is None

    # File should be deleted
    assert not cache_file.exists()


def test_cache_clear_all(cache, temp_cache_dir):
    """Test clearing entire cache."""
    # Add multiple files to cache
    files_added = []
    for i in range(5):
        content = f"Test content {i}".encode()
        checksum = hashlib.sha256(content).hexdigest()
        cache_file = cache.put(checksum, content, "primary")
        files_added.append(cache_file)

    # Verify files exist
    for f in files_added:
        assert f.exists()

    # Clear cache
    deleted_count = cache.clear()
    assert deleted_count == 5

    # Verify files are gone
    for f in files_added:
        assert not f.exists()


def test_cache_clear_pattern(cache):
    """Test clearing cache with pattern."""
    # Add files with different checksums
    content1 = b"Content 1"
    checksum1 = hashlib.sha256(content1).hexdigest()
    cache.put(checksum1, content1, "primary")

    content2 = b"Content 2"
    checksum2 = hashlib.sha256(content2).hexdigest()
    cache.put(checksum2, content2, "updateinfo")

    # Clear only files matching pattern
    pattern = f"{checksum1[:8]}*.xml.gz"
    deleted_count = cache.clear(pattern)

    # At least one file should match the pattern
    assert deleted_count >= 1


def test_cache_stats_empty(cache):
    """Test stats for empty cache."""
    stats = cache.stats()
    assert isinstance(stats, CacheStats)
    assert stats.total_files == 0
    assert stats.total_size_bytes == 0
    assert stats.oldest_file_age_hours is None
    assert stats.newest_file_age_hours is None


def test_cache_stats_with_files(cache):
    """Test stats with cached files."""
    # Add multiple files
    for i in range(3):
        content = f"Test content {i}".encode()
        checksum = hashlib.sha256(content).hexdigest()
        cache.put(checksum, content, f"metadata_{i}")

    stats = cache.stats()
    assert stats.total_files == 3
    assert stats.total_size_bytes > 0
    assert stats.oldest_file_age_hours is not None
    assert stats.newest_file_age_hours is not None
    assert stats.oldest_file_age_hours >= 0  # Very recent files


def test_cache_deduplication(cache):
    """Test that identical content is deduplicated."""
    content = b"Identical content"
    checksum = hashlib.sha256(content).hexdigest()

    # Store same content twice
    cache_file1 = cache.put(checksum, content, "primary")
    cache_file2 = cache.put(checksum, content, "primary")

    # Should be same file
    assert cache_file1 == cache_file2

    # Only one file should exist
    stats = cache.stats()
    assert stats.total_files == 1


def test_cache_disabled_operations(temp_cache_dir):
    """Test that operations work gracefully when cache is disabled."""
    cache = MetadataCache(cache_path=temp_cache_dir, enabled=False)

    # get() returns None
    assert cache.get("abc123", "primary") is None

    # put() returns dummy path
    content = b"Test"
    checksum = hashlib.sha256(content).hexdigest()
    result = cache.put(checksum, content, "primary")
    assert result == Path("/dev/null")

    # clear() returns 0
    assert cache.clear() == 0

    # stats() returns empty stats
    stats = cache.stats()
    assert stats.total_files == 0


def test_cache_atomic_write(cache, temp_cache_dir):
    """Test that cache writes are atomic (temp file + rename)."""
    content = b"Test atomic write"
    checksum = hashlib.sha256(content).hexdigest()

    # Check that no .tmp files are left behind after put()
    cache.put(checksum, content, "primary")

    tmp_files = list(temp_cache_dir.glob("*.tmp"))
    assert len(tmp_files) == 0  # No temp files left behind

    # Verify actual file exists
    cache_file = temp_cache_dir / f"{checksum}.xml.gz"
    assert cache_file.exists()
    assert cache_file.read_bytes() == content


def test_cache_multiple_file_types(cache):
    """Test caching different metadata file types."""
    file_types = ["primary", "updateinfo", "filelists", "other"]

    checksums = {}
    for file_type in file_types:
        content = f"Content for {file_type}".encode()
        checksum = hashlib.sha256(content).hexdigest()
        checksums[file_type] = checksum
        cache.put(checksum, content, file_type)

    # Verify all files can be retrieved
    for file_type, checksum in checksums.items():
        cached_file = cache.get(checksum, file_type)
        assert cached_file is not None

    # Stats should show 4 files
    stats = cache.stats()
    assert stats.total_files == 4
