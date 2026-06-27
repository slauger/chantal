"""Regression tests for filtering RPM secondary metadata (filelists/other).

Two bugs are covered:

* **zstd one-shot decompression** - a ``filelists.xml.zst`` whose frame omits the
  embedded content size (what createrepo_c/streaming producers emit) used to make
  the one-shot ``ZstdDecompressor().decompress()`` raise, so the filter silently
  republished the *unfiltered* upstream file.
* **pkgid checksum algorithm** - filelists/other were matched against the
  surviving packages by ``pkgid`` (the package checksum in the repo's algorithm,
  which may be sha1/sha512), compared to the locally-computed sha256. For a
  sha1/sha512 repo that mismatch dropped *every* package from filelists/other.
  Matching by NVRA fixes both algorithms.
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET

import pytest
import zstandard as zstd

from chantal.core.config import StorageConfig
from chantal.core.storage import StorageManager
from chantal.db.models import ContentItem
from chantal.plugins.rpm.publisher import RpmPublisher

FILELISTS_NS = "http://linux.duke.edu/metadata/filelists"


def _zst_sizeless(data: bytes) -> bytes:
    """zstd-compress without an embedded content-size header (streaming frame)."""
    buf = io.BytesIO()
    with zstd.ZstdCompressor().stream_writer(buf, closefd=False) as w:
        w.write(data)
    return buf.getvalue()


def _filelists_xml(pkgid: str, checksum_type: str) -> bytes:
    """A one-package filelists.xml whose pkgid uses the given checksum algorithm."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<filelists xmlns="{FILELISTS_NS}" packages="2">\n'
        f'  <package pkgid="{pkgid}" name="demo" arch="x86_64">\n'
        '    <version epoch="0" ver="1.0" rel="1.el9"/>\n'
        "    <file>/usr/bin/demo</file>\n"
        "  </package>\n"
        f'  <package pkgid="{"f" * len(pkgid)}" name="gone" arch="x86_64">\n'
        '    <version epoch="0" ver="2.0" rel="1.el9"/>\n'
        "    <file>/usr/bin/gone</file>\n"
        "  </package>\n"
        "</filelists>\n"
    ).encode()


@pytest.fixture
def publisher(tmp_path):
    storage = StorageManager(
        StorageConfig(
            base_path=str(tmp_path),
            pool_path=str(tmp_path / "pool"),
            published_path=str(tmp_path / "published"),
        )
    )
    return RpmPublisher(storage=storage)


@pytest.mark.parametrize(
    "checksum_type, pkgid",
    [
        ("sha1", "a" * 40),  # older repos
        ("sha256", "b" * 64),
        ("sha512", "c" * 128),  # newer EL9/Fedora
    ],
)
def test_filter_filelists_zst_matches_by_nvra(publisher, tmp_path, checksum_type, pkgid):
    """A sha1/sha256/sha512 repo with a size-less .zst filelists must keep the
    surviving package (matched by NVRA) and drop the removed one."""
    repodata = tmp_path / "repodata"
    repodata.mkdir()
    filelists_path = repodata / "filelists.xml.zst"
    filelists_path.write_bytes(_zst_sizeless(_filelists_xml(pkgid, checksum_type)))

    # The surviving package: same NVRA as the 'demo' entry, but its stored sha256
    # deliberately differs from the upstream pkgid (which may be sha1/sha512).
    survivor = ContentItem(
        content_type="rpm",
        name="demo",
        version="1.0",
        sha256="d" * 64,
        size_bytes=1,
        pool_path="dd/dd/demo.rpm",
        filename="demo-1.0-1.el9.x86_64.rpm",
        content_metadata={"release": "1.el9", "arch": "x86_64"},
    )

    result = publisher._filter_and_regenerate_filelists(
        [survivor], repodata, [("filelists", filelists_path)]
    )

    # The filter must have produced a regenerated file (not fallen back to the
    # unfiltered original on a decompression error).
    _, out_path = next(ft for ft in result if ft[0] == "filelists")
    from chantal.plugins.rpm.modules import decompress_bytes

    root = ET.fromstring(decompress_bytes(out_path.read_bytes(), out_path.suffix))
    names = [p.get("name") for p in root.findall(f"{{{FILELISTS_NS}}}package")]
    assert names == ["demo"], f"expected only the surviving NVRA, got {names}"
    assert root.get("packages") == "1"


def _updateinfo_xml() -> str:
    return (
        "<updates>\n"
        '  <update type="security" status="stable">\n'
        "    <id>TEST-1</id>\n"
        "    <title>demo advisory</title>\n"
        '    <issued date="2026-01-01 00:00:00"/>\n'
        "    <pkglist>\n"
        "      <collection>\n"
        '        <package name="demo" version="1.0" release="1.el9" epoch="0" arch="x86_64">\n'
        "          <filename>demo-1.0-1.el9.x86_64.rpm</filename>\n"
        "        </package>\n"
        "      </collection>\n"
        "    </pkglist>\n"
        "  </update>\n"
        "</updates>\n"
    )


def test_filter_updateinfo_xz_stays_xz_compressed(publisher, tmp_path):
    """An xz updateinfo must be rewritten as valid xz, not plaintext under a .xz
    name (the missing .xz branch corrupted errata)."""
    import lzma

    repodata = tmp_path / "repodata"
    repodata.mkdir()
    ui_path = repodata / "updateinfo.xml.xz"
    ui_path.write_bytes(lzma.compress(_updateinfo_xml().encode()))

    survivor = ContentItem(
        content_type="rpm",
        name="demo",
        version="1.0",
        sha256="d" * 64,
        size_bytes=1,
        pool_path="dd/dd/demo.rpm",
        filename="demo-1.0-1.el9.x86_64.rpm",
        content_metadata={"release": "1.el9", "arch": "x86_64"},
    )

    result = publisher._filter_and_regenerate_updateinfo(
        [survivor], repodata, [("updateinfo", ui_path)]
    )

    _, out_path = next(ft for ft in result if ft[0] == "updateinfo")
    # Must be genuinely xz-compressed; lzma raises on plaintext.
    data = lzma.open(out_path, "rb").read()
    assert b"TEST-1" in data  # the advisory survived the filter


def _published(repodata):
    """Create on-disk metadata files and the (file_type, path) tuples for them."""
    files = {
        "primary": "1111-primary.xml.gz",
        "primary_zck": "2222-primary.xml.zck",
        "primary_db": "3333-primary.sqlite.bz2",
    }
    out = []
    for file_type, name in files.items():
        p = repodata / name
        p.write_bytes(b"x")
        out.append((file_type, p))
    return out


def test_filtered_mode_drops_zck_and_db(publisher, tmp_path):
    """Filtered mode must drop the package-enumerating *_zck and *_db variants."""
    repodata = tmp_path / "repodata"
    repodata.mkdir()
    published = _published(repodata)

    kept = publisher._drop_unpublishable_metadata(published, repodata, "filtered")

    assert [ft for ft, _ in kept] == ["primary"]
    assert not (repodata / "2222-primary.xml.zck").exists()
    assert not (repodata / "3333-primary.sqlite.bz2").exists()


def test_mirror_mode_drops_zck_and_db(publisher, tmp_path):
    """Mirror mode also drops *_zck and *_db: chantal regenerates primary.xml
    with rewritten Packages/ locations even in mirror mode, so the kept sqlite
    would point sqlite-consuming clients at stale upstream paths."""
    repodata = tmp_path / "repodata"
    repodata.mkdir()
    published = _published(repodata)

    kept = publisher._drop_unpublishable_metadata(published, repodata, "mirror")

    assert [ft for ft, _ in kept] == ["primary"]
    assert not (repodata / "2222-primary.xml.zck").exists()
    assert not (repodata / "3333-primary.sqlite.bz2").exists()
