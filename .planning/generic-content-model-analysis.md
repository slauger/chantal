# Generic Content Model - Deep Analysis

## Planned Content Types (from GitHub Issues)

Based on open issues, these content types are planned:

### 1. Package Registries
- PyPI (Python Package Index)
- RubyGems
- npm/yarn
- NuGet (.NET)
- Go Modules
- Helm Charts
- APT/DEB
- Alpine APK

### 2. RPM Extensions
- Errata/Advisory Data
- SUSE/SLES Extensions

### 3. Other
- Terraform Provider Registry

## Content Type Requirements Analysis

### RPM (Already Implemented)
```python
# Core fields
name: str           # package name
version: str        # version string
release: str        # release string
epoch: str          # epoch (optional)
arch: str           # x86_64, noarch, etc.

# Content addressing
sha256: str         # checksum
size_bytes: int     # file size
pool_path: str      # storage location
filename: str       # original filename

# Metadata
summary: str
description: str

# Unique identifier: name-epoch:version-release.arch (NEVRA)
```

**Special Requirements:**
- Complex versioning (epoch:version-release)
- Architecture-specific
- Provides/Requires dependencies (complex!)
- Errata/Advisory associations (future)

### Helm Charts
```python
# Core fields
name: str           # chart name
version: str        # chart version (semver)
app_version: str    # application version

# Content addressing
sha256: str
size_bytes: int
pool_path: str
filename: str       # .tgz file

# Metadata
description: str
home: str           # project URL
icon: str           # icon URL
created: str        # ISO 8601 timestamp
keywords: list[str]
maintainers: list[dict]  # {name, email}
sources: list[str]
dependencies: list[dict]  # {name, version, repository}

# Unique identifier: name-version
```

**Special Requirements:**
- Semantic versioning
- Dependencies on other charts
- Maintainers as structured data

### PyPI (Python)
```python
# Core fields
name: str           # package name (normalized)
version: str        # PEP 440 version
python_requires: str  # Python version constraint

# Content addressing
sha256: str
size_bytes: int
pool_path: str
filename: str       # .whl or .tar.gz

# Metadata
summary: str
description: str    # README/long_description
author: str
author_email: str
license: str
home_page: str
project_urls: dict  # {Documentation, Source, ...}
classifiers: list[str]  # Trove classifiers
requires_dist: list[str]  # PEP 508 dependencies
requires_python: str

# Unique identifier: name-version (+ python version + platform for wheels)
```

**Special Requirements:**
- Wheels vs Source distributions
- Platform-specific builds (manylinux, win32, macosx)
- Python version constraints
- Complex dependency specifications (PEP 508)

### npm (JavaScript)
```python
# Core fields
name: str           # @scope/package or package
version: str        # semver

# Content addressing
sha256: str         # integrity hash
size_bytes: int
pool_path: str
filename: str       # .tgz

# Metadata (from package.json)
description: str
homepage: str
license: str
author: dict        # {name, email, url}
contributors: list[dict]
repository: dict    # {type, url}
keywords: list[str]
dependencies: dict  # {package: version}
devDependencies: dict
peerDependencies: dict
engines: dict       # {node: ">=14.0.0"}

# Unique identifier: name-version
```

**Special Requirements:**
- Scoped packages (@org/package)
- Complex dependency types (dev, peer, optional)
- Lockfile support (package-lock.json)

### RubyGems
```python
# Core fields
name: str           # gem name
version: str        # gem version
platform: str       # ruby, java, x86_64-linux

# Content addressing
sha256: str
size_bytes: int
pool_path: str
filename: str       # .gem file

# Metadata
summary: str
description: str
authors: list[str]
email: list[str]
homepage: str
licenses: list[str]
dependencies: list[dict]  # {name, version_requirements, type}

# Unique identifier: name-version-platform
```

**Special Requirements:**
- Platform-specific gems (ruby vs jruby vs native)
- Runtime vs Development dependencies

### NuGet (.NET)
```python
# Core fields
id: str             # package ID (case-insensitive!)
version: str        # semver

# Content addressing
sha256: str
size_bytes: int
pool_path: str
filename: str       # .nupkg file

# Metadata (.nuspec)
description: str
authors: str
owners: str
license_url: str
project_url: str
icon_url: str
tags: str
dependencies: list[dict]  # framework-specific!
framework_assemblies: list[dict]

# Unique identifier: id-version (case-insensitive)
```

**Special Requirements:**
- Case-insensitive package IDs
- Framework-specific dependencies (.NET Framework, .NET Core, .NET 5+)
- Multiple target frameworks in one package

### Go Modules
```python
# Core fields
module_path: str    # github.com/user/repo
version: str        # v1.2.3 or commit hash

# Content addressing
sha256: str
size_bytes: int
pool_path: str
filename: str       # .zip file

# Metadata (from go.mod)
go_version: str     # minimum Go version
dependencies: list[dict]  # {module, version}
replacements: list[dict]  # replace directives

# Unique identifier: module_path@version
```

**Special Requirements:**
- Version can be semver tag OR commit hash
- Pseudo-versions (v0.0.0-20240101120000-abcdef123456)
- Replace directives
- GOPROXY protocol

### APT/DEB (Debian/Ubuntu)
```python
# Core fields
package: str        # package name
version: str        # version (complex Debian format!)
architecture: str   # amd64, all, etc.

# Content addressing
sha256: str
size_bytes: int
pool_path: str
filename: str       # .deb file

# Metadata (from control file)
description: str
maintainer: str
section: str        # main, contrib, non-free
priority: str       # required, important, standard, optional
depends: str        # complex dependency syntax
recommends: str
suggests: str
conflicts: str
provides: str
replaces: str

# Unique identifier: package_version_architecture
```

**Special Requirements:**
- Complex versioning (epoch:upstream-debian)
- Release/Suite/Component structure (bullseye/main, bullseye/updates)
- Multiple architectures + "all"
- Complex dependency syntax
- InRelease/Release files with GPG signatures

### Alpine APK
```python
# Core fields
name: str           # package name
version: str        # version-release
arch: str           # x86_64, aarch64, etc.

# Content addressing
sha256: str
size_bytes: int
pool_path: str
filename: str       # .apk file

# Metadata
description: str
url: str
license: str
depends: list[str]
provides: list[str]
install_if: list[str]  # automatic installation conditions

# Unique identifier: name-version-arch
```

**Special Requirements:**
- install_if (unique to Alpine)
- Repository branches (edge, v3.19, v3.18)

### Terraform Providers
```python
# Core fields
namespace: str      # hashicorp, terraform-providers
name: str           # aws, azurerm, google
version: str        # semver
os: str             # linux, darwin, windows
arch: str           # amd64, arm64

# Content addressing
sha256: str
size_bytes: int
pool_path: str
filename: str       # .zip file

# Metadata
protocols: list[str]  # ["5.0", "6.0"]
shasums_signature_url: str  # GPG signature
signing_keys: dict

# Unique identifier: namespace/name_version_os_arch
```

**Special Requirements:**
- Quad-tuple identifier (namespace/name/version/os_arch)
- GPG signature verification
- Protocol versions

### RPM Errata/Advisories
```python
# This is NOT a package type, but metadata ABOUT packages
advisory_id: str    # RHSA-2024:1234
type: str           # security, bugfix, enhancement
severity: str       # critical, important, moderate, low
issued_date: str
updated_date: str
description: str
packages: list[str]  # Affected package NEVRAs
cves: list[str]     # CVE-2024-1234
references: list[dict]  # {type, url, id}

# Associates with existing RPM packages
```

**Special Requirements:**
- Not a content item itself, but metadata layer
- Many-to-many relationship with packages
- Separate table? Or part of RPM metadata?

## Analysis: Can Generic Model Handle All?

### Common Fields (All Content Types)
✅ All have these:
```python
name/id: str        # Package identifier
version: str        # Version string
sha256: str         # Checksum
size_bytes: int     # File size
pool_path: str      # Storage location
filename: str       # Original filename
```

### Differences

| Content Type | Versioning | Architecture | Dependencies | Special |
|--------------|------------|--------------|--------------|---------|
| RPM | epoch:version-release | Yes (arch) | Complex (provides/requires) | Errata |
| Helm | Semver | No | Simple (chart deps) | App version |
| PyPI | PEP 440 | Yes (platform) | PEP 508 | Multiple files per version |
| npm | Semver | No | Complex (dev/peer/optional) | Scopes |
| RubyGems | Gem version | Yes (platform) | Runtime/Dev | - |
| NuGet | Semver | Yes (framework) | Framework-specific | Case-insensitive |
| Go | Semver/hash | No | Simple | Pseudo-versions |
| APT/DEB | Debian format | Yes (arch) | Very complex | Suite/Component |
| Alpine APK | Version-release | Yes (arch) | Simple | install_if |
| Terraform | Semver | Yes (os/arch) | None | Quad-tuple ID |

### Critical Question: Queries

Will we need to query type-specific fields?

**Examples:**
1. "Find all RPM packages with epoch > 0" → Need to parse JSON?
2. "Find all PyPI wheels for Python 3.11+" → Need to parse JSON?
3. "Find all npm packages with peer dependencies" → Need to parse JSON?
4. "Find all packages matching advisory RHSA-2024:1234" → Need Errata table?

**SQLite JSON support:**
```sql
-- SQLite has JSON functions!
SELECT * FROM content_items
WHERE content_type = 'rpm'
  AND json_extract(metadata, '$.epoch') > 0;

SELECT * FROM content_items
WHERE content_type = 'helm'
  AND json_array_length(json_extract(metadata, '$.dependencies')) > 0;
```

✅ **SQLite can query JSON!** Performance is good enough for our use case.

## Proposed Generic Model

```python
class ContentItem(Base):
    """Generic content model for all package types."""
    __tablename__ = "content_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Content type (determines which plugin handles it)
    content_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # Values: 'rpm', 'helm', 'pypi', 'npm', 'rubygems', 'nuget', 'go', 'apt', 'apk', 'terraform'

    # Universal fields (all content types have these)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # Content addressing (pool storage)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    pool_path: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)

    # Type-specific metadata as JSON
    # Structure depends on content_type:
    # - rpm: {epoch, release, arch, summary, description, ...}
    # - helm: {app_version, keywords, maintainers, icon, ...}
    # - pypi: {python_requires, author, license, requires_dist, ...}
    # - npm: {dependencies, devDependencies, peerDependencies, ...}
    # - etc.
    metadata: Mapped[dict] = mapped_column(JSON, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # Reference counting (garbage collection)
    reference_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships (generic)
    repositories: Mapped[list["Repository"]] = relationship(
        "Repository", secondary=repository_content_items, back_populates="content_items"
    )
    snapshots: Mapped[list["Snapshot"]] = relationship(
        "Snapshot", secondary=snapshot_content_items, back_populates="content_items"
    )

    # Composite index for common queries
    __table_args__ = (
        Index("idx_content_type_name", "content_type", "name"),
        Index("idx_content_type_name_version", "content_type", "name", "version"),
    )
```

### Pydantic Models for Type Safety

Plugins define Pydantic models to validate metadata:

```python
# src/chantal/plugins/rpm/models.py
class RpmMetadata(BaseModel):
    """Metadata schema for RPM packages."""
    epoch: Optional[str] = None
    release: str
    arch: str
    summary: Optional[str] = None
    description: Optional[str] = None
    # ... more fields

# src/chantal/plugins/helm/models.py
class HelmMetadata(BaseModel):
    """Metadata schema for Helm charts."""
    app_version: Optional[str] = None
    keywords: Optional[list[str]] = None
    maintainers: Optional[list[dict]] = None
    # ... more fields
```

Plugins validate on sync:
```python
class RpmSyncer(BaseSyncer):
    async def sync(self, repo: Repository, config: GlobalConfig):
        # ... download package ...

        metadata = RpmMetadata(
            epoch=rpm_data.epoch,
            release=rpm_data.release,
            arch=rpm_data.arch,
            # ...
        )

        content_item = ContentItem(
            content_type="rpm",
            name=rpm_data.name,
            version=rpm_data.version,
            metadata=metadata.model_dump(),  # Validated!
            # ...
        )
```

## Special Cases

### 1. Errata/Advisories

**Option A:** Separate table (recommended)
```python
class Advisory(Base):
    """RPM Errata/Advisory data."""
    __tablename__ = "advisories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    advisory_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # security, bugfix, enhancement
    severity: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    issued_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Many-to-many with content_items
    content_items: Mapped[list["ContentItem"]] = relationship(
        "ContentItem", secondary=advisory_content_items, back_populates="advisories"
    )
```

This is separate because advisories are NOT content items themselves.

### 2. Multi-file Packages (PyPI)

PyPI can have multiple files for one package-version:
- `package-1.0.0.tar.gz` (source)
- `package-1.0.0-py3-none-any.whl` (universal wheel)
- `package-1.0.0-cp311-cp311-manylinux_2_17_x86_64.whl` (Python 3.11, Linux)

**Solution:** Each file is separate ContentItem with unique SHA256
```python
# Same name-version, different files
ContentItem(name="requests", version="2.31.0", filename="requests-2.31.0.tar.gz", sha256="abc...")
ContentItem(name="requests", version="2.31.0", filename="requests-2.31.0-py3-none-any.whl", sha256="def...")
```

Metadata includes file type:
```python
metadata = {
    "python_requires": ">=3.7",
    "file_type": "wheel",  # or "sdist"
    "python_version": "py3",
    "abi_tag": "none",
    "platform_tag": "any",
}
```

## Migration Strategy

### Phase 1: Rename `packages` → `content_items`
```sql
ALTER TABLE packages RENAME TO content_items;
ALTER TABLE packages ADD COLUMN content_type TEXT DEFAULT 'rpm';
ALTER TABLE packages ADD COLUMN metadata JSON;

-- Migrate RPM-specific fields to metadata JSON
UPDATE content_items SET metadata = json_object(
    'epoch', epoch,
    'release', release,
    'arch', arch,
    'summary', summary,
    'description', description
);

-- Drop old columns (after migration verified)
-- ALTER TABLE content_items DROP COLUMN epoch;
-- ALTER TABLE content_items DROP COLUMN release;
-- ...
```

### Phase 2: Add new content types
Just insert with `content_type='helm'`, `content_type='pypi'`, etc.
**NO schema changes needed!**

## Recommendation

✅ **GO GENERIC!**

**Why:**
1. **Scalable**: 10+ content types planned, generic handles all
2. **No schema bloat**: One table instead of 10+
3. **Plugin isolation**: Plugins don't modify DB schema
4. **SQLite JSON**: Fast enough for our use case
5. **Pydantic validation**: Type safety without DB schema
6. **Proven**: Pulp does this successfully

**Migration now is easiest:**
- Only RPM implemented
- No production users yet
- Can test thoroughly before adding more types

**Do it?** 🚀
