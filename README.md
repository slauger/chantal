# Chantal

**_Because every other name was already taken._** - A unified CLI tool for offline repository mirroring.

---

## Features

- 🔄 **Unified Mirroring** - RPM and APT repositories in one tool (MVP: RPM only)
- 📦 **Deduplication** - Content-addressed storage (SHA256), packages stored once
- 📸 **Snapshots** - Immutable point-in-time repository states for patch management
- 🔍 **Views** - Virtual repositories combining multiple repos (e.g., BaseOS + AppStream + EPEL)
- 🔌 **Modular** - Plugin architecture for repository types
- 🚫 **No Daemons** - Simple CLI tool (optional scheduler for future automation)
- 📁 **Static Output** - Serve with any webserver (Apache, NGINX)
- 🔐 **RHEL CDN Support** - Client certificate authentication for Red Hat repos
- 🎯 **Smart Filtering** - Pattern-based package filtering with post-processing
- ⚡ **Fast Updates** - Check for updates without downloading (like `dnf check-update`)

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
- Python 3.10+ (required for `Path.hardlink_to()`)
- PostgreSQL or SQLite (for metadata storage)

### Container Image (Recommended)

Pre-built container images based on Red Hat UBI9 are available from GitHub Container Registry:

```bash
# Pull the latest image
docker pull ghcr.io/slauger/chantal:latest

# Or use podman
podman pull ghcr.io/slauger/chantal:latest
```

**Run with Docker/Podman:**

```bash
# Create directories for persistent storage
mkdir -p config data repos

# Run chantal commands
docker run --rm \
  -v $(pwd)/config:/etc/chantal:ro \
  -v $(pwd)/data:/var/lib/chantal \
  -v $(pwd)/repos:/var/www/repos \
  ghcr.io/slauger/chantal:latest --help

# Initialize chantal
docker run --rm \
  -v $(pwd)/config:/etc/chantal \
  -v $(pwd)/data:/var/lib/chantal \
  -v $(pwd)/repos:/var/www/repos \
  ghcr.io/slauger/chantal:latest init

# Sync repositories
docker run --rm \
  -v $(pwd)/config:/etc/chantal:ro \
  -v $(pwd)/data:/var/lib/chantal \
  -v $(pwd)/repos:/var/www/repos \
  ghcr.io/slauger/chantal:latest repo sync --all
```

**Using Docker Compose:**

Create `docker-compose.yml`:

```yaml
version: '3.8'

services:
  chantal:
    image: ghcr.io/slauger/chantal:latest
    volumes:
      - ./config:/etc/chantal:ro
      - ./data:/var/lib/chantal
      - ./repos:/var/www/repos
    environment:
      - CHANTAL_CONFIG=/etc/chantal/config.yaml
    # Override entrypoint for long-running commands
    entrypoint: []
    command: chantal repo sync --all

  # Optional: PostgreSQL database
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

**Volumes:**
- `/etc/chantal` - Configuration files (read-only recommended)
- `/var/lib/chantal` - Storage pool and database
- `/var/www/repos` - Published repositories (served via web server)

**Available Tags:**
- `latest` - Latest build from main branch
- `v1.0.0`, `v1.0`, `v1` - Semantic version tags
- `main-<sha>` - Specific commit builds

---

## Quick Start

### 1. Initialize Chantal

```bash
# Create database and directory structure
chantal init
```

Output:
```
Chantal initialization...
Database: sqlite:///.dev/chantal-dev.db
Storage base path: ./.dev/dev-storage
Pool path: ./.dev/dev-storage/pool
Published path: ./.dev/dev-storage/published

Creating directories...
  ✓ Created: ./.dev/dev-storage
  ✓ Created: ./.dev/dev-storage/pool
  ✓ Created: ./.dev/dev-storage/published

Initializing database...
  ✓ Database schema created

✓ Chantal initialization complete!
```

### 2. Configure Repositories

Create `config.yaml` (or use `.dev/config.yaml` for development):

```yaml
# Database
database:
  url: sqlite:///.dev/chantal-dev.db  # or postgresql://...

# Storage paths
storage:
  base_path: ./.dev/dev-storage
  pool_path: ./.dev/dev-storage/pool
  published_path: ./.dev/dev-storage/published

# Include repository definitions
include: "conf.d/*.yaml"
```

Repository definitions in `conf.d/epel9.yaml`:

```yaml
repositories:
  # EPEL 9 - vim packages only (latest version)
  - id: epel9-vim-latest
    name: EPEL 9 - vim (latest)
    type: rpm
    feed: https://dl.fedoraproject.org/pub/epel/9/Everything/x86_64/
    enabled: true
    filters:
      patterns:
        include: ["^vim-.*"]
        exclude: [".*-debug.*"]
      metadata:
        architectures:
          include: ["x86_64", "noarch"]
      rpm:
        exclude_source_rpms: true
      post_processing:
        only_latest_version: true
```

For RHEL with subscription (`.dev/conf.d/rhel9-baseos.yaml`):

```yaml
repositories:
  - id: rhel9-baseos-vim-latest
    name: RHEL 9 BaseOS - vim (latest)
    type: rpm
    feed: https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os
    enabled: true
    # RHEL CDN authentication (requires subscription)
    ssl:
      ca_bundle: ".dev/combined-ca-bundle.pem"
      client_cert: ".dev/rhel-entitlement.pem"
      client_key: ".dev/rhel-entitlement-key.pem"
      verify: true
    filters:
      patterns:
        include: ["^vim-.*"]
        exclude: [".*-debug.*"]
      metadata:
        architectures:
          include: ["x86_64", "noarch"]
      rpm:
        exclude_source_rpms: true
      post_processing:
        only_latest_version: true
```

### 3. List Configured Repositories

```bash
chantal repo list
```

Output:
```
Configured Repositories:

ID                                Type Enabled Packages Last Sync
------------------------------------------------------------------------
rhel9-baseos-vim-latest           rpm  Yes            4 2026-01-10 14:34
rhel9-appstream-nginx-latest      rpm  Yes           10 2026-01-10 14:34
rhel9-appstream-httpd-latest      rpm  Yes           26 2026-01-10 14:29
epel9-htop-latest                 rpm  Yes            1 2026-01-10 14:27
epel9-monitoring-latest           rpm  Yes            1 2026-01-10 14:27

Total: 16 repository(ies)
```

### 4. Sync Repository

```bash
# Sync single repository (downloads packages to pool)
chantal repo sync --repo-id epel9-vim-latest
```

Output:
```
Syncing repository: epel9-vim-latest
Feed URL: https://dl.fedoraproject.org/pub/epel/9/Everything/x86_64/
Fetching repomd.xml...
Primary metadata location: repodata/c80c...d2f3-primary.xml.gz
Fetching primary.xml.gz...
Found 24868 packages in repository
Filtered out 24865 packages, 3 remaining
Already have 0 packages in pool

[1/3] Processing vim-common-9.0.2120-1.el9.x86_64
  → Downloading from https://dl.fedoraproject.org/...
  → Downloaded 7.42 MB

[2/3] Processing vim-enhanced-9.0.2120-1.el9.x86_64
  → Downloading from https://dl.fedoraproject.org/...
  → Downloaded 1.89 MB

[3/3] Processing vim-filesystem-9.0.2120-1.el9.noarch
  → Already in pool (SHA256: 3f4a2...)
  → Skipped

Sync complete!
  Downloaded: 2
  Skipped: 1
  Total size: 9.31 MB

✓ Sync completed successfully!
  Total packages: 3
  Downloaded: 2
  Skipped (already in pool): 1
  Data transferred: 9.31 MB
```

**Sync multiple repositories with patterns:**

```bash
# Sync all EPEL repositories
chantal repo sync --pattern "epel9-*"

# Sync all enabled repositories
chantal repo sync --all

# Sync only RPM repositories
chantal repo sync --all --type rpm

# Parallel workers (future feature)
chantal repo sync --all --workers 3
```

### 5. Check for Updates

Check for available updates **without downloading**:

```bash
chantal repo check-updates --repo-id rhel9-appstream-nginx-latest
```

Output when repository is up-to-date:
```
Checking for updates: rhel9-appstream-nginx-latest
Feed URL: https://cdn.redhat.com/content/dist/rhel9/9/x86_64/appstream/os
Fetching repomd.xml...
Fetching primary.xml...
Found 29969 packages in upstream repository
Filtered out 29959 packages, 10 remaining
Currently have 10 unique packages (by name-arch)

Check complete!
  Updates available: 0
  Total size: 0.00 MB

✓ No updates available. Repository is up to date.
```

Output when updates are available:
```
Available Updates (3 packages):

Name      Arch    Local Version         Remote Version        Size
========================================================================
kernel    x86_64  5.14.0-360.el9        5.14.0-362.el9        85.0 MB
nginx     x86_64  2:1.20.1-10.el9       2:1.20.2-1.el9        1.2 MB
httpd     x86_64  2.4.50-1.el9          2.4.51-1.el9          1.5 MB

Summary: 3 package update(s) available (87.7 MB)

Run 'chantal repo sync --repo-id rhel9-appstream-nginx-latest' to download updates
```

**Check multiple repositories:**

```bash
# Check all EPEL repos
chantal repo check-updates --pattern "epel9-*"

# Check all enabled repositories
chantal repo check-updates --all
```

### 6. Show Repository Details

```bash
chantal repo show --repo-id epel9-vim-latest
```

Output:
```
Repository: epel9-vim-latest

Basic Information:
  ID: epel9-vim-latest
  Name: EPEL 9 - vim (latest)
  Type: rpm
  Enabled: Yes
  Feed URL: https://dl.fedoraproject.org/pub/epel/9/Everything/x86_64/

Sync Statistics:
  Total Packages: 3
  Last Sync: 2026-01-10 14:27:35
  Sync Status: Success

Storage Statistics:
  Total Size: 9.31 MB (9,758,240 bytes)
  Average Package Size: 3.10 MB

Packages (showing first 10):
  vim-common-9.0.2120-1.el9.x86_64 (7.42 MB)
  vim-enhanced-9.0.2120-1.el9.x86_64 (1.89 MB)
  vim-filesystem-9.0.2120-1.el9.noarch (42 KB)
```

### 7. Create Snapshots

```bash
# Create snapshot after sync (immutable point-in-time freeze)
chantal snapshot create \
  --repo-id rhel9-baseos-vim-latest \
  --name 20250110 \
  --description "January 2025 patch baseline"

# List snapshots
chantal snapshot list

# List snapshots for specific repository
chantal snapshot list --repo-id rhel9-baseos-vim-latest

# Compare snapshots (show added/removed/updated packages)
chantal snapshot diff \
  --repo-id rhel9-baseos-vim-latest \
  20250110 20250109

# Delete snapshot
chantal snapshot delete \
  --repo-id rhel9-baseos-vim-latest \
  20250108
```

### 8. Create Views (Virtual Repositories)

**Views** combine multiple repositories into a single virtual repository. This is useful for:
- **Combining RHEL channels**: BaseOS + AppStream + CRB in one repository
- **Adding EPEL to RHEL**: Create "RHEL + EPEL" view for mixed packages
- **Custom stacks**: Web server stack (BaseOS + nginx + httpd), monitoring stack (EPEL tools), etc.

**Important**: All packages from all repositories are included (NO deduplication). The client (yum/dnf) decides which version to use based on repository priority.

#### Configure Views

Create `conf.d/views.yaml`:

```yaml
views:
  # RHEL 9 Complete - All channels combined
  - name: rhel9-complete
    description: "RHEL 9 - All repositories (BaseOS + AppStream + CRB)"
    repos:
      - rhel9-baseos-vim-latest
      - rhel9-appstream-nginx-latest
      - rhel9-appstream-httpd-latest
      - rhel9-crb-python-latest

  # RHEL 9 Web Server Stack
  - name: rhel9-webserver
    description: "RHEL 9 Web Server Stack (BaseOS + nginx + httpd)"
    repos:
      - rhel9-baseos-vim-latest
      - rhel9-appstream-nginx-latest
      - rhel9-appstream-httpd-latest

  # Mixed RHEL + EPEL
  - name: rhel9-plus-epel
    description: "RHEL 9 + EPEL Combined"
    repos:
      - rhel9-baseos-vim-latest
      - rhel9-appstream-nginx-latest
      - epel9-htop-latest
      - epel9-monitoring-latest
```

#### List and Show Views

```bash
# List all configured views
chantal view list

# Show view details (repositories, package count)
chantal view show --name rhel9-complete
```

#### Publish Views

```bash
# Publish view (combines all repos at current state)
chantal publish view --name rhel9-complete

# Result: published/views/rhel9-complete/latest/
# Configure on clients:
#   [rhel9-complete]
#   name=RHEL 9 Complete
#   baseurl=http://mirror.example.com/chantal/views/rhel9-complete/latest/
#   enabled=1
#   gpgcheck=0
```

#### Create Atomic View Snapshots

Create snapshots of ALL repositories in a view simultaneously:

```bash
# Create atomic snapshot of entire view
chantal snapshot create \
  --view rhel9-complete \
  --name 2025-01-10 \
  --description "January 2025 baseline"

# This creates:
# - Individual snapshots for each repository in the view
# - A view snapshot that references all repository snapshots
# - Ensures all repositories are frozen at the same point in time

# Publish view snapshot
chantal publish snapshot \
  --view rhel9-complete \
  --snapshot 2025-01-10

# Result: published/views/rhel9-complete/snapshots/2025-01-10/
```

**Benefits of View Snapshots:**
- **Atomic freezes**: All repositories in view frozen simultaneously
- **Patch baselines**: Create monthly baselines across all RHEL channels
- **Testing**: Freeze environment for testing, then promote to production
- **Rollback**: Roll back entire stack (BaseOS + AppStream + EPEL) to previous snapshot

#### Compliance/Audit: Export Snapshot Content

For compliance or audit purposes, export exactly what was in a snapshot:

```bash
# Show package list (human-readable table)
chantal snapshot content --view rhel9-webserver --snapshot 2025-01-10

# Export as JSON (for tools/automation)
chantal snapshot content \
  --view rhel9-webserver \
  --snapshot 2025-01-10 \
  --format json > audit/rhel9-webserver-2025-01-10.json

# Export as CSV (for Excel/reporting)
chantal snapshot content \
  --view rhel9-webserver \
  --snapshot 2025-01-10 \
  --format csv > audit/rhel9-webserver-2025-01-10.csv
```

**CSV includes:**
- View name, snapshot name, repository ID
- Package name, epoch, version, release, architecture
- NEVRA (full package identifier)
- SHA256 checksum (for integrity verification)
- File size, filename

Perfect for:
- Compliance reports ("What was deployed on 2025-01-10?")
- Security audits (verify exact package versions)
- Change management (track package changes over time)

---

## CLI Commands

### Repository Management

```bash
# List all configured repositories
chantal repo list [--format table|json]

# Show repository details
chantal repo show --repo-id <repo-id> [--format table|json]

# Sync repository from upstream (downloads to pool)
chantal repo sync --repo-id <repo-id>
chantal repo sync --all [--type rpm] [--workers 3]
chantal repo sync --pattern "epel9-*" [--type rpm]

# Check for updates without downloading (like 'dnf check-update')
chantal repo check-updates --repo-id <repo-id>
chantal repo check-updates --all
chantal repo check-updates --pattern "rhel9-*"

# Show sync history
chantal repo history --repo-id <repo-id> [--limit 10]
```

### Snapshot Management

```bash
# List snapshots
chantal snapshot list [--repo-id <repo-id>]

# Create repository snapshot
chantal snapshot create \
  --repo-id <repo-id> \
  --name <name> \
  [--description "..."]

# Create view snapshot (atomic snapshot of all repos in view)
chantal snapshot create \
  --view <view-name> \
  --name <name> \
  [--description "..."]

# Show snapshot content (package list) - for compliance/audit
chantal snapshot content --repo-id <repo-id> --snapshot <name> [--format table|json|csv]
chantal snapshot content --view <view-name> --snapshot <name> [--format table|json|csv]

# Compare two snapshots (show added/removed/updated packages)
chantal snapshot diff --repo-id <repo-id> <snapshot1> <snapshot2>

# Delete snapshot
chantal snapshot delete --repo-id <repo-id> <snapshot-name>
```

### View Management

```bash
# List all configured views
chantal view list

# Show view details (repositories, package count)
chantal view show --name <view-name>
```

### Package Management

```bash
# List packages in repository
chantal package list --repo-id <repo-id> [--arch x86_64] [--limit 100]

# Search for packages
chantal package search <query> [--repo-id <repo-id>] [--arch x86_64]

# Show package details
chantal package show <name-version-release.arch>
chantal package show <sha256>
```

### Publishing

```bash
# Publish repository (create hardlinks to published directory)
chantal publish repo --repo-id <repo-id>
chantal publish repo --all

# Publish view (combines all repos into one virtual repository)
chantal publish view --name <view-name>

# Publish repository snapshot
chantal publish snapshot --snapshot <name> --repo-id <repo-id>

# Publish view snapshot
chantal publish snapshot --snapshot <name> --view <view-name>

# List published repositories and snapshots
chantal publish list

# Unpublish repository or snapshot
chantal publish unpublish --repo-id <repo-id>
chantal publish unpublish --snapshot <repo-id>-<name>
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

### Statistics & Database (Upcoming in Milestone 5)

```bash
# Show global statistics
chantal stats

# Show repository-specific statistics
chantal stats --repo-id <repo-id>

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
chantal repo list --format table  # Default: human-readable
chantal repo list --format json   # Machine-readable
```

---

## Configuration

### Configuration File Priority

Chantal looks for configuration files in this order:

1. **`--config` CLI flag** (highest priority)
   ```bash
   chantal --config /path/to/config.yaml repo list
   ```

2. **`CHANTAL_CONFIG` environment variable**
   ```bash
   export CHANTAL_CONFIG=/path/to/config.yaml
   chantal repo list
   ```

3. **Default locations** (searched in order):
   - `/etc/chantal/config.yaml` (production)
   - `~/.config/chantal/config.yaml` (user)
   - `./config.yaml` (current directory)

**Development tip:** Use `CHANTAL_CONFIG` to avoid typing `--config .dev/config.yaml` repeatedly:
```bash
export CHANTAL_CONFIG=.dev/config.yaml
chantal repo sync --repo-id epel9-vim-latest
chantal repo check-updates --all
```

### Global Configuration

The main config file can be placed in any of the locations above

```yaml
# Database connection
database:
  url: postgresql://chantal:password@localhost/chantal
  # or for development:
  # url: sqlite:///.dev/chantal-dev.db

# Storage paths
storage:
  base_path: /var/lib/chantal
  pool_path: /var/lib/chantal/pool
  published_path: /var/www/repos

# Global HTTP Proxy (optional - can be overridden per-repo)
proxy:
  http_proxy: http://proxy.example.com:8080
  https_proxy: http://proxy.example.com:8080
  no_proxy: localhost,127.0.0.1,.internal.domain
  username: proxyuser  # optional
  password: proxypass  # optional

# Global SSL/TLS settings (optional - can be overridden per-repo)
ssl:
  ca_bundle: /path/to/custom-ca-bundle.pem
  verify: true

# Include repository configs
include: conf.d/*.yaml
```

### Repository Configuration

Repository definitions can be split across multiple files in `conf.d/`:

**Example: `/etc/chantal/conf.d/rhel9.yaml`**

```yaml
repositories:
  - id: rhel9-baseos-vim-latest
    name: RHEL 9 BaseOS - vim (latest)
    type: rpm
    feed: https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os
    enabled: true

    # RHEL Subscription Authentication
    ssl:
      ca_bundle: /etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem
      client_cert: /etc/pki/entitlement/1234567890.pem
      client_key: /etc/pki/entitlement/1234567890-key.pem
      verify: true

    # Package filtering
    filters:
      patterns:
        include: ["^vim-.*"]
        exclude: [".*-debug.*", ".*-devel$"]
      metadata:
        architectures:
          include: ["x86_64", "noarch"]
      rpm:
        exclude_source_rpms: true
      post_processing:
        only_latest_version: true  # Keep only latest version

    # Version retention policy
    retention:
      policy: mirror  # mirror, newest-only, keep-all, keep-last-n

    # Publishing configuration
    latest_path: /var/www/repos/rhel9-baseos/latest
    snapshots_path: /var/www/repos/rhel9-baseos/snapshots
```

**Example: `/etc/chantal/conf.d/epel9.yaml`**

```yaml
repositories:
  - id: epel9-htop-latest
    name: EPEL 9 - htop (latest)
    type: rpm
    feed: https://dl.fedoraproject.org/pub/epel/9/Everything/x86_64/
    enabled: true

    filters:
      patterns:
        include: ["^htop-.*"]
      metadata:
        architectures:
          include: ["x86_64"]
      rpm:
        exclude_source_rpms: true
      post_processing:
        only_latest_version: true
```

### Filter Configuration

Chantal supports comprehensive package filtering:

**1. Pattern-based filtering (regex):**
```yaml
filters:
  patterns:
    include: ["^nginx-.*", "^httpd-.*"]  # Only nginx and httpd packages
    exclude: [".*-debug.*", ".*-devel$"]  # Exclude debug and devel packages
```

**2. Architecture filtering:**
```yaml
filters:
  metadata:
    architectures:
      include: ["x86_64", "noarch"]
      # exclude: ["i686"]  # Exclude 32-bit packages
```

**3. RPM-specific filtering:**
```yaml
filters:
  rpm:
    exclude_source_rpms: true  # Skip .src.rpm packages
    groups:
      include: ["System Environment/Base"]
    licenses:
      exclude: ["Proprietary"]
```

**4. Post-processing:**
```yaml
filters:
  post_processing:
    only_latest_version: true  # Keep only latest version per (name, arch)
    # only_latest_n_versions: 3  # Keep last N versions (future)
```

### Tags for Repository Organization

Add tags to repositories for easy filtering and grouping:

```yaml
repositories:
  - id: rhel9-baseos-production
    name: RHEL 9 BaseOS - Production
    type: rpm
    feed: https://cdn.redhat.com/...
    enabled: true
    tags: ["production", "rhel9", "critical"]
```

---

## Architecture

### Content-Addressed Storage

Chantal uses SHA256-based content addressing for package storage:

```
/var/lib/chantal/pool/
├── f2/
│   └── 56/
│       └── f256abc...def789_nginx-1.20.2-1.el9.ngx.x86_64.rpm
├── 95/
│   └── 05/
│       └── 9505484...c1264fde_nginx-module-njs-1.24.0+0.8.3-1.el9.ngx.x86_64.rpm
└── ...
```

**Benefits:**
- **Instant Deduplication**: Single SHA256 lookup to check if package exists
- **2-Level Directory Structure**: Optimal filesystem performance (256×256 = 65,536 buckets)
- **Cross-Repository Sharing**: Identical packages stored once, shared across all repositories
- **Integrity Verification**: SHA256 checksums for all packages

### Publishing with Hardlinks

Published repositories use hardlinks (zero-copy):

```
/var/www/repos/
├── rhel9-baseos/
│   ├── latest/ -> hardlinks to pool
│   └── snapshots/
│       └── 20250110/ -> hardlinks to pool
└── epel9/
    └── latest/ -> hardlinks to pool
```

**Benefits:**
- **Zero-Copy**: No disk space wasted
- **Instant Publishing**: Creating thousands of hardlinks takes milliseconds
- **Atomic Updates**: New metadata published atomically

### Database Schema

SQLAlchemy models with PostgreSQL or SQLite:

- **Repository**: Configured repositories
- **Package**: Content-addressed packages (SHA256, NEVRA, metadata)
- **Snapshot**: Immutable repository snapshots
- **SyncHistory**: Sync tracking and statistics

### Plugin Architecture

Extensible plugin system for package types:

- **RpmSyncPlugin**: RPM repository sync (repomd.xml, primary.xml.gz)
- **RpmPublisher**: RPM metadata generation (repomd.xml, primary.xml.gz)
- **Future**: DebSyncPlugin, DebPublisher for APT repositories

---

## Performance

### Real-World Performance

**EPEL 9 - htop package** (single package):
- First sync: ~2 seconds (download + store)
- Second sync: ~0.5 seconds (skipped via SHA256 check)

**RHEL 9 AppStream - nginx** (10 packages):
- First sync: ~15 seconds
- Second sync: ~2 seconds (all packages skipped)

**RHEL 9 AppStream - httpd** (26 packages):
- First sync: ~45 seconds
- Second sync: ~3 seconds (all packages skipped)

### Why So Fast?

1. **Content-Addressed Storage**: Single SHA256 lookup vs. metadata comparison
2. **No Task Queue**: Direct execution, no Celery/RabbitMQ/Redis overhead
3. **Streaming Downloads**: Efficient 64KB chunks
4. **2-Level Directory Structure**: Optimal filesystem performance
5. **Zero-Copy Publishing**: Hardlinks instead of file copies
6. **Smart Filtering**: Filter at metadata level before downloading

### Storage Efficiency

- Multiple repository versions share packages automatically
- No duplicate storage for identical packages across repos
- Pool size = unique packages only
- Typical deduplication: 60-80% across RHEL variants

---

## Status

**🚀 Active Development - MVP Phase (Milestone 3+ Complete)**

### ✅ Completed Milestones

**Milestone 1: Configuration Management**
- ✅ Pydantic-based configuration models (GlobalConfig, RepositoryConfig, etc.)
- ✅ YAML configuration with include support (`conf.d/*.yaml`)
- ✅ CLI integration with `--config` flag
- ✅ Example configurations for RHEL 9, CentOS, EPEL
- ✅ Proxy and SSL/TLS configuration (global + per-repo override)
- ✅ 17 configuration tests passing

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
- ✅ HTTP client with proxy support and SSL/TLS (client certs for RHEL)
- ✅ Streaming downloads with SHA256 verification
- ✅ XZ and GZ compression support
- ✅ Database integration (Package, Repository models)
- ✅ Pattern-based filtering (include/exclude regex patterns)
- ✅ Metadata filtering (architecture, size, build time)
- ✅ RPM-specific filtering (exclude source RPMs, groups, licenses)
- ✅ Post-processing (only_latest_version, only_latest_n_versions)
- ✅ CLI commands: `chantal init`, `chantal repo sync`, `chantal repo list`
- ✅ Pattern matching for bulk operations (`--pattern "epel9-*"`, `--all`)
- ✅ End-to-end testing: Successfully synced RHEL 9, CentOS, EPEL repositories

**Milestone 3.5: Update Checking**
- ✅ `repo check-updates` command (like `dnf check-update`)
- ✅ Metadata-only comparison (no downloads)
- ✅ Proper RPM version comparison (Epoch → Version → Release)
- ✅ Bulk update checking (`--all`, `--pattern`)
- ✅ Shows new packages and available updates

**Milestone 4: Publishing**
- ✅ RpmPublisher plugin with repomd.xml/primary.xml.gz generation
- ✅ Hardlink-based publishing (zero-copy)
- ✅ CLI commands: `chantal publish repo`, `chantal publish snapshot`

**Milestone 5: Views (Virtual Repositories)**
- ✅ Database models (View, ViewRepository, ViewSnapshot)
- ✅ Alembic migration for view tables
- ✅ ViewConfig Pydantic models (YAML configuration)
- ✅ CLI commands: `chantal view list`, `chantal view show`
- ✅ ViewPublisher plugin (extends RpmPublisher)
- ✅ View publishing: `chantal publish view --name <name>`
- ✅ View snapshots: `chantal snapshot create --view <name>`
- ✅ View snapshot publishing: `chantal publish snapshot --view <name> --snapshot <name>`
- ✅ 10 view tests passing

**Other Completed**
- ✅ Database models (SQLAlchemy with PostgreSQL + SQLite support)
- ✅ CLI framework (Click with comprehensive commands)
- ✅ Configuration validation (YAML syntax errors caught at startup)
- ✅ 74 tests passing (64 core + 10 views)
- ✅ Python 3.10+ support

### ⏳ In Progress / Upcoming

**Milestone 6: Statistics & Database Management** (Next - MVP Required)
- ⏳ Global statistics (`chantal stats`)
- ⏳ Repository statistics (`chantal stats --repo-id`)
- ⏳ Database statistics (`chantal db stats`)
- ⏳ Database integrity check (`chantal db verify`)
- ⏳ Database cleanup (`chantal db cleanup`)

### 📋 Future Features (Post-MVP)

**Automated Scheduling** (moved to backlog - GitHub issue)
- Cron-based scheduling
- Automatic snapshot creation after sync
- Lock mechanism for concurrent runs
- Systemd service integration

**APT/Debian Support** (v2.0)
- APT plugin
- Packages.gz parsing
- .deb handling

**Advanced Features** (v3.0+)
- Web UI (read-only)
- REST API
- Prometheus metrics
- Advanced retention policies

**Progress:** ~75% of MVP complete

See [`.planning/status.md`](.planning/status.md) for detailed status.

---

## Development

### Running Tests

```bash
# Run all tests (74 passing)
pytest

# Run specific test file
pytest tests/test_cli.py -v
pytest tests/test_views.py -v

# Run with coverage
pytest --cov=chantal --cov-report=term-missing

# Test end-to-end sync (requires internet connection, using dev config)
export CHANTAL_CONFIG=.dev/config.yaml
chantal init
chantal repo sync --repo-id epel9-htop-latest

# Test views
chantal view list
chantal publish view --name rhel9-webserver
chantal snapshot create --view rhel9-webserver --name 2025-01-10
chantal publish snapshot --view rhel9-webserver --snapshot 2025-01-10
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

## Why "Chantal"?

Every other name was taken. Seriously.

We checked: berth, conduit, tributary, harbor, stow, fulcrum, vesper, cairn, aperture - all taken.

So we picked something memorable, available, and with personality.

---

## Documentation

- **[Architecture](.planning/architecture.md)** - Full architecture design
- **[CLI Commands](.planning/cli-commands.md)** - Complete CLI reference
- **[MVP Scope](.planning/mvp-scope.md)** - MVP features and timeline
- **[Status](.planning/status.md)** - Current development status
- **[Config vs Database Strategy](.planning/config-vs-database-strategy.md)** - Design decisions

---

## Contributing

Feedback and contributions welcome! This is active development, so design input is especially valuable.

1. Check the [status document](.planning/status.md) for current progress
2. Look at [open issues](https://github.com/slauger/chantal/issues) or create a new one
3. Submit pull requests for fixes or features

---

## License

MIT License - See LICENSE file for details.

---

**Current Phase:** MVP Development - Milestone 5 Complete (Views - Virtual Repositories)
**Next Milestone:** Statistics & Database Management (Milestone 6)
**Test Coverage:** 74 tests passing (64 core + 10 views)
**Real-world Testing:** RHEL 9, CentOS 9, EPEL 9 repositories synced successfully + Views tested
