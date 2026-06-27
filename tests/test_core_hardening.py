"""Core hardening: cache key validation, redirect header stripping, gpg warning."""

from __future__ import annotations

import logging
from unittest.mock import Mock

from chantal.core.cache import MetadataCache
from chantal.core.config import SignatureVerificationConfig
from chantal.core.downloader import RequestsBackend
from chantal.core.gpg_verify import GpgVerifier


# --- cache: a non-hex key must not be used to read/deserialize a file ---------
def test_cache_rejects_traversal_key(tmp_path):
    cache = MetadataCache(cache_path=tmp_path / "cache", enabled=True)
    # Plant a file the traversal would point at, to prove it is NOT read.
    (tmp_path / "evil.xml.gz").write_bytes(b"x")
    assert cache.get("../../evil") is None
    assert cache.get_parsed("../../evil") is None
    # A legit hex key simply misses (nothing cached) without raising.
    assert cache.get("a" * 64) is None


# --- downloader: custom auth headers stripped on a cross-host redirect ---------
def test_custom_headers_stripped_on_cross_host_redirect():
    import requests

    session = requests.Session()
    session.headers.update({"X-API-Key": "secret"})
    RequestsBackend._strip_custom_headers_on_redirect(session, {"X-API-Key"})

    def _req(url, headers):
        r = Mock()
        r.url = url
        r.headers = headers
        return r

    # Cross-host redirect: header dropped.
    prepared = _req("https://evil.example/x", {"X-API-Key": "secret"})
    resp = Mock(request=_req("https://upstream.example/x", {}))
    session.rebuild_auth(prepared, resp)
    assert "X-API-Key" not in prepared.headers

    # Same-host redirect: header kept.
    prepared2 = _req("https://upstream.example/y", {"X-API-Key": "secret"})
    resp2 = Mock(request=_req("https://upstream.example/x", {}))
    session.rebuild_auth(prepared2, resp2)
    assert prepared2.headers.get("X-API-Key") == "secret"


# --- gpg: warn when a shared gnupg_home is used without fingerprint pinning ----
def test_gpg_warns_on_shared_home_without_pinning(tmp_path, caplog):
    home = tmp_path / "gpghome"
    config = SignatureVerificationConfig(enabled=True, keys=["x"], gnupg_home=str(home))
    with caplog.at_level(logging.WARNING):
        GpgVerifier(config)
    assert any("trusted_fingerprints" in r.message for r in caplog.records)


def test_gpg_no_warning_with_default_keyring(tmp_path, caplog):
    config = SignatureVerificationConfig(enabled=True, keys=["x"])  # temp keyring
    with caplog.at_level(logging.WARNING):
        GpgVerifier(config)
    assert not any("trusted_fingerprints" in r.message for r in caplog.records)


# --- pool cleanup: must not delete a snapshot-referenced item with missing file
def test_pool_cleanup_keeps_snapshot_referenced_missing_file(tmp_path):
    import yaml
    from click.testing import CliRunner

    from chantal.cli.main import cli
    from chantal.db.connection import DatabaseManager
    from chantal.db.models import Base, ContentItem, Repository, Snapshot

    db_url = f"sqlite:///{tmp_path / 'chantal.db'}"
    dbm = DatabaseManager(db_url)
    Base.metadata.create_all(dbm.engine)
    session = dbm.get_session()
    repo = Repository(repo_id="r", name="R", type="rpm", feed="http://x", mode="MIRROR")
    session.add(repo)
    session.flush()
    # A content item whose pool file does NOT exist, referenced by a snapshot.
    item = ContentItem(
        content_type="rpm",
        name="demo",
        version="1.0",
        sha256="a" * 64,
        size_bytes=1,
        pool_path="ab/cd/missing.rpm",
        filename="missing.rpm",
        content_metadata={},
    )
    snap = Snapshot(repository_id=repo.id, name="snap-1")
    snap.content_items.append(item)
    session.add(snap)
    session.commit()
    session.close()

    pool = tmp_path / "data" / "pool"
    pool.mkdir(parents=True)  # pool dir exists, but the file inside does not
    config = {
        "database": {"url": db_url},
        "storage": {
            "base_path": str(tmp_path / "data"),
            "pool_path": str(pool),
            "published_path": str(tmp_path / "published"),
        },
        "repositories": [],
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    result = CliRunner().invoke(
        cli, ["--config", str(config_path), "pool", "cleanup", "--missing", "--force"]
    )
    assert result.exit_code == 0, f"{result.output}\n{result.exception}"

    session = dbm.get_session()
    try:
        # The snapshot-referenced item must survive (immutable snapshot intact).
        assert session.query(ContentItem).count() == 1
    finally:
        session.close()
