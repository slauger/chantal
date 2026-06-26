"""Regression test: `db cleanup --orphaned` must remove a repository's snapshots
AND their many-to-many association rows via the ORM cascade. A bulk delete left
dangling snapshot_content_items / snapshot_repository_files rows, which violates
the foreign-key constraint on PostgreSQL.
"""

from __future__ import annotations

from datetime import UTC, datetime

import yaml
from click.testing import CliRunner
from sqlalchemy import text

from chantal.cli.main import cli
from chantal.db.connection import DatabaseManager
from chantal.db.models import (
    Base,
    ContentItem,
    Repository,
    RepositoryFile,
    Snapshot,
    SyncHistory,
)


def _seed_orphan(db_url: str) -> int:
    """Create an orphaned repo with a snapshot that has content + file links."""
    dbm = DatabaseManager(db_url)
    Base.metadata.create_all(dbm.engine)
    session = dbm.get_session()

    repo = Repository(repo_id="orphan", name="Orphan", type="rpm", feed="http://x", mode="MIRROR")
    session.add(repo)
    session.flush()

    item = ContentItem(
        content_type="rpm",
        name="demo",
        version="1.0",
        sha256="a" * 64,
        size_bytes=1,
        pool_path="ab/cd/demo.rpm",
        filename="demo.rpm",
        content_metadata={},
    )
    rf = RepositoryFile(
        file_category="metadata",
        file_type="primary",
        sha256="b" * 64,
        size_bytes=1,
        pool_path="cd/ef/primary.xml.gz",
        original_path="repodata/primary.xml.gz",
        file_metadata={},
    )
    snap = Snapshot(repository_id=repo.id, name="snap-1")
    snap.content_items.append(item)
    snap.repository_files.append(rf)
    session.add(snap)
    session.add(SyncHistory(repository_id=repo.id, status="success", started_at=datetime.now(UTC)))
    session.commit()
    snap_id = snap.id
    session.close()
    return snap_id


def test_db_cleanup_orphaned_clears_snapshot_associations(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'chantal.db'}"
    snap_id = _seed_orphan(db_url)

    config = {
        "database": {"url": db_url},
        "storage": {
            "base_path": str(tmp_path / "data"),
            "pool_path": str(tmp_path / "data" / "pool"),
            "published_path": str(tmp_path / "published"),
        },
        "repositories": [],  # nothing configured -> the DB repo is orphaned
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    result = CliRunner().invoke(
        cli, ["--config", str(config_path), "db", "cleanup", "--orphaned", "--force"]
    )
    assert result.exit_code == 0, f"cleanup failed:\n{result.output}\n{result.exception}"

    # Repo, snapshot and sync history are gone, and crucially no association
    # rows are left dangling for the deleted snapshot.
    session = DatabaseManager(db_url).get_session()
    try:
        assert session.query(Repository).count() == 0
        assert session.query(Snapshot).count() == 0
        assert session.query(SyncHistory).count() == 0
        for assoc in ("snapshot_content_items", "snapshot_repository_files"):
            rows = session.execute(
                text(f"SELECT COUNT(*) FROM {assoc} WHERE snapshot_id = :sid"), {"sid": snap_id}
            ).scalar()
            assert rows == 0, f"orphaned rows left in {assoc}"
    finally:
        session.close()


def _config(tmp_path, db_url, repositories=None):
    cfg = {
        "database": {"url": db_url},
        "storage": {
            "base_path": str(tmp_path / "data"),
            "pool_path": str(tmp_path / "data" / "pool"),
            "published_path": str(tmp_path / "published"),
        },
        "repositories": repositories or [],
    }
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return str(p)


def _seed_unreferenced(db_url):
    """A repo with one referenced item + one truly unreferenced item."""
    dbm = DatabaseManager(db_url)
    Base.metadata.create_all(dbm.engine)
    session = dbm.get_session()
    repo = Repository(repo_id="keep", name="K", type="rpm", feed="http://x", mode="MIRROR")
    session.add(repo)
    session.flush()
    referenced = ContentItem(
        content_type="rpm",
        name="ref",
        version="1",
        sha256="a" * 64,
        size_bytes=100,
        pool_path="aa/ref",
        filename="ref.rpm",
        content_metadata={},
    )
    orphan = ContentItem(
        content_type="rpm",
        name="orphan",
        version="1",
        sha256="b" * 64,
        size_bytes=200,
        pool_path="bb/orphan",
        filename="orphan.rpm",
        content_metadata={},
    )
    repo.content_items.append(referenced)
    session.add_all([referenced, orphan])
    session.commit()
    session.close()


def test_cleanup_unreferenced_deletes_only_orphan_items(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'chantal.db'}"
    _seed_unreferenced(db_url)
    # 'keep' is configured, so it is NOT an orphaned repo.
    cfg = _config(
        tmp_path, db_url, repositories=[{"id": "keep", "type": "rpm", "feed": "http://x"}]
    )

    result = CliRunner().invoke(
        cli, ["--config", cfg, "db", "cleanup", "--unreferenced", "--force"]
    )
    assert result.exit_code == 0, f"{result.output}\n{result.exception}"
    assert "TODO" not in result.output
    assert "Deleted 1 unreferenced packages" in result.output

    session = DatabaseManager(db_url).get_session()
    try:
        names = {c.name for c in session.query(ContentItem).all()}
        assert names == {"ref"}, f"unexpected items: {names}"
    finally:
        session.close()


def test_cleanup_unreferenced_dry_run_deletes_nothing(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'chantal.db'}"
    _seed_unreferenced(db_url)
    cfg = _config(
        tmp_path, db_url, repositories=[{"id": "keep", "type": "rpm", "feed": "http://x"}]
    )

    result = CliRunner().invoke(
        cli, ["--config", cfg, "db", "cleanup", "--unreferenced", "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert "Would delete 1 unreferenced packages" in result.output
    session = DatabaseManager(db_url).get_session()
    try:
        assert session.query(ContentItem).count() == 2  # nothing deleted
    finally:
        session.close()


def test_full_cleanup_removes_items_orphaned_by_repo_deletion(tmp_path):
    """Deleting an orphaned repo unlinks its snapshot's content item; the same
    run's unreferenced pass (recomputed) must then remove that item too."""
    db_url = f"sqlite:///{tmp_path / 'chantal.db'}"
    _seed_orphan(db_url)  # orphan repo + snapshot linked to one content item
    cfg = _config(tmp_path, db_url, repositories=[])  # repo is orphaned

    result = CliRunner().invoke(cli, ["--config", cfg, "db", "cleanup", "--force"])
    assert result.exit_code == 0, f"{result.output}\n{result.exception}"

    session = DatabaseManager(db_url).get_session()
    try:
        assert session.query(Repository).count() == 0
        # The content item that was only linked via the deleted snapshot is gone.
        assert session.query(ContentItem).count() == 0
    finally:
        session.close()


def test_cleanup_unreferenced_confirmation_abort(tmp_path):
    """Without --force, answering 'n' aborts and deletes nothing."""
    db_url = f"sqlite:///{tmp_path / 'chantal.db'}"
    _seed_unreferenced(db_url)
    cfg = _config(
        tmp_path, db_url, repositories=[{"id": "keep", "type": "rpm", "feed": "http://x"}]
    )

    result = CliRunner().invoke(
        cli, ["--config", cfg, "db", "cleanup", "--unreferenced"], input="n\n"
    )
    assert result.exit_code == 0, result.output
    assert "1 unreferenced packages" in result.output  # shown in the confirmation
    assert "Aborted." in result.output
    session = DatabaseManager(db_url).get_session()
    try:
        assert session.query(ContentItem).count() == 2  # nothing deleted
    finally:
        session.close()
