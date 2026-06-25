from __future__ import annotations

"""
APK package checksum helper.

The ``C:`` field in an ``APKINDEX`` is ``Q1`` + base64(SHA1) where the SHA1 is
taken over the *compressed bytes of the control segment* of the ``.apk`` — not
the whole file. An ``.apk`` (APKv2) is a sequence of concatenated gzip streams:
an optional signature, the control segment, then the data segment. The control
segment is therefore always the second-to-last stream.
"""

import base64
import hashlib
import zlib

_GZIP_MAGIC = b"\x1f\x8b"


_CHUNK = 65536


def _split_gzip_streams(data: bytes) -> list[bytes]:
    """Split concatenated gzip streams into their raw (compressed) byte chunks.

    Only the compressed stream boundaries are needed, so the decompressed output
    is produced in bounded chunks and discarded — a maliciously high-expansion
    member cannot exhaust memory.
    """
    streams: list[bytes] = []
    rest = data
    while rest[:2] == _GZIP_MAGIC:
        decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
        pending = rest
        while not decompressor.eof:
            out = decompressor.decompress(pending, _CHUNK)
            pending = decompressor.unconsumed_tail
            if not out and not pending:
                break  # truncated / no progress
        consumed = len(rest) - len(decompressor.unused_data)
        if consumed <= 0:
            break
        streams.append(rest[:consumed])
        rest = decompressor.unused_data
    return streams


def compute_apk_control_checksum(data: bytes) -> str | None:
    """Compute an ``.apk``'s ``C:`` checksum (``Q1`` + base64(SHA1) of control).

    Returns ``None`` when ``data`` is not a parseable APKv2 archive (fewer than
    two gzip streams, or a corrupt stream), so callers can treat that as a
    verification failure.
    """
    try:
        streams = _split_gzip_streams(data)
    except (zlib.error, OverflowError):
        return None
    if len(streams) < 2:
        return None
    control_segment = streams[-2]  # data is last; control precedes it
    digest = hashlib.sha1(control_segment).digest()  # noqa: S324 - APK index format
    return "Q1" + base64.b64encode(digest).decode("ascii")
