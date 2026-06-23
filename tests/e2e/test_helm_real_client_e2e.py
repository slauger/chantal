"""
End-to-end test with a REAL helm client (Docker): custom chart upload (#16).

Builds a genuine chart with `helm package`, uploads it into a HOSTED
(upload-only) helm repo via `chantal package upload`, publishes, then adds the
published repo with `helm repo add` and `helm pull`s the chart in an
alpine/helm container. Proves the whole custom-upload chain for Helm:
pure-Python Chart.yaml extraction, hosted mode, index.yaml generation, and a
real helm client consuming the result.

Docker-gated: skipped where docker is unavailable; runs on the CI helm e2e leg.
`helm repo add` needs an http(s) URL, so the published repo is streamed into the
container as a tar over stdin and served with `python3 -m http.server` locally.
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
_IMAGE = "alpine/helm"

requires_docker = pytest.mark.skipif(not _HAVE_DOCKER, reason="docker not available")


def _build_chart() -> bytes:
    """Build a real chart .tgz with `helm package`; return its bytes."""
    script = (
        "set -e; cd /tmp; helm create demo >/dev/null; "
        "helm package demo >/dev/null; "
        "base64 demo-0.1.0.tgz | tr -d '\\n'"
    )
    out = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "/bin/sh", _IMAGE, "-c", script],
        capture_output=True,
        timeout=300,
    )
    assert out.returncode == 0, f"helm package failed: {out.stderr.decode()[-600:]}"
    return base64.b64decode(out.stdout)


def _helm_pull(published: Path) -> subprocess.CompletedProcess:
    """Stream the published repo into a container, serve it, and `helm pull`."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        tar.add(published, arcname=".")
    script = (
        "set -e; apk add --no-cache python3 >/dev/null; "
        "mkdir -p /repo && tar -xf - -C /repo; "
        "cd /repo && python3 -m http.server 8879 >/dev/null 2>&1 & "
        # wait for the server to accept connections
        "for i in $(seq 1 30); do "
        "  wget -q -O /dev/null http://127.0.0.1:8879/index.yaml && break; sleep 0.3; done; "
        "cd /tmp; "
        "helm repo add local http://127.0.0.1:8879 >/dev/null; "
        "helm repo update >/dev/null; "
        "helm pull local/demo --version 0.1.0; "
        "ls demo-0.1.0.tgz; "
        "helm show chart local/demo | grep '^name:'"
    )
    return subprocess.run(
        ["docker", "run", "--rm", "-i", "--entrypoint", "/bin/sh", _IMAGE, "-c", script],
        input=buf.getvalue(),
        capture_output=True,
        timeout=600,
    )


@requires_docker
def test_helm_hosted_upload_pulls_with_real_helm(tmp_path, chantal_env):
    chart_bytes = _build_chart()
    chart_file = tmp_path / "demo-0.1.0.tgz"
    chart_file.write_bytes(chart_bytes)

    chantal_env.write_config(
        {
            "id": "internal-helm",
            "name": "Internal Helm",
            "type": "helm",
            "enabled": True,
            "mode": "hosted",  # no feed; upload-only
        }
    )

    # Upload the local chart, then publish (no sync — hosted has no upstream).
    chantal_env.run("package", "upload", "--file", str(chart_file), "--repo-id", "internal-helm")
    target = chantal_env.published / "internal-helm"
    chantal_env.run("publish", "repo", "--repo-id", "internal-helm", "--target", str(target))

    # The uploaded chart is in the published repo alongside a generated index.yaml.
    assert list(target.rglob("demo-0.1.0.tgz")), "uploaded chart not published"
    assert list(target.rglob("index.yaml")), "generated index.yaml not found"

    result = _helm_pull(target)
    assert result.returncode == 0, (
        f"real helm pull failed:\nstdout={result.stdout.decode()[-800:]}\n"
        f"stderr={result.stderr.decode()[-800:]}"
    )
    assert b"name: demo" in result.stdout, "helm did not resolve the chart from the repo"
