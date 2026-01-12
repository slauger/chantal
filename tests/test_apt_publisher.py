"""
Tests for APT publisher plugin.

This module tests the AptPublisher implementation, focusing on Packages file
generation and Release file generation.
"""

import gzip
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from chantal.core.config import AptConfig, RepositoryConfig, StorageConfig
from chantal.core.storage import StorageManager
from chantal.db.models import Base, ContentItem, Repository
from chantal.plugins.apt.models import DebMetadata
from chantal.plugins.apt.publisher import AptPublisher


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
def test_deb_file(tmp_path):
    """Create a test .deb file."""
    test_file = tmp_path / "test-package_1.0-1_amd64.deb"
    test_file.write_bytes(b"This is a test DEB package file" * 100)
    return test_file


@pytest.fixture
def test_repository(db_session):
    """Create a test repository in database."""
    repo = Repository(
        repo_id="test-apt-repo",
        name="Test APT Repository",
        type="apt",
        feed="https://example.com/ubuntu",
        enabled=True,
    )
    db_session.add(repo)
    db_session.commit()
    return repo


@pytest.fixture
def test_package(db_session, test_repository, temp_storage, test_deb_file):
    """Create a test package in database and storage pool."""
    # Add package to storage pool
    sha256, pool_path, size_bytes = temp_storage.add_package(
        test_deb_file, "test-package_1.0-1_amd64.deb"
    )

    # Create content item record
    deb_metadata = DebMetadata(
        package="test-package",
        version="1.0-1",
        architecture="amd64",
        filename="pool/main/t/test-package/test-package_1.0-1_amd64.deb",
        size=size_bytes,
        sha256=sha256,
        maintainer="Test Maintainer <test@example.com>",
        description="Test package for unit tests",
        section="utils",
        priority="optional",
    )

    content_item = ContentItem(
        content_type="deb",
        name="test-package",
        version="1.0-1",
        sha256=sha256,
        size_bytes=size_bytes,
        pool_path=pool_path,
        filename="test-package_1.0-1_amd64.deb",
        content_metadata=deb_metadata.model_dump(),
    )

    # Link to repository
    content_item.repositories.append(test_repository)

    db_session.add(content_item)
    db_session.commit()

    return content_item


@pytest.fixture
def apt_config():
    """Create test APT configuration."""
    return RepositoryConfig(
        id="test-apt-repo",
        name="Test APT Repository",
        type="apt",
        feed="https://example.com/ubuntu",
        mode="mirror",
        apt=AptConfig(
            distribution="jammy", components=["main"], architectures=["amd64"]
        ),
    )


# Tests


class TestAptPublisher:
    """Tests for AptPublisher class."""

    def test_publisher_creation(self, temp_storage, apt_config):
        """Test creating AptPublisher instance."""
        publisher = AptPublisher(storage=temp_storage, config=apt_config)

        assert publisher.storage == temp_storage
        assert publisher.config == apt_config
        assert publisher.apt_config == apt_config.apt

    def test_publisher_requires_apt_config(self, temp_storage):
        """Test that AptPublisher requires APT configuration."""
        # Config without apt section should raise error
        bad_config = RepositoryConfig(
            id="test-repo",
            name="Test Repo",
            type="apt",
            feed="https://example.com",
            mode="mirror",
            apt=None,
        )

        with pytest.raises(ValueError, match="missing 'apt' configuration"):
            AptPublisher(storage=temp_storage, config=bad_config)


class TestPackagesFileGeneration:
    """Tests for Packages file generation."""

    def test_generate_packages_file_basic(
        self, db_session, temp_storage, apt_config, test_package
    ):
        """Test generating basic Packages file."""
        publisher = AptPublisher(storage=temp_storage, config=apt_config)

        # Get component/arch path
        component_arch_path = Path(temp_storage.config.published_path) / "test_packages"
        component_arch_path.mkdir(parents=True, exist_ok=True)

        # Generate Packages file
        packages_gz = publisher._generate_packages_file(
            [test_package], component_arch_path, "main", "amd64"
        )

        # Verify Packages.gz was created
        assert packages_gz.exists()
        assert packages_gz.name == "Packages.gz"

        # Verify uncompressed Packages file was created
        packages_file = component_arch_path / "Packages"
        assert packages_file.exists()

        # Read and verify content
        content = packages_file.read_text()

        # Should contain package name
        assert "Package: test-package" in content

        # Should contain version
        assert "Version: 1.0-1" in content

        # Should contain architecture
        assert "Architecture: amd64" in content

        # Should contain SHA256
        assert f"SHA256: {test_package.sha256}" in content

        # Should contain size
        assert f"Size: {test_package.size_bytes}" in content

        # Should contain filename
        assert "Filename: main/binary-amd64/test-package_1.0-1_amd64.deb" in content

    def test_generate_packages_file_multiple_packages(
        self, db_session, temp_storage, apt_config, test_repository
    ):
        """Test generating Packages file with multiple packages."""
        # Create multiple packages
        packages = []
        for i in range(3):
            # Create unique SHA256 for each package
            unique_sha256 = f"{i:02x}" + "a" * 62
            pkg = ContentItem(
                content_type="deb",
                name=f"package-{i}",
                version=f"1.{i}.0",
                sha256=unique_sha256,
                size_bytes=1000 + i * 100,
                pool_path=f"pool/content/{i}/package-{i}.deb",
                filename=f"package-{i}_1.{i}.0_amd64.deb",
                content_metadata={
                    "package": f"package-{i}",
                    "version": f"1.{i}.0",
                    "architecture": "amd64",
                    "filename": f"pool/main/p/package-{i}/package-{i}_1.{i}.0_amd64.deb",
                    "size": 1000 + i * 100,
                    "sha256": unique_sha256,
                    "maintainer": f"Maintainer {i} <m{i}@example.com>",
                    "description": f"Package {i} description",
                },
            )
            pkg.repositories.append(test_repository)
            db_session.add(pkg)
            packages.append(pkg)

        db_session.commit()

        publisher = AptPublisher(storage=temp_storage, config=apt_config)

        component_arch_path = Path(temp_storage.config.published_path) / "test_packages"
        component_arch_path.mkdir(parents=True, exist_ok=True)

        # Generate Packages file
        publisher._generate_packages_file(
            packages, component_arch_path, "main", "amd64"
        )

        # Read content
        packages_file = component_arch_path / "Packages"
        content = packages_file.read_text()

        # Should contain all 3 packages
        for i in range(3):
            assert f"Package: package-{i}" in content
            assert f"Version: 1.{i}.0" in content

        # Stanzas should be separated by blank lines
        stanzas = content.strip().split("\n\n")
        assert len(stanzas) == 3

    def test_generate_packages_file_with_dependencies(
        self, db_session, temp_storage, apt_config, test_repository
    ):
        """Test Packages file generation with package dependencies."""
        unique_sha256 = "d" * 64  # Different from test_package
        pkg = ContentItem(
            content_type="deb",
            name="dependent-package",
            version="1.0.0",
            sha256=unique_sha256,
            size_bytes=1000,
            pool_path="pool/content/dep.deb",
            filename="dependent-package_1.0.0_amd64.deb",
            content_metadata={
                "package": "dependent-package",
                "version": "1.0.0",
                "architecture": "amd64",
                "filename": "pool/main/d/dependent-package/dependent-package_1.0.0_amd64.deb",
                "size": 1000,
                "sha256": unique_sha256,
                "depends": "libc6 (>= 2.34), libssl3 (>= 3.0.0)",
                "recommends": "ca-certificates",
                "suggests": "curl",
                "maintainer": "Test <test@example.com>",
                "description": "Package with dependencies",
            },
        )
        pkg.repositories.append(test_repository)
        db_session.add(pkg)
        db_session.commit()

        publisher = AptPublisher(storage=temp_storage, config=apt_config)

        component_arch_path = Path(temp_storage.config.published_path) / "test_packages"
        component_arch_path.mkdir(parents=True, exist_ok=True)

        publisher._generate_packages_file([pkg], component_arch_path, "main", "amd64")

        # Read content
        packages_file = component_arch_path / "Packages"
        content = packages_file.read_text()

        # Should contain dependency fields
        assert "Depends: libc6 (>= 2.34), libssl3 (>= 3.0.0)" in content
        assert "Recommends: ca-certificates" in content
        assert "Suggests: curl" in content


class TestReleaseFileGeneration:
    """Tests for Release file generation."""

    def test_generate_release_file_basic(self, temp_storage, apt_config):
        """Test generating basic Release file."""
        publisher = AptPublisher(storage=temp_storage, config=apt_config)

        dists_path = Path(temp_storage.config.published_path) / "dists" / "jammy"
        dists_path.mkdir(parents=True, exist_ok=True)

        # Create mock Packages file
        packages_path = dists_path / "main" / "binary-amd64"
        packages_path.mkdir(parents=True, exist_ok=True)
        packages_file = packages_path / "Packages"
        packages_file.write_text("Package: test\nVersion: 1.0\n")

        # Gzip it
        packages_gz = packages_path / "Packages.gz"
        with open(packages_file, "rb") as f_in:
            with gzip.open(packages_gz, "wb") as f_out:
                f_out.write(f_in.read())

        published_metadata = [
            {
                "component": "main",
                "architecture": "amd64",
                "packages_file": packages_gz,
            }
        ]

        # Generate Release file
        release_file = publisher._generate_release_file(
            dists_path, published_metadata, [], "mirror"
        )

        assert release_file.exists()
        content = release_file.read_text()

        # Verify basic fields
        assert "Origin: Chantal" in content
        assert "Label: Test APT Repository" in content
        assert "Suite: jammy" in content
        assert "Codename: jammy" in content
        assert "Architectures: amd64" in content
        assert "Components: main" in content

        # Verify checksum sections exist
        assert "MD5Sum:" in content
        assert "SHA1:" in content
        assert "SHA256:" in content

        # Verify Packages files are listed
        assert "main/binary-amd64/Packages" in content
        assert "main/binary-amd64/Packages.gz" in content

    def test_generate_release_file_multi_component(self, temp_storage):
        """Test Release file with multiple components."""
        config = RepositoryConfig(
            id="test-repo",
            name="Test Repo",
            type="apt",
            feed="https://example.com",
            mode="mirror",
            apt=AptConfig(
                distribution="jammy",
                components=["main", "universe"],
                architectures=["amd64"],
            ),
        )

        publisher = AptPublisher(storage=temp_storage, config=config)

        dists_path = Path(temp_storage.config.published_path) / "dists" / "jammy"
        dists_path.mkdir(parents=True, exist_ok=True)

        # Create Packages files for both components
        published_metadata = []
        for component in ["main", "universe"]:
            comp_path = dists_path / component / "binary-amd64"
            comp_path.mkdir(parents=True, exist_ok=True)

            packages_file = comp_path / "Packages"
            packages_file.write_text("Package: test\n")

            packages_gz = comp_path / "Packages.gz"
            with open(packages_file, "rb") as f_in:
                with gzip.open(packages_gz, "wb") as f_out:
                    f_out.write(f_in.read())

            published_metadata.append(
                {
                    "component": component,
                    "architecture": "amd64",
                    "packages_file": packages_gz,
                }
            )

        # Generate Release file
        release_file = publisher._generate_release_file(
            dists_path, published_metadata, [], "mirror"
        )

        content = release_file.read_text()

        # Should list both components
        assert "Components: main universe" in content

        # Should have checksums for both
        assert "main/binary-amd64/Packages" in content
        assert "universe/binary-amd64/Packages" in content


class TestPackageGrouping:
    """Tests for grouping packages by component and architecture."""

    def test_group_packages_by_component_arch(self, temp_storage, apt_config):
        """Test grouping packages by component and architecture."""
        publisher = AptPublisher(storage=temp_storage, config=apt_config)

        # Create packages with different components/architectures
        packages = [
            ContentItem(
                content_type="deb",
                name="pkg1",
                version="1.0",
                content_metadata={"component": "main", "architecture": "amd64"},
            ),
            ContentItem(
                content_type="deb",
                name="pkg2",
                version="1.0",
                content_metadata={"component": "main", "architecture": "arm64"},
            ),
            ContentItem(
                content_type="deb",
                name="pkg3",
                version="1.0",
                content_metadata={"component": "universe", "architecture": "amd64"},
            ),
        ]

        grouped = publisher._group_packages_by_component_arch(packages)

        # Should have 3 groups
        assert len(grouped) == 3

        # Verify groups
        assert ("main", "amd64") in grouped
        assert ("main", "arm64") in grouped
        assert ("universe", "amd64") in grouped

        # Verify package counts
        assert len(grouped[("main", "amd64")]) == 1
        assert len(grouped[("main", "arm64")]) == 1
        assert len(grouped[("universe", "amd64")]) == 1

    def test_group_packages_defaults(self, temp_storage, apt_config):
        """Test grouping with default component/architecture."""
        publisher = AptPublisher(storage=temp_storage, config=apt_config)

        # Package without component/architecture in metadata
        packages = [
            ContentItem(
                content_type="deb",
                name="pkg1",
                version="1.0",
                content_metadata={},  # No component/arch specified
            )
        ]

        grouped = publisher._group_packages_by_component_arch(packages)

        # Should default to main/amd64
        assert ("main", "amd64") in grouped
        assert len(grouped[("main", "amd64")]) == 1
