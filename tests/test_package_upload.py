"""Unit tests for `chantal package upload` core logic (_upload_rpm).

Covers the dedup / same-NEVRA-conflict / --force matrix without docker, using
synthetic RPMs (same builder as test_rpm_header_metadata) so the metadata
extraction, sha256 dedup and conflict resolution are exercised end to end.
"""

from __future__ import annotations

import struct

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from chantal.cli.package_commands import _upload_rpm
from chantal.core.config import StorageConfig
from chantal.core.storage import StorageManager
from chantal.db.models import Base, ContentItem, Repository

_HEADER_MAGIC = b"\x8e\xad\xe8\x01"
_LEAD = b"\xed\xab\xee\xdb" + b"\x00" * 92
_T_STRING = 6


def _build_header(items: list[tuple[int, int, bytes]]) -> bytes:
    index = b""
    store = b""
    for tag, rpm_type, raw in items:
        index += struct.pack(">IIII", tag, rpm_type, len(store), 1)
        store += raw
    intro = _HEADER_MAGIC + b"\x00" * 4 + struct.pack(">II", len(items), len(store))
    return intro + index + store


def _rpm(name: str, version: str, release: str, arch: str, summary: str) -> bytes:
    sig = _build_header([(1000, _T_STRING, b"x\x00")])
    pad = b"\x00" * (-(96 + len(sig)) % 8)
    main = _build_header(
        [
            (1000, _T_STRING, name.encode() + b"\x00"),
            (1001, _T_STRING, version.encode() + b"\x00"),
            (1002, _T_STRING, release.encode() + b"\x00"),
            (1022, _T_STRING, arch.encode() + b"\x00"),
            (1004, _T_STRING, summary.encode() + b"\x00"),
        ]
    )
    return _LEAD + sig + pad + main


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sess = sessionmaker(bind=engine)()
    yield sess
    sess.close()


@pytest.fixture
def storage(tmp_path):
    (tmp_path / "pool").mkdir()
    return StorageManager(
        StorageConfig(
            base_path=str(tmp_path),
            pool_path=str(tmp_path / "pool"),
            published_path=str(tmp_path / "published"),
        )
    )


@pytest.fixture
def repository(session):
    repo = Repository(repo_id="internal", name="Internal", type="rpm", feed="", mode="HOSTED")
    session.add(repo)
    session.commit()
    return repo


def _rpm_items(repository: Repository) -> list[ContentItem]:
    return [i for i in repository.content_items if i.content_type == "rpm"]


def test_upload_then_link_same_bytes(session, storage, repository, tmp_path):
    f = tmp_path / "demo-1.0-1.noarch.rpm"
    f.write_bytes(_rpm("demo", "1.0", "1", "noarch", "first"))

    assert _upload_rpm(session, storage, repository, f, force=False) == "uploaded"
    # Re-uploading the identical bytes just links (no duplicate ContentItem).
    assert _upload_rpm(session, storage, repository, f, force=False) == "linked"
    assert len(_rpm_items(repository)) == 1


def test_same_nevra_different_content_requires_force(session, storage, repository, tmp_path):
    a = tmp_path / "a.rpm"
    a.write_bytes(_rpm("demo", "1.0", "1", "noarch", "summary-a"))
    b = tmp_path / "b.rpm"
    b.write_bytes(_rpm("demo", "1.0", "1", "noarch", "summary-b"))  # same NEVRA, diff bytes

    assert _upload_rpm(session, storage, repository, a, force=False) == "uploaded"
    with pytest.raises(ValueError, match="already present"):
        _upload_rpm(session, storage, repository, b, force=False)
    # The rejected upload left exactly the original item linked.
    assert len(_rpm_items(repository)) == 1
    assert _rpm_items(repository)[0].content_metadata["summary"] == "summary-a"

    # --force replaces it atomically: still exactly one NEVRA, now the new one.
    assert _upload_rpm(session, storage, repository, b, force=True) == "replaced"
    items = _rpm_items(repository)
    assert len(items) == 1
    assert items[0].content_metadata["summary"] == "summary-b"


def test_pooled_conflict_still_requires_force(session, storage, repository, tmp_path):
    """A differing build whose bytes are already pooled (via another repo) must
    still require --force, not silently link a second same-NEVRA item."""
    other = Repository(repo_id="other", name="Other", type="rpm", feed="", mode="HOSTED")
    session.add(other)
    session.commit()

    a = tmp_path / "a.rpm"
    a.write_bytes(_rpm("demo", "1.0", "1", "noarch", "summary-a"))
    b = tmp_path / "b.rpm"
    b.write_bytes(_rpm("demo", "1.0", "1", "noarch", "summary-b"))

    _upload_rpm(session, storage, repository, a, force=False)  # repo: NEVRA sha-a
    _upload_rpm(session, storage, other, b, force=False)  # pool now also has sha-b

    # Uploading b into repo: bytes are pooled, but it's a different sha for the
    # same NEVRA already in repo -> conflict, not a silent link.
    with pytest.raises(ValueError, match="already present"):
        _upload_rpm(session, storage, repository, b, force=False)
    assert len(_rpm_items(repository)) == 1

    assert _upload_rpm(session, storage, repository, b, force=True) == "replaced"
    assert len(_rpm_items(repository)) == 1
