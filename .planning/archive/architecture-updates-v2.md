# Architecture Updates v2 - Based on Feedback

**Datum:** 2025-01-09
**Basierend auf:** architecture.md v1

---

## Kern-Änderungen

### 1. CLI Syntax → Pulp-Style

**Vorher (v1):**
```bash
chantal repo sync rhel9-baseos
chantal snapshot create rhel9-baseos
```

**Jetzt (v2):**
```bash
chantal repo sync --repo-id rhel9-baseos
chantal snapshot create --repo-id rhel9-baseos --name 2025-01-patch1
```

**Rationale:**
- Konsistenter mit Pulp CLI
- Expliziter (--repo-id macht klar was der Parameter ist)
- Besser für Scripting (weniger Positions-abhängig)

---

### 2. Config-Struktur → Modular

**Vorher (v1):**
```
/etc/chantal/chantal.yaml    # Alles in einer Datei
```

**Jetzt (v2):**
```
/etc/chantal/
├── conf.d/
│   └── global.yaml          # Globale Settings (Storage, DB, etc.)
└── repos.d/
    ├── rhel9-baseos.yaml    # Ein Repo pro File
    ├── rhel9-appstream.yaml
    └── ubuntu-jammy.yaml
```

**Vorteile:**
- **Modular:** Repos einzeln hinzufügen/entfernen
- **Übersichtlich:** Nicht eine riesige YAML-Datei
- **Config-Management-freundlich:** Ansible/Puppet können einzelne Repo-Files deployen
- **Multi-Tenancy:** Verschiedene `/etc/chantal-tenant1/` Verzeichnisse möglich

#### Globale Config

**Datei:** `/etc/chantal/conf.d/global.yaml`

```yaml
# Global Chantal Configuration

# Storage paths
storage:
  base_path: /var/lib/chantal
  # Optional overrides:
  # pool_path: /mnt/storage/pool
  # cache_path: /var/cache/chantal

# Database
database:
  url: postgresql://chantal:password@localhost/chantal
  pool_size: 5

# Download settings
download:
  workers: 10
  retries: 5
  timeout: 300

# Logging
logging:
  level: INFO
  file: /var/log/chantal/chantal.log
  format: json  # or 'text'
```

#### Repository Config

**Datei:** `/etc/chantal/repos.d/rhel9-baseos.yaml`

```yaml
# RHEL 9 BaseOS Repository

name: rhel9-baseos
type: rpm
enabled: true

upstream:
  url: https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os

credentials:
  type: client_cert
  cert: /etc/pki/entitlement/1234567890.pem
  key: /etc/pki/entitlement/1234567890-key.pem
  ca_cert: /etc/rhsm/ca/redhat-uep.pem

# RPM-specific
rpm:
  gpgcheck: true
  gpgkey_url: https://access.redhat.com/security/data/fd431d51.txt
  architectures:
    - x86_64
    - aarch64

# Publishing
publish:
  # Path for "latest" sync (normal sync ohne --snapshot)
  latest_path: /var/www/repos/rhel9-baseos/latest

  # Snapshots werden hier erstellt (mit Snapshot-Name als Subdir)
  snapshots_path: /var/www/repos/rhel9-baseos/snapshots
```

**Datei:** `/etc/chantal/repos.d/ubuntu-jammy.yaml`

```yaml
# Ubuntu 22.04 (Jammy) Repository

name: ubuntu-jammy
type: apt
enabled: true

upstream:
  url: http://archive.ubuntu.com/ubuntu

apt:
  distribution: jammy
  components:
    - main
    - restricted
    - universe
    - multiverse
  architectures:
    - amd64
    - arm64
  gpgkey_url: https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x871920D1991BC93C

publish:
  latest_path: /var/www/repos/ubuntu/jammy/latest
  snapshots_path: /var/www/repos/ubuntu/jammy/snapshots
```

---

### 3. Snapshot-Konzept → Getrennt von Sync

**Neues Konzept:**

1. **Normaler Sync** → Schreibt in "latest" Repo (Pfad konfigurierbar)
2. **Snapshot** → Separater Befehl, erstellt immutable Kopie

#### Normal Sync

```bash
# Sync repository → published to latest_path
chantal repo sync --repo-id rhel9-baseos
```

**Was passiert:**
1. Download neue Pakete
2. Deduplizierung in Pool
3. Publish nach `/var/www/repos/rhel9-baseos/latest/`
4. Webserver kann sofort darauf zugreifen

**Filesystem nach Sync:**
```
/var/www/repos/rhel9-baseos/
└── latest/                    # Immer aktuelle Version
    ├── Packages/
    └── repodata/
```

#### Snapshot erstellen

```bash
# Create snapshot from current repo state
chantal snapshot create --repo-id rhel9-baseos --name 2025-01-patch1
```

**Was passiert:**
1. Aktuelle Package-Liste aus DB holen
2. Snapshot-Record in DB erstellen (immutable!)
3. Publish Snapshot nach `snapshots_path/2025-01-patch1/`

**Filesystem nach Snapshot:**
```
/var/www/repos/rhel9-baseos/
├── latest/                    # Wird bei jedem Sync updated
│   ├── Packages/
│   └── repodata/
└── snapshots/
    ├── 2025-01-patch1/        # Immutable!
    │   ├── Packages/
    │   └── repodata/
    └── 2025-01-patch2/
        ├── Packages/
        └── repodata/
```

#### Snapshot ohne vorherigen Publish

```bash
# Sync + Snapshot in einem Befehl (aber getrennte Pfade!)
chantal repo sync --repo-id rhel9-baseos --create-snapshot --snapshot-name 2025-01-patch1
```

**Was passiert:**
1. Sync + Publish nach `latest/`
2. Snapshot erstellen + Publish nach `snapshots/2025-01-patch1/`

**Vorteile:**
- **Klar getrennt:** Latest = Rolling, Snapshots = Immutable
- **Flexible Workflows:**
  - Nur Latest (immer aktuell für Dev)
  - Latest + Snapshots (Prod bekommt getestete Snapshots)
  - Nur Snapshots (kein Latest)

---

### 4. GPG Key Management

**In Repository Config:**

```yaml
# /etc/chantal/repos.d/rhel9-baseos.yaml

rpm:
  gpgcheck: true
  gpgkey_url: https://access.redhat.com/security/data/fd431d51.txt

  # Optional: Lokale GPG-Key-Datei
  # gpgkey_file: /etc/pki/rpm-gpg/RPM-GPG-KEY-redhat-release
```

**Was Chantal macht:**

1. **Beim Sync:**
   - Download GPG-Key von `gpgkey_url`
   - Speichern in `/var/lib/chantal/gpgkeys/<repo-name>.asc`
   - Importieren in GPG Keyring

2. **Beim Publish:**
   - GPG-Key kopieren nach `<publish_path>/RPM-GPG-KEY-<repo-name>`
   - Clients können Key dann von Mirror-Server holen

**Beispiel für APT:**

```yaml
# /etc/chantal/repos.d/ubuntu-jammy.yaml

apt:
  gpgkey_url: https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x871920D1991BC93C
```

**Publishing:**
```
/var/www/repos/ubuntu/jammy/latest/
├── dists/
│   └── jammy/
│       └── Release.gpg      # Signiert mit Key
├── pool/
└── ubuntu-archive-key.gpg   # Public Key für Clients
```

---

### 5. Updated CLI Commands

```bash
# Repository Management
chantal repo list                                    # List all configured repos
chantal repo sync --repo-id <name>                   # Sync repository to "latest"
chantal repo sync --repo-id <name> --create-snapshot # Sync + create snapshot
chantal repo sync --repo-id <name> --create-snapshot --snapshot-name <name>
chantal repo show --repo-id <name>                   # Show repo details

# Snapshot Management
chantal snapshot create --repo-id <name> --name <snapshot-name>
chantal snapshot list                                # List all snapshots
chantal snapshot list --repo-id <name>               # List snapshots for repo
chantal snapshot show --name <snapshot-name>         # Show snapshot details
chantal snapshot delete --name <snapshot-name>       # Delete snapshot (manual only!)
chantal snapshot diff --from <snap1> --to <snap2>    # Compare snapshots

# Snapshot Merging
chantal snapshot merge \
  --source <snap1> --source <snap2> \
  --name <merged-name> \
  --strategy latest                                  # or: rightmost, keep-all

# Publishing (explicit publish, if you don't want auto-publish)
chantal publish --repo-id <name>                     # Publish latest
chantal publish --snapshot-name <name>               # Publish snapshot

# Database & Cleanup
chantal db cleanup                                   # Remove unreferenced packages from pool
chantal db migrate                                   # Run database migrations

# Initialization
chantal init                                         # Create directories, DB schema
```

---

### 6. Config Loading Logic

**Python Code:**

```python
from pathlib import Path
import yaml
from typing import List

class ConfigLoader:
    """Load Chantal configuration from modular files."""

    def __init__(self, config_dir: Path = Path("/etc/chantal")):
        self.config_dir = config_dir
        self.conf_d = config_dir / "conf.d"
        self.repos_d = config_dir / "repos.d"

    def load(self) -> ChantalConfig:
        """Load complete configuration."""
        # Load global config
        global_config = self._load_global()

        # Load all repository configs
        repo_configs = self._load_repositories()

        return ChantalConfig(
            storage=global_config.get('storage', {}),
            database=global_config.get('database', {}),
            download=global_config.get('download', {}),
            logging=global_config.get('logging', {}),
            repositories=repo_configs
        )

    def _load_global(self) -> dict:
        """Load global configuration from conf.d/."""
        config = {}

        # Load all YAML files in conf.d/
        for yaml_file in self.conf_d.glob("*.yaml"):
            with open(yaml_file) as f:
                data = yaml.safe_load(f)
                config.update(data)

        return config

    def _load_repositories(self) -> List[RepoConfig]:
        """Load repository configurations from repos.d/."""
        repos = []

        for yaml_file in sorted(self.repos_d.glob("*.yaml")):
            with open(yaml_file) as f:
                data = yaml.safe_load(f)

            # Validate and create RepoConfig
            if data.get('type') == 'rpm':
                repo = RpmRepoConfig(**data)
            elif data.get('type') == 'apt':
                repo = AptRepoConfig(**data)
            else:
                raise ValueError(f"Unknown repo type: {data.get('type')}")

            repos.append(repo)

        return repos
```

**CLI Integration:**

```python
@click.group()
@click.option('--config-dir', type=Path, default='/etc/chantal',
              help='Configuration directory')
@click.pass_context
def cli(ctx, config_dir):
    """Chantal - Unified offline repository mirroring."""
    ctx.ensure_object(dict)

    loader = ConfigLoader(config_dir)
    ctx.obj['config'] = loader.load()

@cli.command()
@click.option('--repo-id', required=True)
@click.pass_context
def sync(ctx, repo_id):
    """Sync repository."""
    config = ctx.obj['config']

    # Find repository config
    repo = next((r for r in config.repositories if r.name == repo_id), None)
    if not repo:
        click.echo(f"Repository not found: {repo_id}")
        return

    # Sync...
```

---

### 7. Multi-Tenancy Support

**Approach:** Verschiedene Config-Verzeichnisse

```bash
# Tenant 1
chantal --config-dir /etc/chantal-prod/ repo sync --repo-id rhel9-baseos

# Tenant 2
chantal --config-dir /etc/chantal-dev/ repo sync --repo-id rhel9-baseos
```

**Config pro Tenant:**

```
/etc/chantal-prod/
├── conf.d/
│   └── global.yaml     # storage.base_path: /var/lib/chantal-prod
└── repos.d/
    └── rhel9.yaml

/etc/chantal-dev/
├── conf.d/
│   └── global.yaml     # storage.base_path: /var/lib/chantal-dev
└── repos.d/
    └── rhel9.yaml
```

Jeder Tenant hat:
- Eigenes Storage-Verzeichnis
- Eigene Database (oder Schema in shared DB)
- Eigene Publish-Pfade

---

### 8. Metadaten-Caching (Klarstellung)

**Problem:** Wiederholte Sync-Aufrufe sollen effizient sein

**Lösung:** HTTP-Caching mit ETags/Last-Modified

**Beispiel:**

```python
# Erster Sync: Download repomd.xml
response = requests.get(
    'https://cdn.redhat.com/...repodata/repomd.xml',
    cert=(cert, key)
)

# Cache ETag
cache_file = Path('/var/lib/chantal/cache/http/cdn.redhat.com/repomd.xml.etag')
cache_file.write_text(response.headers['ETag'])

# Zweiter Sync (5 Minuten später): Conditional Request
etag = cache_file.read_text()
response = requests.get(
    'https://cdn.redhat.com/...repodata/repomd.xml',
    cert=(cert, key),
    headers={'If-None-Match': etag}
)

if response.status_code == 304:
    # Not Modified - kein Download notwendig!
    print("Repository unchanged, skipping sync")
else:
    # Changed - download und sync
    ...
```

**Cache-Struktur:**

```
/var/lib/chantal/cache/
└── http/
    ├── cdn.redhat.com/
    │   ├── repomd.xml.etag
    │   └── repomd.xml.last-modified
    └── archive.ubuntu.com/
        └── InRelease.etag
```

**Konfigurierbar:**

```yaml
# /etc/chantal/conf.d/global.yaml

cache:
  enabled: true
  ttl: 3600  # Cache for 1 hour
  max_age: 86400  # Invalidate after 24 hours
```

---

### 9. Gekläre Offene Fragen

| Frage | Entscheidung |
|-------|--------------|
| **Metadaten-Caching** | Filesystem-Cache mit ETags/Last-Modified in `/var/lib/chantal/cache/http/` |
| **Snapshot-Retention** | Nur manuell per `chantal snapshot delete` |
| **GPG-Keys** | URL in Repo-Config, Download + Speichern in data dir, Publish mit Repo |
| **Monitoring** | TODO (nicht MVP), später Prometheus Metrics + JSON Logging |
| **Performance (asyncpg)** | Start mit psycopg2, asyncpg später wenn notwendig |
| **Performance (Redis)** | Nicht MVP, später evaluieren |
| **Multi-Tenancy** | Via `--config-dir` Flag, verschiedene Config-Verzeichnisse |
| **S3 Publishing** | **NEIN** - Nur lokales Filesystem! |

---

### 10. Neue Offene Fragen

1. **Sync-Scheduling:**
   - Soll Chantal built-in Scheduler haben?
   - Oder via systemd timer / cron?

   **→ Empfehlung:** systemd timer (wie im Proposal), kein built-in Scheduler

2. **Parallele Syncs:**
   - Mehrere Repos gleichzeitig syncen?
   - `chantal repo sync --all` mit Parallelisierung?

   **→ Empfehlung:** Ja, `--all` Flag mit `--workers N` Option

3. **Bandwidth-Limiting:**
   - Pro Repo oder global?
   ```yaml
   download:
     bandwidth_limit: 100M  # Mbps
   ```

4. **Failure-Handling:**
   - Was passiert wenn Sync mittendrin abbricht?
   - Rollback? Partial state?

   **→ Empfehlung:** Partial state OK, beim nächsten Sync weitermachen (Resume)

5. **Notification:**
   - Email bei Sync-Completion/Failure?
   - Webhook?

   **→ Empfehlung:** Nicht MVP, später via Plugin

---

## Migration von v1 zu v2

Wenn jemand bereits v1 Config hatte:

**Migration-Script:**

```python
#!/usr/bin/env python3
"""Migrate Chantal v1 config to v2."""

import yaml
from pathlib import Path

def migrate_v1_to_v2(v1_config_file: Path, output_dir: Path):
    """Migrate v1 single-file config to v2 modular config."""

    with open(v1_config_file) as f:
        v1_config = yaml.safe_load(f)

    # Create directories
    conf_d = output_dir / "conf.d"
    repos_d = output_dir / "repos.d"
    conf_d.mkdir(parents=True, exist_ok=True)
    repos_d.mkdir(parents=True, exist_ok=True)

    # Write global config
    global_config = {
        'storage': v1_config.get('storage', {}),
        'database': v1_config.get('database', {}),
        'download': v1_config.get('settings', {}).get('download', {}),
        'logging': v1_config.get('settings', {}).get('logging', {}),
    }

    with open(conf_d / "global.yaml", 'w') as f:
        yaml.dump(global_config, f, default_flow_style=False)

    # Write repository configs
    for repo in v1_config.get('repositories', []):
        repo_name = repo['name']

        with open(repos_d / f"{repo_name}.yaml", 'w') as f:
            yaml.dump(repo, f, default_flow_style=False)

    print(f"Migration complete! Config written to {output_dir}")

if __name__ == '__main__':
    migrate_v1_to_v2(
        Path('/etc/chantal/chantal.yaml'),
        Path('/etc/chantal-v2')
    )
```

---

## Zusammenfassung der Änderungen

✅ **CLI:** Pulp-style mit `--repo-id`
✅ **Config:** Modular `/etc/chantal/conf.d/` + `/etc/chantal/repos.d/`
✅ **Snapshots:** Getrennt von Sync, separate Pfade
✅ **GPG-Keys:** URL in Config, automatischer Download
✅ **Multi-Tenancy:** Via `--config-dir` Flag
✅ **Caching:** Filesystem-basiert mit ETags
✅ **S3:** NICHT implementieren (nur lokal)

**Nächster Schritt:** MVP-Scope Definition basierend auf v2 Architecture
