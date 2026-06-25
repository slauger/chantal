"""Tests for APK control-segment checksum + sync-time integrity rejection."""

from __future__ import annotations

import gzip
import io
import tarfile
import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from chantal.core.config import RepositoryConfig, StorageConfig
from chantal.core.storage import StorageManager
from chantal.plugins.apk.checksum import compute_apk_control_checksum
from chantal.plugins.apk.sync import ApkSyncer


def _gz_tar(name: str, content: bytes) -> bytes:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        info = tarfile.TarInfo(name)
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb") as gz:
        gz.write(raw.getvalue())
    return out.getvalue()


def _apk(control_payload: bytes = b"pkgname = demo\n", data_payload: bytes = b"hello\n") -> bytes:
    return _gz_tar(".PKGINFO", control_payload) + _gz_tar("usr/x", data_payload)


def test_checksum_is_control_segment_not_whole_file():
    apk = _apk()
    csum = compute_apk_control_checksum(apk)
    assert csum is not None and csum.startswith("Q1")
    # It is the control segment's checksum: changing only the DATA segment must
    # not change it, but changing the control segment must.
    apk_other_data = _gz_tar(".PKGINFO", b"pkgname = demo\n") + _gz_tar("usr/x", b"different\n")
    assert compute_apk_control_checksum(apk_other_data) == csum
    apk_other_control = _gz_tar(".PKGINFO", b"pkgname = evil\n") + _gz_tar("usr/x", b"hello\n")
    assert compute_apk_control_checksum(apk_other_control) != csum


def test_checksum_handles_signed_three_stream_apk():
    """For a signed apk [sign, control, data], control is still streams[-2]."""
    unsigned = _apk()  # [control, data]
    control_only = compute_apk_control_checksum(unsigned)
    signed = _gz_tar(".SIGN.RSA.key.pub", b"signature-bytes") + unsigned
    assert compute_apk_control_checksum(signed) == control_only


def test_checksum_rejects_non_apk():
    assert compute_apk_control_checksum(b"not an apk at all") is None
    assert compute_apk_control_checksum(b"") is None
    assert compute_apk_control_checksum(_gz_tar("only-one", b"x")) is None  # single stream


@pytest.fixture
def storage():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        sm = StorageManager(
            StorageConfig(
                base_path=str(tmp / "base"),
                pool_path=str(tmp / "pool"),
                published_path=str(tmp / "published"),
                temp_path=str(tmp / "tmp"),
            )
        )
        sm.ensure_directories()
        yield sm


def _syncer(storage, content: bytes):
    cfg = RepositoryConfig(
        id="a",
        name="A",
        type="apk",
        feed="https://example.com/alpine/",
        apk={"branch": "v3.19", "repository": "main", "architecture": "x86_64"},
    )
    syncer = ApkSyncer(storage=storage, config=cfg)
    resp = Mock()
    resp.raise_for_status = Mock()
    resp.iter_content = lambda chunk_size=8192: iter([content])
    syncer.session.get = Mock(return_value=resp)
    return syncer


def test_download_accepts_matching_checksum(storage):
    apk = _apk()
    expected = compute_apk_control_checksum(apk)
    syncer = _syncer(storage, apk)
    pool_path, sha256, size, ok = syncer._download_package(
        "https://example.com/demo-1.0-r0.apk", syncer.config, expected
    )
    assert ok is True
    assert pool_path and sha256 and size


def test_download_rejects_mismatched_checksum(storage):
    apk = _apk(control_payload=b"pkgname = tampered\n")
    syncer = _syncer(storage, apk)
    # Expected checksum is for a DIFFERENT control segment -> reject, no pooling.
    pool_path, sha256, size, ok = syncer._download_package(
        "https://example.com/demo-1.0-r0.apk", syncer.config, "Q1deadbeefdeadbeefdeadbeefdeadbeef="
    )
    assert ok is False
    assert pool_path is None and sha256 is None and size is None
    # Nothing was written to the pool.
    assert not list((storage.pool_path).rglob("*.apk"))
