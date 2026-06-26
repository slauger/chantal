"""Helm chart version comparison (SemVer 2.0.0).

Helm chart versions are SemVer 2.0.0, *not* PEP 440. The differences that matter
for picking the "latest" version:

* a version with a pre-release is lower than the same without
  (``1.2.3-alpha < 1.2.3``);
* pre-release identifiers are compared dot-separated, numeric ones numerically,
  alphanumeric ones lexically, with numeric < alphanumeric;
* build metadata (``+...``) is ignored for precedence.

PEP 440 disagrees on all of these (and rejects many valid SemVer strings), so the
``only_latest_version`` filter uses this module instead.
"""

from __future__ import annotations

import functools
import re

# Optional leading "v" (Helm tolerates it), then MAJOR.MINOR.PATCH, optional
# -prerelease and +build.
_SEMVER_RE = re.compile(
    r"^v?(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z.-]+))?"
    r"(?:\+(?P<build>[0-9A-Za-z.-]+))?$"
)


def _parse(version: str) -> tuple[int, int, int, list[str]]:
    """Parse a SemVer string into ``(major, minor, patch, prerelease_ids)``.

    Build metadata is discarded. Raises ValueError on a non-SemVer string.
    """
    m = _SEMVER_RE.match(version.strip())
    if not m:
        raise ValueError(f"not a SemVer version: {version!r}")
    pre = m.group("prerelease")
    pre_ids = pre.split(".") if pre else []
    return int(m.group("major")), int(m.group("minor")), int(m.group("patch")), pre_ids


def _cmp_prerelease_id(a: str, b: str) -> int:
    """Compare two pre-release identifiers per SemVer rules."""
    a_num, b_num = a.isdigit(), b.isdigit()
    if a_num and b_num:
        ai, bi = int(a), int(b)
        return (ai > bi) - (ai < bi)
    if a_num != b_num:
        # Numeric identifiers always have lower precedence than alphanumeric.
        return -1 if a_num else 1
    return (a > b) - (a < b)


def semver_compare(a: str, b: str) -> int:
    """Compare two SemVer versions. Returns -1, 0 or 1 (a<b, a==b, a>b).

    Raises ValueError if either version is not valid SemVer.
    """
    pa = _parse(a)
    pb = _parse(b)

    for x, y in zip(pa[:3], pb[:3], strict=True):
        if x != y:
            return (x > y) - (x < y)

    pre_a, pre_b = pa[3], pb[3]
    # A version with a pre-release is lower than one without.
    if not pre_a and pre_b:
        return 1
    if pre_a and not pre_b:
        return -1
    if not pre_a and not pre_b:
        return 0

    for ida, idb in zip(pre_a, pre_b, strict=False):
        c = _cmp_prerelease_id(ida, idb)
        if c:
            return c
    # All shared identifiers equal: the longer pre-release wins.
    return (len(pre_a) > len(pre_b)) - (len(pre_a) < len(pre_b))


semver_key = functools.cmp_to_key(semver_compare)
