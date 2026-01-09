# Chantal Architecture Proposal

**Erstellt:** 2025-01-09
**Status:** Draft v1
**Sprache:** Python 3.11+

---

## Inhaltsverzeichnis

1. [Executive Summary](#executive-summary)
2. [Architektur-Übersicht](#architektur-übersicht)
3. [Component-Design](#component-design)
4. [Datenmodell & Datenbank](#datenmodell--datenbank)
5. [Storage-Architektur](#storage-architektur)
6. [Plugin-System](#plugin-system)
7. [CLI-Interface](#cli-interface)
8. [Konfiguration](#konfiguration)
9. [Data-Flow](#data-flow)
10. [Technology Stack](#technology-stack)
11. [Deployment & Installation](#deployment--installation)
12. [Sicherheit](#sicherheit)
13. [Performance-Considerations](#performance-considerations)
14. [Testing-Strategie](#testing-strategie)
15. [Offene Fragen](#offene-fragen)

---

## Executive Summary

**Chantal** ist ein Python-basiertes CLI-Tool für Offline-Mirroring von APT- und RPM-Repositories mit folgenden Kernfeatures:

- **Unified:** Ein Tool für APT + RPM (später evtl. PyPI)
- **Dedupliziert:** Content-Addressed Storage mit SHA256
- **Snapshots:** Immutable Repository-Versionen für Patch-Management
- **Enterprise-Ready:** Red Hat Subscription-Auth via Client-Zertifikate
- **Einfach:** CLI-only, kein Daemon, kein Service-Stack

**Technologie:**
- Python 3.11+ (Async/Await, Type Hints)
- PostgreSQL (Metadaten, Snapshots, State)
- SQLAlchemy 2.0 (ORM)
- Click (CLI Framework)
- Requests (HTTP Client mit TLS/Client-Cert Support)
- Plugin-basierte Architektur

**Zielgruppe:**
- Unternehmen mit Air-Gapped Systemen
- Patch-Management-Teams
- DevOps-Teams die reproduzierbare Environments brauchen

---

## Architektur-Übersicht

### High-Level Architektur

```
┌─────────────────────────────────────────────────────────────┐
│                         Chantal CLI                         │
│                    (Click-based Commands)                   │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                      Core Engine                            │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   Config    │  │  Repository  │  │   Snapshot   │      │
│  │  Manager    │  │   Manager    │  │   Manager    │      │
│  └─────────────┘  └──────────────┘  └──────────────┘      │
│                                                             │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   Storage   │  │   Download   │  │   Publish    │      │
│  │  Manager    │  │   Manager    │  │   Manager    │      │
│  └─────────────┘  └──────────────┘  └──────────────┘      │
└────────────┬────────────────────────────────────┬──────────┘
             │                                    │
             ▼                                    ▼
┌────────────────────────┐          ┌────────────────────────┐
│   Plugin System        │          │   Database Layer       │
│                        │          │   (SQLAlchemy)         │
│  ┌──────────────────┐  │          │                        │
│  │   RPM Plugin     │  │          │  ┌──────────────────┐  │
│  │  - repomd.xml   │  │          │  │   PostgreSQL     │  │
│  │  - primary.xml  │  │          │  │                  │  │
│  │  - .rpm files   │  │          │  │  - packages      │  │
│  └──────────────────┘  │          │  │  - repositories  │  │
│                        │          │  │  - snapshots     │  │
│  ┌──────────────────┐  │          │  │  - sync_history  │  │
│  │   APT Plugin     │  │          │  └──────────────────┘  │
│  │  - InRelease    │  │          │                        │
│  │  - Packages.gz  │  │          └────────────────────────┘
│  │  - .deb files   │  │
│  └──────────────────┘  │
│                        │
└────────────────────────┘
             │
             ▼
┌────────────────────────────────────────────────────────────┐
│                   Content Pool                             │
│              (SHA256-based Storage)                        │
│                                                            │
│  data/sha256/ab/cd/abcdef123...456_package.rpm            │
│  data/sha256/12/34/123456789...abc_package.deb            │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

### Daten-Flow (Sync Operation)

```
Upstream Repo → Download Manager → Storage Manager → Database
     │                 │                   │              │
     │                 │                   │              │
     ▼                 ▼                   ▼              ▼
  Plugin          HTTP Client        SHA256 Hash      Package
  parses          downloads          dedup check      metadata
  metadata        packages           store file       persisted
```

### Daten-Flow (Publish Operation)

```
Database → Snapshot Manager → Publish Manager → Published Repo
   │             │                   │                  │
   │             │                   │                  │
   ▼             ▼                   ▼                  ▼
Get package   Select        Create hardlinks/        Ready for
references    packages      symlinks + metadata      webserver
```

---

## Component-Design

### 1. Core Engine

**Datei:** `chantal/core/engine.py`

**Verantwortlichkeiten:**
- Koordination aller Operationen
- Transaction-Management
- Error-Handling & Rollback
- Progress-Reporting

**Klassen:**

```python
class ChantalEngine:
    """Main orchestrator for all Chantal operations."""

    def __init__(self, config: Config, db: Database):
        self.config = config
        self.db = db
        self.storage = StorageManager(config.storage_path)
        self.download = DownloadManager(config)
        self.plugins = PluginRegistry.load_all()

    async def sync_repository(
        self,
        repo_name: str,
        create_snapshot: bool = False
    ) -> SyncResult:
        """Sync a repository from upstream."""
        pass

    async def create_snapshot(
        self,
        repo_name: str,
        snapshot_name: Optional[str] = None
    ) -> Snapshot:
        """Create immutable snapshot of repository."""
        pass

    async def publish_snapshot(
        self,
        snapshot_name: str,
        target_path: Path
    ) -> None:
        """Publish snapshot to filesystem."""
        pass
```

### 2. Configuration Manager

**Datei:** `chantal/core/config.py`

**Verantwortlichkeiten:**
- YAML Config laden & validieren
- Credential-Management
- Environment-Variable-Substitution

**Klassen:**

```python
from pydantic import BaseModel, Field
from typing import Literal, Optional, List

class CredentialConfig(BaseModel):
    """Base credential configuration."""
    type: Literal["none", "basic", "client_cert", "subscription_manager"]

class ClientCertCredential(CredentialConfig):
    """Client certificate authentication."""
    type: Literal["client_cert"] = "client_cert"
    cert: Path
    key: Path
    ca_cert: Optional[Path] = None

class BasicAuthCredential(CredentialConfig):
    """HTTP Basic authentication."""
    type: Literal["basic"] = "basic"
    username: str
    password: Optional[str] = None  # or from password_command
    password_command: Optional[str] = None

class SubscriptionManagerCredential(CredentialConfig):
    """Auto-discovery via subscription-manager."""
    type: Literal["subscription_manager"] = "subscription_manager"

class RpmRepoConfig(BaseModel):
    """RPM repository configuration."""
    name: str
    type: Literal["rpm"] = "rpm"
    upstream: str
    enabled: bool = True
    credentials: Optional[CredentialConfig] = None
    gpgcheck: bool = True
    architectures: List[str] = ["x86_64"]

class AptRepoConfig(BaseModel):
    """APT repository configuration."""
    name: str
    type: Literal["apt"] = "apt"
    upstream: str
    distribution: str
    components: List[str]
    enabled: bool = True
    credentials: Optional[CredentialConfig] = None
    architectures: List[str] = ["amd64"]

class StorageConfig(BaseModel):
    """Storage configuration."""
    base_path: Path = Path("/var/lib/chantal")
    pool_path: Optional[Path] = None  # defaults to base_path/data
    repo_path: Optional[Path] = None  # defaults to base_path/repos
    snapshot_path: Optional[Path] = None  # defaults to base_path/snapshots

class DatabaseConfig(BaseModel):
    """Database configuration."""
    url: str = "postgresql://chantal:chantal@localhost/chantal"
    pool_size: int = 5
    echo: bool = False

class ChantalConfig(BaseModel):
    """Main Chantal configuration."""
    storage: StorageConfig = Field(default_factory=StorageConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    repositories: List[RpmRepoConfig | AptRepoConfig] = []

    @classmethod
    def from_yaml(cls, path: Path) -> "ChantalConfig":
        """Load configuration from YAML file."""
        import yaml
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(**data)
```

### 3. Storage Manager

**Datei:** `chantal/core/storage.py`

**Verantwortlichkeiten:**
- Content-Addressed Storage (SHA256)
- Deduplication
- File-Operations (hardlinks, symlinks)
- Cleanup unreferenced files

**Klassen:**

```python
class StorageManager:
    """Manages content-addressed storage pool."""

    def __init__(self, base_path: Path):
        self.base_path = base_path
        self.pool_path = base_path / "data" / "sha256"
        self.pool_path.mkdir(parents=True, exist_ok=True)

    def store_file(self, source: Path, sha256: str) -> Path:
        """
        Store file in content-addressed pool.

        Returns path to stored file. If file already exists (by hash),
        returns existing path without storing duplicate.
        """
        target = self._get_pool_path(sha256, source.name)

        if target.exists():
            # Already in pool, verify hash
            if self._verify_hash(target, sha256):
                return target
            else:
                raise IntegrityError(f"Hash mismatch for {target}")

        # Store new file
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

        # Verify stored file
        if not self._verify_hash(target, sha256):
            target.unlink()
            raise IntegrityError(f"Failed to store {source}")

        return target

    def _get_pool_path(self, sha256: str, filename: str) -> Path:
        """
        Get pool path for given SHA256 hash.

        Layout: pool/sha256/ab/cd/abcdef123...456_filename
        """
        return self.pool_path / sha256[:2] / sha256[2:4] / f"{sha256}_{filename}"

    def create_hardlink(self, pool_file: Path, target: Path) -> None:
        """Create hardlink from pool to published location."""
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.unlink()
        os.link(pool_file, target)

    def cleanup_unreferenced(self, db: Database) -> int:
        """Remove files from pool that are not referenced in database."""
        referenced_hashes = db.get_all_package_hashes()
        removed_count = 0

        for pool_file in self.pool_path.rglob("*"):
            if not pool_file.is_file():
                continue

            # Extract hash from filename: hash_filename
            sha256 = pool_file.name.split("_")[0]

            if sha256 not in referenced_hashes:
                pool_file.unlink()
                removed_count += 1

        return removed_count
```

### 4. Download Manager

**Datei:** `chantal/core/download.py`

**Verantwortlichkeiten:**
- HTTP/HTTPS Downloads
- Client-Certificate Auth
- Retry Logic & Resume
- Progress Tracking
- Parallel Downloads

**Klassen:**

```python
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

class DownloadManager:
    """Manages HTTP downloads with retry, resume, and authentication."""

    def __init__(self, config: ChantalConfig):
        self.config = config
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        """Create requests session with retry logic."""
        session = requests.Session()

        retry = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )

        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session

    async def download_file(
        self,
        url: str,
        destination: Path,
        credentials: Optional[CredentialConfig] = None,
        expected_hash: Optional[str] = None,
        progress_callback: Optional[Callable] = None
    ) -> Path:
        """
        Download file with authentication and verification.

        Supports:
        - Client certificates
        - HTTP Basic Auth
        - Resume (Range requests)
        - Hash verification
        """
        # Setup authentication
        kwargs = {}
        if credentials:
            if isinstance(credentials, ClientCertCredential):
                kwargs["cert"] = (str(credentials.cert), str(credentials.key))
                if credentials.ca_cert:
                    kwargs["verify"] = str(credentials.ca_cert)
            elif isinstance(credentials, BasicAuthCredential):
                password = self._get_password(credentials)
                kwargs["auth"] = (credentials.username, password)

        # Check if partial download exists
        headers = {}
        if destination.exists() and destination.stat().st_size > 0:
            headers["Range"] = f"bytes={destination.stat().st_size}-"
            mode = "ab"
        else:
            mode = "wb"

        # Download
        response = self.session.get(url, stream=True, headers=headers, **kwargs)
        response.raise_for_status()

        total_size = int(response.headers.get("content-length", 0))

        with open(destination, mode) as f:
            downloaded = 0
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded, total_size)

        # Verify hash
        if expected_hash:
            actual_hash = self._calculate_sha256(destination)
            if actual_hash != expected_hash:
                destination.unlink()
                raise IntegrityError(f"Hash mismatch: {url}")

        return destination

    def _get_password(self, creds: BasicAuthCredential) -> str:
        """Get password from config or execute password_command."""
        if creds.password:
            return creds.password
        elif creds.password_command:
            import subprocess
            result = subprocess.run(
                creds.password_command,
                shell=True,
                capture_output=True,
                text=True
            )
            return result.stdout.strip()
        else:
            raise ValueError("No password or password_command configured")

    @staticmethod
    def _calculate_sha256(path: Path) -> str:
        """Calculate SHA256 hash of file."""
        import hashlib
        sha256 = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
```

### 5. Repository Manager

**Datei:** `chantal/core/repository.py`

**Verantwortlichkeiten:**
- Repository CRUD Operations
- Sync Orchestration (via Plugins)
- State Tracking

**Klassen:**

```python
class RepositoryManager:
    """Manages repository operations."""

    def __init__(self, db: Database, storage: StorageManager, download: DownloadManager):
        self.db = db
        self.storage = storage
        self.download = download

    async def sync(
        self,
        repo_config: RpmRepoConfig | AptRepoConfig,
        plugin: RepoPlugin
    ) -> SyncResult:
        """
        Sync repository from upstream using appropriate plugin.
        """
        # Start sync tracking
        sync_record = self.db.start_sync(repo_config.name)

        try:
            # Plugin-specific sync
            result = await plugin.sync(
                config=repo_config,
                storage=self.storage,
                download=self.download,
                db=self.db
            )

            # Update sync record
            self.db.complete_sync(
                sync_record.id,
                status="success",
                packages_added=result.packages_added,
                packages_removed=result.packages_removed,
                bytes_downloaded=result.bytes_downloaded
            )

            return result

        except Exception as e:
            self.db.complete_sync(sync_record.id, status="failed", error=str(e))
            raise
```

### 6. Snapshot Manager

**Datei:** `chantal/core/snapshot.py`

**Verantwortlichkeiten:**
- Snapshot Creation (immutable package lists)
- Snapshot Merge
- Snapshot Diff
- Snapshot Cleanup

**Klassen:**

```python
from enum import Enum

class MergeStrategy(Enum):
    """Snapshot merge strategies."""
    RIGHTMOST = "rightmost"  # Last snapshot wins
    LATEST = "latest"  # Highest version wins
    KEEP_ALL = "keep_all"  # Keep all versions

class SnapshotManager:
    """Manages immutable repository snapshots."""

    def __init__(self, db: Database):
        self.db = db

    def create_snapshot(
        self,
        repo_name: str,
        snapshot_name: Optional[str] = None
    ) -> Snapshot:
        """
        Create immutable snapshot of current repository state.

        Snapshot is just a list of package IDs from database.
        No files are copied - packages remain in pool.
        """
        if not snapshot_name:
            snapshot_name = f"{repo_name}-{datetime.now().strftime('%Y-%m-%d-%H%M%S')}"

        # Get current package IDs for repository
        package_ids = self.db.get_repository_package_ids(repo_name)

        # Create snapshot
        snapshot = self.db.create_snapshot(
            name=snapshot_name,
            repository_name=repo_name,
            package_ids=package_ids
        )

        return snapshot

    def merge_snapshots(
        self,
        snapshot_names: List[str],
        merged_name: str,
        strategy: MergeStrategy = MergeStrategy.RIGHTMOST
    ) -> Snapshot:
        """
        Merge multiple snapshots into new snapshot.

        Strategies:
        - RIGHTMOST: If duplicate (name, arch, version), take from last snapshot
        - LATEST: If duplicate (name, arch), take highest version
        - KEEP_ALL: Keep all versions (may have conflicts)
        """
        all_packages = []

        for snapshot_name in snapshot_names:
            packages = self.db.get_snapshot_packages(snapshot_name)
            all_packages.extend(packages)

        # Apply merge strategy
        if strategy == MergeStrategy.RIGHTMOST:
            merged = self._merge_rightmost(all_packages)
        elif strategy == MergeStrategy.LATEST:
            merged = self._merge_latest(all_packages)
        else:  # KEEP_ALL
            merged = all_packages

        # Create new snapshot
        package_ids = [pkg.id for pkg in merged]
        snapshot = self.db.create_snapshot(
            name=merged_name,
            repository_name=None,  # Merged snapshots have no single repo
            package_ids=package_ids
        )

        return snapshot

    def diff_snapshots(
        self,
        snapshot_a: str,
        snapshot_b: str
    ) -> SnapshotDiff:
        """
        Compare two snapshots.

        Returns packages added, removed, and updated.
        """
        packages_a = set(self.db.get_snapshot_package_ids(snapshot_a))
        packages_b = set(self.db.get_snapshot_package_ids(snapshot_b))

        added = packages_b - packages_a
        removed = packages_a - packages_b

        return SnapshotDiff(
            added=self.db.get_packages_by_ids(added),
            removed=self.db.get_packages_by_ids(removed)
        )
```

### 7. Publish Manager

**Datei:** `chantal/core/publish.py`

**Verantwortlichkeiten:**
- Publish Snapshots to Filesystem
- Create Hardlinks from Pool
- Generate/Copy Metadata
- Atomic Switching

**Klassen:**

```python
class PublishManager:
    """Manages publishing snapshots to filesystem."""

    def __init__(self, storage: StorageManager, db: Database):
        self.storage = storage
        self.db = db

    async def publish_snapshot(
        self,
        snapshot_name: str,
        target_path: Path,
        plugin: RepoPlugin
    ) -> None:
        """
        Publish snapshot to filesystem.

        1. Get packages from snapshot
        2. Create hardlinks from pool to target
        3. Generate/copy metadata via plugin
        """
        # Get snapshot packages
        snapshot = self.db.get_snapshot(snapshot_name)
        packages = self.db.get_snapshot_packages(snapshot_name)

        # Create temp directory for atomic publish
        temp_path = target_path.parent / f".{target_path.name}.tmp"
        temp_path.mkdir(parents=True, exist_ok=True)

        try:
            # Let plugin publish
            await plugin.publish(
                packages=packages,
                storage=self.storage,
                target_path=temp_path
            )

            # Atomic switch
            if target_path.exists():
                old_path = target_path.parent / f".{target_path.name}.old"
                target_path.rename(old_path)

            temp_path.rename(target_path)

            # Cleanup old
            if old_path.exists():
                shutil.rmtree(old_path)

        except Exception as e:
            # Cleanup temp on failure
            if temp_path.exists():
                shutil.rmtree(temp_path)
            raise
```

---

## Datenmodell & Datenbank

### SQLAlchemy Models

**Datei:** `chantal/db/models.py`

```python
from sqlalchemy import Column, Integer, String, BigInteger, DateTime, Boolean, Text, ForeignKey, Table, JSON
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime

Base = declarative_base()

# Association table for snapshot-package many-to-many
snapshot_packages = Table(
    'snapshot_packages',
    Base.metadata,
    Column('snapshot_id', Integer, ForeignKey('snapshots.id'), primary_key=True),
    Column('package_id', Integer, ForeignKey('packages.id'), primary_key=True)
)

class Package(Base):
    """Deduplicated package storage."""
    __tablename__ = 'packages'

    id = Column(Integer, primary_key=True)
    sha256 = Column(String(64), unique=True, nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    size = Column(BigInteger, nullable=False)
    package_type = Column(String(10), nullable=False)  # 'rpm' or 'deb'
    arch = Column(String(20))
    name = Column(String(255), nullable=False, index=True)
    version = Column(String(100), nullable=False)
    metadata = Column(JSON)  # Type-specific metadata
    first_seen = Column(DateTime, default=datetime.utcnow)

    # Relationships
    snapshots = relationship("Snapshot", secondary=snapshot_packages, back_populates="packages")

    __table_args__ = (
        # Ensure unique (type, arch, name, version, sha256)
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4'}
    )

class Repository(Base):
    """Repository configuration and state."""
    __tablename__ = 'repositories'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    type = Column(String(10), nullable=False)  # 'rpm' or 'apt'
    upstream_url = Column(Text)
    config = Column(JSON)  # Full repository config
    enabled = Column(Boolean, default=True)
    last_sync = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    snapshots = relationship("Snapshot", back_populates="repository")
    sync_history = relationship("SyncHistory", back_populates="repository")

class Snapshot(Base):
    """Immutable repository snapshot."""
    __tablename__ = 'snapshots'

    id = Column(Integer, primary_key=True)
    name = Column(String(200), unique=True, nullable=False, index=True)
    repository_id = Column(Integer, ForeignKey('repositories.id'), nullable=True)  # Null for merged snapshots
    created_at = Column(DateTime, default=datetime.utcnow)
    immutable = Column(Boolean, default=True)
    description = Column(Text)

    # Relationships
    repository = relationship("Repository", back_populates="snapshots")
    packages = relationship("Package", secondary=snapshot_packages, back_populates="snapshots")

class SyncHistory(Base):
    """Track sync operations."""
    __tablename__ = 'sync_history'

    id = Column(Integer, primary_key=True)
    repository_id = Column(Integer, ForeignKey('repositories.id'), nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    status = Column(String(20))  # 'running', 'success', 'failed'
    packages_added = Column(Integer)
    packages_removed = Column(Integer)
    bytes_downloaded = Column(BigInteger)
    error_message = Column(Text)

    # Relationships
    repository = relationship("Repository", back_populates="sync_history")
```

### Database Queries

**Datei:** `chantal/db/queries.py`

```python
from sqlalchemy.orm import Session
from typing import List, Set

class Database:
    """Database operations wrapper."""

    def __init__(self, engine):
        self.engine = engine
        Base.metadata.create_all(engine)

    def get_or_create_package(
        self,
        session: Session,
        sha256: str,
        filename: str,
        **kwargs
    ) -> tuple[Package, bool]:
        """Get existing package by hash or create new."""
        package = session.query(Package).filter_by(sha256=sha256).first()

        if package:
            return package, False

        package = Package(
            sha256=sha256,
            filename=filename,
            **kwargs
        )
        session.add(package)
        return package, True

    def get_all_package_hashes(self) -> Set[str]:
        """Get all SHA256 hashes referenced in database."""
        with Session(self.engine) as session:
            result = session.query(Package.sha256).all()
            return {row[0] for row in result}

    def create_snapshot(
        self,
        name: str,
        repository_name: Optional[str],
        package_ids: List[int]
    ) -> Snapshot:
        """Create immutable snapshot."""
        with Session(self.engine) as session:
            repo = None
            if repository_name:
                repo = session.query(Repository).filter_by(name=repository_name).first()

            snapshot = Snapshot(
                name=name,
                repository_id=repo.id if repo else None
            )

            # Add package references
            packages = session.query(Package).filter(Package.id.in_(package_ids)).all()
            snapshot.packages = packages

            session.add(snapshot)
            session.commit()

            return snapshot
```

---

## Storage-Architektur

### Filesystem-Layout

```
/var/lib/chantal/
├── data/                           # Content Pool
│   └── sha256/                     # SHA256-based storage
│       ├── ab/
│       │   └── cd/
│       │       ├── abcdef123...456_package-1.0.rpm
│       │       └── abcdef789...012_package-2.0.rpm
│       ├── 12/
│       │   └── 34/
│       │       └── 123456789...abc_package_1.0_amd64.deb
│       └── ...
│
├── repos/                          # Published Repositories
│   ├── rhel9-baseos/               # RPM Repository
│   │   ├── Packages/               # Hardlinks → data/
│   │   │   ├── a/
│   │   │   │   └── awesome-1.0.rpm  -> ../../data/sha256/.../abc...def_awesome-1.0.rpm
│   │   │   └── ...
│   │   └── repodata/               # RPM Metadata
│   │       ├── repomd.xml
│   │       ├── repomd.xml.asc      # GPG signature
│   │       ├── primary.xml.gz
│   │       ├── filelists.xml.gz
│   │       └── other.xml.gz
│   │
│   └── ubuntu-jammy/               # APT Repository
│       ├── dists/
│       │   └── jammy/
│       │       ├── InRelease       # GPG-signed Release
│       │       ├── Release
│       │       ├── Release.gpg
│       │       └── main/
│       │           ├── binary-amd64/
│       │           │   ├── Packages
│       │           │   ├── Packages.gz
│       │           │   └── Packages.xz
│       │           └── source/
│       │               └── Sources.gz
│       └── pool/                   # Hardlinks → data/
│           └── main/
│               ├── a/
│               │   └── awesome/
│               │       └── awesome_1.0_amd64.deb -> ../../../../data/sha256/.../123...abc_awesome_1.0_amd64.deb
│               └── ...
│
├── snapshots/                      # Snapshot Filesystem Representations (optional)
│   ├── rhel9-baseos-2025-01-09/    # Symlink to published snapshot
│   ├── rhel9-baseos-2025-01-15/
│   └── latest -> rhel9-baseos-2025-01-15/
│
├── cache/                          # Temporary & Cache
│   ├── http/                       # HTTP cache (ETags, etc.)
│   └── downloads/                  # Partial downloads for resume
│
└── chantal.db                      # SQLite (optional, if not using PostgreSQL)
```

### Deduplication-Logic

```python
def store_package(package_path: Path, metadata: dict) -> Package:
    """
    Store package with automatic deduplication.

    1. Calculate SHA256
    2. Check if hash exists in database
    3. If exists: Return existing package (no copy)
    4. If new: Copy to pool, store metadata
    """
    sha256 = calculate_sha256(package_path)

    # Check database
    package = db.get_package_by_hash(sha256)
    if package:
        logger.info(f"Package already in pool: {sha256}")
        return package

    # Store in pool
    pool_path = storage.store_file(package_path, sha256)

    # Create database entry
    package = db.create_package(
        sha256=sha256,
        filename=package_path.name,
        size=package_path.stat().st_size,
        **metadata
    )

    return package
```

---

## Plugin-System

### Plugin Interface

**Datei:** `chantal/plugins/base.py`

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List

@dataclass
class SyncResult:
    """Result of repository sync operation."""
    packages_added: int
    packages_removed: int
    packages_updated: int
    bytes_downloaded: int
    duration_seconds: float

class RepoPlugin(ABC):
    """Base class for repository type plugins."""

    @property
    @abstractmethod
    def type_name(self) -> str:
        """Plugin type identifier (e.g., 'rpm', 'apt')."""
        pass

    @abstractmethod
    async def sync(
        self,
        config: RpmRepoConfig | AptRepoConfig,
        storage: StorageManager,
        download: DownloadManager,
        db: Database
    ) -> SyncResult:
        """
        Sync repository from upstream.

        Responsibilities:
        1. Download & parse metadata
        2. Download packages
        3. Store in content pool
        4. Update database
        """
        pass

    @abstractmethod
    async def publish(
        self,
        packages: List[Package],
        storage: StorageManager,
        target_path: Path
    ) -> None:
        """
        Publish packages to filesystem repository.

        Responsibilities:
        1. Create repository directory structure
        2. Create hardlinks from pool
        3. Generate metadata files
        4. Sign metadata (if configured)
        """
        pass

    @abstractmethod
    def validate_config(self, config: dict) -> bool:
        """Validate repository configuration."""
        pass
```

### RPM Plugin

**Datei:** `chantal/plugins/rpm/plugin.py`

```python
import xml.etree.ElementTree as ET
from pathlib import Path

class RpmPlugin(RepoPlugin):
    """Plugin for RPM/YUM/DNF repositories."""

    @property
    def type_name(self) -> str:
        return "rpm"

    async def sync(
        self,
        config: RpmRepoConfig,
        storage: StorageManager,
        download: DownloadManager,
        db: Database
    ) -> SyncResult:
        """
        Sync RPM repository.

        1. Download repomd.xml
        2. Parse metadata locations
        3. Download primary.xml.gz (package list)
        4. Download packages
        5. Store & deduplicate
        """
        start_time = time.time()
        packages_added = 0
        bytes_downloaded = 0

        # Download repomd.xml
        repomd_url = f"{config.upstream}/repodata/repomd.xml"
        repomd_path = Path("/tmp/repomd.xml")
        await download.download_file(repomd_url, repomd_path, config.credentials)

        # Parse repomd.xml to get primary.xml location
        tree = ET.parse(repomd_path)
        primary_location = self._get_primary_location(tree)

        # Download primary.xml.gz
        primary_url = f"{config.upstream}/{primary_location}"
        primary_path = Path("/tmp/primary.xml.gz")
        await download.download_file(primary_url, primary_path, config.credentials)

        # Parse package list
        packages = self._parse_primary_xml(primary_path)

        # Download packages (parallel)
        tasks = []
        for pkg in packages:
            if pkg['arch'] not in config.architectures:
                continue

            pkg_url = f"{config.upstream}/{pkg['location']}"
            pkg_path = Path(f"/tmp/{pkg['filename']}")

            task = download.download_file(
                pkg_url,
                pkg_path,
                config.credentials,
                expected_hash=pkg['checksum']
            )
            tasks.append((task, pkg, pkg_path))

        # Process downloads
        with Session(db.engine) as session:
            for task, pkg_meta, pkg_path in tasks:
                await task

                # Store in pool
                pool_path = storage.store_file(pkg_path, pkg_meta['checksum'])

                # Add to database
                package, created = db.get_or_create_package(
                    session,
                    sha256=pkg_meta['checksum'],
                    filename=pkg_meta['filename'],
                    size=pkg_meta['size'],
                    package_type='rpm',
                    arch=pkg_meta['arch'],
                    name=pkg_meta['name'],
                    version=pkg_meta['version'],
                    metadata={
                        'epoch': pkg_meta.get('epoch'),
                        'release': pkg_meta['release'],
                        'summary': pkg_meta.get('summary'),
                        'description': pkg_meta.get('description'),
                    }
                )

                if created:
                    packages_added += 1
                    bytes_downloaded += pkg_meta['size']

                # Cleanup temp file
                pkg_path.unlink()

            session.commit()

        duration = time.time() - start_time

        return SyncResult(
            packages_added=packages_added,
            packages_removed=0,  # TODO: Implement removal tracking
            packages_updated=0,
            bytes_downloaded=bytes_downloaded,
            duration_seconds=duration
        )

    async def publish(
        self,
        packages: List[Package],
        storage: StorageManager,
        target_path: Path
    ) -> None:
        """
        Publish RPM repository.

        1. Create Packages/ directory
        2. Hardlink .rpm files from pool
        3. Generate repodata/ metadata
        4. Sign repomd.xml (optional)
        """
        # Create directory structure
        packages_dir = target_path / "Packages"
        repodata_dir = target_path / "repodata"
        packages_dir.mkdir(parents=True, exist_ok=True)
        repodata_dir.mkdir(parents=True, exist_ok=True)

        # Hardlink packages
        for package in packages:
            if package.package_type != 'rpm':
                continue

            pool_file = storage._get_pool_path(package.sha256, package.filename)

            # Organize by first letter
            first_letter = package.name[0].lower()
            target_dir = packages_dir / first_letter
            target_dir.mkdir(exist_ok=True)

            target_file = target_dir / package.filename
            storage.create_hardlink(pool_file, target_file)

        # Generate metadata using createrepo_c
        await self._generate_metadata(target_path)

    async def _generate_metadata(self, repo_path: Path) -> None:
        """Generate RPM metadata using createrepo_c."""
        import subprocess

        result = subprocess.run(
            ["createrepo_c", "--update", str(repo_path)],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            raise RuntimeError(f"createrepo_c failed: {result.stderr}")

    def _parse_primary_xml(self, primary_gz_path: Path) -> List[dict]:
        """Parse primary.xml.gz to extract package metadata."""
        import gzip

        packages = []

        with gzip.open(primary_gz_path, 'rt') as f:
            tree = ET.parse(f)
            root = tree.getroot()

            # Namespace handling
            ns = {'': 'http://linux.duke.edu/metadata/common'}

            for package_elem in root.findall('.//package', ns):
                name = package_elem.find('name', ns).text
                arch = package_elem.find('arch', ns).text

                version_elem = package_elem.find('version', ns)
                version = version_elem.get('ver')
                release = version_elem.get('rel')
                epoch = version_elem.get('epoch', '0')

                checksum_elem = package_elem.find('.//checksum', ns)
                checksum = checksum_elem.text

                location_elem = package_elem.find('.//location', ns)
                location = location_elem.get('href')

                size_elem = package_elem.find('.//size', ns)
                size = int(size_elem.get('package'))

                packages.append({
                    'name': name,
                    'arch': arch,
                    'version': version,
                    'release': release,
                    'epoch': epoch,
                    'checksum': checksum,
                    'location': location,
                    'filename': Path(location).name,
                    'size': size,
                })

        return packages
```

### APT Plugin

**Datei:** `chantal/plugins/apt/plugin.py`

```python
class AptPlugin(RepoPlugin):
    """Plugin for APT/Debian repositories."""

    @property
    def type_name(self) -> str:
        return "apt"

    async def sync(
        self,
        config: AptRepoConfig,
        storage: StorageManager,
        download: DownloadManager,
        db: Database
    ) -> SyncResult:
        """
        Sync APT repository.

        1. Download InRelease or Release + Release.gpg
        2. Parse Release file for component metadata locations
        3. Download Packages.gz for each component/architecture
        4. Download .deb packages
        5. Store & deduplicate
        """
        start_time = time.time()
        packages_added = 0
        bytes_downloaded = 0

        # Download InRelease (GPG-signed Release)
        base_url = f"{config.upstream}/dists/{config.distribution}"
        inrelease_url = f"{base_url}/InRelease"
        inrelease_path = Path("/tmp/InRelease")

        try:
            await download.download_file(inrelease_url, inrelease_path, config.credentials)
        except Exception:
            # Fallback to Release + Release.gpg
            release_url = f"{base_url}/Release"
            release_path = Path("/tmp/Release")
            await download.download_file(release_url, release_path, config.credentials)
            inrelease_path = release_path

        # Parse Release file
        release_data = self._parse_release(inrelease_path)

        all_packages = []

        # Download Packages.gz for each component/arch
        for component in config.components:
            for arch in config.architectures:
                packages_rel_path = f"{component}/binary-{arch}/Packages.gz"

                # Get hash from Release file
                file_info = release_data['files'].get(packages_rel_path)
                if not file_info:
                    continue

                packages_url = f"{base_url}/{packages_rel_path}"
                packages_path = Path(f"/tmp/Packages-{component}-{arch}.gz")

                await download.download_file(
                    packages_url,
                    packages_path,
                    config.credentials,
                    expected_hash=file_info['sha256']
                )

                # Parse package list
                packages = self._parse_packages_gz(packages_path)
                all_packages.extend(packages)

        # Download .deb packages (parallel)
        tasks = []
        for pkg in all_packages:
            pkg_url = f"{config.upstream}/{pkg['filename']}"
            pkg_path = Path(f"/tmp/{Path(pkg['filename']).name}")

            task = download.download_file(
                pkg_url,
                pkg_path,
                config.credentials,
                expected_hash=pkg['sha256']
            )
            tasks.append((task, pkg, pkg_path))

        # Process downloads
        with Session(db.engine) as session:
            for task, pkg_meta, pkg_path in tasks:
                await task

                # Store in pool
                pool_path = storage.store_file(pkg_path, pkg_meta['sha256'])

                # Add to database
                package, created = db.get_or_create_package(
                    session,
                    sha256=pkg_meta['sha256'],
                    filename=Path(pkg_meta['filename']).name,
                    size=pkg_meta['size'],
                    package_type='deb',
                    arch=pkg_meta['architecture'],
                    name=pkg_meta['package'],
                    version=pkg_meta['version'],
                    metadata={
                        'section': pkg_meta.get('section'),
                        'priority': pkg_meta.get('priority'),
                        'description': pkg_meta.get('description'),
                    }
                )

                if created:
                    packages_added += 1
                    bytes_downloaded += pkg_meta['size']

                pkg_path.unlink()

            session.commit()

        duration = time.time() - start_time

        return SyncResult(
            packages_added=packages_added,
            packages_removed=0,
            packages_updated=0,
            bytes_downloaded=bytes_downloaded,
            duration_seconds=duration
        )

    async def publish(
        self,
        packages: List[Package],
        storage: StorageManager,
        target_path: Path
    ) -> None:
        """
        Publish APT repository.

        1. Create pool/ structure
        2. Hardlink .deb files
        3. Generate Packages, Release files
        4. Sign InRelease
        """
        # Create directory structure
        pool_dir = target_path / "pool" / "main"
        dists_dir = target_path / "dists" / "stable"  # TODO: Make configurable
        pool_dir.mkdir(parents=True, exist_ok=True)

        # Hardlink packages to pool
        for package in packages:
            if package.package_type != 'deb':
                continue

            pool_file = storage._get_pool_path(package.sha256, package.filename)

            # Pool structure: pool/main/p/package-name/
            first_letter = package.name[0].lower()
            if package.name.startswith('lib'):
                first_letter = package.name[:4]

            target_dir = pool_dir / first_letter / package.name
            target_dir.mkdir(parents=True, exist_ok=True)

            target_file = target_dir / package.filename
            storage.create_hardlink(pool_file, target_file)

        # Generate Packages files
        await self._generate_metadata(target_path, packages)

    def _parse_packages_gz(self, packages_gz_path: Path) -> List[dict]:
        """Parse Packages.gz file."""
        import gzip

        packages = []
        current_package = {}

        with gzip.open(packages_gz_path, 'rt') as f:
            for line in f:
                line = line.rstrip()

                if not line:
                    # Empty line = end of package stanza
                    if current_package:
                        packages.append(current_package)
                        current_package = {}
                    continue

                if line.startswith(' '):
                    # Continuation of previous field
                    continue

                if ':' in line:
                    key, value = line.split(':', 1)
                    current_package[key.lower()] = value.strip()

        # Don't forget last package
        if current_package:
            packages.append(current_package)

        return packages
```

### Plugin Registry

**Datei:** `chantal/plugins/registry.py`

```python
class PluginRegistry:
    """Registry for repository type plugins."""

    _plugins: Dict[str, RepoPlugin] = {}

    @classmethod
    def register(cls, plugin: RepoPlugin) -> None:
        """Register a plugin."""
        cls._plugins[plugin.type_name] = plugin

    @classmethod
    def get(cls, type_name: str) -> Optional[RepoPlugin]:
        """Get plugin by type name."""
        return cls._plugins.get(type_name)

    @classmethod
    def load_all(cls) -> None:
        """Load all built-in plugins."""
        from chantal.plugins.rpm import RpmPlugin
        from chantal.plugins.apt import AptPlugin

        cls.register(RpmPlugin())
        cls.register(AptPlugin())
```

---

## CLI-Interface

### Command Structure

**Datei:** `chantal/cli/main.py`

```python
import click
from pathlib import Path

@click.group()
@click.option('--config', '-c', type=Path, default='/etc/chantal/chantal.yaml',
              help='Configuration file path')
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
@click.pass_context
def cli(ctx, config, verbose):
    """Chantal - Unified offline repository mirroring."""
    ctx.ensure_object(dict)
    ctx.obj['config_path'] = config
    ctx.obj['verbose'] = verbose

@cli.group()
def repo():
    """Repository management commands."""
    pass

@repo.command('list')
@click.pass_context
def repo_list(ctx):
    """List configured repositories."""
    config = ChantalConfig.from_yaml(ctx.obj['config_path'])

    click.echo("Configured Repositories:")
    for repo in config.repositories:
        status = "✓" if repo.enabled else "✗"
        click.echo(f"  {status} {repo.name} ({repo.type}) - {repo.upstream}")

@repo.command('sync')
@click.argument('repo_name')
@click.option('--snapshot/--no-snapshot', default=False,
              help='Create snapshot after sync')
@click.pass_context
async def repo_sync(ctx, repo_name, snapshot):
    """Sync repository from upstream."""
    config = ChantalConfig.from_yaml(ctx.obj['config_path'])
    engine = ChantalEngine(config)

    with click.progressbar(length=100, label=f'Syncing {repo_name}') as bar:
        result = await engine.sync_repository(repo_name, create_snapshot=snapshot)

    click.echo(f"\nSync complete:")
    click.echo(f"  Packages added: {result.packages_added}")
    click.echo(f"  Bytes downloaded: {result.bytes_downloaded / 1024 / 1024:.2f} MB")
    click.echo(f"  Duration: {result.duration_seconds:.2f}s")

@cli.group()
def snapshot():
    """Snapshot management commands."""
    pass

@snapshot.command('create')
@click.argument('repo_name')
@click.option('--name', '-n', help='Snapshot name (default: auto-generated)')
@click.pass_context
def snapshot_create(ctx, repo_name, name):
    """Create snapshot of repository."""
    config = ChantalConfig.from_yaml(ctx.obj['config_path'])
    engine = ChantalEngine(config)

    snap = engine.create_snapshot(repo_name, name)
    click.echo(f"Created snapshot: {snap.name}")

@snapshot.command('list')
@click.argument('repo_name', required=False)
@click.pass_context
def snapshot_list(ctx, repo_name):
    """List snapshots."""
    config = ChantalConfig.from_yaml(ctx.obj['config_path'])
    db = Database(config.database)

    snapshots = db.get_snapshots(repo_name)

    click.echo("Snapshots:")
    for snap in snapshots:
        pkg_count = len(snap.packages)
        click.echo(f"  {snap.name} ({snap.created_at}) - {pkg_count} packages")

@snapshot.command('merge')
@click.argument('snapshot_names', nargs=-1, required=True)
@click.option('--name', '-n', required=True, help='Name for merged snapshot')
@click.option('--strategy', type=click.Choice(['rightmost', 'latest', 'keep-all']),
              default='rightmost', help='Merge strategy')
@click.pass_context
def snapshot_merge(ctx, snapshot_names, name, strategy):
    """Merge multiple snapshots."""
    config = ChantalConfig.from_yaml(ctx.obj['config_path'])
    engine = ChantalEngine(config)

    snap = engine.merge_snapshots(
        list(snapshot_names),
        name,
        MergeStrategy[strategy.upper().replace('-', '_')]
    )

    click.echo(f"Created merged snapshot: {snap.name}")

@snapshot.command('diff')
@click.argument('snapshot_a')
@click.argument('snapshot_b')
@click.pass_context
def snapshot_diff(ctx, snapshot_a, snapshot_b):
    """Compare two snapshots."""
    config = ChantalConfig.from_yaml(ctx.obj['config_path'])
    engine = ChantalEngine(config)

    diff = engine.diff_snapshots(snapshot_a, snapshot_b)

    click.echo(f"\nAdded packages ({len(diff.added)}):")
    for pkg in diff.added:
        click.echo(f"  + {pkg.name}-{pkg.version}.{pkg.arch}")

    click.echo(f"\nRemoved packages ({len(diff.removed)}):")
    for pkg in diff.removed:
        click.echo(f"  - {pkg.name}-{pkg.version}.{pkg.arch}")

@cli.group()
def publish():
    """Publishing commands."""
    pass

@publish.command('snapshot')
@click.argument('snapshot_name')
@click.argument('target_path', type=Path)
@click.pass_context
async def publish_snapshot(ctx, snapshot_name, target_path):
    """Publish snapshot to filesystem."""
    config = ChantalConfig.from_yaml(ctx.obj['config_path'])
    engine = ChantalEngine(config)

    await engine.publish_snapshot(snapshot_name, target_path)

    click.echo(f"Published {snapshot_name} to {target_path}")

@cli.command('init')
@click.option('--database-url', help='PostgreSQL connection URL')
@click.option('--storage-path', type=Path, help='Storage base path')
def init(database_url, storage_path):
    """Initialize Chantal (create database, directories)."""
    # Create database schema
    # Create directory structure
    # Generate example config
    click.echo("Chantal initialized successfully!")

if __name__ == '__main__':
    cli()
```

### CLI Examples

```bash
# Initialize
chantal init --database-url postgresql://chantal@localhost/chantal

# List repos
chantal repo list

# Sync repository
chantal repo sync rhel9-baseos
chantal repo sync rhel9-baseos --snapshot

# Snapshot management
chantal snapshot create rhel9-baseos
chantal snapshot create rhel9-baseos --name 2025-01-patch1
chantal snapshot list
chantal snapshot list rhel9-baseos

# Merge snapshots
chantal snapshot merge rhel9-baseos-latest internal-rpms-latest \
  --name custom-rhel9 \
  --strategy latest

# Diff snapshots
chantal snapshot diff rhel9-2025-01-09 rhel9-2025-01-15

# Publish
chantal publish snapshot rhel9-baseos-2025-01-09 /var/www/repos/rhel9

# Cleanup
chantal db cleanup  # Remove unreferenced packages from pool
```

---

## Konfiguration

### Vollständiges YAML-Schema

**Datei:** `/etc/chantal/chantal.yaml`

```yaml
# Chantal Configuration

# Storage paths
storage:
  base_path: /var/lib/chantal
  # Optional: Override individual paths
  # pool_path: /mnt/storage/chantal/pool
  # repo_path: /var/www/repos
  # snapshot_path: /var/lib/chantal/snapshots

# Database configuration
database:
  url: postgresql://chantal:password@localhost/chantal
  pool_size: 5
  echo: false  # Set true for SQL debugging

# Repository definitions
repositories:
  # RPM Repository - Red Hat Enterprise Linux 9 BaseOS
  - name: rhel9-baseos
    type: rpm
    upstream: https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os
    enabled: true

    # Client certificate authentication (Red Hat Subscription)
    credentials:
      type: client_cert
      cert: /etc/pki/entitlement/1234567890.pem
      key: /etc/pki/entitlement/1234567890-key.pem
      ca_cert: /etc/rhsm/ca/redhat-uep.pem

    # RPM-specific options
    gpgcheck: true
    architectures:
      - x86_64
      - aarch64

  # RPM Repository - RHEL 9 AppStream
  - name: rhel9-appstream
    type: rpm
    upstream: https://cdn.redhat.com/content/dist/rhel9/9/x86_64/appstream/os
    enabled: true

    # Auto-discovery via subscription-manager
    credentials:
      type: subscription_manager

    architectures:
      - x86_64

  # APT Repository - Ubuntu 22.04 (Jammy)
  - name: ubuntu-jammy
    type: apt
    upstream: http://archive.ubuntu.com/ubuntu
    distribution: jammy
    components:
      - main
      - restricted
      - universe
      - multiverse
    enabled: true
    architectures:
      - amd64
      - arm64

  # APT Repository - Ubuntu Security Updates
  - name: ubuntu-jammy-security
    type: apt
    upstream: http://security.ubuntu.com/ubuntu
    distribution: jammy-security
    components:
      - main
      - restricted
      - universe
      - multiverse
    enabled: true
    architectures:
      - amd64

  # APT Repository - Authenticated (e.g., private repo)
  - name: company-internal-deb
    type: apt
    upstream: https://apt.company.internal/debian
    distribution: stable
    components:
      - main
    enabled: true

    # HTTP Basic Auth with password from external command
    credentials:
      type: basic
      username: deploy
      password_command: "pass show company/apt-password"

    architectures:
      - amd64

# Global settings
settings:
  # Parallel downloads
  download_workers: 10

  # Retry configuration
  download_retries: 5
  download_timeout: 300  # seconds

  # Snapshot retention
  snapshot_retention: 5  # Keep last 5 snapshots per repository

  # Logging
  log_level: INFO
  log_file: /var/log/chantal/chantal.log
```

---

## Data-Flow

### Sync Operation Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. User: chantal repo sync rhel9-baseos --snapshot             │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. Load Configuration                                           │
│    - Read /etc/chantal/chantal.yaml                            │
│    - Validate repository config                                │
│    - Load credentials                                           │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. Initialize Components                                        │
│    - Database connection (PostgreSQL)                           │
│    - Storage manager                                            │
│    - Download manager (HTTP session + auth)                     │
│    - Load RPM plugin                                            │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. Start Sync Transaction                                       │
│    - Create sync_history record (status='running')              │
│    - Get last sync timestamp                                    │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. RPM Plugin: Download Metadata                                │
│    - Download repomd.xml (with client cert auth)                │
│    - Verify GPG signature                                       │
│    - Parse metadata locations                                   │
│    - Download primary.xml.gz                                    │
│    - Parse package list (name, version, arch, checksum, URL)    │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 6. Filter Packages                                              │
│    - Filter by architecture (x86_64, aarch64)                   │
│    - Check if package already in database (by checksum)         │
│    - Create download queue for new/updated packages             │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 7. Download Packages (Parallel)                                 │
│    - Spawn 10 download workers (asyncio)                        │
│    - Each worker:                                               │
│      a) Download .rpm file (with resume support)                │
│      b) Verify SHA256 checksum                                  │
│      c) Report progress                                         │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 8. Store Packages (Deduplication)                               │
│    For each downloaded package:                                 │
│    - Check if SHA256 exists in database                         │
│    - If exists: Skip storage (already in pool)                  │
│    - If new:                                                    │
│      a) Move to pool (data/sha256/ab/cd/hash_filename.rpm)      │
│      b) Create Package database record                          │
│      c) Extract metadata (name, version, arch, deps, etc.)      │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 9. Update Repository State                                      │
│    - Mark packages as belonging to repository                   │
│    - Remove packages no longer in upstream (optional)           │
│    - Update repository.last_sync timestamp                      │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 10. Create Snapshot (if --snapshot flag)                        │
│     - Query all package IDs for repository                      │
│     - Create snapshot record with name "rhel9-baseos-20250109"  │
│     - Insert snapshot_packages references                       │
│     - Mark snapshot as immutable                                │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 11. Complete Sync Transaction                                   │
│     - Update sync_history (status='success')                    │
│     - Record stats (packages_added, bytes_downloaded, duration) │
│     - Commit database transaction                               │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 12. Display Results                                             │
│     Sync complete:                                              │
│       Packages added: 1247                                      │
│       Bytes downloaded: 4.2 GB                                  │
│       Duration: 324.5s                                          │
│       Snapshot created: rhel9-baseos-20250109                   │
└─────────────────────────────────────────────────────────────────┘
```

### Publish Operation Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. User: chantal publish snapshot rhel9-baseos-20250109 \      │
│          /var/www/repos/rhel9                                   │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. Load Snapshot from Database                                  │
│    - Query snapshot by name                                     │
│    - Get all package references (snapshot_packages join)        │
│    - Load package metadata                                      │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. Create Temporary Publish Directory                           │
│    - Create /var/www/repos/.rhel9.tmp/                         │
│    - Atomic publish strategy (build in temp, then swap)         │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. RPM Plugin: Create Directory Structure                       │
│    - .rhel9.tmp/Packages/a/ through /z/                        │
│    - .rhel9.tmp/repodata/                                      │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. Create Hardlinks from Pool                                   │
│    For each package in snapshot:                                │
│    - Get pool path: data/sha256/ab/cd/hash_package.rpm         │
│    - Create hardlink to Packages/p/package.rpm                  │
│    - Hardlink = same inode, no disk space used                  │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 6. RPM Plugin: Generate Metadata                                │
│    - Run createrepo_c --update .rhel9.tmp/                     │
│    - Generates:                                                 │
│      • repomd.xml (master metadata index)                       │
│      • primary.xml.gz (package list + metadata)                 │
│      • filelists.xml.gz (files in packages)                     │
│      • other.xml.gz (changelog, etc.)                           │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 7. Optional: Sign Metadata                                      │
│    - GPG sign repomd.xml → repomd.xml.asc                      │
│    - Clients can verify repository authenticity                 │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 8. Atomic Switch                                                │
│    - Rename /var/www/repos/rhel9 → .rhel9.old                 │
│    - Rename .rhel9.tmp → /var/www/repos/rhel9                  │
│    - Atomic rename = minimal downtime for clients               │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 9. Cleanup Old Version                                          │
│    - Remove .rhel9.old/ directory                              │
│    - Old hardlinks deleted, but pool files remain (still used)  │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 10. Repository Ready                                            │
│     Published repository is now live and can be served by:      │
│     - Apache/nginx (static HTTP server)                         │
│     - Python http.server (development)                          │
│     - S3 bucket (with static website hosting)                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Technology Stack

### Core Dependencies

**Datei:** `pyproject.toml` (Poetry)

```toml
[tool.poetry]
name = "chantal"
version = "0.1.0"
description = "Unified offline repository mirroring for APT and RPM"
authors = ["Your Name <you@example.com>"]
license = "MIT"
readme = "README.md"

[tool.poetry.dependencies]
python = "^3.11"

# Core
click = "^8.1.7"                    # CLI framework
pydantic = "^2.5.0"                 # Configuration validation
pyyaml = "^6.0.1"                   # YAML parsing

# Database
sqlalchemy = "^2.0.23"              # ORM
psycopg2-binary = "^2.9.9"          # PostgreSQL driver (or use psycopg3/asyncpg)
alembic = "^1.13.0"                 # Database migrations

# HTTP & Downloads
requests = "^2.31.0"                # HTTP client
urllib3 = "^2.1.0"                  # HTTP with retry logic
aiohttp = "^3.9.0"                  # Async HTTP (for parallel downloads)
aiofiles = "^23.2.1"                # Async file I/O

# Compression
python-zstandard = "^0.22.0"        # Zstandard compression
python-lz4 = "^4.3.2"               # LZ4 compression

# RPM Support
rpm = "^0.1.0"                      # RPM package parsing (or use rpmfile)
# Note: May need system libr rpm-dev package

# DEB Support
python-debian = "^0.1.49"           # Debian package parsing

# Crypto & Hashing
cryptography = "^41.0.7"            # TLS, X.509 certificates
hashlib                             # (built-in) SHA256 hashing

# Progress & Logging
tqdm = "^4.66.0"                    # Progress bars
rich = "^13.7.0"                    # Rich terminal output
loguru = "^0.7.2"                   # Better logging

# Optional: For GPG signing
python-gnupg = "^0.5.1"             # GPG wrapper

[tool.poetry.group.dev.dependencies]
pytest = "^7.4.3"                   # Testing
pytest-asyncio = "^0.21.1"          # Async testing
pytest-cov = "^4.1.0"               # Coverage
mypy = "^1.7.0"                     # Type checking
black = "^23.11.0"                  # Code formatting
ruff = "^0.1.6"                     # Linting

[tool.poetry.scripts]
chantal = "chantal.cli.main:cli"

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"
```

### System Dependencies

```bash
# PostgreSQL
sudo apt-get install postgresql postgresql-contrib

# RPM support (createrepo_c)
sudo apt-get install createrepo-c

# DEB support (dpkg-scanpackages)
sudo apt-get install dpkg-dev

# GPG for signing
sudo apt-get install gnupg

# Development libraries
sudo apt-get install librpm-dev libssl-dev
```

### Alternative: requirements.txt

```txt
# Core
click>=8.1.7
pydantic>=2.5.0
pyyaml>=6.0.1

# Database
sqlalchemy>=2.0.23
psycopg2-binary>=2.9.9
alembic>=1.13.0

# HTTP
requests>=2.31.0
aiohttp>=3.9.0
aiofiles>=23.2.1

# Compression
python-zstandard>=0.22.0

# Package format support
python-debian>=0.1.49

# Crypto
cryptography>=41.0.7

# UI/Progress
tqdm>=4.66.0
rich>=13.7.0
loguru>=0.7.2

# Optional
python-gnupg>=0.5.1
```

---

## Deployment & Installation

### Installation Methods

#### 1. PyPI Package (Recommended for Users)

```bash
pip install chantal
chantal --version
```

#### 2. From Source (Development)

```bash
git clone https://github.com/slauger/chantal.git
cd chantal
poetry install
poetry run chantal --version
```

#### 3. Docker Container

**Dockerfile:**

```dockerfile
FROM python:3.11-slim

# System dependencies
RUN apt-get update && apt-get install -y \
    postgresql-client \
    createrepo-c \
    dpkg-dev \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install chantal
COPY . /app
WORKDIR /app
RUN pip install -e .

# Create storage directories
RUN mkdir -p /var/lib/chantal /etc/chantal

# Entrypoint
ENTRYPOINT ["chantal"]
CMD ["--help"]
```

**Docker Compose:**

```yaml
version: '3.8'

services:
  chantal:
    build: .
    volumes:
      - /etc/chantal:/etc/chantal:ro
      - /var/lib/chantal:/var/lib/chantal
      - /var/www/repos:/var/www/repos
    environment:
      - CHANTAL_DB_URL=postgresql://chantal:password@postgres/chantal
    depends_on:
      - postgres

  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: chantal
      POSTGRES_USER: chantal
      POSTGRES_PASSWORD: password
    volumes:
      - postgres-data:/var/lib/postgresql/data

volumes:
  postgres-data:
```

### Systemd Service

**File:** `/etc/systemd/system/chantal-sync.service`

```ini
[Unit]
Description=Chantal Repository Sync
After=network.target postgresql.service

[Service]
Type=oneshot
User=chantal
Group=chantal
ExecStart=/usr/local/bin/chantal repo sync --all
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**Timer:** `/etc/systemd/system/chantal-sync.timer`

```ini
[Unit]
Description=Chantal Repository Sync Timer
Requires=chantal-sync.service

[Timer]
# Run daily at 2 AM
OnCalendar=daily
OnCalendar=02:00
Persistent=true

[Install]
WantedBy=timers.target
```

Enable:

```bash
sudo systemctl enable --now chantal-sync.timer
```

---

## Sicherheit

### Credential Management

**Best Practices:**

1. **Environment Variables:**
   ```yaml
   credentials:
     type: basic
     username: ${APT_USER}
     password: ${APT_PASSWORD}
   ```

2. **Password Command (External Secret Manager):**
   ```yaml
   credentials:
     type: basic
     username: deploy
     password_command: "pass show company/apt"
   ```

3. **File Permissions:**
   ```bash
   chmod 600 /etc/chantal/chantal.yaml
   chown chantal:chantal /etc/chantal/chantal.yaml
   ```

4. **Certificate Storage:**
   ```bash
   chmod 400 /etc/pki/entitlement/*.pem
   chown chantal:chantal /etc/pki/entitlement/*.pem
   ```

### TLS/HTTPS Verification

**Always verify:**
- CA certificates for HTTPS
- Client certificates for authenticated repositories
- GPG signatures for metadata

**Configuration:**

```python
# Strict TLS verification (default)
session.verify = True

# Custom CA bundle
session.verify = "/path/to/ca-bundle.crt"

# Client certificates
session.cert = (cert_file, key_file)
```

### GPG Signature Verification

```python
def verify_gpg_signature(file_path: Path, signature_path: Path, keyring: Path) -> bool:
    """Verify GPG signature of file."""
    import gnupg

    gpg = gnupg.GPG(keyring=str(keyring))

    with open(file_path, 'rb') as f:
        verified = gpg.verify_file(f, signature_path)

    return verified.valid
```

### Database Security

- Use strong passwords
- Enable SSL/TLS for PostgreSQL connections
- Use connection pooling limits
- Regular backups

**PostgreSQL SSL:**

```yaml
database:
  url: postgresql://user:pass@host/db?sslmode=require
```

---

## Performance-Considerations

### Parallel Downloads

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

async def download_packages_parallel(packages: List[dict], workers: int = 10):
    """Download packages in parallel using asyncio."""

    semaphore = asyncio.Semaphore(workers)

    async def download_with_limit(pkg):
        async with semaphore:
            return await download_manager.download_file(pkg['url'], pkg['path'])

    tasks = [download_with_limit(pkg) for pkg in packages]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    return results
```

### Database Optimization

**Indexes:**

```sql
CREATE INDEX idx_packages_sha256 ON packages(sha256);
CREATE INDEX idx_packages_name ON packages(name);
CREATE INDEX idx_packages_type_arch ON packages(package_type, arch);
CREATE INDEX idx_snapshots_name ON snapshots(name);
CREATE INDEX idx_snapshot_packages_snapshot_id ON snapshot_packages(snapshot_id);
CREATE INDEX idx_snapshot_packages_package_id ON snapshot_packages(package_id);
```

**Bulk Inserts:**

```python
# Use bulk insert instead of individual inserts
session.bulk_insert_mappings(Package, package_dicts)
session.commit()
```

### Storage Optimization

**Hardlinks vs. Symlinks:**

```python
# Hardlinks (preferred - same inode, no extra disk space)
os.link(source, target)

# Symlinks (alternative - works across filesystems)
os.symlink(source, target)
```

**Cleanup Strategy:**

```python
def cleanup_unreferenced_packages(max_age_days: int = 30):
    """
    Remove packages from pool that:
    1. Are not referenced by any snapshot
    2. Are older than max_age_days
    """
    cutoff_date = datetime.now() - timedelta(days=max_age_days)

    unreferenced = db.query(Package).filter(
        ~Package.snapshots.any(),
        Package.first_seen < cutoff_date
    ).all()

    for package in unreferenced:
        pool_path = storage.get_pool_path(package.sha256, package.filename)
        pool_path.unlink()
        db.delete(package)

    db.commit()
```

---

## Testing-Strategie

### Unit Tests

**Datei:** `tests/test_storage.py`

```python
import pytest
from pathlib import Path
from chantal.core.storage import StorageManager

def test_store_file_deduplication(tmp_path):
    """Test that identical files are deduplicated."""
    storage = StorageManager(tmp_path)

    # Create test file
    test_file = tmp_path / "test.rpm"
    test_file.write_text("package data")

    sha256 = "abc123..."  # Would be actual hash

    # Store first time
    path1 = storage.store_file(test_file, sha256)
    assert path1.exists()

    # Store again - should return existing path
    path2 = storage.store_file(test_file, sha256)
    assert path2 == path1
    assert path1.stat().st_ino == path2.stat().st_ino  # Same inode
```

### Integration Tests

**Datei:** `tests/integration/test_rpm_sync.py`

```python
@pytest.mark.asyncio
async def test_rpm_sync_full_workflow(test_db, tmp_path):
    """Test complete RPM sync workflow."""
    # Setup mock RPM repository
    mock_repo = setup_mock_rpm_repo(tmp_path)

    # Configure Chantal
    config = RpmRepoConfig(
        name="test-repo",
        upstream=f"file://{mock_repo}",
        architectures=["x86_64"]
    )

    # Sync
    engine = ChantalEngine(config, test_db)
    result = await engine.sync_repository("test-repo")

    # Verify
    assert result.packages_added > 0
    assert test_db.get_repository("test-repo") is not None
```

### Mock Repositories

```python
def setup_mock_rpm_repo(base_path: Path) -> Path:
    """Create mock RPM repository for testing."""
    repo_path = base_path / "mock-repo"
    repodata_path = repo_path / "repodata"
    repodata_path.mkdir(parents=True)

    # Create repomd.xml
    repomd = """<?xml version="1.0" encoding="UTF-8"?>
    <repomd xmlns="http://linux.duke.edu/metadata/repo">
      <data type="primary">
        <location href="repodata/primary.xml.gz"/>
        <checksum type="sha256">abc123...</checksum>
      </data>
    </repomd>"""

    (repodata_path / "repomd.xml").write_text(repomd)

    return repo_path
```

---

## Offene Fragen

1. **Metadaten-Caching:**
   - Wie lange sollen HTTP ETags/Last-Modified gecacht werden?
   - Separate Cache-DB oder Filesystem?

2. **Snapshot-Retention:**
   - Automatische Cleanup-Policy für alte Snapshots?
   - Oder manuell per CLI?

3. **GPG-Key-Management:**
   - Wo werden GPG Keys gespeichert?
   - Automatischer Key-Import von Repositories?

4. **Monitoring & Alerting:**
   - Prometheus-Metrics exportieren?
   - Logging-Format (JSON für Log-Aggregation)?

5. **Performance:**
   - Ab welcher Repo-Größe lohnt sich asyncpg statt psycopg2?
   - Redis-Cache für häufige DB-Queries?

6. **Multi-Tenancy:**
   - Support für mehrere unabhängige Chantal-Instanzen auf einem System?

7. **S3 Publishing:**
   - boto3 Integration für direktes S3-Upload?
   - CloudFront-Invalidation nach Publish?

---

**Ende des Architektur-Proposals v1**

Nächster Schritt: Review & Feedback, dann MVP-Scope Definition.
