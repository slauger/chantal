from __future__ import annotations

"""
Database migration helpers using Alembic.

This module provides programmatic access to Alembic operations for database
schema management.
"""

from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from alembic import command


def get_alembic_config(database_url: str) -> Config:
    """Get Alembic configuration.

    Args:
        database_url: SQLAlchemy database URL

    Returns:
        Alembic Config object
    """
    # Find alembic.ini relative to this file
    project_root = Path(__file__).parent.parent.parent.parent
    alembic_ini = project_root / "alembic.ini"

    if not alembic_ini.exists():
        raise FileNotFoundError(f"alembic.ini not found at {alembic_ini}")

    config = Config(str(alembic_ini))
    config.set_main_option("sqlalchemy.url", database_url)

    return config


def get_current_revision(database_url: str) -> str | None:
    """Get current database schema revision.

    Args:
        database_url: SQLAlchemy database URL

    Returns:
        Current revision hash, or None if database not initialized
    """
    try:
        engine = create_engine(database_url)

        # Check if alembic_version table exists
        inspector = inspect(engine)
        if "alembic_version" not in inspector.get_table_names():
            return None

        with engine.connect() as conn:
            context = MigrationContext.configure(conn)
            return context.get_current_revision()
    except Exception:
        return None


def get_head_revision(database_url: str) -> str:
    """Get latest available schema revision.

    Args:
        database_url: SQLAlchemy database URL

    Returns:
        Latest revision hash
    """
    config = get_alembic_config(database_url)
    script = ScriptDirectory.from_config(config)
    return script.get_current_head()


def get_pending_migrations(database_url: str) -> list[tuple[str, str]]:
    """Get list of pending migrations.

    Args:
        database_url: SQLAlchemy database URL

    Returns:
        List of (revision, message) tuples for pending migrations
    """
    current = get_current_revision(database_url)
    config = get_alembic_config(database_url)
    script = ScriptDirectory.from_config(config)

    pending = []

    if current is None:
        # Database not initialized - all migrations are pending
        for rev in script.walk_revisions("base", "heads"):
            pending.append((rev.revision, rev.doc or ""))
        pending.reverse()  # Show oldest first
    else:
        # Get migrations between current and head
        for rev in script.walk_revisions(current, "heads"):
            if rev.revision != current:
                pending.append((rev.revision, rev.doc or ""))
        pending.reverse()  # Show oldest first

    return pending


def get_migration_history(database_url: str) -> list[tuple[str, str, bool]]:
    """Get full migration history with applied status.

    Args:
        database_url: SQLAlchemy database URL

    Returns:
        List of (revision, message, is_applied) tuples
    """
    current = get_current_revision(database_url)
    config = get_alembic_config(database_url)
    script = ScriptDirectory.from_config(config)

    # Get all revisions using iterate_revisions (oldest to newest)
    history = []
    for rev in script.iterate_revisions():
        if current is None:
            # No migrations applied yet
            is_applied = False
        else:
            # Check if this revision is the current one or comes before it
            # We'll mark it as applied if it appears in the chain up to current
            try:
                # Try to walk from current to this revision
                # If we can reach it, it's been applied
                for check_rev in script.walk_revisions(current, rev.revision):
                    if check_rev.revision == rev.revision:
                        is_applied = True
                        break
                else:
                    is_applied = False
            except Exception:
                # If walk fails, check if it's exactly current
                is_applied = rev.revision == current

        history.append((rev.revision, rev.doc or "", is_applied))

    return history


def db_needs_upgrade(database_url: str) -> bool:
    """Check if database needs to be upgraded.

    Args:
        database_url: SQLAlchemy database URL

    Returns:
        True if upgrade needed, False otherwise
    """
    current = get_current_revision(database_url)
    head = get_head_revision(database_url)

    if current is None:
        # Database not initialized
        return True

    return current != head


def init_database(database_url: str) -> None:
    """Initialize database with latest schema using Alembic.

    Args:
        database_url: SQLAlchemy database URL
    """
    config = get_alembic_config(database_url)
    command.upgrade(config, "head")


def upgrade_database(database_url: str, revision: str = "head") -> None:
    """Upgrade database to specific revision.

    Args:
        database_url: SQLAlchemy database URL
        revision: Target revision (default: "head")
    """
    config = get_alembic_config(database_url)
    command.upgrade(config, revision)


def downgrade_database(database_url: str, revision: str) -> None:
    """Downgrade database to specific revision.

    Args:
        database_url: SQLAlchemy database URL
        revision: Target revision
    """
    config = get_alembic_config(database_url)
    command.downgrade(config, revision)


def get_revision_info(database_url: str, revision: str) -> tuple[str, str] | None:
    """Get information about a specific revision.

    Args:
        database_url: SQLAlchemy database URL
        revision: Revision hash (can be partial)

    Returns:
        Tuple of (full_revision, message) or None if not found
    """
    config = get_alembic_config(database_url)
    script = ScriptDirectory.from_config(config)

    try:
        rev = script.get_revision(revision)
        return (rev.revision, rev.doc or "")
    except Exception:
        return None
