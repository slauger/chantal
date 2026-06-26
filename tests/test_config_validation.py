"""Tests for global config validation: extra-key rejection, view validation,
filter type checks, and legacy filter normalization."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from chantal.core.config import GlobalConfig, RepositoryConfig


def _repo(**kw):
    base = {"id": "r", "type": "rpm", "feed": "http://x", "mode": "mirror"}
    base.update(kw)
    return base


def test_unknown_key_on_repository_is_rejected():
    with pytest.raises(ValidationError, match="enabledd|Extra inputs"):
        RepositoryConfig(**_repo(enabledd=True))


def test_unknown_top_level_key_is_rejected():
    with pytest.raises(ValidationError, match="databse|Extra inputs"):
        GlobalConfig(databse={"url": "sqlite://"})


def test_view_referencing_unknown_repo_is_rejected():
    with pytest.raises(ValidationError, match="unknown repository"):
        GlobalConfig(
            repositories=[_repo(id="a")],
            views=[{"name": "v", "repos": ["a", "missing"]}],
        )


def test_view_mixing_repo_types_is_rejected():
    with pytest.raises(ValidationError, match="different types"):
        GlobalConfig(
            repositories=[
                _repo(id="a", type="rpm"),
                _repo(id="b", type="apt", apt={"distribution": "jammy"}),
            ],
            views=[{"name": "v", "repos": ["a", "b"]}],
        )


def test_valid_view_loads():
    cfg = GlobalConfig(
        repositories=[_repo(id="a", type="rpm"), _repo(id="b", type="rpm")],
        views=[{"name": "v", "repos": ["a", "b"]}],
    )
    assert cfg.views[0].repos == ["a", "b"]


def test_rpm_filter_on_apt_repo_is_rejected():
    with pytest.raises(ValidationError, match="Cannot use 'rpm' filters with APT"):
        GlobalConfig(
            repositories=[
                _repo(
                    id="a",
                    type="apt",
                    mode="filtered",
                    apt={"distribution": "jammy"},
                    filters={"rpm": {"vendors": {"include": ["X"]}}},
                )
            ]
        )


def test_deb_filter_on_rpm_repo_is_rejected():
    with pytest.raises(ValidationError, match="Cannot use 'deb' filters with RPM"):
        GlobalConfig(
            repositories=[
                _repo(
                    id="a",
                    type="rpm",
                    mode="filtered",
                    filters={"deb": {"components": {"include": ["main"]}}},
                )
            ]
        )


def test_legacy_flat_filters_are_normalized_for_apt():
    """Legacy include_packages must be migrated into patterns so APT honors it."""
    cfg = GlobalConfig(
        repositories=[
            _repo(
                id="a",
                type="apt",
                mode="filtered",
                apt={"distribution": "jammy"},
                filters={"include_packages": ["^nginx.*"], "exclude_packages": ["-dbg$"]},
            )
        ]
    )
    patterns = cfg.repositories[0].filters.patterns
    assert patterns is not None
    assert patterns.include == ["^nginx.*"]
    assert patterns.exclude == ["-dbg$"]
