"""
End-to-end test: APT by-hash support.

Acquisition: with ``by_hash: true`` sync fetches indices from
``by-hash/SHA256/<checksum>`` (falling back to the plain path). Publishing:
emit ``by-hash/SHA256/`` copies of every regenerated index and set
``Acquire-By-Hash: yes`` in the generated Release.
"""

from __future__ import annotations

import gzip
import hashlib
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

DIST = "jammy"
COMP = "main"
ARCH = "amd64"


def _packages_and_release(root: Path):
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
    packages_gz = gzip.compress(packages)

    def _rel(path, data):
        return f" {hashlib.sha256(data).hexdigest()} {len(data)} {path}\n"

    release = (
        "Origin: Test\n"
        f"Suite: {DIST}\n"
        f"Codename: {DIST}\n"
        f"Components: {COMP}\n"
        f"Architectures: {ARCH}\n"
        "Date: Thu, 01 Jan 2026 00:00:00 UTC\n"
        "Acquire-By-Hash: yes\n"
        "SHA256:\n" + _rel(f"{COMP}/binary-{ARCH}/Packages.gz", packages_gz)
    )
    dist_dir = root / "dists" / DIST
    dist_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "Release").write_text(release, encoding="utf-8")
    return packages_gz


def _build_byhash_only_upstream(root: Path) -> None:
    """Serve Packages.gz ONLY under by-hash/SHA256 (plain path 404s)."""
    packages_gz = _packages_and_release(root)
    comp_dir = root / "dists" / DIST / COMP / f"binary-{ARCH}"
    by_hash = comp_dir / "by-hash" / "SHA256"
    by_hash.mkdir(parents=True, exist_ok=True)
    (by_hash / hashlib.sha256(packages_gz).hexdigest()).write_bytes(packages_gz)
    # Note: the plain Packages.gz is intentionally NOT written.


def _build_plain_upstream(root: Path) -> None:
    packages_gz = _packages_and_release(root)
    comp_dir = root / "dists" / DIST / COMP / f"binary-{ARCH}"
    comp_dir.mkdir(parents=True, exist_ok=True)
    (comp_dir / "Packages.gz").write_bytes(packages_gz)


def _config(repo_id, base_url, mode, by_hash):
    return {
        "id": repo_id,
        "name": repo_id,
        "type": "apt",
        "feed": base_url,
        "enabled": True,
        "mode": mode,
        "apt": {
            "distribution": DIST,
            "components": [COMP],
            "architectures": [ARCH],
            "by_hash": by_hash,
        },
    }


def test_apt_byhash_acquisition(tmp_path, serve, chantal_env):
    # Upstream serves the index only via by-hash; sync must fetch it there.
    upstream = tmp_path / "upstream"
    _build_byhash_only_upstream(upstream)
    base_url = serve(upstream)

    chantal_env.write_config(_config("demo-apt-byhash-acq", base_url, "mirror", True))
    target = chantal_env.sync_and_publish("demo-apt-byhash-acq")
    assert list(target.rglob("demo_1.0_amd64.deb")), "by-hash index not fetched / package missing"


def test_apt_byhash_acquisition_disabled_fails(tmp_path, serve, chantal_env):
    # Without by_hash the plain path 404s, so no package is synced.
    upstream = tmp_path / "upstream"
    _build_byhash_only_upstream(upstream)
    base_url = serve(upstream)

    chantal_env.write_config(_config("demo-apt-byhash-off", base_url, "mirror", False))
    chantal_env.run("repo", "sync", "--repo-id", "demo-apt-byhash-off", "-v", check=False)
    assert not list(chantal_env.pool.rglob("*.deb")), "plain-path 404 should yield no package"


def test_apt_byhash_publishing(tmp_path, serve, chantal_env):
    upstream = tmp_path / "upstream"
    _build_plain_upstream(upstream)
    base_url = serve(upstream)

    chantal_env.write_config(_config("demo-apt-byhash-pub", base_url, "mirror", True))
    target = chantal_env.sync_and_publish("demo-apt-byhash-pub")

    comp_dir = target / "dists" / DIST / COMP / f"binary-{ARCH}"
    by_hash = comp_dir / "by-hash" / "SHA256"
    assert by_hash.is_dir(), "by-hash/SHA256 dir not created"

    # Every regenerated index has a by-hash copy named by its own sha256.
    for index in ("Packages", "Packages.gz"):
        idx = comp_dir / index
        assert idx.exists()
        sha = hashlib.sha256(idx.read_bytes()).hexdigest()
        copy = by_hash / sha
        assert copy.exists(), f"by-hash copy missing for {index}"
        assert hashlib.sha256(copy.read_bytes()).hexdigest() == sha

    release_text = (target / "dists" / DIST / "Release").read_text()
    assert "Acquire-By-Hash: yes" in release_text


def test_apt_byhash_publishing_filtered(tmp_path, serve, chantal_env):
    # by-hash publishing also applies in filtered mode (Release regenerated).
    upstream = tmp_path / "upstream"
    _build_plain_upstream(upstream)
    base_url = serve(upstream)

    chantal_env.write_config(_config("demo-apt-byhash-filt", base_url, "filtered", True))
    target = chantal_env.sync_and_publish("demo-apt-byhash-filt")

    comp_dir = target / "dists" / DIST / COMP / f"binary-{ARCH}"
    by_hash = comp_dir / "by-hash" / "SHA256"
    assert by_hash.is_dir(), "by-hash not emitted in filtered mode"
    pkg = comp_dir / "Packages"
    assert (by_hash / hashlib.sha256(pkg.read_bytes()).hexdigest()).exists()
    assert "Acquire-By-Hash: yes" in (target / "dists" / DIST / "Release").read_text()


def test_apt_byhash_prune_stale(tmp_path, serve, chantal_env):
    # Re-publishing prunes stale content-addressed entries from a prior publish.
    upstream = tmp_path / "upstream"
    _build_plain_upstream(upstream)
    base_url = serve(upstream)

    chantal_env.write_config(_config("demo-apt-byhash-prune", base_url, "mirror", True))
    target = chantal_env.sync_and_publish("demo-apt-byhash-prune")

    comp_dir = target / "dists" / DIST / COMP / f"binary-{ARCH}"
    by_hash = comp_dir / "by-hash" / "SHA256"
    stale = by_hash / ("0" * 64)
    stale.write_bytes(b"stale entry from a previous publish")

    chantal_env.run(
        "publish", "repo", "--repo-id", "demo-apt-byhash-prune", "--target", str(target)
    )

    assert not stale.exists(), "stale by-hash entry not pruned on republish"
    # The current index still has its by-hash entry.
    pkg_gz = comp_dir / "Packages.gz"
    assert (by_hash / hashlib.sha256(pkg_gz.read_bytes()).hexdigest()).exists()


def test_apt_byhash_disabled_no_dirs(tmp_path, serve, chantal_env):
    upstream = tmp_path / "upstream"
    _build_plain_upstream(upstream)
    base_url = serve(upstream)

    chantal_env.write_config(_config("demo-apt-byhash-none", base_url, "mirror", False))
    target = chantal_env.sync_and_publish("demo-apt-byhash-none")

    assert not list(target.rglob("by-hash")), "no by-hash dirs when disabled"
    release_text = (target / "dists" / DIST / "Release").read_text()
    assert "Acquire-By-Hash" not in release_text
