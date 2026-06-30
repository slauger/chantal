"""snapshot delete must refuse to orphan a view snapshot.

``ViewSnapshot.snapshot_ids`` is a plain JSON list of ``Snapshot.id`` with no
foreign key or cascade. Deleting a referenced snapshot would silently leave a
dangling reference that breaks the view snapshot when it is published, so the
delete command must refuse (unless ``--force``).
"""

from __future__ import annotations

import yaml
from click.testing import CliRunner

from chantal.cli.main import cli
from chantal.db.connection import DatabaseManager
from chantal.db.models import Base, Repository, Snapshot, View, ViewSnapshot


def _config(tmp_path, db_url):
    cfg = {
        "database": {"url": db_url},
        "storage": {
            "base_path": str(tmp_path / "data"),
            "pool_path": str(tmp_path / "data" / "pool"),
            "published_path": str(tmp_path / "published"),
        },
        "repositories": [{"id": "repo", "type": "rpm", "feed": "http://x"}],
    }
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return str(p)


def _seed(db_url):
    """A repo with one snapshot referenced by a view snapshot."""
    dbm = DatabaseManager(db_url)
    Base.metadata.create_all(dbm.engine)
    session = dbm.get_session()
    repo = Repository(repo_id="repo", name="R", type="rpm", feed="http://x", mode="MIRROR")
    session.add(repo)
    session.flush()
    snap = Snapshot(repository_id=repo.id, name="2026-01-01")
    session.add(snap)
    session.flush()
    view = View(name="prod", repo_type="rpm")
    session.add(view)
    session.flush()
    vs = ViewSnapshot(view_id=view.id, name="release-1", snapshot_ids=[snap.id])
    session.add(vs)
    session.commit()
    snap_id = snap.id
    session.close()
    return snap_id


def test_delete_refuses_when_referenced_by_view_snapshot(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'chantal.db'}"
    snap_id = _seed(db_url)
    cfg = _config(tmp_path, db_url)

    result = CliRunner().invoke(
        cli, ["--config", cfg, "snapshot", "delete", "--repo-id", "repo", "2026-01-01"]
    )

    # Refused, with a helpful message naming the referencing view snapshot...
    assert result.exit_code != 0
    assert "referenced by" in result.output
    assert "release-1" in result.output
    # ...and the snapshot is still present (no dangling reference created).
    session = DatabaseManager(db_url).get_session()
    assert session.query(Snapshot).filter_by(id=snap_id).first() is not None
    session.close()


def test_force_deletes_referenced_snapshot(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'chantal.db'}"
    snap_id = _seed(db_url)
    cfg = _config(tmp_path, db_url)

    result = CliRunner().invoke(
        cli,
        ["--config", cfg, "snapshot", "delete", "--repo-id", "repo", "2026-01-01", "--force"],
    )

    assert result.exit_code == 0
    session = DatabaseManager(db_url).get_session()
    assert session.query(Snapshot).filter_by(id=snap_id).first() is None
    session.close()
