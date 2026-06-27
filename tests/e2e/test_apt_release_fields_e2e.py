"""
End-to-end test: generated-Release field parity.

Asserts the regenerated Release honors the AptConfig overrides: distinct
Suite/Codename, Origin/Label, NotAutomatic/ButAutomaticUpgrades, and a relative
Valid-Until.
"""

from __future__ import annotations

import gzip
import hashlib
import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.apt]

DIST = "jammy"
COMP = "main"
ARCH = "amd64"


def _build_apt_upstream(root: Path) -> None:
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
    (comp_dir / "Packages").write_bytes(packages)
    packages_gz = gzip.compress(packages)
    (comp_dir / "Packages.gz").write_bytes(packages_gz)

    sha = hashlib.sha256
    release = (
        "Origin: Upstream\n"
        f"Suite: {DIST}\n"
        f"Codename: {DIST}\n"
        f"Components: {COMP}\n"
        f"Architectures: {ARCH}\n"
        "Date: Thu, 01 Jan 2026 00:00:00 UTC\n"
        "SHA256:\n"
        f" {sha(packages).hexdigest()} {len(packages)} {COMP}/binary-{ARCH}/Packages\n"
        f" {sha(packages_gz).hexdigest()} {len(packages_gz)} {COMP}/binary-{ARCH}/Packages.gz\n"
    )
    (root / "dists" / DIST / "Release").write_text(release, encoding="utf-8")


def test_apt_release_field_overrides(tmp_path, serve, chantal_env):
    upstream = tmp_path / "upstream"
    _build_apt_upstream(upstream)
    base_url = serve(upstream)

    chantal_env.write_config(
        {
            "id": "demo-apt-relfields",
            "name": "Demo APT Release fields",
            "type": "apt",
            "feed": base_url,
            "enabled": True,
            "mode": "filtered",
            "apt": {
                "distribution": DIST,
                "components": [COMP],
                "architectures": [ARCH],
                "origin": "ACME Mirror",
                "label": "ACME",
                "suite": "stable",
                "codename": "bookworm",
                "not_automatic": True,
                "but_automatic_upgrades": True,
                "valid_until_days": 7,
            },
        }
    )

    target = chantal_env.sync_and_publish("demo-apt-relfields")
    release = (target / "dists" / DIST / "Release").read_text()

    assert "Origin: ACME Mirror" in release
    assert "Label: ACME" in release
    # Suite and Codename are distinct (the key bug this fixes).
    assert "Suite: stable" in release
    assert "Codename: bookworm" in release
    assert "NotAutomatic: yes" in release
    assert "ButAutomaticUpgrades: yes" in release
    # Valid-Until must use the same RFC1123-style format as Date (apt parses it).
    assert re.search(
        r"Valid-Until: \w{3}, \d{2} \w{3} \d{4} \d{2}:\d{2}:\d{2} UTC", release
    ), "Valid-Until missing or wrong date format"


def test_apt_release_defaults(tmp_path, serve, chantal_env):
    # Without overrides: Origin defaults to Chantal, Suite==Codename==distribution,
    # and no pinning / Valid-Until fields.
    upstream = tmp_path / "upstream"
    _build_apt_upstream(upstream)
    base_url = serve(upstream)

    chantal_env.write_config(
        {
            "id": "demo-apt-reldefault",
            "name": "Demo APT defaults",
            "type": "apt",
            "feed": base_url,
            "enabled": True,
            "mode": "filtered",
            "apt": {"distribution": DIST, "components": [COMP], "architectures": [ARCH]},
        }
    )

    target = chantal_env.sync_and_publish("demo-apt-reldefault")
    release = (target / "dists" / DIST / "Release").read_text()

    assert "Origin: Chantal" in release
    assert "Label: Demo APT defaults" in release  # defaults to the repository name
    assert f"Suite: {DIST}" in release
    assert f"Codename: {DIST}" in release
    assert "NotAutomatic" not in release
    assert "ButAutomaticUpgrades" not in release
    assert "Valid-Until" not in release
