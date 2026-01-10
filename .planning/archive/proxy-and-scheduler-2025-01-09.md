# HTTP Proxy & Scheduler Design

**Datum:** 2025-01-09
**Status:** Planning

---

## 1. HTTP Proxy Support

### Requirements

- **Global proxy configuration** - applies to all repositories by default
- **Per-repository proxy override** - specific repos can use different proxies or bypass proxy
- **Environment variable support** - respect `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`
- **Authentication support** - proxy username/password
- **Certificate validation** - option to verify or skip proxy SSL certificates

### Configuration Design

#### Global Proxy (`/etc/chantal/config.yaml`)

```yaml
# /etc/chantal/config.yaml

# Global proxy settings (optional)
proxy:
  http_proxy: "http://proxy.example.com:8080"
  https_proxy: "http://proxy.example.com:8080"
  no_proxy: "localhost,127.0.0.1,.internal.domain"

  # Proxy authentication (optional)
  username: "proxyuser"
  password: "secret"  # Consider using environment variable: ${CHANTAL_PROXY_PASSWORD}

  # SSL verification
  verify_ssl: true
  ca_bundle: "/etc/ssl/certs/ca-certificates.crt"

storage:
  base_path: /var/lib/chantal

database:
  url: postgresql://chantal:password@localhost/chantal
```

#### Per-Repository Proxy Override (`/etc/chantal/conf.d/rhel9.yaml`)

```yaml
# /etc/chantal/conf.d/rhel9.yaml

repositories:
  - id: rhel9-baseos
    type: rpm
    upstream_url: https://cdn.redhat.com/content/dist/rhel9/...

    # Override global proxy for this repo
    proxy:
      http_proxy: "http://special-proxy.example.com:3128"
      https_proxy: "http://special-proxy.example.com:3128"
      # Or disable proxy for this repo:
      # enabled: false

    # RHEL subscription auth
    auth:
      type: client_cert
      cert_dir: /etc/pki/entitlement

  - id: internal-repo
    type: rpm
    upstream_url: https://repo.internal.company.com/rhel9/

    # Disable proxy for internal repos
    proxy:
      enabled: false
```

### Implementation

#### Pydantic Models

```python
from typing import Optional
from pydantic import BaseModel, Field


class ProxyConfig(BaseModel):
    """HTTP proxy configuration."""

    enabled: bool = True
    http_proxy: Optional[str] = None
    https_proxy: Optional[str] = None
    no_proxy: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    verify_ssl: bool = True
    ca_bundle: Optional[str] = None


class GlobalConfig(BaseModel):
    """Global Chantal configuration."""

    storage: StorageConfig
    database: DatabaseConfig
    proxy: Optional[ProxyConfig] = None  # Global proxy settings


class RepositoryConfig(BaseModel):
    """Repository configuration."""

    id: str
    type: str
    upstream_url: str
    proxy: Optional[ProxyConfig] = None  # Per-repo proxy override
    auth: Optional[AuthConfig] = None
```

#### HTTP Client with Proxy Support

```python
import os
import requests
from typing import Optional, Dict
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class ProxyHTTPClient:
    """HTTP client with proxy support."""

    def __init__(
        self,
        proxy_config: Optional[ProxyConfig] = None,
        global_proxy: Optional[ProxyConfig] = None
    ):
        """Initialize HTTP client with proxy configuration.

        Args:
            proxy_config: Repository-specific proxy config (takes precedence)
            global_proxy: Global proxy config (fallback)
        """
        self.session = requests.Session()

        # Determine which proxy config to use
        effective_proxy = self._resolve_proxy_config(proxy_config, global_proxy)

        # Configure proxy
        if effective_proxy and effective_proxy.enabled:
            self._configure_proxy(effective_proxy)

        # Configure retries
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def _resolve_proxy_config(
        self,
        repo_proxy: Optional[ProxyConfig],
        global_proxy: Optional[ProxyConfig]
    ) -> Optional[ProxyConfig]:
        """Resolve effective proxy configuration.

        Priority:
        1. Repository proxy config (if present)
        2. Global proxy config (if present)
        3. Environment variables (HTTP_PROXY, HTTPS_PROXY, NO_PROXY)
        4. No proxy
        """
        if repo_proxy is not None:
            return repo_proxy

        if global_proxy is not None:
            return global_proxy

        # Check environment variables
        http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
        https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy")

        if http_proxy or https_proxy:
            return ProxyConfig(
                http_proxy=http_proxy,
                https_proxy=https_proxy,
                no_proxy=no_proxy
            )

        return None

    def _configure_proxy(self, proxy_config: ProxyConfig) -> None:
        """Configure session with proxy settings."""
        proxies: Dict[str, str] = {}

        # Build proxy URL with authentication
        if proxy_config.http_proxy:
            proxy_url = proxy_config.http_proxy
            if proxy_config.username and proxy_config.password:
                # Insert auth into URL: http://user:pass@proxy.com:8080
                from urllib.parse import urlparse, urlunparse
                parsed = urlparse(proxy_url)
                auth = f"{proxy_config.username}:{proxy_config.password}"
                netloc = f"{auth}@{parsed.netloc}"
                proxy_url = urlunparse(parsed._replace(netloc=netloc))
            proxies["http"] = proxy_url

        if proxy_config.https_proxy:
            proxy_url = proxy_config.https_proxy
            if proxy_config.username and proxy_config.password:
                from urllib.parse import urlparse, urlunparse
                parsed = urlparse(proxy_url)
                auth = f"{proxy_config.username}:{proxy_config.password}"
                netloc = f"{auth}@{parsed.netloc}"
                proxy_url = urlunparse(parsed._replace(netloc=netloc))
            proxies["https"] = proxy_url

        self.session.proxies.update(proxies)

        # Configure SSL verification
        if not proxy_config.verify_ssl:
            self.session.verify = False
        elif proxy_config.ca_bundle:
            self.session.verify = proxy_config.ca_bundle

    def get(self, url: str, **kwargs) -> requests.Response:
        """HTTP GET request with proxy support."""
        return self.session.get(url, **kwargs)

    def download_file(
        self,
        url: str,
        destination: str,
        cert: Optional[tuple] = None
    ) -> None:
        """Download file with proxy support."""
        response = self.session.get(url, cert=cert, stream=True)
        response.raise_for_status()

        with open(destination, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
```

#### Integration with RPM Plugin

```python
class RPMPlugin:
    """RPM repository plugin with proxy support."""

    def __init__(
        self,
        repo_config: RepositoryConfig,
        global_config: GlobalConfig
    ):
        self.repo_config = repo_config
        self.global_config = global_config

        # Initialize HTTP client with proxy configuration
        self.http_client = ProxyHTTPClient(
            proxy_config=repo_config.proxy,
            global_proxy=global_config.proxy
        )

    def sync(self) -> None:
        """Sync repository using configured proxy."""
        # Download repomd.xml
        repomd_url = f"{self.repo_config.upstream_url}/repodata/repomd.xml"

        # Client certificates for RHEL CDN
        cert = None
        if self.repo_config.auth and self.repo_config.auth.type == "client_cert":
            cert = self._get_client_cert()

        response = self.http_client.get(repomd_url, cert=cert)
        # ... rest of sync logic
```

### Environment Variable Support

Users can also configure proxies via environment variables without changing config files:

```bash
# Set proxy environment variables
export HTTP_PROXY="http://proxy.example.com:8080"
export HTTPS_PROXY="http://proxy.example.com:8080"
export NO_PROXY="localhost,127.0.0.1,.internal.domain"

# Run chantal (will use environment proxy settings)
chantal repo sync --repo-id rhel9-baseos
```

**Priority order:**
1. Per-repository `proxy:` config (highest priority)
2. Global `proxy:` config in `/etc/chantal/config.yaml`
3. Environment variables (`HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`)
4. No proxy (direct connection)

---

## 2. Scheduler & Daemon Service

### Requirements

- **Scheduled syncs** - cron-style scheduling for automatic repository updates
- **Daemon mode** - long-running process that executes scheduled tasks
- **Lock mechanism** - prevent concurrent syncs of the same repository
- **Systemd integration** - proper service file for system management
- **Configurable schedules** - per-repository cron expressions
- **Manual sync override** - allow manual syncs even with scheduler running

### Architecture Options

#### Option A: Built-in Scheduler (Recommended for MVP)

**Pros:**
- Single binary, no external dependencies
- Simple configuration
- Easy to debug

**Cons:**
- Must be running continuously
- Restarts lose schedule state (mitigated by systemd)

#### Option B: External Cron

**Pros:**
- Uses existing system cron
- Simple, proven technology

**Cons:**
- Requires manual crontab configuration
- Less flexible scheduling
- Harder to manage multiple repos

**Decision:** Use Option A (built-in scheduler) for better UX and control.

### Configuration Design

#### Per-Repository Schedule

```yaml
# /etc/chantal/conf.d/rhel9.yaml

repositories:
  - id: rhel9-baseos
    type: rpm
    upstream_url: https://cdn.redhat.com/content/dist/rhel9/...

    # Scheduling configuration
    schedule:
      enabled: true
      cron: "0 2 * * *"  # Daily at 2:00 AM
      create_snapshot: true
      snapshot_name_template: "rhel9-baseos-{date}"  # {date} = YYYYMMDD

    auth:
      type: client_cert
      cert_dir: /etc/pki/entitlement

  - id: epel9
    type: rpm
    upstream_url: https://dl.fedoraproject.org/pub/epel/9/Everything/x86_64/

    schedule:
      enabled: true
      cron: "0 3 * * *"  # Daily at 3:00 AM
      create_snapshot: false  # EPEL changes frequently, no snapshots

  - id: internal-repo
    type: rpm
    upstream_url: https://repo.internal.company.com/rhel9/

    # No schedule - manual sync only
    schedule:
      enabled: false
```

#### Cron Expression Format

Standard cron format (5 fields):

```
┌───────────── minute (0 - 59)
│ ┌───────────── hour (0 - 23)
│ │ ┌───────────── day of month (1 - 31)
│ │ │ ┌───────────── month (1 - 12)
│ │ │ │ ┌───────────── day of week (0 - 6) (Sunday=0)
│ │ │ │ │
│ │ │ │ │
* * * * *
```

**Examples:**
- `0 2 * * *` - Every day at 2:00 AM
- `0 */6 * * *` - Every 6 hours
- `0 0 * * 0` - Every Sunday at midnight
- `*/30 * * * *` - Every 30 minutes
- `0 2 * * 1-5` - Weekdays at 2:00 AM

### Implementation

#### Pydantic Models

```python
from typing import Optional
from pydantic import BaseModel, Field


class ScheduleConfig(BaseModel):
    """Repository sync schedule configuration."""

    enabled: bool = False
    cron: str = Field(..., description="Cron expression (e.g., '0 2 * * *')")
    create_snapshot: bool = False
    snapshot_name_template: Optional[str] = None

    # Optional: jitter to avoid thundering herd
    jitter_seconds: int = Field(0, ge=0, le=300, description="Random delay up to N seconds")


class RepositoryConfig(BaseModel):
    """Repository configuration with scheduling."""

    id: str
    type: str
    upstream_url: str
    schedule: Optional[ScheduleConfig] = None
    proxy: Optional[ProxyConfig] = None
    auth: Optional[AuthConfig] = None
```

#### Scheduler Service

```python
import time
import logging
from datetime import datetime
from typing import List
from croniter import croniter
from pathlib import Path
import random


class SchedulerService:
    """Repository sync scheduler service."""

    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        self.logger = logging.getLogger(__name__)
        self.running = False
        self.repositories: List[RepositoryConfig] = []
        self.last_sync: dict = {}  # repo_id -> last_sync_time

    def load_config(self) -> None:
        """Load repository configurations."""
        # Load main config
        config_file = self.config_dir / "config.yaml"
        # ... load global config

        # Load all repo configs from conf.d/
        conf_d = self.config_dir / "conf.d"
        if conf_d.exists():
            for yaml_file in conf_d.glob("*.yaml"):
                # ... load repo configs
                pass

    def start(self) -> None:
        """Start scheduler daemon."""
        self.logger.info("Starting Chantal scheduler service")
        self.running = True

        self.load_config()

        # Main scheduler loop
        while self.running:
            try:
                self._check_scheduled_syncs()
                time.sleep(60)  # Check every minute
            except KeyboardInterrupt:
                self.logger.info("Received shutdown signal")
                self.stop()
            except Exception as e:
                self.logger.error(f"Scheduler error: {e}", exc_info=True)
                time.sleep(60)

    def stop(self) -> None:
        """Stop scheduler daemon."""
        self.logger.info("Stopping Chantal scheduler service")
        self.running = False

    def _check_scheduled_syncs(self) -> None:
        """Check if any repositories need syncing."""
        now = datetime.now()

        for repo in self.repositories:
            # Skip if scheduling not enabled
            if not repo.schedule or not repo.schedule.enabled:
                continue

            # Check if it's time to sync
            if self._should_sync(repo, now):
                self._trigger_sync(repo)

    def _should_sync(self, repo: RepositoryConfig, now: datetime) -> bool:
        """Determine if repository should be synced now."""
        if not repo.schedule or not repo.schedule.cron:
            return False

        # Get last sync time
        last_sync = self.last_sync.get(repo.id)

        # Parse cron expression
        try:
            cron = croniter(repo.schedule.cron, start_time=last_sync or now)
            next_run = cron.get_next(datetime)

            # If next run time has passed, it's time to sync
            return now >= next_run
        except Exception as e:
            self.logger.error(f"Invalid cron expression for {repo.id}: {e}")
            return False

    def _trigger_sync(self, repo: RepositoryConfig) -> None:
        """Trigger repository sync."""
        self.logger.info(f"Triggering scheduled sync for {repo.id}")

        # Apply jitter if configured
        if repo.schedule and repo.schedule.jitter_seconds > 0:
            jitter = random.randint(0, repo.schedule.jitter_seconds)
            self.logger.info(f"Applying jitter: {jitter} seconds")
            time.sleep(jitter)

        # Acquire lock to prevent concurrent syncs
        lock_file = Path(f"/var/lock/chantal-{repo.id}.lock")

        try:
            # Try to acquire lock (non-blocking)
            import fcntl
            lock_fd = open(lock_file, 'w')
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

            try:
                # Perform sync
                self._perform_sync(repo)

                # Update last sync time
                self.last_sync[repo.id] = datetime.now()

            finally:
                # Release lock
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                lock_fd.close()

        except BlockingIOError:
            self.logger.warning(f"Sync already running for {repo.id}, skipping")
        except Exception as e:
            self.logger.error(f"Sync failed for {repo.id}: {e}", exc_info=True)

    def _perform_sync(self, repo: RepositoryConfig) -> None:
        """Perform actual repository sync."""
        # TODO: Integrate with SyncManager
        # For now, just log
        self.logger.info(f"Syncing {repo.id} from {repo.upstream_url}")

        # Example: call sync command
        # sync_manager = SyncManager(repo)
        # sync_manager.sync()

        # Create snapshot if configured
        if repo.schedule and repo.schedule.create_snapshot:
            snapshot_name = self._generate_snapshot_name(repo)
            self.logger.info(f"Creating snapshot: {snapshot_name}")
            # snapshot_manager.create_snapshot(repo.id, snapshot_name)

    def _generate_snapshot_name(self, repo: RepositoryConfig) -> str:
        """Generate snapshot name from template."""
        if repo.schedule and repo.schedule.snapshot_name_template:
            template = repo.schedule.snapshot_name_template
            # Replace placeholders
            date_str = datetime.now().strftime("%Y%m%d")
            time_str = datetime.now().strftime("%H%M%S")

            return template.format(
                date=date_str,
                time=time_str,
                datetime=f"{date_str}-{time_str}",
                repo_id=repo.id
            )
        else:
            # Default: repo-id-YYYYMMDD-HHMMSS
            return f"{repo.id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
```

#### Lock Mechanism

```python
import fcntl
from pathlib import Path
from contextlib import contextmanager


class SyncLock:
    """File-based lock to prevent concurrent syncs."""

    def __init__(self, repo_id: str, lock_dir: Path = Path("/var/lock")):
        self.repo_id = repo_id
        self.lock_file = lock_dir / f"chantal-{repo_id}.lock"
        self.lock_fd = None

    @contextmanager
    def acquire(self, blocking: bool = False):
        """Acquire sync lock."""
        try:
            self.lock_fd = open(self.lock_file, 'w')

            # Try to acquire lock
            flags = fcntl.LOCK_EX
            if not blocking:
                flags |= fcntl.LOCK_NB

            fcntl.flock(self.lock_fd, flags)

            yield

        except BlockingIOError:
            raise RuntimeError(f"Repository {self.repo_id} is already being synced")
        finally:
            if self.lock_fd:
                fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
                self.lock_fd.close()


# Usage
def sync_repository(repo_id: str):
    """Sync repository with lock protection."""
    lock = SyncLock(repo_id)

    try:
        with lock.acquire(blocking=False):
            # Perform sync
            print(f"Syncing {repo_id}")
            # ... sync logic
    except RuntimeError as e:
        print(f"Error: {e}")
```

### CLI Commands

#### Start Scheduler Daemon

```bash
# Start scheduler in foreground (for testing)
chantal scheduler start

# Start scheduler in background (systemd handles this)
chantal scheduler start --daemon

# Stop scheduler
chantal scheduler stop

# Show scheduler status
chantal scheduler status
# Output:
# Chantal Scheduler: Running
# Uptime: 3 days, 5 hours
# Repositories with schedules: 5
# Last sync: rhel9-baseos at 2025-01-09 02:00:00 (Success)
# Next scheduled sync: epel9 at 2025-01-10 03:00:00

# List scheduled repositories
chantal scheduler list
# Output:
# Repository       Schedule        Next Run             Last Run
# rhel9-baseos     0 2 * * *       2025-01-10 02:00:00  2025-01-09 02:00:00 (Success)
# epel9            0 3 * * *       2025-01-10 03:00:00  2025-01-09 03:00:00 (Success)
# internal-repo    (manual only)   -                    2025-01-08 14:30:00 (Success)
```

#### Manual Sync Override

Manual syncs work even when scheduler is running:

```bash
# Manual sync (acquires lock, blocks if already running)
chantal repo sync --repo-id rhel9-baseos

# Force sync (kills running sync and starts new one - USE WITH CAUTION!)
chantal repo sync --repo-id rhel9-baseos --force
```

### Systemd Integration

#### Service File (`/etc/systemd/system/chantal-scheduler.service`)

```ini
[Unit]
Description=Chantal Repository Sync Scheduler
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=simple
User=chantal
Group=chantal
WorkingDirectory=/var/lib/chantal

# Environment
Environment="PATH=/usr/local/bin:/usr/bin:/bin"
Environment="CHANTAL_CONFIG_DIR=/etc/chantal"

# Run scheduler
ExecStart=/usr/local/bin/chantal scheduler start --daemon

# Restart policy
Restart=always
RestartSec=10s

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=chantal-scheduler

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/chantal /var/lock

[Install]
WantedBy=multi-user.target
```

#### Installation Commands

```bash
# Install systemd service
sudo cp /etc/chantal/chantal-scheduler.service /etc/systemd/system/
sudo systemctl daemon-reload

# Enable service (start on boot)
sudo systemctl enable chantal-scheduler.service

# Start service
sudo systemctl start chantal-scheduler.service

# Check status
sudo systemctl status chantal-scheduler.service

# View logs
sudo journalctl -u chantal-scheduler.service -f

# Stop service
sudo systemctl stop chantal-scheduler.service
```

### Dependencies

Add to `pyproject.toml`:

```toml
dependencies = [
    # ... existing
    "croniter>=2.0.0",  # Cron expression parsing
]
```

---

## 3. Database Backup & Restore

### Requirements

- **Backup database** - Export PostgreSQL database to file
- **Restore database** - Import database from backup file
- **Include metadata** - backup timestamp, Chantal version, database schema version
- **Compression** - gzip compression for smaller backup files
- **Verification** - verify backup integrity
- **Incremental backups** (future) - only backup changes since last backup

### Backup Scope

**What to backup:**
- ✅ Database (PostgreSQL dump)
- ✅ Configuration files (`/etc/chantal/`)
- ⚠️  Package pool (`/var/lib/chantal/pool/`) - **NOT included** (too large, can be re-synced)
- ⚠️  Published repos (`/var/www/repos/`) - **NOT included** (can be re-published from database)

**Backup includes:**
- All packages metadata (name, version, arch, SHA256, etc.)
- All repositories configuration (stored in DB)
- All snapshots and their package associations
- Sync history and statistics
- Database schema version (for migration compatibility)

**Backup does NOT include:**
- Actual RPM/DEB files (multi-GB, re-downloadable)
- Published repository directories (regenerated from metadata)

**Rationale:**
- Database backup is small (few MB to few hundred MB)
- Package pool can be re-synced from upstream if needed
- Most critical data is metadata relationships (what packages are in which snapshots)
- For full disaster recovery, backup package pool separately using rsync/borg/restic

### CLI Commands

```bash
# Backup database
chantal db backup
chantal db backup --output /backups/chantal-backup-20250109.sql.gz
chantal db backup --output /backups/chantal-$(date +%Y%m%d).sql.gz --compress

# Backup database + config
chantal db backup --include-config
# Creates:
# - chantal-backup-20250109.tar.gz
#   ├── database.sql.gz          (PostgreSQL dump)
#   ├── config/                  (copy of /etc/chantal/)
#   └── manifest.json            (metadata: version, timestamp, etc.)

# List backups (from default backup directory)
chantal db backup-list
# Output:
# Backup File                          Date                 Size     Database Version
# chantal-backup-20250109.tar.gz      2025-01-09 14:30:00  45 MB    alembic:abc123
# chantal-backup-20250108.tar.gz      2025-01-08 02:00:00  44 MB    alembic:abc123
# chantal-backup-20250107.tar.gz      2025-01-07 02:00:00  43 MB    alembic:abc123

# Show backup info
chantal db backup-info /backups/chantal-backup-20250109.tar.gz
# Output:
# Backup: chantal-backup-20250109.tar.gz
# Created: 2025-01-09 14:30:00
# Chantal Version: 0.1.0
# Database Version: alembic:abc123 (head)
# Database Size: 45 MB
# Repositories: 5
# Packages: 8,320
# Snapshots: 23
# Includes Config: Yes
# Compression: gzip

# Restore database from backup
chantal db restore /backups/chantal-backup-20250109.tar.gz
chantal db restore /backups/chantal-backup-20250109.tar.gz --confirm

# Restore with confirmation prompt
chantal db restore /backups/chantal-backup-20250109.tar.gz
# Output:
# WARNING: This will DESTROY the current database and replace it with the backup!
# Current database: 8,320 packages, 5 repositories, 23 snapshots
# Backup database: 8,100 packages, 5 repositories, 20 snapshots
#
# Are you sure you want to restore? Type 'yes' to confirm: yes
# Restoring database from backup...
# ✓ Database restored successfully
# ✓ Config files restored to /etc/chantal/
#
# Next steps:
# - Verify repository configuration: chantal config validate
# - Re-sync repositories if needed: chantal repo sync --all
# - Re-publish repositories: chantal publish --all

# Verify backup without restoring
chantal db backup-verify /backups/chantal-backup-20250109.tar.gz
# Output:
# Verifying backup: chantal-backup-20250109.tar.gz
# ✓ Backup file is valid tar.gz archive
# ✓ Manifest file present and valid
# ✓ Database dump file present (45 MB)
# ✓ Config directory present (12 files)
# ✓ Backup is valid and can be restored
```

### Implementation

#### Pydantic Models

```python
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class BackupManifest(BaseModel):
    """Metadata about a Chantal backup."""

    backup_version: str = "1.0"
    chantal_version: str
    database_version: str  # Alembic revision
    created_at: datetime
    hostname: str

    # Database statistics
    repositories_count: int
    packages_count: int
    snapshots_count: int

    # Backup contents
    includes_config: bool
    compression: str  # "gzip", "none"

    # File information
    database_file: str  # "database.sql.gz"
    database_size_bytes: int
    config_files: Optional[List[str]] = None


class BackupInfo(BaseModel):
    """Information about a backup file."""

    backup_file: str
    manifest: BackupManifest
    file_size_bytes: int
```

#### Backup Implementation

```python
import subprocess
import tarfile
import gzip
import json
from pathlib import Path
from datetime import datetime
from typing import Optional


class DatabaseBackupManager:
    """Manages database backups and restores."""

    def __init__(
        self,
        database_url: str,
        config_dir: Path = Path("/etc/chantal"),
        backup_dir: Path = Path("/var/backups/chantal")
    ):
        self.database_url = database_url
        self.config_dir = config_dir
        self.backup_dir = backup_dir
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def create_backup(
        self,
        output_file: Optional[Path] = None,
        include_config: bool = True,
        compress: bool = True
    ) -> Path:
        """Create a database backup.

        Args:
            output_file: Output file path (default: auto-generate)
            include_config: Include config files in backup
            compress: Use gzip compression

        Returns:
            Path to backup file
        """
        # Generate output filename if not provided
        if output_file is None:
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            output_file = self.backup_dir / f"chantal-backup-{timestamp}.tar.gz"

        # Create temporary directory for backup files
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # 1. Dump PostgreSQL database
            db_dump_file = tmppath / "database.sql.gz"
            self._dump_database(db_dump_file)

            # 2. Copy config files if requested
            config_files = []
            if include_config:
                config_backup = tmppath / "config"
                config_backup.mkdir()
                self._copy_config(config_backup, config_files)

            # 3. Get database statistics
            stats = self._get_database_stats()

            # 4. Create manifest
            manifest = BackupManifest(
                chantal_version=self._get_chantal_version(),
                database_version=self._get_database_version(),
                created_at=datetime.now(),
                hostname=self._get_hostname(),
                repositories_count=stats["repositories"],
                packages_count=stats["packages"],
                snapshots_count=stats["snapshots"],
                includes_config=include_config,
                compression="gzip" if compress else "none",
                database_file="database.sql.gz",
                database_size_bytes=db_dump_file.stat().st_size,
                config_files=config_files if include_config else None
            )

            # Write manifest
            manifest_file = tmppath / "manifest.json"
            manifest_file.write_text(manifest.model_dump_json(indent=2))

            # 5. Create tar.gz archive
            with tarfile.open(output_file, "w:gz") as tar:
                tar.add(tmppath / "manifest.json", arcname="manifest.json")
                tar.add(db_dump_file, arcname="database.sql.gz")
                if include_config:
                    tar.add(tmppath / "config", arcname="config")

        return output_file

    def _dump_database(self, output_file: Path) -> None:
        """Dump PostgreSQL database using pg_dump."""
        # Parse database URL
        # postgresql://user:pass@host:port/dbname
        from sqlalchemy.engine.url import make_url
        db_url = make_url(self.database_url)

        # Build pg_dump command
        env = {
            "PGPASSWORD": db_url.password or "",
        }

        cmd = [
            "pg_dump",
            "--host", db_url.host or "localhost",
            "--port", str(db_url.port or 5432),
            "--username", db_url.username or "postgres",
            "--dbname", db_url.database,
            "--format", "plain",  # SQL text format
            "--no-owner",  # Don't include ownership commands
            "--no-acl",  # Don't include ACL commands
        ]

        # Dump database and compress
        with gzip.open(output_file, "wb") as f:
            result = subprocess.run(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True
            )
            f.write(result.stdout)

    def _copy_config(self, target_dir: Path, file_list: List[str]) -> None:
        """Copy config files to backup directory."""
        import shutil

        for item in self.config_dir.iterdir():
            if item.name.startswith("."):
                continue

            target = target_dir / item.name
            if item.is_file():
                shutil.copy2(item, target)
                file_list.append(item.name)
            elif item.is_dir():
                shutil.copytree(item, target)
                file_list.append(f"{item.name}/")

    def _get_database_stats(self) -> dict:
        """Get database statistics."""
        from sqlalchemy import create_engine, text

        engine = create_engine(self.database_url)
        with engine.connect() as conn:
            repos = conn.execute(text("SELECT COUNT(*) FROM repositories")).scalar()
            packages = conn.execute(text("SELECT COUNT(*) FROM packages")).scalar()
            snapshots = conn.execute(text("SELECT COUNT(*) FROM snapshots")).scalar()

        return {
            "repositories": repos or 0,
            "packages": packages or 0,
            "snapshots": snapshots or 0,
        }

    def _get_chantal_version(self) -> str:
        """Get Chantal version."""
        from chantal import __version__
        return __version__

    def _get_database_version(self) -> str:
        """Get database schema version (Alembic revision)."""
        from sqlalchemy import create_engine, text

        engine = create_engine(self.database_url)
        try:
            with engine.connect() as conn:
                result = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
                return f"alembic:{result}" if result else "unknown"
        except:
            return "no-alembic"

    def _get_hostname(self) -> str:
        """Get system hostname."""
        import socket
        return socket.gethostname()

    def restore_backup(
        self,
        backup_file: Path,
        restore_config: bool = True,
        drop_existing: bool = True
    ) -> None:
        """Restore database from backup.

        Args:
            backup_file: Path to backup tar.gz file
            restore_config: Restore config files
            drop_existing: Drop existing database before restore

        Raises:
            ValueError: If backup is invalid
        """
        # Verify backup
        backup_info = self.verify_backup(backup_file)

        # Create temporary directory for extraction
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # Extract backup
            with tarfile.open(backup_file, "r:gz") as tar:
                tar.extractall(tmppath)

            # Restore database
            db_dump = tmppath / "database.sql.gz"
            self._restore_database(db_dump, drop_existing=drop_existing)

            # Restore config if requested and present
            if restore_config and backup_info.manifest.includes_config:
                config_backup = tmppath / "config"
                if config_backup.exists():
                    self._restore_config(config_backup)

    def _restore_database(self, dump_file: Path, drop_existing: bool = True) -> None:
        """Restore PostgreSQL database from dump."""
        from sqlalchemy.engine.url import make_url
        db_url = make_url(self.database_url)

        # Build environment
        env = {
            "PGPASSWORD": db_url.password or "",
        }

        # Drop existing database if requested
        if drop_existing:
            # TODO: Implement database drop/recreate
            pass

        # Restore using psql
        cmd = [
            "psql",
            "--host", db_url.host or "localhost",
            "--port", str(db_url.port or 5432),
            "--username", db_url.username or "postgres",
            "--dbname", db_url.database,
        ]

        # Decompress and restore
        with gzip.open(dump_file, "rb") as f:
            subprocess.run(
                cmd,
                env=env,
                stdin=f,
                check=True
            )

    def _restore_config(self, config_backup: Path) -> None:
        """Restore config files from backup."""
        import shutil

        # Backup existing config first
        if self.config_dir.exists():
            backup_name = f"{self.config_dir}.backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            shutil.move(self.config_dir, backup_name)

        # Restore config from backup
        shutil.copytree(config_backup, self.config_dir)

    def verify_backup(self, backup_file: Path) -> BackupInfo:
        """Verify backup integrity.

        Args:
            backup_file: Path to backup file

        Returns:
            BackupInfo with backup metadata

        Raises:
            ValueError: If backup is invalid
        """
        if not backup_file.exists():
            raise ValueError(f"Backup file not found: {backup_file}")

        # Open and verify tar.gz
        try:
            with tarfile.open(backup_file, "r:gz") as tar:
                # Check manifest exists
                try:
                    manifest_member = tar.getmember("manifest.json")
                    manifest_data = tar.extractfile(manifest_member).read()
                    manifest = BackupManifest.model_validate_json(manifest_data)
                except KeyError:
                    raise ValueError("Backup is missing manifest.json")

                # Check database dump exists
                try:
                    db_member = tar.getmember(manifest.database_file)
                except KeyError:
                    raise ValueError(f"Backup is missing {manifest.database_file}")

                # Check config if included
                if manifest.includes_config:
                    try:
                        tar.getmember("config")
                    except KeyError:
                        raise ValueError("Backup claims to include config but config/ is missing")

            return BackupInfo(
                backup_file=str(backup_file),
                manifest=manifest,
                file_size_bytes=backup_file.stat().st_size
            )

        except tarfile.TarError as e:
            raise ValueError(f"Invalid backup file (not a valid tar.gz): {e}")

    def list_backups(self) -> List[BackupInfo]:
        """List all backups in backup directory."""
        backups = []

        for backup_file in self.backup_dir.glob("chantal-backup-*.tar.gz"):
            try:
                info = self.verify_backup(backup_file)
                backups.append(info)
            except ValueError:
                # Skip invalid backups
                continue

        # Sort by creation date (newest first)
        backups.sort(key=lambda x: x.manifest.created_at, reverse=True)
        return backups
```

#### CLI Commands

```python
# In src/chantal/cli/main.py

@db.command("backup")
@click.option("--output", type=click.Path(), help="Output file path")
@click.option("--include-config/--no-include-config", default=True,
              help="Include config files")
@click.option("--compress/--no-compress", default=True, help="Use gzip compression")
@click.pass_context
def db_backup(
    ctx: click.Context,
    output: Optional[str],
    include_config: bool,
    compress: bool
) -> None:
    """Create database backup."""
    from chantal.db.backup import DatabaseBackupManager

    backup_manager = DatabaseBackupManager(
        database_url=get_database_url(ctx),
        config_dir=ctx.obj["config_dir"]
    )

    backup_file = backup_manager.create_backup(
        output_file=Path(output) if output else None,
        include_config=include_config,
        compress=compress
    )

    click.echo(f"✓ Backup created: {backup_file}")

    # Show backup info
    info = backup_manager.verify_backup(backup_file)
    click.echo(f"  Size: {info.file_size_bytes / 1024 / 1024:.1f} MB")
    click.echo(f"  Packages: {info.manifest.packages_count}")
    click.echo(f"  Repositories: {info.manifest.repositories_count}")
    click.echo(f"  Snapshots: {info.manifest.snapshots_count}")


@db.command("restore")
@click.argument("backup_file", type=click.Path(exists=True))
@click.option("--confirm/--no-confirm", default=True, help="Require confirmation")
@click.option("--restore-config/--no-restore-config", default=True,
              help="Restore config files")
@click.pass_context
def db_restore(
    ctx: click.Context,
    backup_file: str,
    confirm: bool,
    restore_config: bool
) -> None:
    """Restore database from backup."""
    from chantal.db.backup import DatabaseBackupManager

    backup_manager = DatabaseBackupManager(
        database_url=get_database_url(ctx),
        config_dir=ctx.obj["config_dir"]
    )

    # Verify backup
    backup_path = Path(backup_file)
    info = backup_manager.verify_backup(backup_path)

    # Show backup info
    click.echo("Backup Information:")
    click.echo(f"  File: {backup_file}")
    click.echo(f"  Created: {info.manifest.created_at}")
    click.echo(f"  Packages: {info.manifest.packages_count}")
    click.echo(f"  Repositories: {info.manifest.repositories_count}")
    click.echo(f"  Snapshots: {info.manifest.snapshots_count}")
    click.echo()

    # Confirmation
    if confirm:
        click.echo(click.style("WARNING: This will DESTROY the current database!", fg="red", bold=True))
        if not click.confirm("Are you sure you want to restore?"):
            click.echo("Restore cancelled.")
            return

    # Restore
    click.echo("Restoring database...")
    backup_manager.restore_backup(
        backup_path,
        restore_config=restore_config,
        drop_existing=True
    )

    click.echo(click.style("✓ Database restored successfully", fg="green"))


@db.command("backup-list")
@click.pass_context
def db_backup_list(ctx: click.Context) -> None:
    """List available backups."""
    from chantal.db.backup import DatabaseBackupManager

    backup_manager = DatabaseBackupManager(
        database_url=get_database_url(ctx),
        config_dir=ctx.obj["config_dir"]
    )

    backups = backup_manager.list_backups()

    if not backups:
        click.echo("No backups found.")
        return

    # Print table
    click.echo("Available Backups:")
    click.echo()
    click.echo(f"{'Backup File':<40} {'Date':<20} {'Size':>10} {'Packages':>10}")
    click.echo("-" * 85)

    for backup in backups:
        filename = Path(backup.backup_file).name
        date = backup.manifest.created_at.strftime("%Y-%m-%d %H:%M:%S")
        size = f"{backup.file_size_bytes / 1024 / 1024:.1f} MB"
        packages = backup.manifest.packages_count

        click.echo(f"{filename:<40} {date:<20} {size:>10} {packages:>10}")


@db.command("backup-verify")
@click.argument("backup_file", type=click.Path(exists=True))
@click.pass_context
def db_backup_verify(ctx: click.Context, backup_file: str) -> None:
    """Verify backup integrity."""
    from chantal.db.backup import DatabaseBackupManager

    backup_manager = DatabaseBackupManager(
        database_url=get_database_url(ctx),
        config_dir=ctx.obj["config_dir"]
    )

    try:
        info = backup_manager.verify_backup(Path(backup_file))

        click.echo(click.style("✓ Backup is valid", fg="green"))
        click.echo(f"  Created: {info.manifest.created_at}")
        click.echo(f"  Chantal Version: {info.manifest.chantal_version}")
        click.echo(f"  Packages: {info.manifest.packages_count}")
        click.echo(f"  Repositories: {info.manifest.repositories_count}")
        click.echo(f"  Snapshots: {info.manifest.snapshots_count}")
        click.echo(f"  Includes Config: {info.manifest.includes_config}")

    except ValueError as e:
        click.echo(click.style(f"✗ Backup is invalid: {e}", fg="red"))
        raise click.Abort()
```

### Backup Strategy Recommendations

#### Automated Daily Backups

```bash
# Add to crontab
0 3 * * * /usr/local/bin/chantal db backup --output /backups/chantal-$(date +\%Y\%m\%d).tar.gz

# Keep last 30 days of backups
0 4 * * * find /backups/chantal-*.tar.gz -mtime +30 -delete
```

#### Full System Backup (Database + Pool)

For complete disaster recovery, backup both database AND package pool:

```bash
#!/bin/bash
# /usr/local/bin/chantal-full-backup.sh

BACKUP_DATE=$(date +%Y%m%d)

# 1. Backup database
chantal db backup --output /backups/chantal-db-${BACKUP_DATE}.tar.gz

# 2. Backup package pool (using restic/borg/rsync)
# Option A: rsync to remote server
rsync -avz --delete /var/lib/chantal/pool/ backup-server:/backups/chantal-pool/

# Option B: borg backup (deduplicated, compressed)
borg create /mnt/backup-drive/chantal-pool::${BACKUP_DATE} /var/lib/chantal/pool/

# Option C: restic (cloud-compatible)
restic -r /mnt/backup-drive/chantal-pool backup /var/lib/chantal/pool/
```

---

## Priority for MVP

### HTTP Proxy Support

**MVP (High Priority):**
- ✅ Global proxy configuration
- ✅ Per-repository proxy override
- ✅ Environment variable support (`HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`)
- ✅ Basic authentication (username/password)
- ✅ SSL verification control

**Post-MVP (Low Priority):**
- SOCKS proxy support
- Proxy auto-detection (PAC files)
- Advanced proxy authentication (NTLM, Kerberos)

### Scheduler Service

**MVP (Medium Priority):**
- ✅ Built-in scheduler with cron expressions
- ✅ Per-repository scheduling
- ✅ Lock mechanism to prevent concurrent syncs
- ✅ Systemd service file
- ✅ `chantal scheduler start/stop/status` commands

**Post-MVP (Low Priority):**
- Web UI for schedule management
- Email notifications on sync failures
- Webhook support (notify external systems)
- Advanced scheduling (maintenance windows, dependency chains)
- Distributed scheduling (multi-node setups)

### Database Backup & Restore

**MVP (High Priority):**
- ✅ `chantal db backup` - Create database backup (tar.gz with manifest)
- ✅ `chantal db restore` - Restore from backup
- ✅ `chantal db backup-list` - List available backups
- ✅ `chantal db backup-verify` - Verify backup integrity
- ✅ Include config files in backup
- ✅ Backup manifest with metadata (version, timestamp, stats)
- ✅ Compression support (gzip)

**Post-MVP (Low Priority):**
- Incremental backups (only changed data)
- Backup encryption
- Cloud backup targets (S3, Azure Blob)
- Automatic backup retention policies
- Point-in-time recovery

---

## Implementation Plan

### Phase 1: HTTP Proxy Support (Week 2)

1. Add `ProxyConfig` Pydantic model
2. Implement `ProxyHTTPClient` class
3. Update `RPMPlugin` to use proxy client
4. Add proxy configuration to example configs
5. Test with corporate proxy
6. Documentation

**Estimate:** 3-4 days

### Phase 2: Scheduler Service (Week 10-11)

1. Add `ScheduleConfig` Pydantic model
2. Implement `SchedulerService` class
3. Implement `SyncLock` file locking
4. Add `chantal scheduler` CLI commands
5. Create systemd service file
6. Test scheduled syncs
7. Documentation

**Estimate:** 7-10 days

### Phase 3: Database Backup & Restore (Week 3-4)

1. Add `BackupManifest` and `BackupInfo` Pydantic models
2. Implement `DatabaseBackupManager` class
3. Add backup/restore CLI commands (`db backup`, `db restore`, `db backup-list`, `db backup-verify`)
4. Test backup creation and restoration
5. Test with PostgreSQL dump/restore
6. Documentation (including disaster recovery guide)

**Estimate:** 4-5 days

---

## Testing Scenarios

### Proxy Testing

```bash
# Test with global proxy
cat > /etc/chantal/config.yaml <<EOF
proxy:
  http_proxy: "http://proxy.example.com:8080"
  https_proxy: "http://proxy.example.com:8080"
EOF

chantal repo sync --repo-id test-repo --verbose
# Should show proxy being used in logs

# Test with authentication
cat > /etc/chantal/config.yaml <<EOF
proxy:
  http_proxy: "http://proxy.example.com:8080"
  username: "testuser"
  password: "testpass"
EOF

chantal repo sync --repo-id test-repo --verbose

# Test per-repo override
cat > /etc/chantal/conf.d/internal.yaml <<EOF
repositories:
  - id: internal-repo
    upstream_url: https://repo.internal.company.com/
    proxy:
      enabled: false  # Bypass proxy for internal repo
EOF

chantal repo sync --repo-id internal-repo --verbose
# Should NOT use proxy
```

### Scheduler Testing

```bash
# Test scheduler service
cat > /etc/chantal/conf.d/test.yaml <<EOF
repositories:
  - id: test-repo
    type: rpm
    upstream_url: https://example.com/repo
    schedule:
      enabled: true
      cron: "*/5 * * * *"  # Every 5 minutes (for testing)
      create_snapshot: true
EOF

# Start scheduler
chantal scheduler start

# Monitor logs
tail -f /var/log/chantal/scheduler.log

# Should sync every 5 minutes

# Test lock mechanism (run in two terminals simultaneously)
# Terminal 1:
chantal repo sync --repo-id test-repo

# Terminal 2 (while sync is running):
chantal repo sync --repo-id test-repo
# Should fail with "already being synced" error
```

### Database Backup/Restore Testing

```bash
# Test backup creation
chantal db backup --output /tmp/test-backup.tar.gz
# Verify backup was created
ls -lh /tmp/test-backup.tar.gz

# Verify backup integrity
chantal db backup-verify /tmp/test-backup.tar.gz
# Should show: ✓ Backup is valid

# List backups
chantal db backup-list
# Should show the backup in the list

# Test restore (WARNING: destructive!)
# 1. First, create a test database state
chantal repo sync --repo-id test-repo

# 2. Create backup
chantal db backup --output /tmp/before-changes.tar.gz

# 3. Make some changes
chantal repo sync --repo-id another-repo

# 4. Restore from backup
chantal db restore /tmp/before-changes.tar.gz
# Should prompt for confirmation
# Should restore database to previous state

# 5. Verify restoration
chantal repo list
# Should show state from before changes

# Test automated daily backups
# Add to crontab:
crontab -e
# Add line:
0 3 * * * /usr/local/bin/chantal db backup --output /backups/chantal-$(date +\%Y\%m\%d).tar.gz

# Test full system backup (database + pool)
# Create backup script
cat > /usr/local/bin/chantal-full-backup.sh <<'EOF'
#!/bin/bash
BACKUP_DATE=$(date +%Y%m%d)
chantal db backup --output /backups/chantal-db-${BACKUP_DATE}.tar.gz
rsync -avz /var/lib/chantal/pool/ backup-server:/backups/chantal-pool/
EOF
chmod +x /usr/local/bin/chantal-full-backup.sh

# Run backup
/usr/local/bin/chantal-full-backup.sh
```

---

**Next Steps:**
1. **Implement HTTP proxy support first** (Week 2) - needed for corporate environments
2. **Implement database backup/restore** (Week 3-4) - critical for disaster recovery
3. **Implement scheduler service later** (Week 10-11) - nice-to-have for automation
4. Update main architecture documentation with these features
5. Add to CLI commands documentation
