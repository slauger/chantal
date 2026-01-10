# Chantal Development Status

**Last Updated:** 2026-01-10
**Version:** 0.1.0-dev

---

## Current Milestone

**🔄 Milestone 6: Database Management & Operations** ([#14](https://github.com/slauger/chantal/issues/14))

**Status:** In Progress

**Next Tasks:**
- Implement `chantal db stats` command
- Implement `chantal db vacuum` command
- Implement `chantal db export/import` commands
- Add database integrity verification

---

## Completed Milestones

### ✅ Milestone 1: Foundation & Configuration

**Completed:** 2026-01-10 ([#15](https://github.com/slauger/chantal/issues/15))

**Achievements:**
- Generic ContentItem model with JSON metadata (type-safe via Pydantic)
- Pydantic configuration system (GlobalConfig, RepositoryConfig, ViewConfig)
- YAML loading with `include` support
- SQLAlchemy 2.0 database models
- Alembic migrations
- 15 configuration tests passing

**Files:**
- `src/chantal/core/config.py` - Configuration management
- `src/chantal/db/models.py` - Database models
- `alembic/versions/*` - Database migrations

---

### ✅ Milestone 2: Content-Addressed Storage

**Completed:** 2026-01-10 ([#15](https://github.com/slauger/chantal/issues/15))

**Achievements:**
- Universal SHA256-based storage pool
- 2-level directory structure (ab/cd/sha256_filename)
- Content-addressed deduplication (packages stored once)
- Hardlink-based publishing (zero-copy)
- Pool statistics and orphaned file cleanup
- 15 storage tests passing

**Files:**
- `src/chantal/core/storage.py` - Storage manager

---

### ✅ Milestone 3: RPM Plugin & Sync

**Completed:** 2026-01-10

**Achievements:**
- RPM repository sync (repomd.xml, primary.xml.gz)
- RHEL CDN authentication (client certificates)
- Package metadata extraction
- Pattern-based filtering (include/exclude)
- Architecture filtering
- Post-processing (only_latest_version)
- Progress tracking
- 14 publisher tests passing

**Files:**
- `src/chantal/plugins/rpm/__init__.py` - RPM syncer
- `src/chantal/plugins/rpm/models.py` - RPM metadata model

---

### ✅ Milestone 4: Snapshots

**Completed:** 2026-01-10

**Achievements:**
- Immutable point-in-time snapshots
- Snapshot creation from current repository state
- Snapshot publishing
- Snapshot diff (compare two snapshots)
- Snapshot copy (for promotion workflows: testing → stable)
- Database-backed snapshot tracking
- Zero-copy operations (only DB references, no file copies)

**Commands:**
- `chantal snapshot create --repo-id X --name Y`
- `chantal snapshot list [--repo-id X]`
- `chantal snapshot show --name X`
- `chantal snapshot diff --repo-id X --from A --to B`
- `chantal snapshot copy --repo-id X --source A --target B`
- `chantal publish snapshot --name X`

---

### ✅ Milestone 5: Views & Advanced Publishing

**Completed:** 2026-01-10

**Achievements:**
- Views (virtual repositories combining multiple repos)
- View configuration via YAML
- View publishing directly from config (no DB sync needed)
- View snapshots (atomic multi-repo snapshots)
- ViewPublisher plugin
- NO deduplication in views (client decides which package version to use)
- 10 view tests passing

**Commands:**
- `chantal view list`
- `chantal view show --name X`
- `chantal publish view --name X`

**Files:**
- `src/chantal/plugins/view_publisher.py` - View publisher
- `.dev/conf.d/views.yaml` - Example view configuration

---

## Test Status

**Total:** 74 tests passing ✅

**Breakdown:**
- CLI tests: 11 passing
- Config tests: 15 passing
- Database tests: 7 passing
- Publisher tests: 14 passing
- Storage tests: 15 passing
- View tests: 10 passing
- Integration tests: 2 passing

**Coverage:** Core components well-tested

---

## Technical Stack

**Language:** Python 3.10+

**Core Dependencies:**
- SQLAlchemy 2.0 (database ORM)
- Alembic (migrations)
- Click (CLI framework)
- Pydantic (configuration validation)
- PyYAML (config parsing)
- Requests (HTTP client)

**RPM-Specific:**
- lxml (XML parsing)
- defusedxml (safe XML parsing)

**Testing:**
- pytest
- pytest-cov (coverage)

**Development:**
- mypy (type checking)
- black (formatting)
- ruff (linting)

---

## Database Schema

**Current Schema Version:** `a4a922fdfc63` (Generic ContentItem model)

**Main Tables:**
- `repositories` - Repository configurations
- `content_items` - Generic content (RPM, DEB, Helm, PyPI, etc.)
- `snapshots` - Immutable snapshots
- `views` - Virtual repository definitions
- `view_snapshots` - Atomic view snapshots

**Junction Tables:**
- `repository_content_items` - M:N (Repository ↔ ContentItem)
- `snapshot_content_items` - M:N (Snapshot ↔ ContentItem)
- `view_repositories` - M:N (View ↔ Repository, with order)

---

## File Structure

```
chantal/
├── src/chantal/
│   ├── __init__.py
│   ├── cli/
│   │   └── main.py              # CLI commands (Click)
│   ├── core/
│   │   ├── config.py            # Configuration management
│   │   └── storage.py           # Content-addressed storage
│   ├── db/
│   │   ├── models.py            # SQLAlchemy models
│   │   └── connection.py        # Database manager
│   └── plugins/
│       ├── rpm/
│       │   ├── __init__.py      # RPM syncer
│       │   └── models.py        # RPM metadata (Pydantic)
│       └── view_publisher.py    # View publisher
├── tests/
│   ├── test_cli.py
│   ├── test_config.py
│   ├── test_db_models.py
│   ├── test_publisher.py
│   ├── test_storage.py
│   └── test_views.py
├── alembic/
│   └── versions/                # Database migrations
├── .dev/
│   ├── config.yaml              # Dev configuration
│   └── conf.d/
│       ├── repositories.yaml    # Repository configs
│       └── views.yaml           # View configs
├── examples/
│   └── rpm/                     # Example RPM configs
├── pyproject.toml
├── README.md
├── ROADMAP.md                   # Development roadmap
└── TODO.md                      # Archived (see ROADMAP.md)
```

---

## CLI Commands

### Working Commands

**Repository Management:**
```bash
chantal repo list
chantal repo show --repo-id <id>
chantal repo sync --repo-id <id>
chantal repo check-updates --repo-id <id>
```

**Snapshot Management:**
```bash
chantal snapshot create --repo-id <id> --name <name>
chantal snapshot list [--repo-id <id>]
chantal snapshot show --name <name>
chantal snapshot diff --repo-id <id> --from <snap1> --to <snap2>
chantal snapshot copy --repo-id <id> --source <snap1> --target <snap2>
```

**View Management:**
```bash
chantal view list
chantal view show --name <name>
```

**Publishing:**
```bash
chantal publish repo --repo-id <id>
chantal publish snapshot --name <name>
chantal publish view --name <name>
```

**Package Management:**
```bash
chantal package list --repo-id <id>
chantal package show --sha256 <hash>
```

**System:**
```bash
chantal init
chantal --version
```

### Planned Commands

**Database Management:** (Milestone 6)
```bash
chantal db stats
chantal db vacuum
chantal db export [--output <file>]
chantal db import <file>
chantal db verify
```

---

## Known Issues

**None** - All 74 tests passing

---

## Next Steps

1. **Implement database management commands** ([#14](https://github.com/slauger/chantal/issues/14))
   - `chantal db stats`, `vacuum`, `export`, `import`, `verify`

2. **Errata/Advisory Support** ([#12](https://github.com/slauger/chantal/issues/12), [#13](https://github.com/slauger/chantal/issues/13))
   - Parse updateinfo.xml
   - External errata sources (AlmaLinux, Rocky)
   - CVE tracking

3. **Example Configurations** ([#3](https://github.com/slauger/chantal/issues/3))
   - RHEL, CentOS, Fedora configs
   - Third-party repo configs

4. **APT/DEB Support** ([#1](https://github.com/slauger/chantal/issues/1))
   - APT plugin
   - Debian/Ubuntu repository sync

5. **Helm Support** ([#2](https://github.com/slauger/chantal/issues/2))
   - Helm chart repository plugin

---

## Recent Commits

```
7aeab62 - Implement view publishing from config and snapshot copy feature
f1cccd1 - Implement configuration management and storage system (Milestone 1 & 2)
```

---

## Progress Summary

**Overall Progress:** ~60% of core MVP complete

**Milestones:**
- ✅ Milestone 1: Foundation (100%)
- ✅ Milestone 2: Storage (100%)
- ✅ Milestone 3: RPM Plugin (100%)
- ✅ Milestone 4: Snapshots (100%)
- ✅ Milestone 5: Views (100%)
- 🔄 Milestone 6: DB Management (20%)

**Next Major Milestone:** APT/DEB Support (Milestone 9)

---

**Last Session:** Generic ContentItem migration, view publishing refactor, snapshot copy feature
**Next Session:** Database management commands implementation
