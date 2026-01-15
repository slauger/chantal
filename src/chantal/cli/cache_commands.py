from __future__ import annotations

"""Cache management commands."""

import click

from chantal.core.cache import MetadataCache
from chantal.core.config import GlobalConfig

# Click context settings to enable -h as alias for --help
CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


def create_cache_group(cli: click.Group) -> click.Group:
    """Create and return the cache command group.

    Args:
        cli: Parent CLI group to attach to

    Returns:
        The cache command group
    """

    @cli.group(context_settings=CONTEXT_SETTINGS)
    def cache() -> None:
        """Metadata cache management commands."""
        pass

    @cache.command("clear")
    @click.option(
        "--repo-id",
        help="Clear cache for specific repository (not implemented yet - clears all)",
    )
    @click.option("--all", "clear_all", is_flag=True, help="Clear entire cache")
    @click.option("--force", is_flag=True, help="Skip confirmation prompt")
    @click.pass_context
    def cache_clear(ctx: click.Context, repo_id: str, clear_all: bool, force: bool) -> None:
        """Clear metadata cache.

        By default, clears all cached metadata files.
        """
        config: GlobalConfig = ctx.obj["config"]

        # Check if cache is configured
        cache_path = config.storage.get_cache_path()
        if not cache_path:
            click.echo("Cache is not configured (storage.cache_path not set)")
            return

        if not cache_path.exists():
            click.echo(f"Cache directory does not exist: {cache_path}")
            return

        # Initialize cache manager
        cache_manager = MetadataCache(
            cache_path=cache_path,
            max_age_hours=config.cache.max_age_hours if config.cache else None,
            enabled=True,
        )

        # Get stats before clearing
        stats = cache_manager.stats()

        if stats.total_files == 0:
            click.echo("Cache is already empty")
            return

        # Confirm action
        if not force:
            size_mb = stats.total_size_bytes / (1024 * 1024)
            click.echo(f"About to delete {stats.total_files} cached file(s) ({size_mb:.2f} MB)")
            if not click.confirm("Continue?"):
                click.echo("Aborted")
                return

        # Clear cache
        if repo_id:
            click.echo("Note: Per-repository clearing not yet implemented")
            click.echo("Clearing all cache entries instead...")

        files_deleted = cache_manager.clear()
        size_mb = stats.total_size_bytes / (1024 * 1024)

        click.echo()
        click.echo("✓ Cache cleared successfully!")
        click.echo(f"  Files deleted: {files_deleted}")
        click.echo(f"  Space freed: {size_mb:.2f} MB")

    @cache.command("stats")
    @click.pass_context
    def cache_stats(ctx: click.Context) -> None:
        """Show cache statistics."""
        config: GlobalConfig = ctx.obj["config"]

        # Check if cache is configured
        cache_path = config.storage.get_cache_path()
        if not cache_path:
            click.echo("Cache is not configured (storage.cache_path not set)")
            click.echo()
            click.echo("To enable caching, add to your config:")
            click.echo("  storage:")
            click.echo("    cache_path: /var/lib/chantal/cache")
            click.echo("  cache:")
            click.echo("    enabled: true")
            return

        if not cache_path.exists():
            click.echo(f"Cache directory: {cache_path}")
            click.echo("Status: Not created yet (no files cached)")
            return

        # Initialize cache manager
        cache_manager = MetadataCache(
            cache_path=cache_path,
            max_age_hours=config.cache.max_age_hours if config.cache else None,
            enabled=True,
        )

        # Get stats
        stats = cache_manager.stats()

        # Display stats
        click.echo(f"Cache directory: {cache_path}")
        click.echo(
            f"Status: {'Enabled' if config.cache and config.cache.enabled else 'Disabled (global)'}"
        )
        if config.cache and config.cache.max_age_hours:
            click.echo(f"Max age: {config.cache.max_age_hours} hours")
        click.echo()

        if stats.total_files == 0:
            click.echo("Cache is empty")
        else:
            size_mb = stats.total_size_bytes / (1024 * 1024)
            size_gb = stats.total_size_bytes / (1024 * 1024 * 1024)

            click.echo(f"Total files: {stats.total_files}")
            if size_gb >= 1.0:
                click.echo(f"Total size: {size_gb:.2f} GB")
            else:
                click.echo(f"Total size: {size_mb:.2f} MB")

            if stats.oldest_file_age_hours is not None:
                click.echo(f"Oldest file: {stats.oldest_file_age_hours:.1f} hours ago")
            if stats.newest_file_age_hours is not None:
                click.echo(f"Newest file: {stats.newest_file_age_hours:.1f} hours ago")

    @cache.command("list")
    @click.option("--limit", type=int, default=50, help="Limit number of files shown")
    @click.pass_context
    def cache_list(ctx: click.Context, limit: int) -> None:
        """List cached metadata files."""
        config: GlobalConfig = ctx.obj["config"]

        # Check if cache is configured
        cache_path = config.storage.get_cache_path()
        if not cache_path:
            click.echo("Cache is not configured (storage.cache_path not set)")
            return

        if not cache_path.exists():
            click.echo(f"Cache directory does not exist: {cache_path}")
            return

        # List cache files
        cache_files = sorted(
            cache_path.glob("*.xml.gz"), key=lambda p: p.stat().st_mtime, reverse=True
        )

        if not cache_files:
            click.echo("Cache is empty")
            return

        click.echo(f"Cached metadata files in {cache_path}:")
        click.echo()
        click.echo(f"{'Checksum (SHA256)':<70} {'Size':>12} {'Age':>12}")
        click.echo("-" * 100)

        import time

        now = time.time()

        for i, cache_file in enumerate(cache_files):
            if i >= limit:
                break

            stat = cache_file.stat()
            size_mb = stat.st_size / (1024 * 1024)
            age_hours = (now - stat.st_mtime) / 3600

            # Extract checksum from filename (format: {checksum}.xml.gz)
            checksum = cache_file.stem  # Removes .xml.gz

            if size_mb >= 1.0:
                size_str = f"{size_mb:.2f} MB"
            else:
                size_kb = stat.st_size / 1024
                size_str = f"{size_kb:.1f} KB"

            if age_hours < 1:
                age_str = f"{age_hours * 60:.0f}m"
            elif age_hours < 24:
                age_str = f"{age_hours:.1f}h"
            else:
                age_days = age_hours / 24
                age_str = f"{age_days:.1f}d"

            # Truncate checksum for display
            checksum_display = f"{checksum[:64]}..." if len(checksum) > 64 else checksum

            click.echo(f"{checksum_display:<70} {size_str:>12} {age_str:>12}")

        if len(cache_files) > limit:
            click.echo()
            click.echo(f"Showing {limit} of {len(cache_files)} files. Use --limit to show more.")

    return cache
