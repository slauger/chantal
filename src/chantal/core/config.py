from __future__ import annotations

"""
Configuration management for Chantal.

This module provides Pydantic models for configuration validation and
YAML-based configuration loading with include support.
"""

from pathlib import Path, PurePosixPath
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ProxyConfig(BaseModel):
    """HTTP proxy configuration."""

    model_config = ConfigDict(extra="forbid")

    http_proxy: str | None = None
    https_proxy: str | None = None
    no_proxy: str | None = None
    username: str | None = None
    password: str | None = None


class SSLConfig(BaseModel):
    """SSL/TLS configuration for HTTPS connections."""

    model_config = ConfigDict(extra="forbid")

    # Path to CA bundle file (PEM format)
    ca_bundle: str | None = None

    # Inline CA certificates (PEM format, multiple certs separated by newlines)
    ca_cert: str | None = None

    # Disable SSL verification (not recommended for production)
    verify: bool = True

    # Client certificate for mTLS
    client_cert: str | None = None
    client_key: str | None = None


class AuthConfig(BaseModel):
    """Repository authentication configuration."""

    model_config = ConfigDict(extra="forbid")

    type: str  # client_cert, basic, bearer, custom

    # Client certificate authentication (RHEL CDN)
    cert_dir: str | None = None
    cert_file: str | None = None
    key_file: str | None = None

    # HTTP Basic authentication
    username: str | None = None
    password: str | None = None

    # Bearer token authentication
    token: str | None = None

    # Custom HTTP headers
    headers: dict[str, str] | None = None  # e.g., {"X-API-Key": "secret"}

    # NOTE: SSL/TLS verification is configured under the repository's `ssl:`
    # section (SSLConfig), not here.


class RetentionConfig(BaseModel):
    """Package retention policy configuration."""

    model_config = ConfigDict(extra="forbid")

    policy: str = "mirror"  # mirror, newest-only, keep-all, keep-last-n
    keep_count: int | None = None  # For keep-last-n policy

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

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    cron: str = "0 2 * * *"  # Daily at 2:00 AM by default
    create_snapshot: bool = False
    snapshot_name_template: str = "{repo_id}-{date}"


class SizeFilterConfig(BaseModel):
    """Size-based filtering."""

    model_config = ConfigDict(extra="forbid")

    min: int | None = None  # Minimum size in bytes
    max: int | None = None  # Maximum size in bytes


class TimeFilterConfig(BaseModel):
    """Time-based filtering."""

    model_config = ConfigDict(extra="forbid")

    newer_than: str | None = None  # ISO date string (e.g., "2025-01-01")
    older_than: str | None = None  # ISO date string
    last_n_days: int | None = None  # Last N days from now


class ListFilterConfig(BaseModel):
    """Generic list-based filtering (include/exclude)."""

    model_config = ConfigDict(extra="forbid")

    include: list[str] | None = None
    exclude: list[str] | None = None


class GenericMetadataFilterConfig(BaseModel):
    """Generic metadata filters (work for all package types)."""

    model_config = ConfigDict(extra="forbid")

    size_bytes: SizeFilterConfig | None = None
    build_time: TimeFilterConfig | None = None
    architectures: ListFilterConfig | None = None


class RpmFilterConfig(BaseModel):
    """RPM-specific filters."""

    model_config = ConfigDict(extra="forbid")

    exclude_source_rpms: bool = False  # Skip .src.rpm packages
    groups: ListFilterConfig | None = None
    licenses: ListFilterConfig | None = None
    vendors: ListFilterConfig | None = None
    epochs: ListFilterConfig | None = None


class DebFilterConfig(BaseModel):
    """DEB/APT-specific filters (future support)."""

    model_config = ConfigDict(extra="forbid")

    components: ListFilterConfig | None = None  # main, contrib, non-free
    priorities: ListFilterConfig | None = None  # required, important, standard
    sections: ListFilterConfig | None = None  # admin, devel, libs


class ApkConfig(BaseModel):
    """Alpine APK-specific configuration."""

    model_config = ConfigDict(extra="forbid")

    branch: str  # Alpine branch (v3.19, v3.18, edge, etc.)
    repository: str = "main"  # Repository (main, community, testing)
    architecture: str = "x86_64"  # Architecture (x86_64, aarch64, armhf, armv7, x86)


class AptConfig(BaseModel):
    """APT/DEB-specific configuration."""

    model_config = ConfigDict(extra="forbid")

    distribution: str  # Distribution/suite (jammy, bookworm, focal, bullseye, etc.)
    components: list[str] = Field(
        default_factory=lambda: ["main"],
        description="Repository components (main, restricted, universe, multiverse, contrib, non-free)",
    )
    architectures: list[str] = Field(
        default_factory=lambda: ["amd64"],
        description="Architectures to mirror (amd64, arm64, i386, armhf, all)",
    )
    include_source_packages: bool = Field(
        default=False, description="Include source packages (.dsc, .orig.tar.gz, etc.)"
    )
    include_contents: bool = Field(
        default=False,
        description="Mirror Contents-<arch> indices (apt-file). Large; mirror mode only.",
    )
    include_translations: bool = Field(
        default=False,
        description=(
            "Mirror i18n/Translation-* files and i18n/Index (localized package "
            "descriptions). Mirror mode only."
        ),
    )
    by_hash: bool = Field(
        default=False,
        description=(
            "Use/publish by-hash indices. On sync, fetch indices via "
            "by-hash/SHA256/<checksum> (falling back to the plain path). On "
            "publish, emit by-hash/SHA256/ copies and set Acquire-By-Hash: yes "
            "in the generated Release."
        ),
    )

    # Generated-Release field overrides (the published Release is regenerated
    # and re-signed; these control its header fields).
    origin: str | None = Field(None, description="Release Origin field (default: Chantal)")
    label: str | None = Field(None, description="Release Label field (default: repository name)")
    suite: str | None = Field(None, description="Release Suite field (default: distribution)")
    codename: str | None = Field(None, description="Release Codename field (default: distribution)")
    not_automatic: bool = Field(
        default=False,
        description="Emit 'NotAutomatic: yes' so apt does not auto-select this repo's packages",
    )
    but_automatic_upgrades: bool = Field(
        default=False,
        description="Emit 'ButAutomaticUpgrades: yes' (only valid together with not_automatic)",
    )
    valid_until_days: int | None = Field(
        default=None,
        description=(
            "Emit 'Valid-Until' = publish time + this many days (omitted when unset). "
            "Upstream's date is never copied as it is usually already expired by publish time."
        ),
    )

    @model_validator(mode="after")
    def validate_release_fields(self) -> AptConfig:
        """Validate the generated-Release field options."""
        if self.but_automatic_upgrades and not self.not_automatic:
            raise ValueError(
                "but_automatic_upgrades requires not_automatic (apt only honors "
                "ButAutomaticUpgrades together with NotAutomatic)"
            )
        if self.valid_until_days is not None and self.valid_until_days <= 0:
            raise ValueError("valid_until_days must be a positive number of days")
        return self


class GpgConfig(BaseModel):
    """GPG signing configuration for APT repositories.

    Used to sign regenerated metadata (Release) in filtered mode so that
    clients can verify the repository without ``[trusted=yes]``.

    The signing key can be provided in three ways (checked in this order):

    1. ``key_file`` - import a private (secret) key from an ASCII-armored file.
    2. ``key_id`` - use a key already present in the keyring / ``gnupg_home``.
    3. ``generate_key`` - generate a new keypair if none of the above is set.
    """

    model_config = ConfigDict(extra="forbid")

    # Enable/disable signing (allows keeping config while turning signing off)
    enabled: bool = True

    # Key selection
    key_id: str | None = Field(None, description="Key ID or fingerprint of the signing key to use")
    key_file: str | None = Field(
        None, description="Path to ASCII-armored private key file to import before signing"
    )

    # Passphrase handling (file preferred over inline value)
    passphrase: str | None = Field(
        None, description="Signing key passphrase (inline; prefer passphrase_file)"
    )
    passphrase_file: str | None = Field(
        None, description="Path to a file containing the signing key passphrase"
    )

    # GnuPG home directory (keyring location); a temporary one is used if unset
    gnupg_home: str | None = Field(None, description="GNUPGHOME directory holding the keyring")

    # Public key distribution
    public_key_file: str | None = Field(
        None,
        description="Path to the public key to publish for clients "
        "(exported from the keyring if not set)",
    )
    public_key_name: str = Field(
        "key.gpg",
        description="Filename of the published public key inside the repository root",
    )

    # Optional keypair generation when no key is provided
    generate_key: bool = Field(
        False, description="Generate a new signing keypair if no key is provided"
    )
    key_name: str | None = Field(
        None, description="Real name for a generated key (defaults to repository name)"
    )
    key_email: str | None = Field(
        None, description="Email for a generated key (defaults to chantal@localhost)"
    )

    @model_validator(mode="after")
    def validate_key_source(self) -> GpgConfig:
        """Ensure at least one key source is configured when signing is enabled."""
        if not self.enabled:
            return self
        if not (self.key_file or self.key_id or self.generate_key):
            raise ValueError(
                "GPG signing is enabled but no key source is configured. "
                "Provide 'key_file', 'key_id', or set 'generate_key: true'."
            )
        return self

    def read_passphrase(self) -> str | None:
        """Resolve the passphrase from file or inline value.

        Returns:
            The passphrase string, or None if no passphrase is configured.
        """
        if self.passphrase_file:
            return Path(self.passphrase_file).read_text(encoding="utf-8").strip()
        return self.passphrase


class SignatureVerificationConfig(BaseModel):
    """Verify the authenticity of an upstream repository via GPG.

    This is independent of :class:`GpgConfig` (which holds the *private* signing
    key used to re-sign regenerated metadata). Verification needs *public* trust
    anchors - the upstream vendor's public key(s).

    Integrity (SHA256) is always checked during sync; this adds *authenticity*
    (the metadata/packages were signed by a trusted key), analogous to dnf's
    ``repo_gpgcheck`` / ``gpgcheck`` and apt's Release signature check.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False

    # What to verify
    repo_gpgcheck: bool = True  # verify repository metadata signature (repomd.xml.asc)
    gpgcheck: bool = True  # verify individual package (.rpm) signatures

    # Trust anchors (public keys)
    key_files: list[str] = Field(
        default_factory=list, description="Paths to ASCII-armored public key files"
    )
    keys: list[str] = Field(default_factory=list, description="Inline ASCII-armored public keys")
    trusted_fingerprints: list[str] = Field(
        default_factory=list,
        description="Optional allow-list of full key fingerprints (pinning)",
    )

    # Publish the trusted upstream key into the published repository so that
    # downstream clients can verify the mirrored packages (gpgcheck=1). The
    # mirrored .rpm files retain their upstream signatures, so clients need the
    # upstream key. ``{repo_id}`` is substituted with the repository id; an empty
    # value disables publishing. Relative subdirectories are supported.
    client_key_name: str = Field(
        "RPM-GPG-KEY-{repo_id}",
        description=(
            "Filename for the trusted upstream public key written into the "
            "published repository root (empty disables; '{repo_id}' is substituted)"
        ),
    )

    # Keyring location (a private temporary one is used if unset)
    gnupg_home: str | None = None

    # Behavior policy
    on_missing_signature: Literal["fail", "warn", "skip"] = "fail"
    on_invalid_signature: Literal["fail", "warn", "skip"] = "fail"

    @model_validator(mode="after")
    def validate_config(self) -> SignatureVerificationConfig:
        """Validate the verification configuration when enabled."""
        if not self.enabled:
            return self
        if not (self.key_files or self.keys):
            raise ValueError(
                "Signature verification is enabled but no trusted key is configured. "
                "Provide 'key_files' or 'keys'."
            )
        if self.gpgcheck and not self.repo_gpgcheck:
            raise ValueError(
                "gpgcheck requires repo_gpgcheck. A package's header-only signature proves "
                "the vendor built that header, but does not by itself authenticate the package "
                "payload; repo_gpgcheck authenticates the metadata checksums that bind the "
                "downloaded bytes. Enable both (the default)."
            )
        if any(not fpr.strip() for fpr in self.trusted_fingerprints):
            raise ValueError("trusted_fingerprints must not contain empty entries")
        name = self.client_key_name
        if name:
            pure = PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts:
                raise ValueError(
                    "client_key_name must be a relative path within the repository "
                    "(no leading '/' or '..')"
                )
        return self


class MetadataConfig(BaseModel):
    """Metadata generation configuration (RPM, APT, etc.)."""

    model_config = ConfigDict(extra="forbid")

    compression: Literal["auto", "gzip", "zstandard", "bzip2", "none"] = Field(
        default="auto",
        description="Compression format for generated metadata. 'auto' uses same as upstream.",
    )

    @field_validator("compression")
    @classmethod
    def validate_compression(cls, v: str) -> str:
        """Validate compression format."""
        valid_formats = ["auto", "gzip", "zstandard", "bzip2", "none"]
        if v not in valid_formats:
            raise ValueError(f"Invalid compression format: {v}. Must be one of {valid_formats}")
        return v


class PatternFilterConfig(BaseModel):
    """Pattern-based filters (regex)."""

    model_config = ConfigDict(extra="forbid")

    include: list[str] | None = None  # Include patterns
    exclude: list[str] | None = None  # Exclude patterns

    @field_validator("include", "exclude")
    @classmethod
    def validate_patterns(cls, v: list[str] | None) -> list[str] | None:
        """Validate regex patterns."""
        if v is not None:
            import re

            for pattern in v:
                try:
                    re.compile(pattern)
                except re.error as e:
                    raise ValueError(f"Invalid regex pattern '{pattern}': {e}") from e
        return v


class PostProcessingConfig(BaseModel):
    """Post-processing configuration (applied after filtering)."""

    model_config = ConfigDict(extra="forbid")

    only_latest_version: bool = False  # Keep only latest version per (name, arch)
    only_latest_n_versions: int | None = None  # Keep last N versions


class FilterConfig(BaseModel):
    """Package filtering configuration.

    Supports both new structure and legacy flat structure for backward compatibility.

    Structure:
    - metadata: Generic filters (all package types)
    - rpm/deb/helm: Plugin-specific filters
    - patterns: Generic regex patterns
    - post_processing: Applied after all filters
    """

    model_config = ConfigDict(extra="forbid")

    # Generic filters (all package types)
    metadata: GenericMetadataFilterConfig | None = None
    patterns: PatternFilterConfig | None = None
    post_processing: PostProcessingConfig | None = None

    # Plugin-specific filters
    rpm: RpmFilterConfig | None = None
    deb: DebFilterConfig | None = None

    # Legacy flat structure (backward compatibility)
    include_packages: list[str] | None = None  # DEPRECATED: use patterns.include
    exclude_packages: list[str] | None = None  # DEPRECATED: use patterns.exclude
    include_architectures: list[str] | None = None  # DEPRECATED: use metadata.architectures.include
    exclude_architectures: list[str] | None = None  # DEPRECATED: use metadata.architectures.exclude

    @field_validator("include_packages", "exclude_packages")
    @classmethod
    def validate_patterns_legacy(cls, v: list[str] | None) -> list[str] | None:
        """Validate regex patterns (legacy)."""
        if v is not None:
            import re

            for pattern in v:
                try:
                    re.compile(pattern)
                except re.error as e:
                    raise ValueError(f"Invalid regex pattern '{pattern}': {e}") from e
        return v

    def normalize(self) -> FilterConfig:
        """Normalize legacy config to new structure."""
        # If using legacy structure, migrate to new structure
        if self.metadata is None and (self.include_architectures or self.exclude_architectures):
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
            repo_type: Repository type (rpm, apt, etc.)

        Raises:
            ValueError: If incompatible filters are specified
        """
        if repo_type == "rpm" and self.deb is not None:
            raise ValueError("Cannot use 'deb' filters with RPM repository")
        if repo_type == "apt" and self.rpm is not None:
            raise ValueError("Cannot use 'rpm' filters with APT repository")


class RepositoryConfig(BaseModel):
    """Repository configuration."""

    # Reject unknown keys so a typo (e.g. `enabledd: true`) fails loudly at load
    # time instead of being silently ignored.
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str | None = None
    type: str  # rpm, apt
    feed: str = ""  # upstream URL (empty for hosted repos; required otherwise)
    enabled: bool = True

    # Repository mode (mirror, filtered, hosted)
    mode: Literal["mirror", "filtered", "hosted"] = "filtered"

    # Tags for grouping/filtering (e.g., ["production", "web", "rhel"])
    tags: list[str] | None = Field(default_factory=list)

    # Authentication
    auth: AuthConfig | None = None

    # Paths (optional overrides)
    latest_path: str | None = None
    snapshots_path: str | None = None

    # Retention policy
    retention: RetentionConfig | None = Field(default_factory=lambda: RetentionConfig())

    # Scheduling
    schedule: ScheduleConfig | None = Field(default_factory=lambda: ScheduleConfig())

    # Package filtering
    filters: FilterConfig | None = None

    # Per-repository proxy override (overrides global proxy config)
    proxy: ProxyConfig | None = None

    # Per-repository SSL/TLS override (overrides global ssl config)
    ssl: SSLConfig | None = None

    # Metadata cache override (None = use global cache.enabled setting)
    cache_enabled: bool | None = None

    # Plugin-specific configuration
    apk: ApkConfig | None = None  # APK-specific config (branch, repository, architecture)
    apt: AptConfig | None = None  # APT-specific config (distribution, components, architectures)
    metadata: MetadataConfig | None = Field(
        default_factory=lambda: MetadataConfig(),
        description="Metadata generation configuration (compression, etc.)",
    )

    # GPG signing (APT filtered mode); falls back to global gpg config if unset
    gpg: GpgConfig | None = None

    # Upstream signature verification; falls back to global verify config if unset
    verify: SignatureVerificationConfig | None = None

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        """Validate repository type."""
        valid_types = ["rpm", "apt", "helm", "apk"]
        if v not in valid_types:
            raise ValueError(f"Invalid repository type: {v}. Must be one of {valid_types}")
        return v

    @model_validator(mode="after")
    def validate_mode_and_filters(self) -> RepositoryConfig:
        """Validate mode/filters and the feed requirement."""
        if self.mode == "mirror" and self.filters is not None:
            raise ValueError(
                f"Repository '{self.id}': mode='mirror' cannot be used with filters. "
                "Use mode='filtered' to apply filters, or remove filters for true mirror mode."
            )
        # Hosted repos hold only uploaded packages and need no upstream feed;
        # mirror/filtered repos sync from a feed and require one.
        if self.mode != "hosted" and not self.feed:
            raise ValueError(
                f"Repository '{self.id}': a 'feed' is required for mode='{self.mode}'. "
                "Use mode='hosted' for an upload-only repository with no upstream."
            )
        return self

    @property
    def display_name(self) -> str:
        """Get display name (use name if set, otherwise id)."""
        return self.name or self.id


class DatabaseConfig(BaseModel):
    """Database configuration."""

    model_config = ConfigDict(extra="forbid")

    url: str = "sqlite:///chantal.db"
    pool_size: int = 5
    max_overflow: int = 10
    echo: bool = False  # SQLAlchemy echo (verbose SQL logging)


class CacheConfig(BaseModel):
    """Metadata cache configuration."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False  # Global default
    max_age_hours: int | None = None  # Optional TTL for cache invalidation

    @field_validator("max_age_hours")
    @classmethod
    def validate_max_age(cls, v: int | None) -> int | None:
        """Validate max_age_hours."""
        if v is not None and v < 1:
            raise ValueError("max_age_hours must be at least 1")
        return v


class StorageConfig(BaseModel):
    """Storage paths configuration."""

    model_config = ConfigDict(extra="forbid")

    base_path: str = "/var/lib/chantal"
    pool_path: str | None = None  # Defaults to {base_path}/pool
    published_path: str = "/var/www/repos"
    temp_path: str | None = None  # Defaults to {base_path}/tmp
    cache_path: str | None = None  # Metadata cache directory (None = cache disabled)

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

    def get_cache_path(self) -> Path | None:
        """Get cache path (None if caching disabled)."""
        if self.cache_path:
            return Path(self.cache_path)
        return None


class ViewConfig(BaseModel):
    """View configuration - groups multiple repositories into one virtual repository."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = None
    repos: list[str]  # List of repository IDs

    # Optional: Override publish path
    publish_path: str | None = None

    def validate_repos(self, all_repos: list[RepositoryConfig]) -> None:
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

    model_config = ConfigDict(extra="forbid")

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

    # Reject unknown top-level keys so config typos fail loudly at load time.
    model_config = ConfigDict(extra="forbid")

    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    cache: CacheConfig | None = Field(default_factory=CacheConfig)
    proxy: ProxyConfig | None = None
    ssl: SSLConfig | None = None
    download: DownloadConfig | None = Field(default_factory=DownloadConfig)
    # Global GPG signing fallback for repositories without their own gpg config
    gpg: GpgConfig | None = None
    # Global upstream-verification fallback for repositories without their own
    verify: SignatureVerificationConfig | None = None
    repositories: list[RepositoryConfig] = Field(default_factory=list)
    views: list[ViewConfig] = Field(default_factory=list)

    # Include pattern for additional config files
    include: str | None = None

    @model_validator(mode="after")
    def validate_repositories_and_views(self) -> GlobalConfig:
        """Normalize/validate repository filters and validate views at load time.

        - Migrate legacy flat filters to the structured form for every repo
          (previously only the RPM plugin did this, so APT silently ignored
          legacy ``include_packages``/``exclude_packages``).
        - Reject plugin-specific filters used with the wrong repository type.
        - Reject views that reference unknown repositories or mix repo types.
        """
        for repo in self.repositories:
            if repo.filters is not None:
                repo.filters = repo.filters.normalize()
                repo.filters.validate_for_repo_type(repo.type)
        for view in self.views:
            view.validate_repos(self.repositories)
        return self

    def get_repository(self, repo_id: str) -> RepositoryConfig | None:
        """Get repository configuration by ID."""
        for repo in self.repositories:
            if repo.id == repo_id:
                return repo
        return None

    def get_enabled_repositories(self) -> list[RepositoryConfig]:
        """Get all enabled repositories."""
        return [repo for repo in self.repositories if repo.enabled]

    def get_repositories_by_type(self, repo_type: str) -> list[RepositoryConfig]:
        """Get all repositories of a specific type."""
        return [repo for repo in self.repositories if repo.type == repo_type]

    def get_view(self, view_name: str) -> ViewConfig | None:
        """Get view configuration by name."""
        for view in self.views:
            if view.name == view_name:
                return view
        return None

    def get_views_for_repository(self, repo_id: str) -> list[ViewConfig]:
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
            raise ValueError(f"YAML syntax error in {self.config_path}:\n{e}") from e

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
            raise ValueError(f"Configuration validation error in {self.config_path}:\n{e}") from e

    def _load_includes(
        self, include_pattern: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
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
                    raise ValueError(f"YAML syntax error in {config_file}:\n{e}") from e

        return all_repos, all_views


def generate_json_schema() -> dict[str, Any]:
    """Generate the JSON Schema for the Chantal configuration file.

    The schema is derived from the :class:`GlobalConfig` Pydantic model, so it
    is always in sync with the actual configuration validation. It can be used
    by editors (e.g. the VS Code YAML extension) for validation and
    autocompletion of ``config.yaml`` files.

    Returns:
        A JSON Schema (draft 2020-12) document as a dictionary.
    """
    schema = GlobalConfig.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = (
        "https://raw.githubusercontent.com/slauger/chantal/main/"
        "docs/schema/chantal-config.schema.json"
    )
    schema["title"] = "Chantal Configuration"
    return schema


def load_config(config_path: Path | None = None) -> GlobalConfig:
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
        raise FileNotFoundError(
            f"Configuration file not found: {os.environ['CHANTAL_CONFIG']} (from CHANTAL_CONFIG)"
        )
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
