# Phase 5: Kickstart/Installer Support - Implementation Plan

## Overview
Enable automatic detection, download, and publishing of OS installation files (.treeinfo, boot images) for full offline installation support.

## Architecture

### Storage Model
- **file_category**: `"kickstart"` (not "installer")
- **file_type**: `"boot.iso"`, `"vmlinuz"`, `"initrd.img"`, `"install.img"`, `"efiboot.img"`, `"treeinfo"`
- **Storage location**: `pool/files/` (content-addressed by SHA256)
- **Publishing**: Hardlinks to `images/` directory

### .treeinfo Format
INI-style configuration file describing installer components:

```ini
[checksums]
images/boot.iso = sha256:7fa5f43a19f85cfc87dd1f09ea023762ea44eeec79e7e7b13f286fcfe39bb6a8
images/pxeboot/vmlinuz = sha256:5b55ab14126b2979ce37a36ecb8dedd9a4dbb4e4de7f69488923aed0611ae8a0
images/pxeboot/initrd.img = sha256:95b778a741fd237d7daf982989ceaafa4496c3ed23376e734f0410c78b09781b

[images-x86_64]
boot.iso = images/boot.iso
kernel = images/pxeboot/vmlinuz
initrd = images/pxeboot/initrd.img

[general]
arch = x86_64
family = CentOS Stream
version = 9
```

## Implementation Steps

### Step 1: Add .treeinfo Detection to rpm_sync.py

**Location**: `src/chantal/plugins/rpm_sync.py`

**After repomd.xml parsing**, add:

```python
# Check for .treeinfo (installer metadata)
treeinfo_url = urljoin(base_url, ".treeinfo")
try:
    response = self.session.get(treeinfo_url, timeout=30)
    response.raise_for_status()

    treeinfo_content = response.text
    installer_files = self._parse_treeinfo(treeinfo_content)

    # Download installer files
    for file_info in installer_files:
        self._download_installer_file(
            session=session,
            repository=repository,
            base_url=base_url,
            file_info=file_info
        )

    # Store .treeinfo itself as RepositoryFile
    self._store_treeinfo(
        session=session,
        repository=repository,
        treeinfo_content=treeinfo_content
    )

except requests.exceptions.HTTPError as e:
    if e.response.status_code == 404:
        # No .treeinfo - not an installer repository
        print("  No .treeinfo found (not an installer repo)")
    else:
        raise
```

### Step 2: Implement _parse_treeinfo()

**New method in RpmSyncPlugin:**

```python
def _parse_treeinfo(self, content: str) -> List[Dict[str, str]]:
    """Parse .treeinfo and extract installer file metadata.

    Args:
        content: .treeinfo file content (INI format)

    Returns:
        List of dicts with keys: path, sha256, file_type
    """
    import configparser

    parser = configparser.ConfigParser()
    parser.read_string(content)

    installer_files = []

    # Parse checksums section
    checksums = {}
    if parser.has_section('checksums'):
        for key, value in parser.items('checksums'):
            # Format: "images/boot.iso = sha256:abc123..."
            if '=' in value or value.startswith('sha256:'):
                checksum = value.split('sha256:')[1].strip()
                checksums[key] = checksum

    # Parse images section for current arch
    arch = parser.get('general', 'arch', fallback='x86_64')
    images_section = f'images-{arch}'

    if parser.has_section(images_section):
        for file_type, file_path in parser.items(images_section):
            # file_type: boot.iso, kernel, initrd
            # file_path: images/boot.iso, images/pxeboot/vmlinuz

            sha256 = checksums.get(file_path, None)

            installer_files.append({
                'path': file_path,
                'file_type': file_type,  # boot.iso, kernel, initrd
                'sha256': sha256
            })

    return installer_files
```

### Step 3: Implement _download_installer_file()

**New method in RpmSyncPlugin:**

```python
def _download_installer_file(
    self,
    session: Session,
    repository: Repository,
    base_url: str,
    file_info: Dict[str, str]
) -> None:
    """Download and store installer file.

    Args:
        session: Database session
        repository: Repository instance
        base_url: Repository base URL
        file_info: Dict with path, file_type, sha256
    """
    file_path = file_info['path']
    file_type = file_info['file_type']
    expected_sha256 = file_info.get('sha256')

    file_url = urljoin(base_url, file_path)

    print(f"  → Downloading {file_type}: {file_path}")

    # Download to temp file
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
        response = self.session.get(file_url, stream=True, timeout=300)
        response.raise_for_status()

        # Download with progress
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0

        for chunk in response.iter_content(chunk_size=8192):
            tmp_file.write(chunk)
            downloaded += len(chunk)

            # Show progress for large files
            if total_size > 10 * 1024 * 1024:  # > 10MB
                print(f"\r    {downloaded / 1024 / 1024:.1f} MB / {total_size / 1024 / 1024:.1f} MB", end='')

        if total_size > 10 * 1024 * 1024:
            print()  # Newline after progress

        tmp_file_path = tmp_file.name

    # Calculate SHA256
    import hashlib
    sha256_hash = hashlib.sha256()
    with open(tmp_file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256_hash.update(chunk)

    actual_sha256 = sha256_hash.hexdigest()

    # Verify checksum if provided
    if expected_sha256 and actual_sha256 != expected_sha256:
        os.unlink(tmp_file_path)
        raise ValueError(
            f"Checksum mismatch for {file_path}: "
            f"expected {expected_sha256}, got {actual_sha256}"
        )

    # Store in pool via StorageManager
    from pathlib import Path
    pool_path = self.storage.add_repository_file(
        Path(tmp_file_path),
        filename=Path(file_path).name,
        sha256=actual_sha256
    )

    # Create RepositoryFile record
    repo_file = RepositoryFile(
        file_category="kickstart",
        file_type=file_type,
        original_path=file_path,
        pool_path=pool_path,
        sha256=actual_sha256,
        size_bytes=os.path.getsize(tmp_file_path),
        compression=None
    )

    session.add(repo_file)
    repository.repository_files.append(repo_file)

    # Clean up temp file
    os.unlink(tmp_file_path)

    print(f"    ✓ Stored {file_type} ({actual_sha256[:8]})")
```

### Step 4: Implement _store_treeinfo()

```python
def _store_treeinfo(
    self,
    session: Session,
    repository: Repository,
    treeinfo_content: str
) -> None:
    """Store .treeinfo file itself as RepositoryFile."""

    import tempfile
    import hashlib

    # Write to temp file
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.treeinfo') as f:
        f.write(treeinfo_content)
        tmp_path = f.name

    # Calculate SHA256
    sha256_hash = hashlib.sha256(treeinfo_content.encode()).hexdigest()

    # Store in pool
    from pathlib import Path
    pool_path = self.storage.add_repository_file(
        Path(tmp_path),
        filename=".treeinfo",
        sha256=sha256_hash
    )

    # Create RepositoryFile record
    repo_file = RepositoryFile(
        file_category="kickstart",
        file_type="treeinfo",
        original_path=".treeinfo",
        pool_path=pool_path,
        sha256=sha256_hash,
        size_bytes=len(treeinfo_content),
        compression=None
    )

    session.add(repo_file)
    repository.repository_files.append(repo_file)

    os.unlink(tmp_path)
    print("  ✓ Stored .treeinfo")
```

### Step 5: Update RpmPublisher to Publish Kickstart Files

**Location**: `src/chantal/plugins/rpm/__init__.py`

**In _publish_packages() method**, after metadata publishing:

```python
# Publish kickstart/installer files
kickstart_files = [
    rf for rf in repository_files
    if rf.file_category == "kickstart"
]

if kickstart_files:
    self._publish_kickstart_files(kickstart_files, target_path)
```

**New method:**

```python
def _publish_kickstart_files(
    self,
    kickstart_files: List[RepositoryFile],
    target_path: Path
) -> None:
    """Publish kickstart/installer files to images/ directory.

    Args:
        kickstart_files: List of RepositoryFile with file_category="kickstart"
        target_path: Target directory for publishing
    """
    for repo_file in kickstart_files:
        pool_file_path = self.storage.pool_path / repo_file.pool_path

        if not pool_file_path.exists():
            print(f"Warning: Pool file not found: {pool_file_path}")
            continue

        # Determine target path based on original path
        # .treeinfo goes to root, others to images/
        if repo_file.file_type == "treeinfo":
            target_file_path = target_path / ".treeinfo"
        else:
            # original_path like "images/boot.iso" or "images/pxeboot/vmlinuz"
            target_file_path = target_path / repo_file.original_path

        # Create parent directories
        target_file_path.parent.mkdir(parents=True, exist_ok=True)

        # Create hardlink
        if target_file_path.exists():
            target_file_path.unlink()

        import os
        os.link(pool_file_path, target_file_path)

        print(f"  ✓ Published {repo_file.file_type}: {repo_file.original_path}")
```

## File Size Considerations

Typical installer file sizes:
- **boot.iso**: ~1 GB (full bootable ISO)
- **install.img**: ~500 MB (installer image)
- **initrd.img**: ~80 MB (initial ramdisk)
- **vmlinuz**: ~10 MB (kernel)
- **efiboot.img**: ~5 MB (EFI boot image)

**Total**: ~1.6 GB per architecture per repository

## Configuration (Optional)

Add optional flag to RepositoryConfig to disable kickstart sync:

```yaml
repositories:
  - id: centos9-baseos
    type: rpm
    feed: https://mirror.stream.centos.org/9-stream/BaseOS/x86_64/os/
    sync_kickstart: true  # Default: true (auto-detect .treeinfo)
```

## Testing Plan

1. **Unit tests**:
   - Test _parse_treeinfo() with sample .treeinfo
   - Test checksum verification
   - Test RepositoryFile creation with file_category="kickstart"

2. **Integration tests**:
   - Sync CentOS Stream 9 BaseOS (has .treeinfo)
   - Verify all installer files downloaded
   - Verify published images/ directory structure
   - Test snapshot preserves kickstart files

3. **Live test**:
   - Sync real BaseOS repository
   - Verify .treeinfo, boot.iso, vmlinuz, initrd.img present
   - Test PXE boot from published files

## Benefits

- **Offline Installation**: Full OS installation without internet
- **Network Boot**: PXE/TFTP boot from local mirror
- **Air-Gapped Environments**: Complete installation in isolated networks
- **Consistent Experience**: Installation files match package versions

## Edge Cases

1. **No .treeinfo**: Normal repositories (AppStream, EPEL) don't have it - skip silently
2. **Missing checksums**: If .treeinfo lacks checksums, still download but warn
3. **Large files**: Show progress for files > 10MB
4. **Partial download**: Handle interruptions gracefully
5. **Multiple architectures**: .treeinfo may reference multiple arches - only download configured arch

## Future Enhancements

- **Incremental sync**: Skip already-downloaded installer files (check SHA256)
- **Bandwidth control**: Rate limiting for large downloads
- **Mirror selection**: Try multiple mirrors if download fails
- **Verification tool**: `chantal verify-kickstart` to check installer integrity
