# Unified Repository Sync Tool – Vollständige Kontext- und Anforderungsspezifikation

## Zweck dieses Dokuments

Dieses Dokument ist eine **vollständige, kontextreiche Zusammenfassung** der Anforderungen, Ideen, Randbedingungen und Designziele für Chantal - ein neues CLI-Tool zum Synchronisieren (Mirror) von Linux-Paket-Repositories.

Es dient explizit als:
- gemeinsame Wissensbasis
- Referenz für Architektur- und Designentscheidungen
- Ausgangspunkt für weitere Recherche und Implementierungsplanung
- Prompt-Grundlage für KI-gestützte Analyse

**Wichtig:**
Dieses Dokument ist bewusst ausführlich. Redundanz ist hier ein Feature, kein Bug.
Kontextverlust ist ausdrücklich zu vermeiden.

---

## 1. Ausgangsproblem und Motivation

### 1.1 Historische Situation

In der Vergangenheit existierten für unterschiedliche Linux-Ökosysteme **getrennte Lösungen**:

- **RPM/DNF/YUM:**
  - reposync
  - stark an DNF/YUM gekoppelt

- **APT:**
  - apt-mirror
  - aptly

- **PyPI:**
  - bandersnatch
  - devpi

### 1.2 Konkretes Problem in Kundenprojekten

- In Kundenumgebungen werden häufig **APT-, RPM- und PyPI-basierte Systeme parallel** betrieben
- Heute werden dafür meist **drei unterschiedliche Toolchains** benötigt
- Das erhöht:
  - Betriebsaufwand
  - Komplexität
  - Fehleranfälligkeit
- Wunsch: **eine einheitliche, konsistente Lösung**

---

## 2. Zielbild (High Level)

### 2.1 Grundidee

- **Ein einziges CLI-Tool**
- Kein Server, kein Daemon, kein dauerhaft laufender Dienst
- Aufruf:
  - CLI wird gestartet
  - Synchronisierung läuft
  - Tool beendet sich
- Ergebnis:
  - **vollständige Offline-Spiegelung** eines oder mehrerer Repositories
- Veröffentlichung:
  - **explizit out of scope**
  - erfolgt extern (Apache, NGINX, S3, etc.)

---

## 3. Unterstützte Repository-Typen

### 3.1 APT

- Debian
- Ubuntu
- alle Releases
- Multi-Arch:
  - amd64
  - arm64
  - weitere, sofern vorhanden
- **Metadaten müssen 1:1 übernommen werden**
  - InRelease
  - Release
  - Release.gpg
- Signaturen dürfen **nicht** brechen

### 3.2 RPM / DNF / YUM

- RHEL 8 / 9
  - Rocky
  - Alma
- Fedora
- Optional später:
  - Zypper / SLES (pluginfähig)

### 3.3 PyPI

- Python Package Index (pypi.org)
- Simple Index API (PEP 503)
- Wheel und Source Distributions
- Optional später:
  - Private PyPI-Server (devpi, etc.)

---

## 4. Sync-Modell

### 4.1 Art der Synchronisierung

- **Vollständige Offline-Mirror**
- Kein Proxy-Cache
- Kein On-Demand-Fetch
- Wiederholbare Sync-Läufe
- Resume/Retry bei Abbrüchen

### 4.2 Selektivität

- Pro Repository konfigurierbar:
  - Architekturen (z.B. amd64, arm64, aarch64)
- RPM-spezifisch:
  - Möglichkeit, nur bestimmte Pakete zu synchronisieren
- PyPI-spezifisch:
  - Filter nach requirements.txt oder package list

---

## 5. Konfiguration

### 5.1 Format

- YAML-basierte Konfigurationsdatei

### 5.2 Inhalt

- Definition mehrerer Repositories
- Pro Repository:
  - Typ (apt, rpm, pypi)
  - Upstream-URLs
  - Zielpfade
  - Optionale Abweichung von 1:1 URL-Pfaden
  - Architektur-Filter
  - Package-Filter
  - Performance-Optionen

### 5.3 CLI

- Beispiele:
  - `chantal sync all`
  - `chantal sync repo <name>`
  - `chantal snapshot create <name>`
  - `chantal snapshot list`
  - `chantal --dry-run`
  - `chantal --verbose`
  - `chantal --quiet`

---

## 6. Storage-Architektur

### 6.1 Grundprinzip

**Strikte Trennung zwischen:**
- Storage (dedupliziert)
- Präsentation (Publish-Verzeichnis)

### 6.2 Deduplizierter Content Store

- Zentrales `data/`-Verzeichnis
- Artefakte (RPMs, DEBs, Wheels) liegen dort **genau einmal**
- Hash-basiert (z.B. SHA256)
- Ziel:
  - gleiche Pakete aus verschiedenen Repos nur einmal speichern
  - typische Szenarien:
    - RHEL 9.x Minor-Releases
    - identische Pakete in verschiedenen Channels
    - Python packages in multiple indexes

### 6.3 Publish-Verzeichnis

- Enthält:
  - nur Symlinks (oder Hardlinks)
- Spiegelt:
  - gewünschte Repo-Struktur
- Direkt via Webserver auslieferbar

---

## 7. State- & Datenbank-Frage (wichtig!)

### 7.1 Motivation

- Checksummen **nicht bei jedem Lauf neu berechnen**
- Große Pakete (Kernel-RPMs, ML libraries etc.)
- Sehr viele Artefakte (PyPI hat >500k packages)

### 7.2 Grundhaltung

- **Keine Pflicht-Datenbank**
- Aber:
  - **explizit erlaubt**
  - **explizit erwünscht**, wenn sinnvoll

### 7.3 Mögliche Aufgaben einer DB

- Hash-Cache
- Referenzzählung
- Artefakt-Metadaten
- Repo-Zuordnung
- Snapshot-Zuordnung
- Sync history und statistics

### 7.4 Anforderungen an DB

- Embedded (SQLite, DuckDB, etc.)
- Kein externer Service-Zwang
- Robust
- Gut wartbar

### 7.5 Erwartung

- Analyse:
  - Reiner Filesystem-Ansatz vs. DB-gestützt
  - Vor- und Nachteile
  - Empfehlung mit Begründung

---

## 8. Metadaten & Integrität

### 8.1 APT

- Metadaten **unverändert**
- Keine Neugenerierung
- Signaturen müssen gültig bleiben
- Konsequenz:
  - Einschränkungen bei Snapshots wahrscheinlich

### 8.2 RPM

- Möglichst 1:1
- Diskussionspunkte:
  - Wann repodata kopieren?
  - Wann neu generieren?
  - Umgang mit:
    - modules.yaml
    - comps.xml
    - DeltaRPMs

### 8.3 PyPI

- Simple Index (HTML)
- JSON API
- Package metadata (METADATA, PKG-INFO)
- Hash verification (SHA256, optional PGP signatures)

---

## 9. Snapshot / Patch / Freeze Konzept

### 9.1 Ziel

- Patch-Management-fähig
- Monatliche oder manuelle Freeze-Zustände
- Reproduzierbare Zustände

### 9.2 Grundidee

- Trennung von:
  - Sync (kontinuierlich)
  - Snapshot (eingefroren)
- Snapshot:
  - Eigener Verzeichnisbaum
  - Klar benannt (z.B. `2025-01-debian-main`)
  - Optional:
    - `latest`-Symlink
    - Rotation / Retention

### 9.3 Kritische Designfrage

- RPM:
  - Snapshots technisch relativ einfach
- APT:
  - Snapshots ohne Metadaten-Neugenerierung schwierig
- PyPI:
  - Simple Index muss regeneriert werden
- Erwartung:
  - Ehrliche Analyse
  - Klare Aussage, was möglich ist
  - Saubere Kompromissvorschläge

---

## 10. Performance & Betrieb

- Parallel Downloads (konfigurierbar)
- Bandbreitenlimit
- Custom User-Agent
- HTTP-Features:
  - ETag
  - If-Modified-Since
  - Range Requests
- Locking:
  - Schutz vor parallelen Runs
- Logging:
  - strukturiert
  - maschinenlesbar (JSON)
- Exit-Codes für Automation
- Progress reporting

---

## 11. Architektur-Ziel

- **Python CLI**
- **click oder typer** für CLI
- **Modular:**
  - Core
  - Repo-Typ-Plugins (APT, RPM, PyPI)
- **Erweiterbar:**
  - Zypper
  - Alpine APK
  - andere Quellen (Tarballs, GitHub Releases etc.)
- **Veröffentlichung explizit nicht Teil des Tools**

---

## 12. Erwartetes Vorgehen bei Analyse & Design

1. Tiefgehende Recherche bestehender Tools
2. Vergleichsmatrix
3. Lessons Learned
4. Konsolidierte Anforderungen
5. Architekturvorschlag
6. Iterativer Implementierungsplan
7. Rückfragen in klaren Runden (max. 5–7)

---

## 13. Nicht-Ziele (explizit)

- Kein Proxy-Cache
- Kein permanenter Dienst
- Kein Web-UI (zumindest nicht in v1.0)
- Kein integrierter Webserver
- Kein Zwang zu externer Datenbank
- Keine „Enterprise-Plattform"
- Kein Container Registry Mirroring (Harbor, Artifactory existieren bereits)

---

## 14. Name: Chantal

**Tagline:** "Because every other name was already taken."

### Naming Journey

Wir haben dutzende Namen recherchiert und getestet:
- Maritime Metaphern (berth, harbor, tributary)
- Infrastruktur-Begriffe (conduit, fulcrum, atrium)
- Abstrakte Konzepte (cascade, vesper, cairn)

**Alle waren bereits vergeben** durch:
- Docker Tools
- GNOME Utilities
- CNCF Projects
- Security Tools
- Diverse andere Linux/DevOps Tools

**Chantal** ist:
- ✅ Verfügbar auf PyPI
- ✅ Verfügbar auf GitHub
- ✅ Einzigartig und merkbar
- ✅ Kurz und gut tippbar
- ✅ Hat Persönlichkeit

Folgt der Tradition von: Travis, Jenkins, Igor

---

## Ende

Dieses Dokument ist die **maßgebliche Referenz** für alle weiteren Schritte.
Änderungen daran müssen bewusst und explizit erfolgen.

**Last Updated:** 2025-01-09
