"""
Tests for APK repository index (APKINDEX.tar.gz) RSA signing.

APK uses its own signing scheme (not GPG): the signed APKINDEX.tar.gz is a
signature gzip segment (a cut tar holding ``.SIGN.RSA256.<name>``) concatenated
with the unsigned index segment. The signature is RSA PKCS#1 v1.5 over SHA-256
of the index segment bytes.
"""

import gzip
import io
import tarfile

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from chantal.core.config import ApkConfig, GpgConfig, RepositoryConfig, StorageConfig
from chantal.core.storage import StorageManager
from chantal.db.models import Base, ContentItem, Repository, RepositoryMode
from chantal.plugins.apk.models import ApkMetadata
from chantal.plugins.apk.publisher import ApkPublisher
from chantal.plugins.apk.signing import ApkSigner, ApkSigningError


def _unsigned_index(content: bytes = b"C:Q1xxx\nP:test\nV:1.0\n\n") -> bytes:
    """Build an unsigned APKINDEX.tar.gz (gzip(tar(APKINDEX)))."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("APKINDEX")
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def _extract_signature(signed: bytes, unsigned: bytes) -> tuple[str, bytes]:
    """Return (sign-entry-name, signature bytes) from a signed index."""
    segment = signed[: len(signed) - len(unsigned)]
    raw = gzip.decompress(segment)  # the cut tar (no end blocks)
    tar = tarfile.open(fileobj=io.BytesIO(raw + b"\0" * 1024), mode="r")
    name = tar.getnames()[0]
    extracted = tar.extractfile(name)
    assert extracted is not None
    return name, extracted.read()


# --------------------------------------------------------------------------- #
# ApkSigner
# --------------------------------------------------------------------------- #


class TestApkSigner:
    def test_sign_index_structure_and_validity(self):
        """A signed index prepends a valid RSA signature segment."""
        config = GpgConfig(generate_key=True, key_name="chantal-test")
        signer = ApkSigner(config)

        unsigned = _unsigned_index()
        signed = signer.sign_index(unsigned)

        # The index segment is preserved at the end.
        assert signed.endswith(unsigned)
        assert signed != unsigned

        name, signature = _extract_signature(signed, unsigned)
        assert name == f".SIGN.RSA256.{signer.key_name}"

        # The signature verifies against the public key over the index bytes.
        pub = load_pem_public_key(signer.export_public_key())
        pub.verify(signature, unsigned, padding.PKCS1v15(), hashes.SHA256())  # no raise

    def test_key_name_defaults_to_rsa_pub(self):
        config = GpgConfig(generate_key=True, key_name="mymirror")
        signer = ApkSigner(config)
        assert signer.key_name == "mymirror.rsa.pub"

    def test_custom_public_key_name(self):
        config = GpgConfig(generate_key=True, public_key_name="alpine-mirror.rsa.pub")
        signer = ApkSigner(config)
        assert signer.key_name == "alpine-mirror.rsa.pub"

    def test_export_public_key_is_pem(self):
        signer = ApkSigner(GpgConfig(generate_key=True))
        pem = signer.export_public_key()
        assert pem.startswith(b"-----BEGIN PUBLIC KEY-----")

    def test_sign_with_key_file(self, tmp_path):
        """An RSA private key from a file can be used to sign."""
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        key_pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        key_file = tmp_path / "signing.pem"
        key_file.write_bytes(key_pem)

        signer = ApkSigner(GpgConfig(key_file=str(key_file)))
        unsigned = _unsigned_index()
        signed = signer.sign_index(unsigned)

        _, signature = _extract_signature(signed, unsigned)
        key.public_key().verify(signature, unsigned, padding.PKCS1v15(), hashes.SHA256())
        assert signer.key_name == "signing.rsa.pub"

    def test_missing_key_file_raises(self, tmp_path):
        signer = ApkSigner(GpgConfig(key_file=str(tmp_path / "nope.pem")))
        with pytest.raises(ApkSigningError, match="key file not found"):
            signer.sign_index(_unsigned_index())

    def test_no_key_source_raises(self):
        # enabled=False bypasses GpgConfig's own validation; the signer then
        # refuses because no key source is configured.
        signer = ApkSigner(GpgConfig(enabled=False))
        with pytest.raises(ApkSigningError, match="No APK signing key"):
            signer.sign_index(_unsigned_index())

    def test_sign_index_file_writes_outputs(self, tmp_path):
        signer = ApkSigner(GpgConfig(generate_key=True, key_name="repo"))
        index = tmp_path / "APKINDEX.tar.gz"
        unsigned = _unsigned_index()
        index.write_bytes(unsigned)

        outputs = signer.sign_index_file(index, repo_root=tmp_path)
        assert index.read_bytes().endswith(unsigned)
        assert (tmp_path / "repo.rsa.pub").exists()
        assert set(outputs) == {"APKINDEX.tar.gz", "repo.rsa.pub"}


# --------------------------------------------------------------------------- #
# Publisher integration
# --------------------------------------------------------------------------- #


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
    return StorageManager(
        StorageConfig(
            base_path=str(tmp_path),
            pool_path=str(pool_path),
            published_path=str(tmp_path / "published"),
        )
    )


def _make_apk_repo(db_session, temp_storage, tmp_path, mode):
    repo = Repository(
        repo_id="test-apk",
        name="Test APK",
        type="apk",
        feed="https://example.com/alpine",
        enabled=True,
        mode=mode,
    )
    db_session.add(repo)
    db_session.commit()

    apk_file = tmp_path / "test-1.0-r0.apk"
    apk_file.write_bytes(b"fake apk" * 32)
    sha256, pool_path, size_bytes = temp_storage.add_package(apk_file, "test-1.0-r0.apk")

    metadata = ApkMetadata(
        name="test",
        version="1.0-r0",
        architecture="x86_64",
        checksum="Q1abc",
        size=size_bytes,
    )
    item = ContentItem(
        content_type="apk",
        name="test",
        version="1.0-r0",
        sha256=sha256,
        size_bytes=size_bytes,
        pool_path=pool_path,
        filename="test-1.0-r0.apk",
        content_metadata=metadata.model_dump(),
    )
    item.repositories.append(repo)
    db_session.add(item)
    db_session.commit()
    return repo


def _apk_config(mode, gpg):
    return RepositoryConfig(
        id="test-apk",
        name="Test APK",
        type="apk",
        feed="https://example.com/alpine",
        mode=mode,
        apk=ApkConfig(branch="v3.19", repository="main", architecture="x86_64"),
        gpg=gpg,
    )


def _index_path(target):
    return target / "v3.19" / "main" / "x86_64" / "APKINDEX.tar.gz"


class TestApkPublisherSigning:
    def test_filtered_mode_signs_index(self, db_session, temp_storage, tmp_path):
        repo = _make_apk_repo(db_session, temp_storage, tmp_path, RepositoryMode.FILTERED)
        config = _apk_config("filtered", GpgConfig(generate_key=True, key_name="chantal"))
        target = tmp_path / "published" / "test-apk"

        ApkPublisher(storage=temp_storage).publish_repository(
            session=db_session, repository=repo, config=config, target_path=target
        )

        index = _index_path(target)
        assert index.exists()
        # Signed index contains the RSA signature marker.
        assert b".SIGN.RSA256.chantal.rsa.pub" in gzip.decompress(index.read_bytes())
        assert (target / "chantal.rsa.pub").exists()

    def test_filtered_mode_without_gpg_is_unsigned(self, db_session, temp_storage, tmp_path):
        repo = _make_apk_repo(db_session, temp_storage, tmp_path, RepositoryMode.FILTERED)
        config = _apk_config("filtered", None)
        target = tmp_path / "published" / "test-apk"

        ApkPublisher(storage=temp_storage).publish_repository(
            session=db_session, repository=repo, config=config, target_path=target
        )

        index = _index_path(target)
        assert index.exists()
        assert b".SIGN.RSA" not in gzip.decompress(index.read_bytes())

    def test_disabled_gpg_is_unsigned(self, db_session, temp_storage, tmp_path):
        repo = _make_apk_repo(db_session, temp_storage, tmp_path, RepositoryMode.FILTERED)
        config = _apk_config("filtered", GpgConfig(enabled=False))
        target = tmp_path / "published" / "test-apk"

        ApkPublisher(storage=temp_storage).publish_repository(
            session=db_session, repository=repo, config=config, target_path=target
        )

        assert b".SIGN.RSA" not in gzip.decompress(_index_path(target).read_bytes())
