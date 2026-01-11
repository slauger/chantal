from __future__ import annotations

"""Content management commands."""

import csv
import json
import sys

import click

from chantal.core.config import GlobalConfig
from chantal.db.connection import DatabaseManager
from chantal.db.models import ContentItem, Repository, Snapshot

# Click context settings to enable -h as alias for --help
CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


def create_content_group(cli: click.Group) -> click.Group:
    """Create and return the content command group.

    Args:
        cli: Parent CLI group to attach to

    Returns:
        The content command group
    """

    @cli.group(context_settings=CONTEXT_SETTINGS)
    def content() -> None:
        """Content management commands (works with all content types: RPM, Helm, APT, etc.)."""
        pass

    @content.command("list")
    @click.option("--repo-id", help="Filter by repository ID")
    @click.option("--snapshot-id", help="Filter by snapshot ID")
    @click.option("--view", "view_name", help="Filter by view name")
    @click.option(
        "--type",
        "content_type",
        type=click.Choice(["rpm", "helm", "apt"]),
        help="Filter by content type",
    )
    @click.option("--limit", type=int, default=100, help="Limit number of results")
    @click.option(
        "--format",
        "output_format",
        type=click.Choice(["table", "json", "csv"]),
        default="table",
        help="Output format",
    )
    @click.pass_context
    def content_list(
        ctx: click.Context,
        repo_id: str,
        snapshot_id: str,
        view_name: str,
        content_type: str,
        limit: int,
        output_format: str,
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
            click.echo(
                "Error: Only one of --repo-id, --snapshot-id, or --view can be specified.", err=True
            )
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
                writer = csv.writer(sys.stdout)
                writer.writerow(["Name", "Version", "Type", "Arch", "Size (bytes)", "SHA256"])
                for item in items:
                    arch = (
                        item.content_metadata.get("arch", "-")
                        if item.content_metadata and item.content_type == "rpm"
                        else "-"
                    )
                    writer.writerow(
                        [
                            item.name,
                            item.version,
                            item.content_type,
                            arch,
                            item.size_bytes,
                            item.sha256,
                        ]
                    )

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
                types_present = {item.content_type for item in items}
                has_arch = "rpm" in types_present

                # Dynamic column headers
                if has_arch:
                    click.echo(
                        f"{'Name':<35} {'Version':<20} {'Type':<6} {'Arch':<10} {'Size':>12}"
                    )
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
                        click.echo(
                            f"{name:<35} {item.version:<20} {item.content_type:<6} {arch:<10} {size_str:>12}"
                        )
                    else:
                        click.echo(
                            f"{name:<35} {item.version:<20} {item.content_type:<6} {size_str:>12}"
                        )

                click.echo()
                click.echo(f"Total: {len(items)} item(s)")

    @content.command("search")
    @click.argument("query")
    @click.option("--repo-id", help="Search in specific repository only")
    @click.option("--snapshot-id", help="Search in specific snapshot only")
    @click.option("--view", "view_name", help="Search in specific view only")
    @click.option(
        "--type",
        "content_type",
        type=click.Choice(["rpm", "helm", "apt"]),
        help="Filter by content type",
    )
    @click.option(
        "--format",
        "output_format",
        type=click.Choice(["table", "json"]),
        default="table",
        help="Output format",
    )
    @click.pass_context
    def content_search(
        ctx: click.Context,
        query: str,
        repo_id: str,
        snapshot_id: str,
        view_name: str,
        content_type: str,
        output_format: str,
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
            click.echo(
                "Error: Only one of --repo-id, --snapshot-id, or --view can be specified.", err=True
            )
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
                    items_query = items_query.filter(
                        ContentItem.repositories.any(Repository.repo_id.in_(repo_ids))
                    )
                scope_desc = f"view '{view_name}'"

            # Apply name/version search (case-insensitive)
            search_pattern = query.replace("*", "%")
            items_query = items_query.filter(
                (ContentItem.name.ilike(f"%{search_pattern}%"))
                | (ContentItem.version.ilike(f"%{search_pattern}%"))
            )

            # Filter by content type if specified
            if content_type:
                items_query = items_query.filter_by(content_type=content_type)

            # Get results
            items = items_query.all()

            if output_format == "json":
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
                    click.echo("  Try broadening your search query.")
                    return

                click.echo(
                    f"{'Repository':<25} {'Name':<30} {'Version':<15} {'Type':<6} {'Size':>10}"
                )
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

                    click.echo(
                        f"{repo_display:<25} {name:<30} {item.version:<15} {item.content_type:<6} {size_str:>10}"
                    )

                click.echo()
                click.echo(f"Found: {len(items)} item(s)")

    @content.command("show")
    @click.argument("identifier")
    @click.option(
        "--format",
        "output_format",
        type=click.Choice(["table", "json"]),
        default="table",
        help="Output format",
    )
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
            if len(identifier) == 64 and all(c in "0123456789abcdef" for c in identifier.lower()):
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
                                click.echo(
                                    f"  App Version:  {item.content_metadata['app_version']}"
                                )
                            if "description" in item.content_metadata:
                                click.echo(
                                    f"  Description:  {item.content_metadata['description']}"
                                )

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

    return content
