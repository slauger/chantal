"""
End-to-end test: APT i18n Translation mirroring.

With ``include_translations: true`` in MIRROR mode the Translation files and the
``i18n/Index`` are downloaded, republished at their component i18n path, and
referenced in the regenerated Release. FILTERED mode drops them.
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


def _build_apt_upstream_with_translations(root: Path) -> None:
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

    # i18n Translation file + Index.
    i18n_dir = root / "dists" / DIST / COMP / "i18n"
    i18n_dir.mkdir(parents=True, exist_ok=True)
    translation = b"Package: demo\nDescription-md5: 0123456789abcdef\nDescription-en: A demo\n"
    translation_gz = gzip.compress(translation)
    (i18n_dir / "Translation-en.gz").write_bytes(translation_gz)
    index = (
        b"SHA256:\n"
        + f" {hashlib.sha256(translation_gz).hexdigest()} {len(translation_gz)} Translation-en.gz\n".encode()
    )
    (i18n_dir / "Index").write_bytes(index)

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
        + _rel(f"{COMP}/i18n/Translation-en.gz", translation_gz)
        + _rel(f"{COMP}/i18n/Index", index)
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
            "include_translations": True,
        },
    }


def test_apt_translation_mirror_published(tmp_path, serve, chantal_env):
    upstream = tmp_path / "upstream"
    _build_apt_upstream_with_translations(upstream)
    base_url = serve(upstream)

    chantal_env.write_config(_config("demo-apt-i18n", base_url, "mirror"))
    target = chantal_env.sync_and_publish("demo-apt-i18n")

    i18n = target / "dists" / DIST / COMP / "i18n"
    published = i18n / "Translation-en.gz"
    assert published.exists(), "Translation not republished at i18n path"
    assert (i18n / "Index").exists(), "i18n/Index not republished"

    release_text = (target / "dists" / DIST / "Release").read_text()
    assert f"{COMP}/i18n/Translation-en.gz" in release_text, "Release missing Translation"
    assert f"{COMP}/i18n/Index" in release_text, "Release missing i18n/Index"
    assert hashlib.sha256(published.read_bytes()).hexdigest() in release_text


def test_apt_translation_dropped_in_filtered_mode(tmp_path, serve, chantal_env):
    upstream = tmp_path / "upstream"
    _build_apt_upstream_with_translations(upstream)
    base_url = serve(upstream)

    chantal_env.write_config(_config("demo-apt-i18n-filtered", base_url, "filtered"))
    target = chantal_env.sync_and_publish("demo-apt-i18n-filtered")

    assert not list(target.rglob("Translation-*")), "Translation must be dropped in filtered mode"
    release_text = (target / "dists" / DIST / "Release").read_text()
    assert "i18n/Translation" not in release_text, "filtered Release must not reference Translation"
