"""Storage: atomic pool writes and cross-filesystem link fallback."""

from __future__ import annotations

import errno
import os

import pytest

import chantal.core.storage as storage_mod
from chantal.core.config import StorageConfig
from chantal.core.storage import StorageManager


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


def test_atomic_store_failure_leaves_no_partial(storage, tmp_path):
    src = tmp_path / "src.bin"
    src.write_bytes(b"payload")
    dest = storage.pool_path / "ab" / "cd" / "ab_demo.rpm"

    # A wrong expected sha makes the post-copy verification fail.
    with pytest.raises(ValueError, match="Checksum verification failed"):
        storage._atomic_store(src, dest, "0" * 64, verify_checksum=True)

    assert not dest.exists()  # nothing left at the canonical path
    # And no .tmp leftover in the destination dir.
    assert not any(p.suffix == ".tmp" for p in dest.parent.iterdir())


def test_atomic_store_success(storage, tmp_path):
    import hashlib

    src = tmp_path / "src.bin"
    src.write_bytes(b"payload")
    dest = storage.pool_path / "ab" / "cd" / "ab_demo.rpm"

    storage._atomic_store(src, dest, hashlib.sha256(b"payload").hexdigest(), verify_checksum=True)

    assert dest.read_bytes() == b"payload"
    assert not any(p.suffix == ".tmp" for p in dest.parent.iterdir())


def test_link_or_copy_same_filesystem_hardlinks(storage, tmp_path):
    src = storage.pool_path / "src.bin"
    src.write_bytes(b"data")
    target = tmp_path / "out" / "linked.bin"

    storage.link_or_copy(src, target)

    assert target.read_bytes() == b"data"
    assert os.stat(src).st_ino == os.stat(target).st_ino  # a real hardlink


def test_link_or_copy_falls_back_to_copy_on_exdev(storage, tmp_path, monkeypatch):
    src = storage.pool_path / "src.bin"
    src.write_bytes(b"data")
    target = tmp_path / "out" / "copied.bin"

    def fake_link(a, b):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(storage_mod.os, "link", fake_link)
    storage.link_or_copy(src, target)

    assert target.read_bytes() == b"data"
    assert os.stat(src).st_ino != os.stat(target).st_ino  # a copy, not a link


def test_link_or_copy_reraises_other_oserror(storage, tmp_path, monkeypatch):
    src = storage.pool_path / "src.bin"
    src.write_bytes(b"data")
    target = tmp_path / "out" / "x.bin"

    def fake_link(a, b):
        raise OSError(errno.EACCES, "permission denied")

    monkeypatch.setattr(storage_mod.os, "link", fake_link)
    with pytest.raises(OSError, match="permission denied"):
        storage.link_or_copy(src, target)
