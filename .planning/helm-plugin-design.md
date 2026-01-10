# Helm Plugin Design Document

## Overview

This document describes the design for adding Helm chart repository support to Chantal. Helm repositories are simpler than RPM repositories, making them an ideal second plugin to validate our plugin architecture.

## Helm Repository Format

### Structure

A Helm chart repository consists of:

1. **index.yaml** - Metadata file listing all charts and versions
2. **Chart tarballs** - `.tgz` files containing packaged charts

Example repository structure:
```
https://charts.bitnami.com/bitnami/
├── index.yaml                    # Repository metadata
├── nginx-15.0.0.tgz             # Chart tarball
├── nginx-14.2.1.tgz             # Previous version
├── postgresql-12.5.0.tgz
└── redis-17.11.3.tgz
```

### index.yaml Format

```yaml
apiVersion: v1
entries:
  nginx:
    - name: nginx
      version: 15.0.0              # Chart version
      appVersion: "1.25.0"         # Application version
      description: NGINX Open Source Chart
      home: https://github.com/bitnami/charts
      sources:
        - https://github.com/bitnami/containers/tree/main/bitnami/nginx
      urls:
        - https://charts.bitnami.com/bitnami/nginx-15.0.0.tgz
      created: "2024-05-15T10:30:00Z"
      digest: sha256:abc123...     # SHA256 of the .tgz file
      maintainers:
        - name: Bitnami
          email: containers@bitnami.com
      icon: https://bitnami.com/assets/stacks/nginx/img/nginx-stack-220x234.png
      keywords:
        - nginx
        - http
        - web
        - www
      dependencies: []
    - name: nginx
      version: 14.2.1              # Previous version
      ...
  postgresql:
    - name: postgresql
      version: 12.5.0
      appVersion: "16.2.0"
      ...
```

### Key Differences from RPM

| Aspect | RPM | Helm |
|--------|-----|------|
| Metadata | XML (repomd.xml, primary.xml.gz) | YAML (index.yaml) |
| Packages | .rpm files | .tgz files |
| Signing | GPG signatures | Optional provenance files |
| Dependencies | Complex (provides/requires) | Simple (chart dependencies) |
| Metadata generation | createrepo_c / dnf | helm repo index |
| Versioning | epoch:version-release | Semantic versioning |

## Database Model

### HelmChart Table

```sql
CREATE TABLE helm_charts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repository_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    app_version TEXT,
    description TEXT,
    home TEXT,
    icon TEXT,
    created TEXT,
    digest TEXT,
    url TEXT NOT NULL,
    file_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    keywords TEXT,  -- JSON array
    maintainers TEXT,  -- JSON array
    sources TEXT,  -- JSON array
    dependencies TEXT,  -- JSON array

    FOREIGN KEY (repository_id) REFERENCES repositories(id) ON DELETE CASCADE,
    UNIQUE(repository_id, name, version)
);

CREATE INDEX idx_helm_charts_repo ON helm_charts(repository_id);
CREATE INDEX idx_helm_charts_name ON helm_charts(name);
CREATE INDEX idx_helm_charts_sha256 ON helm_charts(sha256);
```

### Snapshot Association

Reuse existing `snapshot_content` table:

```sql
-- Already exists, works for any content type
CREATE TABLE snapshot_content (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL,
    content_type TEXT NOT NULL,  -- 'rpm' or 'helm'
    content_id INTEGER NOT NULL,  -- References helm_charts.id or rpm_packages.id

    FOREIGN KEY (snapshot_id) REFERENCES snapshots(id) ON DELETE CASCADE
);
```

## Plugin Implementation

### 1. HelmSyncer (src/chantal/plugins/helm_syncer.py)

```python
class HelmSyncer(BaseSyncer):
    """Syncer plugin for Helm chart repositories."""

    async def sync(self, repo: Repository, config: GlobalConfig) -> SyncResult:
        """
        1. Fetch index.yaml from repo.feed
        2. Parse YAML to get chart list
        3. Apply filters (name patterns, version constraints)
        4. Download .tgz files to pool (SHA256-based)
        5. Store chart metadata in helm_charts table
        6. Return sync statistics
        """

    async def _fetch_index(self, url: str) -> dict:
        """Fetch and parse index.yaml"""

    async def _download_chart(self, url: str, digest: str) -> Path:
        """Download .tgz to pool, verify SHA256"""

    def _apply_filters(self, charts: list, filters: RepositoryFilters) -> list:
        """Apply name/version filters"""
```

### 2. HelmPublisher (src/chantal/plugins/helm_publisher.py)

```python
class HelmPublisher(PublisherPlugin):
    """Publisher plugin for Helm chart repositories."""

    async def publish_repository(self, repo: Repository, charts: list[HelmChart],
                                 target_dir: Path) -> None:
        """
        1. Create target directory structure
        2. Hardlink .tgz files from pool to target_dir
        3. Generate index.yaml from chart metadata
        4. Write index.yaml to target_dir
        """

    async def publish_snapshot(self, snapshot: Snapshot, charts: list[HelmChart],
                              target_dir: Path) -> None:
        """Same as publish_repository but for snapshot content"""

    async def publish_view(self, view: View, charts: list[HelmChart],
                          target_dir: Path) -> None:
        """Combine charts from multiple repos into single index.yaml"""

    def _generate_index_yaml(self, charts: list[HelmChart], base_url: str) -> str:
        """Generate Helm index.yaml from chart metadata"""
```

### 3. Configuration Support

#### Repository Configuration

```yaml
repositories:
  - id: bitnami
    name: "Bitnami Helm Charts"
    type: helm  # NEW TYPE
    feed: https://charts.bitnami.com/bitnami
    enabled: true

    filters:
      patterns:
        include:
          - "^nginx$"
          - "^postgresql$"
          - "^redis$"
        exclude:
          - "^.*-test$"
      helm:
        # Helm-specific filters
        min_chart_version: "1.0.0"
        max_chart_version: "99.0.0"
        app_version_patterns:
          - "^1\\..*"  # Only app version 1.x
      post_processing:
        only_latest_version: true
```

#### Filter Model Extension

```python
class HelmFilters(BaseModel):
    """Helm-specific filters."""
    min_chart_version: Optional[str] = None
    max_chart_version: Optional[str] = None
    app_version_patterns: Optional[list[str]] = None
    keywords: Optional[list[str]] = None  # Only charts with specific keywords

class RepositoryFilters(BaseModel):
    # ... existing fields ...
    helm: Optional[HelmFilters] = None
```

## CLI Integration

### Existing Commands (No Changes Needed)

All existing commands work automatically:

```bash
# Syncing
chantal repo sync --repo-id bitnami
chantal repo sync --pattern "helm-*"

# Snapshots
chantal snapshot create --repo-id bitnami --name nginx-stable-2025-01
chantal snapshot list --repo-id bitnami

# Publishing
chantal publish repo --repo-id bitnami
chantal publish snapshot --repo-id bitnami --snapshot nginx-stable-2025-01

# Views (combine multiple Helm repos)
chantal view create --name kubernetes-stack
chantal view add-repo --name kubernetes-stack --repo-id bitnami
chantal view add-repo --name kubernetes-stack --repo-id jetstack
chantal publish view --name kubernetes-stack

# Content inspection
chantal snapshot content --repo-id bitnami --snapshot nginx-stable-2025-01 --format json
```

### Helm-Specific Information

```bash
# Show chart details
chantal repo list --repo-id bitnami
# Output includes: X charts, Y versions, Z MB

# Snapshot content shows chart-specific fields
chantal snapshot content --repo-id bitnami --snapshot nginx-stable-2025-01
# Columns: Name, Chart Version, App Version, Size, Description
```

## Storage Integration

### Content-Addressed Pool

Helm charts integrate seamlessly with existing storage:

```
.chantal/pool/
├── ab/
│   └── cd/
│       └── abcdef123456..._nginx-15.0.0.tgz    # SHA256-based filename
└── 12/
    └── 34/
        └── 123456abcdef..._postgresql-12.5.0.tgz
```

### Publishing with Hardlinks

```
.chantal/published/
└── repositories/
    └── bitnami/
        ├── index.yaml                          # Generated metadata
        ├── nginx-15.0.0.tgz                   # Hardlink to pool
        ├── postgresql-12.5.0.tgz              # Hardlink to pool
        └── redis-17.11.3.tgz                  # Hardlink to pool
```

No changes needed to storage system - it's content-agnostic!

## Testing Strategy

### Unit Tests

```python
# tests/test_helm_syncer.py
def test_fetch_index_yaml()
def test_parse_chart_metadata()
def test_download_chart_to_pool()
def test_verify_chart_digest()
def test_apply_name_filters()
def test_apply_version_filters()

# tests/test_helm_publisher.py
def test_generate_index_yaml()
def test_publish_charts_with_hardlinks()
def test_publish_snapshot()
def test_publish_view_combines_charts()
```

### Integration Tests

```python
# tests/integration/test_helm_workflow.py
def test_sync_bitnami_repo()
def test_create_helm_snapshot()
def test_publish_helm_repo()
def test_helm_view_multi_repo()
```

### Manual Testing

Use real Helm repositories:

```bash
# Test with Bitnami
chantal repo add bitnami https://charts.bitnami.com/bitnami --type helm
chantal repo sync --repo-id bitnami

# Verify with helm client
helm repo add local http://localhost:8000/repositories/bitnami
helm search repo local/nginx
helm pull local/nginx
```

## Implementation Plan

### Phase 1: Core Implementation (Milestone 6)

1. ✅ Design document (this file)
2. ⏳ Database model and migration
3. ⏳ HelmSyncer implementation
4. ⏳ HelmPublisher implementation
5. ⏳ Configuration model updates
6. ⏳ Unit tests

### Phase 2: Integration (Milestone 6)

1. ⏳ Integration tests
2. ⏳ CLI testing with real repositories
3. ⏳ Example configurations
4. ⏳ Documentation updates

### Phase 3: Polish (Milestone 6)

1. ⏳ Performance optimization
2. ⏳ Error handling improvements
3. ⏳ User documentation
4. ⏳ Migration guide for users

## Architecture Validation

This implementation validates our plugin architecture:

✅ **Storage abstraction works**: Helm .tgz files use same SHA256 pool as RPM
✅ **Publisher abstraction works**: HelmPublisher implements same interface as RpmPublisher
✅ **Syncer abstraction works**: HelmSyncer follows same pattern as RpmSyncer
✅ **Snapshot system works**: Same snapshot tables work for RPM and Helm
✅ **View system works**: Views can combine repos regardless of type
✅ **CLI is type-agnostic**: No CLI changes needed for new type

### Potential Issues to Watch

1. **View mixing**: Should we allow mixing RPM and Helm in same view?
   - Decision: NO - Views must be homogeneous (all RPM or all Helm)
   - Add validation in view creation

2. **Filter complexity**: Helm has different filtering needs than RPM
   - Solution: Type-specific filter sections (`rpm:`, `helm:`)

3. **Metadata differences**: Helm has app_version, RPM has epoch:version-release
   - Solution: Type-specific fields in database, generic snapshot_content table

## Popular Helm Repositories

Example configurations to create:

1. **Bitnami** - https://charts.bitnami.com/bitnami
   - Most popular Helm charts
   - 50+ charts (nginx, postgresql, redis, kafka, etc.)

2. **Jetstack** - https://charts.jetstack.io
   - cert-manager (Let's Encrypt for Kubernetes)

3. **Prometheus Community** - https://prometheus-community.github.io/helm-charts
   - Prometheus, Grafana, Alert Manager

4. **Ingress NGINX** - https://kubernetes.github.io/ingress-nginx
   - Official NGINX Ingress Controller

5. **Rancher** - https://charts.rancher.io
   - Rancher, Longhorn, Fleet

6. **HashiCorp** - https://helm.releases.hashicorp.com
   - Vault, Consul on Kubernetes

## Client Usage

After publishing, clients use standard Helm commands:

```bash
# Add repository
helm repo add my-mirror http://mirror.example.com/chantal/repositories/bitnami

# Update repository index
helm repo update

# Search for charts
helm search repo my-mirror/nginx

# Install chart
helm install my-nginx my-mirror/nginx --version 15.0.0

# Use snapshot (frozen version)
helm repo add my-mirror-stable http://mirror.example.com/chantal/repositories/bitnami/snapshots/2025-01
```

## Success Criteria

Helm plugin is successful if:

1. ✅ Can sync charts from real Helm repositories
2. ✅ Stores charts in SHA256 pool (deduplication works)
3. ✅ Creates snapshots of Helm repos
4. ✅ Publishes Helm repos that work with `helm` client
5. ✅ Views can combine multiple Helm repos
6. ✅ Filters work (name patterns, version constraints)
7. ✅ No changes needed to storage or CLI
8. ✅ All tests pass

## Future Enhancements

1. **OCI Registry Support**: Helm 3 supports OCI registries (ghcr.io, Docker Hub)
2. **Chart Provenance**: Support .prov files for chart signing
3. **Chart Dependencies**: Resolve and mirror chart dependencies
4. **Chart Linting**: Validate charts before publishing
5. **Chart Search**: Full-text search across chart descriptions/keywords

## References

- Helm Documentation: https://helm.sh/docs/
- Helm Repository Guide: https://helm.sh/docs/topics/chart_repository/
- Chart Repository API: https://helm.sh/docs/topics/chart_repository/#the-chart-repository-structure
- Helm index.yaml spec: https://helm.sh/docs/topics/chart_repository/#the-index-file
