"""Tests for APT index compression-variant selection and decompression.

A repository whose Release advertises a non-gzip Packages index (xz, bz2, zst
or uncompressed) must still be mirrored. Previously only ``Packages.gz`` was
recognised, so such repos synced zero packages.
"""

from __future__ import annotations

import bz2
import gzip
import lzma

import pytest

from chantal.core.config import RepositoryConfig
from chantal.plugins.apt.sync import (
    AptSyncPlugin,
    _decompress_index,
    _pick_index_variant,
)


def test_pick_index_variant_prefers_gz_then_falls_back():
    assert _pick_index_variant("c/binary-amd64/Packages", {"c/binary-amd64/Packages.gz": 1}) == (
        "c/binary-amd64/Packages.gz"
    )
    # Only xz present -> xz is selected (the bug: previously skipped).
    assert _pick_index_variant("c/binary-amd64/Packages", {"c/binary-amd64/Packages.xz": 1}) == (
        "c/binary-amd64/Packages.xz"
    )
    # Uncompressed only.
    assert _pick_index_variant("c/binary-amd64/Packages", {"c/binary-amd64/Packages": 1}) == (
        "c/binary-amd64/Packages"
    )
    # gz preferred over xz when both present.
    both = {"c/binary-amd64/Packages.gz": 1, "c/binary-amd64/Packages.xz": 1}
    assert _pick_index_variant("c/binary-amd64/Packages", both) == "c/binary-amd64/Packages.gz"
    # Nothing present.
    assert _pick_index_variant("c/binary-amd64/Packages", {}) is None


def test_decompress_index_by_suffix():
    payload = b"Package: demo\nVersion: 1.0\n\n"
    assert _decompress_index(gzip.compress(payload), "main/binary-amd64/Packages.gz") == payload
    assert _decompress_index(lzma.compress(payload), "main/binary-amd64/Packages.xz") == payload
    assert _decompress_index(bz2.compress(payload), "main/binary-amd64/Packages.bz2") == payload
    # Uncompressed (no suffix) is returned as-is.
    assert _decompress_index(payload, "main/binary-amd64/Packages") == payload


def test_decompress_index_zst_streaming_frame():
    """zstd frames without an embedded content size (streaming producers) must
    still decompress (the one-shot API would raise on these)."""
    zstd = pytest.importorskip("zstandard")
    payload = b"Package: demo\nVersion: 1.0\n\n"
    # stream_writer produces a frame without a content-size header.
    import io

    buf = io.BytesIO()
    with zstd.ZstdCompressor().stream_writer(buf, closefd=False) as w:
        w.write(payload)
    assert _decompress_index(buf.getvalue(), "main/binary-amd64/Packages.zst") == payload


def _plugin(tmp_path):
    from chantal.core.config import StorageConfig
    from chantal.core.storage import StorageManager

    (tmp_path / "pool").mkdir()
    storage = StorageManager(
        StorageConfig(
            base_path=str(tmp_path),
            pool_path=str(tmp_path / "pool"),
            published_path=str(tmp_path / "published"),
        )
    )
    config = RepositoryConfig(
        id="u",
        name="U",
        type="apt",
        feed="http://example.com/ubuntu",
        apt={"distribution": "jammy", "components": ["main"], "architectures": ["amd64"]},
    )
    return AptSyncPlugin(storage=storage, config=config)


@pytest.mark.parametrize("ext", [".gz", ".xz", ".bz2", ".zst", ""])
def test_build_metadata_file_list_finds_any_variant(ext, tmp_path):
    """An xz-only (or any-variant) Release still yields a Packages entry."""
    plugin = _plugin(tmp_path)
    path = f"main/binary-amd64/Packages{ext}"
    release_metadata = {
        "components": ["main"],
        "architectures": ["amd64"],
        "sha256": {path: ("deadbeef", 123)},
    }
    files = plugin._build_metadata_file_list(release_metadata, mode="filtered")
    packages = [m for m in files if m.file_type == "Packages"]
    assert len(packages) == 1, f"variant {ext!r} not selected"
    assert packages[0].relative_path == path


def test_build_metadata_file_list_empty_when_no_packages(tmp_path):
    plugin = _plugin(tmp_path)
    release_metadata = {"components": ["main"], "architectures": ["amd64"], "sha256": {}}
    files = plugin._build_metadata_file_list(release_metadata, mode="filtered")
    assert not [m for m in files if m.file_type == "Packages"]
