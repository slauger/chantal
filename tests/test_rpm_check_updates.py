"""check_updates must use rpm EVR ordering, not PEP 440.

A release bump 9.el9 -> 10.el9 is a real update, but PEP 440 / lexical string
comparison ('10.el9' > '9.el9' is False) reported "no update available".
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from unittest.mock import patch

import pytest

from chantal.core.config import RepositoryConfig
from chantal.db.connection import DatabaseManager
from chantal.db.models import Base, ContentItem, Repository
from chantal.plugins.rpm.sync import RpmSyncPlugin


@pytest.fixture
def session(tmp_path):
    dbm = DatabaseManager(f"sqlite:///{tmp_path / 'chantal.db'}")
    Base.metadata.create_all(dbm.engine)
    return dbm.get_session()


def _remote_pkg(release: str) -> dict:
    return {
        "name": "demo",
        "arch": "x86_64",
        "version": "1.0",
        "release": release,
        "epoch": "0",
        "size_bytes": 1,
        "sha256": "a" * 64,
        "location": "Packages/demo.rpm",
    }


def test_check_updates_uses_evr_ordering(session):
    repo = Repository(repo_id="demo", name="Demo", type="rpm", feed="http://x", mode="MIRROR")
    session.add(repo)
    session.flush()
    # Locally have 1.0-9.el9; upstream offers 1.0-10.el9 (a real update).
    local = ContentItem(
        content_type="rpm",
        name="demo",
        version="1.0",
        sha256="b" * 64,
        size_bytes=1,
        pool_path="bb/bb/demo.rpm",
        filename="demo-1.0-9.el9.x86_64.rpm",
        content_metadata={"arch": "x86_64", "release": "9.el9", "epoch": "0"},
    )
    local.repositories.append(repo)
    session.add(local)
    session.commit()

    config = RepositoryConfig(id="demo", name="Demo", type="rpm", feed="http://example.com/repo")
    plugin = RpmSyncPlugin(storage=None, config=config)

    with (
        patch("chantal.plugins.rpm.sync.parsers.fetch_repomd_xml", return_value=ET.Element("r")),
        patch(
            "chantal.plugins.rpm.sync.parsers.extract_all_metadata",
            return_value=[{"file_type": "primary", "location": "p", "checksum": "c"}],
        ),
        patch(
            "chantal.plugins.rpm.sync.parsers.fetch_metadata_with_cache",
            return_value=(b"<metadata/>", False),
        ),
        patch(
            "chantal.plugins.rpm.sync.parsers.parse_primary_xml",
            return_value=[_remote_pkg("10.el9")],
        ),
    ):
        result = plugin.check_updates(session, repo)

    assert result.success
    versions = [(u.name, u.remote_release) for u in result.updates_available]
    assert versions == [("demo", "10.el9")], f"10.el9 update not detected: {versions}"
