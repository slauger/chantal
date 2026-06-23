"""
End-to-end test: ``Architecture: all`` packages.

An arch-independent package is listed in every per-arch ``Packages`` index by
Debian convention, and apt clients only read ``binary-<their-arch>/Packages``.
chantal must therefore (a) download the shared .deb once (no crash on the
duplicate sha256) and (b) publish it into every configured per-arch index, not
a lone ``binary-all``.
"""

from __future__ import annotations

import gzip
import hashlib
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

DIST = "jammy"
COMP = "main"
ARCHES = ["amd64", "arm64"]


def _build_upstream(root: Path) -> None:
    # One Architecture: all package (shared across both arch indices) + one
    # regular amd64 package.
    alldeb_rel = f"pool/{COMP}/d/demo-doc/demo-doc_1.0_all.deb"
    (root / alldeb_rel).parent.mkdir(parents=True, exist_ok=True)
    alldeb = b"arch-all doc payload" * 16
    (root / alldeb_rel).write_bytes(alldeb)

    amd_rel = f"pool/{COMP}/d/demo/demo_1.0_amd64.deb"
    (root / amd_rel).parent.mkdir(parents=True, exist_ok=True)
    amddeb = b"amd64 payload" * 16
    (root / amd_rel).write_bytes(amddeb)

    def _stanza(pkg, ver, arch, rel, data):
        return (
            f"Package: {pkg}\nVersion: {ver}\nArchitecture: {arch}\n"
            f"Filename: {rel}\nSize: {len(data)}\n"
            f"SHA256: {hashlib.sha256(data).hexdigest()}\nDescription: {pkg}\n\n"
        )

    all_stanza = _stanza("demo-doc", "1.0", "all", alldeb_rel, alldeb)
    indices = {}  # rel-path -> (packages bytes, packages.gz bytes)
    for arch in ARCHES:
        pkgs = all_stanza  # arch:all appears in EVERY arch index
        if arch == "amd64":
            pkgs += _stanza("demo", "1.0", "amd64", amd_rel, amddeb)
        pkgs_b = pkgs.encode()
        comp_dir = root / "dists" / DIST / COMP / f"binary-{arch}"
        comp_dir.mkdir(parents=True, exist_ok=True)
        (comp_dir / "Packages").write_bytes(pkgs_b)
        gz = gzip.compress(pkgs_b)
        (comp_dir / "Packages.gz").write_bytes(gz)
        indices[f"{COMP}/binary-{arch}/Packages"] = pkgs_b
        indices[f"{COMP}/binary-{arch}/Packages.gz"] = gz

    sha = hashlib.sha256
    lines = "".join(
        f" {sha(data).hexdigest()} {len(data)} {path}\n" for path, data in indices.items()
    )
    release = (
        f"Origin: Upstream\nSuite: {DIST}\nCodename: {DIST}\nComponents: {COMP}\n"
        f"Architectures: {' '.join(ARCHES)}\n"
        "Date: Thu, 01 Jan 2026 00:00:00 UTC\nSHA256:\n" + lines
    )
    (root / "dists" / DIST / "Release").write_text(release, encoding="utf-8")


def test_apt_arch_all_fanned_into_every_arch(tmp_path, serve, chantal_env):
    upstream = tmp_path / "upstream"
    _build_upstream(upstream)
    base_url = serve(upstream)

    chantal_env.write_config(
        {
            "id": "demo-apt-all",
            "name": "Demo APT arch:all",
            "type": "apt",
            "feed": base_url,
            "enabled": True,
            "mode": "filtered",
            "apt": {"distribution": DIST, "components": [COMP], "architectures": ARCHES},
        }
    )

    target = chantal_env.sync_and_publish("demo-apt-all")
    dist = target / "dists" / DIST / COMP

    # The arch:all package appears in EVERY per-arch index...
    for arch in ARCHES:
        packages = (dist / f"binary-{arch}" / "Packages").read_text()
        assert "Package: demo-doc" in packages, f"arch:all missing from binary-{arch}"
        assert "Architecture: all" in packages

    # ...and there is no lone binary-all index.
    assert not (dist / "binary-all").exists(), "arch:all must be fanned out, not binary-all"

    # The shared .deb is pooled once and its Filename resolves.
    pooled = list((target / "pool").rglob("demo-doc_1.0_all.deb"))
    assert len(pooled) == 1, f"arch:all .deb should be pooled once, got {len(pooled)}"
    amd_packages = (dist / "binary-amd64" / "Packages").read_text()
    for line in amd_packages.splitlines():
        if line.startswith("Filename:") and "demo-doc" in line:
            fn = line.split(": ", 1)[1].strip()
            assert (target / fn).is_file(), f"arch:all Filename does not resolve: {fn}"

    # Release lists only real arches (not 'all').
    release = (target / "dists" / DIST / "Release").read_text()
    arch_line = next(line for line in release.splitlines() if line.startswith("Architectures:"))
    assert "all" not in arch_line.split()[1:], "Architectures must not list 'all'"
