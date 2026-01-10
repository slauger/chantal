# Plugin System

Chantal uses a plugin architecture to support different repository types (RPM, DEB/APT, PyPI, etc.).

## Overview

Each repository type requires two plugins:
1. **Sync Plugin** - Fetches and parses repository metadata, downloads packages
2. **Publisher Plugin** - Generates repository metadata, creates hardlinks

## Plugin Types

### Sync Plugin

Responsible for syncing packages from upstream repository.

**Base interface:**

```python
from abc import ABC, abstractmethod

class SyncPlugin(ABC):
    @abstractmethod
    def sync(
        self,
        session: Session,
        repository: Repository,
        config: RepositoryConfig
    ) -> SyncResult:
        """Sync repository from upstream."""
        pass
```

**Responsibilities:**
- Fetch repository metadata (e.g., repomd.xml for RPM)
- Parse package list
- Apply filters
- Download packages to pool
- Update database

### Publisher Plugin

Responsible for publishing packages to target directory.

**Base interface:**

```python
from abc import ABC, abstractmethod

class PublisherPlugin(ABC):
    @abstractmethod
    def publish_repository(
        self,
        session: Session,
        repository: Repository,
        config: RepositoryConfig,
        target_path: Path
    ) -> None:
        """Publish repository to target directory."""
        pass

    @abstractmethod
    def publish_snapshot(
        self,
        session: Session,
        snapshot: Snapshot,
        repository: Repository,
        config: RepositoryConfig,
        target_path: Path
    ) -> None:
        """Publish snapshot to target directory."""
        pass
```

**Responsibilities:**
- Create hardlinks from pool to published directory
- Generate repository metadata
- Compress metadata files

## Available Plugins

### RPM Plugin

**Status:** ✅ Available

**Sync Plugin:** `RpmSyncPlugin`
- Fetches `repomd.xml`
- Parses `primary.xml.gz`
- Supports filters (architecture, patterns, post-processing)
- Downloads RPM packages
- Verifies SHA256 checksums

**Publisher Plugin:** `RpmPublisher`
- Generates `repomd.xml`
- Generates `primary.xml.gz`
- Creates hardlinks to pool
- Compresses metadata with gzip

**File:** `src/chantal/plugins/rpm.py`, `src/chantal/plugins/rpm_sync.py`

### DEB/APT Plugin

**Status:** 🚧 Planned

**Sync Plugin:** `DebSyncPlugin` (planned)
- Fetch `InRelease` / `Release`
- Parse `Packages.gz`
- Download DEB packages

**Publisher Plugin:** `DebPublisher` (planned)
- Generate `InRelease` / `Release`
- Generate `Packages.gz`
- Sign with GPG

**Challenges:**
- APT signatures must remain valid
- Complex metadata structure
- Multiple compression formats

### PyPI Plugin

**Status:** 🚧 Planned

**Sync Plugin:** `PypiSyncPlugin` (planned)
- Fetch simple index (HTML)
- Parse package links
- Download wheels and source distributions

**Publisher Plugin:** `PypiPublisher` (planned)
- Generate simple index HTML
- Generate JSON API (optional)

## Plugin Registration

Plugins are registered in the plugin registry:

```python
# src/chantal/plugins/__init__.py

SYNC_PLUGINS = {
    'rpm': RpmSyncPlugin,
    'apt': DebSyncPlugin,  # Future
    'pypi': PypiSyncPlugin,  # Future
}

PUBLISHER_PLUGINS = {
    'rpm': RpmPublisher,
    'apt': DebPublisher,  # Future
    'pypi': PypiPublisher,  # Future
}
```

## Creating a Custom Plugin

### 1. Implement Sync Plugin

```python
from chantal.plugins.base import SyncPlugin

class MySyncPlugin(SyncPlugin):
    def sync(self, session, repository, config):
        # 1. Fetch metadata
        metadata = self.fetch_metadata(config.feed)

        # 2. Parse package list
        packages = self.parse_packages(metadata)

        # 3. Apply filters
        filtered = self.apply_filters(packages, config.filters)

        # 4. Download packages
        for pkg in filtered:
            self.download_package(pkg)

        # 5. Update database
        self.update_database(session, repository, filtered)
```

### 2. Implement Publisher Plugin

```python
from chantal.plugins.base import PublisherPlugin

class MyPublisher(PublisherPlugin):
    def publish_repository(self, session, repository, config, target_path):
        # 1. Get packages
        packages = repository.packages

        # 2. Create hardlinks
        for pkg in packages:
            self.create_hardlink(pkg, target_path)

        # 3. Generate metadata
        self.generate_metadata(packages, target_path)
```

### 3. Register Plugin

```python
# In src/chantal/plugins/__init__.py
SYNC_PLUGINS['my_type'] = MySyncPlugin
PUBLISHER_PLUGINS['my_type'] = MyPublisher
```

### 4. Add Configuration Support

```python
# In src/chantal/core/config.py
class RepositoryConfig(BaseModel):
    type: Literal['rpm', 'apt', 'pypi', 'my_type']
```

## Plugin Lifecycle

### Sync Lifecycle

```
1. User: chantal repo sync --repo-id example
       ↓
2. Load configuration (config.yaml)
       ↓
3. Identify repository type (e.g., "rpm")
       ↓
4. Load sync plugin (RpmSyncPlugin)
       ↓
5. Execute plugin.sync()
       ↓
6. Plugin fetches metadata
       ↓
7. Plugin parses packages
       ↓
8. Plugin applies filters
       ↓
9. Plugin downloads packages to pool
       ↓
10. Plugin updates database
```

### Publish Lifecycle

```
1. User: chantal publish repo --repo-id example
       ↓
2. Load configuration
       ↓
3. Query database for packages
       ↓
4. Identify repository type
       ↓
5. Load publisher plugin (RpmPublisher)
       ↓
6. Execute plugin.publish_repository()
       ↓
7. Plugin creates hardlinks
       ↓
8. Plugin generates metadata
       ↓
9. Plugin compresses metadata
```

## Plugin Helpers

Common functionality shared across plugins:

### StorageManager

```python
from chantal.core.storage import StorageManager

storage = StorageManager(pool_path)

# Add package to pool
pool_path = storage.add_package(url, sha256, filename)

# Create hardlink
storage.create_hardlink(sha256, filename, target_path)
```

### HTTP Client

```python
from chantal.plugins.http_client import HttpClient

client = HttpClient(proxy_config, ssl_config)

# Fetch URL
response = client.get(url)

# Download file
client.download_file(url, target_path)
```

### Filter Engine

```python
from chantal.plugins.filters import FilterEngine

engine = FilterEngine(filter_config)

# Apply filters
filtered_packages = engine.apply(packages)
```

## Testing Plugins

### Unit Tests

```python
def test_rpm_sync_plugin():
    plugin = RpmSyncPlugin(storage_manager)

    result = plugin.sync(session, repository, config)

    assert result.packages_downloaded > 0
    assert result.status == "success"
```

### Integration Tests

```python
def test_rpm_sync_and_publish():
    # Sync
    sync_plugin = RpmSyncPlugin(storage)
    sync_plugin.sync(session, repo, config)

    # Publish
    pub_plugin = RpmPublisher(storage)
    pub_plugin.publish_repository(session, repo, config, target_path)

    # Verify
    assert (target_path / "repodata" / "repomd.xml").exists()
```

## Best Practices

1. **Idempotent operations**: Plugins should be safe to run multiple times
2. **Error handling**: Always handle network errors, invalid metadata, etc.
3. **Progress reporting**: Report progress for long operations
4. **Checksum verification**: Always verify package checksums
5. **Atomic updates**: Use temporary directories, then atomic rename
6. **Cleanup**: Remove temporary files on failure
7. **Logging**: Log important operations and errors

## Future Enhancements

1. **Plugin discovery**: Auto-discover plugins in `plugins/` directory
2. **Plugin configuration**: Per-plugin configuration options
3. **Plugin versioning**: Support multiple versions of same plugin
4. **Plugin dependencies**: Declare dependencies between plugins
5. **Plugin hooks**: Pre/post sync hooks for custom logic
