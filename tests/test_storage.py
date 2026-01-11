"""Tests for storage manager."""

import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from chantal.core.config import StorageConfig
from chantal.core.storage import StorageManager
from chantal.db.models import Base, ContentItem, RepositoryFile
from chantal.plugins.rpm.models import RpmMetadata


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

    # Should use pool_type/2-level directory structure (default pool_type="content")
    assert pool_path.startswith("content/ab/cd/")
    assert pool_path.endswith(f"{sha256}_{filename}")

    # Check format
    parts = pool_path.split("/")
    assert len(parts) == 4
    assert parts[0] == "content"
    assert parts[1] == "ab"
    assert parts[2] == "cd"
    assert parts[3] == f"{sha256}_{filename}"


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
    rpm_metadata = RpmMetadata(release="1", arch="noarch")
    content_item = ContentItem(
        content_type="rpm",
        name="test",
        version="1.0",
        sha256=sha256,
        size_bytes=size,
        pool_path=pool_path,
        filename="test.txt",
        content_metadata=rpm_metadata.model_dump(exclude_none=False)
    )
    db_session.add(content_item)
    db_session.commit()

    # Should find no orphaned files
    orphaned = temp_storage.get_orphaned_files(db_session)
    assert len(orphaned) == 0

    # Remove from database
    db_session.delete(content_item)
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
    rpm_metadata = RpmMetadata(release="1", arch="noarch")
    content_item = ContentItem(
        content_type="rpm",
        name="test",
        version="1.0",
        sha256=sha256,
        size_bytes=size,
        pool_path=pool_path,
        filename="test.txt",
        content_metadata=rpm_metadata.model_dump(exclude_none=False)
    )
    db_session.add(content_item)
    db_session.commit()

    # Get statistics
    stats = temp_storage.get_pool_statistics(db_session)

    assert stats["total_packages_db"] == 1
    assert stats["total_size_db"] == size
    assert stats["total_files_pool"] == 1
    assert stats["total_size_pool"] == size
    assert stats["orphaned_files"] == 0
    assert stats["deduplication_savings"] == 0  # No savings with single file


# ============================================================================
# RepositoryFile Storage Tests
# ============================================================================

def test_add_repository_file(temp_storage, test_file):
    """Test adding repository file to storage pool."""
    sha256, pool_path, size = temp_storage.add_repository_file(
        test_file,
        "updateinfo.xml.gz"
    )

    # Verify SHA256 was calculated
    assert len(sha256) == 64
    assert pool_path.startswith("files/")  # In files/ subdirectory
    assert size == test_file.stat().st_size

    # Verify file was copied to pool
    pool_file = temp_storage.pool_path / pool_path
    assert pool_file.exists()
    assert pool_file.stat().st_size == size


def test_add_repository_file_deduplication(temp_storage, test_file):
    """Test that identical repository files are deduplicated."""
    # Add file first time
    sha256_1, pool_path_1, size_1 = temp_storage.add_repository_file(
        test_file,
        "updateinfo.xml.gz"
    )

    # Add same file again (different name)
    sha256_2, pool_path_2, size_2 = temp_storage.add_repository_file(
        test_file,
        "filelists.xml.gz"  # Different name
    )

    # SHA256 should be same (same content)
    assert sha256_1 == sha256_2

    # Pool paths will differ (different filename in path)
    assert pool_path_1 != pool_path_2

    # Both files should exist (different names, but same content)
    assert (temp_storage.pool_path / pool_path_1).exists()
    assert (temp_storage.pool_path / pool_path_2).exists()


def test_pool_subdirectories(temp_storage):
    """Test that pool has content/ and files/ subdirectories."""
    # Verify subdirectories were created
    assert temp_storage.content_pool.exists()
    assert temp_storage.file_pool.exists()
    assert temp_storage.content_pool == temp_storage.pool_path / "content"
    assert temp_storage.file_pool == temp_storage.pool_path / "files"


def test_get_pool_path_with_pool_type(temp_storage):
    """Test get_pool_path with pool_type parameter."""
    sha256 = "a" * 64
    filename = "test.rpm"

    # Test content pool (default)
    content_path = temp_storage.get_pool_path(sha256, filename)
    assert content_path == f"content/aa/aa/{sha256}_test.rpm"

    # Test files pool
    files_path = temp_storage.get_pool_path(sha256, filename, pool_type="files")
    assert files_path == f"files/aa/aa/{sha256}_test.rpm"


def test_get_orphaned_files_with_repository_files(temp_storage, test_file, db_session):
    """Test orphaned file detection includes both ContentItem and RepositoryFile."""
    # Add file to pool as repository file
    sha256, pool_path, _ = temp_storage.add_repository_file(test_file, "updateinfo.xml.gz")

    # Create RepositoryFile in database
    repo_file = RepositoryFile(
        file_category="metadata",
        file_type="updateinfo",
        sha256=sha256,
        pool_path=pool_path,
        size_bytes=test_file.stat().st_size,
        original_path="repodata/updateinfo.xml.gz"
    )
    db_session.add(repo_file)
    db_session.commit()

    # Check for orphans - should be empty (file is referenced)
    orphaned = temp_storage.get_orphaned_files(db_session)
    assert len(orphaned) == 0

    # Delete from DB
    db_session.delete(repo_file)
    db_session.commit()

    # Now should be orphaned
    orphaned = temp_storage.get_orphaned_files(db_session)
    assert len(orphaned) == 1
    assert orphaned[0] == temp_storage.pool_path / pool_path


def test_cleanup_orphaned_files_preserves_repository_files(temp_storage, test_file, db_session):
    """Test that cleanup preserves repository files referenced in database."""
    # Add file as repository file
    sha256, pool_path, size = temp_storage.add_repository_file(test_file, "vmlinuz")

    # Create RepositoryFile in database
    repo_file = RepositoryFile(
        file_category="kickstart",
        file_type="vmlinuz",
        sha256=sha256,
        pool_path=pool_path,
        size_bytes=size,
        original_path="images/pxeboot/vmlinuz"
    )
    db_session.add(repo_file)
    db_session.commit()

    # Run cleanup
    files_removed, bytes_freed = temp_storage.cleanup_orphaned_files(
        db_session,
        dry_run=False
    )

    # Nothing should be removed (file is referenced)
    assert files_removed == 0
    assert bytes_freed == 0

    # File should still exist
    assert (temp_storage.pool_path / pool_path).exists()


def test_mixed_content_and_files_cleanup(temp_storage, db_session):
    """Test cleanup with both ContentItem and RepositoryFile."""
    # Create two different test files with different content
    import tempfile

    # File 1: Package file
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".rpm") as f:
        f.write("This is a package file.\n")
        pkg_file = Path(f.name)

    # File 2: Metadata file (different content = different SHA256)
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as f:
        f.write("This is a metadata file with different content.\n")
        meta_file = Path(f.name)

    try:
        # Add as package (content)
        rpm_metadata = RpmMetadata(release="1", arch="x86_64")
        sha256_pkg, pool_path_pkg, size_pkg = temp_storage.add_package(pkg_file, "test.rpm")

        content_item = ContentItem(
            content_type="rpm",
            name="test-package",
            version="1.0",
            sha256=sha256_pkg,
            size_bytes=size_pkg,
            pool_path=pool_path_pkg,
            filename="test.rpm",
            content_metadata=rpm_metadata.model_dump(exclude_none=False)
        )
        db_session.add(content_item)

        # Add as repository file
        sha256_file, pool_path_file, size_file = temp_storage.add_repository_file(
            meta_file,
            "updateinfo.xml.gz"
        )

        repo_file = RepositoryFile(
            file_category="metadata",
            file_type="updateinfo",
            sha256=sha256_file,
            pool_path=pool_path_file,
            size_bytes=size_file,
            original_path="repodata/updateinfo.xml.gz"
        )
        db_session.add(repo_file)
        db_session.commit()

        # SHA256s should be different (different content)
        assert sha256_pkg != sha256_file

        # Both should be preserved
        orphaned = temp_storage.get_orphaned_files(db_session)
        assert len(orphaned) == 0

        # Delete package from DB (but keep file)
        db_session.delete(content_item)
        db_session.commit()

        # Package file should be orphaned, but not metadata file
        orphaned = temp_storage.get_orphaned_files(db_session)
        assert len(orphaned) == 1
        assert orphaned[0] == temp_storage.pool_path / pool_path_pkg

        # Metadata file should still be there
        assert (temp_storage.pool_path / pool_path_file).exists()
    finally:
        # Cleanup temp files
        pkg_file.unlink()
        meta_file.unlink()
