"""Pool GC must not delete an in-flight blob.

A sync writes a pool blob before committing the ContentItem that references it,
so a freshly-written unreferenced file is most likely an in-progress sync, not a
true orphan. get_orphaned_files skips files newer than a grace window.
"""

from __future__ import annotations

import os
import time

import pytest

from chantal.core.config import StorageConfig
from chantal.core.storage import StorageManager
from chantal.db.connection import DatabaseManager
from chantal.db.models import Base


@pytest.fixture
def session(tmp_path):
    dbm = DatabaseManager(f"sqlite:///{tmp_path / 'chantal.db'}")
    Base.metadata.create_all(dbm.engine)
    return dbm.get_session()


@pytest.fixture
def storage(tmp_path):
    pool = tmp_path / "pool"
    pool.mkdir()
    return StorageManager(
        StorageConfig(
            base_path=str(tmp_path), pool_path=str(pool), published_path=str(tmp_path / "pub")
        )
    )


def test_recent_unreferenced_blob_is_not_orphaned(session, storage):
    old = storage.pool_path / ("a" * 64 + "_old.bin")
    old.write_bytes(b"old")
    fresh = storage.pool_path / ("b" * 64 + "_fresh.bin")
    fresh.write_bytes(b"fresh")
    # Age the old blob beyond the grace window; the fresh one is just-written.
    aged = time.time() - 7200
    os.utime(old, (aged, aged))

    names = {p.name for p in storage.get_orphaned_files(session)}
    assert old.name in names  # genuinely old orphan -> collected
    assert fresh.name not in names  # within grace -> skipped (possible in-flight)

    # With no grace, both unreferenced blobs are orphans.
    names0 = {p.name for p in storage.get_orphaned_files(session, grace_seconds=0)}
    assert names0 == {old.name, fresh.name}


def test_cleanup_respects_grace_window(session, storage):
    fresh = storage.pool_path / ("c" * 64 + "_fresh.bin")
    fresh.write_bytes(b"fresh")
    removed, _ = storage.cleanup_orphaned_files(session, dry_run=False)
    assert removed == 0  # the in-flight-looking blob is preserved
    assert fresh.exists()
