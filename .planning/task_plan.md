# Task Plan: Chantal - Unified Repository Sync Tool

**Status:** Phase 6 (Milestone 6) - Database Management Commands
**Letzte Aktualisierung:** 2026-01-10 23:05

## Übersicht

Chantal ist ein Python CLI-Tool für das Spiegeln von Linux-Paket-Repositories (RPM, APT, PyPI, Helm, etc.) mit Content-Addressed Storage, Snapshots und Views.

**Aktueller Stand:** MVP für RPM komplett, 74 Tests passing, Generic ContentItem Model implementiert.

## Phasen

### Phase 1: Foundation & Configuration - ✅ Fertig
**Ziel:** Grundlegende Infrastruktur, Konfiguration, Datenbank-Schema

**Status:** Abgeschlossen am 2026-01-10 (Issue #15)

Aufgaben:
- [x] Project Setup (Poetry, Package Structure)
- [x] Database Models (SQLAlchemy 2.0)
- [x] Generic ContentItem Model mit JSON Metadata
- [x] Pydantic Configuration System
- [x] YAML Loading mit `include` Support
- [x] CLI Skeleton (Click)
- [x] Alembic Migrations
- [x] 15 Configuration Tests

**Ergebnis:** Milestone 1 komplett

---

### Phase 2: Content-Addressed Storage - ✅ Fertig
**Ziel:** SHA256-basierte Storage-Engine mit Deduplikation

**Status:** Abgeschlossen am 2026-01-10 (Issue #15)

Aufgaben:
- [x] SHA256-basierte Pool-Struktur (2-level: ab/cd/)
- [x] Deduplikation-Logic
- [x] Hardlink-Creation für Publishing
- [x] Orphaned Files Cleanup
- [x] Pool Statistics
- [x] 15 Storage Tests

**Ergebnis:** Universal Storage für alle Content-Types, Milestone 2 komplett

---

### Phase 3: RPM Plugin & Sync - ✅ Fertig
**Ziel:** RPM Repository Sync mit Filtering

**Status:** Abgeschlossen am 2026-01-10

Aufgaben:
- [x] repomd.xml Parser
- [x] primary.xml.gz Parser
- [x] RPM Download Logic
- [x] Metadata Extraction (RpmMetadata Pydantic Model)
- [x] RHEL CDN Authentication (Client Certificates)
- [x] Pattern-based Filtering (include/exclude)
- [x] Architecture Filtering
- [x] Post-Processing (only_latest_version)
- [x] Publishing Logic (createrepo_c)
- [x] CLI Commands (repo sync, repo list, repo show)
- [x] 14 Publisher Tests

**Ergebnis:** RHEL, CentOS, EPEL syncbar, Milestone 3 komplett

---

### Phase 4: Snapshots - ✅ Fertig
**Ziel:** Immutable Point-in-Time Snapshots

**Status:** Abgeschlossen am 2026-01-10

Aufgaben:
- [x] Snapshot-Manager
- [x] Snapshot Creation
- [x] Snapshot Publishing
- [x] Snapshot Diff (compare snapshots)
- [x] Snapshot Copy (promotion workflows: testing → stable)
- [x] CLI Commands (snapshot create, list, show, diff, copy)
- [x] Zero-Copy Operations (nur DB, keine File-Kopien)

**Ergebnis:** Patch-Management-fähig, Milestone 4 komplett

---

### Phase 5: Views & Advanced Publishing - ✅ Fertig
**Ziel:** Virtual Repositories (Views)

**Status:** Abgeschlossen am 2026-01-10

Aufgaben:
- [x] View Configuration (YAML)
- [x] ViewPublisher Plugin
- [x] View Publishing from Config (kein DB sync nötig)
- [x] View Snapshots (atomic multi-repo snapshots)
- [x] NO Deduplication in Views (Client entscheidet)
- [x] CLI Commands (view list, view show, publish view)
- [x] 10 View Tests

**Ergebnis:** Views kombinieren mehrere Repos (z.B. BaseOS + AppStream + EPEL), Milestone 5 komplett

---

### Phase 6: Database Management & Operations - 🔄 In Arbeit
**Ziel:** Operationale Database Commands

**Status:** 20% - Issue #14 offen

Aufgaben:
- [ ] `chantal db stats` - Database & Pool Statistics
- [ ] `chantal db vacuum` - SQLite VACUUM
- [ ] `chantal db export` - Export zu JSON/YAML
- [ ] `chantal db import` - Import von Backup
- [ ] `chantal db verify` - Integrity Checks
- [ ] Tests für DB Commands

**Nächster Schritt:** Implementierung der `chantal db stats` Command

**Blockiert durch:** Nichts

---

### Phase 7: Errata & Advisory Support - 📋 Geplant
**Ziel:** RPM Errata/Advisory Data Integration

**Status:** Noch nicht gestartet - Issue #12, #13

Aufgaben:
- [ ] updateinfo.xml Parser
- [ ] Advisory Model (RHSA, RHBA, RHEA)
- [ ] CVE Tracking
- [ ] External Errata Sources (AlmaLinux CEFS, Rocky RLSA)
- [ ] Errata Filtering
- [ ] Integration mit Snapshot Diff
- [ ] CLI Commands (errata list, errata show)

**Dependencies:** Keine

**Geschätzte Dauer:** 1 Woche

---

### Phase 8: Example Configurations - 📋 Geplant
**Ziel:** Vorkonfigurierte Templates für populäre Repos

**Status:** Noch nicht gestartet - Issue #3

Aufgaben:
- [ ] RHEL 8/9 Configs (BaseOS, AppStream, CRB)
- [ ] CentOS Stream Configs
- [ ] Rocky Linux Configs
- [ ] AlmaLinux Configs
- [ ] EPEL Configs
- [ ] Third-Party Repos (Docker, GitLab, PostgreSQL, etc.)
- [ ] README mit Quick-Start

**Dependencies:** Keine

**Geschätzte Dauer:** 2-3 Tage

---

### Phase 9: APT/DEB Support - 📋 Geplant
**Ziel:** Debian/Ubuntu Repository Support

**Status:** Noch nicht gestartet - Issue #1

Aufgaben:
- [ ] APT Plugin Implementation
- [ ] InRelease/Release Parsing
- [ ] Packages.gz/xz Parsing
- [ ] GPG Signature Preservation
- [ ] DEB Package Handling
- [ ] APT Publishing (standard APT structure)
- [ ] Ubuntu/Debian Repo Sync
- [ ] Tests

**Dependencies:** Generic ContentItem Model ✅ (done)

**Geschätzte Dauer:** 2 Wochen

---

### Phase 10: Helm Chart Repository Support - 📋 Geplant
**Ziel:** Kubernetes Helm Chart Mirroring

**Status:** Noch nicht gestartet - Issue #2

Aufgaben:
- [ ] Helm Plugin Implementation
- [ ] index.yaml Parsing
- [ ] Chart Metadata Extraction
- [ ] Chart Versioning
- [ ] Helm Repository Publishing
- [ ] Tests

**Dependencies:** Generic ContentItem Model ✅ (done)

**Geschätzte Dauer:** 1 Woche

---

## Offene Fragen

**Keine aktuellen Fragen** - Alle Requirements geklärt

## Entscheidungslog

- **2026-01-10** - Generic ContentItem Model: Entschieden für JSON Metadata statt separate Tables pro Content-Type. Grund: Skalierbarkeit, keine Schema-Changes für neue Plugins.

- **2026-01-10** - View Publishing: Entschieden für direkte Config-Publishing ohne DB-Sync. Grund: Views sind nur Gruppierungen, kein eigener State nötig.

- **2026-01-10** - Snapshot Copy: Entschieden für Zero-Copy (nur DB). Grund: Content-Addressed Storage macht File-Kopien unnötig.

- **2026-01-10** - SQLite vs PostgreSQL: Entschieden für SQLite als Default. Grund: Einfacheres Setup, ausreichend für typische Use-Cases.

- **2026-01-09** - Tool-Name: Entschieden für "Chantal". Grund: Alle anderen Namen (50+) waren bereits vergeben auf PyPI/GitHub.

---

## Nächste Schritte (Priorität)

1. **Database Management Commands** (Issue #14) - Quick Win
2. **Errata/Advisory Support** (Issue #12, #13) - Wichtig für Production
3. **Example Configurations** (Issue #3) - User Experience
4. **APT/DEB Support** (Issue #1) - Major Feature
5. **Helm Support** (Issue #2) - Cloud-Native Use-Case
