from __future__ import annotations

"""
APT/DEB repository publisher plugin.

This module implements publishing for APT repositories with Debian package metadata.
"""

import gzip
import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from chantal.core.config import RepositoryConfig
from chantal.core.storage import StorageManager
from chantal.db.models import ContentItem, Repository, RepositoryFile, RepositoryMode, Snapshot
from chantal.plugins.base import PublisherPlugin


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
        repository_files: list[RepositoryFile] = None,
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

        # Group packages by component and architecture
        packages_by_component_arch = self._group_packages_by_component_arch(packages)

        # Publish packages for each component/architecture combination
        published_metadata = []
        for (component, architecture), component_packages in packages_by_component_arch.items():
            # Create component/arch directory
            if architecture == "source":
                component_arch_path = dists_path / component / "source"
            else:
                component_arch_path = dists_path / component / f"binary-{architecture}"

            component_arch_path.mkdir(parents=True, exist_ok=True)

            # Create hardlinks for packages in this component/arch
            self._create_package_hardlinks(
                component_packages, component_arch_path, component, architecture
            )

            # Generate Packages file
            packages_file = self._generate_packages_file(
                component_packages, component_arch_path, component, architecture
            )

            published_metadata.append(
                {
                    "component": component,
                    "architecture": architecture,
                    "packages_file": packages_file,
                }
            )

        # In mirror mode, publish all metadata files (Release, InRelease, etc.)
        if mode == RepositoryMode.MIRROR:
            self._publish_metadata_files(repository_files, dists_path)

        # Generate Release file (always generated, even in mirror mode for completeness)
        self._generate_release_file(dists_path, published_metadata, repository_files, mode)

    def _group_packages_by_component_arch(
        self, packages: list[ContentItem]
    ) -> dict[tuple[str, str], list[ContentItem]]:
        """Group packages by component and architecture.

        Args:
            packages: List of content items

        Returns:
            Dictionary mapping (component, architecture) to list of packages
        """
        grouped = {}

        for package in packages:
            component = package.content_metadata.get("component", "main")
            architecture = package.content_metadata.get("architecture", "amd64")

            key = (component, architecture)
            if key not in grouped:
                grouped[key] = []

            grouped[key].append(package)

        return grouped

    def _create_package_hardlinks(
        self,
        packages: list[ContentItem],
        component_arch_path: Path,
        component: str,
        architecture: str,
    ) -> None:
        """Create hardlinks for packages in component/arch directory.

        Args:
            packages: List of content items
            component_arch_path: Path to component/architecture directory
            component: Component name
            architecture: Architecture name
        """
        import os

        for package in packages:
            # Get pool path
            pool_file_path = self.storage.pool_path / package.pool_path

            if not pool_file_path.exists():
                print(f"Warning: Pool file not found: {pool_file_path}")
                continue

            # Target path: dists/SUITE/COMPONENT/binary-ARCH/FILENAME
            target_file_path = component_arch_path / package.filename

            # Create hardlink
            if target_file_path.exists():
                target_file_path.unlink()

            os.link(pool_file_path, target_file_path)

    def _generate_packages_file(
        self,
        packages: list[ContentItem],
        component_arch_path: Path,
        component: str,
        architecture: str,
    ) -> Path:
        """Generate Packages file for component/architecture.

        Args:
            packages: List of content items
            component_arch_path: Path to component/architecture directory
            component: Component name
            architecture: Architecture name

        Returns:
            Path to generated Packages.gz file
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
            filename = f"{component}/binary-{architecture}/{package.filename}"
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

        # Gzip it
        packages_gz_path = component_arch_path / "Packages.gz"
        with open(packages_file_path, "rb") as f_in:
            with gzip.open(packages_gz_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

        print(
            f"  ✓ Generated Packages for {component}/{architecture}: " f"{len(packages)} packages"
        )

        return packages_gz_path

    def _publish_metadata_files(
        self, repository_files: list[RepositoryFile], dists_path: Path
    ) -> None:
        """Create hardlinks for repository metadata files.

        Args:
            repository_files: List of RepositoryFile instances
            dists_path: Path to dists/SUITE directory
        """
        import os

        for repo_file in repository_files:
            # Only publish metadata files
            if repo_file.file_category != "metadata":
                continue

            # Get pool path
            pool_file_path = self.storage.pool_path / repo_file.pool_path

            if not pool_file_path.exists():
                print(f"Warning: Pool file not found: {pool_file_path}")
                continue

            # Determine target path based on original_path
            # original_path is like "dists/jammy/Release" or "dists/jammy/main/binary-amd64/Packages.gz"
            # We need to extract the path relative to dists/SUITE/

            original_path = Path(repo_file.original_path)

            # Remove "dists/SUITE/" prefix to get relative path
            # Example: "dists/jammy/Release" -> "Release"
            # Example: "dists/jammy/main/binary-amd64/Packages.gz" -> "main/binary-amd64/Packages.gz"
            parts = original_path.parts

            if len(parts) >= 3 and parts[0] == "dists":
                # Skip "dists" and suite name
                relative_parts = parts[2:]
                relative_path = Path(*relative_parts) if relative_parts else Path(".")
            else:
                # Fallback: just use the filename
                relative_path = Path(original_path.name)

            # Target path
            target_path = dists_path / relative_path

            # Create parent directories
            target_path.parent.mkdir(parents=True, exist_ok=True)

            # Create hardlink
            if target_path.exists():
                target_path.unlink()

            os.link(pool_file_path, target_path)

            print(f"  ✓ Published {repo_file.file_type}: {relative_path}")

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

        # Origin and Label
        release_lines.append("Origin: Chantal")
        release_lines.append(f"Label: {self.config.name}")

        # Suite and Codename
        release_lines.append(f"Suite: {self.apt_config.distribution}")
        release_lines.append(f"Codename: {self.apt_config.distribution}")

        # Date
        now = datetime.now(timezone.utc)
        # Format: "Thu, 12 Jan 2026 10:30:45 UTC"
        date_str = now.strftime("%a, %d %b %Y %H:%M:%S UTC")
        release_lines.append(f"Date: {date_str}")

        # Architectures
        architectures = sorted(
            set(
                meta["architecture"]
                for meta in published_metadata
                if meta["architecture"] != "source"
            )
        )
        if architectures:
            release_lines.append(f"Architectures: {' '.join(architectures)}")

        # Components
        components = sorted(set(meta["component"] for meta in published_metadata))
        if components:
            release_lines.append(f"Components: {' '.join(components)}")

        # Description
        release_lines.append(f"Description: {self.config.name}")

        # Build file checksums
        md5sums = []
        sha1sums = []
        sha256sums = []

        # Collect all Packages and Packages.gz files
        for meta in published_metadata:
            component = meta["component"]
            architecture = meta["architecture"]
            packages_gz_path = meta["packages_file"]

            # Get relative paths
            if architecture == "source":
                packages_rel = f"{component}/source/Packages"
                packages_gz_rel = f"{component}/source/Packages.gz"
            else:
                packages_rel = f"{component}/binary-{architecture}/Packages"
                packages_gz_rel = f"{component}/binary-{architecture}/Packages.gz"

            # Uncompressed Packages file
            packages_path = packages_gz_path.parent / "Packages"
            if packages_path.exists():
                packages_data = packages_path.read_bytes()
                packages_size = len(packages_data)
                packages_md5 = hashlib.md5(packages_data).hexdigest()
                packages_sha1 = hashlib.sha1(packages_data).hexdigest()
                packages_sha256 = hashlib.sha256(packages_data).hexdigest()

                md5sums.append(f" {packages_md5} {packages_size:8} {packages_rel}")
                sha1sums.append(f" {packages_sha1} {packages_size:8} {packages_rel}")
                sha256sums.append(f" {packages_sha256} {packages_size:8} {packages_rel}")

            # Compressed Packages.gz file
            if packages_gz_path.exists():
                packages_gz_data = packages_gz_path.read_bytes()
                packages_gz_size = len(packages_gz_data)
                packages_gz_md5 = hashlib.md5(packages_gz_data).hexdigest()
                packages_gz_sha1 = hashlib.sha1(packages_gz_data).hexdigest()
                packages_gz_sha256 = hashlib.sha256(packages_gz_data).hexdigest()

                md5sums.append(f" {packages_gz_md5} {packages_gz_size:8} {packages_gz_rel}")
                sha1sums.append(f" {packages_gz_sha1} {packages_gz_size:8} {packages_gz_rel}")
                sha256sums.append(f" {packages_gz_sha256} {packages_gz_size:8} {packages_gz_rel}")

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
