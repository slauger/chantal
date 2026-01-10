# Chantal

**_Because every other name was already taken._** - A unified CLI tool for offline repository mirroring.

[![Documentation](https://img.shields.io/badge/docs-read%20the%20docs-blue)](https://slauger.github.io/chantal/)
[![Container](https://img.shields.io/badge/container-ghcr.io-blue)](https://github.com/slauger/chantal/pkgs/container/chantal)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## What is Chantal?

Chantal is a Python-based CLI tool for offline repository mirroring with:
- **Content-addressed storage** (SHA256) - packages stored once, shared across repositories
- **Immutable snapshots** - point-in-time freezes for patch management and rollback
- **Virtual repositories (Views)** - combine multiple repos (e.g., BaseOS + AppStream + EPEL)
- **RHEL CDN support** - client certificate authentication for Red Hat subscriptions
- **Smart filtering** - pattern-based package selection with post-processing
- **Zero-copy publishing** - hardlinks instead of file copies

**Supported Repository Types:**
- ✅ **RPM/DNF/YUM** (RHEL, CentOS, Fedora, Rocky, AlmaLinux, EPEL) - Available
- 🚧 **DEB/APT** (Debian, Ubuntu) - Planned
- 🚧 **PyPI**, **Alpine APK**, **Helm**, **npm**, **Go Modules** - Planned

---

## Quick Start

### Installation

**Option 1: Container (Recommended)**

```bash
# Pull from GitHub Container Registry
docker pull ghcr.io/slauger/chantal:latest

# Run
docker run --rm \
  -v $(pwd)/config:/etc/chantal:ro \
  -v $(pwd)/data:/var/lib/chantal \
  -v $(pwd)/repos:/var/www/repos \
  ghcr.io/slauger/chantal:latest --help
```

**Option 2: Python Package**

```bash
git clone https://github.com/slauger/chantal.git
cd chantal
pip install -e .
```

**Requirements:** Python 3.10+, PostgreSQL or SQLite

### Basic Usage

```bash
# 1. Initialize
chantal init

# 2. Configure repositories (see docs for examples)
vim /etc/chantal/config.yaml

# 3. Sync repository
chantal repo sync --repo-id epel9-latest

# 4. Create snapshot
chantal snapshot create --repo-id epel9-latest --name 2025-01

# 5. Publish
chantal publish snapshot --snapshot epel9-latest-2025-01
```

**Result:** Published repository in `/var/www/repos/` ready to serve with Apache/NGINX.

---

## Key Features

### Content-Addressed Storage
- SHA256-based deduplication (2-level directory: `ab/cd/sha256_file.rpm`)
- Packages stored once, shared across all repositories
- Typical deduplication: 60-80% across RHEL variants

### Immutable Snapshots
- Point-in-time freezes for patch management
- Compare snapshots (`chantal snapshot diff`)
- Rollback to previous states
- Atomic view snapshots (freeze all repos simultaneously)

### Virtual Repositories (Views)
- Combine multiple repos into one: `BaseOS + AppStream + CRB`
- Mixed repos: `RHEL + EPEL` in single repository
- Stack-specific views: web server, monitoring, etc.

### Smart Filtering
```yaml
filters:
  patterns:
    include: ["^nginx-.*", "^httpd-.*"]
    exclude: [".*-debug.*"]
  metadata:
    architectures:
      include: ["x86_64", "noarch"]
  post_processing:
    only_latest_version: true
```

### Zero-Copy Publishing
- Hardlinks (not copies) to published directories
- Instant publishing (milliseconds for thousands of packages)
- Atomic metadata updates

---

## Architecture

```
/var/lib/chantal/pool/          # Content-addressed storage (SHA256)
├── ab/cd/sha256_package.rpm
└── ...

/var/www/repos/                  # Published repositories (hardlinks)
├── rhel9-baseos/
│   ├── latest/                  # Current state
│   └── snapshots/2025-01/       # Immutable snapshot
└── views/
    └── rhel9-complete/          # Virtual repository
        └── latest/
```

**Database:** PostgreSQL or SQLite (SQLAlchemy models)
**Plugins:** Extensible architecture for repository types (RPM, DEB, PyPI, etc.)

---

## Documentation

📚 **Full Documentation:** https://slauger.github.io/chantal/

- [Installation Guide](https://slauger.github.io/chantal/user-guide/installation.html)
- [Quick Start](https://slauger.github.io/chantal/user-guide/quickstart.html)
- [CLI Commands](https://slauger.github.io/chantal/user-guide/cli-commands.html)
- [Configuration](https://slauger.github.io/chantal/configuration/overview.html)
- [Views (Virtual Repositories)](https://slauger.github.io/chantal/user-guide/views.html)
- [Architecture](https://slauger.github.io/chantal/architecture/overview.html)
- [Plugin Development](https://slauger.github.io/chantal/plugins/custom-plugins.html)

---

## Common Workflows

### Patch Management
```bash
# Monthly cycle
chantal repo sync --all
chantal snapshot create --repo-id rhel9-baseos --name 2025-02
chantal snapshot diff --repo-id rhel9-baseos 2025-01 2025-02
chantal publish snapshot --snapshot rhel9-baseos-2025-02
```

### RHEL Subscription
```yaml
repositories:
  - id: rhel9-baseos
    feed: https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os
    ssl:
      client_cert: /etc/pki/entitlement/1234567890.pem
      client_key: /etc/pki/entitlement/1234567890-key.pem
```

### Air-Gapped Environments
```bash
# Online system
chantal repo sync --all
tar czf export.tar.gz /var/lib/chantal /etc/chantal

# Offline system
tar xzf export.tar.gz
chantal publish repo --all
```

See [Workflows Documentation](https://slauger.github.io/chantal/user-guide/workflows.html) for more examples.

---

## Status

**🚀 Active Development - MVP Phase**

### ✅ Completed
- Content-Addressed Storage (SHA256-based pool)
- RPM Sync Plugin (repomd.xml, primary.xml.gz)
- RPM Publisher (metadata generation)
- Snapshots (immutable point-in-time states)
- Views (virtual repositories)
- Filtering (patterns, architectures, post-processing)
- Update checking (`chantal repo check-updates`)
- RHEL CDN support (client certificates)
- 74 tests passing

### 🚧 In Progress
- Statistics & Database Management (Milestone 6)

### 📋 Planned
- DEB/APT support
- PyPI, Alpine APK, Helm support
- Automated scheduling (cron integration)
- Web UI (read-only)
- REST API
- Prometheus metrics

**See:** [GitHub Issues](https://github.com/slauger/chantal/issues) for detailed roadmap.

---

## Contributing

Contributions welcome! This is active development.

1. Check [GitHub Issues](https://github.com/slauger/chantal/issues)
2. Read the [Architecture Documentation](https://slauger.github.io/chantal/architecture/overview.html)
3. Submit pull requests

**Development:**
```bash
# Run tests
pytest

# Format code
black src/ tests/

# Type checking
mypy src/
```

---

## License

MIT License - See [LICENSE](LICENSE) file for details.

---

## Credits

Developed by [Sebastian Lauger](https://github.com/slauger)

Inspired by: pulp-admin, reposync, aptly, apt-mirror, bandersnatch

---

**📦 Container Images:** `ghcr.io/slauger/chantal:latest`
**📚 Documentation:** https://slauger.github.io/chantal/
**🐛 Issues:** https://github.com/slauger/chantal/issues
