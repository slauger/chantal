# Package Filters

Chantal provides comprehensive package filtering to selectively mirror repository content.

## Filter Types

Filters are applied in this order:

1. **Pattern filters** (regex on package names)
2. **Metadata filters** (architecture, size, build time)
3. **Repository-type filters** (RPM-specific, APT-specific)
4. **Post-processing** (only latest version, etc.)

## Pattern-Based Filtering

Filter packages by name using regular expressions:

```yaml
repositories:
  - id: epel9-webservers
    type: rpm
    feed: https://dl.fedoraproject.org/pub/epel/9/Everything/x86_64/
    filters:
      patterns:
        include: ["^nginx-.*", "^httpd-.*"]
        exclude: [".*-debug.*", ".*-devel$"]
```

### Include Patterns

Only sync packages matching these patterns:

```yaml
filters:
  patterns:
    include:
      - "^vim-.*"      # All vim packages
      - "^kernel-.*"   # All kernel packages
      - "^nginx-.*"    # All nginx packages
```

**Behavior:**
- If `include` is specified, **only** matching packages are synced
- Multiple patterns are OR'ed together
- Uses Python regex syntax

### Exclude Patterns

Exclude packages matching these patterns:

```yaml
filters:
  patterns:
    exclude:
      - ".*-debug.*"        # Exclude debug packages
      - ".*-debuginfo$"     # Exclude debuginfo
      - ".*-debugsource$"   # Exclude debugsource
      - ".*-devel$"         # Exclude development packages
```

**Behavior:**
- Applied **after** include patterns
- Removes packages from the filtered list
- Multiple patterns are OR'ed together

### Combined Example

```yaml
filters:
  patterns:
    include:
      - "^kernel-.*"
      - "^kernel-modules-.*"
    exclude:
      - ".*-debug.*"
      - ".*-debuginfo$"
      - ".*-debugsource$"
```

**Result:**
- Includes: `kernel-5.14.0-360.el9.x86_64.rpm`
- Excludes: `kernel-debuginfo-5.14.0-360.el9.x86_64.rpm`

## Metadata Filters

Filter by package metadata:

```yaml
filters:
  metadata:
    architectures:
      include: ["x86_64", "noarch"]
      # exclude: ["i686"]  # Alternative: exclude specific arches

    size:
      min_bytes: 1024         # Minimum 1 KB
      max_bytes: 1073741824   # Maximum 1 GB

    build_time:
      after: "2024-01-01T00:00:00Z"
      before: "2025-01-01T00:00:00Z"
```

### Architecture Filtering

Most common filter - select specific architectures:

```yaml
filters:
  metadata:
    architectures:
      include: ["x86_64", "noarch"]
```

**Common architectures:**
- `x86_64` - 64-bit Intel/AMD
- `aarch64` - 64-bit ARM
- `noarch` - Architecture-independent
- `i686` - 32-bit Intel/AMD
- `ppc64le` - 64-bit PowerPC Little Endian
- `s390x` - IBM Z Systems

### Size Filtering

Filter by package size:

```yaml
filters:
  metadata:
    size:
      min_bytes: 1024         # At least 1 KB
      max_bytes: 104857600    # At most 100 MB
```

**Use cases:**
- Exclude very small packages (metadata-only)
- Exclude very large packages (kernel-devel, etc.)
- Bandwidth-constrained environments

### Build Time Filtering

Filter by package build time:

```yaml
filters:
  metadata:
    build_time:
      after: "2024-01-01T00:00:00Z"    # Only packages built after this
      before: "2025-01-01T00:00:00Z"   # Only packages built before this
```

**Use cases:**
- Only sync recent packages
- Create historical snapshots
- Exclude outdated packages

## RPM-Specific Filters

Filters specific to RPM repositories:

```yaml
filters:
  rpm:
    exclude_source_rpms: true

    groups:
      include: ["System Environment/Base"]
      # exclude: ["Development/Tools"]

    licenses:
      include: ["GPL", "MIT", "Apache"]
      # exclude: ["Proprietary"]
```

### Exclude Source RPMs

Most common RPM filter - exclude `.src.rpm` files:

```yaml
filters:
  rpm:
    exclude_source_rpms: true
```

**Result:**
- Excludes: `kernel-5.14.0-360.el9.src.rpm`
- Includes: `kernel-5.14.0-360.el9.x86_64.rpm`

### Group Filtering

Filter by RPM group:

```yaml
filters:
  rpm:
    groups:
      include:
        - "System Environment/Base"
        - "System Environment/Daemons"
        - "Applications/Internet"
```

**Common groups:**
- `System Environment/Base`
- `System Environment/Daemons`
- `Applications/Internet`
- `Development/Tools`
- `Development/Libraries`

### License Filtering

Filter by package license:

```yaml
filters:
  rpm:
    licenses:
      include: ["GPL", "GPLv2", "GPLv3", "MIT", "Apache"]
```

**Use cases:**
- Only mirror open-source packages
- Exclude proprietary software
- Compliance requirements

## Post-Processing

Applied **after** all other filters:

```yaml
filters:
  post_processing:
    only_latest_version: true
    # only_latest_n_versions: 3  # Future feature
```

### Only Latest Version

Keep only the latest version of each package:

```yaml
filters:
  post_processing:
    only_latest_version: true
```

**Example:**
```
Before:
  vim-enhanced-9.0.2120-1.el9.x86_64.rpm
  vim-enhanced-9.0.2153-1.el9.x86_64.rpm
  vim-enhanced-9.0.2190-1.el9.x86_64.rpm

After:
  vim-enhanced-9.0.2190-1.el9.x86_64.rpm  (latest only)
```

**Grouping:**
- Groups by (name, architecture)
- Compares versions using RPM version comparison
- Considers Epoch, Version, Release

### Only Latest N Versions

Keep the last N versions (future feature):

```yaml
filters:
  post_processing:
    only_latest_n_versions: 3
```

## Complete Examples

### Example 1: Web Server Packages Only

```yaml
repositories:
  - id: rhel9-appstream-webservers
    name: RHEL 9 AppStream - Web Servers
    type: rpm
    feed: https://cdn.redhat.com/content/dist/rhel9/9/x86_64/appstream/os
    filters:
      patterns:
        include:
          - "^nginx-.*"
          - "^httpd-.*"
          - "^mod_.*"
          - "^php-.*"
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

### Example 2: Minimal Base System

```yaml
repositories:
  - id: rhel9-baseos-minimal
    name: RHEL 9 BaseOS - Minimal
    type: rpm
    feed: https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os
    filters:
      patterns:
        include:
          - "^basesystem$"
          - "^bash$"
          - "^coreutils$"
          - "^systemd$"
          - "^kernel$"
      metadata:
        architectures:
          include: ["x86_64", "noarch"]
      rpm:
        exclude_source_rpms: true
      post_processing:
        only_latest_version: true
```

### Example 3: Security Updates Only

```yaml
repositories:
  - id: rhel9-baseos-security
    name: RHEL 9 BaseOS - Security Updates
    type: rpm
    feed: https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os
    filters:
      metadata:
        build_time:
          after: "2025-01-01T00:00:00Z"  # Only recent packages
        architectures:
          include: ["x86_64", "noarch"]
      rpm:
        exclude_source_rpms: true
      post_processing:
        only_latest_version: true
```

### Example 4: Development Tools

```yaml
repositories:
  - id: epel9-development
    name: EPEL 9 - Development Tools
    type: rpm
    feed: https://dl.fedoraproject.org/pub/epel/9/Everything/x86_64/
    filters:
      patterns:
        include:
          - "^git-.*"
          - "^gcc-.*"
          - "^make$"
          - "^cmake$"
          - "^python3-.*"
      metadata:
        architectures:
          include: ["x86_64", "noarch"]
      rpm:
        exclude_source_rpms: false  # Include source RPMs for development
      post_processing:
        only_latest_version: true
```

## Filter Debugging

### Dry-Run Mode

Test filters without downloading:

```bash
# Future feature
chantal repo sync --repo-id epel9-webservers --dry-run
```

### Verbose Output

See which packages are filtered and why:

```bash
# Future feature
chantal repo sync --repo-id epel9-webservers --verbose
```

## Best Practices

1. **Start broad, refine narrow**: Begin with architecture filters, add specific patterns later
2. **Exclude debug packages**: Almost always exclude `-debug`, `-debuginfo`, `-debugsource`
3. **Exclude source RPMs**: Set `exclude_source_rpms: true` unless you need them
4. **Use latest version**: Enable `only_latest_version` for most use cases
5. **Test filters**: Use dry-run to verify filters before syncing
6. **Document why**: Add comments explaining filter choices
