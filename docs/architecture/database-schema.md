# Database Schema

Chantal uses SQLAlchemy ORM with support for PostgreSQL and SQLite.

## Overview

The database stores:
- Package metadata
- Repository state
- Snapshots
- Views (virtual repositories)
- Sync history

## Core Models

### Package

Stores package metadata with content-addressed storage (SHA256).

```python
class Package(Base):
    sha256: str           # Primary key (content address)
    filename: str         # Original filename
    size: int             # File size in bytes

    # RPM metadata
    name: str             # Package name (e.g., "nginx")
    version: str          # Version
    release: str          # Release
    epoch: int            # Epoch (default: 0)
    architecture: str     # Architecture (e.g., "x86_64")

    # Timestamps
    created_at: datetime

    # Relationships
    repositories: List[Repository]  # Many-to-many
    snapshots: List[Snapshot]       # Many-to-many
```

**Key features:**
- SHA256 as primary key (content-addressed)
- Deduplication via unique SHA256
- Many-to-many relationships with repositories and snapshots

### Repository

Configured repositories from YAML.

```python
class Repository(Base):
    id: str               # Primary key (from config)
    name: str             # Human-readable name
    type: str             # Repository type (rpm, apt, pypi)
    feed_url: str         # Upstream URL
    enabled: bool         # Whether enabled

    # Timestamps
    created_at: datetime
    updated_at: datetime
    last_sync_at: datetime

    # Relationships
    packages: List[Package]       # Many-to-many
    snapshots: List[Snapshot]     # One-to-many
    sync_history: List[SyncHistory]  # One-to-many
```

### Snapshot

Immutable point-in-time repository state.

```python
class Snapshot(Base):
    id: int               # Primary key (auto-increment)
    repository_id: str    # Foreign key to Repository
    name: str             # Snapshot name (e.g., "2025-01")
    description: str      # Optional description

    # Timestamps
    created_at: datetime

    # Relationships
    repository: Repository
    packages: List[Package]  # Many-to-many
```

**Unique constraint:** (repository_id, name)

### View

Virtual repository combining multiple repositories.

```python
class View(Base):
    name: str             # Primary key (from config)
    description: str      # Human-readable description

    # Timestamps
    created_at: datetime
    updated_at: datetime

    # Relationships
    repositories: List[Repository]   # Many-to-many via ViewRepository
    snapshots: List[ViewSnapshot]    # One-to-many
```

### ViewSnapshot

Snapshot of a view (references multiple repository snapshots).

```python
class ViewSnapshot(Base):
    id: int               # Primary key (auto-increment)
    view_name: str        # Foreign key to View
    name: str             # Snapshot name (e.g., "2025-01")
    description: str      # Optional description

    # Timestamps
    created_at: datetime

    # Relationships
    view: View
    snapshots: List[Snapshot]  # Many-to-many
```

### SyncHistory

Tracks sync operations for audit and debugging.

```python
class SyncHistory(Base):
    id: int               # Primary key (auto-increment)
    repository_id: str    # Foreign key to Repository

    # Sync details
    started_at: datetime
    completed_at: datetime
    status: str           # success, failed, partial
    error_message: str    # Error details (if failed)

    # Statistics
    packages_total: int
    packages_downloaded: int
    packages_skipped: int
    bytes_transferred: int

    # Relationships
    repository: Repository
```

## Junction Tables

### repository_packages

Many-to-many relationship between repositories and packages.

```python
repository_packages = Table(
    'repository_packages',
    Column('repository_id', ForeignKey('repositories.id')),
    Column('package_sha256', ForeignKey('packages.sha256')),
    Column('added_at', DateTime),
    PrimaryKey('repository_id', 'package_sha256')
)
```

### snapshot_packages

Many-to-many relationship between snapshots and packages.

```python
snapshot_packages = Table(
    'snapshot_packages',
    Column('snapshot_id', ForeignKey('snapshots.id')),
    Column('package_sha256', ForeignKey('packages.sha256')),
    PrimaryKey('snapshot_id', 'package_sha256')
)
```

### view_repositories

Many-to-many relationship between views and repositories.

```python
view_repositories = Table(
    'view_repositories',
    Column('view_name', ForeignKey('views.name')),
    Column('repository_id', ForeignKey('repositories.id')),
    Column('order', Integer),  # Repository order in view
    PrimaryKey('view_name', 'repository_id')
)
```

### view_snapshot_snapshots

Many-to-many relationship between view snapshots and repository snapshots.

```python
view_snapshot_snapshots = Table(
    'view_snapshot_snapshots',
    Column('view_snapshot_id', ForeignKey('view_snapshots.id')),
    Column('snapshot_id', ForeignKey('snapshots.id')),
    PrimaryKey('view_snapshot_id', 'snapshot_id')
)
```

## Indexes

Critical indexes for performance:

```sql
-- Package lookups
CREATE INDEX idx_packages_name_arch ON packages(name, architecture);
CREATE INDEX idx_packages_name ON packages(name);

-- Repository queries
CREATE INDEX idx_repositories_enabled ON repositories(enabled);

-- Snapshot queries
CREATE INDEX idx_snapshots_repo_name ON snapshots(repository_id, name);

-- Sync history
CREATE INDEX idx_sync_history_repo_started ON sync_history(repository_id, started_at);
```

## Database Migrations

Chantal uses Alembic for schema migrations.

### Migration Files

```
migrations/
├── versions/
│   ├── 001_initial_schema.py
│   ├── 002_add_views.py
│   └── 003_add_sync_history.py
└── env.py
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

### Find all packages in repository

```python
repo = session.query(Repository).filter_by(id="epel9-vim").first()
packages = repo.packages
```

### Find all repositories containing a package

```python
package = session.query(Package).filter_by(sha256="f256abc...").first()
repos = package.repositories
```

### Create snapshot

```python
snapshot = Snapshot(
    repository_id="epel9-vim",
    name="2025-01",
    description="January 2025"
)
snapshot.packages = repo.packages  # Copy current packages
session.add(snapshot)
session.commit()
```

### Find packages added between snapshots

```python
snapshot1 = session.query(Snapshot).filter_by(name="2025-01").first()
snapshot2 = session.query(Snapshot).filter_by(name="2025-02").first()

added = set(snapshot2.packages) - set(snapshot1.packages)
removed = set(snapshot1.packages) - set(snapshot2.packages)
```

## Database Backends

### SQLite (Development)

**Connection string:**
```yaml
database:
  url: sqlite:///.dev/chantal-dev.db
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

## Database Size Estimates

**Typical sizes:**
- 1,000 packages: ~1 MB (SQLite) / ~500 KB (PostgreSQL)
- 10,000 packages: ~10 MB / ~5 MB
- 100,000 packages: ~100 MB / ~50 MB
- 1,000,000 packages: ~1 GB / ~500 MB

**With snapshots:**
- 10 snapshots × 10,000 packages: ~15 MB (snapshots are metadata only)

## Maintenance

### Vacuum (SQLite)

```bash
sqlite3 .dev/chantal-dev.db "VACUUM;"
```

### Analyze (PostgreSQL)

```sql
ANALYZE;
```

### Cleanup Orphaned Packages

```python
# Find packages not in any repository
orphaned = session.query(Package).filter(
    ~Package.repositories.any()
).all()
```

## Schema Diagram

```
┌─────────────┐       ┌──────────────────┐       ┌─────────────┐
│  Repository │◄─────►│ repository_      │◄─────►│   Package   │
│             │       │   packages       │       │             │
│ - id (PK)   │       │                  │       │ - sha256(PK)│
│ - name      │       │ - repository_id  │       │ - name      │
│ - type      │       │ - package_sha256 │       │ - version   │
│ - feed_url  │       │ - added_at       │       │ - arch      │
└─────┬───────┘       └──────────────────┘       └─────┬───────┘
      │                                                  │
      │                                                  │
      ▼                                                  ▼
┌─────────────┐       ┌──────────────────┐       ┌─────────────┐
│  Snapshot   │◄─────►│ snapshot_        │◄──────┤             │
│             │       │   packages       │       │             │
│ - id (PK)   │       │                  │       │             │
│ - repo_id   │       │ - snapshot_id    │       │             │
│ - name      │       │ - package_sha256 │       │             │
└─────────────┘       └──────────────────┘       └─────────────┘

┌─────────────┐       ┌──────────────────┐
│    View     │◄─────►│ view_            │
│             │       │   repositories   │
│ - name (PK) │       │                  │
│ - desc      │       │ - view_name      │
└─────┬───────┘       │ - repository_id  │
      │               │ - order          │
      │               └──────────────────┘
      ▼
┌─────────────┐       ┌──────────────────┐
│ ViewSnapshot│◄─────►│ view_snapshot_   │
│             │       │   snapshots      │
│ - id (PK)   │       │                  │
│ - view_name │       │ - view_snap_id   │
│ - name      │       │ - snapshot_id    │
└─────────────┘       └──────────────────┘
```
