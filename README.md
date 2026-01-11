# Chantal

**_Because every other name was already taken._** - A unified CLI tool for offline repository mirroring.

[![Documentation](https://img.shields.io/badge/docs-read%20the%20docs-blue)](https://slauger.github.io/chantal/)
[![Container](https://img.shields.io/badge/container-ghcr.io-blue)](https://github.com/slauger/chantal/pkgs/container/chantal)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## What is Chantal?

A Python-based CLI tool for offline repository mirroring, inspired by pulp-admin, reposync, and aptly.

**The Problem:** Enterprise environments need offline mirrors of RPM/APT repositories with version control, efficient storage, RHEL subscription support, and simple management. Existing tools either:
- Support only one repository type (`reposync` for RPM, `apt-mirror` for APT)
- Require complex infrastructure (Pulp needs Celery, RabbitMQ, Redis, PostgreSQL)
- Lack proper snapshot and deduplication features

**The Solution:** One simple CLI tool. No daemons, no message queues, no complex setup. Just sync repositories, create snapshots, and publish static files. Works with any webserver (Apache, NGINX) - because it's just files.

## Features

- 🔄 **Unified Mirroring** - Multiple repository types in one tool (RPM, Helm, Alpine APK, and more)
- 📦 **Deduplication** - Content-addressed storage (SHA256), packages stored once
- 📸 **Snapshots** - Immutable point-in-time repository states for patch management
- 🔍 **Views** - Virtual repositories combining multiple repos (e.g., BaseOS + AppStream + EPEL)
- 🔌 **Modular** - Plugin architecture for repository types
- 🚫 **No Daemons** - Simple CLI tool (optional scheduler for future automation)
- 📁 **Static Output** - Serve with any webserver (Apache, NGINX)
- 🔐 **RHEL CDN Support** - Client certificate authentication for Red Hat repos
- 🎯 **Smart Filtering** - Pattern-based package filtering with post-processing
- 🪞 **Mirror & Filtered Modes** - Full metadata mirroring or filtered repos with regenerated metadata
- ⚡ **Fast Updates** - Check for updates without downloading (like `dnf check-update`)

**Supported Repository Types:**
- ✅ **RPM/DNF/YUM** (RHEL, CentOS, Fedora, Rocky, AlmaLinux, EPEL) - Available
- ✅ **Helm Charts** (Kubernetes, Bitnami, AWS EKS, Prometheus, GitLab) - Available
- ✅ **Alpine APK** (Alpine Linux, container base images) - Available
- 🚧 **DEB/APT** (Debian, Ubuntu) - Planned
- 🚧 **PyPI**, **npm**, **Go Modules** - Planned

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

# 3. Sync repository (RPM, Helm, or APK)
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
**Plugins:** Extensible architecture for repository types (RPM, Helm, APK, APT, PyPI)

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

**🚀 Active Development - v0.1.0**

### Current Release: v0.1.0-dev

**✅ Multi-Ecosystem Support:**
- Content-addressed storage (SHA256 deduplication)
- **RPM** repository sync (RHEL, CentOS, Fedora, EPEL, Rocky, AlmaLinux)
  - Mirror mode: Full metadata mirroring (all repomd.xml types)
  - Filtered mode: Smart metadata regeneration (updateinfo, filelists, etc.)
  - Errata/advisory support (updateinfo.xml parsing and filtering)
- **Helm** chart repositories (Kubernetes, Bitnami, AWS EKS, Prometheus, GitLab)
- **Alpine APK** repositories (Alpine Linux, container images)
- Immutable snapshots (all repository types)
- Views (virtual repositories combining multiple repos)
- RHEL CDN support (client certificates)
- Pool management commands (verify, cleanup, orphaned, missing)
- 85+ tests passing

**🔄 Next Up:**
- APT/DEB repository support (Debian, Ubuntu)
- GitHub/GitLab release asset mirroring
- Git repository mirroring
- Web UI for repository management

**📋 Full Roadmap:** See [ROADMAP.md](ROADMAP.md) for detailed milestone plan and [GitHub Issues](https://github.com/slauger/chantal/issues)

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

Developed by [Simon Lauger](https://github.com/slauger)

Inspired by: pulp-admin, reposync, aptly, apt-mirror, bandersnatch

---

**📦 Container Images:** `ghcr.io/slauger/chantal:latest`

**📚 Documentation:** https://slauger.github.io/chantal/

**🐛 Issues:** https://github.com/slauger/chantal/issues
