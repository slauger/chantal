"""APK: stale APKINDEX RepositoryFiles must be pruned on re-sync."""

from __future__ import annotations

import pytest

from chantal.core.config import ApkConfig, RepositoryConfig
from chantal.db.connection import DatabaseManager
from chantal.db.models import Base, Repository, RepositoryFile, Snapshot
from chantal.plugins.apk.sync import ApkSyncer


@pytest.fixture
def session(tmp_path):
    dbm = DatabaseManager(f"sqlite:///{tmp_path / 'chantal.db'}")
    Base.metadata.create_all(dbm.engine)
    return dbm.get_session()


def _apkindex(sha: str) -> RepositoryFile:
    return RepositoryFile(
        file_category="metadata",
        file_type="apkindex",
        sha256=sha,
        size_bytes=1,
        pool_path=f"{sha[:2]}/{sha[2:4]}/APKINDEX.tar.gz",
        original_path="v3.19/main/x86_64/APKINDEX.tar.gz",
        file_metadata={},
    )


def _syncer():
    config = RepositoryConfig(
        id="alpine",
        name="Alpine",
        type="apk",
        feed="http://example.com/alpine",
        apk=ApkConfig(branch="v3.19", repository="main", architecture="x86_64"),
    )
    return ApkSyncer(storage=None, config=config)


def test_prune_unlinks_old_apkindex_keeps_current(session):
    repo = Repository(repo_id="alpine", name="Alpine", type="apk", feed="http://x", mode="MIRROR")
    session.add(repo)
    session.flush()

    current = _apkindex("c" * 64)
    stale_orphan = _apkindex("a" * 64)
    stale_snapshot = _apkindex("b" * 64)
    for rf in (current, stale_orphan, stale_snapshot):
        repo.repository_files.append(rf)
    snap = Snapshot(repository_id=repo.id, name="snap-1")
    snap.repository_files.append(stale_snapshot)
    session.add(snap)
    session.commit()

    _syncer()._prune_stale_apkindex(session, repo, "c" * 64)

    session.refresh(repo)
    assert {rf.sha256 for rf in repo.repository_files} == {"c" * 64}
    remaining = {rf.sha256 for rf in session.query(RepositoryFile).all()}
    assert "a" * 64 not in remaining  # orphan deleted
    assert "b" * 64 in remaining  # snapshot-referenced kept
