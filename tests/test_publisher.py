"""
Tests for publisher plugin system.

This module tests the publisher plugin base class and RPM publisher implementation.
"""

import gzip
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from chantal.core.config import RepositoryConfig, StorageConfig
from chantal.core.storage import StorageManager
from chantal.db.models import Base, ContentItem, Repository, Snapshot
from chantal.plugins.rpm.models import RpmMetadata
from chantal.plugins.base import PublisherPlugin
from chantal.plugins.rpm import RpmPublisher


# Test fixtures


@pytest.fixture
def db_engine():
    """Create in-memory SQLite database engine for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_session(db_engine):
    """Create database session for testing."""
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def temp_storage(tmp_path):
    """Create temporary storage manager for testing."""
    pool_path = tmp_path / "pool"
    pool_path.mkdir()

    config = StorageConfig(
        base_path=str(tmp_path),
        pool_path=str(pool_path),
        published_path=str(tmp_path / "published"),
    )
    return StorageManager(config)


@pytest.fixture
def test_package_file(tmp_path):
    """Create a test RPM file."""
    test_file = tmp_path / "test-package-1.0-1.el9.x86_64.rpm"
    test_file.write_bytes(b"This is a test RPM package file" * 100)
    return test_file


@pytest.fixture
def test_repository(db_session):
    """Create a test repository in database."""
    repo = Repository(
        repo_id="test-repo",
        name="Test Repository",
        type="rpm",
        feed="https://example.com/repo",
        enabled=True,
    )
    db_session.add(repo)
    db_session.commit()
    return repo


@pytest.fixture
def test_package(db_session, test_repository, temp_storage, test_package_file):
    """Create a test package in database and storage pool."""
    # Add package to storage pool
    sha256, pool_path, size_bytes = temp_storage.add_package(
        test_package_file, "test-package-1.0-1.el9.x86_64.rpm"
    )

    # Create content item record
    rpm_metadata = RpmMetadata(
        release="1.el9",
        arch="x86_64",
        epoch="0",
        summary="Test package for unit tests",
        description="This is a test package for unit testing",
    )

    content_item = ContentItem(
        content_type="rpm",
        name="test-package",
        version="1.0",
        sha256=sha256,
        filename="test-package-1.0-1.el9.x86_64.rpm",
        size_bytes=size_bytes,
        pool_path=pool_path,
        content_metadata=rpm_metadata.model_dump(exclude_none=False)
    )
    db_session.add(content_item)
    db_session.commit()
    return content_item


@pytest.fixture
def test_snapshot(db_session, test_repository, test_package):
    """Create a test snapshot with packages."""
    snapshot = Snapshot(
        repository_id=test_repository.id,
        name="test-snapshot-20250109",
        description="Test snapshot",
    )
    snapshot.content_items.append(test_package)
    db_session.add(snapshot)
    db_session.commit()
    return snapshot


@pytest.fixture
def rpm_publisher(temp_storage):
    """Create RPM publisher instance for testing."""
    return RpmPublisher(temp_storage)


@pytest.fixture
def repo_config():
    """Create repository configuration for testing."""
    return RepositoryConfig(
        id="test-repo",
        name="Test Repository",
        type="rpm",
        feed="https://example.com/repo",
        enabled=True,
    )


# Base PublisherPlugin Tests


def test_publisher_plugin_is_abstract():
    """Test that PublisherPlugin cannot be instantiated directly."""
    storage = MagicMock()

    # Should not be able to instantiate abstract class
    with pytest.raises(TypeError):
        PublisherPlugin(storage)


def test_publisher_plugin_requires_implementation(temp_storage):
    """Test that abstract methods must be implemented."""

    class IncompletePublisher(PublisherPlugin):
        """Publisher with no method implementations."""

        pass

    # Should raise TypeError because abstract methods not implemented
    with pytest.raises(TypeError):
        IncompletePublisher(temp_storage)


def test_publisher_plugin_create_hardlinks_helper(
    temp_storage, test_package, db_session, tmp_path
):
    """Test the _create_hardlinks helper method."""

    class TestPublisher(PublisherPlugin):
        """Concrete publisher for testing helper method."""

        def publish_repository(self, session, repository, config, target_path):
            pass

        def publish_snapshot(self, session, snapshot, repository, config, target_path):
            pass

        def unpublish(self, target_path):
            pass

    publisher = TestPublisher(temp_storage)
    target_dir = tmp_path / "published" / "test"
    target_dir.mkdir(parents=True)

    # Create hardlinks
    publisher._create_hardlinks([test_package], target_dir, subdir="Packages")

    # Verify hardlink was created
    expected_path = target_dir / "Packages" / test_package.filename
    assert expected_path.exists()
    assert expected_path.is_file()

    # Verify it's a hardlink (same inode)
    pool_file_path = temp_storage.pool_path / temp_storage.get_pool_path(
        test_package.sha256, test_package.filename
    )
    assert expected_path.stat().st_ino == pool_file_path.stat().st_ino


# RpmPublisher Tests


def test_rpm_publisher_initialization(temp_storage):
    """Test RPM publisher initialization."""
    publisher = RpmPublisher(temp_storage)
    assert publisher.storage == temp_storage
    assert isinstance(publisher, PublisherPlugin)


def test_rpm_publisher_publish_snapshot(
    rpm_publisher, db_session, test_snapshot, test_repository, repo_config, tmp_path
):
    """Test publishing a snapshot."""
    target_path = tmp_path / "published" / "snapshots" / "test-snapshot-20250109"

    # Publish snapshot
    rpm_publisher.publish_snapshot(
        db_session, test_snapshot, test_repository, repo_config, target_path
    )

    # Verify directory structure was created
    assert target_path.exists()
    assert (target_path / "Packages").exists()
    assert (target_path / "repodata").exists()

    # Verify package hardlink was created
    package_path = target_path / "Packages" / test_snapshot.content_items[0].filename
    assert package_path.exists()

    # Verify metadata files were created
    assert (target_path / "repodata" / "repomd.xml").exists()
    assert (target_path / "repodata" / "primary.xml.gz").exists()


def test_rpm_publisher_publish_repository(
    rpm_publisher, db_session, test_repository, test_package, repo_config, tmp_path
):
    """Test publishing a repository."""
    target_path = tmp_path / "published" / "latest"

    # Mock _get_repository_packages to return our test package
    with patch.object(
        rpm_publisher, "_get_repository_packages", return_value=[test_package]
    ):
        rpm_publisher.publish_repository(
            db_session, test_repository, repo_config, target_path
        )

    # Verify directory structure was created
    assert target_path.exists()
    assert (target_path / "Packages").exists()
    assert (target_path / "repodata").exists()

    # Verify package hardlink was created
    package_path = target_path / "Packages" / test_package.filename
    assert package_path.exists()

    # Verify metadata files were created
    assert (target_path / "repodata" / "repomd.xml").exists()
    assert (target_path / "repodata" / "primary.xml.gz").exists()


def test_rpm_publisher_unpublish(rpm_publisher, tmp_path):
    """Test unpublishing a repository."""
    target_path = tmp_path / "published" / "test-repo"
    target_path.mkdir(parents=True)
    (target_path / "test-file.txt").write_text("test")

    # Verify directory exists before unpublish
    assert target_path.exists()
    assert (target_path / "test-file.txt").exists()

    # Unpublish
    rpm_publisher.unpublish(target_path)

    # Verify directory was removed
    assert not target_path.exists()


def test_rpm_publisher_unpublish_nonexistent(rpm_publisher, tmp_path):
    """Test unpublishing a non-existent directory."""
    target_path = tmp_path / "nonexistent"

    # Should not raise error
    rpm_publisher.unpublish(target_path)
    assert not target_path.exists()


def test_rpm_publisher_generate_primary_xml(
    rpm_publisher, test_package, db_session, tmp_path
):
    """Test primary.xml.gz generation."""
    repodata_path = tmp_path / "repodata"
    repodata_path.mkdir()

    # Generate primary.xml.gz
    primary_xml_path = rpm_publisher._generate_primary_xml(
        [test_package], repodata_path
    )

    # Verify file was created
    assert primary_xml_path.exists()
    assert primary_xml_path.name == "primary.xml.gz"

    # Verify it's gzipped
    with gzip.open(primary_xml_path, "rb") as f:
        xml_content = f.read()

    # Parse XML
    root = ET.fromstring(xml_content)

    # Verify root element (handle namespace)
    assert root.tag.endswith("metadata")
    assert root.get("packages") == "1"

    # Define namespace
    ns = {"common": "http://linux.duke.edu/metadata/common"}

    # Verify package element
    package_elem = root.find("common:package", ns)
    assert package_elem is not None
    assert package_elem.get("type") == "rpm"

    # Verify package name
    name_elem = package_elem.find("common:name", ns)
    assert name_elem is not None
    assert name_elem.text == test_package.name

    # Verify version
    version_elem = package_elem.find("common:version", ns)
    assert version_elem is not None
    assert version_elem.get("ver") == test_package.version
    assert version_elem.get("rel") == test_package.content_metadata["release"]

    # Verify checksum
    checksum_elem = package_elem.find("common:checksum", ns)
    assert checksum_elem is not None
    assert checksum_elem.get("type") == "sha256"
    assert checksum_elem.text == test_package.sha256

    # Verify location
    location_elem = package_elem.find("common:location", ns)
    assert location_elem is not None
    assert location_elem.get("href") == f"Packages/{test_package.filename}"


def test_rpm_publisher_generate_primary_xml_multiple_packages(
    rpm_publisher, db_session, test_repository, temp_storage, test_package_file, tmp_path
):
    """Test primary.xml.gz generation with multiple packages."""
    # Create multiple packages
    packages = []
    for i in range(3):
        # Create unique package file
        pkg_file = tmp_path / f"test-pkg-{i}-1.0-1.el9.x86_64.rpm"
        pkg_file.write_bytes(b"test package content" * (i + 1))

        # Add to storage
        sha256, pool_path, size_bytes = temp_storage.add_package(
            pkg_file, f"test-pkg-{i}-1.0-1.el9.x86_64.rpm"
        )

        # Create content item record
        rpm_metadata = RpmMetadata(
            release="1.el9",
            arch="x86_64",
            summary=f"Test package {i}",
            description=f"Description for test package {i}",
        )

        content_item = ContentItem(
            content_type="rpm",
            name=f"test-pkg-{i}",
            version="1.0",
            sha256=sha256,
            filename=f"test-pkg-{i}-1.0-1.el9.x86_64.rpm",
            size_bytes=size_bytes,
            pool_path=pool_path,
            content_metadata=rpm_metadata.model_dump(exclude_none=False)
        )
        db_session.add(content_item)
        packages.append(content_item)

    db_session.commit()

    # Generate primary.xml.gz
    repodata_path = tmp_path / "repodata"
    repodata_path.mkdir()
    primary_xml_path = rpm_publisher._generate_primary_xml(packages, repodata_path)

    # Verify file was created
    assert primary_xml_path.exists()

    # Parse XML
    with gzip.open(primary_xml_path, "rb") as f:
        root = ET.fromstring(f.read())

    # Verify package count
    assert root.get("packages") == "3"

    # Define namespace
    ns = {"common": "http://linux.duke.edu/metadata/common"}

    # Verify all packages are present
    package_elems = root.findall("common:package", ns)
    assert len(package_elems) == 3

    # Verify package names
    package_names = {elem.find("common:name", ns).text for elem in package_elems}
    assert package_names == {"test-pkg-0", "test-pkg-1", "test-pkg-2"}


def test_rpm_publisher_generate_repomd_xml(rpm_publisher, tmp_path):
    """Test repomd.xml generation."""
    repodata_path = tmp_path / "repodata"
    repodata_path.mkdir()

    # Create a dummy primary.xml.gz
    primary_xml_content = b'<?xml version="1.0"?><metadata packages="1"></metadata>'
    primary_xml_path = repodata_path / "primary.xml.gz"
    with gzip.open(primary_xml_path, "wb") as f:
        f.write(primary_xml_content)

    # Generate repomd.xml
    repomd_xml_path = rpm_publisher._generate_repomd_xml(
        repodata_path, primary_xml_path
    )

    # Verify file was created
    assert repomd_xml_path.exists()
    assert repomd_xml_path.name == "repomd.xml"

    # Parse XML
    tree = ET.parse(repomd_xml_path)
    root = tree.getroot()

    # Verify root element (strip namespace)
    assert root.tag.endswith("repomd")

    # Define namespace for finding elements
    ns = {"repo": "http://linux.duke.edu/metadata/repo"}

    # Verify revision exists
    revision_elem = root.find("repo:revision", ns)
    assert revision_elem is not None
    assert revision_elem.text.isdigit()

    # Verify data element for primary
    data_elem = root.find("repo:data[@type='primary']", ns)
    assert data_elem is not None

    # Verify checksum
    checksum_elem = data_elem.find("repo:checksum", ns)
    assert checksum_elem is not None
    assert checksum_elem.get("type") == "sha256"
    assert len(checksum_elem.text) == 64  # SHA256 hex length

    # Verify open-checksum
    open_checksum_elem = data_elem.find("repo:open-checksum", ns)
    assert open_checksum_elem is not None
    assert open_checksum_elem.get("type") == "sha256"

    # Verify location
    location_elem = data_elem.find("repo:location", ns)
    assert location_elem is not None
    assert location_elem.get("href") == "repodata/primary.xml.gz"

    # Verify size
    size_elem = data_elem.find("repo:size", ns)
    assert size_elem is not None
    assert int(size_elem.text) > 0

    # Verify open-size
    open_size_elem = data_elem.find("repo:open-size", ns)
    assert open_size_elem is not None
    assert int(open_size_elem.text) == len(primary_xml_content)


def test_rpm_publisher_publish_empty_snapshot(
    rpm_publisher, db_session, test_repository, repo_config, tmp_path
):
    """Test publishing a snapshot with no packages."""
    # Create empty snapshot
    snapshot = Snapshot(
        repository_id=test_repository.id,
        name="empty-snapshot",
        description="Empty snapshot for testing",
    )
    db_session.add(snapshot)
    db_session.commit()

    target_path = tmp_path / "published" / "empty-snapshot"

    # Publish snapshot
    rpm_publisher.publish_snapshot(
        db_session, snapshot, test_repository, repo_config, target_path
    )

    # Verify directory structure was created
    assert target_path.exists()
    assert (target_path / "Packages").exists()
    assert (target_path / "repodata").exists()

    # Verify metadata files were created
    assert (target_path / "repodata" / "repomd.xml").exists()
    assert (target_path / "repodata" / "primary.xml.gz").exists()

    # Verify no packages in Packages directory
    packages_dir = target_path / "Packages"
    assert len(list(packages_dir.iterdir())) == 0

    # Verify primary.xml shows 0 packages
    with gzip.open(target_path / "repodata" / "primary.xml.gz", "rb") as f:
        root = ET.fromstring(f.read())
    assert root.get("packages") == "0"


def test_rpm_publisher_hardlink_preservation(
    rpm_publisher, db_session, test_snapshot, test_repository, repo_config, tmp_path,
    temp_storage
):
    """Test that published packages are hardlinks, not copies."""
    target_path = tmp_path / "published" / "test-snapshot"

    # Publish snapshot
    rpm_publisher.publish_snapshot(
        db_session, test_snapshot, test_repository, repo_config, target_path
    )

    # Get pool file path
    test_package = test_snapshot.content_items[0]
    pool_file_path = temp_storage.pool_path / temp_storage.get_pool_path(
        test_package.sha256, test_package.filename
    )

    # Get published file path
    published_file_path = target_path / "Packages" / test_package.filename

    # Verify both files exist
    assert pool_file_path.exists()
    assert published_file_path.exists()

    # Verify they are hardlinks (same inode)
    assert pool_file_path.stat().st_ino == published_file_path.stat().st_ino

    # Verify they have the same size
    assert pool_file_path.stat().st_size == published_file_path.stat().st_size


def test_rpm_publisher_metadata_xml_well_formed(
    rpm_publisher, db_session, test_snapshot, test_repository, repo_config, tmp_path
):
    """Test that generated XML metadata is well-formed and valid."""
    target_path = tmp_path / "published" / "test-snapshot"

    # Publish snapshot
    rpm_publisher.publish_snapshot(
        db_session, test_snapshot, test_repository, repo_config, target_path
    )

    # Verify repomd.xml is well-formed
    repomd_tree = ET.parse(target_path / "repodata" / "repomd.xml")
    repomd_root = repomd_tree.getroot()
    assert repomd_root.tag.endswith("repomd")

    # Verify primary.xml.gz is well-formed
    with gzip.open(target_path / "repodata" / "primary.xml.gz", "rb") as f:
        primary_root = ET.fromstring(f.read())
    assert primary_root.tag.endswith("metadata")

    # Verify XML declaration exists in both files (accept both single and double quotes)
    with open(target_path / "repodata" / "repomd.xml", "rb") as f:
        repomd_content = f.read()
    assert b'<?xml version' in repomd_content

    with gzip.open(target_path / "repodata" / "primary.xml.gz", "rb") as f:
        primary_content = f.read()
    assert b'<?xml version' in primary_content
