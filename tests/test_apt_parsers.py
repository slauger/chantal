from __future__ import annotations

"""
Tests for APT plugin parsers.
"""

import gzip
import tempfile
from pathlib import Path

from chantal.plugins.apt.parsers import (
    parse_packages_file,
    parse_packages_from_bytes,
    parse_packages_gz,
    parse_release_file,
    parse_rfc822_file,
    parse_rfc822_stanza,
    parse_sources_file,
    parse_sources_gz,
)


class TestRFC822Parsing:
    """Tests for RFC822 stanza parsing."""

    def test_simple_stanza(self):
        """Test parsing simple RFC822 stanza."""
        stanza_text = """Package: nginx
Version: 1.18.0
Architecture: amd64"""

        result = parse_rfc822_stanza(stanza_text)

        assert result["Package"] == "nginx"
        assert result["Version"] == "1.18.0"
        assert result["Architecture"] == "amd64"

    def test_multiline_field(self):
        """Test parsing multi-line field (continuation with space)."""
        stanza_text = """Package: python3
Description: Python programming language
 Python is an interpreted, interactive, object-oriented programming
 language. It incorporates modules, exceptions, dynamic typing, very
 high level dynamic data types, and classes."""

        result = parse_rfc822_stanza(stanza_text)

        assert result["Package"] == "python3"
        assert "Python is an interpreted" in result["Description"]
        assert "high level dynamic data types" in result["Description"]
        # Multi-line values are joined with newlines
        assert "\n" in result["Description"]

    def test_paragraph_separator(self):
        """Test that '.' is treated as paragraph separator in descriptions."""
        stanza_text = """Package: test
Description: First paragraph
 .
 Second paragraph"""

        result = parse_rfc822_stanza(stanza_text)

        assert "First paragraph\n\nSecond paragraph" == result["Description"]

    def test_empty_field_value(self):
        """Test field with empty value."""
        stanza_text = """Package: test
EmptyField:
Version: 1.0"""

        result = parse_rfc822_stanza(stanza_text)

        assert result["Package"] == "test"
        assert result["EmptyField"] == ""
        assert result["Version"] == "1.0"

    def test_multiple_stanzas(self):
        """Test parsing multiple stanzas separated by blank lines."""
        content = """Package: nginx
Version: 1.18.0

Package: apache2
Version: 2.4.41"""

        stanzas = list(parse_rfc822_file(content))

        assert len(stanzas) == 2
        assert stanzas[0]["Package"] == "nginx"
        assert stanzas[1]["Package"] == "apache2"

    def test_empty_stanzas_ignored(self):
        """Test that empty stanzas are ignored."""
        content = """Package: test1
Version: 1.0


Package: test2
Version: 2.0

"""

        stanzas = list(parse_rfc822_file(content))

        # Should only get 2 stanzas, empty ones ignored
        assert len(stanzas) == 2


class TestPackagesFileParsing:
    """Tests for Packages file parsing."""

    def test_minimal_package(self):
        """Test parsing package with minimal required fields."""
        content = """Package: nginx
Version: 1.18.0-0ubuntu1
Architecture: amd64
Filename: pool/main/n/nginx/nginx_1.18.0-0ubuntu1_amd64.deb
Size: 354232
SHA256: 5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f"""

        packages = parse_packages_file(content)

        assert len(packages) == 1
        pkg = packages[0]
        assert pkg.package == "nginx"
        assert pkg.version == "1.18.0-0ubuntu1"
        assert pkg.architecture == "amd64"
        assert pkg.filename == "pool/main/n/nginx/nginx_1.18.0-0ubuntu1_amd64.deb"
        assert pkg.size == 354232
        assert pkg.sha256 == "5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f"

    def test_full_package(self):
        """Test parsing package with many optional fields."""
        content = """Package: python3
Version: 3.10.6-1
Architecture: amd64
Filename: pool/main/p/python3/python3_3.10.6-1_amd64.deb
Size: 25432
SHA256: abc123def456
Section: python
Priority: optional
Homepage: https://www.python.org/
Maintainer: Ubuntu Developers <ubuntu-devel-discuss@lists.ubuntu.com>
Depends: python3.10 (>= 3.10.6-1~), python3-minimal (= 3.10.6-1)
Recommends: python3-pip
Suggests: python3-doc
Installed-Size: 120
Description: Python programming language
 Python is a high-level, interactive, object-oriented programming language."""

        packages = parse_packages_file(content)

        assert len(packages) == 1
        pkg = packages[0]
        assert pkg.package == "python3"
        assert pkg.section == "python"
        assert pkg.priority == "optional"
        assert pkg.homepage == "https://www.python.org/"
        assert pkg.depends == "python3.10 (>= 3.10.6-1~), python3-minimal (= 3.10.6-1)"
        assert pkg.recommends == "python3-pip"
        assert pkg.suggests == "python3-doc"
        assert pkg.installed_size == 120
        assert "Python is a high-level" in pkg.long_description

    def test_multiple_packages(self):
        """Test parsing multiple packages."""
        content = """Package: nginx
Version: 1.18.0
Architecture: amd64
Filename: pool/nginx_1.18.0_amd64.deb
Size: 100000
SHA256: abc123

Package: apache2
Version: 2.4.41
Architecture: amd64
Filename: pool/apache2_2.4.41_amd64.deb
Size: 200000
SHA256: def456"""

        packages = parse_packages_file(content)

        assert len(packages) == 2
        assert packages[0].package == "nginx"
        assert packages[1].package == "apache2"

    def test_incomplete_package_skipped(self):
        """Test that incomplete packages are skipped with warning."""
        content = """Package: incomplete
Version: 1.0
Architecture: amd64
# Missing Filename, Size, SHA256

Package: complete
Version: 2.0
Architecture: amd64
Filename: pool/complete.deb
Size: 1024
SHA256: abc123"""

        packages = parse_packages_file(content)

        # Should only get the complete package
        assert len(packages) == 1
        assert packages[0].package == "complete"

    def test_invalid_size_skipped(self):
        """Test that packages with invalid size are skipped."""
        content = """Package: bad-size
Version: 1.0
Architecture: amd64
Filename: pool/bad.deb
Size: not-a-number
SHA256: abc123

Package: good-size
Version: 1.0
Architecture: amd64
Filename: pool/good.deb
Size: 1024
SHA256: def456"""

        packages = parse_packages_file(content)

        assert len(packages) == 1
        assert packages[0].package == "good-size"

    def test_description_parsing(self):
        """Test that short and long descriptions are separated."""
        content = """Package: test
Version: 1.0
Architecture: all
Filename: pool/test.deb
Size: 1024
SHA256: abc123
Description: Short description here
 This is the long description.
 It spans multiple lines.
 Each line is indented."""

        packages = parse_packages_file(content)

        pkg = packages[0]
        assert pkg.description == "Short description here"
        assert "This is the long description." in pkg.long_description
        assert "It spans multiple lines." in pkg.long_description

    def test_extra_fields_captured(self):
        """Test that unknown fields are captured in extra_fields."""
        content = """Package: test
Version: 1.0
Architecture: all
Filename: pool/test.deb
Size: 1024
SHA256: abc123
Custom-Field: custom-value
Another-Field: another-value"""

        packages = parse_packages_file(content)

        pkg = packages[0]
        assert "Custom-Field" in pkg.extra_fields
        assert pkg.extra_fields["Custom-Field"] == "custom-value"
        assert pkg.extra_fields["Another-Field"] == "another-value"

    def test_compressed_packages_gz(self):
        """Test parsing gzip-compressed Packages file."""
        content = """Package: nginx
Version: 1.18.0
Architecture: amd64
Filename: pool/nginx.deb
Size: 100000
SHA256: abc123"""

        # Create temporary compressed file
        with tempfile.NamedTemporaryFile(suffix=".gz", delete=False) as tmp:
            with gzip.open(tmp.name, "wt", encoding="utf-8") as gz:
                gz.write(content)
            tmp_path = Path(tmp.name)

        try:
            packages = parse_packages_gz(tmp_path)
            assert len(packages) == 1
            assert packages[0].package == "nginx"
        finally:
            tmp_path.unlink()

    def test_parse_packages_from_bytes(self):
        """Test parsing Packages from bytes (uncompressed)."""
        content = """Package: test
Version: 1.0
Architecture: all
Filename: pool/test.deb
Size: 1024
SHA256: abc123"""

        packages = parse_packages_from_bytes(content.encode("utf-8"), compressed=False)

        assert len(packages) == 1
        assert packages[0].package == "test"

    def test_parse_packages_from_bytes_compressed(self):
        """Test parsing Packages from compressed bytes."""
        content = """Package: test
Version: 1.0
Architecture: all
Filename: pool/test.deb
Size: 1024
SHA256: abc123"""

        # Compress content
        import io

        buf = io.BytesIO()
        with gzip.open(buf, "wt", encoding="utf-8") as gz:
            gz.write(content)
        compressed_data = buf.getvalue()

        packages = parse_packages_from_bytes(compressed_data, compressed=True)

        assert len(packages) == 1
        assert packages[0].package == "test"


class TestReleaseFileParsing:
    """Tests for Release file parsing."""

    def test_minimal_release(self):
        """Test parsing minimal Release file."""
        content = """Suite: jammy
Codename: jammy
Architectures: amd64 arm64
Components: main restricted universe multiverse"""

        release = parse_release_file(content)

        assert release.suite == "jammy"
        assert release.codename == "jammy"
        assert release.architectures == ["amd64", "arm64"]
        assert release.components == ["main", "restricted", "universe", "multiverse"]

    def test_full_release(self):
        """Test parsing full Release file with all fields."""
        content = """Origin: Ubuntu
Label: Ubuntu
Suite: jammy
Codename: jammy
Version: 22.04
Date: Thu, 21 Apr 2022 17:00:00 UTC
Valid-Until: Thu, 21 Apr 2024 17:00:00 UTC
Architectures: amd64 arm64 i386
Components: main restricted universe multiverse
Description: Ubuntu Jammy 22.04 LTS
Acquire-By-Hash: yes"""

        release = parse_release_file(content)

        assert release.origin == "Ubuntu"
        assert release.label == "Ubuntu"
        assert release.version == "22.04"
        assert release.date == "Thu, 21 Apr 2022 17:00:00 UTC"
        assert release.valid_until == "Thu, 21 Apr 2024 17:00:00 UTC"
        assert release.description == "Ubuntu Jammy 22.04 LTS"
        assert release.acquire_by_hash is True

    def test_checksum_parsing(self):
        """Test parsing checksum blocks in Release file."""
        content = """Suite: jammy
Codename: jammy
Architectures: amd64
Components: main
MD5Sum:
 abc123 12345 main/binary-amd64/Packages
 def456 67890 main/binary-amd64/Packages.gz
SHA1:
 sha1abc 12345 main/binary-amd64/Packages
 sha1def 67890 main/binary-amd64/Packages.gz
SHA256:
 sha256abc 12345 main/binary-amd64/Packages
 sha256def 67890 main/binary-amd64/Packages.gz"""

        release = parse_release_file(content)

        # Check MD5Sum
        assert "main/binary-amd64/Packages" in release.md5sum
        assert release.md5sum["main/binary-amd64/Packages"] == ("abc123", 12345)
        assert release.md5sum["main/binary-amd64/Packages.gz"] == ("def456", 67890)

        # Check SHA1
        assert "main/binary-amd64/Packages" in release.sha1
        assert release.sha1["main/binary-amd64/Packages"] == ("sha1abc", 12345)

        # Check SHA256
        assert "main/binary-amd64/Packages" in release.sha256
        assert release.sha256["main/binary-amd64/Packages"] == ("sha256abc", 12345)

    def test_debian_release(self):
        """Test parsing Debian-style Release file."""
        content = """Origin: Debian
Label: Debian
Suite: stable
Codename: bookworm
Version: 12.0
Architectures: amd64 arm64 armhf
Components: main contrib non-free"""

        release = parse_release_file(content)

        assert release.origin == "Debian"
        assert release.suite == "stable"
        assert release.codename == "bookworm"
        assert "contrib" in release.components
        assert "non-free" in release.components

    def test_acquire_by_hash_no(self):
        """Test that Acquire-By-Hash defaults to False."""
        content = """Suite: jammy
Codename: jammy
Architectures: amd64
Components: main
Acquire-By-Hash: no"""

        release = parse_release_file(content)

        assert release.acquire_by_hash is False

    def test_acquire_by_hash_missing(self):
        """Test that missing Acquire-By-Hash defaults to False."""
        content = """Suite: jammy
Codename: jammy
Architectures: amd64
Components: main"""

        release = parse_release_file(content)

        assert release.acquire_by_hash is False


class TestSourcesFileParsing:
    """Tests for Sources file parsing."""

    def test_minimal_source(self):
        """Test parsing source with minimal fields."""
        content = """Package: nginx
Version: 1.18.0-0ubuntu1"""

        sources = parse_sources_file(content)

        assert len(sources) == 1
        src = sources[0]
        assert src.package == "nginx"
        assert src.version == "1.18.0-0ubuntu1"

    def test_full_source(self):
        """Test parsing source with all fields."""
        content = """Package: python3-defaults
Version: 3.10.6-1
Binary: python3, python3-minimal, python3-dev
Architecture: all
Maintainer: Ubuntu Developers <ubuntu-devel@lists.ubuntu.com>
Uploaders: Matthias Klose <doko@debian.org>, Scott Kitterman <scott@kitterman.com>
Homepage: https://www.python.org/
Section: python
Priority: optional
Build-Depends: debhelper (>= 11), python3.10
Build-Depends-Indep: python3-sphinx
Vcs-Browser: https://salsa.debian.org/cpython-team/python3-defaults
Vcs-Git: https://salsa.debian.org/cpython-team/python3-defaults.git
Directory: pool/main/p/python3-defaults
Files:
 abc123 1234 python3-defaults_3.10.6-1.dsc
 def456 5678 python3-defaults_3.10.6.orig.tar.gz
Checksums-Sha256:
 sha256abc 1234 python3-defaults_3.10.6-1.dsc
 sha256def 5678 python3-defaults_3.10.6.orig.tar.gz"""

        sources = parse_sources_file(content)

        assert len(sources) == 1
        src = sources[0]
        assert src.package == "python3-defaults"
        assert src.version == "3.10.6-1"
        assert src.binary == ["python3", "python3-minimal", "python3-dev"]
        assert src.maintainer == "Ubuntu Developers <ubuntu-devel@lists.ubuntu.com>"
        assert len(src.uploaders) == 2
        assert "Matthias Klose" in src.uploaders[0]
        assert src.homepage == "https://www.python.org/"
        assert src.build_depends == "debhelper (>= 11), python3.10"
        assert src.vcs_git == "https://salsa.debian.org/cpython-team/python3-defaults.git"
        assert len(src.files) == 2
        assert src.files[0]["filename"] == "python3-defaults_3.10.6-1.dsc"

    def test_multiple_sources(self):
        """Test parsing multiple source packages."""
        content = """Package: nginx
Version: 1.18.0

Package: apache2
Version: 2.4.41"""

        sources = parse_sources_file(content)

        assert len(sources) == 2
        assert sources[0].package == "nginx"
        assert sources[1].package == "apache2"

    def test_incomplete_source_skipped(self):
        """Test that incomplete sources are skipped."""
        content = """Package: incomplete
# Missing Version

Package: complete
Version: 1.0"""

        sources = parse_sources_file(content)

        assert len(sources) == 1
        assert sources[0].package == "complete"

    def test_binary_parsing(self):
        """Test parsing Binary field (comma and space separated)."""
        content = """Package: test
Version: 1.0
Binary: pkg1, pkg2, pkg3"""

        sources = parse_sources_file(content)

        src = sources[0]
        assert src.binary == ["pkg1", "pkg2", "pkg3"]

    def test_vcs_fields(self):
        """Test parsing VCS fields."""
        content = """Package: test
Version: 1.0
Vcs-Browser: https://github.com/example/test
Vcs-Git: https://github.com/example/test.git
Vcs-Svn: https://svn.example.com/test
Vcs-Bzr: https://bazaar.example.com/test"""

        sources = parse_sources_file(content)

        src = sources[0]
        assert src.vcs_browser == "https://github.com/example/test"
        assert src.vcs_git == "https://github.com/example/test.git"
        assert src.vcs_svn == "https://svn.example.com/test"
        assert src.vcs_bzr == "https://bazaar.example.com/test"

    def test_compressed_sources_gz(self):
        """Test parsing gzip-compressed Sources file."""
        content = """Package: nginx
Version: 1.18.0"""

        # Create temporary compressed file
        with tempfile.NamedTemporaryFile(suffix=".gz", delete=False) as tmp:
            with gzip.open(tmp.name, "wt", encoding="utf-8") as gz:
                gz.write(content)
            tmp_path = Path(tmp.name)

        try:
            sources = parse_sources_gz(tmp_path)
            assert len(sources) == 1
            assert sources[0].package == "nginx"
        finally:
            tmp_path.unlink()
