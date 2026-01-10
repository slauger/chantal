# Chantal - Repository Configuration Examples

This directory contains production-ready example configurations for popular Linux distributions and third-party software repositories.

## Directory Structure

```
examples/
├── README.md                          # This file
└── rpm/                               # RPM-based repository examples
    ├── distributions/                 # Official distribution repositories
    │   ├── rhel8.yaml                # Red Hat Enterprise Linux 8
    │   └── rhel9.yaml                # Red Hat Enterprise Linux 9
    └── third-party/                   # Third-party software repositories
        ├── docker-ce.yaml            # Docker CE (Community Edition)
        ├── epel.yaml                 # Extra Packages for Enterprise Linux
        ├── gitlab.yaml               # GitLab CE/EE
        ├── gitlab-runner.yaml        # GitLab CI/CD Runner
        ├── grafana.yaml              # Grafana Observability Platform
        ├── hashicorp.yaml            # HashiCorp Tools (Terraform, Vault, Consul)
        ├── icinga.yaml               # Icinga Monitoring Platform
        ├── postgresql.yaml           # PostgreSQL Database
        └── zabbix.yaml               # Zabbix Monitoring Platform
```

## How to Use These Examples

### 1. Copy Example Configuration

Copy the example file(s) you need to your Chantal configuration directory:

```bash
# Create configuration directory if it doesn't exist
mkdir -p ~/.config/chantal/conf.d/

# Copy RHEL 9 example
cp examples/rpm/distributions/rhel9.yaml ~/.config/chantal/conf.d/

# Copy Docker CE example
cp examples/rpm/third-party/docker-ce.yaml ~/.config/chantal/conf.d/

# Copy EPEL example
cp examples/rpm/third-party/epel.yaml ~/.config/chantal/conf.d/
```

### 2. Customize Configuration

Edit the copied files to match your environment:

```bash
# Edit RHEL configuration
vim ~/.config/chantal/conf.d/rhel9.yaml
```

**Important customizations:**

- **RHEL repositories**: Replace `YOUR_CERT_ID` with your actual Red Hat entitlement certificate ID
- **Filters**: Enable or disable package filters based on your needs
- **Repository IDs**: Adjust if needed to match your naming conventions
- **Enabled flag**: Set `enabled: true` for repositories you want to sync

### 3. Verify Configuration

Check that Chantal can parse your configuration:

```bash
# List configured repositories
chantal repo list

# Show details for specific repository
chantal repo list --repo-id rhel9-baseos
```

### 4. Start Syncing

Sync repositories to your local mirror:

```bash
# Sync single repository
chantal repo sync --repo-id epel9

# Sync all RHEL repositories
chantal repo sync --pattern "rhel9-*"

# Sync all enabled repositories
chantal repo sync --all
```

## Example Configurations Overview

### Official Distributions

#### RHEL 9 (rhel9.yaml)
Red Hat Enterprise Linux 9 repository configuration with:
- BaseOS (core operating system)
- AppStream (applications and runtimes)
- CodeReady Builder (development tools)
- High Availability, Resilient Storage, Real Time, NFV, SAP (optional add-ons)

**Requirements**: Active RHEL subscription, entitlement certificates

#### RHEL 8 (rhel8.yaml)
Similar to RHEL 9, for RHEL 8 systems (Extended Life Phase until 2029)

### Third-Party Repositories

#### EPEL (epel.yaml)
Extra Packages for Enterprise Linux - Essential third-party repository
- 50,000+ packages not in RHEL
- Community-supported by Fedora Project
- Safe to use alongside RHEL repositories
- Size: ~30-50 GB per major version

**Popular packages**: htop, tmux, ansible, fail2ban, certbot, nginx

#### Docker CE (docker-ce.yaml)
Official Docker Community Edition repository
- Docker Engine, CLI, containerd
- Docker Compose V2 plugin
- Docker Buildx plugin
- Separate repositories for RHEL 8 and 9

#### GitLab (gitlab.yaml)
GitLab Community Edition and Enterprise Edition
- Complete DevOps platform
- Monthly releases (~1 GB per version)
- Version pinning strategies included

#### GitLab Runner (gitlab-runner.yaml)
CI/CD runner for GitLab
- Multiple executor types (Docker, Shell, Kubernetes)
- Should match GitLab server version
- Lightweight (~50-100 MB)

#### Grafana (grafana.yaml)
Open-source observability and monitoring platform
- Dashboards, alerts, data exploration
- Supports Prometheus, InfluxDB, Elasticsearch, and more
- Plugin system for extensibility

#### HashiCorp (hashicorp.yaml)
Infrastructure automation tools
- Terraform (Infrastructure as Code)
- Vault (Secrets Management)
- Consul (Service Mesh)
- Nomad, Packer, Vagrant (optional)

#### Icinga (icinga.yaml)
Scalable monitoring platform
- Icinga 2 core, IcingaDB, Icinga Web 2
- Alternative to Nagios
- Extensible with plugins

#### PostgreSQL (postgresql.yaml)
Official PostgreSQL repository
- Latest PostgreSQL versions (15, 16)
- Extensions: PostGIS, pgAudit, TimescaleDB, pgvector
- pgAdmin, pgBouncer, pgPool-II

#### Zabbix (zabbix.yaml)
Enterprise monitoring platform
- LTS versions (6.0, 7.0) supported for 5 years
- Agent 2 with plugin support
- Database backend: MySQL/PostgreSQL/TimescaleDB

## Configuration Best Practices

### 1. Use Filters to Reduce Mirror Size

Most example configurations include commented filter examples:

```yaml
filters:
  patterns:
    include:
      - "^nginx-.*"         # Only mirror nginx packages
      - "^httpd-.*"         # Only mirror Apache packages
    exclude:
      - ".*-debuginfo$"     # Skip debug packages
      - ".*-devel$"         # Skip development headers
  metadata:
    architectures:
      include: ["x86_64", "noarch"]
  rpm:
    exclude_source_rpms: true  # Skip .src.rpm files
  post_processing:
    only_latest_version: true  # Keep only latest version
```

### 2. Create Snapshots for Version Control

Use snapshots to freeze repository state at specific points in time:

```bash
# Create monthly snapshot
chantal snapshot create --repo-id epel9 --name epel9-2025-01

# Create snapshot after testing
chantal snapshot create --repo-id docker-ce-rhel9 --name docker-ce-tested-2025-01

# Publish specific snapshot
chantal publish snapshot --repo-id epel9 --snapshot epel9-2025-01
```

### 3. Use Views to Combine Repositories

Create views to combine multiple repositories into one published repository:

```yaml
# Example: Complete RHEL 9 system
views:
  - name: rhel9-complete
    repositories:
      - repo_id: rhel9-baseos
      - repo_id: rhel9-appstream
      - repo_id: rhel9-crb
      - repo_id: epel9
```

### 4. Test in Staging Before Production

Recommended workflow:

1. **Development**: Use latest versions (`only_latest_version: true`)
2. **Staging**: Create snapshots, test thoroughly
3. **Production**: Promote tested snapshots

```bash
# Sync latest
chantal repo sync --repo-id epel9

# Create staging snapshot
chantal snapshot create --repo-id epel9 --name staging-2025-01
chantal publish snapshot --repo-id epel9 --snapshot staging-2025-01

# After testing in staging, promote to production
chantal snapshot create --repo-id epel9 --name prod-2025-01
chantal publish snapshot --repo-id epel9 --snapshot prod-2025-01
```

## Authentication and Certificates

### RHEL CDN Authentication

RHEL repositories require client certificate authentication:

1. **Register system with Red Hat**:
   ```bash
   subscription-manager register
   subscription-manager attach --auto
   ```

2. **Find entitlement certificates**:
   ```bash
   ls /etc/pki/entitlement/
   # Look for files like: 1234567890123456789.pem
   ```

3. **Update configuration**:
   Replace `YOUR_CERT_ID` in rhel9.yaml with actual certificate ID (without .pem extension)

### GPG Key Verification

Most repositories use GPG signatures for package verification. Example configurations include `gpgkey` URLs in client configuration sections.

## Storage Requirements

Estimated storage requirements (full mirror with `only_latest_version: true`):

| Repository | Size | Notes |
|------------|------|-------|
| RHEL 9 BaseOS | 10-15 GB | Core OS packages |
| RHEL 9 AppStream | 30-40 GB | Applications and runtimes |
| RHEL 9 CRB | 5-10 GB | Development tools |
| EPEL 9 | 30-50 GB | Extra packages (largest third-party repo) |
| Docker CE | 200-500 MB | Container platform |
| GitLab CE | 500 MB - 1 GB | ~1 GB per version |
| GitLab Runner | 50-100 MB | Lightweight runner |
| Grafana | 100-200 MB | Monitoring platform |
| HashiCorp | 100-300 MB | Per tool |
| Icinga | 50-100 MB | Monitoring platform |
| PostgreSQL | 500 MB - 1 GB | Per major version |
| Zabbix | 100-200 MB | Per major version |

**Storage optimization**:
- Use `only_latest_version: true` to keep only latest package versions (~30-40% reduction)
- Use pattern filters to mirror only needed packages
- Chantal uses content-addressed storage with automatic deduplication
- Snapshots use hardlinks (zero-copy, instant snapshots)

## Support and Updates

These examples are maintained as part of the Chantal project:
- **Repository**: https://github.com/slauger/chantal
- **Issue Tracker**: https://github.com/slauger/chantal/issues
- **Documentation**: See individual YAML files for detailed documentation

### Reporting Issues

If you find issues with example configurations:
1. Check the official repository documentation
2. Verify authentication (for RHEL and other authenticated repos)
3. Open issue on GitHub with configuration details

### Contributing

Contributions welcome! If you create configurations for additional distributions or repositories:
1. Follow the existing format and structure
2. Include comprehensive comments and documentation
3. Add usage examples and client configuration
4. Submit pull request

## Roadmap

Planned additions (see Issue #3):

**RPM Distributions**:
- CentOS Stream
- Rocky Linux
- AlmaLinux
- Fedora

**Additional Third-Party Repositories**:
- Elastic Stack (Elasticsearch, Logstash, Kibana)
- Kubernetes (kubeadm, kubectl, kubelet)
- Prometheus and exporters
- Redis
- MongoDB
- NGINX (official repo)
- MariaDB (official repo)
- Node.js (NodeSource)
- Python packages (RPM packages, not PyPI)

**APT/Debian** (future):
- Ubuntu LTS releases
- Debian stable releases
- APT-based third-party repositories

## License

These example configurations are provided as-is under the same license as Chantal.
Configuration examples are based on publicly available repository information.

## Disclaimer

- RHEL and Red Hat are trademarks of Red Hat, Inc.
- All other trademarks are property of their respective owners
- Example configurations are provided for reference only
- Always verify configurations with official documentation
- Test in non-production environments first
- Ensure compliance with software licenses and terms of service
