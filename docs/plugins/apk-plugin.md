# Alpine APK Plugin

The APK plugin provides support for Alpine Linux package repositories.

## Overview

**Status:** ✅ Available

The APK plugin consists of:
- **ApkSyncer** - Syncs packages from Alpine Linux repositories
- **ApkPublisher** - Publishes Alpine repositories with metadata

## Features

- ✅ APKINDEX.tar.gz parsing
- ✅ APK package downloading (.apk files)
- ✅ SHA1 checksum verification (with graceful handling of stale APKINDEX)
- ✅ SHA256 checksum verification (content-addressed storage)
- ✅ Pattern-based package filtering
- ✅ Version filtering (only latest)
- ✅ Metadata generation (APKINDEX.tar.gz)
- ✅ Package deduplication via content-addressed storage
- ✅ Snapshot support
- ✅ Multi-architecture support (x86_64, aarch64, armhf, armv7, x86)
- ✅ **Mirror Mode** - Byte-for-byte identical repositories with snapshot versioning
- 🚧 Package signing/verification - Planned

## Repository Modes

The APK plugin supports **mirror mode** for byte-for-byte identical repository copies.

### Mirror Mode (Default)

**Status:** ✅ Available

In mirror mode, Chantal stores the original `APKINDEX.tar.gz` metadata file in the content-addressed pool as a `RepositoryFile`. When publishing, the original metadata is hardlinked from the pool to the published directory.

**Benefits:**
- Byte-for-byte identical to upstream repository
- Snapshot versioning of metadata (track APKINDEX changes over time)
- Metadata deduplication across repositories and snapshots
- Historical tracking of metadata changes

**How it works:**

1. **Sync Process:**
   - Downloads APKINDEX.tar.gz from upstream
   - Stores APKINDEX.tar.gz in content-addressed pool by SHA256
   - Creates RepositoryFile database record
   - Links metadata to repository/snapshot

2. **Publish Process:**
   - Queries RepositoryFile for stored APKINDEX.tar.gz
   - Hardlinks original APKINDEX.tar.gz from pool to published directory
   - Creates hardlinks for all .apk package files
   - Result: Byte-for-byte identical copy of upstream

**Example:**

```yaml
repositories:
  - id: alpine-v3.19-main
    name: Alpine 3.19 Main
    type: apk
    feed: https://dl-cdn.alpinelinux.org/alpine/
    enabled: true
    apk:
      branch: v3.19
      repository: main
      architecture: x86_64
    # Mirror mode is automatic - no additional config needed
```

**Use Cases:**
- Offline/air-gapped environments requiring exact upstream mirrors
- Compliance requirements for unmodified upstream metadata
- Snapshot versioning for reproducible builds
- Bandwidth optimization (metadata reused across snapshots)

### Dynamic Generation Mode (Fallback)

If no `RepositoryFile` is found (e.g., for older repositories or filtered repositories), Chantal falls back to dynamic APKINDEX.tar.gz generation from database metadata.

This mode:
- Generates APKINDEX.tar.gz from ApkMetadata in database
- Allows filtered repositories (subset of packages)
- Supports post-processing (e.g., only latest versions)

**Note:** For filtered repositories (pattern-based package selection), dynamic generation is used automatically.

## Configuration

### Basic Alpine Repository

```yaml
repositories:
  - id: alpine-v3.19-main
    name: Alpine 3.19 Main
    type: apk
    feed: https://dl-cdn.alpinelinux.org/alpine/
    enabled: true
    apk:
      branch: v3.19
      repository: main
      architecture: x86_64
```

**Required APK Configuration:**
- `branch`: Alpine branch (v3.19, v3.18, v3.17, edge, etc.)
- `repository`: Repository type (main, community, testing)
- `architecture`: Architecture (x86_64, aarch64, armhf, armv7, x86)

### With Filters

```yaml
repositories:
  - id: alpine-v3.19-minimal
    name: Alpine 3.19 - Essential Packages
    type: apk
    feed: https://dl-cdn.alpinelinux.org/alpine/
    enabled: true
    apk:
      branch: v3.19
      repository: main
      architecture: x86_64
    filters:
      patterns:
        include: ["^alpine-base$", "^busybox$", "^musl$", "^libc-dev$"]
      post_processing:
        only_latest_version: true
```

### Multiple Architectures

Create separate repositories for each architecture:

```yaml
repositories:
  - id: alpine-v3.19-main-x86_64
    name: Alpine 3.19 Main (x86_64)
    type: apk
    feed: https://dl-cdn.alpinelinux.org/alpine/
    enabled: true
    apk:
      branch: v3.19
      repository: main
      architecture: x86_64

  - id: alpine-v3.19-main-aarch64
    name: Alpine 3.19 Main (aarch64)
    type: apk
    feed: https://dl-cdn.alpinelinux.org/alpine/
    enabled: true
    apk:
      branch: v3.19
      repository: main
      architecture: aarch64
```

## How It Works

### Sync Process

1. **Build APKINDEX URL**
   ```
   {feed}/{branch}/{repository}/{architecture}/APKINDEX.tar.gz
   Example: https://dl-cdn.alpinelinux.org/alpine/v3.19/main/x86_64/APKINDEX.tar.gz
   ```

2. **Fetch APKINDEX.tar.gz**
   - Download tar.gz archive
   - Extract APKINDEX file from archive
   - Parse package metadata

3. **Parse package metadata**
   - Package name, version, architecture
   - SHA1 checksum (from APKINDEX)
   - Size, description, dependencies
   - Provides, install_if, origin

4. **Apply filters**
   - Pattern matching (include/exclude regex)
   - Version filtering (only latest)

5. **Download packages**
   - Download .apk files to content-addressed pool
   - Verify SHA1 checksums (with graceful handling)
   - Calculate SHA256 for storage layer
   - Deduplicate identical packages

6. **Store metadata**
   - Create ContentItem records
   - Store APK metadata in database
   - Link packages to repository

**Note on SHA1 Checksums:** Alpine CDN sometimes serves updated packages while the APKINDEX still contains old SHA1 checksums. Chantal logs warnings for mismatches but continues syncing, as SHA256 verification in the storage layer provides integrity guarantees.

### Publish Process

1. **Query database** for packages in repository/snapshot
2. **Create directory structure** for published repository
   ```
   {branch}/{repository}/{architecture}/
   ```
3. **Create hardlinks** from pool to published directory
4. **Generate APKINDEX.tar.gz** with package metadata
5. **Set correct file permissions** for web server access

## Package Filtering

### Pattern Filters

Include specific packages by name:

```yaml
filters:
  patterns:
    include:
      - "^nginx$"           # Exact match: nginx package
      - "^python3-.*"       # All Python 3 packages
      - "^docker-.*"        # All Docker-related packages
```

Exclude packages by pattern:

```yaml
filters:
  patterns:
    exclude:
      - ".*-doc$"           # Exclude documentation packages
      - ".*-dev$"           # Exclude development packages
      - "^linux-firmware$"  # Exclude large firmware package
```

### Version Filtering

Keep only the latest version of each package:

```yaml
filters:
  post_processing:
    only_latest_version: true
```

This is useful for:
- Reducing storage usage
- Simplifying package selection
- Automatically staying current with upstream

**Note:** APK versions use `-rN` suffix for package releases (e.g., `1.2.3-r4`). The version filter properly handles this format.

## Common Use Cases

### Mirror Complete Alpine Branch

```yaml
repositories:
  - id: alpine-v3.19-main
    name: Alpine 3.19 Main
    type: apk
    feed: https://dl-cdn.alpinelinux.org/alpine/
    enabled: true
    apk:
      branch: v3.19
      repository: main
      architecture: x86_64
```

### Mirror Community Repository

```yaml
repositories:
  - id: alpine-v3.19-community
    name: Alpine 3.19 Community
    type: apk
    feed: https://dl-cdn.alpinelinux.org/alpine/
    enabled: true
    apk:
      branch: v3.19
      repository: community
      architecture: x86_64
```

### Mirror Edge (Rolling Release)

```yaml
repositories:
  - id: alpine-edge-main
    name: Alpine Edge Main
    type: apk
    feed: https://dl-cdn.alpinelinux.org/alpine/
    enabled: true
    apk:
      branch: edge
      repository: main
      architecture: x86_64
```

### Selective Mirroring (Container Base)

```yaml
repositories:
  - id: alpine-v3.19-container-base
    name: Alpine 3.19 - Container Base Packages
    type: apk
    feed: https://dl-cdn.alpinelinux.org/alpine/
    enabled: true
    apk:
      branch: v3.19
      repository: main
      architecture: x86_64
    filters:
      patterns:
        include:
          - "^alpine-base$"
          - "^alpine-baselayout$"
          - "^alpine-keys$"
          - "^apk-tools$"
          - "^busybox$"
          - "^ca-certificates$"
          - "^libc-utils$"
          - "^musl$"
          - "^ssl_client$"
      post_processing:
        only_latest_version: true
```

## Publishing Alpine Repositories

### Publish Latest Repository

```bash
chantal publish repo --repo-id alpine-v3.19-main
```

Published structure:
```
/var/www/repos/alpine-v3.19-main/latest/
└── v3.19/
    └── main/
        └── x86_64/
            ├── APKINDEX.tar.gz
            ├── alpine-base-3.19.0-r0.apk
            ├── busybox-1.36.1-r15.apk
            └── ...
```

### Publish Snapshot

```bash
chantal snapshot create --repo-id alpine-v3.19-main --name 2025-01-11
chantal publish snapshot --snapshot alpine-v3.19-main-2025-01-11
```

Published structure:
```
/var/www/repos/alpine-v3.19-main/snapshots/2025-01-11/
└── v3.19/
    └── main/
        └── x86_64/
            ├── APKINDEX.tar.gz
            └── *.apk
```

### Configure Alpine Linux Client

Point Alpine to your mirrored repository:

```bash
# Replace default repositories with mirror
cat > /etc/apk/repositories <<EOF
http://mirror.example.com/repos/alpine-v3.19-main/latest/v3.19/main
http://mirror.example.com/repos/alpine-v3.19-main/latest/v3.19/community
EOF

# Update package index
apk update

# Install packages
apk add nginx
```

### Configure Alpine with Snapshot

Use a specific snapshot for reproducible builds:

```bash
# Use snapshot repository
cat > /etc/apk/repositories <<EOF
http://mirror.example.com/repos/alpine-v3.19-main/snapshots/2025-01-11/v3.19/main
http://mirror.example.com/repos/alpine-v3.19-main/snapshots/2025-01-11/v3.19/community
EOF

# Update and install
apk update
apk add nginx
```

## Package Metadata

Chantal stores comprehensive metadata for each package:

- **name** - Package name
- **version** - Package version (with -rN release suffix)
- **architecture** - Package architecture
- **size** - Package size in bytes
- **installed_size** - Installed size in bytes
- **description** - Package description
- **url** - Project URL
- **license** - Package license
- **dependencies** - Runtime dependencies
- **provides** - Virtual packages provided
- **origin** - Origin package name
- **maintainer** - Package maintainer
- **build_time** - Build timestamp
- **checksum** - SHA1 checksum (from APKINDEX)

This metadata is:
- Stored in the database for querying
- Included in published APKINDEX.tar.gz
- Available via Chantal CLI commands

## Alpine-Specific Features

### Version Format

Alpine packages use semantic versioning with package releases:
```
{version}-r{release}
Examples:
- nginx-1.24.0-r15
- python3-3.11.6-r0
- musl-1.2.4-r2
```

The `-rN` suffix indicates the package release number (rebuild with same upstream version).

### Repository Types

Alpine has three repository types:
- **main** - Core packages, supported by Alpine team
- **community** - Community-maintained packages
- **testing** - Experimental/testing packages (not recommended for production)

### Alpine Branches

Alpine uses versioned branches:
- **v3.19** - Current stable (January 2025)
- **v3.18** - Previous stable
- **v3.17** - Older stable
- **edge** - Rolling release (latest development)

Each stable version is supported for ~2 years.

## Troubleshooting

### APKINDEX Not Found

```
Error: Failed to fetch APKINDEX.tar.gz
```

**Solutions:**
- Check feed URL is correct: `https://dl-cdn.alpinelinux.org/alpine/`
- Verify branch, repository, and architecture are valid
- Check network connectivity
- Try alternative mirror if main CDN is down

### SHA1 Checksum Warnings

```
Warning: SHA1 mismatch for package: expected Q1abc..., got Q1xyz...
```

**This is normal!** Alpine CDN sometimes has stale APKINDEX files. Chantal:
- Logs the warning for transparency
- Continues syncing with the actual package
- Verifies integrity with SHA256 in storage layer

If you see many warnings, the APKINDEX may be stale. The sync will still work correctly.

### No Packages After Filtering

```
Warning: Filtered out all packages, 0 remaining
```

**Solutions:**
- Check filter patterns are correct
- Verify you're not excluding everything
- Review `only_latest_version` setting

### Architecture Mismatch

```
Error: Package architecture 'aarch64' doesn't match configured 'x86_64'
```

**Solutions:**
- Ensure `apk.architecture` matches your target architecture
- Create separate repositories for different architectures
- Don't mix architectures in a single repository

## Integration with Docker

### Alpine Base Image Builds

Use mirrored repositories in Dockerfiles for reproducible builds:

```dockerfile
FROM alpine:3.19

# Use internal mirror
RUN echo "http://mirror.internal/repos/alpine-v3.19-main/snapshots/2025-01-11/v3.19/main" > /etc/apk/repositories && \
    echo "http://mirror.internal/repos/alpine-v3.19-community/snapshots/2025-01-11/v3.19/community" >> /etc/apk/repositories

# Install packages from snapshot
RUN apk update && apk add --no-cache \
    nginx \
    ca-certificates

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

### Multi-Architecture Builds

```yaml
# Configure repositories for different architectures
repositories:
  - id: alpine-v3.19-main-amd64
    type: apk
    feed: https://dl-cdn.alpinelinux.org/alpine/
    apk:
      branch: v3.19
      repository: main
      architecture: x86_64

  - id: alpine-v3.19-main-arm64
    type: apk
    feed: https://dl-cdn.alpinelinux.org/alpine/
    apk:
      branch: v3.19
      repository: main
      architecture: aarch64
```

## Best Practices

1. **Use snapshots for production** - Create dated snapshots for reproducible builds
2. **Mirror main and community** - Most Alpine installations need both
3. **Filter by patterns** - Only mirror packages you need to reduce storage
4. **Keep latest only** - Use `only_latest_version: true` for most use cases
5. **Regular syncing** - Schedule regular syncs to stay current (daily recommended)
6. **Ignore SHA1 warnings** - SHA1 mismatches are normal with Alpine CDN
7. **Document your mirrors** - Keep notes on which branches and architectures you mirror
8. **Test snapshots before production** - Test in staging before promoting

## Further Reading

- [Plugins Overview](overview.md) - Plugin architecture
- [Custom Plugins](custom-plugins.md) - Creating custom plugins
- [Repository Configuration](../configuration/repositories.md) - Repository settings
- [CLI Commands](../user-guide/cli-commands.md) - Command reference
- [Alpine Linux Documentation](https://wiki.alpinelinux.org/wiki/Alpine_Package_Keeper) - Official APK documentation
