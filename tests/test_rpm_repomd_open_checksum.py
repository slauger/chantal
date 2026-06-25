"""Regression test: repomd.xml open-checksum/open-size must describe the
*decompressed* metadata for every supported compression — notably ``.xz``,
which was previously unhandled and got the compressed checksum (so dnf rejected
the repository's filtered ``.xz`` filelists/other).
"""

from __future__ import annotations

import bz2
import gzip
import hashlib
import lzma
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from chantal.core.config import StorageConfig
from chantal.core.storage import StorageManager
from chantal.plugins.rpm.publisher import RpmPublisher

_NS = "http://linux.duke.edu/metadata/repo"


@pytest.fixture
def publisher():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "pool").mkdir()
        storage = StorageManager(
            StorageConfig(
                base_path=str(tmp),
                pool_path=str(tmp / "pool"),
                published_path=str(tmp / "published"),
            )
        )
        yield RpmPublisher(storage=storage)


def _compress(payload: bytes, ext: str) -> bytes:
    if ext == ".gz":
        return gzip.compress(payload)
    if ext == ".xz":
        return lzma.compress(payload)
    if ext == ".bz2":
        return bz2.compress(payload)
    if ext == ".zst":
        import zstandard as zstd

        return zstd.ZstdCompressor().compress(payload)
    return payload


@pytest.mark.parametrize("ext", [".gz", ".xz", ".bz2", ".zst", ""])
def test_repomd_open_checksum_describes_decompressed(ext, tmp_path, publisher):
    repodata = tmp_path / "repodata"
    repodata.mkdir()
    payload = b"<filelists packages='1'><package/></filelists>\n"
    compressed = _compress(payload, ext)
    fl = repodata / f"filelists.xml{ext}"
    fl.write_bytes(compressed)

    publisher._generate_repomd_xml(repodata, [("filelists", fl)])

    root = ET.fromstring((repodata / "repomd.xml").read_text())
    data = next(d for d in root.findall(f"{{{_NS}}}data") if d.get("type") == "filelists")
    checksum = data.find(f"{{{_NS}}}checksum").text
    open_checksum = data.find(f"{{{_NS}}}open-checksum").text
    open_size = int(data.find(f"{{{_NS}}}open-size").text)

    # <checksum> is over the compressed file; <open-checksum>/<open-size> over
    # the decompressed payload (== file for the uncompressed case).
    assert checksum == hashlib.sha256(compressed).hexdigest()
    assert open_checksum == hashlib.sha256(payload).hexdigest()
    assert open_size == len(payload)
