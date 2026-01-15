from __future__ import annotations

"""
Main CLI entry point for Chantal.

This module provides the Click-based command-line interface for Chantal.
"""

from pathlib import Path

import click

from chantal import __version__

# Import command group factories
from chantal.cli.cache_commands import create_cache_group
from chantal.cli.content_commands import create_content_group
from chantal.cli.db_commands import create_db_group
from chantal.cli.pool_commands import create_pool_group
from chantal.cli.publish_commands import create_publish_group
from chantal.cli.repo_commands import create_repo_group
from chantal.cli.snapshot_commands import create_snapshot_group
from chantal.cli.view_commands import create_view_group
from chantal.core.config import GlobalConfig, load_config

# Click context settings to enable -h as alias for --help
CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


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
def cli(ctx: click.Context, config: Path | None, verbose: bool) -> None:
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


# ============================================================================
# Top-Level Commands
# ============================================================================


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


# ============================================================================
# Register Command Groups
# ============================================================================

# Register all command groups
create_cache_group(cli)
create_db_group(cli)
create_repo_group(cli)
create_snapshot_group(cli)
create_view_group(cli)
create_content_group(cli)
create_pool_group(cli)
create_publish_group(cli)


# ============================================================================
# Entry Point
# ============================================================================


def main() -> None:
    """Entry point for CLI."""
    cli(obj={})


if __name__ == "__main__":
    main()
