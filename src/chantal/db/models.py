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
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


# Association table for many-to-many relationship between snapshots and packages
snapshot_packages = Table(
    "snapshot_packages",
    Base.metadata,
    Column("snapshot_id", Integer, ForeignKey("snapshots.id"), primary_key=True),
    Column("package_id", Integer, ForeignKey("packages.id"), primary_key=True),
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

    def __repr__(self) -> str:
        return f"<Repository(repo_id='{self.repo_id}', type='{self.type}')>"


class Package(Base):
    """Package model - represents a unique package file (RPM/DEB).

    Uses content-addressed storage - one package file can be referenced
    by multiple repositories and snapshots.
    """

    __tablename__ = "packages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Package identification
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(255), nullable=False)
    release: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    epoch: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    arch: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # Content addressing
    sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    # Storage
    pool_path: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # Relative path in pool (e.g., "ab/cd/abc123...rpm")

    # Package metadata
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Package type specific
    package_type: Mapped[str] = mapped_column(String(50), nullable=False)  # rpm, deb

    # Original filename
    filename: Mapped[str] = mapped_column(String(255), nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # Reference counting (for garbage collection)
    reference_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    snapshots: Mapped[list["Snapshot"]] = relationship(
        "Snapshot", secondary=snapshot_packages, back_populates="packages"
    )

    # Unique constraint on package identity
    __table_args__ = (
        UniqueConstraint(
            "name", "version", "release", "epoch", "arch", name="uq_package_identity"
        ),
    )

    def __repr__(self) -> str:
        return f"<Package(name='{self.name}', version='{self.version}', arch='{self.arch}', sha256='{self.sha256[:8]}...')>"

    @property
    def nevra(self) -> str:
        """Get NEVRA string (Name-Epoch:Version-Release.Arch)."""
        epoch_str = f"{self.epoch}:" if self.epoch else ""
        release_str = f"-{self.release}" if self.release else ""
        return f"{self.name}-{epoch_str}{self.version}{release_str}.{self.arch}"


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
    packages: Mapped[list["Package"]] = relationship(
        "Package", secondary=snapshot_packages, back_populates="snapshots"
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
