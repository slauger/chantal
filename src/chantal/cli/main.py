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
from chantal.cli.package_commands import create_package_group
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
    from sqlalchemy.exc import OperationalError

    from chantal.core.stats import (
        format_bytes,
        gather_global_stats,
        gather_repository_stats,
    )
    from chantal.db.connection import DatabaseManager

    config: GlobalConfig = ctx.obj["config"]
    db_manager = DatabaseManager(config.database.url)
    try:
        with db_manager.session() as session:
            if repo_id:
                s = gather_repository_stats(session, repo_id)
                if s is None:
                    click.echo(f"Repository '{repo_id}' not found in the database.", err=True)
                    ctx.exit(1)
                click.echo(f"Statistics for repository: {s['repo_id']} ({s['type']}, {s['mode']})")
                click.echo(f"  Packages: {s['content_items']:,}")
                for ctype, count in sorted(s["by_type"].items()):
                    click.echo(f"    {ctype}: {count:,}")
                click.echo(f"  Snapshots: {s['snapshots']:,}")
                click.echo(f"  Size: {format_bytes(s['pool_bytes'])}")
            else:
                s = gather_global_stats(session)
                click.echo("Global Statistics:")
                click.echo(f"  Total Repositories: {s['repositories']:,}")
                click.echo(f"  Total Packages: {s['content_items']:,}")
                for ctype, count in sorted(s["by_type"].items()):
                    click.echo(f"    {ctype}: {count:,}")
                click.echo(f"  Total Snapshots: {s['snapshots']:,}")
                click.echo(f"  Pool Size on Disk: {format_bytes(s['pool_bytes'])}")
                click.echo(
                    f"  Deduplication: {format_bytes(s['saved_bytes'])} saved "
                    f"({s['dedup_pct']:.0f}%)"
                )
    except OperationalError:
        click.echo("Database not initialized. Run 'chantal db init' first.", err=True)
        ctx.exit(1)


# ============================================================================
# Register Command Groups
@cli.command("schema")
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Write the schema to this file instead of stdout.",
)
def schema(output: Path | None) -> None:
    """Output the JSON Schema for the configuration file.

    The schema is generated from the configuration models and can be used by
    editors (e.g. the VS Code YAML extension) to validate and autocomplete
    config.yaml files.
    """
    import json

    from chantal.core.config import generate_json_schema

    text = json.dumps(generate_json_schema(), indent=2) + "\n"
    if output:
        output.write_text(text, encoding="utf-8")
        click.echo(f"Wrote configuration schema to {output}")
    else:
        click.echo(text, nl=False)


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
create_package_group(cli)


# ============================================================================
# Entry Point
# ============================================================================


def main() -> None:
    """Entry point for CLI."""
    cli(obj={})


if __name__ == "__main__":
    main()
