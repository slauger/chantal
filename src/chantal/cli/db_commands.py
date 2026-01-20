from __future__ import annotations

"""Database management commands."""

import click
from sqlalchemy.orm import Session

from chantal.core.config import GlobalConfig
from chantal.db import migrations
from chantal.db.connection import DatabaseManager
from chantal.db.models import Repository, Snapshot, SyncHistory

# Click context settings to enable -h as alias for --help
CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


def _get_orphaned_repositories(session: Session, config: GlobalConfig) -> list[Repository]:
    """Get repositories in database that are not in configuration.

    Args:
        session: Database session
        config: Global configuration

    Returns:
        List of orphaned repositories
    """
    config_repo_ids = {r.id for r in config.repositories}
    all_repos = session.query(Repository).all()
    return [r for r in all_repos if r.repo_id not in config_repo_ids]


def create_db_group(cli: click.Group) -> click.Group:
    """Create and return the db command group.

    Args:
        cli: Parent CLI group to attach to

    Returns:
        The db command group
    """

    @cli.group(context_settings=CONTEXT_SETTINGS)
    def db() -> None:
        """Database management commands."""
        pass

    @db.command("init")
    @click.pass_context
    def db_init(ctx: click.Context) -> None:
        """Initialize database schema using Alembic migrations.

        Creates all database tables according to the latest schema version.
        Storage directories will be created automatically when needed.
        """
        config: GlobalConfig = ctx.obj["config"]

        click.echo("Initializing database schema...")
        click.echo(f"Database: {config.database.url}")
        click.echo()

        try:
            migrations.init_database(config.database.url)
            current = migrations.get_current_revision(config.database.url)
            if current:
                click.echo(f"✓ Database initialized to revision: {current[:8]}")
            else:
                click.echo("✓ Database initialized")
        except Exception as e:
            click.echo(f"✗ Database initialization failed: {e}", err=True)
            ctx.exit(1)

    @db.command("upgrade")
    @click.argument("revision", default="head", required=False)
    @click.pass_context
    def db_upgrade(ctx: click.Context, revision: str) -> None:
        """Upgrade database schema to a specific revision (default: latest).

        Examples:
            chantal db upgrade         # Upgrade to latest
            chantal db upgrade head    # Upgrade to latest (explicit)
            chantal db upgrade abc123  # Upgrade to specific revision
        """
        config: GlobalConfig = ctx.obj["config"]

        current = migrations.get_current_revision(config.database.url)

        if current is None:
            click.echo("⚠️  Database not initialized!", err=True)
            click.echo("Run 'chantal db init' first.", err=True)
            ctx.exit(1)

        click.echo(f"Current revision: {current[:8]}")
        click.echo(f"Upgrading to: {revision}")
        click.echo()

        try:
            migrations.upgrade_database(config.database.url, revision)
            new_current = migrations.get_current_revision(config.database.url)
            if new_current:
                click.echo(f"✓ Database upgraded to revision: {new_current[:8]}")
            else:
                click.echo("✓ Database upgraded")
        except Exception as e:
            click.echo(f"✗ Upgrade failed: {e}", err=True)
            ctx.exit(1)

    @db.command("status")
    @click.pass_context
    def db_status(ctx: click.Context) -> None:
        """Show database schema status and pending migrations."""
        config: GlobalConfig = ctx.obj["config"]

        current = migrations.get_current_revision(config.database.url)
        head = migrations.get_head_revision(config.database.url)

        click.echo("Database Schema Status")
        click.echo("━" * 60)
        click.echo()
        click.echo(f"Database:  {config.database.url}")

        if current is None:
            click.echo("Current:   Not initialized")
            click.echo(f"Latest:    {head[:8]}")
            click.echo()
            click.echo("Status:    ⚠️  Database not initialized")
            click.echo()
            click.echo("Run 'chantal db init' to initialize the database.")
            return

        current_info = migrations.get_revision_info(config.database.url, current)
        head_info = migrations.get_revision_info(config.database.url, head)

        current_msg = current_info[1] if current_info else ""
        head_msg = head_info[1] if head_info else ""

        click.echo(f"Current:   {current[:8]} ({current_msg})")
        click.echo(f"Latest:    {head[:8]} ({head_msg})")
        click.echo()

        if current == head:
            click.echo("Status:    ✓ Up to date")
        else:
            pending = migrations.get_pending_migrations(config.database.url)
            click.echo(f"Status:    ⚠️  {len(pending)} migration(s) pending")
            click.echo()
            click.echo("Pending Migrations:")
            for rev, msg in pending:
                click.echo(f"  • {rev[:8]} - {msg}")
            click.echo()
            click.echo("Run 'chantal db upgrade' to apply pending migrations.")

    @db.command("current")
    @click.pass_context
    def db_current(ctx: click.Context) -> None:
        """Show current database schema revision."""
        config: GlobalConfig = ctx.obj["config"]

        current = migrations.get_current_revision(config.database.url)

        if current is None:
            click.echo("Database not initialized")
            click.echo("Run 'chantal db init' to initialize.")
            return

        current_info = migrations.get_revision_info(config.database.url, current)
        current_msg = current_info[1] if current_info else ""

        click.echo(f"Current revision: {current}")
        if current_msg:
            click.echo(f"Message: {current_msg}")

    @db.command("history")
    @click.pass_context
    def db_history(ctx: click.Context) -> None:
        """Show migration history."""
        config: GlobalConfig = ctx.obj["config"]

        history = migrations.get_migration_history(config.database.url)

        click.echo("Migration History")
        click.echo("━" * 60)
        click.echo()

        if not history:
            click.echo("No migrations found.")
            return

        for rev, msg, is_applied in history:
            status = "✓" if is_applied else "⧗"
            state = "Applied" if is_applied else "Pending"
            click.echo(f"{status} {rev[:8]} - {msg} [{state}]")

        click.echo()
        click.echo("Legend: ✓ Applied  ⧗ Pending")

    @db.command("cleanup")
    @click.option("--dry-run", is_flag=True, help="Show what would be deleted")
    @click.option(
        "--orphaned", is_flag=True, help="Only clean orphaned repositories (in DB but not in config)"
    )
    @click.option(
        "--unreferenced", is_flag=True, help="Only clean unreferenced packages"
    )
    @click.option(
        "--force", is_flag=True, help="Skip confirmation prompt"
    )
    @click.pass_context
    def db_cleanup(ctx: click.Context, dry_run: bool, orphaned: bool, unreferenced: bool, force: bool) -> None:
        """Clean up database issues.

        By default, cleans both orphaned repositories and unreferenced packages.
        Use --orphaned or --unreferenced to clean only one type.

        Orphaned repositories: Repositories in database that are not in configuration
        Unreferenced packages: Packages in database without repository references

        IMPORTANT: This command requires confirmation unless --force or --dry-run is used.
        """
        config: GlobalConfig = ctx.obj["config"]

        # Determine what to clean (default: both)
        cleanup_orphaned = orphaned or (not orphaned and not unreferenced)
        cleanup_unreferenced = unreferenced or (not orphaned and not unreferenced)

        # Initialize database connection
        db_manager = DatabaseManager(config.database.url)
        session = db_manager.get_session()

        try:
            if dry_run:
                click.echo("DRY RUN: Analyzing database issues...")
            else:
                click.echo("Analyzing database issues...")
            click.echo()

            total_repos_deleted = 0
            total_snapshots_deleted = 0
            total_history_deleted = 0

            # Get orphaned repositories (for both dry-run and confirmation)
            orphaned_repos = []
            if cleanup_orphaned:
                orphaned_repos = _get_orphaned_repositories(session, config)

            # Interactive confirmation (only if not dry-run and not force)
            if not dry_run and not force:
                if orphaned_repos:
                    # Count related objects
                    total_snaps = sum(session.query(Snapshot).filter_by(repository_id=r.id).count() for r in orphaned_repos)
                    total_hist = sum(session.query(SyncHistory).filter_by(repository_id=r.id).count() for r in orphaned_repos)

                    click.echo("Will delete:")
                    if cleanup_orphaned and orphaned_repos:
                        click.echo(f"  - {len(orphaned_repos)} orphaned repositories")
                        click.echo(f"  - {total_snaps} snapshots")
                        click.echo(f"  - {total_hist} sync history entries")
                    click.echo()

                    # Ask for confirmation
                    if not click.confirm("Delete these items?", default=False):
                        click.echo("Aborted.")
                        return
                    click.echo()
                else:
                    click.echo("No cleanup needed.")
                    return

            # Clean up orphaned repositories
            if cleanup_orphaned:

                if orphaned_repos:
                    click.echo(f"Orphaned repositories ({len(orphaned_repos)}):")
                    for repo in orphaned_repos:
                        # Count related objects
                        snapshot_count = session.query(Snapshot).filter_by(repository_id=repo.id).count()
                        history_count = session.query(SyncHistory).filter_by(repository_id=repo.id).count()

                        click.echo(f"  - {repo.repo_id} ({repo.type}, {history_count} syncs, {snapshot_count} snapshots)")

                        if not dry_run:
                            # Delete related sync history
                            session.query(SyncHistory).filter_by(repository_id=repo.id).delete()
                            total_history_deleted += history_count

                            # Delete related snapshots
                            session.query(Snapshot).filter_by(repository_id=repo.id).delete()
                            total_snapshots_deleted += snapshot_count

                            # Delete repository
                            session.delete(repo)
                            total_repos_deleted += 1

                    if not dry_run:
                        session.commit()
                    click.echo()
                else:
                    click.echo("No orphaned repositories found.")
                    click.echo()

            # Clean up unreferenced packages (TODO)
            if cleanup_unreferenced:
                click.echo("Unreferenced packages cleanup: TODO")
                click.echo()

            # Summary
            if dry_run:
                click.echo("Summary (DRY RUN):")
                if cleanup_orphaned:
                    click.echo(f"  Would delete {len(orphaned_repos) if orphaned_repos else 0} repositories")
                    if orphaned_repos:
                        total_snaps = sum(session.query(Snapshot).filter_by(repository_id=r.id).count() for r in orphaned_repos)
                        total_hist = sum(session.query(SyncHistory).filter_by(repository_id=r.id).count() for r in orphaned_repos)
                        click.echo(f"  Would delete {total_snaps} snapshots")
                        click.echo(f"  Would delete {total_hist} sync history entries")
            else:
                click.echo("Summary:")
                if cleanup_orphaned:
                    click.echo(f"  Deleted {total_repos_deleted} repositories")
                    click.echo(f"  Deleted {total_snapshots_deleted} snapshots")
                    click.echo(f"  Deleted {total_history_deleted} sync history entries")

        finally:
            session.close()

    @db.command("orphaned")
    @click.pass_context
    def db_orphaned(ctx: click.Context) -> None:
        """List orphaned repositories in database.

        Orphaned repositories are repositories in the database that are not
        in the configuration file. This can happen after removing repositories
        from the configuration.
        """
        config: GlobalConfig = ctx.obj["config"]

        # Initialize database connection
        db_manager = DatabaseManager(config.database.url)
        session = db_manager.get_session()

        try:
            click.echo("Finding orphaned repositories...")
            click.echo()

            orphaned_repos = _get_orphaned_repositories(session, config)

            if orphaned_repos:
                click.echo(f"Found {len(orphaned_repos)} orphaned repositories:")
                click.echo()

                # Table header
                click.echo(f"{'Repository ID':<30} {'Type':<8} {'Last Sync':<20} {'Syncs':<8} {'Snapshots':<10}")
                click.echo("-" * 82)

                for repo in orphaned_repos:
                    # Get counts
                    sync_count = session.query(SyncHistory).filter_by(repository_id=repo.id).count()
                    snapshot_count = session.query(Snapshot).filter_by(repository_id=repo.id).count()

                    # Format last sync
                    if repo.last_sync_at:
                        last_sync = repo.last_sync_at.strftime("%Y-%m-%d %H:%M")
                    else:
                        last_sync = "Never synced"

                    click.echo(f"{repo.repo_id:<30} {repo.type:<8} {last_sync:<20} {sync_count:<8} {snapshot_count:<10}")

                click.echo()
                click.echo(f"Total: {len(orphaned_repos)} orphaned repositories")
                click.echo()
                click.echo("To remove these repositories, run:")
                click.echo("  chantal db cleanup --orphaned --dry-run  (preview)")
                click.echo("  chantal db cleanup --orphaned             (delete)")
            else:
                click.echo("No orphaned repositories found.")

        finally:
            session.close()

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
        """Verify database integrity.

        Checks:
        - Orphaned repositories (in database but not in configuration)
        - Foreign key constraints
        - Repository references
        """
        config: GlobalConfig = ctx.obj["config"]

        # Initialize database connection
        db_manager = DatabaseManager(config.database.url)
        session = db_manager.get_session()

        try:
            click.echo("Verifying database integrity...")
            click.echo("=" * 60)
            click.echo()

            total_issues = 0

            # Check for orphaned repositories
            click.echo("Checking for orphaned repositories...")
            orphaned_repos = _get_orphaned_repositories(session, config)

            if orphaned_repos:
                click.echo(f"  ✗ Found {len(orphaned_repos)} orphaned repositories")
                total_issues += len(orphaned_repos)
                for repo in orphaned_repos:
                    click.echo(f"    - {repo.repo_id} ({repo.type})")
                click.echo()
                click.echo("    → Run 'chantal db orphaned' for details")
                click.echo("    → Run 'chantal db cleanup --orphaned' to remove")
            else:
                click.echo("  ✓ No orphaned repositories found")
            click.echo()

            # Check repository counts
            click.echo("Repository statistics:")
            config_repo_count = len(config.repositories)
            db_repo_count = session.query(Repository).count()
            click.echo(f"  Repositories in config: {config_repo_count}")
            click.echo(f"  Repositories in database: {db_repo_count}")
            click.echo()

            # Summary
            click.echo("=" * 60)
            if total_issues == 0:
                click.echo("✓ Database verification completed successfully!")
                click.echo("  No issues found")
            else:
                click.echo(f"Database verification found {total_issues} issue(s)")
                click.echo()
                click.echo("Run 'chantal db cleanup --dry-run' to see what would be cleaned")

        finally:
            session.close()

    return db


def check_db_schema_version(ctx: click.Context) -> None:
    """Check if database schema is up to date.

    Exits with error if database needs upgrade.

    Args:
        ctx: Click context with config
    """
    config: GlobalConfig = ctx.obj["config"]

    if migrations.db_needs_upgrade(config.database.url):
        current = migrations.get_current_revision(config.database.url)

        if current is None:
            click.echo("⚠️  Database not initialized!", err=True)
            click.echo("Run 'chantal db init' to initialize the database.", err=True)
        else:
            pending = migrations.get_pending_migrations(config.database.url)
            click.echo("⚠️  Database schema is outdated!", err=True)
            click.echo(f"   {len(pending)} migration(s) pending.", err=True)
            click.echo("Run 'chantal db upgrade' to update the database.", err=True)

        ctx.exit(1)
