"""End-to-end sync->publish test for the Alpine APK plugin."""

from __future__ import annotations

import base64
import hashlib
import io
import tarfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

BRANCH = "v3.19"
REPO = "main"
ARCH = "x86_64"


def _build_apk_upstream(root: Path) -> None:
    """Create a minimal Alpine repo (APKINDEX.tar.gz + one .apk)."""
    arch_dir = root / BRANCH / REPO / ARCH
    arch_dir.mkdir(parents=True, exist_ok=True)

    apk = b"dummy apk payload" * 16
    (arch_dir / "demo-1.0-r0.apk").write_bytes(apk)
    # APK checksum field: "Q1" + base64(sha1(file))
    q1 = "Q1" + base64.b64encode(hashlib.sha1(apk).digest()).decode("ascii")

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
