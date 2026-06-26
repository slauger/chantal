"""Tests for the optional ``max_output_bytes`` cap on ``decompress_bytes``.

A small but highly-compressible input must not be allowed to expand into a
multi-gigabyte buffer (decompression bomb). The cap is opt-in: callers that omit
it (RPM primary.xml, APT Packages indices) keep decompressing without a limit.
"""

from __future__ import annotations

import bz2
import gzip
import lzma

import pytest

from chantal.plugins.rpm.modules import (
    DecompressionLimitError,
    compress_bytes,
    decompress_bytes,
)

_FORMATS = [".gz", ".xz", ".bz2", ".zst"]


def _compress(payload: bytes, suffix: str) -> bytes:
    if suffix == ".gz":
        return gzip.compress(payload)
    if suffix == ".xz":
        return lzma.compress(payload)
    if suffix == ".bz2":
        return bz2.compress(payload)
    return compress_bytes(payload, suffix)  # .zst


@pytest.mark.parametrize("suffix", _FORMATS)
def test_under_limit_round_trips(suffix):
    payload = b"hello world\n" * 100
    compressed = _compress(payload, suffix)
    assert decompress_bytes(compressed, suffix, max_output_bytes=1_000_000) == payload


@pytest.mark.parametrize("suffix", _FORMATS)
def test_over_limit_raises_before_full_expansion(suffix):
    # 8 MiB of zeros compresses to a tiny blob; a 1 KiB cap must reject it.
    bomb = _compress(b"\0" * (8 * 1024 * 1024), suffix)
    assert len(bomb) < 64 * 1024  # genuinely a "bomb": tiny on disk
    with pytest.raises(DecompressionLimitError):
        decompress_bytes(bomb, suffix, max_output_bytes=1024)


@pytest.mark.parametrize("suffix", _FORMATS)
def test_exact_limit_is_allowed(suffix):
    payload = b"a" * 4096
    compressed = _compress(payload, suffix)
    # Exactly at the cap is fine; one byte under the cap is not exceeded.
    assert decompress_bytes(compressed, suffix, max_output_bytes=4096) == payload
    with pytest.raises(DecompressionLimitError):
        decompress_bytes(compressed, suffix, max_output_bytes=4095)


@pytest.mark.parametrize("suffix", _FORMATS)
def test_no_limit_is_unbounded(suffix):
    payload = b"x" * (2 * 1024 * 1024)
    compressed = _compress(payload, suffix)
    # Default (no cap) keeps the previous unbounded behavior for large metadata.
    assert decompress_bytes(compressed, suffix) == payload
