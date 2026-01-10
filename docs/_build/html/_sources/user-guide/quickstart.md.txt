# Quick Start

This guide will help you get started with Chantal in minutes.

## 1. Initialize Chantal

Create the database and directory structure:

```bash
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

## 2. Configure Repositories

Create `config.yaml` (or use `.dev/config.yaml` for development):

```yaml
# Database
database:
  url: sqlite:///.dev/chantal-dev.db

# Storage paths
storage:
  base_path: ./.dev/dev-storage
  pool_path: ./.dev/dev-storage/pool
  published_path: ./.dev/dev-storage/published

# Include repository definitions
include: "conf.d/*.yaml"
```

Create a repository definition in `conf.d/epel9.yaml`:

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

## 3. List Configured Repositories

```bash
chantal repo list
```

## 4. Sync Repository

Sync a single repository:

```bash
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

[1/3] Processing vim-common-9.0.2120-1.el9.x86_64
  → Downloading from https://dl.fedoraproject.org/...
  → Downloaded 7.42 MB

✓ Sync completed successfully!
  Total packages: 3
  Downloaded: 2
  Skipped (already in pool): 1
  Data transferred: 9.31 MB
```

## 5. Check for Updates

Check for updates without downloading:

```bash
chantal repo check-updates --repo-id epel9-vim-latest
```

## 6. Create Snapshot

Create an immutable snapshot:

```bash
chantal snapshot create \
  --repo-id epel9-vim-latest \
  --name 20250110 \
  --description "January 2025 baseline"
```

## 7. Publish Repository

Publish the repository (creates hardlinks to published directory):

```bash
chantal publish repo --repo-id epel9-vim-latest
```

## Next Steps

- Learn about [CLI commands](cli-commands.md) in detail
- Configure [RHEL subscriptions](../configuration/ssl-authentication.md) for Red Hat repos
- Understand [workflows](workflows.md) for patch management
