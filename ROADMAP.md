# Chantal Development Roadmap

**Last Updated:** 2026-06-25
**Current Version:** 1.4.0 (released, available on [PyPI](https://pypi.org/project/chantal/))

---

## Current Status

**✅ Multi-format mirroring with signing parity across all plugins.**

- **341 tests passing**; `black`, `ruff`, `mypy` (strict) and `yamllint --strict` clean
- Python **3.12 / 3.13 / 3.14** (3.10/3.11 dropped)
- Formats: **RPM**, **APT/DEB**, **Helm**, **Alpine APK**
- Modes: **mirror**, **filtered**, **hosted** (per plugin)
- Content-addressed storage (SHA256) with deduplication and zero-copy (hardlink) publishing
- Snapshots and views (virtual repositories)
- **Metadata signing in filtered mode for every format:**
  - APT — GPG `InRelease` + `Release.gpg`
  - RPM — GPG `repomd.xml.asc`
  - APK — RSA-signed `APKINDEX.tar.gz`
- Configurable metadata compression (gzip / zstandard / bzip2 / xz where applicable)
- JSON Schema for `config.yaml` (editor validation/autocomplete) + example validation in CI
- Central download manager (auth, SSL/TLS, proxy, retries, checksum verification)
- RHEL CDN authentication (client certificates)

---

## Completed Milestones

| # | Milestone | Issue(s) |
|---|-----------|----------|
| 1 | Foundation & Configuration | [#15](https://github.com/slauger/chantal/issues/15) |
| 2 | Content-Addressed Storage | [#15](https://github.com/slauger/chantal/issues/15) |
| 3 | RPM Plugin & Sync | – |
| 4 | Snapshots | – |
| 5 | Views & Advanced Publishing | – |
| 6 | Database Management (`chantal db`) | [#14](https://github.com/slauger/chantal/issues/14) |
| 7 | Helm Chart Support | [#2](https://github.com/slauger/chantal/issues/2) |
| 8 | Alpine APK Support | [#4](https://github.com/slauger/chantal/issues/4) |
| 9 | Metadata & Mirror Mode | [#18](https://github.com/slauger/chantal/issues/18) |
| 10 | Plugin Structure Refactoring | [#24](https://github.com/slauger/chantal/issues/24) |
| 11 | Central Download Manager | [#25](https://github.com/slauger/chantal/issues/25) |
| 12 | Code Quality & Type Safety | [#22](https://github.com/slauger/chantal/issues/22) |
| 13 | CLI Modularization | – |
| 14 | APK Mirror Mode | [#26](https://github.com/slauger/chantal/issues/26) |
| 15 | Helm Mirror Mode | [#27](https://github.com/slauger/chantal/issues/27) |
| 16 | Example Configurations | [#3](https://github.com/slauger/chantal/issues/3) |
| 17 | APT/DEB Support (incl. Phase 2) | [#1](https://github.com/slauger/chantal/issues/1), [#29](https://github.com/slauger/chantal/issues/29) |
| 18 | Metadata Caching (RPM) | [#17](https://github.com/slauger/chantal/issues/17) |
| 19 | Zstandard Compression | [#23](https://github.com/slauger/chantal/issues/23) |
| 20 | Errata/Advisory Integration (updateinfo) | [#12](https://github.com/slauger/chantal/issues/12), [#13](https://github.com/slauger/chantal/issues/13) |
| 21 | Helm OCI Registry Support | [#34](https://github.com/slauger/chantal/issues/34) |
| 22 | SUSE/SLES Metadata Research | [#11](https://github.com/slauger/chantal/issues/11) |

### Signing & Modernization

- **APT GPG signing** for filtered mode (InRelease, Release.gpg) — [#30](https://github.com/slauger/chantal/issues/30)
- **RPM GPG signing** of regenerated `repomd.xml` (repomd.xml.asc)
- **APK RSA signing** of regenerated `APKINDEX.tar.gz` + published public key
- **Configurable APT `Packages` compression** (gzip/zstandard/bzip2/none)
- **Config JSON Schema** (`chantal schema`) + example-config validation in CI
- **Resolved all deprecation warnings** (Pydantic `ConfigDict`, `datetime.UTC`, alembic)
- **Dropped Python 3.10/3.11, added 3.14**; modernized to `datetime.UTC` / `StrEnum`
- **Bumped GitHub Actions** to Node 24 majors

### Release Engineering & 1.0+ (shipped)

- **Custom package injection / hosted upload** (`chantal package upload`) — [#16](https://github.com/slauger/chantal/issues/16):
  upload local RPM/DEB/Helm packages into the pool and publish them (hosted mode),
  independent of an upstream feed.
- **1.0.0 release** — [#32](https://github.com/slauger/chantal/issues/32): hosted mode,
  end-to-end smoke tests per plugin, documentation, production-grade stability.
- **Release automation**: semantic-release with conventional commits, automatic
  versioning, **PyPI publishing** (`pip install chantal`), TestPyPI prereleases,
  and container images on GHCR.

---

## In Progress / Next

### 📋 Advanced Errata & Advisory Management — [#21](https://github.com/slauger/chantal/issues/21)

Dedicated advisory models, enhanced CVE tracking, external errata sources
(AlmaLinux CEFS, Rocky RLSA, Oracle ELSA), errata-based snapshot diff.

---

## Future Milestones

### New plugin types
- **GitHub/GitLab Release Asset mirroring** — [#19](https://github.com/slauger/chantal/issues/19)
- **Git repository mirroring (tarball approach)** — [#20](https://github.com/slauger/chantal/issues/20)

### Additional package formats
- **PyPI** — [#5](https://github.com/slauger/chantal/issues/5)
- **npm/yarn** — [#7](https://github.com/slauger/chantal/issues/7)
- **RubyGems** — [#6](https://github.com/slauger/chantal/issues/6)
- **NuGet** — [#8](https://github.com/slauger/chantal/issues/8)
- **Go Modules** — [#9](https://github.com/slauger/chantal/issues/9)
- **Terraform Providers** — [#10](https://github.com/slauger/chantal/issues/10)

### Signing follow-ups (no issue yet)
- Sign individual `.apk` packages (not just the index)
- Verify upstream package signatures during sync (RPM/APK)

---

## Long-Term Vision (v2.0+)

**Advanced:** REST API, read-only web UI, Prometheus metrics, scheduling (cron),
webhook notifications, multi-tenancy.

**Performance & scale:** parallel sync optimization, DB query optimization,
100k+ package repositories, bandwidth limiting, resume for interrupted syncs.

**Enterprise:** RBAC, audit logging, policy enforcement, air-gapped sync
(export/import), high availability.

---

## Release Timeline

**v0.1.0** (released 2026-01-12)
- RPM, Helm, Alpine APK support; mirror/filtered modes; snapshots; views

**v1.0.0**
- APT/DEB support (mirror + filtered)
- Metadata signing for all formats (APT/RPM GPG, APK RSA)
- Config JSON Schema; configurable APT compression
- Python 3.12–3.14; deprecation-free; modernized tooling
- End-to-end tests across all plugins; production-grade stability
- Release automation (semantic-release, PyPI, container images)

**v1.4.0** (current, on PyPI)
- Custom package injection / hosted upload (`chantal package upload`) for RPM/APT/Helm
- Hosted mode across plugins; continued stability and documentation improvements

---

## How to Contribute

1. Check this roadmap and the [GitHub Issues](https://github.com/slauger/chantal/issues)
2. Comment on issues you're interested in
3. Submit pull requests

See [GitHub Issues](https://github.com/slauger/chantal/issues) or open a new issue.
