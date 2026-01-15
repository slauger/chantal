# Helm Plugin

The Helm plugin provides support for Kubernetes Helm chart repositories.

## Overview

**Status:** ✅ Available

The Helm plugin consists of:
- **HelmSyncer** - Syncs Helm charts from upstream chart repositories
- **HelmPublisher** - Publishes Helm chart repositories with metadata

## Features

- ✅ index.yaml parsing
- ✅ Helm chart downloading (.tgz files)
- ✅ SHA256 checksum verification
- ✅ Pattern-based chart filtering
- ✅ Version filtering (only latest)
- ✅ Metadata generation (index.yaml)
- ✅ Chart deduplication via content-addressed storage
- ✅ Snapshot support
- ✅ **Mirror Mode** - Byte-for-byte identical repositories with snapshot versioning
- 🚧 Chart signing/verification - Planned
- 🚧 OCI registry support - Planned

## Repository Modes

The Helm plugin supports **mirror mode** for byte-for-byte identical repository copies.

### Mirror Mode (Default)

**Status:** ✅ Available

In mirror mode, Chantal stores the original `index.yaml` metadata file in the content-addressed pool as a `RepositoryFile`. When publishing, the original metadata is hardlinked from the pool to the published directory.

**Benefits:**
- Byte-for-byte identical to upstream repository
- Snapshot versioning of metadata (track index.yaml changes over time)
- Metadata deduplication across repositories and snapshots
- Historical tracking of metadata changes

**How it works:**

1. **Sync Process:**
   - Downloads index.yaml from upstream
   - Stores index.yaml in content-addressed pool by SHA256
   - Creates RepositoryFile database record
   - Links metadata to repository/snapshot

2. **Publish Process:**
   - Queries RepositoryFile for stored index.yaml
   - Hardlinks original index.yaml from pool to published directory
   - Creates hardlinks for all chart .tgz files
   - Result: Byte-for-byte identical copy of upstream

**Example:**

```yaml
repositories:
  - id: ingress-nginx
    name: Ingress NGINX Helm Charts
    type: helm
    feed: https://kubernetes.github.io/ingress-nginx
    enabled: true
    # Mirror mode is automatic - no additional config needed
```

**Use Cases:**
- Offline/air-gapped environments requiring exact upstream mirrors
- Compliance requirements for unmodified upstream metadata
- Snapshot versioning for reproducible deployments
- Bandwidth optimization (metadata reused across snapshots)

### Dynamic Generation Mode (Fallback)

If no `RepositoryFile` is found (e.g., for older repositories or filtered repositories), Chantal falls back to dynamic index.yaml generation from database metadata.

This mode:
- Generates index.yaml from HelmMetadata in database
- Allows filtered repositories (subset of charts)
- Supports post-processing (e.g., only latest versions)

**Note:** For filtered repositories (pattern-based chart selection), dynamic generation is used automatically.

## Configuration

### Basic Helm Repository

```yaml
repositories:
  - id: ingress-nginx
    name: Ingress NGINX Helm Charts
    type: helm
    feed: https://kubernetes.github.io/ingress-nginx
    enabled: true
```

### With Filters

```yaml
repositories:
  - id: bitnami-databases
    name: Bitnami Charts - Databases Only
    type: helm
    feed: https://charts.bitnami.com/bitnami
    enabled: true
    filters:
      patterns:
        include: ["^postgresql$", "^mysql$", "^mongodb$", "^redis$"]
      post_processing:
        only_latest_version: true
```

### With Authentication

Some Helm repositories require authentication:

```yaml
repositories:
  - id: private-charts
    name: Private Helm Charts
    type: helm
    feed: https://charts.example.com/
    enabled: true
    ssl:
      ca_bundle: /etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem
      client_cert: /etc/pki/helm/client.pem
      client_key: /etc/pki/helm/client-key.pem
      verify: true
```

## How It Works

### Sync Process

1. **Fetch index.yaml**
   ```
   GET https://charts.example.com/index.yaml
   ```
   Parse to find available charts and versions

2. **Parse chart metadata**
   - Chart name and version
   - Chart URL (may be relative or absolute)
   - Chart digest (SHA256)
   - Dependencies, maintainers, etc.

3. **Apply filters**
   - Pattern matching (include/exclude regex)
   - Version filtering (only latest)

4. **Download charts**
   - Download .tgz files to content-addressed pool
   - Verify SHA256 checksums
   - Deduplicate identical charts

5. **Store metadata**
   - Create ContentItem records
   - Store Helm metadata in database
   - Link charts to repository

### Publish Process

1. **Query database** for charts in repository/snapshot
2. **Create directory structure** for published repository
3. **Create hardlinks** from pool to published directory
4. **Generate index.yaml** with chart metadata and URLs
5. **Set correct file permissions** for web server access

## Chart Filtering

### Pattern Filters

Include specific charts by name:

```yaml
filters:
  patterns:
    include:
      - "^nginx-.*"       # All nginx-related charts
      - "^prometheus$"    # Exact match: prometheus chart
      - "^grafana-.*"     # All grafana-related charts
```

Exclude charts by pattern:

```yaml
filters:
  patterns:
    exclude:
      - ".*-alpha$"       # Exclude alpha versions
      - ".*-beta$"        # Exclude beta versions
      - "^deprecated-.*"  # Exclude deprecated charts
```

### Version Filtering

Keep only the latest version of each chart:

```yaml
filters:
  post_processing:
    only_latest_version: true
```

This is useful for:
- Reducing storage usage
- Simplifying chart selection for users
- Automatically staying current with upstream

## Common Use Cases

### Mirror Official Kubernetes Charts

```yaml
repositories:
  - id: kubernetes-charts
    name: Official Kubernetes Charts
    type: helm
    feed: https://kubernetes.github.io/ingress-nginx
    enabled: true
```

### Mirror Bitnami Charts (Selective)

```yaml
repositories:
  - id: bitnami-webservers
    name: Bitnami - Web Servers
    type: helm
    feed: https://charts.bitnami.com/bitnami
    enabled: true
    filters:
      patterns:
        include: ["^nginx$", "^apache$"]
      post_processing:
        only_latest_version: true
```

### Mirror Harbor Registry

```yaml
repositories:
  - id: harbor
    name: Harbor Helm Charts
    type: helm
    feed: https://helm.goharbor.io
    enabled: true
```

### Private Chart Repository

```yaml
repositories:
  - id: company-charts
    name: Company Internal Charts
    type: helm
    feed: https://charts.internal.company.com/
    enabled: true
    ssl:
      client_cert: /etc/pki/helm/company-client.pem
      client_key: /etc/pki/helm/company-client-key.pem
      verify: true
```

## Publishing Helm Repositories

### Publish Latest Repository

```bash
chantal publish repo --repo-id ingress-nginx
```

Published structure:
```
/var/www/repos/ingress-nginx/latest/
├── index.yaml
├── ingress-nginx-4.0.15.tgz
├── ingress-nginx-4.0.14.tgz
└── ...
```

### Publish Snapshot

```bash
chantal snapshot create --repo-id ingress-nginx --name 2025-01-10
chantal publish snapshot --snapshot ingress-nginx-2025-01-10
```

Published structure:
```
/var/www/repos/ingress-nginx/snapshots/2025-01-10/
├── index.yaml
└── ingress-nginx-4.0.15.tgz
```

### Configure Helm Client

Point Helm CLI to your mirrored repository:

```bash
# Add repository
helm repo add ingress-nginx http://mirror.example.com/repos/ingress-nginx/latest/

# Update repository index
helm repo update

# Install chart
helm install my-ingress ingress-nginx/ingress-nginx
```

### Configure Helm with Snapshot

Use a specific snapshot for reproducible deployments:

```bash
# Add snapshot repository
helm repo add ingress-nginx-2025-01-10 \
  http://mirror.example.com/repos/ingress-nginx/snapshots/2025-01-10/

# Install from snapshot
helm install my-ingress ingress-nginx-2025-01-10/ingress-nginx
```

## Chart Metadata

Chantal stores comprehensive metadata for each chart:

- **name** - Chart name
- **version** - Chart version (SemVer)
- **description** - Chart description
- **home** - Project home page URL
- **sources** - Source code URLs
- **keywords** - Chart keywords
- **maintainers** - Maintainer information
- **icon** - Chart icon URL
- **appVersion** - Application version
- **deprecated** - Deprecation status
- **annotations** - Chart annotations
- **dependencies** - Chart dependencies
- **type** - Chart type (application/library)
- **apiVersion** - Helm API version

This metadata is:
- Stored in the database for querying
- Included in published index.yaml
- Available via Chantal CLI commands

## Troubleshooting

### Charts Not Syncing

Check index.yaml is accessible:
```bash
curl -I https://charts.example.com/index.yaml
```

Verify repository configuration:
```bash
chantal repo show --repo-id my-helm-repo
```

Check sync logs for errors:
```bash
chantal repo sync --repo-id my-helm-repo
```

### Publishing Issues

Verify charts were synced:
```bash
chantal package list --repo-id my-helm-repo
```

Check published directory permissions:
```bash
ls -la /var/www/repos/my-helm-repo/latest/
```

Verify index.yaml was generated:
```bash
cat /var/www/repos/my-helm-repo/latest/index.yaml
```

### Client Certificate Issues

Verify certificate files exist and are readable:
```bash
ls -la /etc/pki/helm/client.pem
ls -la /etc/pki/helm/client-key.pem
```

Test with curl:
```bash
curl --cert /etc/pki/helm/client.pem \
     --key /etc/pki/helm/client-key.pem \
     https://charts.example.com/index.yaml
```

## Best Practices

1. **Use snapshots for production** - Create dated snapshots for reproducible deployments
2. **Filter by patterns** - Only mirror charts you need to reduce storage
3. **Keep latest only** - Use `only_latest_version: true` unless you need version history
4. **Regular syncing** - Schedule regular syncs to stay current
5. **Verify checksums** - Chantal automatically verifies SHA256 checksums
6. **Document your mirrors** - Keep notes on why specific charts are mirrored
7. **Test before production** - Test snapshots in staging before promoting to production

## Integration with CI/CD

### GitOps Workflow

```yaml
# ArgoCD Application
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
spec:
  source:
    repoURL: http://mirror.example.com/repos/ingress-nginx/snapshots/2025-01-10/
    chart: ingress-nginx
    targetRevision: 4.0.15
```

### Jenkins Pipeline

```groovy
pipeline {
    stages {
        stage('Sync Helm Charts') {
            steps {
                sh 'chantal repo sync --repo-id ingress-nginx'
            }
        }
        stage('Create Snapshot') {
            steps {
                sh 'chantal snapshot create --repo-id ingress-nginx --name ${BUILD_ID}'
            }
        }
        stage('Publish Snapshot') {
            steps {
                sh 'chantal publish snapshot --snapshot ingress-nginx-${BUILD_ID}'
            }
        }
    }
}
```

## Further Reading

- [Plugins Overview](overview.md) - Plugin architecture
- [Custom Plugins](custom-plugins.md) - Creating custom plugins
- [Repository Configuration](../configuration/repositories.md) - Repository settings
- [CLI Commands](../user-guide/cli-commands.md) - Command reference
