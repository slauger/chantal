from __future__ import annotations

"""
Parsers for APT/DEB repository metadata files.

APT metadata uses RFC822-style format (similar to email headers):
- Field: value
- Multi-line values are indented with spaces
- Blank lines separate stanzas (package records)
"""

import gzip
import logging
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path

from chantal.plugins.apt.models import DebMetadata, ReleaseMetadata, SourcesMetadata

logger = logging.getLogger(__name__)


def parse_rfc822_stanza(text: str) -> dict[str, str]:
    """
    Parse a single RFC822 stanza into a dictionary.

    Args:
        text: RFC822-formatted text (single stanza)

    Returns:
        Dictionary of field names to values

    Example:
        >>> stanza = '''Package: nginx
        ... Version: 1.18.0
        ... Description: Small, powerful, scalable web/proxy server
        ...  This is a multi-line
        ...  description.'''
        >>> result = parse_rfc822_stanza(stanza)
        >>> result['Package']
        'nginx'
        >>> result['Description']
        'Small, powerful, scalable web/proxy server\\nThis is a multi-line\\ndescription.'
    """
    fields: dict[str, str] = {}
    current_field: str | None = None
    current_value: list[str] = []

    for line in text.split("\n"):
        # Continuation line (starts with space or tab)
        if line and line[0] in (" ", "\t"):
            if current_field:
                # Remove leading space and add to current value
                continuation = line[1:] if len(line) > 1 else ""
                # Handle "." as paragraph separator
                if continuation == ".":
                    current_value.append("")
                else:
                    current_value.append(continuation)
        # New field (contains colon)
        elif ":" in line:
            # Save previous field if exists
            if current_field:
                fields[current_field] = "\n".join(current_value)
            # Parse new field
            field_name, _, field_value = line.partition(":")
            current_field = field_name.strip()
            current_value = [field_value.strip()] if field_value.strip() else []
        # Empty line or malformed - skip
        else:
            continue

    # Save final field
    if current_field:
        fields[current_field] = "\n".join(current_value)

    return fields


def parse_rfc822_file(content: str) -> Iterator[dict[str, str]]:
    """
    Parse RFC822 file into iterator of stanzas.

    Args:
        content: Full RFC822 file content

    Yields:
        Dictionary for each stanza (package record)
    """
    # Split by double newlines (blank lines separate stanzas)
    stanzas = content.split("\n\n")

    for stanza_text in stanzas:
        stanza_text = stanza_text.strip()
        if not stanza_text:
            continue

        stanza = parse_rfc822_stanza(stanza_text)
        if stanza:  # Only yield non-empty stanzas
            yield stanza


def parse_packages_file(content: str) -> list[DebMetadata]:
    """
    Parse APT Packages file into list of DebMetadata objects.

    Args:
        content: Content of Packages file (uncompressed)

    Returns:
        List of DebMetadata objects

    Example:
        >>> content = '''Package: nginx
        ... Version: 1.18.0-0ubuntu1
        ... Architecture: amd64
        ... Filename: pool/main/n/nginx/nginx_1.18.0-0ubuntu1_amd64.deb
        ... Size: 354232
        ... SHA256: 5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f'''
        >>> packages = parse_packages_file(content)
        >>> packages[0].package
        'nginx'
    """
    packages: list[DebMetadata] = []

    for stanza in parse_rfc822_file(content):
        # Extract required fields
        package = stanza.get("Package")
        version = stanza.get("Version")
        architecture = stanza.get("Architecture")
        filename = stanza.get("Filename")
        size_str = stanza.get("Size")
        sha256 = stanza.get("SHA256")

        # Skip incomplete records
        if not all([package, version, architecture, filename, size_str, sha256]):
            logger.warning(
                f"Skipping incomplete package record: Package={package}, "
                f"Version={version}, missing required fields"
            )
            continue

        # Type narrowing: After the check above, these are guaranteed to be str
        assert package is not None
        assert version is not None
        assert architecture is not None
        assert filename is not None
        assert size_str is not None
        assert sha256 is not None

        # Parse size as integer
        try:
            size = int(size_str)
        except ValueError:
            logger.warning(f"Invalid size for {package} {version}: {size_str}")
            continue

        # Parse optional installed size
        installed_size = None
        if "Installed-Size" in stanza:
            try:
                installed_size = int(stanza["Installed-Size"])
            except ValueError:
                logger.warning(
                    f"Invalid Installed-Size for {package} {version}: "
                    f"{stanza['Installed-Size']}"
                )

        # Handle description (may be multi-line)
        description = stanza.get("Description")
        long_description = None
        if description and "\n" in description:
            # First line is short description, rest is long description
            lines = description.split("\n", 1)
            description = lines[0]
            long_description = lines[1] if len(lines) > 1 else None

        # Collect extra fields not explicitly modeled
        known_fields = {
            "Package",
            "Version",
            "Architecture",
            "Filename",
            "Size",
            "SHA256",
            "Description",
            "Section",
            "Priority",
            "Homepage",
            "Bugs",
            "Depends",
            "Pre-Depends",
            "Recommends",
            "Suggests",
            "Enhances",
            "Breaks",
            "Conflicts",
            "Replaces",
            "Provides",
            "Maintainer",
            "Original-Maintainer",
            "Source",
            "Built-Using",
            "Essential",
            "Multi-Arch",
            "MD5sum",
            "SHA1",
            "Installed-Size",
            "Task",
        }
        extra_fields = {k: v for k, v in stanza.items() if k not in known_fields}

        # Create DebMetadata object
        try:
            metadata = DebMetadata(
                package=package,
                version=version,
                architecture=architecture,
                filename=filename,
                size=size,
                sha256=sha256,
                component=None,  # Will be set by sync plugin based on metadata source
                description=description,
                long_description=long_description,
                section=stanza.get("Section"),
                priority=stanza.get("Priority"),
                homepage=stanza.get("Homepage"),
                bugs=stanza.get("Bugs"),
                depends=stanza.get("Depends"),
                pre_depends=stanza.get("Pre-Depends"),
                recommends=stanza.get("Recommends"),
                suggests=stanza.get("Suggests"),
                enhances=stanza.get("Enhances"),
                breaks=stanza.get("Breaks"),
                conflicts=stanza.get("Conflicts"),
                replaces=stanza.get("Replaces"),
                provides=stanza.get("Provides"),
                maintainer=stanza.get("Maintainer"),
                original_maintainer=stanza.get("Original-Maintainer"),
                source=stanza.get("Source"),
                built_using=stanza.get("Built-Using"),
                essential=stanza.get("Essential"),
                multi_arch=stanza.get("Multi-Arch"),
                md5sum=stanza.get("MD5sum"),
                sha1=stanza.get("SHA1"),
                installed_size=installed_size,
                task=stanza.get("Task"),
                extra_fields=extra_fields,
            )
            packages.append(metadata)
        except Exception as e:
            logger.error(f"Failed to parse package {package} {version}: {e}")
            continue

    return packages


def parse_release_file(content: str) -> ReleaseMetadata:
    """
    Parse APT Release or InRelease file into ReleaseMetadata object.

    Args:
        content: Content of Release/InRelease file

    Returns:
        ReleaseMetadata object

    Example:
        >>> content = '''Origin: Ubuntu
        ... Label: Ubuntu
        ... Suite: jammy
        ... Codename: jammy
        ... Architectures: amd64 arm64
        ... Components: main restricted universe multiverse
        ... SHA256:
        ...  abc123 12345 main/binary-amd64/Packages.gz'''
        >>> release = parse_release_file(content)
        >>> release.suite
        'jammy'
    """
    # Parse as single stanza (Release file has only one record)
    stanza = parse_rfc822_stanza(content.strip())

    # Parse architectures and components (space-separated)
    architectures = []
    if "Architectures" in stanza:
        architectures = stanza["Architectures"].split()

    components = []
    if "Components" in stanza:
        components = stanza["Components"].split()

    # Parse Acquire-By-Hash
    acquire_by_hash = stanza.get("Acquire-By-Hash", "").lower() == "yes"

    # Parse checksums (MD5Sum, SHA1, SHA256)
    md5sum: dict[str, tuple[str, int]] = {}
    sha1: dict[str, tuple[str, int]] = {}
    sha256: dict[str, tuple[str, int]] = {}

    # Helper to parse checksum blocks
    def parse_checksum_block(field_name: str) -> dict[str, tuple[str, int]]:
        result: dict[str, tuple[str, int]] = {}
        if field_name in stanza:
            checksum_text = stanza[field_name]
            for line in checksum_text.strip().split("\n"):
                parts = line.strip().split()
                if len(parts) >= 3:
                    checksum = parts[0]
                    try:
                        size = int(parts[1])
                        filename = parts[2]
                        result[filename] = (checksum, size)
                    except ValueError:
                        logger.warning(f"Invalid checksum line in {field_name}: {line}")
        return result

    md5sum = parse_checksum_block("MD5Sum")
    sha1 = parse_checksum_block("SHA1")
    sha256 = parse_checksum_block("SHA256")

    # Collect extra fields
    known_fields = {
        "Suite",
        "Codename",
        "Architectures",
        "Components",
        "Origin",
        "Label",
        "Version",
        "Description",
        "Date",
        "Valid-Until",
        "Acquire-By-Hash",
        "MD5Sum",
        "SHA1",
        "SHA256",
    }
    extra_fields = {k: v for k, v in stanza.items() if k not in known_fields}

    # Create ReleaseMetadata object
    return ReleaseMetadata(
        suite=stanza.get("Suite"),
        codename=stanza.get("Codename"),
        architectures=architectures,
        components=components,
        origin=stanza.get("Origin"),
        label=stanza.get("Label"),
        version=stanza.get("Version"),
        description=stanza.get("Description"),
        date=stanza.get("Date"),
        valid_until=stanza.get("Valid-Until"),
        acquire_by_hash=acquire_by_hash,
        md5sum=md5sum,
        sha1=sha1,
        sha256=sha256,
        extra_fields=extra_fields,
    )


def parse_sources_file(content: str) -> list[SourcesMetadata]:
    """
    Parse APT Sources file into list of SourcesMetadata objects.

    Args:
        content: Content of Sources file (uncompressed)

    Returns:
        List of SourcesMetadata objects
    """
    sources: list[SourcesMetadata] = []

    for stanza in parse_rfc822_file(content):
        package = stanza.get("Package")
        version = stanza.get("Version")

        if not package or not version:
            logger.warning("Skipping incomplete source record")
            continue

        # Parse binary packages (space-separated)
        binary = []
        if "Binary" in stanza:
            binary = stanza["Binary"].replace(",", " ").split()

        # Parse uploaders (comma-separated)
        uploaders = []
        if "Uploaders" in stanza:
            uploaders = [u.strip() for u in stanza["Uploaders"].split(",")]

        # Parse files (multi-line with checksums)
        def parse_file_list(field_name: str, stanza_data: dict[str, str]) -> list[dict[str, str]]:
            result = []
            if field_name in stanza_data:
                for line in stanza_data[field_name].strip().split("\n"):
                    parts = line.strip().split()
                    if len(parts) >= 3:
                        result.append(
                            {"checksum": parts[0], "size": parts[1], "filename": parts[2]}
                        )
            return result

        files = parse_file_list("Files", stanza)
        checksums_sha1 = parse_file_list("Checksums-Sha1", stanza)
        checksums_sha256 = parse_file_list("Checksums-Sha256", stanza)

        # Collect extra fields
        known_fields = {
            "Package",
            "Version",
            "Binary",
            "Architecture",
            "Maintainer",
            "Uploaders",
            "Homepage",
            "Section",
            "Priority",
            "Build-Depends",
            "Build-Depends-Indep",
            "Build-Conflicts",
            "Build-Conflicts-Indep",
            "Vcs-Browser",
            "Vcs-Git",
            "Vcs-Svn",
            "Vcs-Bzr",
            "Directory",
            "Files",
            "Checksums-Sha1",
            "Checksums-Sha256",
        }
        extra_fields = {k: v for k, v in stanza.items() if k not in known_fields}

        # Create SourcesMetadata object
        try:
            metadata = SourcesMetadata(
                package=package,
                version=version,
                binary=binary,
                architecture=stanza.get("Architecture"),
                maintainer=stanza.get("Maintainer"),
                uploaders=uploaders,
                homepage=stanza.get("Homepage"),
                section=stanza.get("Section"),
                priority=stanza.get("Priority"),
                build_depends=stanza.get("Build-Depends"),
                build_depends_indep=stanza.get("Build-Depends-Indep"),
                build_conflicts=stanza.get("Build-Conflicts"),
                build_conflicts_indep=stanza.get("Build-Conflicts-Indep"),
                vcs_browser=stanza.get("Vcs-Browser"),
                vcs_git=stanza.get("Vcs-Git"),
                vcs_svn=stanza.get("Vcs-Svn"),
                vcs_bzr=stanza.get("Vcs-Bzr"),
                directory=stanza.get("Directory"),
                files=files,
                checksums_sha1=checksums_sha1,
                checksums_sha256=checksums_sha256,
                extra_fields=extra_fields,
            )
            sources.append(metadata)
        except Exception as e:
            logger.error(f"Failed to parse source package {package} {version}: {e}")
            continue

    return sources


def parse_packages_gz(file_path: Path) -> list[DebMetadata]:
    """
    Parse compressed Packages.gz file.

    Args:
        file_path: Path to Packages.gz file

    Returns:
        List of DebMetadata objects
    """
    with gzip.open(file_path, "rt", encoding="utf-8") as f:
        content = f.read()
    return parse_packages_file(content)


def parse_packages_from_bytes(data: bytes, compressed: bool = False) -> list[DebMetadata]:
    """
    Parse Packages file from bytes.

    Args:
        data: Packages file data
        compressed: Whether data is gzip-compressed

    Returns:
        List of DebMetadata objects
    """
    if compressed:
        with gzip.open(BytesIO(data), "rt", encoding="utf-8") as f:
            content = f.read()
    else:
        content = data.decode("utf-8")
    return parse_packages_file(content)


def parse_sources_gz(file_path: Path) -> list[SourcesMetadata]:
    """
    Parse compressed Sources.gz file.

    Args:
        file_path: Path to Sources.gz file

    Returns:
        List of SourcesMetadata objects
    """
    with gzip.open(file_path, "rt", encoding="utf-8") as f:
        content = f.read()
    return parse_sources_file(content)
