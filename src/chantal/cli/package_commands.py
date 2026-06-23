from __future__ import annotations

"""
CLI for uploading custom (local) packages into a repository's content pool.

Supports RPM (.rpm), APT (.deb) and Helm (.tgz) uploads into a hosted
(upload-only) repository. Uploaded packages are added to the content-addressed
pool and linked to the repository as ContentItems, so the existing publisher
includes them when it regenerates the repository metadata.
"""

from pathlib import Path
from typing import Any

import click
from sqlalchemy.orm import Session

from chantal.core.config import GlobalConfig, RepositoryConfig
from chantal.core.storage import StorageManager
from chantal.db.connection import DatabaseManager
from chantal.db.models import ContentItem, Repository
from chantal.plugins.apt.deb import parse_deb_control
from chantal.plugins.apt.models import DebMetadata
from chantal.plugins.helm.chart import parse_chart_metadata
from chantal.plugins.helm.models import HelmMetadata
from chantal.plugins.rpm.models import RpmMetadata
from chantal.plugins.rpm.rpm_header import parse_main_header


def _get_or_create_repository(session: Session, repo_config: RepositoryConfig) -> Repository:
    """Return the DB Repository for ``repo_config``, creating it if needed."""
    repository: Repository | None = (
        session.query(Repository).filter_by(repo_id=repo_config.id).first()
    )
    if repository is None:
        repository = Repository(
            repo_id=repo_config.id,
            name=repo_config.name or repo_config.id,
            type=repo_config.type,
            feed=repo_config.feed or "",  # hosted repos have no upstream feed
            enabled=repo_config.enabled,
            mode=repo_config.mode.upper(),
        )
        session.add(repository)
        session.commit()
    return repository


def _upload_rpm(
    session: Session, storage: StorageManager, repository: Repository, path: Path, force: bool
) -> str:
    """Add one local .rpm to the pool and link it to the repo.

    Returns "uploaded", "linked" (already in pool) or "replaced".
    """
    meta = parse_main_header(path.read_bytes())  # RpmFormatError if not an RPM
    name = meta.get("name")
    version = meta.get("version")
    release = meta.get("release")
    arch = meta.get("arch")
    if not (name and version and release and arch):
        raise ValueError("could not extract NEVRA (name/version/release/arch) from RPM header")

    epoch = meta.get("epoch")
    rpm_metadata = RpmMetadata(
        epoch=str(epoch) if epoch is not None else None,
        release=release,
        arch=arch,
        summary=meta.get("summary"),
        description=meta.get("description"),
        provides=None,
        requires=None,
        conflicts=None,
        obsoletes=None,
    )

    filename = path.name
    sha256, pool_path, size_bytes = storage.add_package(path, filename, verify_checksum=True)

    # Same NEVRA but different content already linked to this repo -> conflict.
    # Checked regardless of pool state, so re-uploading a differing build whose
    # bytes happen to already be pooled still requires --force (no silent dupe).
    conflict = next(
        (
            item
            for item in repository.content_items
            if item.content_type == "rpm"
            and item.name == name
            and item.version == version
            and (item.content_metadata or {}).get("release") == release
            and (item.content_metadata or {}).get("arch") == arch
            and item.sha256 != sha256
        ),
        None,
    )
    nevra = rpm_metadata.get_nevra(name, version)
    if conflict is not None and not force:
        raise ValueError(
            f"{nevra} already present in the repo with different content (use --force to replace)"
        )

    # Apply the unlink (force-replace) and the (re)link in a single transaction
    # so a failure can never leave the repo with the old item dropped and no
    # replacement.
    if conflict is not None:
        conflict.repositories.remove(repository)

    # Identical content already pooled -> reuse the existing ContentItem.
    existing = session.query(ContentItem).filter_by(sha256=sha256).first()
    if existing is not None:
        if repository not in existing.repositories:
            existing.repositories.append(repository)
        session.commit()
        return "replaced" if conflict is not None else "linked"

    content_item = ContentItem(
        content_type="rpm",
        name=name,
        version=version,
        sha256=sha256,
        size_bytes=size_bytes,
        pool_path=pool_path,
        filename=filename,
        content_metadata=rpm_metadata.model_dump(exclude_none=False),
    )
    content_item.repositories.append(repository)
    session.add(content_item)
    session.commit()
    return "replaced" if conflict is not None else "uploaded"


# Debian control field -> DebMetadata field (= content_metadata key the APT
# publisher reads). Package/Version/Architecture are handled explicitly.
_DEB_CONTROL_MAP = {
    "Maintainer": "maintainer",
    "Original-Maintainer": "original_maintainer",
    "Section": "section",
    "Priority": "priority",
    "Homepage": "homepage",
    "Source": "source",
    "Depends": "depends",
    "Pre-Depends": "pre_depends",
    "Recommends": "recommends",
    "Suggests": "suggests",
    "Enhances": "enhances",
    "Breaks": "breaks",
    "Conflicts": "conflicts",
    "Replaces": "replaces",
    "Provides": "provides",
    "Built-Using": "built_using",
    "Essential": "essential",
    "Multi-Arch": "multi_arch",
}


def _upload_deb(
    session: Session,
    storage: StorageManager,
    repository: Repository,
    path: Path,
    force: bool,
    component: str,
) -> str:
    """Add one local .deb to the pool and link it to the repo.

    Returns "uploaded", "linked" (already in pool) or "replaced".
    """
    control = parse_deb_control(path.read_bytes())  # DebFormatError if not a .deb
    name = control.get("Package")
    version = control.get("Version")
    arch = control.get("Architecture")
    if not (name and version and arch):
        raise ValueError("could not extract Package/Version/Architecture from .deb control")

    filename = path.name
    sha256, pool_path, size_bytes = storage.add_package(path, filename, verify_checksum=True)

    # The APT publisher emits Description as a single line; keep only the synopsis
    # there and stash the extended description (which it ignores) separately.
    description = control.get("Description")
    synopsis = long_description = None
    if description is not None:
        synopsis, _, rest = description.partition("\n")
        long_description = rest or None

    installed_size = control.get("Installed-Size")
    data: dict[str, Any] = {
        "package": name,
        "version": version,
        "architecture": arch,
        "filename": filename,
        "size": size_bytes,
        "sha256": sha256,
        "component": component,
        "description": synopsis,
        "long_description": long_description,
        "installed_size": (
            int(installed_size) if installed_size and installed_size.isdigit() else None
        ),
    }
    for src, dest in _DEB_CONTROL_MAP.items():
        if control.get(src):
            data[dest] = control[src]
    deb_metadata = DebMetadata.model_validate(data)

    # Same identity (name, version, arch, component) but different content -> conflict.
    conflict = next(
        (
            item
            for item in repository.content_items
            if item.content_type == "deb"
            and item.name == name
            and item.version == version
            and (item.content_metadata or {}).get("architecture") == arch
            and ((item.content_metadata or {}).get("component") or "main") == component
            and item.sha256 != sha256
        ),
        None,
    )
    ident = f"{name}_{version}_{arch}"
    if conflict is not None and not force:
        raise ValueError(
            f"{ident} already present in the repo with different content (use --force to replace)"
        )

    if conflict is not None:
        conflict.repositories.remove(repository)

    existing = session.query(ContentItem).filter_by(sha256=sha256).first()
    if existing is not None:
        # Content is globally deduplicated by checksum, but a ContentItem carries
        # a single component. Linking identical bytes whose pooled item lives in a
        # different component would silently file the package into the wrong
        # component, so reject it explicitly rather than no-op.
        existing_component = (existing.content_metadata or {}).get("component") or "main"
        if existing_component != component:
            raise ValueError(
                f"{ident}: identical package content is already pooled under component "
                f"'{existing_component}'; the same bytes cannot also be published under "
                f"'{component}' (content is deduplicated by checksum)"
            )
        if repository not in existing.repositories:
            existing.repositories.append(repository)
        session.commit()
        return "replaced" if conflict is not None else "linked"

    content_item = ContentItem(
        content_type="deb",
        name=name,
        version=version,
        sha256=sha256,
        size_bytes=size_bytes,
        pool_path=pool_path,
        filename=filename,
        content_metadata=deb_metadata.model_dump(exclude_none=False),
    )
    content_item.repositories.append(repository)
    session.add(content_item)
    session.commit()
    return "replaced" if conflict is not None else "uploaded"


def _upload_helm(
    session: Session, storage: StorageManager, repository: Repository, path: Path, force: bool
) -> str:
    """Add one local Helm chart .tgz to the pool and link it to the repo.

    Returns "uploaded", "linked" (already in pool) or "replaced".
    """
    chart = parse_chart_metadata(path)  # ChartFormatError if not a chart archive
    # digest/urls/created are index.yaml-only; the publisher fills them itself.
    meta = HelmMetadata(**chart)
    name = meta.name
    version = meta.version

    filename = path.name
    sha256, pool_path, size_bytes = storage.add_package(path, filename, verify_checksum=True)

    # Same chart name+version but different content -> conflict.
    conflict = next(
        (
            item
            for item in repository.content_items
            if item.content_type == "helm"
            and item.name == name
            and item.version == version
            and item.sha256 != sha256
        ),
        None,
    )
    ident = f"{name}-{version}"
    if conflict is not None and not force:
        raise ValueError(
            f"{ident} already present in the repo with different content (use --force to replace)"
        )

    if conflict is not None:
        conflict.repositories.remove(repository)

    existing = session.query(ContentItem).filter_by(sha256=sha256).first()
    if existing is not None:
        if repository not in existing.repositories:
            existing.repositories.append(repository)
        session.commit()
        return "replaced" if conflict is not None else "linked"

    content_item = ContentItem(
        content_type="helm",
        name=name,
        version=version,
        sha256=sha256,
        size_bytes=size_bytes,
        pool_path=pool_path,
        filename=filename,
        content_metadata=meta.model_dump(mode="json"),
    )
    content_item.repositories.append(repository)
    session.add(content_item)
    session.commit()
    return "replaced" if conflict is not None else "uploaded"


def create_package_group(cli: click.Group) -> None:
    """Register the ``package`` command group."""

    @cli.group("package")
    def package() -> None:
        """Manage custom (uploaded) packages."""

    @package.command("upload")
    @click.option(
        "--file",
        "file_path",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        help="A single package file to upload.",
    )
    @click.option(
        "--directory",
        "directory",
        type=click.Path(exists=True, file_okay=False, path_type=Path),
        help="A directory of packages to upload.",
    )
    @click.option("--recursive", is_flag=True, help="Recurse into --directory.")
    @click.option("--repo-id", required=True, help="Target repository id.")
    @click.option("--force", is_flag=True, help="Replace a conflicting same-version package.")
    @click.option(
        "--component",
        default="main",
        show_default=True,
        help="APT component for uploaded .deb packages (ignored for rpm/helm).",
    )
    @click.pass_context
    def upload(
        ctx: click.Context,
        file_path: Path | None,
        directory: Path | None,
        recursive: bool,
        repo_id: str,
        force: bool,
        component: str,
    ) -> None:
        """Upload local package file(s) into a repository's content pool."""
        config: GlobalConfig = ctx.obj["config"]
        repo_config = config.get_repository(repo_id)
        if repo_config is None:
            click.echo(f"Error: repository '{repo_id}' not found in configuration", err=True)
            raise click.Abort()
        if repo_config.type not in ("rpm", "apt", "helm"):
            click.echo(
                f"Error: package upload supports only 'rpm', 'apt' and 'helm' repositories "
                f"(repository '{repo_id}' is '{repo_config.type}')",
                err=True,
            )
            raise click.Abort()
        if not file_path and not directory:
            click.echo("Error: provide --file or --directory", err=True)
            raise click.Abort()

        ext = {"rpm": "*.rpm", "apt": "*.deb", "helm": "*.tgz"}[repo_config.type]
        files: list[Path] = []
        if file_path:
            files.append(file_path)
        if directory:
            files.extend(sorted(directory.rglob(ext) if recursive else directory.glob(ext)))
        if not files:
            click.echo(f"No {ext} files found to upload.")
            return

        storage = StorageManager(config.storage)
        db_manager = DatabaseManager(config.database.url)
        uploaded = linked = replaced = failed = 0
        with db_manager.session() as session:
            repository = _get_or_create_repository(session, repo_config)
            for f in files:
                try:
                    if repo_config.type == "rpm":
                        result = _upload_rpm(session, storage, repository, f, force)
                    elif repo_config.type == "apt":
                        result = _upload_deb(session, storage, repository, f, force, component)
                    else:
                        result = _upload_helm(session, storage, repository, f, force)
                except Exception as e:  # noqa: BLE001 - report per-file, continue
                    session.rollback()
                    failed += 1
                    click.echo(f"  ✗ {f.name}: {e}", err=True)
                    continue
                if result == "uploaded":
                    uploaded += 1
                    click.echo(f"  ✓ {f.name}")
                elif result == "replaced":
                    replaced += 1
                    click.echo(f"  ✓ {f.name} (replaced existing)")
                else:
                    linked += 1
                    click.echo(f"  → {f.name} (already in pool, linked)")

        click.echo(
            f"\nUploaded {uploaded}, replaced {replaced}, linked {linked}, failed {failed} "
            f"into '{repo_id}'."
        )
        click.echo(
            "Run 'chantal publish repo --repo-id <id> --target <dir>' to regenerate metadata."
        )
