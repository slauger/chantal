# Views Feature - Documentation Brief for MkDocs

**Status:** ✅ Complete (Milestone 5) - All implementation done
**Date:** 2026-01-10
**Purpose:** Input for Claude to build comprehensive MkDocs documentation

---

## What are Views?

**Views** are virtual repositories that combine multiple repositories into a single published repository.

**Key Concept:** NO deduplication - ALL packages from ALL repositories are included. The client (yum/dnf) decides which package version to use based on repository priority.

---

## Use Cases

### 1. Combining RHEL Channels
**Problem:** RHEL distributes packages across multiple channels (BaseOS, AppStream, CRB)
**Solution:** Create a view that combines all channels into one repository

**Example:**
```yaml
views:
  - name: rhel9-complete
    description: "RHEL 9 - All channels combined"
    repos:
      - rhel9-baseos-vim-latest
      - rhel9-appstream-nginx-latest
      - rhel9-crb-python-latest
```

### 2. Mixing RHEL + EPEL
**Problem:** Need both RHEL and EPEL packages on systems
**Solution:** Create a view combining RHEL and EPEL repos

**Example:**
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

### 3. Custom Application Stacks
**Problem:** Web server needs specific repos (BaseOS + nginx + httpd)
**Solution:** Create focused view for specific use case

**Example:**
```yaml
views:
  - name: rhel9-webserver
    description: "RHEL 9 Web Server Stack"
    repos:
      - rhel9-baseos-vim-latest
      - rhel9-appstream-nginx-latest
      - rhel9-appstream-httpd-latest
```

---

## Configuration

### Location
`conf.d/views.yaml` (or any file included via `include: conf.d/*.yaml`)

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

### Example Configuration File
```yaml
# .dev/conf.d/views.yaml
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

---

## CLI Commands

### View Management

#### List Views
```bash
chantal view list [--format table|json]
```

**Output:**
```
Configured Views:

Name                Type  Repositories  Description
--------------------------------------------------------------------------------
rhel9-complete      rpm   5             RHEL 9 - All repositories (BaseOS + AppStream + CRB)
rhel9-webserver     rpm   3             RHEL 9 Web Server Stack (BaseOS + nginx + httpd)
epel9-monitoring    rpm   3             EPEL 9 Monitoring Tools Collection

Total: 3 view(s)
```

#### Show View Details
```bash
chantal view show --name <view-name>
```

**Output:**
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

### Publishing Views

#### Publish View (Latest/Rolling)
```bash
chantal publish view --name <view-name>
```

**What it does:**
- Combines ALL packages from ALL repositories in the view
- Creates hardlinks from pool to published directory
- Generates RPM metadata (repomd.xml, primary.xml.gz)
- Updates view.is_published, view.published_at, view.published_path

**Output path:** `published/views/<view-name>/latest/`

**Example:**
```bash
chantal publish view --name rhel9-webserver
```

**Result:**
```
Publishing view: rhel9-webserver
Description: RHEL 9 Web Server Stack (BaseOS + nginx + httpd)

Target: .dev/dev-storage/published/views/rhel9-webserver/latest

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

### View Snapshots

#### Create View Snapshot (Atomic Freeze)
```bash
chantal snapshot create --view <view-name> --name <snapshot-name> [--description "..."]
```

**What it does:**
- Creates individual snapshots for EACH repository in the view (with same name)
- Creates a ViewSnapshot that references all repository snapshots
- Ensures all repositories are frozen at the same point in time (atomic)

**Example:**
```bash
chantal snapshot create --view rhel9-webserver --name 2025-01-10 --description "January baseline"
```

**Output:**
```
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

**What gets created in database:**
- 3 × Snapshot records (one per repository, all named "2025-01-10")
- 1 × ViewSnapshot record (references all 3 snapshot IDs)

#### Publish View Snapshot
```bash
chantal publish snapshot --view <view-name> --snapshot <snapshot-name>
```

**Output path:** `published/views/<view-name>/snapshots/<snapshot-name>/`

**Example:**
```bash
chantal publish snapshot --view rhel9-webserver --snapshot 2025-01-10
```

**Result:**
```
Publishing view snapshot: 2025-01-10
View: rhel9-webserver
Target: .dev/dev-storage/published/views/rhel9-webserver/snapshots/2025-01-10
Packages: 40

✓ View snapshot published successfully!
  Location: .dev/dev-storage/published/views/rhel9-webserver/snapshots/2025-01-10
  Packages directory: .../snapshots/2025-01-10/Packages
  Metadata directory: .../snapshots/2025-01-10/repodata

Configure your package manager:
  [view-rhel9-webserver-snapshot-2025-01-10]
  name=View rhel9-webserver Snapshot 2025-01-10
  baseurl=file://.../views/rhel9-webserver/snapshots/2025-01-10
  enabled=1
  gpgcheck=0
```

#### Show Snapshot Content (Compliance/Audit)
```bash
chantal snapshot content --view <view-name> --snapshot <snapshot-name> [--format table|json|csv]
```

**Formats:**

**1. Table (default)** - Human-readable:
```bash
chantal snapshot content --view rhel9-webserver --snapshot 2025-01-10
```

Output:
```
View Snapshot: rhel9-webserver / 2025-01-10
Created: 2026-01-10 15:32:59
Description: January baseline
Repositories: 3
Total Packages: 40
Total Size: 0.15 GB

Repository: rhel9-baseos-vim-latest (4 packages)
----------------------------------------------------------------------------------------------------
Name                                     Version-Release                     Arch       Size
----------------------------------------------------------------------------------------------------
vim-common                               8.2.2637-20.el9                     x86_64     7.4 MB
vim-enhanced                             8.2.2637-20.el9                     x86_64     1.9 MB
...
```

**2. JSON** - For automation/tools:
```bash
chantal snapshot content --view rhel9-webserver --snapshot 2025-01-10 --format json > audit.json
```

Output:
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
        },
        ...
      ]
    },
    ...
  ]
}
```

**3. CSV** - For Excel/reporting:
```bash
chantal snapshot content --view rhel9-webserver --snapshot 2025-01-10 --format csv > audit.csv
```

Output:
```csv
view,snapshot,repo_id,name,epoch,version,release,arch,nevra,sha256,size_bytes,filename
rhel9-webserver,2025-01-10,rhel9-baseos-vim-latest,vim-enhanced,0,8.2.2637,20.el9,x86_64,vim-enhanced-8.2.2637-20.el9.x86_64,abc123...,1989632,vim-enhanced-8.2.2637-20.el9.x86_64.rpm
rhel9-webserver,2025-01-10,rhel9-appstream-nginx-latest,nginx,2,1.26.3,1.module+el9...,x86_64,nginx-2:1.26.3-1.module+el9....x86_64,def456...,36164,nginx-1.26.3-1.module+el9....x86_64.rpm
...
```

---

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
[dev-stack]
baseurl=http://mirror/chantal/views/dev-stack/latest/
enabled=1
```

**Every time repositories are updated:**
```bash
chantal repo sync --all
chantal publish view --name dev-stack  # Overwrites latest/
```

### Workflow 2: Frozen Baselines (Production)

```bash
# 1. Create monthly baseline (atomic snapshot of all repos)
chantal snapshot create --view prod-stack --name 2025-01-10 --description "January baseline"

# 2. Publish snapshot
chantal publish snapshot --view prod-stack --snapshot 2025-01-10

# 3. Test environment uses January baseline
[prod-stack-test]
baseurl=http://mirror/chantal/views/prod-stack/snapshots/2025-01-10/

# 4. After testing, production also uses January baseline
[prod-stack]
baseurl=http://mirror/chantal/views/prod-stack/snapshots/2025-01-10/

# 5. Next month: Create February baseline
chantal snapshot create --view prod-stack --name 2025-02-15 --description "February baseline"
chantal publish snapshot --view prod-stack --snapshot 2025-02-15

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

---

## Architecture

### Database Models

**1. View** (`chantal.db.models.View`)
```python
class View(Base):
    __tablename__ = "views"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False, index=True)
    description = Column(Text)
    repo_type = Column(String(50), nullable=False)  # "rpm" or "apt"
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Publishing tracking
    is_published = Column(Boolean, default=False)
    published_at = Column(DateTime)
    published_path = Column(Text)

    # Relationships
    view_repositories = relationship("ViewRepository", back_populates="view", cascade="all, delete-orphan")
    view_snapshots = relationship("ViewSnapshot", back_populates="view", cascade="all, delete-orphan")
```

**2. ViewRepository** (`chantal.db.models.ViewRepository`)
```python
class ViewRepository(Base):
    __tablename__ = "view_repositories"

    id = Column(Integer, primary_key=True)
    view_id = Column(Integer, ForeignKey("views.id"), nullable=False)
    repository_id = Column(Integer, ForeignKey("repositories.id"), nullable=False)
    order = Column(Integer, nullable=False)  # Repository priority/order
    added_at = Column(DateTime, default=datetime.utcnow)

    # Unique constraint: one repo can only appear once per view
    __table_args__ = (
        UniqueConstraint("view_id", "repository_id", name="uq_view_repository"),
    )

    # Relationships
    view = relationship("View", back_populates="view_repositories")
    repository = relationship("Repository")
```

**3. ViewSnapshot** (`chantal.db.models.ViewSnapshot`)
```python
class ViewSnapshot(Base):
    __tablename__ = "view_snapshots"

    id = Column(Integer, primary_key=True)
    view_id = Column(Integer, ForeignKey("views.id"), nullable=False)
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    # References to individual repository snapshots (JSON array of snapshot IDs)
    snapshot_ids = Column(JSON, nullable=False)

    # Cached statistics
    package_count = Column(Integer, nullable=False)
    total_size_bytes = Column(Integer, nullable=False)

    # Publishing tracking
    is_published = Column(Boolean, default=False)
    published_at = Column(DateTime)
    published_path = Column(Text)

    # Unique constraint: one snapshot name per view
    __table_args__ = (
        UniqueConstraint("view_id", "name", name="uq_view_snapshot_name"),
    )

    # Relationships
    view = relationship("View", back_populates="view_snapshots")
```

### ViewPublisher Plugin

**File:** `src/chantal/plugins/view_publisher.py`

**Key Design Decision:** Extends `RpmPublisher` to reuse metadata generation logic

```python
class ViewPublisher(RpmPublisher):
    """Publisher for Views (multi-repository virtual repositories).

    Views combine multiple repositories into a single virtual repository.
    All packages from all repositories are included (NO deduplication).
    The client (yum/dnf) decides which package version to use in case of conflicts.
    """

    def publish_view(self, session, view, target_path):
        """Publish view to target directory (combines latest from all repos)."""
        packages = self._get_view_packages(session, view)
        self._publish_packages(packages, target_path)

    def publish_view_snapshot(self, session, view_snapshot, target_path):
        """Publish view snapshot to target directory (combines specific snapshots)."""
        packages = self._get_view_snapshot_packages(session, view_snapshot)
        self._publish_packages(packages, target_path)

    def _get_view_packages(self, session, view):
        """Get all packages from all repositories in view.

        IMPORTANT: NO deduplication! All packages from all repos are included.
        """
        all_packages = []
        session.refresh(view)

        for view_repo in sorted(view.view_repositories, key=lambda vr: vr.order):
            repo = view_repo.repository
            session.refresh(repo)
            all_packages.extend(repo.packages)

        return all_packages

    def _get_view_snapshot_packages(self, session, view_snapshot):
        """Get all packages from all snapshots in a view snapshot."""
        all_packages = []

        for snapshot_id in view_snapshot.snapshot_ids:
            snapshot = session.query(Snapshot).filter_by(id=snapshot_id).first()
            if snapshot:
                all_packages.extend(snapshot.packages)

        return all_packages
```

### Storage Structure

```
.dev/dev-storage/
├── pool/                           # Content-addressed package pool
│   └── ab/cd/sha256_package.rpm   # Shared by all repos/views
├── published/
│   ├── repositories/               # Individual repositories
│   │   ├── rhel9-baseos/latest/
│   │   └── rhel9-appstream/latest/
│   └── views/                      # Views (combining repos)
│       ├── rhel9-complete/
│       │   ├── latest/             # Rolling release
│       │   │   ├── Packages/       # Hardlinks to pool
│       │   │   └── repodata/
│       │   └── snapshots/          # Frozen baselines
│       │       ├── 2025-01-10/
│       │       └── 2025-02-15/
│       └── rhel9-webserver/
│           ├── latest/
│           └── snapshots/
│               └── 2025-01-10/
```

---

## Configuration Integration

### Pydantic Models

**File:** `src/chantal/core/config.py`

```python
class ViewConfig(BaseModel):
    """Configuration for a view (virtual repository combining multiple repos)."""

    name: str = Field(..., description="View name (unique identifier)")
    description: Optional[str] = Field(None, description="Human-readable description")
    repos: List[str] = Field(..., description="List of repository IDs to include")
    publish_path: Optional[str] = Field(None, description="Custom publish path (optional)")

class GlobalConfig(BaseModel):
    """Global configuration."""

    database: DatabaseConfig
    storage: StorageConfig
    repositories: List[RepositoryConfig] = Field(default_factory=list)
    views: List[ViewConfig] = Field(default_factory=list)  # NEW

    def get_view(self, name: str) -> ViewConfig:
        """Get view configuration by name."""
        for view in self.views:
            if view.name == name:
                return view
        raise ValueError(f"View '{name}' not found in configuration")
```

### YAML Loading

**Example:** `.dev/conf.d/views.yaml`
```yaml
views:
  - name: rhel9-complete
    description: "RHEL 9 - All channels"
    repos:
      - rhel9-baseos-vim-latest
      - rhel9-appstream-nginx-latest
```

**Loaded via:**
```python
# In load_config()
config = GlobalConfig(**data)  # Pydantic validates views list
```

---

## Testing

**File:** `tests/test_views.py` (10 tests)

**Test Coverage:**
1. `test_create_view()` - Basic view creation
2. `test_view_unique_name()` - Name uniqueness constraint
3. `test_view_repository_relationship()` - Many-to-many relationship
4. `test_view_repository_unique_constraint()` - Repo can only appear once per view
5. `test_create_view_snapshot()` - ViewSnapshot creation
6. `test_view_snapshot_unique_name_per_view()` - Snapshot name uniqueness per view
7. `test_view_get_all_packages()` - Package collection from multiple repos
8. `test_view_snapshot_retrieves_packages()` - Package retrieval from snapshots
9. `test_view_publish_state()` - Publishing state tracking
10. `test_view_snapshot_publish_state()` - Snapshot publishing state

**All tests passing:** ✅ 74/74 (64 core + 10 views)

---

## Important Design Decisions

### 1. NO Deduplication
**Why:** If two repositories have the same package (e.g., nginx-1.20 in BaseOS and nginx-1.26 in AppStream), BOTH are included in the view. The client (yum/dnf) decides which one to install based on repository priority.

**Rationale:**
- Mirrors real-world RHEL behavior
- Allows repository priority to work correctly
- Simpler implementation (no conflict resolution)

### 2. Repository Order Matters
**Why:** The `order` field in `ViewRepository` determines the order in metadata generation.

**Example:**
```yaml
repos:
  - rhel9-baseos          # Order: 0 (highest priority)
  - rhel9-appstream       # Order: 1
  - epel9                 # Order: 2 (lowest priority)
```

### 3. View Snapshots are Atomic
**Why:** When creating a view snapshot, snapshots are created for ALL repositories simultaneously.

**Benefit:** Ensures consistent state across all repositories (e.g., "January 2025 baseline" freezes BaseOS, AppStream, AND EPEL at the same point in time).

### 4. Hardlink-based Publishing
**Why:** Zero-copy publishing (instant, no disk space wasted)

**Technical:**
- Packages in pool: `/pool/ab/cd/sha256_nginx.rpm` (inode: 12345)
- Hardlink in view: `/views/rhel9/latest/Packages/nginx.rpm` (inode: 12345)
- Same file, multiple paths, single storage

---

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

---

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

---

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
- Pulp: Content Views require activation/promotion
- Chantal: Views publish immediately (no activation needed)
- Pulp: Complex versioning system
- Chantal: Simple snapshots with names/dates

---

## Future Enhancements (Not Yet Implemented)

1. **View Priority/Weight per Repository**
   - Allow custom priority for repositories within a view
   - Example: "Prefer AppStream over BaseOS if package exists in both"

2. **View Diff Command**
   ```bash
   chantal view diff --view prod-stack 2025-01-10 2025-02-15
   ```
   - Show changes across all repositories in the view

3. **View Metadata Merging Options**
   - Currently: All packages included
   - Future: Options for conflict resolution (newest, largest, custom)

4. **View Templates**
   - Reusable view configurations
   - Example: "webserver-template" → applied to RHEL 9, RHEL 10, etc.

---

## Summary for Documentation

**Essential Pages to Create:**

1. **Getting Started with Views**
   - What are views?
   - Why use views?
   - Basic example

2. **Configuring Views**
   - YAML syntax
   - Repository requirements
   - Examples (RHEL channels, RHEL+EPEL, custom stacks)

3. **Publishing Views**
   - Latest (rolling release)
   - Snapshots (frozen baselines)
   - Client configuration

4. **View Snapshots**
   - Creating atomic snapshots
   - Publishing snapshots
   - Compliance/audit exports (CSV, JSON)

5. **Workflows**
   - Development workflow (rolling)
   - Production workflow (frozen baselines)
   - Compliance/audit workflow

6. **Architecture**
   - Database models
   - Publisher plugin
   - Storage structure

7. **Troubleshooting**
   - Common issues
   - Error messages
   - Solutions

---

**End of Views Documentation Brief**
