"""
Tests for Helm sync and publish plugins.

This module tests the HelmSyncer and HelmPublisher implementation,
focusing on mirror mode support (index.yaml as RepositoryFile).
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from chantal.core.config import RepositoryConfig, StorageConfig
from chantal.core.storage import StorageManager
from chantal.db.models import Base, ContentItem, Repository, RepositoryFile, Snapshot
from chantal.plugins.helm.models import HelmMetadata
from chantal.plugins.helm.publisher import HelmPublisher
from chantal.plugins.helm.sync import HelmSyncer


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
def repository(db_session):
    """Create a test repository."""
    repo = Repository(
        repo_id="test-helm",
        name="Test Helm Repository",
        type="helm",
        feed="https://charts.example.com",
        enabled=True,
        mode="MIRROR",
    )
    db_session.add(repo)
    db_session.commit()
    return repo


@pytest.fixture
def sample_index_yaml():
    """Sample index.yaml content."""
    return {
        "apiVersion": "v1",
        "entries": {
            "nginx": [
                {
                    "name": "nginx",
                    "version": "1.0.0",
                    "description": "NGINX chart",
                    "digest": "sha256:abc123def456",
                    "urls": ["https://charts.example.com/nginx-1.0.0.tgz"],
                }
            ]
        },
        "generated": "2025-01-15T12:00:00Z",
    }


class TestHelmSyncerIndexStorage:
    """Tests for HelmSyncer._store_index_file()."""

    @patch("chantal.plugins.helm.sync.HelmSyncer._fetch_index")
    def test_store_index_file_creates_repository_file(
        self, mock_fetch, temp_storage, db_session, repository, sample_index_yaml
    ):
        """Test that _store_index_file creates a RepositoryFile."""
        # Setup
        repo_config = RepositoryConfig(
            id="test-helm",
            name="Test Helm",
            type="helm",
            feed="https://charts.example.com",
        )

        syncer = HelmSyncer(storage=temp_storage, config=repo_config)

        # Mock HTTP response
        mock_response = Mock()
        mock_response.content = yaml.dump(sample_index_yaml).encode("utf-8")
        mock_response.raise_for_status = Mock()
        syncer.session.get = Mock(return_value=mock_response)

        # Execute
        syncer._store_index_file(
            index_url="https://charts.example.com/index.yaml",
            config=repo_config,
            session=db_session,
            repository=repository,
        )

        # Verify RepositoryFile was created
        repo_files = db_session.query(RepositoryFile).all()
        assert len(repo_files) == 1

        repo_file = repo_files[0]
        assert repo_file.file_category == "metadata"
        assert repo_file.file_type == "index"
        assert repo_file.original_path == "index.yaml"
        assert repo_file.sha256 is not None
        assert repo_file.size_bytes > 0

        # Verify link to repository
        assert repository in repo_file.repositories

    @patch("chantal.plugins.helm.sync.HelmSyncer._fetch_index")
    def test_store_index_file_deduplication(
        self, mock_fetch, temp_storage, db_session, repository, sample_index_yaml
    ):
        """Test that identical index.yaml files are deduplicated."""
        repo_config = RepositoryConfig(
            id="test-helm",
            name="Test Helm",
            type="helm",
            feed="https://charts.example.com",
        )

        syncer = HelmSyncer(storage=temp_storage, config=repo_config)

        # Mock HTTP response
        mock_response = Mock()
        mock_response.content = yaml.dump(sample_index_yaml).encode("utf-8")
        mock_response.raise_for_status = Mock()
        syncer.session.get = Mock(return_value=mock_response)

        # Store twice
        syncer._store_index_file(
            index_url="https://charts.example.com/index.yaml",
            config=repo_config,
            session=db_session,
            repository=repository,
        )

        syncer._store_index_file(
            index_url="https://charts.example.com/index.yaml",
            config=repo_config,
            session=db_session,
            repository=repository,
        )

        # Should only have one RepositoryFile (deduplicated)
        repo_files = db_session.query(RepositoryFile).all()
        assert len(repo_files) == 1

    @patch("chantal.plugins.helm.sync.HelmSyncer._fetch_index")
    def test_store_index_file_links_to_multiple_repos(
        self, mock_fetch, temp_storage, db_session, sample_index_yaml
    ):
        """Test that same index.yaml can link to multiple repositories."""
        repo1 = Repository(
            repo_id="helm1", name="Helm 1", type="helm", feed="https://charts1.com", enabled=True
        )
        repo2 = Repository(
            repo_id="helm2", name="Helm 2", type="helm", feed="https://charts2.com", enabled=True
        )
        db_session.add(repo1)
        db_session.add(repo2)
        db_session.commit()

        repo_config = RepositoryConfig(
            id="test-helm", name="Test", type="helm", feed="https://charts.example.com"
        )

        syncer = HelmSyncer(storage=temp_storage, config=repo_config)

        # Mock HTTP response
        mock_response = Mock()
        mock_response.content = yaml.dump(sample_index_yaml).encode("utf-8")
        mock_response.raise_for_status = Mock()
        syncer.session.get = Mock(return_value=mock_response)

        # Store for both repos
        syncer._store_index_file(
            index_url="https://charts.example.com/index.yaml",
            config=repo_config,
            session=db_session,
            repository=repo1,
        )

        syncer._store_index_file(
            index_url="https://charts.example.com/index.yaml",
            config=repo_config,
            session=db_session,
            repository=repo2,
        )

        # Should have one RepositoryFile linked to both repos
        repo_files = db_session.query(RepositoryFile).all()
        assert len(repo_files) == 1
        assert repo1 in repo_files[0].repositories
        assert repo2 in repo_files[0].repositories


class TestHelmPublisherMirrorMode:
    """Tests for HelmPublisher._publish_metadata_files()."""

    def test_publish_metadata_from_repository_file(self, temp_storage, db_session, repository):
        """Test publishing index.yaml from RepositoryFile (mirror mode)."""
        # Create a sample index.yaml in pool
        index_content = yaml.dump({"apiVersion": "v1", "entries": {}}).encode("utf-8")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".yaml") as tmp:
            tmp.write(index_content)
            tmp_path = Path(tmp.name)

        # Add to storage pool
        sha256, pool_path, size_bytes = temp_storage.add_repository_file(
            tmp_path, "index.yaml", verify_checksum=True
        )

        # Create RepositoryFile record
        repo_file = RepositoryFile(
            file_category="metadata",
            file_type="index",
            sha256=sha256,
            pool_path=pool_path,
            size_bytes=size_bytes,
            original_path="index.yaml",
            file_metadata={"checksum_type": "sha256"},
        )
        db_session.add(repo_file)
        db_session.commit()

        # Link to repository
        repo_file.repositories.append(repository)
        db_session.commit()

        # Publish
        publisher = HelmPublisher(storage=temp_storage)
        target_path = temp_storage.published_path
        target_path.mkdir(parents=True, exist_ok=True)

        repo_config = RepositoryConfig(
            id="test-helm", name="Test", type="helm", feed="https://charts.example.com"
        )

        publisher._publish_metadata_files(
            session=db_session,
            repository=repository,
            target_path=target_path,
            config=repo_config,
            charts=[],
            snapshot=None,
        )

        # Verify index.yaml was published
        published_index = target_path / "index.yaml"
        assert published_index.exists()

        # Verify content matches
        assert published_index.read_bytes() == index_content

        # Cleanup
        tmp_path.unlink(missing_ok=True)

    def test_publish_metadata_fallback_to_generation(self, temp_storage, db_session, repository):
        """Test fallback to dynamic generation when no RepositoryFile exists."""
        # Create a sample chart
        chart_metadata = HelmMetadata(
            name="nginx",
            version="1.0.0",
            description="NGINX chart",
            apiVersion="v2",
            appVersion="1.19.0",
        )

        chart = ContentItem(
            content_type="helm",
            name="nginx",
            version="1.0.0",
            filename="nginx-1.0.0.tgz",
            sha256="abc123def456",
            pool_path="ab/c1/abc123def456_nginx-1.0.0.tgz",
            size_bytes=1024,
            content_metadata=chart_metadata.model_dump(mode="json"),
        )
        db_session.add(chart)
        db_session.commit()

        # Publish (no RepositoryFile exists, should generate)
        publisher = HelmPublisher(storage=temp_storage)
        target_path = temp_storage.published_path
        target_path.mkdir(parents=True, exist_ok=True)

        repo_config = RepositoryConfig(
            id="test-helm", name="Test", type="helm", feed="https://charts.example.com"
        )

        publisher._publish_metadata_files(
            session=db_session,
            repository=repository,
            target_path=target_path,
            config=repo_config,
            charts=[chart],
            snapshot=None,
        )

        # Verify index.yaml was generated
        published_index = target_path / "index.yaml"
        assert published_index.exists()

        # Verify content is valid YAML
        index_data = yaml.safe_load(published_index.read_text())
        assert index_data["apiVersion"] == "v1"
        assert "nginx" in index_data["entries"]

    def test_publish_metadata_with_snapshot(self, temp_storage, db_session, repository):
        """Test publishing index.yaml from snapshot's repository_files."""
        # Create RepositoryFile
        index_content = yaml.dump({"apiVersion": "v1", "entries": {}}).encode("utf-8")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".yaml") as tmp:
            tmp.write(index_content)
            tmp_path = Path(tmp.name)

        sha256, pool_path, size_bytes = temp_storage.add_repository_file(
            tmp_path, "index.yaml", verify_checksum=True
        )

        repo_file = RepositoryFile(
            file_category="metadata",
            file_type="index",
            sha256=sha256,
            pool_path=pool_path,
            size_bytes=size_bytes,
            original_path="index.yaml",
            file_metadata={"checksum_type": "sha256"},
        )
        db_session.add(repo_file)
        db_session.commit()

        # Create snapshot and link RepositoryFile
        snapshot = Snapshot(
            repository_id=repository.id,
            name="test-snapshot",
            description="Test snapshot",
        )
        db_session.add(snapshot)
        db_session.commit()

        snapshot.repository_files.append(repo_file)
        db_session.commit()

        # Publish snapshot
        publisher = HelmPublisher(storage=temp_storage)
        target_path = temp_storage.published_path
        target_path.mkdir(parents=True, exist_ok=True)

        repo_config = RepositoryConfig(
            id="test-helm", name="Test", type="helm", feed="https://charts.example.com"
        )

        publisher._publish_metadata_files(
            session=db_session,
            repository=repository,
            target_path=target_path,
            config=repo_config,
            charts=[],
            snapshot=snapshot,
        )

        # Verify index.yaml was published from snapshot
        published_index = target_path / "index.yaml"
        assert published_index.exists()
        assert published_index.read_bytes() == index_content

        # Cleanup
        tmp_path.unlink(missing_ok=True)


class TestHelmIntegration:
    """Integration tests for complete Helm workflow."""

    def test_sync_and_publish_with_mirror_mode(
        self, temp_storage, db_session, repository, sample_index_yaml
    ):
        """Test complete sync → publish workflow with mirror mode."""
        repo_config = RepositoryConfig(
            id="test-helm", name="Test", type="helm", feed="https://charts.example.com"
        )

        syncer = HelmSyncer(storage=temp_storage, config=repo_config)

        # Mock HTTP response for index.yaml
        mock_response = Mock()
        mock_response.content = yaml.dump(sample_index_yaml).encode("utf-8")
        mock_response.raise_for_status = Mock()
        syncer.session.get = Mock(return_value=mock_response)

        # Store index.yaml
        syncer._store_index_file(
            index_url="https://charts.example.com/index.yaml",
            config=repo_config,
            session=db_session,
            repository=repository,
        )

        # Verify RepositoryFile was created
        repo_files = db_session.query(RepositoryFile).all()
        assert len(repo_files) == 1

        # Publish
        publisher = HelmPublisher(storage=temp_storage)
        target_path = temp_storage.published_path
        target_path.mkdir(parents=True, exist_ok=True)

        publisher._publish_metadata_files(
            session=db_session,
            repository=repository,
            target_path=target_path,
            config=repo_config,
            charts=[],
            snapshot=None,
        )

        # Verify published index.yaml
        published_index = target_path / "index.yaml"
        assert published_index.exists()

        # Verify content is byte-for-byte identical (mirror mode)
        original_content = yaml.dump(sample_index_yaml).encode("utf-8")
        assert published_index.read_bytes() == original_content
