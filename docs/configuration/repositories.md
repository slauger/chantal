# Repository Configuration

This page explains how to configure repositories in Chantal.

## Basic Repository Configuration

Minimum required configuration:

```yaml
repositories:
  - id: epel9-latest
    name: EPEL 9 - Latest
    type: rpm
    feed: https://dl.fedoraproject.org/pub/epel/9/Everything/x86_64/
    enabled: true
```

**Required Fields:**
- `id`: Unique identifier (alphanumeric, hyphens, underscores)
- `name`: Human-readable name
- `type`: Repository type (`rpm`, future: `apt`, `pypi`)
- `feed`: Upstream repository URL
- `enabled`: Whether to include in `--all` operations

## Repository Types

### RPM Repositories

For DNF/YUM-based distributions (RHEL, CentOS, Fedora, Rocky, Alma):

```yaml
repositories:
  - id: rhel9-baseos
    name: RHEL 9 BaseOS
    type: rpm
    feed: https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os
    enabled: true
```

**Feed URL Requirements:**
- Must point to a directory containing `repodata/repomd.xml`
- Supports HTTP and HTTPS
- Supports file:// URLs for local mirrors

### APT Repositories (Future)

For Debian/Ubuntu-based distributions:

```yaml
repositories:
  - id: ubuntu-jammy-main
    name: Ubuntu 22.04 - Main
    type: apt
    feed: http://archive.ubuntu.com/ubuntu/
    distribution: jammy
    components: [main, restricted, universe, multiverse]
    architectures: [amd64, arm64]
    enabled: true
```

**Note:** APT support is planned for v2.0.

### PyPI Repositories (Future)

For Python package mirroring:

```yaml
repositories:
  - id: pypi-mirror
    name: PyPI Mirror
    type: pypi
    feed: https://pypi.org/simple/
    enabled: true
```

**Note:** PyPI support is planned for v2.0.

## Advanced Options

### Version Retention Policy

Control which package versions to keep:

```yaml
repositories:
  - id: rhel9-baseos
    type: rpm
    feed: https://...
    retention:
      policy: mirror  # mirror, newest-only, keep-all, keep-last-n
      # keep_last_n: 3  # Only when policy is keep-last-n
```

**Retention Policies:**
- `mirror`: Mirror exactly what's upstream (default)
- `newest-only`: Keep only the latest version
- `keep-all`: Keep all versions ever seen
- `keep-last-n`: Keep last N versions

### Repository Tags

Tag repositories for easier management:

```yaml
repositories:
  - id: rhel9-baseos-production
    name: RHEL 9 BaseOS - Production
    type: rpm
    feed: https://...
    tags: ["production", "rhel9", "critical"]
```

Use tags to filter operations:

```bash
# Future feature
chantal repo sync --tag production
chantal repo list --tag rhel9
```

### Custom Publishing Paths

Override default publishing paths:

```yaml
repositories:
  - id: rhel9-baseos
    type: rpm
    feed: https://...
    latest_path: /var/www/repos/rhel9-baseos/latest
    snapshots_path: /var/www/repos/rhel9-baseos/snapshots
```

## Per-Repository Settings

### Proxy Override

Override global proxy settings:

```yaml
repositories:
  - id: internal-repo
    type: rpm
    feed: https://internal.example.com/repo
    proxy:
      http_proxy: http://internal-proxy:3128
      https_proxy: http://internal-proxy:3128
```

### SSL/TLS Override

Override global SSL settings:

```yaml
repositories:
  - id: rhel9-baseos
    type: rpm
    feed: https://cdn.redhat.com/...
    ssl:
      ca_bundle: /etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem
      client_cert: /etc/pki/entitlement/1234567890.pem
      client_key: /etc/pki/entitlement/1234567890-key.pem
      verify: true
```

### HTTP Headers

Add custom HTTP headers:

```yaml
repositories:
  - id: custom-repo
    type: rpm
    feed: https://custom.example.com/repo
    http_headers:
      User-Agent: "Chantal/1.0"
      X-Custom-Header: "value"
```

## Repository Organization

### Single File Configuration

Simple setup for few repositories:

```yaml
# config.yaml
database:
  url: sqlite:///.dev/chantal-dev.db

storage:
  base_path: ./.dev/dev-storage

repositories:
  - id: epel9-latest
    name: EPEL 9
    type: rpm
    feed: https://dl.fedoraproject.org/pub/epel/9/Everything/x86_64/
    enabled: true
```

### Multi-File Configuration

Recommended for many repositories:

**config.yaml:**
```yaml
database:
  url: postgresql://chantal:password@localhost/chantal

storage:
  base_path: /var/lib/chantal

include: "conf.d/*.yaml"
```

**conf.d/rhel9.yaml:**
```yaml
repositories:
  - id: rhel9-baseos
    name: RHEL 9 BaseOS
    type: rpm
    feed: https://cdn.redhat.com/...
    enabled: true

  - id: rhel9-appstream
    name: RHEL 9 AppStream
    type: rpm
    feed: https://cdn.redhat.com/...
    enabled: true
```

**conf.d/epel9.yaml:**
```yaml
repositories:
  - id: epel9-main
    name: EPEL 9 - Main
    type: rpm
    feed: https://dl.fedoraproject.org/pub/epel/9/Everything/x86_64/
    enabled: true
```

## Real-World Examples

### RHEL 9 with Subscription

```yaml
repositories:
  - id: rhel9-baseos
    name: RHEL 9 BaseOS
    type: rpm
    feed: https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os
    enabled: true
    ssl:
      ca_bundle: /etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem
      client_cert: /etc/pki/entitlement/1234567890.pem
      client_key: /etc/pki/entitlement/1234567890-key.pem
      verify: true
    filters:
      metadata:
        architectures:
          include: ["x86_64", "noarch"]
      rpm:
        exclude_source_rpms: true
```

### Rocky Linux 9

```yaml
repositories:
  - id: rocky9-baseos
    name: Rocky Linux 9 - BaseOS
    type: rpm
    feed: https://dl.rockylinux.org/pub/rocky/9/BaseOS/x86_64/os/
    enabled: true

  - id: rocky9-appstream
    name: Rocky Linux 9 - AppStream
    type: rpm
    feed: https://dl.rockylinux.org/pub/rocky/9/AppStream/x86_64/os/
    enabled: true
```

### EPEL 9 with Selective Mirroring

```yaml
repositories:
  - id: epel9-monitoring
    name: EPEL 9 - Monitoring Tools
    type: rpm
    feed: https://dl.fedoraproject.org/pub/epel/9/Everything/x86_64/
    enabled: true
    filters:
      patterns:
        include:
          - "^nagios-.*"
          - "^prometheus-.*"
          - "^grafana-.*"
      post_processing:
        only_latest_version: true
```

### CentOS Stream 9

```yaml
repositories:
  - id: centos-stream-9-baseos
    name: CentOS Stream 9 - BaseOS
    type: rpm
    feed: https://mirrors.centos.org/mirrorlist?repo=centos-baseos-9-stream&arch=x86_64
    enabled: true
    # Note: mirrorlist URLs are not yet supported, use direct mirror URL
```

## Validation

Chantal validates repository configuration at startup:

```bash
$ chantal repo list
Error: Configuration validation failed:
  - repositories[0].id: must match pattern ^[a-zA-Z0-9_-]+$
  - repositories[1].feed: invalid URL format
  - repositories[2].type: must be one of: rpm
```

## Best Practices

1. **Use descriptive IDs**: `rhel9-baseos` instead of `repo1`
2. **Organize by distribution**: Separate files for RHEL, EPEL, Rocky, etc.
3. **Document filters**: Add comments explaining why filters are applied
4. **Version control**: Keep repository configs in Git
5. **Test first**: Use `--dry-run` or test environment before production
6. **Enable selectively**: Set `enabled: false` for repos not in regular use
