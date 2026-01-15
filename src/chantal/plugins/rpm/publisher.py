from __future__ import annotations

"""
RPM/DNF repository publisher plugin.

This module implements publishing for RPM repositories with yum/dnf metadata.
"""

import bz2
import gzip
import hashlib
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from chantal.core.config import RepositoryConfig
from chantal.core.storage import StorageManager
from chantal.db.models import ContentItem, Repository, RepositoryFile, RepositoryMode, Snapshot
from chantal.plugins.base import PublisherPlugin
from chantal.plugins.rpm.compression import (
    CompressionFormat,
    add_compression_extension,
    compress_file,
)
from chantal.plugins.rpm.updateinfo import (
    UpdateInfoFilter,
    UpdateInfoGenerator,
    UpdateInfoParser,
)


class RpmPublisher(PublisherPlugin):
    """Publisher for RPM/DNF repositories.

    Creates standard yum/dnf repository structure:
    - Packages/ - Package files (hardlinks to pool)
    - repodata/ - Repository metadata
      - repomd.xml - Root metadata file
      - primary.xml.gz - Package metadata
      - filelists.xml.gz - File lists (optional)
      - other.xml.gz - Changelogs (optional)
    """

    def __init__(self, storage: StorageManager):
        """Initialize RPM publisher.

        Args:
            storage: Storage manager instance
        """
        super().__init__(storage)

    def publish_repository(
        self,
        session: Session,
        repository: Repository,
        config: RepositoryConfig,
        target_path: Path,
    ) -> None:
        """Publish RPM repository to target directory.

        Args:
            session: Database session
            repository: Repository model instance
            config: Repository configuration
            target_path: Target directory for publishing
        """
        # Get packages
        packages = self._get_repository_packages(session, repository)

        # Get repository files (metadata)
        session.refresh(repository)
        repository_files = repository.repository_files

        # Publish packages and metadata
        self._publish_packages(packages, target_path, repository_files, repository.mode, config)

    def publish_snapshot(
        self,
        session: Session,
        snapshot: Snapshot,
        repository: Repository,
        config: RepositoryConfig,
        target_path: Path,
    ) -> None:
        """Publish RPM snapshot to target directory.

        Args:
            session: Database session
            snapshot: Snapshot model instance
            repository: Repository model instance
            config: Repository configuration
            target_path: Target directory for publishing
        """
        # Get packages from snapshot
        packages = self._get_snapshot_packages(session, snapshot)

        # Get repository files (metadata) from snapshot
        session.refresh(snapshot)
        repository_files = snapshot.repository_files

        # Publish packages and metadata
        self._publish_packages(packages, target_path, repository_files, repository.mode, config)

    def unpublish(self, target_path: Path) -> None:
        """Remove published RPM repository.

        Args:
            target_path: Target directory to unpublish
        """
        if target_path.exists():
            shutil.rmtree(target_path)

    def _publish_packages(
        self,
        packages: list[ContentItem],
        target_path: Path,
        repository_files: list[RepositoryFile] | None = None,
        mode: str = RepositoryMode.MIRROR,
        config: RepositoryConfig | None = None,
    ) -> None:
        """Publish content items and generate metadata.

        Args:
            packages: List of content items to publish
            target_path: Target directory
            repository_files: List of repository files (metadata) to publish
            mode: Repository mode (mirror/filtered/hosted)
            config: Repository configuration (for metadata compression settings)
        """
        if repository_files is None:
            repository_files = []

        # Determine compression format
        compression: CompressionFormat = "gzip"  # default
        if config and config.metadata:
            compression_setting = config.metadata.compression
            if compression_setting == "auto":
                # Detect from upstream metadata files
                compression = self._detect_upstream_compression(repository_files)
            else:
                compression = compression_setting  # type: ignore

        # Create directory structure
        target_path.mkdir(parents=True, exist_ok=True)
        repodata_path = target_path / "repodata"
        repodata_path.mkdir(exist_ok=True)

        # Create hardlinks for packages
        self._create_hardlinks(packages, target_path, subdir="Packages")

        # Create hardlinks for metadata files
        published_metadata = self._publish_metadata_files(repository_files, repodata_path)

        # Filter and regenerate metadata ONLY in filtered mode
        # In mirror mode, all metadata is published as-is
        if mode == RepositoryMode.FILTERED:
            published_metadata = self._filter_and_regenerate_updateinfo(
                packages, repodata_path, published_metadata
            )
            published_metadata = self._filter_and_regenerate_filelists(
                packages, repodata_path, published_metadata
            )
            published_metadata = self._filter_and_regenerate_other(
                packages, repodata_path, published_metadata
            )

        # Generate primary.xml (always generated)
        primary_xml_path = self._generate_primary_xml(packages, repodata_path, compression)

        # Add primary to published metadata list
        published_metadata.append(("primary", primary_xml_path))

        # Generate repomd.xml with all metadata entries
        self._generate_repomd_xml(repodata_path, published_metadata)

        # Publish kickstart/installer files
        kickstart_files = [rf for rf in repository_files if rf.file_category == "kickstart"]

        if kickstart_files:
            self._publish_kickstart_files(kickstart_files, target_path)

    def _detect_upstream_compression(
        self, repository_files: list[RepositoryFile]
    ) -> CompressionFormat:
        """Detect compression format used in upstream repository.

        Args:
            repository_files: List of repository files from upstream

        Returns:
            Detected compression format (defaults to gzip if not detected)
        """
        # Check primary metadata file
        for rf in repository_files:
            if rf.file_type == "primary":
                from chantal.plugins.rpm.compression import detect_compression

                detected = detect_compression(rf.relative_path)
                if detected and detected != "none":
                    return detected
        # Fallback to gzip
        return "gzip"

    def _generate_primary_xml(
        self,
        packages: list[ContentItem],
        repodata_path: Path,
        compression: CompressionFormat = "gzip",
    ) -> Path:
        """Generate primary.xml metadata file with configurable compression.

        Args:
            packages: List of content items
            repodata_path: Path to repodata directory
            compression: Compression format (gzip, zstandard, bzip2, none)

        Returns:
            Path to generated primary.xml file (with compression)
        """
        # Create primary.xml
        metadata = ET.Element("metadata")
        metadata.set("xmlns", "http://linux.duke.edu/metadata/common")
        metadata.set("xmlns:rpm", "http://linux.duke.edu/metadata/rpm")
        metadata.set("packages", str(len(packages)))

        for package in packages:
            pkg_elem = ET.SubElement(metadata, "package")
            pkg_elem.set("type", "rpm")

            # Basic info
            name = ET.SubElement(pkg_elem, "name")
            name.text = package.name

            arch = ET.SubElement(pkg_elem, "arch")
            arch.text = package.content_metadata.get("arch", "")

            # Version
            version = ET.SubElement(pkg_elem, "version")
            epoch = package.content_metadata.get("epoch")
            if epoch:
                version.set("epoch", epoch)
            version.set("ver", package.version)
            release = package.content_metadata.get("release")
            if release:
                version.set("rel", release)

            # Checksum
            checksum = ET.SubElement(pkg_elem, "checksum")
            checksum.set("type", "sha256")
            checksum.set("pkgid", "YES")
            checksum.text = package.sha256

            # Summary
            summary_text = package.content_metadata.get("summary")
            if summary_text:
                summary = ET.SubElement(pkg_elem, "summary")
                summary.text = summary_text

            # Description
            description_text = package.content_metadata.get("description")
            if description_text:
                description = ET.SubElement(pkg_elem, "description")
                description.text = description_text

            # Location
            location = ET.SubElement(pkg_elem, "location")
            location.set("href", f"Packages/{package.filename}")

            # Size
            size = ET.SubElement(pkg_elem, "size")
            size.set("package", str(package.size_bytes))

            # Time (use current time for now)
            time_elem = ET.SubElement(pkg_elem, "time")
            time_elem.set("file", str(int(datetime.utcnow().timestamp())))

        # Write XML
        tree = ET.ElementTree(metadata)
        primary_xml_path = repodata_path / "primary.xml"

        # Pretty print XML
        ET.indent(tree, space="  ")
        tree.write(primary_xml_path, encoding="UTF-8", xml_declaration=True)

        # Compress with configured format
        compressed_filename = add_compression_extension("primary.xml", compression)
        primary_xml_compressed_path = repodata_path / compressed_filename

        with open(primary_xml_path, "rb") as f_in:
            xml_data = f_in.read()
            compressed_data = compress_file(xml_data, compression)

        with open(primary_xml_compressed_path, "wb") as f_out:
            f_out.write(compressed_data)

        # Remove uncompressed version
        primary_xml_path.unlink()

        return primary_xml_compressed_path

    def _publish_metadata_files(
        self, repository_files: list[RepositoryFile], repodata_path: Path
    ) -> list[tuple[str, Path]]:
        """Create hardlinks for repository metadata files.

        Args:
            repository_files: List of RepositoryFile instances
            repodata_path: Path to repodata directory

        Returns:
            List of tuples (file_type, published_path) for each published file
        """
        published = []

        for repo_file in repository_files:
            # Only publish metadata files (not kickstart, etc.)
            if repo_file.file_category != "metadata":
                continue

            # Get pool path
            pool_file_path = self.storage.pool_path / repo_file.pool_path

            if not pool_file_path.exists():
                print(f"Warning: Pool file not found: {pool_file_path}")
                continue

            # Extract filename
            filename = Path(repo_file.original_path).name

            # Target path in repodata/
            target_path = repodata_path / filename

            # Create hardlink
            if target_path.exists():
                target_path.unlink()

            import os

            os.link(pool_file_path, target_path)

            # Add to published list
            published.append((repo_file.file_type, target_path))

        return published

    def _publish_kickstart_files(
        self, kickstart_files: list[RepositoryFile], target_path: Path
    ) -> None:
        """Publish kickstart/installer files to images/ directory.

        Args:
            kickstart_files: List of RepositoryFile with file_category="kickstart"
            target_path: Target directory for publishing
        """
        import os

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

            os.link(pool_file_path, target_file_path)

            print(f"  ✓ Published {repo_file.file_type}: {repo_file.original_path}")

    def _generate_repomd_xml(
        self, repodata_path: Path, metadata_files: list[tuple[str, Path]]
    ) -> Path:
        """Generate repomd.xml root metadata file.

        Args:
            repodata_path: Path to repodata directory
            metadata_files: List of (file_type, file_path) tuples for all metadata

        Returns:
            Path to generated repomd.xml
        """
        # Create repomd.xml
        repomd = ET.Element("repomd")
        repomd.set("xmlns", "http://linux.duke.edu/metadata/repo")
        repomd.set("xmlns:rpm", "http://linux.duke.edu/metadata/rpm")

        # Revision (timestamp)
        revision = ET.SubElement(repomd, "revision")
        revision.text = str(int(datetime.utcnow().timestamp()))

        # Add data entry for each metadata file
        for file_type, file_path in metadata_files:
            # Calculate checksum and size of compressed file
            with open(file_path, "rb") as f:
                file_data = f.read()
                file_sha256 = hashlib.sha256(file_data).hexdigest()
                file_size = len(file_data)

            # Calculate checksum of uncompressed file (if compressed)
            try:
                if file_path.suffix == ".gz":
                    with gzip.open(file_path, "rb") as f:
                        open_data = f.read()
                        open_sha256 = hashlib.sha256(open_data).hexdigest()
                        open_size = len(open_data)
                elif file_path.suffix == ".zst":
                    import zstandard as zstd

                    dctx = zstd.ZstdDecompressor()
                    open_data = dctx.decompress(file_data)
                    open_sha256 = hashlib.sha256(open_data).hexdigest()
                    open_size = len(open_data)
                elif file_path.suffix == ".bz2":
                    open_data = bz2.decompress(file_data)
                    open_sha256 = hashlib.sha256(open_data).hexdigest()
                    open_size = len(open_data)
                else:
                    # Not compressed
                    open_sha256 = file_sha256
                    open_size = file_size
            except Exception:
                # If decompression fails, use compressed values
                open_sha256 = file_sha256
                open_size = file_size

            # Create data entry
            data = ET.SubElement(repomd, "data")
            data.set("type", file_type)

            checksum = ET.SubElement(data, "checksum")
            checksum.set("type", "sha256")
            checksum.text = file_sha256

            open_checksum = ET.SubElement(data, "open-checksum")
            open_checksum.set("type", "sha256")
            open_checksum.text = open_sha256

            location = ET.SubElement(data, "location")
            location.set("href", f"repodata/{file_path.name}")

            timestamp = ET.SubElement(data, "timestamp")
            timestamp.text = str(int(datetime.utcnow().timestamp()))

            size = ET.SubElement(data, "size")
            size.text = str(file_size)

            open_size_elem = ET.SubElement(data, "open-size")
            open_size_elem.text = str(open_size)

        # Write repomd.xml
        tree = ET.ElementTree(repomd)
        repomd_xml_path = repodata_path / "repomd.xml"

        # Pretty print XML
        ET.indent(tree, space="  ")
        tree.write(repomd_xml_path, encoding="UTF-8", xml_declaration=True)

        return repomd_xml_path

    def _filter_and_regenerate_updateinfo(
        self,
        packages: list[ContentItem],
        repodata_path: Path,
        published_metadata: list[tuple[str, Path]],
    ) -> list[tuple[str, Path]]:
        """Filter and regenerate updateinfo.xml based on available packages.

        Args:
            packages: List of available ContentItem packages
            repodata_path: Path to repodata directory
            published_metadata: List of (file_type, file_path) tuples

        Returns:
            Updated list of (file_type, file_path) tuples with filtered updateinfo
        """
        # Find updateinfo in published metadata
        updateinfo_entry = None
        updateinfo_index = None

        for i, (file_type, file_path) in enumerate(published_metadata):
            if file_type == "updateinfo":
                updateinfo_entry = (file_type, file_path)
                updateinfo_index = i
                break

        if not updateinfo_entry:
            # No updateinfo to filter
            return published_metadata

        updateinfo_path = updateinfo_entry[1]

        try:
            # Parse updateinfo
            parser = UpdateInfoParser()
            updates = parser.parse_file(updateinfo_path)

            # Build set of available package NVRAs
            available_nvras = self._build_package_nvra_set(packages)

            # Filter updates
            filter_obj = UpdateInfoFilter()
            filtered_updates = filter_obj.filter_updates(updates, available_nvras)

            print(
                f"Filtered updateinfo: {len(updates)} → {len(filtered_updates)} updates "
                f"(removed {len(updates) - len(filtered_updates)} unavailable)"
            )

            # Generate new updateinfo.xml
            generator = UpdateInfoGenerator()
            filtered_xml = generator.generate_xml(filtered_updates)

            # Write filtered XML to temp file
            import tempfile

            with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".xml") as tmp_f:
                tmp_f.write(filtered_xml)
                tmp_xml_path = Path(tmp_f.name)

            # Compress it
            filtered_updateinfo_path = repodata_path / updateinfo_path.name

            # Determine compression based on extension
            if updateinfo_path.suffix == ".bz2":
                with open(tmp_xml_path, "rb") as f_in:
                    with bz2.open(filtered_updateinfo_path, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
            elif updateinfo_path.suffix == ".gz":
                with open(tmp_xml_path, "rb") as f_in:
                    with gzip.open(filtered_updateinfo_path, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
            elif updateinfo_path.suffix == ".zst":
                import zstandard as zstd

                with open(tmp_xml_path, "rb") as f_in:
                    xml_data = f_in.read()
                    cctx = zstd.ZstdCompressor()
                    compressed_data = cctx.compress(xml_data)

                with open(filtered_updateinfo_path, "wb") as f_out:
                    f_out.write(compressed_data)
            else:
                # No compression
                shutil.copy(tmp_xml_path, filtered_updateinfo_path)

            # Clean up temp file
            tmp_xml_path.unlink()

            # Replace in published_metadata list
            updated_metadata = published_metadata.copy()
            updated_metadata[updateinfo_index] = ("updateinfo", filtered_updateinfo_path)

            return updated_metadata

        except Exception as e:
            print(f"Warning: Failed to filter updateinfo: {e}")
            # Return original metadata if filtering fails
            return published_metadata

    def _build_package_nvra_set(self, packages: list[ContentItem]) -> set[str]:
        """Build set of package NVRAs for filtering.

        Args:
            packages: List of ContentItem packages

        Returns:
            Set of NVRA strings (name-version-release.arch)
        """
        nvras = set()

        for pkg in packages:
            name = pkg.name
            version = pkg.version
            release = pkg.content_metadata.get("release", "")
            arch = pkg.content_metadata.get("arch", "")

            if name and version and release and arch:
                nvra = f"{name}-{version}-{release}.{arch}"
                nvras.add(nvra)

        return nvras

    def _build_package_pkgid_set(self, packages: list[ContentItem]) -> set[str]:
        """Build set of package IDs (SHA256) for filtering.

        Args:
            packages: List of ContentItem packages

        Returns:
            Set of pkgid strings (SHA256 checksums)
        """
        return {pkg.sha256 for pkg in packages}

    def _filter_and_regenerate_filelists(
        self,
        packages: list[ContentItem],
        repodata_path: Path,
        published_metadata: list[tuple[str, Path]],
    ) -> list[tuple[str, Path]]:
        """Filter and regenerate filelists.xml based on available packages.

        Args:
            packages: List of available ContentItem packages
            repodata_path: Path to repodata directory
            published_metadata: List of (file_type, file_path) tuples

        Returns:
            Updated list of (file_type, file_path) tuples with filtered filelists
        """
        # Find filelists in published metadata
        filelists_entry = None
        filelists_index = None

        for i, (file_type, file_path) in enumerate(published_metadata):
            if file_type == "filelists":
                filelists_entry = (file_type, file_path)
                filelists_index = i
                break

        if not filelists_entry:
            # No filelists to filter
            return published_metadata

        filelists_path = filelists_entry[1]

        try:
            # Build set of available package IDs
            available_pkgids = self._build_package_pkgid_set(packages)

            # Parse and filter filelists.xml
            import lzma
            import xml.etree.ElementTree as ET

            # Decompress based on extension
            if filelists_path.suffix == ".xz":
                with lzma.open(filelists_path, "rb") as f:
                    tree = ET.parse(f)
            elif filelists_path.suffix == ".bz2":
                with bz2.open(filelists_path, "rb") as f:
                    tree = ET.parse(f)
            elif filelists_path.suffix == ".gz":
                with gzip.open(filelists_path, "rb") as f:
                    tree = ET.parse(f)
            elif filelists_path.suffix == ".zst":
                import io

                import zstandard as zstd

                with open(filelists_path, "rb") as f:
                    dctx = zstd.ZstdDecompressor()
                    decompressed = dctx.decompress(f.read())
                    tree = ET.parse(io.BytesIO(decompressed))
            else:
                tree = ET.parse(filelists_path)

            root = tree.getroot()
            original_count = int(root.get("packages", "0"))

            # Filter packages by pkgid
            packages_to_remove = []
            for package_elem in root.findall("{http://linux.duke.edu/metadata/filelists}package"):
                pkgid = package_elem.get("pkgid")
                if pkgid not in available_pkgids:
                    packages_to_remove.append(package_elem)

            for package_elem in packages_to_remove:
                root.remove(package_elem)

            # Update package count
            filtered_count = len(root.findall("{http://linux.duke.edu/metadata/filelists}package"))
            root.set("packages", str(filtered_count))

            print(
                f"Filtered filelists: {original_count} → {filtered_count} packages "
                f"(removed {original_count - filtered_count} unavailable)"
            )

            # Write filtered XML to temp file
            import tempfile

            with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".xml") as tmp_f:
                tree.write(tmp_f, encoding="UTF-8", xml_declaration=True)
                tmp_xml_path = Path(tmp_f.name)

            # Compress it
            filtered_filelists_path = repodata_path / filelists_path.name

            # Determine compression based on extension
            if filelists_path.suffix == ".xz":
                with open(tmp_xml_path, "rb") as f_in:
                    with lzma.open(filtered_filelists_path, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
            elif filelists_path.suffix == ".bz2":
                with open(tmp_xml_path, "rb") as f_in:
                    with bz2.open(filtered_filelists_path, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
            elif filelists_path.suffix == ".gz":
                with open(tmp_xml_path, "rb") as f_in:
                    with gzip.open(filtered_filelists_path, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
            elif filelists_path.suffix == ".zst":
                import zstandard as zstd

                with open(tmp_xml_path, "rb") as f_in:
                    xml_data = f_in.read()
                    cctx = zstd.ZstdCompressor()
                    compressed_data = cctx.compress(xml_data)

                with open(filtered_filelists_path, "wb") as f_out:
                    f_out.write(compressed_data)
            else:
                # No compression
                shutil.copy(tmp_xml_path, filtered_filelists_path)

            # Clean up temp file
            tmp_xml_path.unlink()

            # Replace in published_metadata list
            updated_metadata = published_metadata.copy()
            updated_metadata[filelists_index] = ("filelists", filtered_filelists_path)

            return updated_metadata

        except Exception as e:
            print(f"Warning: Failed to filter filelists: {e}")
            # Return original metadata if filtering fails
            return published_metadata

    def _filter_and_regenerate_other(
        self,
        packages: list[ContentItem],
        repodata_path: Path,
        published_metadata: list[tuple[str, Path]],
    ) -> list[tuple[str, Path]]:
        """Filter and regenerate other.xml based on available packages.

        Args:
            packages: List of available ContentItem packages
            repodata_path: Path to repodata directory
            published_metadata: List of (file_type, file_path) tuples

        Returns:
            Updated list of (file_type, file_path) tuples with filtered other
        """
        # Find other in published metadata
        other_entry = None
        other_index = None

        for i, (file_type, file_path) in enumerate(published_metadata):
            if file_type == "other":
                other_entry = (file_type, file_path)
                other_index = i
                break

        if not other_entry:
            # No other to filter
            return published_metadata

        other_path = other_entry[1]

        try:
            # Build set of available package IDs
            available_pkgids = self._build_package_pkgid_set(packages)

            # Parse and filter other.xml
            import lzma
            import xml.etree.ElementTree as ET

            # Decompress based on extension
            if other_path.suffix == ".xz":
                with lzma.open(other_path, "rb") as f:
                    tree = ET.parse(f)
            elif other_path.suffix == ".bz2":
                with bz2.open(other_path, "rb") as f:
                    tree = ET.parse(f)
            elif other_path.suffix == ".gz":
                with gzip.open(other_path, "rb") as f:
                    tree = ET.parse(f)
            elif other_path.suffix == ".zst":
                import io

                import zstandard as zstd

                with open(other_path, "rb") as f:
                    dctx = zstd.ZstdDecompressor()
                    decompressed = dctx.decompress(f.read())
                    tree = ET.parse(io.BytesIO(decompressed))
            else:
                tree = ET.parse(other_path)

            root = tree.getroot()
            original_count = int(root.get("packages", "0"))

            # Filter packages by pkgid
            packages_to_remove = []
            for package_elem in root.findall("{http://linux.duke.edu/metadata/other}package"):
                pkgid = package_elem.get("pkgid")
                if pkgid not in available_pkgids:
                    packages_to_remove.append(package_elem)

            for package_elem in packages_to_remove:
                root.remove(package_elem)

            # Update package count
            filtered_count = len(root.findall("{http://linux.duke.edu/metadata/other}package"))
            root.set("packages", str(filtered_count))

            print(
                f"Filtered other: {original_count} → {filtered_count} packages "
                f"(removed {original_count - filtered_count} unavailable)"
            )

            # Write filtered XML to temp file
            import tempfile

            with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".xml") as tmp_f:
                tree.write(tmp_f, encoding="UTF-8", xml_declaration=True)
                tmp_xml_path = Path(tmp_f.name)

            # Compress it
            filtered_other_path = repodata_path / other_path.name

            # Determine compression based on extension
            if other_path.suffix == ".xz":
                with open(tmp_xml_path, "rb") as f_in:
                    with lzma.open(filtered_other_path, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
            elif other_path.suffix == ".bz2":
                with open(tmp_xml_path, "rb") as f_in:
                    with bz2.open(filtered_other_path, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
            elif other_path.suffix == ".gz":
                with open(tmp_xml_path, "rb") as f_in:
                    with gzip.open(filtered_other_path, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
            elif other_path.suffix == ".zst":
                import zstandard as zstd

                with open(tmp_xml_path, "rb") as f_in:
                    xml_data = f_in.read()
                    cctx = zstd.ZstdCompressor()
                    compressed_data = cctx.compress(xml_data)

                with open(filtered_other_path, "wb") as f_out:
                    f_out.write(compressed_data)
            else:
                # No compression
                shutil.copy(tmp_xml_path, filtered_other_path)

            # Clean up temp file
            tmp_xml_path.unlink()

            # Replace in published_metadata list
            updated_metadata = published_metadata.copy()
            updated_metadata[other_index] = ("other", filtered_other_path)

            return updated_metadata

        except Exception as e:
            print(f"Warning: Failed to filter other: {e}")
            # Return original metadata if filtering fails
            return published_metadata
