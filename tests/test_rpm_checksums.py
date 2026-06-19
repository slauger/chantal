"""Tests for algorithm-aware RPM checksum handling (sha256/sha512/sha1)."""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET

import pytest

from chantal.plugins.rpm import parsers


class TestNormalizeChecksumType:
    def test_defaults_to_sha256(self):
        assert parsers.normalize_checksum_type(None) == "sha256"

    def test_sha_alias_is_sha1(self):
        assert parsers.normalize_checksum_type("sha") == "sha1"
        assert parsers.normalize_checksum_type("SHA1") == "sha1"

    def test_sha512(self):
        assert parsers.normalize_checksum_type("sha512") == "sha512"

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unsupported checksum type"):
            parsers.normalize_checksum_type("crc32")

    def test_md5_rejected(self):
        # md5 gives no meaningful integrity guarantee and is not accepted.
        with pytest.raises(ValueError, match="Unsupported checksum type"):
            parsers.normalize_checksum_type("md5")


class TestVerifyDataChecksum:
    def test_sha256_match(self):
        data = b"hello"
        assert parsers.verify_data_checksum(data, "sha256", hashlib.sha256(data).hexdigest())

    def test_sha512_match(self):
        data = b"hello"
        assert parsers.verify_data_checksum(data, "sha512", hashlib.sha512(data).hexdigest())

    def test_default_type_is_sha256(self):
        data = b"hello"
        assert parsers.verify_data_checksum(data, None, hashlib.sha256(data).hexdigest())

    def test_mismatch(self):
        assert not parsers.verify_data_checksum(b"hello", "sha256", "0" * 64)

    def test_wrong_algorithm_fails(self):
        # A sha512 value won't match when verified as sha256.
        data = b"hello"
        assert not parsers.verify_data_checksum(data, "sha256", hashlib.sha512(data).hexdigest())

    def test_empty_expected_raises(self):
        # Fail closed rather than silently skip verification.
        with pytest.raises(ValueError, match="empty expected checksum"):
            parsers.verify_data_checksum(b"hello", "sha256", "")


class TestVerifyFileChecksum:
    def test_file_sha512(self, tmp_path):
        f = tmp_path / "blob"
        f.write_bytes(b"payload" * 100)
        digest = hashlib.sha512(f.read_bytes()).hexdigest()
        assert parsers.verify_file_checksum(f, "sha512", digest)
        assert not parsers.verify_file_checksum(f, "sha512", "0" * 128)

    def test_file_sha1_alias(self, tmp_path):
        f = tmp_path / "blob"
        f.write_bytes(b"legacy")
        digest = hashlib.sha1(f.read_bytes()).hexdigest()
        # "sha" is the legacy alias for sha1 used by old repositories.
        assert parsers.verify_file_checksum(f, "sha", digest)

    def test_empty_expected_raises(self, tmp_path):
        f = tmp_path / "blob"
        f.write_bytes(b"x")
        with pytest.raises(ValueError, match="empty expected checksum"):
            parsers.verify_file_checksum(f, "sha256", "")


class TestCacheAlgorithmAware:
    def test_cache_put_get_sha512(self, tmp_path):
        from chantal.core.cache import MetadataCache

        cache = MetadataCache(cache_path=tmp_path / "cache", enabled=True)
        content = b"compressed-metadata-bytes" * 10
        sha512 = hashlib.sha512(content).hexdigest()

        # Previously this raised because put() assumed sha256 for the key.
        cached = cache.put(sha512, content, "primary", algorithm="sha512")
        assert cached.exists()
        assert cache.get(sha512, "primary") == cached
        assert cached.read_bytes() == content

    def test_cache_put_rejects_mismatch(self, tmp_path):
        from chantal.core.cache import MetadataCache

        cache = MetadataCache(cache_path=tmp_path / "cache", enabled=True)
        with pytest.raises(ValueError, match="Checksum mismatch"):
            cache.put("0" * 128, b"content", "primary", algorithm="sha512")


class TestChecksumTypeParsing:
    def test_repomd_checksum_type_extracted(self):
        repomd = (
            '<repomd xmlns="http://linux.duke.edu/metadata/repo">'
            '<data type="primary">'
            '<checksum type="sha512">abc</checksum>'
            '<open-checksum type="sha512">def</open-checksum>'
            '<location href="repodata/primary.xml.gz"/>'
            "<size>1</size><open-size>2</open-size>"
            "</data></repomd>"
        )
        meta = parsers.extract_all_metadata(ET.fromstring(repomd))
        assert meta[0]["checksum_type"] == "sha512"
        assert meta[0]["open_checksum_type"] == "sha512"

    def test_primary_checksum_type_extracted(self):
        primary = (
            '<metadata xmlns="http://linux.duke.edu/metadata/common"'
            ' xmlns:rpm="http://linux.duke.edu/metadata/rpm" packages="1">'
            '<package type="rpm"><name>demo</name><arch>x86_64</arch>'
            '<version epoch="0" ver="1.0" rel="1"/>'
            '<checksum type="sha512" pkgid="YES">deadbeef</checksum>'
            "<summary>s</summary>"
            '<size package="1"/><location href="demo.rpm"/>'
            "</package></metadata>"
        )
        pkgs = parsers.parse_primary_xml(primary.encode("utf-8"))
        assert pkgs[0]["checksum_type"] == "sha512"
        assert pkgs[0]["sha256"] == "deadbeef"  # value field holds the declared checksum
