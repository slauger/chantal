"""
Main CLI entry point for Chantal.

This module provides the Click-based command-line interface for Chantal.
"""

import shutil

import click
from pathlib import Path
from typing import Optional

from chantal import __version__
from chantal.core.config import GlobalConfig, load_config
from chantal.core.storage import StorageManager
from chantal.db.connection import DatabaseManager
from chantal.db.models import Repository, Snapshot
from chantal.plugins.rpm_sync import RpmSyncPlugin
from chantal.plugins.rpm import RpmPublisher


@click.group()
@click.version_option(version=__version__)
@click.option(
    "--config",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to configuration file (default: /etc/chantal/config.yaml)",
)
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def cli(ctx: click.Context, config: Optional[Path], verbose: bool) -> None:
    """Chantal - Unified offline repository mirroring.

    Because every other name was already taken.
    """
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose

    # Load configuration
    try:
        ctx.obj["config"] = load_config(config)
    except FileNotFoundError:
        if config:
            # User specified a config file that doesn't exist - fail
            click.echo(f"Error: Configuration file not found: {config}", err=True)
            ctx.exit(1)
        else:
            # No config file found, use defaults
            ctx.obj["config"] = GlobalConfig()

    if verbose:
        click.echo(f"Loaded configuration: {len(ctx.obj['config'].repositories)} repositories")


@cli.command()
@click.pass_context
def init(ctx: click.Context) -> None:
    """Initialize Chantal (create directories, database schema)."""
    config: GlobalConfig = ctx.obj["config"]

    click.echo("Chantal initialization...")
    click.echo(f"Database: {config.database.url}")
    click.echo(f"Storage base path: {config.storage.base_path}")
    click.echo(f"Pool path: {config.storage.get_pool_path()}")
    click.echo(f"Published path: {config.storage.published_path}")
    click.echo()

    # Create directories
    click.echo("Creating directories...")
    base_path = Path(config.storage.base_path)
    pool_path = Path(config.storage.get_pool_path())
    published_path = Path(config.storage.published_path)

    for path in [base_path, pool_path, published_path]:
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            click.echo(f"  ✓ Created: {path}")
        else:
            click.echo(f"  - Already exists: {path}")

    # Initialize database
    click.echo("\nInitializing database...")
    db_manager = DatabaseManager(config.database.url)
    db_manager.create_all()
    click.echo("  ✓ Database schema created")

    click.echo("\n✓ Chantal initialized successfully!")


@cli.group()
def repo() -> None:
    """Repository management commands."""
    pass


@repo.command("list")
@click.pass_context
def repo_list(ctx: click.Context) -> None:
    """List configured repositories."""
    click.echo("Configured Repositories:")
    click.echo("TODO: Load and display repositories")


@repo.command("sync")
@click.option("--repo-id", help="Repository ID to sync")
@click.option("--all", is_flag=True, help="Sync all enabled repositories")
@click.option("--type", help="Filter by repository type (rpm, apt) when using --all")
@click.option("--workers", type=int, default=1, help="Number of parallel workers for --all")
@click.pass_context
def repo_sync(
    ctx: click.Context,
    repo_id: str,
    all: bool,
    type: str,
    workers: int,
) -> None:
    """Sync repository from upstream.

    Downloads packages from upstream and stores them in the content-addressed pool.
    Does NOT create snapshots automatically - use 'chantal snapshot create' for that.

    Either specify --repo-id for a single repository or --all for all enabled repositories.
    """
    if not repo_id and not all:
        click.echo("Error: Either --repo-id or --all is required")
        raise click.Abort()

    if repo_id and all:
        click.echo("Error: Cannot use both --repo-id and --all")
        raise click.Abort()

    config: GlobalConfig = ctx.obj["config"]

    # Initialize managers
    storage = StorageManager(config.storage)
    db_manager = DatabaseManager(config.database.url)
    session = db_manager.get_session()

    try:
        if all:
            click.echo("Syncing all enabled repositories")
            if type:
                click.echo(f"Filtered by type: {type}")
            if workers > 1:
                click.echo(f"Using {workers} parallel workers")

            # Get all enabled repositories from config
            repos_to_sync = [r for r in config.repositories if r.enabled]
            if type:
                repos_to_sync = [r for r in repos_to_sync if r.type == type]

            if not repos_to_sync:
                click.echo("No enabled repositories found")
                return

            click.echo(f"Found {len(repos_to_sync)} repositories to sync\n")

            # TODO: Implement parallel workers if workers > 1
            for repo_config in repos_to_sync:
                click.echo(f"--- Syncing {repo_config.id} ---")
                _sync_single_repository(session, storage, config, repo_config)
                click.echo()
        else:
            # Sync single repository
            repo_config = next((r for r in config.repositories if r.id == repo_id), None)
            if not repo_config:
                click.echo(f"Error: Repository '{repo_id}' not found in configuration")
                raise click.Abort()

            _sync_single_repository(session, storage, config, repo_config)
    finally:
        session.close()


def _sync_single_repository(session, storage, global_config, repo_config):
    """Helper function to sync a single repository."""
    # Get or create repository in database
    repository = session.query(Repository).filter_by(repo_id=repo_config.id).first()
    if not repository:
        click.echo(f"Creating new repository: {repo_config.id}")
        repository = Repository(
            repo_id=repo_config.id,
            name=repo_config.name or repo_config.id,
            type=repo_config.type,
            feed=repo_config.feed,
            enabled=repo_config.enabled,
        )
        session.add(repository)
        session.commit()

    # Initialize sync plugin based on repository type
    if repo_config.type == "rpm":
        sync_plugin = RpmSyncPlugin(
            storage=storage,
            config=repo_config,
            proxy_config=global_config.proxy,
        )
    else:
        click.echo(f"Error: Unsupported repository type: {repo_config.type}")
        return

    # Perform sync
    result = sync_plugin.sync_repository(session, repository)

    # Display result
    if result.success:
        click.echo(f"\n✓ Sync completed successfully!")
        click.echo(f"  Total packages: {result.packages_total}")
        click.echo(f"  Downloaded: {result.packages_downloaded}")
        click.echo(f"  Skipped (already in pool): {result.packages_skipped}")
        click.echo(f"  Data transferred: {result.bytes_downloaded / 1024 / 1024:.2f} MB")
    else:
        click.echo(f"\n✗ Sync failed: {result.error_message}", err=True)


@repo.command("show")
@click.option("--repo-id", required=True, help="Repository ID")
@click.pass_context
def repo_show(ctx: click.Context, repo_id: str) -> None:
    """Show repository details."""
    click.echo(f"Repository: {repo_id}")
    click.echo("TODO: Show repository configuration and status")


@repo.command("check-updates")
@click.option("--repo-id", required=True, help="Repository ID")
@click.option("--format", "output_format", type=click.Choice(["table", "json"]),
              default="table", help="Output format")
@click.pass_context
def repo_check_updates(ctx: click.Context, repo_id: str, output_format: str) -> None:
    """Check for available updates without syncing.

    Downloads remote metadata and compares with local database
    to show which packages have updates available.
    Similar to 'dnf check-update'.
    """
    click.echo(f"Checking for updates: {repo_id}")
    click.echo("TODO: Download remote metadata and compare with local")
    click.echo()
    click.echo("Expected output:")
    click.echo()
    click.echo("Available Updates:")
    click.echo("  Name                 Local Version        Remote Version       Size")
    click.echo("  ------------------------------------------------------------------------------------")
    click.echo("  kernel              5.14.0-360.el9       5.14.0-362.el9       85 MB")
    click.echo("  nginx               1.20.1-10.el9        1.20.2-1.el9         1.2 MB")
    click.echo("  httpd               2.4.50-1.el9         2.4.51-1.el9         1.5 MB")
    click.echo()
    click.echo("Summary: 3 package updates available (87.7 MB)")
    click.echo()
    click.echo("Run 'chantal repo sync --repo-id {repo_id}' to download updates")


@repo.command("history")
@click.option("--repo-id", required=True, help="Repository ID")
@click.option("--limit", type=int, default=10, help="Number of sync entries to show")
@click.option("--format", "output_format", type=click.Choice(["table", "json"]),
              default="table", help="Output format")
@click.pass_context
def repo_history(ctx: click.Context, repo_id: str, limit: int, output_format: str) -> None:
    """Show sync history for repository.

    Displays past sync operations with status, duration, packages added/removed, etc.
    """
    click.echo(f"Sync History: {repo_id}")
    click.echo(f"Showing last {limit} syncs")
    click.echo()
    click.echo("Expected output:")
    click.echo()
    click.echo("Date                 Status   Packages    Downloaded  Duration")
    click.echo("--------------------------------------------------------------------------------")
    click.echo("2025-01-09 14:30:00  Success  47 added    450 MB      5m 23s")
    click.echo("                              5 updated")
    click.echo("                              2 removed")
    click.echo("2025-01-08 02:00:00  Success  12 added    120 MB      2m 15s")
    click.echo("2025-01-07 02:00:00  Failed   -           -           -")
    click.echo("                              Error: Connection timeout")
    click.echo()
    click.echo("TODO: Query sync_history table from database")


@cli.group()
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
        click.echo(f"{'Name':<30} {'Repository':<20} {'Packages':>10} {'Size':>12} {'Created':<20}")
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

            click.echo(f"{snapshot.name:<30} {repo_name:<20} {snapshot.package_count:>10} {size_str:>12} {created_str:<20}")

        click.echo()
        click.echo(f"Total: {len(snapshots)} snapshot(s)")


@snapshot.command("create")
@click.option("--repo-id", required=True, help="Repository ID")
@click.option("--name", required=True, help="Snapshot name")
@click.option("--description", help="Snapshot description")
@click.pass_context
def snapshot_create(ctx: click.Context, repo_id: str, name: str, description: str) -> None:
    """Create snapshot of repository.

    Creates an immutable point-in-time snapshot of the current repository state.
    The snapshot references packages from the content-addressed pool.
    """
    config: GlobalConfig = ctx.obj["config"]

    click.echo(f"Creating snapshot '{name}' of repository '{repo_id}'...")
    if description:
        click.echo(f"Description: {description}")
    click.echo()

    # Initialize database
    db_manager = DatabaseManager(config.database.url)

    with db_manager.session() as session:
        # Get repository from database
        repository = session.query(Repository).filter_by(repo_id=repo_id).first()
        if not repository:
            click.echo(f"Error: Repository '{repo_id}' not found in database.", err=True)
            click.echo("Run 'chantal repo list' to see available repositories.", err=True)
            ctx.exit(1)

        # Check if snapshot with this name already exists
        existing_snapshot = (
            session.query(Snapshot)
            .filter_by(repository_id=repository.id, name=name)
            .first()
        )
        if existing_snapshot:
            click.echo(f"Error: Snapshot '{name}' already exists for repository '{repo_id}'.", err=True)
            click.echo(f"Created: {existing_snapshot.created_at}", err=True)
            click.echo("Use a different name or delete the existing snapshot first.", err=True)
            ctx.exit(1)

        # Get current packages in repository
        session.refresh(repository)
        packages = list(repository.packages)

        if not packages:
            click.echo(f"Warning: Repository '{repo_id}' has no packages.", err=True)
            click.echo("Sync the repository first with: chantal repo sync --repo-id {repo_id}")
            ctx.exit(1)

        # Calculate statistics
        package_count = len(packages)
        total_size_bytes = sum(pkg.size_bytes for pkg in packages)

        click.echo(f"Repository has {package_count} packages ({total_size_bytes / (1024**3):.2f} GB)")

        # Create snapshot
        snapshot = Snapshot(
            repository_id=repository.id,
            name=name,
            description=description,
            package_count=package_count,
            total_size_bytes=total_size_bytes,
        )

        # Link packages to snapshot
        snapshot.packages = packages

        session.add(snapshot)
        session.commit()

        click.echo()
        click.echo(f"✓ Snapshot '{name}' created successfully!")
        click.echo(f"  Repository: {repo_id}")
        click.echo(f"  Packages: {package_count}")
        click.echo(f"  Total size: {total_size_bytes / (1024**3):.2f} GB")
        click.echo(f"  Created: {snapshot.created_at}")
        click.echo()
        click.echo(f"To publish this snapshot:")
        click.echo(f"  chantal publish snapshot --snapshot {name}")


@snapshot.command("diff")
@click.option("--repo-id", required=True, help="Repository ID")
@click.argument("snapshot1")
@click.argument("snapshot2")
@click.option("--format", "output_format", type=click.Choice(["table", "json"]),
              default="table", help="Output format")
@click.pass_context
def snapshot_diff(ctx: click.Context, repo_id: str, snapshot1: str, snapshot2: str, output_format: str) -> None:
    """Compare two snapshots within a repository.

    Shows packages that were added, removed, or updated between two snapshots
    of the same repository. Perfect for generating patch announcements!
    """
    config: GlobalConfig = ctx.obj["config"]
    db_manager = DatabaseManager(config.database.url)

    with db_manager.session() as session:
        # Get repository
        repository = session.query(Repository).filter_by(repo_id=repo_id).first()
        if not repository:
            click.echo(f"Error: Repository '{repo_id}' not found.", err=True)
            ctx.exit(1)

        # Get both snapshots
        snap1 = (
            session.query(Snapshot)
            .filter_by(repository_id=repository.id, name=snapshot1)
            .first()
        )
        snap2 = (
            session.query(Snapshot)
            .filter_by(repository_id=repository.id, name=snapshot2)
            .first()
        )

        if not snap1:
            click.echo(f"Error: Snapshot '{snapshot1}' not found.", err=True)
            ctx.exit(1)
        if not snap2:
            click.echo(f"Error: Snapshot '{snapshot2}' not found.", err=True)
            ctx.exit(1)

        # Get packages for both snapshots
        packages1 = {pkg.sha256: pkg for pkg in snap1.packages}
        packages2 = {pkg.sha256: pkg for pkg in snap2.packages}

        # Calculate differences
        added_sha256s = set(packages2.keys()) - set(packages1.keys())
        removed_sha256s = set(packages1.keys()) - set(packages2.keys())
        common_sha256s = set(packages1.keys()) & set(packages2.keys())

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
            import json
            result = {
                "repository": repo_id,
                "snapshot1": snapshot1,
                "snapshot2": snapshot2,
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
            click.echo(f"Comparing: {snapshot1} → {snapshot2}")
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

            click.echo(f"Summary: {len(added)} added, {len(removed)} removed, {len(updated)} updated")


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
    storage = StorageManager(config.storage)

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
            click.echo(f"Error: Snapshot '{snapshot_name}' not found for repository '{repo_id}'.", err=True)
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


@cli.group()
def package() -> None:
    """Package management commands."""
    pass


@package.command("list")
@click.option("--repo-id", required=True, help="Repository ID")
@click.option("--limit", type=int, default=100, help="Limit number of results")
@click.option("--arch", help="Filter by architecture (e.g., x86_64, noarch)")
@click.option("--format", "output_format", type=click.Choice(["table", "json", "csv"]),
              default="table", help="Output format")
@click.pass_context
def package_list(
    ctx: click.Context, repo_id: str, limit: int, arch: str, output_format: str
) -> None:
    """List packages in repository."""
    click.echo(f"Packages in repository: {repo_id}")
    if arch:
        click.echo(f"Filtered by architecture: {arch}")
    click.echo(f"Showing up to {limit} packages")
    click.echo(f"Format: {output_format}")
    click.echo("TODO: Query packages from database")


@package.command("search")
@click.argument("query")
@click.option("--repo-id", help="Search in specific repository only")
@click.option("--arch", help="Filter by architecture")
@click.option("--format", "output_format", type=click.Choice(["table", "json"]),
              default="table", help="Output format")
@click.pass_context
def package_search(
    ctx: click.Context, query: str, repo_id: str, arch: str, output_format: str
) -> None:
    """Search for packages by name."""
    click.echo(f"Searching for: {query}")
    if repo_id:
        click.echo(f"In repository: {repo_id}")
    if arch:
        click.echo(f"Architecture: {arch}")
    click.echo("TODO: Search packages in database")


@package.command("show")
@click.argument("package")
@click.pass_context
def package_show(ctx: click.Context, package: str) -> None:
    """Show detailed package information.

    PACKAGE can be either:
    - Full NEVRA: nginx-1.20.1-10.el9.x86_64
    - SHA256 checksum: abc123...
    """
    click.echo(f"Package: {package}")
    click.echo("TODO: Query package details from database")
    click.echo()
    click.echo("Expected output:")
    click.echo("  Name: nginx")
    click.echo("  Version: 1.20.1-10.el9")
    click.echo("  Arch: x86_64")
    click.echo("  Size: 1.2 MB")
    click.echo("  SHA256: abc123...")
    click.echo("  Repositories: rhel9-baseos, rhel9-appstream")
    click.echo("  Snapshots: rhel9-baseos-20250109, ...")


@cli.command("stats")
@click.option("--repo-id", help="Show statistics for specific repository")
@click.pass_context
def stats(ctx: click.Context, repo_id: str) -> None:
    """Show repository and package statistics."""
    if repo_id:
        click.echo(f"Statistics for repository: {repo_id}")
        click.echo("TODO: Query repository-specific statistics")
    else:
        click.echo("Global Statistics:")
        click.echo("TODO: Query global statistics")
    click.echo()
    click.echo("Expected output:")
    click.echo("  Total Repositories: 5")
    click.echo("  Total Packages: 12,450")
    click.echo("  Deduplicated: 8,320 (33% savings)")
    click.echo("  Total Size on Disk: 18.5 GB")
    click.echo("  Total Snapshots: 23")


@cli.group()
def db() -> None:
    """Database management commands."""
    pass


@db.command("cleanup")
@click.option("--dry-run", is_flag=True, help="Show what would be deleted")
@click.pass_context
def db_cleanup(ctx: click.Context, dry_run: bool) -> None:
    """Remove unreferenced packages from pool."""
    if dry_run:
        click.echo("DRY RUN: Would cleanup unreferenced packages")
    else:
        click.echo("Cleaning up unreferenced packages...")
    click.echo("TODO: Implement cleanup logic")


@db.command("stats")
@click.pass_context
def db_stats(ctx: click.Context) -> None:
    """Show database statistics."""
    click.echo("Database Statistics:")
    click.echo("TODO: Query database statistics")
    click.echo()
    click.echo("Expected output:")
    click.echo("  Total Packages: 8,320")
    click.echo("  Referenced Packages: 8,273 (99%)")
    click.echo("  Unreferenced Packages: 47 (1%, 450 MB)")
    click.echo("  Total Repositories: 5")
    click.echo("  Total Snapshots: 23")
    click.echo("  Database Size: 245 MB")


@db.command("verify")
@click.pass_context
def db_verify(ctx: click.Context) -> None:
    """Verify database integrity."""
    click.echo("Verifying database integrity...")
    click.echo("TODO: Implement database verification")
    click.echo()
    click.echo("Expected checks:")
    click.echo("  - All packages in database have files in pool")
    click.echo("  - All pool files have database entries")
    click.echo("  - Foreign key constraints are valid")


@cli.group()
def pool() -> None:
    """Storage pool management commands."""
    pass


@pool.command("stats")
@click.pass_context
def pool_stats(ctx: click.Context) -> None:
    """Show storage pool statistics."""
    from chantal.core.storage import StorageManager
    from chantal.db.connection import DatabaseManager

    config: GlobalConfig = ctx.obj["config"]

    # Initialize storage manager
    storage = StorageManager(config.storage)

    # Initialize database connection
    db_manager = DatabaseManager(config.database.url)
    session = db_manager.get_session()

    try:
        # Get statistics
        stats = storage.get_pool_statistics(session)

        click.echo("Storage Pool Statistics:")
        click.echo("=" * 60)
        click.echo(f"Pool Path: {stats['pool_path']}")
        click.echo()
        click.echo(f"Packages in Database:    {stats['total_packages_db']:,}")
        click.echo(f"Database Size:           {stats['total_size_db']:,} bytes ({stats['total_size_db'] / (1024**3):.2f} GB)")
        click.echo()
        click.echo(f"Files in Pool:           {stats['total_files_pool']:,}")
        click.echo(f"Pool Size on Disk:       {stats['total_size_pool']:,} bytes ({stats['total_size_pool'] / (1024**3):.2f} GB)")
        click.echo()
        click.echo(f"Orphaned Files:          {stats['orphaned_files']:,}")

        if stats['deduplication_savings'] > 0:
            savings_pct = (stats['deduplication_savings'] / stats['total_size_db']) * 100 if stats['total_size_db'] > 0 else 0
            click.echo(f"Deduplication Savings:   {stats['deduplication_savings']:,} bytes ({savings_pct:.1f}%)")

    finally:
        session.close()


@pool.command("cleanup")
@click.option("--dry-run", is_flag=True, help="Show what would be deleted without actually deleting")
@click.pass_context
def pool_cleanup(ctx: click.Context, dry_run: bool) -> None:
    """Remove orphaned files from storage pool.

    Orphaned files are package files in the pool that are not referenced
    in the database. This can happen after package deletion or cleanup operations.
    """
    from chantal.core.storage import StorageManager
    from chantal.db.connection import DatabaseManager

    config: GlobalConfig = ctx.obj["config"]

    # Initialize storage manager
    storage = StorageManager(config.storage)

    # Initialize database connection
    db_manager = DatabaseManager(config.database.url)
    session = db_manager.get_session()

    try:
        if dry_run:
            click.echo("DRY RUN: Finding orphaned files...")
        else:
            click.echo("Cleaning up orphaned files...")

        click.echo()

        # Cleanup orphaned files
        files_removed, bytes_freed = storage.cleanup_orphaned_files(session, dry_run=dry_run)

        if dry_run:
            click.echo(f"Would remove {files_removed:,} orphaned files")
            click.echo(f"Would free {bytes_freed:,} bytes ({bytes_freed / (1024**2):.2f} MB)")
        else:
            click.echo(f"Removed {files_removed:,} orphaned files")
            click.echo(f"Freed {bytes_freed:,} bytes ({bytes_freed / (1024**2):.2f} MB)")

    finally:
        session.close()


@pool.command("verify")
@click.pass_context
def pool_verify(ctx: click.Context) -> None:
    """Verify storage pool integrity.

    Checks:
    - All packages in database have corresponding files in pool
    - All pool files match their recorded SHA256 checksums
    - Pool directory structure is correct
    """
    from chantal.core.storage import StorageManager
    from chantal.db.connection import DatabaseManager
    from chantal.db.models import Package

    config: GlobalConfig = ctx.obj["config"]

    # Initialize storage manager
    storage = StorageManager(config.storage)

    # Initialize database connection
    db_manager = DatabaseManager(config.database.url)
    session = db_manager.get_session()

    try:
        click.echo("Verifying storage pool integrity...")
        click.echo("=" * 60)
        click.echo()

        errors = 0
        warnings = 0

        # Get all packages from database
        packages = session.query(Package).all()
        click.echo(f"Checking {len(packages):,} packages...")

        for i, package in enumerate(packages, 1):
            if i % 100 == 0:
                click.echo(f"  Checked {i:,}/{len(packages):,} packages...", nl=False)
                click.echo("\r", nl=False)

            # Check if file exists
            pool_file = storage.pool_path / package.pool_path

            if not pool_file.exists():
                click.echo(f"ERROR: Missing pool file for {package.filename} (SHA256: {package.sha256[:8]}...)")
                errors += 1
                continue

            # Verify SHA256
            actual_sha256 = storage.calculate_sha256(pool_file)
            if actual_sha256 != package.sha256:
                click.echo(f"ERROR: SHA256 mismatch for {package.filename}")
                click.echo(f"  Expected: {package.sha256}")
                click.echo(f"  Actual:   {actual_sha256}")
                errors += 1

            # Verify file size
            actual_size = pool_file.stat().st_size
            if actual_size != package.size_bytes:
                click.echo(f"WARNING: Size mismatch for {package.filename}")
                click.echo(f"  Expected: {package.size_bytes:,} bytes")
                click.echo(f"  Actual:   {actual_size:,} bytes")
                warnings += 1

        click.echo()
        click.echo("=" * 60)

        if errors == 0 and warnings == 0:
            click.echo("✓ Pool verification completed successfully!")
            click.echo(f"  All {len(packages):,} packages verified")
        else:
            click.echo(f"Pool verification completed with issues:")
            if errors > 0:
                click.echo(f"  Errors: {errors}")
            if warnings > 0:
                click.echo(f"  Warnings: {warnings}")

    finally:
        session.close()


@cli.group()
def publish() -> None:
    """Publishing management commands."""
    pass


@publish.command("repo")
@click.option("--repo-id", help="Repository ID to publish")
@click.option("--all", is_flag=True, help="Publish all repositories")
@click.option("--target", help="Custom target directory (default: from config)")
@click.pass_context
def publish_repo(ctx: click.Context, repo_id: str, all: bool, target: str) -> None:
    """Publish repository to target directory.

    Creates hardlinks from package pool to published repository directory.
    Updates repository metadata (repomd.xml, etc.).
    """
    if not repo_id and not all:
        click.echo("Error: Either --repo-id or --all is required")
        raise click.Abort()

    if repo_id and all:
        click.echo("Error: Cannot use both --repo-id and --all")
        raise click.Abort()

    config: GlobalConfig = ctx.obj["config"]

    # Initialize managers
    storage = StorageManager(config.storage)
    db_manager = DatabaseManager(config.database.url)
    session = db_manager.get_session()

    try:
        if all:
            click.echo("Publishing all repositories")
            repos_to_publish = config.repositories

            if not repos_to_publish:
                click.echo("No repositories found in configuration")
                return

            click.echo(f"Found {len(repos_to_publish)} repositories to publish\n")

            for repo_config in repos_to_publish:
                click.echo(f"--- Publishing {repo_config.id} ---")
                _publish_single_repository(session, storage, config, repo_config, target)
                click.echo()
        else:
            # Publish single repository
            repo_config = next((r for r in config.repositories if r.id == repo_id), None)
            if not repo_config:
                click.echo(f"Error: Repository '{repo_id}' not found in configuration")
                raise click.Abort()

            _publish_single_repository(session, storage, config, repo_config, target)
    finally:
        session.close()


def _publish_single_repository(session, storage, global_config, repo_config, custom_target=None):
    """Helper function to publish a single repository."""
    # Get repository from database
    repository = session.query(Repository).filter_by(repo_id=repo_config.id).first()
    if not repository:
        click.echo(f"Error: Repository '{repo_config.id}' not found in database. Sync it first.")
        return

    # Determine target path
    if custom_target:
        target_path = Path(custom_target)
    else:
        # Use configured published path + repo_id
        target_path = Path(global_config.storage.published_path) / repo_config.id

    click.echo(f"Publishing repository: {repo_config.id}")
    click.echo(f"Target: {target_path}")

    # Initialize publisher based on repository type
    if repo_config.type == "rpm":
        publisher = RpmPublisher(storage=storage)
    else:
        click.echo(f"Error: Unsupported repository type: {repo_config.type}")
        return

    # Publish repository
    try:
        publisher.publish_repository(
            session=session,
            repository=repository,
            config=repo_config,
            target_path=target_path
        )
        click.echo(f"\n✓ Repository published successfully!")
        click.echo(f"  Location: {target_path}")
        click.echo(f"  Packages directory: {target_path}/Packages")
        click.echo(f"  Metadata directory: {target_path}/repodata")
    except Exception as e:
        click.echo(f"\n✗ Publishing failed: {e}", err=True)
        raise


@publish.command("snapshot")
@click.option("--snapshot", required=True, help="Snapshot name to publish")
@click.option("--repo-id", help="Repository ID (optional if snapshot name is unique)")
@click.option("--target", help="Custom target directory (default: published_path/snapshots/<repo>/<snapshot>)")
@click.pass_context
def publish_snapshot(ctx: click.Context, snapshot: str, repo_id: str, target: str) -> None:
    """Publish a specific snapshot.

    Creates hardlinks from package pool to snapshot directory with RPM metadata.
    Perfect for creating immutable snapshots or parallel environments.
    """
    config: GlobalConfig = ctx.obj["config"]
    db_manager = DatabaseManager(config.database.url)
    storage = StorageManager(config.storage)

    with db_manager.session() as session:
        # Get snapshot from database
        query = session.query(Snapshot).filter_by(name=snapshot)

        if repo_id:
            # Filter by repository if specified
            repository = session.query(Repository).filter_by(repo_id=repo_id).first()
            if not repository:
                click.echo(f"Error: Repository '{repo_id}' not found.", err=True)
                ctx.exit(1)
            query = query.filter_by(repository_id=repository.id)

        snap = query.first()

        if not snap:
            if repo_id:
                click.echo(f"Error: Snapshot '{snapshot}' not found for repository '{repo_id}'.", err=True)
            else:
                click.echo(f"Error: Snapshot '{snapshot}' not found.", err=True)
                click.echo("Specify --repo-id if multiple repositories have snapshots with this name.", err=True)
            ctx.exit(1)

        # Get repository
        repository = session.query(Repository).filter_by(id=snap.repository_id).first()

        # Find repository config
        repo_config = None
        for rc in config.repositories:
            if rc.id == repository.repo_id:
                repo_config = rc
                break

        if not repo_config:
            click.echo(f"Error: Repository configuration '{repository.repo_id}' not found in config.", err=True)
            ctx.exit(1)

        # Determine target path
        if target:
            target_path = Path(target)
        else:
            # Default: published_path/snapshots/<repo-id>/<snapshot-name>
            target_path = Path(config.storage.published_path) / "snapshots" / repository.repo_id / snapshot

        click.echo(f"Publishing snapshot: {snapshot}")
        click.echo(f"Repository: {repository.repo_id}")
        click.echo(f"Target: {target_path}")
        click.echo(f"Packages: {snap.package_count}")
        click.echo()

        # Initialize publisher based on repository type
        if repo_config.type == "rpm":
            publisher = RpmPublisher(storage=storage)
        else:
            click.echo(f"Error: Unsupported repository type: {repo_config.type}", err=True)
            ctx.exit(1)

        # Publish snapshot
        try:
            publisher.publish_snapshot(
                session=session,
                snapshot=snap,
                repository=repository,
                config=repo_config,
                target_path=target_path
            )

            # Update snapshot metadata
            snap.is_published = True
            snap.published_path = str(target_path)
            session.commit()

            click.echo()
            click.echo(f"✓ Snapshot published successfully!")
            click.echo(f"  Location: {target_path}")
            click.echo(f"  Packages directory: {target_path}/Packages")
            click.echo(f"  Metadata directory: {target_path}/repodata")
            click.echo()
            click.echo(f"Configure your package manager:")
            click.echo(f"  [rhel9-baseos-snapshot-{snapshot}]")
            click.echo(f"  name=RHEL 9 BaseOS Snapshot {snapshot}")
            click.echo(f"  baseurl=file://{target_path}")
            click.echo(f"  enabled=1")
            click.echo(f"  gpgcheck=0")

        except Exception as e:
            click.echo(f"\n✗ Publishing failed: {e}", err=True)
            raise


@publish.command("list")
@click.pass_context
def publish_list(ctx: click.Context) -> None:
    """List currently published repositories and snapshots."""
    click.echo("Currently Published:")
    click.echo()
    click.echo("Expected output:")
    click.echo()
    click.echo("Repositories:")
    click.echo("  rhel9-baseos     → /var/www/repos/rhel9-baseos/latest")
    click.echo("  rhel9-appstream  → /var/www/repos/rhel9-appstream/latest")
    click.echo()
    click.echo("Snapshots:")
    click.echo("  rhel9-baseos-20250109  → /var/www/repos/rhel9-baseos/snapshots/20250109")
    click.echo("  rhel9-baseos-20250108  → /var/www/repos/rhel9-baseos/snapshots/20250108")
    click.echo()
    click.echo("TODO: Query database for published repos/snapshots")


@publish.command("unpublish")
@click.option("--repo-id", help="Repository ID to unpublish")
@click.option("--snapshot", help="Snapshot name to unpublish")
@click.pass_context
def publish_unpublish(ctx: click.Context, repo_id: str, snapshot: str) -> None:
    """Unpublish repository or snapshot.

    Removes the published directory (hardlinks). Does not delete packages from pool.
    """
    if not repo_id and not snapshot:
        click.echo("Error: Either --repo-id or --snapshot is required")
        raise click.Abort()

    if repo_id and snapshot:
        click.echo("Error: Cannot use both --repo-id and --snapshot")
        raise click.Abort()

    if repo_id:
        click.echo(f"Unpublishing repository: {repo_id}")
    else:
        click.echo(f"Unpublishing snapshot: {snapshot}")

    click.echo("TODO: Remove published directory")


def main() -> None:
    """Main entry point."""
    cli(obj={})


if __name__ == "__main__":
    main()
