"""Tests for database models."""

import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from chantal.db.models import Base, Repository, ContentItem, Snapshot, SyncHistory
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
        enabled=True
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
        content_metadata=rpm_metadata.model_dump(exclude_none=False)
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
    rpm_metadata = RpmMetadata(
        release="1.el9",
        arch="x86_64",
        epoch="2"
    )

    content_item = ContentItem(
        content_type="rpm",
        name="test-package",
        version="1.0",
        sha256="def456abc123" * 4,
        size_bytes=1000,
        pool_path="de/f4/def456_test.rpm",
        filename="test-package-1.0-1.el9.x86_64.rpm",
        content_metadata=rpm_metadata.model_dump(exclude_none=False)
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
        enabled=True
    )
    db_session.add(repo)
    db_session.commit()

    # Create snapshot
    snapshot = Snapshot(
        repository_id=repo.id,
        name="test-repo-20250109",
        description="Test snapshot",
        package_count=100,
        total_size_bytes=1024 * 1024 * 100  # 100 MB
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
        enabled=True
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
        content_metadata=rpm_metadata1.model_dump(exclude_none=False)
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
        content_metadata=rpm_metadata2.model_dump(exclude_none=False)
    )

    db_session.add_all([pkg1, pkg2])
    db_session.commit()

    # Create snapshot and associate content items
    snapshot = Snapshot(
        repository_id=repo.id,
        name="snapshot-1",
        package_count=2,
        total_size_bytes=3000
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
        enabled=True
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
        bytes_downloaded=450 * 1024 * 1024  # 450 MB
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
        enabled=True
    )
    db_session.add(repo1)
    db_session.commit()

    # Try to create duplicate repo_id
    repo2 = Repository(
        repo_id="test-repo",  # Same repo_id
        name="Test Repo 2",
        type="rpm",
        feed="https://example.com/repo2",
        enabled=True
    )
    db_session.add(repo2)

    with pytest.raises(Exception):  # SQLAlchemy will raise IntegrityError
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
        content_metadata=rpm_metadata1.model_dump(exclude_none=False)
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
        content_metadata=rpm_metadata2.model_dump(exclude_none=False)
    )
    db_session.add(item2)

    with pytest.raises(Exception):  # SQLAlchemy will raise IntegrityError
        db_session.commit()
