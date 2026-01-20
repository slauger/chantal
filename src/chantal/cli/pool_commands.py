from __future__ import annotations

"""Storage pool management commands."""

import click

from chantal.core.config import GlobalConfig
from chantal.core.storage import StorageManager
from chantal.db.connection import DatabaseManager
from chantal.db.models import ContentItem

# Click context settings to enable -h as alias for --help
CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


def create_pool_group(cli: click.Group) -> click.Group:
    """Create and return the pool command group.

    Args:
        cli: Parent CLI group to attach to

    Returns:
        The pool command group
    """

    @cli.group(context_settings=CONTEXT_SETTINGS)
    def pool() -> None:
        """Storage pool management commands."""
        pass

    @pool.command("stats")
    @click.pass_context
    def pool_stats(ctx: click.Context) -> None:
        """Show storage pool statistics."""
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
            click.echo(
                f"Database Size:           {stats['total_size_db']:,} bytes ({stats['total_size_db'] / (1024**3):.2f} GB)"
            )
            click.echo()
            click.echo(f"Files in Pool:           {stats['total_files_pool']:,}")
            click.echo(
                f"Pool Size on Disk:       {stats['total_size_pool']:,} bytes ({stats['total_size_pool'] / (1024**3):.2f} GB)"
            )
            click.echo()
            click.echo(f"Orphaned Files:          {stats['orphaned_files']:,}")

            if stats["deduplication_savings"] > 0:
                savings_pct = (
                    (stats["deduplication_savings"] / stats["total_size_db"]) * 100
                    if stats["total_size_db"] > 0
                    else 0
                )
                click.echo(
                    f"Deduplication Savings:   {stats['deduplication_savings']:,} bytes ({savings_pct:.1f}%)"
                )

        finally:
            session.close()

    @pool.command("cleanup")
    @click.option(
        "--dry-run", is_flag=True, help="Show what would be deleted without actually deleting"
    )
    @click.option(
        "--orphaned", is_flag=True, help="Only clean orphaned files (in pool but not in database)"
    )
    @click.option(
        "--missing", is_flag=True, help="Only clean missing entries (in database but not in pool)"
    )
    @click.option(
        "--force", is_flag=True, help="Skip confirmation prompt"
    )
    @click.pass_context
    def pool_cleanup(ctx: click.Context, dry_run: bool, orphaned: bool, missing: bool, force: bool) -> None:
        """Clean up pool integrity issues.

        By default, cleans both orphaned files and missing database entries.
        Use --orphaned or --missing to clean only one type.

        Orphaned files: Files in pool that are not referenced in database
        Missing entries: Database entries without corresponding pool files

        IMPORTANT: This command requires confirmation unless --force or --dry-run is used.
        """
        config: GlobalConfig = ctx.obj["config"]

        # Determine what to clean (default: both)
        cleanup_orphaned = orphaned or (not orphaned and not missing)
        cleanup_missing = missing or (not orphaned and not missing)

        # Initialize storage manager
        storage = StorageManager(config.storage)

        # Initialize database connection
        db_manager = DatabaseManager(config.database.url)
        session = db_manager.get_session()

        try:
            if dry_run:
                click.echo("DRY RUN: Analyzing pool integrity issues...")
            else:
                click.echo("Analyzing pool integrity issues...")
            click.echo()

            total_files_removed = 0
            total_bytes_freed = 0
            total_db_removed = 0

            # First pass: Count what would be cleaned (for confirmation)
            orphaned_file_count = 0
            orphaned_bytes = 0
            missing_entry_count = 0

            if not dry_run:
                # Count orphaned files
                if cleanup_orphaned:
                    click.echo("Checking for orphaned files...")
                    orphaned_files = storage.get_orphaned_files(session)
                    orphaned_file_count = len(orphaned_files)
                    orphaned_bytes = sum(f.stat().st_size for f in orphaned_files)

                # Count missing entries
                if cleanup_missing:
                    click.echo("Checking for missing files...")
                    packages = session.query(ContentItem).all()
                    for package in packages:
                        pool_file = storage.pool_path / package.pool_path
                        if not pool_file.exists():
                            missing_entry_count += 1

                click.echo()

                # Show summary and ask for confirmation
                if orphaned_file_count > 0 or missing_entry_count > 0:
                    click.echo("Will delete:")
                    if cleanup_orphaned and orphaned_file_count > 0:
                        click.echo(f"  - {orphaned_file_count:,} orphaned files ({orphaned_bytes / (1024**2):.2f} MB)")
                    if cleanup_missing and missing_entry_count > 0:
                        click.echo(f"  - {missing_entry_count:,} database entries")
                    click.echo()

                    # Ask for confirmation unless --force is used
                    if not force:
                        if not click.confirm("Delete these items?", default=False):
                            click.echo("Aborted.")
                            return
                        click.echo()
                else:
                    click.echo("No cleanup needed.")
                    return

            # Clean up orphaned files (in pool but not in DB)
            if cleanup_orphaned:
                if dry_run:
                    click.echo("Checking for orphaned files...")
                else:
                    click.echo("Removing orphaned files...")

                files_removed, bytes_freed = storage.cleanup_orphaned_files(
                    session, dry_run=dry_run
                )
                total_files_removed += files_removed
                total_bytes_freed += bytes_freed

                if dry_run:
                    click.echo(
                        f"  Would remove {files_removed:,} orphaned files ({bytes_freed / (1024**2):.2f} MB)"
                    )
                else:
                    click.echo(
                        f"  Removed {files_removed:,} orphaned files ({bytes_freed / (1024**2):.2f} MB)"
                    )
                click.echo()

            # Clean up missing entries (in DB but not in pool)
            if cleanup_missing:
                if dry_run:
                    click.echo("Checking for missing files...")
                else:
                    click.echo("Removing database entries with missing files...")

                # Find packages with missing files
                packages = session.query(ContentItem).all()
                missing_packages = []

                for package in packages:
                    pool_file = storage.pool_path / package.pool_path
                    if not pool_file.exists():
                        missing_packages.append(package)

                if not dry_run:
                    for package in missing_packages:
                        session.delete(package)
                    session.commit()

                total_db_removed = len(missing_packages)

                if dry_run:
                    click.echo(f"  Would remove {total_db_removed:,} database entries")
                else:
                    click.echo(f"  Removed {total_db_removed:,} database entries")
                click.echo()

            # Summary
            click.echo("=" * 60)
            if dry_run:
                click.echo("Summary (DRY RUN):")
            else:
                click.echo("Summary:")

            if cleanup_orphaned:
                click.echo(
                    f"  Orphaned files: {total_files_removed:,} ({total_bytes_freed / (1024**2):.2f} MB)"
                )
            if cleanup_missing:
                click.echo(f"  Missing entries: {total_db_removed:,}")

        finally:
            session.close()

    @pool.command("orphaned")
    @click.pass_context
    def pool_orphaned(ctx: click.Context) -> None:
        """List orphaned files in storage pool.

        Orphaned files are package files in the pool that are not referenced
        in the database. This can happen after package deletion or cleanup operations.
        """
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
                click.echo(
                    f"Total: {len(orphaned_files):,} files, {total_size:,} bytes ({total_size / (1024**2):.2f} MB)"
                )
            else:
                click.echo("No orphaned files found.")

        finally:
            session.close()

    @pool.command("missing")
    @click.pass_context
    def pool_missing(ctx: click.Context) -> None:
        """List packages in database with missing pool files.

        Missing files are packages referenced in the database but whose
        files are not present in the storage pool. This indicates data loss
        or corruption.
        """
        config: GlobalConfig = ctx.obj["config"]

        # Initialize storage manager
        storage = StorageManager(config.storage)

        # Initialize database connection
        db_manager = DatabaseManager(config.database.url)
        session = db_manager.get_session()

        try:
            click.echo("Finding missing pool files...")
            click.echo()

            missing_packages = []
            total_size = 0

            # Get all packages from database
            packages = session.query(ContentItem).all()

            for package in packages:
                pool_file = storage.pool_path / package.pool_path

                if not pool_file.exists():
                    missing_packages.append(package)
                    total_size += package.size_bytes

            if missing_packages:
                click.echo(f"Found {len(missing_packages):,} missing files:")
                click.echo()

                for package in missing_packages:
                    click.echo(f"  {package.pool_path} ({package.size_bytes:,} bytes)")
                    click.echo(f"    Package: {package.name}-{package.version}")
                    click.echo(f"    SHA256: {package.sha256[:16]}...")
                    click.echo()

                click.echo(
                    f"Total: {len(missing_packages):,} files, {total_size:,} bytes ({total_size / (1024**2):.2f} MB)"
                )
            else:
                click.echo("No missing files found.")

        finally:
            session.close()

    @pool.command("verify")
    @click.pass_context
    def pool_verify(ctx: click.Context) -> None:
        """Verify storage pool integrity.

        Comprehensive integrity check:
        - Orphaned files (in pool but not in database)
        - Missing files (in database but not in pool)
        - SHA256 checksum verification
        - File size verification

        For detailed file lists, use 'pool orphaned' or 'pool missing'.
        """
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

            # Counters
            missing_files = 0
            sha256_mismatches = 0
            size_mismatches = 0
            orphaned_count = 0

            # Get all packages from database
            packages = session.query(ContentItem).all()
            click.echo(f"Checking {len(packages):,} packages from database...")

            for i, package in enumerate(packages, 1):
                if i % 100 == 0:
                    click.echo(f"  Progress: {i:,}/{len(packages):,} packages...", nl=False)
                    click.echo("\r", nl=False)

                # Check if file exists
                pool_file = storage.pool_path / package.pool_path

                if not pool_file.exists():
                    missing_files += 1
                    continue

                # Verify SHA256
                actual_sha256 = storage.calculate_sha256(pool_file)
                if actual_sha256 != package.sha256:
                    sha256_mismatches += 1

                # Verify file size
                actual_size = pool_file.stat().st_size
                if actual_size != package.size_bytes:
                    size_mismatches += 1

            click.echo()

            # Check for orphaned files
            click.echo("Checking for orphaned files in pool...")
            orphaned_files = storage.get_orphaned_files(session)
            orphaned_count = len(orphaned_files)
            orphaned_size = sum(f.stat().st_size for f in orphaned_files)

            click.echo()
            click.echo("=" * 60)
            click.echo("Verification Results:")
            click.echo("=" * 60)

            total_issues = missing_files + sha256_mismatches + size_mismatches + orphaned_count

            if total_issues == 0:
                click.echo("✓ Pool verification completed successfully!")
                click.echo(f"  All {len(packages):,} packages verified")
                click.echo("  No orphaned files found")
            else:
                click.echo(f"Pool verification found {total_issues:,} issues:")
                click.echo()

                if missing_files > 0:
                    click.echo(f"  ✗ Missing files: {missing_files:,}")
                    click.echo("    (in database but not in pool)")
                    click.echo("    → Run 'chantal pool missing' for details")
                    click.echo()

                if orphaned_count > 0:
                    click.echo(
                        f"  ✗ Orphaned files: {orphaned_count:,} ({orphaned_size / (1024**2):.2f} MB)"
                    )
                    click.echo("    (in pool but not in database)")
                    click.echo("    → Run 'chantal pool orphaned' for details")
                    click.echo("    → Run 'chantal pool cleanup' to remove")
                    click.echo()

                if sha256_mismatches > 0:
                    click.echo(f"  ✗ SHA256 mismatches: {sha256_mismatches:,}")
                    click.echo("    (file content doesn't match expected checksum)")
                    click.echo()

                if size_mismatches > 0:
                    click.echo(f"  ⚠ Size mismatches: {size_mismatches:,}")
                    click.echo("    (file size doesn't match expected size)")
                    click.echo()

        finally:
            session.close()

    return pool
