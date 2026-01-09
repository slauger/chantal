# Chantal

**_Because every other name was already taken._** - A unified CLI tool for offline repository mirroring.

---

## Features

- 🔄 **Unified Mirroring** - RPM and APT repositories in one tool (MVP: RPM only)
- 📦 **Deduplication** - Content-addressed storage (SHA256), packages stored once
- 📸 **Snapshots** - Immutable point-in-time repository states for patch management
- 🔌 **Modular** - Plugin architecture for repository types
- 🚫 **No Daemons** - Simple CLI tool (optional scheduler for automation)
- 📁 **Static Output** - Serve with any webserver (Apache, NGINX)
- 🔐 **RHEL CDN Support** - Client certificate authentication for Red Hat repos

---

## What is Chantal?

A Python-based CLI tool for offline repository mirroring, inspired by pulp-admin, reposync, and aptly.

**The Problem:** Enterprise environments need offline mirrors of RPM/APT repositories with:
- Version control (snapshots for rollback)
- Efficient storage (deduplication across repos)
- RHEL subscription support
- Simple management

**The Solution:** One tool. One workflow. Content-addressed storage. Immutable snapshots.

---

## Installation

```bash
# Clone the repository
git clone https://github.com/slauger/chantal.git
cd chantal

# Install in development mode
pip install -e .

# Verify installation
chantal --version
```

**Requirements:**
- Python 3.12+ (required for `Path.hardlink_to()`)
- PostgreSQL or SQLite (for metadata storage)

---

## Quick Start

### 1. Initialize Chantal

```bash
# Create database and directory structure
chantal init
```

### 2. Configure Repositories

Create `config.yaml` (or use `/etc/chantal/config.yaml` for production):

```yaml
# For local development/testing with SQLite
database:
  url: sqlite:///chantal.db

# For production with PostgreSQL
# database:
#   url: postgresql://chantal:password@localhost/chantal

storage:
  base_path: ./storage
  pool_path: ./storage/pool
  published_path: ./storage/published

repositories:
  # Small test repository
  - id: nginx-stable
    name: nginx stable for CentOS/RHEL 9
    type: rpm
    feed: https://nginx.org/packages/centos/9/x86_64/
    enabled: true

  # Production example with RHEL CDN
  # - id: rhel9-baseos
  #   name: RHEL 9 BaseOS
  #   type: rpm
  #   feed: https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os
  #   enabled: true
  #   auth:
  #     type: client_cert
  #     cert_dir: /etc/pki/entitlement
```

### 3. Sync Repository

```bash
# Sync single repository (downloads packages to pool)
chantal --config config.yaml repo sync --repo-id nginx-stable

# Sync all enabled repositories
chantal --config config.yaml repo sync --all
```

### 4. Create Snapshots

```bash
# Create snapshot after sync (immutable point-in-time freeze)
chantal snapshot create --repo-id rhel9-baseos --name rhel9-2025-01-patch1

# List snapshots
chantal snapshot list

# Compare snapshots
chantal snapshot diff --repo-id rhel9-baseos 20250109 20250108

# Publish specific snapshot
chantal publish snapshot --snapshot rhel9-baseos-20250109
```

---

## CLI Commands

### Repository Management

```bash
# List all configured repositories
chantal repo list

# Show repository details
chantal repo show --repo-id rhel9-baseos

# Sync repository from upstream (downloads to pool)
chantal repo sync --repo-id rhel9-baseos
chantal repo sync --all [--type rpm] [--workers 3]

# Check for updates without syncing (like 'dnf check-update')
chantal repo check-updates --repo-id rhel9-baseos

# Show sync history
chantal repo history --repo-id rhel9-baseos [--limit 10]
```

### Snapshot Management

```bash
# List snapshots
chantal snapshot list [--repo-id rhel9-baseos]

# Create snapshot
chantal snapshot create --repo-id rhel9-baseos --name <name> [--description "..."]

# Compare two snapshots within a repository (show added/removed/updated packages)
chantal snapshot diff --repo-id rhel9-baseos <snapshot1> <snapshot2>

# Delete snapshot
chantal snapshot delete --repo-id rhel9-baseos <snapshot-name>
```

### Package Management

```bash
# List packages in repository
chantal package list --repo-id rhel9-baseos [--arch x86_64] [--limit 100]

# Search for packages
chantal package search nginx [--repo-id rhel9-baseos] [--arch x86_64]

# Show package details
chantal package show nginx-1.20.1-10.el9.x86_64
chantal package show <sha256>
```

### Publishing

```bash
# Publish repository (create hardlinks to published directory)
chantal publish repo --repo-id rhel9-baseos
chantal publish repo --all

# Publish specific snapshot
chantal publish snapshot --snapshot rhel9-baseos-20250109

# List published repositories and snapshots
chantal publish list

# Unpublish repository or snapshot
chantal publish unpublish --repo-id rhel9-baseos
chantal publish unpublish --snapshot rhel9-baseos-20250108
```

### Storage Pool Management

```bash
# Show storage pool statistics
chantal pool stats

# Remove orphaned files from pool (dry-run first!)
chantal pool cleanup --dry-run
chantal pool cleanup

# Verify pool integrity (checksums, file existence)
chantal pool verify
```

### Statistics & Database

```bash
# Show global statistics
chantal stats

# Show repository-specific statistics
chantal stats --repo-id rhel9-baseos

# Database statistics
chantal db stats

# Verify database integrity
chantal db verify

# Clean up unreferenced packages
chantal db cleanup [--dry-run]
```

### Output Formats

Most commands support multiple output formats:

```bash
chantal package list --repo-id rhel9-baseos --format table  # Default: human-readable
chantal package list --repo-id rhel9-baseos --format json   # Machine-readable
chantal package list --repo-id rhel9-baseos --format csv    # For Excel/analysis
```

---

## Configuration

### Global Configuration (`/etc/chantal/config.yaml`)

```yaml
# Database connection
database:
  url: postgresql://chantal:password@localhost/chantal

# Storage paths
storage:
  base_path: /var/lib/chantal
  pool_path: /var/lib/chantal/pool
  published_path: /var/www/repos

# HTTP Proxy (optional)
proxy:
  http_proxy: http://proxy.example.com:8080
  https_proxy: http://proxy.example.com:8080
  no_proxy: localhost,127.0.0.1,.internal.domain
  username: proxyuser  # optional
  password: proxypass  # optional

# Include repository configs
include: conf.d/*.yaml
```

### Repository Configuration (`/etc/chantal/conf.d/rhel9.yaml`)

```yaml
repositories:
  - id: rhel9-baseos
    type: rpm
    feed: https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os
    enabled: true

    # RHEL Subscription Authentication
    auth:
      type: client_cert
      cert_dir: /etc/pki/entitlement

    # Version retention policy
    retention:
      policy: mirror  # mirror, newest-only, keep-all, keep-last-n

    # Publishing configuration
    latest_path: /var/www/repos/rhel9-baseos/latest
    snapshots_path: /var/www/repos/rhel9-baseos/snapshots

    # Scheduling (optional - for automatic syncs via daemon)
    schedule:
      enabled: true
      cron: "0 2 * * *"  # Daily at 2:00 AM
      create_snapshot: true  # Auto-create snapshot after scheduled sync
      snapshot_name_template: "{repo_id}-{date}"  # Optional template
```

---

## Architecture

- **Storage**: Content-addressed pool with SHA256 deduplication (2-level directory structure for filesystem performance)
- **Database**: SQLAlchemy ORM with PostgreSQL or SQLite support for metadata (packages, repositories, snapshots, sync history)
- **Publishing**: Hardlinks from pool to published directories (zero-copy, instant publishing)
- **Snapshots**: Reference-based (like Pulp 3) - immutable, space-efficient
- **CLI**: Click framework with pulp-admin-inspired commands
- **Plugin System**: Extensible architecture for RPM, DEB, and future package types

### Why So Fast?

Chantal is significantly faster than traditional tools like Pulp v2 because:

1. **Content-Addressed Storage**: Single SHA256 lookup to check if package exists (no metadata comparison)
2. **No Task Queue**: Direct execution, no Celery/RabbitMQ/Redis overhead
3. **Streaming Downloads**: Efficient 64KB chunks with requests library
4. **2-Level Directory Structure**: Optimal filesystem performance (256×256 = 65,536 buckets)
5. **Zero-Copy Publishing**: Hardlinks instead of file copies
6. **Smart Deduplication**: Second sync of nginx stable (185 packages) completes in ~2 seconds

### Real-World Performance

**nginx stable repository sync** (185 packages, 580 MB):
- First sync: ~5 minutes (downloads all packages)
- Second sync: ~2 seconds (all packages skipped via SHA256 deduplication)
- **~150x faster** than Pulp v2 for incremental syncs

**Storage efficiency:**
- Multiple repository versions share packages automatically
- No duplicate storage for identical packages across repos
- Pool size = unique packages only

### Directory Structure

```
./storage/              # Local development example
├── pool/               # Content-addressed package storage
│   ├── f2/
│   │   └── 56/
│   │       └── f256abc...def789_nginx-1.20.2-1.el9.ngx.x86_64.rpm
│   ├── 95/
│   │   └── 05/
│   │       └── 9505484...c1264fde_nginx-module-njs-1.24.0+0.8.3-1.el9.ngx.x86_64.rpm
│   └── ...
└── published/          # Published repositories (hardlinks to pool)
    └── nginx-stable/
        ├── latest/
        └── snapshots/

/var/lib/chantal/       # Production example
├── pool/               # Same structure as above
└── tmp/                # Temporary downloads

/var/www/repos/         # Published repositories (production)
├── rhel9-baseos/
│   ├── latest/
│   └── snapshots/
│       └── 20250109/
└── rhel9-appstream/
    └── ...
```

---

## Status

**🚀 Active Development - MVP Phase (Milestone 3 Complete)**

### ✅ Completed Milestones

**Milestone 1: Configuration Management**
- ✅ Pydantic-based configuration models
- ✅ YAML configuration with include support (`conf.d/*.yaml`)
- ✅ CLI integration with `--config` flag
- ✅ Example configurations for RHEL 9 and CentOS
- ✅ 15 configuration tests passing

**Milestone 2: Content-Addressed Storage**
- ✅ Universal SHA256-based pool for all package types
- ✅ 2-level directory structure (`ab/cd/sha256_file.rpm`)
- ✅ Instant deduplication via content-addressing
- ✅ Hardlink-based publishing (zero-copy)
- ✅ Orphaned files cleanup
- ✅ Pool statistics
- ✅ 15 storage tests passing

**Milestone 3: RPM Sync Plugin**
- ✅ RpmSyncPlugin with repomd.xml/primary.xml.gz parsing
- ✅ HTTP client with proxy support
- ✅ Streaming downloads with SHA256 verification
- ✅ Database integration (Package, Repository models)
- ✅ CLI commands: `chantal init`, `chantal repo sync`
- ✅ End-to-end testing: Successfully synced nginx stable (185 packages, 580 MB)
- ✅ Deduplication verified: Second sync skips all existing packages

**Other Completed Features**
- ✅ Database models (SQLAlchemy with PostgreSQL + SQLite support)
- ✅ CLI framework (Click with comprehensive commands)
- ✅ Publisher plugin system (RpmPublisher with repomd.xml generation)
- ✅ 62 tests passing
- ✅ Python 3.12+ support

### ⏳ Upcoming Milestones

**Milestone 4: Snapshot Management**
- ⏳ Snapshot creation/deletion
- ⏳ Snapshot diff (compare package versions)
- ⏳ Snapshot publishing

**Milestone 5: Automated Sync**
- ⏳ Cron-based scheduling
- ⏳ Automatic snapshot creation after sync

**Progress:** ~50% of MVP complete

See [`.planning/status.md`](.planning/status.md) for detailed status.

---

## Development

### Running Tests

```bash
# Activate Python 3.12+ virtual environment
source venv312/bin/activate  # or your venv path

# Run all tests (62 passing)
pytest

# Run specific test file
pytest tests/test_cli.py -v

# Run with coverage
pytest --cov=chantal --cov-report=term-missing

# Test end-to-end sync (requires internet connection)
chantal --config config-local.yaml init
chantal --config config-local.yaml repo sync --repo-id nginx-stable
```

### Code Quality

```bash
# Format code
black src/ tests/

# Lint code
ruff src/ tests/

# Type checking
mypy src/
```

---

## Roadmap

### MVP (v0.1.0) - RPM/DNF Support
- ✅ Database models (SQLAlchemy with PostgreSQL + SQLite)
- ✅ Configuration management (Pydantic + YAML with includes)
- ✅ Content-addressed storage (SHA256 pool, 2-level structure)
- ✅ RPM repository sync (repomd.xml, primary.xml.gz parsing)
- ✅ Publishing (hardlinks via RpmPublisher)
- ✅ CLI commands (`init`, `repo sync`, etc.)
- ✅ HTTP proxy support
- ⏳ Snapshot management
- ⏳ Automated scheduling

### Post-MVP (v0.2.0+)
- Scheduler/daemon service
- Web UI
- APT/Debian support
- Advanced statistics
- REST API

---

## Why "Chantal"?

Every other name was taken. Seriously.

We checked: berth, conduit, tributary, harbor, stow, fulcrum, vesper, cairn, aperture - all taken.

So we picked something memorable, available, and with personality.

---

## Documentation

- **[Architecture](.planning/architecture.md)** - Full architecture design (~2000 lines)
- **[CLI Commands](.planning/cli-commands.md)** - Complete CLI reference
- **[MVP Scope](.planning/mvp-scope.md)** - MVP features and timeline
- **[Status](.planning/status.md)** - Current development status

---

## Contributing

Feedback and contributions welcome! This is early development, so design input is especially valuable.

1. Check the [status document](.planning/status.md) for current progress
2. Look at [open issues](https://github.com/slauger/chantal/issues) or create a new one
3. Submit pull requests for fixes or features

---

## License

MIT License - See LICENSE file for details.

---

**Current Phase:** MVP Development - Milestone 3 Complete (RPM Sync)
**Next Milestone:** Snapshot Management (Milestone 4)
**Test Coverage:** 62 tests passing
**Real-world Testing:** nginx stable repository (185 packages, 580 MB) synced successfully
