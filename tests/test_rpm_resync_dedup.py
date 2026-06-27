"""Regression: re-syncing an RPM repo whose pkgid is not sha256 must not abort.

The pre-download dedup keys on the upstream pkgid (the package checksum in the
repo's algorithm - sha1/sha512), not the locally-computed sha256, so for a
non-sha256 repo it never matches and a re-sync would try to insert a second
ContentItem with the same sha256 -> IntegrityError at commit (which also poisons
the session). _download_package must dedup by the actual sha256 and link.
"""

from __future__ import annotations

import hashlib
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from chantal.core.config import RepositoryConfig, StorageConfig
from chantal.core.storage import StorageManager
from chantal.db.models import Base, ContentItem, Repository
from chantal.plugins.rpm.sync import RpmSyncPlugin


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_download_package_dedups_by_sha256_for_sha512_repo(tmp_path, session):
    (tmp_path / "pool").mkdir()
    storage = StorageManager(
        StorageConfig(
            base_path=str(tmp_path),
            pool_path=str(tmp_path / "pool"),
            published_path=str(tmp_path / "published"),
        )
    )
    config = RepositoryConfig(
        id="r", name="R", type="rpm", feed="http://example.com/repo", mode="mirror"
    )
    plugin = RpmSyncPlugin(storage=storage, config=config)

    rpm_bytes = b"rpm-payload" * 100
    sha256 = hashlib.sha256(rpm_bytes).hexdigest()
    sha512 = hashlib.sha512(rpm_bytes).hexdigest()  # the upstream pkgid (sha512)

    def fake_get(*a, **k):
        resp = Mock()
        resp.raise_for_status = Mock()
        resp.iter_content = lambda chunk_size=65536: [rpm_bytes]
        return resp

    plugin.session.get = Mock(side_effect=fake_get)

    pkg_meta = {
        "name": "demo",
        "version": "1.0",
        "release": "1.el9",
        "arch": "x86_64",
        "epoch": None,
        "location": "demo-1.0-1.el9.x86_64.rpm",
        "checksum_type": "sha512",
        "sha256": sha512,  # primary.xml stores the pkgid under this key
    }

    repo_a = Repository(repo_id="a", name="A", type="rpm", feed="http://x", mode="MIRROR")
    repo_b = Repository(repo_id="b", name="B", type="rpm", feed="http://y", mode="MIRROR")
    session.add_all([repo_a, repo_b])
    session.commit()

    # First sync downloads + stores. Second "sync" (e.g. another repo, or a
    # re-sync where the pkgid-keyed pre-check missed) must link, not re-insert.
    plugin._download_package("http://x/demo.rpm", pkg_meta, session, repo_a)
    plugin._download_package("http://x/demo.rpm", pkg_meta, session, repo_b)

    items = session.query(ContentItem).filter_by(sha256=sha256).all()
    assert len(items) == 1  # deduped, no IntegrityError
    assert repo_a in items[0].repositories
    assert repo_b in items[0].repositories
