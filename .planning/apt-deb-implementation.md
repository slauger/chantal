# APT/DEB Repository Support - Implementation Plan

**Status:** Planning
**Created:** 2026-01-11
**Estimated Effort:** ~8 days
**Priority:** High

## Overview

Implementation of APT/Debian repository mirror support with architectural improvements:

1. **Phase 0: Plugin Structure Refactoring** - Consistent structure for all plugins
2. **Phase 1: Central Download Manager** - Abstraction layer for downloads
3. **Phase 2: APT/DEB Implementation** - Mirror mode support
4. **Phase 3: Integration** - Migrate RPM to DownloadManager

## Dependencies

- Issue #24: Plugin Structure Refactoring (Phase 0)
- Issue #25: Central Download Manager (Phase 1)
- Issue #1: APT/DEB Support (Phase 2+3) - depends on #24, #25

## Phase 0: Plugin Structure Refactoring (~2 days)

### Problem

Current plugin structure is inconsistent and some files are too large:
- `rpm_sync.py`: 1462 lines, 23 methods - TOO LARGE
- `rpm/__init__.py`: 794 lines, 14 methods - borderline
- `apk/__init__.py`: 578 lines (Syncer + Publisher mixed)
- `helm/__init__.py`: 493 lines (Syncer + Publisher mixed)

### Solution: Consistent Structure

```
plugins/
├── rpm/
│   ├── models.py           # RpmMetadata (unchanged)
│   ├── updateinfo.py       # UpdateInfo handling (unchanged)
│   ├── parsers.py          # NEW: XML/Metadata parsing (~400 lines)
│   ├── filters.py          # NEW: Filter logic (~400 lines)
│   ├── sync.py             # NEW: RpmSyncPlugin main logic (~300 lines)
│   └── publisher.py        # RENAMED: __init__.py → publisher.py
│
├── apt/
│   ├── models.py           # NEW: DebMetadata
│   ├── parsers.py          # NEW: Release/Packages parsing
│   ├── sync.py             # NEW: AptSyncPlugin
│   └── publisher.py        # NEW: AptPublisher
│
├── apk/
│   ├── models.py           # ApkMetadata (unchanged)
│   ├── sync.py             # SPLIT: ApkSyncer from __init__.py
│   └── publisher.py        # SPLIT: ApkPublisher from __init__.py
│
└── helm/
    ├── models.py           # HelmMetadata (unchanged)
    ├── sync.py             # SPLIT: HelmSyncer from __init__.py
    └── publisher.py        # SPLIT: HelmPublisher from __init__.py
```

### Refactoring Tasks

**Day 1: RPM Refactoring**
- [ ] Create `rpm/parsers.py` - Extract parsing methods:
  - `_fetch_repomd_xml()`
  - `_parse_primary_xml()`
  - `_parse_treeinfo()`
  - `_extract_primary_location()`
  - `_extract_all_metadata()`
- [ ] Create `rpm/filters.py` - Extract filter methods:
  - `_apply_filters()`
  - `_check_generic_metadata_filters()`
  - `_check_rpm_filters()`
  - `_check_list_filter()`
  - `_check_pattern_filters()`
  - `_apply_post_processing()`
  - `_keep_only_latest_versions()`
- [ ] Create `rpm/sync.py` - Main RpmSyncPlugin:
  - `sync_repository()`
  - `check_updates()`
  - `_download_metadata_file()`
  - `_download_package()`
  - `_download_installer_file()`
  - Import parsers and filters
- [ ] Rename `rpm/__init__.py` → `rpm/publisher.py`
- [ ] Update imports in:
  - `src/chantal/cli/main.py`
  - All test files
- [ ] Run tests (125 tests must pass)

**Day 2: APK/Helm Refactoring**
- [ ] Split `apk/__init__.py`:
  - `apk/sync.py` - ApkSyncer
  - `apk/publisher.py` - ApkPublisher
- [ ] Split `helm/__init__.py`:
  - `helm/sync.py` - HelmSyncer
  - `helm/publisher.py` - HelmPublisher
- [ ] Update imports in CLI/tests
- [ ] Run tests (all must pass)

### Benefits

- Smaller, more maintainable files (~300-400 lines each)
- Clear separation of concerns (parsing, filtering, sync, publish)
- Consistent structure across all plugins
- Easier to add new plugins (APT, PyPI, NPM, etc.)

## Phase 1: Central Download Manager (~1 day)

### Problem

Each plugin currently implements its own download logic:
- Duplicated code (requests.Session setup, auth, SSL)
- Hard to add new download backends (aria2c, curl, wget)
- No consistent retry/timeout handling

### Solution: Download Abstraction Layer

**New file: `src/chantal/core/downloader.py`**

```python
from pathlib import Path
from typing import List, Optional
import requests
from dataclasses import dataclass

from chantal.core.config import RepositoryConfig

@dataclass
class DownloadTask:
    """Single file download task."""
    url: str
    dest: Path
    expected_sha256: Optional[str] = None

class DownloadBackend:
    """Abstract download backend."""

    def download_file(self, url: str, dest: Path,
                     expected_sha256: Optional[str] = None) -> Path:
        raise NotImplementedError

    def download_batch(self, tasks: List[DownloadTask]) -> List[Path]:
        raise NotImplementedError

class RequestsBackend(DownloadBackend):
    """Download backend using requests library."""

    def __init__(self, config: RepositoryConfig):
        self.session = requests.Session()
        # Setup auth/SSL from config (current logic from rpm_sync.py)

    def download_file(self, url: str, dest: Path,
                     expected_sha256: Optional[str] = None) -> Path:
        # Download with SHA256 verification

    def download_batch(self, tasks: List[DownloadTask]) -> List[Path]:
        # Sequential downloads (MVP)
        # Later: parallel with ThreadPoolExecutor

class Aria2cBackend(DownloadBackend):
    """Download backend using aria2c (future)."""
    # High-performance parallel downloads

class DownloadManager:
    """Central download manager for all repository types."""

    def __init__(self, config: RepositoryConfig, backend: str = "requests"):
        self.config = config
        self.backend = self._init_backend(backend)

    def _init_backend(self, backend: str) -> DownloadBackend:
        if backend == "requests":
            return RequestsBackend(self.config)
        elif backend == "aria2c":
            return Aria2cBackend(self.config)
        raise ValueError(f"Unknown backend: {backend}")

    def download_file(self, url: str, dest: Path, **kwargs) -> Path:
        return self.backend.download_file(url, dest, **kwargs)

    def download_batch(self, tasks: List[DownloadTask]) -> List[Path]:
        return self.backend.download_batch(tasks)
```

### Configuration

**Update `src/chantal/core/config.py`:**

```python
class DownloadConfig(BaseModel):
    """Generic download configuration."""
    backend: str = "requests"  # requests, aria2c, curl, wget
    parallel: int = 1          # Parallel downloads (backend-dependent)
    timeout: int = 300
    retry_attempts: int = 3
    verify_checksum: bool = True

class GlobalConfig(BaseModel):
    # ... existing fields ...
    download: Optional[DownloadConfig] = None  # Global download settings
```

**Example config:**

```yaml
# Global download settings
download:
  backend: requests
  parallel: 20
  timeout: 300
  retry_attempts: 3

repositories:
  - id: ubuntu-jammy
    type: apt
    # ... uses global download config
```

### Usage in Plugins

```python
class AptSyncPlugin:
    def __init__(self, config: RepositoryConfig, storage: StorageManager):
        self.config = config
        self.storage = storage
        self.downloader = DownloadManager(config)  # Centralized!

    def sync_repository(self, ...):
        # Download InRelease
        release_file = self.downloader.download_file(
            url=f"{feed}/dists/{dist}/InRelease",
            dest=temp_dir / "InRelease"
        )

        # Download batch of .deb files
        tasks = [DownloadTask(url=pkg_url, dest=dest, expected_sha256=sha256)
                 for pkg in packages]
        self.downloader.download_batch(tasks)
```

### Benefits

- Single place for download logic
- Easy to add new backends (aria2c for performance)
- Consistent retry/timeout/auth handling
- No plugin changes needed to add new backends

## Phase 2: APT/DEB Implementation (~4 days)

### Goals

- Mirror mode: 1:1 metadata copy with preserved GPG signatures
- Support Ubuntu, Debian, and derivatives
- Metadata files stored as RepositoryFile
- Packages stored as ContentItem with DebMetadata

### Design Decisions (Finalized)

1. **Parsing**: Self-implemented (no python-debian) - RFC822 format is simple
2. **GPG Verification**: `verify: true` with `fail_on_invalid: false` (verify + warn, don't block)
3. **by-hash Support**: Copy if present, don't generate
4. **Contents-*.gz**: Copy in mirror mode (like all metadata)
5. **Source Packages**: `include_source_packages: true/false` option

### Configuration Schema

```python
# src/chantal/core/config.py

class AptGpgConfig(BaseModel):
    """APT GPG verification configuration."""
    verify: bool = True
    fail_on_invalid: bool = False
    trusted_keys: Optional[List[str]] = None  # Paths to GPG key files

class AptConfig(BaseModel):
    """APT/Debian-specific configuration."""
    distribution: str              # jammy, bookworm, etc.
    components: List[str]          # main, restricted, universe, multiverse
    architectures: List[str]       # amd64, arm64, i386, all
    include_source_packages: bool = True
    gpg: Optional[AptGpgConfig] = None

class RepositoryConfig(BaseModel):
    # ... existing fields ...
    apt: Optional[AptConfig] = None
```

### Example Configurations

**Ubuntu Jammy:**

```yaml
repositories:
  - id: ubuntu-jammy-main
    name: Ubuntu 22.04 LTS (Jammy) - Main
    type: apt
    feed: http://archive.ubuntu.com/ubuntu/
    mode: mirror  # 1:1 copy, GPG signatures preserved

    apt:
      distribution: jammy
      components: [main]
      architectures: [amd64, arm64]
      include_source_packages: true

      gpg:
        verify: true              # Verify signatures
        fail_on_invalid: false    # Warn but don't fail (MVP)
```

**Debian Bookworm:**

```yaml
repositories:
  - id: debian-bookworm-main
    name: Debian 12 (Bookworm) - Main
    type: apt
    feed: http://deb.debian.org/debian/
    mode: mirror

    apt:
      distribution: bookworm
      components: [main, contrib, non-free]
      architectures: [amd64]
      include_source_packages: false  # Binary only
```

### Implementation Files

**Day 1: Models + Parsers**

`src/chantal/plugins/apt/models.py`:

```python
from typing import Optional, List
from pydantic import BaseModel, Field

class DebMetadata(BaseModel):
    """Metadata schema for DEB packages in ContentItem.content_metadata."""

    # DEB-specific identifiers
    architecture: str      # amd64, arm64, i386, all, source
    component: str         # main, restricted, universe, multiverse

    # Package info
    priority: Optional[str] = None  # required, important, standard, optional
    section: Optional[str] = None   # admin, devel, libs, net, etc.
    maintainer: Optional[str] = None
    description: Optional[str] = None
    homepage: Optional[str] = None

    # Dependencies (stored as strings for simplicity in MVP)
    depends: Optional[List[str]] = None
    recommends: Optional[List[str]] = None
    suggests: Optional[List[str]] = None
    conflicts: Optional[List[str]] = None
    breaks: Optional[List[str]] = None
    replaces: Optional[List[str]] = None
    provides: Optional[List[str]] = None

    class Config:
        extra = "allow"  # Forward compatibility
```

`src/chantal/plugins/apt/parsers.py`:

```python
def parse_release(content: str) -> dict:
    """Parse InRelease or Release file (RFC822 format)."""
    # Extract: Suite, Codename, Architectures, Components, SHA256 file list

def parse_packages(content: str) -> List[dict]:
    """Parse Packages file (RFC822 format)."""
    # Extract: Package, Version, Architecture, Filename, SHA256, Size, etc.

def parse_sources(content: str) -> List[dict]:
    """Parse Sources file for source packages."""

def verify_gpg_signature(content: str) -> bool:
    """Verify GPG signature on InRelease file (optional)."""
    # Use gpg command or python-gnupg
    # Return True/False, log warning if invalid
```

**Day 2-3: Sync Plugin**

`src/chantal/plugins/apt/sync.py`:

```python
class AptSyncPlugin:
    """Sync plugin for APT/Debian repositories."""

    def __init__(self, config: RepositoryConfig, storage: StorageManager):
        self.config = config
        self.storage = storage
        self.downloader = DownloadManager(config)

    def sync_repository(self, session: Session, repository: Repository) -> SyncResult:
        """Sync APT repository using 3-phase strategy."""

        # Phase 1: Release Metadata
        release_data = self._download_release()
        if self.config.apt.gpg.verify:
            if not verify_gpg_signature(release_data):
                if self.config.apt.gpg.fail_on_invalid:
                    raise ValueError("Invalid GPG signature")
                print("Warning: Invalid GPG signature")

        metadata = parse_release(release_data)

        # Phase 2: Package Indices
        indices = self._download_indices(metadata)
        packages = self._parse_indices(indices)

        # Phase 3: Package Download
        self._download_packages(session, repository, packages)

    def _download_release(self) -> str:
        """Download InRelease or Release + Release.gpg."""

    def _download_indices(self, metadata: dict) -> dict:
        """Download ALL metadata files (Packages.gz, Contents-*.gz, by-hash/, etc.)."""
        # Store as RepositoryFile in pool/files/

    def _parse_indices(self, indices: dict) -> List[dict]:
        """Parse Packages.gz to extract package list."""

    def _download_packages(self, session, repository, packages):
        """Download .deb files with SHA256 verification."""
        # Store as ContentItem in pool/content/
```

**Day 4: Publisher**

`src/chantal/plugins/apt/publisher.py`:

```python
class AptPublisher(PublisherPlugin):
    """Publisher for APT/Debian repositories."""

    def publish_repository(self, session, repository, config, target_path):
        """Publish APT repository with dists/ + pool/ structure."""

        # Get packages and metadata files
        packages = self._get_repository_packages(session, repository)
        metadata_files = repository.repository_files

        # Create dists/ structure
        self._publish_dists(target_path, metadata_files, config.apt)

        # Create pool/ structure
        self._publish_pool(target_path, packages, config.apt)

    def _publish_dists(self, target_path, metadata_files, apt_config):
        """Hardlink ALL metadata files to dists/ structure."""
        # InRelease, Release, Release.gpg
        # Packages.gz, Packages.xz
        # Sources.gz (if include_source_packages)
        # Contents-*.gz
        # by-hash/SHA256/* (if present)

    def _publish_pool(self, target_path, packages, apt_config):
        """Hardlink .deb files to pool/ structure."""
        # pool/main/n/nginx/nginx_1.20.1-1_amd64.deb
```

### Directory Structure

**Published APT repository:**

```
published/ubuntu-jammy-main/
├── dists/
│   └── jammy/
│       ├── InRelease               # Hardlink from pool/files/
│       ├── Release                 # Hardlink from pool/files/
│       ├── Release.gpg             # Hardlink from pool/files/
│       ├── main/
│       │   ├── binary-amd64/
│       │   │   ├── Packages        # Hardlink from pool/files/
│       │   │   ├── Packages.gz     # Hardlink
│       │   │   ├── Packages.xz     # Hardlink
│       │   │   └── by-hash/SHA256/...  # Hardlink (if present)
│       │   ├── source/
│       │   │   └── Sources.gz      # Hardlink
│       │   └── Contents-amd64.gz   # Hardlink
└── pool/
    └── main/n/nginx/
        └── nginx_1.20.1-1_amd64.deb  # Hardlink from pool/content/
```

### Sync Workflow (3-Phase Strategy - from apt-mirror)

**Phase 1: Release Metadata**
1. Download `dists/$DIST/InRelease` or `Release` + `Release.gpg`
2. GPG verify (optional, warn if invalid)
3. Parse → Components, Architectures, File list with checksums

**Phase 2: Package Indices**
1. Download `Packages.gz` for each Component/Architecture
2. Download `Sources.gz` (if `include_source_packages: true`)
3. Download `Contents-*.gz` and ALL other metadata files listed in Release
4. Store all as RepositoryFile in `pool/files/`
5. Parse Packages → Extract package list

**Phase 3: Package Download**
1. Download .deb files (via DownloadManager)
2. SHA256 verification against Packages.gz checksums
3. Store in `pool/content/` via `StorageManager.add_package()`
4. Deduplication automatic via content-addressing
5. Link to Repository via `repository_content_items` table

### Testing

**Unit Tests (~15 tests):**

`tests/test_apt_models.py`:
- DebMetadata validation
- JSON serialization/deserialization

`tests/test_apt_parsers.py`:
- parse_release() with sample Release file
- parse_packages() with sample Packages file
- parse_sources() with sample Sources file
- verify_gpg_signature() (mock)

`tests/test_apt_sync.py`:
- Sync workflow (mocked downloads)
- Error handling
- Filter logic

`tests/test_apt_publisher.py`:
- Publishing logic
- Directory structure
- Hardlink creation

**Integration Test (manual):**

```bash
# 1. Configure Ubuntu Jammy test repo
cat > .dev/conf.d/ubuntu-test.yaml <<EOF
repositories:
  - id: ubuntu-jammy-test
    name: Ubuntu Jammy Test
    type: apt
    feed: http://archive.ubuntu.com/ubuntu/
    mode: mirror
    apt:
      distribution: jammy
      components: [main]
      architectures: [amd64]
      include_source_packages: false
EOF

# 2. Sync (~1500 packages)
chantal repo sync --repo-id ubuntu-jammy-test

# 3. Create snapshot
chantal snapshot create --repo-id ubuntu-jammy-test --name test-snap

# 4. Publish snapshot
chantal snapshot publish --snapshot-id test-snap

# 5. APT client test
echo "deb [trusted=yes] file:///path/to/published/ubuntu-jammy-test jammy main" \
  > /etc/apt/sources.list.d/chantal-test.list

apt update
apt install nginx  # Should work!
```

## Phase 3: RPM Migration (~1 day)

### Tasks

- [ ] Update `rpm/sync.py` to use DownloadManager instead of requests.Session
- [ ] Remove old download code
- [ ] Update tests
- [ ] Verify all 125+ tests still pass

### Code Changes

**Before:**

```python
class RpmSyncPlugin:
    def __init__(self, config, storage):
        self.session = requests.Session()
        # Setup auth/SSL...

    def _download_package(self, url, dest):
        response = self.session.get(url)
        # ...
```

**After:**

```python
class RpmSyncPlugin:
    def __init__(self, config, storage):
        self.downloader = DownloadManager(config)

    def _download_package(self, url, dest, expected_sha256):
        return self.downloader.download_file(url, dest, expected_sha256)
```

## Timeline

**Total: ~8 days**

- **Day 1-2**: Phase 0 - Plugin Refactoring
  - Day 1: RPM refactoring (parsers.py, filters.py, sync.py, publisher.py)
  - Day 2: APK/Helm refactoring

- **Day 3**: Phase 1 - DownloadManager
  - Implement downloader.py with RequestsBackend
  - Add DownloadConfig to config.py

- **Day 4-7**: Phase 2 - APT Implementation
  - Day 4: models.py + parsers.py + tests
  - Day 5-6: sync.py + tests
  - Day 7: publisher.py + integration test

- **Day 8**: Phase 3 - RPM Migration
  - Update RPM to use DownloadManager
  - Full test suite

## Success Criteria

- [ ] All 125+ existing tests pass after refactoring
- [ ] Ubuntu Jammy main/amd64 fully syncable (~1500 packages)
- [ ] APT client can `apt update` + `apt install` successfully
- [ ] GPG signatures preserved in mirror mode
- [ ] Deduplication works (second sync skips existing packages)
- [ ] Snapshots can be created and published
- [ ] Consistent plugin structure for future extensions
- [ ] Central DownloadManager ready for aria2c backend

## Future Enhancements (Post-MVP)

- [ ] APT filtered mode (metadata regeneration)
- [ ] GPG signing support for regenerated repos
- [ ] aria2c backend for high-performance downloads
- [ ] Parallel package downloads
- [ ] Contents-*.gz generation for filtered repos
- [ ] by-hash generation
- [ ] Support for more Debian derivatives (Raspbian, etc.)

## References

- Debian Repository Format: https://wiki.debian.org/DebianRepository/Format
- APT SecureApt: https://wiki.debian.org/SecureApt
- apt-mirror: https://github.com/apt-mirror/apt-mirror (reference implementation)
- aptly: https://github.com/aptly-dev/aptly (architecture inspiration)
- Issue #1: APT/DEB Repository Support
- Issue #24: Plugin Structure Refactoring
- Issue #25: Central Download Manager
