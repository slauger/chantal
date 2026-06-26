"""Tests that `chantal stats` and `chantal db stats` report real numbers."""

from __future__ import annotations

import yaml
from click.testing import CliRunner

from chantal.cli.main import cli
from chantal.db.connection import DatabaseManager
from chantal.db.models import Base, ContentItem, Repository, Snapshot


def _seed(db_url: str) -> None:
    dbm = DatabaseManager(db_url)
    Base.metadata.create_all(dbm.engine)
    session = dbm.get_session()

    repo = Repository(repo_id="r1", name="R1", type="rpm", feed="http://x", mode="MIRROR")
    session.add(repo)
    session.flush()

    shared = ContentItem(
        content_type="rpm",
        name="shared",
        version="1.0",
        sha256="a" * 64,
        size_bytes=1000,
        pool_path="aa/bb/shared.rpm",
        filename="shared.rpm",
        content_metadata={},
    )
    orphan = ContentItem(
        content_type="rpm",
        name="orphan",
        version="1.0",
        sha256="b" * 64,
        size_bytes=500,
        pool_path="bb/cc/orphan.rpm",
        filename="orphan.rpm",
        content_metadata={},
    )
    repo.content_items.append(shared)  # referenced; orphan is unreferenced
    snap = Snapshot(repository_id=repo.id, name="snap-1")
    snap.content_items.append(shared)  # shared is linked twice -> dedup savings
    session.add_all([shared, orphan, snap])
    session.commit()
    session.close()


def _config(tmp_path, db_url: str) -> str:
    config = {
        "database": {"url": db_url},
        "storage": {
            "base_path": str(tmp_path / "data"),
            "pool_path": str(tmp_path / "data" / "pool"),
            "published_path": str(tmp_path / "pub"),
        },
        "repositories": [],
    }
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(config), encoding="utf-8")
    return str(p)


def test_global_stats_reports_real_numbers(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'chantal.db'}"
    _seed(db_url)
    out = CliRunner().invoke(cli, ["--config", _config(tmp_path, db_url), "stats"])
    assert out.exit_code == 0, out.output
    assert "TODO" not in out.output and "Expected output" not in out.output
    assert "Total Repositories: 1" in out.output
    assert "Total Packages: 2" in out.output
    assert "Total Snapshots: 1" in out.output
    # shared (1000 B) is referenced by a repo + a snapshot -> 1000 B deduplicated.
    assert "Deduplication: 1000 B saved" in out.output


def test_repo_stats(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'chantal.db'}"
    _seed(db_url)
    out = CliRunner().invoke(
        cli, ["--config", _config(tmp_path, db_url), "stats", "--repo-id", "r1"]
    )
    assert out.exit_code == 0, out.output
    assert "Packages: 1" in out.output  # only 'shared' is linked to r1
    assert "TODO" not in out.output


def test_repo_stats_unknown_repo(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'chantal.db'}"
    _seed(db_url)
    out = CliRunner().invoke(
        cli, ["--config", _config(tmp_path, db_url), "stats", "--repo-id", "nope"]
    )
    assert out.exit_code == 1
    assert "not found" in out.output


def test_db_stats_reports_unreferenced(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'chantal.db'}"
    _seed(db_url)
    out = CliRunner().invoke(cli, ["--config", _config(tmp_path, db_url), "db", "stats"])
    assert out.exit_code == 0, out.output
    assert "TODO" not in out.output and "Expected output" not in out.output
    assert "Total Packages: 2" in out.output
    assert "Referenced Packages: 1" in out.output
    assert "Unreferenced Packages: 1" in out.output
