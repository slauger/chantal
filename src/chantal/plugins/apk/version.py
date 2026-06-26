"""Alpine ``apk`` version comparison.

Alpine packages are *not* ordered by PEP 440. ``apk`` has its own scheme
(apk-tools ``src/version.c``): a version is a sequence of dot-separated numeric
segments, an optional single trailing letter, zero or more ``_suffix[number]``
parts, an optional ``~hash`` commit marker, and a trailing ``-r<pkgrel>``.

The suffixes are ordered around the bare release: pre-release suffixes
(``_alpha``/``_beta``/``_pre``/``_rc``) sort *below* the release, post-release
suffixes (``_cvs``/``_svn``/``_git``/``_hg``/``_p``) sort *above* it. So
``1.0_pre1 < 1.0 < 1.0_p1`` and ``1.0-r2 < 1.0-r10`` (pkgrel is numeric) — both
of which PEP 440 gets wrong.

This module implements ``apk_version_compare`` faithfully enough for the
``only_latest_version`` filter, plus an ``apk_version_key`` for sorting.

Simplifications vs. apk-tools (all harmless for real APKINDEX data, whose ``V:``
fields always carry an explicit ``-rN``): an absent ``-r`` is treated as ``-r0``;
a ``~commithash`` marker is ignored; and the rare suffix-without-number vs.
suffix-with-number edge ordering is not modelled.
"""

from __future__ import annotations

import functools
import re

# Suffix ordering relative to the bare release (rank 0). Pre-release suffixes are
# negative (older than release); post-release suffixes are positive (newer).
_SUFFIX_RANK = {
    "alpha": -4,
    "beta": -3,
    "pre": -2,
    "rc": -1,
    "cvs": 1,
    "svn": 2,
    "git": 3,
    "hg": 4,
    "p": 5,
}

_SUFFIX_RE = re.compile(r"_([a-z]+)(\d*)")


class _Parsed:
    """A parsed apk version split into comparable components."""

    __slots__ = ("segments", "letter", "suffixes", "pkgrel")

    def __init__(
        self,
        segments: list[tuple[bool, str]],
        letter: str,
        suffixes: list[tuple[int, int]],
        pkgrel: int,
    ) -> None:
        # segments: list of (is_leading_zero, digits) dot-separated numeric parts
        self.segments = segments
        self.letter = letter  # single trailing letter, or ""
        self.suffixes = suffixes  # list of (rank, number)
        self.pkgrel = pkgrel  # -rN, default 0


def _parse(version: str) -> _Parsed:
    """Parse an apk version string. Raises ValueError on clearly invalid input."""
    s = version.strip()
    if not s:
        raise ValueError("empty version")

    # Trailing -rN pkgrel.
    pkgrel = 0
    m = re.search(r"-r(\d+)$", s)
    if m:
        pkgrel = int(m.group(1))
        s = s[: m.start()]

    # Drop an optional ~commithash marker (treated as opaque/equal).
    s = s.split("~", 1)[0]

    # Suffixes (_alpha, _p1, ...). Pull them off the end first.
    suffixes: list[tuple[int, int]] = []
    while True:
        m = re.search(r"_([a-z]+)(\d*)$", s)
        if not m:
            break
        name = m.group(1)
        if name not in _SUFFIX_RANK:
            # Unknown suffix: stop; leave it on the core (will likely be invalid).
            break
        num = int(m.group(2)) if m.group(2) else 0
        suffixes.insert(0, (_SUFFIX_RANK[name], num))
        s = s[: m.start()]

    # Optional single trailing letter directly after the numeric part.
    letter = ""
    if s and s[-1].isalpha():
        letter = s[-1]
        s = s[:-1]

    if not s:
        raise ValueError(f"no numeric component in version: {version!r}")

    segments: list[tuple[bool, str]] = []
    for part in s.split("."):
        if not part.isdigit():
            raise ValueError(f"invalid numeric segment {part!r} in version {version!r}")
        segments.append((len(part) > 1 and part[0] == "0", part))

    return _Parsed(segments, letter, suffixes, pkgrel)


def _cmp_segment(a: tuple[bool, str], b: tuple[bool, str]) -> int:
    """Compare two dot-separated numeric segments.

    If either has a leading zero, compare as decimal fractions (string compare),
    matching apk's DIGIT_OR_ZERO rule (e.g. ``1.05 < 1.5``). Otherwise compare as
    integers.
    """
    a_zero, a_digits = a
    b_zero, b_digits = b
    if a_zero or b_zero:
        return (a_digits > b_digits) - (a_digits < b_digits)
    ai, bi = int(a_digits), int(b_digits)
    return (ai > bi) - (ai < bi)


def _suffix_list_rank(suffixes: list[tuple[int, int]]) -> int:
    """Rank used when one side has suffixes and the other does not.

    The first suffix decides whether the suffixed version is below (pre-release)
    or above (post-release) the bare release.
    """
    return suffixes[0][0] if suffixes else 0


def apk_version_compare(a: str, b: str) -> int:
    """Compare two apk version strings. Returns -1, 0 or 1 (a<b, a==b, a>b).

    Raises ValueError if either version cannot be parsed.
    """
    pa, pb = _parse(a), _parse(b)

    # Compare dot-separated numeric segments in lock-step. A missing segment is
    # treated as lower than any present segment (1.0 < 1.0.1).
    for i in range(max(len(pa.segments), len(pb.segments))):
        if i >= len(pa.segments):
            return -1
        if i >= len(pb.segments):
            return 1
        c = _cmp_segment(pa.segments[i], pb.segments[i])
        if c:
            return c

    # Trailing letter: a bare version is lower than a lettered one (1.0 < 1.0a).
    if pa.letter != pb.letter:
        return (pa.letter > pb.letter) - (pa.letter < pb.letter)

    # Suffixes. Compare in lock-step; when one side runs out, the other side's
    # next suffix rank decides (pre-suffix -> lower, post-suffix -> higher).
    for i in range(max(len(pa.suffixes), len(pb.suffixes))):
        if i >= len(pa.suffixes):
            r = _suffix_list_rank(pb.suffixes[i:])
            return -1 if r > 0 else 1 if r < 0 else 0
        if i >= len(pb.suffixes):
            r = _suffix_list_rank(pa.suffixes[i:])
            return 1 if r > 0 else -1 if r < 0 else 0
        ra, na = pa.suffixes[i]
        rb, nb = pb.suffixes[i]
        if ra != rb:
            return (ra > rb) - (ra < rb)
        if na != nb:
            return (na > nb) - (na < nb)

    # Finally, pkgrel (-rN), compared numerically.
    if pa.pkgrel != pb.pkgrel:
        return (pa.pkgrel > pb.pkgrel) - (pa.pkgrel < pb.pkgrel)

    return 0


apk_version_key = functools.cmp_to_key(apk_version_compare)
