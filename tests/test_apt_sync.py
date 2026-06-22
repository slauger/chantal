"""
Tests for APT sync plugin.

This module tests the AptSyncPlugin implementation, focusing on Release file
parsing and metadata file list building.
"""

from chantal.plugins.apt.sync import AptSyncPlugin, MetadataFileInfo


class TestReleaseFileParsing:
    """Tests for Release file parsing and metadata discovery."""

    def test_build_metadata_file_list_simple(self):
        """Test building metadata file list from simple Release file."""
        # Simulate Release metadata with SHA256 section
        # Format: {"path": (checksum, size)}
        release_metadata = {
            "suite": "jammy",
            "components": ["main"],
            "architectures": ["amd64"],
            "sha256": {
                "main/binary-amd64/Packages.gz": ("abc123def456", 1234567),
                "main/binary-amd64/Packages": ("def456ghi789", 234567),
            },
        }

        # Create sync plugin with mock config
        from chantal.core.config import AptConfig, RepositoryConfig

        repo_config = RepositoryConfig(
            id="test-repo",
            name="Test Repo",
            type="apt",
            feed="https://example.com/repo",
            mode="mirror",
            apt=AptConfig(distribution="jammy", components=["main"], architectures=["amd64"]),
        )

        # Build metadata file list
        sync_plugin = AptSyncPlugin(
            storage=None, config=repo_config, proxy_config=None, ssl_config=None
        )
        metadata_files = sync_plugin._build_metadata_file_list(release_metadata)

        # Should get Packages.gz file
        packages_files = [f for f in metadata_files if f.file_type == "Packages"]
        assert len(packages_files) == 1
        assert packages_files[0].relative_path == "main/binary-amd64/Packages.gz"
        assert packages_files[0].checksum == "abc123def456"
        assert packages_files[0].size == 1234567
        assert packages_files[0].component == "main"
        assert packages_files[0].architecture == "amd64"

    def test_build_metadata_file_list_multi_component(self):
        """Test building metadata file list with multiple components."""
        release_metadata = {
            "suite": "jammy",
            "components": ["main", "universe"],
            "architectures": ["amd64"],
            "sha256": {
                "main/binary-amd64/Packages.gz": ("abc123", 1000),
                "universe/binary-amd64/Packages.gz": ("def456", 2000),
            },
        }

        from chantal.core.config import AptConfig, RepositoryConfig

        repo_config = RepositoryConfig(
            id="test-repo",
            name="Test Repo",
            type="apt",
            feed="https://example.com/repo",
            mode="mirror",
            apt=AptConfig(
                distribution="jammy",
                components=["main", "universe"],
                architectures=["amd64"],
            ),
        )

        sync_plugin = AptSyncPlugin(
            storage=None, config=repo_config, proxy_config=None, ssl_config=None
        )
        metadata_files = sync_plugin._build_metadata_file_list(release_metadata)

        # Should get 2 Packages files (main + universe)
        packages_files = [f for f in metadata_files if f.file_type == "Packages"]
        assert len(packages_files) == 2

        components = {f.component for f in packages_files}
        assert components == {"main", "universe"}

    def test_build_metadata_file_list_multi_arch(self):
        """Test building metadata file list with multiple architectures."""
        release_metadata = {
            "suite": "jammy",
            "components": ["main"],
            "architectures": ["amd64", "arm64"],
            "sha256": {
                "main/binary-amd64/Packages.gz": ("abc123", 1000),
                "main/binary-arm64/Packages.gz": ("def456", 2000),
            },
        }

        from chantal.core.config import AptConfig, RepositoryConfig

        repo_config = RepositoryConfig(
            id="test-repo",
            name="Test Repo",
            type="apt",
            feed="https://example.com/repo",
            mode="mirror",
            apt=AptConfig(
                distribution="jammy", components=["main"], architectures=["amd64", "arm64"]
            ),
        )

        sync_plugin = AptSyncPlugin(
            storage=None, config=repo_config, proxy_config=None, ssl_config=None
        )
        metadata_files = sync_plugin._build_metadata_file_list(release_metadata)

        # Should get 2 Packages files (amd64 + arm64)
        packages_files = [f for f in metadata_files if f.file_type == "Packages"]
        assert len(packages_files) == 2

        architectures = {f.architecture for f in packages_files}
        assert architectures == {"amd64", "arm64"}

    def test_build_metadata_file_list_source_packages(self):
        """Test building metadata file list with source packages."""
        release_metadata = {
            "suite": "jammy",
            "components": ["main"],
            "architectures": ["amd64"],
            "sha256": {
                "main/binary-amd64/Packages.gz": ("abc123", 1000),
                "main/source/Sources.gz": ("def456", 2000),
            },
        }

        from chantal.core.config import AptConfig, RepositoryConfig

        repo_config = RepositoryConfig(
            id="test-repo",
            name="Test Repo",
            type="apt",
            feed="https://example.com/repo",
            mode="mirror",
            apt=AptConfig(
                distribution="jammy",
                components=["main"],
                architectures=["amd64"],
                include_source_packages=True,
            ),
        )

        sync_plugin = AptSyncPlugin(
            storage=None, config=repo_config, proxy_config=None, ssl_config=None
        )
        metadata_files = sync_plugin._build_metadata_file_list(release_metadata)

        # Should get Packages + Sources files
        assert len(metadata_files) >= 2

        file_types = {f.file_type for f in metadata_files}
        assert "Packages" in file_types
        assert "Sources" in file_types

    def test_build_metadata_file_list_filters_by_config(self):
        """Test that metadata file list is filtered by repository config."""
        # Release has main + universe, but config only wants main
        release_metadata = {
            "suite": "jammy",
            "components": ["main", "universe"],
            "architectures": ["amd64", "arm64"],
            "sha256": {
                "main/binary-amd64/Packages.gz": ("abc123", 1000),
                "universe/binary-amd64/Packages.gz": ("def456", 2000),
                "main/binary-arm64/Packages.gz": ("ghi789", 3000),
            },
        }

        from chantal.core.config import AptConfig, RepositoryConfig

        # Config only wants main/amd64
        repo_config = RepositoryConfig(
            id="test-repo",
            name="Test Repo",
            type="apt",
            feed="https://example.com/repo",
            mode="mirror",
            apt=AptConfig(distribution="jammy", components=["main"], architectures=["amd64"]),
        )

        sync_plugin = AptSyncPlugin(
            storage=None, config=repo_config, proxy_config=None, ssl_config=None
        )
        metadata_files = sync_plugin._build_metadata_file_list(release_metadata)

        # Should only get main/amd64
        packages_files = [f for f in metadata_files if f.file_type == "Packages"]
        assert len(packages_files) == 1
        assert packages_files[0].component == "main"
        assert packages_files[0].architecture == "amd64"

    def test_build_metadata_file_list_additional_metadata(self):
        """Test discovering additional metadata files (Contents, etc.)."""
        release_metadata = {
            "suite": "jammy",
            "components": ["main"],
            "architectures": ["amd64"],
            "sha256": {
                "main/binary-amd64/Packages.gz": ("abc123", 1000),
                "main/Contents-amd64.gz": ("def456", 5000),
                "main/i18n/Translation-en.gz": ("ghi789", 3000),
            },
        }

        from chantal.core.config import AptConfig, RepositoryConfig

        repo_config = RepositoryConfig(
            id="test-repo",
            name="Test Repo",
            type="apt",
            feed="https://example.com/repo",
            mode="mirror",
            apt=AptConfig(distribution="jammy", components=["main"], architectures=["amd64"]),
        )

        sync_plugin = AptSyncPlugin(
            storage=None, config=repo_config, proxy_config=None, ssl_config=None
        )
        metadata_files = sync_plugin._build_metadata_file_list(release_metadata)

        # In mirror mode, should include all metadata types
        file_types = {f.file_type for f in metadata_files}
        assert "Packages" in file_types
        # Additional metadata files are discovered but handled separately
        # This test verifies the basic structure is working

    def test_build_metadata_file_list_contents(self):
        """Contents indices are discovered in mirror mode and dropped in filtered."""
        from chantal.core.config import AptConfig, RepositoryConfig

        release_metadata = {
            "components": ["main"],
            "architectures": ["amd64"],
            "sha256": {
                "main/binary-amd64/Packages.gz": ("abc", 1000),
                "main/Contents-amd64.gz": ("def", 5000),
            },
        }
        repo_config = RepositoryConfig(
            id="test-repo",
            name="Test Repo",
            type="apt",
            feed="https://example.com/repo",
            mode="mirror",
            apt=AptConfig(
                distribution="jammy",
                components=["main"],
                architectures=["amd64"],
                include_contents=True,
            ),
        )
        plugin = AptSyncPlugin(storage=None, config=repo_config, proxy_config=None, ssl_config=None)

        mirror = plugin._build_metadata_file_list(release_metadata, "mirror")
        contents = [f for f in mirror if f.file_type == "Contents"]
        assert len(contents) == 1
        assert contents[0].relative_path == "main/Contents-amd64.gz"

        # Filtered mode drops Contents entirely.
        filtered = plugin._build_metadata_file_list(release_metadata, "filtered")
        assert not [f for f in filtered if f.file_type == "Contents"]

        # Default (include_contents=False) discovers no Contents.
        repo_config.apt.include_contents = False
        none = plugin._build_metadata_file_list(release_metadata, "mirror")
        assert not [f for f in none if f.file_type == "Contents"]

    def test_build_metadata_file_list_contents_variants_and_dedup(self):
        """Contents-all/udeb/.xz variants are picked up; suite-level deduped."""
        from chantal.core.config import AptConfig, RepositoryConfig

        release_metadata = {
            "components": ["main", "universe"],
            "architectures": ["amd64"],
            "sha256": {
                "main/binary-amd64/Packages.gz": ("p1", 1),
                "universe/binary-amd64/Packages.gz": ("p2", 1),
                "main/Contents-amd64.xz": ("c1", 1),  # .xz variant
                "main/Contents-all.gz": ("c2", 1),  # arch "all"
                "universe/Contents-udeb-amd64.gz": ("c3", 1),  # udeb variant
                "Contents-amd64.gz": ("c4", 1),  # suite-level (no component)
            },
        }
        repo_config = RepositoryConfig(
            id="test-repo",
            name="Test Repo",
            type="apt",
            feed="https://example.com/repo",
            mode="mirror",
            apt=AptConfig(
                distribution="jammy",
                components=["main", "universe"],
                architectures=["amd64"],
                include_contents=True,
            ),
        )
        plugin = AptSyncPlugin(storage=None, config=repo_config, proxy_config=None, ssl_config=None)

        contents = [
            f.relative_path
            for f in plugin._build_metadata_file_list(release_metadata, "mirror")
            if f.file_type == "Contents"
        ]
        # Each present variant discovered exactly once (suite-level not duplicated
        # across the two components).
        assert sorted(contents) == sorted(
            [
                "main/Contents-amd64.xz",
                "main/Contents-all.gz",
                "universe/Contents-udeb-amd64.gz",
                "Contents-amd64.gz",
            ]
        )

    def test_build_metadata_file_list_translations(self):
        """i18n Translation files + Index are discovered (mirror only)."""
        from chantal.core.config import AptConfig, RepositoryConfig

        release_metadata = {
            "components": ["main", "universe"],
            "architectures": ["amd64"],
            "sha256": {
                "main/binary-amd64/Packages.gz": ("p1", 1),
                "universe/binary-amd64/Packages.gz": ("p2", 1),
                "main/i18n/Translation-en.gz": ("t1", 1),
                "main/i18n/Translation-de.xz": ("t2", 1),
                "main/i18n/Index": ("t3", 1),
                "universe/i18n/Translation-en.gz": ("t4", 1),
            },
        }
        repo_config = RepositoryConfig(
            id="test-repo",
            name="Test Repo",
            type="apt",
            feed="https://example.com/repo",
            mode="mirror",
            apt=AptConfig(
                distribution="jammy",
                components=["main", "universe"],
                architectures=["amd64"],
                include_translations=True,
            ),
        )
        plugin = AptSyncPlugin(storage=None, config=repo_config, proxy_config=None, ssl_config=None)

        translations = [
            f.relative_path
            for f in plugin._build_metadata_file_list(release_metadata, "mirror")
            if f.file_type == "Translation"
        ]
        assert sorted(translations) == sorted(
            [
                "main/i18n/Translation-en.gz",
                "main/i18n/Translation-de.xz",
                "main/i18n/Index",
                "universe/i18n/Translation-en.gz",
            ]
        )

        # Filtered mode drops Translation; default flag discovers none.
        assert not [
            f
            for f in plugin._build_metadata_file_list(release_metadata, "filtered")
            if f.file_type == "Translation"
        ]
        repo_config.apt.include_translations = False
        assert not [
            f
            for f in plugin._build_metadata_file_list(release_metadata, "mirror")
            if f.file_type == "Translation"
        ]


class TestByHashUrl:
    """Tests for by-hash URL construction."""

    def test_nested_index(self):
        url = AptSyncPlugin._by_hash_url(
            "http://h/dists/jammy/", "main/binary-amd64/Packages.gz", "abc123"
        )
        assert url == "http://h/dists/jammy/main/binary-amd64/by-hash/SHA256/abc123"

    def test_top_level_index(self):
        # A suite-level file (parent == ".") must not get a "./" prefix.
        url = AptSyncPlugin._by_hash_url("http://h/dists/jammy/", "Contents-amd64.gz", "deadbeef")
        assert url == "http://h/dists/jammy/by-hash/SHA256/deadbeef"


class TestMetadataFileInfo:
    """Tests for MetadataFileInfo dataclass."""

    def test_metadata_file_info_creation(self):
        """Test creating MetadataFileInfo instance."""
        metadata = MetadataFileInfo(
            file_type="Packages",
            relative_path="main/binary-amd64/Packages.gz",
            checksum="abc123def456",
            size=1234567,
            component="main",
            architecture="amd64",
        )

        assert metadata.file_type == "Packages"
        assert metadata.relative_path == "main/binary-amd64/Packages.gz"
        assert metadata.checksum == "abc123def456"
        assert metadata.size == 1234567
        assert metadata.component == "main"
        assert metadata.architecture == "amd64"

    def test_metadata_file_info_optional_fields(self):
        """Test MetadataFileInfo with optional fields as None."""
        metadata = MetadataFileInfo(
            file_type="Release",
            relative_path="Release",
            checksum="abc123",
            size=1000,
            component=None,
            architecture=None,
        )

        assert metadata.file_type == "Release"
        assert metadata.component is None
        assert metadata.architecture is None
