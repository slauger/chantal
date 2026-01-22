from __future__ import annotations

"""
RPM repository metadata parsers.

This module provides functions for parsing RPM repository metadata files.
"""

import bz2
import configparser
import gzip
import logging
import lzma
import xml.etree.ElementTree as ET
from urllib.parse import urljoin

import requests
import zstandard as zstd

from chantal.core.cache import MetadataCache

logger = logging.getLogger(__name__)


def fetch_repomd_xml(session: requests.Session, base_url: str) -> ET.Element:
    """Fetch and parse repomd.xml.

    Args:
        session: Requests session (with auth/SSL configured)
        base_url: Base URL of repository

    Returns:
        XML root element

    Raises:
        requests.RequestException: On HTTP errors
        ET.ParseError: On XML parse errors
    """
    repomd_url = urljoin(base_url + "/", "repodata/repomd.xml")
    response = session.get(repomd_url, timeout=30)
    response.raise_for_status()
    return ET.fromstring(response.content)


def extract_all_metadata(repomd_root: ET.Element) -> list[dict]:
    """Extract all metadata file information from repomd.xml.

    Args:
        repomd_root: Parsed repomd.xml root element

    Returns:
        List of dicts with metadata file information
        Each dict contains: file_type, location, checksum, size, open_checksum, open_size

    Raises:
        ValueError: If metadata parsing fails
    """
    # Handle XML namespaces
    ns = {"repo": "http://linux.duke.edu/metadata/repo"}

    metadata_files = []

    # Find all data elements
    data_elems = repomd_root.findall("repo:data", ns)
    if not data_elems:
        # Try without namespace
        data_elems = repomd_root.findall("data")

    for data_elem in data_elems:
        try:
            # Get type attribute
            file_type = data_elem.get("type")
            if not file_type:
                continue

            # Find location element
            location_elem = data_elem.find("repo:location", ns)
            if location_elem is None:
                location_elem = data_elem.find("location")
            if location_elem is None:
                continue

            location = location_elem.get("href")
            if not location:
                continue

            # Find checksum element
            checksum_elem = data_elem.find("repo:checksum", ns)
            if checksum_elem is None:
                checksum_elem = data_elem.find("checksum")
            if checksum_elem is None or not checksum_elem.text:
                continue

            # Find size element
            size_elem = data_elem.find("repo:size", ns)
            if size_elem is None:
                size_elem = data_elem.find("size")
            size = int(size_elem.text) if size_elem is not None and size_elem.text else 0

            # Optional: open-checksum and open-size
            open_checksum_elem = data_elem.find("repo:open-checksum", ns)
            if open_checksum_elem is None:
                open_checksum_elem = data_elem.find("open-checksum")
            open_checksum = open_checksum_elem.text if open_checksum_elem is not None else None

            open_size_elem = data_elem.find("repo:open-size", ns)
            if open_size_elem is None:
                open_size_elem = data_elem.find("open-size")
            open_size = (
                int(open_size_elem.text)
                if open_size_elem is not None and open_size_elem.text
                else None
            )

            # Create metadata file info dict
            metadata_info = {
                "file_type": file_type,
                "location": location,
                "checksum": checksum_elem.text,
                "size": size,
                "open_checksum": open_checksum,
                "open_size": open_size,
            }
            metadata_files.append(metadata_info)

        except Exception as e:
            # Skip malformed entries
            print(f"Warning: Failed to parse metadata entry: {e}")
            continue

    return metadata_files


def fetch_metadata_with_cache(
    session: requests.Session,
    base_url: str,
    location: str,
    checksum: str,
    cache: MetadataCache | None = None,
    file_type: str = "metadata",
) -> tuple[bytes, bool]:
    """Download and decompress metadata file with optional caching.

    Args:
        session: Requests session (with auth/SSL configured)
        base_url: Base URL of repository
        location: Relative path to metadata file (e.g., "repodata/abc-primary.xml.gz")
        checksum: Expected SHA256 checksum
        cache: Optional MetadataCache instance
        file_type: Type hint for logging (e.g., "primary", "updateinfo")

    Returns:
        Tuple of (decompressed XML content as bytes, from_cache boolean)

    Raises:
        requests.RequestException: On HTTP errors
        ValueError: If compression format is unknown or checksum mismatch
    """
    # Try cache first if enabled
    if cache:
        cached_file = cache.get(checksum, file_type)
        if cached_file:
            # Read cached compressed file
            compressed_content = cached_file.read_bytes()
            # Decompress and return
            return _decompress_metadata(compressed_content, location), True

    # Cache miss or disabled - download from upstream
    metadata_url = urljoin(base_url + "/", location)
    logger.info(f"Downloading {file_type} from {metadata_url}")
    response = session.get(metadata_url, timeout=60)
    response.raise_for_status()

    # Store in cache if enabled (compressed)
    if cache:
        try:
            cache.put(checksum, response.content, file_type)
        except Exception as e:
            logger.warning(f"Failed to cache {file_type}: {e}")

    # Decompress and return
    return _decompress_metadata(response.content, location), False


def _decompress_metadata(compressed_content: bytes, filename: str) -> bytes:
    """Decompress metadata file based on extension or magic bytes.

    Args:
        compressed_content: Compressed file content
        filename: Filename for extension detection

    Returns:
        Decompressed content

    Raises:
        ValueError: If compression format is unknown
    """
    # Try extension-based detection first
    if filename.endswith(".xz"):
        return lzma.decompress(compressed_content)
    elif filename.endswith(".gz"):
        return gzip.decompress(compressed_content)
    elif filename.endswith(".zst"):
        dctx = zstd.ZstdDecompressor()
        return dctx.decompress(compressed_content)  # type: ignore[no-any-return]
    elif filename.endswith(".bz2"):
        return bz2.decompress(compressed_content)

    # Fallback to magic byte detection
    if compressed_content[:2] == b"\x1f\x8b":  # gzip magic
        return gzip.decompress(compressed_content)
    elif compressed_content[:6] == b"\xfd7zXZ\x00":  # xz magic
        return lzma.decompress(compressed_content)
    elif compressed_content[:4] == b"\x28\xb5\x2f\xfd":  # zstandard magic
        dctx = zstd.ZstdDecompressor()
        return dctx.decompress(compressed_content)  # type: ignore[no-any-return]
    elif compressed_content[:3] == b"BZh":  # bzip2 magic
        return bz2.decompress(compressed_content)
    else:
        raise ValueError(f"Unknown compression format for {filename}")


def parse_primary_xml(xml_content: bytes) -> list[dict]:
    """Parse primary.xml content and extract package metadata.

    Args:
        xml_content: Decompressed primary.xml content

    Returns:
        List of dicts with package metadata
        Each dict contains: name, version, release, epoch, arch, sha256, size_bytes,
        location, summary, description, build_time, file_time, group, license,
        vendor, sourcerpm
    """
    root = ET.fromstring(xml_content)
    packages = []

    # Handle namespace
    ns = {"common": "http://linux.duke.edu/metadata/common"}

    # Find all package elements
    package_elems = root.findall("common:package", ns)
    if not package_elems:
        # Try without namespace
        package_elems = root.findall("package")

    for pkg_elem in package_elems:
        try:
            # Namespace URI for common elements
            ns_uri = "{http://linux.duke.edu/metadata/common}"
            rpm_ns = "{http://linux.duke.edu/metadata/rpm}"

            # Extract basic info
            name_elem = pkg_elem.find(f"{ns_uri}name")
            arch_elem = pkg_elem.find(f"{ns_uri}arch")
            version_elem = pkg_elem.find(f"{ns_uri}version")
            checksum_elem = pkg_elem.find(f"{ns_uri}checksum")
            size_elem = pkg_elem.find(f"{ns_uri}size")
            location_elem = pkg_elem.find(f"{ns_uri}location")
            summary_elem = pkg_elem.find(f"{ns_uri}summary")
            desc_elem = pkg_elem.find(f"{ns_uri}description")

            # Extract extended metadata
            time_elem = pkg_elem.find(f"{ns_uri}time")
            format_elem = pkg_elem.find(f"{ns_uri}format")

            # Extract RPM-specific metadata from <format> element
            group = None
            license_str = None
            vendor = None
            sourcerpm = None
            if format_elem is not None:
                group_elem = format_elem.find(f"{rpm_ns}group")
                license_elem = format_elem.find(f"{rpm_ns}license")
                vendor_elem = format_elem.find(f"{rpm_ns}vendor")
                sourcerpm_elem = format_elem.find(f"{rpm_ns}sourcerpm")

                group = group_elem.text if group_elem is not None else None
                license_str = license_elem.text if license_elem is not None else None
                vendor = vendor_elem.text if vendor_elem is not None else None
                sourcerpm = sourcerpm_elem.text if sourcerpm_elem is not None else None

            # Extract time metadata
            build_time = None
            file_time = None
            if time_elem is not None:
                build_time_str = time_elem.get("build")
                file_time_str = time_elem.get("file")
                build_time = int(build_time_str) if build_time_str else None
                file_time = int(file_time_str) if file_time_str else None

            # ElementTree elements can be falsy even if not None, so check explicitly
            if (
                name_elem is None
                or arch_elem is None
                or version_elem is None
                or checksum_elem is None
                or location_elem is None
            ):
                continue  # Skip incomplete packages

            pkg_meta = {
                "name": name_elem.text,
                "version": version_elem.get("ver"),
                "release": version_elem.get("rel") or "",
                "epoch": version_elem.get("epoch"),
                "arch": arch_elem.text,
                "sha256": checksum_elem.text,
                "size_bytes": int(size_elem.get("package") or "0") if size_elem is not None else 0,
                "location": location_elem.get("href"),
                "summary": summary_elem.text if summary_elem is not None else None,
                "description": desc_elem.text if desc_elem is not None else None,
                "build_time": build_time,
                "file_time": file_time,
                "group": group,
                "license": license_str,
                "vendor": vendor,
                "sourcerpm": sourcerpm,
            }
            packages.append(pkg_meta)

        except Exception as e:
            # Skip packages with parsing errors
            print(f"Warning: Failed to parse package: {e}")
            continue

    return packages


def parse_treeinfo(content: str) -> list[dict[str, str | None]]:
    """Parse .treeinfo and extract installer file metadata.

    Args:
        content: .treeinfo file content (INI format)

    Returns:
        List of dicts with keys: path, file_type, sha256 (sha256 can be None)
    """
    parser = configparser.ConfigParser()
    parser.read_string(content)

    installer_files = []

    # Parse checksums section
    checksums = {}
    if parser.has_section("checksums"):
        for key, value in parser.items("checksums"):
            # Format: "images/boot.iso = sha256:abc123..."
            if "sha256:" in value:
                checksum = value.split("sha256:")[1].strip()
                checksums[key] = checksum

    # Parse images section for current arch
    arch = parser.get("general", "arch", fallback="x86_64")
    images_section = f"images-{arch}"

    if parser.has_section(images_section):
        for file_type, file_path in parser.items(images_section):
            # file_type: boot.iso, kernel, initrd, etc.
            # file_path: images/boot.iso, images/pxeboot/vmlinuz

            sha256 = checksums.get(file_path)

            installer_files.append({"path": file_path, "file_type": file_type, "sha256": sha256})

    return installer_files
