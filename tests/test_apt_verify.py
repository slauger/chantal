"""
Tests for APT upstream Release signature verification.

Covers the clearsigned ``InRelease`` path (new ``GpgVerifier.verify_clearsigned``)
and the detached ``Release`` + ``Release.gpg`` path (existing ``verify_detached``).
Uses an ephemeral "upstream" key to sign, then verifies with a fresh keyring
holding only the public key.
"""

import shutil
import tempfile
from pathlib import Path

import pytest

from chantal.core.config import GpgConfig, SignatureVerificationConfig
from chantal.core.gpg import GpgSigner
from chantal.core.gpg_verify import GpgVerifier

pytestmark = pytest.mark.skipif(
    shutil.which("gpg") is None and shutil.which("gpg2") is None,
    reason="gpg binary not available",
)

_RELEASE = (
    b"Origin: Test\n"
    b"Suite: jammy\n"
    b"Codename: jammy\n"
    b"Components: main\n"
    b"Architectures: amd64\n"
    b"SHA256:\n"
    b" 0000000000000000000000000000000000000000000000000000000000000000 10 main/binary-amd64/Packages\n"
)


def _short_home() -> str:
    base = "/tmp" if Path("/tmp").is_dir() else None
    return tempfile.mkdtemp(prefix="cg-", dir=base)


@pytest.fixture
def upstream_signer():
    home = _short_home()
    signer = GpgSigner(GpgConfig(generate_key=True, gnupg_home=home, key_email="vendor@upstream"))
    _ = signer.key_id
    yield signer
    signer.close()
    shutil.rmtree(home, ignore_errors=True)


@pytest.fixture
def verifier_home():
    home = _short_home()
    yield home
    shutil.rmtree(home, ignore_errors=True)


def _verify_config(public_key: str, home: str, **kw) -> SignatureVerificationConfig:
    return SignatureVerificationConfig(enabled=True, keys=[public_key], gnupg_home=home, **kw)


class TestVerifyClearsigned:
    def test_valid_inrelease_returns_payload(self, upstream_signer, verifier_home):
        blob = upstream_signer.clearsign(_RELEASE)
        pub = upstream_signer.export_public_key().decode("utf-8")

        with GpgVerifier(_verify_config(pub, verifier_home)) as verifier:
            payload = verifier.verify_clearsigned(blob)

        assert payload is not None
        # The verified payload must carry the signed Release fields.
        assert b"Suite: jammy" in payload
        assert b"Architectures: amd64" in payload

    def test_tampered_payload_returns_none(self, upstream_signer, verifier_home):
        blob = upstream_signer.clearsign(_RELEASE)
        pub = upstream_signer.export_public_key().decode("utf-8")
        # Flip a byte inside the signed content.
        tampered = blob.replace(b"Suite: jammy", b"Suite: trusty")

        with GpgVerifier(_verify_config(pub, verifier_home)) as verifier:
            assert verifier.verify_clearsigned(tampered) is None

    def test_untrusted_key_returns_none(self, upstream_signer, verifier_home):
        blob = upstream_signer.clearsign(_RELEASE)

        other_home = _short_home()
        other = GpgSigner(GpgConfig(generate_key=True, gnupg_home=other_home, key_email="x@y"))
        try:
            other_pub = other.export_public_key().decode("utf-8")
            with GpgVerifier(_verify_config(other_pub, verifier_home)) as verifier:
                assert verifier.verify_clearsigned(blob) is None
        finally:
            other.close()
            shutil.rmtree(other_home, ignore_errors=True)

    def test_fingerprint_pin_match(self, upstream_signer, verifier_home):
        blob = upstream_signer.clearsign(_RELEASE)
        pub = upstream_signer.export_public_key().decode("utf-8")
        cfg = _verify_config(pub, verifier_home, trusted_fingerprints=[upstream_signer.key_id])

        with GpgVerifier(cfg) as verifier:
            assert verifier.verify_clearsigned(blob) is not None

    def test_fingerprint_pin_mismatch_returns_none(self, upstream_signer, verifier_home):
        blob = upstream_signer.clearsign(_RELEASE)
        pub = upstream_signer.export_public_key().decode("utf-8")
        cfg = _verify_config(pub, verifier_home, trusted_fingerprints=["0" * 40])

        with GpgVerifier(cfg) as verifier:
            assert verifier.verify_clearsigned(blob) is None


class TestVerifyDetachedRelease:
    def test_release_plus_gpg(self, upstream_signer, verifier_home):
        sig = upstream_signer.detach_sign(_RELEASE)
        pub = upstream_signer.export_public_key().decode("utf-8")

        with GpgVerifier(_verify_config(pub, verifier_home)) as verifier:
            assert verifier.verify_detached(_RELEASE, sig) is True
            assert verifier.verify_detached(_RELEASE + b"x", sig) is False
