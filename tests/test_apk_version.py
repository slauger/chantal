"""Tests for Alpine apk version comparison and the only_latest_version filter."""

from __future__ import annotations

import pytest

from chantal.plugins.apk.version import apk_version_compare, apk_version_key


@pytest.mark.parametrize(
    "a, b, expected",
    [
        # Pre-release suffixes sort below the bare release...
        ("1.0_alpha1", "1.0_beta1", -1),
        ("1.0_beta1", "1.0_pre1", -1),
        ("1.0_pre1", "1.0_rc1", -1),
        ("1.0_rc1", "1.0", -1),
        ("1.0_pre1", "1.0", -1),
        # ...and post-release suffixes sort above it (PEP 440 gets these wrong).
        ("1.0", "1.0_cvs1", -1),
        ("1.0", "1.0_git1", -1),
        ("1.0", "1.0_p1", -1),
        ("1.0_git20230101", "1.0_p1", -1),
        # pkgrel (-rN) is numeric, not lexical.
        ("1.0-r2", "1.0-r10", -1),
        ("1.0-r0", "1.0-r0", 0),
        ("1.0_pre1-r5", "1.0-r0", -1),  # suffix dominates pkgrel
        # Trailing letter is a sub-version above the bare one.
        ("1.0", "1.0a", -1),
        ("1.0a", "1.0b", -1),
        # Numeric segments.
        ("1.0.1", "1.0", 1),
        ("1.10", "1.9", 1),  # numeric, not lexical
        ("1.05", "1.5", -1),  # leading-zero segment -> fractional compare
        ("2.0", "1.99", 1),
        # Equality / symmetry.
        ("1.2.3-r4", "1.2.3-r4", 0),
    ],
)
def test_apk_version_compare(a, b, expected):
    assert apk_version_compare(a, b) == expected
    # Antisymmetry: swapping arguments negates the result.
    assert apk_version_compare(b, a) == -expected


def test_apk_version_key_sorts_correctly():
    versions = ["1.0", "1.0_pre1", "1.0-r2", "1.0_p1", "1.0-r10", "0.9"]
    ordered = sorted(versions, key=apk_version_key)
    # pre-suffix < release < pkgrel(numeric) < post-suffix.
    assert ordered == ["0.9", "1.0_pre1", "1.0", "1.0-r2", "1.0-r10", "1.0_p1"]


def test_apk_version_compare_rejects_unparseable():
    with pytest.raises(ValueError):
        apk_version_compare("not-a-version", "1.0")
    with pytest.raises(ValueError):
        apk_version_compare("1.0", "")


def _apk_config():
    from chantal.core.config import (
        ApkConfig,
        FilterConfig,
        PostProcessingConfig,
        RepositoryConfig,
    )

    return RepositoryConfig(
        id="alpine",
        name="Alpine",
        type="apk",
        feed="http://example.com/alpine",
        apk=ApkConfig(branch="v3.19", repository="main", architecture="x86_64"),
        filters=FilterConfig(post_processing=PostProcessingConfig(only_latest_version=True)),
    )


def test_only_latest_version_filter_uses_apk_ordering():
    """The only_latest_version filter must keep the apk-newest of each package."""
    from chantal.plugins.apk.sync import ApkSyncer

    config = _apk_config()
    syncer = ApkSyncer(storage=None, config=config)

    def pkg(name, version):
        return {"name": name, "version": version, "architecture": "x86_64"}

    packages = [
        pkg("demo", "1.0_pre1-r0"),  # pre-release: must NOT win
        pkg("demo", "1.0-r2"),
        pkg("demo", "1.0-r10"),  # apk-newest (PEP 440 string-sorts r2 > r10)
        pkg("other", "2.0"),
        pkg("other", "2.0_p1"),  # post-release (_p) > 2.0; PEP 440 can't parse it
    ]

    result = syncer._apply_filters(packages, config)
    winners = {p["name"]: p["version"] for p in result}
    assert winners == {"demo": "1.0-r10", "other": "2.0_p1"}


def test_only_latest_version_keeps_distinct_architectures():
    """Per-(name, arch) grouping: different arches coexist."""
    from chantal.plugins.apk.sync import ApkSyncer

    config = _apk_config()
    syncer = ApkSyncer(storage=None, config=config)

    packages = [
        {"name": "demo", "version": "1.0-r0", "architecture": "x86_64"},
        {"name": "demo", "version": "1.0-r1", "architecture": "x86_64"},
        {"name": "demo", "version": "1.0-r0", "architecture": "aarch64"},
    ]
    result = syncer._apply_filters(packages, config)
    got = {(p["name"], p["architecture"]): p["version"] for p in result}
    assert got == {("demo", "x86_64"): "1.0-r1", ("demo", "aarch64"): "1.0-r0"}
