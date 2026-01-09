# Chantal MVP Scope - RPM/DNF Focus

**Version:** 1.0
**Datum:** 2025-01-09
**Ziel:** Minimum Viable Product nur für RPM/DNF Repositories

---

## MVP-Philosophie

**"Do one thing well"** - Erst RPM perfekt, dann APT.

### In Scope (MVP)

✅ RPM/DNF Repository Sync
✅ RHEL Subscription-Auth (Client-Zertifikate)
✅ Content-Addressed Storage (Deduplikation)
✅ Snapshots (Immutable Repository-Versionen)
✅ Version-Retention Policies
✅ Latest + Snapshot Publishing
✅ CLI-Interface (Pulp-style)
✅ PostgreSQL Database
✅ Modular Config

### Out of Scope (Post-MVP)

❌ APT/Debian Support (v2.0)
❌ PyPI Support (Future)
❌ REST API (Future)
❌ Web UI (Future)
❌ S3 Publishing (Future)
❌ Monitoring/Metrics (Future)
❌ Multi-Tenancy (Future)

---

## MVP Feature-Set

### 1. Repository Management

**Commands:**
```bash
chantal repo list
chantal repo sync --repo-id <name>
chantal repo sync --repo-id <name> --create-snapshot
chantal repo show --repo-id <name>
```

**Features:**
- Sync RPM repositories from upstream
- Support für RHEL CDN (Client-Cert Auth)
- Support für Standard HTTP/HTTPS Repos
- Parallel Downloads (konfigurierbar)
- Resume bei Unterbrechung
- Progress-Anzeige (tqdm)

**Config:**
```yaml
# /etc/chantal/conf.d/rhel9-baseos.yaml
name: rhel9-baseos
type: rpm
enabled: true

upstream:
  url: https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os

credentials:
  type: client_cert
  cert: /etc/pki/entitlement/123.pem
  key: /etc/pki/entitlement/123-key.pem
  ca_cert: /etc/rhsm/ca/redhat-uep.pem

rpm:
  architectures: [x86_64]
  gpgcheck: true
  gpgkey_url: https://access.redhat.com/security/data/fd431d51.txt

retention:
  policy: mirror
  deleted_packages: remove

publish:
  latest_path: /var/www/repos/rhel9-baseos/latest
  snapshots_path: /var/www/repos/rhel9-baseos/snapshots
```

### 2. Storage

**Content-Addressed Pool:**
```
/var/lib/chantal/
└── data/
    └── sha256/
        ├── ab/cd/abcdef123...456_package-1.0.rpm
        └── ...
```

**Deduplikation:**
- SHA256-basierte Deduplikation
- Package wird nur einmal gespeichert
- Hardlinks für Published Repos

**Database:**
- PostgreSQL mit SQLAlchemy 2.0
- Tables: packages, repositories, snapshots, sync_history
- Indizes für Performance

### 3. Snapshots

**Commands:**
```bash
chantal snapshot create --repo-id <name> --name <snapshot-name>
chantal snapshot list
chantal snapshot list --repo-id <name>
chantal snapshot show --name <snapshot-name>
chantal snapshot delete --name <snapshot-name>
chantal snapshot diff --from <snap1> --to <snap2>
```

**Features:**
- Immutable Repository-Snapshots
- Reference-basiert (keine File-Kopien)
- Separate Publishing-Pfade
- Diff zwischen Snapshots

**Use-Case:**
```bash
# Daily sync to "latest"
chantal repo sync --repo-id rhel9-baseos

# Monthly snapshot for production
chantal snapshot create --repo-id rhel9-baseos --name 2025-01-patch

# Clients können dann wählen:
# - latest: http://mirror/rhel9-baseos/latest/
# - snapshot: http://mirror/rhel9-baseos/snapshots/2025-01-patch/
```

### 4. Version Retention Policies

**Policies (MVP):**

1. **mirror** (Default)
   - Exakt was Upstream hat
   - Löscht wenn Upstream löscht

2. **newest-only**
   - Nur neueste Version jedes Paketes
   - Wie EPEL

3. **keep-all**
   - Alle Versionen akkumulieren
   - Nie löschen

**Config:**
```yaml
retention:
  policy: mirror  # or: newest-only, keep-all
  deleted_packages: keep  # or: remove
```

**Post-MVP:**
- ❌ `keep-last-n` (später)

### 5. CLI Interface

**Main Commands (MVP):**

```bash
# Init
chantal init

# Repository
chantal repo list
chantal repo sync --repo-id <name>
chantal repo sync --repo-id <name> --create-snapshot --snapshot-name <name>
chantal repo show --repo-id <name>

# Snapshot
chantal snapshot create --repo-id <name> --name <name>
chantal snapshot list
chantal snapshot list --repo-id <name>
chantal snapshot show --name <name>
chantal snapshot delete --name <name>
chantal snapshot diff --from <snap1> --to <snap2>

# Database
chantal db cleanup
chantal db migrate
```

**Post-MVP Commands:**
- ❌ `chantal snapshot merge` (später)
- ❌ `chantal publish` (explizites Publishing, MVP macht auto-publish)
- ❌ `chantal repo sync --all` (später)

### 6. Configuration

**Struktur:**
```
/etc/chantal/
├── config.yaml          # Main config mit include
└── conf.d/
    ├── 00-global.yaml   # Global settings
    ├── 10-rhel9-baseos.yaml
    └── 20-epel9.yaml
```

**Global Config:**
```yaml
# /etc/chantal/config.yaml
include: conf.d/*.yaml

storage:
  base_path: /var/lib/chantal

database:
  url: postgresql://chantal:password@localhost/chantal

download:
  workers: 10
  retries: 5
  timeout: 300
```

**Post-MVP:**
- ❌ Environment-Variable-Substitution (später)
- ❌ Config-Validation CLI (`chantal config validate`)

### 7. Authentication

**Supported (MVP):**

1. **Client Certificates** (RHEL CDN)
   ```yaml
   credentials:
     type: client_cert
     cert: /path/to/cert.pem
     key: /path/to/key.pem
     ca_cert: /path/to/ca.pem
   ```

2. **HTTP Basic Auth**
   ```yaml
   credentials:
     type: basic
     username: user
     password: pass
   ```

3. **No Auth** (Public Repos)
   ```yaml
   credentials:
     type: none
   ```

**Post-MVP:**
- ❌ `subscription_manager` auto-discovery (später)
- ❌ `password_command` (External password manager)
- ❌ Keyring-Integration

### 8. Publishing

**MVP:**
- Auto-Publish nach jedem Sync
- Hardlinks von Pool nach Published Repo
- Metadata-Kopie (repodata/)
- Atomic-Switch (temp → live)

**Filesystem-Layout:**
```
/var/www/repos/
└── rhel9-baseos/
    ├── latest/
    │   ├── Packages/
    │   └── repodata/
    └── snapshots/
        ├── 2025-01-patch1/
        │   ├── Packages/
        │   └── repodata/
        └── 2025-01-patch2/
```

**Post-MVP:**
- ❌ GPG-Signing von repomd.xml (später)
- ❌ S3 Publishing
- ❌ Explizites Publishing (`chantal publish`)

---

## Technical Stack (MVP)

### Python Packages

**Core:**
- Python 3.11+
- click (CLI)
- pydantic (Config Validation)
- pyyaml (Config Parsing)

**Database:**
- sqlalchemy >= 2.0
- psycopg2-binary (PostgreSQL Driver)
- alembic (Migrations)

**HTTP:**
- requests (Sync Downloads)
- urllib3 (Retry Logic)

**RPM:**
- python-rpm-spec (RPM Parsing) - oder direkt XML parsen
- createrepo_c (System-Tool für Metadata-Generation)

**Progress:**
- tqdm (Progress Bars)
- rich (Terminal Output) - Optional

### System Dependencies

```bash
# RHEL/CentOS
sudo dnf install postgresql python3-devel createrepo_c

# Database
sudo postgresql-setup --initdb
sudo systemctl enable --now postgresql
```

### Python Package Structure

```
chantal/
├── chantal/
│   ├── __init__.py
│   ├── cli/
│   │   ├── __init__.py
│   │   └── main.py          # Click CLI
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py        # Config Loading
│   │   ├── engine.py        # Main Engine
│   │   ├── storage.py       # Content-Addressed Storage
│   │   ├── download.py      # Download Manager
│   │   ├── repository.py    # Repo Manager
│   │   └── snapshot.py      # Snapshot Manager
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py        # SQLAlchemy Models
│   │   └── queries.py       # Database Queries
│   └── plugins/
│       ├── __init__.py
│       ├── base.py          # Plugin Interface
│       └── rpm/
│           ├── __init__.py
│           └── plugin.py    # RPM Plugin
├── tests/
│   ├── test_storage.py
│   ├── test_rpm_plugin.py
│   └── integration/
├── poc/
│   └── rhel-cdn-auth-test.py
├── pyproject.toml
├── README.md
└── LICENSE
```

---

## MVP Milestones

### Milestone 1: Foundation (Week 1-2)

- [x] Architecture Design
- [x] PoC: RHEL CDN Auth
- [ ] Project Setup (Poetry, Package Structure)
- [ ] Database Models (SQLAlchemy)
- [ ] Config Loading (Pydantic + YAML)
- [ ] CLI Skeleton (Click)

**Deliverable:** `chantal --version` funktioniert, DB-Schema erstellt

### Milestone 2: Core Storage (Week 3-4)

- [ ] Content-Addressed Storage
  - SHA256-basierte Pool-Struktur
  - Deduplikation-Logic
  - Hardlink-Creation
- [ ] Download Manager
  - HTTP Client mit Requests
  - Client-Cert Auth
  - Retry Logic
  - Resume Support
- [ ] Basic Database Operations
  - Package CRUD
  - Repository CRUD

**Deliverable:** Package kann gespeichert und dedupliziert werden

### Milestone 3: RPM Plugin (Week 5-6)

- [ ] repomd.xml Parser
- [ ] primary.xml.gz Parser
- [ ] RPM Download Logic
- [ ] Metadata-Extraktion
- [ ] Publishing Logic
  - Hardlinks erstellen
  - createrepo_c aufrufen
- [ ] Basic CLI Commands
  - `chantal repo sync --repo-id <name>`

**Deliverable:** RHEL 9 BaseOS komplett syncbar

### Milestone 4: Snapshots (Week 7-8)

- [ ] Snapshot-Manager
- [ ] Snapshot Creation
- [ ] Snapshot Publishing
- [ ] Snapshot CLI Commands
  - `chantal snapshot create`
  - `chantal snapshot list`
  - `chantal snapshot show`
- [ ] Snapshot Diff

**Deliverable:** Snapshots funktionieren, Rollback möglich

### Milestone 5: Retention Policies (Week 9-10)

- [ ] Policy-Engine
  - mirror
  - newest-only
  - keep-all
- [ ] Deleted Package Handling
- [ ] Database-Tracking
  - last_seen_in_upstream
  - marked_for_deletion
- [ ] Cleanup Command
  - `chantal db cleanup`

**Deliverable:** EPEL mit newest-only syncbar

### Milestone 6: Testing & Polish (Week 11-12)

- [ ] Unit Tests
  - Storage
  - Config
  - RPM Plugin
- [ ] Integration Tests
  - Full Sync Workflow
  - Snapshot Workflow
- [ ] Error Handling
- [ ] Logging
- [ ] Documentation
- [ ] Installation Guide

**Deliverable:** MVP 1.0 Release!

---

## Success Criteria (MVP)

### Functional

✅ **Sync RHEL 9 BaseOS** von Red Hat CDN mit Client-Zerts
✅ **Sync EPEL 9** mit newest-only Policy
✅ **Deduplikation** funktioniert (gleiche Pakete nur einmal)
✅ **Snapshots** erstellen und publishen
✅ **Rollback** via Snapshot-Switch
✅ **Resume** bei Sync-Unterbrechung

### Performance

✅ **Sync-Speed:** Min. 10 MB/s bei 100 Mbps Leitung
✅ **Parallel Downloads:** 10 parallel requests
✅ **Dedup-Speed:** < 1s pro Package für Hash-Check

### Reliability

✅ **Retry:** 5 Versuche bei Download-Fehlern
✅ **Atomic Publishing:** Kein partial state für Clients
✅ **Transaction-Safety:** DB-Rollback bei Fehlern

### Usability

✅ **CLI:** Intuitive Commands
✅ **Config:** YAML mit klaren Defaults
✅ **Errors:** Hilfreiche Fehlermeldungen
✅ **Progress:** Sichtbare Progress-Bars

---

## Post-MVP Roadmap

### v2.0: APT Support

- APT Plugin
- Debian/Ubuntu Repository Sync
- Packages.gz Parsing
- .deb Handling
- GPG-Signing für APT

### v3.0: Advanced Features

- REST API (Optional)
- Snapshot Merging
- `keep-last-n` Retention Policy
- Prometheus Metrics
- JSON Logging

### v4.0: Enterprise Features

- Multi-Tenancy
- RBAC/Authentication
- S3 Publishing
- Web UI (Read-Only)
- Webhook Notifications

---

## Known Limitations (MVP)

⚠️ **Nur RPM/DNF** - Kein APT Support
⚠️ **Kein GPG-Signing** - Metadata nicht signiert (später)
⚠️ **Nur PostgreSQL** - Kein SQLite Support
⚠️ **Keine REST API** - Nur CLI
⚠️ **Manual Snapshot Cleanup** - Kein Auto-Retention
⚠️ **Kein S3** - Nur lokales Filesystem

---

## Installation (MVP Target)

### Via PyPI (Ziel)

```bash
pip install chantal
chantal init
```

### Via Source

```bash
git clone https://github.com/slauger/chantal.git
cd chantal
poetry install
poetry run chantal init
```

### System Setup

```bash
# PostgreSQL
sudo dnf install postgresql-server
sudo postgresql-setup --initdb
sudo systemctl enable --now postgresql

# Create database
sudo -u postgres psql
CREATE DATABASE chantal;
CREATE USER chantal WITH PASSWORD 'chantal';
GRANT ALL PRIVILEGES ON DATABASE chantal TO chantal;

# Chantal Init
chantal init
```

---

## Documentation (MVP)

### Required Docs

- [ ] README.md (Getting Started)
- [ ] INSTALL.md (Installation Guide)
- [ ] CONFIG.md (Configuration Reference)
- [ ] CLI.md (CLI Command Reference)
- [ ] ARCHITECTURE.md (Technical Overview)
- [ ] CONTRIBUTING.md (Development Guide)

### Optional (Post-MVP)

- ❌ API.md (REST API Docs)
- ❌ DEPLOYMENT.md (Production Deployment)
- ❌ PERFORMANCE.md (Tuning Guide)

---

## Questions & Decisions

### Resolved

✅ **Sprache:** Python (nicht Rust)
✅ **Scope:** MVP nur RPM/DNF
✅ **Database:** PostgreSQL
✅ **CLI-Style:** Pulp-style mit `--repo-id`
✅ **Config:** Modular `/etc/chantal/conf.d/`
✅ **Snapshots:** Getrennt von latest
✅ **Retention:** mirror, newest-only, keep-all (MVP)

### Open

❓ **createrepo_c vs. Python-Implementation?**
   - MVP: createrepo_c (System-Tool)
   - Later: Pure Python? (Dependency-Freiheit)

❓ **GPG-Signing in MVP?**
   - Aktuell: Nein (Post-MVP)
   - Aber: GPG-Key-Download ja (für Clients)

❓ **Progress-Reporting Detail-Level?**
   - Package-Level? (Package 1/1000)
   - Byte-Level? (42 MB / 4.2 GB)
   - Beides?

❓ **Sync-Resume-Strategie?**
   - Partial File Resume (Range Requests)?
   - Oder nur Package-Level Skip?

---

## Success Metrics

### MVP Launch Criteria

- ✅ 100% Test Coverage für Core Components
- ✅ 3 Real-World Repos successfully synced
  - RHEL 9 BaseOS
  - RHEL 9 AppStream
  - EPEL 9
- ✅ Documentation Complete
- ✅ Installation Guide Tested
- ✅ 0 Critical Bugs
- ✅ Performance Benchmarks Met

### Community Adoption (Post-Launch)

- 10+ GitHub Stars (Week 1)
- 5+ Community Feedback/Issues
- 1+ External Contributor
- 100+ PyPI Downloads (Month 1)

---

**Status:** Ready for Implementation
**Next Step:** Milestone 1 - Foundation Setup
