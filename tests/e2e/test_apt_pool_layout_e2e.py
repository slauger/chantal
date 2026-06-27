"""
End-to-end test: published APT repos use a real ``pool/`` layout.

Package files must live under ``pool/`` at the repository root (not inside
``dists/``), and each ``Filename:`` in Packages must resolve to the actual file
— otherwise a real apt client cannot download/install packages. (Validated
against real apt separately; this locks the layout invariant in CI.)
"""

from __future__ import annotations

import gzip
import hashlib
from pathlib import Path

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.apt]

DIST = "jammy"
COMP = "main"
ARCH = "amd64"


def _build_apt_upstream(root: Path) -> None:
    deb_rel = f"pool/{COMP}/d/demo/demo_1.0_{ARCH}.deb"
    (root / deb_rel).parent.mkdir(parents=True, exist_ok=True)
    deb = b"dummy deb payload" * 16
    (root / deb_rel).write_bytes(deb)

    packages = (
        "Package: demo\n"
        "Version: 1.0\n"
        f"Architecture: {ARCH}\n"
        f"Filename: {deb_rel}\n"
        f"Size: {len(deb)}\n"
        f"SHA256: {hashlib.sha256(deb).hexdigest()}\n"
        "Description: demo\n"
        "\n"
    ).encode()
    comp_dir = root / "dists" / DIST / COMP / f"binary-{ARCH}"
    comp_dir.mkdir(parents=True, exist_ok=True)
    (comp_dir / "Packages").write_bytes(packages)
    packages_gz = gzip.compress(packages)
    (comp_dir / "Packages.gz").write_bytes(packages_gz)

    sha = hashlib.sha256
    release = (
        f"Origin: Upstream\nSuite: {DIST}\nCodename: {DIST}\n"
        f"Components: {COMP}\nArchitectures: {ARCH}\n"
        "Date: Thu, 01 Jan 2026 00:00:00 UTC\nSHA256:\n"
        f" {sha(packages).hexdigest()} {len(packages)} {COMP}/binary-{ARCH}/Packages\n"
        f" {sha(packages_gz).hexdigest()} {len(packages_gz)} {COMP}/binary-{ARCH}/Packages.gz\n"
    )
    (root / "dists" / DIST / "Release").write_text(release, encoding="utf-8")


def test_apt_pool_layout(tmp_path, serve, chantal_env):
    upstream = tmp_path / "upstream"
    _build_apt_upstream(upstream)
    base_url = serve(upstream)

    chantal_env.write_config(
        {
            "id": "demo-apt-pool",
            "name": "Demo APT pool",
            "type": "apt",
            "feed": base_url,
            "enabled": True,
            "mode": "filtered",
            "apt": {"distribution": DIST, "components": [COMP], "architectures": [ARCH]},
        }
    )

    target = chantal_env.sync_and_publish("demo-apt-pool")

    # The .deb lives under pool/, not under dists/.
    pool_debs = list((target / "pool").rglob("*.deb"))
    assert pool_debs, "no .deb under pool/"
    assert not list((target / "dists").rglob("*.deb")), ".deb must not live under dists/"

    # Every Filename in Packages is pool-relative AND resolves to a real file.
    packages = (target / "dists" / DIST / COMP / f"binary-{ARCH}" / "Packages").read_text()
    filenames = [
        line.split(": ", 1)[1].strip()
        for line in packages.splitlines()
        if line.startswith("Filename:")
    ]
    assert filenames, "no Filename entries in Packages"
    for fn in filenames:
        assert fn.startswith("pool/"), f"Filename not pool-relative: {fn}"
        # The key invariant: Filename (repo-root-relative) must resolve.
        assert (target / fn).is_file(), f"Filename does not resolve: {fn}"
