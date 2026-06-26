"""Tests for Helm SemVer comparison and the only_latest_version filter."""

from __future__ import annotations

import pytest

from chantal.plugins.helm.version import semver_compare, semver_key


@pytest.mark.parametrize(
    "a, b, expected",
    [
        ("2.0.0", "1.9.9", 1),
        ("1.10.0", "1.9.0", 1),  # numeric, not lexical
        ("1.2.3", "1.2.3", 0),
        ("1.2.3-alpha", "1.2.3", -1),  # pre-release < release
        ("1.2.3-alpha", "1.2.3-alpha.1", -1),
        ("1.2.3-alpha.1", "1.2.3-alpha.beta", -1),  # numeric < alphanumeric
        ("1.2.3-beta.2", "1.2.3-beta.11", -1),  # numeric identifiers numeric
        ("1.2.3-rc.1", "1.2.3", -1),
        ("1.2.3+build1", "1.2.3+build2", 0),  # build metadata ignored
        ("v1.2.3", "1.2.3", 0),  # leading v tolerated
    ],
)
def test_semver_compare(a, b, expected):
    assert semver_compare(a, b) == expected
    assert semver_compare(b, a) == -expected


def test_semver_key_sorts():
    versions = ["1.2.3", "1.2.3-rc.1", "1.10.0", "1.2.3-alpha", "2.0.0"]
    assert sorted(versions, key=semver_key) == [
        "1.2.3-alpha",
        "1.2.3-rc.1",
        "1.2.3",
        "1.10.0",
        "2.0.0",
    ]


def test_semver_compare_rejects_non_semver():
    with pytest.raises(ValueError):
        semver_compare("1.2", "1.2.3")  # not 3-part
    with pytest.raises(ValueError):
        semver_compare("notaversion", "1.2.3")


def test_only_latest_version_filter_uses_semver():
    from chantal.core.config import FilterConfig, PostProcessingConfig, RepositoryConfig
    from chantal.plugins.helm.sync import HelmSyncer

    config = RepositoryConfig(
        id="demo",
        name="Demo",
        type="helm",
        feed="http://example.com/charts",
        filters=FilterConfig(post_processing=PostProcessingConfig(only_latest_version=True)),
    )
    syncer = HelmSyncer(storage=None, config=config)

    charts = [
        {"name": "demo", "version": "1.2.3-rc.1"},  # pre-release: must NOT win
        {"name": "demo", "version": "1.2.3"},
        {"name": "demo", "version": "1.10.0"},  # newest (PEP 440 string-confusion aside)
        {"name": "demo", "version": "1.9.0"},
    ]
    result = syncer._apply_filters(charts, config)
    assert [c["version"] for c in result] == ["1.10.0"]
