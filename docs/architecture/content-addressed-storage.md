# Content-Addressed Storage

Chantal uses SHA256-based content-addressed storage for automatic deduplication and efficient package management.

## Overview

Instead of organizing packages by repository or path, Chantal stores them by their content hash (SHA256). This provides:

- **Automatic deduplication** - Identical packages stored once
- **Fast existence checks** - Single hash lookup
- **Integrity verification** - Built-in checksum validation
- **Cross-repository sharing** - Packages shared across all repos

## Storage Structure

### 2-Level Directory Hierarchy

Packages are stored in a 2-level directory structure:

```
pool/
├── f2/                          # First 2 chars of SHA256
│   └── 56/                      # Next 2 chars of SHA256
│       └── f256abc...def789_nginx-1.20.2-1.el9.x86_64.rpm
├── 95/
│   └── 05/
│       └── 9505484...1264_nginx-module-njs-1.24.0.rpm
└── ...
```

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

1. Calculate SHA256 of package file
2. Check if file exists in pool: `pool/{sha256[:2]}/{sha256[2:4]}/{sha256}_{filename}`
3. If exists: Skip download, reference existing file
4. If not exists: Download and store

**Example:**

```python
# Package: nginx-1.20.2-1.el9.x86_64.rpm
sha256 = "f256abcdef0123456789abcdef0123456789abcdef0123456789abcdef789"

# Storage path
pool_path = f"pool/f2/56/f256abc...def789_nginx-1.20.2-1.el9.x86_64.rpm"

# Check existence
if pool_path.exists():
    print("Package already in pool, skipping download")
else:
    download_package(url, pool_path)
```

### Cross-Repository Deduplication

Identical packages across repositories are stored once:

```
Repository A: nginx-1.20.2-1.el9.x86_64.rpm (SHA256: f256abc...)
Repository B: nginx-1.20.2-1.el9.x86_64.rpm (SHA256: f256abc...)
Repository C: nginx-1.20.2-1.el9.x86_64.rpm (SHA256: f256abc...)

Pool storage: 1 copy (f2/56/f256abc...rpm)
Database: 3 repository associations
```

**Typical deduplication rates:**
- RHEL 9.x minor versions: 60-80% deduplication
- RHEL + CentOS + Rocky: 70-85% deduplication
- RHEL BaseOS + AppStream: 5-10% deduplication

## Database Integration

### Package Model

```python
class Package:
    sha256: str           # Primary key (content address)
    filename: str         # Original filename
    size: int             # File size in bytes

    name: str             # Package name (e.g., "nginx")
    version: str          # Version
    release: str          # Release
    architecture: str     # arch (e.g., "x86_64")

    # Many-to-many with repositories
    repositories: List[Repository]
```

### Junction Table

Packages can belong to multiple repositories:

```
repository_packages (junction table)
├── repository_id: str
├── package_sha256: str
└── added_at: datetime
```

**Query examples:**

```python
# Find all packages in a repository
packages = repository.packages

# Find all repositories containing a package
repositories = package.repositories

# Check if package is in pool
package = session.query(Package).filter_by(sha256=sha256).first()
if package:
    print(f"Package in pool, used by {len(package.repositories)} repos")
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
# Create hardlink from pool to published directory
pool_path = "pool/f2/56/f256abc...rpm"
published_path = "published/rhel9-baseos/latest/Packages/nginx-1.20.2-1.el9.x86_64.rpm"

# Both paths point to same inode (same physical data)
published_path.hardlink_to(pool_path)

# Deleting one doesn't affect the other
# Data is deleted only when all hardlinks are removed
```

## Storage Operations

### Add Package

```python
def add_package(url: str, sha256: str, filename: str) -> Path:
    """Add package to pool."""
    # Compute storage path
    dir1 = sha256[:2]
    dir2 = sha256[2:4]
    pool_path = pool_dir / dir1 / dir2 / f"{sha256}_{filename}"

    # Check if exists
    if pool_path.exists():
        return pool_path  # Already in pool

    # Download and verify
    pool_path.parent.mkdir(parents=True, exist_ok=True)
    download_file(url, pool_path)
    verify_sha256(pool_path, sha256)

    return pool_path
```

### Create Hardlink

```python
def create_hardlink(sha256: str, filename: str, target_path: Path):
    """Create hardlink from pool to target."""
    # Find in pool
    pool_path = find_in_pool(sha256, filename)

    # Create parent directories
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # Create hardlink
    target_path.hardlink_to(pool_path)
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

```python
def cleanup_orphaned_files():
    """Remove files in pool not referenced by database."""
    # Get all SHA256s in database
    db_sha256s = set(session.query(Package.sha256).all())

    # Scan pool
    for pool_file in pool_dir.rglob("*"):
        if pool_file.is_file():
            sha256 = pool_file.name.split("_")[0]
            if sha256 not in db_sha256s:
                print(f"Orphaned: {pool_file}")
                pool_file.unlink()  # Delete
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
