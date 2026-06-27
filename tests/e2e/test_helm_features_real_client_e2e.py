"""
End-to-end tests with a REAL helm client (Docker) covering Helm repo features.

Beyond the basic hosted-upload pull (test_helm_real_client_e2e.py), these prove
the sync-based paths a real helm client observes:

* **Mirror mode** — an upstream chart repo mirrored 1:1; the published
  ``index.yaml`` is byte-identical and real ``helm pull`` retrieves the chart.
* **Multiple versions** — two versions of a chart are both visible via
  ``helm search repo --versions`` and individually pullable.
* **Filtered selection** — a chart excluded by filters is not pullable, the
  kept one is.

Docker-gated; runs on the CI helm e2e leg (filename contains ``helm``).
A real upstream chart repo is built in-container with ``helm package``; the
published repo is streamed into the helm container as a tar over stdin and
served with ``python3 -m http.server`` (helm needs an http URL).
"""

from __future__ import annotations

import base64
import hashlib
import io
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.e2e, pytest.mark.helm]

_HAVE_DOCKER = shutil.which("docker") is not None
_IMAGE = "alpine/helm"

requires_docker = pytest.mark.skipif(not _HAVE_DOCKER, reason="docker not available")


def _build_charts(specs: list[tuple[str, str]]) -> dict[tuple[str, str], bytes]:
    """Build real chart .tgz files in-container.

    ``specs`` is a list of (name, version); returns {(name, version): tgz bytes}.
    """
    cmds = ["set -e; cd /tmp"]
    for name, version in specs:
        cmds.append(f"helm create {name} >/dev/null 2>&1 || true")
        cmds.append(f"helm package {name} --version {version} >/dev/null")
    # Emit each tgz as "name version base64" lines.
    for name, version in specs:
        cmds.append(f"echo \"{name} {version} $(base64 {name}-{version}.tgz | tr -d '\\n')\"")
    out = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "/bin/sh", _IMAGE, "-c", "; ".join(cmds)],
        capture_output=True,
        timeout=300,
    )
    assert out.returncode == 0, f"helm package failed: {out.stderr.decode()[-600:]}"
    charts: dict[tuple[str, str], bytes] = {}
    for line in out.stdout.decode().splitlines():
        name, version, b64 = line.split(" ", 2)
        charts[(name, version)] = base64.b64decode(b64)
    return charts


def _write_upstream(
    root: Path, charts: dict[tuple[str, str], bytes], url_base: str | None = None
) -> None:
    """Write an upstream chart repo (the .tgz files + an index.yaml).

    When ``url_base`` is given the index uses absolute chart URLs (the Bitnami
    case: ``https://charts.example.com/demo-0.1.0.tgz``); otherwise relative
    filenames are used. The tarballs are always written under ``root`` so a
    mirror that rewrites URLs to relative filenames can serve them locally.
    """
    root.mkdir(parents=True, exist_ok=True)
    entries: dict[str, list] = {}
    for (name, version), data in charts.items():
        fname = f"{name}-{version}.tgz"
        (root / fname).write_bytes(data)
        url = f"{url_base.rstrip('/')}/{fname}" if url_base else fname
        entries.setdefault(name, []).append(
            {
                "name": name,
                "version": version,
                "apiVersion": "v2",
                "digest": hashlib.sha256(data).hexdigest(),
                "urls": [url],
            }
        )
    index = {"apiVersion": "v1", "entries": entries, "generated": "2026-01-01T00:00:00Z"}
    (root / "index.yaml").write_text(yaml.safe_dump(index), encoding="utf-8")


def _helm(published: Path, helm_script: str) -> subprocess.CompletedProcess:
    """Stream the published repo into a container, serve it, run ``helm_script``.

    ``helm_script`` runs after ``helm repo add local http://127.0.0.1:8879`` and
    ``helm repo update``.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        tar.add(published, arcname=".")
    script = (
        "set -e; apk add --no-cache python3 >/dev/null; "
        "mkdir -p /repo && tar -xf - -C /repo; "
        "cd /repo && python3 -m http.server 8879 >/dev/null 2>&1 & "
        "for i in $(seq 1 30); do "
        "  wget -q -O /dev/null http://127.0.0.1:8879/index.yaml && break; sleep 0.3; done; "
        "cd /tmp; "
        "helm repo add local http://127.0.0.1:8879 >/dev/null; "
        "helm repo update >/dev/null; " + helm_script
    )
    return subprocess.run(
        ["docker", "run", "--rm", "-i", "--entrypoint", "/bin/sh", _IMAGE, "-c", script],
        input=buf.getvalue(),
        capture_output=True,
        timeout=600,
    )


# --------------------------------------------------------------------------- #


@requires_docker
def test_helm_mirror_consumed_by_real_client(tmp_path, serve, chantal_env):
    """A mirror-mode repo is consumable by real helm; URLs point at the mirror."""
    charts = _build_charts([("demo", "0.1.0")])
    upstream = tmp_path / "upstream"
    _write_upstream(upstream, charts)

    chantal_env.write_config(
        {
            "id": "demo-mirror",
            "name": "Demo mirror",
            "type": "helm",
            "feed": serve(upstream),
            "enabled": True,
            "mode": "mirror",
        }
    )
    target = chantal_env.sync_and_publish("demo-mirror")

    # The mirror's index.yaml points clients at its own (relative) chart paths.
    published = yaml.safe_load((target / "index.yaml").read_text())
    assert published["entries"]["demo"][0]["urls"] == ["demo-0.1.0.tgz"]

    ok = _helm(
        target,
        "helm pull local/demo --version 0.1.0; "
        "test -f demo-0.1.0.tgz; "
        "helm show chart local/demo | grep '^name: demo'",
    )
    assert ok.returncode == 0, (
        f"real helm pull from mirror failed:\nstdout={ok.stdout.decode()[-800:]}\n"
        f"stderr={ok.stderr.decode()[-800:]}"
    )


@requires_docker
def test_helm_mirror_rewrites_absolute_urls(tmp_path, serve, chantal_env):
    """Absolute upstream chart URLs (Bitnami-style) are rewritten to the mirror.

    Without rewriting, the mirrored index would send `helm pull` back to the
    (here unreachable) upstream host, defeating the offline mirror.
    """
    charts = _build_charts([("demo", "0.1.0")])
    upstream = tmp_path / "upstream"
    upstream.mkdir(parents=True, exist_ok=True)
    # Absolute URLs back to the upstream server (the Bitnami pattern): reachable
    # at sync time, but a mirror must rewrite them so offline clients use the
    # local copy instead of being sent back upstream.
    base = serve(upstream)
    _write_upstream(upstream, charts, url_base=base)

    chantal_env.write_config(
        {
            "id": "demo-mirror-abs",
            "name": "Demo mirror abs",
            "type": "helm",
            "feed": base,
            "enabled": True,
            "mode": "mirror",
        }
    )
    target = chantal_env.sync_and_publish("demo-mirror-abs")

    published = yaml.safe_load((target / "index.yaml").read_text())
    urls = published["entries"]["demo"][0]["urls"]
    assert urls == ["demo-0.1.0.tgz"], f"absolute URL not rewritten: {urls}"

    ok = _helm(
        target,
        "helm pull local/demo --version 0.1.0; "
        "test -f demo-0.1.0.tgz; "
        "helm show chart local/demo | grep '^name: demo'",
    )
    assert ok.returncode == 0, (
        f"real helm pull from mirror failed:\nstdout={ok.stdout.decode()[-800:]}\n"
        f"stderr={ok.stderr.decode()[-800:]}"
    )


@requires_docker
def test_helm_multiple_versions_visible_to_real_client(tmp_path, serve, chantal_env):
    """Both chart versions appear in `helm search repo --versions` and pull."""
    charts = _build_charts([("demo", "0.1.0"), ("demo", "0.2.0")])
    upstream = tmp_path / "upstream"
    _write_upstream(upstream, charts)

    chantal_env.write_config(
        {
            "id": "demo-multi",
            "name": "Demo multi",
            "type": "helm",
            "feed": serve(upstream),
            "enabled": True,
            "mode": "filtered",  # regenerates index.yaml from both versions
        }
    )
    target = chantal_env.sync_and_publish("demo-multi")

    ok = _helm(
        target,
        "helm search repo local/demo --versions | tee /tmp/s; "
        "grep -q 0.1.0 /tmp/s && grep -q 0.2.0 /tmp/s; "
        "helm pull local/demo --version 0.1.0 && test -f demo-0.1.0.tgz; "
        "helm pull local/demo --version 0.2.0 && test -f demo-0.2.0.tgz",
    )
    assert ok.returncode == 0, (
        f"multi-version helm consumption failed:\nstdout={ok.stdout.decode()[-800:]}\n"
        f"stderr={ok.stderr.decode()[-800:]}"
    )


@requires_docker
def test_helm_filtering_excludes_chart_from_real_client(tmp_path, serve, chantal_env):
    """A chart excluded by filters is not pullable; the kept one is."""
    charts = _build_charts([("demo", "0.1.0"), ("other", "0.1.0")])
    upstream = tmp_path / "upstream"
    _write_upstream(upstream, charts)

    chantal_env.write_config(
        {
            "id": "demo-filt",
            "name": "Demo filtered",
            "type": "helm",
            "feed": serve(upstream),
            "enabled": True,
            "mode": "filtered",
            "filters": {"patterns": {"include": ["^demo$"]}},
        }
    )
    target = chantal_env.sync_and_publish("demo-filt")

    # The published index.yaml itself must be regenerated from the filtered set:
    # the excluded chart must NOT be listed (not just absent as a .tgz).
    index = yaml.safe_load((target / "index.yaml").read_text())
    assert "demo" in index["entries"], "kept chart missing from published index.yaml"
    assert "other" not in index["entries"], (
        "excluded chart 'other' still listed in the published index.yaml "
        "(filtered mode must regenerate the index, not republish upstream)"
    )

    ok = _helm(
        target,
        "helm search repo local/ | tee /tmp/s; "
        "grep -q demo /tmp/s && ! grep -q other /tmp/s; "
        "helm pull local/demo --version 0.1.0 && test -f demo-0.1.0.tgz && echo KEPT_OK; "
        "if helm pull local/other --version 0.1.0 2>/dev/null; then echo OTHER_PRESENT; "
        "else echo OTHER_ABSENT; fi",
    )
    assert ok.returncode == 0, (
        f"filtered helm consumption failed:\nstdout={ok.stdout.decode()[-800:]}\n"
        f"stderr={ok.stderr.decode()[-800:]}"
    )
    assert b"KEPT_OK" in ok.stdout, "kept chart 'demo' not pullable"
    assert b"OTHER_ABSENT" in ok.stdout, "excluded chart 'other' should not be pullable"
