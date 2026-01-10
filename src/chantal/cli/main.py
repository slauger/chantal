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
from chantal.db.models import Repository, Snapshot, SyncHistory, Package
from chantal.plugins.rpm_sync import RpmSyncPlugin, CheckUpdatesResult, PackageUpdate
from chantal.plugins.rpm import RpmPublisher

# Click context settings to enable -h as alias for --help
CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(version=__version__)
@click.option(
    "--config",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to configuration file (default: /etc/chantal/config.yaml, or $CHANTAL_CONFIG)",
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
    except ValueError as e:
        # YAML syntax error or validation error
        click.echo(f"Error: {e}", err=True)
        ctx.exit(1)

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


@cli.group(context_settings=CONTEXT_SETTINGS)
def repo() -> None:
    """Repository management commands."""
    pass


@repo.command("list")
@click.option("--format", "output_format", type=click.Choice(["table", "json"]),
              default="table", help="Output format")
@click.pass_context
def repo_list(ctx: click.Context, output_format: str) -> None:
    """List configured repositories.

    Shows all repositories from config with their current sync status.
    Config is the source of truth - database provides runtime status only.
    """
    config: GlobalConfig = ctx.obj["config"]
    db_manager = DatabaseManager(config.database.url)

    with db_manager.session() as session:
        # Get all repositories from config (source of truth)
        config_repos = config.repositories

        # Get DB status for all repos
        db_repos = {repo.repo_id: repo for repo in session.query(Repository).all()}

        if output_format == "json":
            import json
            result = []
            for repo_config in config_repos:
                db_repo = db_repos.get(repo_config.id)
                result.append({
                    "repo_id": repo_config.id,
                    "name": repo_config.name,
                    "type": repo_config.type,
                    "feed": repo_config.feed,
                    "enabled": repo_config.enabled,
                    "package_count": len(db_repo.packages) if db_repo else 0,
                    "last_sync": db_repo.last_sync_at.isoformat() if db_repo and db_repo.last_sync_at else None,
                    "synced": db_repo is not None,
                })
            click.echo(json.dumps(result, indent=2))
        else:
            # Table format
            click.echo("Configured Repositories:")
            click.echo()

            if not config_repos:
                click.echo("  No repositories configured.")
                click.echo("\nAdd repositories to your config file.")
                return

            # Collect all rows first to calculate column widths
            rows = []
            for repo_config in config_repos:
                db_repo = db_repos.get(repo_config.id)

                enabled_str = "Yes" if repo_config.enabled else "No"
                package_count = len(db_repo.packages) if db_repo else 0

                if db_repo and db_repo.last_sync_at:
                    last_sync_str = db_repo.last_sync_at.strftime("%Y-%m-%d %H:%M")
                else:
                    last_sync_str = "Not synced"

                rows.append({
                    "id": repo_config.id,
                    "type": repo_config.type,
                    "enabled": enabled_str,
                    "packages": str(package_count),
                    "last_sync": last_sync_str,
                })

            # Calculate column widths (minimum 10 chars, based on longest entry)
            col_widths = {
                "id": max(len("ID"), max(len(row["id"]) for row in rows)),
                "type": max(len("Type"), max(len(row["type"]) for row in rows)),
                "enabled": max(len("Enabled"), max(len(row["enabled"]) for row in rows)),
                "packages": max(len("Packages"), max(len(row["packages"]) for row in rows)),
                "last_sync": max(len("Last Sync"), max(len(row["last_sync"]) for row in rows)),
            }

            # Header
            header = f"{('ID'):<{col_widths['id']}} {('Type'):<{col_widths['type']}} {('Enabled'):<{col_widths['enabled']}} {('Packages'):>{col_widths['packages']}} {('Last Sync'):<{col_widths['last_sync']}}"
            click.echo(header)
            click.echo("-" * len(header))

            # Rows
            for row in rows:
                click.echo(f"{row['id']:<{col_widths['id']}} {row['type']:<{col_widths['type']}} {row['enabled']:<{col_widths['enabled']}} {row['packages']:>{col_widths['packages']}} {row['last_sync']:<{col_widths['last_sync']}}")

            click.echo()
            click.echo(f"Total: {len(config_repos)} repository(ies)")


@repo.command("sync")
@click.option("--repo-id", help="Repository ID to sync")
@click.option("--all", is_flag=True, help="Sync all enabled repositories")
@click.option("--pattern", help="Sync repositories matching pattern (e.g., 'epel9-*', '*-latest')")
@click.option("--type", help="Filter by repository type (rpm, apt) when using --all or --pattern")
@click.option("--workers", type=int, default=1, help="Number of parallel workers for --all or --pattern")
@click.pass_context
def repo_sync(
    ctx: click.Context,
    repo_id: str,
    all: bool,
    pattern: str,
    type: str,
    workers: int,
) -> None:
    """Sync repository from upstream.

    Downloads packages from upstream and stores them in the content-addressed pool.
    Does NOT create snapshots automatically - use 'chantal snapshot create' for that.

    Options:
      --repo-id ID       Sync a single repository
      --all              Sync all enabled repositories
      --pattern PATTERN  Sync repositories matching pattern (e.g., 'epel9-*', '*-latest')
      --type TYPE        Filter by repository type (rpm, apt)

    Examples:
      chantal repo sync --repo-id rhel9-baseos-vim-latest
      chantal repo sync --all
      chantal repo sync --pattern "epel9-*"
      chantal repo sync --pattern "*-latest" --type rpm
    """
    if not repo_id and not all and not pattern:
        click.echo("Error: Either --repo-id, --all, or --pattern is required")
        raise click.Abort()

    if sum([bool(repo_id), bool(all), bool(pattern)]) > 1:
        click.echo("Error: Cannot use multiple selection methods (--repo-id, --all, --pattern)")
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

        elif pattern:
            import fnmatch

            click.echo(f"Syncing repositories matching pattern: {pattern}")
            if type:
                click.echo(f"Filtered by type: {type}")
            if workers > 1:
                click.echo(f"Using {workers} parallel workers")

            # Get all enabled repositories matching pattern
            repos_to_sync = [
                r for r in config.repositories
                if r.enabled and fnmatch.fnmatch(r.id, pattern)
            ]
            if type:
                repos_to_sync = [r for r in repos_to_sync if r.type == type]

            if not repos_to_sync:
                click.echo(f"No enabled repositories found matching pattern '{pattern}'")
                click.echo("\nAvailable enabled repositories:")
                for r in config.repositories:
                    if r.enabled:
                        click.echo(f"  - {r.id}")
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

    # Merge proxy and SSL config: repo-specific overrides global
    effective_proxy = repo_config.proxy if repo_config.proxy is not None else global_config.proxy
    effective_ssl = repo_config.ssl if repo_config.ssl is not None else global_config.ssl

    # Initialize sync plugin based on repository type
    if repo_config.type == "rpm":
        sync_plugin = RpmSyncPlugin(
            storage=storage,
            config=repo_config,
            proxy_config=effective_proxy,
            ssl_config=effective_ssl,
        )
    else:
        click.echo(f"Error: Unsupported repository type: {repo_config.type}")
        return

    # Perform sync
    result = sync_plugin.sync_repository(session, repository)

    # Display result
    if result.success:
        # Update last sync timestamp
        from datetime import datetime, timezone
        repository.last_sync_at = datetime.now(timezone.utc)
        session.commit()

        click.echo(f"\n✓ Sync completed successfully!")
        click.echo(f"  Total packages: {result.packages_total}")
        click.echo(f"  Downloaded: {result.packages_downloaded}")
        click.echo(f"  Skipped (already in pool): {result.packages_skipped}")
        click.echo(f"  Data transferred: {result.bytes_downloaded / 1024 / 1024:.2f} MB")
    else:
        click.echo(f"\n✗ Sync failed: {result.error_message}", err=True)


@repo.command("show")
@click.option("--repo-id", required=True, help="Repository ID")
@click.option("--format", "output_format", type=click.Choice(["table", "json"]),
              default="table", help="Output format")
@click.pass_context
def repo_show(ctx: click.Context, repo_id: str, output_format: str) -> None:
    """Show detailed repository information.

    Displays comprehensive repository details including configuration,
    package statistics, sync history, and snapshots.
    """
    config: GlobalConfig = ctx.obj["config"]
    db_manager = DatabaseManager(config.database.url)

    with db_manager.session() as session:
        # Get repository from database
        repository = session.query(Repository).filter_by(repo_id=repo_id).first()

        if not repository:
            click.echo(f"Error: Repository '{repo_id}' not found in database.", err=True)
            click.echo("Run 'chantal repo list' to see available repositories.", err=True)
            ctx.exit(1)

        # Get repository config from YAML
        repo_config = next((r for r in config.repositories if r.id == repo_id), None)

        # Get statistics
        session.refresh(repository)
        packages = list(repository.packages)
        package_count = len(packages)
        total_size_bytes = sum(pkg.size_bytes for pkg in packages) if packages else 0

        # Get snapshots count
        snapshots = session.query(Snapshot).filter_by(repository_id=repository.id).all()
        snapshot_count = len(snapshots)

        if output_format == "json":
            import json
            result = {
                "repo_id": repository.repo_id,
                "name": repository.name,
                "type": repository.type,
                "feed": repository.feed,
                "enabled": repository.enabled,
                "statistics": {
                    "package_count": package_count,
                    "total_size_bytes": total_size_bytes,
                    "total_size_gb": round(total_size_bytes / (1024**3), 2),
                    "snapshot_count": snapshot_count,
                },
                "sync": {
                    "last_sync": repository.last_sync_at.isoformat() if repository.last_sync_at else None,
                },
                "config": {
                    "has_filters": bool(repo_config.filters) if repo_config else False,
                } if repo_config else None,
            }
            click.echo(json.dumps(result, indent=2))
        else:
            # Table format
            click.echo("=" * 70)
            click.echo(f"Repository: {repository.repo_id}")
            click.echo("=" * 70)
            click.echo()

            click.echo("Configuration:")
            click.echo(f"  Name:         {repository.name}")
            click.echo(f"  Type:         {repository.type}")
            click.echo(f"  Feed URL:     {repository.feed}")
            click.echo(f"  Enabled:      {'Yes' if repository.enabled else 'No'}")

            if repo_config and repo_config.filters:
                click.echo(f"  Filters:      Active")
                if hasattr(repo_config.filters, 'post_processing') and repo_config.filters.post_processing:
                    if repo_config.filters.post_processing.only_latest_version:
                        click.echo(f"                - Only latest versions")
            else:
                click.echo(f"  Filters:      None")

            click.echo()
            click.echo("Statistics:")
            click.echo(f"  Total Packages:   {package_count:,}")

            if total_size_bytes > 0:
                size_gb = total_size_bytes / (1024**3)
                if size_gb >= 1.0:
                    click.echo(f"  Total Size:       {size_gb:.2f} GB")
                else:
                    size_mb = total_size_bytes / (1024**2)
                    click.echo(f"  Total Size:       {size_mb:.1f} MB")
            else:
                click.echo(f"  Total Size:       0 bytes")

            click.echo(f"  Snapshots:        {snapshot_count}")

            click.echo()
            click.echo("Sync Information:")
            if repository.last_sync_at:
                click.echo(f"  Last Sync:    {repository.last_sync_at.strftime('%Y-%m-%d %H:%M:%S')}")
            else:
                click.echo(f"  Last Sync:    Never")
                click.echo()
                click.echo(f"  Run 'chantal repo sync --repo-id {repo_id}' to sync this repository.")

            if snapshots:
                click.echo()
                click.echo(f"Recent Snapshots (showing {min(5, len(snapshots))}):")
                for snap in sorted(snapshots, key=lambda s: s.created_at, reverse=True)[:5]:
                    published = " [PUBLISHED]" if snap.is_published else ""
                    click.echo(f"  - {snap.name:<30} {snap.created_at.strftime('%Y-%m-%d %H:%M')}{published}")

            click.echo()
            click.echo("=" * 70)


@repo.command("check-updates")
@click.option("--repo-id", help="Repository ID to check")
@click.option("--all", is_flag=True, help="Check all enabled repositories")
@click.option("--pattern", help="Check repositories matching pattern (e.g., 'epel9-*', '*-latest')")
@click.option("--type", help="Filter by repository type (rpm, apt) when using --all or --pattern")
@click.option("--format", "output_format", type=click.Choice(["table", "json"]),
              default="table", help="Output format")
@click.pass_context
def repo_check_updates(
    ctx: click.Context,
    repo_id: str,
    all: bool,
    pattern: str,
    type: str,
    output_format: str,
) -> None:
    """Check for available updates without syncing.

    Downloads remote metadata and compares with local database
    to show which packages have updates available.
    Similar to 'dnf check-update'.

    Options:
      --repo-id ID       Check a single repository
      --all              Check all enabled repositories
      --pattern PATTERN  Check repositories matching pattern (e.g., 'epel9-*', '*-latest')
      --type TYPE        Filter by repository type (rpm, apt)

    Examples:
      chantal repo check-updates --repo-id rhel9-baseos-vim-latest
      chantal repo check-updates --all
      chantal repo check-updates --pattern "epel9-*"
      chantal repo check-updates --pattern "*-latest" --type rpm
    """
    if not repo_id and not all and not pattern:
        click.echo("Error: Either --repo-id, --all, or --pattern is required")
        raise click.Abort()

    if sum([bool(repo_id), bool(all), bool(pattern)]) > 1:
        click.echo("Error: Cannot use multiple selection methods (--repo-id, --all, --pattern)")
        raise click.Abort()

    config: GlobalConfig = ctx.obj["config"]

    # Initialize managers
    storage = StorageManager(config.storage)
    db_manager = DatabaseManager(config.database.url)
    session = db_manager.get_session()

    try:
        repos_to_check = []

        if all:
            # Get all enabled repositories from config
            repos_to_check = [r for r in config.repositories if r.enabled]
            if type:
                repos_to_check = [r for r in repos_to_check if r.type == type]

            if not repos_to_check:
                click.echo("No enabled repositories found")
                return

        elif pattern:
            # Pattern matching
            import fnmatch

            click.echo(f"Matching pattern: {pattern}")
            if type:
                click.echo(f"Filtered by type: {type}")

            repos_to_check = [
                r
                for r in config.repositories
                if r.enabled and fnmatch.fnmatch(r.id, pattern)
            ]

            if type:
                repos_to_check = [r for r in repos_to_check if r.type == type]

            if not repos_to_check:
                click.echo(f"No repositories found matching pattern '{pattern}'")
                return

        else:
            # Single repository
            repo_config = config.get_repository(repo_id)
            if not repo_config:
                click.echo(f"Error: Repository not found: {repo_id}")
                raise click.Abort()

            repos_to_check = [repo_config]

        # Check each repository
        all_results = []
        for repo_config in repos_to_check:
            if len(repos_to_check) > 1:
                click.echo(f"\n{'='*80}")
                click.echo(f"Repository: {repo_config.id}")
                click.echo(f"{'='*80}\n")

            result = _check_updates_single_repository(session, storage, config, repo_config)
            all_results.append((repo_config, result))

        # Display combined summary for multiple repos
        if len(repos_to_check) > 1:
            click.echo(f"\n{'='*80}")
            click.echo("SUMMARY")
            click.echo(f"{'='*80}\n")

            total_updates = sum(len(r.updates_available) for _, r in all_results if r.success)
            total_size = sum(r.total_size_bytes for _, r in all_results if r.success)

            click.echo(f"Checked {len(repos_to_check)} repositories")
            click.echo(f"Total updates available: {total_updates}")
            click.echo(f"Total download size: {total_size / 1024 / 1024:.2f} MB")

    finally:
        session.close()


def _check_updates_single_repository(session, storage, global_config, repo_config):
    """Helper function to check updates for a single repository."""
    # Get or create repository in database
    repository = session.query(Repository).filter_by(repo_id=repo_config.id).first()
    if not repository:
        click.echo(f"Repository not found in database: {repo_config.id}")
        click.echo("Run 'chantal repo sync' first to initialize the repository")
        return CheckUpdatesResult(
            updates_available=[],
            total_packages=0,
            total_size_bytes=0,
            success=False,
            error_message="Repository not initialized",
        )

    # Merge proxy and SSL config: repo-specific overrides global
    effective_proxy = repo_config.proxy if repo_config.proxy is not None else global_config.proxy
    effective_ssl = repo_config.ssl if repo_config.ssl is not None else global_config.ssl

    # Initialize sync plugin based on repository type
    if repo_config.type == "rpm":
        sync_plugin = RpmSyncPlugin(
            storage=storage,
            config=repo_config,
            proxy_config=effective_proxy,
            ssl_config=effective_ssl,
        )
    else:
        click.echo(f"Error: Unsupported repository type: {repo_config.type}")
        return CheckUpdatesResult(
            updates_available=[],
            total_packages=0,
            total_size_bytes=0,
            success=False,
            error_message=f"Unsupported repository type: {repo_config.type}",
        )

    # Check for updates
    result = sync_plugin.check_updates(session, repository)

    # Display result
    if result.success:
        if len(result.updates_available) == 0:
            click.echo("\n✓ No updates available. Repository is up to date.")
        else:
            click.echo(f"\nAvailable Updates ({len(result.updates_available)} packages):")
            click.echo()

            # Calculate column widths
            max_name = max((len(u.name) for u in result.updates_available), default=20)
            max_name = min(max_name, 40)  # Cap at 40 chars

            # Header
            header = f"{'Name':<{max_name}}  {'Arch':<10}  {'Local Version':<20}  {'Remote Version':<20}  {'Size':>10}"
            click.echo(header)
            click.echo("=" * len(header))

            # Rows
            for update in result.updates_available:
                if update.is_new:
                    local_ver = "[new]"
                else:
                    local_ver = f"{update.local_version}-{update.local_release}"

                remote_ver = f"{update.remote_version}-{update.remote_release}"
                if update.remote_epoch and update.remote_epoch != "0":
                    remote_ver = f"{update.remote_epoch}:{remote_ver}"

                size_mb = update.size_bytes / 1024 / 1024
                size_str = f"{size_mb:.1f} MB" if size_mb >= 1 else f"{update.size_bytes / 1024:.0f} KB"

                name_display = update.name[:max_name] if len(update.name) > max_name else update.name

                click.echo(
                    f"{name_display:<{max_name}}  {update.arch:<10}  {local_ver:<20}  {remote_ver:<20}  {size_str:>10}"
                )

            click.echo()
            click.echo(f"Summary: {len(result.updates_available)} package update(s) available ({result.total_size_bytes / 1024 / 1024:.2f} MB)")
            click.echo()
            click.echo(f"Run 'chantal repo sync --repo-id {repo_config.id}' to download updates")

    else:
        click.echo(f"\n✗ Check failed: {result.error_message}", err=True)

    return result


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
    config: GlobalConfig = ctx.obj["config"]
    db_manager = DatabaseManager(config.database.url)

    with db_manager.session() as session:
        # Get repository from database
        repository = session.query(Repository).filter_by(repo_id=repo_id).first()

        if not repository:
            click.echo(f"Error: Repository '{repo_id}' not found in database.", err=True)
            click.echo("Run 'chantal repo list' to see available repositories.", err=True)
            ctx.exit(1)

        # Get sync history ordered by most recent first
        history = (
            session.query(SyncHistory)
            .filter_by(repository_id=repository.id)
            .order_by(SyncHistory.started_at.desc())
            .limit(limit)
            .all()
        )

        if output_format == "json":
            import json
            result = []
            for sync in history:
                duration = None
                if sync.completed_at:
                    duration_seconds = (sync.completed_at - sync.started_at).total_seconds()
                    duration = duration_seconds

                result.append({
                    "started_at": sync.started_at.isoformat(),
                    "completed_at": sync.completed_at.isoformat() if sync.completed_at else None,
                    "status": sync.status,
                    "duration_seconds": duration,
                    "packages_added": sync.packages_added,
                    "packages_removed": sync.packages_removed,
                    "packages_updated": sync.packages_updated,
                    "bytes_downloaded": sync.bytes_downloaded,
                    "error_message": sync.error_message,
                })
            click.echo(json.dumps(result, indent=2))
        else:
            # Table format
            click.echo(f"Sync History: {repo_id}")
            click.echo(f"Showing last {limit} sync(s)")
            click.echo()

            if not history:
                click.echo("  No sync history found.")
                click.echo()
                click.echo(f"  Run 'chantal repo sync --repo-id {repo_id}' to sync this repository.")
                return

            click.echo(f"{'Date':<20} {'Status':<10} {'Duration':>10} {'Changes':<30}")
            click.echo("-" * 80)

            for sync in history:
                # Format date
                date_str = sync.started_at.strftime("%Y-%m-%d %H:%M")

                # Format status
                status_str = sync.status.capitalize()

                # Format duration
                if sync.completed_at:
                    duration_seconds = (sync.completed_at - sync.started_at).total_seconds()
                    if duration_seconds >= 60:
                        minutes = int(duration_seconds // 60)
                        seconds = int(duration_seconds % 60)
                        duration_str = f"{minutes}m {seconds}s"
                    else:
                        duration_str = f"{int(duration_seconds)}s"
                else:
                    duration_str = "Running"

                # Format changes
                changes = []
                if sync.packages_added > 0:
                    changes.append(f"+{sync.packages_added}")
                if sync.packages_updated > 0:
                    changes.append(f"~{sync.packages_updated}")
                if sync.packages_removed > 0:
                    changes.append(f"-{sync.packages_removed}")

                if changes:
                    changes_str = " ".join(changes)
                else:
                    changes_str = "No changes"

                click.echo(f"{date_str:<20} {status_str:<10} {duration_str:>10} {changes_str:<30}")

                # Show error message if failed
                if sync.status == "failed" and sync.error_message:
                    click.echo(f"  Error: {sync.error_message}")

            click.echo()
            click.echo(f"Total: {len(history)} sync operation(s)")


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
        packages1 = {pkg.sha256: pkg for pkg in snap1.packages}

        # Get second comparison source (snapshot or upstream)
        if snapshot2.lower() == "upstream":
            # Compare against current repository state
            session.refresh(repository)
            packages2 = {pkg.sha256: pkg for pkg in repository.packages}
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

            packages2 = {pkg.sha256: pkg for pkg in snap2.packages}
            comparison_name = snapshot2

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


@cli.group(context_settings=CONTEXT_SETTINGS)
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
    """List packages in repository.

    Shows packages currently in the specified repository with optional
    architecture filtering.
    """
    config: GlobalConfig = ctx.obj["config"]
    db_manager = DatabaseManager(config.database.url)

    with db_manager.session() as session:
        # Get repository from database
        repository = session.query(Repository).filter_by(repo_id=repo_id).first()

        if not repository:
            click.echo(f"Error: Repository '{repo_id}' not found in database.", err=True)
            click.echo("Run 'chantal repo list' to see available repositories.", err=True)
            ctx.exit(1)

        # Build query for packages in this repository
        session.refresh(repository)
        packages = list(repository.packages)

        # Apply architecture filter if specified
        if arch:
            packages = [pkg for pkg in packages if pkg.arch == arch]

        # Apply limit
        packages = packages[:limit]

        if output_format == "json":
            import json
            result = []
            for pkg in packages:
                result.append({
                    "name": pkg.name,
                    "version": pkg.version,
                    "release": pkg.release,
                    "arch": pkg.arch,
                    "nevra": pkg.nevra,
                    "size_bytes": pkg.size_bytes,
                    "sha256": pkg.sha256,
                })
            click.echo(json.dumps(result, indent=2))
        elif output_format == "csv":
            import csv
            import sys
            writer = csv.writer(sys.stdout)
            writer.writerow(["Name", "Version", "Release", "Arch", "Size (bytes)", "SHA256"])
            for pkg in packages:
                writer.writerow([pkg.name, pkg.version, pkg.release, pkg.arch, pkg.size_bytes, pkg.sha256])
        else:
            # Table format
            click.echo(f"Packages in repository: {repo_id}")
            if arch:
                click.echo(f"Filtered by architecture: {arch}")
            click.echo(f"Showing up to {limit} packages")
            click.echo()

            if not packages:
                click.echo("  No packages found.")
                if arch:
                    click.echo(f"  Try removing the --arch filter or sync the repository.")
                return

            click.echo(f"{'Name':<35} {'Version':<20} {'Arch':<10} {'Size':>12}")
            click.echo("-" * 85)

            for pkg in packages:
                version_str = f"{pkg.version}-{pkg.release}" if pkg.release else pkg.version

                # Format size
                size_mb = pkg.size_bytes / (1024**2)
                if size_mb >= 1.0:
                    size_str = f"{size_mb:.1f} MB"
                else:
                    size_kb = pkg.size_bytes / 1024
                    size_str = f"{size_kb:.0f} KB"

                click.echo(f"{pkg.name:<35} {version_str:<20} {pkg.arch:<10} {size_str:>12}")

            click.echo()
            click.echo(f"Total: {len(packages)} package(s)")

            total_packages = len(list(repository.packages))
            if arch:
                click.echo(f"(Repository has {total_packages} total packages across all architectures)")


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
    """Search for packages by name.

    Searches package names using case-insensitive pattern matching.
    Use wildcards (* or %) for broader searches.
    """
    config: GlobalConfig = ctx.obj["config"]
    db_manager = DatabaseManager(config.database.url)

    with db_manager.session() as session:
        # Build base query
        packages_query = session.query(Package)

        # Filter by repository if specified
        if repo_id:
            repository = session.query(Repository).filter_by(repo_id=repo_id).first()
            if not repository:
                click.echo(f"Error: Repository '{repo_id}' not found in database.", err=True)
                click.echo("Run 'chantal repo list' to see available repositories.", err=True)
                ctx.exit(1)

            # Filter packages belonging to this repository
            packages_query = packages_query.filter(Package.repositories.contains(repository))

        # Apply name search (case-insensitive, wildcard support)
        search_pattern = query.replace("*", "%")
        packages_query = packages_query.filter(Package.name.ilike(f"%{search_pattern}%"))

        # Filter by architecture if specified
        if arch:
            packages_query = packages_query.filter_by(arch=arch)

        # Get results
        packages = packages_query.all()

        if output_format == "json":
            import json
            result = []
            for pkg in packages:
                # Get repository names for this package
                repo_names = [repo.repo_id for repo in pkg.repositories]
                result.append({
                    "name": pkg.name,
                    "version": pkg.version,
                    "release": pkg.release,
                    "arch": pkg.arch,
                    "nevra": pkg.nevra,
                    "size_bytes": pkg.size_bytes,
                    "repositories": repo_names,
                })
            click.echo(json.dumps(result, indent=2))
        else:
            # Table format
            click.echo(f"Searching for: {query}")
            if repo_id:
                click.echo(f"In repository: {repo_id}")
            if arch:
                click.echo(f"Architecture: {arch}")
            click.echo()

            if not packages:
                click.echo("  No packages found.")
                click.echo(f"\n  Try broadening your search query.")
                return

            click.echo(f"{'Name':<35} {'Version':<20} {'Arch':<10} {'Repositories':<30}")
            click.echo("-" * 105)

            for pkg in packages:
                version_str = f"{pkg.version}-{pkg.release}" if pkg.release else pkg.version

                # Get repository names (limit to first 2 for display)
                repo_names = [repo.repo_id for repo in pkg.repositories]
                if len(repo_names) > 2:
                    repo_str = f"{repo_names[0]}, {repo_names[1]}, +{len(repo_names)-2}"
                else:
                    repo_str = ", ".join(repo_names)

                click.echo(f"{pkg.name:<35} {version_str:<20} {pkg.arch:<10} {repo_str:<30}")

            click.echo()
            click.echo(f"Found: {len(packages)} package(s)")


@package.command("show")
@click.argument("package")
@click.option("--format", "output_format", type=click.Choice(["table", "json"]),
              default="table", help="Output format")
@click.pass_context
def package_show(ctx: click.Context, package: str, output_format: str) -> None:
    """Show detailed package information.

    PACKAGE can be either:
    - Full NEVRA: vim-minimal-8.2.2637-20.el9_1.x86_64
    - Package name: vim-minimal (shows all versions)
    - SHA256 checksum: abc123...
    """
    config: GlobalConfig = ctx.obj["config"]
    db_manager = DatabaseManager(config.database.url)

    with db_manager.session() as session:
        # Try to find package by different methods
        pkg = None
        packages = []

        # Check if it's a SHA256 (64 hex characters)
        if len(package) == 64 and all(c in '0123456789abcdef' for c in package.lower()):
            pkg = session.query(Package).filter_by(sha256=package).first()
            if pkg:
                packages = [pkg]

        # Try name match (may return multiple packages)
        if not packages:
            packages = session.query(Package).filter_by(name=package).all()

        # Try filename match if name didn't work
        if not packages:
            pkg = session.query(Package).filter_by(filename=package).first()
            if pkg:
                packages = [pkg]

        if not packages:
            click.echo(f"Error: Package '{package}' not found in database.", err=True)
            click.echo("\nTry searching: chantal package search <query>", err=True)
            ctx.exit(1)

        if output_format == "json":
            import json
            result = []
            for pkg in packages:
                repo_names = [repo.repo_id for repo in pkg.repositories]
                snapshot_names = [snap.name for snap in pkg.snapshots]
                result.append({
                    "name": pkg.name,
                    "version": pkg.version,
                    "release": pkg.release,
                    "arch": pkg.arch,
                    "nevra": pkg.nevra,
                    "filename": pkg.filename,
                    "size_bytes": pkg.size_bytes,
                    "sha256": pkg.sha256,
                    "pool_path": pkg.pool_path,
                    "repositories": repo_names,
                    "snapshots": snapshot_names,
                })
            click.echo(json.dumps(result, indent=2))
        else:
            # Table format
            if len(packages) > 1:
                click.echo(f"Found {len(packages)} packages matching '{package}':")
                click.echo()

            for i, pkg in enumerate(packages, 1):
                if len(packages) > 1:
                    click.echo(f"[{i}/{len(packages)}]")
                    click.echo("=" * 70)
                else:
                    click.echo("=" * 70)
                    click.echo(f"Package: {pkg.nevra}")
                    click.echo("=" * 70)
                    click.echo()

                click.echo("Basic Information:")
                click.echo(f"  Name:         {pkg.name}")
                click.echo(f"  Version:      {pkg.version}")
                if pkg.release:
                    click.echo(f"  Release:      {pkg.release}")
                click.echo(f"  Architecture: {pkg.arch}")
                click.echo(f"  NEVRA:        {pkg.nevra}")
                click.echo(f"  Filename:     {pkg.filename}")

                click.echo()
                click.echo("Storage:")
                size_mb = pkg.size_bytes / (1024**2)
                if size_mb >= 1.0:
                    size_str = f"{size_mb:.2f} MB"
                else:
                    size_kb = pkg.size_bytes / 1024
                    size_str = f"{size_kb:.1f} KB"
                click.echo(f"  Size:         {size_str} ({pkg.size_bytes:,} bytes)")
                click.echo(f"  SHA256:       {pkg.sha256}")
                click.echo(f"  Pool Path:    {pkg.pool_path}")

                # Get repositories
                repo_names = [repo.repo_id for repo in pkg.repositories]
                click.echo()
                click.echo(f"Repositories ({len(repo_names)}):")
                if repo_names:
                    for repo_name in repo_names:
                        click.echo(f"  - {repo_name}")
                else:
                    click.echo("  (none)")

                # Get snapshots
                snapshot_names = [snap.name for snap in pkg.snapshots]
                click.echo()
                click.echo(f"Snapshots ({len(snapshot_names)}):")
                if snapshot_names:
                    for snap_name in snapshot_names[:10]:  # Show first 10
                        click.echo(f"  - {snap_name}")
                    if len(snapshot_names) > 10:
                        click.echo(f"  ... and {len(snapshot_names) - 10} more")
                else:
                    click.echo("  (none)")

                if len(packages) > 1 and i < len(packages):
                    click.echo()
                    click.echo()

            if len(packages) == 1:
                click.echo()
                click.echo("=" * 70)


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


@cli.group(context_settings=CONTEXT_SETTINGS)
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


@cli.group(context_settings=CONTEXT_SETTINGS)
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


@cli.group(context_settings=CONTEXT_SETTINGS)
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
@click.option("--format", "output_format", type=click.Choice(["table", "json"]),
              default="table", help="Output format")
@click.pass_context
def publish_list(ctx: click.Context, output_format: str) -> None:
    """List currently published repositories and snapshots.

    Shows all published snapshots with their paths and metadata.
    """
    config: GlobalConfig = ctx.obj["config"]
    db_manager = DatabaseManager(config.database.url)

    with db_manager.session() as session:
        # Get all published snapshots
        published_snapshots = (
            session.query(Snapshot)
            .filter_by(is_published=True)
            .order_by(Snapshot.created_at.desc())
            .all()
        )

        if output_format == "json":
            import json
            result = {
                "snapshots": []
            }

            for snapshot in published_snapshots:
                repo = session.query(Repository).filter_by(id=snapshot.repository_id).first()
                result["snapshots"].append({
                    "name": snapshot.name,
                    "repository": repo.repo_id if repo else "Unknown",
                    "path": snapshot.published_path,
                    "packages": snapshot.package_count,
                    "size_bytes": snapshot.total_size_bytes,
                    "created": snapshot.created_at.isoformat(),
                })

            click.echo(json.dumps(result, indent=2))
        else:
            # Table format
            click.echo("Currently Published:")
            click.echo()

            if not published_snapshots:
                click.echo("  No published snapshots found.")
                click.echo()
                click.echo("  Publish a snapshot with:")
                click.echo("    chantal publish snapshot --snapshot <name>")
                return

            click.echo("Snapshots:")
            click.echo(f"{'Name':<35} {'Repository':<25} {'Path':<50}")
            click.echo("-" * 115)

            for snapshot in published_snapshots:
                # Get repository info
                repo = session.query(Repository).filter_by(id=snapshot.repository_id).first()
                repo_name = repo.repo_id if repo else "Unknown"

                # Shorten path if needed
                path = snapshot.published_path
                if len(path) > 48:
                    path = "..." + path[-45:]

                click.echo(f"{snapshot.name:<35} {repo_name:<25} {path:<50}")

            click.echo()
            click.echo(f"Total: {len(published_snapshots)} published snapshot(s)")


@publish.command("unpublish")
@click.option("--snapshot", required=True, help="Snapshot name to unpublish")
@click.option("--repo-id", help="Repository ID (optional if snapshot name is unique)")
@click.pass_context
def publish_unpublish(ctx: click.Context, snapshot: str, repo_id: str) -> None:
    """Unpublish a snapshot.

    Removes the published directory (hardlinks). Does not delete packages from pool.
    The snapshot remains in the database and can be re-published later.
    """
    config: GlobalConfig = ctx.obj["config"]
    db_manager = DatabaseManager(config.database.url)

    with db_manager.session() as session:
        # Find snapshot
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

        # Check if published
        if not snap.is_published:
            click.echo(f"Snapshot '{snapshot}' is not currently published.", err=True)
            ctx.exit(1)

        # Get repository info
        repository = session.query(Repository).filter_by(id=snap.repository_id).first()

        click.echo(f"Unpublishing snapshot: {snapshot}")
        click.echo(f"Repository: {repository.repo_id}")
        click.echo(f"Path: {snap.published_path}")
        click.echo()

        # Remove published directory
        published_path = Path(snap.published_path)
        if published_path.exists():
            import shutil
            shutil.rmtree(published_path)
            click.echo(f"✓ Removed published directory")
        else:
            click.echo(f"⚠ Published directory not found (already deleted?)")

        # Update snapshot metadata
        snap.is_published = False
        snap.published_path = None
        session.commit()

        click.echo()
        click.echo(f"✓ Snapshot '{snapshot}' unpublished successfully!")
        click.echo("Note: Snapshot remains in database and can be re-published with:")
        click.echo(f"  chantal publish snapshot --snapshot {snapshot}")


def main() -> None:
    """Main entry point."""
    cli(obj={})


if __name__ == "__main__":
    main()
