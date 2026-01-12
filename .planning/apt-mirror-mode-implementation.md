# APT/DEB Mirror Mode Implementation Plan

**Status:** In Progress
**Created:** 2026-01-11
**GitHub Issues:**
- #1 (APT/DEB Support - Main implementation)
- #3 (Example configs for Debian/Ubuntu)

**Estimated Effort:** ~3-4 days (Mirror Mode only, no filtering)
**Priority:** High

---

## Overview

Implementation of APT/Debian repository **mirror mode** support:
- **Mirror Mode Only**: 1:1 copy of all metadata files
- **GPG Signatures Preserved**: No regeneration, no signing
- **No Filtering**: Complete repository mirror (filtering is separate issue for later)
- **Deduplication**: Via content-addressed storage (SHA256)

**Prerequisites (COMPLETED):**
- ✅ Phase 0: Plugin Structure Refactoring (Issue #24)
- ✅ Phase 1: Central Download Manager (Issue #25)

---

## Design Decisions

### What We Build (Mirror Mode)
1. ✅ Download ALL metadata files from Release
2. ✅ Store metadata as RepositoryFile (pool/files/)
3. ✅ Download .deb packages
4. ✅ Store packages as ContentItem (pool/content/)
5. ✅ Preserve GPG signatures (InRelease, Release.gpg)
6. ✅ Hardlink-based publishing (zero-copy)

### What We DON'T Build (Deferred to Future)
1. ❌ Filtered mode (regenerate metadata for subset)
2. ❌ GPG signing (sign regenerated metadata)
3. ❌ Contents-*.gz generation
4. ❌ by-hash generation
5. ❌ Source package building/verification

### GPG Verification Strategy
- **Parse GPG signatures**: Yes (extract info from InRelease)
- **Verify signatures**: Nice to have (python-gnupg if available)
- **Fail on invalid**: No (warn only)
- **Sign metadata**: No (mirror mode = preserve upstream signatures)

---

## Phase Breakdown

### Phase 1: Foundation (Day 1) - Models + Config + Parsers

**Goal:** Create data structures and parsing logic

**Files to Create:**
```
src/chantal/plugins/apt/
├── __init__.py (empty)
├── models.py (DebMetadata model)
└── parsers.py (RFC822 parsing)

tests/
├── test_apt_models.py (~5 tests)
└── test_apt_parsers.py (~8 tests)
```

**Tasks:**

#### 1.1 APT Configuration Schema
**File:** `src/chantal/core/config.py`

Add APT-specific config:
```python
class AptConfig(BaseModel):
    """APT/Debian-specific configuration."""
    distribution: str              # jammy, bookworm, etc.
    components: list[str]          # main, restricted, universe, multiverse
    architectures: list[str]       # amd64, arm64, i386, all
    include_source_packages: bool = True

class RepositoryConfig(BaseModel):
    # ... existing fields ...
    apt: AptConfig | None = None
```

**No GPG config needed** (mirror mode preserves signatures as-is)

#### 1.2 DEB Metadata Model
**File:** `src/chantal/plugins/apt/models.py`

```python
from pydantic import BaseModel

class DebMetadata(BaseModel):
    """Metadata schema for DEB packages in ContentItem.content_metadata."""

    # DEB-specific identifiers
    architecture: str      # amd64, arm64, i386, all, source
    component: str         # main, restricted, universe, multiverse

    # Package info
    priority: str | None = None      # required, important, standard, optional
    section: str | None = None       # admin, devel, libs, net, etc.
    maintainer: str | None = None
    description: str | None = None
    homepage: str | None = None

    # Dependencies (stored as strings for MVP)
    depends: list[str] | None = None
    recommends: list[str] | None = None
    suggests: list[str] | None = None
    conflicts: list[str] | None = None
    breaks: list[str] | None = None
    replaces: list[str] | None = None
    provides: list[str] | None = None

    class Config:
        extra = "allow"  # Forward compatibility
```

#### 1.3 RFC822 Parsers
**File:** `src/chantal/plugins/apt/parsers.py`

```python
def parse_release(content: str) -> dict:
    """Parse InRelease or Release file (RFC822 format).

    Returns:
        {
            'suite': 'jammy',
            'codename': 'jammy',
            'architectures': ['amd64', 'arm64', ...],
            'components': ['main', 'restricted', ...],
            'files': [
                {'sha256': '...', 'size': 12345, 'path': 'main/binary-amd64/Packages.gz'},
                ...
            ]
        }
    """

def parse_packages(content: str) -> list[dict]:
    """Parse Packages file (RFC822 paragraphs).

    Returns:
        [
            {
                'package': 'nginx',
                'version': '1.20.1-1',
                'architecture': 'amd64',
                'filename': 'pool/main/n/nginx/nginx_1.20.1-1_amd64.deb',
                'sha256': '...',
                'size': 12345,
                'section': 'httpd',
                'priority': 'optional',
                'depends': ['libc6', ...],
                ...
            },
            ...
        ]
    """

def parse_sources(content: str) -> list[dict]:
    """Parse Sources file for source packages."""

def extract_gpg_info(inrelease_content: str) -> dict:
    """Extract GPG signature info from InRelease file (metadata only).

    Returns:
        {
            'signed': True,
            'key_id': 'ABCD1234' or None,
            'valid': None  # Not verified in mirror mode
        }
    """
```

#### 1.4 Tests
**Files:** `tests/test_apt_models.py`, `tests/test_apt_parsers.py`

- DebMetadata validation (~5 tests)
- parse_release() with sample data (~3 tests)
- parse_packages() with sample data (~3 tests)
- parse_sources() with sample data (~2 tests)

**Success Criteria for Phase 1:**
- ✅ AptConfig validates Ubuntu/Debian configs
- ✅ DebMetadata handles all common fields
- ✅ Parsers handle real Ubuntu/Debian metadata
- ✅ ~15 new tests passing
- ✅ All 125 existing tests still pass

---

### Phase 2: Sync Implementation (Day 2-3) - Download + Storage

**Goal:** Implement actual repository syncing

**Files to Create:**
```
src/chantal/plugins/apt/sync.py
tests/test_apt_sync.py (~10 tests)
```

#### 2.1 Sync Plugin
**File:** `src/chantal/plugins/apt/sync.py`

```python
class AptSyncPlugin:
    """Sync plugin for APT/Debian repositories (Mirror Mode)."""

    def __init__(self, storage: StorageManager, config: RepositoryConfig,
                 proxy_config=None, ssl_config=None):
        self.storage = storage
        self.config = config
        self.downloader = DownloadManager(config, proxy_config=proxy_config,
                                          ssl_config=ssl_config)

    def sync_repository(self, session: Session, repository: Repository,
                       config: RepositoryConfig) -> dict:
        """Sync APT repository using 3-phase strategy.

        Phase 1: Release Metadata
        Phase 2: Package Indices + All Metadata Files
        Phase 3: Package Download

        Returns:
            {
                'packages_added': 123,
                'packages_updated': 5,
                'packages_skipped': 890,
                'bytes_downloaded': 12345678,
                'metadata_files': 25
            }
        """
```

**Workflow:**

**Phase 1: Release Metadata**
```python
def _download_release_metadata(self) -> dict:
    """Download InRelease or Release + Release.gpg.

    Try InRelease first (signed), fall back to Release + Release.gpg.
    Extract GPG info for logging (verify=nice to have, don't fail).
    """

    # Try InRelease first
    inrelease_url = f"{feed}/dists/{dist}/InRelease"
    # Fall back to Release + Release.gpg

    # Store as RepositoryFile
    self.storage.add_repository_file(...)

    # Parse metadata
    return parse_release(content)
```

**Phase 2: Package Indices + Metadata Files**
```python
def _download_all_metadata(self, release_metadata: dict) -> dict:
    """Download ALL files listed in Release (Mirror Mode).

    This includes:
    - Packages.gz, Packages.xz (per component/arch)
    - Sources.gz (if include_source_packages)
    - Contents-*.gz
    - by-hash/SHA256/* (if present)
    - i18n/Translation-*.gz
    - dep11/* (AppStream metadata)
    - All other files in Release

    Store ALL as RepositoryFile.
    """

    for file_info in release_metadata['files']:
        # Download with SHA256 verification
        path = self.downloader.download_file(
            url=f"{feed}/dists/{dist}/{file_info['path']}",
            dest=temp_file,
            expected_sha256=file_info['sha256']
        )

        # Store as RepositoryFile
        self.storage.add_repository_file(
            session=session,
            repository=repository,
            file_path=file_info['path'],  # main/binary-amd64/Packages.gz
            source_path=path,
            file_type='packages_index',  # or 'sources_index', 'contents', etc.
            metadata={'component': 'main', 'architecture': 'amd64'}
        )

    # Parse Packages.gz for package list
    packages_data = self._parse_all_packages_files(...)
    return packages_data
```

**Phase 3: Package Download**
```python
def _download_packages(self, session, repository, packages_data):
    """Download .deb files and store as ContentItem.

    Use DownloadManager.download_batch() for efficiency.
    """

    for pkg_info in packages_data:
        # Check if already in pool (deduplication)
        existing = self.storage.get_content_by_sha256(pkg_info['sha256'])
        if existing:
            # Link to repository
            continue

        # Download .deb file
        deb_url = f"{feed}/{pkg_info['filename']}"
        local_path = self.downloader.download_file(
            url=deb_url,
            dest=temp_file,
            expected_sha256=pkg_info['sha256']
        )

        # Create DebMetadata
        metadata = DebMetadata(
            architecture=pkg_info['architecture'],
            component=pkg_info.get('section', '').split('/')[0] or 'main',
            priority=pkg_info.get('priority'),
            section=pkg_info.get('section'),
            depends=pkg_info.get('depends', '').split(', ') if pkg_info.get('depends') else None,
            # ... other fields
        )

        # Store as ContentItem
        self.storage.add_content(
            session=session,
            repository=repository,
            name=pkg_info['package'],
            version=pkg_info['version'],
            content_type='deb',
            source_path=local_path,
            content_metadata=metadata.model_dump(),
            size_bytes=pkg_info['size']
        )
```

#### 2.2 Tests
**File:** `tests/test_apt_sync.py`

- Sync workflow with mocked downloads (~5 tests)
- Error handling (network errors, checksum mismatch) (~3 tests)
- Deduplication logic (~2 tests)

**Success Criteria for Phase 2:**
- ✅ Can sync Ubuntu Jammy main/amd64 repository
- ✅ All metadata files stored as RepositoryFile
- ✅ All .deb files stored as ContentItem
- ✅ Deduplication works (second sync skips existing)
- ✅ ~10 new tests passing
- ✅ All existing tests still pass

---

### Phase 3: Publisher (Day 3) - Publishing Logic

**Goal:** Publish mirrored repositories

**Files to Create:**
```
src/chantal/plugins/apt/publisher.py
tests/test_apt_publisher.py (~8 tests)
```

#### 3.1 Publisher Plugin
**File:** `src/chantal/plugins/apt/publisher.py`

```python
class AptPublisher(PublisherPlugin):
    """Publisher for APT/Debian repositories (Mirror Mode)."""

    def publish_repository(self, session, repository, config, target_path):
        """Publish APT repository with dists/ + pool/ structure.

        Mirror mode: Hardlink ALL metadata files as-is (GPG preserved).
        """

        # Get packages and metadata files
        packages = self._get_repository_packages(session, repository)
        metadata_files = repository.repository_files

        # Create dists/ structure (hardlink metadata)
        self._publish_dists(target_path, metadata_files, config.apt)

        # Create pool/ structure (hardlink .deb files)
        self._publish_pool(target_path, packages, config.apt)
```

**dists/ Publishing:**
```python
def _publish_dists(self, target_path, metadata_files, apt_config):
    """Hardlink ALL metadata files to dists/ structure.

    Mirror mode: Exact 1:1 copy, GPG signatures preserved.

    Structure:
        dists/jammy/
        ├── InRelease (hardlink from pool/files/)
        ├── Release (hardlink)
        ├── Release.gpg (hardlink)
        ├── main/
        │   ├── binary-amd64/
        │   │   ├── Packages (hardlink)
        │   │   ├── Packages.gz (hardlink)
        │   │   ├── Packages.xz (hardlink)
        │   │   └── by-hash/SHA256/... (hardlink)
        │   ├── source/
        │   │   └── Sources.gz (hardlink)
        │   └── Contents-amd64.gz (hardlink)
        └── ...
    """

    dist_path = target_path / "dists" / apt_config.distribution

    for repo_file in metadata_files:
        # Hardlink from pool/files/ to dists/
        source = Path(repo_file.pool_path)
        dest = dist_path / repo_file.file_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        source.hardlink_to(dest)
```

**pool/ Publishing:**
```python
def _publish_pool(self, target_path, packages, apt_config):
    """Hardlink .deb files to pool/ structure.

    Structure:
        pool/main/n/nginx/nginx_1.20.1-1_amd64.deb
    """

    for pkg in packages:
        # Extract pool path from original filename
        # Example: pool/main/n/nginx/nginx_1.20.1-1_amd64.deb
        pool_subpath = self._extract_pool_path(pkg)

        source = Path(pkg.pool_path)
        dest = target_path / pool_subpath
        dest.parent.mkdir(parents=True, exist_ok=True)
        source.hardlink_to(dest)
```

#### 3.2 Tests
**File:** `tests/test_apt_publisher.py`

- Publishing creates correct directory structure (~3 tests)
- Hardlinks work correctly (~2 tests)
- Multiple components/architectures (~3 tests)

**Success Criteria for Phase 3:**
- ✅ Publishing creates valid APT repository structure
- ✅ GPG signatures preserved (InRelease, Release.gpg)
- ✅ APT client can `apt update` successfully
- ✅ APT client can `apt install` packages
- ✅ ~8 new tests passing
- ✅ All existing tests still pass

---

### Phase 4: Integration + Examples (Day 4) - Config + Testing

**Goal:** Integration testing and example configurations

#### 4.1 Example Configurations (Issue #3)
**Files to Create:**
```
examples/configs/
├── ubuntu-jammy.yaml
├── ubuntu-focal.yaml
├── debian-bookworm.yaml
└── debian-bullseye.yaml
```

**Ubuntu Jammy Example:**
```yaml
# examples/configs/ubuntu-jammy.yaml
repositories:
  - id: ubuntu-jammy-main
    name: Ubuntu 22.04 LTS (Jammy Jellyfish) - Main
    type: apt
    feed: http://archive.ubuntu.com/ubuntu/
    mode: mirror
    enabled: true

    apt:
      distribution: jammy
      components: [main]
      architectures: [amd64]
      include_source_packages: false  # Binary only for smaller mirror

  - id: ubuntu-jammy-full
    name: Ubuntu 22.04 LTS (Jammy) - Full Mirror
    type: apt
    feed: http://archive.ubuntu.com/ubuntu/
    mode: mirror
    enabled: false  # Disabled by default (large)

    apt:
      distribution: jammy
      components: [main, restricted, universe, multiverse]
      architectures: [amd64, arm64]
      include_source_packages: true
```

**Debian Bookworm Example:**
```yaml
# examples/configs/debian-bookworm.yaml
repositories:
  - id: debian-bookworm-main
    name: Debian 12 (Bookworm) - Main
    type: apt
    feed: http://deb.debian.org/debian/
    mode: mirror
    enabled: true

    apt:
      distribution: bookworm
      components: [main]
      architectures: [amd64]
      include_source_packages: false

  - id: debian-bookworm-full
    name: Debian 12 (Bookworm) - Full
    type: apt
    feed: http://deb.debian.org/debian/
    mode: mirror
    enabled: false

    apt:
      distribution: bookworm
      components: [main, contrib, non-free, non-free-firmware]
      architectures: [amd64]
      include_source_packages: true
```

#### 4.2 Integration Testing

**Manual Test 1: Ubuntu Jammy Minimal**
```bash
# Small test: nginx package only (~50 packages with deps)
cat > test-ubuntu-minimal.yaml <<EOF
repositories:
  - id: ubuntu-jammy-test
    type: apt
    feed: http://archive.ubuntu.com/ubuntu/
    mode: mirror
    apt:
      distribution: jammy
      components: [main]
      architectures: [amd64]
      include_source_packages: false
EOF

chantal repo sync --repo-id ubuntu-jammy-test
chantal snapshot create --repo-id ubuntu-jammy-test --name test-snap
chantal publish snapshot --snapshot test-snap --repo-id ubuntu-jammy-test
```

**Manual Test 2: APT Client Verification**
```bash
# Test with real APT client
echo "deb [trusted=yes] file:///path/to/published/ubuntu-jammy-test jammy main" \
  > /etc/apt/sources.list.d/chantal-test.list

apt update  # Should work!
apt install nginx  # Should work!
```

**Success Criteria for Phase 4:**
- ✅ Example configs for 4 distributions
- ✅ Ubuntu Jammy main/amd64 fully syncable
- ✅ Debian Bookworm main/amd64 fully syncable
- ✅ APT client can update and install packages
- ✅ Issue #3 can be closed

---

## Final Checklist

### Functionality
- [ ] APT repository syncing works (Ubuntu, Debian)
- [ ] All metadata files stored as RepositoryFile
- [ ] All .deb files stored as ContentItem
- [ ] GPG signatures preserved (not verified, but preserved)
- [ ] Deduplication works (content-addressed storage)
- [ ] Publishing creates valid APT repository
- [ ] APT client can `apt update` and `apt install`

### Testing
- [ ] ~40 new tests for APT (models, parsers, sync, publisher)
- [ ] All 125+ existing tests still pass
- [ ] Manual integration test with Ubuntu Jammy
- [ ] Manual integration test with Debian Bookworm

### Documentation
- [ ] Example configs for Ubuntu (Jammy, Focal)
- [ ] Example configs for Debian (Bookworm, Bullseye)
- [ ] Update README.md with APT support
- [ ] Update ROADMAP.md (Milestone 7 complete)

### Issues
- [ ] Update Issue #1 during implementation
- [ ] Close Issue #1 when complete
- [ ] Close Issue #3 after example configs
- [ ] Create new Issue for Filtered Mode (future)

---

## Timeline

**Day 1: Foundation**
- Morning: AptConfig + DebMetadata model
- Afternoon: RFC822 parsers + tests
- **Deliverable:** ~15 tests passing

**Day 2: Sync Implementation (Part 1)**
- Morning: AptSyncPlugin structure
- Afternoon: Phase 1+2 (Release + Metadata download)
- **Deliverable:** Metadata syncing works

**Day 3: Sync + Publisher**
- Morning: Phase 3 (Package download) + tests
- Afternoon: AptPublisher + tests
- **Deliverable:** End-to-end sync + publish works

**Day 4: Integration + Examples**
- Morning: Integration testing
- Afternoon: Example configs + documentation
- **Deliverable:** Issue #1 and #3 closed

**Total: 4 days**

---

## Success Criteria

### Must Have
1. ✅ Mirror Ubuntu Jammy main/amd64
2. ✅ Mirror Debian Bookworm main/amd64
3. ✅ GPG signatures preserved
4. ✅ APT client works (update + install)
5. ✅ All tests passing (~165 total)
6. ✅ Example configs for 4 distros

### Nice to Have
1. ⚠️ GPG signature verification (warn if invalid, don't fail)
2. ⚠️ Support for all Ubuntu/Debian derivatives
3. ⚠️ Progress bars for large downloads

### Future (Separate Issue)
1. ❌ Filtered mode (subset of packages)
2. ❌ Metadata regeneration
3. ❌ GPG signing (for filtered repos)
4. ❌ Contents-*.gz generation
5. ❌ by-hash generation

---

## References

- Debian Repository Format: https://wiki.debian.org/DebianRepository/Format
- APT SecureApt: https://wiki.debian.org/SecureApt
- apt-mirror: https://github.com/apt-mirror/apt-mirror (reference)
- Issue #1: APT/DEB Repository Support
- Issue #3: Example Configurations
- Issue #24: Plugin Structure Refactoring (DONE)
- Issue #25: Central Download Manager (DONE)
