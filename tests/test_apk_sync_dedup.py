"""Regression: a duplicate/identical-content APKINDEX entry must not abort sync.

ContentItem.sha256 is globally unique and the production DB session is
autoflush=False, so a naive "query before insert" dedup misses a row added
earlier in the same run. Previously a repeated APKINDEX record (or two names for
one file) inserted a second row with the same sha256 and raised IntegrityError
at the final commit, rolling back the entire sync.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from chantal.core.config import ApkConfig, RepositoryConfig
from chantal.db.connection import DatabaseManager
from chantal.db.models import Base, ContentItem, Repository
from chantal.plugins.apk.sync import ApkSyncer


def _config():
    return RepositoryConfig(
        id="alpine",
        name="Alpine",
        type="apk",
        feed="http://example.com/alpine",
        apk=ApkConfig(branch="v3.19", repository="main", architecture="x86_64"),
    )


def _entry():
    return {
        "name": "demo",
        "version": "1.0-r0",
        "architecture": "x86_64",
        "checksum": "Q1" + "A" * 27,
        "size": "100",
    }


@pytest.fixture
def session(tmp_path):
    # Use the real DatabaseManager session (autoflush=False) to reproduce the bug.
    dbm = DatabaseManager(f"sqlite:///{tmp_path / 'chantal.db'}")
    Base.metadata.create_all(dbm.engine)
    return dbm.get_session()


def _run(session, syncer, config, repo, parsed):
    with (
        patch.object(syncer, "_fetch_apkindex", return_value=("", b"")),
        patch.object(syncer, "_store_apkindex_file"),
        patch.object(syncer, "_parse_apkindex", return_value=parsed),
        patch.object(
            syncer,
            "_download_package",
            return_value=("ab/cd/demo.apk", "ab" * 32, 100, True),
        ),
    ):
        return syncer.sync_repository(session, repo, config)


def test_duplicate_entries_in_one_sync_do_not_abort(session):
    repo = Repository(repo_id="alpine", name="Alpine", type="apk", feed="http://x", mode="MIRROR")
    session.add(repo)
    session.commit()

    config = _config()
    syncer = ApkSyncer(storage=None, config=config)

    # Same record listed twice in one APKINDEX -> identical downloaded bytes.
    stats = _run(session, syncer, config, repo, [_entry(), _entry()])

    assert stats["packages_added"] == 1  # second deduped, no IntegrityError
    items = session.query(ContentItem).filter_by(content_type="apk").all()
    assert len(items) == 1


def test_resync_links_instead_of_reinserting(session):
    repo = Repository(repo_id="alpine", name="Alpine", type="apk", feed="http://x", mode="MIRROR")
    session.add(repo)
    session.commit()

    config = _config()
    syncer = ApkSyncer(storage=None, config=config)

    first = _run(session, syncer, config, repo, [_entry()])
    assert first["packages_added"] == 1

    second = _run(session, syncer, config, repo, [_entry()])
    assert second["packages_added"] == 0
    assert session.query(ContentItem).filter_by(content_type="apk").count() == 1
