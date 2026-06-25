# Content-Addressed Storage

Chantal uses SHA256-based content-addressed storage for automatic deduplication and efficient package management.

## Overview

Instead of organizing packages by repository or path, Chantal stores them by their content hash (SHA256). This provides:

- **Automatic deduplication** - Identical packages stored once
- **Fast existence checks** - Single hash lookup
- **Integrity verification** - Built-in checksum validation
- **Cross-repository sharing** - Packages shared across all repos

## Storage Structure

### Two Pools + 2-Level Directory Hierarchy

The pool is split by **pool type** into two top-level subdirectories, and each is
organized in a 2-level directory structure keyed on the SHA256:

- `pool/content/` - packages (`ContentItem`)
- `pool/files/` - metadata, signatures and installer files (`RepositoryFile`)

```
pool/
├── content/                         # Packages (ContentItem)
│   ├── f2/                          # First 2 chars of SHA256
│   │   └── 56/                      # Next 2 chars of SHA256
│   │       └── f256abc...def789_nginx-1.20.2-1.el9.x86_64.rpm
│   └── 95/
│       └── 05/
│           └── 9505484...1264_nginx-module-njs-1.24.0.rpm
└── files/                           # Metadata/installer files (RepositoryFile)
    └── 56/
        └── 78/
            └── 5678abc..._updateinfo.xml.gz
```

`StorageManager.get_pool_path(sha256, filename, pool_type="content")` prepends the
pool type (`content` or `files`) to the relative path.

**Filename format:**
```
{sha256}_{original_filename}
```

**Example:**
```
f256abcdef0123456789abcdef0123456789abcdef0123456789abcdef789_nginx-1.20.2-1.el9.x86_64.rpm
```

### Why 2 Levels?

**Performance optimization:**
- Most filesystems slow down with >10,000 files per directory
- 2 levels = 256 × 256 = 65,536 buckets
- Typical repository: 10,000-100,000 packages
- Average: ~1-2 packages per bucket

**Alternative approaches:**
- 1 level: Too many files in single directory (poor performance)
- 3+ levels: Over-optimization, complexity without benefit

## Deduplication

### Automatic Deduplication

When syncing a package:

1. Download the package to a temporary file
2. Calculate SHA256 of the file
3. Compute the pool path: `pool/content/{sha256[:2]}/{sha256[2:4]}/{sha256}_{filename}`
4. If it already exists: skip the copy, reference the existing file
5. If not: copy into the pool and verify the checksum

**Example:**

```python
# Package: nginx-1.20.2-1.el9.x86_64.rpm
sha256 = "f256abcdef0123456789abcdef0123456789abcdef0123456789abcdef789"

# Storage path (packages live under content/)
pool_path = "pool/content/f2/56/f256abc...def789_nginx-1.20.2-1.el9.x86_64.rpm"

# StorageManager.add_package() handles dedup + checksum verification on a LOCAL file
sha256, pool_path_rel, size_bytes = storage.add_package(source_path, filename)
```

### Cross-Repository Deduplication

Identical packages across repositories are stored once:

```
Repository A: nginx-1.20.2-1.el9.x86_64.rpm (SHA256: f256abc...)
Repository B: nginx-1.20.2-1.el9.x86_64.rpm (SHA256: f256abc...)
Repository C: nginx-1.20.2-1.el9.x86_64.rpm (SHA256: f256abc...)

Pool storage: 1 copy (content/f2/56/f256abc...rpm)
Database: 3 repository associations
```

**Typical deduplication rates:**
- RHEL 9.x minor versions: 60-80% deduplication
- RHEL + CentOS + Rocky: 70-85% deduplication
- RHEL BaseOS + AppStream: 5-10% deduplication

## Database Integration

### ContentItem Model

Packages of all types are stored in the generic `ContentItem` model. The SHA256
is a **unique** column (the primary key is an integer `id`). See
[Database Schema](database-schema.md) for the full definition.

```python
class ContentItem:
    id: int               # Primary key
    sha256: str           # Content address (UNIQUE)
    filename: str         # Original filename
    size_bytes: int       # File size in bytes
    pool_path: str        # Relative pool path (e.g. "content/ab/cd/<sha>_file.rpm")

    content_type: str     # "rpm", "helm", "apt", ...
    name: str             # Package name (e.g., "nginx")
    version: str          # Version
    content_metadata: dict  # JSON: release/arch/epoch/etc. (type-specific)

    # Many-to-many with repositories and snapshots
    repositories: list[Repository]
    snapshots: list[Snapshot]
```

`RepositoryFile` mirrors this design for metadata/installer files, stored under
`pool/files/` instead of `pool/content/`.

### Junction Table

Content items can belong to multiple repositories:

```
repository_content_items (junction table)
├── repository_id: int        (FK -> repositories.id)
├── content_item_id: int      (FK -> content_items.id)
└── added_at: datetime
```

**Query examples:**

```python
# Find all content items in a repository
items = repository.content_items

# Find all repositories containing a content item
repositories = item.repositories

# Check if a content item is in the pool
item = session.query(ContentItem).filter_by(sha256=sha256).first()
if item:
    print(f"In pool, used by {len(item.repositories)} repos")
```

## Hardlink-Based Publishing

Published repositories use hardlinks to pool:

```
published/
├── rhel9-baseos/
│   └── latest/
│       ├── Packages/
│       │   ├── nginx-1.20.2-1.el9.x86_64.rpm  → hardlink to pool
│       │   └── httpd-2.4.51-1.el9.x86_64.rpm  → hardlink to pool
│       └── repodata/
│           ├── repomd.xml
│           └── primary.xml.gz
└── rhel9-baseos/
    └── snapshots/
        └── 2025-01/
            └── ...
```

**Benefits:**
- **Zero-copy:** No disk space wasted
- **Instant publishing:** Creating hardlinks takes milliseconds
- **Atomic updates:** Metadata published atomically

**How hardlinks work:**

```python
import os

# Create hardlink from pool to published directory
pool_path = "pool/content/f2/56/f256abc...rpm"
published_path = "published/rhel9-baseos/latest/Packages/nginx-1.20.2-1.el9.x86_64.rpm"

# Both paths point to the same inode (same physical data).
# os.link() is used (not Path.hardlink_to()).
os.link(pool_path, published_path)

# Deleting one doesn't affect the other.
# Data is deleted only when all hardlinks are removed.
```

## Storage Operations

### Add Package

`add_package()` operates on a **local** file that has already been downloaded; it
does not fetch from a URL. It hashes the file, copies it into `pool/content/`
(unless an identical SHA256 is already present), optionally verifies the checksum,
and returns `(sha256, pool_path, size_bytes)`.

```python
def add_package(
    self, source_path: Path, filename: str, verify_checksum: bool = True
) -> tuple[str, str, int]:
    """Add a local package file to the content pool."""
    sha256 = self.calculate_sha256(source_path)
    pool_path_rel = self.get_pool_path(sha256, filename)        # "content/ab/cd/..."
    pool_path_abs = self.pool_path / pool_path_rel
    size_bytes = source_path.stat().st_size

    if pool_path_abs.exists():
        return sha256, pool_path_rel, size_bytes  # Already in pool (dedup)

    pool_path_abs.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, pool_path_abs)
    # ... optional checksum verification ...
    return sha256, pool_path_rel, size_bytes
```

Metadata/installer files use the sibling method `add_repository_file()`, which is
identical except it stores under `pool/files/`.

### Create Hardlink

```python
def create_hardlink(self, sha256: str, filename: str, target_path: Path) -> None:
    """Create hardlink from pool to target."""
    source_path = self.get_absolute_pool_path(sha256, filename)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists():
        target_path.unlink()
    # os.link for compatibility (not Path.hardlink_to)
    os.link(source_path, target_path)
```

### Verify Pool Integrity

```python
def verify_pool():
    """Verify all files in pool match their SHA256."""
    for pool_file in pool_dir.rglob("*"):
        if pool_file.is_file():
            # Extract SHA256 from filename
            sha256 = pool_file.name.split("_")[0]

            # Verify checksum
            actual_sha256 = hash_file(pool_file)
            if actual_sha256 != sha256:
                print(f"ERROR: {pool_file} checksum mismatch")
```

### Cleanup Orphaned Files

Orphan detection unions the SHA256s from **both** content-addressed tables —
`ContentItem` (packages) and `RepositoryFile` (metadata/installer files) — and
scans both pool subdirectories (`content/` and `files/`).

```python
def get_orphaned_files(self, session):
    """Find pool files not referenced by either content table."""
    content_sha256s = {row.sha256 for row in session.query(ContentItem.sha256).all()}
    file_sha256s = {row.sha256 for row in session.query(RepositoryFile.sha256).all()}
    db_sha256s = content_sha256s | file_sha256s  # Union of both tables

    orphaned = []
    for pool_file in self.pool_path.rglob("*"):
        if pool_file.is_file() and "_" in pool_file.name:
            file_sha256 = pool_file.name.split("_", 1)[0]
            if len(file_sha256) == 64 and file_sha256 not in db_sha256s:
                orphaned.append(pool_file)
    return orphaned
```

## Storage Statistics

### Pool Stats

```bash
$ chantal pool stats
Pool Statistics:

Total Packages: 1,234
Total Size: 12.5 GB
Average Package Size: 10.1 MB

Top 10 Largest Packages:
  kernel-5.14.0-360.el9.x86_64.rpm: 85.2 MB
  kernel-modules-5.14.0-360.el9.x86_64.rpm: 42.1 MB
  ...
```

### Deduplication Stats

```bash
$ chantal stats --deduplication
Deduplication Statistics:

Unique Packages: 1,234
Total References: 3,456
Deduplication Ratio: 64%
Space Saved: 15.2 GB
```

## Advantages

1. **Instant Duplicate Detection:** O(1) lookup via SHA256
2. **Automatic Deduplication:** No manual intervention needed
3. **Integrity Verification:** Built-in checksums
4. **Cross-Repository Sharing:** One package, many repos
5. **Efficient Publishing:** Zero-copy hardlinks
6. **Snapshot-Friendly:** Metadata-only snapshots

## Limitations

1. **Hardlink Requirements:** Pool and published must be on same filesystem
2. **No Compression:** Packages stored as-is (trade-off for deduplication)
3. **Orphan Cleanup:** Requires periodic cleanup if packages are deleted

## Best Practices

1. **Same Filesystem:** Ensure pool and published are on same filesystem for hardlinks
2. **Regular Verification:** Run `chantal pool verify` periodically
3. **Cleanup Orphans:** Run `chantal pool cleanup` after deleting repos/snapshots
4. **Monitor Disk Space:** Track pool growth over time
5. **Backup Strategy:** Backup pool and database together
