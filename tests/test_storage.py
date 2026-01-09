"""Tests for storage manager."""

import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from chantal.core.config import StorageConfig
from chantal.core.storage import StorageManager
from chantal.db.models import Base, Package


@pytest.fixture
def temp_storage():
    """Create temporary storage for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        config = StorageConfig(
            base_path=str(tmpdir / "base"),
            pool_path=str(tmpdir / "pool"),
            published_path=str(tmpdir / "published"),
            temp_path=str(tmpdir / "tmp"),
        )
        storage = StorageManager(config)
        storage.ensure_directories()
        yield storage


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)

    session = Session(engine)
    yield session

    session.close()


@pytest.fixture
def test_file():
    """Create a test file with known content."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
        f.write("This is a test file for SHA256 calculation.\n")
        f.write("It has some content to hash.\n")
        test_path = Path(f.name)

    yield test_path

    # Cleanup
    if test_path.exists():
        test_path.unlink()


def test_storage_manager_initialization(temp_storage):
    """Test storage manager initialization."""
    assert temp_storage.pool_path.exists()
    assert temp_storage.temp_path.exists()
    assert temp_storage.published_path.exists()


def test_calculate_sha256(temp_storage, test_file):
    """Test SHA256 calculation."""
    sha256 = temp_storage.calculate_sha256(test_file)

    # SHA256 should be 64 hex characters
    assert len(sha256) == 64
    assert all(c in "0123456789abcdef" for c in sha256)

    # Calculate again - should be same
    sha256_2 = temp_storage.calculate_sha256(test_file)
    assert sha256 == sha256_2


def test_get_pool_path(temp_storage):
    """Test pool path calculation."""
    sha256 = "abcdef1234567890" * 4  # 64 chars
    filename = "test-package.rpm"

    pool_path = temp_storage.get_pool_path(sha256, filename)

    # Should use 2-level directory structure
    assert pool_path.startswith("ab/cd/")
    assert pool_path.endswith(f"{sha256}_{filename}")

    # Check format
    parts = pool_path.split("/")
    assert len(parts) == 3
    assert parts[0] == "ab"
    assert parts[1] == "cd"
    assert parts[2] == f"{sha256}_{filename}"


def test_get_absolute_pool_path(temp_storage):
    """Test absolute pool path generation."""
    sha256 = "abc123" * 10 + "abcd"  # 64 chars
    filename = "package.rpm"

    abs_path = temp_storage.get_absolute_pool_path(sha256, filename)

    assert abs_path.is_absolute()
    assert str(temp_storage.pool_path) in str(abs_path)
    assert filename in str(abs_path)


def test_package_exists(temp_storage, test_file):
    """Test package existence check."""
    # Add package
    sha256, pool_path, size = temp_storage.add_package(
        test_file,
        "test.txt",
        verify_checksum=True
    )

    # Should exist now
    assert temp_storage.package_exists(sha256, "test.txt")

    # Non-existent package
    assert not temp_storage.package_exists("0" * 64, "nonexistent.rpm")


def test_add_package(temp_storage, test_file):
    """Test adding package to pool."""
    sha256, pool_path, size_bytes = temp_storage.add_package(
        test_file,
        "test.txt",
        verify_checksum=True
    )

    # Check return values
    assert len(sha256) == 64
    assert "test.txt" in pool_path
    assert size_bytes > 0

    # Check file exists in pool
    abs_pool_path = temp_storage.pool_path / pool_path
    assert abs_pool_path.exists()
    assert abs_pool_path.stat().st_size == size_bytes


def test_add_package_deduplication(temp_storage, test_file):
    """Test package deduplication."""
    # Add package first time
    sha256_1, pool_path_1, size_1 = temp_storage.add_package(
        test_file,
        "test.txt",
        verify_checksum=True
    )

    # Add same package again
    sha256_2, pool_path_2, size_2 = temp_storage.add_package(
        test_file,
        "test.txt",
        verify_checksum=True
    )

    # Should get same results
    assert sha256_1 == sha256_2
    assert pool_path_1 == pool_path_2
    assert size_1 == size_2

    # File should only exist once
    abs_pool_path = temp_storage.pool_path / pool_path_1
    assert abs_pool_path.exists()


def test_add_package_file_not_found(temp_storage):
    """Test adding non-existent package."""
    with pytest.raises(FileNotFoundError):
        temp_storage.add_package(
            Path("/non/existent/file.rpm"),
            "file.rpm"
        )


def test_create_hardlink(temp_storage, test_file):
    """Test hardlink creation."""
    # Add package to pool
    sha256, pool_path, size = temp_storage.add_package(
        test_file,
        "test.txt",
        verify_checksum=True
    )

    # Create hardlink
    target_path = temp_storage.published_path / "repos" / "test" / "test.txt"
    temp_storage.create_hardlink(sha256, "test.txt", target_path)

    # Check hardlink exists
    assert target_path.exists()
    assert target_path.stat().st_size == size

    # Check it's actually a hardlink (same inode)
    source_path = temp_storage.pool_path / pool_path
    assert source_path.stat().st_ino == target_path.stat().st_ino


def test_create_hardlink_creates_parent_dirs(temp_storage, test_file):
    """Test that create_hardlink creates parent directories."""
    # Add package to pool
    sha256, pool_path, size = temp_storage.add_package(
        test_file,
        "test.txt",
        verify_checksum=True
    )

    # Create hardlink in deep directory structure
    target_path = (
        temp_storage.published_path
        / "repos"
        / "test"
        / "subdir1"
        / "subdir2"
        / "test.txt"
    )

    temp_storage.create_hardlink(sha256, "test.txt", target_path)

    # Parent directories should be created
    assert target_path.parent.exists()
    assert target_path.exists()


def test_create_hardlink_overwrites_existing(temp_storage, test_file):
    """Test that create_hardlink overwrites existing file."""
    # Add package to pool
    sha256, pool_path, size = temp_storage.add_package(
        test_file,
        "test.txt",
        verify_checksum=True
    )

    target_path = temp_storage.published_path / "test.txt"

    # Create hardlink first time
    temp_storage.create_hardlink(sha256, "test.txt", target_path)
    assert target_path.exists()

    # Create hardlink again (should overwrite)
    temp_storage.create_hardlink(sha256, "test.txt", target_path)
    assert target_path.exists()


def test_get_orphaned_files(temp_storage, test_file, db_session):
    """Test finding orphaned files in pool."""
    # Add package to pool
    sha256, pool_path, size = temp_storage.add_package(
        test_file,
        "test.txt",
        verify_checksum=True
    )

    # Add to database
    package = Package(
        name="test",
        version="1.0",
        arch="noarch",
        sha256=sha256,
        size_bytes=size,
        pool_path=pool_path,
        package_type="rpm",
        filename="test.txt",
    )
    db_session.add(package)
    db_session.commit()

    # Should find no orphaned files
    orphaned = temp_storage.get_orphaned_files(db_session)
    assert len(orphaned) == 0

    # Remove from database
    db_session.delete(package)
    db_session.commit()

    # Should find orphaned file now
    orphaned = temp_storage.get_orphaned_files(db_session)
    assert len(orphaned) == 1
    assert orphaned[0].name.startswith(sha256)


def test_cleanup_orphaned_files_dry_run(temp_storage, test_file, db_session):
    """Test cleanup orphaned files in dry-run mode."""
    # Add package to pool (but not to database)
    sha256, pool_path, size = temp_storage.add_package(
        test_file,
        "test.txt",
        verify_checksum=True
    )

    # Run cleanup in dry-run mode
    files_removed, bytes_freed = temp_storage.cleanup_orphaned_files(
        db_session,
        dry_run=True
    )

    # Should report what would be removed
    assert files_removed == 1
    assert bytes_freed == size

    # File should still exist
    abs_pool_path = temp_storage.pool_path / pool_path
    assert abs_pool_path.exists()


def test_cleanup_orphaned_files_real(temp_storage, test_file, db_session):
    """Test cleanup orphaned files (actually delete)."""
    # Add package to pool (but not to database)
    sha256, pool_path, size = temp_storage.add_package(
        test_file,
        "test.txt",
        verify_checksum=True
    )

    # Run cleanup for real
    files_removed, bytes_freed = temp_storage.cleanup_orphaned_files(
        db_session,
        dry_run=False
    )

    # Should have removed file
    assert files_removed == 1
    assert bytes_freed == size

    # File should be gone
    abs_pool_path = temp_storage.pool_path / pool_path
    assert not abs_pool_path.exists()


def test_get_pool_statistics(temp_storage, test_file, db_session):
    """Test getting pool statistics."""
    # Add package
    sha256, pool_path, size = temp_storage.add_package(
        test_file,
        "test.txt",
        verify_checksum=True
    )

    # Add to database
    package = Package(
        name="test",
        version="1.0",
        arch="noarch",
        sha256=sha256,
        size_bytes=size,
        pool_path=pool_path,
        package_type="rpm",
        filename="test.txt",
    )
    db_session.add(package)
    db_session.commit()

    # Get statistics
    stats = temp_storage.get_pool_statistics(db_session)

    assert stats["total_packages_db"] == 1
    assert stats["total_size_db"] == size
    assert stats["total_files_pool"] == 1
    assert stats["total_size_pool"] == size
    assert stats["orphaned_files"] == 0
    assert stats["deduplication_savings"] == 0  # No savings with single file
