"""
End-to-end test: APT Contents-<arch> index mirroring.

With ``include_contents: true`` in MIRROR mode the Contents index is downloaded
and republished verbatim at its component path; the (verbatim upstream) Release
references it.
In FILTERED mode Contents are dropped (regenerating one would need per-.deb file
lists chantal does not extract).
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


def _build_apt_upstream_with_contents(root: Path) -> None:
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

    # Component-scoped Contents index (file -> package mapping).
    contents = b"usr/bin/demo    main/demo\nusr/share/doc/demo/README    main/demo\n"
    contents_gz = gzip.compress(contents)
    (root / "dists" / DIST / COMP / f"Contents-{ARCH}.gz").write_bytes(contents_gz)

    sha = hashlib.sha256

    def _rel(path, data):
        return f" {sha(data).hexdigest()} {len(data)} {path}\n"

    release = (
        "Origin: Test\n"
        f"Suite: {DIST}\n"
        f"Codename: {DIST}\n"
        f"Components: {COMP}\n"
        f"Architectures: {ARCH}\n"
        "Date: Thu, 01 Jan 2026 00:00:00 UTC\n"
        "SHA256:\n"
        + _rel(f"{COMP}/binary-{ARCH}/Packages", packages)
        + _rel(f"{COMP}/binary-{ARCH}/Packages.gz", packages_gz)
        + _rel(f"{COMP}/Contents-{ARCH}.gz", contents_gz)
    )
    (root / "dists" / DIST / "Release").write_text(release, encoding="utf-8")


def _config(repo_id: str, base_url: str, mode: str) -> dict:
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
            "include_contents": True,
        },
    }


def test_apt_contents_mirror_published(tmp_path, serve, chantal_env):
    upstream = tmp_path / "upstream"
    _build_apt_upstream_with_contents(upstream)
    base_url = serve(upstream)

    chantal_env.write_config(_config("demo-apt-contents", base_url, "mirror"))
    target = chantal_env.sync_and_publish("demo-apt-contents")

    # Republished at the correct component path (not flattened to the suite root).
    published = target / "dists" / DIST / COMP / f"Contents-{ARCH}.gz"
    assert published.exists(), "Contents index not republished at component path"
    assert not (target / "dists" / DIST / f"Contents-{ARCH}.gz").exists(), "Contents flattened"

    # Release references the Contents index with a matching checksum.
    release_text = (target / "dists" / DIST / "Release").read_text()
    assert f"{COMP}/Contents-{ARCH}.gz" in release_text, "Release does not reference Contents"
    expected_sha = hashlib.sha256(published.read_bytes()).hexdigest()
    assert expected_sha in release_text, "Release Contents checksum mismatch"


def test_apt_contents_dropped_in_filtered_mode(tmp_path, serve, chantal_env):
    upstream = tmp_path / "upstream"
    _build_apt_upstream_with_contents(upstream)
    base_url = serve(upstream)

    chantal_env.write_config(_config("demo-apt-contents-filtered", base_url, "filtered"))
    target = chantal_env.sync_and_publish("demo-apt-contents-filtered")

    assert not list(target.rglob("Contents-*")), "Contents must be dropped in filtered mode"
    release_text = (target / "dists" / DIST / "Release").read_text()
    assert "Contents-" not in release_text, "filtered Release must not reference Contents"
