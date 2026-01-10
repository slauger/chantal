# Workflows

Common workflows for using Chantal in different scenarios.

## Patch Management Workflow

This workflow demonstrates how to use Chantal for monthly patch management.

### Step 1: Initial Setup

```bash
# Initialize Chantal
chantal init

# Configure repositories (see configuration guide)
vim conf.d/rhel9.yaml

# Sync initial state
chantal repo sync --all
```

### Step 2: Create Monthly Baseline

```bash
# Create baseline snapshot (e.g., January 2025)
chantal snapshot create \
  --repo-id rhel9-baseos \
  --name 2025-01 \
  --description "January 2025 patch baseline"

# Publish snapshot for test environment
chantal publish snapshot --snapshot rhel9-baseos-2025-01
```

### Step 3: Monthly Update Cycle

```bash
# Check for new updates
chantal repo check-updates --all

# Sync new packages
chantal repo sync --all

# Create new snapshot
chantal snapshot create \
  --repo-id rhel9-baseos \
  --name 2025-02 \
  --description "February 2025 patch baseline"

# Compare with previous month
chantal snapshot diff \
  --repo-id rhel9-baseos \
  2025-01 2025-02

# Publish new snapshot for testing
chantal publish snapshot --snapshot rhel9-baseos-2025-02
```

### Step 4: Promote to Production

After testing in dev/test environment:

```bash
# Unpublish old production snapshot
chantal publish unpublish --snapshot rhel9-baseos-2024-12

# Publish new production snapshot
chantal publish snapshot --snapshot rhel9-baseos-2025-01
```

## Development Environment Workflow

For developers who need specific package versions.

### Setup

```bash
# Initialize
chantal init

# Sync specific packages
chantal repo sync --repo-id epel9-development-tools
```

### Working with Snapshots

```bash
# Create snapshot for current sprint
chantal snapshot create \
  --repo-id epel9-development-tools \
  --name sprint-24 \
  --description "Sprint 24 dependencies"

# Publish for team
chantal publish snapshot --snapshot epel9-development-tools-sprint-24
```

## Air-Gapped Environment Workflow

For completely offline environments.

### Phase 1: Online System (Internet-Connected)

```bash
# Sync all required repositories
chantal repo sync --all

# Create snapshots
chantal snapshot create --repo-id rhel9-baseos --name airgap-2025-01
chantal snapshot create --repo-id rhel9-appstream --name airgap-2025-01

# Export pool and database
tar czf chantal-export-2025-01.tar.gz \
  /var/lib/chantal/pool \
  /var/lib/chantal/chantal.db \
  /etc/chantal/config.yaml \
  /etc/chantal/conf.d/
```

### Phase 2: Offline System (Air-Gapped)

```bash
# Extract export
tar xzf chantal-export-2025-01.tar.gz

# Publish repositories
chantal publish snapshot --snapshot rhel9-baseos-airgap-2025-01
chantal publish snapshot --snapshot rhel9-appstream-airgap-2025-01

# Serve via web server
# Published repositories are now in /var/www/repos
```

## RHEL Subscription Workflow

Working with Red Hat CDN repositories.

### Setup RHEL Subscription

1. Register system or obtain entitlement certificates:
   ```bash
   # Option 1: Register with subscription-manager
   sudo subscription-manager register
   sudo subscription-manager attach --auto

   # Certificates will be in /etc/pki/entitlement/
   ```

2. Configure Chantal:
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
   ```

3. Sync:
   ```bash
   chantal repo sync --repo-id rhel9-baseos
   ```

## Selective Mirroring Workflow

Only mirror specific packages to save space.

### Example: Only Mirror Web Server Packages

```yaml
repositories:
  - id: rhel9-appstream-webservers
    name: RHEL 9 AppStream - Web Servers
    type: rpm
    feed: https://cdn.redhat.com/content/dist/rhel9/9/x86_64/appstream/os
    enabled: true
    filters:
      patterns:
        include:
          - "^nginx-.*"
          - "^httpd-.*"
          - "^mod_.*"
        exclude:
          - ".*-debug.*"
          - ".*-devel$"
      metadata:
        architectures:
          include: ["x86_64", "noarch"]
      rpm:
        exclude_source_rpms: true
      post_processing:
        only_latest_version: true
```

```bash
# Sync only web server packages
chantal repo sync --repo-id rhel9-appstream-webservers
```

## Multi-Architecture Workflow

Mirror for multiple architectures (x86_64, aarch64).

### Configuration

```yaml
repositories:
  # x86_64
  - id: rhel9-baseos-x86_64
    name: RHEL 9 BaseOS - x86_64
    type: rpm
    feed: https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os
    enabled: true
    filters:
      metadata:
        architectures:
          include: ["x86_64", "noarch"]

  # aarch64
  - id: rhel9-baseos-aarch64
    name: RHEL 9 BaseOS - aarch64
    type: rpm
    feed: https://cdn.redhat.com/content/dist/rhel9/9/aarch64/baseos/os
    enabled: true
    filters:
      metadata:
        architectures:
          include: ["aarch64", "noarch"]
```

### Sync Both Architectures

```bash
# Sync all architectures
chantal repo sync --pattern "rhel9-baseos-*"

# Create snapshots for both
chantal snapshot create --repo-id rhel9-baseos-x86_64 --name 2025-01
chantal snapshot create --repo-id rhel9-baseos-aarch64 --name 2025-01
```

## Scheduled Sync Workflow

Use cron or systemd timers for automated syncing.

### Cron Example

```bash
# Edit crontab
crontab -e

# Add daily sync at 2 AM
0 2 * * * cd /var/lib/chantal && chantal repo sync --all >> /var/log/chantal/sync.log 2>&1
```

### Systemd Timer Example

Create `/etc/systemd/system/chantal-sync.service`:

```ini
[Unit]
Description=Chantal Repository Sync
After=network-online.target

[Service]
Type=oneshot
User=chantal
Group=chantal
WorkingDirectory=/var/lib/chantal
ExecStart=/usr/local/bin/chantal repo sync --all
StandardOutput=journal
StandardError=journal
```

Create `/etc/systemd/system/chantal-sync.timer`:

```ini
[Unit]
Description=Daily Chantal Repository Sync
Requires=chantal-sync.service

[Timer]
OnCalendar=daily
OnCalendar=02:00
Persistent=true

[Install]
WantedBy=timers.target
```

Enable timer:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now chantal-sync.timer
```

## Disaster Recovery Workflow

Backup and restore Chantal state.

### Backup

```bash
# Backup pool and database
tar czf chantal-backup-$(date +%Y%m%d).tar.gz \
  /var/lib/chantal/pool \
  /var/lib/chantal/chantal.db \
  /etc/chantal/

# Store backup offsite
rsync -avz chantal-backup-*.tar.gz backup-server:/backups/
```

### Restore

```bash
# Extract backup
tar xzf chantal-backup-20250110.tar.gz -C /

# Verify database
chantal db verify

# Republish all repositories
chantal publish repo --all
```
