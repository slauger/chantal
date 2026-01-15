"""Tests for RPM parser zstandard support."""

from __future__ import annotations

import zstandard as zstd
import pytest

from chantal.plugins.rpm.parsers import _decompress_metadata


class TestZstdDecompression:
    """Test zstandard decompression in parsers."""

    TEST_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<metadata xmlns="http://linux.duke.edu/metadata/common" packages="1">
    <package type="rpm">
        <name>nginx</name>
        <version>1.20.1</version>
    </package>
</metadata>
"""

    def test_decompress_zst_by_extension(self) -> None:
        """Test decompression of .zst file by extension."""
        # Compress with zstandard
        cctx = zstd.ZstdCompressor()
        compressed = cctx.compress(self.TEST_XML)

        # Decompress with parser function
        decompressed = _decompress_metadata(compressed, "primary.xml.zst")
        assert decompressed == self.TEST_XML

    def test_decompress_zst_by_magic_bytes(self) -> None:
        """Test decompression of .zst file by magic bytes."""
        # Compress with zstandard
        cctx = zstd.ZstdCompressor()
        compressed = cctx.compress(self.TEST_XML)

        # Verify magic bytes are present
        assert compressed[:4] == b"\x28\xb5\x2f\xfd"

        # Decompress without extension hint (should detect by magic)
        decompressed = _decompress_metadata(compressed, "unknown.bin")
        assert decompressed == self.TEST_XML

    def test_decompress_zst_with_path(self) -> None:
        """Test decompression of .zst file with full path."""
        # Compress with zstandard
        cctx = zstd.ZstdCompressor()
        compressed = cctx.compress(self.TEST_XML)

        # Decompress with full path
        decompressed = _decompress_metadata(
            compressed, "repodata/abc123-primary.xml.zst"
        )
        assert decompressed == self.TEST_XML

    def test_decompress_gzip_still_works(self) -> None:
        """Test that gzip decompression still works."""
        import gzip

        compressed = gzip.compress(self.TEST_XML)
        decompressed = _decompress_metadata(compressed, "primary.xml.gz")
        assert decompressed == self.TEST_XML

    def test_decompress_bzip2_still_works(self) -> None:
        """Test that bzip2 decompression still works."""
        import bz2

        compressed = bz2.compress(self.TEST_XML)
        decompressed = _decompress_metadata(compressed, "primary.xml.bz2")
        assert decompressed == self.TEST_XML

    def test_decompress_xz_still_works(self) -> None:
        """Test that xz decompression still works."""
        import lzma

        compressed = lzma.compress(self.TEST_XML)
        decompressed = _decompress_metadata(compressed, "primary.xml.xz")
        assert decompressed == self.TEST_XML

    def test_decompress_unknown_format_raises(self) -> None:
        """Test that unknown format raises error."""
        with pytest.raises(ValueError, match="Unknown compression format"):
            _decompress_metadata(b"invalid data", "unknown.xyz")


class TestZstdVariousLevels:
    """Test zstandard decompression at various compression levels."""

    TEST_DATA = b"x" * 10000  # Repetitive data

    def test_decompress_zst_level_1(self) -> None:
        """Test decompression of level 1 zstandard."""
        cctx = zstd.ZstdCompressor(level=1)
        compressed = cctx.compress(self.TEST_DATA)
        decompressed = _decompress_metadata(compressed, "test.zst")
        assert decompressed == self.TEST_DATA

    def test_decompress_zst_level_10(self) -> None:
        """Test decompression of level 10 zstandard."""
        cctx = zstd.ZstdCompressor(level=10)
        compressed = cctx.compress(self.TEST_DATA)
        decompressed = _decompress_metadata(compressed, "test.zst")
        assert decompressed == self.TEST_DATA

    def test_decompress_zst_level_22(self) -> None:
        """Test decompression of max level (22) zstandard."""
        cctx = zstd.ZstdCompressor(level=22)
        compressed = cctx.compress(self.TEST_DATA)
        decompressed = _decompress_metadata(compressed, "test.zst")
        assert decompressed == self.TEST_DATA


class TestZstdLargeData:
    """Test zstandard with larger data."""

    def test_decompress_large_xml(self) -> None:
        """Test decompression of large XML file."""
        # Create large XML (simulating primary.xml)
        large_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<metadata xmlns="http://linux.duke.edu/metadata/common" packages="1000">
"""
        for i in range(1000):
            large_xml += f"""    <package type="rpm">
        <name>package-{i}</name>
        <version>1.0.{i}</version>
        <release>1.el9</release>
        <arch>x86_64</arch>
    </package>
""".encode()
        large_xml += b"</metadata>\n"

        # Compress and decompress
        cctx = zstd.ZstdCompressor()
        compressed = cctx.compress(large_xml)
        decompressed = _decompress_metadata(compressed, "primary.xml.zst")

        assert decompressed == large_xml
        # Verify compression actually worked
        assert len(compressed) < len(large_xml)
