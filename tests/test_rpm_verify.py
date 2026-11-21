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

    def test_gpgcheck_accepted(self):
        cfg = SignatureVerificationConfig(enabled=True, keys=["k"], gpgcheck=True)
        assert cfg.gpgcheck is True

    def test_gpgcheck_requires_repo_gpgcheck(self):
        with pytest.raises(ValueError, match="requires repo_gpgcheck"):
            SignatureVerificationConfig(
                enabled=True, keys=["k"], gpgcheck=True, repo_gpgcheck=False
            )

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


# --------------------------------------------------------------------------- #
# RPM header parsing + package signature verification
# --------------------------------------------------------------------------- #

import struct  # noqa: E402

from chantal.plugins.rpm.rpm_header import (  # noqa: E402
    RPMTAG_RSAHEADER,
    RpmFormatError,
    extract_header_signature,
)

_LEAD = b"\xed\xab\xee\xdb" + b"\x00" * 92  # 96-byte lead


def _build_header(items: list[tuple[int, bytes]]) -> bytes:
    """Serialize a minimal RPM 'header' structure from (tag, raw_bytes) items."""
    index = b""
    store = b""
    for tag, raw in items:
        index += struct.pack(">IIII", tag, 7, len(store), len(raw))  # type 7 = BIN
        store += raw
    intro = b"\x8e\xad\xe8\x01" + b"\x00" * 4 + struct.pack(">II", len(items), len(store))
    return intro + index + store


def _build_rpm(main_blob: bytes, sig_packet: bytes) -> bytes:
    """Assemble lead + signature header (RSAHEADER) + padding + main header."""
    sig_header = _build_header([(RPMTAG_RSAHEADER, sig_packet)])
    sig_end = _LEAD_SIZE_LOCAL + len(sig_header)
    pad = b"\x00" * (-sig_end % 8)
    return _LEAD + sig_header + pad + main_blob


_LEAD_SIZE_LOCAL = 96


class TestRpmHeaderParser:
    def test_extract_round_trip(self):
        main_blob = _build_header([(1000, b"name=demo\x00"), (1001, b"1.0\x00")])
        rpm = _build_rpm(main_blob, b"FAKE-SIGNATURE-PACKET")
        result = extract_header_signature(rpm)
        assert result is not None
        sig, blob = result
        assert sig == b"FAKE-SIGNATURE-PACKET"
        assert blob == main_blob

    def test_unsigned_returns_none(self):
        main_blob = _build_header([(1000, b"x")])
        # signature header with a non-signature tag only
        sig_header = _build_header([(1004, b"\x00" * 16)])  # MD5-ish, not a header sig
        sig_end = 96 + len(sig_header)
        rpm = _LEAD + sig_header + b"\x00" * (-sig_end % 8) + main_blob
        assert extract_header_signature(rpm) is None

    def test_not_an_rpm_raises(self):
        with pytest.raises(RpmFormatError, match="bad lead magic"):
            extract_header_signature(b"not an rpm" * 20)


class TestPackageSignatureVerification:
    def test_valid_package_signature(self, upstream_signer, verifier_home):
        main_blob = _build_header([(1000, b"demo-1.0\x00")])
        sig = upstream_signer.detach_sign(main_blob)  # detached OpenPGP signature
        rpm = _build_rpm(main_blob, sig)
        pub = upstream_signer.export_public_key().decode("utf-8")

        extracted = extract_header_signature(rpm)
        assert extracted is not None
        packet, blob = extracted
        with GpgVerifier(_verify_config(pub, verifier_home)) as verifier:
            assert verifier.verify_detached(blob, packet) is True

    def test_tampered_header_fails(self, upstream_signer, verifier_home):
        main_blob = _build_header([(1000, b"demo-1.0\x00")])
        sig = upstream_signer.detach_sign(main_blob)
        rpm = bytearray(_build_rpm(main_blob, sig))
        rpm[-1] ^= 0xFF  # corrupt the last byte of the main header blob
        pub = upstream_signer.export_public_key().decode("utf-8")

        extracted = extract_header_signature(bytes(rpm))
        assert extracted is not None
        packet, blob = extracted
        with GpgVerifier(_verify_config(pub, verifier_home)) as verifier:
            assert verifier.verify_detached(blob, packet) is False


# --------------------------------------------------------------------------- #
# rpm >= 6: RPMSIGTAG_OPENPGP (278), base64 signatures in a string array
# --------------------------------------------------------------------------- #

import base64  # noqa: E402

from chantal.plugins.rpm.rpm_header import (  # noqa: E402
    RPMTAG_OPENPGP,
    extract_header_signatures,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "rpm"


def _build_rpm6(main_blob: bytes, sig_packets: list[bytes]) -> bytes:
    """Lead + signature header with an OPENPGP string array + main header."""
    store = b"".join(base64.b64encode(p) + b"\x00" for p in sig_packets)
    index = struct.pack(">IIII", RPMTAG_OPENPGP, 8, 0, len(sig_packets))  # 8 = STRING_ARRAY
    sig_header = b"\x8e\xad\xe8\x01" + b"\x00" * 4 + struct.pack(">II", 1, len(store))
    sig_header += index + store
    pad = b"\x00" * (-(96 + len(sig_header)) % 8)
    return _LEAD + sig_header + pad + main_blob


@pytest.fixture
def other_signer():
    """A second signer whose key is not trusted by the verifier."""
    home = _short_home()
    signer = GpgSigner(GpgConfig(generate_key=True, gnupg_home=home, key_email="other@elsewhere"))
    _ = signer.key_id
    yield signer
    signer.close()
    shutil.rmtree(home, ignore_errors=True)


class TestRpm6Signatures:
    def test_real_rpm6_signed_package_verifies(self, verifier_home):
        """A package signed by rpm 6.0.1 (no RSAHEADER/DSAHEADER) verifies."""
        rpm = (_FIXTURES / "demo-1.0-1.noarch.rpm6-signed.rpm").read_bytes()
        pub = (_FIXTURES / "rpm6-signing-key.asc").read_text()

        extracted = extract_header_signatures(rpm)
        assert extracted is not None, "rpm 6 OPENPGP header signature not found"
        packets, blob = extracted
        assert len(packets) == 1
        assert extract_header_signature(rpm) == (packets[0], blob)
        with GpgVerifier(_verify_config(pub, verifier_home)) as verifier:
            assert verifier.verify_detached(blob, packets[0]) is True
            tampered = bytearray(blob)
            tampered[len(tampered) // 2] ^= 0xFF
            assert verifier.verify_detached(bytes(tampered), packets[0]) is False

    def test_multiple_signatures_are_decoded_in_order(self):
        main_blob = _build_header([(1000, b"demo\x00")])
        rpm = _build_rpm6(main_blob, [b"\x88first", b"\x88second"])
        assert extract_header_signatures(rpm) == ([b"\x88first", b"\x88second"], main_blob)

    def test_signature_count_is_capped(self):
        """A crafted package cannot make sync run thousands of gpg verifications."""
        from chantal.plugins.rpm.rpm_header import MAX_HEADER_SIGNATURES

        main_blob = _build_header([(1000, b"demo\x00")])
        extracted = extract_header_signatures(_build_rpm6(main_blob, [b"\x88"] * 32))
        assert extracted is not None and len(extracted[0]) == MAX_HEADER_SIGNATURES == 32
        with pytest.raises(RpmFormatError, match="more than"):
            extract_header_signatures(_build_rpm6(main_blob, [b"\x88"] * 200_000))

    def test_invalid_base64_raises(self):
        main_blob = _build_header([(1000, b"demo\x00")])
        rpm = bytearray(_build_rpm6(main_blob, [b"\x88sig"]))
        start = rpm.index(base64.b64encode(b"\x88sig"))
        rpm[start] = ord("!")
        with pytest.raises(RpmFormatError, match="base64"):
            extract_header_signatures(bytes(rpm))

    @pytest.mark.parametrize("trusted_included", [True, False])
    def test_sync_accepts_one_trusted_signature(
        self, upstream_signer, other_signer, verifier_home, tmp_path, trusted_included
    ):
        """Like rpm, a package passes gpgcheck if any of its signatures is valid
        and trusted (e.g. signed with an old and a new key during rotation)."""
        from chantal.core.config import RepositoryConfig
        from chantal.core.gpg_verify import SignatureVerificationError
        from chantal.plugins.rpm.sync import RpmSyncPlugin

        main_blob = _build_header([(1000, b"demo-1.0\x00")])
        sigs = [other_signer.detach_sign(main_blob)]
        if trusted_included:
            sigs.append(upstream_signer.detach_sign(main_blob))
        rpm_path = tmp_path / "demo.rpm"
        rpm_path.write_bytes(_build_rpm6(main_blob, sigs))

        pub = upstream_signer.export_public_key().decode("utf-8")
        config = RepositoryConfig(
            id="r",
            name="r",
            type="rpm",
            feed="http://example.com/repo",
            verify={"enabled": True, "keys": [pub], "gnupg_home": verifier_home},
        )
        plugin = RpmSyncPlugin(storage=None, config=config)
        plugin._setup_package_verifier()
        try:
            if trusted_included:
                plugin._verify_package_signature(rpm_path, "demo-1.0")
            else:
                with pytest.raises(SignatureVerificationError, match="untrusted"):
                    plugin._verify_package_signature(rpm_path, "demo-1.0")
        finally:
            plugin._teardown_package_verifier()
