"""
End-to-end test: mirror mode is a byte-for-byte 1:1 copy.

In ``mode: mirror`` the published repo must reproduce upstream exactly: the
signed ``InRelease`` and the ``Packages``/``Contents`` indices byte-identical,
packages at their upstream pool paths, and nothing regenerated or re-signed.
"""

from __future__ import annotations

import gzip
import hashlib
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

DIST = "jammy"
COMP = "main"
ARCH = "amd64"


def _build_upstream(root: Path) -> dict[str, bytes]:
    """Build an InRelease-signed upstream; return the verbatim bytes to compare."""
    deb_rel = f"pool/{COMP}/d/demo/demo_1.0_{ARCH}.deb"
    (root / deb_rel).parent.mkdir(parents=True, exist_ok=True)
    deb = b"dummy deb payload" * 16
    (root / deb_rel).write_bytes(deb)

    packages = (
        "Package: demo\n"
        "Version: 1.0\n"
        f"Architecture: {ARCH}\n"
        f"Filename: {deb_rel}\n"
        f"Size: {len(deb)}\n"
        f"SHA256: {hashlib.sha256(deb).hexdigest()}\n"
        "Description: demo\n"
        "\n"
    ).encode()
    comp_dir = root / "dists" / DIST / COMP / f"binary-{ARCH}"
    comp_dir.mkdir(parents=True, exist_ok=True)
    packages_gz = gzip.compress(packages)
    (comp_dir / "Packages.gz").write_bytes(packages_gz)

    contents = b"usr/bin/demo    main/demo\n"
    contents_gz = gzip.compress(contents)
    (root / "dists" / DIST / COMP / f"Contents-{ARCH}.gz").write_bytes(contents_gz)

    sha = hashlib.sha256
    release_body = (
        f"Origin: Upstream\nLabel: Upstream\nSuite: {DIST}\nCodename: {DIST}\n"
        f"Components: {COMP}\nArchitectures: {ARCH}\n"
        "Date: Thu, 01 Jan 2026 00:00:00 UTC\nSHA256:\n"
        f" {sha(packages_gz).hexdigest()} {len(packages_gz)} {COMP}/binary-{ARCH}/Packages.gz\n"
        f" {sha(contents_gz).hexdigest()} {len(contents_gz)} {COMP}/Contents-{ARCH}.gz\n"
    )
    # A clearsigned InRelease (fake signature; verification is off in this test).
    inrelease = (
        "-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA256\n\n"
        + release_body
        + "-----BEGIN PGP SIGNATURE-----\n\nFAKE-SIGNATURE-BLOCK\n-----END PGP SIGNATURE-----\n"
    ).encode()
    (root / "dists" / DIST / "InRelease").write_bytes(inrelease)

    return {
        "InRelease": inrelease,
        f"{COMP}/binary-{ARCH}/Packages.gz": packages_gz,
        f"{COMP}/Contents-{ARCH}.gz": contents_gz,
        deb_rel: deb,
    }


def test_apt_mirror_is_byte_for_byte(tmp_path, serve, chantal_env):
    upstream = tmp_path / "upstream"
    verbatim = _build_upstream(upstream)
    base_url = serve(upstream)

    chantal_env.write_config(
        {
            "id": "demo-apt-mirror",
            "name": "Demo APT mirror",
            "type": "apt",
            "feed": base_url,
            "enabled": True,
            "mode": "mirror",
            "apt": {
                "distribution": DIST,
                "components": [COMP],
                "architectures": [ARCH],
                "include_contents": True,
            },
        }
    )

    target = chantal_env.sync_and_publish("demo-apt-mirror")

    # InRelease, Packages.gz and Contents are byte-identical to upstream.
    assert (target / "dists" / DIST / "InRelease").read_bytes() == verbatim["InRelease"]
    pkgs = target / "dists" / DIST / COMP / f"binary-{ARCH}" / "Packages.gz"
    assert pkgs.read_bytes() == verbatim[f"{COMP}/binary-{ARCH}/Packages.gz"]
    contents = target / "dists" / DIST / COMP / f"Contents-{ARCH}.gz"
    assert contents.read_bytes() == verbatim[f"{COMP}/Contents-{ARCH}.gz"]

    # The package sits at its upstream pool path (Filename resolves).
    deb_rel = f"pool/{COMP}/d/demo/demo_1.0_{ARCH}.deb"
    assert (target / deb_rel).read_bytes() == verbatim[deb_rel]

    # Nothing regenerated: no chantal Release, no stray suite-root Packages.gz.
    assert not (target / "dists" / DIST / "Release").exists(), "mirror must not regenerate Release"
    assert not (target / "dists" / DIST / "Packages.gz").exists(), "stray suite-root index"
    assert b"Origin: Chantal" not in (target / "dists" / DIST / "InRelease").read_bytes()
