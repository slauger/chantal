"""Helm: stale index.yaml pruning and autoflush-safe in-run chart dedup."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from chantal.core.config import RepositoryConfig
from chantal.db.connection import DatabaseManager
from chantal.db.models import Base, ContentItem, Repository, RepositoryFile, Snapshot
from chantal.plugins.helm.sync import HelmSyncer


def _config():
    return RepositoryConfig(id="demo", name="Demo", type="helm", feed="http://example.com/charts")


@pytest.fixture
def session(tmp_path):
    dbm = DatabaseManager(f"sqlite:///{tmp_path / 'chantal.db'}")
    Base.metadata.create_all(dbm.engine)
    return dbm.get_session()


def _index_file(sha: str) -> RepositoryFile:
    return RepositoryFile(
        file_category="metadata",
        file_type="index",
        sha256=sha,
        size_bytes=1,
        pool_path=f"{sha[:2]}/{sha[2:4]}/index.yaml",
        original_path="index.yaml",
        file_metadata={},
    )


def test_prune_stale_index_unlinks_old_keeps_current(session):
    repo = Repository(repo_id="demo", name="Demo", type="helm", feed="http://x", mode="MIRROR")
    session.add(repo)
    session.flush()

    current = _index_file("c" * 64)
    stale_orphan = _index_file("a" * 64)
    stale_snapshot = _index_file("b" * 64)
    for rf in (current, stale_orphan, stale_snapshot):
        repo.repository_files.append(rf)
    snap = Snapshot(repository_id=repo.id, name="snap-1")
    snap.repository_files.append(stale_snapshot)
    session.add(snap)
    session.commit()

    syncer = HelmSyncer(storage=None, config=_config())
    syncer._prune_stale_index(session, repo, "c" * 64)

    session.refresh(repo)
    linked = {rf.sha256 for rf in repo.repository_files}
    assert linked == {"c" * 64}  # only the current index remains linked
    remaining = {rf.sha256 for rf in session.query(RepositoryFile).all()}
    assert "a" * 64 not in remaining  # orphan deleted
    assert "b" * 64 in remaining  # snapshot-referenced kept


def test_digestless_duplicate_in_one_sync_dedup_autoflush_off(session):
    """Two digest-less entries with identical bytes in one sync must dedup even
    though the production session is autoflush=False."""
    repo = Repository(repo_id="demo", name="Demo", type="helm", feed="http://x", mode="MIRROR")
    session.add(repo)
    session.commit()

    config = _config()
    syncer = HelmSyncer(storage=None, config=config)

    index = {
        "apiVersion": "v1",
        "entries": {
            "demo": [
                {"name": "demo", "version": "0.1.0", "urls": ["demo-0.1.0.tgz"]},
                {"name": "demo", "version": "0.1.0-dup", "urls": ["demo-0.1.0-dup.tgz"]},
            ]
        },
    }
    with (
        patch.object(syncer, "_fetch_index", return_value=index),
        patch.object(syncer, "_store_index_file", return_value="e" * 64),
        patch.object(syncer, "_download_chart", return_value=("ab/cd/demo.tgz", "cd" * 32, 123)),
    ):
        stats = syncer.sync_repository(session, repo, config)

    assert stats["charts_added"] == 1  # second deduped, no IntegrityError
    assert session.query(ContentItem).filter_by(content_type="helm").count() == 1
