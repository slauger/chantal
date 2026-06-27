"""End-to-end sync->publish test for the Alpine APK plugin."""

from __future__ import annotations

import gzip
import io
import tarfile
from pathlib import Path

import pytest

from chantal.plugins.apk.checksum import compute_apk_control_checksum

pytestmark = [pytest.mark.e2e, pytest.mark.apk]

BRANCH = "v3.19"
REPO = "main"
ARCH = "x86_64"


def _gz_tar(name: str, content: bytes) -> bytes:
    """Return a single gzip stream wrapping a one-entry tar (an .apk segment)."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        info = tarfile.TarInfo(name)
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb") as gz:
        gz.write(raw.getvalue())
    return out.getvalue()


def _build_minimal_apk(revision: int = 1) -> bytes:
    """A valid APKv2 archive: concatenated control + data gzip streams.

    ``revision`` is woven into the data segment so the archive bytes (and thus
    the control checksum) differ between revisions, modelling a repackaged .apk.
    """
    control = _gz_tar(".PKGINFO", b"pkgname = demo\npkgver = 1.0-r0\n")
    data = _gz_tar("usr/share/demo/README", f"hello-from-demo rev{revision}\n".encode())
    return control + data


def _build_apk_upstream(root: Path, revision: int = 1) -> None:
    """Create a minimal Alpine repo (APKINDEX.tar.gz + one .apk)."""
    arch_dir = root / BRANCH / REPO / ARCH
    arch_dir.mkdir(parents=True, exist_ok=True)

    apk = _build_minimal_apk(revision)
    (arch_dir / "demo-1.0-r0.apk").write_bytes(apk)
    # APK checksum field: Q1 + base64(SHA1 of the control segment).
    q1 = compute_apk_control_checksum(apk)

    apkindex = (
        f"C:{q1}\n"
        "P:demo\n"
        "V:1.0-r0\n"
        f"A:{ARCH}\n"
        f"S:{len(apk)}\n"
        f"I:{len(apk)}\n"
        "T:demo package\n"
        "U:http://example.com\n"
        "L:MIT\n"
        "o:demo\n"
        "m:Test <test@example.com>\n"
        "t:1\n"
        "\n"
    ).encode()

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("APKINDEX")
        info.size = len(apkindex)
        tar.addfile(info, io.BytesIO(apkindex))
    (arch_dir / "APKINDEX.tar.gz").write_bytes(buf.getvalue())


def test_apk_sync_and_publish(tmp_path, serve, chantal_env):
    upstream = tmp_path / "upstream"
    _build_apk_upstream(upstream)
    base_url = serve(upstream)

    chantal_env.write_config(
        {
            "id": "demo-apk",
            "name": "Demo APK",
            "type": "apk",
            "feed": base_url,
            "enabled": True,
            "mode": "filtered",
            "apk": {
                "branch": BRANCH,
                "repository": REPO,
                "architecture": ARCH,
            },
        }
    )

    target = chantal_env.sync_and_publish("demo-apk")

    # APKINDEX.tar.gz was regenerated and the .apk was published.
    assert list(target.rglob("APKINDEX.tar.gz")), "published APKINDEX not found"
    assert list(target.rglob("demo-1.0-r0.apk")), "published .apk not found"


def _apkindex_demo_count(apkindex_path: Path) -> int:
    """Return how many demo package stanzas the published APKINDEX contains."""
    buf = io.BytesIO(apkindex_path.read_bytes())
    with tarfile.open(fileobj=buf, mode="r:gz") as tar:
        member = tar.extractfile("APKINDEX")
        assert member is not None
        text = member.read().decode()
    return sum(1 for line in text.splitlines() if line == "P:demo")


def test_apk_mirror_sync_and_publish(tmp_path, serve, chantal_env):
    """Mirror mode must publish the upstream .apk and a usable APKINDEX."""
    upstream = tmp_path / "upstream"
    _build_apk_upstream(upstream)
    base_url = serve(upstream)

    chantal_env.write_config(
        {
            "id": "demo-apk",
            "name": "Demo APK",
            "type": "apk",
            "feed": base_url,
            "enabled": True,
            "mode": "mirror",
            "apk": {
                "branch": BRANCH,
                "repository": REPO,
                "architecture": ARCH,
            },
        }
    )

    target = chantal_env.sync_and_publish("demo-apk")

    indexes = list(target.rglob("APKINDEX.tar.gz"))
    assert indexes, "published APKINDEX not found"
    assert list(target.rglob("demo-1.0-r0.apk")), "published .apk not found"
    assert _apkindex_demo_count(indexes[0]) == 1


def test_apk_resync_does_not_duplicate_package(tmp_path, serve, chantal_env):
    """Re-syncing a repackaged demo 1.0-r0 must leave exactly one index entry.

    When upstream repackages the .apk (same version, new control checksum), the
    stale ContentItem must not stay associated and get republished: the
    regenerated APKINDEX would list demo twice and the pool would grow unbounded.
    """
    upstream = tmp_path / "upstream"
    _build_apk_upstream(upstream, revision=1)
    base_url = serve(upstream)

    chantal_env.write_config(
        {
            "id": "demo-apk",
            "name": "Demo APK",
            "type": "apk",
            "feed": base_url,
            "enabled": True,
            "mode": "filtered",
            "apk": {
                "branch": BRANCH,
                "repository": REPO,
                "architecture": ARCH,
            },
        }
    )

    chantal_env.sync_and_publish("demo-apk")

    # Upstream repackages demo 1.0-r0 with new bytes (fresh control checksum).
    _build_apk_upstream(upstream, revision=2)
    target = chantal_env.sync_and_publish("demo-apk")

    indexes = list(target.rglob("APKINDEX.tar.gz"))
    assert indexes, "published APKINDEX not found"
    assert _apkindex_demo_count(indexes[0]) == 1, "re-sync left duplicate demo stanzas in APKINDEX"
    apks = list(target.rglob("demo-1.0-r0.apk"))
    assert len(apks) == 1, f"re-sync published duplicate .apk files: {apks}"
