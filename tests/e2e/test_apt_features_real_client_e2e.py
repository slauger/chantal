"""
End-to-end tests with a REAL apt client (Docker) covering APT repo features.

Beyond the basic install tests (test_apt_real_client_e2e / test_deb_real_client),
these prove the security- and feature-critical paths a real apt client observes:

* **Authenticity** — chantal signs the regenerated ``Release`` (InRelease +
  Release.gpg) with a generated key and exports the public key; a real apt
  installs with ``signed-by=`` and **no** ``[trusted=yes]``, and a client
  without the key is refused.
* **by-hash** — apt fetches indices through ``by-hash/SHA256/`` even when the
  plain index files are removed from the served tree.
* **arch:all** — an ``Architecture: all`` package is installable on a
  concrete-arch client from the regenerated per-arch index.

Docker-gated; runs on the CI apt e2e leg (filename contains ``apt``).
Self-contained: the upstream (real ``.deb``/source + indices) is built
in-container with ``dpkg-deb``; the published repo is streamed into the apt
container as a tar over stdin (no bind-mounts).
"""

from __future__ import annotations

import io
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.apt]

_HAVE_DOCKER = shutil.which("docker") is not None
_HAVE_GPG = shutil.which("gpg") is not None
_IMAGE = "debian:bookworm"

DIST = "jammy"
COMP = "main"
ARCH = "amd64"

requires_docker = pytest.mark.skipif(not _HAVE_DOCKER, reason="docker not available")
requires_gpg = pytest.mark.skipif(not _HAVE_GPG, reason="gpg not available (chantal signs on host)")


def _build_real_deb(name: str = "hello-chantal") -> bytes:
    """Build a genuine .deb in a debian container; return its bytes."""
    script = (
        "set -e; mkdir -p /pkg/DEBIAN /pkg/usr/bin; "
        f'printf "Package: {name}\\nVersion: 1.0\\nArchitecture: amd64\\n'
        f'Maintainer: t <t@e.x>\\nDescription: chantal real-apt test\\n" > /pkg/DEBIAN/control; '
        f'printf "#!/bin/sh\\necho hello-from-{name}\\n" > /pkg/usr/bin/{name}; '
        f"chmod +x /pkg/usr/bin/{name}; "
        "dpkg-deb --build /pkg /out.deb >/dev/null; base64 -w0 /out.deb"
    )
    out = subprocess.run(
        ["docker", "run", "--rm", _IMAGE, "bash", "-c", script],
        capture_output=True,
        timeout=300,
    )
    assert out.returncode == 0, f"deb build failed: {out.stderr.decode()[-500:]}"
    import base64

    return base64.b64decode(out.stdout)


def _build_binary_upstream(
    root: Path, deb: bytes, name: str = "hello-chantal", *, compression: str = "gz"
) -> None:
    """Write a minimal binary apt upstream (pool + Packages + Release).

    ``compression`` selects which Packages index variant the upstream ships:
    ``"gz"`` writes Packages + Packages.gz; ``"xz"`` writes ONLY Packages.xz
    (to exercise non-gzip index handling).
    """
    import gzip
    import hashlib
    import lzma

    deb_rel = f"pool/{COMP}/h/{name}/{name}_1.0_{ARCH}.deb"
    (root / deb_rel).parent.mkdir(parents=True, exist_ok=True)
    (root / deb_rel).write_bytes(deb)

    packages = (
        f"Package: {name}\n"
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
    sha = hashlib.sha256
    lines = []
    if compression == "xz":
        packages_xz = lzma.compress(packages)
        (comp_dir / "Packages.xz").write_bytes(packages_xz)
        lines.append(
            f" {sha(packages_xz).hexdigest()} {len(packages_xz)} "
            f"{COMP}/binary-{ARCH}/Packages.xz\n"
        )
    else:
        (comp_dir / "Packages").write_bytes(packages)
        packages_gz = gzip.compress(packages)
        (comp_dir / "Packages.gz").write_bytes(packages_gz)
        lines.append(
            f" {sha(packages).hexdigest()} {len(packages)} " f"{COMP}/binary-{ARCH}/Packages\n"
        )
        lines.append(
            f" {sha(packages_gz).hexdigest()} {len(packages_gz)} "
            f"{COMP}/binary-{ARCH}/Packages.gz\n"
        )

    release = (
        f"Origin: Upstream\nSuite: {DIST}\nCodename: {DIST}\nComponents: {COMP}\n"
        f"Architectures: {ARCH}\nDate: Thu, 01 Jan 2026 00:00:00 UTC\nSHA256:\n" + "".join(lines)
    )
    (root / "dists" / DIST / "Release").write_text(release, encoding="utf-8")


def _client(published: Path, script: str) -> subprocess.CompletedProcess:
    """Stream the published repo into a debian container and run ``script``."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        tar.add(published, arcname=".")
    prep = (
        "set -e; mkdir -p /repo && tar -xf - -C /repo; "
        "rm -f /etc/apt/sources.list /etc/apt/sources.list.d/* 2>/dev/null || true; "
    )
    return subprocess.run(
        ["docker", "run", "--rm", "-i", _IMAGE, "bash", "-c", prep + script],
        input=buf.getvalue(),
        capture_output=True,
        timeout=600,
    )


# --------------------------------------------------------------------------- #


@requires_docker
@requires_gpg
def test_apt_signed_repo_installs_without_trusted(tmp_path, serve, chantal_env):
    """chantal-signed Release verifies in a real apt via signed-by= (no
    trusted=yes); a client without the key is refused."""
    deb = _build_real_deb()
    upstream = tmp_path / "upstream"
    _build_binary_upstream(upstream, deb)

    chantal_env.write_config(
        {
            "id": "signed-apt",
            "name": "Signed apt",
            "type": "apt",
            "feed": serve(upstream),
            "enabled": True,
            "mode": "filtered",
            "apt": {"distribution": DIST, "components": [COMP], "architectures": [ARCH]},
            "gpg": {
                "enabled": True,
                "generate_key": True,
                "key_email": "repo@chantal.local",
                "public_key_name": "key.asc",
            },
        }
    )
    target = chantal_env.sync_and_publish("signed-apt")
    assert (target / "key.asc").is_file(), "exported public key not published"
    assert (target / "dists" / DIST / "InRelease").is_file(), "InRelease not signed"

    # Install with signature verification ON (signed-by=, no trusted=yes).
    ok = _client(
        target,
        "mkdir -p /etc/apt/keyrings; cp /repo/key.asc /etc/apt/keyrings/chantal.asc; "
        f'echo "deb [signed-by=/etc/apt/keyrings/chantal.asc] file:/repo {DIST} {COMP}" '
        "> /etc/apt/sources.list.d/c.list; "
        "apt-get update; apt-get install -y hello-chantal; hello-chantal",
    )
    assert ok.returncode == 0, (
        f"signed apt install failed:\nstdout={ok.stdout.decode()[-800:]}\n"
        f"stderr={ok.stderr.decode()[-800:]}"
    )
    assert b"hello-from-hello-chantal" in ok.stdout

    # Without the key, apt-get update must fail (NO_PUBKEY / not signed).
    bad = _client(
        target,
        f'echo "deb file:/repo {DIST} {COMP}" > /etc/apt/sources.list.d/c.list; ' "apt-get update",
    )
    assert (
        bad.returncode != 0
    ), f"unsigned-trust apt update should fail:\nstderr={bad.stderr.decode()[-800:]}"
    combined = (bad.stdout + bad.stderr).upper()
    assert (
        b"NO_PUBKEY" in combined or b"NOT SIGNED" in combined or b"NOTSIGNED" in combined
    ), f"failure should be a signature/key error, got:\n{bad.stderr.decode()[-800:]}"


@requires_docker
def test_apt_byhash_fetch_from_real_client(tmp_path, serve, chantal_env):
    """apt retrieves indices via by-hash/SHA256 even when the plain Packages
    files are removed from the published tree."""
    deb = _build_real_deb()
    upstream = tmp_path / "upstream"
    _build_binary_upstream(upstream, deb)

    chantal_env.write_config(
        {
            "id": "byhash-apt",
            "name": "By-hash apt",
            "type": "apt",
            "feed": serve(upstream),
            "enabled": True,
            "mode": "filtered",
            "apt": {
                "distribution": DIST,
                "components": [COMP],
                "architectures": [ARCH],
                "by_hash": True,
            },
        }
    )
    target = chantal_env.sync_and_publish("byhash-apt")
    byhash_dir = target / "dists" / DIST / COMP / f"binary-{ARCH}" / "by-hash" / "SHA256"
    assert byhash_dir.is_dir(), "by-hash dir not published"

    # Remove the plain Packages indices so the client MUST use by-hash.
    for p in (target / "dists" / DIST / COMP / f"binary-{ARCH}").glob("Packages*"):
        p.unlink()

    ok = _client(
        target,
        f'echo "deb [trusted=yes] file:/repo {DIST} {COMP}" > /etc/apt/sources.list.d/c.list; '
        "apt-get -o Acquire::By-Hash=force update; "
        "apt-get install -y hello-chantal; hello-chantal",
    )
    assert ok.returncode == 0, (
        f"by-hash apt install failed:\nstdout={ok.stdout.decode()[-800:]}\n"
        f"stderr={ok.stderr.decode()[-800:]}"
    )
    assert b"hello-from-hello-chantal" in ok.stdout


@requires_docker
def test_apt_arch_all_visible_to_real_client(tmp_path, serve, chantal_env):
    """An Architecture: all package is installable on a concrete-arch client
    (fanned out into binary-<arch>/Packages)."""
    import base64
    import gzip
    import hashlib

    # Build an arch:all .deb in-container.
    script = (
        "set -e; mkdir -p /pkg/DEBIAN /pkg/usr/share/demo-doc; "
        'printf "Package: demo-doc\\nVersion: 1.0\\nArchitecture: all\\n'
        'Maintainer: t <t@e.x>\\nDescription: arch all doc\\n" > /pkg/DEBIAN/control; '
        "echo archall-readme-marker > /pkg/usr/share/demo-doc/README; "
        "dpkg-deb --build /pkg /out.deb >/dev/null; base64 -w0 /out.deb"
    )
    out = subprocess.run(
        ["docker", "run", "--rm", _IMAGE, "bash", "-c", script],
        capture_output=True,
        timeout=300,
    )
    assert out.returncode == 0, f"arch:all deb build failed: {out.stderr.decode()[-500:]}"
    deb = base64.b64decode(out.stdout)

    upstream = tmp_path / "upstream"
    deb_rel = f"pool/{COMP}/d/demo-doc/demo-doc_1.0_all.deb"
    (upstream / deb_rel).parent.mkdir(parents=True, exist_ok=True)
    (upstream / deb_rel).write_bytes(deb)
    # An Architecture: all package is listed in each per-arch index by Debian
    # convention (apt only reads binary-<its-arch>/Packages).
    packages = (
        "Package: demo-doc\nVersion: 1.0\nArchitecture: all\nMaintainer: t <t@e.x>\n"
        f"Filename: {deb_rel}\nSize: {len(deb)}\n"
        f"SHA256: {hashlib.sha256(deb).hexdigest()}\nDescription: arch all doc\n\n"
    ).encode()
    comp_dir = upstream / "dists" / DIST / COMP / f"binary-{ARCH}"
    comp_dir.mkdir(parents=True, exist_ok=True)
    (comp_dir / "Packages").write_bytes(packages)
    pgz = gzip.compress(packages)
    (comp_dir / "Packages.gz").write_bytes(pgz)
    sha = hashlib.sha256
    release = (
        f"Origin: Upstream\nSuite: {DIST}\nCodename: {DIST}\nComponents: {COMP}\n"
        f"Architectures: {ARCH}\nDate: Thu, 01 Jan 2026 00:00:00 UTC\nSHA256:\n"
        f" {sha(packages).hexdigest()} {len(packages)} {COMP}/binary-{ARCH}/Packages\n"
        f" {sha(pgz).hexdigest()} {len(pgz)} {COMP}/binary-{ARCH}/Packages.gz\n"
    )
    (upstream / "dists" / DIST / "Release").write_text(release, encoding="utf-8")

    chantal_env.write_config(
        {
            "id": "archall-apt",
            "name": "arch all apt",
            "type": "apt",
            "feed": serve(upstream),
            "enabled": True,
            "mode": "filtered",
            "apt": {"distribution": DIST, "components": [COMP], "architectures": [ARCH]},
        }
    )
    target = chantal_env.sync_and_publish("archall-apt")
    # arch:all must be fanned out into the concrete binary-amd64 index.
    assert (
        target / "dists" / DIST / COMP / f"binary-{ARCH}" / "Packages"
    ).is_file(), "binary-amd64 index missing for arch:all package"

    ok = _client(
        target,
        f'echo "deb [trusted=yes] file:/repo {DIST} {COMP}" > /etc/apt/sources.list.d/c.list; '
        "apt-get update; apt-get install -y demo-doc; cat /usr/share/demo-doc/README",
    )
    assert ok.returncode == 0, (
        f"arch:all install on {ARCH} failed:\nstdout={ok.stdout.decode()[-800:]}\n"
        f"stderr={ok.stderr.decode()[-800:]}"
    )
    assert b"archall-readme-marker" in ok.stdout


@requires_docker
def test_apt_xz_only_repo_installs(tmp_path, serve, chantal_env):
    """A repo whose Release advertises only Packages.xz still mirrors and
    installs (previously such repos synced zero packages)."""
    deb = _build_real_deb()
    upstream = tmp_path / "upstream"
    _build_binary_upstream(upstream, deb, compression="xz")

    chantal_env.write_config(
        {
            "id": "xz-apt",
            "name": "Xz apt",
            "type": "apt",
            "feed": serve(upstream),
            "enabled": True,
            "mode": "filtered",
            "apt": {"distribution": DIST, "components": [COMP], "architectures": [ARCH]},
        }
    )
    target = chantal_env.sync_and_publish("xz-apt")
    assert list(target.rglob("hello-chantal_1.0_amd64.deb")), "xz-only repo synced 0 packages"

    ok = _client(
        target,
        f'echo "deb [trusted=yes] file:/repo {DIST} {COMP}" > /etc/apt/sources.list.d/c.list; '
        "apt-get update; apt-get install -y hello-chantal; hello-chantal",
    )
    assert ok.returncode == 0, (
        f"xz-only repo install failed:\nstdout={ok.stdout.decode()[-800:]}\n"
        f"stderr={ok.stderr.decode()[-800:]}"
    )
    assert b"hello-from-hello-chantal" in ok.stdout
