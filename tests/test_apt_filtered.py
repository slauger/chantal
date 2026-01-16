"""
Tests for APT filtered mode functionality.

This module tests the filtered mode implementation for APT repositories,
including package filtering and metadata regeneration without GPG signatures.
"""

import pytest

from chantal.core.config import (
    AptConfig,
    DebFilterConfig,
    FilterConfig,
    ListFilterConfig,
    PatternFilterConfig,
    PostProcessingConfig,
    RepositoryConfig,
)
from chantal.plugins.apt.models import DebMetadata
from chantal.plugins.apt.sync import AptSyncPlugin


@pytest.fixture
def sample_packages():
    """Create sample package metadata for testing."""
    return [
        DebMetadata(
            package="nginx",
            version="1.18.0-1",
            architecture="amd64",
            component="main",
            priority="optional",
            section="web",
            maintainer="Debian Nginx Team",
            description="High performance web server",
            filename="pool/main/n/nginx/nginx_1.18.0-1_amd64.deb",
            size=1024000,
            sha256="abc123def456",
        ),
        DebMetadata(
            package="nginx",
            version="1.20.0-1",
            architecture="amd64",
            component="main",
            priority="optional",
            section="web",
            maintainer="Debian Nginx Team",
            description="High performance web server",
            filename="pool/main/n/nginx/nginx_1.20.0-1_amd64.deb",
            size=1100000,
            sha256="def456ghi789",
        ),
        DebMetadata(
            package="apache2",
            version="2.4.48-1",
            architecture="amd64",
            component="main",
            priority="optional",
            section="web",
            maintainer="Debian Apache Team",
            description="Apache HTTP Server",
            filename="pool/main/a/apache2/apache2_2.4.48-1_amd64.deb",
            size=2048000,
            sha256="ghi789jkl012",
        ),
        DebMetadata(
            package="postgresql-14",
            version="14.1-1",
            architecture="amd64",
            component="universe",
            priority="optional",
            section="database",
            maintainer="Debian PostgreSQL Team",
            description="PostgreSQL database server",
            filename="pool/universe/p/postgresql/postgresql-14_14.1-1_amd64.deb",
            size=4096000,
            sha256="jkl012mno345",
        ),
        DebMetadata(
            package="vim",
            version="8.2.3400-1",
            architecture="amd64",
            component="main",
            priority="important",
            section="editors",
            maintainer="Debian Vim Team",
            description="Vi IMproved - enhanced vi editor",
            filename="pool/main/v/vim/vim_8.2.3400-1_amd64.deb",
            size=2500000,
            sha256="mno345pqr678",
        ),
        DebMetadata(
            package="emacs",
            version="27.1-1",
            architecture="amd64",
            component="universe",
            priority="optional",
            section="editors",
            maintainer="Debian Emacs Team",
            description="GNU Emacs editor",
            filename="pool/universe/e/emacs/emacs_27.1-1_amd64.deb",
            size=30000000,
            sha256="pqr678stu901",
        ),
    ]


class TestComponentFiltering:
    """Tests for component-based filtering."""

    def test_filter_by_component_include(self, sample_packages):
        """Test filtering packages by component inclusion."""
        config = RepositoryConfig(
            id="test-repo",
            name="Test Repo",
            type="apt",
            feed="https://example.com/repo",
            mode="filtered",
            apt=AptConfig(distribution="jammy", components=["main"], architectures=["amd64"]),
            filters=FilterConfig(
                deb=DebFilterConfig(components=ListFilterConfig(include=["main"]))
            ),
        )

        sync_plugin = AptSyncPlugin(storage=None, config=config, proxy_config=None, ssl_config=None)
        filtered = sync_plugin._apply_filters(sample_packages, config)

        # Should only include packages from 'main' component
        assert len(filtered) == 4  # nginx (2), apache2, vim
        assert all(p.component == "main" for p in filtered)

    def test_filter_by_component_exclude(self, sample_packages):
        """Test filtering packages by component exclusion."""
        config = RepositoryConfig(
            id="test-repo",
            name="Test Repo",
            type="apt",
            feed="https://example.com/repo",
            mode="filtered",
            apt=AptConfig(
                distribution="jammy",
                components=["main", "universe"],
                architectures=["amd64"],
            ),
            filters=FilterConfig(
                deb=DebFilterConfig(components=ListFilterConfig(exclude=["universe"]))
            ),
        )

        sync_plugin = AptSyncPlugin(storage=None, config=config, proxy_config=None, ssl_config=None)
        filtered = sync_plugin._apply_filters(sample_packages, config)

        # Should exclude packages from 'universe' component
        assert all(p.component != "universe" for p in filtered)
        assert len(filtered) == 4  # nginx (2), apache2, vim


class TestPriorityFiltering:
    """Tests for priority-based filtering."""

    def test_filter_by_priority_include(self, sample_packages):
        """Test filtering packages by priority inclusion."""
        config = RepositoryConfig(
            id="test-repo",
            name="Test Repo",
            type="apt",
            feed="https://example.com/repo",
            mode="filtered",
            apt=AptConfig(distribution="jammy", components=["main"], architectures=["amd64"]),
            filters=FilterConfig(
                deb=DebFilterConfig(priorities=ListFilterConfig(include=["important"]))
            ),
        )

        sync_plugin = AptSyncPlugin(storage=None, config=config, proxy_config=None, ssl_config=None)
        filtered = sync_plugin._apply_filters(sample_packages, config)

        # Should only include packages with 'important' priority
        assert len(filtered) == 1  # vim
        assert all(p.priority == "important" for p in filtered)

    def test_filter_by_priority_exclude(self, sample_packages):
        """Test filtering packages by priority exclusion."""
        config = RepositoryConfig(
            id="test-repo",
            name="Test Repo",
            type="apt",
            feed="https://example.com/repo",
            mode="filtered",
            apt=AptConfig(distribution="jammy", components=["main"], architectures=["amd64"]),
            filters=FilterConfig(
                deb=DebFilterConfig(priorities=ListFilterConfig(exclude=["optional"]))
            ),
        )

        sync_plugin = AptSyncPlugin(storage=None, config=config, proxy_config=None, ssl_config=None)
        filtered = sync_plugin._apply_filters(sample_packages, config)

        # Should exclude packages with 'optional' priority
        assert all(p.priority != "optional" for p in filtered)
        assert len(filtered) == 1  # vim (important)


class TestPatternFiltering:
    """Tests for pattern-based filtering."""

    def test_filter_by_pattern_include(self, sample_packages):
        """Test filtering packages by name pattern inclusion."""
        config = RepositoryConfig(
            id="test-repo",
            name="Test Repo",
            type="apt",
            feed="https://example.com/repo",
            mode="filtered",
            apt=AptConfig(distribution="jammy", components=["main"], architectures=["amd64"]),
            filters=FilterConfig(patterns=PatternFilterConfig(include=["^nginx.*", "^apache.*"])),
        )

        sync_plugin = AptSyncPlugin(storage=None, config=config, proxy_config=None, ssl_config=None)
        filtered = sync_plugin._apply_filters(sample_packages, config)

        # Should only include nginx and apache2
        assert len(filtered) == 3  # nginx (2 versions), apache2
        package_names = {p.package for p in filtered}
        assert package_names == {"nginx", "apache2"}

    def test_filter_by_pattern_exclude(self, sample_packages):
        """Test filtering packages by name pattern exclusion."""
        config = RepositoryConfig(
            id="test-repo",
            name="Test Repo",
            type="apt",
            feed="https://example.com/repo",
            mode="filtered",
            apt=AptConfig(distribution="jammy", components=["main"], architectures=["amd64"]),
            filters=FilterConfig(patterns=PatternFilterConfig(exclude=["^nginx$", "^emacs$"])),
        )

        sync_plugin = AptSyncPlugin(storage=None, config=config, proxy_config=None, ssl_config=None)
        filtered = sync_plugin._apply_filters(sample_packages, config)

        # Should exclude nginx and emacs
        package_names = {p.package for p in filtered}
        assert "nginx" not in package_names
        assert "emacs" not in package_names
        assert len(filtered) == 3  # apache2, postgresql-14, vim


class TestPostProcessingFiltering:
    """Tests for post-processing filters."""

    def test_only_latest_version(self, sample_packages):
        """Test keeping only latest version of each package."""
        config = RepositoryConfig(
            id="test-repo",
            name="Test Repo",
            type="apt",
            feed="https://example.com/repo",
            mode="filtered",
            apt=AptConfig(distribution="jammy", components=["main"], architectures=["amd64"]),
            filters=FilterConfig(post_processing=PostProcessingConfig(only_latest_version=True)),
        )

        sync_plugin = AptSyncPlugin(storage=None, config=config, proxy_config=None, ssl_config=None)
        filtered = sync_plugin._apply_filters(sample_packages, config)

        # Should keep only 1 nginx (latest version 1.20.0-1)
        nginx_packages = [p for p in filtered if p.package == "nginx"]
        assert len(nginx_packages) == 1
        assert nginx_packages[0].version == "1.20.0-1"

        # Each package should appear only once
        package_counts = {}
        for pkg in filtered:
            key = (pkg.package, pkg.architecture)
            package_counts[key] = package_counts.get(key, 0) + 1

        assert all(count == 1 for count in package_counts.values())


class TestCombinedFiltering:
    """Tests for combined filtering scenarios."""

    def test_component_and_pattern_combined(self, sample_packages):
        """Test combining component and pattern filters."""
        config = RepositoryConfig(
            id="test-repo",
            name="Test Repo",
            type="apt",
            feed="https://example.com/repo",
            mode="filtered",
            apt=AptConfig(
                distribution="jammy",
                components=["main", "universe"],
                architectures=["amd64"],
            ),
            filters=FilterConfig(
                deb=DebFilterConfig(components=ListFilterConfig(include=["main"])),
                patterns=PatternFilterConfig(include=["^nginx$", "^vim$"]),
            ),
        )

        sync_plugin = AptSyncPlugin(storage=None, config=config, proxy_config=None, ssl_config=None)
        filtered = sync_plugin._apply_filters(sample_packages, config)

        # Should include only nginx and vim from main component
        assert len(filtered) == 3  # nginx (2 versions), vim
        assert all(p.component == "main" for p in filtered)
        package_names = {p.package for p in filtered}
        assert package_names == {"nginx", "vim"}

    def test_pattern_and_latest_version_combined(self, sample_packages):
        """Test combining pattern filtering with only_latest_version."""
        config = RepositoryConfig(
            id="test-repo",
            name="Test Repo",
            type="apt",
            feed="https://example.com/repo",
            mode="filtered",
            apt=AptConfig(distribution="jammy", components=["main"], architectures=["amd64"]),
            filters=FilterConfig(
                patterns=PatternFilterConfig(include=["^nginx$", "^apache.*"]),
                post_processing=PostProcessingConfig(only_latest_version=True),
            ),
        )

        sync_plugin = AptSyncPlugin(storage=None, config=config, proxy_config=None, ssl_config=None)
        filtered = sync_plugin._apply_filters(sample_packages, config)

        # Should include latest nginx and apache2
        assert len(filtered) == 2  # nginx 1.20.0-1, apache2
        package_names = {p.package for p in filtered}
        assert package_names == {"nginx", "apache2"}

        # Verify nginx is latest version
        nginx_pkg = next(p for p in filtered if p.package == "nginx")
        assert nginx_pkg.version == "1.20.0-1"


class TestNoFiltering:
    """Tests for repositories without filters (passthrough)."""

    def test_no_filters_passthrough(self, sample_packages):
        """Test that packages pass through unchanged when no filters configured."""
        config = RepositoryConfig(
            id="test-repo",
            name="Test Repo",
            type="apt",
            feed="https://example.com/repo",
            mode="filtered",
            apt=AptConfig(distribution="jammy", components=["main"], architectures=["amd64"]),
            filters=None,  # No filters
        )

        sync_plugin = AptSyncPlugin(storage=None, config=config, proxy_config=None, ssl_config=None)
        filtered = sync_plugin._apply_filters(sample_packages, config)

        # Should return all packages unchanged
        assert len(filtered) == len(sample_packages)
        assert filtered == sample_packages
