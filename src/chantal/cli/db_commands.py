from __future__ import annotations

"""Database management commands."""

import click

from chantal.core.config import GlobalConfig
from chantal.db import migrations

# Click context settings to enable -h as alias for --help
CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


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
            click.echo(f"✓ Database initialized to revision: {current[:8]}")
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
            click.echo(f"✓ Database upgraded to revision: {new_current[:8]}")
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
