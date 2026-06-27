"""
End-to-end test with a REAL apt client (Docker): custom .deb upload (#16).

Builds a genuine .deb, uploads it into a HOSTED (upload-only) apt repo via
`chantal package upload`, publishes, then `apt-get install`s it from the
published repo in a debian container. Proves the whole custom-upload chain for
APT: pure-Python ar/control extraction, hosted mode, Packages/Release
generation, real pool layout, and real apt install.

Docker-gated: skipped where docker is unavailable; runs on the CI apt e2e leg.
Self-contained: the .deb is built in-container (dpkg-deb) and the published repo
is streamed into the apt container as a tar over stdin (no bind-mounts).
"""

from __future__ import annotations

import base64
import io
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.apt]

_HAVE_DOCKER = shutil.which("docker") is not None
_IMAGE = "debian:bookworm"

DIST = "jammy"
COMP = "main"
ARCH = "amd64"

requires_docker = pytest.mark.skipif(not _HAVE_DOCKER, reason="docker not available")


def _build_real_deb() -> bytes:
    """Build a genuine .deb in a debian container; return its bytes."""
    script = (
        "set -e; mkdir -p /pkg/DEBIAN /pkg/usr/bin; "
        'printf "Package: demo-hosted\\nVersion: 1.0\\nArchitecture: amd64\\n'
        'Maintainer: t <t@e.x>\\nDescription: chantal hosted deb test\\n"'
        " > /pkg/DEBIAN/control; "
        'printf "#!/bin/sh\\necho hello-from-hosted-deb\\n" > /pkg/usr/bin/demo-hosted; '
        "chmod +x /pkg/usr/bin/demo-hosted; "
        "dpkg-deb --build /pkg /out.deb >/dev/null; base64 -w0 /out.deb"
    )
    out = subprocess.run(
        ["docker", "run", "--rm", _IMAGE, "bash", "-c", script],
        capture_output=True,
        timeout=300,
    )
    assert out.returncode == 0, f"deb build failed: {out.stderr.decode()[-500:]}"
    return base64.b64decode(out.stdout)


def _apt_install(published: Path) -> subprocess.CompletedProcess:
    """Stream the published repo into a debian container and apt-install from it."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        tar.add(published, arcname=".")
    script = (
        "set -e; mkdir -p /repo && tar -xf - -C /repo; "
        "rm -f /etc/apt/sources.list /etc/apt/sources.list.d/* 2>/dev/null || true; "
        f'echo "deb [trusted=yes] file:/repo {DIST} {COMP}" > /etc/apt/sources.list.d/c.list; '
        "apt-get update >/dev/null; "
        "apt-get install -y demo-hosted >/dev/null; "
        "demo-hosted"
    )
    return subprocess.run(
        ["docker", "run", "--rm", "-i", _IMAGE, "bash", "-c", script],
        input=buf.getvalue(),
        capture_output=True,
        timeout=600,
    )


@requires_docker
def test_deb_hosted_upload_installs_with_real_apt(tmp_path, chantal_env):
    deb_bytes = _build_real_deb()
    deb_file = tmp_path / "demo-hosted_1.0_amd64.deb"
    deb_file.write_bytes(deb_bytes)

    chantal_env.write_config(
        {
            "id": "internal-deb",
            "name": "Internal DEB",
            "type": "apt",
            "enabled": True,
            "mode": "hosted",  # no feed; upload-only
            "apt": {"distribution": DIST, "components": [COMP], "architectures": [ARCH]},
        }
    )

    # Upload the local .deb, then publish (no sync — hosted has no upstream).
    chantal_env.run("package", "upload", "--file", str(deb_file), "--repo-id", "internal-deb")
    target = chantal_env.published / "internal-deb"
    chantal_env.run("publish", "repo", "--repo-id", "internal-deb", "--target", str(target))

    # The uploaded package is in the published pool.
    assert list(target.rglob("demo-hosted_1.0_amd64.deb")), "uploaded deb not published"

    result = _apt_install(target)
    assert result.returncode == 0, (
        f"real apt install failed:\nstdout={result.stdout.decode()[-800:]}\n"
        f"stderr={result.stderr.decode()[-800:]}"
    )
    assert b"hello-from-hosted-deb" in result.stdout, "installed binary did not run"
