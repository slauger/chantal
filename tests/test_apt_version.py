"""Tests for Debian version comparison and the only_latest_version filter."""

from __future__ import annotations

import pytest

from chantal.plugins.apt.version import dpkg_compare, dpkg_version_key


@pytest.mark.parametrize(
    "a, b, expected",
    [
        ("2.0", "1.0", 1),
        ("1.10", "1.9", 1),  # numeric upstream, not lexical
        ("1:1.0", "2.0", 1),  # epoch wins
        ("0:1.0", "1.0", 0),  # explicit epoch 0 == none
        ("1.0~rc1", "1.0", -1),  # tilde sorts before the release
        ("1.0~~", "1.0~", -1),
        ("1.0-1", "1.0-10", -1),  # revision numeric, not lexical
        ("1.0", "1.0-1", -1),  # no revision < revision
        ("1.0", "1.0-0", 0),  # empty revision == -0
        ("1.0+deb1", "1.0", 1),  # '+' sorts after end
        ("2.2.4-1", "2.2.4-1", 0),
    ],
)
def test_dpkg_compare(a, b, expected):
    assert dpkg_compare(a, b) == expected
    assert dpkg_compare(b, a) == -expected


def test_dpkg_key_sorts():
    versions = ["1.0", "1:0.5", "1.0~rc1", "1.0-2", "1.0-10", "2.0"]
    assert sorted(versions, key=dpkg_version_key) == [
        "1.0~rc1",
        "1.0",
        "1.0-2",
        "1.0-10",
        "2.0",
        "1:0.5",  # epoch 1 outranks everything with epoch 0
    ]


def test_dpkg_compare_rejects_unparseable():
    with pytest.raises(ValueError):
        dpkg_compare("", "1.0")


def test_only_latest_version_filter_uses_dpkg_ordering():
    from chantal.core.config import (
        AptConfig,
        FilterConfig,
        PostProcessingConfig,
        RepositoryConfig,
    )
    from chantal.plugins.apt.models import DebMetadata
    from chantal.plugins.apt.sync import AptSyncPlugin

    config = RepositoryConfig(
        id="deb",
        name="Deb",
        type="apt",
        feed="http://example.com/ubuntu",
        apt=AptConfig(distribution="jammy", components=["main"], architectures=["amd64"]),
        filters=FilterConfig(post_processing=PostProcessingConfig(only_latest_version=True)),
    )
    syncer = AptSyncPlugin(storage=None, config=config)

    def deb(version):
        return DebMetadata(
            package="demo",
            version=version,
            architecture="amd64",
            filename=f"pool/demo_{version}_amd64.deb",
            size=1,
            sha256="0" * 64,
        )

    # 2.0 was first-seen; the epoch'd 1:1.0 is newer in Debian (PEP 440 can't even
    # parse it and would keep 2.0).
    packages = [deb("2.0"), deb("1:1.0"), deb("1.0~rc1")]
    result = syncer._apply_filters(packages, config)
    assert [p.version for p in result] == ["1:1.0"]
