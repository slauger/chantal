# RPM Plugin

The RPM plugin provides support for DNF/YUM-based repositories (RHEL, CentOS, Fedora, Rocky Linux, AlmaLinux).

## Overview

**Status:** ✅ Available

The RPM plugin consists of:
- **RpmSyncPlugin** - Syncs packages from upstream RPM repositories
- **RpmPublisher** - Publishes RPM repositories with metadata

## Features

**Repository Modes:**
- ✅ **Mirror Mode** - Full metadata mirroring (all repomd.xml types)
- ✅ **Filtered Mode** - Smart metadata regeneration for filtered repos
- ✅ **Hosted Mode** - For self-hosted packages (future)

**Package Management:**
- ✅ Repomd.xml/primary.xml.gz parsing
- ✅ RPM package downloading
- ✅ SHA256 checksum verification
- ✅ Architecture filtering
- ✅ Pattern-based package filtering
- ✅ Source RPM exclusion
- ✅ Version filtering (only latest)

**Metadata Support:**
- ✅ Full metadata mirroring (updateinfo, filelists, other, comps, modules, etc.)
- ✅ Updateinfo/errata parsing and filtering
- ✅ Metadata regeneration for filtered repositories
- ✅ Gzip/XZ/BZ2 compression support
- ✅ RHEL CDN support (client certificates)

**Planned:**
- 🚧 Delta RPMs
- 🚧 GPG signature verification

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

## Repository Modes

Chantal supports three repository operation modes for RPM repositories:

### Mirror Mode (Default)

**Full metadata mirroring** - Downloads and publishes ALL metadata types from upstream repository unchanged.

```yaml
repositories:
  - id: rhel9-baseos-mirror
    name: RHEL 9 BaseOS (Full Mirror)
    type: rpm
    feed: https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os
    enabled: true
    mode: mirror  # Default
```

**Behavior:**
- ✅ All metadata files downloaded: updateinfo, filelists, other, comps, modules, etc.
- ✅ Metadata published unchanged (no filtering)
- ✅ Perfect 1:1 mirror of upstream repository
- ✅ Ideal for: Complete repository mirrors, compliance requirements

**Metadata types mirrored:**
- `primary` - Package metadata (name, version, arch, dependencies)
- `filelists` - File listings for each package
- `other` - Changelog data
- `updateinfo` - Errata/security advisories
- `comps` - Package groups and categories
- `modules` - Modular metadata (RHEL 8+)
- And any other metadata types present in repomd.xml

### Filtered Mode

**Smart filtering with metadata regeneration** - Filters packages and regenerates metadata to match.

```yaml
repositories:
  - id: epel9-webservers
    name: EPEL 9 - Web Servers Only
    type: rpm
    feed: https://dl.fedoraproject.org/pub/epel/9/Everything/x86_64/
    enabled: true
    mode: filtered
    filters:
      patterns:
        include: ["^nginx-.*", "^httpd-.*", "^php-.*"]
      post_processing:
        only_latest_version: true
```

**Behavior:**
- ✅ Packages filtered based on patterns/filters
- ✅ Metadata regenerated to match available packages
- ✅ Updateinfo filtered to include only relevant errata
- ✅ Filelists, other metadata filtered accordingly
- ✅ Ideal for: Custom repositories, filtered mirrors, disk space optimization

**Metadata regeneration:**
- `primary.xml` - Regenerated with filtered package list
- `filelists.xml` - Regenerated with filtered packages
- `other.xml` - Regenerated with filtered packages
- `updateinfo.xml` - **Filtered** to include only errata for available packages
- `comps.xml` - Copied unchanged (groups still valid)
- `modules.yaml` - Copied unchanged (if present)

**Updateinfo Filtering Example:**

Upstream has 1000 security advisories, but you only mirror nginx packages:
- **Mirror mode**: All 1000 advisories published (irrelevant for your packages)
- **Filtered mode**: Only nginx-related advisories published (smart filtering)

```python
# Filtered updateinfo only includes errata matching your packages
# RHSA-2024:1234 for nginx-1.20.1-1.el9 → INCLUDED
# RHSA-2024:5678 for kernel-5.14.0-362.el9 → EXCLUDED (kernel not mirrored)
```

### Hosted Mode

**Self-hosted packages** - For future use (uploading custom RPMs).

```yaml
repositories:
  - id: custom-rpms
    name: Custom Internal RPMs
    type: rpm
    mode: hosted
    enabled: true
```

**Status:** Planned feature for uploading custom-built RPMs.

## How It Works

### Sync Process

#### 1. Fetch repomd.xml
```
GET https://example.com/repo/repodata/repomd.xml
```
Parse repomd.xml to discover all metadata types:
- `primary` - Package metadata (required)
- `filelists` - File listings
- `other` - Changelog data
- `updateinfo` - Errata/advisories
- `comps` - Package groups
- `modules` - Modular metadata
- ... and any other types

#### 2. Download Metadata

**Mirror Mode:**
- Downloads ALL metadata types from repomd.xml
- Stores in pool: `/var/lib/chantal/pool/files/`
- Metadata tracked in `RepositoryFile` model

**Filtered Mode:**
- Downloads primary.xml (required for package discovery)
- Downloads updateinfo.xml (for errata filtering)
- Other metadata downloaded as needed

#### 3. Parse Packages

Fetch and parse `primary.xml.gz`:
```
GET https://example.com/repo/repodata/abc123-primary.xml.gz
```
Extract package list with metadata:
- Name, version, release, epoch, architecture
- Dependencies, provides, requires
- SHA256 checksum
- File location

#### 4. Apply Filters (Filtered Mode Only)

- Pattern matching (include/exclude regex)
- Architecture filtering
- Size/build time filtering
- RPM-specific filters (exclude source RPMs, etc.)
- Post-processing (only latest version)

**Mirror Mode:** No filtering applied.

#### 5. Download Packages

```
For each package:
  - Calculate expected SHA256
  - Check if exists in pool
  - If not, download to pool
  - Verify checksum
```

Pool structure:
```
/var/lib/chantal/pool/content/{sha256[0:2]}/{sha256[2:4]}/{sha256}.rpm
```

#### 6. Update Database

- Add packages to database (`ContentItem` model)
- Add metadata files to database (`RepositoryFile` model)
- Associate with repository
- Record sync history

### Publish Process

#### 1. Query Packages
```python
packages = repository.content_items
metadata_files = repository.repository_files  # Mirror mode only
```

#### 2. Create Directory Structure
```
/var/www/repos/repo-id/latest/
├── Packages/
└── repodata/
```

#### 3. Create Package Hardlinks
```
For each package:
  pool/content/f2/56/f256...rpm
    → /var/www/repos/repo-id/latest/Packages/nginx-1.20.2.rpm
```

Zero-copy publishing using hardlinks.

#### 4. Publish Metadata

**Mirror Mode:**
- Copy ALL metadata files from pool to `repodata/`
- Hardlinks: `pool/files/{sha256}.xml.gz` → `repodata/{type}.xml.gz`
- Copy `repomd.xml` unchanged
- Perfect 1:1 mirror

**Filtered Mode:**
- Generate `primary.xml` with filtered package list
- Generate `filelists.xml` with filtered packages
- Generate `other.xml` with filtered packages
- **Filter `updateinfo.xml`** to include only relevant errata
- Copy `comps.xml` unchanged (if present)
- Generate new `repomd.xml` with checksums

#### 5. Updateinfo Filtering (Filtered Mode)

Parse upstream updateinfo.xml:
```xml
<updates>
  <update type="security" id="RHSA-2024:1234">
    <title>nginx security update</title>
    <pkglist>
      <package name="nginx" version="1.20.1" release="1.el9" arch="x86_64"/>
    </pkglist>
  </update>
  <update type="security" id="RHSA-2024:5678">
    <title>kernel security update</title>
    <pkglist>
      <package name="kernel" version="5.14.0" release="362.el9" arch="x86_64"/>
    </pkglist>
  </update>
</updates>
```

Filter logic:
- Extract package NVRAs from each advisory
- Check if ANY package in advisory is in your filtered repository
- If yes: Include advisory in filtered updateinfo.xml
- If no: Exclude advisory

Result:
```xml
<updates>
  <update type="security" id="RHSA-2024:1234">
    <!-- nginx advisory INCLUDED (nginx is in filtered repo) -->
  </update>
  <!-- kernel advisory EXCLUDED (kernel not in filtered repo) -->
</updates>
```

#### 6. Result

**Mirror Mode:**
```
/var/www/repos/rhel9-baseos-mirror/latest/
├── Packages/
│   ├── nginx-1.20.2-1.el9.x86_64.rpm
│   ├── kernel-5.14.0-362.el9.x86_64.rpm
│   └── ... (all packages)
└── repodata/
    ├── repomd.xml
    ├── abc123-primary.xml.gz
    ├── def456-filelists.xml.gz
    ├── ghi789-other.xml.gz
    ├── jkl012-updateinfo.xml.gz
    ├── mno345-comps.xml.gz
    └── ... (all metadata types)
```

**Filtered Mode:**
```
/var/www/repos/epel9-webservers/latest/
├── Packages/
│   ├── nginx-1.20.2-1.el9.x86_64.rpm
│   └── httpd-2.4.51-1.el9.x86_64.rpm
└── repodata/
    ├── repomd.xml (regenerated)
    ├── abc123-primary.xml.gz (regenerated)
    ├── def456-filelists.xml.gz (regenerated)
    ├── ghi789-other.xml.gz (regenerated)
    └── jkl012-updateinfo.xml.gz (filtered)
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
