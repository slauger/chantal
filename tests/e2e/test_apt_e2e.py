"""End-to-end sync->publish test for the APT/DEB plugin."""

from __future__ import annotations

import gzip
import hashlib
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

DIST = "jammy"
COMP = "main"
ARCH = "amd64"


def _build_apt_upstream(root: Path) -> None:
    """Create a minimal APT repo (Release + Packages(.gz) + one .deb)."""
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
    )
    (root / "dists" / DIST / "Release").write_text(release, encoding="utf-8")


def test_apt_sync_and_publish(tmp_path, serve, chantal_env):
    upstream = tmp_path / "upstream"
    _build_apt_upstream(upstream)
    base_url = serve(upstream)

    chantal_env.write_config(
        {
            "id": "demo-apt",
            "name": "Demo APT",
            "type": "apt",
            "feed": base_url,
            "enabled": True,
            "mode": "filtered",
            "apt": {
                "distribution": DIST,
                "components": [COMP],
                "architectures": [ARCH],
            },
        }
    )

    target = chantal_env.sync_and_publish("demo-apt")

    # Release + Packages were regenerated and the .deb was published.
    assert (target / "dists" / DIST / "Release").exists()
    assert list(target.rglob("Packages")), "published Packages index not found"
    assert list(target.rglob("demo_1.0_amd64.deb")), "published .deb not found"
