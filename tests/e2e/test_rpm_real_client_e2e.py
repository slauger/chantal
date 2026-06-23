"""
End-to-end test with a REAL dnf client (Docker): custom RPM upload (#16).

Builds a genuine .rpm, uploads it into a HOSTED (upload-only) repo via
`chantal package upload`, publishes, then `dnf install`s it from the published
repo in an almalinux container. Proves the whole custom-upload chain: pure-Python
RPM metadata extraction, hosted mode, repodata generation, and real dnf install.

Docker-gated: skipped where docker is unavailable; runs on the CI rpm e2e leg.
Self-contained: the .rpm is built in-container (rpmbuild) and the published repo
is streamed into the dnf container as a tar over stdin (no bind-mounts).
"""

from __future__ import annotations

import base64
import io
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

_HAVE_DOCKER = shutil.which("docker") is not None
_IMAGE = "almalinux:9"
requires_docker = pytest.mark.skipif(not _HAVE_DOCKER, reason="docker not available")

_SPEC = """\
Name: demo-hosted
Version: 1.0
Release: 1
Summary: chantal hosted test
License: MIT
BuildArch: noarch

%description
test package

%install
mkdir -p %{buildroot}/usr/share/demo-hosted
echo hello-from-hosted > %{buildroot}/usr/share/demo-hosted/README

%files
/usr/share/demo-hosted/README
"""


def _build_rpm() -> bytes:
    """Build a real noarch .rpm in a container; return its bytes."""
    spec_b64 = base64.b64encode(_SPEC.encode()).decode()
    script = (
        "set -e; dnf install -y rpm-build >/dev/null 2>&1; mkdir -p /root/rpmbuild/SPECS; "
        f"echo {spec_b64} | base64 -d > /root/rpmbuild/SPECS/demo.spec; "
        "rpmbuild -bb /root/rpmbuild/SPECS/demo.spec >/dev/null 2>&1; "
        "base64 -w0 /root/rpmbuild/RPMS/noarch/demo-hosted-1.0-1.noarch.rpm"
    )
    out = subprocess.run(
        ["docker", "run", "--rm", _IMAGE, "bash", "-c", script],
        capture_output=True,
        timeout=600,
    )
    assert out.returncode == 0, f"rpm build failed: {out.stderr.decode()[-600:]}"
    return base64.b64decode(out.stdout)


def _dnf_install(published: Path) -> subprocess.CompletedProcess:
    """Stream the published repo into a container and dnf-install from it."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        tar.add(published, arcname=".")
    script = (
        "set -e; mkdir -p /repo && tar -xf - -C /repo; "
        'printf "[hosted]\\nname=hosted\\nbaseurl=file:///repo\\nenabled=1\\ngpgcheck=0\\n"'
        " > /etc/yum.repos.d/hosted.repo; "
        "dnf install -y demo-hosted >/dev/null; "
        "cat /usr/share/demo-hosted/README"
    )
    return subprocess.run(
        ["docker", "run", "--rm", "-i", _IMAGE, "bash", "-c", script],
        input=buf.getvalue(),
        capture_output=True,
        timeout=600,
    )


@requires_docker
def test_rpm_hosted_upload_installs_with_real_dnf(tmp_path, chantal_env):
    rpm_bytes = _build_rpm()
    rpm_file = tmp_path / "demo-hosted-1.0-1.noarch.rpm"
    rpm_file.write_bytes(rpm_bytes)

    chantal_env.write_config(
        {
            "id": "internal-rpm",
            "name": "Internal RPM",
            "type": "rpm",
            "enabled": True,
            "mode": "hosted",  # no feed; upload-only
        }
    )

    # Upload the local RPM, then publish (no sync — hosted has no upstream).
    chantal_env.run("package", "upload", "--file", str(rpm_file), "--repo-id", "internal-rpm")
    target = chantal_env.published / "internal-rpm"
    chantal_env.run("publish", "repo", "--repo-id", "internal-rpm", "--target", str(target))

    # The uploaded package is in the published repodata + pool.
    assert list(target.rglob("demo-hosted-1.0-1.noarch.rpm")), "uploaded rpm not published"

    result = _dnf_install(target)
    assert result.returncode == 0, (
        f"real dnf install failed:\nstdout={result.stdout.decode()[-800:]}\n"
        f"stderr={result.stderr.decode()[-800:]}"
    )
    assert b"hello-from-hosted" in result.stdout, "installed package file missing"
