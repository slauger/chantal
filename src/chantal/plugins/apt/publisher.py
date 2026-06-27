from __future__ import annotations

"""
APT/DEB repository publisher plugin.

This module implements publishing for APT repositories with Debian package metadata.
"""

import hashlib
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

from sqlalchemy.orm import Session

from chantal.core.config import GpgConfig, RepositoryConfig
from chantal.core.storage import StorageManager
from chantal.db.models import ContentItem, Repository, RepositoryFile, RepositoryMode, Snapshot
from chantal.plugins.apt.gpg import GpgSigner, GpgSigningError
from chantal.plugins.base import PublisherPlugin
from chantal.plugins.rpm.compression import CompressionFormat, compress_file, get_extension

# Compressed Packages index variants that may exist in a component directory.
# Used when collecting checksums for the Release file.
_PACKAGES_VARIANTS = ("Packages", "Packages.gz", "Packages.xz", "Packages.zst", "Packages.bz2")

# Sources index variants (the source-package analog of _PACKAGES_VARIANTS).
_SOURCES_VARIANTS = ("Sources", "Sources.gz", "Sources.xz", "Sources.zst", "Sources.bz2")


class AptPublisher(PublisherPlugin):
    """Publisher for APT/DEB repositories.

    Creates standard APT repository structure:
    - dists/SUITE/COMPONENT/binary-ARCH/ - Package files
    - dists/SUITE/COMPONENT/binary-ARCH/Packages - Package metadata (RFC822)
    - dists/SUITE/COMPONENT/binary-ARCH/Packages.gz - Compressed metadata
    - dists/SUITE/Release - Release metadata
    - dists/SUITE/InRelease - GPG-signed Release (if available)
    """

    def __init__(self, storage: StorageManager, config: RepositoryConfig):
        """Initialize APT publisher.

        Args:
            storage: Storage manager instance
            config: Repository configuration
        """
        super().__init__(storage)
        self.config = config

        # Validate APT-specific config
        if not config.apt:
            raise ValueError(
                f"Repository '{config.id}' is type 'apt' but missing 'apt' configuration"
            )

        self.apt_config = config.apt

    def publish_repository(
        self,
        session: Session,
        repository: Repository,
        config: RepositoryConfig,
        target_path: Path,
    ) -> None:
        """Publish APT repository to target directory.

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
        self._publish_packages(packages, target_path, repository_files, repository.mode)

    def publish_snapshot(
        self,
        session: Session,
        snapshot: Snapshot,
        repository: Repository,
        config: RepositoryConfig,
        target_path: Path,
    ) -> None:
        """Publish APT snapshot to target directory.

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
        self._publish_packages(packages, target_path, repository_files, repository.mode)

    def unpublish(self, target_path: Path) -> None:
        """Remove published APT repository.

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
    ) -> None:
        """Publish content items and generate metadata.

        Args:
            packages: List of content items to publish
            target_path: Target directory
            repository_files: List of repository files (metadata) to publish
            mode: Repository mode (mirror/filtered/hosted)
        """
        if repository_files is None:
            repository_files = []

        # Create base directory structure
        target_path.mkdir(parents=True, exist_ok=True)
        dists_path = target_path / "dists" / self.apt_config.distribution
        dists_path.mkdir(parents=True, exist_ok=True)

        # Mirror mode is a byte-for-byte copy: place every package at its
        # upstream path and republish every metadata file (incl. the signed
        # Release/InRelease) verbatim. Nothing is regenerated or re-signed.
        if mode == RepositoryMode.MIRROR:
            self._publish_verbatim(packages, target_path, repository_files, dists_path)
            return

        # Group packages by component and architecture
        packages_by_component_arch = self._group_packages_by_component_arch(packages)

        # Resolve the compression format for generated Packages indices.
        compression = self._resolve_compression()

        # Publish packages for each component/architecture combination
        published_metadata = []
        for (component, architecture), component_packages in packages_by_component_arch.items():
            # Create component/arch directory
            if architecture == "source":
                component_arch_path = dists_path / component / "source"
            else:
                component_arch_path = dists_path / component / f"binary-{architecture}"

            component_arch_path.mkdir(parents=True, exist_ok=True)

            # Place the actual package files in the content pool (not under
            # dists/), so Filename:/Directory: resolve for a real apt client.
            self._link_packages_into_pool(component_packages, target_path, component)

            # Generate the index: Sources for the source group, Packages else.
            if architecture == "source":
                generated = self._generate_sources_file(
                    component_packages, component_arch_path, component, compression
                )
            else:
                generated = self._generate_packages_file(
                    component_packages, component_arch_path, component, architecture, compression
                )

            published_metadata.append(
                {
                    "component": component,
                    "architecture": architecture,
                    # Uncompressed Packages path; its parent is the component dir.
                    "packages_file": generated[0],
                }
            )

        # Generate Release from the regenerated indices (filtered/hosted mode;
        # mirror mode returned early with verbatim metadata).
        release_file = self._generate_release_file(
            dists_path, published_metadata, repository_files, mode
        )

        # In filtered/hosted mode the regenerated Release has no upstream
        # signature. Sign it ourselves when a GPG key is configured, else warn.
        if mode in (RepositoryMode.FILTERED, RepositoryMode.HOSTED):
            gpg_config = self.config.gpg
            if gpg_config is not None and gpg_config.enabled:
                self._sign_release(release_file, target_path, gpg_config)
            else:
                print(f"\n⚠️  WARNING: {mode} mode - Publishing without GPG signatures!")
                print("    Regenerating metadata based on the repository's packages.")
                print("    Clients must use [trusted=yes] or Acquire::AllowInsecureRepositories=1")
                print(
                    "    Example: deb [trusted=yes] http://mirror/ubuntu jammy main restricted universe multiverse"
                )
                print("    Configure a 'gpg' section to publish signed metadata instead.")

    def _resolve_compression(self) -> CompressionFormat:
        """Resolve the compression format for generated Packages indices.

        Honors ``config.metadata.compression``. For APT, ``auto`` falls back to
        gzip since Debian/Ubuntu repositories always provide a ``Packages.gz``.

        Returns:
            The compression format (gzip, zstandard, bzip2, or none).
        """
        setting = self.config.metadata.compression if self.config.metadata else "auto"
        if setting == "auto":
            return "gzip"
        return setting

    def _group_packages_by_component_arch(
        self, packages: list[ContentItem]
    ) -> dict[tuple[str, str], list[ContentItem]]:
        """Group packages by component and architecture.

        Args:
            packages: List of content items

        Returns:
            Dictionary mapping (component, architecture) to list of packages

        ``Architecture: all`` packages are fanned out into every configured
        per-arch index, because apt clients only read
        ``binary-<their-arch>/Packages`` — a lone ``binary-all`` index would
        leave arch-independent packages invisible to them.
        """
        grouped: dict[tuple[str, str], list[ContentItem]] = {}
        configured_arches = [a for a in self.apt_config.architectures if a != "all"]

        for package in packages:
            # Use `or` so an explicit None in the metadata still falls back.
            component = package.content_metadata.get("component") or "main"
            architecture = package.content_metadata.get("architecture") or "amd64"

            if architecture == "source":
                targets = ["source"]
            elif architecture == "all":
                # Duplicate into each real arch (fall back to binary-all only if
                # no concrete architecture is configured).
                targets = configured_arches or ["all"]
            else:
                targets = [architecture]

            for arch in targets:
                grouped.setdefault((component, arch), []).append(package)

        return grouped

    @staticmethod
    def _safe_name(name: str) -> str:
        """Neutralize path traversal in an upstream-controlled package name.

        Debian package names never contain path separators; a hostile or broken
        upstream ``Package:`` field must not be able to escape the pool via
        ``/`` or ``..`` once it flows into a filesystem path.
        """
        safe = PurePosixPath(name).name
        if not safe or safe.startswith("."):
            safe = "_" + safe
        return safe

    @staticmethod
    def _pool_prefix(name: str) -> str:
        """Debian pool prefix: ``libx`` for lib* packages, else the first letter."""
        if name.startswith("lib") and len(name) >= 4:
            return name[:4]
        return name[:1] or "_"

    def _pool_relpath(self, component: str, name: str, filename: str) -> str:
        """Repo-root-relative pool path: ``pool/<comp>/<prefix>/<name>/<file>``."""
        safe = self._safe_name(name)
        return f"pool/{self._safe_name(component)}/{self._pool_prefix(safe)}/{safe}/{Path(filename).name}"

    def _pool_dir(self, component: str, name: str) -> str:
        """Repo-root-relative pool directory (used as a source ``Directory:``)."""
        safe = self._safe_name(name)
        return f"pool/{self._safe_name(component)}/{self._pool_prefix(safe)}/{safe}"

    def _link_packages_into_pool(
        self,
        packages: list[ContentItem],
        target_path: Path,
        component: str,
    ) -> None:
        """Hardlink packages into the content pool (``<root>/pool/...``).

        Real apt repositories keep the actual .deb/source files in ``pool/`` at
        the repository root (referenced by ``Filename:``/``Directory:`` from the
        indices under ``dists/``), not inside ``dists/``. This makes the
        published repo installable by a real apt client. Idempotent: an
        ``Architecture: all`` package linked from several arch indices resolves
        to one pool file.
        """

        for package in packages:
            pool_file_path = self.storage.pool_path / package.pool_path
            if not pool_file_path.exists():
                print(f"Warning: Pool file not found: {pool_file_path}")
                continue

            target_file_path = target_path / self._pool_relpath(
                component, package.name, package.filename
            )
            # Defense in depth: never write outside the publish root.
            if not target_file_path.resolve().is_relative_to(target_path.resolve()):
                print(f"Warning: skipping package with unsafe pool path: {package.name!r}")
                continue
            target_file_path.parent.mkdir(parents=True, exist_ok=True)
            if target_file_path.exists():
                target_file_path.unlink()
            self.storage.link_or_copy(pool_file_path, target_file_path)

    def _upstream_rel_path(self, package: ContentItem) -> str | None:
        """Repo-root-relative path a package occupied upstream (for verbatim mirror).

        Returns None when the upstream path is unknown (legacy rows without the
        captured ``Filename:``); the caller then skips it rather than placing it
        at a guessed path the verbatim index would not reference.
        """
        meta = package.content_metadata or {}
        if package.content_type == "deb-source":
            directory = meta.get("directory") or ""
            return f"{directory}/{package.filename}" if directory else package.filename
        upstream = meta.get("filename")
        return str(upstream) if upstream else None

    def _link_verbatim(self, src: Path, dest: Path) -> None:
        """Hardlink ``src`` to ``dest`` (copying across filesystems)."""
        self.storage.link_or_copy(src, dest)

    def _publish_verbatim(
        self,
        packages: list[ContentItem],
        target_path: Path,
        repository_files: list[RepositoryFile],
        dists_path: Path,
    ) -> None:
        """Publish a byte-for-byte 1:1 mirror.

        Each package is placed at the upstream path it occupied (from the stored
        ``Filename:``/``Directory:``), and every stored metadata file — including
        the signed ``Release``/``InRelease`` — is republished verbatim. Nothing
        is regenerated or re-signed, so the upstream signatures stay valid (and
        may eventually expire, which is expected for a true mirror).
        """
        # Packages at their upstream paths.
        for package in packages:
            pool_file = self.storage.pool_path / package.pool_path
            if not pool_file.exists():
                print(f"Warning: Pool file not found: {pool_file}")
                continue
            rel = self._upstream_rel_path(package)
            if rel is None:
                print(f"Warning: no upstream path for {package.name!r}; skipping (verbatim)")
                continue
            dest = target_path / rel
            if not dest.resolve().is_relative_to(target_path.resolve()):
                print(f"Warning: skipping package with unsafe path: {package.name!r}")
                continue
            self._link_verbatim(pool_file, dest)

        # Every metadata/signature file verbatim under dists/<suite>/.
        for repo_file in repository_files:
            if repo_file.file_category not in ("metadata", "signature"):
                continue
            pool_file = self.storage.pool_path / repo_file.pool_path
            if not pool_file.exists():
                print(f"Warning: Pool file not found: {pool_file}")
                continue
            dest = dists_path / repo_file.original_path
            if not dest.resolve().is_relative_to(dists_path.resolve()):
                print(f"Warning: skipping metadata with unsafe path: {repo_file.original_path!r}")
                continue
            self._link_verbatim(pool_file, dest)

        gpg_config = self.config.gpg
        if gpg_config is not None and gpg_config.enabled:
            print("  ℹ Mirror mode: GPG signing skipped (upstream signatures preserved verbatim).")

        print(f"  ✓ Published verbatim mirror ({len(packages)} packages)")

    def _generate_packages_file(
        self,
        packages: list[ContentItem],
        component_arch_path: Path,
        component: str,
        architecture: str,
        compression: CompressionFormat = "gzip",
    ) -> list[Path]:
        """Generate Packages file(s) for component/architecture.

        Writes the uncompressed ``Packages`` file plus a compressed variant
        (unless ``compression`` is ``none``).

        Args:
            packages: List of content items
            component_arch_path: Path to component/architecture directory
            component: Component name
            architecture: Architecture name
            compression: Compression format for the compressed Packages index

        Returns:
            List of generated paths; the uncompressed ``Packages`` first,
            followed by the compressed variant (if any).
        """
        # Build Packages file content (RFC822 format)
        packages_content = []

        for package in packages:
            stanza = []

            # Package name
            stanza.append(f"Package: {package.name}")

            # Version
            stanza.append(f"Version: {package.version}")

            # Architecture
            arch = package.content_metadata.get("architecture", architecture)
            stanza.append(f"Architecture: {arch}")

            # Maintainer
            maintainer = package.content_metadata.get("maintainer", "")
            if maintainer:
                stanza.append(f"Maintainer: {maintainer}")

            # Installed-Size
            installed_size = package.content_metadata.get("installed_size", "")
            if installed_size:
                stanza.append(f"Installed-Size: {installed_size}")

            # Depends
            depends = package.content_metadata.get("depends", "")
            if depends:
                stanza.append(f"Depends: {depends}")

            # Pre-Depends
            pre_depends = package.content_metadata.get("pre_depends", "")
            if pre_depends:
                stanza.append(f"Pre-Depends: {pre_depends}")

            # Recommends
            recommends = package.content_metadata.get("recommends", "")
            if recommends:
                stanza.append(f"Recommends: {recommends}")

            # Suggests
            suggests = package.content_metadata.get("suggests", "")
            if suggests:
                stanza.append(f"Suggests: {suggests}")

            # Conflicts
            conflicts = package.content_metadata.get("conflicts", "")
            if conflicts:
                stanza.append(f"Conflicts: {conflicts}")

            # Replaces
            replaces = package.content_metadata.get("replaces", "")
            if replaces:
                stanza.append(f"Replaces: {replaces}")

            # Provides
            provides = package.content_metadata.get("provides", "")
            if provides:
                stanza.append(f"Provides: {provides}")

            # Section
            section = package.content_metadata.get("section", "")
            if section:
                stanza.append(f"Section: {section}")

            # Priority
            priority = package.content_metadata.get("priority", "")
            if priority:
                stanza.append(f"Priority: {priority}")

            # Homepage
            homepage = package.content_metadata.get("homepage", "")
            if homepage:
                stanza.append(f"Homepage: {homepage}")

            # Description
            description = package.content_metadata.get("description", "")
            if description:
                stanza.append(f"Description: {description}")

            # Filename (relative to dists/)
            filename = self._pool_relpath(component, package.name, package.filename)
            stanza.append(f"Filename: {filename}")

            # Size
            stanza.append(f"Size: {package.size_bytes}")

            # Checksums
            md5sum = package.content_metadata.get("md5sum", "")
            if md5sum:
                stanza.append(f"MD5sum: {md5sum}")

            sha1 = package.content_metadata.get("sha1", "")
            if sha1:
                stanza.append(f"SHA1: {sha1}")

            stanza.append(f"SHA256: {package.sha256}")

            # SHA512 (if available)
            sha512 = package.content_metadata.get("sha512", "")
            if sha512:
                stanza.append(f"SHA512: {sha512}")

            # Join stanza lines
            packages_content.append("\n".join(stanza))

        # Join all stanzas with blank lines
        full_content = "\n\n".join(packages_content)
        if full_content:
            full_content += "\n"

        # Write uncompressed Packages file
        packages_file_path = component_arch_path / "Packages"
        packages_file_path.write_text(full_content, encoding="utf-8")
        generated = [packages_file_path]

        # Write the compressed variant (unless disabled)
        if compression != "none":
            ext = get_extension(compression)
            compressed_path = component_arch_path / f"Packages{ext}"
            compressed_path.write_bytes(compress_file(packages_file_path.read_bytes(), compression))
            generated.append(compressed_path)

        print(
            f"  ✓ Generated Packages for {component}/{architecture}: "
            f"{len(packages)} packages ({compression})"
        )

        return generated

    def _generate_sources_file(
        self,
        packages: list[ContentItem],
        source_path: Path,
        component: str,
        compression: CompressionFormat = "gzip",
    ) -> list[Path]:
        """Generate a ``Sources`` index for source-package artifacts.

        Each source ``ContentItem`` is one artifact file; they are regrouped by
        (source package, source version) into one stanza listing all artifacts
        with their MD5/SHA1/SHA256 checksums.

        Returns:
            The generated paths; uncompressed ``Sources`` first, then the
            compressed variant (if any).
        """
        groups: dict[tuple[str, str], list[ContentItem]] = {}
        for pkg in packages:
            key = (
                pkg.content_metadata.get("source_package") or pkg.name,
                pkg.content_metadata.get("source_version") or pkg.version,
            )
            groups.setdefault(key, []).append(pkg)

        stanzas: list[str] = []
        for (src_name, src_version), artifacts in groups.items():
            meta = artifacts[0].content_metadata
            lines = [f"Package: {src_name}"]

            if meta.get("source_format"):
                lines.append(f"Format: {meta['source_format']}")
            binary = meta.get("binary") or []
            if binary:
                lines.append(f"Binary: {', '.join(binary)}")
            lines.append(f"Version: {src_version}")
            if meta.get("maintainer"):
                lines.append(f"Maintainer: {meta['maintainer']}")
            lines.append(f"Architecture: {meta.get('source_architecture') or 'any'}")
            if meta.get("priority"):
                lines.append(f"Priority: {meta['priority']}")
            if meta.get("section"):
                lines.append(f"Section: {meta['section']}")
            lines.append(f"Directory: {self._pool_dir(component, src_name)}")

            files_lines = []
            sha1_lines = []
            sha256_lines = []
            for art in sorted(artifacts, key=lambda a: a.filename):
                size = art.size_bytes
                amd5 = art.content_metadata.get("md5sum")
                asha1 = art.content_metadata.get("sha1")
                if amd5:
                    files_lines.append(f" {amd5} {size} {art.filename}")
                if asha1:
                    sha1_lines.append(f" {asha1} {size} {art.filename}")
                sha256_lines.append(f" {art.sha256} {size} {art.filename}")

            if files_lines:
                lines.append("Files:")
                lines.extend(files_lines)
            if sha1_lines:
                lines.append("Checksums-Sha1:")
                lines.extend(sha1_lines)
            if sha256_lines:
                lines.append("Checksums-Sha256:")
                lines.extend(sha256_lines)

            stanzas.append("\n".join(lines))

        full_content = "\n\n".join(stanzas)
        if full_content:
            full_content += "\n"

        sources_file_path = source_path / "Sources"
        sources_file_path.write_text(full_content, encoding="utf-8")
        generated = [sources_file_path]

        if compression != "none":
            ext = get_extension(compression)
            compressed_path = source_path / f"Sources{ext}"
            compressed_path.write_bytes(compress_file(sources_file_path.read_bytes(), compression))
            generated.append(compressed_path)

        print(
            f"  ✓ Generated Sources for {component}: {len(groups)} source packages ({compression})"
        )

        return generated

    def _emit_by_hash(
        self, file_path: Path, sha256_hex: str, emitted: dict[Path, set[str]]
    ) -> None:
        """Hardlink ``file_path`` into its sibling ``by-hash/SHA256/<sha>`` dir.

        apt fetches indices from these content-addressed copies so a mirror
        stays consistent while it is being updated. The emitted sha is recorded
        in ``emitted`` so stale entries can be pruned afterwards.
        """

        by_hash_dir = file_path.parent / "by-hash" / "SHA256"
        by_hash_dir.mkdir(parents=True, exist_ok=True)
        target = by_hash_dir / sha256_hex
        if target.exists():
            target.unlink()
        self.storage.link_or_copy(file_path, target)
        emitted.setdefault(by_hash_dir, set()).add(sha256_hex)

    def _prune_by_hash(self, emitted: dict[Path, set[str]]) -> None:
        """Remove by-hash entries left over from previous publishes.

        Content-addressed by-hash files are never overwritten in place, so a
        republish into an existing target would otherwise accumulate stale
        entries indefinitely.
        """
        for by_hash_dir, keep in emitted.items():
            for entry in by_hash_dir.iterdir():
                if entry.is_file() and entry.name not in keep:
                    entry.unlink()

    def _generate_release_file(
        self,
        dists_path: Path,
        published_metadata: list[dict],
        repository_files: list[RepositoryFile],
        mode: str,
    ) -> Path:
        """Generate Release file for the distribution.

        Args:
            dists_path: Path to dists/SUITE directory
            published_metadata: List of metadata info dicts
            repository_files: List of repository files
            mode: Repository mode

        Returns:
            Path to generated Release file
        """
        release_lines = []
        cfg = self.apt_config
        date_fmt = "%a, %d %b %Y %H:%M:%S UTC"

        # Origin and Label
        release_lines.append(f"Origin: {cfg.origin or 'Chantal'}")
        release_lines.append(f"Label: {cfg.label or self.config.name}")

        # Suite and Codename (distinct upstream values, e.g. 'stable' vs
        # 'bookworm'; default both to the configured distribution).
        release_lines.append(f"Suite: {cfg.suite or cfg.distribution}")
        release_lines.append(f"Codename: {cfg.codename or cfg.distribution}")

        # Date (and optional relative Valid-Until)
        now = datetime.now(UTC)
        date_str = now.strftime(date_fmt)
        release_lines.append(f"Date: {date_str}")
        if cfg.valid_until_days is not None:
            valid_until = now + timedelta(days=cfg.valid_until_days)
            release_lines.append(f"Valid-Until: {valid_until.strftime(date_fmt)}")

        # Apt pinning hints
        if cfg.not_automatic:
            release_lines.append("NotAutomatic: yes")
        if cfg.but_automatic_upgrades:
            release_lines.append("ButAutomaticUpgrades: yes")

        # Architectures
        architectures = sorted(
            {
                meta["architecture"]
                for meta in published_metadata
                if meta["architecture"] != "source"
            }
        )
        if architectures:
            release_lines.append(f"Architectures: {' '.join(architectures)}")

        # Components
        components = sorted({meta["component"] for meta in published_metadata})
        if components:
            release_lines.append(f"Components: {' '.join(components)}")

        # Description
        release_lines.append(f"Description: {self.config.name}")

        # Advertise by-hash availability for the indices listed below.
        if cfg.by_hash:
            release_lines.append("Acquire-By-Hash: yes")

        # Build file checksums
        by_hash = cfg.by_hash
        by_hash_emitted: dict[Path, set[str]] = {}
        md5sums = []
        sha1sums = []
        sha256sums = []

        # Collect checksums for the uncompressed Packages and every compressed
        # variant present in each component/architecture directory.
        for meta in published_metadata:
            component = meta["component"]
            architecture = meta["architecture"]
            component_dir = meta["packages_file"].parent

            if architecture == "source":
                rel_prefix = f"{component}/source"
                variants = _SOURCES_VARIANTS
            else:
                rel_prefix = f"{component}/binary-{architecture}"
                variants = _PACKAGES_VARIANTS

            for variant in variants:
                variant_path = component_dir / variant
                if not variant_path.exists():
                    continue

                data = variant_path.read_bytes()
                size = len(data)
                rel = f"{rel_prefix}/{variant}"

                sha = hashlib.sha256(data).hexdigest()
                md5sums.append(f" {hashlib.md5(data).hexdigest()} {size:8} {rel}")
                sha1sums.append(f" {hashlib.sha1(data).hexdigest()} {size:8} {rel}")
                sha256sums.append(f" {sha} {size:8} {rel}")
                if by_hash:
                    self._emit_by_hash(variant_path, sha, by_hash_emitted)

        if by_hash:
            self._prune_by_hash(by_hash_emitted)

        # Add checksum sections
        if md5sums:
            release_lines.append("MD5Sum:")
            release_lines.extend(md5sums)

        if sha1sums:
            release_lines.append("SHA1:")
            release_lines.extend(sha1sums)

        if sha256sums:
            release_lines.append("SHA256:")
            release_lines.extend(sha256sums)

        # Write Release file
        release_content = "\n".join(release_lines) + "\n"
        release_file_path = dists_path / "Release"
        release_file_path.write_text(release_content, encoding="utf-8")

        print("  ✓ Generated Release file")

        return release_file_path

    def _sign_release(
        self,
        release_file: Path,
        target_path: Path,
        gpg_config: GpgConfig,
    ) -> None:
        """Sign the Release file with GPG (InRelease, Release.gpg, public key).

        Args:
            release_file: Path to the generated Release file.
            target_path: Repository root where the public key is published.
            gpg_config: GPG configuration.
        """
        try:
            with GpgSigner(gpg_config, default_name=self.config.display_name) as signer:
                outputs = signer.sign_release(release_file, repo_root=target_path)
                print(f"  ✓ Signed Release with GPG key {signer.key_id}")
                for name in outputs:
                    print(f"  ✓ Published {name}")
        except GpgSigningError as exc:
            raise RuntimeError(f"GPG signing failed for repo '{self.config.id}': {exc}") from exc
