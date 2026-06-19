"""
Golden cross-check: parse and verify the header signature of a *real* RPM.

The synthetic parser test constructs its own RPM, so it cannot prove the
byte-layout matches what `rpm`/`rpmsign` actually produce. This test builds a
real package with `rpmbuild`, signs it with the real `rpm` toolchain, then
asserts that our pure-Python parser finds the header signature and that it
verifies against the signing key. Skipped where the rpm toolchain is absent
(e.g. macOS dev machines); runs in the RPM CI leg.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.e2e

_HAVE_RPM = bool(
    shutil.which("rpmbuild")
    and (shutil.which("rpmsign") or shutil.which("rpm"))
    and (shutil.which("gpg") or shutil.which("gpg2"))
)
# CI sets this for the RPM leg so a missing toolchain fails rather than silently
# skipping the only test that validates the byte layout against real rpm output.
_REQUIRED = bool(os.environ.get("CHANTAL_REQUIRE_RPM_E2E"))


@pytest.mark.skipif(
    not _HAVE_RPM and not _REQUIRED, reason="rpm/rpmbuild/gpg toolchain not available"
)
def test_real_signed_rpm_header_signature_verifies(tmp_path):
    if not _HAVE_RPM:
        pytest.fail("CHANTAL_REQUIRE_RPM_E2E is set but the rpm/rpmbuild/gpg toolchain is missing")

    import gnupg

    from chantal.core.config import SignatureVerificationConfig
    from chantal.core.gpg_verify import GpgVerifier
    from chantal.plugins.rpm.rpm_header import extract_header_signature

    # 1. Generate an ephemeral signing key.
    gnupghome = tmp_path / "gnupg"
    gnupghome.mkdir()
    os.chmod(gnupghome, 0o700)
    gpg = gnupg.GPG(gnupghome=str(gnupghome))
    gpg.encoding = "utf-8"
    key = gpg.gen_key(
        gpg.gen_key_input(
            name_real="Chantal RPM Test",
            name_email="rpm-test@chantal.local",
            key_type="RSA",
            key_length=3072,
            expire_date=0,
            no_protection=True,
        )
    )
    assert key.fingerprint, "failed to generate signing key"
    public_key = gpg.export_keys(key.fingerprint)
    assert public_key

    # 2. Build a minimal noarch package.
    spec = tmp_path / "demo.spec"
    spec.write_text(
        "Name: demo\n"
        "Version: 1.0\n"
        "Release: 1\n"
        "Summary: demo\n"
        "License: MIT\n"
        "BuildArch: noarch\n"
        "%description\n"
        "demo\n"
        "%files\n",
        encoding="utf-8",
    )
    topdir = tmp_path / "rpmbuild"
    build = subprocess.run(
        ["rpmbuild", "--define", f"_topdir {topdir}", "-bb", str(spec)],
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, f"rpmbuild failed:\n{build.stdout}\n{build.stderr}"
    rpms = list(topdir.rglob("*.rpm"))
    assert rpms, "rpmbuild produced no .rpm"
    rpm_path = rpms[0]

    # 3. Sign the package header with the real rpm toolchain.
    signer = "rpmsign" if shutil.which("rpmsign") else "rpm"
    sign = subprocess.run(
        [
            signer,
            "--define",
            "_gpg_name rpm-test@chantal.local",
            "--define",
            f"_gpg_path {gnupghome}",
            "--addsign",
            str(rpm_path),
        ],
        capture_output=True,
        text=True,
    )
    assert sign.returncode == 0, f"rpm --addsign failed:\n{sign.stdout}\n{sign.stderr}"

    # 4. Our parser must find the header signature, and it must verify.
    extracted = extract_header_signature(rpm_path.read_bytes())
    assert extracted is not None, "parser did not find the header signature in a real signed RPM"
    packet, header_blob = extracted

    cfg = SignatureVerificationConfig(
        enabled=True, keys=[public_key], gnupg_home=str(tmp_path / "verify")
    )
    with GpgVerifier(cfg) as verifier:
        assert verifier.verify_detached(header_blob, packet) is True
        # A modified header must not verify.
        tampered = bytearray(header_blob)
        tampered[len(tampered) // 2] ^= 0xFF
        assert verifier.verify_detached(bytes(tampered), packet) is False
