"""APT: bounded index decompression and lenient index decoding."""

from __future__ import annotations

import gzip

import pytest

import chantal.plugins.apt.sync as apt_sync
from chantal.plugins.apt.parsers import parse_packages_from_bytes
from chantal.plugins.apt.sync import _decompress_index
from chantal.plugins.rpm.modules import DecompressionLimitError


def test_decompress_index_rejects_bomb(monkeypatch):
    monkeypatch.setattr(apt_sync, "_MAX_INDEX_BYTES", 64)
    bomb = gzip.compress(b"\0" * (1024 * 1024))  # 1 MiB -> tiny gz, over the 64 B cap
    with pytest.raises(DecompressionLimitError):
        _decompress_index(bomb, "main/binary-amd64/Packages.gz")


def test_decompress_index_under_cap_round_trips():
    payload = b"Package: demo\n\n"
    assert _decompress_index(gzip.compress(payload), "main/binary-amd64/Packages.gz") == payload
    # Uncompressed (no known suffix) is returned as-is.
    assert _decompress_index(payload, "main/binary-amd64/Packages") == payload


def test_parse_packages_is_lenient_on_bad_utf8():
    """A stray non-UTF-8 byte must not drop the whole index."""
    stanza = (
        b"Package: demo\n"
        b"Version: 1.0\n"
        b"Architecture: amd64\n"
        b"Maintainer: Ma\xffntainer\n"  # invalid UTF-8 byte
        b"Filename: pool/demo_1.0_amd64.deb\n"
        b"Size: 10\n"
        b"SHA256: " + b"a" * 64 + b"\n"
        b"Description: a demo\n"
        b"\n"
    )
    packages = parse_packages_from_bytes(stanza, compressed=False)
    assert [p.package for p in packages] == ["demo"]
