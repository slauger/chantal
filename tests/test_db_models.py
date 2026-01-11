"""Tests for database models."""

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from chantal.db.models import Base, ContentItem, Repository, RepositoryFile, Snapshot, SyncHistory
from chantal.plugins.rpm.models import RpmMetadata


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)

    session = Session(engine)
    yield session

    session.close()


def test_create_repository(db_session):
    """Test creating a repository."""
    repo = Repository(
        repo_id="rhel9-baseos",
        name="RHEL 9 BaseOS",
        type="rpm",
        feed="https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os",
        enabled=True,
    )

    db_session.add(repo)
    db_session.commit()

    # Query back
    found = db_session.query(Repository).filter_by(repo_id="rhel9-baseos").first()
    assert found is not None
    assert found.name == "RHEL 9 BaseOS"
    assert found.type == "rpm"
    assert found.enabled is True


def test_create_package(db_session):
    """Test creating a content item (RPM package)."""
    rpm_metadata = RpmMetadata(
        release="10.el9",
        arch="x86_64",
        epoch=None,
        summary="High performance web server",
        description="Nginx is a web server with a focus on high concurrency.",
    )

    content_item = ContentItem(
        content_type="rpm",
        name="nginx",
        version="1.20.1",
        sha256="abc123def456" * 4,  # 64 chars
        size_bytes=1258496,
        pool_path="ab/c1/abc123def456_nginx-1.20.1-10.el9.x86_64.rpm",
        filename="nginx-1.20.1-10.el9.x86_64.rpm",
        content_metadata=rpm_metadata.model_dump(exclude_none=False),
    )

    db_session.add(content_item)
    db_session.commit()

    # Query back
    found = db_session.query(ContentItem).filter_by(name="nginx").first()
    assert found is not None
    assert found.version == "1.20.1"
    assert found.content_metadata["arch"] == "x86_64"
    assert found.nevra == "nginx-1.20.1-10.el9.x86_64"


def test_package_nevra_with_epoch(db_session):
    """Test NEVRA string generation with epoch."""
    rpm_metadata = RpmMetadata(release="1.el9", arch="x86_64", epoch="2")

    content_item = ContentItem(
        content_type="rpm",
        name="test-package",
        version="1.0",
        sha256="def456abc123" * 4,
        size_bytes=1000,
        pool_path="de/f4/def456_test.rpm",
        filename="test-package-1.0-1.el9.x86_64.rpm",
        content_metadata=rpm_metadata.model_dump(exclude_none=False),
    )

    assert content_item.nevra == "test-package-2:1.0-1.el9.x86_64"


def test_create_snapshot(db_session):
    """Test creating a snapshot."""
    # Create repository first
    repo = Repository(
        repo_id="test-repo",
        name="Test Repo",
        type="rpm",
        feed="https://example.com/repo",
        enabled=True,
    )
    db_session.add(repo)
    db_session.commit()

    # Create snapshot
    snapshot = Snapshot(
        repository_id=repo.id,
        name="test-repo-20250109",
        description="Test snapshot",
        package_count=100,
        total_size_bytes=1024 * 1024 * 100,  # 100 MB
    )

    db_session.add(snapshot)
    db_session.commit()

    # Query back
    found = db_session.query(Snapshot).filter_by(name="test-repo-20250109").first()
    assert found is not None
    assert found.repository_id == repo.id
    assert found.package_count == 100


def test_snapshot_package_relationship(db_session):
    """Test many-to-many relationship between snapshots and packages."""
    # Create repository
    repo = Repository(
        repo_id="test-repo",
        name="Test Repo",
        type="rpm",
        feed="https://example.com/repo",
        enabled=True,
    )
    db_session.add(repo)
    db_session.commit()

    # Create content items
    rpm_metadata1 = RpmMetadata(release="1", arch="x86_64")
    pkg1 = ContentItem(
        content_type="rpm",
        name="package1",
        version="1.0",
        sha256="a" * 64,
        size_bytes=1000,
        pool_path="aa/aa/aaa_pkg1.rpm",
        filename="package1-1.0.x86_64.rpm",
        content_metadata=rpm_metadata1.model_dump(exclude_none=False),
    )

    rpm_metadata2 = RpmMetadata(release="1", arch="x86_64")
    pkg2 = ContentItem(
        content_type="rpm",
        name="package2",
        version="2.0",
        sha256="b" * 64,
        size_bytes=2000,
        pool_path="bb/bb/bbb_pkg2.rpm",
        filename="package2-2.0.x86_64.rpm",
        content_metadata=rpm_metadata2.model_dump(exclude_none=False),
    )

    db_session.add_all([pkg1, pkg2])
    db_session.commit()

    # Create snapshot and associate content items
    snapshot = Snapshot(
        repository_id=repo.id, name="snapshot-1", package_count=2, total_size_bytes=3000
    )
    snapshot.content_items.append(pkg1)
    snapshot.content_items.append(pkg2)

    db_session.add(snapshot)
    db_session.commit()

    # Verify relationships
    found_snapshot = db_session.query(Snapshot).filter_by(name="snapshot-1").first()
    assert len(found_snapshot.content_items) == 2
    assert pkg1 in found_snapshot.content_items
    assert pkg2 in found_snapshot.content_items

    # Verify reverse relationship
    assert found_snapshot in pkg1.snapshots
    assert found_snapshot in pkg2.snapshots


def test_sync_history(db_session):
    """Test sync history tracking."""
    # Create repository
    repo = Repository(
        repo_id="test-repo",
        name="Test Repo",
        type="rpm",
        feed="https://example.com/repo",
        enabled=True,
    )
    db_session.add(repo)
    db_session.commit()

    # Create sync history
    sync = SyncHistory(
        repository_id=repo.id,
        started_at=datetime(2025, 1, 9, 14, 0, 0),
        completed_at=datetime(2025, 1, 9, 14, 5, 23),
        status="success",
        packages_added=47,
        packages_removed=2,
        packages_updated=5,
        bytes_downloaded=450 * 1024 * 1024,  # 450 MB
    )

    db_session.add(sync)
    db_session.commit()

    # Query back
    found = db_session.query(SyncHistory).filter_by(repository_id=repo.id).first()
    assert found is not None
    assert found.status == "success"
    assert found.packages_added == 47
    assert found.duration_seconds == 323.0  # 5 minutes 23 seconds


def test_unique_constraints(db_session):
    """Test unique constraints."""
    # Repository repo_id must be unique
    repo1 = Repository(
        repo_id="test-repo",
        name="Test Repo 1",
        type="rpm",
        feed="https://example.com/repo1",
        enabled=True,
    )
    db_session.add(repo1)
    db_session.commit()

    # Try to create duplicate repo_id
    repo2 = Repository(
        repo_id="test-repo",  # Same repo_id
        name="Test Repo 2",
        type="rpm",
        feed="https://example.com/repo2",
        enabled=True,
    )
    db_session.add(repo2)

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()

    # ContentItem SHA256 must be unique
    rpm_metadata1 = RpmMetadata(release="1", arch="x86_64")
    item1 = ContentItem(
        content_type="rpm",
        name="package1",
        version="1.0",
        sha256="c" * 64,
        size_bytes=1000,
        pool_path="cc/cc/ccc_pkg1.rpm",
        filename="package1-1.0.x86_64.rpm",
        content_metadata=rpm_metadata1.model_dump(exclude_none=False),
    )
    db_session.add(item1)
    db_session.commit()

    # Try to create duplicate SHA256
    rpm_metadata2 = RpmMetadata(release="1", arch="x86_64")
    item2 = ContentItem(
        content_type="rpm",
        name="package2",
        version="2.0",
        sha256="c" * 64,  # Same SHA256
        size_bytes=2000,
        pool_path="cc/cc/ccc_pkg2.rpm",
        filename="package2-2.0.x86_64.rpm",
        content_metadata=rpm_metadata2.model_dump(exclude_none=False),
    )
    db_session.add(item2)

    with pytest.raises(IntegrityError):
        db_session.commit()


# ============================================================================
# RepositoryFile Tests
# ============================================================================


def test_create_repository_file(db_session):
    """Test creating a repository file (metadata/installer)."""
    repo_file = RepositoryFile(
        file_category="metadata",
        file_type="updateinfo",
        sha256="abc123def456" * 4,  # 64 chars
        pool_path="files/ab/c1/abc123def456_updateinfo.xml.gz",
        size_bytes=524288,
        original_path="repodata/abc123-updateinfo.xml.gz",
        file_metadata={
            "checksum_type": "sha256",
            "open_checksum": "xyz789abc456" * 4,
            "timestamp": 1704844800,
        },
    )

    db_session.add(repo_file)
    db_session.commit()

    # Query back
    found = db_session.query(RepositoryFile).filter_by(file_type="updateinfo").first()
    assert found is not None
    assert found.file_category == "metadata"
    assert found.size_bytes == 524288
    assert found.file_metadata["checksum_type"] == "sha256"
    assert found.original_path == "repodata/abc123-updateinfo.xml.gz"


def test_repository_to_repository_file_relationship(db_session):
    """Test many-to-many relationship between Repository and RepositoryFile."""
    # Create repository
    repo = Repository(
        repo_id="rhel9-baseos",
        name="RHEL 9 BaseOS",
        type="rpm",
        feed="https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os",
        enabled=True,
    )
    db_session.add(repo)

    # Create repository file
    repo_file = RepositoryFile(
        file_category="metadata",
        file_type="updateinfo",
        sha256="abc123" * 8,
        pool_path="files/ab/c1/abc123_updateinfo.xml.gz",
        size_bytes=100000,
        original_path="repodata/updateinfo.xml.gz",
    )
    db_session.add(repo_file)

    # Link repository to file
    repo.repository_files.append(repo_file)
    db_session.commit()

    # Verify relationship from repository side
    found_repo = db_session.query(Repository).filter_by(repo_id="rhel9-baseos").first()
    assert len(found_repo.repository_files) == 1
    assert found_repo.repository_files[0].file_type == "updateinfo"

    # Verify relationship from file side
    found_file = db_session.query(RepositoryFile).first()
    assert len(found_file.repositories) == 1
    assert found_file.repositories[0].repo_id == "rhel9-baseos"


def test_snapshot_to_repository_file_relationship(db_session):
    """Test many-to-many relationship between Snapshot and RepositoryFile."""
    # Create repository
    repo = Repository(
        repo_id="rhel9-baseos",
        name="RHEL 9 BaseOS",
        type="rpm",
        feed="https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os",
    )
    db_session.add(repo)
    db_session.commit()

    # Create snapshot
    snapshot = Snapshot(
        repository_id=repo.id,
        name="snapshot-2025-01-11",
        description="Test snapshot",
        package_count=0,
        total_size_bytes=0,
    )
    db_session.add(snapshot)

    # Create repository file
    repo_file = RepositoryFile(
        file_category="metadata",
        file_type="updateinfo",
        sha256="def456" * 8,
        pool_path="files/de/f4/def456_updateinfo.xml.gz",
        size_bytes=200000,
        original_path="repodata/def456-updateinfo.xml.gz",
    )
    db_session.add(repo_file)

    # Link snapshot to file
    snapshot.repository_files.append(repo_file)
    db_session.commit()

    # Verify relationship from snapshot side
    found_snapshot = db_session.query(Snapshot).first()
    assert len(found_snapshot.repository_files) == 1
    assert found_snapshot.repository_files[0].file_type == "updateinfo"

    # Verify relationship from file side
    found_file = db_session.query(RepositoryFile).first()
    assert len(found_file.snapshots) == 1
    assert found_file.snapshots[0].name == "snapshot-2025-01-11"


def test_repository_file_deduplication(db_session):
    """Test that RepositoryFile uses SHA256 for deduplication."""
    # Create two repositories
    repo1 = Repository(
        repo_id="rhel9-baseos",
        name="RHEL 9 BaseOS",
        type="rpm",
        feed="https://example.com/rhel9/baseos",
    )
    repo2 = Repository(
        repo_id="rhel9-appstream",
        name="RHEL 9 AppStream",
        type="rpm",
        feed="https://example.com/rhel9/appstream",
    )
    db_session.add_all([repo1, repo2])

    # Create one RepositoryFile (e.g., vmlinuz that's identical in both repos)
    repo_file = RepositoryFile(
        file_category="kickstart",
        file_type="vmlinuz",
        sha256="fedcba98" * 8,  # Same kernel
        pool_path="files/fe/dc/fedcba98_vmlinuz",
        size_bytes=10485760,  # 10MB
        original_path="images/pxeboot/vmlinuz",
    )
    db_session.add(repo_file)

    # Link to both repositories
    repo1.repository_files.append(repo_file)
    repo2.repository_files.append(repo_file)
    db_session.commit()

    # Verify only one RepositoryFile record exists
    count = db_session.query(RepositoryFile).count()
    assert count == 1

    # Verify both repos reference it
    found_file = db_session.query(RepositoryFile).first()
    assert len(found_file.repositories) == 2
    repo_ids = [r.repo_id for r in found_file.repositories]
    assert "rhel9-baseos" in repo_ids
    assert "rhel9-appstream" in repo_ids


def test_snapshot_preserves_old_metadata(db_session):
    """Test that snapshots preserve historical metadata versions."""
    # Create repository
    repo = Repository(
        repo_id="rhel9-baseos",
        name="RHEL 9 BaseOS",
        type="rpm",
        feed="https://example.com/rhel9/baseos",
    )
    db_session.add(repo)
    db_session.commit()

    # Create old metadata file
    old_metadata = RepositoryFile(
        file_category="metadata",
        file_type="updateinfo",
        sha256="old123abc" * 8,
        pool_path="files/ol/d1/old123abc_updateinfo.xml.gz",
        size_bytes=100000,
        original_path="repodata/old123-updateinfo.xml.gz",
    )
    db_session.add(old_metadata)

    # Link to repo and create snapshot
    repo.repository_files.append(old_metadata)
    snapshot1 = Snapshot(
        repository_id=repo.id, name="snapshot-2025-01-10", package_count=0, total_size_bytes=0
    )
    snapshot1.repository_files.append(old_metadata)
    db_session.add(snapshot1)
    db_session.commit()

    # Simulate repo sync with new metadata (different SHA256)
    new_metadata = RepositoryFile(
        file_category="metadata",
        file_type="updateinfo",
        sha256="new456def" * 8,  # NEW SHA256
        pool_path="files/ne/w4/new456def_updateinfo.xml.gz",
        size_bytes=150000,
        original_path="repodata/new456-updateinfo.xml.gz",  # Same path, new file
    )
    db_session.add(new_metadata)

    # Remove old metadata from repo, add new
    repo.repository_files.remove(old_metadata)
    repo.repository_files.append(new_metadata)

    # Create new snapshot
    snapshot2 = Snapshot(
        repository_id=repo.id, name="snapshot-2025-01-11", package_count=0, total_size_bytes=0
    )
    snapshot2.repository_files.append(new_metadata)
    db_session.add(snapshot2)
    db_session.commit()

    # Verify: old snapshot still has old metadata
    found_snap1 = db_session.query(Snapshot).filter_by(name="snapshot-2025-01-10").first()
    assert len(found_snap1.repository_files) == 1
    assert found_snap1.repository_files[0].sha256 == "old123abc" * 8

    # Verify: new snapshot has new metadata
    found_snap2 = db_session.query(Snapshot).filter_by(name="snapshot-2025-01-11").first()
    assert len(found_snap2.repository_files) == 1
    assert found_snap2.repository_files[0].sha256 == "new456def" * 8

    # Verify: both RepositoryFile records still exist in DB
    assert db_session.query(RepositoryFile).count() == 2

    # Verify: repo only has new metadata
    found_repo = db_session.query(Repository).first()
    assert len(found_repo.repository_files) == 1
    assert found_repo.repository_files[0].sha256 == "new456def" * 8


def test_repository_file_repr(db_session):
    """Test RepositoryFile __repr__ method."""
    repo_file = RepositoryFile(
        file_category="kickstart",
        file_type="vmlinuz",
        sha256="test1234" * 8,
        pool_path="files/te/st/test1234_vmlinuz",
        size_bytes=10000,
        original_path="images/pxeboot/vmlinuz",
    )

    repr_str = repr(repo_file)
    assert "RepositoryFile" in repr_str
    assert "kickstart" in repr_str
    assert "vmlinuz" in repr_str
    assert "images/pxeboot/vmlinuz" in repr_str
    assert "test1234" in repr_str  # First 8 chars of SHA256
