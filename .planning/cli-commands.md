# Chantal CLI Commands - pulp-admin inspired

**Basierend auf:** pulp-admin CLI Design
**Datum:** 2025-01-09

---

## pulp-admin Command Reference

### Repository Management

```bash
# List repositories
pulp-admin rpm repo list

# Show repository details
pulp-admin rpm repo show --repo-id=rhel9-baseos

# Create repository
pulp-admin rpm repo create --repo-id=myrepo --feed=https://...

# Delete repository
pulp-admin rpm repo delete --repo-id=myrepo

# Update repository
pulp-admin rpm repo update --repo-id=myrepo --feed=https://...
```

### Sync Operations

```bash
# Sync repository
pulp-admin rpm repo sync run --repo-id=rhel9-baseos

# Check sync status
pulp-admin rpm repo sync status --repo-id=rhel9-baseos

# Sync history
pulp-admin rpm repo sync history --repo-id=rhel9-baseos
```

### Content Management

```bash
# List packages in repository
pulp-admin rpm repo content rpm --repo-id=rhel9-baseos

# Search for packages
pulp-admin rpm repo search rpm --repo-id=rhel9-baseos --str-eq name=nginx

# Remove package from repository
pulp-admin rpm repo remove rpm --repo-id=rhel9-baseos --str-eq name=old-package
```

### Publishing

```bash
# Publish repository
pulp-admin rpm repo publish run --repo-id=rhel9-baseos

# Publish status
pulp-admin rpm repo publish status --repo-id=rhel9-baseos
```

---

## Chantal CLI Design (pulp-admin-inspired)

### Repository Management

```bash
# List all repositories
chantal repo list
chantal repo list --type rpm
chantal repo list --enabled-only

# Show repository details
chantal repo show --repo-id rhel9-baseos
# Output:
# Repository: rhel9-baseos
# Type: rpm
# Enabled: Yes
# Upstream: https://cdn.redhat.com/...
# Last Sync: 2025-01-09 14:30:00
# Packages: 1247
# Size: 4.2 GB
# Latest Snapshot: rhel9-baseos-20250109
# Published: /var/www/repos/rhel9-baseos/latest

# Show repository configuration
chantal repo config --repo-id rhel9-baseos
# Shows full YAML config

# Update repository (future)
chantal repo update --repo-id rhel9-baseos --enabled false
```

### Sync Operations

```bash
# Sync repository
chantal repo sync --repo-id rhel9-baseos
chantal repo sync --repo-id rhel9-baseos --create-snapshot
chantal repo sync --repo-id rhel9-baseos --create-snapshot --snapshot-name 2025-01-patch1

# Sync multiple repositories
chantal repo sync --all
chantal repo sync --all --type rpm
chantal repo sync --all --workers 3

# Dry-run sync
chantal repo sync --repo-id rhel9-baseos --dry-run
# Shows: 47 packages to download, 1200 already present, 5 to remove

# Sync status (show running syncs)
chantal repo sync-status
chantal repo sync-status --repo-id rhel9-baseos

# Sync history
chantal repo sync-history --repo-id rhel9-baseos
chantal repo sync-history --repo-id rhel9-baseos --limit 10
# Output:
# Date                 Status   Packages  Downloaded  Duration
# 2025-01-09 14:30:00  Success  47 added  450 MB      5m 23s
# 2025-01-08 02:00:00  Success  12 added  120 MB      2m 15s
# 2025-01-07 02:00:00  Failed   -         -           -
```

### Content Management (NEW!)

```bash
# List packages in repository
chantal package list --repo-id rhel9-baseos
chantal package list --repo-id rhel9-baseos --limit 50
chantal package list --repo-id rhel9-baseos --arch x86_64
chantal package list --repo-id rhel9-baseos --format table
chantal package list --repo-id rhel9-baseos --format json

# Output (table format):
# Name           Version         Arch    Size      Repo
# nginx          1.20.1-10.el9   x86_64  1.2 MB    rhel9-baseos
# httpd          2.4.51-1.el9    x86_64  1.5 MB    rhel9-baseos
# ...

# Search packages
chantal package search nginx
chantal package search --name nginx
chantal package search --name "nginx*" --arch x86_64
chantal package search --repo-id rhel9-baseos --name "kernel*"

# Show package details
chantal package show nginx-1.20.1-10.el9.x86_64
chantal package show --sha256 abc123...
# Output:
# Package: nginx
# Version: 1.20.1-10.el9
# Arch: x86_64
# Size: 1.2 MB
# SHA256: abc123def456...
# Installed in Repositories: rhel9-baseos, rhel9-appstream
# Installed in Snapshots: rhel9-baseos-20250109, rhel9-baseos-20250108
# Summary: High performance web server
# Description: ...
# Dependencies: ...
# File: /var/lib/chantal/data/sha256/ab/cd/abc123...def456_nginx-1.20.1-10.el9.x86_64.rpm

# Package dependencies
chantal package deps nginx-1.20.1-10.el9.x86_64
chantal package deps --sha256 abc123...
# Output:
# Requires:
#   - glibc >= 2.34
#   - openssl >= 3.0.1
#   - pcre >= 8.45
# Provides:
#   - nginx
#   - webserver

# Packages requiring this package
chantal package required-by nginx
# Output:
# Packages that require nginx:
#   - nginx-mod-http-image-filter-1.20.1-10.el9.x86_64
#   - nginx-mod-stream-1.20.1-10.el9.x86_64
```

### Package Statistics

```bash
# Repository statistics
chantal stats --repo-id rhel9-baseos
# Output:
# Repository: rhel9-baseos
# Total Packages: 1247
# Total Size: 4.2 GB
# Unique Packages: 1247 (100% dedup)
# Architectures: x86_64 (1200), noarch (47)
# Latest Package: kernel-5.14.0-362.el9 (2025-01-08)
# Oldest Package: basesystem-11-13.el9 (2022-05-01)

# Global statistics
chantal stats
# Output:
# Total Repositories: 5
# Total Packages: 12,450
# Deduplicated: 8,320 (33% savings)
# Total Size on Disk: 18.5 GB
# Total Snapshots: 23
# Database Size: 245 MB

# Package distribution
chantal stats packages
# Output:
# Top 20 packages by size:
# 1. kernel-5.14.0-362.el9.x86_64       - 85 MB
# 2. firefox-115.6.0-1.el9.x86_64       - 78 MB
# ...

# Deduplication report
chantal stats dedup
# Output:
# Deduplication Report:
# nginx-1.20.1-10.el9.x86_64 - present in 3 repos (saved 2.4 MB)
# httpd-2.4.51-1.el9.x86_64  - present in 2 repos (saved 1.5 MB)
# ...
# Total space saved: 4.5 GB
```

### Snapshot Management

```bash
# List snapshots
chantal snapshot list
chantal snapshot list --repo-id rhel9-baseos
chantal snapshot list --format table

# Output:
# Name                      Repository      Created              Packages  Size
# rhel9-baseos-20250109    rhel9-baseos    2025-01-09 14:30:00  1247      4.2 GB
# rhel9-baseos-20250108    rhel9-baseos    2025-01-08 02:00:00  1242      4.1 GB
# ...

# Show snapshot details
chantal snapshot show rhel9-baseos-20250109
# Output:
# Snapshot: rhel9-baseos-20250109
# Repository: rhel9-baseos
# Created: 2025-01-09 14:30:00
# Packages: 1247
# Size: 4.2 GB
# Published: /var/www/repos/rhel9-baseos/snapshots/rhel9-baseos-20250109
# Immutable: Yes

# Create snapshot
chantal snapshot create --repo-id rhel9-baseos --name 2025-01-patch1
chantal snapshot create --repo-id rhel9-baseos --name 2025-01-patch1 --description "January 2025 Patch Release"

# Delete snapshot
chantal snapshot delete rhel9-baseos-20250108
chantal snapshot delete rhel9-baseos-20250108 --force

# Compare snapshots (diff)
chantal snapshot diff rhel9-baseos-20250108 rhel9-baseos-20250109
# Output:
# Comparing rhel9-baseos-20250108 → rhel9-baseos-20250109
#
# Added (5):
#   + kernel-5.14.0-362.el9.x86_64
#   + nginx-1.20.2-1.el9.x86_64
#   ...
#
# Removed (2):
#   - kernel-5.14.0-360.el9.x86_64
#   - nginx-1.20.1-10.el9.x86_64
#
# Updated (3):
#   ~ httpd: 2.4.50-1.el9 → 2.4.51-1.el9
#   ~ glibc: 2.34-60.el9 → 2.34-61.el9
#   ...

# Merge snapshots (future)
chantal snapshot merge \
  --source rhel9-baseos-latest \
  --source internal-rpms-latest \
  --name custom-rhel9-20250109 \
  --strategy latest

# Snapshot content
chantal snapshot packages rhel9-baseos-20250109
chantal snapshot packages rhel9-baseos-20250109 --name "nginx*"
```

### Database & Maintenance

```bash
# Database cleanup
chantal db cleanup
chantal db cleanup --dry-run
# Output (dry-run):
# Would remove 47 unreferenced packages (450 MB)
# Packages:
#   - old-package-1.0-1.el9.x86_64 (10 MB)
#   - another-old-package-2.0-1.el9.x86_64 (15 MB)
#   ...

# Database statistics
chantal db stats
# Output:
# Database Statistics:
# Total Packages: 8,320
# Referenced Packages: 8,273 (99%)
# Unreferenced Packages: 47 (1%, 450 MB)
# Total Repositories: 5
# Total Snapshots: 23
# Database Size: 245 MB

# Database migrations
chantal db migrate
chantal db migrate --revision head
chantal db migrate --revision +1

# Database vacuum (optimize)
chantal db vacuum

# Verify database integrity
chantal db verify
# Output:
# Verifying database integrity...
# ✓ All packages in database have files in pool
# ✓ All pool files have database entries
# ✗ Found 3 orphaned pool files (25 MB)
# Run 'chantal db cleanup' to remove orphaned files
```

### Publishing

```bash
# Publish latest (auto-published after sync by default)
chantal publish --repo-id rhel9-baseos
chantal publish --repo-id rhel9-baseos --target /custom/path

# Publish snapshot
chantal publish --snapshot rhel9-baseos-20250109
chantal publish --snapshot rhel9-baseos-20250109 --target /var/www/repos/prod/

# Atomic switch (change what "latest" points to)
chantal publish switch rhel9-baseos --snapshot rhel9-baseos-20250109

# Unpublish (remove from webserver directory)
chantal publish unpublish --repo-id rhel9-baseos
chantal publish unpublish --snapshot rhel9-baseos-20250108
```

### Logs & Monitoring

```bash
# Show logs
chantal logs
chantal logs --follow
chantal logs --repo-id rhel9-baseos
chantal logs --level ERROR
chantal logs --since "2025-01-09"
chantal logs --tail 100

# Watch sync progress
chantal watch --repo-id rhel9-baseos
# Output (live updating):
# Syncing: rhel9-baseos
# Progress: [████████░░] 80% (1000/1247 packages)
# Downloaded: 3.5 GB / 4.2 GB
# Speed: 15 MB/s
# ETA: 45 seconds
```

### Configuration

```bash
# Show current configuration
chantal config show
chantal config show --repo-id rhel9-baseos

# Validate configuration
chantal config validate
chantal config validate --repo-id rhel9-baseos

# Test repository connectivity
chantal config test --repo-id rhel9-baseos
# Output:
# Testing repository: rhel9-baseos
# ✓ Upstream URL reachable
# ✓ Authentication successful
# ✓ Metadata downloadable (repomd.xml: 4161 bytes)
# ✓ Repository is valid
```

---

## Output Formats

All list commands support multiple output formats:

```bash
# Table format (default, human-readable)
chantal package list --repo-id rhel9-baseos --format table

# JSON format (machine-readable)
chantal package list --repo-id rhel9-baseos --format json
# Output:
# [
#   {
#     "name": "nginx",
#     "version": "1.20.1-10.el9",
#     "arch": "x86_64",
#     "size": 1258496,
#     "sha256": "abc123..."
#   },
#   ...
# ]

# CSV format (for Excel/analysis)
chantal package list --repo-id rhel9-baseos --format csv
# Output:
# name,version,arch,size,sha256
# nginx,1.20.1-10.el9,x86_64,1258496,abc123...

# YAML format
chantal package list --repo-id rhel9-baseos --format yaml
```

---

## Interactive Mode (Future)

```bash
# Interactive shell (like pulp-admin shell)
chantal shell

chantal> repo list
chantal> repo show rhel9-baseos
chantal> package search nginx
chantal> exit
```

---

## Comparison: pulp-admin vs Chantal

| Feature | pulp-admin | Chantal |
|---------|------------|---------|
| **Repo List** | `pulp-admin rpm repo list` | `chantal repo list` |
| **Repo Show** | `pulp-admin rpm repo show --repo-id=X` | `chantal repo show --repo-id X` |
| **Sync** | `pulp-admin rpm repo sync run --repo-id=X` | `chantal repo sync --repo-id X` |
| **Sync Status** | `pulp-admin rpm repo sync status` | `chantal repo sync-status` |
| **List Packages** | `pulp-admin rpm repo content rpm` | `chantal package list --repo-id X` |
| **Search Packages** | `pulp-admin rpm repo search rpm` | `chantal package search <query>` |
| **Publish** | `pulp-admin rpm repo publish run` | `chantal publish --repo-id X` |
| **Snapshots** | (via versions in Pulp 3) | `chantal snapshot list/create/delete` |
| **Stats** | (limited) | `chantal stats` (comprehensive!) |

---

## Priority for MVP

**High Priority (MVP):**
- ✅ `chantal repo list`
- ✅ `chantal repo show --repo-id X`
- ✅ `chantal repo sync --repo-id X`
- ✅ `chantal snapshot list/create/delete/diff`
- ⏳ `chantal package list --repo-id X` (NEW!)
- ⏳ `chantal package search <query>` (NEW!)
- ⏳ `chantal stats` (NEW!)

**Medium Priority (Post-MVP):**
- `chantal repo sync-status`
- `chantal repo sync-history`
- `chantal package show <package>`
- `chantal db stats`
- `chantal db verify`
- `chantal logs`

**Low Priority (Future):**
- `chantal package deps`
- `chantal snapshot merge`
- `chantal publish switch`
- `chantal config test`
- `chantal watch`
- `chantal shell`
- Multiple output formats (JSON, CSV, YAML)

---

**Next Step:** Implement `package` commands for MVP!
