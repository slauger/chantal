"""
Configuration management for Chantal.

This module provides Pydantic models for configuration validation and
YAML-based configuration loading with include support.
"""

from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


class ProxyConfig(BaseModel):
    """HTTP proxy configuration."""

    http_proxy: Optional[str] = None
    https_proxy: Optional[str] = None
    no_proxy: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


class SSLConfig(BaseModel):
    """SSL/TLS configuration for HTTPS connections."""

    # Path to CA bundle file (PEM format)
    ca_bundle: Optional[str] = None

    # Inline CA certificates (PEM format, multiple certs separated by newlines)
    ca_cert: Optional[str] = None

    # Disable SSL verification (not recommended for production)
    verify: bool = True

    # Client certificate for mTLS
    client_cert: Optional[str] = None
    client_key: Optional[str] = None


class AuthConfig(BaseModel):
    """Repository authentication configuration."""

    type: str  # client_cert, basic, bearer, custom

    # Client certificate authentication (RHEL CDN)
    cert_dir: Optional[str] = None
    cert_file: Optional[str] = None
    key_file: Optional[str] = None

    # HTTP Basic authentication
    username: Optional[str] = None
    password: Optional[str] = None

    # Bearer token authentication
    token: Optional[str] = None

    # Custom HTTP headers
    headers: Optional[Dict[str, str]] = None  # e.g., {"X-API-Key": "secret"}

    # SSL/TLS verification
    verify_ssl: bool = True  # Verify SSL certificates (set False to disable)
    ca_bundle: Optional[str] = None  # Path to CA bundle for custom CAs


class RetentionConfig(BaseModel):
    """Package retention policy configuration."""

    policy: str = "mirror"  # mirror, newest-only, keep-all, keep-last-n
    keep_count: Optional[int] = None  # For keep-last-n policy

    @field_validator("policy")
    @classmethod
    def validate_policy(cls, v: str) -> str:
        """Validate retention policy."""
        valid_policies = ["mirror", "newest-only", "keep-all", "keep-last-n"]
        if v not in valid_policies:
            raise ValueError(f"Invalid retention policy: {v}. Must be one of {valid_policies}")
        return v


class ScheduleConfig(BaseModel):
    """Repository sync schedule configuration."""

    enabled: bool = False
    cron: str = "0 2 * * *"  # Daily at 2:00 AM by default
    create_snapshot: bool = False
    snapshot_name_template: str = "{repo_id}-{date}"


class SizeFilterConfig(BaseModel):
    """Size-based filtering."""

    min: Optional[int] = None  # Minimum size in bytes
    max: Optional[int] = None  # Maximum size in bytes


class TimeFilterConfig(BaseModel):
    """Time-based filtering."""

    newer_than: Optional[str] = None  # ISO date string (e.g., "2025-01-01")
    older_than: Optional[str] = None  # ISO date string
    last_n_days: Optional[int] = None  # Last N days from now


class ListFilterConfig(BaseModel):
    """Generic list-based filtering (include/exclude)."""

    include: Optional[List[str]] = None
    exclude: Optional[List[str]] = None


class GenericMetadataFilterConfig(BaseModel):
    """Generic metadata filters (work for all package types)."""

    size_bytes: Optional[SizeFilterConfig] = None
    build_time: Optional[TimeFilterConfig] = None
    architectures: Optional[ListFilterConfig] = None


class RpmFilterConfig(BaseModel):
    """RPM-specific filters."""

    exclude_source_rpms: bool = False  # Skip .src.rpm packages
    groups: Optional[ListFilterConfig] = None
    licenses: Optional[ListFilterConfig] = None
    vendors: Optional[ListFilterConfig] = None
    epochs: Optional[ListFilterConfig] = None


class DebFilterConfig(BaseModel):
    """DEB/APT-specific filters (future support)."""

    components: Optional[ListFilterConfig] = None  # main, contrib, non-free
    priorities: Optional[ListFilterConfig] = None  # required, important, standard
    sections: Optional[ListFilterConfig] = None  # admin, devel, libs


class ApkConfig(BaseModel):
    """Alpine APK-specific configuration."""

    branch: str  # Alpine branch (v3.19, v3.18, edge, etc.)
    repository: str = "main"  # Repository (main, community, testing)
    architecture: str = "x86_64"  # Architecture (x86_64, aarch64, armhf, armv7, x86)


class PatternFilterConfig(BaseModel):
    """Pattern-based filters (regex)."""

    include: Optional[List[str]] = None  # Include patterns
    exclude: Optional[List[str]] = None  # Exclude patterns

    @field_validator("include", "exclude")
    @classmethod
    def validate_patterns(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """Validate regex patterns."""
        if v is not None:
            import re
            for pattern in v:
                try:
                    re.compile(pattern)
                except re.error as e:
                    raise ValueError(f"Invalid regex pattern '{pattern}': {e}")
        return v


class PostProcessingConfig(BaseModel):
    """Post-processing configuration (applied after filtering)."""

    only_latest_version: bool = False  # Keep only latest version per (name, arch)
    only_latest_n_versions: Optional[int] = None  # Keep last N versions


class FilterConfig(BaseModel):
    """Package filtering configuration.

    Supports both new structure and legacy flat structure for backward compatibility.

    Structure:
    - metadata: Generic filters (all package types)
    - rpm/deb/helm: Plugin-specific filters
    - patterns: Generic regex patterns
    - post_processing: Applied after all filters
    """

    # Generic filters (all package types)
    metadata: Optional[GenericMetadataFilterConfig] = None
    patterns: Optional[PatternFilterConfig] = None
    post_processing: Optional[PostProcessingConfig] = None

    # Plugin-specific filters
    rpm: Optional[RpmFilterConfig] = None
    deb: Optional[DebFilterConfig] = None

    # Legacy flat structure (backward compatibility)
    include_packages: Optional[List[str]] = None  # DEPRECATED: use patterns.include
    exclude_packages: Optional[List[str]] = None  # DEPRECATED: use patterns.exclude
    include_architectures: Optional[List[str]] = None  # DEPRECATED: use metadata.architectures.include
    exclude_architectures: Optional[List[str]] = None  # DEPRECATED: use metadata.architectures.exclude

    @field_validator("include_packages", "exclude_packages")
    @classmethod
    def validate_patterns_legacy(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """Validate regex patterns (legacy)."""
        if v is not None:
            import re
            for pattern in v:
                try:
                    re.compile(pattern)
                except re.error as e:
                    raise ValueError(f"Invalid regex pattern '{pattern}': {e}")
        return v

    def normalize(self) -> "FilterConfig":
        """Normalize legacy config to new structure."""
        # If using legacy structure, migrate to new structure
        if self.metadata is None and (
            self.include_architectures or self.exclude_architectures
        ):
            self.metadata = GenericMetadataFilterConfig(
                architectures=ListFilterConfig(
                    include=self.include_architectures,
                    exclude=self.exclude_architectures,
                )
            )

        if self.patterns is None and (self.include_packages or self.exclude_packages):
            self.patterns = PatternFilterConfig(
                include=self.include_packages,
                exclude=self.exclude_packages,
            )

        return self

    def validate_for_repo_type(self, repo_type: str) -> None:
        """Validate that only appropriate plugin-specific filters are used.

        Args:
            repo_type: Repository type (rpm, deb, etc.)

        Raises:
            ValueError: If incompatible filters are specified
        """
        if repo_type == "rpm" and self.deb is not None:
            raise ValueError("Cannot use 'deb' filters with RPM repository")
        if repo_type == "deb" and self.rpm is not None:
            raise ValueError("Cannot use 'rpm' filters with DEB repository")


class RepositoryConfig(BaseModel):
    """Repository configuration."""

    id: str
    name: Optional[str] = None
    type: str  # rpm, apt
    feed: str  # upstream URL
    enabled: bool = True

    # Repository mode (mirror, filtered, hosted)
    mode: Literal["mirror", "filtered", "hosted"] = "filtered"

    # Tags for grouping/filtering (e.g., ["production", "web", "rhel"])
    tags: Optional[List[str]] = Field(default_factory=list)

    # Authentication
    auth: Optional[AuthConfig] = None

    # Paths (optional overrides)
    latest_path: Optional[str] = None
    snapshots_path: Optional[str] = None

    # Retention policy
    retention: Optional[RetentionConfig] = Field(default_factory=lambda: RetentionConfig())

    # Scheduling
    schedule: Optional[ScheduleConfig] = Field(default_factory=lambda: ScheduleConfig())

    # Package filtering
    filters: Optional[FilterConfig] = None

    # Per-repository proxy override (overrides global proxy config)
    proxy: Optional[ProxyConfig] = None

    # Per-repository SSL/TLS override (overrides global ssl config)
    ssl: Optional[SSLConfig] = None

    # Plugin-specific configuration
    apk: Optional[ApkConfig] = None  # APK-specific config (branch, repository, architecture)

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        """Validate repository type."""
        valid_types = ["rpm", "apt", "helm", "apk"]
        if v not in valid_types:
            raise ValueError(f"Invalid repository type: {v}. Must be one of {valid_types}")
        return v

    @model_validator(mode="after")
    def validate_mode_and_filters(self) -> "RepositoryConfig":
        """Validate that mirror mode is not used with filters."""
        if self.mode == "mirror" and self.filters is not None:
            raise ValueError(
                f"Repository '{self.id}': mode='mirror' cannot be used with filters. "
                "Use mode='filtered' to apply filters, or remove filters for true mirror mode."
            )
        return self

    @property
    def display_name(self) -> str:
        """Get display name (use name if set, otherwise id)."""
        return self.name or self.id


class DatabaseConfig(BaseModel):
    """Database configuration."""

    url: str = "postgresql://chantal:chantal@localhost/chantal"
    pool_size: int = 5
    max_overflow: int = 10
    echo: bool = False  # SQLAlchemy echo (verbose SQL logging)


class StorageConfig(BaseModel):
    """Storage paths configuration."""

    base_path: str = "/var/lib/chantal"
    pool_path: Optional[str] = None  # Defaults to {base_path}/pool
    published_path: str = "/var/www/repos"
    temp_path: Optional[str] = None  # Defaults to {base_path}/tmp

    def get_pool_path(self) -> Path:
        """Get pool path (with default)."""
        if self.pool_path:
            return Path(self.pool_path)
        return Path(self.base_path) / "pool"

    def get_temp_path(self) -> Path:
        """Get temp path (with default)."""
        if self.temp_path:
            return Path(self.temp_path)
        return Path(self.base_path) / "tmp"


class ViewConfig(BaseModel):
    """View configuration - groups multiple repositories into one virtual repository."""

    name: str
    description: Optional[str] = None
    repos: List[str]  # List of repository IDs

    # Optional: Override publish path
    publish_path: Optional[str] = None

    def validate_repos(self, all_repos: List[RepositoryConfig]) -> None:
        """Validate that all referenced repositories exist and have same type.

        Args:
            all_repos: List of all repository configurations

        Raises:
            ValueError: If repo doesn't exist or types don't match
        """
        repo_ids = {repo.id for repo in all_repos}
        repo_types = {}

        for repo_id in self.repos:
            if repo_id not in repo_ids:
                raise ValueError(f"View '{self.name}' references unknown repository: {repo_id}")

            # Get repo type
            repo = next(r for r in all_repos if r.id == repo_id)
            repo_types[repo_id] = repo.type

        # Check all repos have same type
        types = set(repo_types.values())
        if len(types) > 1:
            raise ValueError(
                f"View '{self.name}' contains repositories of different types: {types}. "
                f"All repositories in a view must have the same type."
            )


class DownloadConfig(BaseModel):
    """Download configuration for file downloads."""

    backend: str = "requests"  # requests, aria2c (future)
    parallel: int = 1  # Parallel downloads (backend-dependent)
    timeout: int = 300  # Download timeout in seconds
    retry_attempts: int = 3  # Number of retry attempts on failure
    verify_checksum: bool = True  # Verify checksums after download

    @field_validator("backend")
    @classmethod
    def validate_backend(cls, v: str) -> str:
        """Validate download backend."""
        valid_backends = ["requests", "aria2c"]
        if v not in valid_backends:
            raise ValueError(f"Invalid download backend: {v}. Must be one of {valid_backends}")
        return v

    @field_validator("parallel")
    @classmethod
    def validate_parallel(cls, v: int) -> int:
        """Validate parallel download count."""
        if v < 1:
            raise ValueError("parallel must be at least 1")
        if v > 100:
            raise ValueError("parallel cannot exceed 100")
        return v

    @field_validator("timeout")
    @classmethod
    def validate_timeout(cls, v: int) -> int:
        """Validate timeout value."""
        if v < 1:
            raise ValueError("timeout must be at least 1 second")
        return v

    @field_validator("retry_attempts")
    @classmethod
    def validate_retry_attempts(cls, v: int) -> int:
        """Validate retry attempts."""
        if v < 0:
            raise ValueError("retry_attempts cannot be negative")
        if v > 10:
            raise ValueError("retry_attempts cannot exceed 10")
        return v


class GlobalConfig(BaseModel):
    """Global Chantal configuration."""

    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    proxy: Optional[ProxyConfig] = None
    ssl: Optional[SSLConfig] = None
    download: Optional[DownloadConfig] = Field(default_factory=DownloadConfig)
    repositories: List[RepositoryConfig] = Field(default_factory=list)
    views: List[ViewConfig] = Field(default_factory=list)

    # Include pattern for additional config files
    include: Optional[str] = None

    def get_repository(self, repo_id: str) -> Optional[RepositoryConfig]:
        """Get repository configuration by ID."""
        for repo in self.repositories:
            if repo.id == repo_id:
                return repo
        return None

    def get_enabled_repositories(self) -> List[RepositoryConfig]:
        """Get all enabled repositories."""
        return [repo for repo in self.repositories if repo.enabled]

    def get_repositories_by_type(self, repo_type: str) -> List[RepositoryConfig]:
        """Get all repositories of a specific type."""
        return [repo for repo in self.repositories if repo.type == repo_type]

    def get_view(self, view_name: str) -> Optional[ViewConfig]:
        """Get view configuration by name."""
        for view in self.views:
            if view.name == view_name:
                return view
        return None

    def get_views_for_repository(self, repo_id: str) -> List[ViewConfig]:
        """Get all views that contain a specific repository."""
        return [view for view in self.views if repo_id in view.repos]


class ConfigLoader:
    """Configuration file loader with include support."""

    def __init__(self, config_path: Path):
        """Initialize config loader.

        Args:
            config_path: Path to main configuration file
        """
        self.config_path = config_path

    def load(self) -> GlobalConfig:
        """Load configuration from YAML file.

        Returns:
            GlobalConfig instance

        Raises:
            FileNotFoundError: If config file doesn't exist
            ValueError: If config is invalid
        """
        if not self.config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")

        # Load main config file
        try:
            with open(self.config_path) as f:
                config_data = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            raise ValueError(f"YAML syntax error in {self.config_path}:\n{e}")

        # Handle includes
        if "include" in config_data:
            include_pattern = config_data["include"]
            included_repos, included_views = self._load_includes(include_pattern)

            # Merge included repositories
            if "repositories" not in config_data:
                config_data["repositories"] = []
            config_data["repositories"].extend(included_repos)

            # Merge included views
            if "views" not in config_data:
                config_data["views"] = []
            config_data["views"].extend(included_views)

        # Validate and create GlobalConfig
        try:
            return GlobalConfig(**config_data)
        except Exception as e:
            raise ValueError(f"Configuration validation error in {self.config_path}:\n{e}")

    def _load_includes(self, include_pattern: str) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Load included configuration files.

        Args:
            include_pattern: Glob pattern for include files (e.g., "conf.d/*.yaml")

        Returns:
            Tuple of (repositories, views) from included files
        """
        # Resolve pattern relative to main config directory
        config_dir = self.config_path.parent
        include_path = config_dir / include_pattern

        # Get parent directory and pattern
        if "*" in include_pattern:
            # It's a glob pattern
            pattern_parts = Path(include_pattern).parts
            if len(pattern_parts) > 1:
                search_dir = config_dir / Path(*pattern_parts[:-1])
                pattern = pattern_parts[-1]
            else:
                search_dir = config_dir
                pattern = include_pattern

            # Find matching files
            if search_dir.exists():
                config_files = sorted(search_dir.glob(pattern))
            else:
                config_files = []
        else:
            # Single file
            config_files = [include_path] if include_path.exists() else []

        # Load all included files
        all_repos = []
        all_views = []
        for config_file in config_files:
            if config_file.suffix in [".yaml", ".yml"]:
                try:
                    with open(config_file) as f:
                        data = yaml.safe_load(f) or {}
                        if "repositories" in data:
                            all_repos.extend(data["repositories"])
                        if "views" in data:
                            all_views.extend(data["views"])
                except yaml.YAMLError as e:
                    raise ValueError(f"YAML syntax error in {config_file}:\n{e}")

        return all_repos, all_views


def load_config(config_path: Optional[Path] = None) -> GlobalConfig:
    """Load configuration from file.

    Priority:
    1. Explicit config_path parameter (--config CLI flag)
    2. CHANTAL_CONFIG environment variable
    3. Default locations (/etc/chantal/config.yaml, ~/.config/chantal/config.yaml, ./config.yaml)

    Args:
        config_path: Path to config file. If None, tries CHANTAL_CONFIG env or default locations.

    Returns:
        GlobalConfig instance

    Raises:
        FileNotFoundError: If no config file found
    """
    import os

    # Default config locations
    default_paths = [
        Path("/etc/chantal/config.yaml"),
        Path.home() / ".config" / "chantal" / "config.yaml",
        Path("config.yaml"),
    ]

    if config_path:
        # Explicit path from CLI flag
        paths_to_try = [config_path]
    elif os.environ.get("CHANTAL_CONFIG"):
        # CHANTAL_CONFIG environment variable
        paths_to_try = [Path(os.environ["CHANTAL_CONFIG"])]
    else:
        # Default locations
        paths_to_try = default_paths

    # Try each path
    for path in paths_to_try:
        if path.exists():
            loader = ConfigLoader(path)
            return loader.load()

    # No config found
    if config_path:
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    elif os.environ.get("CHANTAL_CONFIG"):
        raise FileNotFoundError(f"Configuration file not found: {os.environ['CHANTAL_CONFIG']} (from CHANTAL_CONFIG)")
    else:
        # Return default config if no file found
        return GlobalConfig()


def create_example_config(output_path: Path) -> None:
    """Create an example configuration file.

    Args:
        output_path: Path to write example config
    """
    example_config = {
        "database": {
            "url": "postgresql://chantal:password@localhost/chantal",
            "pool_size": 5,
            "echo": False,
        },
        "storage": {
            "base_path": "/var/lib/chantal",
            "pool_path": "/var/lib/chantal/pool",
            "published_path": "/var/www/repos",
        },
        "proxy": {
            "http_proxy": "http://proxy.example.com:8080",
            "https_proxy": "http://proxy.example.com:8080",
            "no_proxy": "localhost,127.0.0.1,.internal.domain",
            "username": None,
            "password": None,
        },
        "repositories": [
            {
                "id": "rhel9-baseos",
                "name": "RHEL 9 BaseOS",
                "type": "rpm",
                "feed": "https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os",
                "enabled": True,
                "auth": {
                    "type": "client_cert",
                    "cert_dir": "/etc/pki/entitlement",
                },
                "retention": {
                    "policy": "mirror",
                },
                "schedule": {
                    "enabled": True,
                    "cron": "0 2 * * *",
                    "create_snapshot": True,
                    "snapshot_name_template": "{repo_id}-{date}",
                },
            }
        ],
        "include": "conf.d/*.yaml",
    }

    with open(output_path, "w") as f:
        yaml.dump(example_config, f, default_flow_style=False, sort_keys=False)
