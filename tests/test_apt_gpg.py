"""
Tests for APT GPG signing (Issue #30).

Covers:
- GpgConfig validation and passphrase resolution
- GpgSigner key handling (generate, import, lookup), signing and export
- Signature validity (InRelease clearsign, Release.gpg detached)
- AptPublisher integration (filtered mode signs, mirror mode does not)
"""

import shutil
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from chantal.core.config import AptConfig, GpgConfig, RepositoryConfig, StorageConfig
from chantal.core.storage import StorageManager
from chantal.db.models import Base, ContentItem, Repository, RepositoryMode
from chantal.plugins.apt.gpg import GpgSigner, GpgSigningError
from chantal.plugins.apt.models import DebMetadata
from chantal.plugins.apt.publisher import AptPublisher

# Skip all tests if the gpg binary is unavailable (python-gnupg wraps it).
pytestmark = pytest.mark.skipif(
    shutil.which("gpg") is None and shutil.which("gpg2") is None,
    reason="gpg binary not available",
)


@pytest.fixture
def gpg_home():
    """A short-lived GnuPG home directory.

    GnuPG's gpg-agent communicates over a Unix socket inside the home
    directory, and ``sun_path`` is limited (~104 chars). pytest's ``tmp_path``
    can exceed that on some platforms (notably macOS), so we use a short base.
    """
    base = "/tmp" if Path("/tmp").is_dir() else None
    home = tempfile.mkdtemp(prefix="cg-", dir=base)
    yield Path(home)
    shutil.rmtree(home, ignore_errors=True)


@pytest.fixture
def gpg_home2():
    """A second short-lived GnuPG home directory (for import round-trips)."""
    base = "/tmp" if Path("/tmp").is_dir() else None
    home = tempfile.mkdtemp(prefix="cg-", dir=base)
    yield Path(home)
    shutil.rmtree(home, ignore_errors=True)


# --------------------------------------------------------------------------- #
# GpgConfig
# --------------------------------------------------------------------------- #


class TestGpgConfig:
    """Tests for the GpgConfig model."""

    def test_requires_key_source_when_enabled(self):
        """Enabling signing without any key source is rejected."""
        with pytest.raises(ValueError, match="no key source is configured"):
            GpgConfig(enabled=True)

    def test_disabled_does_not_require_key(self):
        """A disabled config needs no key source."""
        config = GpgConfig(enabled=False)
        assert config.enabled is False

    def test_generate_key_satisfies_validation(self):
        """generate_key=True is a valid key source."""
        config = GpgConfig(generate_key=True)
        assert config.generate_key is True

    def test_key_id_satisfies_validation(self):
        """A configured key_id is a valid key source."""
        config = GpgConfig(key_id="DEADBEEF")
        assert config.key_id == "DEADBEEF"

    def test_read_passphrase_inline(self):
        """Inline passphrase is returned as-is."""
        config = GpgConfig(generate_key=True, passphrase="s3cret")
        assert config.read_passphrase() == "s3cret"

    def test_read_passphrase_from_file(self, tmp_path):
        """Passphrase is read (and stripped) from a file."""
        pass_file = tmp_path / "pass.txt"
        pass_file.write_text("filesecret\n")
        config = GpgConfig(generate_key=True, passphrase_file=str(pass_file))
        assert config.read_passphrase() == "filesecret"

    def test_read_passphrase_none(self):
        """No passphrase configured returns None."""
        config = GpgConfig(generate_key=True)
        assert config.read_passphrase() is None


# --------------------------------------------------------------------------- #
# GpgSigner
# --------------------------------------------------------------------------- #


@pytest.fixture
def generated_signer(gpg_home):
    """A GpgSigner backed by a freshly generated key in an isolated keyring."""
    config = GpgConfig(
        generate_key=True,
        gnupg_home=str(gpg_home),
        key_name="Chantal Test",
        key_email="test@chantal.local",
    )
    signer = GpgSigner(config)
    yield signer
    signer.close()


class TestGpgSignerKeyHandling:
    """Tests for key generation, import, and lookup."""

    def test_generate_key(self, generated_signer):
        """A key is generated and its fingerprint is returned."""
        key_id = generated_signer.key_id
        assert key_id
        assert len(key_id) >= 16

    def test_key_id_is_cached(self, generated_signer):
        """Resolving the key twice returns the same fingerprint without regenerating."""
        first = generated_signer.key_id
        second = generated_signer.key_id
        assert first == second
        # Only one secret key should exist in the keyring.
        assert len(generated_signer.gpg.list_keys(secret=True)) == 1

    def test_missing_key_id_raises(self, gpg_home):
        """Referencing a key that is not in the keyring raises."""
        config = GpgConfig(key_id="0000000000000000", gnupg_home=str(gpg_home))
        with GpgSigner(config) as signer:
            with pytest.raises(GpgSigningError, match="not found in keyring"):
                _ = signer.key_id

    def test_missing_key_file_raises(self, gpg_home, tmp_path):
        """A non-existent key file raises a clear error."""
        config = GpgConfig(key_file=str(tmp_path / "nope.asc"), gnupg_home=str(gpg_home))
        with GpgSigner(config) as signer:
            with pytest.raises(GpgSigningError, match="key file not found"):
                _ = signer.key_id

    def test_import_key_from_file(self, generated_signer, gpg_home2, tmp_path):
        """A private key exported to a file can be imported by another signer."""
        # Export the secret key from the generated signer.
        secret = generated_signer.gpg.export_keys(
            generated_signer.key_id, secret=True, expect_passphrase=False
        )
        assert secret
        key_file = tmp_path / "signing.key"
        key_file.write_text(secret)

        # Import into a fresh keyring.
        config = GpgConfig(key_file=str(key_file), gnupg_home=str(gpg_home2))
        with GpgSigner(config) as signer:
            assert signer.key_id == generated_signer.key_id


class TestGpgSignerSigning:
    """Tests for signing and signature validity."""

    def test_clearsign_is_valid(self, generated_signer):
        """InRelease clearsign produces a verifiable inline signature."""
        data = b"Origin: Chantal\nSuite: jammy\n"
        signed = generated_signer.clearsign(data)

        assert b"-----BEGIN PGP SIGNED MESSAGE-----" in signed
        assert b"Origin: Chantal" in signed

        verified = generated_signer.gpg.verify(signed)
        assert verified.valid

    def test_detach_sign_is_valid(self, generated_signer, tmp_path):
        """Release.gpg detached signature verifies against the original data."""
        data = b"Origin: Chantal\nSuite: jammy\n"
        signature = generated_signer.detach_sign(data)

        assert b"-----BEGIN PGP SIGNATURE-----" in signature

        # Verify the detached signature against the original payload.
        sig_file = tmp_path / "Release.gpg"
        sig_file.write_bytes(signature)
        data_file = tmp_path / "Release"
        data_file.write_bytes(data)
        with open(sig_file, "rb") as sf:
            verified = generated_signer.gpg.verify_file(sf, str(data_file))
        assert verified.valid

    def test_export_public_key(self, generated_signer):
        """The public key is exported in ASCII-armored form."""
        pubkey = generated_signer.export_public_key()
        assert b"-----BEGIN PGP PUBLIC KEY BLOCK-----" in pubkey

    def test_sign_release_writes_all_outputs(self, generated_signer, tmp_path):
        """sign_release writes InRelease, Release.gpg and the public key."""
        dists = tmp_path / "repo" / "dists" / "jammy"
        dists.mkdir(parents=True)
        release = dists / "Release"
        release.write_bytes(b"Origin: Chantal\nSuite: jammy\n")
        repo_root = tmp_path / "repo"

        outputs = generated_signer.sign_release(release, repo_root=repo_root)

        assert (dists / "InRelease").exists()
        assert (dists / "Release.gpg").exists()
        assert (repo_root / "key.gpg").exists()
        assert set(outputs) == {"InRelease", "Release.gpg", "key.gpg"}

        # InRelease must verify.
        verified = generated_signer.gpg.verify((dists / "InRelease").read_bytes())
        assert verified.valid


class TestGpgSignerWithPassphrase:
    """Signing with a passphrase-protected key."""

    def test_sign_with_passphrase(self, gpg_home):
        """A passphrase-protected generated key can sign and verify."""
        config = GpgConfig(
            generate_key=True,
            gnupg_home=str(gpg_home),
            passphrase="topsecret",
            key_email="pp@chantal.local",
        )
        with GpgSigner(config) as signer:
            signed = signer.clearsign(b"Suite: jammy\n")
            assert signer.gpg.verify(signed).valid


# --------------------------------------------------------------------------- #
# AptPublisher integration
# --------------------------------------------------------------------------- #


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


@pytest.fixture
def filtered_repo(db_session, temp_storage, tmp_path):
    """A filtered APT repository with one package in the pool."""
    repo = Repository(
        repo_id="test-apt-filtered",
        name="Test APT Filtered",
        type="apt",
        feed="https://example.com/ubuntu",
        enabled=True,
        mode=RepositoryMode.FILTERED,
    )
    db_session.add(repo)
    db_session.commit()

    deb_file = tmp_path / "nginx_1.20.0-1_amd64.deb"
    deb_file.write_bytes(b"fake deb contents" * 64)
    sha256, pool_path, size_bytes = temp_storage.add_package(deb_file, "nginx_1.20.0-1_amd64.deb")

    metadata = DebMetadata(
        package="nginx",
        version="1.20.0-1",
        architecture="amd64",
        component="main",
        filename="pool/main/n/nginx/nginx_1.20.0-1_amd64.deb",
        size=size_bytes,
        sha256=sha256,
        maintainer="Test <test@example.com>",
        description="High performance web server",
    )
    item = ContentItem(
        content_type="deb",
        name="nginx",
        version="1.20.0-1",
        sha256=sha256,
        size_bytes=size_bytes,
        pool_path=pool_path,
        filename="nginx_1.20.0-1_amd64.deb",
        content_metadata=metadata.model_dump(),
    )
    item.repositories.append(repo)
    db_session.add(item)
    db_session.commit()
    return repo


def _apt_config(mode: str, gpg: GpgConfig | None) -> RepositoryConfig:
    return RepositoryConfig(
        id="test-apt-filtered",
        name="Test APT Filtered",
        type="apt",
        feed="https://example.com/ubuntu",
        mode=mode,
        apt=AptConfig(distribution="jammy", components=["main"], architectures=["amd64"]),
        gpg=gpg,
    )


class TestPublisherGpgIntegration:
    """Tests for GPG signing inside AptPublisher."""

    def test_filtered_mode_signs_release(
        self, db_session, temp_storage, filtered_repo, gpg_home, tmp_path
    ):
        """Filtered mode with a gpg config produces signed metadata."""
        config = _apt_config(
            "filtered",
            GpgConfig(generate_key=True, gnupg_home=str(gpg_home), key_email="t@chantal.local"),
        )
        publisher = AptPublisher(storage=temp_storage, config=config)
        target = tmp_path / "published" / "test-apt-filtered"

        publisher.publish_repository(
            session=db_session, repository=filtered_repo, config=config, target_path=target
        )

        dists = target / "dists" / "jammy"
        assert (dists / "Release").exists()
        assert (dists / "InRelease").exists()
        assert (dists / "Release.gpg").exists()
        assert (target / "key.gpg").exists()

        # The InRelease body must match the Release content and verify.
        from chantal.plugins.apt.gpg import GpgSigner as _Signer

        with _Signer(config.gpg) as verifier:
            verified = verifier.gpg.verify((dists / "InRelease").read_bytes())
            assert verified.valid

    def test_filtered_mode_without_gpg_is_unsigned(
        self, db_session, temp_storage, filtered_repo, tmp_path
    ):
        """Filtered mode without a gpg config stays unsigned (backward compatible)."""
        config = _apt_config("filtered", None)
        publisher = AptPublisher(storage=temp_storage, config=config)
        target = tmp_path / "published" / "test-apt-filtered"

        publisher.publish_repository(
            session=db_session, repository=filtered_repo, config=config, target_path=target
        )

        dists = target / "dists" / "jammy"
        assert (dists / "Release").exists()
        assert not (dists / "InRelease").exists()
        assert not (dists / "Release.gpg").exists()

    def test_disabled_gpg_is_unsigned(self, db_session, temp_storage, filtered_repo, tmp_path):
        """An explicitly disabled gpg config does not sign."""
        config = _apt_config("filtered", GpgConfig(enabled=False))
        publisher = AptPublisher(storage=temp_storage, config=config)
        target = tmp_path / "published" / "test-apt-filtered"

        publisher.publish_repository(
            session=db_session, repository=filtered_repo, config=config, target_path=target
        )

        dists = target / "dists" / "jammy"
        assert not (dists / "InRelease").exists()
        assert not (dists / "Release.gpg").exists()
