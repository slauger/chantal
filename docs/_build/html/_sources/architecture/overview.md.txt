# Architecture Overview

Chantal follows a clean, modular architecture designed for simplicity and extensibility.

## Core Principles

1. **Content-Addressed Storage** - SHA256-based deduplication
2. **Plugin Architecture** - Extensible repository type support
3. **Database-Backed Metadata** - Fast lookups, no re-scanning
4. **Hardlink-Based Publishing** - Zero-copy, instant publishing
5. **No Daemons** - Simple CLI tool, no background services

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     CLI Layer                           │
│  (Click commands: init, repo, snapshot, publish, etc.)  │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│                  Core Layer                             │
│  • Config Management (Pydantic models)                  │
│  • Storage Manager (content-addressed pool)             │
│  • Database Manager (SQLAlchemy ORM)                    │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│                 Plugin Layer                            │
│  • Sync Plugins (RPM, APT, PyPI)                        │
│  • Publisher Plugins (metadata generation)              │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│              External Systems                           │
│  • Upstream Repositories (HTTP/HTTPS)                   │
│  • Database (PostgreSQL/SQLite)                         │
│  • Filesystem (pool, published)                         │
└─────────────────────────────────────────────────────────┘
```

## Components

### CLI Layer

**Technologies:** Click (Python CLI framework)

**Responsibilities:**
- Parse command-line arguments
- Load configuration
- Initialize services
- Execute commands
- Format output

**Key Files:**
- `src/chantal/cli/` - All CLI commands
- `src/chantal/cli/repo.py` - Repository management commands
- `src/chantal/cli/snapshot.py` - Snapshot commands
- `src/chantal/cli/publish.py` - Publishing commands

### Core Layer

#### Configuration Management

**Technologies:** Pydantic (validation), PyYAML (parsing)

**Responsibilities:**
- Load and parse YAML configuration
- Validate configuration structure
- Provide type-safe configuration access
- Handle configuration includes

**Key Files:**
- `src/chantal/core/config.py` - Configuration models
- `GlobalConfig`, `RepositoryConfig`, `FilterConfig`

#### Storage Manager

**Technologies:** Python pathlib, SHA256 hashing

**Responsibilities:**
- Content-addressed storage (2-level SHA256-based directories)
- Deduplication (automatic via content addressing)
- Hardlink creation for publishing
- Pool statistics and verification

**Key Files:**
- `src/chantal/core/storage.py` - StorageManager class

**Storage Layout:**
```
pool/
├── f2/
│   └── 56/
│       └── f256abc...def789_nginx-1.20.2-1.el9.x86_64.rpm
├── 95/
│   └── 05/
│       └── 9505484...c1264fde_nginx-module-njs-1.24.0.rpm
└── ...
```

#### Database Manager

**Technologies:** SQLAlchemy (ORM), Alembic (migrations)

**Responsibilities:**
- Package metadata storage
- Repository state tracking
- Snapshot management
- Sync history
- Junction tables for many-to-many relationships

**Key Files:**
- `src/chantal/db/models.py` - SQLAlchemy models
- `src/chantal/db/session.py` - Database session management

**Database Models:**
- `Repository` - Configured repositories
- `Package` - Content-addressed packages
- `Snapshot` - Immutable snapshots
- `SyncHistory` - Sync tracking

### Plugin Layer

#### Sync Plugins

**Technologies:** ABC (Abstract Base Classes), Requests (HTTP)

**Responsibilities:**
- Fetch repository metadata
- Parse package lists
- Apply filters
- Download packages
- Verify checksums

**Plugins:**
- `RpmSyncPlugin` - RPM/DNF/YUM repositories
- `DebSyncPlugin` - APT repositories (future)
- `PypiSyncPlugin` - Python Package Index (future)

**Key Files:**
- `src/chantal/plugins/base.py` - Base plugin interface
- `src/chantal/plugins/rpm_sync.py` - RPM sync implementation
- `src/chantal/plugins/rpm.py` - RPM publisher implementation

#### Publisher Plugins

**Technologies:** XML generation, compression (gzip, xz)

**Responsibilities:**
- Generate repository metadata
- Create hardlinks to pool
- Compress metadata files
- Sign repositories (future)

**Key Files:**
- `src/chantal/plugins/base.py` - Publisher plugin interface
- `src/chantal/plugins/rpm.py` - RPM publisher (repomd.xml, primary.xml.gz)

## Data Flow

### Sync Workflow

```
1. User: chantal repo sync --repo-id example
       │
2. CLI loads configuration
       │
3. Identify repository type (RPM)
       │
4. Load RpmSyncPlugin
       │
5. Fetch repomd.xml from upstream
       │
6. Parse primary.xml.gz (package list)
       │
7. Apply filters (patterns, metadata, post-processing)
       │
8. For each package:
       │
       ├─> Calculate SHA256
       ├─> Check if exists in pool
       ├─> Download if missing
       └─> Store in pool (f2/56/f256abc...rpm)
       │
9. Update database (packages, repository associations)
       │
10. Done!
```

### Publish Workflow

```
1. User: chantal publish repo --repo-id example
       │
2. Query database for repository packages
       │
3. Load RpmPublisher plugin
       │
4. Create target directory structure
       │
5. Create hardlinks from pool to published/
       │
6. Generate repomd.xml
       │
7. Generate primary.xml.gz
       │
8. Generate filelists.xml.gz (future)
       │
9. Done! Repository ready to serve
```

## Technology Stack

### Runtime
- **Python 3.10+** - Required for Path.hardlink_to()
- **SQLAlchemy** - Database ORM
- **Alembic** - Database migrations
- **Click** - CLI framework
- **Requests** - HTTP client
- **lxml** - XML parsing
- **Pydantic** - Configuration validation
- **PyYAML** - YAML parsing

### Development
- **pytest** - Testing framework
- **black** - Code formatting
- **ruff** - Linting
- **mypy** - Type checking

### Database
- **PostgreSQL** (production) - Recommended for large deployments
- **SQLite** (development) - Simple, embedded database

## Design Decisions

### Why Content-Addressed Storage?

**Alternatives considered:**
1. Flat directory with all packages
2. Mirror upstream directory structure
3. Hash-based subdirectories (chosen)

**Chosen approach:**
- 2-level SHA256-based directories (f2/56/f256...)
- Automatic deduplication
- Efficient filesystem performance (65,536 buckets)

### Why Database for Metadata?

**Alternatives considered:**
1. Scan filesystem on every operation
2. JSON/YAML metadata files
3. Database (chosen)

**Chosen approach:**
- PostgreSQL/SQLite for metadata
- Fast queries
- Relationship management
- Transactional integrity

### Why Hardlinks for Publishing?

**Alternatives considered:**
1. Copy files (wastes space)
2. Symlinks (may break permissions)
3. Hardlinks (chosen)

**Chosen approach:**
- Zero-copy (no disk space wasted)
- Instant publishing (milliseconds)
- Atomic updates
- Preserves permissions

## Performance Characteristics

### Sync Performance
- First sync: Limited by network bandwidth
- Subsequent syncs: Fast (skip existing packages via SHA256 check)
- Filter overhead: Minimal (in-memory regex matching)

### Storage Efficiency
- Typical deduplication: 60-80% across RHEL variants
- Snapshot overhead: Near-zero (metadata only)
- Publishing overhead: Zero (hardlinks)

### Database Performance
- SQLite: Good for <100K packages
- PostgreSQL: Excellent for millions of packages
- Indexes on: sha256, (name, arch), repo_id

## Extensibility Points

### Adding Repository Types

1. Implement `SyncPlugin` interface
2. Implement `PublisherPlugin` interface
3. Register plugin in plugin registry
4. Add configuration validation

Example: APT plugin (future)

### Adding Filter Types

1. Add to `FilterConfig` in `config.py`
2. Implement filter logic in plugin
3. Add tests

### Adding Output Formats

1. Add format option to CLI command
2. Implement formatter (JSON, CSV, etc.)
3. Update command output logic

## Security Considerations

1. **Certificate validation:** Always verify SSL certificates
2. **Checksum verification:** All packages verified via SHA256
3. **Database injection:** SQLAlchemy prevents SQL injection
4. **Path traversal:** All paths validated and normalized
5. **Permissions:** Follow principle of least privilege

## Future Enhancements

1. **Parallel downloads:** Download multiple packages concurrently
2. **Delta syncs:** Only download package deltas
3. **Signature verification:** GPG signature checking
4. **Compression:** Compress pool storage
5. **Web UI:** Read-only web interface
6. **REST API:** HTTP API for automation
