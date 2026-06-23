"""Unit tests for RPM main-header metadata extraction (parse_main_header)."""

from __future__ import annotations

import struct

from chantal.plugins.rpm.rpm_header import parse_main_header

_HEADER_MAGIC = b"\x8e\xad\xe8\x01"
_LEAD = b"\xed\xab\xee\xdb" + b"\x00" * 92  # 96-byte lead

# RPM type codes
_T_INT32 = 4
_T_STRING = 6
_T_I18NSTRING = 9


def _build_header(items: list[tuple[int, int, bytes]]) -> bytes:
    """Serialize an RPM header from (tag, type, raw_value) items."""
    index = b""
    store = b""
    for tag, rpm_type, raw in items:
        index += struct.pack(">IIII", tag, rpm_type, len(store), 1)
        store += raw
    intro = _HEADER_MAGIC + b"\x00" * 4 + struct.pack(">II", len(items), len(store))
    return intro + index + store


def _build_rpm(main_items: list[tuple[int, int, bytes]]) -> bytes:
    """Assemble lead + a minimal signature header + padding + main header."""
    sig_header = _build_header([(1000, _T_STRING, b"x\x00")])
    sig_end = 96 + len(sig_header)
    pad = b"\x00" * (-sig_end % 8)
    return _LEAD + sig_header + pad + _build_header(main_items)


def test_parse_main_header_nevra():
    rpm = _build_rpm(
        [
            (1000, _T_STRING, b"nginx\x00"),
            (1001, _T_STRING, b"1.20.1\x00"),
            (1002, _T_STRING, b"1.el9\x00"),
            (1003, _T_INT32, struct.pack(">I", 1)),
            (1004, _T_I18NSTRING, b"High performance web server\x00"),
            (1022, _T_STRING, b"x86_64\x00"),
            (1044, _T_STRING, b"nginx-1.20.1-1.el9.src.rpm\x00"),
        ]
    )
    meta = parse_main_header(rpm)
    assert meta["name"] == "nginx"
    assert meta["version"] == "1.20.1"
    assert meta["release"] == "1.el9"
    assert meta["epoch"] == 1  # INT32 decoded as int
    assert meta["arch"] == "x86_64"
    assert meta["summary"] == "High performance web server"
    assert meta["sourcerpm"] == "nginx-1.20.1-1.el9.src.rpm"


def test_parse_main_header_noarch_no_epoch():
    rpm = _build_rpm(
        [
            (1000, _T_STRING, b"demo\x00"),
            (1001, _T_STRING, b"1.0\x00"),
            (1002, _T_STRING, b"1\x00"),
            (1022, _T_STRING, b"noarch\x00"),
        ]
    )
    meta = parse_main_header(rpm)
    assert meta["name"] == "demo"
    assert meta["arch"] == "noarch"
    assert "epoch" not in meta  # no EPOCH tag -> absent
