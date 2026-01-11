from __future__ import annotations

"""View management commands."""

import json

import click

from chantal.core.config import GlobalConfig

# Click context settings to enable -h as alias for --help
CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


def create_view_group(cli: click.Group) -> click.Group:
    """Create and return the view command group.

    Args:
        cli: Parent CLI group to attach to

    Returns:
        The view command group
    """

    @cli.group(context_settings=CONTEXT_SETTINGS)
    def view() -> None:
        """View management commands.

        Views group multiple repositories into a single virtual repository.
        All repositories in a view must have the same type (rpm or apt).
        """
        pass

    @view.command("list")
    @click.option(
        "--format", "output_format", type=click.Choice(["table", "json"]), default="table"
    )
    @click.pass_context
    def view_list(ctx, output_format):
        """List all configured views."""
        config: GlobalConfig = ctx.obj["config"]

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
    @click.option(
        "--format", "output_format", type=click.Choice(["table", "json"]), default="table"
    )
    @click.pass_context
    def view_show(ctx, name, output_format):
        """Show detailed information about a view."""
        config: GlobalConfig = ctx.obj["config"]

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
                repos_info.append(
                    {
                        "id": repo_id,
                        "name": f"UNKNOWN ({repo_id})",
                        "type": "?",
                        "enabled": False,
                        "packages": 0,
                        "status": "NOT FOUND",
                    }
                )
            else:
                # Try to get package count from database
                try:
                    from chantal.db.connection import DatabaseManager
                    from chantal.db.models import Repository

                    db_manager = DatabaseManager(config.database.url)
                    session = db_manager.get_session()
                    db_repo = session.query(Repository).filter_by(repo_id=repo_config.id).first()
                    pkg_count = len(db_repo.content_items) if db_repo else 0
                    total_packages += pkg_count
                    session.close()
                except Exception:
                    pkg_count = 0

                repos_info.append(
                    {
                        "id": repo_config.id,
                        "name": repo_config.display_name,
                        "type": repo_config.type,
                        "enabled": repo_config.enabled,
                        "packages": pkg_count,
                        "status": "OK",
                    }
                )

        if output_format == "json":
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
            click.echo(
                f"  {info['id']:<30} {info['type']:<6} {enabled_str:<8} {info['packages']:<10} {info['status']}"
            )

        click.echo()
        click.echo("Usage:")
        click.echo(f"  Publish view:          chantal publish view --name {view_config.name}")
        click.echo(
            f"  Create view snapshot:  chantal snapshot create --view {view_config.name} --name YYYY-MM-DD"
        )

    return view
