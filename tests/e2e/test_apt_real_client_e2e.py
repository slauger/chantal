"""
End-to-end test with a REAL apt client (Docker).

Builds a genuine .deb, mirrors it with chantal, then runs `apt-get update` +
`apt-get install` in a debian container against the published repo and asserts
the package actually installs and its binary runs. This is the definitive proof
that a chantal-published APT repo is consumable by real apt (pool layout +
Filename resolution + index/Release consistency).

Docker-gated: skipped where docker is unavailable; runs on the CI apt leg.
Network-free: the .deb is built in-container (base64 over stdout) and the
published repo is streamed into the apt container as a tar over stdin, so no
bind-mounts or host networking are required.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
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
        'printf "Package: hello-chantal\\nVersion: 1.0\\nArchitecture: amd64\\n'
        'Maintainer: t <t@e.x>\\nDescription: chantal real-apt test\\n" > /pkg/DEBIAN/control; '
        'printf "#!/bin/sh\\necho hello-from-chantal\\n" > /pkg/usr/bin/hello-chantal; '
        "chmod +x /pkg/usr/bin/hello-chantal; "
        "dpkg-deb --build /pkg /out.deb >/dev/null; base64 -w0 /out.deb"
    )
    out = subprocess.run(
        ["docker", "run", "--rm", _IMAGE, "bash", "-c", script],
        capture_output=True,
        timeout=300,
    )
    assert out.returncode == 0, f"deb build failed: {out.stderr.decode()[-500:]}"
    return base64.b64decode(out.stdout)


def _build_upstream(root: Path, deb: bytes) -> None:
    deb_rel = f"pool/{COMP}/h/hello-chantal/hello-chantal_1.0_{ARCH}.deb"
    (root / deb_rel).parent.mkdir(parents=True, exist_ok=True)
    (root / deb_rel).write_bytes(deb)

    packages = (
        "Package: hello-chantal\n"
        "Version: 1.0\n"
        f"Architecture: {ARCH}\n"
        "Maintainer: t <t@e.x>\n"
        f"Filename: {deb_rel}\n"
        f"Size: {len(deb)}\n"
        f"SHA256: {hashlib.sha256(deb).hexdigest()}\n"
        "Description: chantal real-apt test\n"
        "\n"
    ).encode()
    comp_dir = root / "dists" / DIST / COMP / f"binary-{ARCH}"
    comp_dir.mkdir(parents=True, exist_ok=True)
    (comp_dir / "Packages").write_bytes(packages)
    packages_gz = gzip.compress(packages)
    (comp_dir / "Packages.gz").write_bytes(packages_gz)

    sha = hashlib.sha256
    release = (
        f"Origin: Upstream\nSuite: {DIST}\nCodename: {DIST}\nComponents: {COMP}\n"
        f"Architectures: {ARCH}\nDate: Thu, 01 Jan 2026 00:00:00 UTC\nSHA256:\n"
        f" {sha(packages).hexdigest()} {len(packages)} {COMP}/binary-{ARCH}/Packages\n"
        f" {sha(packages_gz).hexdigest()} {len(packages_gz)} {COMP}/binary-{ARCH}/Packages.gz\n"
    )
    (root / "dists" / DIST / "Release").write_text(release, encoding="utf-8")


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
        "apt-get install -y hello-chantal >/dev/null; "
        "hello-chantal"
    )
    return subprocess.run(
        ["docker", "run", "--rm", "-i", _IMAGE, "bash", "-c", script],
        input=buf.getvalue(),
        capture_output=True,
        timeout=600,
    )


@requires_docker
def test_apt_published_repo_installs_with_real_apt(tmp_path, serve, chantal_env):
    deb = _build_real_deb()
    upstream = tmp_path / "upstream"
    _build_upstream(upstream, deb)
    base_url = serve(upstream)

    chantal_env.write_config(
        {
            "id": "demo-real-apt",
            "name": "Demo real apt",
            "type": "apt",
            "feed": base_url,
            "enabled": True,
            "mode": "filtered",
            "apt": {"distribution": DIST, "components": [COMP], "architectures": [ARCH]},
        }
    )

    target = chantal_env.sync_and_publish("demo-real-apt")

    result = _apt_install(target)
    assert result.returncode == 0, (
        f"real apt install failed:\nstdout={result.stdout.decode()[-800:]}\n"
        f"stderr={result.stderr.decode()[-800:]}"
    )
    assert b"hello-from-chantal" in result.stdout, "installed binary did not run"
