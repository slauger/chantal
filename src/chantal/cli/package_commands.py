from __future__ import annotations

"""
CLI for uploading custom (local) packages into a repository's content pool.

Phase 1 supports RPM uploads into a hosted (upload-only) or hybrid repository.
Uploaded packages are added to the content-addressed pool and linked to the
repository as ContentItems, so the existing publisher includes them when it
regenerates the repository metadata.
"""

from pathlib import Path

import click
from sqlalchemy.orm import Session

from chantal.core.config import GlobalConfig, RepositoryConfig
from chantal.core.storage import StorageManager
from chantal.db.connection import DatabaseManager
from chantal.db.models import ContentItem, Repository
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
    @click.option("--force", is_flag=True, help="Replace a conflicting same-NEVRA package.")
    @click.pass_context
    def upload(
        ctx: click.Context,
        file_path: Path | None,
        directory: Path | None,
        recursive: bool,
        repo_id: str,
        force: bool,
    ) -> None:
        """Upload local package file(s) into a repository's content pool."""
        config: GlobalConfig = ctx.obj["config"]
        repo_config = config.get_repository(repo_id)
        if repo_config is None:
            click.echo(f"Error: repository '{repo_id}' not found in configuration", err=True)
            raise click.Abort()
        if repo_config.type != "rpm":
            click.echo(
                f"Error: package upload currently supports only 'rpm' repositories "
                f"(repository '{repo_id}' is '{repo_config.type}')",
                err=True,
            )
            raise click.Abort()
        if not file_path and not directory:
            click.echo("Error: provide --file or --directory", err=True)
            raise click.Abort()

        files: list[Path] = []
        if file_path:
            files.append(file_path)
        if directory:
            files.extend(sorted(directory.rglob("*.rpm") if recursive else directory.glob("*.rpm")))
        if not files:
            click.echo("No .rpm files found to upload.")
            return

        storage = StorageManager(config.storage)
        db_manager = DatabaseManager(config.database.url)
        uploaded = linked = replaced = failed = 0
        with db_manager.session() as session:
            repository = _get_or_create_repository(session, repo_config)
            for f in files:
                try:
                    result = _upload_rpm(session, storage, repository, f, force)
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
