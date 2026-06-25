# Database Schema

Chantal uses SQLAlchemy ORM with support for PostgreSQL and SQLite.

## Overview

The database stores:
- Content item metadata (packages of any type)
- Repository metadata/installer files
- Repository state
- Snapshots
- Views (virtual repositories) and view snapshots
- Sync history

All models are defined in `src/chantal/db/models.py`.

## Design: Generic Content Items

Chantal does **not** have a type-specific `Package` model. Instead, all package
types (RPM, Helm, PyPI, APT/DEB, Alpine APK, etc.) are stored in a single generic
`ContentItem` model. Type-specific attributes are kept in a JSON column
(`content_metadata`) rather than as dedicated columns. This keeps the schema
stable when new content types are added: a new plugin only needs to agree on the
JSON layout for its `content_type`.

For RPM, attributes like `epoch`, `release` and `arch` live inside
`content_metadata` and are exposed through read-only `@property` accessors on the
model (including a derived `nevra` string).

## Core Models

### ContentItem

Generic, content-addressed model for all package types (table `content_items`).

```python
class ContentItem(Base):
    id: int                  # Primary key (auto-increment)

    content_type: str        # 'rpm', 'helm', 'pypi', 'apt', 'apk', ... (indexed)

    name: str                # Package name (e.g., "nginx"), indexed
    version: str             # Version, indexed

    sha256: str              # Content address - UNIQUE, indexed (NOT the PK)
    size_bytes: int          # File size in bytes
    pool_path: str           # Relative path in pool (e.g., "content/ab/cd/<sha>_file.rpm")
    filename: str            # Original filename

    content_metadata: dict   # JSON; type-specific fields (NOT called 'metadata'
                             # because that name is reserved by SQLAlchemy)

    created_at: datetime
    reference_count: int     # For garbage collection

    # Relationships (many-to-many)
    repositories: list[Repository]   # via repository_content_items
    snapshots: list[Snapshot]        # via snapshot_content_items
```

**Key features:**
- Integer `id` is the primary key; `sha256` is a separate **unique** indexed column.
- Deduplication is enforced by the unique `sha256` constraint.
- Composite indexes: `(content_type, name)` and `(content_type, name, version)`.

**RPM-specific properties** (read JSON from `content_metadata`):

```python
item.epoch     # content_metadata["epoch"]   (rpm only)
item.release   # content_metadata["release"] (rpm only)
item.arch      # content_metadata["arch"]    (rpm/deb)
item.nevra     # "name-epoch:version-release.arch" (rpm only)
```

### Repository

Configured repositories from YAML (table `repositories`).

```python
class Repository(Base):
    id: int               # Primary key (auto-increment)
    repo_id: str          # Stable config identifier - UNIQUE
    name: str             # Human-readable name
    type: str             # Repository type (rpm, apt, helm, apk)
    feed: str             # Upstream URL (Pulp terminology, NOT "feed_url")
    enabled: bool
    mode: RepositoryMode  # Enum: mirror / filtered / hosted (default: filtered)

    # Paths
    latest_path: str | None
    snapshots_path: str | None

    # Timestamps
    created_at: datetime
    updated_at: datetime

    # Sync state
    last_sync_at: datetime | None
    last_sync_status: str | None   # success, failed, running

    # Relationships
    snapshots: list[Snapshot]            # One-to-many
    sync_history: list[SyncHistory]      # One-to-many
    content_items: list[ContentItem]     # Many-to-many via repository_content_items
    repository_files: list[RepositoryFile]  # Many-to-many via repository_repository_files
```

#### RepositoryMode

```python
class RepositoryMode(enum.StrEnum):
    MIRROR = "mirror"      # Full mirror, no filtering, metadata unchanged
    FILTERED = "filtered"  # Filtered packages with customized metadata (default)
    HOSTED = "hosted"      # Self-hosted / uploaded packages (no upstream sync)
```

The `mode` column was added in the head migration `e190d159daac`.

### ContentItem vs. RepositoryFile

A repository is more than just its packages. Metadata files (`updateinfo.xml`,
`filelists.xml`, `comps.xml`, `modules.yaml`), signatures, and installer/kickstart
artifacts (`vmlinuz`, `initrd.img`, `.treeinfo`) are stored separately in the
`RepositoryFile` model. Both `ContentItem` and `RepositoryFile` use
content-addressed pool storage, but they live in different pool subdirectories
(`pool/content/` vs. `pool/files/`).

### RepositoryFile

Non-package repository files: metadata, signatures, installer/kickstart artifacts
(table `repository_files`). Added in migration `4ae7cc6b7243`.

```python
class RepositoryFile(Base):
    id: int                # Primary key (auto-increment)

    file_category: str     # "metadata", "signature", "kickstart", "debian-installer" (indexed)
    file_type: str         # "updateinfo", "filelists", "comps", "modules",
                           # "vmlinuz", "initrd", ".treeinfo", ... (indexed)

    sha256: str            # Content address (indexed, not unique)
    pool_path: str         # e.g. "files/ab/cd/<sha>_updateinfo.xml.gz"
    size_bytes: int

    original_path: str     # Exact upstream path to preserve when publishing
                           # e.g. "repodata/<hash>-updateinfo.xml.gz", ".treeinfo"

    file_metadata: dict | None  # JSON; type-specific info (reserved-name workaround)

    created_at: datetime
    updated_at: datetime

    # Relationships (many-to-many, like ContentItem)
    repositories: list[Repository]   # via repository_repository_files
    snapshots: list[Snapshot]        # via snapshot_repository_files
```

### Snapshot

Immutable point-in-time repository state (table `snapshots`).

```python
class Snapshot(Base):
    id: int               # Primary key (auto-increment)
    repository_id: int    # Foreign key to Repository.id
    name: str             # Snapshot name (e.g., "2025-01")
    description: str | None

    created_at: datetime
    is_published: bool
    published_path: str | None

    # Cached statistics
    package_count: int
    total_size_bytes: int

    # Relationships
    repository: Repository
    content_items: list[ContentItem]      # Many-to-many via snapshot_content_items
    repository_files: list[RepositoryFile] # Many-to-many via snapshot_repository_files
```

**Unique constraint:** `(repository_id, name)` (`uq_snapshot_name`).

### View

Virtual repository combining multiple repositories (table `views`).

```python
class View(Base):
    id: int               # Primary key (auto-increment)
    name: str             # UNIQUE, indexed
    description: str | None
    repo_type: str        # All repos in a view must share this type (rpm, apt)

    created_at: datetime
    updated_at: datetime

    is_published: bool
    published_at: datetime | None
    published_path: str | None

    # Relationships
    view_repositories: list[ViewRepository]  # One-to-many (ordered membership)
    view_snapshots: list[ViewSnapshot]       # One-to-many
```

### ViewRepository

Membership of repositories in a view, with ordering. This is a full ORM model
(table `view_repositories`), not a plain association table.

```python
class ViewRepository(Base):
    id: int               # Primary key (auto-increment)
    view_id: int          # Foreign key to View.id
    repository_id: int    # Foreign key to Repository.id
    order: int            # Precedence for metadata merging (lower = higher priority)
    added_at: datetime

    # Relationships
    view: View
    repository: Repository
```

**Unique constraint:** `(view_id, repository_id)` (`uq_view_repository`).

### ViewSnapshot

Atomic snapshot of all repositories in a view (table `view_snapshots`). It does
**not** use a junction table; instead it stores the included repository snapshot
IDs directly in a JSON array.

```python
class ViewSnapshot(Base):
    id: int               # Primary key (auto-increment)
    view_id: int          # Foreign key to View.id
    name: str             # Snapshot name, indexed
    description: str | None

    created_at: datetime

    snapshot_ids: list[int]  # JSON array of Snapshot.id values (e.g. [12, 45, 67])

    is_published: bool
    published_at: datetime | None
    published_path: str | None

    # Cached statistics
    package_count: int
    total_size_bytes: int

    # Relationships
    view: View
```

**Unique constraint:** `(view_id, name)` (`uq_view_snapshot_name`).

### SyncHistory

Tracks sync operations for audit and debugging (table `sync_history`).

```python
class SyncHistory(Base):
    id: int               # Primary key (auto-increment)
    repository_id: int    # Foreign key to Repository.id

    # Sync timing
    started_at: datetime
    completed_at: datetime | None

    # Result
    status: str           # running, success, failed
    error_message: str | None

    # Statistics
    packages_added: int
    packages_removed: int
    packages_updated: int
    bytes_downloaded: int

    # Snapshot created during this sync (optional)
    snapshot_id: int | None   # Foreign key to Snapshot.id

    # Relationships
    repository: Repository
    snapshot: Snapshot | None
```

`duration_seconds` is a derived `@property` (`completed_at - started_at`).

## Junction Tables

The following are plain SQLAlchemy association `Table`s (no ORM class):

### repository_content_items

Many-to-many between repositories and content items (the "latest" state).

```python
repository_content_items = Table(
    "repository_content_items",
    Column("repository_id", ForeignKey("repositories.id"), primary_key=True),
    Column("content_item_id", ForeignKey("content_items.id"), primary_key=True),
    Column("added_at", DateTime),
)
```

### snapshot_content_items

Many-to-many between snapshots and content items.

```python
snapshot_content_items = Table(
    "snapshot_content_items",
    Column("snapshot_id", ForeignKey("snapshots.id"), primary_key=True),
    Column("content_item_id", ForeignKey("content_items.id"), primary_key=True),
)
```

### repository_repository_files

Many-to-many between repositories and repository files (the "latest" state).

```python
repository_repository_files = Table(
    "repository_repository_files",
    Column("repository_id", ForeignKey("repositories.id"), primary_key=True),
    Column("repository_file_id", ForeignKey("repository_files.id"), primary_key=True),
    Column("added_at", DateTime),
)
```

### snapshot_repository_files

Many-to-many between snapshots and repository files.

```python
snapshot_repository_files = Table(
    "snapshot_repository_files",
    Column("snapshot_id", ForeignKey("snapshots.id"), primary_key=True),
    Column("repository_file_id", ForeignKey("repository_files.id"), primary_key=True),
)
```

> **Note:** View-to-repository membership is the ORM model `ViewRepository`
> (see above), and view snapshots reference repository snapshots through the
> `ViewSnapshot.snapshot_ids` JSON array — there is no `view_repositories` plain
> table and no `view_snapshot_snapshots` junction table.

## Indexes

Indexes declared on the models:

```text
content_items:
  - content_type            (column index)
  - name                    (column index)
  - version                 (column index)
  - sha256                  (unique index)
  - idx_content_type_name           (content_type, name)
  - idx_content_type_name_version   (content_type, name, version)

repository_files:
  - file_category, file_type, sha256  (column indexes)
  - idx_repo_file_category (file_category)
  - idx_repo_file_type (file_type)

repositories:
  - repo_id (unique)

snapshots:
  - name (column index)

views / view_snapshots:
  - name (column index)
```

## Database Migrations

Chantal uses Alembic for schema migrations. Migration scripts live in
`alembic/versions/`.

### Migration Files

```text
alembic/
├── versions/
│   ├── 20260110_2202_a4a922fdfc63_initial_schema_with_generic_content_.py
│   ├── 20260111_1138_4ae7cc6b7243_add_repository_files_table_and_.py
│   └── 20260111_1242_e190d159daac_add_repository_mode_field.py
└── env.py
```

Revision chain (head is `e190d159daac`):

```text
a4a922fdfc63 (initial schema, generic ContentItem)
    → 4ae7cc6b7243 (add repository_files table + junctions)
        → e190d159daac (add Repository.mode field)   ← head
```

### Run Migrations

```bash
# Upgrade to latest
alembic upgrade head

# Downgrade one version
alembic downgrade -1

# Show current version
alembic current
```

## Example Queries

### Find all content items in a repository

```python
repo = session.query(Repository).filter_by(repo_id="epel9-vim").first()
items = repo.content_items
```

### Find all repositories containing a content item

```python
item = session.query(ContentItem).filter_by(sha256="f256abc...").first()
repos = item.repositories
```

### Create snapshot

```python
snapshot = Snapshot(
    repository_id=repo.id,
    name="2025-01",
    description="January 2025",
)
snapshot.content_items = list(repo.content_items)  # Copy current items
snapshot.repository_files = list(repo.repository_files)
session.add(snapshot)
session.commit()
```

### Find content items added between snapshots

```python
snapshot1 = session.query(Snapshot).filter_by(name="2025-01").first()
snapshot2 = session.query(Snapshot).filter_by(name="2025-02").first()

added = set(snapshot2.content_items) - set(snapshot1.content_items)
removed = set(snapshot1.content_items) - set(snapshot2.content_items)
```

## Database Backends

### SQLite (Development)

**Connection string:**
```yaml
database:
  url: sqlite:///chantal.db
```

**Pros:**
- No external service
- Easy setup
- Good for testing

**Cons:**
- Limited concurrency
- Not suitable for large-scale

### PostgreSQL (Production)

**Connection string:**
```yaml
database:
  url: postgresql://chantal:password@localhost/chantal
```

**Pros:**
- Better performance
- Concurrent access
- Better for large datasets

**Cons:**
- Requires PostgreSQL installation
- More complex setup

## Maintenance

### Vacuum (SQLite)

```bash
sqlite3 /var/lib/chantal/chantal.db "VACUUM;"
```

### Analyze (PostgreSQL)

```sql
ANALYZE;
```

### Cleanup Orphaned Content Items

```python
# Find content items not in any repository
orphaned = session.query(ContentItem).filter(
    ~ContentItem.repositories.any()
).all()
```

## Schema Diagram

```text
┌──────────────┐     ┌───────────────────────────┐     ┌──────────────┐
│  Repository  │◄───►│ repository_content_items  │◄───►│ ContentItem  │
│              │     │                           │     │              │
│ - id (PK)    │     │ - repository_id           │     │ - id (PK)    │
│ - repo_id (U)│     │ - content_item_id         │     │ - sha256 (U) │
│ - type       │     │ - added_at                │     │ - content_type│
│ - feed       │     └───────────────────────────┘     │ - name        │
│ - mode       │                                        │ - version     │
└──┬───────┬───┘     ┌───────────────────────────┐     │ - content_    │
   │       │◄───────►│ repository_repository_files│◄──►│   metadata    │
   │       │         └───────────────────────────┘  │  └──────────────┘
   │       │                                          │
   │       ▼                                          ▼
   │  ┌──────────────┐  ┌──────────────────────┐  ┌──────────────┐
   │  │   Snapshot   │◄►│ snapshot_content_items│◄►│ RepositoryFile│
   │  │ - id (PK)    │  └──────────────────────┘  │ - id (PK)     │
   │  │ - repo_id FK │  ┌──────────────────────┐  │ - sha256      │
   │  │ - name       │◄►│snapshot_repository_files│◄│ - file_category│
   │  └──────────────┘  └──────────────────────┘  │ - original_path│
   │                                               └──────────────┘
   ▼
┌──────────────┐     ┌──────────────────┐
│ SyncHistory  │     │     View         │
│ - id (PK)    │     │ - id (PK)        │
│ - repo_id FK │     │ - name (U)       │
│ - status     │     │ - repo_type      │
└──────────────┘     └───┬──────────┬───┘
                         │          │
            ┌────────────▼───┐  ┌───▼──────────────┐
            │ ViewRepository │  │  ViewSnapshot    │
            │ - id (PK)      │  │ - id (PK)        │
            │ - view_id FK   │  │ - view_id FK     │
            │ - repo_id FK   │  │ - snapshot_ids   │  (JSON array of Snapshot.id)
            │ - order        │  └──────────────────┘
            └────────────────┘
```
