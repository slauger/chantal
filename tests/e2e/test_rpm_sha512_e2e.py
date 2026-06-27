"""
End-to-end test: sync an RPM repo whose metadata/packages use **sha512**
checksums (not sha256). Proves the algorithm-aware checksum handling: such a
repo previously broke because chantal assumed sha256 everywhere.
"""

from __future__ import annotations

import gzip
import hashlib
from pathlib import Path

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.rpm]


def _build_sha512_rpm_upstream(root: Path, *, corrupt_package_checksum: bool = False) -> None:
    repodata = root / "repodata"
    repodata.mkdir(parents=True, exist_ok=True)

    rpm = b"dummy rpm payload" * 16
    rpm_name = "demo-1.0-1.el9.x86_64.rpm"
    (root / rpm_name).write_bytes(rpm)
    rpm_sha512 = hashlib.sha512(rpm).hexdigest()
    if corrupt_package_checksum:
        # Declare a wrong checksum: the package must be rejected, not published.
        rpm_sha512 = "0" * 128

    primary = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<metadata xmlns="http://linux.duke.edu/metadata/common"'
        ' xmlns:rpm="http://linux.duke.edu/metadata/rpm" packages="1">\n'
        '<package type="rpm">\n'
        "  <name>demo</name>\n"
        "  <arch>x86_64</arch>\n"
        '  <version epoch="0" ver="1.0" rel="1.el9"/>\n'
        f'  <checksum type="sha512" pkgid="YES">{rpm_sha512}</checksum>\n'
        "  <summary>demo</summary>\n"
        '  <size package="' + str(len(rpm)) + '"/>\n'
        f'  <location href="{rpm_name}"/>\n'
        "  <format><rpm:sourcerpm>demo-1.0-1.el9.src.rpm</rpm:sourcerpm></format>\n"
        "</package>\n"
        "</metadata>\n"
    ).encode("utf-8")

    gz = gzip.compress(primary)
    (repodata / "primary.xml.gz").write_bytes(gz)

    repomd = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<repomd xmlns="http://linux.duke.edu/metadata/repo">\n'
        "  <revision>1</revision>\n"
        '  <data type="primary">\n'
        f'    <checksum type="sha512">{hashlib.sha512(gz).hexdigest()}</checksum>\n'
        f'    <open-checksum type="sha512">{hashlib.sha512(primary).hexdigest()}</open-checksum>\n'
        '    <location href="repodata/primary.xml.gz"/>\n'
        f"    <size>{len(gz)}</size>\n"
        f"    <open-size>{len(primary)}</open-size>\n"
        "  </data>\n"
        "</repomd>\n"
    )
    (repodata / "repomd.xml").write_text(repomd, encoding="utf-8")


def test_rpm_sha512_sync_and_publish(tmp_path, serve, chantal_env):
    upstream = tmp_path / "upstream"
    _build_sha512_rpm_upstream(upstream)
    base_url = serve(upstream)

    chantal_env.write_config(
        {
            "id": "demo-rpm-sha512",
            "name": "Demo RPM sha512",
            "type": "rpm",
            "feed": base_url,
            "enabled": True,
            "mode": "filtered",
        }
    )

    target = chantal_env.sync_and_publish("demo-rpm-sha512")

    assert (target / "repodata" / "repomd.xml").exists()
    assert list(target.rglob("demo-1.0-1.el9.x86_64.rpm")), "sha512 package not synced/published"


def test_rpm_sha512_bad_package_checksum_is_rejected(tmp_path, serve, chantal_env):
    upstream = tmp_path / "upstream"
    _build_sha512_rpm_upstream(upstream, corrupt_package_checksum=True)
    base_url = serve(upstream)

    chantal_env.write_config(
        {
            "id": "demo-rpm-bad",
            "name": "Demo RPM bad checksum",
            "type": "rpm",
            "feed": base_url,
            "enabled": True,
            "mode": "filtered",
        }
    )

    target = chantal_env.sync_and_publish("demo-rpm-bad")

    # Metadata still publishes, but the package with the wrong checksum must not.
    assert not list(
        target.rglob("demo-1.0-1.el9.x86_64.rpm")
    ), "package with invalid sha512 checksum should have been rejected"
