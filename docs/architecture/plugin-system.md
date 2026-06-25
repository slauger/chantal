# Plugin System

Chantal uses a plugin architecture to support different repository types (RPM, DEB/APT, Helm, Alpine APK).

## Overview

Each repository type requires two plugins:
1. **Sync Plugin** - Fetches and parses repository metadata, downloads packages
2. **Publisher Plugin** - Generates repository metadata, creates hardlinks

## Plugin Types

### Sync Plugin

Responsible for syncing packages from an upstream repository.

There is **no** abstract `SyncPlugin` base class. "Sync plugin" is a convention,
not an enforced interface: each sync plugin (`RpmSyncPlugin`, `AptSyncPlugin`,
`HelmSyncer`, `ApkSyncer`) is a plain class that follows the same shape.

**Convention:**

```python
class RpmSyncPlugin:  # inherits nothing
    def __init__(
        self,
        storage: StorageManager,
        config: RepositoryConfig,
        proxy_config: ProxyConfig | None = None,
        ssl_config: SSLConfig | None = None,
        cache: MetadataCache | None = None,
        output_level: OutputLevel = OutputLevel.NORMAL,
    ):
        ...

    def sync_repository(
        self,
        session: Session,
        repository: Repository,
    ) -> SyncResult:
        """Sync repository from upstream."""
        ...
```

Note that configuration is passed to `__init__`, **not** to `sync_repository()`.
`SyncResult` is a `@dataclass` defined in `chantal.plugins.rpm.sync` (the APT
plugin defines its own equivalently named `SyncResult` in
`chantal.plugins.apt.sync`).

**Responsibilities:**
- Fetch repository metadata (e.g., repomd.xml for RPM)
- Parse the package list
- Apply filters
- Download packages to the pool (and metadata files as `RepositoryFile`)
- Update the database

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

**File:** `src/chantal/plugins/rpm/sync.py`, `src/chantal/plugins/rpm/publisher.py`

### APT/DEB Plugin

**Status:** ✅ Available

**Sync Plugin:** `AptSyncPlugin`
- Fetches `InRelease` / `Release`
- Parses `Packages(.gz)`
- Downloads DEB packages

**Publisher Plugin:** `AptPublisher`
- Generates `Packages` indices and the `Release` file
- Signs metadata with GPG in filtered mode (`InRelease`, `Release.gpg`)

**File:** `src/chantal/plugins/apt/sync.py`, `src/chantal/plugins/apt/publisher.py`

### Helm & Alpine APK Plugins

**Status:** ✅ Available

- **Helm:** `HelmSyncer` / `HelmPublisher` - HTTP and OCI registries, `index.yaml`
- **APK:** `ApkSyncer` / `ApkPublisher` - `APKINDEX.tar.gz`, RSA index signing

## Plugin Dispatch

There is **no** plugin registry. `src/chantal/plugins/__init__.py` only re-exports
a few classes:

```python
# src/chantal/plugins/__init__.py
from chantal.plugins.base import PublisherPlugin
from chantal.plugins.rpm.publisher import RpmPublisher
from chantal.plugins.rpm.sync import RpmSyncPlugin

__all__ = ["PublisherPlugin", "RpmPublisher", "RpmSyncPlugin"]
```

Plugin selection is done with hardcoded `if/elif` branches on the repository type
inside the CLI command modules:

- **Sync dispatch:** `src/chantal/cli/repo_commands.py`
- **Publish dispatch:** `src/chantal/cli/publish_commands.py`

```python
# Sync dispatch (cli/repo_commands.py, simplified)
if repo_config.type == "rpm":
    sync_plugin = RpmSyncPlugin(storage=storage, config=repo_config, ...)
    result = sync_plugin.sync_repository(session, repository)
elif repo_config.type == "helm":
    helm_syncer = HelmSyncer(storage=storage, config=repo_config, ...)
    ...
elif repo_config.type == "apk":
    apk_syncer = ApkSyncer(storage=storage, config=repo_config, ...)
    ...
elif repo_config.type == "apt":
    apt_syncer = AptSyncPlugin(storage=storage, config=repo_config, ...)
    ...
else:
    raise click.ClickException(f"Unsupported repository type: {repo_config.type}")
```

```python
# Publish dispatch (cli/publish_commands.py, simplified)
if repo_config.type == "rpm":
    publisher = RpmPublisher(storage=storage)
elif repo_config.type == "helm":
    publisher = HelmPublisher(storage=storage)
elif repo_config.type == "apk":
    publisher = ApkPublisher(storage=storage)
elif repo_config.type == "apt":
    publisher = AptPublisher(storage=storage, config=repo_config)
else:
    raise click.ClickException(f"Unsupported repository type: {repo_config.type}")
```

## Creating a Custom Plugin

### 1. Implement a Sync Plugin

Follow the sync-plugin convention (a plain class — no base class to inherit):

```python
class MySyncPlugin:
    def __init__(self, storage, config, **kwargs):
        self.storage = storage
        self.config = config

    def sync_repository(self, session, repository) -> SyncResult:
        # 1. Fetch metadata from self.config.feed
        # 2. Parse the package list
        # 3. Apply filters
        # 4. For each package: storage.add_package(local_path, filename)
        # 5. Update the database (ContentItem rows + associations)
        ...
```

### 2. Implement a Publisher Plugin

```python
from chantal.plugins.base import PublisherPlugin

class MyPublisher(PublisherPlugin):
    def publish_repository(self, session, repository, config, target_path):
        # 1. Get content items (NOT .packages)
        packages = repository.content_items

        # 2. Create hardlinks from the pool (base-class helper)
        self._create_hardlinks(packages, target_path)

        # 3. Generate metadata
        self.generate_metadata(packages, target_path)

    def publish_snapshot(self, session, snapshot, repository, config, target_path):
        ...

    def unpublish(self, target_path):
        ...
```

### 3. Wire Up Dispatch

Add an `elif` branch for the new type in the sync/publish dispatch in
`src/chantal/cli/repo_commands.py` and `src/chantal/cli/publish_commands.py`.

### 4. Add Configuration Support

```python
# In src/chantal/core/config.py
class RepositoryConfig(BaseModel):
    type: Literal['rpm', 'apt', 'helm', 'apk', 'my_type']
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
5. Execute plugin.sync_repository(session, repository)
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

`StorageManager` is constructed from a `StorageConfig` (not a bare pool path).
`add_package()` operates on a **local** file that has already been downloaded — it
does not fetch from a URL — and returns `(sha256, pool_path, size_bytes)`.

```python
from chantal.core.storage import StorageManager

storage = StorageManager(config)  # config: StorageConfig

# Add a local package file to the pool (pool/content/...)
sha256, pool_path, size_bytes = storage.add_package(
    source_path, filename, verify_checksum=True
)

# Add a metadata/installer file to the pool (pool/files/...)
sha256, pool_path, size_bytes = storage.add_repository_file(source_path, filename)

# Create a hardlink from the pool to a publish target
storage.create_hardlink(sha256, filename, target_path)
```

### Downloading

Sync plugins download upstream files themselves via `DownloadManager`
(`chantal.core.downloader`), which is configured from the repository config plus
optional `ProxyConfig` / `SSLConfig`. There is no `chantal.plugins.http_client`
module.

### Filters

RPM filtering lives in `chantal.plugins.rpm.filters` and is applied by the sync
plugin against the parsed package metadata. There is no generic
`chantal.plugins.filters.FilterEngine`.

## Testing Plugins

### Unit Tests

```python
def test_rpm_sync_plugin():
    plugin = RpmSyncPlugin(storage=storage, config=config)

    result = plugin.sync_repository(session, repository)

    assert result.packages_downloaded > 0
    assert result.success is True
```

### Integration Tests

```python
def test_rpm_sync_and_publish():
    # Sync
    sync_plugin = RpmSyncPlugin(storage=storage, config=config)
    sync_plugin.sync_repository(session, repo)

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
