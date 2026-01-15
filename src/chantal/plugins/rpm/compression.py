"""Compression utilities for RPM metadata."""

from __future__ import annotations

import bz2
import gzip
from pathlib import Path
from typing import Literal

import zstandard as zstd

CompressionFormat = Literal["gzip", "zstandard", "bzip2", "none"]


def detect_compression(filename: str) -> CompressionFormat | None:
    """Detect compression format from filename extension.

    Args:
        filename: Filename to check (e.g., "primary.xml.gz", "primary.xml.zst")

    Returns:
        Compression format or None if no compression detected
    """
    if filename.endswith(".gz"):
        return "gzip"
    elif filename.endswith(".zst"):
        return "zstandard"
    elif filename.endswith(".bz2"):
        return "bzip2"
    else:
        return "none"


def decompress_file(compressed_data: bytes, compression: CompressionFormat) -> bytes:
    """Decompress data based on compression format.

    Args:
        compressed_data: Compressed bytes
        compression: Compression format

    Returns:
        Decompressed bytes

    Raises:
        ValueError: If compression format is unknown
    """
    if compression == "gzip":
        return gzip.decompress(compressed_data)
    elif compression == "zstandard":
        dctx = zstd.ZstdDecompressor()
        return dctx.decompress(compressed_data)
    elif compression == "bzip2":
        return bz2.decompress(compressed_data)
    elif compression == "none":
        return compressed_data
    else:
        raise ValueError(f"Unknown compression format: {compression}")


def compress_file(
    data: bytes, compression: CompressionFormat, compression_level: int | None = None
) -> bytes:
    """Compress data based on compression format.

    Args:
        data: Uncompressed bytes
        compression: Compression format
        compression_level: Compression level (format-dependent, None = default)

    Returns:
        Compressed bytes

    Raises:
        ValueError: If compression format is unknown
    """
    if compression == "gzip":
        level = compression_level if compression_level is not None else 6
        return gzip.compress(data, compresslevel=level)
    elif compression == "zstandard":
        level = compression_level if compression_level is not None else 3
        cctx = zstd.ZstdCompressor(level=level)
        return cctx.compress(data)
    elif compression == "bzip2":
        level = compression_level if compression_level is not None else 9
        return bz2.compress(data, compresslevel=level)
    elif compression == "none":
        return data
    else:
        raise ValueError(f"Unknown compression format: {compression}")


def get_extension(compression: CompressionFormat) -> str:
    """Get file extension for compression format.

    Args:
        compression: Compression format

    Returns:
        File extension (e.g., ".gz", ".zst", "")
    """
    if compression == "gzip":
        return ".gz"
    elif compression == "zstandard":
        return ".zst"
    elif compression == "bzip2":
        return ".bz2"
    elif compression == "none":
        return ""
    else:
        raise ValueError(f"Unknown compression format: {compression}")


def add_compression_extension(filename: str, compression: CompressionFormat) -> str:
    """Add compression extension to filename if needed.

    Args:
        filename: Base filename (e.g., "primary.xml")
        compression: Compression format

    Returns:
        Filename with compression extension (e.g., "primary.xml.gz")
    """
    ext = get_extension(compression)
    if ext:
        return f"{filename}{ext}"
    return filename


def detect_compression_from_repomd(repomd_data: dict[str, dict]) -> CompressionFormat:
    """Detect compression format used in upstream repository from repomd.xml data.

    Args:
        repomd_data: Parsed repomd.xml data structure

    Returns:
        Detected compression format (defaults to "gzip" if cannot be determined)
    """
    # Check primary metadata href to detect compression
    if "primary" in repomd_data:
        href = repomd_data["primary"].get("href", "")
        detected = detect_compression(href)
        if detected:
            return detected

    # Fallback to gzip (most common)
    return "gzip"
