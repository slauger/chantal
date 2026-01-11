# Chantal Development Roadmap

**Last Updated:** 2026-01-12
**Current Version:** 0.1.0

---

## Current Status

**✅ Multi-Format Repository Tool Complete** - RPM, Helm, Alpine APK support with snapshots and views

- 102 tests passing
- Generic ContentItem model with JSON metadata
- Content-addressed storage with deduplication
- RPM, Helm, Alpine APK sync, publish, snapshots, views operational
- RHEL CDN authentication working
- Mirror mode with metadata preservation
- Central download manager with auth/SSL/proxy support

---

## Completed Milestones

### ✅ Milestone 1: Foundation & Configuration (Complete)
**Status:** Closed via [#15](https://github.com/slauger/chantal/issues/15)

- Generic ContentItem model with JSON metadata
- Pydantic-based configuration (GlobalConfig, RepositoryConfig)
- YAML loading with include support
- CLI integration with --config flag
- Database models (Repository, ContentItem, Snapshot, View)
- 15 configuration tests passing

### ✅ Milestone 2: Content-Addressed Storage (Complete)
**Status:** Closed via [#15](https://github.com/slauger/chantal/issues/15)

- Universal SHA256-based storage pool
- 2-level directory structure (ab/cd/sha256_file.rpm)
- Instant deduplication via content-addressing
- Hardlink-based publishing (zero-copy)
- Orphaned files cleanup
- Pool statistics
- 15 storage tests passing

### ✅ Milestone 3: RPM Plugin & Sync (Complete)

- RPM repository sync (repomd.xml, primary.xml.gz)
- Package filtering (patterns, architectures)
- RHEL CDN authentication (client certificates)
- Progress tracking
- Metadata extraction
- 14 publisher tests passing

### ✅ Milestone 4: Snapshots (Complete)

- Immutable point-in-time snapshots
- Snapshot creation and management
- Snapshot publishing
- Snapshot diff functionality
- Snapshot copy for promotion workflows
- Database-backed snapshot tracking

### ✅ Milestone 5: Views & Advanced Publishing (Complete)

- Views (virtual repositories combining multiple repos)
- View publishing directly from config (no DB sync needed)
- View snapshots (atomic multi-repo snapshots)
- Publisher plugin system (RpmPublisher, ViewPublisher)
- 10 view tests passing

### ✅ Milestone 6: Database Management & Operations (Complete)
**Status:** Closed via [#14](https://github.com/slauger/chantal/issues/14) - 2026-01-11

- `chantal db init` - Initialize database schema with Alembic
- `chantal db upgrade` - Upgrade database to specific revision
- `chantal db status` - Show schema status and pending migrations
- `chantal db current` - Show current database revision
- `chantal db history` - Show migration history
- `chantal pool stats` - Show storage pool statistics
- `chantal pool cleanup` - Clean orphaned files and missing entries
- `chantal pool verify` - Comprehensive pool integrity check

### ✅ Milestone 7: Helm Chart Repository Support (Complete)
**Status:** Closed via [#2](https://github.com/slauger/chantal/issues/2) - 2026-01-10

- Helm plugin implementation (HelmSyncer, HelmPublisher)
- index.yaml parsing and generation
- Chart metadata extraction (version, app_version, description)
- Chart filtering (patterns, version constraints)
- Helm repository publishing
- Content-addressed storage for .tgz charts
- Authentication support (Basic, Bearer, Client Cert)

### ✅ Milestone 8: Alpine APK Support (Complete)
**Status:** Closed via [#4](https://github.com/slauger/chantal/issues/4) - 2026-01-10

- APK plugin implementation (ApkSyncer, ApkPublisher)
- APKINDEX.tar.gz parsing
- APK package metadata extraction
- Package filtering (patterns, version constraints)
- Alpine repository publishing
- Content-addressed storage for .apk files
- Multi-architecture support

### ✅ Milestone 9: Metadata and Mirror Mode Support (Complete)
**Status:** Closed via [#18](https://github.com/slauger/chantal/issues/18) - 2026-01-11

- RepositoryFile model for metadata storage
- Full metadata mirroring (updateinfo, filelists, other, comps, modules)
- Repository modes (MIRROR, FILTERED, HOSTED)
- Updateinfo filtering in FILTERED mode
- Kickstart/installer support (.treeinfo, vmlinuz, initrd.img, boot.iso)
- Content-addressed metadata storage with deduplication

### ✅ Milestone 10: Plugin Structure Refactoring (Complete)
**Status:** Closed via [#24](https://github.com/slauger/chantal/issues/24) - 2026-01-11

- Cleaned up plugin module structure
- Separated sync and publisher plugins
- Moved parsers to dedicated modules
- Improved type hints and documentation
- Consistent plugin API across RPM, Helm, APK

### ✅ Milestone 11: Central Download Manager (Complete)
**Status:** Closed via [#25](https://github.com/slauger/chantal/issues/25) - 2026-01-11

- DownloadManager abstraction layer
- Unified auth setup (client cert, basic, bearer, headers)
- Consistent SSL/TLS verification across all plugins
- Global and per-repository proxy support
- Retry logic with configurable attempts
- SHA256 checksum verification

### ✅ Milestone 12: Code Quality & Type Safety (Complete)
**Status:** Closed via [#22](https://github.com/slauger/chantal/issues/22) - 2026-01-11

- Fixed all linting errors (ruff, black)
- Added comprehensive type hints
- MyPy strict type checking enabled
- CI/CD with lint and type check workflows
- Python 3.10+ compatibility ensured

---

## In Progress

### 🔄 Milestone 13: CLI Modularization
**Status:** Completed refactoring, testing in progress

- ✅ Split cli/main.py (3758 lines) into 7 modular command files
- ✅ Created db_commands.py, repo_commands.py, snapshot_commands.py, etc.
- ✅ All 15 CLI tests passing
- ⏳ Update remaining documentation references

---

## Next Milestones

### 📋 Milestone 14: APK Mirror Mode Support

**GitHub Issue:** [#26](https://github.com/slauger/chantal/issues/26)

**Status:** Planned

**Scope:**
- Store APKINDEX.tar.gz as RepositoryFile (not parsed)
- Implement MIRROR mode for Alpine repositories
- Preserve signatures and metadata exactly as upstream
- Full repository replication without content parsing

**Why Important:** Enables exact Alpine repository mirrors for air-gapped environments

**Dependencies:** Milestone 8 (Alpine APK) ✅ - Already completed

**Estimated Effort:** 2-3 days

---

### 📋 Milestone 15: Helm Mirror Mode Support

**GitHub Issue:** [#27](https://github.com/slauger/chantal/issues/27)

**Status:** Planned

**Scope:**
- Store index.yaml as RepositoryFile (not parsed)
- Implement MIRROR mode for Helm repositories
- Preserve signatures and metadata exactly as upstream
- Full repository replication without chart parsing

**Why Important:** Enables exact Helm repository mirrors for air-gapped environments

**Dependencies:** Milestone 7 (Helm) ✅ - Already completed

**Estimated Effort:** 2-3 days

---

### 📋 Milestone 16: Example Configurations

**GitHub Issue:** [#3](https://github.com/slauger/chantal/issues/3)

**Status:** Planned

**Scope:**
- Example configs for popular Linux distributions
  - RHEL 8/9 (BaseOS, AppStream, CRB)
  - CentOS Stream
  - Rocky Linux
  - AlmaLinux
  - Fedora
  - Alpine Linux
- Third-party repositories
  - EPEL
  - Docker CE
  - GitLab Runner
  - PostgreSQL
  - Zabbix, Grafana, Hashicorp, etc.
- Helm chart repositories
- Best practices documentation
- Quick-start templates

**Why Important:** Reduces setup time for new users

**Dependencies:** None

**Estimated Effort:** 2-3 days

---

### 📋 Milestone 17: APT/DEB Repository Support

**GitHub Issue:** [#1](https://github.com/slauger/chantal/issues/1)

**Status:** Planned

**Scope:**
- APT plugin implementation
- InRelease/Release parsing
- Packages.gz/xz parsing
- GPG signature preservation
- deb package handling
- APT publishing (standard APT repo structure)
- Content-addressed storage for debs
- Ubuntu/Debian repository sync
- MIRROR, FILTERED, HOSTED modes

**Why Important:** Extends Chantal to Debian/Ubuntu ecosystem

**Dependencies:** Generic ContentItem model ✅ (already implemented)

**Estimated Effort:** 2 weeks

---

### 📋 Milestone 18: Advanced Errata & Advisory Management

**GitHub Issue:** [#21](https://github.com/slauger/chantal/issues/21)

**Status:** Planned

**Scope:**
- Dedicated Advisory/Errata database models
- Enhanced CVE tracking and metadata
- External errata sources (AlmaLinux CEFS, Rocky RLSA, Oracle ELSA)
- Advisory search and filtering
- Errata-based snapshot diff
- Security bulletin generation

**Why Important:** Advanced security patch management for enterprise environments

**Dependencies:** Current updateinfo.xml support ✅ (already implemented)

**Estimated Effort:** 1-2 weeks

---

## Future Milestones

### 📋 Milestone 19: Zstandard Compression Support
**GitHub Issue:** [#23](https://github.com/slauger/chantal/issues/23)
**Effort:** 3-5 days
**Scope:** Support .zst compressed RPM metadata files (Fedora 31+, RHEL 9+)

### 📋 Milestone 20: PyPI Support
**GitHub Issue:** [#5](https://github.com/slauger/chantal/issues/5)
**Effort:** 2 weeks
**Scope:** Python package repository mirroring and hosting

### 📋 Milestone 21: npm/yarn Support
**GitHub Issue:** [#7](https://github.com/slauger/chantal/issues/7)
**Effort:** 2 weeks
**Scope:** Node.js package repository mirroring and hosting

### 📋 Milestone 22: Additional Package Formats
**GitHub Issues:**
- [#6](https://github.com/slauger/chantal/issues/6) - RubyGems
- [#8](https://github.com/slauger/chantal/issues/8) - NuGet
- [#9](https://github.com/slauger/chantal/issues/9) - Go Modules
- [#10](https://github.com/slauger/chantal/issues/10) - Terraform Providers
**Effort:** 1-2 weeks each

### 📋 Milestone 23: SUSE/SLES Extensions
**GitHub Issue:** [#11](https://github.com/slauger/chantal/issues/11)
**Effort:** 1 week
**Scope:** SUSE-specific repository features and patterns

---

## Long-Term Vision (v2.0+)

### Advanced Features
- REST API (optional)
- Web UI (read-only monitoring)
- Prometheus metrics export
- Automated scheduling (cron integration)
- Webhook notifications
- Multi-tenancy support

### Performance & Scale
- Parallel sync optimization
- Database query optimization
- Large-scale repository handling (100k+ packages)
- Bandwidth limiting
- Resume support for interrupted syncs

### Enterprise Features
- RBAC and authentication
- Audit logging
- Policy enforcement
- Air-gapped sync (export/import)
- High availability setup

---

## Priority Guidance

**Recommended Order:**
1. **Milestone 14/15** (APK/Helm Mirror Mode) - Quick wins, complete existing plugin features
2. **Milestone 16** (Example Configs) - Reduces friction for new users
3. **Milestone 19** (Zstandard Support) - Needed for modern Fedora/RHEL 9
4. **Milestone 17** (APT/DEB) - Major ecosystem expansion
5. **Milestone 18** (Advanced Errata) - Enhanced security management

**User-Driven Priorities:**
- If you need air-gapped mirrors → Milestones 14/15 first
- If you need Debian/Ubuntu support → Milestone 17 first
- If you need advanced security features → Milestone 18 first
- If you use Fedora 31+/RHEL 9+ → Milestone 19 first

---

## How to Contribute

1. Check this roadmap for planned features
2. Review [GitHub Issues](https://github.com/slauger/chantal/issues)
3. Comment on issues you're interested in
4. Submit pull requests

---

## Release Timeline

**v0.1.0** (Released: 2026-01-12)
- RPM, Helm, Alpine APK support
- Mirror, filtered, and hosted modes
- Snapshots and views
- 102 tests passing
- Production-ready for multi-format use cases

**v0.2.0** (Target: Q1 2026)
- APK/Helm mirror mode support
- Example configurations for popular distros
- Zstandard compression support
- Documentation improvements

**v0.3.0** (Target: Q2 2026)
- APT/DEB support
- Advanced errata/advisory management
- PyPI support (maybe)

**v1.0.0** (Target: Q3 2026)
- Multiple package formats (RPM, DEB, Helm, APK, PyPI)
- Production-grade stability
- Comprehensive documentation
- Performance optimization

---

## Questions?

See [GitHub Issues](https://github.com/slauger/chantal/issues) or open a new issue.
