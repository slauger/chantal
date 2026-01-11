# Plugins Overview

Chantal's plugin architecture enables support for different repository types.

## What are Plugins?

Plugins extend Chantal to support different repository types like RPM, DEB/APT, PyPI, etc. Each repository type requires two types of plugins:

1. **Sync Plugin** - Downloads and stores packages from upstream
2. **Publisher Plugin** - Creates publishable repositories with correct metadata

## Available Plugins

| Plugin | Type | Status | Description |
|--------|------|--------|-------------|
| [RPM](rpm-plugin.md) | Sync + Publisher | ✅ Available | DNF/YUM repositories (RHEL, CentOS, Fedora) |
| [Helm](helm-plugin.md) | Sync + Publisher | ✅ Available | Kubernetes Helm chart repositories |
| [Alpine APK](apk-plugin.md) | Sync + Publisher | ✅ Available | Alpine Linux package repositories |
| DEB/APT | Sync + Publisher | 🚧 Planned | Debian/Ubuntu repositories |
| PyPI | Sync + Publisher | 🚧 Planned | Python Package Index |

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
- Modular repository support (future)

**See:** [RPM Plugin Documentation](rpm-plugin.md)

### DEB/APT Plugin (Planned)

For Debian/Ubuntu-based distributions.

**Planned features:**
- InRelease/Release parsing
- Packages.gz generation
- GPG signature support
- Multi-architecture support

### PyPI Plugin (Planned)

For Python Package Index mirroring.

**Planned features:**
- Simple Index API (PEP 503)
- Wheel and source distribution support
- JSON API generation
- Requirements.txt filtering

## Creating Custom Plugins

See [Custom Plugins](custom-plugins.md) for detailed guide on creating your own plugins.

**Quick example:**

```python
from chantal.plugins.base import SyncPlugin

class MyPlugin(SyncPlugin):
    def sync(self, session, repository, config):
        # Implement sync logic
        pass
```

## Plugin Configuration

Plugins are configured per-repository in YAML:

```yaml
repositories:
  - id: my-repo
    type: rpm  # Selects RPM plugin
    feed: https://example.com/repo
    # Plugin-specific options...
```

## Plugin Registry

Plugins are registered in `src/chantal/plugins/__init__.py`:

```python
SYNC_PLUGINS = {
    'rpm': RpmSyncPlugin,
    # Add new plugins here
}

PUBLISHER_PLUGINS = {
    'rpm': RpmPublisher,
    # Add new plugins here
}
```

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
- [Custom Plugins](custom-plugins.md) - Creating your own plugins
- [Plugin System Architecture](../architecture/plugin-system.md) - Technical details
