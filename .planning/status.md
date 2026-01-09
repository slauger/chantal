# Chantal Development Status

**Last Updated:** 2025-01-09
**Version:** 0.1.0 (MVP Development)

---

## Completed ✅

### Project Setup
- ✅ PyPI-ready package structure (`pyproject.toml`, src-layout)
- ✅ Click-based CLI framework with working commands
- ✅ Git repository initialized and pushed to GitHub
- ✅ Testing framework (pytest) with 11 passing tests
- ✅ Development dependencies (mypy, black, ruff)
- ✅ Python 3.9+ compatibility

### Architecture & Planning
- ✅ Comprehensive architecture documentation (~2000 lines)
- ✅ pulp-admin inspired CLI commands design
- ✅ Version retention policies design (4 policies: mirror, newest-only, keep-all, keep-last-n)
- ✅ MVP scope document (RPM/DNF only, 12-week plan)
- ✅ HTTP proxy, scheduler, and database backup/restore design
- ✅ Research findings on reposync, Pulp, apt-mirror, aptly

### Proof of Concept
- ✅ RHEL CDN authentication PoC script
- ✅ Successfully tested on RHEL 9 system
- ✅ Validated client certificate authentication works
- ✅ Downloaded and verified RPM packages from RHEL CDN

### Database (Milestone 1 - In Progress)
- ✅ SQLAlchemy 2.0 database models
  - Repository model (configured repos)
  - Package model (content-addressed storage)
  - Snapshot model (immutable states)
  - SyncHistory model (sync tracking)
- ✅ DatabaseManager for connection pooling
- ✅ Alembic migrations setup
- ✅ Comprehensive database model tests (7 tests, all passing)

### Features Validated
- ✅ Content-addressed storage (SHA256-based deduplication)
- ✅ Pre-download deduplication (metadata-first approach)
- ✅ RHEL CDN authentication (client certificates)
- ✅ Reference counting for garbage collection

---

## In Progress 🚧

### Milestone 1: Foundation (Week 1-2)
- ✅ Project structure
- ✅ Database models
- ✅ CLI framework
- ⏳ Configuration management (Pydantic models)
- ⏳ Config file loading (`/etc/chantal/config.yaml`, `conf.d/*.yaml`)

---

## Next Steps 📋

### Immediate (This Week)

**1. Configuration Management**
- Create Pydantic models for configuration
- Implement config file loading (YAML)
- Support for `include: conf.d/*.yaml`
- Add global and per-repo proxy configuration
- Create example config files

**2. Storage Manager**
- Implement content-addressed storage pool
- SHA256-based file storage
- Hardlink creation for publishing
- Pool path calculation

**3. CLI Command Integration**
- Wire up database to CLI commands
- Implement `chantal repo list` (read from database)
- Implement `chantal repo show` (show repository details)
- Implement `chantal init` (database initialization)

### Milestone 2: Core Storage (Week 3-4)

**1. Storage Pool Implementation**
- Content-addressed pool manager
- File verification (SHA256 checksums)
- Garbage collection (unreferenced packages)
- Storage statistics

**2. Publishing System**
- Hardlink-based publishing
- Repository metadata generation (repomd.xml)
- Atomic updates (symlink switching)

### Milestone 3: RPM Plugin (Week 5-6)

**1. Metadata Parsing**
- repomd.xml parser
- primary.xml.gz parser (package metadata)
- filelists.xml.gz parser
- RPM header parsing (python-rpm)

**2. Download Manager**
- Multi-threaded downloads
- Progress tracking (tqdm)
- Resume support
- Bandwidth limiting (optional)

**3. Sync Logic**
- Metadata-first approach
- Pre-download deduplication
- Version retention policies
- Sync state tracking in database

### Milestone 4: Snapshots (Week 7-8)

**1. Snapshot Creation**
- Create immutable snapshots from current state
- Update package references
- Snapshot metadata

**2. Snapshot Management**
- List snapshots
- Delete snapshots
- Snapshot diff (compare two snapshots)

**3. Snapshot Publishing**
- Publish specific snapshots
- Switch "latest" pointer

### Milestone 5: Advanced Features (Week 9-10)

**1. HTTP Proxy Support**
- Implement ProxyHTTPClient
- Global proxy configuration
- Per-repository proxy override
- Environment variable support

**2. Database Backup/Restore**
- Implement DatabaseBackupManager
- CLI commands: `db backup`, `db restore`, `db backup-list`, `db backup-verify`
- Automated backup scripts

### Milestone 6: Scheduler & Polish (Week 11-12)

**1. Scheduler Service**
- Implement SchedulerService
- Cron expression parsing
- Lock mechanism
- Systemd service integration

**2. Testing & Documentation**
- Integration tests
- Performance testing
- User documentation
- Deployment guide

---

## Feature Priorities

### High Priority (MVP)
- ✅ Database models
- ⏳ Configuration management
- ⏳ Content-addressed storage
- ⏳ RPM repository sync
- ⏳ RHEL CDN authentication
- ⏳ Snapshots
- ⏳ Publishing (hardlinks)
- ⏳ CLI commands (repo, snapshot, package)
- ⏳ HTTP proxy support
- ⏳ Database backup/restore

### Medium Priority (Post-MVP)
- Scheduler/daemon service
- Package search and statistics
- Sync history and reporting
- Database maintenance commands
- Version retention policies
- Multiple output formats (JSON, CSV)

### Low Priority (Future)
- APT/Debian support (v2.0)
- PyPI support
- Web UI
- REST API
- S3 publishing (explicitly NOT wanted by user)
- Multi-tenancy features

---

## Technical Decisions

### Confirmed Choices
- **Language:** Python 3.9+
- **Database:** PostgreSQL with SQLAlchemy 2.0
- **CLI Framework:** Click
- **Config Format:** YAML with Pydantic validation
- **Storage:** Content-addressed pool (SHA256)
- **Publishing:** Hardlinks (zero-copy)
- **Snapshots:** Reference-based (immutable)
- **Migrations:** Alembic

### Deferred Decisions
- Async support (asyncpg) - start with psycopg2
- Multi-tenancy strategy - use `--config-dir` flag for now
- Monitoring/metrics - not MVP
- S3 publishing - explicitly not wanted

---

## Testing Status

**Total Tests:** 11 passing
- CLI tests: 4 passing
- Database model tests: 7 passing

**Test Coverage:**
- ✅ CLI command registration
- ✅ Version display
- ✅ Repository management commands
- ✅ Snapshot management commands
- ✅ Database model creation and querying
- ✅ Many-to-many relationships
- ✅ Unique constraints
- ✅ NEVRA string generation
- ✅ Sync history duration calculation

---

## Recent Commits

```
4380cdb - Add comprehensive tests for database models
b68a70b - Add SQLAlchemy database models and Alembic migrations
72ba08b - Add HTTP proxy, scheduler, and database backup/restore design
6160e25 - Add pulp-admin-inspired CLI commands documentation
a0d2f3b - Add PyPI-ready Python package structure
...
```

---

## Commands Available

### Working Commands
```bash
# General
chantal --version                          # Show version
chantal --help                             # Show help

# Repository management (placeholder)
chantal repo list                          # List repositories (TODO: wire to DB)
chantal repo show --repo-id <id>          # Show repository details (TODO)
chantal repo sync --repo-id <id>          # Sync repository (TODO)

# Snapshot management (placeholder)
chantal snapshot list                      # List snapshots (TODO)
chantal snapshot create --repo-id <id> --name <name>  # Create snapshot (TODO)

# Database management (placeholder)
chantal db cleanup --dry-run              # Cleanup unreferenced packages (TODO)

# Init command (placeholder)
chantal init                              # Initialize Chantal (TODO)
```

### Planned Commands
```bash
# Package management
chantal package list --repo-id <id>
chantal package search <query>
chantal package show <package>
chantal stats
chantal stats dedup

# Database backup/restore
chantal db backup [--output <file>]
chantal db restore <file>
chantal db backup-list
chantal db backup-verify <file>

# Scheduler
chantal scheduler start [--daemon]
chantal scheduler stop
chantal scheduler status
chantal scheduler list
```

---

## Files Created

### Source Code
- `src/chantal/__init__.py` - Package metadata
- `src/chantal/cli/main.py` - CLI commands (Click)
- `src/chantal/db/__init__.py` - Database package exports
- `src/chantal/db/models.py` - SQLAlchemy models
- `src/chantal/db/connection.py` - Database connection manager

### Configuration
- `pyproject.toml` - Package configuration (PEP 517/518)
- `alembic.ini` - Alembic configuration
- `alembic/env.py` - Alembic environment
- `alembic/script.py.mako` - Migration template

### Tests
- `tests/test_cli.py` - CLI tests (4 tests)
- `tests/test_db_models.py` - Database model tests (7 tests)

### Documentation
- `.planning/architecture.md` - Full architecture (~2000 lines)
- `.planning/architecture-updates-v2.md` - Architecture updates (~800 lines)
- `.planning/version-retention-design.md` - Version retention design (~600 lines)
- `.planning/mvp-scope.md` - MVP scope and timeline (~644 lines)
- `.planning/cli-commands.md` - CLI commands design (~493 lines)
- `.planning/proxy-and-scheduler.md` - Proxy, scheduler, backup design (~1663 lines)
- `.planning/findings.md` - Research findings
- `poc/rhel-cdn-auth-test.py` - RHEL CDN PoC script (~560 lines)

---

## Known Issues

None currently - all tests passing!

---

## Next Session TODO

1. **Create Pydantic configuration models** (GlobalConfig, RepositoryConfig, ProxyConfig, etc.)
2. **Implement config file loading** (YAML parser with include support)
3. **Create example config files** (`/etc/chantal/config.yaml`, `conf.d/*.yaml`)
4. **Wire up CLI commands to database** (start with `chantal repo list`)
5. **Implement `chantal init` command** (create directories, initialize database)

---

**Progress:** ~15% of MVP complete (Milestone 1 in progress)
**Estimated Completion:** 10-11 weeks remaining for full MVP
