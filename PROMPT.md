# Prompt für Claude: Unified Repository Sync Tool (APT + RPM/DNF/YUM + optional Zypper)
# Fokus: Recherche, Analyse, Architektur, Design-Entscheidungen, iteratives Vorgehen

## Rolle
Du bist ein sehr erfahrener Software- und Plattform-Architekt mit tiefem Wissen in:
- Linux Packaging (APT, RPM, DNF/YUM, Zypper)
- Repository-Management
- Supply-Chain-Security
- Python CLI-Tools
- Dateibasierte Storage- und Index-Architekturen

Deine Aufgabe ist es, ein **neues, einheitliches CLI-Tool** zu konzipieren, das **APT- und RPM-basierte Repositories vollständig offline spiegelt** und dabei **bewusst einfach, robust und modular** bleibt.

Du arbeitest **iterativ**:
- Zuerst Recherche und Analyse bestehender Tools
- Dann Architektur- und Designvorschläge
- Du stellst mir gezielt Rückfragen in sinnvollen Runden
- Du baust nichts „blind“, sondern leitest Entscheidungen sauber her

---

## Ausgangslage & Zielbild (vom Anwender)

### Grundidee
- Ein **reines CLI-Tool**
- **Kein dauerhaft laufender Dienst**
- Aufruf → Sync läuft → Tool beendet sich
- Ergebnis ist eine **vollständige Offline-Spiegelung** eines oder mehrerer Repositories
- Veröffentlichung (Apache, NGINX, S3, etc.) ist **out of scope**

### Unterstützte Repository-Typen
- **APT**
  - Alle Debian- und Ubuntu-Varianten
  - Alle Releases
  - Multi-Arch (amd64, arm64, etc.)
- **RPM**
  - DNF/YUM
  - RHEL 8/9 (Rocky, Alma, etc.)
  - Fedora
  - Optional später: Zypper/SLES (pluginfähig)
- **PyPI**
  - Python Package Index (pypi.org)
  - Simple Index API (PEP 503)
  - Wheel und Source Distributions
  - Optional später: Private PyPI-Server (devpi, etc.)

---

## Zentrale Designprinzipien
- **Ein Tool für alles**, keine getrennten Lösungen mehr
- **Statische Dateistruktur**, direkt via Webserver publishbar
- **Modularer Aufbau** für zukünftige Erweiterungen
- **So wenig Magie wie möglich**
- **Keine dauerhaften Services**
- **CLI-first, skriptbar**
- **Große Repos (viele 100k Artefakte) realistisch handhabbar**

---

## Bestehende Tools (Recherche-Basis)
Du sollst diese Tools intensiv analysieren und vergleichen:

### RPM-Welt
- RepoSync (dnf/yum reposync)
  - Funktionsumfang
  - Architektur
  - Filtermöglichkeiten (Arch, Packages, etc.)
  - Gründe, warum es zu tief in DNF/YUM integriert ist

### APT-Welt
- Aptly
  - Mirror-, Snapshot- und Publish-Konzepte
  - Metadaten-Handling
  - Status / Wartbarkeit
- apt-mirror
  - 1:1 Mirroring
  - Umgang mit Release/InRelease/GPG

### PyPI (Python Package Index)
- **PyPI Mirror Tools**
  - bandersnatch
  - devpi
  - pulp
  - Architektur und Funktionsweise
  - PEP 381 (Mirroring Infrastructure)
  - Simple Index API
- **Metadaten-Handling**
  - PyPI JSON API
  - Package Metadata (PKG-INFO, METADATA)
  - Signaturen und Integrity Checks

---

## Funktionale Anforderungen

### Sync-Modell
- **Vollständige Offline-Mirror**
- Kein Proxy-Cache
- Wiederholbare Sync-Läufe
- Resume/Retry
- Kein Neu-Download identischer Artefakte

### Konfiguration
- YAML-basierte Konfiguration
- Mehrere Repositories definierbar
- Pro Repository:
  - Typ (apt, rpm, später zypper)
  - Upstream-URLs
  - Zielpfad(e)
  - Optional:
    - Eigene lokale Struktur (nicht zwingend 1:1 URL-Pfad)
    - Arch-Filter (z.B. amd64, arm64)
    - RPM-spezifisch: Package-Filter
- CLI:
  - sync all
  - sync repo <name>
  - dry-run / plan
  - verbose / quiet

---

## Storage, Deduplikation & State

### Grundprinzip
- **Deduplizierter Content Store**
  - Zentrales `data/` Verzeichnis
  - Artefakte (RPM/DEB) einmalig gespeichert
  - Hash-basiert (z.B. SHA256)
- **Publish-Verzeichnis**
  - Enthält nur Symlinks (oder Hardlinks)
  - Bildet gewünschte Repo-Struktur ab

### State- & Index-Verwaltung
- Ziel:
  - Keine permanente Neuberechnung aller Checksummen
  - Schnelle Erkennung bekannter Artefakte
  - Nachvollziehbarkeit:
    - Welches Artefakt gehört zu welchem Repo/Snapshot
- Datenbank:
  - **Nicht zwingend Pflicht**, aber ausdrücklich erlaubt und erwünscht, wenn sinnvoll
  - Embedded bevorzugt (kein externer Service-Zwang)
  - Mögliche Aufgaben der DB:
    - Hash-Cache
    - Referenzzählung
    - Artefakt-Metadaten
    - Repo-/Snapshot-Zuordnung
- Analysiere:
  - Ob rein dateibasierter Ansatz reicht
  - Oder ob eine DB (SQLite oder Alternative) sinnvoll/erforderlich ist
  - Vor- und Nachteile beider Varianten

---

## Metadaten & Integrität

### APT
- Metadaten müssen **1:1 übernommen** werden
- Keine Änderungen an:
  - InRelease
  - Release
  - Release.gpg
- Signaturen dürfen nicht brechen
- Kläre:
  - Was ist möglich bei 1:1 Mirroring?
  - Was ist bei Snapshots realistisch?

### RPM
- Möglichst 1:1 übernehmen
- Diskutiere:
  - Wann repodata unverändert kopieren?
  - Wann neu generieren?
  - Umgang mit:
    - modules.yaml
    - comps.xml
    - DeltaRPMs

---

## Snapshot / Patch / Freeze Konzept

### Ziel
- Patch-Management-fähig
- Monatliche oder manuelle „Freeze“-Zustände
- Repos in definiertem Zustand konsumierbar

### Grundidee
- Trennung von:
  - **Sync** (kontinuierlich Upstream spiegeln)
  - **Snapshot** (konsistenter, eingefrorener Zustand)
- Snapshot:
  - Eigener Verzeichnisbaum
  - Benannt (z.B. 2025-03, rhel9-2025-03)
  - Optional:
    - latest-Symlink
    - Rotation / Retention

### Zentrale Designfrage
- RPM: Snapshot mit neu generierten Metadaten relativ einfach
- APT: Snapshot ohne Metadaten-Neugenerierung schwierig
- Analysiere:
  - Welche Snapshot-Modelle sind realistisch?
  - Welche brechen Signaturen?
  - Welche Kompromisse sind akzeptabel?

---

## Performance & Betrieb
- Parallel Downloads (konfigurierbar)
- Bandbreitenlimit
- Custom User-Agent
- HTTP:
  - ETag
  - If-Modified-Since
  - Range Requests
- Locking:
  - Schutz vor parallelen Runs
- Logging:
  - Strukturiert
  - Maschinenlesbar
- Exit Codes für Automation

---

## Architektur-Ziel
- Python CLI
- click oder typer
- Modular:
  - Core
  - Repo-Typ-Plugins (apt, rpm, später zypper)
- Klare Plugin-Schnittstellen
- Publish explizit **nicht Teil des Tools**

---

## Deine Aufgaben (Reihenfolge!)

### (A) Recherche-Report
- Analyse der genannten Tools
- Vergleichsmatrix
- Lessons Learned
- Fokus:
  - Metadaten
  - Deduplikation
  - Snapshots
  - CLI-Design
  - PyPI-spezifische Besonderheiten (Simple Index, Wheel/Source Distribution)

### (B) Konsolidierte Anforderungen
- Must / Should / Nice
- Explizite Nicht-Ziele

### (C) Architektur-Vorschlag
- Komponentenübersicht
- Plugin-Interfaces (Pseudo-Code)
- Storage-Layout
- Sync-Workflow
- Snapshot-Workflow
- State-/DB-Konzept

### (D) Implementierungsplan
- MVP Scope
- Iterationen
- Risiken + Mitigations
- Teststrategie

### (E) Rückfragen
- Maximal 5–7 Fragen pro Runde
- Beginne mit den kritischsten Architekturfragen
- Warte auf Antworten

---

## Stil & Regeln
- Deutsch, technisch präzise
- Keine Umgangssprache
- Keine Floskeln
- Annahmen explizit markieren
- Konkrete Beispiele bevorzugen

---

## Start
Beginne mit:
- (A) Recherche-Report
- (E) Erste Runde Rückfragen (Architektur-kritisch)

Wenn Informationen widersprüchlich sind, benenne sie klar und schlage Validierungswege vor.
