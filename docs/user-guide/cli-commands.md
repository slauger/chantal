# CLI Commands

Complete reference for all Chantal commands.

## Global Options

All commands support these global options:

```bash
chantal [OPTIONS] COMMAND [ARGS]...

Options:
  --config PATH      Path to configuration file
  --version          Show version and exit
  -h, --help         Show help message and exit
```

## Configuration File Priority

Chantal looks for configuration files in this order:

1. `--config` CLI flag (highest priority)
2. `CHANTAL_CONFIG` environment variable
3. Default locations:
   - `/etc/chantal/config.yaml` (production)
   - `~/.config/chantal/config.yaml` (user)
   - `./config.yaml` (current directory)

**Tip:** If not using default location, set `CHANTAL_CONFIG`:

```bash
# For custom config location
export CHANTAL_CONFIG=/path/to/config.yaml
chantal repo sync --repo-id epel9-vim-latest

# Development with local config
export CHANTAL_CONFIG=./config-dev.yaml
```

## Initialize

### `chantal init`

Initialize Chantal database and directory structure.

```bash
chantal init
```

Creates:
- Database schema
- Pool directory
- Published directory

## Repository Management

### `chantal repo list`

List all configured repositories.

```bash
chantal repo list [--format table|json] [--type rpm|apt|helm]
```

**Options:**
- `--format`: Output format (default: table)
- `--type`: Filter by repository type (rpm, apt, or helm)

**Example:**
```bash
$ chantal repo list
Configured Repositories:

ID                          Type Enabled Packages Last Sync
----------------------------------------------------------------------
rhel9-baseos-vim-latest     rpm  Yes     4        2026-01-10 14:34
epel9-vim-latest            rpm  Yes     3        2026-01-10 14:27
ingress-nginx               helm Yes     1        2026-01-10 23:20
```

**Filter by type:**
```bash
$ chantal repo list --type helm
Configured Repositories:

ID                          Type Enabled Packages Last Sync
----------------------------------------------------------------------
ingress-nginx               helm Yes     1        2026-01-10 23:20
```

### `chantal repo show`

Show detailed information about a repository.

```bash
chantal repo show --repo-id REPO_ID [--format table|json]
```

**Options:**
- `--repo-id`: Repository ID (required)
- `--format`: Output format (default: table)

**Example:**
```bash
$ chantal repo show --repo-id epel9-vim-latest
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
```

### `chantal repo sync`

Sync repository from upstream.

```bash
# Sync single repository
chantal repo sync --repo-id REPO_ID

# Sync all enabled repositories
chantal repo sync --all [--type rpm]

# Sync repositories matching pattern
chantal repo sync --pattern "epel9-*"
```

**Options:**
- `--repo-id`: Repository ID
- `--all`: Sync all enabled repositories
- `--pattern`: Repository ID pattern (glob)
- `--type`: Filter by repository type

**Examples:**
```bash
# Sync single repository
chantal repo sync --repo-id epel9-vim-latest

# Sync all EPEL repositories
chantal repo sync --pattern "epel9-*"

# Sync all enabled repositories
chantal repo sync --all

# Sync only RPM repositories
chantal repo sync --all --type rpm
```

### `chantal repo check-updates`

Check for available updates without downloading.

```bash
# Check single repository
chantal repo check-updates --repo-id REPO_ID

# Check all enabled repositories
chantal repo check-updates --all

# Check repositories matching pattern
chantal repo check-updates --pattern "rhel9-*"
```

**Options:**
- `--repo-id`: Repository ID
- `--all`: Check all enabled repositories
- `--pattern`: Repository ID pattern (glob)

**Example:**
```bash
$ chantal repo check-updates --repo-id rhel9-appstream-nginx-latest
Checking for updates: rhel9-appstream-nginx-latest
Feed URL: https://cdn.redhat.com/content/dist/rhel9/9/x86_64/appstream/os

✓ No updates available. Repository is up to date.
```

### `chantal repo history`

Show sync history for a repository.

```bash
chantal repo history --repo-id REPO_ID [--limit 10]
```

**Options:**
- `--repo-id`: Repository ID (required)
- `--limit`: Maximum number of entries to show

## Snapshot Management

### `chantal snapshot list`

List all snapshots.

```bash
chantal snapshot list [--repo-id REPO_ID]
```

**Options:**
- `--repo-id`: Filter by repository ID

### `chantal snapshot create`

Create a new snapshot.

```bash
chantal snapshot create \
  --repo-id REPO_ID \
  --name NAME \
  [--description "..."]
```

**Options:**
- `--repo-id`: Repository ID (required)
- `--name`: Snapshot name (required)
- `--description`: Optional description

**Example:**
```bash
chantal snapshot create \
  --repo-id rhel9-baseos-vim-latest \
  --name 20250110 \
  --description "January 2025 patch baseline"
```

### `chantal snapshot content`

Show snapshot content (package list) for compliance/audit.

```bash
# Repository snapshot
chantal snapshot content \
  --repo-id REPO_ID \
  --snapshot SNAPSHOT_NAME \
  [--format table|json|csv]

# View snapshot
chantal snapshot content \
  --view VIEW_NAME \
  --snapshot SNAPSHOT_NAME \
  [--format table|json|csv]
```

**Options:**
- `--repo-id`: Repository ID (for repository snapshots)
- `--view`: View name (for view snapshots)
- `--snapshot`: Snapshot name (required)
- `--format`: Output format (default: table)

**Example (human-readable table):**
```bash
chantal snapshot content \
  --view rhel9-webserver \
  --snapshot 2025-01-10
```

**Example (JSON for automation):**
```bash
chantal snapshot content \
  --view rhel9-webserver \
  --snapshot 2025-01-10 \
  --format json > audit/rhel9-webserver-2025-01-10.json
```

**Example (CSV for reporting):**
```bash
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

**Perfect for:**
- Compliance reports ("What was deployed on 2025-01-10?")
- Security audits (verify exact package versions)
- Change management (track package changes over time)

### `chantal snapshot diff`

Compare two snapshots.

```bash
chantal snapshot diff \
  --repo-id REPO_ID \
  SNAPSHOT1 SNAPSHOT2
```

Shows:
- Added packages
- Removed packages
- Updated packages (version changes)

**Example:**
```bash
chantal snapshot diff \
  --repo-id rhel9-baseos-vim-latest \
  20250110 20250109
```

### `chantal snapshot delete`

Delete a snapshot.

```bash
chantal snapshot delete \
  --repo-id REPO_ID \
  SNAPSHOT_NAME
```

**Options:**
- `--repo-id`: Repository ID (required)
- `SNAPSHOT_NAME`: Snapshot name to delete (required)

## Content Management

The `content` commands work with all content types (RPM, Helm, APK, etc.) in a unified way.

### `chantal content list`

List content items from repositories, snapshots, or views.

```bash
# List all content in a repository
chantal content list --repo-id REPO_ID

# List content in a snapshot
chantal content list --snapshot-id SNAPSHOT_ID

# List content in a view
chantal content list --view VIEW_NAME

# Filter by content type
chantal content list --repo-id REPO_ID --type rpm
chantal content list --repo-id REPO_ID --type helm
chantal content list --repo-id REPO_ID --type apk

# Limit results
chantal content list --repo-id REPO_ID --limit 50

# Output formats
chantal content list --repo-id REPO_ID --format json
chantal content list --repo-id REPO_ID --format csv
```

**Options:**
- `--repo-id`: Filter by repository ID
- `--snapshot-id`: Filter by snapshot ID
- `--view`: Filter by view name
- `--type`: Filter by content type (rpm, helm, apk)
- `--limit`: Maximum number of items to show (default: 100)
- `--format`: Output format (table, json, csv)

**Note:** Only one of `--repo-id`, `--snapshot-id`, or `--view` can be specified.

### `chantal content search`

Search for content by name or version.

```bash
# Global search
chantal content search nginx

# Search in specific repository
chantal content search nginx --repo-id epel9-latest

# Search in snapshot
chantal content search nginx --snapshot-id epel9-latest-2025-01-10

# Search in view
chantal content search nginx --view rhel9-webserver

# Filter by content type
chantal content search python --type rpm
chantal content search ingress --type helm
chantal content search alpine --type apk

# Output as JSON
chantal content search nginx --format json
```

**Options:**
- `QUERY`: Search query (required) - matches name or version
- `--repo-id`: Search in specific repository
- `--snapshot-id`: Search in specific snapshot
- `--view`: Search in specific view
- `--type`: Filter by content type (rpm, helm, apk)
- `--format`: Output format (table, json)

**Note:** Only one of `--repo-id`, `--snapshot-id`, or `--view` can be specified.

### `chantal content show`

Show detailed content information.

```bash
# By SHA256 hash
chantal content show abc123def456...

# By name (shows all matching items)
chantal content show nginx

# By name@version (specific version)
chantal content show nginx@1.20.1
chantal content show ingress-nginx@4.0.15

# Output as JSON
chantal content show nginx@1.20.1 --format json
```

**Options:**
- `IDENTIFIER`: Content identifier (required)
  - SHA256 hash (64 hex characters)
  - Name (e.g., `nginx`)
  - Name@version (e.g., `nginx@1.20.1`)
- `--format`: Output format (table, json)

**Example output:**
```bash
$ chantal content show nginx@1.20.1
======================================================================
Content: nginx 1.20.1
======================================================================

Basic Information:
  Name:         nginx
  Version:      1.20.1
  Type:         rpm
  Filename:     nginx-1.20.1-1.el9.x86_64.rpm
  Architecture: x86_64
  Release:      1.el9

Storage:
  Size:         1.23 MB (1,234,567 bytes)
  SHA256:       abc123def...
  Pool Path:    pool/ab/c1/abc123def...

Repositories (2):
  - epel9-latest
  - epel9-webserver

Snapshots (1):
  - epel9-latest-2025-01-10

======================================================================
```

## Publishing

### `chantal publish repo`

Publish a repository.

```bash
# Publish single repository
chantal publish repo --repo-id REPO_ID

# Publish all repositories
chantal publish repo --all
```

**Options:**
- `--repo-id`: Repository ID
- `--all`: Publish all repositories

### `chantal publish snapshot`

Publish a snapshot.

```bash
chantal publish snapshot --snapshot REPO_ID-NAME
```

**Options:**
- `--snapshot`: Snapshot identifier (format: `repo-id-name`)

### `chantal publish list`

List published repositories and snapshots.

```bash
chantal publish list
```

### `chantal publish unpublish`

Unpublish a repository or snapshot.

```bash
# Unpublish repository
chantal publish unpublish --repo-id REPO_ID

# Unpublish snapshot
chantal publish unpublish --snapshot REPO_ID-NAME
```

## Storage Pool Management

### `chantal pool stats`

Show storage pool statistics.

```bash
chantal pool stats
```

### `chantal pool orphaned`

List orphaned files in pool (not referenced by any repository).

```bash
chantal pool orphaned
```

Shows files that exist in pool but are not referenced in the database.

### `chantal pool cleanup`

Remove orphaned files from pool.

```bash
# Dry-run (show what would be removed)
chantal pool cleanup --dry-run

# Actually remove orphaned files
chantal pool cleanup

# Clean only content files (packages)
chantal pool cleanup --content-only

# Clean only metadata files
chantal pool cleanup --metadata-only

# Delete specific pool entries by SHA256
chantal pool cleanup --sha256 abc123def456...
```

**Options:**
- `--dry-run`: Show what would be removed without actually removing
- `--content-only`: Only clean orphaned content files (packages)
- `--metadata-only`: Only clean orphaned metadata files
- `--sha256`: Delete specific pool entry by SHA256 checksum

### `chantal pool verify`

Verify pool integrity.

```bash
# Verify all pool files
chantal pool verify

# Verify specific repository
chantal pool verify --repo-id epel9-latest

# Verify and show detailed output
chantal pool verify --verbose
```

**Checks:**
- File existence (database entry exists but file missing)
- Checksum verification (file SHA256 matches database)
- Database consistency (orphaned entries, duplicate files)

**Options:**
- `--repo-id`: Verify only files for specific repository
- `--verbose`: Show detailed verification output

### `chantal pool missing`

List files that are referenced in database but missing from pool.

```bash
chantal pool missing

# Check specific repository
chantal pool missing --repo-id rhel9-baseos
```

Shows content items that have database entries but missing pool files.

## Statistics & Database

### `chantal stats`

Show global statistics.

```bash
chantal stats [--repo-id REPO_ID]
```

**Options:**
- `--repo-id`: Show repository-specific statistics

### `chantal db stats`

Show database statistics.

```bash
chantal db stats
```

### `chantal db verify`

Verify database integrity.

```bash
chantal db verify
```

### `chantal db cleanup`

Clean up unreferenced packages.

```bash
# Dry-run
chantal db cleanup --dry-run

# Actually cleanup
chantal db cleanup
```

## Output Formats

Most commands support multiple output formats:

```bash
# Human-readable table (default)
chantal repo list --format table

# Machine-readable JSON
chantal repo list --format json
```
