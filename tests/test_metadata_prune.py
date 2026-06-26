"""Regression tests for ``_prune_stale_metadata`` (RPM + APT sync plugins).

On re-sync, when upstream regenerates its indices with fresh checksums, the
previous metadata files must be unlinked from the repository so they are not
republished alongside the current ones (duplicate indices) and so their pool
blobs become reclaimable. A metadata file that is still referenced by a snapshot
must be unlinked from the repository but its row kept (the snapshot still needs
it).
"""

from __future__ import annotations

import pytest

from chantal.core.config import AptConfig, RepositoryConfig
from chantal.db.connection import DatabaseManager
from chantal.db.models import Base, Repository, RepositoryFile, Snapshot
from chantal.plugins.apt.sync import AptSyncPlugin
from chantal.plugins.rpm.sync import RpmSyncPlugin


def _make_repo_file(sha: str, category: str, file_type: str) -> RepositoryFile:
    return RepositoryFile(
        file_category=category,
        file_type=file_type,
        sha256=sha,
        size_bytes=1,
        pool_path=f"{sha[:2]}/{sha[2:4]}/{file_type}",
        original_path=f"repodata/{file_type}",
        file_metadata={},
    )


def _rpm_plugin() -> RpmSyncPlugin:
    config = RepositoryConfig(
        id="demo", name="Demo", type="rpm", feed="http://example.com/repo", mode="mirror"
    )
    return RpmSyncPlugin(storage=None, config=config, proxy_config=None, ssl_config=None)


def _apt_plugin() -> AptSyncPlugin:
    config = RepositoryConfig(
        id="demo",
        name="Demo",
        type="apt",
        feed="http://example.com/repo",
        mode="mirror",
        apt=AptConfig(distribution="jammy", components=["main"], architectures=["amd64"]),
    )
    return AptSyncPlugin(storage=None, config=config, proxy_config=None, ssl_config=None)


@pytest.mark.parametrize("plugin_factory", [_rpm_plugin, _apt_plugin])
def test_prune_unlinks_stale_metadata_keeps_current(tmp_path, plugin_factory):
    dbm = DatabaseManager(f"sqlite:///{tmp_path / 'chantal.db'}")
    Base.metadata.create_all(dbm.engine)
    session = dbm.get_session()

    repo = Repository(repo_id="demo", name="Demo", type="rpm", feed="http://x", mode="MIRROR")
    session.add(repo)
    session.flush()

    current = _make_repo_file("c" * 64, "metadata", "primary")
    stale_orphan = _make_repo_file("a" * 64, "metadata", "primary")
    stale_snapshot = _make_repo_file("b" * 64, "metadata", "filelists")
    kickstart = _make_repo_file("d" * 64, "kickstart", "treeinfo")
    for rf in (current, stale_orphan, stale_snapshot, kickstart):
        repo.repository_files.append(rf)

    # The stale snapshot-referenced file must be preserved (unlinked from the
    # repo but its row kept because a snapshot still needs it).
    snap = Snapshot(repository_id=repo.id, name="snap-1")
    snap.repository_files.append(stale_snapshot)
    session.add(snap)
    session.commit()

    plugin_factory()._prune_stale_metadata(session, repo, {"c" * 64})

    session.refresh(repo)
    linked = {rf.sha256 for rf in repo.repository_files}
    # Current metadata stays; non-metadata (kickstart) is untouched; both stale
    # metadata files are unlinked from the repository.
    assert "c" * 64 in linked
    assert "d" * 64 in linked
    assert "a" * 64 not in linked
    assert "b" * 64 not in linked

    # The orphaned stale file's row is deleted; the snapshot-referenced one is kept.
    remaining = {rf.sha256 for rf in session.query(RepositoryFile).all()}
    assert "a" * 64 not in remaining
    assert "b" * 64 in remaining


def test_apt_prune_also_unlinks_stale_signature(tmp_path):
    """The APT prune covers ``signature`` files (Release.gpg), not just metadata."""
    dbm = DatabaseManager(f"sqlite:///{tmp_path / 'chantal.db'}")
    Base.metadata.create_all(dbm.engine)
    session = dbm.get_session()

    repo = Repository(repo_id="demo", name="Demo", type="apt", feed="http://x", mode="MIRROR")
    session.add(repo)
    session.flush()

    current = _make_repo_file("c" * 64, "metadata", "InRelease")
    stale_sig = _make_repo_file("e" * 64, "signature", "Release.gpg")
    repo.repository_files.append(current)
    repo.repository_files.append(stale_sig)
    session.commit()

    _apt_plugin()._prune_stale_metadata(session, repo, {"c" * 64})

    session.refresh(repo)
    linked = {rf.sha256 for rf in repo.repository_files}
    assert linked == {"c" * 64}
    assert session.query(RepositoryFile).filter_by(sha256="e" * 64).first() is None
