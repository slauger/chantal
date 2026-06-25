"""Tests for Helm chart digest verification during sync.

A chart whose downloaded bytes do not match the digest advertised in
index.yaml must be rejected (never stored or linked). The digest comparison is
tolerant of an optional ``sha256:`` prefix.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from chantal.core.config import RepositoryConfig, StorageConfig
from chantal.core.storage import StorageManager
from chantal.db.models import Base, ContentItem, Repository
from chantal.plugins.helm.sync import HelmSyncer, normalize_digest

_GOOD = "a" * 64
_BAD = "b" * 64


@pytest.fixture
def storage():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        sm = StorageManager(
            StorageConfig(
                base_path=str(tmp / "base"),
                pool_path=str(tmp / "pool"),
                published_path=str(tmp / "published"),
                temp_path=str(tmp / "tmp"),
            )
        )
        sm.ensure_directories()
        yield sm


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sess = Session(engine)
    yield sess
    sess.close()


@pytest.fixture
def repository(session):
    repo = Repository(repo_id="h", name="H", type="helm", feed="https://charts.example.com")
    session.add(repo)
    session.commit()
    return repo


def _index(digest: str) -> dict:
    return {
        "apiVersion": "v1",
        "entries": {
            "demo": [
                {
                    "name": "demo",
                    "version": "0.1.0",
                    "digest": digest,
                    "urls": ["https://charts.example.com/demo-0.1.0.tgz"],
                }
            ]
        },
    }


def _syncer(storage, repo_config, *, downloaded_sha: str):
    syncer = HelmSyncer(storage=storage, config=repo_config)
    # Avoid real HTTP for the index-store side effect.
    syncer._store_index_file = lambda *a, **k: None  # type: ignore[method-assign]
    # _download_chart returns (pool_path, sha256, size).
    syncer._download_chart = lambda *a, **k: (Path("/pool/demo-0.1.0.tgz"), downloaded_sha, 123)  # type: ignore[method-assign]
    return syncer


def test_normalize_digest():
    assert normalize_digest("sha256:" + _GOOD) == _GOOD
    assert normalize_digest(_GOOD) == _GOOD
    assert normalize_digest(None) is None
    assert normalize_digest("") is None


def test_tampered_chart_is_rejected(storage, session, repository):
    """index.yaml advertises _GOOD, but the bytes hash to _BAD -> rejected."""
    cfg = RepositoryConfig(id="h", name="H", type="helm", feed="https://charts.example.com")
    syncer = _syncer(storage, cfg, downloaded_sha=_BAD)

    with patch.object(syncer, "_fetch_index", return_value=_index(_GOOD)):
        stats = syncer.sync_repository(session, repository, cfg)

    assert stats["charts_added"] == 0, "tampered chart must not be added"
    assert session.query(ContentItem).count() == 0, "no ContentItem for a tampered chart"


def test_matching_chart_is_accepted(storage, session, repository):
    cfg = RepositoryConfig(id="h", name="H", type="helm", feed="https://charts.example.com")
    syncer = _syncer(storage, cfg, downloaded_sha=_GOOD)

    with patch.object(syncer, "_fetch_index", return_value=_index(_GOOD)):
        stats = syncer.sync_repository(session, repository, cfg)

    assert stats["charts_added"] == 1
    item = session.query(ContentItem).one()
    assert item.sha256 == _GOOD


def test_prefixed_digest_matches(storage, session, repository):
    """A 'sha256:'-prefixed index digest still verifies against the bare hash."""
    cfg = RepositoryConfig(id="h", name="H", type="helm", feed="https://charts.example.com")
    syncer = _syncer(storage, cfg, downloaded_sha=_GOOD)

    with patch.object(syncer, "_fetch_index", return_value=_index("sha256:" + _GOOD)):
        stats = syncer.sync_repository(session, repository, cfg)

    assert stats["charts_added"] == 1


def test_prefixed_digest_dedup(storage, session, repository):
    """A 'sha256:'-prefixed index digest dedups against a stored bare sha256."""
    existing = ContentItem(
        content_type="helm",
        name="demo",
        version="0.1.0",
        sha256=_GOOD,
        size_bytes=123,
        pool_path="ab/cd/demo-0.1.0.tgz",
        filename="demo-0.1.0.tgz",
        content_metadata={},
    )
    session.add(existing)
    session.commit()

    cfg = RepositoryConfig(id="h", name="H", type="helm", feed="https://charts.example.com")
    # If dedup works, _download_chart is never called; make it fail loudly if it is.
    syncer = HelmSyncer(storage=storage, config=cfg)
    syncer._store_index_file = lambda *a, **k: None  # type: ignore[method-assign]

    def _boom(*a, **k):
        raise AssertionError("_download_chart should not be called when the chart is deduped")

    syncer._download_chart = _boom  # type: ignore[method-assign]

    with patch.object(syncer, "_fetch_index", return_value=_index("sha256:" + _GOOD)):
        stats = syncer.sync_repository(session, repository, cfg)

    assert stats["charts_added"] == 0
    assert session.query(ContentItem).count() == 1  # linked, not duplicated
    assert repository in existing.repositories
