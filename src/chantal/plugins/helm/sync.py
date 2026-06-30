from __future__ import annotations

"""
Helm chart repository syncer.

This module implements syncing for Helm chart repositories.
"""

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import yaml
from sqlalchemy.orm import Session

from chantal.core.config import ProxyConfig, RepositoryConfig, SSLConfig
from chantal.core.downloader import DownloadManager
from chantal.core.output import OutputLevel, SyncOutputter
from chantal.core.storage import StorageManager
from chantal.db.models import ContentItem, Repository, RepositoryFile
from chantal.plugins.helm.models import HelmMetadata

logger = logging.getLogger(__name__)


def normalize_digest(digest: str | None) -> str | None:
    """Return the bare hex of a chart digest, stripping an optional algo prefix.

    Helm ``index.yaml`` digests are bare hex, but some producers (including
    chantal's own generated index, historically) prefix them with ``sha256:``.
    """
    if not digest:
        return None
    return digest.split(":", 1)[1] if ":" in digest else digest


class HelmSyncer:
    """Syncer for Helm chart repositories.

    Syncs charts from Helm repositories by:
    1. Fetching index.yaml
    2. Parsing chart metadata
    3. Filtering charts based on repository config
    4. Downloading chart .tgz files to content-addressed pool
    5. Storing metadata in database as ContentItems
    """

    def __init__(
        self,
        storage: StorageManager,
        config: RepositoryConfig,
        proxy_config: ProxyConfig | None = None,
        ssl_config: SSLConfig | None = None,
        output_level: OutputLevel = OutputLevel.NORMAL,
    ):
        """Initialize Helm syncer.

        Args:
            storage: Storage manager instance
            config: Repository configuration
            proxy_config: Optional proxy configuration
            ssl_config: Optional SSL/TLS configuration
            output_level: Output verbosity level
        """
        self.storage = storage
        self.config = config
        self.proxy_config = proxy_config
        self.ssl_config = ssl_config
        self.output = SyncOutputter(output_level)

        # Setup download manager with all authentication and SSL/TLS configuration
        self.downloader = DownloadManager(
            config=config, proxy_config=proxy_config, ssl_config=ssl_config
        )

        # Backward compatibility
        self.session = self.downloader.session

    def sync_repository(
        self,
        session: Session,
        repository: Repository,
        config: RepositoryConfig,
    ) -> dict:
        """Sync Helm repository.

        Args:
            session: Database session
            repository: Repository model instance
            config: Repository configuration

        Returns:
            dict: Sync statistics
        """
        logger.info(f"Syncing Helm repository: {repository.repo_id}")
        self.output.header(repository.repo_id, "helm", config.feed)

        # Fetch and parse index.yaml
        # Ensure feed URL ends with / for proper urljoin behavior
        feed_url = config.feed if config.feed.endswith("/") else config.feed + "/"
        index_url = urljoin(feed_url, "index.yaml")

        self.output.phase("Downloading index.yaml", number=1)
        index_data = self._fetch_index(index_url, config)

        # Store the upstream index.yaml as a RepositoryFile so mirror mode can
        # republish it. Filtered mode ignores it and regenerates the index from
        # the published charts at publish time. Prune the previous sync's index
        # so the mirror publisher doesn't pick up a stale one.
        index_sha = self._store_index_file(index_url, config, session, repository)
        self._prune_stale_index(session, repository, index_sha)

        # Parse charts from index
        all_charts = self._parse_index(index_data)
        logger.info(f"Found {len(all_charts)} chart versions in index.yaml")
        self.output.info(f"Found {len(all_charts)} chart versions in index.yaml")

        # Apply filters
        filtered_charts = self._apply_filters(all_charts, config)
        logger.info(f"After filtering: {len(filtered_charts)} chart versions")
        self.output.info(f"After filtering: {len(filtered_charts)} chart versions")

        # Download and store charts
        self.output.phase("Downloading charts", number=2)
        stats = {
            "charts_added": 0,
            "charts_updated": 0,
            "charts_skipped": 0,
            "bytes_downloaded": 0,
        }

        self.output.start_progress(len(filtered_charts), "Downloading charts", "charts")

        # ContentItem.sha256 is globally unique. The DB session is
        # autoflush=False, so a query can't see a chart added earlier in this
        # same run; track in-run inserts so a digest-less duplicate links instead
        # of inserting a second row and aborting the sync at commit.
        inserted_by_sha: dict[str, ContentItem] = {}

        for i, chart_entry in enumerate(filtered_charts, 1):
            try:
                # The index.yaml digest is the expected SHA256 of the chart
                # tarball (bare hex, possibly with a 'sha256:' prefix).
                expected_digest = normalize_digest(chart_entry.get("digest"))

                # Check if chart already exists (content-addressed by digest).
                existing = (
                    session.query(ContentItem)
                    .filter_by(content_type="helm", sha256=expected_digest)
                    .first()
                    if expected_digest
                    else None
                )

                if existing:
                    # Chart already exists - link to repository if not already linked
                    chart_name = f"{chart_entry['name']}-{chart_entry['version']}"
                    self.output.already_in_pool(chart_name, chart_entry.get("digest", ""))
                    if repository not in existing.repositories:
                        existing.repositories.append(repository)
                        stats["charts_updated"] += 1
                    else:
                        stats["charts_skipped"] += 1
                    # Progress is advanced once by the finally block below.
                    continue

                # Download chart
                chart_url = chart_entry["urls"][0]  # Use first URL
                if not chart_url.startswith(("http://", "https://")):
                    # Relative URL - make absolute
                    # Ensure feed URL ends with / for proper urljoin behavior
                    feed_url = config.feed if config.feed.endswith("/") else config.feed + "/"
                    chart_url = urljoin(feed_url, chart_url)

                chart_name = f"{chart_entry['name']}-{chart_entry['version']}"
                self.output.downloading(chart_name, 0, i, len(filtered_charts))

                pool_path, sha256, size, filename = self._download_chart(chart_url, config)

                # Verify the downloaded bytes against the digest advertised in
                # index.yaml. A mismatch means the tarball was tampered with or
                # corrupted in transit; reject it (the chart is skipped, never
                # stored or published).
                if expected_digest and sha256 != expected_digest:
                    # The download already content-addressed the bytes into the
                    # pool; remove the orphan if nothing else references it. Use
                    # the actual pool path (the chart url basename is unreliable
                    # for oci:// and signed/query URLs). Consult the in-run dict
                    # too: with autoflush=False a query can't see a chart added
                    # earlier this run that legitimately shares these bytes, so
                    # without it we could delete a blob a committed chart needs.
                    if (
                        sha256 not in inserted_by_sha
                        and not session.query(ContentItem).filter_by(sha256=sha256).first()
                    ):
                        (self.storage.pool_path / pool_path).unlink(missing_ok=True)
                    raise ValueError(
                        f"digest mismatch for {chart_name}: index.yaml advertises "
                        f"{expected_digest}, downloaded content is {sha256} (possible tampering)"
                    )

                # Deduplicate by the actual downloaded content. When index.yaml
                # omits a digest the pre-download check above is skipped, so a
                # re-sync would otherwise try to insert a second ContentItem with
                # the same sha256 and hit the unique constraint (IntegrityError).
                # The in-run dict covers a duplicate added earlier in this same
                # run (the session is autoflush=False, so a query can't see it).
                existing_by_content = inserted_by_sha.get(sha256) or (
                    session.query(ContentItem).filter_by(content_type="helm", sha256=sha256).first()
                )
                if existing_by_content:
                    if repository not in existing_by_content.repositories:
                        existing_by_content.repositories.append(repository)
                        stats["charts_updated"] += 1
                    else:
                        stats["charts_skipped"] += 1
                    continue

                # Create metadata
                metadata = HelmMetadata(**chart_entry)

                # Create ContentItem
                content_item = ContentItem(
                    name=metadata.name,
                    version=metadata.version,
                    sha256=sha256,
                    filename=filename,
                    size_bytes=size,
                    pool_path=str(pool_path),
                    content_type="helm",
                    content_metadata=metadata.model_dump(mode="json"),
                )
                content_item.repositories.append(repository)

                session.add(content_item)
                inserted_by_sha[sha256] = content_item
                stats["charts_added"] += 1
                stats["bytes_downloaded"] += size

                logger.debug(f"Added chart: {metadata.name}-{metadata.version}")
                self.output.downloaded(size / 1024 / 1024)

            except Exception as e:
                logger.error(f"Error syncing chart {chart_entry.get('name')}: {e}")
                self.output.error(f"Error syncing chart {chart_entry.get('name')}: {e}")
                continue
            finally:
                self.output.update_progress()

        self.output.finish_progress()

        session.commit()
        logger.info(f"Sync complete: {stats}")

        self.output.summary(
            charts_added=stats["charts_added"],
            charts_updated=stats["charts_updated"],
            charts_skipped=stats["charts_skipped"],
            total_size_mb=f"{stats['bytes_downloaded'] / 1024 / 1024:.2f} MB",
        )

        return stats

    def _fetch_index(self, url: str, config: RepositoryConfig) -> dict[str, Any]:
        """Fetch and parse index.yaml.

        Args:
            url: Index URL
            config: Repository configuration (for credentials)

        Returns:
            dict: Parsed index.yaml data
        """
        logger.info(f"Fetching index.yaml from {url}")
        self.output.verbose(f"Fetching index.yaml from {url}")

        response = self.session.get(url, timeout=30)
        response.raise_for_status()

        # Handle encoding - response.content is bytes, decode as UTF-8
        # Some index.yaml files may have special chars, ignore errors
        try:
            content = response.content.decode("utf-8")
        except UnicodeDecodeError:
            # Fallback to latin-1 if UTF-8 fails
            content = response.content.decode("latin-1")

        # Remove control characters that YAML doesn't allow
        # Keep tab (\x09), newline (\x0A), carriage return (\x0D)
        import re

        content = re.sub(r"[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F-\x9F]", "", content)

        result: dict[str, Any] = yaml.safe_load(content)
        return result

    def _parse_index(self, index_data: dict) -> list[dict]:
        """Parse chart entries from index.yaml.

        Args:
            index_data: Parsed index.yaml data

        Returns:
            list: List of chart entry dictionaries
        """
        all_charts = []

        entries = index_data.get("entries", {})
        for _chart_name, versions in entries.items():
            for version_entry in versions:
                all_charts.append(version_entry)

        return all_charts

    def _store_index_file(
        self,
        index_url: str,
        config: RepositoryConfig,
        session: Session,
        repository: Repository,
    ) -> str:
        """Download and store index.yaml as RepositoryFile for mirror mode.

        Args:
            index_url: URL to index.yaml
            config: Repository configuration
            session: Database session
            repository: Repository model instance

        Returns:
            The pool SHA256 of the stored index.yaml (used to prune the previous
            sync's index from the repository).
        """
        logger.info("Storing index.yaml as RepositoryFile")

        # Download index.yaml
        response = self.session.get(index_url, timeout=30)
        response.raise_for_status()

        # Write to temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".yaml") as tmp:
            tmp.write(response.content)
            tmp_path = Path(tmp.name)

        try:
            # Add to storage pool
            sha256, pool_path, size_bytes = self.storage.add_repository_file(
                tmp_path, "index.yaml", verify_checksum=True
            )

            # Check if this RepositoryFile already exists
            existing_file = session.query(RepositoryFile).filter_by(sha256=sha256).first()

            if existing_file:
                # File already exists - just link to repository if not already linked
                if repository not in existing_file.repositories:
                    existing_file.repositories.append(repository)
                    session.commit()
                logger.debug(f"index.yaml already exists in pool: {sha256[:16]}...")
            else:
                # Create new RepositoryFile record
                repo_file = RepositoryFile(
                    file_category="metadata",
                    file_type="index",
                    sha256=sha256,
                    pool_path=pool_path,
                    size_bytes=size_bytes,
                    original_path="index.yaml",
                    file_metadata={
                        "checksum_type": "sha256",
                    },
                )
                session.add(repo_file)
                session.commit()

                # Link to repository
                repo_file.repositories.append(repository)
                session.commit()

                logger.info(f"Stored index.yaml in pool: {sha256[:16]}... ({size_bytes} bytes)")

            return sha256

        finally:
            # Clean up temp file
            tmp_path.unlink(missing_ok=True)

    def _prune_stale_index(
        self, session: Session, repository: Repository, current_sha: str
    ) -> None:
        """Unlink index.yaml files from previous syncs.

        On every sync the upstream index.yaml is re-stored; without pruning, each
        changed index accumulates another ``file_type="index"`` link and the
        mirror publisher (which picks the first match) would republish a stale
        index. Unlink any index file whose sha differs from the current one, and
        delete the row when nothing else (another repository or a snapshot) still
        references it so its pool blob is reclaimable.
        """
        removed = 0
        for repo_file in list(repository.repository_files):
            if repo_file.file_category != "metadata" or repo_file.file_type != "index":
                continue
            if repo_file.sha256 == current_sha:
                continue
            repository.repository_files.remove(repo_file)
            removed += 1
            if not repo_file.repositories and not repo_file.snapshots:
                session.delete(repo_file)
        if removed:
            session.commit()
            logger.info(f"Pruned {removed} stale index.yaml file(s) from a previous sync")

    def _apply_filters(self, charts: list[dict], config: RepositoryConfig) -> list[dict]:
        """Apply filters to chart list.

        Args:
            charts: List of chart entries
            config: Repository configuration

        Returns:
            list: Filtered chart list
        """
        filtered = charts

        # Pattern filters
        if config.filters and config.filters.patterns:
            if config.filters.patterns.include:
                import re

                include_patterns = [re.compile(p) for p in config.filters.patterns.include]
                filtered = [
                    c
                    for c in filtered
                    if any(pattern.match(c["name"]) for pattern in include_patterns)
                ]

            if config.filters.patterns.exclude:
                import re

                exclude_patterns = [re.compile(p) for p in config.filters.patterns.exclude]
                filtered = [
                    c
                    for c in filtered
                    if not any(pattern.match(c["name"]) for pattern in exclude_patterns)
                ]

        # Post-processing: only_latest_version
        if config.filters and config.filters.post_processing:
            if config.filters.post_processing.only_latest_version:
                # Keep the newest version of each chart using SemVer ordering
                # (Helm versions are SemVer 2.0.0, not PEP 440).
                from chantal.plugins.helm.version import semver_compare

                by_name: dict[str, dict] = {}
                for chart in filtered:
                    name = chart["name"]
                    current = by_name.get(name)
                    if current is None:
                        by_name[name] = chart
                        continue
                    try:
                        if semver_compare(chart["version"], current["version"]) > 0:
                            by_name[name] = chart
                    except ValueError as e:
                        # Unparseable version: keep the already-stored chart so
                        # the result is deterministic rather than arbitrary.
                        logger.warning(
                            f"Helm version comparison failed for {name} "
                            f"({chart['version']} vs {current['version']}): {e}"
                        )

                filtered = list(by_name.values())

        return filtered

    def _download_chart(self, url: str, config: RepositoryConfig) -> tuple[Path, str, int, str]:
        """Download chart .tgz file to pool.

        Supports both HTTP/HTTPS and OCI registry URLs.

        Args:
            url: Chart URL (http://, https://, or oci://)
            config: Repository configuration (for credentials)

        Returns:
            tuple: (pool_path, sha256, size_bytes, filename) - filename is the
            name the chart was actually pooled/published under (NOT the raw URL
            basename, which is wrong for oci:// and signed/query URLs).
        """
        logger.debug(f"Downloading chart from {url}")

        parsed = urlparse(url)

        if parsed.scheme == "oci":
            return self._download_oci_chart(url, config)
        else:
            return self._download_http_chart(url, config)

    def _download_http_chart(
        self, url: str, config: RepositoryConfig
    ) -> tuple[Path, str, int, str]:
        """Download chart from HTTP/HTTPS URL.

        Args:
            url: HTTP/HTTPS chart URL
            config: Repository configuration

        Returns:
            tuple: (pool_path, sha256, size_bytes, filename)
        """
        response = self.session.get(url, timeout=300, stream=True)
        response.raise_for_status()

        # Download to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".tgz") as tmp:
            for chunk in response.iter_content(chunk_size=8192):
                tmp.write(chunk)
            tmp_path = Path(tmp.name)

        # Strip any query string/fragment from the URL before taking the
        # basename, so a signed/parameterized URL doesn't bake `?token=...` into
        # the pooled and published filename (and the served index.yaml).
        filename = Path(urlparse(url).path).name

        # Add to pool (this calculates SHA256, deduplicates, and moves file)
        sha256, pool_path, size = self.storage.add_package(tmp_path, filename)

        # Clean up temp file
        tmp_path.unlink(missing_ok=True)

        logger.debug(f"Stored chart in pool: {pool_path}")

        return Path(pool_path), sha256, size, filename

    def _download_oci_chart(self, url: str, config: RepositoryConfig) -> tuple[Path, str, int, str]:
        """Download chart from OCI registry.

        Uses helm CLI to pull charts from OCI registries.

        Args:
            url: OCI chart URL (oci://registry/chart:version)
            config: Repository configuration (may contain registry credentials)

        Returns:
            tuple: (pool_path, sha256, size_bytes, filename) - filename is the
            real ``<chart>-<version>.tgz`` helm produced, not the oci:// basename.

        Raises:
            RuntimeError: If helm binary not found or pull fails
        """
        logger.debug(f"Downloading OCI chart from {url}")

        # Create temp directory for helm pull
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Build helm command
            cmd = ["helm", "pull", url, "--destination", str(tmpdir_path)]

            # Pass registry credentials directly so private OCI registries work
            # without relying on a prior `helm registry login` (which would make
            # the mirror depend on ambient host state).
            if config.auth and config.auth.username and config.auth.password:
                cmd += [
                    "--username",
                    config.auth.username,
                    "--password",
                    config.auth.password,
                ]

            try:
                # Execute helm pull
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=300,
                    check=True,
                )
                logger.debug(f"helm pull output: {result.stdout}")

            except FileNotFoundError as e:
                msg = "helm binary not found. Please install Helm CLI to use OCI registry support."
                logger.error(msg)
                raise RuntimeError(msg) from e

            except subprocess.CalledProcessError as e:
                msg = f"helm pull failed: {e.stderr}"
                logger.error(msg)
                raise RuntimeError(msg) from e

            except subprocess.TimeoutExpired as e:
                msg = "helm pull timed out after 300 seconds"
                logger.error(msg)
                raise RuntimeError(msg) from e

            # Find the downloaded .tgz file
            tgz_files = list(tmpdir_path.glob("*.tgz"))
            if not tgz_files:
                msg = f"No .tgz file found after helm pull from {url}"
                logger.error(msg)
                raise RuntimeError(msg)

            if len(tgz_files) > 1:
                logger.warning(f"Multiple .tgz files found, using first: {tgz_files[0]}")

            tmp_path = tgz_files[0]
            filename = tmp_path.name

            # Add to pool (calculates SHA256, deduplicates, moves file)
            sha256, pool_path, size = self.storage.add_package(tmp_path, filename)

            logger.debug(f"Stored OCI chart in pool: {pool_path}")

            return Path(pool_path), sha256, size, filename
