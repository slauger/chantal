from __future__ import annotations

"""
Tests for APT plugin Pydantic models.
"""

import pytest
from pydantic import ValidationError

from chantal.plugins.apt.models import DebMetadata, ReleaseMetadata, SourcesMetadata


class TestDebMetadata:
    """Tests for DebMetadata model."""

    def test_minimal_valid_package(self):
        """Test creating package with minimal required fields."""
        pkg = DebMetadata(
            package="nginx",
            version="1.18.0-0ubuntu1",
            architecture="amd64",
            filename="pool/main/n/nginx/nginx_1.18.0-0ubuntu1_amd64.deb",
            size=354232,
            sha256="5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f",
        )

        assert pkg.package == "nginx"
        assert pkg.version == "1.18.0-0ubuntu1"
        assert pkg.architecture == "amd64"
        assert pkg.size == 354232
        assert pkg.sha256 == "5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f"
        assert pkg.description is None
        assert pkg.depends is None

    def test_package_with_all_fields(self):
        """Test creating package with all optional fields."""
        pkg = DebMetadata(
            package="python3",
            version="3.10.6-1",
            architecture="amd64",
            filename="pool/main/p/python3/python3_3.10.6-1_amd64.deb",
            size=25432,
            sha256="abc123def456",
            description="Python interactive high-level object-oriented language",
            long_description="Python is a high-level, interactive...",
            section="python",
            priority="optional",
            homepage="https://www.python.org/",
            depends="python3.10 (>= 3.10.6-1~), python3-minimal (= 3.10.6-1)",
            recommends="python3-pip, python3-setuptools",
            suggests="python3-doc",
            maintainer="Ubuntu Developers <ubuntu-devel-discuss@lists.ubuntu.com>",
            installed_size=120,
            md5sum="abc123",
            sha1="def456",
        )

        assert pkg.package == "python3"
        assert pkg.section == "python"
        assert pkg.priority == "optional"
        assert pkg.homepage == "https://www.python.org/"
        assert pkg.depends == "python3.10 (>= 3.10.6-1~), python3-minimal (= 3.10.6-1)"
        assert pkg.recommends == "python3-pip, python3-setuptools"
        assert pkg.suggests == "python3-doc"
        assert pkg.installed_size == 120

    def test_package_with_extra_fields(self):
        """Test that extra fields are stored in extra_fields dict."""
        pkg = DebMetadata(
            package="test",
            version="1.0",
            architecture="all",
            filename="pool/test_1.0_all.deb",
            size=1024,
            sha256="abc123",
            extra_fields={"Custom-Field": "custom-value", "Another-Field": "value2"},
        )

        assert pkg.extra_fields == {"Custom-Field": "custom-value", "Another-Field": "value2"}

    def test_missing_required_fields(self):
        """Test that missing required fields raise ValidationError."""
        with pytest.raises(ValidationError):
            DebMetadata(
                package="test",
                version="1.0",
                # Missing architecture, filename, size, sha256
            )

    def test_invalid_size_type(self):
        """Test that invalid size type raises ValidationError."""
        with pytest.raises(ValidationError):
            DebMetadata(
                package="test",
                version="1.0",
                architecture="amd64",
                filename="pool/test.deb",
                size="not-a-number",  # Should be int
                sha256="abc123",
            )

    def test_multi_arch_field(self):
        """Test multi-arch field handling."""
        pkg = DebMetadata(
            package="libtest",
            version="1.0",
            architecture="amd64",
            filename="pool/libtest_1.0_amd64.deb",
            size=1024,
            sha256="abc123",
            multi_arch="same",
        )

        assert pkg.multi_arch == "same"

    def test_dependency_fields(self):
        """Test all dependency field types."""
        pkg = DebMetadata(
            package="complex-package",
            version="2.0",
            architecture="amd64",
            filename="pool/complex.deb",
            size=2048,
            sha256="def456",
            depends="libc6 (>= 2.27)",
            pre_depends="dpkg (>= 1.15.6)",
            recommends="ca-certificates",
            suggests="python3-doc",
            enhances="python3",
            breaks="old-package (<< 1.0)",
            conflicts="other-package",
            replaces="obsolete-package",
            provides="virtual-package",
        )

        assert pkg.depends == "libc6 (>= 2.27)"
        assert pkg.pre_depends == "dpkg (>= 1.15.6)"
        assert pkg.recommends == "ca-certificates"
        assert pkg.breaks == "old-package (<< 1.0)"
        assert pkg.provides == "virtual-package"


class TestReleaseMetadata:
    """Tests for ReleaseMetadata model."""

    def test_minimal_release(self):
        """Test creating Release with minimal fields."""
        release = ReleaseMetadata(
            suite="jammy",
            codename="jammy",
            architectures=["amd64", "arm64"],
            components=["main", "restricted", "universe"],
        )

        assert release.suite == "jammy"
        assert release.codename == "jammy"
        assert release.architectures == ["amd64", "arm64"]
        assert release.components == ["main", "restricted", "universe"]
        assert release.origin is None
        assert release.acquire_by_hash is False

    def test_full_release(self):
        """Test creating Release with all fields."""
        release = ReleaseMetadata(
            suite="jammy",
            codename="jammy",
            architectures=["amd64", "arm64", "i386"],
            components=["main", "restricted", "universe", "multiverse"],
            origin="Ubuntu",
            label="Ubuntu",
            version="22.04",
            description="Ubuntu Jammy 22.04 LTS",
            date="Thu, 21 Apr 2022 17:00:00 UTC",
            valid_until="Thu, 21 Apr 2024 17:00:00 UTC",
            acquire_by_hash=True,
            sha256={
                "main/binary-amd64/Packages.gz": ("abc123", 12345),
                "main/binary-amd64/Release": ("def456", 678),
            },
        )

        assert release.origin == "Ubuntu"
        assert release.version == "22.04"
        assert release.description == "Ubuntu Jammy 22.04 LTS"
        assert release.acquire_by_hash is True
        assert "main/binary-amd64/Packages.gz" in release.sha256
        assert release.sha256["main/binary-amd64/Packages.gz"] == ("abc123", 12345)

    def test_checksum_parsing(self):
        """Test checksum dictionary structure."""
        release = ReleaseMetadata(
            suite="bookworm",
            codename="bookworm",
            architectures=["amd64"],
            components=["main"],
            md5sum={"Packages": ("md5hash", 1000)},
            sha1={"Packages": ("sha1hash", 1000)},
            sha256={"Packages": ("sha256hash", 1000)},
        )

        assert release.md5sum["Packages"] == ("md5hash", 1000)
        assert release.sha1["Packages"] == ("sha1hash", 1000)
        assert release.sha256["Packages"] == ("sha256hash", 1000)

    def test_empty_release(self):
        """Test that Release can be created with empty optional fields."""
        release = ReleaseMetadata()

        assert release.suite is None
        assert release.architectures == []
        assert release.components == []
        assert release.sha256 == {}

    def test_debian_release(self):
        """Test Debian-style Release metadata."""
        release = ReleaseMetadata(
            suite="stable",
            codename="bookworm",
            architectures=["amd64", "arm64", "armhf"],
            components=["main", "contrib", "non-free"],
            origin="Debian",
            label="Debian",
            version="12.0",
        )

        assert release.suite == "stable"
        assert release.codename == "bookworm"
        assert "contrib" in release.components
        assert "non-free" in release.components
        assert release.origin == "Debian"


class TestSourcesMetadata:
    """Tests for SourcesMetadata model."""

    def test_minimal_source(self):
        """Test creating source package with minimal fields."""
        src = SourcesMetadata(
            package="nginx",
            version="1.18.0-0ubuntu1",
        )

        assert src.package == "nginx"
        assert src.version == "1.18.0-0ubuntu1"
        assert src.binary == []
        assert src.files == []

    def test_full_source(self):
        """Test creating source package with all fields."""
        src = SourcesMetadata(
            package="python3-defaults",
            version="3.10.6-1",
            binary=["python3", "python3-minimal", "python3-dev"],
            architecture="all",
            maintainer="Ubuntu Developers <ubuntu-devel@lists.ubuntu.com>",
            uploaders=["Matthias Klose <doko@debian.org>"],
            homepage="https://www.python.org/",
            section="python",
            priority="optional",
            build_depends="debhelper (>= 11), python3.10",
            vcs_browser="https://salsa.debian.org/cpython-team/python3-defaults",
            vcs_git="https://salsa.debian.org/cpython-team/python3-defaults.git",
            directory="pool/main/p/python3-defaults",
            files=[
                {"checksum": "abc123", "size": "1234", "filename": "python3-defaults_3.10.6-1.dsc"},
                {
                    "checksum": "def456",
                    "size": "5678",
                    "filename": "python3-defaults_3.10.6.orig.tar.gz",
                },
            ],
            checksums_sha256=[
                {
                    "checksum": "sha256abc",
                    "size": "1234",
                    "filename": "python3-defaults_3.10.6-1.dsc",
                },
            ],
        )

        assert src.package == "python3-defaults"
        assert src.binary == ["python3", "python3-minimal", "python3-dev"]
        assert src.maintainer == "Ubuntu Developers <ubuntu-devel@lists.ubuntu.com>"
        assert src.uploaders == ["Matthias Klose <doko@debian.org>"]
        assert src.build_depends == "debhelper (>= 11), python3.10"
        assert src.vcs_git == "https://salsa.debian.org/cpython-team/python3-defaults.git"
        assert len(src.files) == 2
        assert src.files[0]["filename"] == "python3-defaults_3.10.6-1.dsc"

    def test_source_with_vcs_fields(self):
        """Test source package with VCS fields."""
        src = SourcesMetadata(
            package="test-package",
            version="1.0",
            vcs_browser="https://github.com/example/test",
            vcs_git="https://github.com/example/test.git",
            vcs_svn="https://svn.example.com/test",
            vcs_bzr="https://bazaar.example.com/test",
        )

        assert src.vcs_browser == "https://github.com/example/test"
        assert src.vcs_git == "https://github.com/example/test.git"
        assert src.vcs_svn == "https://svn.example.com/test"
        assert src.vcs_bzr == "https://bazaar.example.com/test"

    def test_source_build_dependencies(self):
        """Test source package build dependencies."""
        src = SourcesMetadata(
            package="complex-build",
            version="2.0",
            build_depends="debhelper (>= 11), gcc, make",
            build_depends_indep="python3-sphinx, doxygen",
            build_conflicts="autoconf2.13",
            build_conflicts_indep="python-sphinx (<< 1.0)",
        )

        assert src.build_depends == "debhelper (>= 11), gcc, make"
        assert src.build_depends_indep == "python3-sphinx, doxygen"
        assert src.build_conflicts == "autoconf2.13"
        assert src.build_conflicts_indep == "python-sphinx (<< 1.0)"

    def test_missing_required_fields(self):
        """Test that missing required fields raise ValidationError."""
        with pytest.raises(ValidationError):
            SourcesMetadata(
                package="test",
                # Missing version
            )


class TestAptConfig:
    """Tests for AptConfig model."""

    def test_minimal_apt_config(self):
        """Test creating AptConfig with minimal fields."""
        from chantal.core.config import AptConfig

        config = AptConfig(distribution="jammy")

        assert config.distribution == "jammy"
        assert config.components == ["main"]
        assert config.architectures == ["amd64"]
        assert config.include_source_packages is False

    def test_full_apt_config(self):
        """Test creating AptConfig with all fields."""
        from chantal.core.config import AptConfig

        config = AptConfig(
            distribution="jammy",
            components=["main", "restricted", "universe", "multiverse"],
            architectures=["amd64", "arm64", "i386"],
            include_source_packages=True,
        )

        assert config.distribution == "jammy"
        assert config.components == ["main", "restricted", "universe", "multiverse"]
        assert config.architectures == ["amd64", "arm64", "i386"]
        assert config.include_source_packages is True

    def test_debian_apt_config(self):
        """Test Debian-style AptConfig."""
        from chantal.core.config import AptConfig

        config = AptConfig(
            distribution="bookworm",
            components=["main", "contrib", "non-free"],
            architectures=["amd64", "armhf"],
        )

        assert config.distribution == "bookworm"
        assert "contrib" in config.components
        assert "non-free" in config.components
