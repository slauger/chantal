# APT Plugin

The APT plugin provides support for Debian/Ubuntu APT repositories.

## Overview

**Status:** ✅ Available (v0.2.0)

The APT plugin consists of:
- **AptSyncPlugin** - Syncs packages from upstream APT repositories
- **AptPublisher** - Publishes APT repositories with Debian-compliant metadata

## Features

**Repository Modes:**
- ✅ **Mirror Mode** - Full metadata mirroring (InRelease, Release, Packages)
- ✅ **Filtered Mode** - Smart metadata regeneration for filtered repos (with optional GPG signing)
- ⏳ **Hosted Mode** - For self-hosted packages (future)

**Package Management:**
- ✅ InRelease/Release file parsing
- ✅ Packages(.gz) parsing
- ✅ DEB package downloading
- ✅ SHA256/SHA1/MD5 checksum verification
- ✅ Architecture filtering (amd64, arm64, armhf, i386, all, etc.)
- ✅ Component filtering (main, contrib, non-free, etc.)
- ✅ Pattern-based package filtering
- ✅ Source package exclusion
- ✅ Version filtering (only latest)

**Metadata Support:**
- ✅ RFC822-format Packages file generation
- ✅ Release file generation with MD5/SHA1/SHA256 checksums
- ✅ InRelease file preservation (GPG-signed)
- ✅ GPG signature generation for filtered mode (InRelease, Release.gpg)
- ✅ Multi-component and multi-architecture layouts
- ✅ Configurable Packages index compression (gzip, zstandard, bzip2, none)
- ✅ Dependency metadata (Depends, Recommends, Suggests, Conflicts, etc.)

**Planned:**
- 🚧 Translation files (i18n)
- 🚧 Contents indices
- 🚧 diff/Index support
- 🚧 Source package syncing

## Configuration

### Basic APT Repository

```yaml
repositories:
  - id: ubuntu-jammy-main
    name: Ubuntu 22.04 Jammy - Main
    type: apt
    feed: http://archive.ubuntu.com/ubuntu
    enabled: true

    apt:
      distribution: jammy
      components:
        - main
      architectures:
        - amd64
```

### Multi-Component Repository

```yaml
repositories:
  - id: ubuntu-jammy-full
    name: Ubuntu 22.04 Jammy - Full
    type: apt
    feed: http://archive.ubuntu.com/ubuntu
    enabled: true

    apt:
      distribution: jammy
      components:
        - main
        - restricted
        - universe
        - multiverse
      architectures:
        - amd64
        - arm64
```

### Mirror Mode (Exact Copy)

```yaml
repositories:
  - id: debian-bookworm-mirror
    name: Debian 12 Bookworm - Mirror
    type: apt
    feed: http://deb.debian.org/debian
    enabled: true
    mode: mirror

    apt:
      distribution: bookworm
      components:
        - main
        - contrib
        - non-free
      architectures:
        - amd64
```

### With Authentication

```yaml
repositories:
  - id: private-apt-repo
    name: Private APT Repository
    type: apt
    feed: https://apt.example.com/debian
    enabled: true

    apt:
      distribution: stable
      components:
        - main
      architectures:
        - amd64

    auth:
      basic:
        username: myuser
        password: mypassword
```

## APT-Specific Options

The `apt` section in repository configuration supports these options:

### Required Options

- **`distribution`** (string) - APT distribution/suite name
  - Examples: `jammy`, `focal`, `bookworm`, `bullseye`, `stable`
  - Used in the URL: `dists/{distribution}/`

- **`components`** (list) - Repository components to sync
  - Examples: `main`, `restricted`, `universe`, `multiverse` (Ubuntu)
  - Examples: `main`, `contrib`, `non-free`, `non-free-firmware` (Debian)
  - Examples: `stable`, `edge`, `testing` (third-party repos)

- **`architectures`** (list) - Architectures to sync
  - Common: `amd64`, `arm64`, `armhf`, `i386`, `all`
  - Special: `source` (for source packages, requires `include_source_packages: true`)

### Optional Options

- **`include_source_packages`** (boolean, default: false)
  - Whether to sync source packages (.dsc, .tar.gz, etc.)
  - Note: Source packages are stored separately and require significant space

- **`flat_repository`** (boolean, default: false)
  - Support for flat repositories (no dists/ structure)
  - Rare, used by some very old repositories

## Metadata Compression

In filtered mode Chantal regenerates the `Packages` index. The uncompressed
`Packages` file is always written, alongside one compressed variant controlled
by the top-level `metadata.compression` option:

```yaml
repositories:
  - id: ubuntu-jammy-filtered
    type: apt
    feed: http://archive.ubuntu.com/ubuntu
    mode: filtered
    apt:
      distribution: jammy
      components: [main]
      architectures: [amd64]
    metadata:
      compression: zstandard   # gzip (default) | zstandard | bzip2 | none
```

| Value | Output | Notes |
|-------|--------|-------|
| `auto` (default) | `Packages` + `Packages.gz` | `auto` maps to gzip for APT |
| `gzip` | `Packages` + `Packages.gz` | Universally supported |
| `zstandard` | `Packages` + `Packages.zst` | Supported by modern apt (Ubuntu) |
| `bzip2` | `Packages` + `Packages.bz2` | Legacy |
| `none` | `Packages` only | Uncompressed index only |

All generated variants are listed with their checksums in the `Release` file, so
clients automatically pick a format they support.

## Publishing

### Publish Latest Repository State

```bash
chantal publish repo --repo-id ubuntu-jammy-main
```

Output structure:
```
/var/www/repos/ubuntu-jammy-main/
├── dists/
│   └── jammy/
│       ├── InRelease           # GPG-signed (if available from upstream)
│       ├── Release              # Contains MD5/SHA1/SHA256 checksums
│       └── main/
│           └── binary-amd64/
│               ├── Packages     # RFC822 format
│               └── Packages.gz  # Compressed
└── pool/
    └── main/
        └── d/
            └── docker-ce/
                └── docker-ce_20.10.21_amd64.deb
```

Client configuration (sources.list):
```
deb [arch=amd64] http://mirror.example.com/repos/ubuntu-jammy-main jammy main
```

### Publish Snapshot

```bash
# Create snapshot first
chantal snapshot create ubuntu-jammy-main --name 2026-01-12

# Publish the snapshot
chantal publish snapshot --snapshot 2026-01-12 --repo-id ubuntu-jammy-main
```

Client configuration for snapshot:
```
deb [arch=amd64] http://mirror.example.com/repos/snapshots/ubuntu-jammy-main/2026-01-12 jammy main
```

### Unpublish

```bash
# Unpublish repository
chantal publish unpublish --repo-id ubuntu-jammy-main

# Unpublish snapshot
chantal publish unpublish --snapshot 2026-01-12 --repo-id ubuntu-jammy-main
```

## Directory Structure

### Standard APT Repository Layout

```
/var/www/repos/{repo-id}/
├── dists/
│   └── {distribution}/
│       ├── InRelease                    # GPG-signed Release (preserved in mirror mode)
│       ├── Release                      # Repository metadata with checksums
│       ├── Release.gpg                  # Detached GPG signature (if available)
│       ├── main/
│       │   ├── binary-amd64/
│       │   │   ├── Packages            # Package metadata (RFC822 format)
│       │   │   └── Packages.gz         # Compressed packages index
│       │   ├── binary-arm64/
│       │   │   ├── Packages
│       │   │   └── Packages.gz
│       │   └── source/                 # If include_source_packages: true
│       │       ├── Sources
│       │       └── Sources.gz
│       └── contrib/
│           └── binary-amd64/
│               ├── Packages
│               └── Packages.gz
└── pool/
    ├── main/
    │   ├── a/
    │   │   └── apt/
    │   │       └── apt_2.4.8_amd64.deb
    │   └── d/
    │       └── docker-ce/
    │           └── docker-ce_24.0.7_amd64.deb
    └── contrib/
        └── v/
            └── virtualbox/
                └── virtualbox-7.0_7.0.12_amd64.deb
```

### Content-Addressed Storage Pool

All .deb files are stored in the global content-addressed pool:

```
/var/lib/chantal/pool/
└── ab/
    └── cd/
        └── abcdef1234567890...sha256_docker-ce_24.0.7_amd64.deb
```

Publishing uses hardlinks (zero-copy) from the pool to the published directory.

## Repository Modes

### MIRROR Mode

Preserves original repository structure and metadata exactly as upstream.

**Behavior:**
- Downloads InRelease/Release files directly from upstream
- Downloads Packages files directly from upstream
- No metadata regeneration
- Preserves GPG signatures
- Ideal for exact repository mirrors

**Use Cases:**
- Air-gapped environments requiring exact upstream copies
- Compliance requirements for unmodified repositories
- CDN/mirror acceleration

**Example:**
```yaml
repositories:
  - id: debian-mirror
    name: Debian Bookworm Mirror
    type: apt
    feed: http://deb.debian.org/debian
    mode: mirror
    apt:
      distribution: bookworm
      components: [main, contrib, non-free]
      architectures: [amd64, arm64]
```

### FILTERED Mode

**Status:** ✅ Available (v0.2.0) - without GPG signing

Regenerates metadata for filtered package sets based on configured filters.

**Behavior:**
- Downloads and parses upstream Packages files
- Applies configured filters:
  - Component filtering (main, contrib, non-free, etc.)
  - Priority filtering (required, important, standard, optional)
  - Pattern-based filtering (regex include/exclude)
  - Version filtering (only latest versions)
- Regenerates Packages and Release files based on filtered packages
- **Optional GPG signing** - signs the regenerated metadata when a `gpg` section
  is configured (see [GPG Signing](#gpg-signing-filtered-mode)); otherwise
  publishes without InRelease/Release.gpg
- Optimal for curated/filtered repositories

**Use Cases:**
- Security-focused repos (only specific packages)
- Bandwidth optimization (exclude large packages)
- Version control (only latest versions)
- Curated package sets for specific use cases

**Client Configuration:**

⚠️ **IMPORTANT:** Since filtered repositories regenerate metadata, GPG signatures from upstream become invalid.

**Recommended: Sign the repository** (see [GPG Signing](#gpg-signing-filtered-mode)).
Once a `gpg` section is configured, clients can use the repository securely
without `[trusted=yes]`:
```
deb [signed-by=/etc/apt/keyrings/chantal.asc] http://mirror.example.com/repos/ubuntu-filtered jammy main
```

If you do **not** configure signing, clients must explicitly trust the repository:

**Option 1: Per-repository trust**
```
deb [trusted=yes] http://mirror.example.com/repos/ubuntu-filtered jammy main
```

**Option 2: Global insecure repository allow**
```bash
# /etc/apt/apt.conf.d/99allow-insecure
APT::Get::AllowUnauthenticated "true";
Acquire::AllowInsecureRepositories "true";
```

**Example Configuration:**

```yaml
repositories:
  - id: ubuntu-jammy-webservers
    name: Ubuntu 22.04 - Web Servers Only
    type: apt
    feed: http://archive.ubuntu.com/ubuntu
    enabled: true
    mode: filtered  # Enable filtered mode

    apt:
      distribution: jammy
      components:
        - main
        - universe
      architectures:
        - amd64

    filters:
      # Component filtering
      deb:
        components:
          include: [main]  # Only main component
        priorities:
          include: [important, optional]  # Skip required/standard

      # Pattern-based filtering
      patterns:
        include:
          - "^nginx.*"
          - "^apache2.*"
          - "^php.*"
        exclude:
          - ".*-dbg$"  # Exclude debug packages
          - ".*-doc$"  # Exclude documentation packages

      # Post-processing
      post_processing:
        only_latest_version: true  # Keep only latest version of each package
```

**Workflow:**

```bash
# Sync with filters applied
chantal repo sync --repo-id ubuntu-jammy-webservers

# Publish filtered repository
chantal publish repo --repo-id ubuntu-jammy-webservers
```

Output:
```
=== Applying Filters (Filtered Mode) ===
After filtering: 45 packages
⚠️  WARNING: Filtered mode will regenerate metadata without GPG signatures!
    Clients must use [trusted=yes] or Acquire::AllowInsecureRepositories=1
```

**Filtering Options:**

See [Filters Configuration](../configuration/filters.md) for complete documentation on available filters:

- **Component Filters** - Filter by APT component (main, universe, contrib, non-free)
- **Priority Filters** - Filter by package priority (required, important, standard, optional)
- **Pattern Filters** - Regex-based include/exclude by package name
- **Post-Processing** - Keep only latest versions, limit to N versions

**Limitations:**

- Without a `gpg` section, clients must explicitly trust the repository
- Dependency resolution must be handled by client (APT)

**Comparison with Mirror Mode:**

| Feature | Mirror Mode | Filtered Mode |
|---------|------------|--------------|
| GPG Signatures | ✅ Preserved (upstream) | ✅ Re-signed with own key (optional) |
| Package Filtering | ❌ All packages | ✅ Configurable |
| Metadata Source | Upstream | Regenerated |
| Client Trust | Automatic (GPG) | GPG (signed-by) or manual (trusted=yes) |
| Use Case | Exact mirrors | Curated subsets |

## GPG Signing (Filtered Mode)

**Status:** ✅ Available

In filtered mode the regenerated `Release` file no longer matches the upstream
GPG signatures. Configure a `gpg` section to have Chantal sign the metadata with
its own key, so clients can verify the repository without `[trusted=yes]`.

When signing is enabled, publishing produces:

- `dists/<dist>/InRelease` - the clearsigned (inline) `Release`
- `dists/<dist>/Release.gpg` - the detached ASCII-armored signature
- `<repo-root>/key.gpg` - the exported public key for client distribution

### Configuration

The `gpg` section can be set per repository or globally (as a fallback for all
repositories that don't define their own).

```yaml
repositories:
  - id: ubuntu-jammy-filtered
    name: Ubuntu 22.04 - Filtered
    type: apt
    feed: http://archive.ubuntu.com/ubuntu
    mode: filtered

    apt:
      distribution: jammy
      components: [main]
      architectures: [amd64]

    filters:
      patterns:
        include: ["^nginx.*"]

    gpg:
      # Use an existing key already present in the keyring / gnupg_home
      key_id: "ABCD1234EF567890"
      # Or import a private key from a file:
      key_file: /etc/chantal/keys/signing.asc
      # Passphrase handling (file preferred over inline value):
      passphrase_file: /etc/chantal/keys/passphrase.txt
      # Keyring location (a private temporary one is used if omitted):
      gnupg_home: /etc/chantal/gnupg
```

**Options:**

| Option | Description |
|--------|-------------|
| `enabled` | Enable/disable signing (default: `true`) |
| `key_id` | Key ID/fingerprint of an existing key to sign with |
| `key_file` | Path to an ASCII-armored **private** key to import before signing |
| `passphrase` | Signing key passphrase (inline; prefer `passphrase_file`) |
| `passphrase_file` | Path to a file containing the passphrase |
| `gnupg_home` | GnuPG home directory (keyring location) |
| `public_key_file` | Path to a public key to publish (exported from the keyring if unset) |
| `public_key_name` | Filename of the published public key (default: `key.gpg`) |
| `generate_key` | Generate a new signing keypair if no key is provided (default: `false`) |
| `key_name` / `key_email` | Identity used when generating a key |

At least one of `key_id`, `key_file`, or `generate_key` must be set when signing
is enabled.

### Global Fallback

```yaml
# Global GPG config applies to every APT repository without its own gpg section
gpg:
  key_id: "ABCD1234EF567890"
  gnupg_home: /etc/chantal/gnupg

repositories:
  - id: ubuntu-jammy-filtered
    type: apt
    feed: http://archive.ubuntu.com/ubuntu
    mode: filtered
    apt:
      distribution: jammy
      components: [main]
      architectures: [amd64]
    # inherits the global gpg config
```

### Key Generation Workflow

You can generate a dedicated signing key with `gpg` and reference it by ID:

```bash
# Create a keyring location for Chantal
export GNUPGHOME=/etc/chantal/gnupg
mkdir -p "$GNUPGHOME" && chmod 700 "$GNUPGHOME"

# Generate a signing key (RSA 3072)
gpg --batch --gen-key <<EOF
Key-Type: RSA
Key-Length: 3072
Name-Real: Chantal Repository Signing Key
Name-Email: repo@example.com
Expire-Date: 0
%no-protection
%commit
EOF

# Find the key ID / fingerprint
gpg --list-secret-keys --keyid-format LONG
```

Then reference it in the config:

```yaml
gpg:
  key_id: "<fingerprint-from-above>"
  gnupg_home: /etc/chantal/gnupg
```

Alternatively, let Chantal generate the key automatically on first publish with
`generate_key: true` (the keypair is created in `gnupg_home`).

### Client Configuration (Signed Repository)

```bash
# Download the published public key and install it as a keyring
sudo mkdir -p /etc/apt/keyrings
wget -O /etc/apt/keyrings/chantal.asc \
  http://mirror.example.com/repos/ubuntu-jammy-filtered/key.gpg

# Reference the keyring in the sources entry (no [trusted=yes] needed)
echo "deb [signed-by=/etc/apt/keyrings/chantal.asc] \
  http://mirror.example.com/repos/ubuntu-jammy-filtered jammy main" \
  | sudo tee /etc/apt/sources.list.d/chantal.list

sudo apt-get update
```

The legacy `apt-key` workflow also works but is deprecated on modern systems:

```bash
wget -O - http://mirror.example.com/repos/ubuntu-jammy-filtered/key.gpg | sudo apt-key add -
```

## Workflow Examples

### Example 1: Mirror Ubuntu LTS

```yaml
repositories:
  - id: ubuntu-jammy
    name: Ubuntu 22.04 Jammy LTS
    type: apt
    feed: http://archive.ubuntu.com/ubuntu
    enabled: true
    mode: mirror

    apt:
      distribution: jammy
      components:
        - main
        - restricted
        - universe
        - multiverse
      architectures:
        - amd64

    retention:
      policy: mirror
```

Sync and publish:
```bash
# Initial sync
chantal repo sync --repo-id ubuntu-jammy

# Create monthly snapshot
chantal snapshot create ubuntu-jammy --name $(date +%Y-%m)

# Publish latest state
chantal publish repo --repo-id ubuntu-jammy

# Publish snapshot
chantal publish snapshot --snapshot $(date +%Y-%m) --repo-id ubuntu-jammy
```

### Example 2: Docker CE Mirror

```yaml
repositories:
  - id: docker-ce-ubuntu-jammy
    name: Docker CE - Ubuntu Jammy
    type: apt
    feed: https://download.docker.com/linux/ubuntu
    enabled: true
    mode: mirror

    apt:
      distribution: jammy
      components:
        - stable
      architectures:
        - amd64
      include_source_packages: false

    retention:
      policy: keep_snapshots
      max_snapshots: 10
```

Automated workflow:
```bash
# Sync latest Docker packages
chantal repo sync --repo-id docker-ce-ubuntu-jammy

# Create snapshot with current date
chantal snapshot create docker-ce-ubuntu-jammy --name $(date +%Y-%m-%d)

# Check what changed
chantal snapshot diff docker-ce-ubuntu-jammy --from-snapshot 2026-01-01 --to-snapshot $(date +%Y-%m-%d)

# Publish latest
chantal publish repo --repo-id docker-ce-ubuntu-jammy
```

**Note:** For filtered Docker repositories (specific packages only), use filtered mode with pattern-based filtering (see FILTERED Mode section above).

## Troubleshooting

### InRelease file not found

Some repositories don't provide InRelease files, only Release + Release.gpg:

```
WARNING: InRelease file not found, trying Release + Release.gpg
```

This is normal for older repositories. Chantal will automatically fall back to Release file.

### Architecture not found

If you request an architecture that doesn't exist:

```
ERROR: Architecture arm64 not found for jammy/main
```

Check the upstream repository's Release file to see available architectures.

### Component not available

If a component doesn't exist:

```
ERROR: Component 'non-free-firmware' not found in jammy
```

Note: `non-free-firmware` was added in Debian 12. Debian 11 uses `non-free` only.

### Source packages missing

If `include_source_packages: true` but no sources are found:

```
WARNING: No source packages found for jammy/main
```

Some repositories don't provide source packages. This is expected for third-party repos.

## Advanced Topics

### Dependency Resolution

Chantal preserves full dependency metadata:

- **Depends** - Required packages
- **Pre-Depends** - Pre-installation requirements
- **Recommends** - Recommended packages (installed by default)
- **Suggests** - Suggested packages
- **Enhances** - Packages enhanced by this package
- **Breaks** - Packages broken by this package
- **Conflicts** - Conflicting packages
- **Replaces** - Packages replaced by this package
- **Provides** - Virtual packages provided

### Multi-Arch Support

Chantal supports Debian's multi-arch feature:

- `Multi-Arch: same` - Can be installed for multiple architectures simultaneously
- `Multi-Arch: foreign` - Satisfies dependencies from any architecture
- `Multi-Arch: allowed` - Can satisfy dependencies from other architectures

### Package Priorities

Standard Debian priorities are preserved:

- `required` - Essential for system boot
- `important` - Important system packages
- `standard` - Standard system packages
- `optional` - Optional packages
- `extra` - Conflicts with other packages (deprecated, use `optional`)

### Sections

Common package sections:

- `admin` - System administration
- `base` - Base system
- `comm` - Communication programs
- `devel` - Development tools
- `doc` - Documentation
- `editors` - Text editors
- `graphics` - Graphics software
- `libs` - Libraries
- `mail` - Mail programs
- `net` - Network programs
- `utils` - Utilities
- `web` - Web software

## Integration with Other Tools

### apt-mirror Replacement

Chantal can replace apt-mirror with additional features:

| Feature | apt-mirror | Chantal |
|---------|-----------|---------|
| Mirror mode | ✅ | ✅ |
| Filtered sync | ❌ | ✅ |
| Snapshots | ❌ | ✅ |
| Content deduplication | ❌ | ✅ |
| Multiple formats | ❌ | ✅ (RPM, Helm, APK) |
| Database tracking | ❌ | ✅ |

### aptly Comparison

| Feature | aptly | Chantal |
|---------|-------|---------|
| APT mirroring | ✅ | ✅ |
| Package filtering | ✅ | ✅ |
| Snapshots | ✅ | ✅ |
| GPG signing | ✅ | ✅ |
| Package uploads | ✅ | ⏳ (planned) |
| Multi-format | ❌ | ✅ |
| Views (virtual repos) | ❌ | ✅ |

## Performance

**Sync Speed:**
- Depends on upstream repository size and network bandwidth
- Typical: 100-500 MB/s for package downloads
- Content-addressed storage eliminates duplicate downloads across repositories

**Storage:**
- Deduplication via content-addressing
- Hardlinks for published repositories (zero-copy)
- Typical compression: Packages.gz is ~5% of uncompressed size

**Example:**
- Ubuntu Jammy main (amd64): ~70,000 packages, ~80 GB
- Docker CE stable (amd64): ~50 packages, ~500 MB

## See Also

- [Configuration Overview](../configuration/overview.md) - Global configuration
- [Repository Configuration](../configuration/repositories.md) - Repository settings
- [Filters](../configuration/filters.md) - Filtering options
- [SSL & Authentication](../configuration/ssl-authentication.md) - Authentication
- [CLI Commands](../user-guide/cli-commands.md) - Command reference
- [Workflows](../user-guide/workflows.md) - Common workflows
