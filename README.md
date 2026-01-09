# Chantal

**_Because every other name was already taken._** - A unified CLI tool for offline repository mirroring.

---

## Features

- 🔄 **Unified Mirroring** - APT and RPM repositories in one tool
- 📦 **Deduplication** - Content-addressed storage, packages stored once
- 📸 **Snapshots** - Freeze repo states for patch management
- 🔌 **Modular** - Plugin architecture for repo types
- 🚫 **No Daemons** - Simple CLI tool, not a service
- 📁 **Static Output** - Serve with any webserver (Apache, NGINX, S3)

---

## What is Chantal?

A unified CLI tool for offline repository mirroring across APT and RPM ecosystems.

**The Problem:** Running Debian and RHEL systems requires different tools (apt-mirror, aptly, reposync), different configs, different workflows.

**The Solution:** One tool. One config. One workflow.

```bash
chantal sync --all
```

## Quick Example

```yaml
# chantal.yaml
repos:
  - name: debian-bookworm
    type: apt
    upstream: http://deb.debian.org/debian
    releases: [bookworm]
    architectures: [amd64, arm64]

  - name: rhel9-baseos
    type: rpm
    upstream: https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os
    architectures: [x86_64]
```

```bash
chantal sync debian-bookworm
chantal snapshot create 2025-01
```

## Status

**⚠️ Early Development - Research Phase**

Currently analyzing existing tools (apt-mirror, aptly, reposync) to design a better solution.

Not ready for production. See [TODO.md](TODO.md) for roadmap.

## Why "Chantal"?

Every other name was taken. Seriously.

We checked: berth (Docker tool), conduit (5+ tools), tributary (d3.js), harbor (CNCF), stow (GNU), fulcrum, vesper, cairn, aperture - all taken.

So we picked something memorable, available, and with personality.

## Documentation

- **[CONTEXT.md](CONTEXT.md)** - Full project specification and requirements
- **[TODO.md](TODO.md)** - Detailed roadmap and task breakdown
- **[CONTRIBUTING.md](CONTRIBUTING.md)** - How to contribute (feedback welcome!)

## License

TBD - Will be decided before first code commit.

---

**Current Phase:** Research & Tool Analysis
**Next Milestone:** Architecture Proposal
