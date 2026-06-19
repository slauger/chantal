"""
Tests for upstream signature verification config + GpgVerifier.

Covers the repository-metadata signature path (RPM ``repomd.xml.asc`` and, more
generally, any detached OpenPGP signature). Uses an ephemeral "upstream" key to
sign data, then verifies with a fresh keyring holding only the public key.
"""

import shutil
import tempfile
from pathlib import Path

import pytest

from chantal.core.config import GpgConfig, SignatureVerificationConfig
from chantal.core.gpg import GpgSigner
from chantal.core.gpg_verify import GpgVerificationError, GpgVerifier

pytestmark = pytest.mark.skipif(
    shutil.which("gpg") is None and shutil.which("gpg2") is None,
    reason="gpg binary not available",
)


def _short_home() -> str:
    base = "/tmp" if Path("/tmp").is_dir() else None
    return tempfile.mkdtemp(prefix="cg-", dir=base)


@pytest.fixture
def upstream_signer():
    """An ephemeral 'upstream vendor' signer (private key in its own keyring)."""
    home = _short_home()
    signer = GpgSigner(GpgConfig(generate_key=True, gnupg_home=home, key_email="vendor@upstream"))
    # Force key creation up front.
    _ = signer.key_id
    yield signer
    signer.close()
    shutil.rmtree(home, ignore_errors=True)


@pytest.fixture
def verifier_home():
    home = _short_home()
    yield home
    shutil.rmtree(home, ignore_errors=True)


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


class TestSignatureVerificationConfig:
    def test_enabled_requires_a_key(self):
        with pytest.raises(ValueError, match="no trusted key"):
            SignatureVerificationConfig(enabled=True)

    def test_disabled_needs_no_key(self):
        assert SignatureVerificationConfig(enabled=False).enabled is False

    def test_enabled_with_inline_key(self):
        cfg = SignatureVerificationConfig(enabled=True, keys=["-----BEGIN PGP PUBLIC KEY-----"])
        assert cfg.enabled is True

    def test_gpgcheck_rejected_until_implemented(self):
        with pytest.raises(ValueError, match="not yet implemented"):
            SignatureVerificationConfig(enabled=True, keys=["k"], gpgcheck=True)

    def test_empty_fingerprint_rejected(self):
        with pytest.raises(ValueError, match="empty entries"):
            SignatureVerificationConfig(enabled=True, keys=["k"], trusted_fingerprints=[""])


# --------------------------------------------------------------------------- #
# GpgVerifier
# --------------------------------------------------------------------------- #


def _verify_config(public_key: str, home: str, **kw) -> SignatureVerificationConfig:
    return SignatureVerificationConfig(enabled=True, keys=[public_key], gnupg_home=home, **kw)


class TestGpgVerifier:
    def test_valid_signature_passes(self, upstream_signer, verifier_home):
        data = b"<repomd><revision>1</revision></repomd>"
        sig = upstream_signer.detach_sign(data)
        pub = upstream_signer.export_public_key().decode("utf-8")

        with GpgVerifier(_verify_config(pub, verifier_home)) as verifier:
            assert verifier.verify_detached(data, sig) is True

    def test_tampered_data_fails(self, upstream_signer, verifier_home):
        data = b"<repomd><revision>1</revision></repomd>"
        sig = upstream_signer.detach_sign(data)
        pub = upstream_signer.export_public_key().decode("utf-8")

        with GpgVerifier(_verify_config(pub, verifier_home)) as verifier:
            assert verifier.verify_detached(data + b"tampered", sig) is False

    def test_untrusted_key_fails(self, upstream_signer, verifier_home):
        # Verifier trusts a DIFFERENT key than the one that signed.
        data = b"payload"
        sig = upstream_signer.detach_sign(data)

        other_home = _short_home()
        other = GpgSigner(GpgConfig(generate_key=True, gnupg_home=other_home, key_email="x@y"))
        try:
            other_pub = other.export_public_key().decode("utf-8")
            with GpgVerifier(_verify_config(other_pub, verifier_home)) as verifier:
                assert verifier.verify_detached(data, sig) is False
        finally:
            other.close()
            shutil.rmtree(other_home, ignore_errors=True)

    def test_fingerprint_pin_match(self, upstream_signer, verifier_home):
        data = b"payload"
        sig = upstream_signer.detach_sign(data)
        pub = upstream_signer.export_public_key().decode("utf-8")
        cfg = _verify_config(pub, verifier_home, trusted_fingerprints=[upstream_signer.key_id])

        with GpgVerifier(cfg) as verifier:
            assert verifier.verify_detached(data, sig) is True

    def test_fingerprint_pin_long_keyid_suffix(self, upstream_signer, verifier_home):
        # A long key-id (last 16 hex of the fingerprint) is accepted.
        data = b"payload"
        sig = upstream_signer.detach_sign(data)
        pub = upstream_signer.export_public_key().decode("utf-8")
        long_keyid = upstream_signer.key_id[-16:]
        cfg = _verify_config(pub, verifier_home, trusted_fingerprints=[long_keyid])

        with GpgVerifier(cfg) as verifier:
            assert verifier.verify_detached(data, sig) is True

    def test_fingerprint_pin_mismatch_fails(self, upstream_signer, verifier_home):
        data = b"payload"
        sig = upstream_signer.detach_sign(data)
        pub = upstream_signer.export_public_key().decode("utf-8")
        cfg = _verify_config(pub, verifier_home, trusted_fingerprints=["0" * 40])

        with GpgVerifier(cfg) as verifier:
            assert verifier.verify_detached(data, sig) is False

    def test_missing_key_file_raises(self, verifier_home, tmp_path):
        cfg = SignatureVerificationConfig(
            enabled=True, key_files=[str(tmp_path / "nope.asc")], gnupg_home=verifier_home
        )
        with GpgVerifier(cfg) as verifier:
            with pytest.raises(GpgVerificationError, match="not found"):
                verifier.verify_detached(b"x", b"y")
