from __future__ import annotations

"""Repository management commands."""

from datetime import datetime, timezone

import click

from chantal.core.config import GlobalConfig
from chantal.core.storage import StorageManager
from chantal.db.connection import DatabaseManager
from chantal.db.models import Repository, Snapshot, SyncHistory
from chantal.plugins.apk.sync import ApkSyncer
from chantal.plugins.helm.sync import HelmSyncer
from chantal.plugins.rpm.sync import CheckUpdatesResult, RpmSyncPlugin

from .db_commands import check_db_schema_version

# Click context settings to enable -h as alias for --help
CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


def create_repo_group(cli: click.Group) -> click.Group:
    """Create and return the repo command group.

    Args:
        cli: Parent CLI group to attach to

    Returns:
        The repo command group
    """

    @cli.group(context_settings=CONTEXT_SETTINGS)
    def repo() -> None:
        """Repository management commands."""
        pass

    @repo.command("list")
    @click.option(
        "--format",
        "output_format",
        type=click.Choice(["table", "json"]),
        default="table",
        help="Output format",
    )
    @click.option(
        "--type",
        "repo_type",
        type=click.Choice(["rpm", "apt", "helm"]),
        default=None,
        help="Filter by repository type",
    )
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
                    result.append(
                        {
                            "repo_id": repo_config.id,
                            "name": repo_config.name,
                            "type": repo_config.type,
                            "feed": repo_config.feed,
                            "enabled": repo_config.enabled,
                            "package_count": len(db_repo.packages) if db_repo else 0,
                            "last_sync": (
                                db_repo.last_sync_at.isoformat()
                                if db_repo and db_repo.last_sync_at
                                else None
                            ),
                            "synced": db_repo is not None,
                        }
                    )
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

                    rows.append(
                        {
                            "id": repo_config.id,
                            "type": repo_config.type,
                            "enabled": enabled_str,
                            "packages": str(package_count),
                            "last_sync": last_sync_str,
                        }
                    )

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
                    click.echo(
                        f"{row['id']:<{col_widths['id']}} {row['type']:<{col_widths['type']}} {row['enabled']:<{col_widths['enabled']}} {row['packages']:>{col_widths['packages']}} {row['last_sync']:<{col_widths['last_sync']}}"
                    )

                click.echo()
                click.echo(f"Total: {len(config_repos)} repository(ies)")

    @repo.command("sync")
    @click.option("--repo-id", help="Repository ID to sync")
    @click.option("--all", is_flag=True, help="Sync all enabled repositories")
    @click.option(
        "--pattern", help="Sync repositories matching pattern (e.g., 'epel9-*', '*-latest')"
    )
    @click.option(
        "--type", help="Filter by repository type (rpm, apt) when using --all or --pattern"
    )
    @click.option(
        "--workers", type=int, default=1, help="Number of parallel workers for --all or --pattern"
    )
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

        # Check database schema version
        check_db_schema_version(ctx)

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
                    r for r in config.repositories if r.enabled and fnmatch.fnmatch(r.id, pattern)
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

    @repo.command("show")
    @click.option("--repo-id", required=True, help="Repository ID")
    @click.option(
        "--format",
        "output_format",
        type=click.Choice(["table", "json"]),
        default="table",
        help="Output format",
    )
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
                # Check if repository exists in configuration
                repo_config = next((r for r in config.repositories if r.id == repo_id), None)
                if repo_config:
                    click.echo(f"Error: Repository '{repo_id}' has not been synced yet.", err=True)
                    click.echo(f"Run 'chantal repo sync --repo-id {repo_id}' first.", err=True)
                else:
                    click.echo(
                        f"Error: Repository '{repo_id}' not found in configuration.", err=True
                    )
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
                        "last_sync": (
                            repository.last_sync_at.isoformat() if repository.last_sync_at else None
                        ),
                    },
                    "config": (
                        {
                            "has_filters": bool(repo_config.filters) if repo_config else False,
                        }
                        if repo_config
                        else None
                    ),
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
                    click.echo("  Filters:      Active")
                    if (
                        hasattr(repo_config.filters, "post_processing")
                        and repo_config.filters.post_processing
                    ):
                        if repo_config.filters.post_processing.only_latest_version:
                            click.echo("                - Only latest versions")
                else:
                    click.echo("  Filters:      None")

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
                    click.echo("  Total Size:       0 bytes")

                click.echo(f"  Snapshots:        {snapshot_count}")

                click.echo()
                click.echo("Sync Information:")
                if repository.last_sync_at:
                    click.echo(
                        f"  Last Sync:    {repository.last_sync_at.strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                else:
                    click.echo("  Last Sync:    Never")
                    click.echo()
                    click.echo(
                        f"  Run 'chantal repo sync --repo-id {repo_id}' to sync this repository."
                    )

                if snapshots:
                    click.echo()
                    click.echo(f"Recent Snapshots (showing {min(5, len(snapshots))}):")
                    for snap in sorted(snapshots, key=lambda s: s.created_at, reverse=True)[:5]:
                        published = " [PUBLISHED]" if snap.is_published else ""
                        click.echo(
                            f"  - {snap.name:<30} {snap.created_at.strftime('%Y-%m-%d %H:%M')}{published}"
                        )

                click.echo()
                click.echo("=" * 70)

    @repo.command("check-updates")
    @click.option("--repo-id", help="Repository ID to check")
    @click.option("--all", is_flag=True, help="Check all enabled repositories")
    @click.option(
        "--pattern", help="Check repositories matching pattern (e.g., 'epel9-*', '*-latest')"
    )
    @click.option(
        "--type", help="Filter by repository type (rpm, apt) when using --all or --pattern"
    )
    @click.option(
        "--format",
        "output_format",
        type=click.Choice(["table", "json"]),
        default="table",
        help="Output format",
    )
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
                    r for r in config.repositories if r.enabled and fnmatch.fnmatch(r.id, pattern)
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

    @repo.command("history")
    @click.option("--repo-id", required=True, help="Repository ID")
    @click.option("--limit", type=int, default=10, help="Number of sync entries to show")
    @click.option(
        "--format",
        "output_format",
        type=click.Choice(["table", "json"]),
        default="table",
        help="Output format",
    )
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
                # Check if repository exists in configuration
                repo_config = next((r for r in config.repositories if r.id == repo_id), None)
                if repo_config:
                    click.echo(f"Error: Repository '{repo_id}' has not been synced yet.", err=True)
                    click.echo(f"Run 'chantal repo sync --repo-id {repo_id}' first.", err=True)
                else:
                    click.echo(
                        f"Error: Repository '{repo_id}' not found in configuration.", err=True
                    )
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

                    result.append(
                        {
                            "started_at": sync.started_at.isoformat(),
                            "completed_at": (
                                sync.completed_at.isoformat() if sync.completed_at else None
                            ),
                            "status": sync.status,
                            "duration_seconds": duration,
                            "packages_added": sync.packages_added,
                            "packages_removed": sync.packages_removed,
                            "packages_updated": sync.packages_updated,
                            "bytes_downloaded": sync.bytes_downloaded,
                            "error_message": sync.error_message,
                        }
                    )
                click.echo(json.dumps(result, indent=2))
            else:
                # Table format
                click.echo(f"Sync History: {repo_id}")
                click.echo(f"Showing last {limit} sync(s)")
                click.echo()

                if not history:
                    click.echo("  No sync history found.")
                    click.echo()
                    click.echo(
                        f"  Run 'chantal repo sync --repo-id {repo_id}' to sync this repository."
                    )
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

                    click.echo(
                        f"{date_str:<20} {status_str:<10} {duration_str:>10} {changes_str:<30}"
                    )

                    # Show error message if failed
                    if sync.status == "failed" and sync.error_message:
                        click.echo(f"  Error: {sync.error_message}")

                click.echo()
                click.echo(f"Total: {len(history)} sync operation(s)")

    return repo


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
            mode=repo_config.mode.upper(),  # Convert to uppercase for enum (MIRROR, FILTERED, HOSTED)
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
        helm_syncer = HelmSyncer(
            storage=storage,
            config=repo_config,
            proxy_config=effective_proxy,
            ssl_config=effective_ssl,
        )
        stats = helm_syncer.sync_repository(session, repository, repo_config)

        # Update last sync timestamp
        repository.last_sync_at = datetime.now(timezone.utc)
        session.commit()

        # Display result
        click.echo("\n✓ Helm sync completed successfully!")
        click.echo(f"  Charts added: {stats['charts_added']}")
        click.echo(f"  Charts updated: {stats['charts_updated']}")
        click.echo(f"  Charts skipped: {stats['charts_skipped']}")
        click.echo(f"  Data transferred: {stats['bytes_downloaded'] / 1024 / 1024:.2f} MB")
        return
    elif repo_config.type == "apk":
        apk_syncer = ApkSyncer(
            storage=storage,
            config=repo_config,
            proxy_config=effective_proxy,
            ssl_config=effective_ssl,
        )
        stats = apk_syncer.sync_repository(session, repository, repo_config)

        # Update last sync timestamp
        repository.last_sync_at = datetime.now(timezone.utc)
        session.commit()

        # Display result
        click.echo("\n✓ APK sync completed successfully!")
        click.echo(f"  Packages added: {stats['packages_added']}")
        click.echo(f"  Packages updated: {stats['packages_updated']}")
        click.echo(f"  Packages skipped: {stats['packages_skipped']}")
        click.echo(f"  Data transferred: {stats['bytes_downloaded'] / 1024 / 1024:.2f} MB")
        if stats["sha1_mismatches"] > 0:
            click.echo(
                f"  SHA1 mismatches: {stats['sha1_mismatches']} (stale APKINDEX, integrity verified via SHA256)"
            )
        return
    else:
        click.echo(f"Error: Unsupported repository type: {repo_config.type}")
        return

    # Perform sync
    result = sync_plugin.sync_repository(session, repository)

    # Display result
    if result.success:
        # Update last sync timestamp
        repository.last_sync_at = datetime.now(timezone.utc)
        session.commit()

        click.echo("\n✓ Sync completed successfully!")
        click.echo(f"  Total packages: {result.packages_total}")
        click.echo(f"  Downloaded: {result.packages_downloaded}")
        click.echo(f"  Skipped (already in pool): {result.packages_skipped}")
        click.echo(f"  Data transferred: {result.bytes_downloaded / 1024 / 1024:.2f} MB")
    else:
        click.echo(f"\n✗ Sync failed: {result.error_message}", err=True)


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
                size_str = (
                    f"{size_mb:.1f} MB" if size_mb >= 1 else f"{update.size_bytes / 1024:.0f} KB"
                )

                name_display = (
                    update.name[:max_name] if len(update.name) > max_name else update.name
                )

                click.echo(
                    f"{name_display:<{max_name}}  {update.arch:<10}  {local_ver:<20}  {remote_ver:<20}  {size_str:>10}"
                )

            click.echo()
            click.echo(
                f"Summary: {len(result.updates_available)} package update(s) available ({result.total_size_bytes / 1024 / 1024:.2f} MB)"
            )
            click.echo()
            click.echo(f"Run 'chantal repo sync --repo-id {repo_config.id}' to download updates")

    else:
        click.echo(f"\n✗ Check failed: {result.error_message}", err=True)

    return result
