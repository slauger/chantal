# RPM Plugin

The RPM plugin provides support for DNF/YUM-based repositories (RHEL, CentOS, Fedora, Rocky Linux, AlmaLinux).

## Overview

**Status:** ✅ Available

The RPM plugin consists of:
- **RpmSyncPlugin** - Syncs packages from upstream RPM repositories
- **RpmPublisher** - Publishes RPM repositories with metadata

## Features

- ✅ Repomd.xml/primary.xml.gz parsing
- ✅ RPM package downloading
- ✅ SHA256 checksum verification
- ✅ Architecture filtering
- ✅ Pattern-based package filtering
- ✅ Source RPM exclusion
- ✅ Version filtering (only latest)
- ✅ RHEL CDN support (client certificates)
- ✅ Metadata generation (repomd.xml, primary.xml.gz)
- ✅ Gzip/XZ compression support
- 🚧 Modular repositories (modules.yaml) - Planned
- 🚧 Delta RPMs - Planned
- 🚧 GPG signature verification - Planned

## Configuration

### Basic RPM Repository

```yaml
repositories:
  - id: epel9-latest
    name: EPEL 9 - Latest
    type: rpm
    feed: https://dl.fedoraproject.org/pub/epel/9/Everything/x86_64/
    enabled: true
```

### With Filters

```yaml
repositories:
  - id: epel9-webservers
    name: EPEL 9 - Web Servers
    type: rpm
    feed: https://dl.fedoraproject.org/pub/epel/9/Everything/x86_64/
    enabled: true
    filters:
      patterns:
        include: ["^nginx-.*", "^httpd-.*"]
        exclude: [".*-debug.*"]
      metadata:
        architectures:
          include: ["x86_64", "noarch"]
      rpm:
        exclude_source_rpms: true
      post_processing:
        only_latest_version: true
```

### RHEL with Client Certificates

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

## How It Works

### Sync Process

1. **Fetch repomd.xml**
   ```
   GET https://example.com/repo/repodata/repomd.xml
   ```
   Parse to find primary.xml.gz location

2. **Fetch primary.xml.gz**
   ```
   GET https://example.com/repo/repodata/abc123-primary.xml.gz
   ```
   Decompress and parse package list

3. **Apply filters**
   - Pattern matching (include/exclude regex)
   - Architecture filtering
   - Size/build time filtering
   - RPM-specific filters (exclude source RPMs, etc.)
   - Post-processing (only latest version)

4. **Download packages**
   ```
   For each package:
     - Calculate expected SHA256
     - Check if exists in pool
     - If not, download to pool
     - Verify checksum
   ```

5. **Update database**
   - Add packages to database
   - Associate with repository
   - Record sync history

### Publish Process

1. **Query packages**
   ```python
   packages = repository.packages
   ```

2. **Create directory structure**
   ```
   published/repo-id/latest/
   ├── Packages/
   └── repodata/
   ```

3. **Create hardlinks**
   ```
   For each package:
     pool/f2/56/f256...rpm
       → published/repo-id/latest/Packages/nginx-1.20.2.rpm
   ```

4. **Generate metadata**
   - Create `primary.xml` with package metadata
   - Compress to `primary.xml.gz`
   - Generate `repomd.xml` with checksums
   - Calculate and add checksums

5. **Result**
   ```
   published/repo-id/latest/
   ├── Packages/
   │   ├── nginx-1.20.2-1.el9.x86_64.rpm
   │   └── httpd-2.4.51-1.el9.x86_64.rpm
   └── repodata/
       ├── repomd.xml
       └── abc123-primary.xml.gz
   ```

## Metadata Files

### repomd.xml

Root metadata file:

```xml
<?xml version="1.0"?>
<repomd xmlns="http://linux.duke.edu/metadata/repo">
  <revision>1641816000</revision>
  <data type="primary">
    <checksum type="sha256">abc123...</checksum>
    <location href="repodata/abc123-primary.xml.gz"/>
    <timestamp>1641816000</timestamp>
    <size>12345</size>
    <open-checksum type="sha256">def456...</open-checksum>
    <open-size>67890</open-size>
  </data>
</repomd>
```

### primary.xml.gz

Package list (gzip-compressed):

```xml
<?xml version="1.0"?>
<metadata packages="2">
  <package type="rpm">
    <name>nginx</name>
    <arch>x86_64</arch>
    <version epoch="0" ver="1.20.2" rel="1.el9"/>
    <checksum type="sha256" pkgid="YES">f256abc...</checksum>
    <summary>High performance web server</summary>
    <description>...</description>
    <packager>...</packager>
    <url>...</url>
    <time file="1641816000" build="1641815000"/>
    <size package="1234567" installed="4567890" archive="1234000"/>
    <location href="Packages/nginx-1.20.2-1.el9.x86_64.rpm"/>
    <format>
      <rpm:license>BSD</rpm:license>
      <rpm:vendor>EPEL</rpm:vendor>
      <rpm:group>System Environment/Daemons</rpm:group>
      <rpm:buildhost>buildvm.example.com</rpm:buildhost>
      <rpm:sourcerpm>nginx-1.20.2-1.el9.src.rpm</rpm:sourcerpm>
      <rpm:provides>...</rpm:provides>
      <rpm:requires>...</rpm:requires>
    </format>
  </package>
</metadata>
```

## RPM-Specific Filters

### Exclude Source RPMs

```yaml
filters:
  rpm:
    exclude_source_rpms: true
```

Excludes packages ending with `.src.rpm`.

### Group Filtering

```yaml
filters:
  rpm:
    groups:
      include:
        - "System Environment/Base"
        - "Applications/Internet"
```

Filter by RPM group metadata.

### License Filtering

```yaml
filters:
  rpm:
    licenses:
      include: ["GPL", "MIT", "Apache"]
```

Filter by package license.

## Supported Distributions

### Red Hat Enterprise Linux (RHEL)

- RHEL 8, 9
- Requires subscription and client certificates

**Example:**
```yaml
repositories:
  - id: rhel9-baseos
    type: rpm
    feed: https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os
    ssl:
      client_cert: /etc/pki/entitlement/xxx.pem
      client_key: /etc/pki/entitlement/xxx-key.pem
```

### CentOS Stream

- CentOS Stream 8, 9

**Example:**
```yaml
repositories:
  - id: centos-stream-9-baseos
    type: rpm
    feed: https://mirror.stream.centos.org/9-stream/BaseOS/x86_64/os/
```

### Fedora

- Fedora 38, 39, 40+

**Example:**
```yaml
repositories:
  - id: fedora-40-everything
    type: rpm
    feed: https://download.fedoraproject.org/pub/fedora/linux/releases/40/Everything/x86_64/os/
```

### EPEL (Extra Packages for Enterprise Linux)

- EPEL 8, 9

**Example:**
```yaml
repositories:
  - id: epel9-everything
    type: rpm
    feed: https://dl.fedoraproject.org/pub/epel/9/Everything/x86_64/
```

### Rocky Linux

- Rocky Linux 8, 9

**Example:**
```yaml
repositories:
  - id: rocky9-baseos
    type: rpm
    feed: https://dl.rockylinux.org/pub/rocky/9/BaseOS/x86_64/os/
```

### AlmaLinux

- AlmaLinux 8, 9

**Example:**
```yaml
repositories:
  - id: alma9-baseos
    type: rpm
    feed: https://repo.almalinux.org/almalinux/9/BaseOS/x86_64/os/
```

## Troubleshooting

### Metadata Not Found

```
Error: Failed to fetch repomd.xml
```

**Solutions:**
- Check feed URL is correct
- Ensure URL ends with `/` (e.g., `.../os/` not `.../os`)
- Verify network connectivity
- Check SSL certificates if using HTTPS

### Checksum Mismatch

```
Error: SHA256 checksum mismatch for package
```

**Solutions:**
- Corrupted download - retry sync
- Upstream changed package without updating metadata
- Network issue - check connection

### No Packages After Filtering

```
Warning: Filtered out all packages, 0 remaining
```

**Solutions:**
- Check filter patterns are correct
- Verify architecture filter includes needed architectures
- Review `only_latest_version` setting

## Future Enhancements

- **Modular repositories** - Support for modules.yaml
- **Delta RPMs** - Download only package deltas
- **GPG verification** - Verify package signatures
- **Comps.xml** - Package group metadata
- **Updateinfo.xml** - Security/bug fix advisories
- **Filelists.xml** - File listings for packages
