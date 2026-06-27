"""
End-to-end test: publishing an RPM repo with a configured trusted upstream key
writes that key into the published repository root so downstream clients can
``gpgcheck=1``. Exercises the full sync->publish CLI path.

``gpgcheck``/``repo_gpgcheck`` are disabled so no signature verification (and
hence no gpg toolchain) is needed during sync; ``verify`` stays enabled so the
publisher emits the client key.
"""

from __future__ import annotations

import gzip
import hashlib
from pathlib import Path

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.rpm]

_UPSTREAM_KEY = (
    "-----BEGIN PGP PUBLIC KEY BLOCK-----\n"
    "mDMEZ-fake-upstream-vendor-key-material\n"
    "-----END PGP PUBLIC KEY BLOCK-----"
)


def _build_rpm_upstream(root: Path) -> None:
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
        f'  <size package="{len(rpm)}"/>\n'
        f'  <location href="{rpm_name}"/>\n'
        "  <format><rpm:sourcerpm>demo-1.0-1.el9.src.rpm</rpm:sourcerpm></format>\n"
        "</package>\n"
        "</metadata>\n"
    ).encode()
    primary_gz = gzip.compress(primary)
    (repodata / "primary.xml.gz").write_bytes(primary_gz)

    repomd = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<repomd xmlns="http://linux.duke.edu/metadata/repo">\n'
        "  <revision>1</revision>\n"
        '  <data type="primary">\n'
        f'    <checksum type="sha256">{hashlib.sha256(primary_gz).hexdigest()}</checksum>\n'
        f'    <open-checksum type="sha256">{hashlib.sha256(primary).hexdigest()}</open-checksum>\n'
        '    <location href="repodata/primary.xml.gz"/>\n'
        f"    <size>{len(primary_gz)}</size>\n"
        f"    <open-size>{len(primary)}</open-size>\n"
        "  </data>\n"
        "</repomd>\n"
    )
    (repodata / "repomd.xml").write_text(repomd, encoding="utf-8")


def test_rpm_publishes_trusted_upstream_key(tmp_path, serve, chantal_env):
    upstream = tmp_path / "upstream"
    _build_rpm_upstream(upstream)
    base_url = serve(upstream)

    chantal_env.write_config(
        {
            "id": "demo-rpm-clientkey",
            "name": "Demo RPM client key",
            "type": "rpm",
            "feed": base_url,
            "enabled": True,
            "mode": "filtered",
            "verify": {
                "enabled": True,
                # No actual verification (keeps the gpg toolchain out of the
                # test); we only want the publisher to emit the trusted key.
                "gpgcheck": False,
                "repo_gpgcheck": False,
                "keys": [_UPSTREAM_KEY],
            },
        }
    )

    target = chantal_env.sync_and_publish("demo-rpm-clientkey")

    key_file = target / "RPM-GPG-KEY-demo-rpm-clientkey"
    assert key_file.exists(), "trusted upstream key was not published"
    assert _UPSTREAM_KEY in key_file.read_text()


def test_rpm_publishes_key_from_global_verify_fallback(tmp_path, serve, chantal_env):
    # verify is configured only globally; the repo inherits it via the publish
    # global-fallback. Proves the CLI wiring, not just the publisher.
    upstream = tmp_path / "upstream"
    _build_rpm_upstream(upstream)
    base_url = serve(upstream)

    chantal_env.write_config(
        {
            "id": "demo-rpm-globalkey",
            "name": "Demo RPM global key",
            "type": "rpm",
            "feed": base_url,
            "enabled": True,
            "mode": "filtered",
        },
        extra={
            "verify": {
                "enabled": True,
                "gpgcheck": False,
                "repo_gpgcheck": False,
                "keys": [_UPSTREAM_KEY],
            }
        },
    )

    target = chantal_env.sync_and_publish("demo-rpm-globalkey")

    key_file = target / "RPM-GPG-KEY-demo-rpm-globalkey"
    assert key_file.exists(), "global verify fallback did not publish the key"
    assert _UPSTREAM_KEY in key_file.read_text()
