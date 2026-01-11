"""
Main CLI entry point for Chantal.

This module provides the Click-based command-line interface for Chantal.
"""

import shutil
from datetime import datetime

import click
from pathlib import Path
from typing import Optional

from chantal import __version__
from chantal.core.config import GlobalConfig, load_config
from chantal.core.storage import StorageManager
from chantal.db.connection import DatabaseManager
from chantal.db.models import Repository, Snapshot, SyncHistory, ContentItem
from chantal.plugins.rpm_sync import RpmSyncPlugin, CheckUpdatesResult, PackageUpdate
from chantal.plugins.rpm import RpmPublisher
from chantal.plugins.helm import HelmSyncer, HelmPublisher
from chantal.plugins.apk import ApkSyncer, ApkPublisher

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
@click.option("--type", "repo_type", type=click.Choice(["rpm", "apt", "helm"]),
              default=None, help="Filter by repository type")
@click.pass_context
def repo_list(ctx: click.Context, output_format: str, repo_type: str = None) -> None:
    """List configured repositories.

    Shows all repositories from config with their current sync status.
    Config is the source of truth - database provides runtime status only.
    """
    config: GlobalConfig = ctx.obj["config"]
    db_manager = DatabaseManager(config.database.url)

    with db_manager.session() as session:
        # Get all repositories from config (source of truth)
        config_repos = config.repositories

        # Filter by type if specified
        if repo_type:
            config_repos = [repo for repo in config_repos if repo.type == repo_type]

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
                package_count = len(db_repo.content_items) if db_repo else 0

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
    elif repo_config.type == "helm":
        helm_syncer = HelmSyncer(storage=storage)
        stats = helm_syncer.sync_repository(session, repository, repo_config)

        # Update last sync timestamp
        from datetime import datetime, timezone
        repository.last_sync_at = datetime.now(timezone.utc)
        session.commit()

        # Display result
        click.echo(f"\n✓ Helm sync completed successfully!")
        click.echo(f"  Charts added: {stats['charts_added']}")
        click.echo(f"  Charts updated: {stats['charts_updated']}")
        click.echo(f"  Charts skipped: {stats['charts_skipped']}")
        click.echo(f"  Data transferred: {stats['bytes_downloaded'] / 1024 / 1024:.2f} MB")
        return
    elif repo_config.type == "apk":
        apk_syncer = ApkSyncer(storage=storage)
        stats = apk_syncer.sync_repository(session, repository, repo_config)

        # Update last sync timestamp
        from datetime import datetime, timezone
        repository.last_sync_at = datetime.now(timezone.utc)
        session.commit()

        # Display result
        click.echo(f"\n✓ APK sync completed successfully!")
        click.echo(f"  Packages added: {stats['packages_added']}")
        click.echo(f"  Packages updated: {stats['packages_updated']}")
        click.echo(f"  Packages skipped: {stats['packages_skipped']}")
        click.echo(f"  Data transferred: {stats['bytes_downloaded'] / 1024 / 1024:.2f} MB")
        if stats['sha1_mismatches'] > 0:
            click.echo(f"  SHA1 mismatches: {stats['sha1_mismatches']} (stale APKINDEX, integrity verified via SHA256)")
        return
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
        packages = list(repository.content_items)
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
@click.option("--repo-id", help="Repository ID (mutually exclusive with --view)")
@click.option("--view", help="View name (mutually exclusive with --repo-id)")
@click.option("--name", required=True, help="Snapshot name")
@click.option("--description", help="Snapshot description")
@click.pass_context
def snapshot_create(ctx: click.Context, repo_id: str, view: str, name: str, description: str) -> None:
    """Create snapshot of repository or view.

    Creates an immutable point-in-time snapshot of the current state.
    The snapshot references packages from the content-addressed pool.

    For repositories: Creates snapshot of single repository
    For views: Creates snapshots of ALL repositories in view + ViewSnapshot
    """
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


def _create_repository_snapshot(
    ctx: click.Context,
    config: GlobalConfig,
    db_manager: DatabaseManager,
    repo_id: str,
    name: str,
    description: str
) -> None:
    """Create snapshot of a single repository."""
    from chantal.db.models import Repository, Snapshot

    click.echo(f"Creating snapshot '{name}' of repository '{repo_id}'...")
    if description:
        click.echo(f"Description: {description}")
    click.echo()

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
        packages = list(repository.content_items)

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
        snapshot.content_items = packages

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
        click.echo(f"  chantal publish snapshot --snapshot {name} --repo-id {repo_id}")


def _create_view_snapshot(
    ctx: click.Context,
    config: GlobalConfig,
    db_manager: DatabaseManager,
    view_name: str,
    snapshot_name: str,
    description: str
) -> None:
    """Create atomic snapshot of ALL repositories in a view."""
    from chantal.db.models import Repository, Snapshot, View, ViewSnapshot

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
            session.query(ViewSnapshot)
            .filter_by(view_id=view.id, name=snapshot_name)
            .first()
        )
        if existing_snapshot:
            click.echo(f"Error: View snapshot '{snapshot_name}' already exists for view '{view_name}'.", err=True)
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
            packages = list(repo.packages)
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
        click.echo(f"To publish this view snapshot:")
        click.echo(f"  chantal publish snapshot --view {view_name} --snapshot {snapshot_name}")


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


@snapshot.command("copy")
@click.option("--source", required=True, help="Source snapshot name")
@click.option("--target", required=True, help="Target snapshot name")
@click.option("--repo-id", required=True, help="Repository ID")
@click.option("--description", help="Description for new snapshot")
@click.pass_context
def snapshot_copy(ctx: click.Context, source: str, target: str, repo_id: str, description: str) -> None:
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
            session.query(Snapshot)
            .filter_by(repository_id=repository.id, name=source)
            .first()
        )

        if not source_snapshot:
            click.echo(f"Error: Source snapshot '{source}' not found for repository '{repo_id}'.", err=True)
            ctx.exit(1)

        # Check if target already exists
        existing_target = (
            session.query(Snapshot)
            .filter_by(repository_id=repository.id, name=target)
            .first()
        )

        if existing_target:
            click.echo(f"Error: Target snapshot '{target}' already exists for repository '{repo_id}'.", err=True)
            click.echo(f"Created: {existing_target.created_at}", err=True)
            click.echo("Use a different target name or delete the existing snapshot first.", err=True)
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

        session.add(new_snapshot)
        session.commit()

        click.echo(f"✓ Snapshot copied successfully!")
        click.echo(f"  Source: {source}")
        click.echo(f"  Target: {target}")
        click.echo(f"  Packages: {new_snapshot.package_count}")
        click.echo(f"  Total size: {new_snapshot.total_size_bytes / (1024**3):.2f} GB")
        click.echo()
        click.echo("Note: Both snapshots share the same packages in the pool (zero-copy)")
        click.echo()
        click.echo(f"To publish the new snapshot:")
        click.echo(f"  chantal publish snapshot --snapshot {target} --repo-id {repo_id}")


@snapshot.command("content")
@click.option("--repo-id", help="Repository ID (for repository snapshots)")
@click.option("--view", help="View name (for view snapshots)")
@click.option("--snapshot", "snapshot_name", required=True, help="Snapshot name")
@click.option("--format", "output_format", type=click.Choice(["table", "json", "csv"]), default="table", help="Output format")
@click.option("--limit", type=int, help="Limit number of packages shown (table format only)")
@click.pass_context
def snapshot_content(ctx: click.Context, repo_id: str, view: str, snapshot_name: str, output_format: str, limit: int) -> None:
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
        _show_repository_snapshot_content(ctx, db_manager, repo_id, snapshot_name, output_format, limit)


def _show_repository_snapshot_content(
    ctx: click.Context,
    db_manager: DatabaseManager,
    repo_id: str,
    snapshot_name: str,
    output_format: str,
    limit: int
) -> None:
    """Show repository snapshot content."""
    from chantal.db.models import Repository, Snapshot

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

        # Get packages
        packages = list(snapshot.content_items)

        if output_format == "json":
            import json
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
                ]
            }
            click.echo(json.dumps(output, indent=2))

        elif output_format == "csv":
            click.echo("name,epoch,version,release,arch,nevra,sha256,size_bytes,filename")
            for pkg in sorted(packages, key=lambda p: p.name):
                click.echo(f"{pkg.name},{pkg.epoch or ''},{pkg.version},{pkg.release},"
                          f"{pkg.arch},{pkg.nevra},{pkg.sha256},{pkg.size_bytes},{pkg.filename}")

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
                click.echo(f"Showing {limit} of {len(packages)} packages. Use --limit to show more or --format json for full export.")


def _show_view_snapshot_content(
    ctx: click.Context,
    db_manager: DatabaseManager,
    view_name: str,
    snapshot_name: str,
    output_format: str,
    limit: int
) -> None:
    """Show view snapshot content."""
    from chantal.db.models import View, ViewSnapshot, Snapshot

    with db_manager.session() as session:
        # Get view
        view = session.query(View).filter_by(name=view_name).first()
        if not view:
            click.echo(f"Error: View '{view_name}' not found.", err=True)
            ctx.exit(1)

        # Get view snapshot
        view_snapshot = (
            session.query(ViewSnapshot)
            .filter_by(view_id=view.id, name=snapshot_name)
            .first()
        )

        if not view_snapshot:
            click.echo(f"Error: View snapshot '{snapshot_name}' not found for view '{view_name}'.", err=True)
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

            repositories_data.append({
                "repo_id": repo.repo_id,
                "snapshot_name": snapshot.name,
                "package_count": len(packages),
                "packages": packages,
            })
            all_packages.extend(packages)

        if output_format == "json":
            import json
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
                        ]
                    }
                    for repo_data in repositories_data
                ]
            }
            click.echo(json.dumps(output, indent=2))

        elif output_format == "csv":
            click.echo("view,snapshot,repo_id,name,epoch,version,release,arch,nevra,sha256,size_bytes,filename")
            for repo_data in repositories_data:
                for pkg in sorted(repo_data["packages"], key=lambda p: p.name):
                    click.echo(f"{view_name},{snapshot_name},{repo_data['repo_id']},"
                              f"{pkg.name},{pkg.epoch or ''},{pkg.version},{pkg.release},"
                              f"{pkg.arch},{pkg.nevra},{pkg.sha256},{pkg.size_bytes},{pkg.filename}")

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
                click.echo(f"Repository: {repo_data['repo_id']} ({repo_data['package_count']} packages)")
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
                click.echo(f"Use --format json or --format csv for full export of all {view_snapshot.package_count} packages.")


@cli.group(context_settings=CONTEXT_SETTINGS)
def view() -> None:
    """View management commands.

    Views group multiple repositories into a single virtual repository.
    All repositories in a view must have the same type (rpm or apt).
    """
    pass


@view.command("list")
@click.option("--format", "output_format", type=click.Choice(["table", "json"]), default="table")
@click.pass_context
def view_list(ctx, output_format):
    """List all configured views."""
    config = ctx.obj["config"]

    if not config.views:
        click.echo("No views configured.")
        click.echo()
        click.echo("Add views to your config.yaml or conf.d/*.yaml:")
        click.echo("  views:")
        click.echo("    - name: rhel9-complete")
        click.echo("      description: RHEL 9 - All repos")
        click.echo("      repos:")
        click.echo("        - rhel9-baseos")
        click.echo("        - rhel9-appstream")
        return

    if output_format == "json":
        import json
        views_data = [
            {
                "name": v.name,
                "description": v.description,
                "repos": v.repos,
                "repo_count": len(v.repos),
            }
            for v in config.views
        ]
        click.echo(json.dumps(views_data, indent=2))
        return

    # Table format
    click.echo("Configured Views:")
    click.echo()
    click.echo(f"{'Name':<30} {'Repos':<6} {'Description'}")
    click.echo("-" * 80)

    for v in config.views:
        desc = v.description or ""
        if len(desc) > 40:
            desc = desc[:37] + "..."
        click.echo(f"{v.name:<30} {len(v.repos):<6} {desc}")

    click.echo()
    click.echo(f"Total: {len(config.views)} view(s)")


@view.command("show")
@click.option("--name", required=True, help="View name")
@click.option("--format", "output_format", type=click.Choice(["table", "json"]), default="table")
@click.pass_context
def view_show(ctx, name, output_format):
    """Show detailed information about a view."""
    config = ctx.obj["config"]

    # Find view
    view_config = config.get_view(name)
    if not view_config:
        click.echo(f"Error: View '{name}' not found in configuration", err=True)
        return

    # Collect repo information
    repos_info = []
    total_packages = 0
    for repo_id in view_config.repos:
        repo_config = config.get_repository(repo_id)
        if not repo_config:
            repos_info.append({
                "id": repo_id,
                "name": f"UNKNOWN ({repo_id})",
                "type": "?",
                "enabled": False,
                "packages": 0,
                "status": "NOT FOUND",
            })
        else:
            # Try to get package count from database
            try:
                from chantal.db.session import get_session
                from chantal.db.models import Repository

                session = get_session(config.database.url)
                db_repo = session.query(Repository).filter_by(repo_id=repo_config.id).first()
                pkg_count = len(db_repo.packages) if db_repo else 0
                total_packages += pkg_count
                session.close()
            except Exception:
                pkg_count = 0

            repos_info.append({
                "id": repo_config.id,
                "name": repo_config.display_name,
                "type": repo_config.type,
                "enabled": repo_config.enabled,
                "packages": pkg_count,
                "status": "OK",
            })

    if output_format == "json":
        import json
        view_data = {
            "name": view_config.name,
            "description": view_config.description,
            "repositories": repos_info,
            "total_repos": len(view_config.repos),
            "total_packages": total_packages,
        }
        click.echo(json.dumps(view_data, indent=2))
        return

    # Table format
    click.echo(f"View: {view_config.name}")
    click.echo()

    click.echo("Basic Information:")
    click.echo(f"  Name: {view_config.name}")
    if view_config.description:
        click.echo(f"  Description: {view_config.description}")
    click.echo(f"  Total Repositories: {len(view_config.repos)}")
    click.echo(f"  Total Packages: {total_packages}")
    click.echo()

    click.echo("Repositories in this view:")
    click.echo(f"  {'ID':<30} {'Type':<6} {'Enabled':<8} {'Packages':<10} {'Status'}")
    click.echo("  " + "-" * 75)

    for info in repos_info:
        enabled_str = "Yes" if info["enabled"] else "No"
        click.echo(f"  {info['id']:<30} {info['type']:<6} {enabled_str:<8} {info['packages']:<10} {info['status']}")

    click.echo()
    click.echo("Usage:")
    click.echo(f"  Publish view:          chantal publish view --name {view_config.name}")
    click.echo(f"  Create view snapshot:  chantal snapshot create --view {view_config.name} --name YYYY-MM-DD")


@cli.group(context_settings=CONTEXT_SETTINGS)
def content() -> None:
    """Content management commands (works with all content types: RPM, Helm, APT, etc.)."""
    pass


@content.command("list")
@click.option("--repo-id", help="Filter by repository ID")
@click.option("--snapshot-id", help="Filter by snapshot ID")
@click.option("--view", "view_name", help="Filter by view name")
@click.option("--type", "content_type", type=click.Choice(["rpm", "helm", "apt"]),
              help="Filter by content type")
@click.option("--limit", type=int, default=100, help="Limit number of results")
@click.option("--format", "output_format", type=click.Choice(["table", "json", "csv"]),
              default="table", help="Output format")
@click.pass_context
def content_list(
    ctx: click.Context,
    repo_id: str,
    snapshot_id: str,
    view_name: str,
    content_type: str,
    limit: int,
    output_format: str
) -> None:
    """List content items.

    Shows content items from repository, snapshot, or view.
    Works with all content types: RPM, Helm, APT, etc.
    """
    config: GlobalConfig = ctx.obj["config"]
    db_manager = DatabaseManager(config.database.url)

    # Validate scope (only one can be specified)
    scope_count = sum([bool(repo_id), bool(snapshot_id), bool(view_name)])
    if scope_count > 1:
        click.echo("Error: Only one of --repo-id, --snapshot-id, or --view can be specified.", err=True)
        ctx.exit(1)

    with db_manager.session() as session:
        # Get content items based on scope
        items = []
        scope_desc = "all content"

        if repo_id:
            repository = session.query(Repository).filter_by(repo_id=repo_id).first()
            if not repository:
                click.echo(f"Error: Repository '{repo_id}' not found.", err=True)
                ctx.exit(1)
            items = list(repository.content_items)
            scope_desc = f"repository '{repo_id}'"

        elif snapshot_id:
            snapshot = session.query(Snapshot).filter_by(snapshot_id=snapshot_id).first()
            if not snapshot:
                click.echo(f"Error: Snapshot '{snapshot_id}' not found.", err=True)
                ctx.exit(1)
            items = list(snapshot.content_items)
            scope_desc = f"snapshot '{snapshot_id}'"

        elif view_name:
            # Get all repos in view and collect their items
            view_config = config.get_view(view_name)
            if not view_config:
                click.echo(f"Error: View '{view_name}' not found in config.", err=True)
                ctx.exit(1)
            for repo_id in view_config.repos:
                repo = session.query(Repository).filter_by(repo_id=repo_id).first()
                if repo:
                    items.extend(repo.content_items)
            scope_desc = f"view '{view_name}'"
        else:
            # No scope - show all content
            items = session.query(ContentItem).all()

        # Apply content type filter
        if content_type:
            items = [item for item in items if item.content_type == content_type]

        # Apply limit
        items = items[:limit]

        # Output
        if output_format == "json":
            import json
            result = []
            for item in items:
                data = {
                    "name": item.name,
                    "version": item.version,
                    "type": item.content_type,
                    "size_bytes": item.size_bytes,
                    "sha256": item.sha256,
                }
                # Add type-specific fields from metadata
                if item.content_metadata:
                    if item.content_type == "rpm":
                        data["arch"] = item.content_metadata.get("arch", "")
                        data["release"] = item.content_metadata.get("release", "")
                    elif item.content_type == "helm":
                        data["app_version"] = item.content_metadata.get("app_version")
                result.append(data)
            click.echo(json.dumps(result, indent=2))

        elif output_format == "csv":
            import csv
            import sys
            writer = csv.writer(sys.stdout)
            writer.writerow(["Name", "Version", "Type", "Arch", "Size (bytes)", "SHA256"])
            for item in items:
                arch = item.content_metadata.get("arch", "-") if item.content_metadata and item.content_type == "rpm" else "-"
                writer.writerow([item.name, item.version, item.content_type, arch, item.size_bytes, item.sha256])

        else:
            # Table format
            click.echo(f"Content in {scope_desc}")
            if content_type:
                click.echo(f"Filtered by type: {content_type}")
            click.echo(f"Showing up to {limit} items")
            click.echo()

            if not items:
                click.echo("  No content found.")
                return

            # Determine if we have mixed types
            types_present = set(item.content_type for item in items)
            has_arch = "rpm" in types_present

            # Dynamic column headers
            if has_arch:
                click.echo(f"{'Name':<35} {'Version':<20} {'Type':<6} {'Arch':<10} {'Size':>12}")
                click.echo("-" * 91)
            else:
                click.echo(f"{'Name':<35} {'Version':<20} {'Type':<6} {'Size':>12}")
                click.echo("-" * 81)

            for item in items:
                # Get arch from metadata if RPM
                arch = "-"
                if item.content_type == "rpm" and item.content_metadata:
                    arch = item.content_metadata.get("arch", "-")

                # Format size
                size_mb = item.size_bytes / (1024**2)
                if size_mb >= 1.0:
                    size_str = f"{size_mb:.1f} MB"
                else:
                    size_kb = item.size_bytes / 1024
                    size_str = f"{size_kb:.0f} KB"

                # Truncate name if too long
                name = item.name[:33] + ".." if len(item.name) > 35 else item.name

                if has_arch:
                    click.echo(f"{name:<35} {item.version:<20} {item.content_type:<6} {arch:<10} {size_str:>12}")
                else:
                    click.echo(f"{name:<35} {item.version:<20} {item.content_type:<6} {size_str:>12}")

            click.echo()
            click.echo(f"Total: {len(items)} item(s)")


@content.command("search")
@click.argument("query")
@click.option("--repo-id", help="Search in specific repository only")
@click.option("--snapshot-id", help="Search in specific snapshot only")
@click.option("--view", "view_name", help="Search in specific view only")
@click.option("--type", "content_type", type=click.Choice(["rpm", "helm", "apt"]),
              help="Filter by content type")
@click.option("--format", "output_format", type=click.Choice(["table", "json"]),
              default="table", help="Output format")
@click.pass_context
def content_search(
    ctx: click.Context,
    query: str,
    repo_id: str,
    snapshot_id: str,
    view_name: str,
    content_type: str,
    output_format: str
) -> None:
    """Search for content by name or version.

    Searches globally across all repositories by default.
    Supports case-insensitive pattern matching.
    """
    config: GlobalConfig = ctx.obj["config"]
    db_manager = DatabaseManager(config.database.url)

    # Validate scope (only one can be specified)
    scope_count = sum([bool(repo_id), bool(snapshot_id), bool(view_name)])
    if scope_count > 1:
        click.echo("Error: Only one of --repo-id, --snapshot-id, or --view can be specified.", err=True)
        ctx.exit(1)

    with db_manager.session() as session:
        # Build base query
        items_query = session.query(ContentItem)

        # Filter by scope
        scope_desc = "all repositories"
        if repo_id:
            repository = session.query(Repository).filter_by(repo_id=repo_id).first()
            if not repository:
                click.echo(f"Error: Repository '{repo_id}' not found.", err=True)
                ctx.exit(1)
            items_query = items_query.filter(ContentItem.repositories.contains(repository))
            scope_desc = f"repository '{repo_id}'"

        elif snapshot_id:
            snapshot = session.query(Snapshot).filter_by(snapshot_id=snapshot_id).first()
            if not snapshot:
                click.echo(f"Error: Snapshot '{snapshot_id}' not found.", err=True)
                ctx.exit(1)
            items_query = items_query.filter(ContentItem.snapshots.contains(snapshot))
            scope_desc = f"snapshot '{snapshot_id}'"

        elif view_name:
            view_config = config.get_view(view_name)
            if not view_config:
                click.echo(f"Error: View '{view_name}' not found.", err=True)
                ctx.exit(1)
            # Get all repos in view
            repo_ids = view_config.repos
            repos = session.query(Repository).filter(Repository.repo_id.in_(repo_ids)).all()
            # Filter by any of these repositories
            if repos:
                items_query = items_query.filter(ContentItem.repositories.any(Repository.repo_id.in_(repo_ids)))
            scope_desc = f"view '{view_name}'"

        # Apply name/version search (case-insensitive)
        search_pattern = query.replace("*", "%")
        items_query = items_query.filter(
            (ContentItem.name.ilike(f"%{search_pattern}%")) |
            (ContentItem.version.ilike(f"%{search_pattern}%"))
        )

        # Filter by content type if specified
        if content_type:
            items_query = items_query.filter_by(content_type=content_type)

        # Get results
        items = items_query.all()

        if output_format == "json":
            import json
            result = []
            for item in items:
                # Get repository names for this item
                repo_names = [repo.repo_id for repo in item.repositories]
                data = {
                    "name": item.name,
                    "version": item.version,
                    "type": item.content_type,
                    "size_bytes": item.size_bytes,
                    "sha256": item.sha256,
                    "repositories": repo_names,
                }
                # Add type-specific fields
                if item.content_metadata:
                    if item.content_type == "rpm":
                        data["arch"] = item.content_metadata.get("arch", "")
                        data["release"] = item.content_metadata.get("release", "")
                result.append(data)
            click.echo(json.dumps(result, indent=2))
        else:
            # Table format
            click.echo(f"Searching for: '{query}' in {scope_desc}")
            if content_type:
                click.echo(f"Content type: {content_type}")
            click.echo()

            if not items:
                click.echo("  No content found.")
                click.echo(f"  Try broadening your search query.")
                return

            click.echo(f"{'Repository':<25} {'Name':<30} {'Version':<15} {'Type':<6} {'Size':>10}")
            click.echo("-" * 93)

            for item in items:
                # Get first repository (for display)
                repo_names = [repo.repo_id for repo in item.repositories]
                repo_display = repo_names[0] if repo_names else "(none)"
                if len(repo_names) > 1:
                    repo_display += f" +{len(repo_names)-1}"

                # Truncate name if too long
                name = item.name[:28] + ".." if len(item.name) > 30 else item.name

                # Format size
                size_mb = item.size_bytes / (1024**2)
                if size_mb >= 1.0:
                    size_str = f"{size_mb:.1f} MB"
                else:
                    size_kb = item.size_bytes / 1024
                    size_str = f"{size_kb:.0f} KB"

                click.echo(f"{repo_display:<25} {name:<30} {item.version:<15} {item.content_type:<6} {size_str:>10}")

            click.echo()
            click.echo(f"Found: {len(items)} item(s)")


@content.command("show")
@click.argument("identifier")
@click.option("--format", "output_format", type=click.Choice(["table", "json"]),
              default="table", help="Output format")
@click.pass_context
def content_show(ctx: click.Context, identifier: str, output_format: str) -> None:
    """Show detailed content information.

    IDENTIFIER can be:
    - SHA256 hash: abc123def456... (64 hex chars)
    - Name: nginx (shows all matching items)
    - Name@version: nginx@1.20.1 (specific version)
    """
    config: GlobalConfig = ctx.obj["config"]
    db_manager = DatabaseManager(config.database.url)

    with db_manager.session() as session:
        # Try to find content by different methods
        items = []

        # Check if it's a SHA256 (64 hex characters)
        if len(identifier) == 64 and all(c in '0123456789abcdef' for c in identifier.lower()):
            item = session.query(ContentItem).filter_by(sha256=identifier).first()
            if item:
                items = [item]

        # Check if it's name@version format
        elif "@" in identifier:
            name, version = identifier.rsplit("@", 1)
            items = session.query(ContentItem).filter_by(name=name, version=version).all()

        # Try name match (may return multiple items)
        else:
            items = session.query(ContentItem).filter_by(name=identifier).all()

        if not items:
            click.echo(f"Error: Content '{identifier}' not found in database.", err=True)
            click.echo("\nTry searching: chantal content search <query>", err=True)
            ctx.exit(1)

        if output_format == "json":
            import json
            result = []
            for item in items:
                repo_names = [repo.repo_id for repo in item.repositories]
                snapshot_names = [snap.name for snap in item.snapshots]
                data = {
                    "name": item.name,
                    "version": item.version,
                    "type": item.content_type,
                    "filename": item.filename,
                    "size_bytes": item.size_bytes,
                    "sha256": item.sha256,
                    "pool_path": item.pool_path,
                    "repositories": repo_names,
                    "snapshots": snapshot_names,
                    "metadata": item.content_metadata,
                }
                result.append(data)
            click.echo(json.dumps(result, indent=2))
        else:
            # Table format
            if len(items) > 1:
                click.echo(f"Found {len(items)} items matching '{identifier}':")
                click.echo()

            for i, item in enumerate(items, 1):
                if len(items) > 1:
                    click.echo(f"[{i}/{len(items)}]")
                    click.echo("=" * 70)
                else:
                    click.echo("=" * 70)
                    click.echo(f"Content: {item.name} {item.version}")
                    click.echo("=" * 70)
                    click.echo()

                click.echo("Basic Information:")
                click.echo(f"  Name:         {item.name}")
                click.echo(f"  Version:      {item.version}")
                click.echo(f"  Type:         {item.content_type}")
                click.echo(f"  Filename:     {item.filename}")

                # Type-specific fields from metadata
                if item.content_metadata:
                    if item.content_type == "rpm":
                        if "arch" in item.content_metadata:
                            click.echo(f"  Architecture: {item.content_metadata['arch']}")
                        if "release" in item.content_metadata:
                            click.echo(f"  Release:      {item.content_metadata['release']}")
                    elif item.content_type == "helm":
                        if "app_version" in item.content_metadata:
                            click.echo(f"  App Version:  {item.content_metadata['app_version']}")
                        if "description" in item.content_metadata:
                            click.echo(f"  Description:  {item.content_metadata['description']}")

                click.echo()
                click.echo("Storage:")
                size_mb = item.size_bytes / (1024**2)
                if size_mb >= 1.0:
                    size_str = f"{size_mb:.2f} MB"
                else:
                    size_kb = item.size_bytes / 1024
                    size_str = f"{size_kb:.1f} KB"
                click.echo(f"  Size:         {size_str} ({item.size_bytes:,} bytes)")
                click.echo(f"  SHA256:       {item.sha256}")
                click.echo(f"  Pool Path:    {item.pool_path}")

                # Get repositories
                repo_names = [repo.repo_id for repo in item.repositories]
                click.echo()
                click.echo(f"Repositories ({len(repo_names)}):")
                if repo_names:
                    for repo_name in repo_names:
                        click.echo(f"  - {repo_name}")
                else:
                    click.echo("  (none)")

                # Get snapshots
                snapshot_names = [snap.name for snap in item.snapshots]
                click.echo()
                click.echo(f"Snapshots ({len(snapshot_names)}):")
                if snapshot_names:
                    for snap_name in snapshot_names[:10]:  # Show first 10
                        click.echo(f"  - {snap_name}")
                    if len(snapshot_names) > 10:
                        click.echo(f"  ... and {len(snapshot_names) - 10} more")
                else:
                    click.echo("  (none)")

                if len(items) > 1 and i < len(items):
                    click.echo()
                    click.echo()

            if len(items) == 1:
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


@pool.command("orphaned")
@click.pass_context
def pool_orphaned(ctx: click.Context) -> None:
    """List orphaned files in storage pool.

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
        click.echo("Finding orphaned files...")
        click.echo()

        orphaned_files = storage.get_orphaned_files(session)

        if orphaned_files:
            click.echo(f"Found {len(orphaned_files):,} orphaned files:")
            click.echo()

            total_size = 0
            for file_path in orphaned_files:
                file_size = file_path.stat().st_size
                total_size += file_size
                # Show relative path from pool root
                rel_path = file_path.relative_to(storage.pool_path)
                click.echo(f"  {rel_path} ({file_size:,} bytes)")

            click.echo()
            click.echo(f"Total: {len(orphaned_files):,} files, {total_size:,} bytes ({total_size / (1024**2):.2f} MB)")
        else:
            click.echo("No orphaned files found.")

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
    from chantal.db.models import ContentItem

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
        packages = session.query(ContentItem).all()
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
    elif repo_config.type == "helm":
        publisher = HelmPublisher(storage=storage)
        # Publish repository
        try:
            publisher.publish_repository(
                session=session,
                repository=repository,
                config=repo_config,
                target_path=target_path
            )
            click.echo(f"\n✓ Helm repository published successfully!")
            click.echo(f"  Location: {target_path}")
            click.echo(f"  Chart files: {target_path}/*.tgz")
            click.echo(f"  Index file: {target_path}/index.yaml")
        except Exception as e:
            click.echo(f"\n✗ Publishing failed: {e}", err=True)
            raise
    elif repo_config.type == "apk":
        publisher = ApkPublisher(storage=storage)
        # Publish repository
        try:
            publisher.publish_repository(
                session=session,
                repository=repository,
                config=repo_config,
                target_path=target_path
            )
            apk_config = repo_config.apk
            arch_path = target_path / apk_config.branch / apk_config.repository / apk_config.architecture
            click.echo(f"\n✓ APK repository published successfully!")
            click.echo(f"  Location: {target_path}")
            click.echo(f"  Package directory: {arch_path}")
            click.echo(f"  Index file: {arch_path}/APKINDEX.tar.gz")
        except Exception as e:
            click.echo(f"\n✗ Publishing failed: {e}", err=True)
            raise
    else:
        click.echo(f"Error: Unsupported repository type: {repo_config.type}")
        return


@publish.command("snapshot")
@click.option("--snapshot", required=True, help="Snapshot name to publish")
@click.option("--repo-id", help="Repository ID (for repository snapshots)")
@click.option("--view", help="View name (for view snapshots)")
@click.option("--target", help="Custom target directory")
@click.pass_context
def publish_snapshot(ctx: click.Context, snapshot: str, repo_id: str, view: str, target: str) -> None:
    """Publish a specific snapshot (repository or view snapshot).

    Creates hardlinks from package pool to snapshot directory with RPM metadata.
    Perfect for creating immutable snapshots or parallel environments.

    For repository snapshots: --snapshot <name> --repo-id <repo>
    For view snapshots: --snapshot <name> --view <view>
    """
    config: GlobalConfig = ctx.obj["config"]

    # Validate: at most one of --repo-id or --view can be specified
    if repo_id and view:
        click.echo("Error: Cannot specify both --repo-id and --view", err=True)
        ctx.exit(1)

    # Initialize database and storage
    db_manager = DatabaseManager(config.database.url)
    storage = StorageManager(config.storage)

    if view:
        # Publish view snapshot
        _publish_view_snapshot(ctx, config, db_manager, storage, view, snapshot, target)
    else:
        # Publish repository snapshot (existing behavior)
        _publish_repository_snapshot(ctx, config, db_manager, storage, repo_id, snapshot, target)


def _publish_repository_snapshot(
    ctx: click.Context,
    config: GlobalConfig,
    db_manager: DatabaseManager,
    storage: StorageManager,
    repo_id: str,
    snapshot: str,
    target: str
) -> None:
    """Publish a repository snapshot."""
    from chantal.db.models import Repository, Snapshot
    from chantal.plugins.rpm import RpmPublisher

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


def _publish_view_snapshot(
    ctx: click.Context,
    config: GlobalConfig,
    db_manager: DatabaseManager,
    storage: StorageManager,
    view_name: str,
    snapshot_name: str,
    target: str
) -> None:
    """Publish a view snapshot."""
    from chantal.db.models import View, ViewSnapshot
    from chantal.plugins.view_publisher import ViewPublisher

    with db_manager.session() as session:
        # Get view from database
        view = session.query(View).filter_by(name=view_name).first()
        if not view:
            click.echo(f"Error: View '{view_name}' not found in database.", err=True)
            click.echo("Run 'chantal view list' to see available views.", err=True)
            ctx.exit(1)

        # Get view snapshot from database
        view_snapshot = (
            session.query(ViewSnapshot)
            .filter_by(view_id=view.id, name=snapshot_name)
            .first()
        )

        if not view_snapshot:
            click.echo(f"Error: View snapshot '{snapshot_name}' not found for view '{view_name}'.", err=True)
            click.echo(f"Run 'chantal snapshot list' to see available snapshots.", err=True)
            ctx.exit(1)

        # Determine target path
        if target:
            target_path = Path(target)
        else:
            # Default: published_path/views/<view-name>/snapshots/<snapshot-name>
            target_path = Path(config.storage.published_path) / "views" / view_name / "snapshots" / snapshot_name

        click.echo(f"Publishing view snapshot: {snapshot_name}")
        click.echo(f"View: {view_name}")
        click.echo(f"Target: {target_path}")
        click.echo(f"Packages: {view_snapshot.package_count}")
        click.echo()

        # Initialize view publisher
        publisher = ViewPublisher(storage)

        # Publish view snapshot
        try:
            publisher.publish_view_snapshot(
                session=session,
                view_snapshot=view_snapshot,
                target_path=target_path
            )

            # Update view snapshot metadata
            view_snapshot.is_published = True
            view_snapshot.published_at = datetime.utcnow()
            view_snapshot.published_path = str(target_path)
            session.commit()

            click.echo()
            click.echo(f"✓ View snapshot published successfully!")
            click.echo(f"  Location: {target_path}")
            click.echo(f"  Packages directory: {target_path}/Packages")
            click.echo(f"  Metadata directory: {target_path}/repodata")
            click.echo()
            click.echo(f"Configure your package manager:")
            click.echo(f"  [view-{view_name}-snapshot-{snapshot_name}]")
            click.echo(f"  name=View {view_name} Snapshot {snapshot_name}")
            click.echo(f"  baseurl=file://{target_path}")
            click.echo(f"  enabled=1")
            click.echo(f"  gpgcheck=0")

        except Exception as e:
            click.echo(f"\n✗ Publishing failed: {e}", err=True)
            raise


@publish.command("view")
@click.option("--name", required=True, help="View name to publish")
@click.pass_context
def publish_view(ctx: click.Context, name: str) -> None:
    """Publish a view (combines all repos into one virtual repository).

    Creates a combined repository from all repositories in the view.
    All packages from all repos are included (client decides on conflicts).

    Views are published directly from the configuration file - no database sync needed.

    Examples:
        chantal publish view --name rhel9-complete
        chantal publish view --name rhel9-webserver
    """
    from chantal.db.connection import DatabaseManager
    from chantal.plugins.view_publisher import ViewPublisher

    config = ctx.obj["config"]

    # Get view config
    view_config = config.get_view(name)
    if not view_config:
        click.echo(f"Error: View '{name}' not found in configuration", err=True)
        return

    click.echo(f"Publishing view: {name}")
    if view_config.description:
        click.echo(f"Description: {view_config.description}")
    click.echo()

    # Determine target path
    storage = config.storage
    if view_config.publish_path:
        target_path = Path(view_config.publish_path) / "latest"
    else:
        target_path = Path(storage.published_path) / "views" / name / "latest"

    click.echo(f"Target: {target_path}")
    click.echo()

    # Connect to database
    db = DatabaseManager(config.database.url)

    try:
        with db.session() as session:
            # Initialize publisher
            from chantal.core.storage import StorageManager
            storage_manager = StorageManager(config.storage)
            publisher = ViewPublisher(storage_manager)

            # Publish view from config (no DB view object needed)
            click.echo(f"Collecting packages from {len(view_config.repos)} repositories...")
            package_count = publisher.publish_view_from_config(
                session,
                view_config.repos,
                target_path
            )

            click.echo()
            click.echo(f"✓ View published successfully!")
            click.echo(f"  Packages: {package_count}")
            click.echo()
            click.echo("Client configuration:")
            click.echo(f"  [view-{name}]")
            click.echo(f"  name=View: {name}")
            click.echo(f"  baseurl=file://{target_path.absolute()}")
            click.echo(f"  enabled=1")
            click.echo(f"  gpgcheck=0")

    except ValueError as e:
        click.echo(f"\n✗ Publishing view failed: {e}", err=True)
        click.echo(f"Hint: Make sure all repositories in the view are synced to database first")
        raise
    except Exception as e:
        click.echo(f"\n✗ Publishing view failed: {e}", err=True)
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
