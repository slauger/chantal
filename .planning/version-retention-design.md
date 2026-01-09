# Version Retention & Package Lifecycle Design

**Datum:** 2025-01-09
**Kritisches Design-Dokument**

---

## Problem-Statement

Verschiedene Upstream-Repositories haben unterschiedliche Policies:

- **RHEL Base Repos:** Behalten mehrere Versionen (z.B. kernel 5.14.0-1, 5.14.0-2, 5.14.0-3)
  - **Rationale:** Rollback bei Problem-Kernel

- **EPEL:** Nur neueste Version (z.B. nginx 1.20 → 1.22, alte wird gelöscht)
  - **Rationale:** Platzsparend, nur aktuellste Version relevant

- **Ubuntu:** Mix - Security Updates meist nur newest, aber mehrere Kernel-Versionen

**Chantal muss:**
1. Beide Patterns unterstützen
2. Konfigurierbar sein (per Repository)
3. Gelöschte Pakete behandeln können
4. Rollback-Szenarien ermöglichen

---

## Retention Policies

### Policy-Typen

| Policy | Beschreibung | Use-Case | Beispiel |
|--------|--------------|----------|----------|
| **mirror** | Exaktes Mirror - Was Upstream macht, macht Chantal auch | Standard-Mirroring | RHEL Base |
| **newest-only** | Nur neueste Version jedes Paketes | Platzsparend, EPEL-Style | EPEL |
| **keep-all** | Alle Versionen behalten, nie löschen | Max. Rollback-Optionen | Eigene Repos |
| **keep-last-n** | Letzte N Versionen behalten | Compromise | Ubuntu |

### Detailed Behavior

#### 1. mirror (Default)

```yaml
# /etc/chantal/conf.d/rhel9-baseos.yaml
name: rhel9-baseos
type: rpm
retention:
  policy: mirror
```

**Verhalten:**

- **Upstream hat:** pkg-1.0, pkg-2.0, pkg-3.0 → **Chantal hat:** pkg-1.0, pkg-2.0, pkg-3.0
- **Upstream löscht:** pkg-1.0 → **Chantal löscht auch:** pkg-1.0
- **Upstream fügt hinzu:** pkg-4.0 → **Chantal fügt hinzu:** pkg-4.0

**Implementation:**

```python
def sync_mirror_policy(upstream_packages, local_packages):
    """Mirror exactly what upstream has."""

    upstream_set = {(pkg.name, pkg.version, pkg.arch) for pkg in upstream_packages}
    local_set = {(pkg.name, pkg.version, pkg.arch) for pkg in local_packages}

    # Add new packages
    to_add = upstream_set - local_set

    # Remove deleted packages
    to_remove = local_set - upstream_set

    return to_add, to_remove
```

#### 2. newest-only (EPEL-Style)

```yaml
name: epel9
type: rpm
retention:
  policy: newest-only
```

**Verhalten:**

- **Upstream hat:** pkg-1.0, pkg-2.0, pkg-3.0 → **Chantal speichert nur:** pkg-3.0
- **Upstream fügt hinzu:** pkg-4.0 → **Chantal:** Löscht pkg-3.0, speichert pkg-4.0

**Rollback:**
- ❌ **Nicht möglich** mit dieser Policy alleine
- ✅ **Aber:** Snapshots ermöglichen Rollback auf Repository-Level!

**Implementation:**

```python
def sync_newest_only_policy(upstream_packages, local_packages):
    """Keep only newest version of each package."""

    from packaging import version

    # Group by (name, arch)
    grouped = {}
    for pkg in upstream_packages:
        key = (pkg.name, pkg.arch)
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(pkg)

    # Select newest version for each (name, arch)
    newest = []
    for key, packages in grouped.items():
        newest_pkg = max(packages, key=lambda p: version.parse(p.version))
        newest.append(newest_pkg)

    # Remove all old versions from local
    local_set = {(pkg.name, pkg.version, pkg.arch) for pkg in local_packages}
    newest_set = {(pkg.name, pkg.version, pkg.arch) for pkg in newest}

    to_add = newest_set - local_set
    to_remove = local_set - newest_set

    return to_add, to_remove
```

#### 3. keep-all (Accumulated)

```yaml
name: internal-rpms
type: rpm
retention:
  policy: keep-all
```

**Verhalten:**

- **Upstream hat:** pkg-1.0, pkg-2.0 → **Chantal hat:** pkg-1.0, pkg-2.0
- **Upstream löscht:** pkg-1.0 → **Chantal behält:** pkg-1.0, pkg-2.0
- **Upstream fügt hinzu:** pkg-3.0 → **Chantal hat:** pkg-1.0, pkg-2.0, pkg-3.0

**Vorteile:**
- Max. Rollback-Optionen
- Accumulated Mirror (wächst nur)

**Nachteile:**
- Platzbedarf steigt kontinuierlich
- Braucht manuelle Cleanup

**Implementation:**

```python
def sync_keep_all_policy(upstream_packages, local_packages):
    """Keep all versions, never delete."""

    upstream_set = {(pkg.name, pkg.version, pkg.arch) for pkg in upstream_packages}
    local_set = {(pkg.name, pkg.version, pkg.arch) for pkg in local_packages}

    # Only add new packages
    to_add = upstream_set - local_set

    # Never remove
    to_remove = set()

    return to_add, to_remove
```

#### 4. keep-last-n (Sliding Window)

```yaml
name: ubuntu-jammy
type: apt
retention:
  policy: keep-last-n
  keep_versions: 3  # Keep last 3 versions
```

**Verhalten:**

- **Upstream hat:** pkg-1.0, pkg-2.0, pkg-3.0, pkg-4.0 → **Chantal speichert:** pkg-2.0, pkg-3.0, pkg-4.0
- **Upstream fügt hinzu:** pkg-5.0 → **Chantal:** Löscht pkg-2.0, speichert pkg-5.0
- **Chantal hat dann:** pkg-3.0, pkg-4.0, pkg-5.0

**Compromise:** Rollback auf letzte N Versionen + Platzsparend

**Implementation:**

```python
def sync_keep_last_n_policy(upstream_packages, local_packages, keep_versions=3):
    """Keep last N versions of each package."""

    from packaging import version

    # Group by (name, arch)
    grouped = {}
    for pkg in upstream_packages:
        key = (pkg.name, pkg.arch)
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(pkg)

    # Select last N versions for each (name, arch)
    keep = []
    for key, packages in grouped.items():
        sorted_pkgs = sorted(packages, key=lambda p: version.parse(p.version), reverse=True)
        keep.extend(sorted_pkgs[:keep_versions])

    local_set = {(pkg.name, pkg.version, pkg.arch) for pkg in local_packages}
    keep_set = {(pkg.name, pkg.version, pkg.arch) for pkg in keep}

    to_add = keep_set - local_set
    to_remove = local_set - keep_set

    return to_add, to_remove
```

---

## Deleted Package Handling

**Separate Config für gelöschte Pakete:**

```yaml
retention:
  policy: newest-only

  # What to do when upstream deletes a package entirely (not just old version)
  deleted_packages: keep  # or 'remove'
```

### Options:

**1. remove (Mirror Exact)**

```yaml
deleted_packages: remove
```

- Package war in Upstream, ist jetzt komplett weg
- Chantal löscht es auch
- **Use-Case:** Exaktes Mirror

**2. keep (Accumulated)**

```yaml
deleted_packages: keep
```

- Package war in Upstream, ist jetzt weg
- Chantal behält es trotzdem
- **Use-Case:** "Was einmal da war, bleibt da"

**Example Scenario:**

```
# Upstream vor 1 Monat:
- nginx-1.20-1.el9.x86_64.rpm
- httpd-2.4.51-1.el9.x86_64.rpm

# Upstream heute:
- nginx-1.22-1.el9.x86_64.rpm
# httpd wurde komplett entfernt (EOL)

# Chantal mit deleted_packages: remove
- nginx-1.22-1.el9.x86_64.rpm
# httpd ist weg

# Chantal mit deleted_packages: keep
- nginx-1.22-1.el9.x86_64.rpm
- httpd-2.4.51-1.el9.x86_64.rpm  # Behalten!
```

---

## Config-Beispiele

### RHEL Base (Multiple Versions, Mirror Exact)

```yaml
name: rhel9-baseos
type: rpm
upstream:
  url: https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os

retention:
  policy: mirror
  deleted_packages: remove
```

### EPEL (Newest Only, But Keep Deleted)

```yaml
name: epel9
type: rpm
upstream:
  url: https://download.fedoraproject.org/pub/epel/9/Everything/x86_64/

retention:
  policy: newest-only
  deleted_packages: keep  # Keep packages that EPEL deletes (for rollback)
```

**Rationale für `deleted_packages: keep`:**
- EPEL löscht oft Pakete komplett (nicht nur alte Versionen)
- Wir wollen sie behalten falls Client noch braucht
- Kombiniert mit Snapshots → Rollback möglich

### Ubuntu (Keep Last 3, Mirror Deleted)

```yaml
name: ubuntu-jammy
type: apt
upstream:
  url: http://archive.ubuntu.com/ubuntu

retention:
  policy: keep-last-n
  keep_versions: 3
  deleted_packages: remove  # Mirror Ubuntu's deletions
```

### Internal Repo (Never Delete)

```yaml
name: company-internal
type: rpm
upstream:
  url: https://repos.company.internal/rpm

retention:
  policy: keep-all
  deleted_packages: keep
```

---

## Interaction mit Snapshots

**Wichtig:** Retention Policy betrifft nur "latest" Repo!

```yaml
# Repository Config
publish:
  latest_path: /var/www/repos/epel9/latest
  snapshots_path: /var/www/repos/epel9/snapshots

retention:
  policy: newest-only  # Nur für latest!
  deleted_packages: keep
```

**Workflow:**

1. **Sync:** Wendet Retention Policy an → Updated "latest"
2. **Snapshot:** Erstellt immutable Copy vom AKTUELLEN Stand

**Beispiel:**

```bash
# Tag 1: Sync
chantal repo sync --repo-id epel9
# latest/ hat: nginx-1.20 (newest)

# Tag 1: Snapshot
chantal snapshot create --repo-id epel9 --name 2025-01-01
# snapshots/2025-01-01/ hat: nginx-1.20

# Tag 30: Neues nginx im Upstream
chantal repo sync --repo-id epel9
# latest/ hat: nginx-1.22 (newest-only → 1.20 gelöscht!)

# Tag 30: Snapshot
chantal snapshot create --repo-id epel9 --name 2025-01-30
# snapshots/2025-01-30/ hat: nginx-1.22
# snapshots/2025-01-01/ hat: NOCH IMMER nginx-1.20 (immutable!)
```

**Rollback-Strategie:**

Clients können auf old snapshot switchen:

```bash
# Client yum config
[epel9]
baseurl=http://mirror.company.com/epel9/snapshots/2025-01-01/
# Nutzt nginx-1.20 obwohl latest nginx-1.22 hat!
```

---

## Database Schema Erweiterungen

```python
class Package(Base):
    """Package model with retention tracking."""
    __tablename__ = 'packages'

    id = Column(Integer, primary_key=True)
    sha256 = Column(String(64), unique=True, nullable=False)
    # ... existing fields ...

    # Retention tracking
    last_seen_in_upstream = Column(DateTime)  # When was this last in upstream?
    marked_for_deletion = Column(Boolean, default=False)
    deletion_reason = Column(String(50))  # 'superseded', 'removed_from_upstream', 'policy'

class RepositoryPackage(Base):
    """Many-to-many with retention info."""
    __tablename__ = 'repository_packages'

    repository_id = Column(Integer, ForeignKey('repositories.id'), primary_key=True)
    package_id = Column(Integer, ForeignKey('packages.id'), primary_key=True)

    # Tracking
    added_at = Column(DateTime, default=datetime.utcnow)
    removed_at = Column(DateTime, nullable=True)
    removal_reason = Column(String(100))

    # State
    is_active = Column(Boolean, default=True)
```

---

## CLI Commands

```bash
# Show retention policy
chantal repo show --repo-id epel9

# Override retention for single sync
chantal repo sync --repo-id epel9 --retention-policy keep-all

# Manual cleanup
chantal repo cleanup --repo-id epel9 --dry-run
chantal repo cleanup --repo-id epel9 --remove-marked

# Show deleted packages
chantal repo list-deleted --repo-id epel9

# Restore deleted package (if policy allows)
chantal repo restore-package --repo-id epel9 --package nginx-1.20-1.el9
```

---

## Implementation Flow

```python
async def sync_repository(repo_config: RepoConfig) -> SyncResult:
    """Sync repository with retention policy."""

    # 1. Get upstream packages
    upstream_packages = await plugin.fetch_package_list(repo_config.upstream)

    # 2. Get local packages
    local_packages = db.get_repository_packages(repo_config.name)

    # 3. Apply retention policy
    policy = repo_config.retention.policy

    if policy == 'mirror':
        to_add, to_remove = sync_mirror_policy(upstream_packages, local_packages)
    elif policy == 'newest-only':
        to_add, to_remove = sync_newest_only_policy(upstream_packages, local_packages)
    elif policy == 'keep-all':
        to_add, to_remove = sync_keep_all_policy(upstream_packages, local_packages)
    elif policy == 'keep-last-n':
        to_add, to_remove = sync_keep_last_n_policy(
            upstream_packages,
            local_packages,
            repo_config.retention.keep_versions
        )

    # 4. Handle deleted packages separately
    if repo_config.retention.deleted_packages == 'keep':
        # Filter out packages that were completely removed from upstream
        to_remove = filter_only_superseded(to_remove, upstream_packages)

    # 5. Download new packages
    for pkg_meta in to_add:
        await download_and_store(pkg_meta)

    # 6. Mark packages for removal (but don't delete from pool yet!)
    for pkg_meta in to_remove:
        db.mark_package_for_deletion(repo_config.name, pkg_meta)

    # 7. Publish updated repo
    await publish_manager.publish_latest(repo_config)

    return SyncResult(...)
```

---

## Testing Strategy

```python
@pytest.mark.parametrize("policy,upstream,local,expected_add,expected_remove", [
    # Mirror policy
    (
        'mirror',
        ['pkg-1.0', 'pkg-2.0', 'pkg-3.0'],  # upstream
        ['pkg-1.0', 'pkg-2.0'],              # local
        ['pkg-3.0'],                         # should add
        []                                   # should remove
    ),

    # Newest-only policy
    (
        'newest-only',
        ['pkg-1.0', 'pkg-2.0', 'pkg-3.0'],
        ['pkg-1.0', 'pkg-2.0'],
        ['pkg-3.0'],
        ['pkg-1.0', 'pkg-2.0']               # Remove old versions!
    ),

    # Keep-all policy
    (
        'keep-all',
        ['pkg-3.0'],                         # upstream only has 3.0
        ['pkg-1.0', 'pkg-2.0'],              # local has old versions
        ['pkg-3.0'],
        []                                   # Never remove!
    ),
])
def test_retention_policy(policy, upstream, local, expected_add, expected_remove):
    """Test retention policies."""
    # ...
```

---

## Performance Considerations

**Problem:** Version-Vergleich bei 100k+ Paketen kann langsam sein

**Lösung 1:** Caching

```python
# Cache parsed versions
@lru_cache(maxsize=100000)
def parse_version(version_string: str) -> version.Version:
    return version.parse(version_string)
```

**Lösung 2:** Bulk-Processing in DB

```sql
-- Find superseded packages directly in DB
WITH ranked_packages AS (
  SELECT
    id,
    name,
    version,
    arch,
    ROW_NUMBER() OVER (
      PARTITION BY name, arch
      ORDER BY version DESC
    ) as rn
  FROM packages
  WHERE repository_id = 123
)
SELECT id FROM ranked_packages WHERE rn > 3;  -- Keep only top 3
```

---

## Migration Path

**Default für bestehende Repos:**

```yaml
# Auto-generated for existing repos without retention config
retention:
  policy: mirror  # Safest default
  deleted_packages: keep  # Never lose data
```

**Recommendation in Docs:**

- **RHEL Base/AppStream:** `policy: mirror`
- **EPEL:** `policy: newest-only` + `deleted_packages: keep`
- **Ubuntu:** `policy: keep-last-n` mit `keep_versions: 3`
- **Internal Repos:** `policy: keep-all`

---

## Summary

✅ **Policies Defined:** mirror, newest-only, keep-all, keep-last-n
✅ **Deleted Package Handling:** keep vs. remove
✅ **Snapshot Interaction:** Policies nur für "latest", Snapshots immutable
✅ **Config Schema:** Klar definiert
✅ **Implementation Plan:** Ready to code
✅ **Testing Strategy:** Parametrized tests

**Nächster Schritt:** Integration in architecture.md und MVP-Scope
