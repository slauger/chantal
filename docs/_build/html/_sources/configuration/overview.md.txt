# Configuration Overview

Chantal uses YAML-based configuration files for managing repositories and settings.

## Configuration File Structure

The main configuration file contains global settings and can include additional repository and view definitions:

```yaml
# Global database configuration
database:
  url: postgresql://chantal:password@localhost/chantal
  # or for development/testing: sqlite:///chantal.db

# Storage paths
storage:
  base_path: /var/lib/chantal
  pool_path: /var/lib/chantal/pool
  published_path: /var/www/repos

# Global HTTP proxy (optional)
proxy:
  http_proxy: http://proxy.example.com:8080
  https_proxy: http://proxy.example.com:8080
  no_proxy: localhost,127.0.0.1,.internal.domain
  username: proxyuser  # optional
  password: proxypass  # optional

# Global SSL/TLS settings (optional)
ssl:
  ca_bundle: /etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem
  verify: true

# Include repository and view configs
include: /etc/chantal/conf.d/*.yaml
```

## Configuration File Priority

Chantal searches for configuration files in this order (first found wins):

1. **`--config` CLI flag** (highest priority)
   ```bash
   chantal --config /path/to/config.yaml repo list
   ```

2. **`CHANTAL_CONFIG` environment variable**
   ```bash
   export CHANTAL_CONFIG=/path/to/config.yaml
   chantal repo list
   ```

3. **Default locations** (searched in order):
   - `/etc/chantal/config.yaml` (production)
   - `~/.config/chantal/config.yaml` (user)
   - `./config.yaml` (current directory)

## Development vs. Production

### Production Setup

Standard production configuration:

`/etc/chantal/config.yaml`:
```yaml
database:
  url: postgresql://chantal:password@localhost/chantal

storage:
  base_path: /var/lib/chantal
  pool_path: /var/lib/chantal/pool
  published_path: /var/www/repos

include: /etc/chantal/conf.d/*.yaml
```

**Directory structure:**
```
/etc/chantal/
├── config.yaml
└── conf.d/
    ├── rhel9.yaml
    ├── epel9.yaml
    ├── centos9.yaml
    └── views.yaml
```

### Development Setup

For local development and testing:

```bash
export CHANTAL_CONFIG=config-dev.yaml
```

`config-dev.yaml`:
```yaml
database:
  url: sqlite:///chantal-dev.db

storage:
  base_path: ./storage
  pool_path: ./storage/pool
  published_path: ./storage/published

include: conf.d/*.yaml
```

## Database Configuration

### SQLite (Development/Testing)

Best for development, testing, and small deployments:

```yaml
database:
  url: sqlite:///chantal.db
  # or absolute path:
  # url: sqlite:////var/lib/chantal/chantal.db
```

**Pros:**
- No external service required
- Easy setup
- Good for testing

**Cons:**
- Not suitable for large-scale deployments
- No concurrent write support

### PostgreSQL (Production)

Recommended for production:

```yaml
database:
  url: postgresql://chantal:password@localhost/chantal
  # or with connection options:
  # url: postgresql://chantal:password@localhost:5432/chantal?sslmode=require
```

**Pros:**
- Better performance for large datasets
- Concurrent access support
- Better for high-volume syncs

**Cons:**
- Requires PostgreSQL installation
- More complex setup

## Storage Configuration

### Storage Paths

```yaml
storage:
  base_path: /var/lib/chantal       # Base directory
  pool_path: /var/lib/chantal/pool  # Content-addressed storage
  published_path: /var/www/repos    # Published repositories
```

**Pool Path:**
- Content-addressed storage (SHA256-based)
- Deduplication happens here
- Packages stored once, referenced many times

**Published Path:**
- Hardlinks to pool
- Organized by repository/snapshot
- Served by web server (Apache, NGINX)

### Directory Permissions

For production:

```bash
sudo mkdir -p /var/lib/chantal/{pool,published}
sudo chown -R chantal:chantal /var/lib/chantal
sudo chmod 755 /var/lib/chantal
sudo chmod 755 /var/lib/chantal/{pool,published}
```

## Proxy Configuration

### Global Proxy

Applied to all repositories unless overridden:

```yaml
proxy:
  http_proxy: http://proxy.example.com:8080
  https_proxy: http://proxy.example.com:8080
  no_proxy: localhost,127.0.0.1,.internal.domain
  username: proxyuser  # optional
  password: proxypass  # optional
```

### Per-Repository Proxy Override

```yaml
repositories:
  - id: external-repo
    name: External Repository
    type: rpm
    feed: https://external.example.com/repo
    proxy:
      http_proxy: http://different-proxy.example.com:3128
```

### No Proxy for Specific Repository

```yaml
repositories:
  - id: internal-repo
    name: Internal Repository
    type: rpm
    feed: https://internal.example.com/repo
    proxy:
      http_proxy: null  # Disable proxy for this repo
```

## SSL/TLS Configuration

### Global SSL Settings

```yaml
ssl:
  ca_bundle: /etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem
  verify: true
```

### Per-Repository SSL (e.g., RHEL CDN)

```yaml
repositories:
  - id: rhel9-baseos
    name: RHEL 9 BaseOS
    type: rpm
    feed: https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os
    ssl:
      ca_bundle: /etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem
      client_cert: /etc/pki/entitlement/1234567890.pem
      client_key: /etc/pki/entitlement/1234567890-key.pem
      verify: true
```

## Including Additional Configuration Files

Use `include` to split configuration across multiple files:

```yaml
# Main /etc/chantal/config.yaml
database:
  url: postgresql://chantal:password@localhost/chantal

storage:
  base_path: /var/lib/chantal

# Include all YAML files in conf.d/
include: /etc/chantal/conf.d/*.yaml
```

**Directory structure:**
```
/etc/chantal/
├── config.yaml
└── conf.d/
    ├── rhel9.yaml          # RHEL repositories
    ├── epel9.yaml          # EPEL repositories
    ├── centos9.yaml        # CentOS repositories
    └── views.yaml          # Views (virtual repositories)
```

**Example repository file** (`/etc/chantal/conf.d/rhel9.yaml`):
```yaml
repositories:
  - id: rhel9-baseos
    name: RHEL 9 BaseOS
    type: rpm
    feed: https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os
    enabled: true
```

**Example views file** (`/etc/chantal/conf.d/views.yaml`):
```yaml
views:
  - name: rhel9-complete
    description: "RHEL 9 - All channels combined"
    repos:
      - rhel9-baseos
      - rhel9-appstream
      - rhel9-crb
```

## Configuration Validation

Chantal validates configuration at startup:

```bash
$ chantal repo list
Error: Configuration validation failed:
  - repositories[0].id: field required
  - repositories[1].feed: invalid URL format
  - database.url: field required
```

## Environment Variables

Chantal supports environment variable interpolation:

```yaml
database:
  url: ${DATABASE_URL:-sqlite:///chantal.db}

storage:
  base_path: ${CHANTAL_STORAGE_PATH:-/var/lib/chantal}
```

**Note:** This feature may be added in a future version.

## Best Practices

1. **Separate concerns:** Use `conf.d/` for repository definitions
2. **Version control:** Keep configuration in Git (except secrets)
3. **Secrets management:** Use environment variables or secret managers for passwords
4. **Production vs. Development:** Use different config files
5. **Documentation:** Add comments to explain non-obvious settings
