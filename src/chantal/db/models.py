"""
SQLAlchemy database models for Chantal.

This module defines the database schema for packages, repositories,
snapshots, and their relationships.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


# Association table for many-to-many relationship between repositories and content items
# This tracks which content items are currently in a repository (the "latest" state)
repository_content_items = Table(
    "repository_content_items",
    Base.metadata,
    Column("repository_id", Integer, ForeignKey("repositories.id"), primary_key=True),
    Column("content_item_id", Integer, ForeignKey("content_items.id"), primary_key=True),
    Column("added_at", DateTime, default=datetime.utcnow, nullable=False),
)

# Association table for many-to-many relationship between snapshots and content items
# This tracks immutable point-in-time copies of repository state
snapshot_content_items = Table(
    "snapshot_content_items",
    Base.metadata,
    Column("snapshot_id", Integer, ForeignKey("snapshots.id"), primary_key=True),
    Column("content_item_id", Integer, ForeignKey("content_items.id"), primary_key=True),
)

# Association table for many-to-many relationship between repositories and repository files
# This tracks which metadata/installer files are currently in a repository (the "latest" state)
repository_repository_files = Table(
    "repository_repository_files",
    Base.metadata,
    Column("repository_id", Integer, ForeignKey("repositories.id"), primary_key=True),
    Column("repository_file_id", Integer, ForeignKey("repository_files.id"), primary_key=True),
    Column("added_at", DateTime, default=datetime.utcnow, nullable=False),
)

# Association table for many-to-many relationship between snapshots and repository files
# This tracks immutable point-in-time copies of repository metadata/installer files
snapshot_repository_files = Table(
    "snapshot_repository_files",
    Base.metadata,
    Column("snapshot_id", Integer, ForeignKey("snapshots.id"), primary_key=True),
    Column("repository_file_id", Integer, ForeignKey("repository_files.id"), primary_key=True),
)


class Repository(Base):
    """Repository model - represents a configured RPM/APT repository."""

    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # rpm, apt
    feed: Mapped[str] = mapped_column(Text, nullable=False)  # upstream URL (Pulp terminology)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Paths
    latest_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    snapshots_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Sync state
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_sync_status: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )  # success, failed, running

    # Relationships
    snapshots: Mapped[list["Snapshot"]] = relationship(
        "Snapshot", back_populates="repository", cascade="all, delete-orphan"
    )
    sync_history: Mapped[list["SyncHistory"]] = relationship(
        "SyncHistory", back_populates="repository", cascade="all, delete-orphan"
    )
    content_items: Mapped[list["ContentItem"]] = relationship(
        "ContentItem", secondary=repository_content_items, back_populates="repositories"
    )
    repository_files: Mapped[list["RepositoryFile"]] = relationship(
        "RepositoryFile", secondary=repository_repository_files, back_populates="repositories"
    )

    def __repr__(self) -> str:
        return f"<Repository(repo_id='{self.repo_id}', type='{self.type}')>"


class ContentItem(Base):
    """Generic content model for all package types (RPM, Helm, APT, PyPI, etc.).

    Uses content-addressed storage - one content item file can be referenced
    by multiple repositories and snapshots.

    Type-specific metadata is stored as JSON in the metadata field.
    """

    __tablename__ = "content_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Content type (determines which plugin handles it)
    content_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # Values: 'rpm', 'helm', 'pypi', 'npm', 'rubygems', 'nuget', 'go', 'apt', 'apk', 'terraform', etc.

    # Universal fields (all content types have these)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # Content addressing (pool storage)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    pool_path: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # Relative path in pool (e.g., "ab/cd/abc123...rpm")
    filename: Mapped[str] = mapped_column(String(255), nullable=False)

    # Type-specific metadata as JSON
    # Structure depends on content_type:
    # - rpm: {epoch, release, arch, summary, description, provides, requires, ...}
    # - helm: {app_version, keywords, maintainers, icon, dependencies, ...}
    # - pypi: {python_requires, author, license, requires_dist, file_type, ...}
    # - etc.
    # Note: Named 'content_metadata' because 'metadata' is reserved by SQLAlchemy
    content_metadata: Mapped[dict] = mapped_column(JSON, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # Reference counting (for garbage collection)
    reference_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships (generic)
    repositories: Mapped[list["Repository"]] = relationship(
        "Repository", secondary=repository_content_items, back_populates="content_items"
    )
    snapshots: Mapped[list["Snapshot"]] = relationship(
        "Snapshot", secondary=snapshot_content_items, back_populates="content_items"
    )

    # Composite indexes for common queries
    __table_args__ = (
        Index("idx_content_type_name", "content_type", "name"),
        Index("idx_content_type_name_version", "content_type", "name", "version"),
    )

    def __repr__(self) -> str:
        return f"<ContentItem(type='{self.content_type}', name='{self.name}', version='{self.version}', sha256='{self.sha256[:8]}...')>"

    @property
    def nevra(self) -> Optional[str]:
        """Get NEVRA string for RPM packages (Name-Epoch:Version-Release.Arch).

        Returns None for non-RPM content types.
        """
        if self.content_type != "rpm":
            return None

        epoch = self.content_metadata.get("epoch", "")
        release = self.content_metadata.get("release", "")
        arch = self.content_metadata.get("arch", "")

        epoch_str = f"{epoch}:" if epoch else ""
        release_str = f"-{release}" if release else ""
        return f"{self.name}-{epoch_str}{self.version}{release_str}.{arch}"


class Snapshot(Base):
    """Snapshot model - represents an immutable point-in-time repository state.

    A snapshot is a collection of packages. Multiple snapshots can reference
    the same package (content-addressed storage with reference counting).
    """

    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("repositories.id"), nullable=False
    )

    # Snapshot identification
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # State
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    published_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Statistics (cached for performance)
    package_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    repository: Mapped["Repository"] = relationship("Repository", back_populates="snapshots")
    content_items: Mapped[list["ContentItem"]] = relationship(
        "ContentItem", secondary=snapshot_content_items, back_populates="snapshots"
    )
    repository_files: Mapped[list["RepositoryFile"]] = relationship(
        "RepositoryFile", secondary=snapshot_repository_files, back_populates="snapshots"
    )

    # Unique constraint: snapshot name must be unique per repository
    __table_args__ = (UniqueConstraint("repository_id", "name", name="uq_snapshot_name"),)

    def __repr__(self) -> str:
        return f"<Snapshot(name='{self.name}', repository_id={self.repository_id}, packages={self.package_count})>"


class SyncHistory(Base):
    """Sync history model - tracks repository synchronization events."""

    __tablename__ = "sync_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("repositories.id"), nullable=False
    )

    # Sync timing
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Sync result
    status: Mapped[str] = mapped_column(String(50), nullable=False)  # running, success, failed
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Statistics
    packages_added: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    packages_removed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    packages_updated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bytes_downloaded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Snapshot created during this sync
    snapshot_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("snapshots.id"), nullable=True
    )

    # Relationships
    repository: Mapped["Repository"] = relationship("Repository", back_populates="sync_history")
    snapshot: Mapped[Optional["Snapshot"]] = relationship("Snapshot")

    def __repr__(self) -> str:
        return f"<SyncHistory(repository_id={self.repository_id}, status='{self.status}', started_at='{self.started_at}')>"

    @property
    def duration_seconds(self) -> Optional[float]:
        """Calculate sync duration in seconds."""
        if self.started_at and self.completed_at:
            delta = self.completed_at - self.started_at
            return delta.total_seconds()
        return None


class View(Base):
    """View model - groups multiple repositories into a single virtual repository.

    A view is a collection of repositories that can be published together as one.
    Views can be published as "latest" (mutable) or as snapshots (immutable).
    """

    __tablename__ = "views"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # View identification
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Repository type (all repos in view must have same type)
    repo_type: Mapped[str] = mapped_column(String(50), nullable=False)  # rpm, apt

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Publishing status (for "latest" publish)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    published_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    view_repositories: Mapped[list["ViewRepository"]] = relationship(
        "ViewRepository", back_populates="view", cascade="all, delete-orphan"
    )
    view_snapshots: Mapped[list["ViewSnapshot"]] = relationship(
        "ViewSnapshot", back_populates="view", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<View(name='{self.name}', type='{self.repo_type}')>"


class ViewRepository(Base):
    """Junction table: View -> Repositories (with ordering).

    Defines which repositories are part of a view and their precedence order.
    """

    __tablename__ = "view_repositories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    view_id: Mapped[int] = mapped_column(Integer, ForeignKey("views.id"), nullable=False)
    repository_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("repositories.id"), nullable=False
    )

    # Order/precedence for metadata merging (lower = higher priority)
    order: Mapped[int] = mapped_column(Integer, nullable=False)

    # Timestamps
    added_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # Relationships
    view: Mapped["View"] = relationship("View", back_populates="view_repositories")
    repository: Mapped["Repository"] = relationship("Repository")

    # Unique constraint: repository can only be in view once
    __table_args__ = (
        UniqueConstraint("view_id", "repository_id", name="uq_view_repository"),
    )

    def __repr__(self) -> str:
        return f"<ViewRepository(view_id={self.view_id}, repository_id={self.repository_id}, order={self.order})>"


class ViewSnapshot(Base):
    """View snapshot model - represents an atomic snapshot of all repositories in a view.

    When creating a view snapshot, all repositories in the view are snapshotted
    simultaneously, creating an immutable point-in-time state of the entire view.
    """

    __tablename__ = "view_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    view_id: Mapped[int] = mapped_column(Integer, ForeignKey("views.id"), nullable=False)

    # Snapshot identification
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # State
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # Which repository snapshots are included (JSON array of snapshot IDs)
    # Example: [12, 45, 67] - references Snapshot.id
    snapshot_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False)

    # Publishing status
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    published_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Statistics (cached for performance)
    package_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    view: Mapped["View"] = relationship("View", back_populates="view_snapshots")

    # Unique constraint: snapshot name must be unique per view
    __table_args__ = (UniqueConstraint("view_id", "name", name="uq_view_snapshot_name"),)

    def __repr__(self) -> str:
        return f"<ViewSnapshot(name='{self.name}', view_id={self.view_id}, snapshots={len(self.snapshot_ids)})>"


class RepositoryFile(Base):
    """Repository metadata and installer files.

    Stores non-package files like:
    - Metadata: updateinfo.xml, filelists.xml, comps.xml, modules.yaml, etc.
    - Signatures: repomd.xml.asc, Release.gpg
    - Kickstart: vmlinuz, initrd.img, .treeinfo
    - Debian installer: debian-installer/
    - SUSE specific: susedata.xml, patterns.xml, products.xml

    Uses content-addressed storage like ContentItem - files can be shared
    across multiple repositories and snapshots.
    """

    __tablename__ = "repository_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Classification (NO ENUM - flexible for future SUSE/other formats!)
    file_category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # Values: "metadata", "signature", "kickstart", "debian-installer"

    file_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # Values: "updateinfo", "filelists", "comps", "modules",
    #         "vmlinuz", "initrd", ".treeinfo",
    #         "susedata", "suseinfo", "patterns", "products" (SUSE future)

    # Content-addressed storage (in pool/files/ subdirectory)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    pool_path: Mapped[str] = mapped_column(Text, nullable=False)
    # Format: "files/ab/cd/abc123_updateinfo.xml.gz"
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    # Publishing path (preserve exact upstream structure)
    original_path: Mapped[str] = mapped_column(Text, nullable=False)
    # Examples:
    #   "repodata/abc123-updateinfo.xml.gz"
    #   "images/pxeboot/vmlinuz"
    #   ".treeinfo"
    #   "v3.19/main/x86_64/APKINDEX.tar.gz"

    # Flexible metadata (type-specific info stored as JSON)
    # Note: Named 'file_metadata' because 'metadata' is reserved by SQLAlchemy
    file_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # Examples:
    #   {"checksum_type": "sha256", "open_checksum": "xyz", "timestamp": 123456}
    #   {"kernel_version": "5.14.0-362.8.1.el9_3"}

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships (many-to-many like ContentItem)
    repositories: Mapped[list["Repository"]] = relationship(
        "Repository", secondary=repository_repository_files, back_populates="repository_files"
    )
    snapshots: Mapped[list["Snapshot"]] = relationship(
        "Snapshot", secondary=snapshot_repository_files, back_populates="repository_files"
    )

    # Indexes for common queries
    __table_args__ = (
        # Composite index for common query: "get all updateinfo files for repo X"
        Index("idx_repo_file_category", "file_category"),
        Index("idx_repo_file_type", "file_type"),
    )

    def __repr__(self) -> str:
        return f"<RepositoryFile(category='{self.file_category}', type='{self.file_type}', path='{self.original_path}', sha256='{self.sha256[:8]}...')>"
