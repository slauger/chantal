from __future__ import annotations

"""
Minimal pure-Python RPM container parser for signature verification.

An RPM file is::

    [ Lead              96 bytes ]
    [ Signature header  (header struct, padded to an 8-byte boundary) ]
    [ Main header       (header struct - the package metadata) ]
    [ Payload           (compressed cpio) ]

Both headers use the same binary "header" structure::

    magic  : 4 bytes  -> 8e ad e8 01
    reserved: 4 bytes
    nindex : uint32 BE  (number of index entries)
    hsize  : uint32 BE  (size of the data store)
    index  : nindex * 16 bytes   (tag, type, offset, count - each uint32 BE)
    store  : hsize bytes

The header-only OpenPGP signature lives in the *signature header* under tag
``RPMSIGTAG_RSAHEADER`` (268, RSA) or ``RPMSIGTAG_DSAHEADER`` (267, DSA/ECDSA).
Its value is a raw OpenPGP signature packet, and the signed data is exactly the
serialized *main header* blob. Verification therefore reduces to a normal
detached-signature check of that packet over the main-header bytes.

References: RPM file format / ``rpm-head-signing`` (see the research notes).
"""

import mmap
import struct

# Accepts in-memory bytes or an mmap of the file (so only the header region is
# read for large packages). Slicing either yields real ``bytes``.
_Buffer = bytes | mmap.mmap

RPMTAG_RSAHEADER = 268
RPMTAG_DSAHEADER = 267

# Main-header value tags (package metadata) and their RPM type codes.
_RPM_TYPE_INT32 = 4
_RPM_TYPE_STRING = 6
_RPM_TYPE_STRING_ARRAY = 8
_RPM_TYPE_I18NSTRING = 9
_MAIN_HEADER_TAGS = {
    1000: "name",
    1001: "version",
    1002: "release",
    1003: "epoch",
    1004: "summary",
    1005: "description",
    1022: "arch",
    1044: "sourcerpm",
}

_LEAD_MAGIC = b"\xed\xab\xee\xdb"
_HEADER_MAGIC = b"\x8e\xad\xe8\x01"
_LEAD_SIZE = 96
_INTRO_SIZE = 16
_INDEX_ENTRY_SIZE = 16


class RpmFormatError(Exception):
    """Raised when the bytes are not a parseable RPM."""


def _parse_header(data: _Buffer, offset: int) -> tuple[list[tuple[int, int, int, int]], bytes, int]:
    """Parse one RPM header structure at ``offset``.

    Returns (index_entries, store_bytes, end_offset).
    """
    if len(data) < offset + _INTRO_SIZE:
        raise RpmFormatError("truncated header intro")
    intro = data[offset : offset + _INTRO_SIZE]
    if intro[:4] != _HEADER_MAGIC:
        raise RpmFormatError(f"bad header magic at offset {offset}")

    nindex, hsize = struct.unpack(">II", intro[8:16])
    index_start = offset + _INTRO_SIZE
    store_start = index_start + nindex * _INDEX_ENTRY_SIZE
    store_end = store_start + hsize
    if len(data) < store_end:
        raise RpmFormatError("truncated header (index/store beyond end of file)")

    entries: list[tuple[int, int, int, int]] = []
    for i in range(nindex):
        entry = data[
            index_start + i * _INDEX_ENTRY_SIZE : index_start + (i + 1) * _INDEX_ENTRY_SIZE
        ]
        entries.append(struct.unpack(">IIII", entry))  # (tag, type, offset, count)

    store = data[store_start:store_end]
    return entries, store, store_end


def extract_header_signature(data: _Buffer) -> tuple[bytes, bytes] | None:
    """Extract the header-only OpenPGP signature and the data it covers.

    Args:
        data: The full ``.rpm`` file bytes.

    Returns:
        ``(signature_packet, main_header_blob)`` if a header signature
        (RSAHEADER/DSAHEADER) is present, or ``None`` if the package carries no
        header signature.

    Raises:
        RpmFormatError: If the bytes are not a parseable RPM.
    """
    if len(data) < _LEAD_SIZE + _INTRO_SIZE or data[:4] != _LEAD_MAGIC:
        raise RpmFormatError("not an RPM file (bad lead magic)")

    sig_entries, sig_store, sig_end = _parse_header(data, _LEAD_SIZE)

    # The signature header is padded with zeros to the next 8-byte boundary.
    # The signature header starts at offset 96 (a multiple of 8), so aligning
    # the absolute end offset is equivalent.
    main_offset = sig_end + (-sig_end % 8)

    _main_entries, _main_store, main_end = _parse_header(data, main_offset)
    main_header_blob = data[main_offset:main_end]

    for tag, _type, store_offset, count in sig_entries:
        if tag in (RPMTAG_RSAHEADER, RPMTAG_DSAHEADER):
            signature_packet = sig_store[store_offset : store_offset + count]
            if not signature_packet:
                raise RpmFormatError("empty header signature packet")
            return signature_packet, main_header_blob

    return None


def _read_cstring(store: bytes, offset: int) -> str:
    """Read a NUL-terminated string from the header store at ``offset``."""
    end = store.find(b"\x00", offset)
    if end == -1:
        end = len(store)
    return store[offset:end].decode("utf-8", "replace")


def parse_main_header(data: _Buffer) -> dict:
    """Extract package metadata (NEVRA, summary, ...) from an RPM's main header.

    Pure-Python: reuses the same header parsing as the signature path, so no
    ``rpm`` binary is required. Returns a dict with any of the keys: ``name``,
    ``version``, ``release``, ``epoch`` (int), ``arch``, ``summary``,
    ``description``, ``sourcerpm``.

    Raises:
        RpmFormatError: If the bytes are not a parseable RPM.
    """
    if len(data) < _LEAD_SIZE + _INTRO_SIZE or data[:4] != _LEAD_MAGIC:
        raise RpmFormatError("not an RPM file (bad lead magic)")

    _sig_entries, _sig_store, sig_end = _parse_header(data, _LEAD_SIZE)
    main_offset = sig_end + (-sig_end % 8)
    entries, store, _ = _parse_header(data, main_offset)

    result: dict = {}
    for tag, rpm_type, store_offset, _count in entries:
        key = _MAIN_HEADER_TAGS.get(tag)
        if key is None:
            continue
        if rpm_type in (_RPM_TYPE_STRING, _RPM_TYPE_I18NSTRING, _RPM_TYPE_STRING_ARRAY):
            # I18NSTRING/STRING_ARRAY: take the first entry.
            result[key] = _read_cstring(store, store_offset)
        elif rpm_type == _RPM_TYPE_INT32:
            (value,) = struct.unpack(">I", store[store_offset : store_offset + 4])
            result[key] = value
    return result
