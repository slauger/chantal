"""
Main CLI entry point for Chantal.

This module provides the Click-based command-line interface for Chantal.
"""

import click
from pathlib import Path
from typing import Optional

from chantal import __version__
from chantal.core.config import GlobalConfig, load_config


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
    click.echo("TODO: Create directories and database schema")


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

    if all:
        click.echo("Syncing all enabled repositories")
        if type:
            click.echo(f"Filtered by type: {type}")
        if workers > 1:
            click.echo(f"Using {workers} parallel workers")
        click.echo("TODO: Implement batch sync logic")
    else:
        click.echo(f"Syncing repository: {repo_id}")
        click.echo("TODO: Implement sync logic")


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
    """List snapshots."""
    if repo_id:
        click.echo(f"Snapshots for repository: {repo_id}")
    else:
        click.echo("All snapshots:")
    click.echo("TODO: List snapshots from database")


@snapshot.command("create")
@click.option("--repo-id", required=True, help="Repository ID")
@click.option("--name", required=True, help="Snapshot name")
@click.option("--description", help="Snapshot description")
@click.pass_context
def snapshot_create(ctx: click.Context, repo_id: str, name: str, description: str) -> None:
    """Create snapshot of repository."""
    click.echo(f"Creating snapshot '{name}' of repository '{repo_id}'")
    if description:
        click.echo(f"Description: {description}")
    click.echo("TODO: Implement snapshot creation")


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
    of the same repository.
    """
    click.echo(f"Repository: {repo_id}")
    click.echo(f"Comparing snapshots: {snapshot1} → {snapshot2}")
    click.echo()
    click.echo("Expected output:")
    click.echo()
    click.echo("Added (5):")
    click.echo("  + kernel-5.14.0-362.el9.x86_64")
    click.echo("  + nginx-1.20.2-1.el9.x86_64")
    click.echo("  + httpd-2.4.51-1.el9.x86_64")
    click.echo("  + glibc-2.34-61.el9.x86_64")
    click.echo("  + systemd-252-14.el9.x86_64")
    click.echo()
    click.echo("Removed (2):")
    click.echo("  - kernel-5.14.0-360.el9.x86_64")
    click.echo("  - nginx-1.20.1-10.el9.x86_64")
    click.echo()
    click.echo("Updated (3):")
    click.echo("  ~ httpd: 2.4.50-1.el9 → 2.4.51-1.el9")
    click.echo("  ~ glibc: 2.34-60.el9 → 2.34-61.el9")
    click.echo("  ~ systemd: 252-13.el9 → 252-14.el9")
    click.echo()
    click.echo("Summary: 5 added, 2 removed, 3 updated")
    click.echo("TODO: Query database and compare package lists")


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

    if all:
        click.echo("Publishing all repositories")
        click.echo("TODO: Publish all repos to their configured paths")
    else:
        click.echo(f"Publishing repository: {repo_id}")
        if target:
            click.echo(f"Target: {target}")
        click.echo("TODO: Create hardlinks and generate metadata")


@publish.command("snapshot")
@click.option("--snapshot", required=True, help="Snapshot name to publish")
@click.option("--target", help="Custom target directory (default: from config)")
@click.pass_context
def publish_snapshot(ctx: click.Context, snapshot: str, target: str) -> None:
    """Publish a specific snapshot.

    Creates hardlinks from package pool to snapshot directory.
    Useful for publishing older snapshots or creating parallel environments.
    """
    click.echo(f"Publishing snapshot: {snapshot}")
    if target:
        click.echo(f"Target: {target}")
    click.echo("TODO: Create hardlinks and generate metadata for snapshot")


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
