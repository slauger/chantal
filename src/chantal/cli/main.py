"""
Main CLI entry point for Chantal.

This module provides the Click-based command-line interface for Chantal.
"""

import click
from pathlib import Path

from chantal import __version__


@click.group()
@click.version_option(version=__version__)
@click.option(
    "--config-dir",
    type=click.Path(path_type=Path),
    default="/etc/chantal",
    help="Configuration directory",
)
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def cli(ctx: click.Context, config_dir: Path, verbose: bool) -> None:
    """Chantal - Unified offline repository mirroring.

    Because every other name was already taken.
    """
    ctx.ensure_object(dict)
    ctx.obj["config_dir"] = config_dir
    ctx.obj["verbose"] = verbose


@cli.command()
@click.pass_context
def init(ctx: click.Context) -> None:
    """Initialize Chantal (create directories, database schema)."""
    click.echo("Chantal initialization...")
    click.echo(f"Config directory: {ctx.obj['config_dir']}")
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
@click.option("--repo-id", required=True, help="Repository ID to sync")
@click.option("--create-snapshot", is_flag=True, help="Create snapshot after sync")
@click.option("--snapshot-name", help="Custom snapshot name")
@click.pass_context
def repo_sync(
    ctx: click.Context, repo_id: str, create_snapshot: bool, snapshot_name: str
) -> None:
    """Sync repository from upstream."""
    click.echo(f"Syncing repository: {repo_id}")
    if create_snapshot:
        click.echo(f"Will create snapshot: {snapshot_name or 'auto-generated'}")
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
@click.pass_context
def snapshot_create(ctx: click.Context, repo_id: str, name: str) -> None:
    """Create snapshot of repository."""
    click.echo(f"Creating snapshot '{name}' of repository '{repo_id}'")
    click.echo("TODO: Implement snapshot creation")


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


def main() -> None:
    """Main entry point."""
    cli(obj={})


if __name__ == "__main__":
    main()
