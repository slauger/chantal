"""
Tests for RPM GPG signing of repository metadata (repomd.xml).

In filtered mode the RPM publisher regenerates repomd.xml, which invalidates the
upstream repomd.xml.asc signature. When a gpg config is present it signs the
regenerated repomd.xml with its own key (repomd.xml.asc) and publishes the
public key. Packages are never re-signed.
"""

import shutil
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from chantal.core.config import GpgConfig, RepositoryConfig, StorageConfig
from chantal.core.gpg import GpgSigner
from chantal.core.storage import StorageManager
from chantal.db.models import Base, ContentItem, Repository, RepositoryMode
from chantal.plugins.rpm.models import RpmMetadata
from chantal.plugins.rpm.publisher import RpmPublisher

# Skip all tests if the gpg binary is unavailable (python-gnupg wraps it).
pytestmark = pytest.mark.skipif(
    shutil.which("gpg") is None and shutil.which("gpg2") is None,
    reason="gpg binary not available",
)


@pytest.fixture
def gpg_home():
    """A short-lived GnuPG home directory.

    gpg-agent's Unix socket lives inside the home dir and sun_path is limited
    (~104 chars); pytest's tmp_path can exceed that, so use a short base.
    """
    base = "/tmp" if Path("/tmp").is_dir() else None
    home = tempfile.mkdtemp(prefix="cg-", dir=base)
    yield Path(home)
    shutil.rmtree(home, ignore_errors=True)


@pytest.fixture
def db_session():
    """In-memory database session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def temp_storage(tmp_path):
    """Temporary storage manager."""
    pool_path = tmp_path / "pool"
    pool_path.mkdir()
    config = StorageConfig(
        base_path=str(tmp_path),
        pool_path=str(pool_path),
        published_path=str(tmp_path / "published"),
    )
    return StorageManager(config)


def _make_repo(db_session, temp_storage, tmp_path, mode):
    """Create a repository with one package in the pool."""
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

    metadata = RpmMetadata(
        release="1.el9",
        arch="x86_64",
        epoch="0",
        summary="Test package",
        description="Test package for GPG signing tests",
    )
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


def _config(mode, gpg):
    return RepositoryConfig(
        id="test-rpm-repo",
        name="Test RPM Repo",
        type="rpm",
        feed="https://example.com/repo",
        mode=mode,
        gpg=gpg,
    )


# --------------------------------------------------------------------------- #
# Shared signer: RPM-specific entry point
# --------------------------------------------------------------------------- #


class TestSignRepomd:
    """Tests for GpgSigner.sign_repomd."""

    def test_sign_repomd_outputs_and_validity(self, gpg_home, tmp_path):
        """sign_repomd writes a valid detached signature and the public key."""
        config = GpgConfig(generate_key=True, gnupg_home=str(gpg_home), key_email="t@chantal.local")
        repodata = tmp_path / "repo" / "repodata"
        repodata.mkdir(parents=True)
        repomd = repodata / "repomd.xml"
        repomd.write_bytes(b"<repomd><revision>1</revision></repomd>")
        repo_root = tmp_path / "repo"

        with GpgSigner(config) as signer:
            outputs = signer.sign_repomd(repomd, repo_root=repo_root)

            asc = repodata / "repomd.xml.asc"
            assert asc.exists()
            assert (repo_root / "key.gpg").exists()
            assert set(outputs) == {"repomd.xml.asc", "key.gpg"}
            assert b"-----BEGIN PGP SIGNATURE-----" in asc.read_bytes()

            # The detached signature must verify against repomd.xml.
            with open(asc, "rb") as sig:
                verified = signer.gpg.verify_file(sig, str(repomd))
            assert verified.valid

    def test_custom_public_key_name(self, gpg_home, tmp_path):
        """public_key_name controls the published key filename (RPM convention)."""
        config = GpgConfig(
            generate_key=True,
            gnupg_home=str(gpg_home),
            key_email="t@chantal.local",
            public_key_name="RPM-GPG-KEY-chantal",
        )
        repodata = tmp_path / "repo" / "repodata"
        repodata.mkdir(parents=True)
        repomd = repodata / "repomd.xml"
        repomd.write_bytes(b"<repomd/>")
        repo_root = tmp_path / "repo"

        with GpgSigner(config) as signer:
            signer.sign_repomd(repomd, repo_root=repo_root)
        assert (repo_root / "RPM-GPG-KEY-chantal").exists()


# --------------------------------------------------------------------------- #
# RpmPublisher integration
# --------------------------------------------------------------------------- #


class TestPublisherRpmGpgIntegration:
    """Tests for GPG signing inside RpmPublisher."""

    def test_filtered_mode_signs_repomd(self, db_session, temp_storage, tmp_path, gpg_home):
        """Filtered mode with a gpg config signs repomd.xml."""
        repo = _make_repo(db_session, temp_storage, tmp_path, RepositoryMode.FILTERED)
        config = _config(
            "filtered",
            GpgConfig(generate_key=True, gnupg_home=str(gpg_home), key_email="t@chantal.local"),
        )
        publisher = RpmPublisher(storage=temp_storage)
        target = tmp_path / "published" / "test-rpm-repo"

        publisher.publish_repository(
            session=db_session, repository=repo, config=config, target_path=target
        )

        repomd = target / "repodata" / "repomd.xml"
        asc = target / "repodata" / "repomd.xml.asc"
        assert repomd.exists()
        assert asc.exists()
        assert (target / "key.gpg").exists()

        with GpgSigner(config.gpg) as verifier:
            with open(asc, "rb") as sig:
                verified = verifier.gpg.verify_file(sig, str(repomd))
            assert verified.valid

    def test_filtered_mode_without_gpg_is_unsigned(self, db_session, temp_storage, tmp_path):
        """Filtered mode without a gpg config stays unsigned (backward compatible)."""
        repo = _make_repo(db_session, temp_storage, tmp_path, RepositoryMode.FILTERED)
        config = _config("filtered", None)
        publisher = RpmPublisher(storage=temp_storage)
        target = tmp_path / "published" / "test-rpm-repo"

        publisher.publish_repository(
            session=db_session, repository=repo, config=config, target_path=target
        )

        assert (target / "repodata" / "repomd.xml").exists()
        assert not (target / "repodata" / "repomd.xml.asc").exists()

    def test_mirror_mode_does_not_sign(self, db_session, temp_storage, tmp_path, gpg_home):
        """Mirror mode preserves upstream signatures and does not re-sign."""
        repo = _make_repo(db_session, temp_storage, tmp_path, RepositoryMode.MIRROR)
        config = _config(
            "mirror",
            GpgConfig(generate_key=True, gnupg_home=str(gpg_home), key_email="t@chantal.local"),
        )
        publisher = RpmPublisher(storage=temp_storage)
        target = tmp_path / "published" / "test-rpm-repo"

        publisher.publish_repository(
            session=db_session, repository=repo, config=config, target_path=target
        )

        assert (target / "repodata" / "repomd.xml").exists()
        assert not (target / "repodata" / "repomd.xml.asc").exists()

    def test_disabled_gpg_is_unsigned(self, db_session, temp_storage, tmp_path):
        """An explicitly disabled gpg config does not sign."""
        repo = _make_repo(db_session, temp_storage, tmp_path, RepositoryMode.FILTERED)
        config = _config("filtered", GpgConfig(enabled=False))
        publisher = RpmPublisher(storage=temp_storage)
        target = tmp_path / "published" / "test-rpm-repo"

        publisher.publish_repository(
            session=db_session, repository=repo, config=config, target_path=target
        )

        assert not (target / "repodata" / "repomd.xml.asc").exists()
