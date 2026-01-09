"""Tests for configuration management."""

import tempfile
from pathlib import Path

import pytest

from chantal.core.config import (
    AuthConfig,
    ConfigLoader,
    DatabaseConfig,
    GlobalConfig,
    RepositoryConfig,
    RetentionConfig,
    StorageConfig,
    load_config,
)


def test_database_config_defaults():
    """Test database config with defaults."""
    config = DatabaseConfig()
    assert config.url == "postgresql://chantal:chantal@localhost/chantal"
    assert config.pool_size == 5
    assert config.max_overflow == 10
    assert config.echo is False


def test_storage_config_defaults():
    """Test storage config with defaults."""
    config = StorageConfig()
    assert config.base_path == "/var/lib/chantal"
    assert config.published_path == "/var/www/repos"
    assert config.pool_path is None

    # Test path getters
    assert config.get_pool_path() == Path("/var/lib/chantal/pool")
    assert config.get_temp_path() == Path("/var/lib/chantal/tmp")


def test_storage_config_custom_paths():
    """Test storage config with custom paths."""
    config = StorageConfig(
        base_path="/custom/base",
        pool_path="/custom/pool",
        temp_path="/custom/tmp",
    )

    assert config.get_pool_path() == Path("/custom/pool")
    assert config.get_temp_path() == Path("/custom/tmp")


def test_retention_config_validation():
    """Test retention policy validation."""
    # Valid policies
    for policy in ["mirror", "newest-only", "keep-all", "keep-last-n"]:
        config = RetentionConfig(policy=policy)
        assert config.policy == policy

    # Invalid policy
    with pytest.raises(ValueError, match="Invalid retention policy"):
        RetentionConfig(policy="invalid-policy")


def test_repository_config_validation():
    """Test repository type validation."""
    # Valid types
    for repo_type in ["rpm", "apt"]:
        config = RepositoryConfig(
            id="test-repo",
            type=repo_type,
            feed="https://example.com/repo",
        )
        assert config.type == repo_type

    # Invalid type
    with pytest.raises(ValueError, match="Invalid repository type"):
        RepositoryConfig(
            id="test-repo",
            type="invalid-type",
            feed="https://example.com/repo",
        )


def test_repository_config_display_name():
    """Test repository display name property."""
    # With explicit name
    config = RepositoryConfig(
        id="rhel9-baseos",
        name="RHEL 9 BaseOS",
        type="rpm",
        feed="https://cdn.redhat.com/repo",
    )
    assert config.display_name == "RHEL 9 BaseOS"

    # Without explicit name (uses ID)
    config = RepositoryConfig(
        id="rhel9-baseos",
        type="rpm",
        feed="https://cdn.redhat.com/repo",
    )
    assert config.display_name == "rhel9-baseos"


def test_global_config_defaults():
    """Test global config with defaults."""
    config = GlobalConfig()
    assert isinstance(config.database, DatabaseConfig)
    assert isinstance(config.storage, StorageConfig)
    assert config.proxy is None
    assert config.repositories == []


def test_global_config_get_repository():
    """Test getting repository by ID."""
    config = GlobalConfig(
        repositories=[
            RepositoryConfig(
                id="repo1",
                type="rpm",
                feed="https://example.com/repo1",
            ),
            RepositoryConfig(
                id="repo2",
                type="rpm",
                feed="https://example.com/repo2",
            ),
        ]
    )

    repo = config.get_repository("repo1")
    assert repo is not None
    assert repo.id == "repo1"

    # Non-existent repo
    repo = config.get_repository("repo-not-found")
    assert repo is None


def test_global_config_get_enabled_repositories():
    """Test getting enabled repositories."""
    config = GlobalConfig(
        repositories=[
            RepositoryConfig(
                id="repo1",
                type="rpm",
                feed="https://example.com/repo1",
                enabled=True,
            ),
            RepositoryConfig(
                id="repo2",
                type="rpm",
                feed="https://example.com/repo2",
                enabled=False,
            ),
            RepositoryConfig(
                id="repo3",
                type="rpm",
                feed="https://example.com/repo3",
                enabled=True,
            ),
        ]
    )

    enabled = config.get_enabled_repositories()
    assert len(enabled) == 2
    assert enabled[0].id == "repo1"
    assert enabled[1].id == "repo3"


def test_global_config_get_repositories_by_type():
    """Test getting repositories by type."""
    config = GlobalConfig(
        repositories=[
            RepositoryConfig(
                id="repo1",
                type="rpm",
                feed="https://example.com/repo1",
            ),
            RepositoryConfig(
                id="repo2",
                type="apt",
                feed="https://example.com/repo2",
            ),
            RepositoryConfig(
                id="repo3",
                type="rpm",
                feed="https://example.com/repo3",
            ),
        ]
    )

    rpm_repos = config.get_repositories_by_type("rpm")
    assert len(rpm_repos) == 2
    assert rpm_repos[0].id == "repo1"
    assert rpm_repos[1].id == "repo3"

    apt_repos = config.get_repositories_by_type("apt")
    assert len(apt_repos) == 1
    assert apt_repos[0].id == "repo2"


def test_config_loader_basic():
    """Test basic configuration loading."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "config.yaml"

        # Write test config
        config_yaml = """
database:
  url: postgresql://test:test@localhost/test
  pool_size: 10

storage:
  base_path: /tmp/chantal
  published_path: /tmp/repos

repositories:
  - id: test-repo
    type: rpm
    feed: https://example.com/repo
    enabled: true
"""
        config_path.write_text(config_yaml)

        # Load config
        loader = ConfigLoader(config_path)
        config = loader.load()

        assert config.database.url == "postgresql://test:test@localhost/test"
        assert config.database.pool_size == 10
        assert config.storage.base_path == "/tmp/chantal"
        assert len(config.repositories) == 1
        assert config.repositories[0].id == "test-repo"


def test_config_loader_with_includes():
    """Test configuration loading with includes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        config_path = tmpdir / "config.yaml"
        conf_d = tmpdir / "conf.d"
        conf_d.mkdir()

        # Write main config
        config_yaml = """
database:
  url: postgresql://test:test@localhost/test

storage:
  base_path: /tmp/chantal

repositories:
  - id: main-repo
    type: rpm
    feed: https://example.com/main
    enabled: true

include: conf.d/*.yaml
"""
        config_path.write_text(config_yaml)

        # Write included config
        included_yaml = """
repositories:
  - id: included-repo-1
    type: rpm
    feed: https://example.com/included1
    enabled: true
  - id: included-repo-2
    type: apt
    feed: https://example.com/included2
    enabled: false
"""
        (conf_d / "repos.yaml").write_text(included_yaml)

        # Load config
        loader = ConfigLoader(config_path)
        config = loader.load()

        # Should have main repo + 2 included repos
        assert len(config.repositories) == 3
        assert config.repositories[0].id == "main-repo"
        assert config.repositories[1].id == "included-repo-1"
        assert config.repositories[2].id == "included-repo-2"


def test_config_loader_file_not_found():
    """Test loading non-existent config file."""
    config_path = Path("/non/existent/config.yaml")
    loader = ConfigLoader(config_path)

    with pytest.raises(FileNotFoundError):
        loader.load()


def test_load_config_default_paths():
    """Test load_config with default path fallback."""
    # This should return default config since no file exists
    config = load_config(config_path=None)

    assert isinstance(config, GlobalConfig)
    assert config.database.url == "postgresql://chantal:chantal@localhost/chantal"
    assert config.repositories == []


def test_auth_config():
    """Test authentication configuration."""
    # Client cert auth
    auth = AuthConfig(
        type="client_cert",
        cert_dir="/etc/pki/entitlement",
    )
    assert auth.type == "client_cert"
    assert auth.cert_dir == "/etc/pki/entitlement"

    # Basic auth
    auth = AuthConfig(
        type="basic",
        username="user",
        password="pass",
    )
    assert auth.type == "basic"
    assert auth.username == "user"
    assert auth.password == "pass"

    # Bearer token
    auth = AuthConfig(
        type="bearer",
        token="abc123",
    )
    assert auth.type == "bearer"
    assert auth.token == "abc123"
