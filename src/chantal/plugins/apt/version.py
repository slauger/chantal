"""Debian package version comparison (dpkg semantics).

Debian versions are ``[epoch:]upstream_version[-debian_revision]`` and are *not*
ordered by PEP 440: the epoch is compared first as an integer, ``~`` sorts before
everything (even the empty string, so ``1.0~rc1 < 1.0``), and digit/non-digit
runs alternate with dpkg's own character ordering. PEP 440 rejects the epoch
colon and ``~`` outright, so the ``only_latest_version`` filter uses this faithful
port of dpkg's ``verrevcmp`` instead.
"""

from __future__ import annotations

import functools
import re

_VERSION_RE = re.compile(r"^(?:(\d+):)?([A-Za-z0-9.+~-]*?)(?:-([A-Za-z0-9.+~]+))?$")


def _order(char: str) -> int:
    """Character ranking used by dpkg's non-digit comparison.

    ``~`` < (end of string) < digits-position < letters < other punctuation.
    """
    if char == "~":
        return -1
    if char.isalpha():
        return ord(char)
    # Non-letter, non-digit, non-tilde: sort after letters.
    return ord(char) + 256


def _verrevcmp(a: str, b: str) -> int:
    """Compare two upstream/revision strings exactly as dpkg's verrevcmp does."""
    i = j = 0
    la, lb = len(a), len(b)
    while i < la or j < lb:
        # Compare the leading non-digit run.
        while (i < la and not a[i].isdigit()) or (j < lb and not b[j].isdigit()):
            ac = _order(a[i]) if i < la and not a[i].isdigit() else 0
            bc = _order(b[j]) if j < lb and not b[j].isdigit() else 0
            if ac != bc:
                return -1 if ac < bc else 1
            i += 1
            j += 1
        # Skip leading zeros, then compare the digit run by value (length first).
        while i < la and a[i] == "0":
            i += 1
        while j < lb and b[j] == "0":
            j += 1
        first_diff = 0
        while i < la and a[i].isdigit() and j < lb and b[j].isdigit():
            if first_diff == 0:
                first_diff = ord(a[i]) - ord(b[j])
            i += 1
            j += 1
        if i < la and a[i].isdigit():
            return 1  # a has a longer number -> larger
        if j < lb and b[j].isdigit():
            return -1
        if first_diff != 0:
            return -1 if first_diff < 0 else 1
    return 0


def _split(version: str) -> tuple[int, str, str]:
    """Split a Debian version into ``(epoch, upstream, revision)``."""
    m = _VERSION_RE.match(version.strip())
    if not m:
        raise ValueError(f"not a Debian version: {version!r}")
    epoch = int(m.group(1)) if m.group(1) else 0
    upstream = m.group(2) or ""
    revision = m.group(3) or ""
    if not upstream:
        raise ValueError(f"empty upstream version in {version!r}")
    return epoch, upstream, revision


def dpkg_compare(a: str, b: str) -> int:
    """Compare two Debian versions. Returns -1, 0 or 1 (a<b, a==b, a>b).

    Raises ValueError if either version cannot be parsed.
    """
    ea, ua, ra = _split(a)
    eb, ub, rb = _split(b)
    if ea != eb:
        return -1 if ea < eb else 1
    c = _verrevcmp(ua, ub)
    if c:
        return c
    return _verrevcmp(ra, rb)


dpkg_version_key = functools.cmp_to_key(dpkg_compare)
