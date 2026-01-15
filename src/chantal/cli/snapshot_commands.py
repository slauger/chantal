from __future__ import annotations

"""Snapshot management commands."""

import json
import shutil
from pathlib import Path

import click

from chantal.core.config import GlobalConfig
from chantal.db.connection import DatabaseManager
from chantal.db.models import Repository, Snapshot, View, ViewSnapshot

# Click context settings to enable -h as alias for --help
CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


def create_snapshot_group(cli: click.Group) -> click.Group:
    """Create and return the snapshot command group.

    Args:
        cli: Parent CLI group to attach to

    Returns:
        The snapshot command group
    """

    @cli.group(context_settings=CONTEXT_SETTINGS)
    def snapshot() -> None:
        """Snapshot management commands."""
        pass

    @snapshot.command("list")
    @click.option("--repo-id", help="Filter by repository ID")
    @click.pass_context
    def snapshot_list(ctx: click.Context, repo_id: str) -> None:
        """List snapshots.

        Shows all snapshots with package count, size, and creation date.
        Optionally filter by repository ID.
        """
        config: GlobalConfig = ctx.obj["config"]

        # Initialize database
        db_manager = DatabaseManager(config.database.url)

        with db_manager.session() as session:
            # Build query
            query = session.query(Snapshot)

            if repo_id:
                # Filter by repository
                repository = session.query(Repository).filter_by(repo_id=repo_id).first()
                if not repository:
                    click.echo(f"Error: Repository '{repo_id}' not found.", err=True)
                    ctx.exit(1)
                query = query.filter_by(repository_id=repository.id)
                click.echo(f"Snapshots for repository '{repo_id}':")
            else:
                click.echo("All snapshots:")

            # Get snapshots with repository info
            snapshots = query.order_by(Snapshot.created_at.desc()).all()

            if not snapshots:
                click.echo("  No snapshots found.")
                if not repo_id:
                    click.echo("\nCreate a snapshot with:")
                    click.echo("  chantal snapshot create --repo-id <repo-id> --name <name>")
                return

            click.echo()
            click.echo(
                f"{'Name':<30} {'Repository':<20} {'Packages':>10} {'Size':>12} {'Created':<20}"
            )
            click.echo("-" * 100)

            for snapshot in snapshots:
                # Get repository info
                repo = session.query(Repository).filter_by(id=snapshot.repository_id).first()
                repo_name = repo.repo_id if repo else "Unknown"

                # Format size
                size_gb = snapshot.total_size_bytes / (1024**3)
                if size_gb >= 1.0:
                    size_str = f"{size_gb:.2f} GB"
                else:
                    size_mb = snapshot.total_size_bytes / (1024**2)
                    size_str = f"{size_mb:.1f} MB"

                # Format created date
                created_str = snapshot.created_at.strftime("%Y-%m-%d %H:%M")

                click.echo(
                    f"{snapshot.name:<30} {repo_name:<20} {snapshot.package_count:>10} {size_str:>12} {created_str:<20}"
                )

            click.echo()
            click.echo(f"Total: {len(snapshots)} snapshot(s)")

    @snapshot.command("create")
    @click.option("--repo-id", help="Repository ID (mutually exclusive with --view)")
    @click.option("--view", help="View name (mutually exclusive with --repo-id)")
    @click.option("--name", required=True, help="Snapshot name")
    @click.option("--description", help="Snapshot description")
    @click.pass_context
    def snapshot_create(
        ctx: click.Context, repo_id: str, view: str, name: str, description: str
    ) -> None:
        """Create snapshot of repository or view.

        Creates an immutable point-in-time snapshot of the current state.
        The snapshot references packages from the content-addressed pool.

        For repositories: Creates snapshot of single repository
        For views: Creates snapshots of ALL repositories in view + ViewSnapshot
        """
        # Check database schema version
        from chantal.cli.db_commands import check_db_schema_version

        check_db_schema_version(ctx)

        config: GlobalConfig = ctx.obj["config"]

        # Validate: exactly one of --repo-id or --view must be specified
        if not repo_id and not view:
            click.echo("Error: Must specify either --repo-id or --view", err=True)
            ctx.exit(1)
        if repo_id and view:
            click.echo("Error: Cannot specify both --repo-id and --view", err=True)
            ctx.exit(1)

        # Initialize database
        db_manager = DatabaseManager(config.database.url)

        if repo_id:
            # Create repository snapshot (existing behavior)
            _create_repository_snapshot(ctx, config, db_manager, repo_id, name, description)
        else:
            # Create view snapshot (new behavior)
            _create_view_snapshot(ctx, config, db_manager, view, name, description)

    @snapshot.command("diff")
    @click.option("--repo-id", required=True, help="Repository ID")
    @click.argument("snapshot1")
    @click.argument("snapshot2")
    @click.option(
        "--format",
        "output_format",
        type=click.Choice(["table", "json"]),
        default="table",
        help="Output format",
    )
    @click.pass_context
    def snapshot_diff(
        ctx: click.Context, repo_id: str, snapshot1: str, snapshot2: str, output_format: str
    ) -> None:
        """Compare two snapshots within a repository, or a snapshot against upstream.

        Shows packages that were added, removed, or updated between two snapshots
        or between a snapshot and the current upstream state.

        Use "upstream" as snapshot2 to compare against current repository state:
          chantal snapshot diff --repo-id rhel9-baseos 2025-01-10 upstream

        Perfect for generating patch announcements!
        """
        config: GlobalConfig = ctx.obj["config"]
        db_manager = DatabaseManager(config.database.url)

        with db_manager.session() as session:
            # Get repository
            repository = session.query(Repository).filter_by(repo_id=repo_id).first()
            if not repository:
                click.echo(f"Error: Repository '{repo_id}' not found.", err=True)
                ctx.exit(1)

            # Get first snapshot
            snap1 = (
                session.query(Snapshot)
                .filter_by(repository_id=repository.id, name=snapshot1)
                .first()
            )

            if not snap1:
                click.echo(f"Error: Snapshot '{snapshot1}' not found.", err=True)
                ctx.exit(1)

            # Get packages from first snapshot
            packages1 = {pkg.sha256: pkg for pkg in snap1.content_items}

            # Get second comparison source (snapshot or upstream)
            if snapshot2.lower() == "upstream":
                # Compare against current repository state
                session.refresh(repository)
                packages2 = {pkg.sha256: pkg for pkg in repository.content_items}
                comparison_name = "upstream (current)"
            else:
                # Compare against another snapshot
                snap2 = (
                    session.query(Snapshot)
                    .filter_by(repository_id=repository.id, name=snapshot2)
                    .first()
                )

                if not snap2:
                    click.echo(f"Error: Snapshot '{snapshot2}' not found.", err=True)
                    ctx.exit(1)

                packages2 = {pkg.sha256: pkg for pkg in snap2.content_items}
                comparison_name = snapshot2

            # Calculate differences
            added_sha256s = set(packages2.keys()) - set(packages1.keys())
            removed_sha256s = set(packages1.keys()) - set(packages2.keys())

            # Find updated packages (same name, different version)
            # Group packages by name for easier comparison
            packages1_by_name = {}
            for pkg in packages1.values():
                packages1_by_name[pkg.name] = pkg

            packages2_by_name = {}
            for pkg in packages2.values():
                packages2_by_name[pkg.name] = pkg

            # Find packages with same name but different SHA256 (= different version)
            updated = []
            for name in packages1_by_name.keys() & packages2_by_name.keys():
                pkg1 = packages1_by_name[name]
                pkg2 = packages2_by_name[name]
                if pkg1.sha256 != pkg2.sha256:
                    updated.append((pkg1, pkg2))
                    # Remove from added/removed since they're updates
                    added_sha256s.discard(pkg2.sha256)
                    removed_sha256s.discard(pkg1.sha256)

            added = [packages2[sha] for sha in added_sha256s]
            removed = [packages1[sha] for sha in removed_sha256s]

            # Sort for consistent output
            added.sort(key=lambda p: p.name)
            removed.sort(key=lambda p: p.name)
            updated.sort(key=lambda p: p[0].name)

            # Output
            if output_format == "json":
                result = {
                    "repository": repo_id,
                    "snapshot1": snapshot1,
                    "snapshot2": comparison_name,
                    "added": [
                        {
                            "name": pkg.name,
                            "version": pkg.version,
                            "release": pkg.release,
                            "arch": pkg.arch,
                            "nevra": pkg.nevra,
                        }
                        for pkg in added
                    ],
                    "removed": [
                        {
                            "name": pkg.name,
                            "version": pkg.version,
                            "release": pkg.release,
                            "arch": pkg.arch,
                            "nevra": pkg.nevra,
                        }
                        for pkg in removed
                    ],
                    "updated": [
                        {
                            "name": old.name,
                            "old_version": f"{old.version}-{old.release}",
                            "new_version": f"{new.version}-{new.release}",
                            "arch": old.arch,
                        }
                        for old, new in updated
                    ],
                    "summary": {
                        "added": len(added),
                        "removed": len(removed),
                        "updated": len(updated),
                    },
                }
                click.echo(json.dumps(result, indent=2))
            else:
                # Table format
                click.echo(f"Repository: {repo_id}")
                click.echo(f"Comparing: {snapshot1} → {comparison_name}")
                click.echo()

                if added:
                    click.echo(f"Added ({len(added)}):")
                    for pkg in added:
                        click.echo(f"  + {pkg.nevra}")
                    click.echo()

                if removed:
                    click.echo(f"Removed ({len(removed)}):")
                    for pkg in removed:
                        click.echo(f"  - {pkg.nevra}")
                    click.echo()

                if updated:
                    click.echo(f"Updated ({len(updated)}):")
                    for old, new in updated:
                        old_ver = f"{old.version}-{old.release}" if old.release else old.version
                        new_ver = f"{new.version}-{new.release}" if new.release else new.version
                        click.echo(f"  ~ {old.name}: {old_ver} → {new_ver}")
                    click.echo()

                if not added and not removed and not updated:
                    click.echo("No changes between snapshots.")
                    click.echo()

                click.echo(
                    f"Summary: {len(added)} added, {len(removed)} removed, {len(updated)} updated"
                )

    @snapshot.command("delete")
    @click.option("--repo-id", required=True, help="Repository ID")
    @click.argument("snapshot_name")
    @click.option("--force", is_flag=True, help="Force deletion even if published")
    @click.pass_context
    def snapshot_delete(ctx: click.Context, repo_id: str, snapshot_name: str, force: bool) -> None:
        """Delete a snapshot.

        Removes snapshot from database and unpublishes if needed.
        Packages remain in the pool for other snapshots/repositories.
        """
        config: GlobalConfig = ctx.obj["config"]
        db_manager = DatabaseManager(config.database.url)

        with db_manager.session() as session:
            # Get repository
            repository = session.query(Repository).filter_by(repo_id=repo_id).first()
            if not repository:
                click.echo(f"Error: Repository '{repo_id}' not found.", err=True)
                ctx.exit(1)

            # Get snapshot
            snapshot = (
                session.query(Snapshot)
                .filter_by(repository_id=repository.id, name=snapshot_name)
                .first()
            )

            if not snapshot:
                click.echo(
                    f"Error: Snapshot '{snapshot_name}' not found for repository '{repo_id}'.",
                    err=True,
                )
                ctx.exit(1)

            # Check if published
            if snapshot.is_published and not force:
                click.echo(f"Error: Snapshot '{snapshot_name}' is currently published.", err=True)
                click.echo(f"Published at: {snapshot.published_path}", err=True)
                click.echo("Unpublish first or use --force to delete anyway.", err=True)
                ctx.exit(1)

            click.echo(f"Deleting snapshot: {snapshot_name}")
            click.echo(f"Repository: {repo_id}")
            click.echo(f"Packages: {snapshot.package_count}")

            # Unpublish if needed
            if snapshot.is_published:
                published_path = Path(snapshot.published_path)
                if published_path.exists():
                    click.echo(f"Unpublishing from: {published_path}")
                    shutil.rmtree(published_path)
                snapshot.is_published = False
                snapshot.published_path = None

            # Delete snapshot (cascade will remove snapshot_packages entries)
            session.delete(snapshot)
            session.commit()

            click.echo()
            click.echo(f"✓ Snapshot '{snapshot_name}' deleted successfully!")
            click.echo("Note: Packages remain in pool for other repositories/snapshots")

    @snapshot.command("copy")
    @click.option("--source", required=True, help="Source snapshot name")
    @click.option("--target", required=True, help="Target snapshot name")
    @click.option("--repo-id", required=True, help="Repository ID")
    @click.option("--description", help="Description for new snapshot")
    @click.pass_context
    def snapshot_copy(
        ctx: click.Context, source: str, target: str, repo_id: str, description: str
    ) -> None:
        """Copy a snapshot to a new name (enables promotion workflows).

        Creates a new snapshot with a different name that references the same packages.
        No files are copied - only database entries. Both snapshots share the same
        content-addressed packages in the pool.

        Examples:
            # Promote tested snapshot to stable
            chantal snapshot copy --source 2025-01-10 --target stable --repo-id rhel9-baseos

            # Create production snapshot from staging
            chantal snapshot copy --source staging --target production --repo-id rhel9-baseos
        """
        config: GlobalConfig = ctx.obj["config"]
        db_manager = DatabaseManager(config.database.url)

        with db_manager.session() as session:
            # Get repository
            repository = session.query(Repository).filter_by(repo_id=repo_id).first()
            if not repository:
                click.echo(f"Error: Repository '{repo_id}' not found.", err=True)
                ctx.exit(1)

            # Get source snapshot
            source_snapshot = (
                session.query(Snapshot).filter_by(repository_id=repository.id, name=source).first()
            )

            if not source_snapshot:
                click.echo(
                    f"Error: Source snapshot '{source}' not found for repository '{repo_id}'.",
                    err=True,
                )
                ctx.exit(1)

            # Check if target already exists
            existing_target = (
                session.query(Snapshot).filter_by(repository_id=repository.id, name=target).first()
            )

            if existing_target:
                click.echo(
                    f"Error: Target snapshot '{target}' already exists for repository '{repo_id}'.",
                    err=True,
                )
                click.echo(f"Created: {existing_target.created_at}", err=True)
                click.echo(
                    "Use a different target name or delete the existing snapshot first.", err=True
                )
                ctx.exit(1)

            click.echo(f"Copying snapshot: {source} → {target}")
            click.echo(f"Repository: {repo_id}")
            click.echo(f"Packages: {source_snapshot.package_count}")
            click.echo()

            # Create new snapshot with same content
            new_snapshot = Snapshot(
                repository_id=source_snapshot.repository_id,
                name=target,
                description=description or f"Copy of '{source}'",
                package_count=source_snapshot.package_count,
                total_size_bytes=source_snapshot.total_size_bytes,
            )

            # Copy content item relationships (NOT the files - they stay in pool)
            new_snapshot.content_items = list(source_snapshot.content_items)

            # Copy repository file relationships (metadata)
            new_snapshot.repository_files = list(source_snapshot.repository_files)

            session.add(new_snapshot)
            session.commit()

            click.echo("✓ Snapshot copied successfully!")
            click.echo(f"  Source: {source}")
            click.echo(f"  Target: {target}")
            click.echo(f"  Packages: {new_snapshot.package_count}")
            click.echo(f"  Total size: {new_snapshot.total_size_bytes / (1024**3):.2f} GB")
            click.echo()
            click.echo("Note: Both snapshots share the same packages in the pool (zero-copy)")
            click.echo()
            click.echo("To publish the new snapshot:")
            click.echo(f"  chantal publish snapshot --snapshot {target} --repo-id {repo_id}")

    @snapshot.command("content")
    @click.option("--repo-id", help="Repository ID (for repository snapshots)")
    @click.option("--view", help="View name (for view snapshots)")
    @click.option("--snapshot", "snapshot_name", required=True, help="Snapshot name")
    @click.option(
        "--format",
        "output_format",
        type=click.Choice(["table", "json", "csv"]),
        default="table",
        help="Output format",
    )
    @click.option("--limit", type=int, help="Limit number of packages shown (table format only)")
    @click.pass_context
    def snapshot_content(
        ctx: click.Context,
        repo_id: str,
        view: str,
        snapshot_name: str,
        output_format: str,
        limit: int,
    ) -> None:
        """Show content (package list) of a snapshot.

        For repository snapshots: --repo-id <repo> --snapshot <name>
        For view snapshots: --view <view> --snapshot <name>

        Useful for compliance/audit purposes - shows exactly what was in a snapshot.
        """
        config: GlobalConfig = ctx.obj["config"]

        # Validate: exactly one of --repo-id or --view must be specified
        if not repo_id and not view:
            click.echo("Error: Must specify either --repo-id or --view", err=True)
            ctx.exit(1)
        if repo_id and view:
            click.echo("Error: Cannot specify both --repo-id and --view", err=True)
            ctx.exit(1)

        db_manager = DatabaseManager(config.database.url)

        if view:
            # Show view snapshot content
            _show_view_snapshot_content(ctx, db_manager, view, snapshot_name, output_format, limit)
        else:
            # Show repository snapshot content
            _show_repository_snapshot_content(
                ctx, db_manager, repo_id, snapshot_name, output_format, limit
            )

    return snapshot


# ============================================================================
# Helper Functions
# ============================================================================


def _create_repository_snapshot(
    ctx: click.Context,
    config: GlobalConfig,
    db_manager: DatabaseManager,
    repo_id: str,
    name: str,
    description: str,
) -> None:
    """Create snapshot of a single repository."""
    click.echo(f"Creating snapshot '{name}' of repository '{repo_id}'...")
    if description:
        click.echo(f"Description: {description}")
    click.echo()

    with db_manager.session() as session:
        # Get repository from database
        repository = session.query(Repository).filter_by(repo_id=repo_id).first()
        if not repository:
            # Check if repository exists in configuration
            repo_config = next((r for r in config.repositories if r.id == repo_id), None)
            if repo_config:
                click.echo(f"Error: Repository '{repo_id}' has not been synced yet.", err=True)
                click.echo(f"Run 'chantal repo sync --repo-id {repo_id}' first.", err=True)
            else:
                click.echo(f"Error: Repository '{repo_id}' not found in configuration.", err=True)
                click.echo("Run 'chantal repo list' to see available repositories.", err=True)
            ctx.exit(1)

        # Check if snapshot with this name already exists
        existing_snapshot = (
            session.query(Snapshot).filter_by(repository_id=repository.id, name=name).first()
        )
        if existing_snapshot:
            click.echo(
                f"Error: Snapshot '{name}' already exists for repository '{repo_id}'.", err=True
            )
            click.echo(f"Created: {existing_snapshot.created_at}", err=True)
            click.echo("Use a different name or delete the existing snapshot first.", err=True)
            ctx.exit(1)

        # Get current packages in repository
        session.refresh(repository)
        packages = list(repository.content_items)

        if not packages:
            click.echo(f"Warning: Repository '{repo_id}' has no packages.", err=True)
            click.echo("Sync the repository first with: chantal repo sync --repo-id {repo_id}")
            ctx.exit(1)

        # Calculate statistics
        package_count = len(packages)
        total_size_bytes = sum(pkg.size_bytes for pkg in packages)

        click.echo(
            f"Repository has {package_count} packages ({total_size_bytes / (1024**3):.2f} GB)"
        )

        # Create snapshot
        snapshot = Snapshot(
            repository_id=repository.id,
            name=name,
            description=description,
            package_count=package_count,
            total_size_bytes=total_size_bytes,
        )

        # Link packages to snapshot
        snapshot.content_items = packages

        # Link repository files (metadata) to snapshot
        session.refresh(repository)
        snapshot.repository_files = list(repository.repository_files)

        session.add(snapshot)
        session.commit()

        click.echo()
        click.echo(f"✓ Snapshot '{name}' created successfully!")
        click.echo(f"  Repository: {repo_id}")
        click.echo(f"  Packages: {package_count}")
        click.echo(f"  Total size: {total_size_bytes / (1024**3):.2f} GB")
        click.echo(f"  Created: {snapshot.created_at}")
        click.echo()
        click.echo("To publish this snapshot:")
        click.echo(f"  chantal publish snapshot --snapshot {name} --repo-id {repo_id}")


def _create_view_snapshot(
    ctx: click.Context,
    config: GlobalConfig,
    db_manager: DatabaseManager,
    view_name: str,
    snapshot_name: str,
    description: str,
) -> None:
    """Create atomic snapshot of ALL repositories in a view."""
    click.echo(f"Creating view snapshot '{snapshot_name}' of view '{view_name}'...")
    if description:
        click.echo(f"Description: {description}")
    click.echo()

    with db_manager.session() as session:
        # Get view from database
        view = session.query(View).filter_by(name=view_name).first()
        if not view:
            click.echo(f"Error: View '{view_name}' not found in database.", err=True)
            click.echo("Run 'chantal view list' to see available views.", err=True)
            ctx.exit(1)

        # Check if view snapshot with this name already exists
        existing_snapshot = (
            session.query(ViewSnapshot).filter_by(view_id=view.id, name=snapshot_name).first()
        )
        if existing_snapshot:
            click.echo(
                f"Error: View snapshot '{snapshot_name}' already exists for view '{view_name}'.",
                err=True,
            )
            click.echo(f"Created: {existing_snapshot.created_at}", err=True)
            click.echo("Use a different name or delete the existing snapshot first.", err=True)
            ctx.exit(1)

        # Refresh view to get latest relationships
        session.refresh(view)

        if not view.view_repositories:
            click.echo(f"Error: View '{view_name}' has no repositories.", err=True)
            ctx.exit(1)

        click.echo(f"Creating snapshots for {len(view.view_repositories)} repositories...")
        click.echo()

        # Create snapshot for each repository in view
        created_snapshot_ids = []
        total_packages = 0
        total_bytes = 0

        for view_repo in sorted(view.view_repositories, key=lambda vr: vr.order):
            repo = view_repo.repository
            session.refresh(repo)

            click.echo(f"  [{view_repo.order + 1}/{len(view.view_repositories)}] {repo.repo_id}...")

            # Get packages
            packages = list(repo.content_items)
            if not packages:
                click.echo(f"      Warning: Repository '{repo.repo_id}' has no packages (skipped)")
                continue

            package_count = len(packages)
            size_bytes = sum(pkg.size_bytes for pkg in packages)

            # Create snapshot for this repository
            snapshot = Snapshot(
                repository_id=repo.id,
                name=f"{snapshot_name}",
                description=f"Auto-created for view snapshot '{view_name}/{snapshot_name}'",
                package_count=package_count,
                total_size_bytes=size_bytes,
            )
            snapshot.content_items = packages

            # Link repository files (metadata) to snapshot
            session.refresh(repo)
            snapshot.repository_files = list(repo.repository_files)

            session.add(snapshot)
            session.flush()  # Get snapshot ID

            created_snapshot_ids.append(snapshot.id)
            total_packages += package_count
            total_bytes += size_bytes

            click.echo(f"      ✓ {package_count} packages ({size_bytes / (1024**3):.2f} GB)")

        if not created_snapshot_ids:
            click.echo()
            click.echo("Error: No snapshots created (all repositories empty)", err=True)
            ctx.exit(1)

        # Create view snapshot
        view_snapshot = ViewSnapshot(
            view_id=view.id,
            name=snapshot_name,
            description=description,
            snapshot_ids=created_snapshot_ids,
            package_count=total_packages,
            total_size_bytes=total_bytes,
        )
        session.add(view_snapshot)
        session.commit()

        click.echo()
        click.echo(f"✓ View snapshot '{snapshot_name}' created successfully!")
        click.echo(f"  View: {view_name}")
        click.echo(f"  Repositories: {len(created_snapshot_ids)}")
        click.echo(f"  Total packages: {total_packages}")
        click.echo(f"  Total size: {total_bytes / (1024**3):.2f} GB")
        click.echo(f"  Created: {view_snapshot.created_at}")
        click.echo()
        click.echo("To publish this view snapshot:")
        click.echo(f"  chantal publish snapshot --view {view_name} --snapshot {snapshot_name}")


def _show_repository_snapshot_content(
    ctx: click.Context,
    db_manager: DatabaseManager,
    repo_id: str,
    snapshot_name: str,
    output_format: str,
    limit: int,
) -> None:
    """Show repository snapshot content."""
    with db_manager.session() as session:
        # Get repository
        repository = session.query(Repository).filter_by(repo_id=repo_id).first()
        if not repository:
            click.echo(f"Error: Repository '{repo_id}' not found.", err=True)
            ctx.exit(1)

        # Get snapshot
        snapshot = (
            session.query(Snapshot)
            .filter_by(repository_id=repository.id, name=snapshot_name)
            .first()
        )

        if not snapshot:
            click.echo(
                f"Error: Snapshot '{snapshot_name}' not found for repository '{repo_id}'.", err=True
            )
            ctx.exit(1)

        # Get packages
        packages = list(snapshot.content_items)

        if output_format == "json":
            output = {
                "type": "repository_snapshot",
                "repository": repo_id,
                "snapshot": snapshot_name,
                "created_at": snapshot.created_at.isoformat(),
                "description": snapshot.description,
                "package_count": snapshot.package_count,
                "total_size_bytes": snapshot.total_size_bytes,
                "packages": [
                    {
                        "name": pkg.name,
                        "epoch": pkg.epoch,
                        "version": pkg.version,
                        "release": pkg.release,
                        "arch": pkg.arch,
                        "nevra": pkg.nevra,
                        "sha256": pkg.sha256,
                        "size_bytes": pkg.size_bytes,
                        "filename": pkg.filename,
                    }
                    for pkg in sorted(packages, key=lambda p: p.name)
                ],
            }
            click.echo(json.dumps(output, indent=2))

        elif output_format == "csv":
            click.echo("name,epoch,version,release,arch,nevra,sha256,size_bytes,filename")
            for pkg in sorted(packages, key=lambda p: p.name):
                click.echo(
                    f"{pkg.name},{pkg.epoch or ''},{pkg.version},{pkg.release},"
                    f"{pkg.arch},{pkg.nevra},{pkg.sha256},{pkg.size_bytes},{pkg.filename}"
                )

        else:  # table
            click.echo(f"Repository Snapshot: {repo_id} / {snapshot_name}")
            click.echo(f"Created: {snapshot.created_at}")
            if snapshot.description:
                click.echo(f"Description: {snapshot.description}")
            click.echo(f"Packages: {snapshot.package_count}")
            click.echo(f"Total Size: {snapshot.total_size_bytes / (1024**3):.2f} GB")
            click.echo()

            # Show packages
            packages_to_show = packages[:limit] if limit else packages

            click.echo(f"{'Name':<40} {'Version-Release':<35} {'Arch':<10} {'Size':<12}")
            click.echo("-" * 100)

            for pkg in sorted(packages_to_show, key=lambda p: p.name):
                vr = f"{pkg.version}-{pkg.release}"
                if pkg.epoch:
                    vr = f"{pkg.epoch}:{vr}"

                size_mb = pkg.size_bytes / (1024**2)
                if size_mb >= 1.0:
                    size_str = f"{size_mb:.1f} MB"
                else:
                    size_kb = pkg.size_bytes / 1024
                    size_str = f"{size_kb:.0f} KB"

                click.echo(f"{pkg.name:<40} {vr:<35} {pkg.arch:<10} {size_str:<12}")

            if limit and len(packages) > limit:
                click.echo()
                click.echo(
                    f"Showing {limit} of {len(packages)} packages. Use --limit to show more or --format json for full export."
                )


def _show_view_snapshot_content(
    ctx: click.Context,
    db_manager: DatabaseManager,
    view_name: str,
    snapshot_name: str,
    output_format: str,
    limit: int,
) -> None:
    """Show view snapshot content."""
    with db_manager.session() as session:
        # Get view
        view = session.query(View).filter_by(name=view_name).first()
        if not view:
            click.echo(f"Error: View '{view_name}' not found.", err=True)
            ctx.exit(1)

        # Get view snapshot
        view_snapshot = (
            session.query(ViewSnapshot).filter_by(view_id=view.id, name=snapshot_name).first()
        )

        if not view_snapshot:
            click.echo(
                f"Error: View snapshot '{snapshot_name}' not found for view '{view_name}'.",
                err=True,
            )
            ctx.exit(1)

        # Collect all packages from all snapshots
        repositories_data = []
        all_packages = []

        for snapshot_id in view_snapshot.snapshot_ids:
            snapshot = session.query(Snapshot).filter_by(id=snapshot_id).first()
            if not snapshot:
                continue

            repo = snapshot.repository
            packages = list(snapshot.content_items)

            repositories_data.append(
                {
                    "repo_id": repo.repo_id,
                    "snapshot_name": snapshot.name,
                    "package_count": len(packages),
                    "packages": packages,
                }
            )
            all_packages.extend(packages)

        if output_format == "json":
            output = {
                "type": "view_snapshot",
                "view": view_name,
                "snapshot": snapshot_name,
                "created_at": view_snapshot.created_at.isoformat(),
                "description": view_snapshot.description,
                "total_packages": view_snapshot.package_count,
                "total_size_bytes": view_snapshot.total_size_bytes,
                "repositories": [
                    {
                        "repo_id": repo_data["repo_id"],
                        "snapshot_name": repo_data["snapshot_name"],
                        "package_count": repo_data["package_count"],
                        "packages": [
                            {
                                "name": pkg.name,
                                "epoch": pkg.epoch,
                                "version": pkg.version,
                                "release": pkg.release,
                                "arch": pkg.arch,
                                "nevra": pkg.nevra,
                                "sha256": pkg.sha256,
                                "size_bytes": pkg.size_bytes,
                                "filename": pkg.filename,
                            }
                            for pkg in sorted(repo_data["packages"], key=lambda p: p.name)
                        ],
                    }
                    for repo_data in repositories_data
                ],
            }
            click.echo(json.dumps(output, indent=2))

        elif output_format == "csv":
            click.echo(
                "view,snapshot,repo_id,name,epoch,version,release,arch,nevra,sha256,size_bytes,filename"
            )
            for repo_data in repositories_data:
                for pkg in sorted(repo_data["packages"], key=lambda p: p.name):
                    click.echo(
                        f"{view_name},{snapshot_name},{repo_data['repo_id']},"
                        f"{pkg.name},{pkg.epoch or ''},{pkg.version},{pkg.release},"
                        f"{pkg.arch},{pkg.nevra},{pkg.sha256},{pkg.size_bytes},{pkg.filename}"
                    )

        else:  # table
            click.echo(f"View Snapshot: {view_name} / {snapshot_name}")
            click.echo(f"Created: {view_snapshot.created_at}")
            if view_snapshot.description:
                click.echo(f"Description: {view_snapshot.description}")
            click.echo(f"Repositories: {len(repositories_data)}")
            click.echo(f"Total Packages: {view_snapshot.package_count}")
            click.echo(f"Total Size: {view_snapshot.total_size_bytes / (1024**3):.2f} GB")
            click.echo()

            # Show packages grouped by repository
            for repo_data in repositories_data:
                click.echo(
                    f"Repository: {repo_data['repo_id']} ({repo_data['package_count']} packages)"
                )
                click.echo("-" * 100)
                click.echo(f"{'Name':<40} {'Version-Release':<35} {'Arch':<10} {'Size':<12}")
                click.echo("-" * 100)

                packages_to_show = repo_data["packages"][:limit] if limit else repo_data["packages"]

                for pkg in sorted(packages_to_show, key=lambda p: p.name):
                    vr = f"{pkg.version}-{pkg.release}"
                    if pkg.epoch:
                        vr = f"{pkg.epoch}:{vr}"

                    size_mb = pkg.size_bytes / (1024**2)
                    if size_mb >= 1.0:
                        size_str = f"{size_mb:.1f} MB"
                    else:
                        size_kb = pkg.size_bytes / 1024
                        size_str = f"{size_kb:.0f} KB"

                    click.echo(f"{pkg.name:<40} {vr:<35} {pkg.arch:<10} {size_str:<12}")

                if limit and len(repo_data["packages"]) > limit:
                    remaining = len(repo_data["packages"]) - limit
                    click.echo(f"... and {remaining} more packages")

                click.echo()

            if limit:
                click.echo(
                    f"Use --format json or --format csv for full export of all {view_snapshot.package_count} packages."
                )
