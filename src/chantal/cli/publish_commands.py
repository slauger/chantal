from __future__ import annotations

"""Publishing management commands."""

import json
import shutil
from datetime import datetime
from pathlib import Path

import click

from chantal.core.config import GlobalConfig
from chantal.core.storage import StorageManager
from chantal.db.connection import DatabaseManager
from chantal.db.models import Repository, Snapshot, View, ViewSnapshot
from chantal.plugins.apk.publisher import ApkPublisher
from chantal.plugins.helm.publisher import HelmPublisher
from chantal.plugins.rpm.publisher import RpmPublisher
from chantal.plugins.view_publisher import ViewPublisher

# Click context settings to enable -h as alias for --help
CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


def create_publish_group(cli: click.Group) -> click.Group:
    """Create and return the publish command group.

    Args:
        cli: Parent CLI group to attach to

    Returns:
        The publish command group
    """
    @cli.group(context_settings=CONTEXT_SETTINGS)
    def publish() -> None:
        """Publishing management commands."""
        pass

    @publish.command("repo")
    @click.option("--repo-id", help="Repository ID to publish")
    @click.option("--all", is_flag=True, help="Publish all repositories")
    @click.option("--target", help="Custom target directory (default: from config)")
    @click.pass_context
    def publish_repo(ctx: click.Context, repo_id: str, all: bool, target: str) -> None:
        """Publish repository to target directory.

        Creates hardlinks from package pool to published repository directory.
        Updates repository metadata (repomd.xml, etc.).
        """
        if not repo_id and not all:
            click.echo("Error: Either --repo-id or --all is required")
            raise click.Abort()

        if repo_id and all:
            click.echo("Error: Cannot use both --repo-id and --all")
            raise click.Abort()

        # Check database schema version
        from chantal.cli.db_commands import check_db_schema_version
        check_db_schema_version(ctx)

        config: GlobalConfig = ctx.obj["config"]

        # Initialize managers
        storage = StorageManager(config.storage)
        db_manager = DatabaseManager(config.database.url)
        session = db_manager.get_session()

        try:
            if all:
                click.echo("Publishing all repositories")
                repos_to_publish = config.repositories

                if not repos_to_publish:
                    click.echo("No repositories found in configuration")
                    return

                click.echo(f"Found {len(repos_to_publish)} repositories to publish\n")

                for repo_config in repos_to_publish:
                    click.echo(f"--- Publishing {repo_config.id} ---")
                    _publish_single_repository(session, storage, config, repo_config, target)
                    click.echo()
            else:
                # Publish single repository
                repo_config = next((r for r in config.repositories if r.id == repo_id), None)
                if not repo_config:
                    click.echo(f"Error: Repository '{repo_id}' not found in configuration")
                    raise click.Abort()

                _publish_single_repository(session, storage, config, repo_config, target)
        finally:
            session.close()

    @publish.command("snapshot")
    @click.option("--snapshot", required=True, help="Snapshot name to publish")
    @click.option("--repo-id", help="Repository ID (for repository snapshots)")
    @click.option("--view", help="View name (for view snapshots)")
    @click.option("--target", help="Custom target directory")
    @click.pass_context
    def publish_snapshot(
        ctx: click.Context, snapshot: str, repo_id: str, view: str, target: str
    ) -> None:
        """Publish a specific snapshot (repository or view snapshot).

        Creates hardlinks from package pool to snapshot directory with RPM metadata.
        Perfect for creating immutable snapshots or parallel environments.

        For repository snapshots: --snapshot <name> --repo-id <repo>
        For view snapshots: --snapshot <name> --view <view>
        """
        # Check database schema version
        from chantal.cli.db_commands import check_db_schema_version
        check_db_schema_version(ctx)

        config: GlobalConfig = ctx.obj["config"]

        # Validate: at most one of --repo-id or --view can be specified
        if repo_id and view:
            click.echo("Error: Cannot specify both --repo-id and --view", err=True)
            ctx.exit(1)

        # Initialize database and storage
        db_manager = DatabaseManager(config.database.url)
        storage = StorageManager(config.storage)

        if view:
            # Publish view snapshot
            _publish_view_snapshot(ctx, config, db_manager, storage, view, snapshot, target)
        else:
            # Publish repository snapshot (existing behavior)
            _publish_repository_snapshot(ctx, config, db_manager, storage, repo_id, snapshot, target)

    @publish.command("view")
    @click.option("--name", required=True, help="View name to publish")
    @click.pass_context
    def publish_view(ctx: click.Context, name: str) -> None:
        """Publish a view (combines all repos into one virtual repository).

        Creates a combined repository from all repositories in the view.
        All packages from all repos are included (client decides on conflicts).

        Views are published directly from the configuration file - no database sync needed.

        Examples:
            chantal publish view --name rhel9-complete
            chantal publish view --name rhel9-webserver
        """
        config = ctx.obj["config"]

        # Get view config
        view_config = config.get_view(name)
        if not view_config:
            click.echo(f"Error: View '{name}' not found in configuration", err=True)
            return

        click.echo(f"Publishing view: {name}")
        if view_config.description:
            click.echo(f"Description: {view_config.description}")
        click.echo()

        # Determine target path
        storage = config.storage
        if view_config.publish_path:
            target_path = Path(view_config.publish_path) / "latest"
        else:
            target_path = Path(storage.published_path) / "views" / name / "latest"

        click.echo(f"Target: {target_path}")
        click.echo()

        # Connect to database
        db = DatabaseManager(config.database.url)

        try:
            with db.session() as session:
                # Initialize publisher
                storage_manager = StorageManager(config.storage)
                publisher = ViewPublisher(storage_manager)

                # Publish view from config (no DB view object needed)
                click.echo(f"Collecting packages from {len(view_config.repos)} repositories...")
                package_count = publisher.publish_view_from_config(
                    session, view_config.repos, target_path
                )

                click.echo()
                click.echo("✓ View published successfully!")
                click.echo(f"  Packages: {package_count}")
                click.echo()
                click.echo("Client configuration:")
                click.echo(f"  [view-{name}]")
                click.echo(f"  name=View: {name}")
                click.echo(f"  baseurl=file://{target_path.absolute()}")
                click.echo("  enabled=1")
                click.echo("  gpgcheck=0")

        except ValueError as e:
            click.echo(f"\n✗ Publishing view failed: {e}", err=True)
            click.echo("Hint: Make sure all repositories in the view are synced to database first")
            raise
        except Exception as e:
            click.echo(f"\n✗ Publishing view failed: {e}", err=True)
            raise

    @publish.command("list")
    @click.option(
        "--format",
        "output_format",
        type=click.Choice(["table", "json"]),
        default="table",
        help="Output format",
    )
    @click.pass_context
    def publish_list(ctx: click.Context, output_format: str) -> None:
        """List currently published repositories and snapshots.

        Shows all published snapshots with their paths and metadata.
        """
        config: GlobalConfig = ctx.obj["config"]
        db_manager = DatabaseManager(config.database.url)

        with db_manager.session() as session:
            # Get all published snapshots
            published_snapshots = (
                session.query(Snapshot)
                .filter_by(is_published=True)
                .order_by(Snapshot.created_at.desc())
                .all()
            )

            if output_format == "json":
                result = {"snapshots": []}

                for snapshot in published_snapshots:
                    repo = session.query(Repository).filter_by(id=snapshot.repository_id).first()
                    result["snapshots"].append(
                        {
                            "name": snapshot.name,
                            "repository": repo.repo_id if repo else "Unknown",
                            "path": snapshot.published_path,
                            "packages": snapshot.package_count,
                            "size_bytes": snapshot.total_size_bytes,
                            "created": snapshot.created_at.isoformat(),
                        }
                    )

                click.echo(json.dumps(result, indent=2))
            else:
                # Table format
                click.echo("Currently Published:")
                click.echo()

                if not published_snapshots:
                    click.echo("  No published snapshots found.")
                    click.echo()
                    click.echo("  Publish a snapshot with:")
                    click.echo("    chantal publish snapshot --snapshot <name>")
                    return

                click.echo("Snapshots:")
                click.echo(f"{'Name':<35} {'Repository':<25} {'Path':<50}")
                click.echo("-" * 115)

                for snapshot in published_snapshots:
                    # Get repository info
                    repo = session.query(Repository).filter_by(id=snapshot.repository_id).first()
                    repo_name = repo.repo_id if repo else "Unknown"

                    # Shorten path if needed
                    path = snapshot.published_path
                    if len(path) > 48:
                        path = "..." + path[-45:]

                    click.echo(f"{snapshot.name:<35} {repo_name:<25} {path:<50}")

                click.echo()
                click.echo(f"Total: {len(published_snapshots)} published snapshot(s)")

    @publish.command("unpublish")
    @click.option("--snapshot", required=True, help="Snapshot name to unpublish")
    @click.option("--repo-id", help="Repository ID (optional if snapshot name is unique)")
    @click.pass_context
    def publish_unpublish(ctx: click.Context, snapshot: str, repo_id: str) -> None:
        """Unpublish a snapshot.

        Removes the published directory (hardlinks). Does not delete packages from pool.
        The snapshot remains in the database and can be re-published later.
        """
        config: GlobalConfig = ctx.obj["config"]
        db_manager = DatabaseManager(config.database.url)

        with db_manager.session() as session:
            # Find snapshot
            query = session.query(Snapshot).filter_by(name=snapshot)

            if repo_id:
                # Filter by repository if specified
                repository = session.query(Repository).filter_by(repo_id=repo_id).first()
                if not repository:
                    click.echo(f"Error: Repository '{repo_id}' not found.", err=True)
                    ctx.exit(1)
                query = query.filter_by(repository_id=repository.id)

            snap = query.first()

            if not snap:
                if repo_id:
                    click.echo(
                        f"Error: Snapshot '{snapshot}' not found for repository '{repo_id}'.", err=True
                    )
                else:
                    click.echo(f"Error: Snapshot '{snapshot}' not found.", err=True)
                    click.echo(
                        "Specify --repo-id if multiple repositories have snapshots with this name.",
                        err=True,
                    )
                ctx.exit(1)

            # Check if published
            if not snap.is_published:
                click.echo(f"Snapshot '{snapshot}' is not currently published.", err=True)
                ctx.exit(1)

            # Get repository info
            repository = session.query(Repository).filter_by(id=snap.repository_id).first()

            click.echo(f"Unpublishing snapshot: {snapshot}")
            click.echo(f"Repository: {repository.repo_id}")
            click.echo(f"Path: {snap.published_path}")
            click.echo()

            # Remove published directory
            published_path = Path(snap.published_path)
            if published_path.exists():
                shutil.rmtree(published_path)
                click.echo("✓ Removed published directory")
            else:
                click.echo("⚠ Published directory not found (already deleted?)")

            # Update snapshot metadata
            snap.is_published = False
            snap.published_path = None
            session.commit()

            click.echo()
            click.echo(f"✓ Snapshot '{snapshot}' unpublished successfully!")
            click.echo("Note: Snapshot remains in database and can be re-published with:")
            click.echo(f"  chantal publish snapshot --snapshot {snapshot}")

    return publish


def _publish_single_repository(session, storage, global_config, repo_config, custom_target=None):
    """Helper function to publish a single repository."""
    # Get repository from database
    repository = session.query(Repository).filter_by(repo_id=repo_config.id).first()
    if not repository:
        click.echo(f"Error: Repository '{repo_config.id}' has not been synced yet.", err=True)
        click.echo(f"Run 'chantal repo sync --repo-id {repo_config.id}' first.", err=True)
        return

    # Determine target path
    if custom_target:
        target_path = Path(custom_target)
    else:
        # Use configured published path + repo_id
        target_path = Path(global_config.storage.published_path) / repo_config.id

    click.echo(f"Publishing repository: {repo_config.id}")
    click.echo(f"Target: {target_path}")

    # Initialize publisher based on repository type
    if repo_config.type == "rpm":
        publisher = RpmPublisher(storage=storage)
        # Publish repository
        try:
            publisher.publish_repository(
                session=session, repository=repository, config=repo_config, target_path=target_path
            )
            click.echo("\n✓ Repository published successfully!")
            click.echo(f"  Location: {target_path}")
            click.echo(f"  Packages directory: {target_path}/Packages")
            click.echo(f"  Metadata directory: {target_path}/repodata")
        except Exception as e:
            click.echo(f"\n✗ Publishing failed: {e}", err=True)
            raise
    elif repo_config.type == "helm":
        publisher = HelmPublisher(storage=storage)
        # Publish repository
        try:
            publisher.publish_repository(
                session=session, repository=repository, config=repo_config, target_path=target_path
            )
            click.echo("\n✓ Helm repository published successfully!")
            click.echo(f"  Location: {target_path}")
            click.echo(f"  Chart files: {target_path}/*.tgz")
            click.echo(f"  Index file: {target_path}/index.yaml")
        except Exception as e:
            click.echo(f"\n✗ Publishing failed: {e}", err=True)
            raise
    elif repo_config.type == "apk":
        publisher = ApkPublisher(storage=storage)
        # Publish repository
        try:
            publisher.publish_repository(
                session=session, repository=repository, config=repo_config, target_path=target_path
            )
            apk_config = repo_config.apk
            arch_path = (
                target_path / apk_config.branch / apk_config.repository / apk_config.architecture
            )
            click.echo("\n✓ APK repository published successfully!")
            click.echo(f"  Location: {target_path}")
            click.echo(f"  Package directory: {arch_path}")
            click.echo(f"  Index file: {arch_path}/APKINDEX.tar.gz")
        except Exception as e:
            click.echo(f"\n✗ Publishing failed: {e}", err=True)
            raise
    else:
        click.echo(f"Error: Unsupported repository type: {repo_config.type}")
        return


def _publish_repository_snapshot(
    ctx: click.Context,
    config: GlobalConfig,
    db_manager: DatabaseManager,
    storage: StorageManager,
    repo_id: str,
    snapshot: str,
    target: str,
) -> None:
    """Publish a repository snapshot."""
    with db_manager.session() as session:
        # Get snapshot from database
        query = session.query(Snapshot).filter_by(name=snapshot)

        if repo_id:
            # Filter by repository if specified
            repository = session.query(Repository).filter_by(repo_id=repo_id).first()
            if not repository:
                click.echo(f"Error: Repository '{repo_id}' not found.", err=True)
                ctx.exit(1)
            query = query.filter_by(repository_id=repository.id)

        snap = query.first()

        if not snap:
            if repo_id:
                click.echo(
                    f"Error: Snapshot '{snapshot}' not found for repository '{repo_id}'.", err=True
                )
            else:
                click.echo(f"Error: Snapshot '{snapshot}' not found.", err=True)
                click.echo(
                    "Specify --repo-id if multiple repositories have snapshots with this name.",
                    err=True,
                )
            ctx.exit(1)

        # Get repository
        repository = session.query(Repository).filter_by(id=snap.repository_id).first()

        # Find repository config
        repo_config = None
        for rc in config.repositories:
            if rc.id == repository.repo_id:
                repo_config = rc
                break

        if not repo_config:
            click.echo(
                f"Error: Repository configuration '{repository.repo_id}' not found in config.",
                err=True,
            )
            ctx.exit(1)

        # Determine target path
        if target:
            target_path = Path(target)
        else:
            # Default: published_path/snapshots/<repo-id>/<snapshot-name>
            target_path = (
                Path(config.storage.published_path) / "snapshots" / repository.repo_id / snapshot
            )

        click.echo(f"Publishing snapshot: {snapshot}")
        click.echo(f"Repository: {repository.repo_id}")
        click.echo(f"Target: {target_path}")
        click.echo(f"Packages: {snap.package_count}")
        click.echo()

        # Initialize publisher based on repository type
        if repo_config.type == "rpm":
            publisher = RpmPublisher(storage=storage)
        else:
            click.echo(f"Error: Unsupported repository type: {repo_config.type}", err=True)
            ctx.exit(1)

        # Publish snapshot
        try:
            publisher.publish_snapshot(
                session=session,
                snapshot=snap,
                repository=repository,
                config=repo_config,
                target_path=target_path,
            )

            # Update snapshot metadata
            snap.is_published = True
            snap.published_path = str(target_path)
            session.commit()

            click.echo()
            click.echo("✓ Snapshot published successfully!")
            click.echo(f"  Location: {target_path}")
            click.echo(f"  Packages directory: {target_path}/Packages")
            click.echo(f"  Metadata directory: {target_path}/repodata")
            click.echo()
            click.echo("Configure your package manager:")
            click.echo(f"  [rhel9-baseos-snapshot-{snapshot}]")
            click.echo(f"  name=RHEL 9 BaseOS Snapshot {snapshot}")
            click.echo(f"  baseurl=file://{target_path}")
            click.echo("  enabled=1")
            click.echo("  gpgcheck=0")

        except Exception as e:
            click.echo(f"\n✗ Publishing failed: {e}", err=True)
            raise


def _publish_view_snapshot(
    ctx: click.Context,
    config: GlobalConfig,
    db_manager: DatabaseManager,
    storage: StorageManager,
    view_name: str,
    snapshot_name: str,
    target: str,
) -> None:
    """Publish a view snapshot."""
    with db_manager.session() as session:
        # Get view from database
        view = session.query(View).filter_by(name=view_name).first()
        if not view:
            click.echo(f"Error: View '{view_name}' not found in database.", err=True)
            click.echo("Run 'chantal view list' to see available views.", err=True)
            ctx.exit(1)

        # Get view snapshot from database
        view_snapshot = (
            session.query(ViewSnapshot).filter_by(view_id=view.id, name=snapshot_name).first()
        )

        if not view_snapshot:
            click.echo(
                f"Error: View snapshot '{snapshot_name}' not found for view '{view_name}'.",
                err=True,
            )
            click.echo("Run 'chantal snapshot list' to see available snapshots.", err=True)
            ctx.exit(1)

        # Determine target path
        if target:
            target_path = Path(target)
        else:
            # Default: published_path/views/<view-name>/snapshots/<snapshot-name>
            target_path = (
                Path(config.storage.published_path)
                / "views"
                / view_name
                / "snapshots"
                / snapshot_name
            )

        click.echo(f"Publishing view snapshot: {snapshot_name}")
        click.echo(f"View: {view_name}")
        click.echo(f"Target: {target_path}")
        click.echo(f"Packages: {view_snapshot.package_count}")
        click.echo()

        # Initialize view publisher
        publisher = ViewPublisher(storage)

        # Publish view snapshot
        try:
            publisher.publish_view_snapshot(
                session=session, view_snapshot=view_snapshot, target_path=target_path
            )

            # Update view snapshot metadata
            view_snapshot.is_published = True
            view_snapshot.published_at = datetime.utcnow()
            view_snapshot.published_path = str(target_path)
            session.commit()

            click.echo()
            click.echo("✓ View snapshot published successfully!")
            click.echo(f"  Location: {target_path}")
            click.echo(f"  Packages directory: {target_path}/Packages")
            click.echo(f"  Metadata directory: {target_path}/repodata")
            click.echo()
            click.echo("Configure your package manager:")
            click.echo(f"  [view-{view_name}-snapshot-{snapshot_name}]")
            click.echo(f"  name=View {view_name} Snapshot {snapshot_name}")
            click.echo(f"  baseurl=file://{target_path}")
            click.echo("  enabled=1")
            click.echo("  gpgcheck=0")

        except Exception as e:
            click.echo(f"\n✗ Publishing failed: {e}", err=True)
            raise
