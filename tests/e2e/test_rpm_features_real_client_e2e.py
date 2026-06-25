"""
End-to-end tests with a REAL dnf client (Docker) covering RPM repo features.

Beyond the basic hosted-upload install (test_rpm_real_client_e2e.py), these
prove the security- and feature-critical paths a real `dnf`/`rpm` client
observes:

* **Authenticity** — a signed mirror installed with ``gpgcheck=1`` +
  ``repo_gpgcheck=1`` against the upstream key chantal republishes
  (``RPM-GPG-KEY-<id>``); a client lacking that key is refused.
* **Metadata signing (filtered)** — chantal re-signs ``repomd.xml`` with its own
  key; a client verifies it with ``repo_gpgcheck=1``; tampering is detected.
* **Filtering** — an excluded package is not installable.
* **Compression** — zstd-compressed regenerated metadata is consumed by dnf.

Docker-gated; runs on the CI rpm e2e leg (filename contains ``rpm``).
Self-contained: the signed upstream repo is built in-container with
``rpmbuild``/``rpm --addsign``/``createrepo_c``/``gpg``; the published repo is
streamed into the dnf container as a tar over stdin (no bind-mounts).
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
_HAVE_GPG = shutil.which("gpg") is not None or shutil.which("gpg2") is not None
_IMAGE = "almalinux:9"
_EMAIL = "rpm-test@chantal.local"

requires_docker = pytest.mark.skipif(not _HAVE_DOCKER, reason="docker not available")
requires_gpg = pytest.mark.skipif(not _HAVE_GPG, reason="gpg not available (chantal signs on host)")

# Build N signed packages (demo-keep + demo-drop), createrepo_c, and detach-sign
# repomd.xml with an ephemeral key. Emits a tar of the repo dir followed by a
# marker and the ASCII-armored public key, all base64 over stdout.
_BUILD_SCRIPT = r"""
set -e
dnf install -y rpm-build rpm-sign createrepo_c gnupg2 >/dev/null 2>&1
export GNUPGHOME=/gpg; mkdir -p /gpg; chmod 700 /gpg
printf '%%no-protection\nKey-Type: RSA\nKey-Length: 3072\nName-Real: Chantal Test\nName-Email: %s\nExpire-Date: 0\n%%commit\n' EMAIL > /key
gpg --batch --gen-key /key >/dev/null 2>&1
mkdir -p /rb/SPECS /up
for name in demo-keep demo-drop; do
  printf 'Name: %s\nVersion: 1.0\nRelease: 1\nSummary: %s\nLicense: MIT\nBuildArch: noarch\n%%description\n%s\n%%install\nmkdir -p %%{buildroot}/usr/share/%s\necho hello-from-%s > %%{buildroot}/usr/share/%s/README\n%%files\n/usr/share/%s/README\n' \
    "$name" "$name" "$name" "$name" "$name" "$name" "$name" > /rb/SPECS/$name.spec
  rpmbuild --define "_topdir /rb" -bb /rb/SPECS/$name.spec >/dev/null 2>&1
done
cp /rb/RPMS/noarch/*.rpm /up/
rpm --define "_gpg_name EMAIL" --addsign /up/*.rpm >/dev/null 2>&1
createrepo_c /up >/dev/null 2>&1
gpg --batch --yes --detach-sign --armor -o /up/repodata/repomd.xml.asc /up/repodata/repomd.xml
tar -cf - -C /up . | base64 | tr -d '\n'
echo ===KEY===
gpg --armor --export EMAIL | base64 | tr -d '\n'
""".replace("EMAIL", _EMAIL)


def _build_signed_upstream(root: Path) -> str:
    """Build a signed upstream repo into ``root``; return the armored public key."""
    out = subprocess.run(
        ["docker", "run", "--rm", _IMAGE, "bash", "-c", _BUILD_SCRIPT],
        capture_output=True,
        timeout=600,
    )
    assert out.returncode == 0, f"rpm upstream build failed: {out.stderr.decode()[-800:]}"
    repo_b64, _, key_b64 = out.stdout.partition(b"===KEY===")
    root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(base64.b64decode(repo_b64))) as tar:
        tar.extractall(root)  # noqa: S202 - trusted, self-built tar
    return base64.b64decode(key_b64).decode()


def _dnf(published: Path, script: str) -> subprocess.CompletedProcess:
    """Stream the published repo into a dnf container and run ``script``."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        tar.add(published, arcname=".")
    full = "set -e; mkdir -p /repo && tar -xf - -C /repo; " + script
    return subprocess.run(
        ["docker", "run", "--rm", "-i", _IMAGE, "bash", "-c", full],
        input=buf.getvalue(),
        capture_output=True,
        timeout=600,
    )


def _repo_file(*, gpgcheck: int, repo_gpgcheck: int, gpgkey: str | None) -> str:
    lines = [
        "[demo]",
        "name=demo",
        "baseurl=file:///repo",
        "enabled=1",
        f"gpgcheck={gpgcheck}",
        f"repo_gpgcheck={repo_gpgcheck}",
    ]
    if gpgkey:
        lines.append(f"gpgkey=file:///repo/{gpgkey}")
    body = "\\n".join(lines)
    return f'printf "{body}\\n" > /etc/yum.repos.d/demo.repo; '


# --------------------------------------------------------------------------- #


@requires_docker
@requires_gpg
def test_rpm_signed_mirror_installs_with_gpgcheck(tmp_path, serve, chantal_env):
    """A mirror republishes the upstream trust key (``RPM-GPG-KEY-<id>``); a real
    client installs the (upstream-signed) package with ``gpgcheck=1``, and a
    client that does not trust the key is refused."""
    upstream = tmp_path / "upstream"
    pubkey = _build_signed_upstream(upstream)

    chantal_env.write_config(
        {
            "id": "secure",
            "name": "Secure mirror",
            "type": "rpm",
            "feed": serve(upstream),
            "enabled": True,
            "mode": "mirror",
            "verify": {
                "enabled": True,
                "gpgcheck": True,
                "repo_gpgcheck": True,
                "keys": [pubkey],
                "client_key_name": "RPM-GPG-KEY-{repo_id}",
            },
        }
    )
    target = chantal_env.sync_and_publish("secure")
    assert (target / "RPM-GPG-KEY-secure").is_file(), "upstream key not republished"

    # Package authenticity: import the republished key, dnf verifies the
    # upstream-retained package signature with gpgcheck=1.
    ok = _dnf(
        target,
        "rpm --import /repo/RPM-GPG-KEY-secure; "
        + _repo_file(gpgcheck=1, repo_gpgcheck=0, gpgkey="RPM-GPG-KEY-secure")
        + "dnf install -y demo-keep >/dev/null; cat /usr/share/demo-keep/README",
    )
    assert ok.returncode == 0, (
        f"signed install failed:\nstdout={ok.stdout.decode()[-800:]}\n"
        f"stderr={ok.stderr.decode()[-800:]}"
    )
    assert b"hello-from-demo-keep" in ok.stdout

    # With gpgcheck=1 but no key available (none configured, none imported),
    # dnf must refuse the signed package rather than install it unverified.
    bad = _dnf(
        target,
        _repo_file(gpgcheck=1, repo_gpgcheck=0, gpgkey=None)
        + "dnf install -y demo-keep </dev/null",
    )
    assert bad.returncode != 0, (
        f"gpgcheck without a trusted key should refuse the package:\n"
        f"{bad.stdout.decode()[-800:]}"
    )
    combined = (bad.stdout + bad.stderr).upper()
    assert b"GPG" in combined or b"KEY" in combined or b"SIGNATURE" in combined, (
        f"failure should be a GPG/key error, got:\n{bad.stdout.decode()[-800:]}\n"
        f"{bad.stderr.decode()[-800:]}"
    )


@requires_docker
@requires_gpg
def test_rpm_filtered_metadata_signing_repo_gpgcheck(tmp_path, serve, chantal_env):
    """Filtered mode re-signs repomd.xml with chantal's key; a client verifies it
    with repo_gpgcheck=1, and a tampered repomd is rejected."""
    upstream = tmp_path / "upstream"
    pubkey = _build_signed_upstream(upstream)

    chantal_env.write_config(
        {
            "id": "filt",
            "name": "Filtered signed",
            "type": "rpm",
            "feed": serve(upstream),
            "enabled": True,
            "mode": "filtered",
            "verify": {
                "enabled": True,
                "gpgcheck": False,
                "repo_gpgcheck": False,
                "keys": [pubkey],
            },
            "gpg": {"enabled": True, "generate_key": True, "public_key_name": "key.gpg"},
            "filters": {"patterns": {"include": ["^demo-keep$"]}},
        }
    )
    target = chantal_env.sync_and_publish("filt")
    assert (target / "key.gpg").is_file(), "metadata signing key not published"
    assert (target / "repodata" / "repomd.xml.asc").is_file(), "repomd not signed"

    ok = _dnf(
        target,
        "rpm --import /repo/key.gpg; "
        + _repo_file(gpgcheck=0, repo_gpgcheck=1, gpgkey="key.gpg")
        + "dnf -y makecache >/dev/null && dnf install -y demo-keep >/dev/null; "
        + "cat /usr/share/demo-keep/README",
    )
    assert ok.returncode == 0, (
        f"repo_gpgcheck install failed:\nstdout={ok.stdout.decode()[-800:]}\n"
        f"stderr={ok.stderr.decode()[-800:]}"
    )
    assert b"hello-from-demo-keep" in ok.stdout

    # Tampering with the signed repomd.xml must break metadata verification.
    bad = _dnf(
        target,
        "rpm --import /repo/key.gpg; "
        + "sed -i 's/<data/<DATA/' /repo/repodata/repomd.xml; "
        + _repo_file(gpgcheck=0, repo_gpgcheck=1, gpgkey="key.gpg")
        + "dnf -y makecache </dev/null",
    )
    assert (
        bad.returncode != 0
    ), f"tampered repomd should fail repo_gpgcheck:\n{bad.stdout.decode()[-800:]}"
    combined = (bad.stdout + bad.stderr).upper()
    assert b"SIGNATURE" in combined or b"GPG" in combined, (
        f"tamper failure should be a signature error, got:\n"
        f"{bad.stdout.decode()[-800:]}\n{bad.stderr.decode()[-800:]}"
    )


@requires_docker
def test_rpm_filtered_excludes_package(tmp_path, serve, chantal_env):
    """An excluded package is absent from the published repo for a real client."""
    upstream = tmp_path / "upstream"
    _build_signed_upstream(upstream)

    chantal_env.write_config(
        {
            "id": "filt2",
            "name": "Filtered",
            "type": "rpm",
            "feed": serve(upstream),
            "enabled": True,
            "mode": "filtered",
            "filters": {"patterns": {"include": ["^demo-keep$"]}},
        }
    )
    target = chantal_env.sync_and_publish("filt2")

    res = _dnf(
        target,
        _repo_file(gpgcheck=0, repo_gpgcheck=0, gpgkey=None)
        + "dnf install -y demo-keep >/dev/null && echo KEEP_OK; "
        + "dnf list available demo-drop 2>/dev/null && echo DROP_PRESENT || echo DROP_ABSENT",
    )
    assert b"KEEP_OK" in res.stdout, f"kept package failed: {res.stderr.decode()[-600:]}"
    assert b"DROP_ABSENT" in res.stdout, "excluded package should not be available"


@requires_docker
def test_rpm_zstd_metadata_installs(tmp_path, serve, chantal_env):
    """zstd-compressed regenerated repodata is consumable by real dnf."""
    upstream = tmp_path / "upstream"
    _build_signed_upstream(upstream)

    chantal_env.write_config(
        {
            "id": "zstd",
            "name": "Zstd",
            "type": "rpm",
            "feed": serve(upstream),
            "enabled": True,
            "mode": "filtered",
            "filters": {"patterns": {"include": ["^demo-keep$"]}},
            "metadata": {"compression": "zstandard"},
        }
    )
    target = chantal_env.sync_and_publish("zstd")
    assert list(target.glob("repodata/*primary.xml.zst")), "primary.xml.zst not generated"

    ok = _dnf(
        target,
        _repo_file(gpgcheck=0, repo_gpgcheck=0, gpgkey=None)
        + "dnf install -y demo-keep >/dev/null; cat /usr/share/demo-keep/README",
    )
    assert ok.returncode == 0, f"zstd repo install failed: {ok.stderr.decode()[-800:]}"
    assert b"hello-from-demo-keep" in ok.stdout
