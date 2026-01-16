from __future__ import annotations

"""
Pydantic models for APT/DEB repository metadata.
"""

from pydantic import BaseModel, Field


class DebMetadata(BaseModel):
    """
    Pydantic model for Debian package metadata.

    Based on the RFC822-style format used in APT Packages files.
    See: https://wiki.debian.org/DebianRepository/Format#A.22Packages.22_Indices
    """

    # Required fields
    package: str = Field(..., description="Package name")
    version: str = Field(..., description="Package version")
    architecture: str = Field(..., description="Package architecture (amd64, arm64, all, etc.)")
    filename: str = Field(..., description="Relative path to .deb file in pool/")
    size: int = Field(..., description="File size in bytes")
    sha256: str = Field(..., description="SHA256 checksum")

    # Optional fields with defaults
    component: str | None = Field(
        None, description="Repository component (main, contrib, non-free)"
    )
    description: str | None = Field(None, description="Short description")
    long_description: str | None = Field(None, description="Long description (multiple lines)")
    section: str | None = Field(None, description="Package section (admin, devel, libs, etc.)")
    priority: str | None = Field(
        None, description="Package priority (required, important, standard, optional, extra)"
    )
    homepage: str | None = Field(None, description="Upstream project homepage")
    bugs: str | None = Field(None, description="Bug tracking URL")

    # Dependency fields
    depends: str | None = Field(None, description="Runtime dependencies")
    pre_depends: str | None = Field(None, description="Pre-installation dependencies")
    recommends: str | None = Field(None, description="Recommended packages")
    suggests: str | None = Field(None, description="Suggested packages")
    enhances: str | None = Field(None, description="Packages enhanced by this package")
    breaks: str | None = Field(None, description="Packages broken by this package")
    conflicts: str | None = Field(None, description="Conflicting packages")
    replaces: str | None = Field(None, description="Packages replaced by this package")
    provides: str | None = Field(None, description="Virtual packages provided")

    # Maintainer information
    maintainer: str | None = Field(None, description="Package maintainer")
    original_maintainer: str | None = Field(
        None, description="Original maintainer (for derivative distros)"
    )

    # Build information
    source: str | None = Field(None, description="Source package name")
    built_using: str | None = Field(None, description="Packages used during build")
    essential: str | None = Field(None, description="Essential package flag (yes/no)")
    multi_arch: str | None = Field(None, description="Multi-arch support (same, foreign, allowed)")

    # Additional checksums
    md5sum: str | None = Field(None, description="MD5 checksum (legacy)")
    sha1: str | None = Field(None, description="SHA1 checksum")

    # Installed size
    installed_size: int | None = Field(None, description="Installed size in KiB")

    # Task metadata (Ubuntu-specific)
    task: str | None = Field(None, description="Task packages (Ubuntu)")

    # Additional fields stored as raw dictionary
    extra_fields: dict[str, str] = Field(
        default_factory=dict, description="Additional fields not explicitly modeled"
    )

    class Config:
        """Pydantic configuration."""

        extra = "allow"  # Allow additional fields for forward compatibility


class ReleaseMetadata(BaseModel):
    """
    Pydantic model for APT Release/InRelease file metadata.

    See: https://wiki.debian.org/DebianRepository/Format#A.22Release.22_files
    """

    # Required fields
    suite: str | None = Field(None, description="Suite name (stable, jammy, bookworm)")
    codename: str | None = Field(None, description="Codename (bullseye, focal)")
    architectures: list[str] = Field(default_factory=list, description="Supported architectures")
    components: list[str] = Field(
        default_factory=list, description="Repository components (main, contrib, non-free)"
    )

    # Optional metadata
    origin: str | None = Field(None, description="Distribution origin (Debian, Ubuntu)")
    label: str | None = Field(None, description="Distribution label")
    version: str | None = Field(None, description="Release version")
    description: str | None = Field(None, description="Release description")
    date: str | None = Field(None, description="Release date (RFC 2822 format)")
    valid_until: str | None = Field(None, description="Expiration date (RFC 2822 format)")

    # Acquire-By-Hash support
    acquire_by_hash: bool = Field(False, description="Acquire-By-Hash support enabled")

    # Checksums for metadata files
    md5sum: dict[str, tuple[str, int]] = Field(
        default_factory=dict, description="MD5 checksums: {filename: (checksum, size)}"
    )
    sha1: dict[str, tuple[str, int]] = Field(
        default_factory=dict, description="SHA1 checksums: {filename: (checksum, size)}"
    )
    sha256: dict[str, tuple[str, int]] = Field(
        default_factory=dict, description="SHA256 checksums: {filename: (checksum, size)}"
    )

    # Additional fields
    extra_fields: dict[str, str] = Field(default_factory=dict, description="Additional fields")

    class Config:
        """Pydantic configuration."""

        extra = "allow"


class SourcesMetadata(BaseModel):
    """
    Pydantic model for Debian source package metadata.

    Based on the RFC822-style format used in APT Sources files.
    """

    # Required fields
    package: str = Field(..., description="Source package name")
    version: str = Field(..., description="Source package version")

    # Optional fields
    binary: list[str] = Field(
        default_factory=list, description="Binary packages built from this source"
    )
    architecture: str | None = Field(None, description="Architectures for which source can build")
    maintainer: str | None = Field(None, description="Package maintainer")
    uploaders: list[str] = Field(default_factory=list, description="Additional uploaders")
    homepage: str | None = Field(None, description="Upstream homepage")
    section: str | None = Field(None, description="Package section")
    priority: str | None = Field(None, description="Package priority")

    # Dependency fields
    build_depends: str | None = Field(None, description="Build dependencies")
    build_depends_indep: str | None = Field(
        None, description="Architecture-independent build dependencies"
    )
    build_conflicts: str | None = Field(None, description="Build conflicts")
    build_conflicts_indep: str | None = Field(
        None, description="Architecture-independent build conflicts"
    )

    # VCS fields
    vcs_browser: str | None = Field(None, description="VCS web browser URL")
    vcs_git: str | None = Field(None, description="Git repository URL")
    vcs_svn: str | None = Field(None, description="SVN repository URL")
    vcs_bzr: str | None = Field(None, description="Bazaar repository URL")

    # Files
    directory: str | None = Field(None, description="Directory in pool/")
    files: list[dict[str, str]] = Field(
        default_factory=list, description="Source files (dsc, orig.tar.gz, debian.tar.xz)"
    )
    checksums_sha1: list[dict[str, str]] = Field(
        default_factory=list, description="SHA1 checksums for source files"
    )
    checksums_sha256: list[dict[str, str]] = Field(
        default_factory=list, description="SHA256 checksums for source files"
    )

    # Additional fields
    extra_fields: dict[str, str] = Field(default_factory=dict, description="Additional fields")

    class Config:
        """Pydantic configuration."""

        extra = "allow"
