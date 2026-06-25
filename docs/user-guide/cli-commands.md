# CLI Commands

Complete reference for all Chantal commands.

## Global Options

All commands support these global options:

```bash
chantal [OPTIONS] COMMAND [ARGS]...

Options:
  --config PATH      Path to configuration file
  --version          Show version and exit
  -v, --verbose      Verbose output
  -h, --help         Show help message and exit
```

**Command groups:** `repo`, `snapshot`, `content`, `publish`, `view`,
`package`, `pool`, `cache`, `db`, `stats`, `schema`. Each group is documented
in the sections below.

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

## Database Management

### `chantal db init`

Initialize the database schema using Alembic migrations.

```bash
chantal db init
```

Creates all database tables and applies all migrations to reach the latest schema version.

### `chantal db status`

Show database schema status and pending migrations.

```bash
chantal db status
```

### `chantal db current`

Show current database schema version.

```bash
chantal db current
```

### `chantal db upgrade`

Upgrade database schema to a specific revision or latest.

```bash
# Upgrade to latest
chantal db upgrade

# Upgrade to specific revision
chantal db upgrade abc123
```

### `chantal db history`

Show migration history.

```bash
chantal db history
```

**Note:** Storage directories (`/var/lib/chantal/pool`, `/var/www/repos`) are created automatically when needed.

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
- `--type`: Filter by repository type (rpm, apt) when using `--all` or `--pattern`
- `--workers`: Number of parallel workers (with `--all` or `--pattern`)
- `-v`, `--verbose`: Show detailed package-by-package progress
- `-q`, `--quiet`: Show only errors, no progress output

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

# Sync all with 4 parallel workers, quiet output
chantal repo sync --all --workers 4 --quiet
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
# History for one repository
chantal repo history --repo-id REPO_ID [--limit 10]

# History across all repositories
chantal repo history --all

# Only the last sync of each repository
chantal repo history --all --last
```

**Options:**
- `--repo-id`: Repository ID
- `--all`: Show sync history for all repositories
- `--last`: Show only the last sync (use with `--all`)
- `--limit`: Maximum number of entries to show
- `--format`: Output format (table, json)

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
- `--force`: Force deletion even if the snapshot is currently published

### `chantal snapshot copy`

Copy a snapshot to a new name to enable promotion workflows (e.g. staging →
production). Only database entries are created - no files are copied, since both
snapshots reference the same content-addressed packages in the pool.

```bash
chantal snapshot copy \
  --source SOURCE_NAME \
  --target TARGET_NAME \
  --repo-id REPO_ID \
  [--description "..."]
```

**Options:**
- `--source`: Source snapshot name (required)
- `--target`: Target snapshot name (required)
- `--repo-id`: Repository ID (required)
- `--description`: Description for the new snapshot

**Example:**
```bash
# Promote a tested snapshot to "stable"
chantal snapshot copy \
  --source 2025-01-10 \
  --target stable \
  --repo-id rhel9-baseos
```

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
chantal content list --repo-id REPO_ID --type apt

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
- `--type`: Filter by content type (rpm, helm, apt)
- `--limit`: Maximum number of items to show
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
chantal content search nginx --type apt

# Output as JSON
chantal content search nginx --format json
```

**Options:**
- `QUERY`: Search query (required) - matches name or version
- `--repo-id`: Search in specific repository
- `--snapshot-id`: Search in specific snapshot
- `--view`: Search in specific view
- `--type`: Filter by content type (rpm, helm, apt)
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

## View Management

Views group multiple repositories into a single virtual repository. All
repositories in a view must have the same type (rpm or apt). See
[Views (Virtual Repositories)](views.md) for the full guide.

### `chantal view list`

List all configured views.

```bash
chantal view list [--format table|json]
```

**Options:**
- `--format`: Output format (table, json)

### `chantal view show`

Show detailed information about a view, including its repositories and package
counts.

```bash
chantal view show --name VIEW_NAME [--format table|json]
```

**Options:**
- `--name`: View name (required)
- `--format`: Output format (table, json)

> **Note:** Views are *published* with `chantal publish view` and *snapshotted*
> with `chantal snapshot create --view` (see those commands).

## Package Management

The `package` commands inject custom (locally provided) packages into a
repository's content-addressed pool. This powers *hosted* repositories built
from your own packages, independent of an upstream feed.

### `chantal package upload`

Upload one or more local package files into a repository's pool.

```bash
# Upload a single package
chantal package upload --file ./mypackage-1.0.0.x86_64.rpm --repo-id myrepo

# Upload all packages in a directory
chantal package upload --directory ./packages/ --repo-id myrepo

# Recurse into subdirectories
chantal package upload --directory ./packages/ --recursive --repo-id myrepo

# Replace a conflicting same-version package
chantal package upload --file ./mypackage-1.0.0.x86_64.rpm --repo-id myrepo --force

# Upload .deb packages into a specific APT component
chantal package upload --file ./mypackage_1.0.0_amd64.deb --repo-id myrepo --component contrib
```

**Options:**
- `--file`: A single package file to upload
- `--directory`: A directory of packages to upload
- `--recursive`: Recurse into `--directory`
- `--repo-id`: Target repository ID (required)
- `--force`: Replace a conflicting same-version package
- `--component`: APT component for uploaded `.deb` packages (default: `main`; ignored for rpm/helm)

**Supported types:** RPM, DEB/APT, and Helm. (Alpine APK upload is not supported.)

## Publishing

### `chantal publish repo`

Publish a repository to its target directory. Creates hardlinks from the package
pool and (re)generates repository metadata.

```bash
# Publish single repository
chantal publish repo --repo-id REPO_ID

# Publish all repositories
chantal publish repo --all

# Publish to a custom target directory
chantal publish repo --repo-id REPO_ID --target /var/www/custom
```

**Options:**
- `--repo-id`: Repository ID
- `--all`: Publish all repositories
- `--target`: Custom target directory (default: from config)

### `chantal publish snapshot`

Publish a specific snapshot. Works for both repository snapshots (`--repo-id`)
and view snapshots (`--view`).

```bash
# Repository snapshot
chantal publish snapshot --snapshot NAME --repo-id REPO_ID

# View snapshot
chantal publish snapshot --snapshot NAME --view VIEW_NAME
```

**Options:**
- `--snapshot`: Snapshot name (required)
- `--repo-id`: Repository ID (for repository snapshots)
- `--view`: View name (for view snapshots)
- `--target`: Custom target directory

### `chantal publish view`

Publish a view (combines all repositories in the view into one virtual
repository). Views are published directly from the configuration file - no
database sync needed.

```bash
chantal publish view --name VIEW_NAME
```

**Options:**
- `--name`: View name to publish (required)

See [Views (Virtual Repositories)](views.md) for details.

### `chantal publish list`

List currently published repositories and snapshots.

```bash
chantal publish list
```

### `chantal publish unpublish`

Unpublish a snapshot. Removes the published directory (hardlinks) but keeps the
packages in the pool and the snapshot in the database, so it can be re-published
later.

```bash
# Unpublish by snapshot name
chantal publish unpublish --snapshot SNAPSHOT_NAME

# Disambiguate when the same snapshot name exists in multiple repositories
chantal publish unpublish --snapshot SNAPSHOT_NAME --repo-id REPO_ID
```

**Options:**
- `--snapshot`: Snapshot name to unpublish (required)
- `--repo-id`: Repository ID (optional; only needed if the snapshot name is not unique)

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

Clean up pool integrity issues. By default cleans both orphaned files (in pool
but not in database) and missing entries (in database but without a pool file).
Requires confirmation unless `--force` or `--dry-run` is used.

```bash
# Dry-run (show what would be deleted)
chantal pool cleanup --dry-run

# Clean both orphaned files and missing entries (prompts for confirmation)
chantal pool cleanup

# Clean only orphaned files (in pool but not in database)
chantal pool cleanup --orphaned

# Clean only missing entries (in database but not in pool)
chantal pool cleanup --missing

# Skip the confirmation prompt
chantal pool cleanup --force
```

**Options:**
- `--dry-run`: Show what would be deleted without actually deleting
- `--orphaned`: Only clean orphaned files (in pool but not in database)
- `--missing`: Only clean missing entries (in database but not in pool)
- `--force`: Skip confirmation prompt

### `chantal pool verify`

Verify pool integrity. Performs a comprehensive integrity check.

```bash
chantal pool verify
```

**Checks:**
- Orphaned files (in pool but not in database)
- Missing files (in database but not in pool)
- SHA256 checksum verification
- File size verification

For detailed file lists, use `chantal pool orphaned` or `chantal pool missing`.

This command takes no options.

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

Clean up database issues. By default cleans both orphaned repositories (in the
database but not in the configuration) and unreferenced packages (without
repository references). Requires confirmation unless `--force` or `--dry-run`
is used.

```bash
# Dry-run
chantal db cleanup --dry-run

# Clean both (prompts for confirmation)
chantal db cleanup

# Clean only orphaned repositories
chantal db cleanup --orphaned

# Clean only unreferenced packages
chantal db cleanup --unreferenced

# Skip the confirmation prompt
chantal db cleanup --force
```

**Options:**
- `--dry-run`: Show what would be deleted without actually deleting
- `--orphaned`: Only clean orphaned repositories (in DB but not in config)
- `--unreferenced`: Only clean unreferenced packages
- `--force`: Skip confirmation prompt

### `chantal db orphaned`

List orphaned repositories in the database (present in the database but not in
the configuration file).

```bash
chantal db orphaned
```

## Metadata Cache Management

The `cache` commands manage the SHA256-based metadata cache (used to speed up
RPM syncs).

### `chantal cache stats`

Show cache statistics.

```bash
chantal cache stats
```

### `chantal cache list`

List cached metadata files.

```bash
chantal cache list [--limit N]
```

**Options:**
- `--limit`: Limit the number of files shown

### `chantal cache clear`

Clear the metadata cache. By default clears all cached metadata files.

```bash
# Clear the entire cache (prompts for confirmation)
chantal cache clear

# Skip the confirmation prompt
chantal cache clear --force
```

**Options:**
- `--all`: Clear the entire cache
- `--force`: Skip confirmation prompt
- `--repo-id`: Reserved for per-repository clearing (currently clears all)

## Configuration Schema

### `chantal schema`

Output the JSON Schema for the configuration file. The schema is generated from
the configuration models and can be used by editors (e.g. the VS Code YAML
extension) to validate and autocomplete `config.yaml`.

```bash
# Print schema to stdout
chantal schema

# Write schema to a file
chantal schema --output chantal-config.schema.json
```

**Options:**
- `-o`, `--output`: Write the schema to this file instead of stdout

## Output Formats

Most commands support multiple output formats:

```bash
# Human-readable table (default)
chantal repo list --format table

# Machine-readable JSON
chantal repo list --format json
```
