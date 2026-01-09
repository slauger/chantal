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
- Python 3.9+
- PostgreSQL (for metadata storage)

---

## Quick Start

### 1. Initialize Chantal

```bash
# Create database and directory structure
chantal init
```

### 2. Configure Repositories

Create `/etc/chantal/config.yaml`:

```yaml
database:
  url: postgresql://chantal:password@localhost/chantal

storage:
  base_path: /var/lib/chantal
  pool_path: /var/lib/chantal/pool

repositories:
  - id: rhel9-baseos
    type: rpm
    feed: https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os
    enabled: true
    auth:
      type: client_cert
      cert_dir: /etc/pki/entitlement
```

### 3. Sync Repository

```bash
# Sync single repository (downloads packages to pool)
chantal repo sync --repo-id rhel9-baseos

# Sync all enabled repositories
chantal repo sync --all

# Sync with parallel workers
chantal repo sync --all --workers 3
```

### 4. Create Snapshots

```bash
# Create snapshot after sync (immutable point-in-time freeze)
chantal snapshot create --repo-id rhel9-baseos --name rhel9-2025-01-patch1

# List snapshots
chantal snapshot list

# Compare snapshots
chantal snapshot diff rhel9-baseos-20250109 rhel9-baseos-20250108

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

# Compare two snapshots (show added/removed/updated packages)
chantal snapshot diff <snapshot1> <snapshot2>

# Delete snapshot
chantal snapshot delete <snapshot-name>
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

- **Storage**: Content-addressed pool with SHA256 deduplication
- **Database**: PostgreSQL for metadata (packages, repositories, snapshots, sync history)
- **Publishing**: Hardlinks from pool to published directories (zero-copy)
- **Snapshots**: Reference-based (like Pulp 3) - immutable, efficient
- **CLI**: Click framework with pulp-admin-inspired commands

### Directory Structure

```
/var/lib/chantal/
├── pool/               # Content-addressed package storage
│   └── ab/cd/abc123...def456_package.rpm
├── config/             # Runtime configuration cache
└── tmp/                # Temporary downloads

/var/www/repos/         # Published repositories
├── rhel9-baseos/
│   ├── latest/         # Rolling latest (hardlinks to pool)
│   └── snapshots/
│       └── 20250109/   # Immutable snapshot (hardlinks to pool)
└── rhel9-appstream/
    └── ...
```

---

## Status

**🚧 Active Development - MVP Phase (Milestone 1)**

- ✅ Database models (SQLAlchemy with PostgreSQL)
- ✅ CLI framework (Click with comprehensive commands)
- ✅ Architecture design and planning
- ✅ RHEL CDN authentication PoC
- ✅ 18 tests passing
- ⏳ Configuration management (in progress)
- ⏳ RPM sync implementation
- ⏳ Publishing system

**Progress:** ~15% of MVP complete

See [`.planning/status.md`](.planning/status.md) for detailed status.

---

## Development

### Running Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_cli.py

# Run with coverage
pytest --cov=chantal --cov-report=term-missing
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
- ✅ Database models
- ⏳ Configuration management
- ⏳ Content-addressed storage
- ⏳ RPM repository sync
- ⏳ Snapshot management
- ⏳ Publishing (hardlinks)
- ⏳ CLI commands
- ⏳ HTTP proxy support

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

**Current Phase:** MVP Development (Milestone 1 - Foundation)
**Next Milestone:** Configuration Management & Storage Implementation
