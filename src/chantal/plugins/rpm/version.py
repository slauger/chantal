"""RPM EVR (epoch:version-release) comparison.

RPM versions are *not* ordered by PEP 440. ``rpm`` compares the epoch as an
integer, then the version and release each with ``rpmvercmp``: a segment-wise
comparison where ``~`` sorts before everything (pre-release), ``^`` sorts after
the end of a version but before a following segment (post-release snapshot),
numeric segments outrank alphabetic ones, and a longer numeric segment is
greater (so ``10.el9`` > ``9.el9``, which lexical/PEP 440 ordering gets wrong).

This is a faithful port of rpm's ``rpmvercmp`` (lib/rpmvercmp.c), used by the
``only_latest_version`` filter.
"""

from __future__ import annotations

import functools


def rpmvercmp(a: str, b: str) -> int:
    """Compare two RPM version (or release) strings. Returns -1, 0 or 1."""
    if a == b:
        return 0

    i, j = 0, 0
    la, lb = len(a), len(b)

    def _sep(c: str) -> bool:
        return not (c.isalnum() or c in "~^")

    while i < la or j < lb:
        # Skip separators (anything that isn't alphanumeric, '~' or '^').
        while i < la and _sep(a[i]):
            i += 1
        while j < lb and _sep(b[j]):
            j += 1

        # Tilde: sorts before everything, even the empty string.
        a_t = i < la and a[i] == "~"
        b_t = j < lb and b[j] == "~"
        if a_t or b_t:
            if not a_t:
                return 1
            if not b_t:
                return -1
            i += 1
            j += 1
            continue

        # Caret: greater than the end of string, less than a following segment.
        a_c = i < la and a[i] == "^"
        b_c = j < lb and b[j] == "^"
        if a_c or b_c:
            if i >= la:
                return -1
            if j >= lb:
                return 1
            if not a_c:
                return 1
            if not b_c:
                return -1
            i += 1
            j += 1
            continue

        # One side ran out (after skipping separators).
        if not (i < la and j < lb):
            break

        # Grab the next segment (a run of digits or a run of letters).
        start_i, start_j = i, j
        if a[i].isdigit():
            while i < la and a[i].isdigit():
                i += 1
            while j < lb and b[j].isdigit():
                j += 1
            isnum = True
        else:
            while i < la and a[i].isalpha():
                i += 1
            while j < lb and b[j].isalpha():
                j += 1
            isnum = False

        seg_a = a[start_i:i]
        seg_b = b[start_j:j]

        if seg_b == "":
            # b has no segment of this type here: a numeric segment outranks it,
            # an alphabetic one is outranked.
            return 1 if isnum else -1

        if isnum:
            # Numeric: ignore leading zeros, then the longer number is greater.
            seg_a = seg_a.lstrip("0")
            seg_b = seg_b.lstrip("0")
            if len(seg_a) > len(seg_b):
                return 1
            if len(seg_b) > len(seg_a):
                return -1

        if seg_a < seg_b:
            return -1
        if seg_a > seg_b:
            return 1

    if i >= la and j >= lb:
        return 0
    return -1 if i >= la else 1


def evr_compare(epoch_a: int, ver_a: str, rel_a: str, epoch_b: int, ver_b: str, rel_b: str) -> int:
    """Compare two RPM EVRs. Returns -1, 0 or 1."""
    if epoch_a != epoch_b:
        return -1 if epoch_a < epoch_b else 1
    c = rpmvercmp(ver_a, ver_b)
    if c:
        return c
    return rpmvercmp(rel_a, rel_b)


def _evr_pkg_compare(p1: dict, p2: dict) -> int:
    """Compare two package dicts (name/version/release/epoch fields) by EVR."""
    return evr_compare(
        int(p1.get("epoch", 0) or 0),
        p1.get("version", "") or "",
        p1.get("release", "") or "",
        int(p2.get("epoch", 0) or 0),
        p2.get("version", "") or "",
        p2.get("release", "") or "",
    )


# ``sorted(packages, key=evr_pkg_key)`` orders package dicts oldest-to-newest.
evr_pkg_key = functools.cmp_to_key(_evr_pkg_compare)
