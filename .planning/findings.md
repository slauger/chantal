# Findings: Chantal - Unified Repository Sync Tool

Erstellt: 2025-01-09

## Recherche-Ergebnisse

### Tool 1: reposync (dnf-plugins-core) - 2025-01-09

**Repository:** https://github.com/rpm-software-management/dnf-plugins-core
**Plugin Source:** https://github.com/rpm-software-management/dnf-plugins-core/blob/master/plugins/reposync.py
**Dokumentation:** https://dnf-plugins-core.readthedocs.io/en/latest/reposync.html

#### Funktionsübersicht

reposync ist ein DNF-Plugin zum Synchronisieren von RPM-Repositories. Kernfunktionen:
- Download aller Pakete eines oder mehrerer Repositories
- Filter nach Architektur (`--arch`)
- Filter newest-only (`--newest-only`)
- Source-Pakete (`--source`)
- Metadaten-Download (`--download-metadata`)
- GPG-Signatur-Prüfung (`--gpgcheck`)
- Delete-Funktion für nicht mehr vorhandene Pakete

**Wichtige Erkenntnis:** reposync ist nur ein dünner Wrapper um DNF's Repository-System.

#### Architektur

**Storage-Modell:**
- Einfaches Filesystem-Layout
- Pakete werden in `--download-path` gespeichert
- Standard-Layout: `<download-path>/<repo-id>/Packages/`
- Keine Deduplikation zwischen Repositories
- Bei `--download-metadata`: Komplette Repository-Struktur mit `repodata/`

**Code-Struktur:**
```python
class RepoSyncCommand(dnf.cli.Command):
    def configure(self):
        # Repository-Konfiguration aus DNF übernehmen
        # Keine eigene Auth-Logik!

    def run(self):
        # Paket-Query über DNF's hawkey
        # Download über DNF's Download-System
```

**Kritisch:** reposync implementiert KEINE eigene Download- oder Auth-Logik. Es nutzt vollständig DNF's Infrastruktur.

#### Metadaten-Handling

**repodata:**
- Bei `--download-metadata`: Komplettes repodata/ wird heruntergeladen
- Metadaten werden 1:1 kopiert, NICHT neu generiert
- GPG-Signaturen bleiben erhalten
- Timestamp-Preservation möglich

**modules.yaml / comps.xml:**
- Werden mit `--download-metadata` kopiert
- Keine Filterung oder Modifikation

#### Red Hat Subscription-Auth - DER KRITISCHE PUNKT

**Der komplette Auth-Flow:**

1. **subscription-manager** verwaltet die Subscriptions:
   ```bash
   subscription-manager register
   subscription-manager attach --auto
   ```

2. **Zertifikat-Locations:**
   - `/etc/pki/consumer/` - Consumer-Zertifikat (System-Identity)
   - `/etc/pki/entitlement/` - Entitlement-Zertifikate (Subscription-Berechtigungen)
   - `/etc/rhsm/ca/redhat-uep.pem` - CA-Zertifikat für Red Hat CDN

3. **Automatische .repo-Generierung:**
   subscription-manager erstellt `/etc/yum.repos.d/redhat.repo` mit:
   ```ini
   [rhel-9-baseos-rpms]
   name=Red Hat Enterprise Linux 9 - BaseOS
   baseurl=https://cdn.redhat.com/content/dist/rhel9/9/$basearch/baseos/os
   enabled=1
   gpgcheck=1
   sslverify=1
   sslcacert=/etc/rhsm/ca/redhat-uep.pem
   sslclientcert=/etc/pki/entitlement/1234567890123456789.pem
   sslclientkey=/etc/pki/entitlement/1234567890123456789-key.pem
   ```

4. **DNF liest diese Konfiguration:**
   - DNF parst `/etc/yum.repos.d/*.repo` Dateien
   - Liest `sslclientcert` und `sslclientkey` Pfade
   - Nutzt Python `requests` Library mit Client-Zertifikaten für HTTPS

5. **reposync nutzt DNF:**
   - Ruft einfach DNF's Repository-API auf
   - Bekommt authentifizierten HTTP-Client automatisch
   - KEINE eigene Subscription-Logik notwendig!

**Wichtigste Erkenntnis:** reposync macht **NICHTS** Spezielles für RHEL-Auth. Es funktioniert einfach, weil subscription-manager die .repo-Dateien korrekt konfiguriert.

#### CLI & Konfiguration

**Wichtige CLI-Optionen:**
```bash
dnf reposync \
  --repoid=rhel-9-baseos-rpms \
  --download-path=/mirror \
  --arch=x86_64,aarch64 \
  --download-metadata \
  --newest-only
```

**Konfiguration:**
- Nutzt standard DNF/YUM `.repo` Dateien
- Keine eigene Config für reposync
- Alle DNF-Config-Optionen gelten (proxy, timeout, retries, etc.)

#### Sync-Workflow

1. DNF Repository-Objekte initialisieren (aus .repo-Dateien)
2. Metadaten von Remote holen (repomd.xml, primary.xml.gz, etc.)
3. Paket-Query ausführen (Filter nach Arch, newest, etc.)
4. Download-Queue erstellen
5. Parallel-Download (DNF's Download-Manager)
6. GPG-Verifikation (optional)
7. Metadaten lokal speichern (bei --download-metadata)

**Performance:**
- Parallel-Downloads über DNF's asyncio-basierter Downloader
- HTTP/2 Support (via libcurl in librepo)
- ETag / If-Modified-Since automatisch durch DNF
- Keine explizite Resume-Logik (DNF hat Range-Request-Support)

#### Stärken

✅ **Einfachheit:** Minimal-Wrapper um DNF
✅ **Subscription-Auth:** Funktioniert out-of-the-box mit subscription-manager
✅ **Metadaten:** 1:1 Kopie, Signaturen bleiben gültig
✅ **Performance:** Nutzt DNF's optimierten Download-Stack
✅ **Maintenance:** Wird aktiv von Red Hat gepflegt
✅ **GPG:** Volle Integration mit DNF's GPG-System

#### Schwächen

❌ **Keine Deduplikation:** Gleiche RPMs in mehreren Repos werden mehrfach gespeichert
❌ **Kein Snapshot-Konzept:** Keine eingebaute Snapshot-Funktionalität
❌ **Storage-Layout:** Fest vorgegeben, nicht flexibel
❌ **Nur RPM:** Keine Multi-Ecosystem-Unterstützung
❌ **Abhängigkeit:** Braucht vollständiges DNF-Stack
❌ **Kein State-Management:** Keine History, kein Tracking

#### Lessons Learned für Chantal

**Was wir übernehmen sollten:**

1. **DNF's Auth-Mechanismus verstehen und nutzen:**
   - `sslclientcert` / `sslclientkey` in Repository-Config
   - Python `requests` mit Client-Zertifikaten
   - Beispiel-Code:
   ```python
   import requests

   response = requests.get(
       'https://cdn.redhat.com/content/dist/rhel9/...',
       cert=('/etc/pki/entitlement/123.pem', '/etc/pki/entitlement/123-key.pem'),
       verify='/etc/rhsm/ca/redhat-uep.pem'
   )
   ```

2. **Subscription-Manager-Integration (optional):**
   - Chantal könnte subscription-manager als **optionale** Dependency nutzen
   - Falls nicht vorhanden: Manuelle Cert-Konfiguration in YAML:
   ```yaml
   repos:
     - name: rhel9-baseos
       type: rpm
       upstream: https://cdn.redhat.com/...
       ssl_client_cert: /etc/pki/entitlement/123.pem
       ssl_client_key: /etc/pki/entitlement/123-key.pem
       ssl_ca_cert: /etc/rhsm/ca/redhat-uep.pem
   ```

3. **Metadaten 1:1 kopieren:**
   - Für RPM: repodata einfach kopieren, nicht regenerieren
   - Signaturen bleiben gültig
   - Offline-Mirror ist sofort nutzbar

**Was wir ANDERS machen sollten:**

1. **Deduplikation:** Content-addressed Storage mit Symlinks/Hardlinks
2. **Snapshot-System:** Eingebaute Snapshot-Funktionalität
3. **Multi-Ecosystem:** APT + RPM in einem Tool
4. **State-Management:** DB oder strukturierte Files für History/Tracking
5. **Flexibles Storage-Layout:** Konfigurierbar, nicht fest vorgegeben

**Offene Fragen:**

- **FRAGE:** Funktioniert subscription-manager auch in Container-Umgebungen?
- **FRAGE:** Gibt es Rate-Limiting von Red Hat CDN?
- **FRAGE:** Können wir Zertifikate aus subscription-manager programmatisch auslesen?
- **FRAGE:** Alternative Auth für Satellite/Pulp-Server statt CDN?

## Design-Entscheidungen

<!-- Wird nach vollständiger Recherche gefüllt -->

## Code-Snippets & Beispiele

### Python: HTTPS mit Client-Zertifikaten (requests)

```python
import requests

# Beispiel: Red Hat CDN mit Entitlement-Zertifikat
response = requests.get(
    url='https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os/repodata/repomd.xml',
    cert=(
        '/etc/pki/entitlement/1234567890.pem',      # Client Cert
        '/etc/pki/entitlement/1234567890-key.pem'   # Client Key
    ),
    verify='/etc/rhsm/ca/redhat-uep.pem'           # CA Cert
)

if response.status_code == 200:
    print("Authenticated successfully!")
```

### DNF .repo Datei mit Zertifikaten

```ini
[rhel-9-baseos]
name=RHEL 9 BaseOS
baseurl=https://cdn.redhat.com/content/dist/rhel9/9/$basearch/baseos/os
enabled=1
gpgcheck=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-redhat-release

# Subscription Auth
sslverify=1
sslcacert=/etc/rhsm/ca/redhat-uep.pem
sslclientcert=/etc/pki/entitlement/1234567890.pem
sslclientkey=/etc/pki/entitlement/1234567890-key.pem
```

## Referenzen

### reposync
- GitHub: https://github.com/rpm-software-management/dnf-plugins-core
- Docs: https://dnf-plugins-core.readthedocs.io/en/latest/reposync.html
- Source: https://github.com/rpm-software-management/dnf-plugins-core/blob/master/plugins/reposync.py

### DNF Configuration
- DNF Conf Reference: https://dnf.readthedocs.io/en/latest/conf_ref.html
- Repository Configuration Options (SSL): Alle `sslclientcert`, `sslclientkey`, `sslcacert` Optionen

### Red Hat Subscription Management
- Get Started Guide: https://access.redhat.com/articles/433903
- Troubleshooting: https://access.redhat.com/solutions/189533
- Certificate Locations: `/etc/pki/consumer/`, `/etc/pki/entitlement/`, `/etc/rhsm/`

---

### Tool 2: Pulp 2 & Pulp 3 - 2025-01-09

**Repository:** https://github.com/pulp/pulp (Pulp 2 - EOL)
**Pulp 3 Projekt:** https://pulpproject.org/
**Architektur-Docs:** https://docs.pulpproject.org/en/2.20/dev-guide/architecture.html

#### Funktionsübersicht

Pulp ist ein vollwertiges **Repository-Management-System**, NICHT nur ein Mirror-Tool. Kernfunktionen:
- Repository-Sync von Upstream-Quellen
- Content-Publishing mit Versioning
- REST API für Management
- Multi-Tenancy und RBAC
- Consumer-Management (nur Pulp 2)
- Cloud-Storage-Support (S3, Azure - nur Pulp 3)

**Wichtiger Unterschied zu reposync:** Pulp ist eine **Plattform**, kein CLI-Tool.

#### Architektur: Pulp 2 vs. Pulp 3

**Pulp 2 (EOL):**
- **Datenbank:** MongoDB
- **Server:** Python, Celery für async Tasks
- **Plugins:** Importers (Sync), Distributors (Publish), Agent Handlers
- **Features:** System-Management, Consumer-Tracking
- **Problem:** Komplexe Architektur, schwer zu warten

**Pulp 3 (Aktuell):**
- **Datenbank:** PostgreSQL
- **Framework:** Django + Django REST Framework
- **OpenAPI:** Vollständige REST API Spec
- **Plugins:** Vereinfachte Plugin-API
- **Repository-Versioning:** Built-in Snapshot-System!
- **Performance:** 2-8x schneller als Pulp 2
- **Fokus:** Nur Repository-Management (kein System-Management)

**Warum komplett neu geschrieben?**
- Pulp 2 Architektur war zu komplex
- MongoDB → PostgreSQL Migration notwendig
- Plugin-API zu schwer zu nutzen
- Performance-Probleme
- Versionierung fehlte

#### Credential-Handling für Upstream-Repositories

**Pulp 3 Remote-Konfiguration:**

Pulp 3 hat ein `Remote`-Objekt für Upstream-Repositories:

```python
# Pulp 3 REST API - Remote erstellen mit Zertifikaten
POST /pulp/api/v3/remotes/rpm/rpm/
{
  "name": "rhel-9-baseos",
  "url": "https://cdn.redhat.com/content/dist/rhel9/...",
  "policy": "on_demand",  # oder "immediate"
  "client_cert": "-----BEGIN CERTIFICATE-----\n...",
  "client_key": "-----BEGIN PRIVATE KEY-----\n...",
  "ca_cert": "-----BEGIN CERTIFICATE-----\n...",
  "tls_validation": true,
  "username": null,  # Optional: HTTP Basic Auth
  "password": null   # Verschlüsselt in DB gespeichert
}
```

**Credential-Typen:**
1. **Client-Zertifikate:** `client_cert` + `client_key` (wie DNF)
2. **HTTP Basic Auth:** `username` + `password`
3. **CA-Zertifikat:** `ca_cert` für TLS-Validierung

**Storage:** Credentials werden **encrypted in PostgreSQL** gespeichert!

**pulp-cli Beispiel:**
```bash
pulp rpm remote create \
  --name rhel9-baseos \
  --url 'https://cdn.redhat.com/...' \
  --client-cert @/etc/pki/entitlement/123.pem \
  --client-key @/etc/pki/entitlement/123-key.pem \
  --ca-cert @/etc/rhsm/ca/redhat-uep.pem
```

#### Repository-Versioning (Snapshots!)

**Das ist der Killer-Feature von Pulp 3:**

Pulp 3 Repositories sind **versioniert**. Jede Änderung erstellt eine neue Version:

1. **Sync:** Erstellt neue Repository-Version
2. **Rollback:** Zurück zu früherer Version möglich
3. **Publishing:** Jede Version kann separat gepublisht werden

**Konzept:**
```
Repository "rhel-9-baseos"
├─ Version 1 (2025-01-01) - 1000 Pakete
├─ Version 2 (2025-01-08) - 1005 Pakete (5 neue)
├─ Version 3 (2025-01-15) - 1008 Pakete (3 neue)
└─ Version 4 (aktuell)
```

**API:**
```bash
# Neue Version durch Sync
pulp rpm repository sync --name rhel-9-baseos --remote rhel9-upstream

# Publikation einer spezifischen Version
pulp rpm publication create \
  --repository rhel-9-baseos \
  --version 2  # Publish Version 2, nicht latest!
```

**Vorteil:** Patch-Management! Man kann genau kontrollieren, welche Version deployed wird.

#### Plugin-Architektur

**Pulp 3 Plugin-System:**

- **pulpcore:** Platform/Core
- **Plugins:** `pulp_rpm`, `pulp_deb`, `pulp_file`, `pulp_container`, etc.
- **Plugin API:** Django-Models, Serializers, ViewSets

**Simplified Plugin-API (vs. Pulp 2):**
- Plugins definieren Models (Repository, Remote, Content)
- Sync-Logic in `stages`-Pipeline
- Publish-Logic in eigenen Tasks

**Beispiel-Plugins:**
- pulp_rpm - RPM/YUM/DNF
- pulp_deb - APT/Debian
- pulp_file - Generische Files
- pulp_container - Container Images (OCI)
- pulp_ansible - Ansible Collections

#### Storage-Modell

**Pulp 3 Storage:**

1. **Content:** Dedupliziert in `/var/lib/pulp/media/`
2. **Artifacts:** Hash-basiert (SHA256)
3. **Repository-Versionen:** Pointer auf Content (in DB)
4. **Publications:** Publishable Snapshots
5. **Distributions:** Web-Zugriff auf Publications

**Content-Addressable Storage:**
- Artefakte werden einmal gespeichert (Deduplikation!)
- Repository-Versionen sind nur DB-Einträge mit Referenzen
- Sehr Storage-effizient

**Cloud-Storage:** S3, Azure Blob Storage supported!

#### Stärken

✅ **Repository-Versioning:** Built-in Snapshot-System
✅ **Deduplikation:** Content-addressed Storage
✅ **Plugin-System:** Gut designte API
✅ **REST API:** Vollständige Management-API
✅ **Performance:** Sehr schnell (Pulp 3)
✅ **Credentials:** Verschlüsselt in DB
✅ **Cloud-Storage:** S3, Azure Support
✅ **Multi-Ecosystem:** Plugins für RPM, DEB, Container, etc.

#### Schwächen (für unseren Use-Case)

❌ **Komplexität:** Vollständiges System mit DB, REST API, Worker
❌ **Infrastruktur:** PostgreSQL + Redis + Worker-Prozesse notwendig
❌ **Overhead:** Zu schwergewichtig für einfaches Offline-Mirroring
❌ **Operational Complexity:** Service-Management, Monitoring, Backup
❌ **Nicht-CLI-First:** API-first, CLI ist Wrapper

**Pulp ist zu viel für Chantal's Zweck!**

#### Lessons Learned für Chantal

**Was wir NICHT übernehmen:**
- ❌ REST API / Service-Architektur (Chantal ist CLI-only!)
- ❌ Datenbank-Zwang (zu komplex)
- ❌ Worker/Celery-System
- ❌ Django-Framework

**Was wir ÜBERNEHMEN sollten:**

1. **Repository-Versioning-Konzept:**
   - Jeder Sync kann optional eine Version/Snapshot erstellen
   - Snapshots sind immutabel
   - Können alte Snapshots behalten oder löschen
   ```yaml
   snapshots:
     retention: 3  # Behalte letzte 3 Snapshots
     naming: "YYYY-MM"  # Format
   ```

2. **Credential-Konfiguration:**
   - Ähnliches Schema wie Pulp Remote
   ```yaml
   repos:
     - name: rhel9-baseos
       upstream_url: https://cdn.redhat.com/...
       credentials:
         type: client_cert
         cert_file: /etc/pki/entitlement/123.pem
         key_file: /etc/pki/entitlement/123-key.pem
         ca_file: /etc/rhsm/ca/redhat-uep.pem
   ```

3. **Content-Addressed Storage:**
   - `data/sha256/ab/cd/ef...`
   - Repositories als Symlink-Forests
   - Automatische Deduplikation

4. **Plugin-Konzept (vereinfacht):**
   - Kein Django, sondern einfache Python-Classes
   - Interface: `RepoPlugin` mit `sync()` und `publish()` Methods
   - Plugins registrieren sich selbst

**Was wir ANDERS/EINFACHER machen:**

1. **Keine Datenbank (optional SQLite für Cache):**
   - State in Files oder optional embedded DB
   - Kein PostgreSQL-Zwang

2. **CLI-First:**
   - Keine REST API
   - Direkter Command-Line-Aufruf

3. **Kein Service:**
   - Run & Exit
   - Keine dauerhaften Worker

4. **Einfachere Snapshots:**
   - Filesystem-basiert
   - Optional Symlink zu "latest"
   - Keine komplexe Versionierungs-DB

**Offene Fragen:**

- **FRAGE:** Wie genau macht Pulp die Credential-Encryption in PostgreSQL?
- **FRAGE:** Welcher Encryption-Algorithmus? Wo ist der Key?
- **FRAGE:** Performance: Wie schnell ist Pulp 3 wirklich vs. einfacher File-Copy?

---

## Vergleichsmatrix: reposync vs. Pulp

| Kriterium | reposync | Pulp 2 | Pulp 3 | **Chantal (Ziel)** |
|-----------|----------|--------|--------|-------------------|
| **Architektur** | CLI Plugin | Service + DB | Service + DB | **CLI-only** |
| **Datenbank** | Keine | MongoDB | PostgreSQL | **Optional SQLite** |
| **Deduplikation** | ❌ Keine | ✅ Ja | ✅ Content-addressed | **✅ SHA256-based** |
| **Snapshots** | ❌ Keine | ❌ Keine | ✅ Versioning | **✅ Filesystem-based** |
| **Multi-Ecosystem** | ❌ Nur RPM | ✅ Plugins | ✅ Plugins | **✅ APT + RPM** |
| **Credential-Handling** | Via DNF Config | Via Importer | Via Remote | **YAML Config** |
| **Client-Certs** | ✅ DNF sslclientcert | ✅ Ja | ✅ client_cert | **✅ Ja** |
| **REST API** | ❌ Nein | ✅ Ja | ✅ Django REST | **❌ Nein** |
| **Storage-Model** | Flat Files | Custom | Content-addressed | **Content-addressed** |
| **Metadaten** | 1:1 Copy | Kopiert | Kopiert | **1:1 Copy** |
| **Performance** | Schnell | Langsam | Sehr schnell | **Ziel: Schnell** |
| **Operational Complexity** | ⭐ Niedrig | ⭐⭐⭐⭐ Hoch | ⭐⭐⭐ Mittel | **⭐ Niedrig** |
| **Use-Case** | Simple Mirror | Enterprise Platform | Enterprise Platform | **Offline Mirror** |

## Design-Entscheidungen für Chantal

### 1. Credential-Handling (ENTSCHIEDEN)

**Ansatz:** Hybrid - subscription-manager optional, manuelle Config möglich

```yaml
repos:
  - name: rhel9-baseos
    type: rpm
    upstream: https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os

    # Option A: Auto-Discovery (subscription-manager)
    credentials:
      type: subscription_manager  # Liest /etc/pki/entitlement/

    # Option B: Manuelle Konfiguration
    credentials:
      type: client_cert
      cert: /path/to/cert.pem
      key: /path/to/key.pem
      ca_cert: /path/to/ca.pem

    # Option C: HTTP Basic Auth
    credentials:
      type: basic
      username: myuser
      password: ${ENV_VAR}  # oder prompt
```

**Implementation:** Python `requests` mit `cert=(cert_file, key_file)`

### 2. Storage-Architektur (ENTSCHIEDEN)

**Content-Addressed Storage wie Pulp 3:**

```
chantal/
├── data/                    # Deduplicated content
│   └── sha256/
│       ├── ab/cd/ef...      # RPMs, DEBs
│       └── ...
├── repos/                   # Published repos (symlinks)
│   ├── rhel9-baseos/
│   │   ├── Packages/        # Symlinks zu data/
│   │   └── repodata/        # Metadaten
│   └── debian-bookworm/
│       ├── dists/
│       └── pool/            # Symlinks zu data/
└── snapshots/               # Immutable snapshots
    ├── 2025-01/
    └── latest -> 2025-01/   # Symlink
```

### 3. Snapshot-System (ENTSCHIEDEN)

**Filesystem-basiertes Snapshot-System:**

```bash
# Sync mit auto-snapshot
chantal sync rhel9-baseos --snapshot

# Erstellt:
# snapshots/rhel9-baseos/2025-01-09/
# snapshots/rhel9-baseos/latest -> 2025-01-09/

# Manueller Snapshot
chantal snapshot create rhel9-baseos --name 2025-01-patch1

# Liste Snapshots
chantal snapshot list rhel9-baseos

# Restore Snapshot
chantal snapshot restore rhel9-baseos 2025-01-patch1
```

**Implementation:** Hardlinks oder Symlinks + Metadaten-Kopie

### 4. State-Management (ZU DISKUTIEREN)

**Optionen:**

**A) Rein Filesystem-basiert:**
```
chantal/
└── state/
    ├── last_sync.json
    ├── hash_cache.json  # SHA256 Cache
    └── sync_history.json
```

**B) Optionale SQLite-DB:**
```sql
CREATE TABLE artifacts (
  sha256 TEXT PRIMARY KEY,
  size INTEGER,
  first_seen TIMESTAMP,
  repos TEXT  -- JSON array
);

CREATE TABLE sync_history (
  id INTEGER PRIMARY KEY,
  repo_name TEXT,
  timestamp TIMESTAMP,
  packages_added INTEGER,
  packages_removed INTEGER
);
```

**Empfehlung:** Start mit Filesystem, später optionale SQLite für Performance

### 5. Plugin-System (ENTSCHIEDEN)

**Einfaches Python-Plugin-Interface:**

```python
from abc import ABC, abstractmethod

class RepoPlugin(ABC):
    @abstractmethod
    def sync(self, config: RepoConfig, storage: ContentStorage):
        """Sync repository from upstream"""
        pass

    @abstractmethod
    def publish(self, storage: ContentStorage, publish_path: Path):
        """Publish repository to filesystem"""
        pass

# Plugins registrieren sich:
class RPMPlugin(RepoPlugin):
    type_name = "rpm"

    def sync(self, config, storage):
        # RPM-spezifische Sync-Logik
        pass
```

**Plugins:**
- `chantal.plugins.rpm` - RPM/YUM/DNF
- `chantal.plugins.apt` - APT/Debian
- (später) `chantal.plugins.pypi`, etc.

---

## Zusammenfassung der Recherche-Phase

### Kernerkenntnis zur RHEL Subscription-Auth:

**Der Auth-Flow ist einfacher als gedacht:**

1. subscription-manager schreibt Zertifikate nach `/etc/pki/entitlement/`
2. subscription-manager generiert `/etc/yum.repos.d/redhat.repo` mit `sslclientcert`/`sslclientkey`
3. DNF/YUM liest die .repo-Dateien
4. Python `requests` nutzt die Zertifikate für HTTPS
5. **Chantal kann dasselbe tun:** Einfach Cert-Pfade in Config, dann `requests.get(cert=(cert, key))`

**Kein Magie notwendig!**

### Was Chantal besser machen kann als bestehende Tools:

1. **Unified:** Ein Tool für APT + RPM (reposync: nur RPM)
2. **Einfach:** CLI-only, kein Service (Pulp: zu komplex)
3. **Deduplikation:** Content-addressed Storage (reposync: keine Dedup)
4. **Snapshots:** Built-in Snapshot-System (reposync: keine Snapshots)
5. **Flexibel:** Subscription-manager optional, manuelle Config möglich

---

### Tool 3: apt-mirror - 2025-01-09

**Repository:** https://github.com/apt-mirror/apt-mirror
**Dokumentation:** https://apt-mirror.github.io/
**Sprache:** Perl (94.6%)
**Status:** ⚠️ **Sucht Maintainer** - Nicht mehr aktiv gepflegt

#### Funktionsübersicht

apt-mirror ist ein Perl-basiertes Tool zum Spiegeln von Debian/Ubuntu APT-Repositories. Kernfunktionen:
- Download kompletter oder partieller APT-Repositories
- Multithreaded-Downloads (20 parallel)
- Unterstützung für deb und deb-src
- GPG-Signatur-Prüfung
- Automatisches Cleanup alter Pakete
- Pool-compliant Directory-Structure

**Download-Engine:** Verwendet wget als External-Tool für Downloads.

#### Architektur

**3-Phasen-Download-Prozess:**

1. **Release-Files:** Download von Release, InRelease, Release.gpg
2. **Metadaten-Indexes:** Packages.gz, Sources.gz, Contents-*.gz
3. **Paket-Download:** Eigentliche .deb Pakete aus dem Pool

**Storage-Layout:**
```
/var/spool/apt-mirror/
├── mirror/          # Gespiegelte Inhalte (pool-compliant)
│   └── <hostname>/  # z.B. archive.ubuntu.com/ubuntu/
│       ├── dists/   # Distributions-Metadaten
│       └── pool/    # .deb Pakete (alphabetisch)
├── skel/            # Temp-Download-Metadaten
└── var/             # Logs, URLs, MD5-Checksums, Tracking
```

**Pool-Compliance:** ✅ Ja - Repliziert Standard Debian/Ubuntu Repository-Struktur korrekt.

#### Credential-Handling

**Unterstützte Auth-Methoden:**

1. **HTTP Basic Auth (URL-embedded):**
   ```
   deb http://user:pass@example.com:8080/debian stable main
   ```

2. **APT auth.conf Integration:**
   - Liest `/etc/apt/auth.conf`
   - Sicherer als URL-embedded Credentials
   ```
   machine example.org/deb
   login apt
   password debian
   ```

3. **Proxy Auth:**
   ```perl
   set proxy http://proxy:8080/
   set proxy_user username
   set proxy_password password
   ```

**Probleme:**
- ❌ **Bug #124:** Credentials in URLs brechen Cleanup-Funktion (alle dists/ Files werden gelöscht)
- ❌ **Sicherheit:** URL-embedded Credentials sind world-readable in Configs

**HTTPS Client-Zertifikate:** ❌ NICHT unterstützt!

#### Metadaten-Handling

**Unterstützte Metadaten:**
- Release / InRelease / Release.gpg
- Packages / Packages.gz / Packages.xz
- Sources / Sources.gz / Sources.xz
- Contents-*.gz (File-Listings)
- dep-11/ (AppStream Metadata)
- by-hash/ (Content-addressed Metadata)

**by-hash Support:**
- ✅ PR #131 fügte by-hash/SHA256 Support hinzu
- ⚠️ Implementation könnte unvollständig sein

**Bekannte Probleme:**
- InRelease Files werden nicht korrekt cleaned up → Hash Sum Errors
- Probleme mit InRelease Files die Spaces nach Hash-Namen haben
- "Packages.gz: No such file" Errors
- Release Files werden manchmal nicht heruntergeladen

#### HTTP-Download-Implementation

**wget-Aufruf:**
```bash
wget --no-cache \
     --limit-rate=<config> \
     -t 5 \              # 5 Retry-Versuche
     -r \                # Recursive
     -N \                # Timestamp-Checking
     -l inf \            # Infinite Recursion Depth
     <url>
```

**Performance:**
- Multithreading: 20 parallel Downloads (konfigurierbar)
- Incremental Updates: Timestamp/Size-Checking via wget `-N`
- ❌ **Kein Resume:** Fehlt wget `-c` Flag → Unterbrochene Downloads starten von vorne
- ❌ **Bandwidth-Limiting:** Inaccurate (Bug #140)

**Protokolle:** HTTP, HTTPS, FTP

#### Storage & Deduplikation

**Storage-Ansatz:** 1:1 Mirror der Upstream-Repository-Struktur

**Deduplikation:** ❌ **KEINE eingebaute Deduplikation!**

**Workaround:** Externe Tools nach dem Mirror-Prozess:
- `hardlink` - Standard Linux Utility
- `hadori` - Memory-effiziente Alternative
- `deduprs` - Rust-based
- `fslint` - File-Level Deduplication

**Ergebnis:** User berichten 30% Disk-Space-Einsparungen durch Hardlink-Tools.

**Limitierungen:**
- Hardlinks nur innerhalb gleichen Filesystems
- Modifizierung einer Datei bricht alle Hardlinks
- Keine automatische Maintenance

#### Stärken

✅ **Einfachheit:** Leicht zu konfigurieren
✅ **Geschwindigkeit:** 20 parallele Downloads
✅ **Pool-Compliance:** Korrekte Debian/Ubuntu Struktur
✅ **Multi-Arch:** Mehrere Architekturen gleichzeitig
✅ **Incremental Updates:** Nur geänderte Files
✅ **Etabliert:** Weit verbreitet in Debian/Ubuntu Community
✅ **Low-Resource:** Nur Perl + wget notwendig

#### Schwächen

❌ **Unmaintained:** Keine aktive Entwicklung, sucht Maintainer
❌ **Keine Deduplikation:** Externe Tools notwendig
❌ **Kein Resume:** Downloads starten bei Abbruch von vorne
❌ **Metadaten-Bugs:** InRelease, by-hash, Cleanup-Probleme
❌ **Bandwidth-Limiting:** Funktioniert nicht korrekt
❌ **Process-Management:** Schwer zu stoppen/kontrollieren
❌ **Incomplete Mirrors:** User berichten gelegentlichen File-Verlust
❌ **Auth-Bugs:** Credentials brechen Cleanup
❌ **Keine Client-Certs:** HTTPS Client-Zertifikate nicht unterstützt
❌ **Kein Delta-Sync:** Kein rsync-style Delta-Transfer

#### Lessons Learned für Chantal

**Was übernehmen:**

1. **3-Phasen-Download-Strategie:** Release → Metadaten → Pakete
2. **Pool-Compliant Structure:** Standard APT Repository-Layout
3. **Multithreading:** Parallele Downloads
4. **Incremental Updates:** Size/Timestamp-basiert

**Was BESSER machen:**

1. **✅ Content-Addressed Storage:** Eingebaute Deduplikation (apt-mirror: keine)
2. **✅ Resume/Retry:** Robuste Resume-Logic (apt-mirror: fehlt)
3. **✅ Metadaten-Handling:** Robuste by-hash, InRelease-Verarbeitung
4. **✅ Bandwidth-Limiting:** Akkurates Rate-Limiting
5. **✅ Credential-Management:** Sichere Credential-Storage (kein URL-embedding)
6. **✅ Client-Certs:** HTTPS Client-Certificate Support
7. **✅ Active Maintenance:** Moderner Code (Rust), gepflegt

**Was VERMEIDEN:**

- ❌ Externe Download-Tools (wget) - Use integrierte HTTP Library
- ❌ Perl - Use moderne Sprache (Rust)
- ❌ URL-embedded Credentials
- ❌ Manuelle Deduplikation-Workflow

---

### Tool 4: aptly - 2025-01-09

**Repository:** https://github.com/aptly-dev/aptly
**Dokumentation:** https://www.aptly.info/
**Sprache:** Go (64.8%)
**Status:** ✅ Aktiv gepflegt - Genutzt von Intel, Amazon, Instagram, Dell

#### Funktionsübersicht

aptly ist ein **vollwertiges Repository-Management-System** für Debian/Ubuntu. Kernfunktionen:
- Mirror Management (Full & Partial)
- Local Repository Creation
- Snapshot System (immutable versioning)
- Repository Merging & Filtering
- Multi-Component Publishing
- REST API + CLI
- S3/Swift Publishing

**Wichtiger Unterschied zu apt-mirror:** aptly ist eine **Plattform**, kein einfaches Mirror-Tool.

#### Architektur

**Implementation:**
- **Sprache:** Go (Golang)
- **Datenbank:** LevelDB (Key-Value Store)
- **Storage:** Content-Addressed (SHA256-basiert)

**Directory-Struktur:**
```
~/.aptly/
├── db/         # LevelDB Datenbank mit Package-Metadaten
├── pool/       # Deduplizierter Package-Storage
└── public/     # Gepublishte Repositories
```

**Pool-Layout (seit 1.1.0):**
```
pool/
└── sha256[0:2]/sha256[2:4]/sha256[4:32]_filename
```

Zwei-Level Directory-Struktur mit SHA256-Hashes zur Vermeidung von Hash-Kollisionen.

#### Storage-Modell & Deduplikation

**Content-Addressed Storage:** ✅ **JA** - SHA256-basiert

**Deduplikation:**
- Pakete mit identischem `(architecture, name, version)` Tupel + Inhalt werden dedupliziert
- **Cross-Repository Deduplication:** ✅ JA
- Pakete werden einmal im Pool gespeichert
- Repositories/Snapshots referenzieren Pakete
- Cleanup: `aptly db cleanup` entfernt unreferenzierte Pakete

**Vorteil:** Neue Mirrors mit anderen URLs laden keine Files die bereits im Pool sind.

**Package-Identity:**
- Gleiche `(arch, name, version)` + gleicher Inhalt → Ein Package
- Gleiche `(arch, name, version)` + unterschiedlicher Inhalt → Konflikt (nicht im gleichen Repo erlaubt)

#### Snapshot-System - **DAS KILLER-FEATURE**

**Definition:** "Fixed state of repository mirror or local repository, internally represented as list of references to packages"

**Eigenschaften:**
- **Immutable:** Komplett unveränderbar nach Erstellung
- **Copy-on-Write:** ✅ JA - Reference-basiert, keine Paket-Duplikation
- **Storage-Efficiency:** Extrem effizient - Snapshots sind nur Package-Reference-Listen
- **Vergleich zu Pulp 3:** Sehr ähnliches Konzept!

**Snapshot-Operationen:**

```bash
# Erstellen
aptly snapshot create <name> from mirror <mirror-name>
aptly snapshot create <name> from repo <repo-name>

# Mergen (mehrere Strategien)
aptly snapshot merge <new> <snap1> <snap2>
  --latest          # Höchste Version gewinnt
  --no-remove       # Behalte alle Versionen

# Filtern
aptly snapshot filter <source> <destination> <package-query>

# Pullen mit Dependencies
aptly snapshot pull <name> <source> <destination> <package-query>

# Diff
aptly snapshot diff <snap1> <snap2>

# Atomic Switch
aptly publish switch <distribution> <snapshot>
```

**Vorteil:** Patch-Management! Exakte Kontrolle welche Version deployed wird.

#### Repository-Management-Capabilities

**Mirroring:**
- Full & Partial Mirrors
- Architektur-Filterung
- Component-Selection
- Flat Repository Support
- .udeb Support (Debian Installer)

**Local Repositories:**
- Unbegrenzt viele lokale Repos
- Package-Addition via Files, Directory-Scan, Import
- Package-Operationen: Add, Remove, Move, Copy
- Automatischer Source-Package-Retrieval

**Mixing Mirrors + Custom Packages:**

Workflow:
1. Snapshot von Mirrors erstellen
2. Snapshot von Local Repos erstellen (custom packages)
3. Snapshots mergen
4. Merged Snapshot publishen

**Use-Case:** Perfekt für Orgs die Upstream + Internal Packages brauchen!

#### Publishing

**Publishing-Targets:**
- Filesystem (lokales Directory)
- Amazon S3
- OpenStack Swift

**Metadaten-Generierung:**
- Packages, Packages.gz, Packages.bz2
- Sources
- Contents (optional, kann mit `-skip-contents` übersprungen werden)
- Release, InRelease, Release.gpg
- GPG-Signing (extern oder internal Go-Implementation)

**⚠️ WICHTIG:** aptly **regeneriert** Metadaten → Original-Signaturen von Mirrors werden NICHT erhalten!

**Multi-Component:** ✅ Ja - Mehrere Components in einem Repository publishbar

**Atomic Updates:** ✅ Ja - Snapshot-Switching ist atomar

#### Credential-Handling

**Upstream-Repository-Auth:**
- ⚠️ **Eingeschränkt:** Basische Auth limitiert
- Wahrscheinlich URL-basiert: `http://user:pass@repo-url/`
- ❌ **HTTPS Client-Certs:** NICHT nativ unterstützt (Issue #292)
  - Workaround: stunnel oder Reverse-Proxy

**API-Auth:**
- ❌ **KEINE native API-Auth**
- Empfehlung: nginx/Apache vorschalten mit Basic Auth + HTTPS

**Schwäche:** Auth ist NICHT eine Stärke von aptly.

#### REST API

**Command:** `aptly api serve` (default Port: 8080)

**Endpoints:**
- Version API
- Local Repos API
- Mirrors API
- File Upload API
- Snapshot API
- Publish API
- Package API
- Misc API

**Use-Cases:**
- Remote Package-Uploads von CI/CD
- Concurrent Multi-User Access
- Automatisiertes Repository-Management

**Limitations:**
- Manche Operationen brauchen Restart
- GPG-Passphrase-Input via Console nicht supported
- URL-Parameter mit "/" problematisch

**Concurrency:** `-no-lock` Flag für concurrent CLI + API Usage

#### Performance - **KRITISCHES PROBLEM**

**1. Langsames Publishing (MAJOR ISSUE):**

- **~50k Packages:** 10 Minuten zum Publishen
- **~2.7k Packages:** 33+ Minuten auf i9-9900K (!!)
- **Bottleneck:** "Generating metadata files and linking package files" - 99% der Zeit

**Ursachen:**

1. **Contents-Generierung:** PRIMARY BOTTLENECK
   - Öffnet JEDES Package um Contents zu bauen
   - Ruft `xz --decompress --stdout` für jedes Package auf
   - Sehr langsam für große Packages (Kernel)
   - Single-threaded!

2. **XZ Compression:** Single-Core only (nutzt nicht Multi-Core)

3. **Disk-bound:** Meist I/O limitiert

**Lösungen/Workarounds:**

- `-skip-contents` Flag → Spart 5+ Minuten
- Contents-Index ist oft nicht notwendig
- Caching: Contents wird nach erstem Generate gecached
- Erste Publikation ist immer am langsamsten

**2. Memory-Usage:**

- **Problem:** Hoher Memory-Verbrauch bei großen Repos (30k+ Packages)
- 512 MB VMs erleben severe Swapping
- **Optimierungen gemacht:** ~3x Memory-Reduktion
- **Immer noch:** Memory-intensiv für sehr große Repos

**3. S3 Publishing Scalability:**

- Trifft S3 API Throttling-Limits bei großen Repos
- Kein graceful Handling, schlägt fehl

**4. Single-Threaded:**

- Meiste Operationen nutzen nicht Multi-Core
- Langsam auf Multi-Core-Systemen für große Repos

#### CLI-Interface

**Design:** Umfassende Subcommand-Struktur

```bash
aptly mirror    # create, update, list, drop, show, rename, edit
aptly repo      # create, add, remove, import, show, list, copy, move, drop, rename, edit, include
aptly snapshot  # create, list, show, verify, pull, diff, merge, drop, rename, filter, search
aptly publish   # snapshot, repo, switch, update, drop, list, show
aptly db        # cleanup, recover
aptly serve     # HTTP Repository-Server
aptly api serve # REST API Server
aptly graph     # Dependency-Visualisierung
```

**Features:**
- Search: Query packages across mirrors/snapshots/repos
- Dependency-Resolution: Automatische Dependency-Handling
- Batch-Operationen: Scripting-Support

#### Stärken

✅ **Snapshot-System:** Immutable Versioning mit Copy-on-Write
✅ **Content-Addressed Storage:** SHA256-basierte Deduplikation
✅ **Repository-Mixing:** Merge Mirrors + Custom Packages
✅ **Multi-Component Publishing:** Exzellenter Support
✅ **Aktive Maintenance:** Produktiv genutzt von großen Firmen
✅ **REST API + CLI:** Beide Interfaces verfügbar
✅ **Mature Debian Support:** Production-tested
✅ **GPG-Signing:** Volle GPG-Integration
✅ **Storage-Efficiency:** Reference-based Snapshots

#### Schwächen

❌ **Performance (KRITISCH):** Sehr langsames Publishing (Stunden für große Repos)
❌ **Scalability:** Memory-Probleme bei 30k+ Packages
❌ **LevelDB:** Keine Distributed Options, keine Concurrency
❌ **Auth-Schwächen:** Schlechte Upstream-Auth, keine API-Auth
❌ **Monolithic:** Single Binary, nicht horizontal skalierbar
❌ **Limited Concurrency:** `-no-lock` Workaround notwendig
❌ **Single-Threaded:** Nutzt nicht Multi-Core effektiv

#### Vergleich: aptly vs. apt-mirror

| Feature | aptly | apt-mirror |
|---------|-------|------------|
| **Mirroring** | Full & Partial | Full only |
| **Snapshots** | ✅ Immutable Versioning | ❌ Keine |
| **Multi-Versionen** | ✅ Ja | ❌ Nein |
| **Repo-Mixing** | ✅ Merge Mirrors + Custom | ❌ Nein |
| **Config** | Komplexer | Einfacher |
| **Maintenance** | ✅ Aktiv | ❌ Unmaintained |
| **Performance** | ⚠️ Langsames Publish (1+ Stunde) | ✅ Schneller |
| **Storage** | ✅ Content-addressed, dedupliziert | ❌ Simple File-Copy |
| **Use-Case** | Advanced Repo-Management | Simple Mirroring |

**Zusammenfassung:** aptly ist komplexer aber deutlich mächtiger. apt-mirror ist einfacher aber limitiert und unmaintained.

#### Vergleich: aptly vs. Pulp 3

| Feature | aptly | Pulp 3 |
|---------|-------|--------|
| **Focus** | Debian-spezifisch | Multi-Format (Plugins) |
| **Snapshots** | ✅ Immutable Reference-Lists | ✅ Versioned Repo-States |
| **Deduplication** | ✅ SHA256 Pool | ✅ Content-addressed |
| **Datenbank** | LevelDB (KV) | PostgreSQL |
| **Storage** | Local + S3/Swift | Flexibel (S3, Azure, etc.) |
| **Publishing** | Multi-Component, Atomic | Per-Distribution Base-URLs |
| **Interface** | CLI + REST API | CLI + REST API |
| **Maturity (Debian)** | ✅ Production-Ready | Plugin noch maturing |
| **Workflow** | Einfacher, Debian-fokussiert | Generischer, schwerer |
| **Performance** | ⚠️ Langsames Publish | Bessere Performance |
| **Scalability** | ⚠️ Memory/Perf-Issues | Besser für Scale designt |

**User-Feedback:** Pulp Workflow "feels too heavy and error-prone" für Debian im Vergleich zu aptly.

#### Lessons Learned für Chantal

**Was ÜBERNEHMEN:**

1. **Snapshot-Implementation:**
   - Immutable, reference-based Snapshots
   - Snapshots als Package-Reference-Lists in DB
   - Packages in shared, deduplicated Pool
   - **Bewährt und effizient!**

2. **Content-Addressed Storage:**
   - SHA256-based Pool-Layout: `hash[0:2]/hash[2:4]/hash[4:...]_filename`
   - Deduplikation über alle Repos durch Content-Hash
   - Separate Storage: Metadata-DB, Package-Pool, Published-Repos
   - **Sound Architecture!**

3. **Package-Deduplication-Logic:**
   - Deduplizierung durch `(architecture, name, version)` + Content-Hash
   - Konfliktbehandlung (same identity, different content)
   - Reference-Counting für Cleanup
   - **Korrekt!**

4. **Snapshot-Merge-Strategien:**
   - Multiple Merge-Strategien (rightmost wins, latest wins, keep all)
   - Conflict-Resolution-Optionen
   - Filter & Pull Operations auf Snapshots
   - **Wertvolle Flexibilität!**

5. **Multi-Component Publishing:**
   - Mehrere Components in einem Repo
   - Mixing Mirrors + Custom via Snapshot-Merge
   - **Löst "curated workspace" Requirement!**

**Was NICHT übernehmen:**

1. **LevelDB Datenbank:**
   - ✅ Use PostgreSQL für Scalability, Querying, Concurrency
   - Need proper Relational Model
   - Need ACID Transactions

2. **Single-Threaded Publishing:**
   - ✅ Make Publishing parallel + multi-threaded
   - ✅ Optimize Contents-Generation (oder skip by default)
   - ✅ Use Worker-Pools

3. **Contents-Generation-Approach:**
   - ✅ Don't regenerate Contents durch Decompression
   - ✅ Cache aggressively oder make truly optional
   - ✅ Consider pre-computed Metadata

4. **Monolithic Architecture:**
   - ✅ Use Microservices für Scalability
   - ✅ Separate API, Worker, Storage Services
   - ✅ Enable Horizontal Scaling

5. **Limited Auth:**
   - ✅ Build robust Auth von Anfang an
   - ✅ Support Credentials für Upstream (inkl. Client-Certs)
   - ✅ Token-based API Auth

**Architectural Insights:**

1. **Immutability is Key:**
   - aptly's immutable Snapshots sind brilliant
   - Macht Rollbacks trivial
   - Enables Reproducible Environments
   - **Chantal MUSS diesem Prinzip folgen!**

2. **References vs. Copies:**
   - Niemals Package-Files kopieren
   - Immer References auf shared Pool
   - Cleanup basiert auf Reference-Counting
   - **Der korrekte Ansatz!**

3. **Separation of Concerns:**
   - Mirror-Management (Ingest)
   - Snapshot-Management (Versioning)
   - Publishing (Serving)
   - **Wie aptly: Separate halten!**

4. **Performance Matters:**
   - Architecture allein reicht nicht
   - Von Anfang an für Performance designen
   - Parallel Operations, Caching, Optimization sind kritisch
   - **aptly's Performance-Issues zeigen das!**

---

## Comprehensive Tool Comparison Matrix

| Kriterium | reposync | Pulp 3 | apt-mirror | aptly | **Chantal (Ziel)** |
|-----------|----------|--------|------------|-------|-------------------|
| **Ecosystem** | RPM/YUM/DNF | Multi (Plugins) | APT/Debian | APT/Debian | **APT + RPM** |
| **Architektur** | CLI Plugin | Service + DB | CLI Tool | CLI + API | **CLI + Optional API** |
| **Sprache** | Python | Python (Django) | Perl | Go | **Rust** |
| **Datenbank** | Keine | PostgreSQL | Keine | LevelDB | **PostgreSQL** |
| **Deduplikation** | ❌ Keine | ✅ Content-addressed | ❌ Keine (ext. Tools) | ✅ SHA256 Pool | **✅ SHA256-based** |
| **Snapshots** | ❌ Keine | ✅ Versioning | ❌ Keine | ✅ Immutable | **✅ Immutable** |
| **Storage-Model** | Flat/Repo-Struktur | Content-addressed | Pool-compliant Mirror | Content-addressed | **Content-addressed** |
| **Credential-Handling** | Via DNF Config | Via Remote (encrypted) | URL/auth.conf | ⚠️ Limitiert | **Secure YAML + Keyring** |
| **Client-Certs** | ✅ DNF sslclientcert | ✅ client_cert | ❌ Nicht supported | ❌ Nicht supported | **✅ Full Support** |
| **Resume/Retry** | ✅ Ja (DNF) | ✅ Ja | ❌ Nein | ✅ Ja | **✅ Robust** |
| **Parallel Downloads** | ✅ Ja | ✅ Ja | ✅ 20 Threads (wget) | ✅ Ja | **✅ Configurable** |
| **Performance** | Schnell | Sehr schnell | Schnell | ⚠️ Langsames Publish | **Optimiert** |
| **Maintenance** | ✅ Aktiv (Red Hat) | ✅ Aktiv | ❌ Unmaintained | ✅ Aktiv | **✅ Modern Stack** |
| **Complexity** | ⭐ Niedrig | ⭐⭐⭐⭐ Sehr Hoch | ⭐ Niedrig | ⭐⭐⭐ Mittel | **⭐⭐ Moderat** |
| **Use-Case** | Simple RPM Mirror | Enterprise Platform | Simple APT Mirror | Advanced APT Mgmt | **Unified Offline Mirror** |
| **REST API** | ❌ Nein | ✅ Ja (Django REST) | ❌ Nein | ✅ Ja | **Optional** |
| **Repo-Mixing** | ❌ Nein | ⚠️ Kompliziert | ❌ Nein | ✅ Snapshot-Merge | **✅ Snapshot-Merge** |
| **Multi-Component** | N/A (RPM) | ⚠️ Per-Dist URLs | ✅ Ja | ✅ Exzellent | **✅ Ja** |

---

## Finalized Design-Entscheidungen für Chantal

### 1. Credential-Handling ✅ FINAL

**Ansatz:** Hybrid - Secure YAML Config + Optional System-Integration

```yaml
repos:
  - name: rhel9-baseos
    type: rpm
    upstream: https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os

    # Option A: Auto-Discovery (subscription-manager) - Optional
    credentials:
      type: subscription_manager  # Liest /etc/pki/entitlement/

    # Option B: Client-Zertifikate (RPM/RHEL)
    credentials:
      type: client_cert
      cert: /path/to/cert.pem
      key: /path/to/key.pem
      ca_cert: /path/to/ca.pem

    # Option C: HTTP Basic Auth
    credentials:
      type: basic
      username: myuser
      password: ${ENV_VAR}  # oder Keyring-Integration

  - name: ubuntu-jammy
    type: apt
    upstream: http://archive.ubuntu.com/ubuntu
    distribution: jammy
    components: [main, restricted, universe]

    # Option D: Authenticated APT Repository
    credentials:
      type: basic
      username: ${APT_USER}
      password_command: "pass show apt/ubuntu"  # External Password Manager
```

**Implementation:**
- Python `requests`: `cert=(cert_file, key_file)` für Client-Certs
- Rust `reqwest`: Analog
- Environment-Variables für Secrets
- Optional: Keyring-Integration (OS-Keychain)

**Sicherheit:**
- ❌ KEINE URL-embedded Credentials
- ✅ Environment Variables
- ✅ External Password Managers
- ✅ Optional: OS Keyring

### 2. Storage-Architektur ✅ FINAL

**Content-Addressed Storage (aptly + Pulp 3 Modell):**

```
chantal/
├── data/                      # Deduplicated Content Pool
│   └── sha256/
│       ├── ab/cd/abcdef123..._package.deb
│       ├── 12/34/123456789..._package.rpm
│       └── ...
├── repos/                     # Published Repositories (Symlinks/Hardlinks)
│   ├── rhel9-baseos/
│   │   ├── Packages/          # Hardlinks → data/
│   │   └── repodata/          # RPM Metadata
│   └── ubuntu-jammy/
│       ├── dists/             # APT Metadata
│       └── pool/              # Hardlinks → data/
├── snapshots/                 # Immutable Snapshots
│   ├── rhel9-baseos/
│   │   ├── 2025-01-09/        # Snapshot-Timestamp
│   │   ├── 2025-01-15/
│   │   └── latest -> 2025-01-15/
│   └── ubuntu-jammy/
│       └── 2025-01-09/
└── metadata.db               # PostgreSQL (Package-Metadata, References)
```

**Key Points:**
- SHA256-based Pool: `sha256/[0:2]/[2:4]/[4:64]_filename`
- Hardlinks oder Reflinks für Published Repos
- Snapshots als DB-References (wie aptly)
- Automatic Cross-Repository Deduplication

### 3. Snapshot-System ✅ FINAL

**Immutable, Reference-Based (aptly + Pulp 3 Modell):**

```bash
# Sync mit auto-snapshot
chantal sync rhel9-baseos --snapshot

# Erstellt DB-Eintrag:
# - snapshot_id: rhel9-baseos-2025-01-09
# - package_refs: [pkg1_id, pkg2_id, ...]
# - immutable: true

# Snapshot-Merge
chantal snapshot merge \
  --name custom-rhel9 \
  --sources rhel9-baseos-latest,internal-rpms-latest \
  --strategy latest  # oder rightmost, keep-all

# Snapshot-Publish
chantal publish snapshot rhel9-baseos-2025-01-09 \
  --to /var/www/repos/rhel9

# Atomic Snapshot-Switch
chantal publish switch rhel9-baseos \
  --from 2025-01-09 \
  --to 2025-01-15
```

**Implementation:**
- Snapshots sind **immutable Package-Reference-Lists** in PostgreSQL
- Publishing erstellt Hardlinks aus data/ Pool
- Switching ist atomic (Symlink-Swap)
- Cleanup entfernt unreferenzierte Packages

**Vorteile:**
- Zero-Copy Snapshots (nur DB-Einträge)
- Triviale Rollbacks
- Patch-Management
- Reproduzierbare Environments

### 4. State-Management ✅ FINAL

**PostgreSQL mit Hybrid-Ansatz:**

```sql
-- Packages (dedupliziert)
CREATE TABLE packages (
  id SERIAL PRIMARY KEY,
  sha256 TEXT UNIQUE NOT NULL,
  filename TEXT NOT NULL,
  size BIGINT NOT NULL,
  package_type TEXT NOT NULL,  -- 'rpm' or 'deb'
  arch TEXT,
  name TEXT,
  version TEXT,
  metadata JSONB,  -- Type-spezifische Metadata
  first_seen TIMESTAMP DEFAULT NOW(),
  UNIQUE(package_type, arch, name, version, sha256)
);

-- Repositories
CREATE TABLE repositories (
  id SERIAL PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  type TEXT NOT NULL,  -- 'rpm' or 'apt'
  upstream_url TEXT,
  config JSONB,
  last_sync TIMESTAMP
);

-- Snapshots (Immutable)
CREATE TABLE snapshots (
  id SERIAL PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  repository_id INTEGER REFERENCES repositories(id),
  created_at TIMESTAMP DEFAULT NOW(),
  immutable BOOLEAN DEFAULT TRUE
);

-- Snapshot-Package-References
CREATE TABLE snapshot_packages (
  snapshot_id INTEGER REFERENCES snapshots(id),
  package_id INTEGER REFERENCES packages(id),
  PRIMARY KEY (snapshot_id, package_id)
);

-- Sync-History
CREATE TABLE sync_history (
  id SERIAL PRIMARY KEY,
  repository_id INTEGER REFERENCES repositories(id),
  started_at TIMESTAMP,
  completed_at TIMESTAMP,
  packages_added INTEGER,
  packages_removed INTEGER,
  bytes_downloaded BIGINT,
  status TEXT  -- 'success', 'failed', 'interrupted'
);
```

**Filesystem-State (minimal):**
```
chantal/
└── cache/
    ├── http_cache/      # ETags, Last-Modified für HTTP-Requests
    └── temp_downloads/  # Partial Downloads für Resume
```

**Vorteile:**
- Queryable Metadata (PostgreSQL)
- ACID Transactions
- Reference-Counting für Cleanup
- Sync-History für Auditing
- Horizontal Scalability (Read-Replicas)

### 5. Plugin-System ✅ FINAL

**Einfaches Rust Trait-basiertes Plugin-System:**

```rust
// chantal/core/src/plugin.rs
pub trait RepoPlugin: Send + Sync {
    fn type_name(&self) -> &'static str;

    async fn sync(
        &self,
        config: &RepoConfig,
        storage: &ContentStorage,
        db: &Database
    ) -> Result<SyncResult>;

    async fn publish(
        &self,
        snapshot: &Snapshot,
        storage: &ContentStorage,
        target_path: &Path
    ) -> Result<()>;

    fn validate_config(&self, config: &RepoConfig) -> Result<()>;
}

// chantal/plugins/rpm/src/lib.rs
pub struct RpmPlugin;

impl RepoPlugin for RpmPlugin {
    fn type_name(&self) -> &'static str { "rpm" }

    async fn sync(&self, config, storage, db) -> Result<SyncResult> {
        // 1. Download repomd.xml
        // 2. Parse Metadata (primary.xml.gz, etc.)
        // 3. Download Pakete (parallel)
        // 4. SHA256-Verify + Store in Pool
        // 5. Update DB
    }

    async fn publish(&self, snapshot, storage, target_path) -> Result<()> {
        // 1. Create target_path/Packages/
        // 2. Hardlink Packages aus Pool
        // 3. Copy Metadaten (repodata/)
        // 4. Optional: GPG-Sign repomd.xml
    }
}

// chantal/plugins/apt/src/lib.rs
pub struct AptPlugin;

impl RepoPlugin for AptPlugin {
    fn type_name(&self) -> &'static str { "apt" }

    async fn sync(&self, config, storage, db) -> Result<SyncResult> {
        // 1. Download InRelease / Release
        // 2. Download Packages.gz, Sources.gz
        // 3. Parse Package-Lists
        // 4. Download .deb Files (parallel)
        // 5. SHA256-Verify + Store in Pool
        // 6. Update DB
    }

    async fn publish(&self, snapshot, storage, target_path) -> Result<()> {
        // 1. Create pool/ Structure
        // 2. Hardlink .debs aus Pool
        // 3. Generate Packages, Release Files
        // 4. GPG-Sign InRelease
    }
}
```

**Plugin-Registry:**
```rust
pub struct PluginRegistry {
    plugins: HashMap<String, Box<dyn RepoPlugin>>
}

impl PluginRegistry {
    pub fn register_defaults() -> Self {
        let mut registry = Self { plugins: HashMap::new() };
        registry.register(Box::new(RpmPlugin));
        registry.register(Box::new(AptPlugin));
        registry
    }

    pub fn get(&self, type_name: &str) -> Option<&dyn RepoPlugin> {
        self.plugins.get(type_name).map(|b| b.as_ref())
    }
}
```

**Vorteile:**
- Einfaches Trait-Interface
- Compile-Time Plugin-Registration
- Type-Safety durch Rust
- Async-Support
- Leicht testbar

---

## Zusammenfassung: Was Chantal besser macht

### vs. reposync
1. ✅ Multi-Ecosystem (APT + RPM statt nur RPM)
2. ✅ Content-Addressed Storage mit Deduplikation
3. ✅ Snapshot-System
4. ✅ Standalone-Tool (kein DNF-Dependency)

### vs. Pulp 3
1. ✅ Einfacher: CLI-only, kein Service-Stack
2. ✅ Niedrigere Complexity (kein Django, Worker, Redis)
3. ✅ Fokussiert auf Offline-Mirroring (nicht Full Enterprise Platform)
4. ⚠️ Ähnlich: Content-Addressed Storage, Snapshots (Pulp's Design ist gut!)

### vs. apt-mirror
1. ✅ Aktive Maintenance (apt-mirror: unmaintained)
2. ✅ Content-Addressed Storage (apt-mirror: keine Dedup)
3. ✅ Resume/Retry (apt-mirror: fehlt)
4. ✅ Robuste Metadaten-Handling
5. ✅ Client-Cert Support
6. ✅ Multi-Ecosystem (apt-mirror: nur APT)

### vs. aptly
1. ✅ Multi-Ecosystem (aptly: nur APT)
2. ✅ Performance: Optimiertes Publishing (aptly: sehr langsam)
3. ✅ PostgreSQL statt LevelDB (bessere Scalability)
4. ✅ Multi-Threaded Operations
5. ✅ Robust Auth (aptly: schwach)
6. ⚠️ Ähnlich: Snapshot-System, Content-Addressed Storage (aptly's Design ist gut!)

---

### Nächste Schritte:

- [x] APT-Tools analysieren (apt-mirror, aptly)
- [x] Architektur-Proposal erstellen (detailliertes Design-Doc)
- [x] MVP-Scope definieren
- [x] Technology-Stack finalisieren (Python + Click + SQLAlchemy + Pydantic)
- [x] Proof-of-Concept: RHEL CDN Auth testen
- [x] Proof-of-Concept: Content-Addressed Storage implementieren

---

## Implementation Decisions (January 2026)

Die folgenden Design-Entscheidungen wurden während der Implementation (2026-01-09 bis 2026-01-10) getroffen:

### 1. Generic ContentItem Model (2026-01-10)

**Problem:** Ursprüngliche Schema hatte separate `packages` Tabelle für RPM-Pakete. Bei Unterstützung weiterer Content-Typen (APT, Helm, PyPI) wären separate Tabellen (`deb_packages`, `helm_charts`, etc.) notwendig → Schema-Changes für jeden neuen Plugin.

**Entscheidung:** Generic ContentItem Model mit JSON Metadata (inspiriert von Pulp 3 Ansatz)

**Implementation:**
```python
class ContentItem(Base):
    __tablename__ = "content_items"

    id = Column(Integer, primary_key=True)
    sha256 = Column(String(64), unique=True, nullable=False, index=True)
    filename = Column(String, nullable=False)
    size = Column(BigInteger, nullable=False)
    content_type = Column(String, nullable=False, index=True)  # 'rpm', 'deb', 'helm', etc.
    content_metadata = Column(JSON, nullable=False)  # Type-specific metadata
    created_at = Column(DateTime, default=datetime.utcnow)
```

**Type-Safe Metadata via Pydantic:**
```python
class RpmMetadata(BaseModel):
    """Type-safe RPM metadata model"""
    name: str
    version: str
    release: str
    epoch: Optional[int] = None
    arch: str
    source_rpm: Optional[str] = None
    # ... weitere RPM-spezifische Fields
```

**Vorteile:**
- ✅ Keine Schema-Changes für neue Plugins nötig
- ✅ Type-Safety durch Pydantic Models
- ✅ Flexibel für verschiedene Content-Typen
- ✅ Einfache Migration: Generic `content_items` statt `packages`

**Referenzen:**
- Issue #15: Generic Content Model Migration
- Alembic Migration: `a4a922fdfc63` (packages → content_items)
- Code: `src/chantal/db/models.py:ContentItem`
- Code: `src/chantal/plugins/rpm/models.py:RpmMetadata`

### 2. View Publishing Without DB Sync (2026-01-10)

**Problem:** Ursprüngliche Implementation erforderte `chantal view sync` vor `chantal publish view` → Views mussten in DB gespeichert werden, obwohl sie nur Gruppierungen von Repositories sind.

**User-Feedback:** "warum view sync? wir haben doch gesagt nur nen publish? warum müssen wir da was zur db syncen?"

**Entscheidung:** Views werden direkt aus Config published, KEINE DB-Persistenz notwendig

**Implementation:**
```python
# ViewPublisher.publish_view_from_config()
def publish_view_from_config(
    self,
    session: Session,
    repo_ids: List[str],  # Direct from YAML config
    target_path: Path,
) -> int:
    """Publish view directly from config (no DB view object needed)"""
    repositories = []
    for repo_id in repo_ids:
        repo = session.query(Repository).filter_by(repo_id=repo_id).first()
        if not repo:
            raise ValueError(f"Repository '{repo_id}' not found")
        repositories.append(repo)

    packages = self._get_packages_from_repositories(session, repositories)
    self._publish_packages(packages, target_path)
    return len(packages)
```

**Workflow:**
```bash
# YAML Config
views:
  - name: rhel9-complete
    repos: [rhel9-baseos, rhel9-appstream, epel9]

# Publishing (OHNE vorherigen view sync!)
chantal publish view --name rhel9-complete
```

**Vorteile:**
- ✅ Einfacherer Workflow (ein Schritt weniger)
- ✅ Views sind stateless (nur Gruppierung)
- ✅ Keine unnötige DB-Persistenz
- ✅ Config ist Single Source of Truth

**Code:**
- `src/chantal/cli/main.py:publish_view()` - Refactored
- `src/chantal/plugins/view_publisher.py:publish_view_from_config()` - New method

### 3. Snapshot Copy for Promotion Workflows (2026-01-10)

**Use-Case:** Promotion Workflows (testing → stable → production)

**User-Request:** "können wir vielleicht noch schauen das wir einen snapshot copy einbauen? damit man quasi von redhat-base-os-2025-01 nach redhat-base-os-stable kopieren kann?"

**Entscheidung:** Zero-Copy Snapshot Copy (nur DB, keine File-Operationen)

**Implementation:**
```python
# CLI Command
@snapshot.command("copy")
@click.option("--source", required=True)
@click.option("--target", required=True)
@click.option("--repo-id", required=True)
def snapshot_copy(ctx, source, target, repo_id, description):
    """Copy a snapshot to a new name (enables promotion workflows)."""
    source_snapshot = session.query(Snapshot).filter_by(
        repository_id=repo.id,
        name=source
    ).first()

    # Create new snapshot with SAME content_items references
    new_snapshot = Snapshot(
        repository_id=source_snapshot.repository_id,
        name=target,
        description=description or f"Copy of '{source}'",
        package_count=source_snapshot.package_count,
        total_size_bytes=source_snapshot.total_size_bytes,
    )
    new_snapshot.content_items = list(source_snapshot.content_items)  # Reference copy!
    session.add(new_snapshot)
```

**Workflow:**
```bash
# Testing Phase
chantal snapshot create --repo-id rhel9-baseos --name 2025-01
chantal publish snapshot --name rhel9-baseos-2025-01

# After Testing: Promote to Stable
chantal snapshot copy --repo-id rhel9-baseos --source 2025-01 --target stable
chantal publish snapshot --name rhel9-baseos-stable

# Later: Promote to Production
chantal snapshot copy --repo-id rhel9-baseos --source stable --target production
chantal publish snapshot --name rhel9-baseos-production
```

**Vorteile:**
- ✅ Zero-Copy (nur DB-Einträge, keine File-Kopien)
- ✅ Instant Operation (Millisekunden)
- ✅ Ermöglicht Promotion Pipelines
- ✅ Nutzt Content-Addressed Storage optimal

**Code:**
- `src/chantal/cli/main.py:snapshot_copy()` - Lines 1326-1409

### 4. SQLite as Default Database (2026-01-09)

**Original Plan:** PostgreSQL (wie in findings.md dokumentiert)

**Entscheidung:** SQLite als Default, PostgreSQL optional

**Begründung:**
- ✅ Einfacheres Setup für MVP und kleinere Deployments
- ✅ Keine externe DB-Installation notwendig
- ✅ Ausreichend für typische Use-Cases (bis ~100k Packages)
- ✅ SQLAlchemy macht Migration zu PostgreSQL trivial
- ✅ Embedded DB besser für CLI-Tool

**Configuration:**
```python
# Config
database_url = os.getenv(
    "CHANTAL_DATABASE_URL",
    "sqlite:///var/lib/chantal/chantal.db"
)

# PostgreSQL möglich via:
export CHANTAL_DATABASE_URL="postgresql://user:pass@localhost/chantal"
```

**Migration Path:**
- SQLite für Entwicklung, Testing, kleine Deployments
- PostgreSQL für große Production Deployments (> 100k Packages)
- Beide nutzen gleiche SQLAlchemy Models → kein Code-Change

**Code:**
- `src/chantal/db/connection.py:DatabaseManager`

### 5. View Deduplication Strategy (2026-01-10)

**Frage:** Sollten Views Pakete deduplizieren wenn mehrere Repos dasselbe Package haben?

**Beispiel:**
```yaml
views:
  - name: rhel9-complete
    repos: [rhel9-baseos, rhel9-appstream]
    # Beide Repos haben möglicherweise "bash-5.1-1.el9.x86_64.rpm"
```

**Entscheidung:** KEINE Deduplikation in Views

**Begründung:**
- DNF/YUM Client entscheidet welche Package-Version zu nutzen ist
- Repository-Priorität wird vom Client gesteuert (nicht von Chantal)
- View ist nur eine Gruppierung, keine intelligente Merge-Operation
- Wenn Deduplikation gewünscht ist → Snapshot-Merge nutzen

**Implementation:**
```python
def _get_packages_from_repositories(self, session, repositories):
    """Get all packages from repositories (NO deduplication)"""
    all_packages = []
    for repo in repositories:
        all_packages.extend(repo.content_items)
    return all_packages  # Duplicates möglich!
```

**Alternative:** Für deduplizierte Views → Snapshot-Merge verwenden:
```bash
chantal snapshot create --repo-id rhel9-baseos --name baseos-latest
chantal snapshot create --repo-id rhel9-appstream --name appstream-latest
chantal snapshot merge \
  --sources baseos-latest,appstream-latest \
  --target rhel9-merged \
  --strategy latest  # Höchste Version gewinnt
chantal publish snapshot --name rhel9-merged
```

**Code:**
- `src/chantal/plugins/view_publisher.py:_get_packages_from_repositories()`

---

## Aktuelle Architektur (Stand 2026-01-10)

**Implemented:**
- ✅ Content-Addressed Storage (SHA256 Pool)
- ✅ Generic ContentItem Model (RPM functional, APT/Helm vorbereitet)
- ✅ Pydantic Configuration System
- ✅ RPM Plugin (RHEL CDN Auth, Filtering, Post-Processing)
- ✅ Immutable Snapshots (Reference-based)
- ✅ Snapshot Copy (Zero-Copy Promotion)
- ✅ Views (Virtual Repositories, Config-based Publishing)
- ✅ Hardlink-based Publishing (Zero-Copy)
- ✅ SQLite Database (PostgreSQL optional)

**Test Coverage:** 74 tests passing

**Next Steps:** Database Management Commands (Issue #14)
