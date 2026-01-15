"""Tests for RPM compression utilities."""

from __future__ import annotations

import gzip
import bz2
import pytest
import zstandard as zstd

from chantal.plugins.rpm.compression import (
    CompressionFormat,
    detect_compression,
    compress_file,
    decompress_file,
    get_extension,
    add_compression_extension,
)


class TestCompressionDetection:
    """Test compression format detection."""

    def test_detect_gzip(self) -> None:
        """Test gzip detection from filename."""
        assert detect_compression("primary.xml.gz") == "gzip"
        assert detect_compression("repodata/abc123-primary.xml.gz") == "gzip"

    def test_detect_zstandard(self) -> None:
        """Test zstandard detection from filename."""
        assert detect_compression("primary.xml.zst") == "zstandard"
        assert detect_compression("repodata/abc123-primary.xml.zst") == "zstandard"

    def test_detect_bzip2(self) -> None:
        """Test bzip2 detection from filename."""
        assert detect_compression("primary.xml.bz2") == "bzip2"
        assert detect_compression("repodata/abc123-primary.xml.bz2") == "bzip2"

    def test_detect_none(self) -> None:
        """Test detection of uncompressed files."""
        assert detect_compression("primary.xml") == "none"
        assert detect_compression("repodata.xml") == "none"


class TestCompressionRoundtrip:
    """Test compression and decompression roundtrips."""

    TEST_DATA = b"<metadata><package>test</package></metadata>"

    def test_gzip_roundtrip(self) -> None:
        """Test gzip compression and decompression."""
        compressed = compress_file(self.TEST_DATA, "gzip")
        decompressed = decompress_file(compressed, "gzip")
        assert decompressed == self.TEST_DATA

    def test_zstandard_roundtrip(self) -> None:
        """Test zstandard compression and decompression."""
        compressed = compress_file(self.TEST_DATA, "zstandard")
        decompressed = decompress_file(compressed, "zstandard")
        assert decompressed == self.TEST_DATA

    def test_bzip2_roundtrip(self) -> None:
        """Test bzip2 compression and decompression."""
        compressed = compress_file(self.TEST_DATA, "bzip2")
        decompressed = decompress_file(compressed, "bzip2")
        assert decompressed == self.TEST_DATA

    def test_none_roundtrip(self) -> None:
        """Test no compression (passthrough)."""
        compressed = compress_file(self.TEST_DATA, "none")
        decompressed = decompress_file(compressed, "none")
        assert compressed == self.TEST_DATA
        assert decompressed == self.TEST_DATA


class TestCompressionLevels:
    """Test compression levels."""

    TEST_DATA = b"x" * 100000  # Repetitive data compresses well (larger for level differences)

    def test_gzip_compression_levels(self) -> None:
        """Test different gzip compression levels."""
        compressed_1 = compress_file(self.TEST_DATA, "gzip", compression_level=1)
        compressed_9 = compress_file(self.TEST_DATA, "gzip", compression_level=9)

        # Higher compression should be smaller
        assert len(compressed_9) < len(compressed_1)

        # Both should decompress to original
        assert decompress_file(compressed_1, "gzip") == self.TEST_DATA
        assert decompress_file(compressed_9, "gzip") == self.TEST_DATA

    def test_zstandard_compression_levels(self) -> None:
        """Test different zstandard compression levels."""
        compressed_1 = compress_file(self.TEST_DATA, "zstandard", compression_level=1)
        compressed_10 = compress_file(self.TEST_DATA, "zstandard", compression_level=10)

        # Higher compression should be smaller
        assert len(compressed_10) < len(compressed_1)

        # Both should decompress to original
        assert decompress_file(compressed_1, "zstandard") == self.TEST_DATA
        assert decompress_file(compressed_10, "zstandard") == self.TEST_DATA


class TestExtensions:
    """Test file extension utilities."""

    def test_get_extension_gzip(self) -> None:
        """Test getting gzip extension."""
        assert get_extension("gzip") == ".gz"

    def test_get_extension_zstandard(self) -> None:
        """Test getting zstandard extension."""
        assert get_extension("zstandard") == ".zst"

    def test_get_extension_bzip2(self) -> None:
        """Test getting bzip2 extension."""
        assert get_extension("bzip2") == ".bz2"

    def test_get_extension_none(self) -> None:
        """Test getting no extension."""
        assert get_extension("none") == ""

    def test_add_compression_extension_gzip(self) -> None:
        """Test adding gzip extension."""
        assert add_compression_extension("primary.xml", "gzip") == "primary.xml.gz"

    def test_add_compression_extension_zstandard(self) -> None:
        """Test adding zstandard extension."""
        assert add_compression_extension("primary.xml", "zstandard") == "primary.xml.zst"

    def test_add_compression_extension_bzip2(self) -> None:
        """Test adding bzip2 extension."""
        assert add_compression_extension("primary.xml", "bzip2") == "primary.xml.bz2"

    def test_add_compression_extension_none(self) -> None:
        """Test adding no extension."""
        assert add_compression_extension("primary.xml", "none") == "primary.xml"


class TestErrorHandling:
    """Test error handling."""

    def test_decompress_invalid_format(self) -> None:
        """Test decompressing with invalid format."""
        with pytest.raises(ValueError, match="Unknown compression format"):
            decompress_file(b"test", "invalid")  # type: ignore

    def test_compress_invalid_format(self) -> None:
        """Test compressing with invalid format."""
        with pytest.raises(ValueError, match="Unknown compression format"):
            compress_file(b"test", "invalid")  # type: ignore

    def test_get_extension_invalid_format(self) -> None:
        """Test getting extension for invalid format."""
        with pytest.raises(ValueError, match="Unknown compression format"):
            get_extension("invalid")  # type: ignore


class TestCompatibility:
    """Test compatibility with standard libraries."""

    TEST_DATA = b"<metadata><package>test</package></metadata>"

    def test_gzip_compatible_with_stdlib(self) -> None:
        """Test that our gzip is compatible with stdlib gzip."""
        # Compress with our function
        compressed = compress_file(self.TEST_DATA, "gzip")

        # Decompress with stdlib
        decompressed = gzip.decompress(compressed)
        assert decompressed == self.TEST_DATA

        # Compress with stdlib
        stdlib_compressed = gzip.compress(self.TEST_DATA)

        # Decompress with our function
        our_decompressed = decompress_file(stdlib_compressed, "gzip")
        assert our_decompressed == self.TEST_DATA

    def test_bzip2_compatible_with_stdlib(self) -> None:
        """Test that our bzip2 is compatible with stdlib bz2."""
        # Compress with our function
        compressed = compress_file(self.TEST_DATA, "bzip2")

        # Decompress with stdlib
        decompressed = bz2.decompress(compressed)
        assert decompressed == self.TEST_DATA

        # Compress with stdlib
        stdlib_compressed = bz2.compress(self.TEST_DATA)

        # Decompress with our function
        our_decompressed = decompress_file(stdlib_compressed, "bzip2")
        assert our_decompressed == self.TEST_DATA

    def test_zstandard_compatible_with_library(self) -> None:
        """Test that our zstandard is compatible with zstandard library."""
        # Compress with our function
        compressed = compress_file(self.TEST_DATA, "zstandard")

        # Decompress with library
        dctx = zstd.ZstdDecompressor()
        decompressed = dctx.decompress(compressed)
        assert decompressed == self.TEST_DATA

        # Compress with library
        cctx = zstd.ZstdCompressor()
        lib_compressed = cctx.compress(self.TEST_DATA)

        # Decompress with our function
        our_decompressed = decompress_file(lib_compressed, "zstandard")
        assert our_decompressed == self.TEST_DATA


class TestCompressionRatios:
    """Test compression effectiveness."""

    # XML data compresses well
    TEST_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<metadata xmlns="http://linux.duke.edu/metadata/common" packages="100">
    <package type="rpm">
        <name>nginx</name>
        <version>1.20.1</version>
        <release>1.el9</release>
        <arch>x86_64</arch>
        <summary>High performance web server</summary>
        <description>Nginx is a web server with a strong focus on high concurrency, performance and low memory usage.</description>
    </package>
</metadata>
""" * 100  # Repeat to make it larger

    def test_gzip_compresses(self) -> None:
        """Test that gzip actually compresses."""
        compressed = compress_file(self.TEST_XML, "gzip")
        assert len(compressed) < len(self.TEST_XML)

    def test_zstandard_compresses(self) -> None:
        """Test that zstandard actually compresses."""
        compressed = compress_file(self.TEST_XML, "zstandard")
        assert len(compressed) < len(self.TEST_XML)

    def test_bzip2_compresses(self) -> None:
        """Test that bzip2 actually compresses."""
        compressed = compress_file(self.TEST_XML, "bzip2")
        assert len(compressed) < len(self.TEST_XML)

    def test_zstandard_vs_gzip(self) -> None:
        """Test that zstandard compresses as well or better than gzip."""
        gzip_compressed = compress_file(self.TEST_XML, "gzip")
        zstd_compressed = compress_file(self.TEST_XML, "zstandard")

        # Zstandard should be competitive with gzip
        # Allow some margin (within 20%)
        assert len(zstd_compressed) <= len(gzip_compressed) * 1.2
