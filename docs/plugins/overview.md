# Plugins Overview

Chantal's plugin architecture enables support for different repository types.

## What are Plugins?

Plugins extend Chantal to support different repository types: RPM, DEB/APT, Helm, and Alpine APK. Each repository type requires two types of plugins:

1. **Sync Plugin** - Downloads and stores packages from upstream
2. **Publisher Plugin** - Creates publishable repositories with correct metadata

## Available Plugins

| Plugin | Type | Status | Description |
|--------|------|--------|-------------|
| [RPM](rpm-plugin.md) | Sync + Publisher | ✅ Available | DNF/YUM repositories (RHEL, CentOS, Fedora) |
| [APT/DEB](apt-plugin.md) | Sync + Publisher | ✅ Available | Debian/Ubuntu APT repositories |
| [Helm](helm-plugin.md) | Sync + Publisher | ✅ Available | Kubernetes Helm chart repositories |
| [Alpine APK](apk-plugin.md) | Sync + Publisher | ✅ Available | Alpine Linux package repositories |

Additional package ecosystems are tracked on the [GitHub Issues](https://github.com/slauger/chantal/issues) tracker.

## Plugin Architecture

```
┌─────────────────────────────────────────┐
│         CLI Commands                     │
│  (chantal repo sync, publish, etc.)     │
└────────────────┬────────────────────────┘
                 │
┌────────────────▼────────────────────────┐
│        Plugin Manager                    │
│  - Plugin discovery                      │
│  - Plugin registration                   │
│  - Plugin execution                      │
└────────────────┬────────────────────────┘
                 │
        ┌────────┴────────┐
        ▼                 ▼
┌───────────────┐  ┌───────────────┐
│  Sync Plugin  │  │Publisher Plugin│
│               │  │                │
│ - Fetch       │  │ - Hardlinks    │
│ - Parse       │  │ - Metadata     │
│ - Filter      │  │ - Compress     │
│ - Download    │  │                │
└───────────────┘  └───────────────┘
```

## How Plugins Work

### Sync Plugin Workflow

1. **Fetch metadata** from upstream (e.g., `repomd.xml` for RPM)
2. **Parse package list** from metadata
3. **Apply filters** (architecture, patterns, etc.)
4. **Download packages** to content-addressed pool
5. **Update database** with package metadata

### Publisher Plugin Workflow

1. **Query database** for packages in repository
2. **Create directory structure** for published repository
3. **Create hardlinks** from pool to published directory
4. **Generate metadata** specific to repository type
5. **Compress metadata** files

## Plugin Types

### RPM Plugin

For DNF/YUM-based distributions (RHEL, CentOS, Fedora, Rocky, Alma).

**Features:**
- Repomd.xml/primary.xml.gz parsing
- RPM-specific filtering
- RHEL CDN support (client certificates)
- Modular repository support (modules.yaml)

**See:** [RPM Plugin Documentation](rpm-plugin.md)

### APT/DEB Plugin

For Debian/Ubuntu-based distributions.

**Features:**
- InRelease/Release parsing
- Packages(.gz) parsing and generation
- Multi-component and multi-architecture support
- RFC822-format metadata
- Mirror and filtered modes
- Content-addressed storage for .deb files

**See:** [APT Plugin Documentation](apt-plugin.md)

### Helm Plugin

For Kubernetes Helm chart repositories (HTTP `index.yaml` feeds; `oci://` charts
referenced by an upstream index can be ingested via the `helm` binary).

**See:** [Helm Plugin Documentation](helm-plugin.md)

### Alpine APK Plugin

For Alpine Linux package repositories.

**See:** [Alpine APK Plugin Documentation](apk-plugin.md)

## Creating Custom Plugins

See [Custom Plugins](custom-plugins.md) for detailed guide on creating your own plugins.

**Quick example:**

```python
from chantal.plugins.base import PublisherPlugin

class MyPublisher(PublisherPlugin):
    def publish_repository(self, session, repository, config, target_path):
        # Implement publish logic
        ...
```

`PublisherPlugin` (in `chantal.plugins.base`) is the only abstract base class.
Syncers are plain classes (e.g. `RpmSyncPlugin`, `HelmSyncer`); there is no
`SyncPlugin` base class.

## Plugin Configuration

Plugins are configured per-repository in YAML:

```yaml
repositories:
  - id: my-repo
    type: rpm  # Selects RPM plugin
    feed: https://example.com/repo
    # Plugin-specific options...
```

## Plugin Dispatch

There is no plugin registry. The repository `type` is dispatched with a hardcoded
`if/elif` chain in the CLI command modules — `src/chantal/cli/repo_commands.py`
(sync) and `src/chantal/cli/publish_commands.py` (publish):

```python
# src/chantal/cli/publish_commands.py
if repo_config.type == "rpm":
    ...
elif repo_config.type == "helm":
    ...
elif repo_config.type == "apk":
    ...
elif repo_config.type == "apt":
    ...
```

Adding a new type means extending those branches (and `RepositoryConfig.type` in
`src/chantal/core/config.py`).

## Plugin Best Practices

1. **Idempotent operations** - Safe to run multiple times
2. **Error handling** - Handle network errors gracefully
3. **Progress reporting** - Report progress for long operations
4. **Checksum verification** - Always verify package integrity
5. **Atomic updates** - Use temporary directories
6. **Cleanup** - Remove temporary files on failure
7. **Logging** - Log operations and errors

## Further Reading

- [RPM Plugin](rpm-plugin.md) - RPM/DNF/YUM support
- [APT Plugin](apt-plugin.md) - Debian/Ubuntu APT support
- [Helm Plugin](helm-plugin.md) - Kubernetes Helm charts
- [Alpine APK Plugin](apk-plugin.md) - Alpine Linux packages
- [Custom Plugins](custom-plugins.md) - Creating your own plugins
- [Plugin System Architecture](../architecture/plugin-system.md) - Technical details
