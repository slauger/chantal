"""
End-to-end test: APT upstream Release signature verification during sync.

Builds a signed apt repo (InRelease clearsigned + Release + Release.gpg), then
syncs with ``verify.enabled`` and asserts: a valid signature passes, a tampered
Release fails (on_invalid_signature=fail), and an untrusted key fails.

Needs the gpg toolchain; skipped where unavailable.
"""

from __future__ import annotations

import gzip
import hashlib
import shutil
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

_HAVE_GPG = shutil.which("gpg") is not None or shutil.which("gpg2") is not None

DIST = "jammy"
COMP = "main"
ARCH = "amd64"


def _short_home() -> str:
    base = "/tmp" if Path("/tmp").is_dir() else None
    return tempfile.mkdtemp(prefix="cg-", dir=base)


def _build_signed_apt_upstream(
    root: Path,
    *,
    tamper: bool = False,
    with_inrelease: bool = True,
    with_release_gpg: bool = True,
) -> str:
    """Build a GPG-signed apt repo; return the upstream public key (armored)."""
    from chantal.core.config import GpgConfig
    from chantal.core.gpg import GpgSigner

    deb_rel = f"pool/{COMP}/d/demo/demo_1.0_{ARCH}.deb"
    deb_path = root / deb_rel
    deb_path.parent.mkdir(parents=True, exist_ok=True)
    deb = b"dummy deb payload" * 16
    deb_path.write_bytes(deb)

    packages = (
        "Package: demo\n"
        "Version: 1.0\n"
        f"Architecture: {ARCH}\n"
        "Maintainer: Test <test@example.com>\n"
        f"Filename: {deb_rel}\n"
        f"Size: {len(deb)}\n"
        f"SHA256: {hashlib.sha256(deb).hexdigest()}\n"
        "Description: demo package\n"
        "\n"
    ).encode()

    comp_dir = root / "dists" / DIST / COMP / f"binary-{ARCH}"
    comp_dir.mkdir(parents=True, exist_ok=True)
    (comp_dir / "Packages").write_bytes(packages)
    packages_gz = gzip.compress(packages)
    (comp_dir / "Packages.gz").write_bytes(packages_gz)

    rel_pkgs = f"{COMP}/binary-{ARCH}/Packages"
    sha = hashlib.sha256
    release = (
        "Origin: Test\n"
        "Label: Test\n"
        f"Suite: {DIST}\n"
        f"Codename: {DIST}\n"
        f"Components: {COMP}\n"
        f"Architectures: {ARCH}\n"
        "Date: Thu, 01 Jan 2026 00:00:00 UTC\n"
        "SHA256:\n"
        f" {sha(packages).hexdigest()} {len(packages)} {rel_pkgs}\n"
        f" {sha(packages_gz).hexdigest()} {len(packages_gz)} {rel_pkgs}.gz\n"
    ).encode()

    home = _short_home()
    signer = GpgSigner(GpgConfig(generate_key=True, gnupg_home=home, key_email="vendor@upstream"))
    try:
        pub = signer.export_public_key().decode("utf-8")
        inrelease = signer.clearsign(release)
        release_gpg = signer.detach_sign(release)
    finally:
        signer.close()

    dist_dir = root / "dists" / DIST
    if tamper:
        # Corrupt the signed payload: the signature no longer matches.
        inrelease = inrelease.replace(b"Origin: Test", b"Origin: Evil")
    if with_inrelease:
        (dist_dir / "InRelease").write_bytes(inrelease)
    (dist_dir / "Release").write_bytes(release)
    if with_release_gpg:
        (dist_dir / "Release.gpg").write_bytes(release_gpg)

    shutil.rmtree(home, ignore_errors=True)
    return pub


def _config(repo_id: str, base_url: str, pub: str, **verify_extra) -> dict:
    return {
        "id": repo_id,
        "name": repo_id,
        "type": "apt",
        "feed": base_url,
        "enabled": True,
        "mode": "filtered",
        "apt": {"distribution": DIST, "components": [COMP], "architectures": [ARCH]},
        "verify": {"enabled": True, "keys": [pub], **verify_extra},
    }


@pytest.mark.skipif(not _HAVE_GPG, reason="gpg toolchain not available")
def test_apt_verify_valid_signature_syncs(tmp_path, serve, chantal_env):
    upstream = tmp_path / "upstream"
    pub = _build_signed_apt_upstream(upstream)
    base_url = serve(upstream)

    chantal_env.write_config(_config("demo-apt-verified", base_url, pub))
    target = chantal_env.sync_and_publish("demo-apt-verified")

    assert (target / "dists" / DIST / "Release").exists()
    assert list(target.rglob("demo_1.0_amd64.deb")), "published .deb not found"


@pytest.mark.skipif(not _HAVE_GPG, reason="gpg toolchain not available")
def test_apt_verify_tampered_release_fails(tmp_path, serve, chantal_env):
    upstream = tmp_path / "upstream"
    pub = _build_signed_apt_upstream(upstream, tamper=True)
    base_url = serve(upstream)

    chantal_env.write_config(_config("demo-apt-tampered", base_url, pub))
    result = chantal_env.run("repo", "sync", "--repo-id", "demo-apt-tampered", "-v", check=False)

    output = (result.stdout + result.stderr).lower()
    assert "signature verification failed" in output, "verification failure not reported"
    # The sync must abort before trusting metadata / downloading packages.
    assert not list(chantal_env.pool.rglob("*.deb")), "no .deb should be synced on bad signature"


@pytest.mark.skipif(not _HAVE_GPG, reason="gpg toolchain not available")
def test_apt_verify_untrusted_key_fails(tmp_path, serve, chantal_env):
    upstream = tmp_path / "upstream"
    _build_signed_apt_upstream(upstream)  # signed by the real upstream key
    base_url = serve(upstream)

    # Configure a DIFFERENT trusted key than the one that signed.
    other_home = _short_home()
    from chantal.core.config import GpgConfig
    from chantal.core.gpg import GpgSigner

    other = GpgSigner(GpgConfig(generate_key=True, gnupg_home=other_home, key_email="x@y"))
    try:
        other_pub = other.export_public_key().decode("utf-8")
    finally:
        other.close()
        shutil.rmtree(other_home, ignore_errors=True)

    chantal_env.write_config(_config("demo-apt-untrusted", base_url, other_pub))
    result = chantal_env.run("repo", "sync", "--repo-id", "demo-apt-untrusted", "-v", check=False)

    output = (result.stdout + result.stderr).lower()
    assert "signature verification failed" in output, "verification failure not reported"
    assert not list(chantal_env.pool.rglob("*.deb")), "no .deb should be synced on untrusted key"


@pytest.mark.skipif(not _HAVE_GPG, reason="gpg toolchain not available")
def test_apt_verify_detached_release_syncs(tmp_path, serve, chantal_env):
    # No InRelease: the detached Release + Release.gpg path must verify.
    upstream = tmp_path / "upstream"
    pub = _build_signed_apt_upstream(upstream, with_inrelease=False)
    base_url = serve(upstream)

    chantal_env.write_config(_config("demo-apt-detached", base_url, pub))
    target = chantal_env.sync_and_publish("demo-apt-detached")
    assert list(target.rglob("demo_1.0_amd64.deb")), "detached-verified .deb not published"


@pytest.mark.skipif(not _HAVE_GPG, reason="gpg toolchain not available")
def test_apt_verify_missing_signature_fails(tmp_path, serve, chantal_env):
    # No InRelease and no Release.gpg: on_missing_signature=fail must abort.
    upstream = tmp_path / "upstream"
    pub = _build_signed_apt_upstream(upstream, with_inrelease=False, with_release_gpg=False)
    base_url = serve(upstream)

    chantal_env.write_config(_config("demo-apt-nosig", base_url, pub))
    result = chantal_env.run("repo", "sync", "--repo-id", "demo-apt-nosig", "-v", check=False)

    output = (result.stdout + result.stderr).lower()
    assert "signature verification failed" in output, "missing-signature failure not reported"
    assert not list(chantal_env.pool.rglob("*.deb")), "no .deb should be synced without a signature"


@pytest.mark.skipif(not _HAVE_GPG, reason="gpg toolchain not available")
def test_apt_verify_warn_policy_continues(tmp_path, serve, chantal_env):
    # on_invalid_signature=warn: a bad signature warns but the sync proceeds.
    upstream = tmp_path / "upstream"
    pub = _build_signed_apt_upstream(upstream, tamper=True)
    base_url = serve(upstream)

    chantal_env.write_config(_config("demo-apt-warn", base_url, pub, on_invalid_signature="warn"))
    target = chantal_env.sync_and_publish("demo-apt-warn")
    assert list(target.rglob("demo_1.0_amd64.deb")), "warn policy should not block the sync"
