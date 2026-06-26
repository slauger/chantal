"""Regression test: installer/.treeinfo paths from upstream must be confined.

``original_path`` for kickstart/installer files comes verbatim from the upstream
``.treeinfo``. A malicious entry (``../../etc/cron.d/x`` or an absolute path)
must not let the publisher hardlink attacker-controlled content outside the
published repository tree.
"""

from __future__ import annotations

import pytest

from chantal.core.config import StorageConfig
from chantal.core.storage import StorageManager
from chantal.db.models import RepositoryFile
from chantal.plugins.rpm.publisher import RpmPublisher


@pytest.fixture
def publisher_and_pool(tmp_path):
    pool = tmp_path / "pool"
    pool.mkdir()
    storage = StorageManager(
        StorageConfig(
            base_path=str(tmp_path),
            pool_path=str(pool),
            published_path=str(tmp_path / "published"),
        )
    )
    # A pooled blob the kickstart files point at.
    blob_dir = pool / "ab" / "cd"
    blob_dir.mkdir(parents=True)
    (blob_dir / "blob.bin").write_bytes(b"payload")
    return RpmPublisher(storage=storage), tmp_path


def _kickstart(original_path: str) -> RepositoryFile:
    return RepositoryFile(
        file_category="kickstart",
        file_type="boot.iso",
        sha256="a" * 64,
        pool_path="ab/cd/blob.bin",
        size_bytes=7,
        original_path=original_path,
        file_metadata={},
    )


def test_kickstart_relative_traversal_is_skipped(publisher_and_pool):
    publisher, tmp_path = publisher_and_pool
    target = tmp_path / "published"
    target.mkdir(exist_ok=True)

    publisher._publish_kickstart_files([_kickstart("../escaped.bin")], target)

    # The escaping write must not have happened anywhere outside the repo tree.
    assert not (tmp_path / "escaped.bin").exists()
    assert list(target.rglob("*")) == []  # nothing published either


def test_kickstart_absolute_path_is_skipped(publisher_and_pool):
    publisher, tmp_path = publisher_and_pool
    target = tmp_path / "published"
    target.mkdir(exist_ok=True)
    evil = tmp_path / "evil_abs.bin"

    publisher._publish_kickstart_files([_kickstart(str(evil))], target)

    assert not evil.exists()


def test_kickstart_safe_relative_path_is_published(publisher_and_pool):
    publisher, tmp_path = publisher_and_pool
    target = tmp_path / "published"
    target.mkdir(exist_ok=True)

    publisher._publish_kickstart_files([_kickstart("images/pxeboot/vmlinuz")], target)

    out = target / "images" / "pxeboot" / "vmlinuz"
    assert out.exists() and out.read_bytes() == b"payload"
