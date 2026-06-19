"""End-to-end sync->publish test for the RPM plugin."""

from __future__ import annotations

import gzip
import hashlib
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e


def _build_rpm_upstream(root: Path) -> None:
    """Create a minimal yum/dnf repo (repomd.xml + primary.xml.gz + one rpm)."""
    repodata = root / "repodata"
    repodata.mkdir(parents=True, exist_ok=True)

    rpm = b"dummy rpm payload" * 16
    rpm_name = "demo-1.0-1.el9.x86_64.rpm"
    (root / rpm_name).write_bytes(rpm)
    rpm_sha = hashlib.sha256(rpm).hexdigest()

    primary = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<metadata xmlns="http://linux.duke.edu/metadata/common"'
        ' xmlns:rpm="http://linux.duke.edu/metadata/rpm" packages="1">\n'
        '<package type="rpm">\n'
        "  <name>demo</name>\n"
        "  <arch>x86_64</arch>\n"
        '  <version epoch="0" ver="1.0" rel="1.el9"/>\n'
        f'  <checksum type="sha256" pkgid="YES">{rpm_sha}</checksum>\n'
        "  <summary>demo</summary>\n"
        "  <description>demo package</description>\n"
        '  <time file="1" build="1"/>\n'
        f'  <size package="{len(rpm)}" installed="{len(rpm)}" archive="{len(rpm)}"/>\n'
        f'  <location href="{rpm_name}"/>\n'
        "  <format>\n"
        "    <rpm:license>MIT</rpm:license>\n"
        "    <rpm:group>Unspecified</rpm:group>\n"
        "    <rpm:sourcerpm>demo-1.0-1.el9.src.rpm</rpm:sourcerpm>\n"
        '    <rpm:header-range start="0" end="0"/>\n'
        "  </format>\n"
        "</package>\n"
        "</metadata>\n"
    ).encode()

    gz = gzip.compress(primary)
    (repodata / "primary.xml.gz").write_bytes(gz)

    repomd = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<repomd xmlns="http://linux.duke.edu/metadata/repo"'
        ' xmlns:rpm="http://linux.duke.edu/metadata/rpm">\n'
        "  <revision>1</revision>\n"
        '  <data type="primary">\n'
        f'    <checksum type="sha256">{hashlib.sha256(gz).hexdigest()}</checksum>\n'
        f'    <open-checksum type="sha256">{hashlib.sha256(primary).hexdigest()}</open-checksum>\n'
        '    <location href="repodata/primary.xml.gz"/>\n'
        "    <timestamp>1</timestamp>\n"
        f"    <size>{len(gz)}</size>\n"
        f"    <open-size>{len(primary)}</open-size>\n"
        "  </data>\n"
        "</repomd>\n"
    )
    (repodata / "repomd.xml").write_text(repomd, encoding="utf-8")


def test_rpm_sync_and_publish(tmp_path, serve, chantal_env):
    upstream = tmp_path / "upstream"
    _build_rpm_upstream(upstream)
    base_url = serve(upstream)

    chantal_env.write_config(
        {
            "id": "demo-rpm",
            "name": "Demo RPM",
            "type": "rpm",
            "feed": base_url,
            "enabled": True,
            "mode": "filtered",
        }
    )

    target = chantal_env.sync_and_publish("demo-rpm")

    # repomd.xml was regenerated and the package was published.
    assert (target / "repodata" / "repomd.xml").exists()
    assert list(target.rglob("demo-1.0-1.el9.x86_64.rpm")), "published rpm not found"
