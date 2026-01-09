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


def main() -> None:
    """Main entry point."""
    cli(obj={})


if __name__ == "__main__":
    main()
