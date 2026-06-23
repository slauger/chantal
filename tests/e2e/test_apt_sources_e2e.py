"""
End-to-end test: APT source-package mirroring.

With ``include_source_packages: true`` the sync must download the source
artifacts (.dsc / .orig.tar.* / .debian.tar.*) referenced by the Sources index,
pool them, and the publisher must regenerate a ``Sources`` index and list it in
``Release``.
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


def _build_apt_upstream_with_sources(root: Path, *, corrupt: str | None = None) -> None:
    # --- binary package ---
    deb_rel = f"pool/{COMP}/d/demo/demo_1.0_{ARCH}.deb"
    (root / deb_rel).parent.mkdir(parents=True, exist_ok=True)
    deb = b"dummy deb payload" * 16
    (root / deb_rel).write_bytes(deb)

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

    # --- source artifacts ---
    src_dir_rel = f"pool/{COMP}/d/demo"
    artifacts = {
        "demo_1.0.dsc": b"fake dsc contents\n",
        "demo_1.0.orig.tar.gz": b"fake orig tarball" * 8,
        "demo_1.0.debian.tar.xz": b"fake debian tarball" * 8,
    }
    for name, data in artifacts.items():
        (root / src_dir_rel / name).write_bytes(data)

    def _sha256(name, data):
        if corrupt and name == corrupt:
            return "0" * 64
        return hashlib.sha256(data).hexdigest()

    files_md5 = "".join(
        f" {hashlib.md5(d).hexdigest()} {len(d)} {n}\n" for n, d in artifacts.items()
    )
    files_sha256 = "".join(f" {_sha256(n, d)} {len(d)} {n}\n" for n, d in artifacts.items())

    sources = (
        "Package: demo\n"
        "Format: 3.0 (quilt)\n"
        "Binary: demo\n"
        "Version: 1.0\n"
        "Maintainer: Test <test@example.com>\n"
        "Architecture: any\n"
        f"Directory: {src_dir_rel}\n"
        "Files:\n" + files_md5 + "Checksums-Sha256:\n" + files_sha256 + "\n"
    ).encode()
    src_index_dir = root / "dists" / DIST / COMP / "source"
    src_index_dir.mkdir(parents=True, exist_ok=True)
    (src_index_dir / "Sources").write_bytes(sources)
    sources_gz = gzip.compress(sources)
    (src_index_dir / "Sources.gz").write_bytes(sources_gz)

    # --- Release ---
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
        + _rel(f"{COMP}/source/Sources", sources)
        + _rel(f"{COMP}/source/Sources.gz", sources_gz)
    )
    (root / "dists" / DIST / "Release").write_text(release, encoding="utf-8")


def test_apt_sources_sync_and_publish(tmp_path, serve, chantal_env):
    upstream = tmp_path / "upstream"
    _build_apt_upstream_with_sources(upstream)
    base_url = serve(upstream)

    chantal_env.write_config(
        {
            "id": "demo-apt-src",
            "name": "Demo APT sources",
            "type": "apt",
            "feed": base_url,
            "enabled": True,
            "mode": "filtered",
            "apt": {
                "distribution": DIST,
                "components": [COMP],
                "architectures": [ARCH],
                "include_source_packages": True,
            },
        }
    )

    target = chantal_env.sync_and_publish("demo-apt-src")

    # The regenerated Sources index stays under dists/ and lists all artifacts.
    sources_index = target / "dists" / DIST / COMP / "source" / "Sources"
    assert sources_index.exists(), "regenerated Sources index missing"
    text = sources_index.read_text()
    for name in ("demo_1.0.dsc", "demo_1.0.orig.tar.gz", "demo_1.0.debian.tar.xz"):
        assert name in text, f"{name} missing from regenerated Sources"
        # Artifacts live in the content pool (referenced by Directory:).
        assert list(target.rglob(name)), f"{name} not published"
    # Directory points into the pool (where the artifacts actually are).
    assert f"Directory: pool/{COMP}/" in text, "source Directory not pool-relative"
    # The Format field is preserved (apt-get source needs it).
    assert "Format: 3.0 (quilt)" in text, "Format field not preserved"

    # Release lists the source index.
    release_text = (target / "dists" / DIST / "Release").read_text()
    assert f"{COMP}/source/Sources" in release_text, "Release does not reference Sources"


def test_apt_sources_checksum_mismatch_rejected(tmp_path, serve, chantal_env):
    # An artifact whose declared sha256 is wrong must be rejected, not published.
    upstream = tmp_path / "upstream"
    _build_apt_upstream_with_sources(upstream, corrupt="demo_1.0.dsc")
    base_url = serve(upstream)

    chantal_env.write_config(
        {
            "id": "demo-apt-src-bad",
            "name": "Demo APT bad source checksum",
            "type": "apt",
            "feed": base_url,
            "enabled": True,
            "mode": "filtered",
            "apt": {
                "distribution": DIST,
                "components": [COMP],
                "architectures": [ARCH],
                "include_source_packages": True,
            },
        }
    )

    target = chantal_env.sync_and_publish("demo-apt-src-bad")
    # The corrupt .dsc is rejected; the well-formed artifacts still publish (pool).
    assert not list(target.rglob("demo_1.0.dsc")), "artifact with bad checksum was published"
    assert list(target.rglob("demo_1.0.orig.tar.gz")), "valid artifact missing"


def _build_shared_artifact_upstream(root: Path) -> None:
    """Two source packages that share an identical .orig.tar.gz (same sha256)."""
    src_dir_rel = f"pool/{COMP}/s/shared"
    shared = b"shared upstream tarball" * 8
    stanzas = []
    src_pkg_dir = root / src_dir_rel
    src_pkg_dir.mkdir(parents=True, exist_ok=True)
    (src_pkg_dir / "shared_1.0.orig.tar.gz").write_bytes(shared)
    for pkg in ("alpha", "beta"):
        dsc = f"fake dsc {pkg}\n".encode()
        (src_pkg_dir / f"{pkg}_1.0.dsc").write_bytes(dsc)
        arts = {f"{pkg}_1.0.dsc": dsc, "shared_1.0.orig.tar.gz": shared}
        md5 = "".join(f" {hashlib.md5(d).hexdigest()} {len(d)} {n}\n" for n, d in arts.items())
        s256 = "".join(f" {hashlib.sha256(d).hexdigest()} {len(d)} {n}\n" for n, d in arts.items())
        stanzas.append(
            f"Package: {pkg}\nVersion: 1.0\nArchitecture: any\n"
            f"Directory: {src_dir_rel}\nFiles:\n{md5}Checksums-Sha256:\n{s256}"
        )
    sources = ("\n".join(stanzas) + "\n").encode()
    src_index_dir = root / "dists" / DIST / COMP / "source"
    src_index_dir.mkdir(parents=True, exist_ok=True)
    (src_index_dir / "Sources").write_bytes(sources)
    sources_gz = gzip.compress(sources)
    (src_index_dir / "Sources.gz").write_bytes(sources_gz)

    sha = hashlib.sha256
    release = (
        f"Origin: Test\nSuite: {DIST}\nCodename: {DIST}\n"
        f"Components: {COMP}\nArchitectures: {ARCH}\n"
        "Date: Thu, 01 Jan 2026 00:00:00 UTC\nSHA256:\n"
        f" {sha(sources).hexdigest()} {len(sources)} {COMP}/source/Sources\n"
        f" {sha(sources_gz).hexdigest()} {len(sources_gz)} {COMP}/source/Sources.gz\n"
    )
    (root / "dists" / DIST / "Release").write_text(release, encoding="utf-8")


def test_apt_sources_shared_artifact_dedup(tmp_path, serve, chantal_env):
    # A shared identical artifact across two source stanzas must not crash the
    # sync (duplicate sha256 -> in-run dedup, no IntegrityError cascade).
    upstream = tmp_path / "upstream"
    _build_shared_artifact_upstream(upstream)
    base_url = serve(upstream)

    chantal_env.write_config(
        {
            "id": "demo-apt-src-shared",
            "name": "Demo APT shared source artifact",
            "type": "apt",
            "feed": base_url,
            "enabled": True,
            "mode": "filtered",
            "apt": {
                "distribution": DIST,
                "components": [COMP],
                "architectures": [ARCH],
                "include_source_packages": True,
            },
        }
    )

    target = chantal_env.sync_and_publish("demo-apt-src-shared")
    # All artifacts published (under the pool); the shared one appears once.
    assert list(target.rglob("shared_1.0.orig.tar.gz")), "shared artifact missing"
    assert list(target.rglob("alpha_1.0.dsc"))
    assert list(target.rglob("beta_1.0.dsc"))
    # The shared artifact lives once in the content pool (content-addressed).
    pooled = list(chantal_env.pool.rglob("*shared_1.0.orig.tar.gz"))
    assert len(pooled) == 1, f"shared artifact should be pooled once, got {len(pooled)}"
