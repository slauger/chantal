"""Helm: publish resolves charts via the stored pool_path, and HTTP downloads
strip query strings from the pooled/published filename.

Regression for OCI charts: their ContentItem.filename (e.g. "chart:1.2.3", from
the oci:// basename) does not match the name they were pooled under
("chart-1.2.3.tgz"), so a publisher that rebuilds the pool path from
sha256+filename can't find the file.
"""

from __future__ import annotations

from unittest.mock import Mock

from chantal.core.config import RepositoryConfig, StorageConfig
from chantal.core.storage import StorageManager
from chantal.db.models import Base, ContentItem, Repository
from chantal.plugins.helm.publisher import HelmPublisher
from chantal.plugins.helm.sync import HelmSyncer


def _storage(tmp_path):
    (tmp_path / "pool").mkdir()
    return StorageManager(
        StorageConfig(
            base_path=str(tmp_path),
            pool_path=str(tmp_path / "pool"),
            published_path=str(tmp_path / "published"),
        )
    )


def test_publish_resolves_via_stored_pool_path(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    storage = _storage(tmp_path)
    # Pool a chart under its real tarball name.
    src = tmp_path / "src.tgz"
    src.write_bytes(b"chart-bytes")
    sha256, pool_rel, size = storage.add_package(src, "mychart-1.2.3.tgz")

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    repo = Repository(repo_id="oci", name="OCI", type="helm", feed="oci://x", mode="FILTERED")
    session.add(repo)
    session.commit()

    # The ContentItem.filename is the (wrong) oci:// basename, but pool_path is
    # authoritative.
    chart = ContentItem(
        content_type="helm",
        name="mychart",
        version="1.2.3",
        sha256=sha256,
        size_bytes=size,
        pool_path=pool_rel,
        filename="mychart:1.2.3",
        content_metadata={"name": "mychart", "version": "1.2.3"},
    )

    config = RepositoryConfig(id="oci", name="OCI", type="helm", feed="oci://x")
    target = tmp_path / "published"
    publisher = HelmPublisher(storage=storage)

    # Must not raise FileNotFoundError (the bug); the chart is published.
    publisher._publish_charts([chart], target, config, session, repo)
    assert (target / "mychart:1.2.3").read_bytes() == b"chart-bytes"


def test_http_download_strips_query_string(tmp_path):
    storage = _storage(tmp_path)
    config = RepositoryConfig(id="h", name="H", type="helm", feed="http://x")
    syncer = HelmSyncer(storage=storage, config=config)

    resp = Mock()
    resp.iter_content = lambda chunk_size=8192: [b"data"]
    resp.raise_for_status = Mock()
    syncer.session.get = Mock(return_value=resp)

    _, _, _, filename = syncer._download_http_chart(
        "https://charts.example.com/demo-1.0.0.tgz?token=abc&x=1", config
    )
    assert filename == "demo-1.0.0.tgz"  # no query string baked in
