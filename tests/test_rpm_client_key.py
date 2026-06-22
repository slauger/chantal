"""
Tests for publishing the trusted upstream GPG key into an RPM repository.

The mirrored .rpm files keep their upstream signatures, so downstream clients
need the upstream public key to run ``gpgcheck=1``. The publisher writes the
configured trust anchor(s) (``verify.key_files`` + ``verify.keys``) into the
repository root. This is pure file handling -- no gpg binary required.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from chantal.core.config import (
    RepositoryConfig,
    SignatureVerificationConfig,
    StorageConfig,
)
from chantal.core.storage import StorageManager
from chantal.db.models import Base, ContentItem, Repository, RepositoryMode
from chantal.plugins.rpm.models import RpmMetadata
from chantal.plugins.rpm.publisher import RpmPublisher

_KEY_A = (
    "-----BEGIN PGP PUBLIC KEY BLOCK-----\nAAAA-upstream-key-A\n-----END PGP PUBLIC KEY BLOCK-----"
)
_KEY_B = (
    "-----BEGIN PGP PUBLIC KEY BLOCK-----\nBBBB-upstream-key-B\n-----END PGP PUBLIC KEY BLOCK-----"
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def temp_storage(tmp_path):
    pool_path = tmp_path / "pool"
    pool_path.mkdir()
    config = StorageConfig(
        base_path=str(tmp_path),
        pool_path=str(pool_path),
        published_path=str(tmp_path / "published"),
    )
    return StorageManager(config)


def _make_repo(db_session, temp_storage, tmp_path, mode):
    repo = Repository(
        repo_id="test-rpm-repo",
        name="Test RPM Repo",
        type="rpm",
        feed="https://example.com/repo",
        enabled=True,
        mode=mode,
    )
    db_session.add(repo)
    db_session.commit()

    rpm_file = tmp_path / "test-package-1.0-1.el9.x86_64.rpm"
    rpm_file.write_bytes(b"fake rpm contents" * 64)
    sha256, pool_path, size_bytes = temp_storage.add_package(
        rpm_file, "test-package-1.0-1.el9.x86_64.rpm"
    )
    metadata = RpmMetadata(release="1.el9", arch="x86_64", epoch="0", summary="Test package")
    item = ContentItem(
        content_type="rpm",
        name="test-package",
        version="1.0",
        sha256=sha256,
        filename="test-package-1.0-1.el9.x86_64.rpm",
        size_bytes=size_bytes,
        pool_path=pool_path,
        content_metadata=metadata.model_dump(exclude_none=False),
    )
    item.repositories.append(repo)
    db_session.add(item)
    db_session.commit()
    return repo


def _config(mode, verify):
    return RepositoryConfig(
        id="test-rpm-repo",
        name="Test RPM Repo",
        type="rpm",
        feed="https://example.com/repo",
        mode=mode,
        verify=verify,
    )


def _publish(db_session, temp_storage, tmp_path, mode, verify):
    repo = _make_repo(db_session, temp_storage, tmp_path, mode)
    config = _config(mode, verify)
    publisher = RpmPublisher(storage=temp_storage)
    target = tmp_path / "published" / "test-rpm-repo"
    publisher.publish_repository(
        session=db_session, repository=repo, config=config, target_path=target
    )
    return target


class TestPublishUpstreamKey:
    def test_published_with_inline_key_filtered(self, db_session, temp_storage, tmp_path):
        verify = SignatureVerificationConfig(enabled=True, keys=[_KEY_A])
        target = _publish(db_session, temp_storage, tmp_path, RepositoryMode.FILTERED, verify)

        key_file = target / "RPM-GPG-KEY-test-rpm-repo"
        assert key_file.exists()
        assert _KEY_A in key_file.read_text()

    def test_published_in_mirror_mode(self, db_session, temp_storage, tmp_path):
        # Packages keep upstream signatures in mirror mode too -> key is needed.
        verify = SignatureVerificationConfig(enabled=True, keys=[_KEY_A])
        target = _publish(db_session, temp_storage, tmp_path, RepositoryMode.MIRROR, verify)
        assert (target / "RPM-GPG-KEY-test-rpm-repo").exists()

    def test_no_verify_config_writes_nothing(self, db_session, temp_storage, tmp_path):
        target = _publish(db_session, temp_storage, tmp_path, RepositoryMode.FILTERED, None)
        assert not list(target.glob("RPM-GPG-KEY-*"))

    def test_disabled_verify_writes_nothing(self, db_session, temp_storage, tmp_path):
        verify = SignatureVerificationConfig(enabled=False, keys=[_KEY_A])
        target = _publish(db_session, temp_storage, tmp_path, RepositoryMode.FILTERED, verify)
        assert not list(target.glob("RPM-GPG-KEY-*"))

    def test_empty_name_disables_publishing(self, db_session, temp_storage, tmp_path):
        verify = SignatureVerificationConfig(enabled=True, keys=[_KEY_A], client_key_name="")
        target = _publish(db_session, temp_storage, tmp_path, RepositoryMode.FILTERED, verify)
        assert not list(target.rglob("RPM-GPG-KEY-*"))

    def test_multiple_keys_concatenated(self, db_session, temp_storage, tmp_path):
        verify = SignatureVerificationConfig(enabled=True, keys=[_KEY_A, _KEY_B])
        target = _publish(db_session, temp_storage, tmp_path, RepositoryMode.FILTERED, verify)
        content = (target / "RPM-GPG-KEY-test-rpm-repo").read_text()
        assert _KEY_A in content
        assert _KEY_B in content

    def test_custom_name_with_subdirectory(self, db_session, temp_storage, tmp_path):
        verify = SignatureVerificationConfig(
            enabled=True, keys=[_KEY_A], client_key_name="keys/RPM-GPG-KEY-custom"
        )
        target = _publish(db_session, temp_storage, tmp_path, RepositoryMode.FILTERED, verify)
        key_file = target / "keys" / "RPM-GPG-KEY-custom"
        assert key_file.exists()
        assert _KEY_A in key_file.read_text()

    def test_key_files_are_read_from_disk(self, db_session, temp_storage, tmp_path):
        key_path = tmp_path / "upstream.asc"
        key_path.write_text(_KEY_B + "\n")
        verify = SignatureVerificationConfig(enabled=True, key_files=[str(key_path)])
        target = _publish(db_session, temp_storage, tmp_path, RepositoryMode.FILTERED, verify)
        assert _KEY_B in (target / "RPM-GPG-KEY-test-rpm-repo").read_text()

    def test_missing_key_file_raises(self, db_session, temp_storage, tmp_path):
        verify = SignatureVerificationConfig(
            enabled=True, key_files=[str(tmp_path / "does-not-exist.asc")]
        )
        with pytest.raises(FileNotFoundError, match="Trusted key file not found"):
            _publish(db_session, temp_storage, tmp_path, RepositoryMode.FILTERED, verify)

    def test_collision_with_signing_key_is_skipped(self, db_session, temp_storage, tmp_path):
        # client_key_name resolving to the metadata-signing key must not clobber it.
        from chantal.core.config import GpgConfig

        config = RepositoryConfig(
            id="test-rpm-repo",
            name="Test RPM Repo",
            type="rpm",
            feed="https://example.com/repo",
            mode=RepositoryMode.FILTERED,
            gpg=GpgConfig(enabled=True, key_id="DEADBEEF"),  # publishes key.gpg
            verify=SignatureVerificationConfig(
                enabled=True, keys=[_KEY_A], client_key_name="key.gpg"
            ),
        )
        target = tmp_path / "published" / "test-rpm-repo"
        target.mkdir(parents=True)
        publisher = RpmPublisher(storage=temp_storage)
        # Call the helper directly to avoid invoking gpg for repomd signing.
        publisher._publish_upstream_key(target, config)
        # The upstream key was NOT written over the signing-key filename.
        assert not (target / "key.gpg").exists()


class TestClientKeyNameValidation:
    def test_rejects_absolute_path(self):
        with pytest.raises(ValueError, match="relative path"):
            SignatureVerificationConfig(enabled=True, keys=[_KEY_A], client_key_name="/etc/passwd")

    def test_rejects_parent_traversal(self):
        with pytest.raises(ValueError, match="relative path"):
            SignatureVerificationConfig(enabled=True, keys=[_KEY_A], client_key_name="../../etc/x")

    def test_accepts_relative_subdir(self):
        cfg = SignatureVerificationConfig(
            enabled=True, keys=[_KEY_A], client_key_name="keys/RPM-GPG-KEY-foo"
        )
        assert cfg.client_key_name == "keys/RPM-GPG-KEY-foo"
