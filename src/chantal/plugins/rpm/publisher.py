from __future__ import annotations

"""
RPM/DNF repository publisher plugin.

This module implements publishing for RPM repositories with yum/dnf metadata.
"""

import hashlib
import shutil
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from sqlalchemy.orm import Session

from chantal.core.config import GpgConfig, RepositoryConfig
from chantal.core.gpg import GpgSigner, GpgSigningError
from chantal.core.storage import StorageManager
from chantal.db.models import ContentItem, Repository, RepositoryFile, RepositoryMode, Snapshot
from chantal.plugins.base import PublisherPlugin
from chantal.plugins.rpm.compression import (
    CompressionFormat,
    add_compression_extension,
    compress_file,
    open_decompressed,
)
from chantal.plugins.rpm.modules import (
    compress_bytes,
    decompress_bytes,
    filter_modules_yaml,
)
from chantal.plugins.rpm.updateinfo import (
    UpdateInfoFilter,
    UpdateInfoParser,
)
from chantal.plugins.rpm.xmlstream import filter_metadata_file

# Compression levels of the regenerated primary (same as compress_file()).
_PRIMARY_COMPRESSION_LEVELS: dict[str, int] = {"gzip": 6, "zstandard": 3, "bzip2": 9}


def _stream_digest(stream: BinaryIO) -> tuple[str, int]:
    """SHA256 hex digest and size of everything readable from ``stream``."""
    digest = hashlib.sha256()
    size = 0
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


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
                compression = compression_setting

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
            published_metadata = self._filter_and_regenerate_modules(
                packages, repodata_path, published_metadata
            )

        # Drop metadata variants we cannot republish correctly. zchunk (*_zck)
        # needs de-chunking to recompute its open-checksum (no pure-Python
        # support), so a regenerated repomd entry would be invalid in any mode;
        # the sqlite (*_db) primary/filelists/other enumerate the full upstream
        # package set, so they must not survive filtered mode (clients preferring
        # them would see excluded packages). dnf/yum fall back to primary.xml(.gz).
        published_metadata = self._drop_unpublishable_metadata(
            published_metadata, repodata_path, mode
        )

        # Produce exactly one primary.xml. Prefer regenerating it from the
        # upstream primary: that preserves the <format> block (provides /
        # requires / conflicts / obsoletes and the primary file list) that dnf
        # needs for dependency resolution, with each package <location> rewritten
        # to the republished Packages/ layout. Fall back to a minimal,
        # database-built primary only when there is no upstream primary
        # (e.g. hosted/upload-only repositories).
        published_metadata, regenerated = self._regenerate_primary(
            packages, repodata_path, mode, compression, published_metadata
        )
        if not regenerated:
            published_metadata = [m for m in published_metadata if m[0] != "primary"]
            primary_xml_path = self._generate_primary_xml(packages, repodata_path, compression)
            published_metadata.append(("primary", primary_xml_path))

        # Generate repomd.xml with all metadata entries
        repomd_path = self._generate_repomd_xml(repodata_path, published_metadata)

        # repomd.xml is regenerated in EVERY mode (the primary is relocated and
        # recompressed, with a fresh revision), so the upstream repomd.xml.asc
        # never matches what we publish - mirror mode included. Sign it ourselves
        # whenever a GPG key is configured so clients can use repo_gpgcheck=1 in
        # mirror mode too. Packages are never re-signed: they retain their
        # upstream signatures (verified via gpgcheck=1).
        if config is not None:
            gpg_config = config.gpg
            if gpg_config is not None and gpg_config.enabled:
                self._sign_repomd(repomd_path, target_path, gpg_config, config)

        # Publish the trusted upstream key(s) so downstream clients can verify
        # the mirrored packages (gpgcheck=1). Packages retain their upstream
        # signatures in both mirror and filtered mode, so this is mode-agnostic.
        if config is not None:
            self._publish_upstream_key(target_path, config)

        # Publish kickstart/installer files
        kickstart_files = [rf for rf in repository_files if rf.file_category == "kickstart"]

        if kickstart_files:
            self._publish_kickstart_files(kickstart_files, target_path)

    def _sign_repomd(
        self,
        repomd_path: Path,
        target_path: Path,
        gpg_config: GpgConfig,
        config: RepositoryConfig,
    ) -> None:
        """Sign repomd.xml with GPG (repomd.xml.asc + exported public key).

        Args:
            repomd_path: Path to the generated repomd.xml file.
            target_path: Repository root where the public key is published.
            gpg_config: GPG configuration.
            config: Repository configuration (used for the key's default name).
        """
        try:
            with GpgSigner(gpg_config, default_name=config.display_name) as signer:
                outputs = signer.sign_repomd(repomd_path, repo_root=target_path)
                print(f"  ✓ Signed repomd.xml with GPG key {signer.key_id}")
                for name in outputs:
                    print(f"  ✓ Published {name}")
        except GpgSigningError as exc:
            raise RuntimeError(f"GPG signing failed for repo '{config.id}': {exc}") from exc

    def _publish_upstream_key(self, target_path: Path, config: RepositoryConfig) -> None:
        """Write the trusted upstream public key(s) into the repository root.

        Downstream clients reference this file via ``gpgkey=`` to verify the
        mirrored packages, which keep their upstream signatures. The key material
        is the same trust anchor configured for sync-time verification
        (``verify.key_files`` + ``verify.keys``); it is written verbatim as a
        single (possibly multi-key) ASCII-armored file. No-op when verification
        is not configured, disabled, has no key material, or the filename is
        empty.

        Args:
            target_path: Repository root where the key file is written.
            config: Repository configuration (provides ``verify`` and ``id``).
        """
        verify = config.verify
        if verify is None or not verify.enabled:
            return

        key_name = (verify.client_key_name or "").replace("{repo_id}", config.id)
        if not key_name:
            # Publishing explicitly disabled.
            return

        # Confine the output to the repository tree (the literal name is also
        # validated in config, but config.id substitution is guarded here too).
        key_path = (target_path / key_name).resolve()
        if not key_path.is_relative_to(target_path.resolve()):
            raise ValueError(f"client_key_name escapes the repository root: {key_name!r}")

        # Avoid clobbering the metadata-signing public key published by
        # _sign_repomd (GpgConfig.public_key_name).
        gpg_config = config.gpg
        if gpg_config is not None and gpg_config.enabled:
            signing_key_path = (target_path / gpg_config.public_key_name).resolve()
            if key_path == signing_key_path:
                print(
                    f"  ! Skipping upstream key: client_key_name '{key_name}' collides with "
                    f"the metadata-signing key '{gpg_config.public_key_name}'"
                )
                return

        blocks: list[str] = []
        for key_file in verify.key_files:
            path = Path(key_file)
            if not path.is_file():
                raise FileNotFoundError(f"Trusted key file not found: {key_file}")
            text = path.read_text(encoding="utf-8").strip()
            if text:
                blocks.append(text)
        for inline in verify.keys:
            text = inline.strip()
            if text:
                blocks.append(text)

        if not blocks:
            return

        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_text("\n".join(blocks) + "\n", encoding="utf-8")
        print(f"  ✓ Published upstream trusted key {key_name}")

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

                detected = detect_compression(rf.original_path)
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
            time_elem.set("file", str(int(datetime.now(UTC).timestamp())))

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

    def _regenerate_primary(
        self,
        packages: list[ContentItem],
        repodata_path: Path,
        mode: str,
        compression: CompressionFormat,
        published_metadata: list[tuple[str, Path]],
    ) -> tuple[list[tuple[str, Path]], bool]:
        """Regenerate primary.xml from the upstream primary, preserving <format>.

        Filters the upstream primary to the published package set (filtered mode)
        and rewrites every package ``<location>`` to the republished ``Packages/``
        layout, keeping the ``<format>`` dependency metadata and file lists
        verbatim. The single regenerated primary replaces the upstream one in
        ``published_metadata`` so repomd.xml references exactly one primary.

        Returns ``(updated_metadata, True)`` on success, or
        ``(published_metadata, False)`` when there is no upstream primary to work
        from (the caller then builds a minimal primary from the database).
        """
        primary_index = next(
            (i for i, (ft, _) in enumerate(published_metadata) if ft == "primary"), None
        )
        if primary_index is None:
            return published_metadata, False

        primary_path = published_metadata[primary_index][1]
        common_ns = "http://linux.duke.edu/metadata/common"

        # Match published packages by NEVR+arch (checksum-independent, so it
        # works regardless of whether the upstream primary uses sha1/sha256/
        # sha512 pkgids).
        def _nevra_of_content(pkg: ContentItem) -> tuple[str, str, str, str]:
            meta = pkg.content_metadata or {}
            return (pkg.name, pkg.version, meta.get("release", ""), meta.get("arch", ""))

        kept = {_nevra_of_content(pkg) for pkg in packages}
        filename_by_nevra = {_nevra_of_content(pkg): pkg.filename for pkg in packages}

        def keep(pkg_elem: ET.Element) -> bool:
            name_elem = pkg_elem.find(f"{{{common_ns}}}name")
            version_elem = pkg_elem.find(f"{{{common_ns}}}version")
            arch_elem = pkg_elem.find(f"{{{common_ns}}}arch")
            nevra = (
                (name_elem.text or "") if name_elem is not None else "",
                version_elem.get("ver", "") if version_elem is not None else "",
                version_elem.get("rel", "") if version_elem is not None else "",
                (arch_elem.text or "") if arch_elem is not None else "",
            )

            if mode == RepositoryMode.FILTERED and nevra not in kept:
                return False

            # Rewrite <location> to the republished Packages/<filename> path.
            location = pkg_elem.find(f"{{{common_ns}}}location")
            if location is not None:
                href = location.get("href", "")
                filename = filename_by_nevra.get(nevra) or PurePosixPath(href).name
                location.set("href", f"Packages/{filename}")
            return True

        # Write the regenerated primary using the repository's configured
        # metadata compression (not necessarily the upstream's). Streamed: the
        # upstream primary of large repositories is >1 GB uncompressed.
        target = repodata_path / add_compression_extension("primary.xml", compression)
        try:
            original_count, kept_count = filter_metadata_file(
                primary_path,
                target,
                "package",
                keep,
                compression_level=_PRIMARY_COMPRESSION_LEVELS.get(compression),
            )
        except MemoryError:
            raise
        except Exception as e:  # noqa: BLE001 - fall back to DB-built primary
            print(f"Warning: failed to regenerate primary from upstream: {e}")
            return published_metadata, False

        # Safety net: if matching dropped everything (e.g. unexpected NEVRA
        # shape) but we do have packages, fall back to the database-built
        # primary rather than publishing an empty index.
        if kept_count == 0 and packages:
            if target != primary_path:
                target.unlink(missing_ok=True)
            return published_metadata, False

        removed = original_count - kept_count
        if removed:
            print(
                f"Filtered primary: {original_count} → {kept_count} packages "
                f"(removed {removed} unavailable)"
            )

        if target != primary_path:
            primary_path.unlink(missing_ok=True)  # drop the hardlinked upstream primary

        updated = published_metadata.copy()
        updated[primary_index] = ("primary", target)
        return updated, True

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

            self.storage.link_or_copy(pool_file_path, target_path)

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
                # original_path is taken verbatim from the upstream .treeinfo, so
                # confine it to the repository tree: a malicious entry like
                # "../../etc/cron.d/x" or an absolute path would otherwise hardlink
                # attacker-controlled content outside the published repo.
                target_file_path = (target_path / repo_file.original_path).resolve()
                if not target_file_path.is_relative_to(target_path.resolve()):
                    print(
                        f"Warning: skipping installer file with unsafe path: "
                        f"{repo_file.original_path!r}"
                    )
                    continue

            # Create parent directories
            target_file_path.parent.mkdir(parents=True, exist_ok=True)

            # Create hardlink
            if target_file_path.exists():
                target_file_path.unlink()

            self.storage.link_or_copy(pool_file_path, target_file_path)

            print(f"  ✓ Published {repo_file.file_type}: {repo_file.original_path}")

    def _drop_unpublishable_metadata(
        self,
        published_metadata: list[tuple[str, Path]],
        repodata_path: Path,
        mode: str,
    ) -> list[tuple[str, Path]]:
        """Drop metadata variants chantal cannot republish correctly.

        Both are dropped in *every* mode, because chantal regenerates primary.xml
        with each package ``<location>`` rewritten to the republished ``Packages/``
        layout in mirror mode too:

        - ``*_zck`` (zchunk): chantal cannot recompute the de-chunked
          open-checksum, so a repomd entry for it would be invalid.
        - ``*_db`` (sqlite primary/filelists/other): the sqlite still carries the
          upstream package locations (and, in filtered mode, the full upstream
          package set), so a sqlite-consuming client would resolve wrong/removed
          download URLs. chantal cannot rewrite sqlite, so drop it.

        dnf/yum fall back to ``primary.xml(.gz)``. The dropped files are unlinked
        from the published repodata so the repository does not carry metadata the
        repomd no longer references. (``mode`` is retained for signature parity
        with the other filter helpers.)
        """
        kept: list[tuple[str, Path]] = []
        for file_type, file_path in published_metadata:
            is_zck = file_type.endswith("_zck") or file_path.name.endswith(".zck")
            is_db = file_type.endswith("_db")
            if is_zck or is_db:
                file_path.unlink(missing_ok=True)
                continue
            kept.append((file_type, file_path))
        return kept

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
        revision.text = str(int(datetime.now(UTC).timestamp()))

        # Add data entry for each metadata file
        for file_type, file_path in metadata_files:
            # Calculate checksum and size of compressed file
            with open(file_path, "rb") as f:
                file_sha256, file_size = _stream_digest(f)

            # Checksum/size of the uncompressed payload. dnf decompresses the
            # metadata and verifies it against open-checksum/open-size, so this
            # must describe the decompressed bytes for every supported format
            # (gz/xz/bz2/zst); uncompressed files use the file values as-is.
            # Hashed as a stream: filelists of large repositories decompress to
            # well over a gigabyte.
            try:
                with open_decompressed(file_path) as stream:
                    open_sha256, open_size = _stream_digest(stream)
            except MemoryError:
                raise
            except Exception:
                # If decompression fails, fall back to the compressed values.
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
            timestamp.text = str(int(datetime.now(UTC).timestamp()))

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

        if not updateinfo_entry or updateinfo_index is None:
            # No updateinfo to filter
            return published_metadata

        updateinfo_path = updateinfo_entry[1]

        # Build set of available package NVRAs
        available_nvras = self._build_package_nvra_set(packages)
        parser = UpdateInfoParser()
        filter_obj = UpdateInfoFilter()

        def keep(update_elem: ET.Element) -> bool:
            try:
                update = parser.parse_update(update_elem)
            except Exception as e:
                print(f"Warning: Failed to parse update: {e}")
                return False
            return update is not None and bool(filter_obj.filter_updates([update], available_nvras))

        # Streamed: updateinfo of large repositories is hundreds of MB
        # uncompressed. Kept <update> elements are copied verbatim.
        filtered_updateinfo_path = repodata_path / updateinfo_path.name
        try:
            total, kept = filter_metadata_file(
                updateinfo_path, filtered_updateinfo_path, "update", keep, count_attr=None
            )
        except MemoryError:
            raise
        except Exception as e:
            print(f"Warning: Failed to filter updateinfo: {e}")
            # Return original metadata if filtering fails
            return published_metadata

        print(
            f"Filtered updateinfo: {total} → {kept} updates "
            f"(removed {total - kept} unavailable)"
        )

        # Replace in published_metadata list
        updated_metadata = published_metadata.copy()
        updated_metadata[updateinfo_index] = ("updateinfo", filtered_updateinfo_path)

        return updated_metadata

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

    @staticmethod
    def _package_elem_nvra(package_elem: ET.Element, ns: str) -> str | None:
        """NVRA of a filelists/other ``<package>`` element, or None if incomplete.

        filelists.xml/other.xml ``<package>`` carry ``name``/``arch`` attributes
        and a ``<version epoch ver rel/>`` child - the same fields used to build
        the surviving-package NVRA set, so matching is algorithm-agnostic (works
        for sha1/sha256/sha512 repos, unlike the pkgid checksum).
        """
        name = package_elem.get("name")
        arch = package_elem.get("arch")
        version_elem = package_elem.find(f"{{{ns}}}version")
        if version_elem is None or not name or not arch:
            return None
        ver = version_elem.get("ver")
        rel = version_elem.get("rel")
        if not ver or not rel:
            return None
        return f"{name}-{ver}-{rel}.{arch}"

    def _build_module_artifact_nevra_set(self, packages: list[ContentItem]) -> set[str]:
        """Build the modulemd-style NEVRA set used to filter ``modules.yaml``.

        modulemd ``data.artifacts.rpms`` entries are full NEVRAs with an
        explicit epoch: ``name-epoch:version-release.arch`` (epoch defaults to
        ``0`` when absent). This differs from :meth:`_build_package_nvra_set`,
        which omits the epoch.

        Args:
            packages: List of ContentItem packages

        Returns:
            Set of NEVRA strings in modulemd artifact form.
        """
        nevras = set()

        for pkg in packages:
            name = pkg.name
            version = pkg.version
            meta = pkg.content_metadata or {}
            release = meta.get("release", "")
            arch = meta.get("arch", "")
            epoch = meta.get("epoch")
            epoch_str = str(epoch) if epoch not in (None, "") else "0"

            if name and version and release and arch:
                nevras.add(f"{name}-{epoch_str}:{version}-{release}.{arch}")

        return nevras

    def _filter_and_regenerate_modules(
        self,
        packages: list[ContentItem],
        repodata_path: Path,
        published_metadata: list[tuple[str, Path]],
    ) -> list[tuple[str, Path]]:
        """Filter ``modules.yaml`` (modulemd) to the published package set.

        Prunes each module stream's RPM artifacts to the packages actually
        published so downstream ``dnf module`` operations never reference a
        missing RPM. If every stream is pruned away, ``modules.yaml`` is dropped
        from the published set entirely.

        Args:
            packages: List of available ContentItem packages
            repodata_path: Path to repodata directory
            published_metadata: List of (file_type, file_path) tuples

        Returns:
            Updated list of (file_type, file_path) tuples.
        """
        modules_index = None
        for i, (file_type, _file_path) in enumerate(published_metadata):
            if file_type == "modules":
                modules_index = i
                break

        if modules_index is None:
            # No modules.yaml in this repository (the common case).
            return published_metadata

        modules_path = published_metadata[modules_index][1]

        try:
            available_nevras = self._build_module_artifact_nevra_set(packages)
            suffix = modules_path.suffix

            raw = decompress_bytes(modules_path.read_bytes(), suffix)
            filtered = filter_modules_yaml(raw, available_nevras)

            updated_metadata = published_metadata.copy()

            if filtered is None:
                # Nothing survived: drop modules.yaml so no dangling
                # <data type="modules"> block is written.
                modules_path.unlink(missing_ok=True)
                updated_metadata.pop(modules_index)
                print("Filtered modules: all streams pruned; dropping modules.yaml")
                return updated_metadata

            filtered_modules_path = repodata_path / modules_path.name
            # The published file is a hardlink to the pool blob; remove it first
            # so we write a fresh inode instead of truncating the shared pool
            # file in place.
            filtered_modules_path.unlink(missing_ok=True)
            filtered_modules_path.write_bytes(compress_bytes(filtered, suffix))
            updated_metadata[modules_index] = ("modules", filtered_modules_path)
            print("Filtered modules: pruned module artifacts to published packages")
            return updated_metadata

        except Exception as e:
            # Unlike updateinfo/filelists/other (where extra entries are
            # harmless), an unfiltered modules.yaml would advertise module
            # artifacts for packages that were filtered out, breaking downstream
            # `dnf module` operations. Drop it rather than re-publish dangling
            # metadata.
            print(f"Warning: Failed to filter modules, dropping modules.yaml: {e}")
            modules_path.unlink(missing_ok=True)
            updated_metadata = published_metadata.copy()
            updated_metadata.pop(modules_index)
            return updated_metadata

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

        if not filelists_entry or filelists_index is None:
            # No filelists to filter
            return published_metadata

        return self._filter_package_metadata(
            "filelists", filelists_index, packages, repodata_path, published_metadata
        )

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

        if not other_entry or other_index is None:
            # No other to filter
            return published_metadata

        return self._filter_package_metadata(
            "other", other_index, packages, repodata_path, published_metadata
        )

    def _filter_package_metadata(
        self,
        file_type: str,
        index: int,
        packages: list[ContentItem],
        repodata_path: Path,
        published_metadata: list[tuple[str, Path]],
    ) -> list[tuple[str, Path]]:
        """Filter filelists/other (``published_metadata[index]``) to ``packages``.

        Streamed package by package: AppStream filelists decompress to almost
        2 GB. Packages are matched by NVRA (not pkgid): the pkgid is the package
        checksum in the repo's algorithm (sha1/sha256/sha512), which need not
        equal the locally-computed sha256 we store. NVRA matches the primary
        filter exactly, so primary and filelists/other always agree.
        """
        source_path = published_metadata[index][1]
        available_nvras = self._build_package_nvra_set(packages)

        def keep(package_elem: ET.Element) -> bool:
            ns = package_elem.tag[1:].split("}", 1)[0] if package_elem.tag.startswith("{") else ""
            nvra = self._package_elem_nvra(package_elem, ns)
            return nvra is not None and nvra in available_nvras

        # Same name as the published hardlink, which is replaced (not written
        # through to the pool blob).
        filtered_path = repodata_path / source_path.name
        try:
            original_count, filtered_count = filter_metadata_file(
                source_path, filtered_path, "package", keep
            )
        except MemoryError:
            raise
        except Exception as e:
            print(f"Warning: Failed to filter {file_type}: {e}")
            # Return original metadata if filtering fails
            return published_metadata

        print(
            f"Filtered {file_type}: {original_count} → {filtered_count} packages "
            f"(removed {original_count - filtered_count} unavailable)"
        )

        updated_metadata = published_metadata.copy()
        updated_metadata[index] = (file_type, filtered_path)
        return updated_metadata
