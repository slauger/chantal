"""APK: bounded APKINDEX extraction, lenient decode, and single-fetch reuse."""

from __future__ import annotations

import io
import tarfile
from unittest.mock import Mock

import pytest

import chantal.plugins.apk.sync as apk_sync
from chantal.core.config import ApkConfig, RepositoryConfig
from chantal.plugins.apk.sync import ApkSyncer


def _apkindex_targz(body: bytes) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("APKINDEX")
        info.size = len(body)
        tar.addfile(info, io.BytesIO(body))
    return buf.getvalue()


def _syncer():
    config = RepositoryConfig(
        id="alpine",
        name="Alpine",
        type="apk",
        feed="http://example.com/alpine",
        apk=ApkConfig(branch="v3.19", repository="main", architecture="x86_64"),
    )
    syncer = ApkSyncer(storage=None, config=config)
    return syncer


def _mock_get(syncer, raw: bytes):
    resp = Mock()
    resp.content = raw
    resp.raise_for_status = Mock()
    syncer.session.get = Mock(return_value=resp)


def test_fetch_returns_text_and_raw_bytes():
    raw = _apkindex_targz(b"C:Q1xxx\nP:demo\nV:1.0-r0\n")
    syncer = _syncer()
    _mock_get(syncer, raw)

    text, returned_raw = syncer._fetch_apkindex("http://x/APKINDEX.tar.gz", syncer.config)

    assert "P:demo" in text
    assert returned_raw == raw  # raw reused for storage -> single download
    syncer.session.get.assert_called_once()


def test_fetch_decode_is_lenient():
    raw = _apkindex_targz(b"P:demo\nm:Ma\xffntainer\n")  # invalid UTF-8 byte
    syncer = _syncer()
    _mock_get(syncer, raw)

    text, _ = syncer._fetch_apkindex("http://x/APKINDEX.tar.gz", syncer.config)

    assert "P:demo" in text  # the index is not dropped over one bad byte


def test_fetch_rejects_oversized_apkindex(monkeypatch):
    monkeypatch.setattr(apk_sync, "_MAX_APKINDEX_BYTES", 8)
    raw = _apkindex_targz(b"P:demo\nV:1.0-r0\n")  # > 8 bytes uncompressed
    syncer = _syncer()
    _mock_get(syncer, raw)

    with pytest.raises(ValueError, match="too large"):
        syncer._fetch_apkindex("http://x/APKINDEX.tar.gz", syncer.config)
