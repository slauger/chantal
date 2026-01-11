"""Tests for Views functionality."""

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from chantal.db.models import (
    Base,
    ContentItem,
    Repository,
    Snapshot,
    View,
    ViewRepository,
    ViewSnapshot,
)
from chantal.plugins.rpm.models import RpmMetadata


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)

    session = Session(engine)
    yield session

    session.close()


@pytest.fixture
def test_repositories(db_session):
    """Create test repositories."""
    repos = [
        Repository(
            repo_id="rhel9-baseos",
            name="RHEL 9 BaseOS",
            type="rpm",
            feed="https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os",
            enabled=True,
        ),
        Repository(
            repo_id="rhel9-appstream",
            name="RHEL 9 AppStream",
            type="rpm",
            feed="https://cdn.redhat.com/content/dist/rhel9/9/x86_64/appstream/os",
            enabled=True,
        ),
        Repository(
            repo_id="epel9",
            name="EPEL 9",
            type="rpm",
            feed="https://dl.fedoraproject.org/pub/epel/9/Everything/x86_64/",
            enabled=True,
        ),
    ]

    db_session.add_all(repos)
    db_session.commit()

    return repos


@pytest.fixture
def test_packages(db_session, test_repositories):
    """Create test packages for repositories."""
    packages = [
        # BaseOS packages
        ContentItem(
            content_type="rpm",
            name="vim-enhanced",
            version="8.2.2637",
            sha256="a" * 64,
            size_bytes=2000000,
            pool_path="aa/aa/aaa_vim.rpm",
            filename="vim-enhanced-8.2.2637-20.el9.x86_64.rpm",
            content_metadata=RpmMetadata(release="20.el9", arch="x86_64").model_dump(
                exclude_none=False
            ),
        ),
        ContentItem(
            content_type="rpm",
            name="bash",
            version="5.1.8",
            sha256="b" * 64,
            size_bytes=1500000,
            pool_path="bb/bb/bbb_bash.rpm",
            filename="bash-5.1.8-6.el9.x86_64.rpm",
            content_metadata=RpmMetadata(release="6.el9", arch="x86_64").model_dump(
                exclude_none=False
            ),
        ),
        # AppStream packages
        ContentItem(
            content_type="rpm",
            name="nginx",
            version="1.20.1",
            sha256="c" * 64,
            size_bytes=1800000,
            pool_path="cc/cc/ccc_nginx.rpm",
            filename="nginx-1.20.1-10.el9.x86_64.rpm",
            content_metadata=RpmMetadata(release="10.el9", arch="x86_64").model_dump(
                exclude_none=False
            ),
        ),
        ContentItem(
            content_type="rpm",
            name="httpd",
            version="2.4.51",
            sha256="d" * 64,
            size_bytes=2200000,
            pool_path="dd/dd/ddd_httpd.rpm",
            filename="httpd-2.4.51-7.el9.x86_64.rpm",
            content_metadata=RpmMetadata(release="7.el9", arch="x86_64").model_dump(
                exclude_none=False
            ),
        ),
        # EPEL packages
        ContentItem(
            content_type="rpm",
            name="htop",
            version="3.2.1",
            sha256="e" * 64,
            size_bytes=120000,
            pool_path="ee/ee/eee_htop.rpm",
            filename="htop-3.2.1-1.el9.x86_64.rpm",
            content_metadata=RpmMetadata(release="1.el9", arch="x86_64").model_dump(
                exclude_none=False
            ),
        ),
    ]

    db_session.add_all(packages)
    db_session.commit()

    # Associate content items with repositories
    test_repositories[0].content_items.extend([packages[0], packages[1]])  # BaseOS
    test_repositories[1].content_items.extend([packages[2], packages[3]])  # AppStream
    test_repositories[2].content_items.append(packages[4])  # EPEL

    db_session.commit()

    return packages


def test_create_view(db_session):
    """Test creating a view."""
    view = View(name="rhel9-complete", description="Complete RHEL 9 stack", repo_type="rpm")

    db_session.add(view)
    db_session.commit()

    # Query back
    found = db_session.query(View).filter_by(name="rhel9-complete").first()
    assert found is not None
    assert found.description == "Complete RHEL 9 stack"
    assert found.repo_type == "rpm"
    assert found.is_published is False
    assert found.published_at is None


def test_view_unique_name(db_session):
    """Test view name uniqueness constraint."""
    view1 = View(name="test-view", repo_type="rpm")
    db_session.add(view1)
    db_session.commit()

    # Try to create duplicate name
    view2 = View(name="test-view", repo_type="rpm")
    db_session.add(view2)

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_view_repository_relationship(db_session, test_repositories):
    """Test view-repository many-to-many relationship."""
    view = View(name="rhel9-stack", repo_type="rpm")
    db_session.add(view)
    db_session.commit()

    # Add repositories to view with order
    vr1 = ViewRepository(view_id=view.id, repository_id=test_repositories[0].id, order=0)  # BaseOS
    vr2 = ViewRepository(
        view_id=view.id, repository_id=test_repositories[1].id, order=1  # AppStream
    )

    db_session.add_all([vr1, vr2])
    db_session.commit()

    # Query back
    found_view = db_session.query(View).filter_by(name="rhel9-stack").first()
    assert len(found_view.view_repositories) == 2

    # Check order
    sorted_repos = sorted(found_view.view_repositories, key=lambda vr: vr.order)
    assert sorted_repos[0].repository.repo_id == "rhel9-baseos"
    assert sorted_repos[1].repository.repo_id == "rhel9-appstream"


def test_view_repository_unique_constraint(db_session, test_repositories):
    """Test unique constraint on view-repository pairs."""
    view = View(name="test-view", repo_type="rpm")
    db_session.add(view)
    db_session.commit()

    # Add repository once
    vr1 = ViewRepository(view_id=view.id, repository_id=test_repositories[0].id, order=0)
    db_session.add(vr1)
    db_session.commit()

    # Try to add same repository again
    vr2 = ViewRepository(view_id=view.id, repository_id=test_repositories[0].id, order=1)
    db_session.add(vr2)

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_create_view_snapshot(db_session, test_repositories):
    """Test creating a view snapshot."""
    # Create view
    view = View(name="rhel9-view", repo_type="rpm")
    db_session.add(view)
    db_session.commit()

    # Create snapshots for repositories
    snap1 = Snapshot(
        repository_id=test_repositories[0].id,
        name="2025-01-10",
        package_count=10,
        total_size_bytes=10000000,
    )
    snap2 = Snapshot(
        repository_id=test_repositories[1].id,
        name="2025-01-10",
        package_count=20,
        total_size_bytes=20000000,
    )

    db_session.add_all([snap1, snap2])
    db_session.commit()

    # Create view snapshot
    view_snapshot = ViewSnapshot(
        view_id=view.id,
        name="2025-01-10",
        description="Complete snapshot",
        snapshot_ids=[snap1.id, snap2.id],
        package_count=30,
        total_size_bytes=30000000,
    )

    db_session.add(view_snapshot)
    db_session.commit()

    # Query back
    found = db_session.query(ViewSnapshot).filter_by(name="2025-01-10").first()
    assert found is not None
    assert found.view_id == view.id
    assert found.package_count == 30
    assert found.total_size_bytes == 30000000
    assert len(found.snapshot_ids) == 2
    assert snap1.id in found.snapshot_ids
    assert snap2.id in found.snapshot_ids
    assert found.is_published is False


def test_view_snapshot_unique_name_per_view(db_session, test_repositories):
    """Test view snapshot name uniqueness per view."""
    # Create two views
    view1 = View(name="view1", repo_type="rpm")
    view2 = View(name="view2", repo_type="rpm")
    db_session.add_all([view1, view2])
    db_session.commit()

    # Create snapshot for view1
    vs1 = ViewSnapshot(
        view_id=view1.id, name="snapshot-1", snapshot_ids=[], package_count=0, total_size_bytes=0
    )
    db_session.add(vs1)
    db_session.commit()

    # Can create same name for view2 (different view)
    vs2 = ViewSnapshot(
        view_id=view2.id,
        name="snapshot-1",  # Same name, different view
        snapshot_ids=[],
        package_count=0,
        total_size_bytes=0,
    )
    db_session.add(vs2)
    db_session.commit()  # Should succeed

    # Cannot create duplicate for view1
    vs3 = ViewSnapshot(
        view_id=view1.id,
        name="snapshot-1",  # Duplicate
        snapshot_ids=[],
        package_count=0,
        total_size_bytes=0,
    )
    db_session.add(vs3)

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_view_get_all_packages(db_session, test_repositories, test_packages):
    """Test getting all packages from a view (via ViewPublisher logic)."""
    # Create view
    view = View(name="rhel9-webserver", repo_type="rpm")
    db_session.add(view)
    db_session.commit()

    # Add repositories (BaseOS + AppStream)
    vr1 = ViewRepository(view_id=view.id, repository_id=test_repositories[0].id, order=0)
    vr2 = ViewRepository(view_id=view.id, repository_id=test_repositories[1].id, order=1)
    db_session.add_all([vr1, vr2])
    db_session.commit()

    # Get all packages from view (simulating ViewPublisher._get_view_packages)
    db_session.refresh(view)

    all_packages = []
    for view_repo in sorted(view.view_repositories, key=lambda vr: vr.order):
        repo = view_repo.repository
        db_session.refresh(repo)
        all_packages.extend(repo.content_items)

    # Should have 4 packages: 2 from BaseOS + 2 from AppStream
    assert len(all_packages) == 4
    package_names = {pkg.name for pkg in all_packages}
    assert package_names == {"vim-enhanced", "bash", "nginx", "httpd"}


def test_view_snapshot_retrieves_packages(db_session, test_repositories, test_packages):
    """Test that view snapshot can retrieve packages from referenced snapshots."""
    # Create view
    view = View(name="test-view", repo_type="rpm")
    db_session.add(view)
    db_session.commit()

    # Create snapshots with packages
    snap1 = Snapshot(
        repository_id=test_repositories[0].id,
        name="snap-1",
        package_count=2,
        total_size_bytes=3500000,
    )
    snap1.content_items = [test_packages[0], test_packages[1]]  # vim, bash

    snap2 = Snapshot(
        repository_id=test_repositories[1].id,
        name="snap-2",
        package_count=2,
        total_size_bytes=4000000,
    )
    snap2.content_items = [test_packages[2], test_packages[3]]  # nginx, httpd

    db_session.add_all([snap1, snap2])
    db_session.commit()

    # Create view snapshot
    view_snapshot = ViewSnapshot(
        view_id=view.id,
        name="combined-snapshot",
        snapshot_ids=[snap1.id, snap2.id],
        package_count=4,
        total_size_bytes=7500000,
    )
    db_session.add(view_snapshot)
    db_session.commit()

    # Retrieve packages from snapshots (simulating ViewPublisher._get_view_snapshot_packages)
    all_packages = []
    for snapshot_id in view_snapshot.snapshot_ids:
        snapshot = db_session.query(Snapshot).filter_by(id=snapshot_id).first()
        if snapshot:
            all_packages.extend(snapshot.content_items)

    # Should have all 4 packages
    assert len(all_packages) == 4
    package_names = {pkg.name for pkg in all_packages}
    assert package_names == {"vim-enhanced", "bash", "nginx", "httpd"}


def test_view_publish_state(db_session):
    """Test view publish state tracking."""
    view = View(name="test-view", repo_type="rpm")
    db_session.add(view)
    db_session.commit()

    # Initially not published
    assert view.is_published is False
    assert view.published_at is None
    assert view.published_path is None

    # Mark as published
    view.is_published = True
    view.published_at = datetime.utcnow()
    view.published_path = "/var/www/repos/views/test-view/latest"
    db_session.commit()

    # Query back
    found = db_session.query(View).filter_by(name="test-view").first()
    assert found.is_published is True
    assert found.published_at is not None
    assert found.published_path == "/var/www/repos/views/test-view/latest"


def test_view_snapshot_publish_state(db_session):
    """Test view snapshot publish state tracking."""
    view = View(name="test-view", repo_type="rpm")
    db_session.add(view)
    db_session.commit()

    view_snapshot = ViewSnapshot(
        view_id=view.id, name="snapshot-1", snapshot_ids=[], package_count=0, total_size_bytes=0
    )
    db_session.add(view_snapshot)
    db_session.commit()

    # Initially not published
    assert view_snapshot.is_published is False
    assert view_snapshot.published_at is None
    assert view_snapshot.published_path is None

    # Mark as published
    view_snapshot.is_published = True
    view_snapshot.published_at = datetime.utcnow()
    view_snapshot.published_path = "/var/www/repos/views/test-view/snapshots/snapshot-1"
    db_session.commit()

    # Query back
    found = db_session.query(ViewSnapshot).filter_by(name="snapshot-1").first()
    assert found.is_published is True
    assert found.published_at is not None
    assert found.published_path == "/var/www/repos/views/test-view/snapshots/snapshot-1"
