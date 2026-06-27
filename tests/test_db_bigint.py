"""Size/byte columns must be BigInteger so PostgreSQL doesn't overflow int4
for >2 GiB files or multi-GiB aggregate counters."""

from __future__ import annotations

import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.orm import sessionmaker

from chantal.db.models import (
    Base,
    ContentItem,
    Repository,
    RepositoryFile,
    Snapshot,
    SyncHistory,
    ViewSnapshot,
)

_OVER_INT4 = 5_000_000_000  # > 2_147_483_647 (int4 max)


@pytest.mark.parametrize(
    "model, column",
    [
        (ContentItem, "size_bytes"),
        (RepositoryFile, "size_bytes"),
        (Snapshot, "total_size_bytes"),
        (SyncHistory, "bytes_downloaded"),
        (ViewSnapshot, "total_size_bytes"),
    ],
)
def test_size_columns_are_bigint(model, column):
    assert isinstance(model.__table__.c[column].type, BigInteger)


def test_large_size_round_trips():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    repo = Repository(repo_id="r", name="R", type="rpm", feed="http://x", mode="MIRROR")
    item = ContentItem(
        content_type="rpm",
        name="huge",
        version="1.0",
        sha256="a" * 64,
        size_bytes=_OVER_INT4,
        pool_path="ab/cd/huge.rpm",
        filename="huge.rpm",
        content_metadata={},
    )
    session.add_all([repo, item])
    session.commit()

    assert session.query(ContentItem).one().size_bytes == _OVER_INT4
