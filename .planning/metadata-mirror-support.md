# Complete Metadata & Mirror Support - Master Plan

**Status:** Planning
**Created:** 2026-01-11
**Owner:** Architecture Team
**Related Issues:** #12 (updateinfo), #11 (SUSE)

---

## Problem Statement

**Current Limitations:**
- ❌ RPM: Only syncs/publishes `primary.xml.gz` (package list only)
- ❌ No security advisory/errata support (Issue #12)
- ❌ No true 1:1 mirror mode (metadata always regenerated, signatures lost)
- ❌ No kickstart/installer file support (USP vs reposync!)
- ❌ Missing metadata: updateinfo, filelists, other, comps, modules
- ❌ APK/APT will have same issues when metadata is needed

**Impact:**
- Published repos incomplete (dnf/apt clients may fail)
- Security tools can't work (no updateinfo.xml)
- Can't create offline installation media (no kickstart files)
- Can't preserve original vendor signatures

---

## Solution Architecture

### Two Operating Modes

**Mode 1: Mirror (1:1 Copy)**
- All packages + all metadata + signatures
- Original files preserved in pool
- Publish via hardlinks (zero-copy)
- Original signatures valid
- No filters allowed
- Perfect for air-gapped mirrors

**Mode 2: Filtered (Current + Enhanced)**
- Apply filters to packages
- Parse important metadata (updateinfo → errata DB)
- Regenerate metadata from DB
- Support snapshots
- Can mix custom + upstream packages

### Core Architecture: `repository_file` Table

```sql
CREATE TABLE repository_file (
  id INTEGER PRIMARY KEY,
  repository_id INTEGER,      -- FK to repository

  -- Classification (NO ENUM - must be flexible for SUSE/future formats!)
  file_category TEXT,          -- "metadata" | "signature" | "kickstart" | "debian-installer"
  file_type TEXT,              -- "updateinfo" | "vmlinuz" | "susedata" | etc. (NO ENUM!)

  -- Storage (in universal pool)
  sha256 TEXT,                 -- Content hash (deduplication)
  pool_path TEXT,              -- "ab/cd/abc123_updateinfo.xml.gz"
  size_bytes INTEGER,

  -- Publishing
  original_path TEXT,          -- "repodata/xxx-updateinfo.xml.gz" (exact structure)

  -- Metadata (flexible JSON for type-specific data)
  metadata JSON,

  created_at DATETIME,
  updated_at DATETIME,

  UNIQUE(repository_id, original_path)
)
```

**Design Decisions:**
- ✅ `file_type` = STRING (not enum) - supports SUSE, future formats
- ✅ `file_category` specific values (kickstart vs debian-installer)
- ✅ Universal pool → deduplication across all files
- ✅ `original_path` preserves exact structure → publishing trivial
- ✅ JSON metadata → flexible per file type

**Example file_category Values:**
- `metadata` - Package indices (primary.xml, Packages.gz, APKINDEX)
- `signature` - GPG signatures, keys (.asc, .SIGN.*)
- `kickstart` - RPM Anaconda installer files (.treeinfo, vmlinuz, initrd, EFI/, isolinux/)
- `debian-installer` - APT debian-installer files (linux, initrd.gz)
- `netboot` - Generic PXE boot files
- `iso-content` - ISO image content

**Example file_type Values (flexible string, not enum!):**
- RPM: updateinfo, filelists, other, comps, modules, susedata, patterns, products
- APK: APKINDEX, description
- APT: Release, Packages, Contents, Translation, Sources
- Kickstart: treeinfo, vmlinuz, initrd, boot_iso, efi_boot, efi_file, isolinux_file
- Installer: kernel, initrd, pxelinux
- Signature: public_key, content_signature, release_gpg

### Pool Structure with Subdirectories

**Decision:** Use single pool with subdirectories (not separate pools)

**Rationale:**
- ✅ Single config path (simple)
- ✅ Deduplication across all content (vmlinuz can appear in multiple repos)
- ✅ Clear separation of content types
- ✅ Flexible for future additions
- ✅ Consistent with DB table names (ContentItem → content/, RepositoryFile → files/)

**Directory Structure:**
```
/var/lib/chantal/pool/
  content/                      ← ContentItem (packages: RPM, APK, DEB)
    ab/cd/abc123_nginx-1.20.rpm
    12/34/1234def_busybox-1.35.apk
    ef/gh/efgh456_python3.deb

  files/                        ← RepositoryFile (metadata, installer, signatures)
    56/78/5678abc_updateinfo.xml.gz
    9a/bc/9abcde_vmlinuz
    de/f0/def012_APKINDEX.tar.gz
    34/56/3456ab_.treeinfo
```

**pool_path in Database:**

ContentItem (packages):
```python
pool_path = "content/ab/cd/abc123_nginx-1.20.rpm"
```

RepositoryFile (metadata/installer):
```python
pool_path = "files/56/78/5678abc_updateinfo.xml.gz"
```

**Config (unchanged):**
```yaml
storage:
  base_path: /var/lib/chantal
  pool_path: /var/lib/chantal/pool    # Single path!
  published_path: /var/www/repos
  temp_path: /var/lib/chantal/tmp
```

**StorageManager Changes:**
```python
class StorageManager:
    def __init__(self, config: StorageConfig):
        self.pool_path = config.get_pool_path()
        self.content_pool = self.pool_path / "content"  # NEW
        self.file_pool = self.pool_path / "files"       # NEW

    def get_pool_path(self, sha256: str, filename: str, pool_type: str = "content") -> str:
        """Get relative pool path.

        Args:
            pool_type: "content" for packages, "files" for metadata/installer
        """
        level1 = sha256[:2]
        level2 = sha256[2:4]
        pool_filename = f"{sha256}_{filename}"
        return f"{pool_type}/{level1}/{level2}/{pool_filename}"

    def add_package(self, source_path, filename):
        """Add package to content/ pool."""
        pool_path = self.get_pool_path(sha256, filename, pool_type="content")
        # ...

    def add_repository_file(self, source_path, filename):  # NEW
        """Add repository file to files/ pool."""
        pool_path = self.get_pool_path(sha256, filename, pool_type="files")
        # ...
```

**Deduplication Works Across Types:**
- Same vmlinuz in BaseOS + AppStream → same SHA256 → **one file** in files/ ✅
- Same nginx.rpm in multiple repos → same SHA256 → **one file** in content/ ✅
- Different updateinfo.xml per repo → different SHA256 → **separate files** ✅

---

## GitHub Issues Structure

### Master Epic
**Issue: "Complete Repository Metadata & Mirror Support"**
- Links to all sub-issues
- Overall progress tracking
- Architecture documentation reference (this file)

### Sub-Issues

#### Phase 1: Foundation
- [ ] **Issue: Repository File Infrastructure**
  - Description: Create DB table, SQLAlchemy models, storage integration
  - Subtasks:
    - [ ] Research: Schema validation, snapshot integration
    - [ ] DB table + Alembic migration
    - [ ] SQLAlchemy model `RepositoryFile`
    - [ ] Extend `StorageManager` for non-package files
    - [ ] Unit tests

#### Phase 2: Mirror Mode
- [ ] **Issue: Mirror Mode - Core Infrastructure**
  - Description: Config, RPM sync all metadata, hardlink publishing
  - Subtasks:
    - [ ] Config schema (`mode`, `mirror_options`)
    - [ ] Validation: mirror + filters = error
    - [ ] RPM sync: Download all repomd.xml entries
    - [ ] RPM publish: Hardlink mode
    - [ ] Tests for both modes

- [ ] **Issue: Mirror Mode - URL Rewriting**
  - Description: Detect & rewrite URLs in metadata files
  - Subtasks:
    - [ ] URL detection in metadata
    - [ ] Rewrite logic (configurable)
    - [ ] Tests

#### Phase 3: Core Metadata (Filtered Mode)
- [ ] **Issue #12: updateinfo.xml Support (Security Advisories)** - HIGH PRIORITY
  - Description: Parse updateinfo.xml, store errata, link to packages
  - Subtasks:
    - [ ] Parser for updateinfo.xml
    - [ ] DB schema for `errata` table
    - [ ] DB schema for `errata_packages` (many-to-many)
    - [ ] Link CVEs to packages
    - [ ] CLI: Query errata (by severity, CVE, date)
    - [ ] Publisher: Generate updateinfo.xml from DB
    - [ ] Tests

- [ ] **Issue: filelists.xml Support**
  - Description: File listings metadata
  - Options: Pass-through or parse+regenerate
  - Recommendation: Start with pass-through

- [ ] **Issue: other.xml Support**
  - Description: Changelogs
  - Implementation: Pass-through in both modes

- [ ] **Issue: comps.xml / group.xml Support**
  - Description: Package groups
  - Subtasks:
    - [ ] Parse groups
    - [ ] DB table: `package_groups`
    - [ ] Publisher: Generate or pass-through

#### Phase 4: Advanced Features
- [ ] **Issue: Kickstart Support (RPM Installer Files)**
  - Description: Download .treeinfo, vmlinuz, initrd, images/, EFI/, isolinux/
  - Subtasks:
    - [ ] .treeinfo detection
    - [ ] Download installer files
    - [ ] Store with file_category=kickstart
    - [ ] Publishing: Reconstruct tree structure
    - [ ] Tests

- [ ] **Issue: debian-installer Support**
  - Description: APT installer files
  - Similar structure to kickstart

- [ ] **Issue: modules.yaml Support**
  - Description: DNF modularity
  - Implementation: Pass-through initially

- [ ] **Issue: Delta RPM Support**
  - Description: prestodelta.xml
  - Implementation: Pass-through

#### Phase 5: APK & APT Mirror
- [ ] **Issue: APK Mirror Mode**
- [ ] **Issue: APT Mirror Mode**

#### SUSE Support (Future)
- [ ] **Issue #11: SUSE Repository Support - Research & Planning**
  - Description: Research SUSE-specific formats, validate schema
  - Subtasks:
    - [ ] Document SUSE RPM-MD extensions (susedata, suseinfo, patterns, products, deltainfo)
    - [ ] Document YaST2/susetags format
    - [ ] Validate `repository_file` schema compatibility
    - [ ] Create implementation plan

- [ ] **Issue: SUSE RPM-MD Extensions Implementation**
  - Description: Implement susedata, patterns, products
  - Blocked by: Issue #11 (research)

- [ ] **Issue: YaST2 Format Support**
  - Description: YaST2/susetags format (if needed)
  - Blocked by: Issue #11 (research)

#### Documentation
- [ ] **Issue: Documentation Updates**
  - Description: README, new docs, comparison table
  - Subtasks:
    - [ ] README.md: Add kickstart/installer as USP
    - [ ] New doc: `docs/mirror-mode.md`
    - [ ] New doc: `docs/kickstart-support.md`
    - [ ] New doc: `docs/metadata-types.md`
    - [ ] New doc: `docs/errata.md`
    - [ ] Comparison table with reposync, apt-mirror, Pulp

---

## Implementation Phases - Detailed

### **Phase 1: Repository File Infrastructure** (Foundation)

**Goal:** Generic system to store ANY repo file in pool

**GitHub Issue:** "Repository File Infrastructure"

**Tasks:**

1. **DB Schema Design & Validation**
   - Review schema with all use cases
   - Research questions:
     - How do snapshots reference repository_files?
     - Deduplication: Same file across multiple repos?
     - Versioning: New repo sync updates files - keep history?
     - Cleanup: Orphaned repository_files in pool?
     - Indexes needed?

2. **Implementation**
   - Create `repository_file` table (Alembic migration)
   - SQLAlchemy model `RepositoryFile`
   - Add relationship: `Repository.files` (one-to-many)
   - Extend `StorageManager` for non-package files

3. **Testing**
   - Unit tests for RepositoryFile model
   - Storage manager tests (add/retrieve files)

**Deliverables:**
- DB migration for `repository_file` table
- SQLAlchemy model
- Storage manager extensions
- Unit tests

**Blockers:** None (can start immediately)

**Estimated Effort:** Medium (1-2 days)

---

### **Phase 2: Mirror Mode - Core Infrastructure**

**Goal:** Enable true 1:1 mirrors with original signatures

**GitHub Issue:** "Mirror Mode - Core Infrastructure"

**Dependencies:** Phase 1 complete

**Config Schema:**
```yaml
repositories:
  - id: centos9-mirror
    type: rpm
    feed: https://mirror.stream.centos.org/9-stream/BaseOS/x86_64/os/

    mode: mirror              # NEW: mirror | filtered (default: filtered)

    mirror_options:           # NEW
      preserve_metadata: true
      preserve_signatures: true
      rewrite_urls: auto      # auto | always | never
      verify_checksums: true

    # Mirror mode: no filters allowed!
    filters: null
```

**Tasks:**

**2.1 Config Updates:**
- Add `mode` field to RepositoryConfig (Pydantic model)
- Add `MirrorOptionsConfig` Pydantic model
- Validation: mirror mode + filters = config error
- Update example configs

**2.2 RPM Sync Updates:**

Current behavior (`rpm_sync.py`):
```python
# Line 255-259: Only downloads primary.xml
repomd_root = self._fetch_repomd_xml(self.config.feed)
primary_location = self._extract_primary_location(repomd_root)
packages = self._fetch_primary_xml(self.config.feed, primary_location)
```

New behavior:
```python
def _fetch_all_metadata(self, base_url, repomd_root, session, repository):
    """Download ALL metadata files from repomd.xml."""
    for data_elem in repomd_root.findall("data"):
        mdtype = data_elem.get("type")  # primary, updateinfo, filelists, etc.
        location_elem = data_elem.find("location")
        location = location_elem.get("href")

        # Download metadata file
        metadata_url = urljoin(base_url + "/", location)
        response = self.session.get(metadata_url, timeout=60)
        response.raise_for_status()

        # Save to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xml.gz") as tmp:
            tmp.write(response.content)
            tmp_path = Path(tmp.name)

        # Add to pool
        filename = Path(location).name
        sha256, pool_path, size_bytes = self.storage.add_package(
            tmp_path, filename, verify_checksum=True
        )

        # Store in repository_file table
        repo_file = RepositoryFile(
            repository=repository,
            file_category="metadata",
            file_type=mdtype,  # Flexible string! (updateinfo, susedata, etc.)
            sha256=sha256,
            pool_path=pool_path,
            size_bytes=size_bytes,
            original_path=location,
            metadata={
                "mdtype": mdtype,
                "compression": "gzip" if location.endswith(".gz") else "xz"
            }
        )
        session.add(repo_file)

        tmp_path.unlink()  # Cleanup temp file

    session.commit()
```

**2.3 RPM Publish Updates:**

Current behavior (`rpm/__init__.py`):
```python
# Lines 116-120: Always generates new metadata
primary_xml_path = self._generate_primary_xml(packages, repodata_path)
repomd_xml_path = self._generate_repomd_xml(repodata_path, primary_xml_path)
```

New behavior:
```python
def publish_snapshot(self, session, snapshot, repository, config, target_path):
    # Get packages
    packages = self._get_snapshot_packages(session, snapshot)

    # Publish packages
    self._publish_packages(packages, target_path)

    # Publish metadata based on mode
    if config.mode == "mirror":
        # Mirror mode: Hardlink original metadata from pool
        self._publish_metadata_mirror(repository, target_path)
    else:
        # Filtered mode: Generate new metadata from DB
        self._publish_metadata_filtered(packages, target_path)

def _publish_metadata_mirror(self, repository, target_path):
    """Publish metadata in mirror mode (hardlink originals)."""
    for repo_file in repository.files:
        # Source: pool
        src = self.storage.pool_path / repo_file.pool_path

        # Destination: reconstruct original path
        dst = target_path / repo_file.original_path

        # Create parent directories
        dst.parent.mkdir(parents=True, exist_ok=True)

        # Remove existing file if present
        if dst.exists():
            dst.unlink()

        # Hardlink (zero-copy)
        os.link(src, dst)

def _publish_metadata_filtered(self, packages, target_path):
    """Publish metadata in filtered mode (regenerate)."""
    # Current behavior: generate primary.xml, repomd.xml
    repodata_path = target_path / "repodata"
    repodata_path.mkdir(exist_ok=True)

    primary_xml_path = self._generate_primary_xml(packages, repodata_path)
    repomd_xml_path = self._generate_repomd_xml(repodata_path, primary_xml_path)
```

**2.4 URL Rewriting (separate sub-issue):**
- Detect URLs in metadata files (e.g., `<location href="https://...">`)
- Rewrite to relative paths if needed
- Configurable: auto | always | never
- Can be implemented later

**Deliverables:**
- Config schema with `mode` and `mirror_options`
- RPM sync downloads all repomd.xml entries → repository_file table
- RPM publish supports hardlink mode
- Tests for both modes
- Can mirror CentOS Stream / RHEL repos 1:1

**Blockers:** Phase 1 complete

**Estimated Effort:** Medium-Large (2-3 days)

---

### **Phase 3: Core Metadata Types** (Filtered Mode)

#### **3.1 updateinfo.xml Support (Issue #12 - HIGH PRIORITY)**

**Goal:** Security advisory/errata support

**Dependencies:** Phase 1 complete (repository_file table exists)

**New DB Tables:**
```sql
CREATE TABLE errata (
  id TEXT PRIMARY KEY,        -- e.g., "RHSA-2024:0001"
  type TEXT,                  -- security | bugfix | enhancement
  severity TEXT,              -- critical | important | moderate | low
  title TEXT,
  description TEXT,
  solution TEXT,
  issued_date DATETIME,
  updated_date DATETIME,
  references JSON,            -- CVEs, BugIDs, URLs
  metadata JSON,              -- Flexible for distro-specific fields
  created_at DATETIME,
  updated_at DATETIME
);

CREATE TABLE errata_packages (
  errata_id TEXT,
  package_id INTEGER,         -- FK to content_item
  PRIMARY KEY(errata_id, package_id),
  FOREIGN KEY(errata_id) REFERENCES errata(id),
  FOREIGN KEY(package_id) REFERENCES content_item(id)
);
```

**updateinfo.xml Format (Example):**
```xml
<updates>
  <update from="security@redhat.com" status="stable" type="security" version="1">
    <id>RHSA-2024:0001</id>
    <title>Important: kernel security update</title>
    <severity>Important</severity>
    <description>Security fix for CVE-2024-1234</description>
    <issued date="2024-01-01"/>
    <updated date="2024-01-02"/>
    <references>
      <reference href="https://access.redhat.com/errata/RHSA-2024:0001" id="RHSA-2024:0001" title="RHSA-2024:0001" type="self"/>
      <reference href="https://access.redhat.com/security/cve/CVE-2024-1234" id="CVE-2024-1234" title="CVE-2024-1234" type="cve"/>
    </references>
    <pkglist>
      <collection short="RHEL9">
        <package arch="x86_64" epoch="0" name="kernel" release="123.el9" version="5.14.0">
          <filename>kernel-5.14.0-123.el9.x86_64.rpm</filename>
        </package>
      </collection>
    </pkglist>
  </update>
</updates>
```

**Tasks:**

1. **Parser Implementation** (`plugins/rpm/updateinfo_parser.py`)
   - Parse updateinfo.xml format
   - Extract errata metadata
   - Extract package references
   - Unit tests for parser

2. **DB Models** (`db/models.py`)
   - SQLAlchemy model for `errata` table
   - SQLAlchemy model for `errata_packages` table
   - Relationships

3. **Sync Integration** (`plugins/rpm_sync.py`)
   - After downloading packages, parse updateinfo.xml
   - Store errata in DB
   - Link errata ↔ packages

4. **CLI Commands** (`cli/main.py`)
   ```bash
   # Query errata
   chantal errata list --repo-id centos9-baseos
   chantal errata list --severity critical
   chantal errata list --type security --since 2024-01-01
   chantal errata show RHSA-2024:0001
   chantal errata search CVE-2024-1234

   # Show affected packages
   chantal errata packages RHSA-2024:0001
   ```

5. **Publisher** (`plugins/rpm/__init__.py`)
   - Generate updateinfo.xml from errata DB
   - Include in repomd.xml

**Deliverables:**
- updateinfo.xml parser
- Errata DB schema + models
- Sync integration
- CLI commands for querying
- Publisher generates updateinfo.xml
- Tests

**Blockers:** Phase 1 complete

**Estimated Effort:** Large (3-5 days)

#### **3.2 filelists.xml Support**

**Goal:** File listings metadata

**Options:**
- Option A (simple): Pass-through only (don't parse)
- Option B (complex): Parse + store + regenerate

**Recommendation:** Start with Option A (pass-through)

**Implementation:**
- Mirror mode: Already handled (downloads all metadata)
- Filtered mode: Pass-through for now (just copy from upstream)

**Deliverables:**
- filelists.xml in published repos (pass-through)

**Blockers:** Phase 2 complete

**Estimated Effort:** Small (1 day)

#### **3.3 other.xml Support (Changelogs)**

**Goal:** Changelog metadata

**Implementation:** Pass-through in both modes

**Deliverables:**
- other.xml in published repos

**Blockers:** Phase 2 complete

**Estimated Effort:** Small (1 day)

#### **3.4 comps.xml / group.xml Support (Package Groups)**

**Goal:** Package group metadata

**Implementation:**
- Parse groups
- Store in DB (new table: `package_groups`)
- Publisher: Generate or pass-through

**Deliverables:**
- comps.xml parser
- DB schema for package groups
- Publisher generates comps.xml

**Blockers:** Phase 2 complete

**Estimated Effort:** Medium (2-3 days)

---

### **Phase 4: Kickstart & Installer Support**

**Goal:** Download installer files (USP vs reposync!)

**GitHub Issue:** "Kickstart & Installer File Support"

**Dependencies:** Phase 1 complete

**.treeinfo Format (Example):**
```ini
[general]
family = CentOS Stream
timestamp = 1704067200
variant = BaseOS
version = 9

[images-x86_64]
kernel = images/pxeboot/vmlinuz
initrd = images/pxeboot/initrd.img
boot.iso = images/boot.iso
```

**Files to Download:**

**RPM Kickstart:**
```
.treeinfo                          → file_category=kickstart, file_type=treeinfo
images/pxeboot/vmlinuz             → file_category=kickstart, file_type=vmlinuz
images/pxeboot/initrd.img          → file_category=kickstart, file_type=initrd
images/boot.iso                    → file_category=kickstart, file_type=boot_iso
images/efiboot.img                 → file_category=kickstart, file_type=efi_boot
EFI/**/*                           → file_category=kickstart, file_type=efi_file
isolinux/**/*                      → file_category=kickstart, file_type=isolinux_file
```

**Tasks:**

1. **Detection**
   - Check for `.treeinfo` file at repo root
   - Parse .treeinfo to find installer files

2. **Download**
   - Download all files listed in .treeinfo
   - Download directories (EFI/, isolinux/)
   - Store in pool with file_category=kickstart

3. **Publishing**
   - Reconstruct exact directory structure via `original_path`
   - Hardlink from pool to published location

**Deliverables:**
- .treeinfo parser
- Kickstart file downloader
- Publisher: Reconstruct tree
- Tests
- Can create offline installation media

**Blockers:** Phase 1 complete

**Estimated Effort:** Medium (2-3 days)

---

### **Phase 5: APK & APT Mirror Support**

**APK:**
- Download `APKINDEX.tar.gz` to repository_file
- Download `.SIGN.*` signature files
- Publish: Hardlink originals
- **APK perfect for mirror mode!**

**APT:**
- Download `Release` / `InRelease`
- Download all `Packages.gz`, `Contents-*.gz`, `Translation-*.xz`
- Download `Release.gpg`
- Publish: Hardlink originals

**Deliverables:**
- APK mirror mode
- APT mirror mode

**Blockers:** Phase 2 complete

**Estimated Effort:** Medium (2-3 days each)

---

## Documentation Updates

### README.md - Feature Section

Add to feature list:

```markdown
## Key Features

### Complete Repository Mirroring
- **Full metadata support** - All repodata files (updateinfo, filelists, comps, modules)
- **Kickstart & installer support** - Download vmlinuz, initrd, .treeinfo for offline installations
- **Signature preservation** - Keep original GPG signatures in mirror mode
- **Security advisories** - Track CVEs and errata (RHEL, CentOS, Ubuntu, Debian)

### Two Operating Modes
- **Mirror mode** - True 1:1 copy with original signatures (perfect for air-gapped environments)
- **Filtered mode** - Curated repos with package filtering, snapshots, and custom content

### What Chantal Does That Others Don't

Unlike tools like `reposync` or `apt-mirror`, Chantal can:
- ✅ Mirror complete installation repositories (kickstart files, installer images)
- ✅ Preserve original vendor signatures in mirror mode
- ✅ Parse and query security advisories (CVEs, errata)
- ✅ Support both mirror and filtered modes
- ✅ Unified pool for all content types (packages, metadata, installer files)
- ✅ Deduplication across all repositories

Perfect for fully air-gapped environments and enterprise deployments!
```

### New Documentation Pages

**1. `docs/mirror-mode.md` - Mirror vs Filtered Mode**

Topics:
- Comparison table
- When to use each mode
- Configuration examples
- Signature preservation
- Limitations

**2. `docs/kickstart-support.md` - Kickstart & Installer Files**

Topics:
- What Chantal downloads
- Comparison with reposync (doesn't support kickstart)
- Use cases: Offline installation media
- Configuration examples
- .treeinfo format

**3. `docs/metadata-types.md` - All Supported Metadata Types**

Topics:
- RPM metadata (updateinfo, filelists, other, comps, modules)
- APK metadata (APKINDEX)
- APT metadata (Release, Packages, Contents, Translation)
- SUSE metadata (susedata, patterns, products) - future
- How metadata is stored (repository_file table)

**4. `docs/errata.md` - Security Advisory Tracking**

Topics:
- Querying errata
- CVE tracking
- CLI examples
- Integration with security tools

### Comparison Table

Add to documentation:

| Feature | reposync | apt-mirror | Pulp | Chantal |
|---------|----------|------------|------|---------|
| **Basic Syncing** |
| Package sync | ✅ | ✅ | ✅ | ✅ |
| Incremental sync | ✅ | ✅ | ✅ | ✅ |
| **Metadata** |
| Full metadata | ❌ (primary only) | ⚠️ (manual config) | ✅ | ✅ |
| Kickstart files | ❌ | ❌ | ⚠️ (complex) | ✅ |
| Installer images | ❌ | ❌ | ⚠️ | ✅ |
| **Signatures** |
| Preserve signatures | ❌ | ⚠️ (sometimes) | ✅ | ✅ |
| True 1:1 mirror | ❌ | ⚠️ | ✅ | ✅ |
| **Security** |
| Errata tracking | ❌ | ❌ | ✅ | ✅ |
| CVE queries | ❌ | ❌ | ✅ | ✅ |
| **Advanced** |
| Filtering | ⚠️ (limited) | ❌ | ✅ | ✅ |
| Snapshots | ❌ | ❌ | ✅ | ✅ |
| Deduplication | ❌ | ❌ | ❌ | ✅ |
| Multi-format pool | ❌ | ❌ | ❌ | ✅ |
| **Ease of Use** |
| Simple config | ✅ | ✅ | ❌ (complex) | ✅ |
| Single binary | ✅ | ✅ | ❌ (services) | ✅ |

---

## SUSE Support (Future)

### Issue #11: SUSE Repository Support - Research & Planning

**Goal:** Document SUSE-specific requirements, validate schema

**Tasks:**

1. **Research SUSE RPM-MD Extensions**
   - `susedata` - SUSE extensions (EULA, keywords)
   - `suseinfo` - Repository info (distro/update tags)
   - `patterns` - Software patterns (like comps)
   - `products` - Product metadata (SLES editions)
   - `deltainfo` - Delta RPMs

2. **Research YaST2/susetags Format**
   - `content` file (master index)
   - `content.asc` (signature)
   - `suse/setup/descr/packages` (package cache)
   - Pattern `.pat` files

3. **Validate Schema Compatibility**
   - Confirm `file_type` as string (not enum) works
   - Test with SUSE repos
   - Document any needed changes

4. **Create Implementation Plan**
   - Prioritize SUSE mdtypes
   - Decide on YaST2 support (if needed)
   - Create sub-issues for implementation

**Deliverables:**
- SUSE format documentation
- Schema validation report
- Implementation plan
- New GitHub issues for implementation

**Blockers:** None (can start anytime)

**Estimated Effort:** Small (research only, 1-2 days)

**Note:** Mirror mode will automatically work for SUSE RPM-MD repos because `file_type` is a flexible string! Parser extensions can be added incrementally.

---

## Success Criteria

### Phase 1 Complete
- ✅ `repository_file` table created and working
- ✅ Files stored in universal pool
- ✅ Tests passing
- ✅ Schema validated for all use cases

### Phase 2 Complete
- ✅ Mirror mode working for RPM repos
- ✅ Original signatures preserved
- ✅ Can mirror CentOS Stream / RHEL repos 1:1
- ✅ Hardlink publishing works
- ✅ Config validation works (mirror + filters = error)

### Phase 3.1 Complete (updateinfo)
- ✅ Can parse updateinfo.xml
- ✅ Errata stored in DB
- ✅ Can query errata by CVE, severity, date
- ✅ updateinfo.xml generated correctly in filtered mode
- ✅ Security tools work with published repos

### Phase 4 Complete (Kickstart)
- ✅ Can detect kickstart repos (.treeinfo)
- ✅ Downloads all installer files
- ✅ Can create offline installation media
- ✅ Feature parity with Pulp (better than reposync!)

### Overall Success
- ✅ Chantal can mirror complete repos (packages + metadata + installer files)
- ✅ Original vendor signatures preserved in mirror mode
- ✅ Security advisories tracked and queryable
- ✅ Air-gapped deployments fully supported
- ✅ USP clearly documented vs other tools

---

## Recommended Implementation Order

**Iteration 1: Foundation (Phase 1)**
- Create repository_file infrastructure
- Research & schema validation
- **Estimated: 1-2 days**
- **Deliverable: Working DB table, storage integration**

**Iteration 2: Mirror Mode (Phase 2)**
- Config + validation
- RPM sync all metadata
- RPM publish hardlink mode
- **Estimated: 2-3 days**
- **Deliverable: Working mirror mode for RPM repos**

**Iteration 3: Security Advisories (Phase 3.1)**
- updateinfo.xml parser
- Errata DB schema
- CLI for querying
- Publisher integration
- **Estimated: 3-5 days**
- **Deliverable: Errata tracking & queries**

**Iteration 4: Kickstart Support (Phase 4)**
- .treeinfo detection & parsing
- Installer file download
- Publishing: Reconstruct tree
- **Estimated: 2-3 days**
- **Deliverable: Full installer support**

**Iteration 5: Additional Metadata (Phase 3.2-3.4)**
- filelists, other, comps
- **Estimated: 3-5 days**
- **Deliverable: Complete metadata support**

**Iteration 6: APK/APT Mirror (Phase 5)**
- APK mirror mode
- APT mirror mode
- **Estimated: 4-6 days**
- **Deliverable: Multi-format mirror support**

**Future: SUSE Support**
- Research first (Issue #11)
- Implementation after validation
- **Estimated: TBD after research**

---

## Risk Assessment

### High Risk
- **Schema changes needed during implementation**
  - Mitigation: Thorough Phase 1 research
  - Mitigation: Alembic migrations for DB changes

- **Upstream metadata format changes**
  - Mitigation: Flexible string types (not enums)
  - Mitigation: Generic JSON metadata field

### Medium Risk
- **URL rewriting complexity**
  - Mitigation: Optional feature, can be done later
  - Mitigation: Configurable (auto | always | never)

- **Performance with large metadata files**
  - Mitigation: Stream downloads
  - Mitigation: Deduplication in pool

### Low Risk
- **Breaking existing repos**
  - Mitigation: Backward compatible (default: filtered mode)
  - Mitigation: Extensive tests

---

## Open Questions (Phase 1 Research)

1. **Snapshots & repository_files:**
   - Do snapshots reference repository_files directly?
   - Or only through repository relationship?
   - Should snapshots freeze metadata files?

2. **Deduplication:**
   - Same metadata file across repos → single pool entry?
   - Or separate entries per repo?

3. **Versioning:**
   - New sync updates metadata files → replace or keep history?
   - How to handle rollback?

4. **Cleanup:**
   - `pool cleanup` should also check repository_files?
   - Orphaned metadata files in pool?

5. **Indexes:**
   - Index on `sha256` for dedup queries?
   - Index on `repository_id` for performance?
   - Index on `file_category` + `file_type` for queries?

**Action:** Answer these in Phase 1 before proceeding!

---

## Tracking

**Planning Doc:** `.planning/metadata-mirror-support.md` (this file)
**GitHub Project:** TBD (create board for tracking)
**Related Issues:** #12 (updateinfo), #11 (SUSE)

**Updates:** This document should be updated as decisions are made during implementation.

---

**Last Updated:** 2026-01-11
**Status:** Planning - Ready for Phase 1 Research
