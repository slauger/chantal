# Chantal Development Roadmap

**Last Updated:** 2026-01-10
**Current Version:** 0.1.0-dev

---

## Current Status

**✅ MVP Core Complete** - RPM mirroring with snapshots and views functional

- 74 tests passing
- Generic ContentItem model implemented
- Content-addressed storage working
- RPM sync, publish, snapshots, views operational
- RHEL CDN authentication working

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

---

## In Progress

### 🔄 Milestone 6: Database Management & Operations

**GitHub Issue:** [#14](https://github.com/slauger/chantal/issues/14)

**Status:** In Progress

**Remaining Tasks:**
- [ ] `chantal db stats` - Show database and pool statistics
- [ ] `chantal db vacuum` - Database maintenance
- [ ] `chantal db export` - Export database to JSON/YAML
- [ ] `chantal db import` - Import database from backup
- [ ] `chantal db verify` - Verify database integrity

**Why Important:** Operational commands for system administrators

**Estimated Completion:** 1-2 days

---

## Next Milestones

### 📋 Milestone 7: RPM Errata & Advisory Support

**GitHub Issues:**
- [#12](https://github.com/slauger/chantal/issues/12) - Errata/Advisory Data Integration (updateinfo.xml)
- [#13](https://github.com/slauger/chantal/issues/13) - Errata Import from External Sources

**Status:** Planned

**Scope:**
- Parse updateinfo.xml from RPM repositories
- Advisory model (RHSA, RHBA, RHEA)
- CVE tracking and metadata
- External errata sources (AlmaLinux CEFS, Rocky RLSA)
- Errata filtering and querying
- Integration with snapshot diff

**Why Important:** Critical for security patch management in enterprise environments

**Dependencies:** None

**Estimated Effort:** 1 week

---

### 📋 Milestone 8: Example Configurations

**GitHub Issue:** [#3](https://github.com/slauger/chantal/issues/3)

**Status:** Planned

**Scope:**
- Example configs for popular Linux distributions
  - RHEL 8/9 (BaseOS, AppStream, CRB)
  - CentOS Stream
  - Rocky Linux
  - AlmaLinux
  - Fedora
- Third-party repositories
  - EPEL
  - Docker CE
  - GitLab Runner
  - PostgreSQL
  - Zabbix, Grafana, Hashicorp, etc.
- Best practices documentation
- Quick-start templates

**Why Important:** Reduces setup time for new users

**Dependencies:** None

**Estimated Effort:** 2-3 days

---

### 📋 Milestone 9: APT/DEB Repository Support

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

**Why Important:** Extends Chantal to Debian/Ubuntu ecosystem

**Dependencies:** Generic ContentItem model ✅ (already implemented)

**Estimated Effort:** 2 weeks

---

### 📋 Milestone 10: Helm Chart Repository Support

**GitHub Issue:** [#2](https://github.com/slauger/chantal/issues/2)

**Status:** Planned

**Scope:**
- Helm plugin implementation
- index.yaml parsing
- Chart metadata extraction
- Chart versioning
- Helm repository publishing
- Content-addressed storage for charts

**Why Important:** Kubernetes/Helm is widely used in cloud-native environments

**Dependencies:** Generic ContentItem model ✅ (already implemented)

**Estimated Effort:** 1 week

---

## Future Milestones

### 📋 Milestone 11: PyPI Support
**GitHub Issue:** [#5](https://github.com/slauger/chantal/issues/5)
**Effort:** 2 weeks

### 📋 Milestone 12: Alpine APK Support
**GitHub Issue:** [#4](https://github.com/slauger/chantal/issues/4)
**Effort:** 1 week

### 📋 Milestone 13: npm/yarn Support
**GitHub Issue:** [#7](https://github.com/slauger/chantal/issues/7)
**Effort:** 2 weeks

### 📋 Milestone 14: Additional Package Formats
**GitHub Issues:**
- [#6](https://github.com/slauger/chantal/issues/6) - RubyGems
- [#8](https://github.com/slauger/chantal/issues/8) - NuGet
- [#9](https://github.com/slauger/chantal/issues/9) - Go Modules
- [#10](https://github.com/slauger/chantal/issues/10) - Terraform Providers
**Effort:** 1-2 weeks each

### 📋 Milestone 15: SUSE/SLES Extensions
**GitHub Issue:** [#11](https://github.com/slauger/chantal/issues/11)
**Effort:** 1 week

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
1. **Milestone 6** (DB Management) - Quick win, improves usability
2. **Milestone 7** (Errata/Advisories) - Critical for RHEL production use
3. **Milestone 8** (Example Configs) - Reduces friction for new users
4. **Milestone 9** (APT/DEB) - Major ecosystem expansion
5. **Milestone 10** (Helm) - Popular in cloud-native environments

**User-Driven Priorities:**
- If you need Debian/Ubuntu support → Milestone 9 first
- If you need Kubernetes/Helm → Milestone 10 first
- If you need security advisories → Milestone 7 first

---

## How to Contribute

1. Check this roadmap for planned features
2. Review [GitHub Issues](https://github.com/slauger/chantal/issues)
3. Comment on issues you're interested in
4. Submit pull requests

---

## Release Timeline

**v0.1.0** (Current)
- RPM mirroring with snapshots and views
- 74 tests passing
- Production-ready for RPM use cases

**v0.2.0** (Target: Q1 2025)
- Database management commands
- Errata/advisory support
- Example configurations
- Documentation improvements

**v0.3.0** (Target: Q2 2025)
- APT/DEB support
- Helm support
- PyPI support (maybe)

**v1.0.0** (Target: Q3 2025)
- Multiple package formats
- Production-grade stability
- Comprehensive documentation
- Performance optimization

---

## Questions?

See [GitHub Issues](https://github.com/slauger/chantal/issues) or open a new issue.
