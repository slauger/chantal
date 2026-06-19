"""
End-to-end test: a filtered-mode RPM sync must prune ``modules.yaml`` so the
published modulemd document only references packages that were actually
published (no dangling module artifacts).
"""

from __future__ import annotations

import gzip
import hashlib
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.e2e


def _build_rpm_upstream_with_modules(root: Path) -> None:
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

    # modules.yaml references the published 'demo' package AND a 'ghost' package
    # that is not in primary.xml (so it never gets synced/published).
    modules_yaml = (
        b"---\n"
        b"document: modulemd\n"
        b"version: 2\n"
        b"data:\n"
        b"  name: demo\n"
        b'  stream: "1"\n'
        b"  version: 1\n"
        b"  context: abcd1234\n"
        b"  arch: x86_64\n"
        b"  summary: demo module\n"
        b"  artifacts:\n"
        b"    rpms:\n"
        b"      - demo-0:1.0-1.el9.x86_64\n"
        b"      - ghost-0:9.9-9.el9.x86_64\n"
        b"...\n"
    )
    modules_gz = gzip.compress(modules_yaml)
    (repodata / "modules.yaml.gz").write_bytes(modules_gz)

    # filelists/other/updateinfo blobs exercise the sibling in-place rewrite
    # paths so the pool-integrity assertion covers all four filters (each is a
    # hardlink into the content-addressed pool and must not be truncated).
    filelists = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<filelists xmlns="http://linux.duke.edu/metadata/filelists" packages="1">\n'
        f'<package pkgid="{rpm_sha}" name="demo" arch="x86_64">\n'
        '  <version epoch="0" ver="1.0" rel="1.el9"/>\n'
        "  <file>/usr/bin/demo</file>\n"
        "</package>\n"
        "</filelists>\n"
    ).encode()
    filelists_gz = gzip.compress(filelists)
    (repodata / "filelists.xml.gz").write_bytes(filelists_gz)

    other = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<otherdata xmlns="http://linux.duke.edu/metadata/other" packages="1">\n'
        f'<package pkgid="{rpm_sha}" name="demo" arch="x86_64">\n'
        '  <version epoch="0" ver="1.0" rel="1.el9"/>\n'
        "</package>\n"
        "</otherdata>\n"
    ).encode()
    other_gz = gzip.compress(other)
    (repodata / "other.xml.gz").write_bytes(other_gz)

    updateinfo = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b"<updates>\n"
        b'  <update type="security">\n'
        b"    <id>DEMO-2024:0001</id>\n"
        b'    <pkglist><collection><package name="demo" version="1.0"'
        b' release="1.el9" arch="x86_64"/></collection></pkglist>\n'
        b"  </update>\n"
        b"</updates>\n"
    )
    updateinfo_gz = gzip.compress(updateinfo)
    (repodata / "updateinfo.xml.gz").write_bytes(updateinfo_gz)

    def _block(file_type: str, href: str, comp: bytes, raw: bytes) -> str:
        return (
            f'  <data type="{file_type}">\n'
            f'    <checksum type="sha256">{hashlib.sha256(comp).hexdigest()}</checksum>\n'
            f'    <open-checksum type="sha256">{hashlib.sha256(raw).hexdigest()}</open-checksum>\n'
            f'    <location href="{href}"/>\n'
            f"    <size>{len(comp)}</size>\n"
            f"    <open-size>{len(raw)}</open-size>\n"
            "  </data>\n"
        )

    repomd = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<repomd xmlns="http://linux.duke.edu/metadata/repo">\n'
        "  <revision>1</revision>\n"
        + _block("primary", "repodata/primary.xml.gz", primary_gz, primary)
        + _block("filelists", "repodata/filelists.xml.gz", filelists_gz, filelists)
        + _block("other", "repodata/other.xml.gz", other_gz, other)
        + _block("updateinfo", "repodata/updateinfo.xml.gz", updateinfo_gz, updateinfo)
        + _block("modules", "repodata/modules.yaml.gz", modules_gz, modules_yaml)
        + "</repomd>\n"
    )
    (repodata / "repomd.xml").write_text(repomd, encoding="utf-8")


def test_rpm_modules_filtered_prunes_dangling_artifacts(tmp_path, serve, chantal_env):
    upstream = tmp_path / "upstream"
    _build_rpm_upstream_with_modules(upstream)
    base_url = serve(upstream)

    chantal_env.write_config(
        {
            "id": "demo-rpm-modules",
            "name": "Demo RPM modules",
            "type": "rpm",
            "feed": base_url,
            "enabled": True,
            "mode": "filtered",
        }
    )

    target = chantal_env.sync_and_publish("demo-rpm-modules")

    published = list(target.rglob("*modules.yaml*"))
    assert published, "modules.yaml was not published"

    raw = gzip.decompress(published[0].read_bytes())
    docs = list(yaml.safe_load_all(raw.decode("utf-8")))
    stream = next((d for d in docs if d.get("document") == "modulemd"), None)
    assert stream is not None, "module stream document missing"

    rpms = set(stream["data"]["artifacts"]["rpms"])
    assert rpms == {"demo-0:1.0-1.el9.x86_64"}, f"dangling artifacts not pruned: {rpms}"

    # Regression: the published files are hardlinks into the content-addressed
    # pool. Filtering must not truncate the shared pool blob in place. Every
    # pool file is named "<sha256>_<filename>", so verify each still hashes to
    # the sha256 embedded in its name.
    for pool_file in chantal_env.pool.rglob("*"):
        if not pool_file.is_file():
            continue
        expected = pool_file.name.split("_", 1)[0]
        actual = hashlib.sha256(pool_file.read_bytes()).hexdigest()
        assert actual == expected, f"pool blob corrupted: {pool_file}"
