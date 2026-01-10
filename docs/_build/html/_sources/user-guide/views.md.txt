# Views (Virtual Repositories)

**Views** are virtual repositories that combine multiple repositories into a single published repository.

**Status:** ✅ Available (Milestone 5 Complete)

## What are Views?

Views allow you to combine multiple repositories into one virtual repository. For example:

- **Combine RHEL channels**: BaseOS + AppStream + CRB in one repository
- **Add EPEL to RHEL**: Create "RHEL + EPEL" view for mixed packages
- **Custom stacks**: Web server stack (BaseOS + nginx + httpd), monitoring stack (EPEL tools), etc.

**Important:** ALL packages from ALL repositories are included (NO deduplication). The client (yum/dnf) decides which version to use based on repository priority.

## Use Cases

### 1. Combining RHEL Channels

**Problem:** RHEL distributes packages across multiple channels (BaseOS, AppStream, CRB). Clients need to configure 3 separate repositories.

**Solution:** Create a view that combines all channels:

```yaml
views:
  - name: rhel9-complete
    description: "RHEL 9 - All channels combined"
    repos:
      - rhel9-baseos-vim-latest
      - rhel9-appstream-nginx-latest
      - rhel9-crb-python-latest
```

**Result:** Clients only need one repository configuration.

### 2. Mixing RHEL + EPEL

**Problem:** Need both RHEL and EPEL packages on systems.

**Solution:** Create a view combining RHEL and EPEL:

```yaml
views:
  - name: rhel9-plus-epel
    description: "RHEL 9 + EPEL Combined"
    repos:
      - rhel9-baseos-vim-latest
      - rhel9-appstream-nginx-latest
      - epel9-htop-latest
      - epel9-monitoring-latest
```

**Result:** One repository with both RHEL and EPEL packages.

### 3. Custom Application Stacks

**Problem:** Web application needs specific packages from multiple repositories.

**Solution:** Create custom application stack view:

```yaml
views:
  - name: rhel9-webserver
    description: "RHEL 9 Web Server Stack"
    repos:
      - rhel9-baseos-vim-latest
      - rhel9-appstream-nginx-latest
      - rhel9-appstream-httpd-latest
```

**Result:** Application-specific repository with only needed packages.

## Configuration

### Location

Create `conf.d/views.yaml` (or any file included via `include: conf.d/*.yaml`).

### Format

```yaml
views:
  - name: view-name              # Unique identifier
    description: "Description"   # Optional human-readable description
    repos:                        # List of repository IDs
      - repo-id-1
      - repo-id-2
      - repo-id-3
```

### Requirements

- All repositories in a view must exist in the configuration
- All repositories must have the same type (rpm or apt)
- Repository order matters (determines metadata merge priority)

### Example Configuration

```yaml
# /etc/chantal/conf.d/views.yaml
views:
  # RHEL 9 Complete - All RHEL 9 repositories combined
  - name: rhel9-complete
    description: "RHEL 9 - All repositories (BaseOS + AppStream + CRB)"
    repos:
      - rhel9-baseos-vim-latest
      - rhel9-appstream-nginx-latest
      - rhel9-appstream-httpd-latest
      - rhel9-appstream-postgresql-latest
      - rhel9-crb-python-latest

  # RHEL 9 Web Server Stack
  - name: rhel9-webserver
    description: "RHEL 9 Web Server Stack (BaseOS + nginx + httpd)"
    repos:
      - rhel9-baseos-vim-latest
      - rhel9-appstream-nginx-latest
      - rhel9-appstream-httpd-latest

  # EPEL 9 Monitoring Tools
  - name: epel9-monitoring
    description: "EPEL 9 Monitoring Tools Collection"
    repos:
      - epel9-htop-latest
      - epel9-monitoring-latest
      - epel9-btop-latest
```

## CLI Commands

### List Views

```bash
chantal view list [--format table|json]
```

**Example output:**
```
Configured Views:

Name                Type  Repositories  Description
--------------------------------------------------------------------------------
rhel9-complete      rpm   5             RHEL 9 - All repositories (BaseOS + AppStream + CRB)
rhel9-webserver     rpm   3             RHEL 9 Web Server Stack (BaseOS + nginx + httpd)
epel9-monitoring    rpm   3             EPEL 9 Monitoring Tools Collection

Total: 3 view(s)
```

### Show View Details

```bash
chantal view show --name <view-name>
```

**Example output:**
```
View: rhel9-webserver

Basic Information:
  Name: rhel9-webserver
  Description: RHEL 9 Web Server Stack (BaseOS + nginx + httpd)
  Total Repositories: 3
  Total Packages: 36

Repositories in this view:
  ID                             Type   Enabled  Packages   Status
  ---------------------------------------------------------------------------
  rhel9-baseos-vim-latest        rpm    Yes      4          OK
  rhel9-appstream-nginx-latest   rpm    Yes      10         OK
  rhel9-appstream-httpd-latest   rpm    Yes      26         OK

Usage:
  Publish view:          chantal publish view --name rhel9-webserver
  Create view snapshot:  chantal snapshot create --view rhel9-webserver --name YYYY-MM-DD
```

### Publish View (Latest/Rolling)

```bash
chantal publish view --name <view-name>
```

**What it does:**
- Combines ALL packages from ALL repositories in the view
- Creates hardlinks from pool to published directory
- Generates RPM metadata (repomd.xml, primary.xml.gz)

**Output path:** `published/views/<view-name>/latest/`

**Example:**
```bash
$ chantal publish view --name rhel9-webserver

Publishing view: rhel9-webserver
Description: RHEL 9 Web Server Stack (BaseOS + nginx + httpd)

Target: /var/www/repos/views/rhel9-webserver/latest

Collecting packages from 3 repositories...

✓ View published successfully!

Client configuration:
  [view-rhel9-webserver]
  name=View: rhel9-webserver
  baseurl=file:///path/to/published/views/rhel9-webserver/latest
  enabled=1
  gpgcheck=0
```

**Directory structure:**
```
published/views/rhel9-webserver/latest/
├── Packages/          # Hardlinks to pool (all packages from all repos)
│   ├── nginx-*.rpm
│   ├── httpd-*.rpm
│   └── vim-*.rpm
└── repodata/
    ├── repomd.xml
    └── primary.xml.gz
```

## View Snapshots

### Create View Snapshot (Atomic Freeze)

```bash
chantal snapshot create \
  --view <view-name> \
  --name <snapshot-name> \
  [--description "..."]
```

**What it does:**
- Creates individual snapshots for EACH repository in the view (with same name)
- Creates a ViewSnapshot that references all repository snapshots
- Ensures all repositories are frozen at the same point in time (atomic)

**Example:**
```bash
$ chantal snapshot create \
    --view rhel9-webserver \
    --name 2025-01-10 \
    --description "January baseline"

Creating view snapshot '2025-01-10' of view 'rhel9-webserver'...
Description: January baseline

Creating snapshots for 3 repositories...

  [1/3] rhel9-baseos-vim-latest...
      ✓ 4 packages (0.05 GB)
  [2/3] rhel9-appstream-nginx-latest...
      ✓ 10 packages (0.02 GB)
  [3/3] rhel9-appstream-httpd-latest...
      ✓ 26 packages (0.08 GB)

✓ View snapshot '2025-01-10' created successfully!
  View: rhel9-webserver
  Repositories: 3
  Total packages: 40
  Total size: 0.15 GB
  Created: 2026-01-10 15:32:59

To publish this view snapshot:
  chantal publish snapshot --view rhel9-webserver --snapshot 2025-01-10
```

### Publish View Snapshot

```bash
chantal publish snapshot \
  --view <view-name> \
  --snapshot <snapshot-name>
```

**Output path:** `published/views/<view-name>/snapshots/<snapshot-name>/`

**Example:**
```bash
$ chantal publish snapshot \
    --view rhel9-webserver \
    --snapshot 2025-01-10

Publishing view snapshot: 2025-01-10
View: rhel9-webserver
Target: /var/www/repos/views/rhel9-webserver/snapshots/2025-01-10
Packages: 40

✓ View snapshot published successfully!
  Location: /var/www/repos/views/rhel9-webserver/snapshots/2025-01-10

Configure your package manager:
  [view-rhel9-webserver-snapshot-2025-01-10]
  name=View rhel9-webserver Snapshot 2025-01-10
  baseurl=file://.../views/rhel9-webserver/snapshots/2025-01-10
  enabled=1
  gpgcheck=0
```

### Show Snapshot Content (Compliance/Audit)

Export exact package list from snapshot:

```bash
# Human-readable table
chantal snapshot content \
  --view <view-name> \
  --snapshot <snapshot-name>

# JSON for automation
chantal snapshot content \
  --view <view-name> \
  --snapshot <snapshot-name> \
  --format json > audit/snapshot.json

# CSV for Excel/reporting
chantal snapshot content \
  --view <view-name> \
  --snapshot <snapshot-name> \
  --format csv > audit/snapshot.csv
```

**Table format (default):**
```
View Snapshot: rhel9-webserver / 2025-01-10
Created: 2026-01-10 15:32:59
Description: January baseline
Repositories: 3
Total Packages: 40
Total Size: 0.15 GB

Repository: rhel9-baseos-vim-latest (4 packages)
----------------------------------------------------------------------------------------------------
Name                   Version-Release           Arch       Size
----------------------------------------------------------------------------------------------------
vim-common             8.2.2637-20.el9           x86_64     7.4 MB
vim-enhanced           8.2.2637-20.el9           x86_64     1.9 MB
...
```

**JSON format:**
```json
{
  "type": "view_snapshot",
  "view": "rhel9-webserver",
  "snapshot": "2025-01-10",
  "created_at": "2026-01-10T15:32:59",
  "description": "January baseline",
  "total_packages": 40,
  "total_size_bytes": 157286400,
  "repositories": [
    {
      "repo_id": "rhel9-baseos-vim-latest",
      "snapshot_name": "2025-01-10",
      "package_count": 4,
      "packages": [
        {
          "name": "vim-enhanced",
          "epoch": "0",
          "version": "8.2.2637",
          "release": "20.el9",
          "arch": "x86_64",
          "nevra": "vim-enhanced-8.2.2637-20.el9.x86_64",
          "sha256": "abc123...",
          "size_bytes": 1989632,
          "filename": "vim-enhanced-8.2.2637-20.el9.x86_64.rpm"
        }
      ]
    }
  ]
}
```

**CSV format:**
```csv
view,snapshot,repo_id,name,epoch,version,release,arch,nevra,sha256,size_bytes,filename
rhel9-webserver,2025-01-10,rhel9-baseos-vim-latest,vim-enhanced,0,8.2.2637,20.el9,x86_64,vim-enhanced-8.2.2637-20.el9.x86_64,abc123...,1989632,vim-enhanced-8.2.2637-20.el9.x86_64.rpm
```

**Use cases:**
- Compliance reports ("What was deployed on date X?")
- Security audits (verify exact package versions)
- Change management (track package changes over time)

## Workflows

### Workflow 1: Rolling Release (Development)

```bash
# 1. Configure view
cat > conf.d/views.yaml <<EOF
views:
  - name: dev-stack
    repos:
      - rhel9-baseos-latest
      - rhel9-appstream-latest
EOF

# 2. Sync repositories
chantal repo sync --all

# 3. Publish view (latest)
chantal publish view --name dev-stack

# 4. Configure clients
# /etc/yum.repos.d/dev-stack.repo:
[dev-stack]
baseurl=http://mirror/chantal/views/dev-stack/latest/
enabled=1
gpgcheck=0
```

**Every time repositories are updated:**
```bash
chantal repo sync --all
chantal publish view --name dev-stack  # Overwrites latest/
```

### Workflow 2: Frozen Baselines (Production)

```bash
# 1. Create monthly baseline (atomic snapshot of all repos)
chantal snapshot create \
  --view prod-stack \
  --name 2025-01-10 \
  --description "January baseline"

# 2. Publish snapshot
chantal publish snapshot \
  --view prod-stack \
  --snapshot 2025-01-10

# 3. Test environment uses January baseline
# /etc/yum.repos.d/prod-stack-test.repo:
[prod-stack-test]
baseurl=http://mirror/chantal/views/prod-stack/snapshots/2025-01-10/
enabled=1
gpgcheck=0

# 4. After testing, production also uses January baseline
[prod-stack]
baseurl=http://mirror/chantal/views/prod-stack/snapshots/2025-01-10/
enabled=1
gpgcheck=0

# 5. Next month: Create February baseline
chantal snapshot create \
  --view prod-stack \
  --name 2025-02-15 \
  --description "February baseline"

chantal publish snapshot \
  --view prod-stack \
  --snapshot 2025-02-15

# 6. Test with February, then update production
```

### Workflow 3: Compliance/Audit

```bash
# Export snapshot content for compliance
chantal snapshot content \
  --view production \
  --snapshot 2025-01-10 \
  --format csv > compliance/prod-2025-01-10.csv

# Import into Excel, send to auditors
# CSV includes: view, snapshot, repo, name, epoch, version, release, arch, nevra, sha256, size, filename
```

**Use cases:**
- "What was deployed on 2025-01-10?" → CSV shows exact package list
- "Verify package integrity" → SHA256 checksums included
- "Track changes over time" → Compare CSV files from different dates

### Workflow 4: Automated Monthly Compliance Reports

```bash
#!/bin/bash
# compliance-report.sh - Run monthly via cron

DATE=$(date +%Y-%m)
VIEW="rhel9-production"

# Create snapshot
chantal snapshot create \
  --view "$VIEW" \
  --name "$DATE" \
  --description "Automated monthly snapshot"

# Export CSV
chantal snapshot content \
  --view "$VIEW" \
  --snapshot "$DATE" \
  --format csv > "compliance/$VIEW-$DATE.csv"

# Export JSON (machine-readable)
chantal snapshot content \
  --view "$VIEW" \
  --snapshot "$DATE" \
  --format json > "compliance/$VIEW-$DATE.json"

# Commit to audit repository
cd compliance/
git add "$VIEW-$DATE.csv" "$VIEW-$DATE.json"
git commit -m "Compliance snapshot: $VIEW $DATE"
git push
```

## Important Design Decisions

### 1. NO Deduplication

**Key Concept:** If two repositories have the same package (e.g., `nginx-1.20` in BaseOS and `nginx-1.26` in AppStream), BOTH are included in the view.

**Why:**
- Mirrors real-world RHEL behavior
- Allows repository priority to work correctly
- The client (yum/dnf) decides which version to install based on repository priority
- Simpler implementation (no conflict resolution)

**Example:**
```yaml
repos:
  - rhel9-baseos      # Contains: vim-8.2.2637
  - epel9-latest      # Contains: vim-9.0.2120

# Both packages are published
# Client chooses based on priority/version
```

### 2. Repository Order Matters

Repository order in the configuration determines the order in metadata generation.

**Example:**
```yaml
repos:
  - rhel9-baseos          # Order: 0 (highest priority)
  - rhel9-appstream       # Order: 1
  - epel9                 # Order: 2 (lowest priority)
```

### 3. View Snapshots are Atomic

When creating a view snapshot, snapshots are created for ALL repositories simultaneously.

**Benefit:** Ensures consistent state across all repositories (e.g., "January 2025 baseline" freezes BaseOS, AppStream, AND EPEL at the same point in time).

### 4. Hardlink-based Publishing

**Why:** Zero-copy publishing (instant, no disk space wasted)

**Technical:**
- Packages in pool: `/pool/ab/cd/sha256_nginx.rpm` (inode: 12345)
- Hardlink in view: `/views/rhel9/latest/Packages/nginx.rpm` (inode: 12345)
- Same file, multiple paths, single storage

## Client Configuration Examples

### Example 1: Development (Rolling Release)

```ini
[dev-stack]
name=Development Stack
baseurl=http://mirror.example.com/chantal/views/dev-stack/latest/
enabled=1
gpgcheck=0
priority=10
```

### Example 2: Production (Frozen Baseline)

```ini
[prod-stack]
name=Production Stack - January 2025 Baseline
baseurl=http://mirror.example.com/chantal/views/prod-stack/snapshots/2025-01-10/
enabled=1
gpgcheck=0
priority=10
```

### Example 3: Testing New Baseline

```ini
[test-february]
name=Test Environment - February 2025 Baseline
baseurl=http://mirror.example.com/chantal/views/prod-stack/snapshots/2025-02-15/
enabled=1
gpgcheck=0
priority=10
```

## Troubleshooting

### View shows 0 packages

**Problem:** `chantal view show --name myview` shows 0 packages

**Cause:** Repositories in view haven't been synced yet

**Solution:**
```bash
# Sync all repos in the view
chantal repo sync --repo-id repo1
chantal repo sync --repo-id repo2
chantal repo sync --repo-id repo3
```

### View snapshot creation fails

**Problem:** `Error: Repository 'repo-xyz' has no packages (skipped)`

**Cause:** One or more repositories in view are empty

**Solution:** Sync the empty repositories or remove them from the view configuration

### Published view doesn't update

**Problem:** New packages in repos don't appear in published view

**Cause:** View shows latest state at time of publishing (not auto-updated)

**Solution:**
```bash
# Re-publish view to pick up new packages
chantal publish view --name myview
```

### Repository not found in view

**Problem:** `Error: Repository 'rhel9-baseos' not found`

**Solution:** Ensure all repositories in view exist and are configured in `repositories:` section

### View type mismatch

**Problem:** `Error: All repositories in view must have the same type`

**Cause:** Trying to mix RPM and DEB repositories in same view

**Solution:** Create separate views for different repository types

## Best Practices

1. **Use descriptive names**: `rhel9-complete` instead of `view1`
2. **Document purpose**: Add clear descriptions explaining what the view combines
3. **Atomic snapshots**: Always use view snapshots for patch management
4. **Test before promoting**: Test view snapshots in dev/staging before production
5. **Regular cleanup**: Delete old snapshots to save space
6. **Repository priority**: Configure repository priorities on clients if needed
7. **Compliance exports**: Export snapshots regularly for audit trail

## Migration from Pulp/Katello

### Pulp "Composite Content Views" → Chantal "Views"

**Pulp Concept:**
```ruby
# Pulp composite content view
composite_content_view 'rhel9-complete' do
  component_ids ['rhel9-baseos-cv', 'rhel9-appstream-cv']
end
```

**Chantal Equivalent:**
```yaml
views:
  - name: rhel9-complete
    repos:
      - rhel9-baseos
      - rhel9-appstream
```

**Key Differences:**
- **Pulp:** Content Views require activation/promotion
- **Chantal:** Views publish immediately (no activation needed)
- **Pulp:** Complex versioning system
- **Chantal:** Simple snapshots with names/dates
- **Pulp:** Requires Katello/Foreman
- **Chantal:** Standalone CLI tool

## Technical Details

### Database Models

Views are stored in three database tables:

1. **View** - View metadata (name, description, type)
2. **ViewRepository** - Many-to-many relationship (view ↔ repositories)
3. **ViewSnapshot** - Snapshot metadata with references to repository snapshots

See [Database Schema](../architecture/database-schema.md) for details.

### Storage Structure

```
/var/lib/chantal/                   # Storage base path
├── pool/                           # Content-addressed package pool
│   └── ab/cd/sha256_package.rpm   # Shared by all repos/views

/var/www/repos/                     # Published path
├── repositories/                   # Individual repositories
│   ├── rhel9-baseos/latest/
│   └── rhel9-appstream/latest/
└── views/                          # Views (combining repos)
    ├── rhel9-complete/
    │   ├── latest/                 # Rolling release
    │   │   ├── Packages/           # Hardlinks to pool
    │   │   └── repodata/
    │   └── snapshots/              # Frozen baselines
    │       ├── 2025-01-10/
    │       └── 2025-02-15/
    └── rhel9-webserver/
        ├── latest/
        └── snapshots/
            └── 2025-01-10/
```

## Future Enhancements

Ideas for future versions (not yet implemented):

1. **View Priority/Weight per Repository** - Custom priority for repositories within a view
2. **View Diff Command** - Show changes across all repositories in the view
3. **View Metadata Merging Options** - Options for conflict resolution
4. **View Templates** - Reusable view configurations
