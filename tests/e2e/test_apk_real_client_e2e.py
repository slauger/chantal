"""
End-to-end test with a REAL apk client (Docker): signed APKINDEX + filtering.

chantal mirrors a small genuine Alpine package, regenerates and **RSA-signs**
the APKINDEX in filtered mode, and publishes a public key at the repo root.
A real `apk` client then installs from the published repo with signature
verification ON (no `--allow-untrusted`) — proving the whole chain: APKINDEX
regeneration, RSA index signing, key publication, and trust by stock apk.

Docker-gated: skipped where docker is unavailable; runs on the CI apk e2e leg.
Self-contained: the upstream (a real .apk + index) is built in-container with
`apk fetch`/`apk index`, and the published repo is streamed into the client
container as a tar over stdin (no bind-mounts).
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
_IMAGE = "alpine:3.20"

BRANCH = "v3.20"
REPO = "main"
ARCH = "x86_64"
KEY_NAME = "chantal"  # -> published key file "chantal.rsa.pub"

requires_docker = pytest.mark.skipif(not _HAVE_DOCKER, reason="docker not available")


def _build_upstream(root: Path, packages: str) -> None:
    """Build a genuine Alpine upstream (real .apk files + APKINDEX) in-container.

    ``packages`` is a space-separated list fetched with their deps; the result
    is unpacked into ``root/<branch>/<repo>/<arch>/``.
    """
    script = (
        "set -e; apk update >/dev/null 2>&1; mkdir -p /out; "
        f"apk fetch -R -o /out {packages} >/dev/null 2>&1; "
        "cd /out && apk index -o APKINDEX.tar.gz *.apk >/dev/null 2>&1; "
        "tar -cf - -C /out . | base64 | tr -d '\\n'"
    )
    out = subprocess.run(
        ["docker", "run", "--rm", _IMAGE, "sh", "-c", script],
        capture_output=True,
        timeout=300,
    )
    assert out.returncode == 0, f"apk upstream build failed: {out.stderr.decode()[-600:]}"
    arch_dir = root / BRANCH / REPO / ARCH
    arch_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(base64.b64decode(out.stdout))) as tar:
        tar.extractall(arch_dir)  # noqa: S202 - trusted, self-built tar


def _apk_add(published: Path, pkg: str, *, install_key: bool = True) -> subprocess.CompletedProcess:
    """Stream the published repo into a container and `apk add` from it."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        tar.add(published, arcname=".")
    key_step = (
        f"cp /repo/{KEY_NAME}.rsa.pub /etc/apk/keys/{KEY_NAME}.rsa.pub; " if install_key else ""
    )
    script = (
        "set -e; mkdir -p /repo && tar -xf - -C /repo; "
        + key_step
        + f"echo /repo/{BRANCH}/{REPO} > /etc/apk/repositories; "
        "apk update; "
        f"apk add {pkg}; "
        f"apk info -e {pkg}"
    )
    return subprocess.run(
        ["docker", "run", "--rm", "-i", _IMAGE, "sh", "-c", script],
        input=buf.getvalue(),
        capture_output=True,
        timeout=300,
    )


def _write_apk_config(chantal_env, repo_id: str, feed: str, filters: dict | None = None) -> None:
    repo: dict = {
        "id": repo_id,
        "name": "Internal APK",
        "type": "apk",
        "feed": feed,
        "enabled": True,
        "mode": "filtered",
        "apk": {"branch": BRANCH, "repository": REPO, "architecture": ARCH},
        "gpg": {"enabled": True, "generate_key": True, "key_name": KEY_NAME},
    }
    if filters is not None:
        repo["filters"] = filters
    chantal_env.write_config(repo)


@requires_docker
def test_apk_signed_repo_installs_with_real_apk(tmp_path, serve, chantal_env):
    upstream = tmp_path / "upstream"
    _build_upstream(upstream, "tzdata")
    _write_apk_config(chantal_env, "internal-apk", serve(upstream))

    target = chantal_env.sync_and_publish("internal-apk")

    # The regenerated index is RSA-signed and a public key was published.
    assert (target / f"{KEY_NAME}.rsa.pub").is_file(), "published apk public key not found"
    index = target / BRANCH / REPO / ARCH / "APKINDEX.tar.gz"
    assert index.is_file(), "published APKINDEX not found"
    with tarfile.open(index) as tar:
        names = tar.getnames()
    assert any(
        n == f".SIGN.RSA256.{KEY_NAME}.rsa.pub" for n in names
    ), f"APKINDEX is not signed: {names}"

    # Real apk installs from the signed repo WITH verification on (key trusted).
    result = _apk_add(target, "tzdata", install_key=True)
    assert result.returncode == 0, (
        f"real apk add failed:\nstdout={result.stdout.decode()[-800:]}\n"
        f"stderr={result.stderr.decode()[-800:]}"
    )
    assert b"tzdata" in result.stdout, "tzdata not reported installed"


@requires_docker
def test_apk_signed_repo_rejected_without_key(tmp_path, serve, chantal_env):
    """Without the published key in /etc/apk/keys, apk must refuse the signed repo."""
    upstream = tmp_path / "upstream"
    _build_upstream(upstream, "tzdata")
    _write_apk_config(chantal_env, "internal-apk", serve(upstream))

    target = chantal_env.sync_and_publish("internal-apk")

    result = _apk_add(target, "tzdata", install_key=False)
    assert result.returncode != 0, "apk add should fail for an untrusted signed repo"
    assert (
        b"UNTRUSTED" in result.stderr.upper() or b"untrusted" in result.stderr.lower()
    ), f"expected an untrusted-signature error, got:\nstderr={result.stderr.decode()[-800:]}"


@requires_docker
def test_apk_filtering_excludes_packages_from_real_client(tmp_path, serve, chantal_env):
    """A package excluded by filters is not installable by a real apk client."""
    upstream = tmp_path / "upstream"
    _build_upstream(upstream, "tzdata tini")  # both fetched; only tzdata kept
    _write_apk_config(
        chantal_env,
        "internal-apk",
        serve(upstream),
        filters={"patterns": {"include": ["^tzdata$"]}},
    )

    target = chantal_env.sync_and_publish("internal-apk")

    # Kept package installs; excluded package is absent from the published repo.
    ok = _apk_add(target, "tzdata", install_key=True)
    assert ok.returncode == 0, f"kept package failed to install: {ok.stderr.decode()[-600:]}"

    missing = _apk_add(target, "tini", install_key=True)
    assert missing.returncode != 0, "excluded package 'tini' should not be installable"
