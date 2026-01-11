from __future__ import annotations

"""
Central download manager for all repository types.

This module provides an abstraction layer for downloading files from remote
repositories, enabling consistent handling of authentication, SSL/TLS, proxies,
retries, and checksums across all plugin types.
"""

import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import Path

import requests

from chantal.core.config import (
    AuthConfig,
    DownloadConfig,
    ProxyConfig,
    RepositoryConfig,
    SSLConfig,
)


@dataclass
class DownloadTask:
    """Single file download task."""

    url: str
    dest: Path
    expected_sha256: str | None = None


class DownloadBackend:
    """Abstract download backend."""

    def download_file(self, url: str, dest: Path, expected_sha256: str | None = None) -> Path:
        """Download a single file.

        Args:
            url: Source URL
            dest: Destination path
            expected_sha256: Expected SHA256 checksum (optional)

        Returns:
            Path to downloaded file

        Raises:
            requests.RequestException: On download errors
            ValueError: On checksum mismatch
        """
        raise NotImplementedError

    def download_batch(self, tasks: list[DownloadTask]) -> list[Path]:
        """Download multiple files.

        Args:
            tasks: List of download tasks

        Returns:
            List of paths to downloaded files

        Raises:
            requests.RequestException: On download errors
            ValueError: On checksum mismatch
        """
        raise NotImplementedError


class RequestsBackend(DownloadBackend):
    """Download backend using requests library."""

    def __init__(
        self,
        config: RepositoryConfig,
        download_config: DownloadConfig | None = None,
        proxy_config: ProxyConfig | None = None,
        ssl_config: SSLConfig | None = None,
    ):
        """Initialize requests backend.

        Args:
            config: Repository configuration
            download_config: Download configuration (timeout, retries, etc.)
            proxy_config: Optional proxy configuration
            ssl_config: Optional SSL/TLS configuration
        """
        self.config = config
        self.download_config = download_config or DownloadConfig()
        self.proxy_config = proxy_config
        self.ssl_config = ssl_config
        self._temp_ca_file: str | None = None

        # Setup HTTP session
        self.session = self._setup_session()

    def _setup_session(self) -> requests.Session:
        """Setup requests session with auth, SSL, and proxy configuration.

        Returns:
            Configured requests session
        """
        session = requests.Session()

        # Setup proxy
        if self.proxy_config:
            proxies = {}
            if self.proxy_config.http_proxy:
                proxies["http"] = self.proxy_config.http_proxy
            if self.proxy_config.https_proxy:
                proxies["https"] = self.proxy_config.https_proxy
            session.proxies.update(proxies)

            # Basic auth for proxy if needed
            if self.proxy_config.username and self.proxy_config.password:
                session.auth = (self.proxy_config.username, self.proxy_config.password)

        # Setup SSL/TLS verification
        if self.ssl_config:
            if not self.ssl_config.verify:
                # Disable SSL verification (not recommended)
                session.verify = False
            elif self.ssl_config.ca_cert:
                # Use inline CA certificate - write to temp file
                ca_file = tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False)
                ca_file.write(self.ssl_config.ca_cert)
                ca_file.flush()
                ca_file.close()
                session.verify = ca_file.name
                self._temp_ca_file = ca_file.name  # Store for cleanup
            elif self.ssl_config.ca_bundle:
                # Use CA bundle file path
                session.verify = self.ssl_config.ca_bundle

            # Setup client certificate for mTLS if configured
            if self.ssl_config.client_cert:
                if self.ssl_config.client_key:
                    session.cert = (
                        self.ssl_config.client_cert,
                        self.ssl_config.client_key,
                    )
                else:
                    session.cert = self.ssl_config.client_cert

        # Setup repository authentication
        if self.config.auth:
            self._setup_auth(session, self.config.auth)

        return session

    def _setup_auth(self, session: requests.Session, auth: AuthConfig) -> None:
        """Setup authentication on session.

        Args:
            session: Requests session
            auth: Authentication configuration
        """
        if auth.type == "client_cert":
            # Client certificate authentication (RHEL CDN)
            if auth.cert_file and auth.key_file:
                # Specific cert/key files provided
                session.cert = (auth.cert_file, auth.key_file)
                print("Using client certificate authentication")
            elif auth.cert_dir:
                # Find cert/key in directory (RHEL entitlement pattern)
                cert_dir = Path(auth.cert_dir)
                if cert_dir.exists():
                    # Find first .pem certificate (not -key.pem)
                    certs = [f for f in cert_dir.glob("*.pem") if not f.name.endswith("-key.pem")]
                    if certs:
                        cert_file = certs[0]
                        # Look for corresponding key file
                        key_file = cert_dir / cert_file.name.replace(".pem", "-key.pem")
                        if key_file.exists():
                            session.cert = (str(cert_file), str(key_file))
                            print(f"Using client certificate: {cert_file.name}")
                        else:
                            print(f"Warning: Key file not found for {cert_file.name}")

        elif auth.type == "basic":
            # HTTP Basic authentication
            if auth.username and auth.password:
                session.auth = (auth.username, auth.password)
                print(f"Using HTTP Basic authentication (user: {auth.username})")

        elif auth.type == "bearer":
            # Bearer token authentication
            if auth.token:
                session.headers.update({"Authorization": f"Bearer {auth.token}"})
                print("Using Bearer token authentication")

        elif auth.type == "custom":
            # Custom HTTP headers
            if auth.headers:
                session.headers.update(auth.headers)
                print("Using custom HTTP headers")

    def download_file(self, url: str, dest: Path, expected_sha256: str | None = None) -> Path:
        """Download a single file with retry and checksum verification.

        Args:
            url: Source URL
            dest: Destination path
            expected_sha256: Expected SHA256 checksum (optional)

        Returns:
            Path to downloaded file

        Raises:
            requests.RequestException: On download errors
            ValueError: On checksum mismatch
        """
        # Create parent directory if needed
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Download with retries
        last_exception = None
        for attempt in range(self.download_config.retry_attempts + 1):
            try:
                # Stream download
                response = self.session.get(url, stream=True, timeout=self.download_config.timeout)
                response.raise_for_status()

                # Download to temporary file first
                with tempfile.NamedTemporaryFile(
                    delete=False, dir=dest.parent, suffix=dest.suffix
                ) as tmp_file:
                    tmp_path = Path(tmp_file.name)

                    # Download with progress
                    sha256_hash = hashlib.sha256()
                    for chunk in response.iter_content(chunk_size=65536):
                        tmp_file.write(chunk)
                        if self.download_config.verify_checksum and expected_sha256:
                            sha256_hash.update(chunk)

                    tmp_file.flush()

                # Verify checksum if requested
                if self.download_config.verify_checksum and expected_sha256:
                    actual_sha256 = sha256_hash.hexdigest()
                    if actual_sha256 != expected_sha256:
                        tmp_path.unlink()
                        raise ValueError(
                            f"Checksum mismatch for {url}: "
                            f"expected {expected_sha256}, got {actual_sha256}"
                        )

                # Move to final destination
                tmp_path.replace(dest)
                return dest

            except (requests.RequestException, ValueError) as e:
                last_exception = e
                if attempt < self.download_config.retry_attempts:
                    print(
                        f"Download failed (attempt {attempt + 1}/"
                        f"{self.download_config.retry_attempts + 1}): {e}"
                    )
                    continue
                else:
                    # Final attempt failed
                    raise

        # Should not reach here, but just in case
        if last_exception:
            raise last_exception
        raise RuntimeError(f"Download failed for {url}")

    def download_batch(self, tasks: list[DownloadTask]) -> list[Path]:
        """Download multiple files sequentially.

        Args:
            tasks: List of download tasks

        Returns:
            List of paths to downloaded files

        Raises:
            requests.RequestException: On download errors
            ValueError: On checksum mismatch
        """
        results = []
        for task in tasks:
            result = self.download_file(task.url, task.dest, task.expected_sha256)
            results.append(result)
        return results

    def __del__(self) -> None:
        """Cleanup temporary files."""
        if self._temp_ca_file:
            try:
                Path(self._temp_ca_file).unlink()
            except Exception:
                pass


class DownloadManager:
    """Central download manager for all repository types."""

    def __init__(
        self,
        config: RepositoryConfig,
        download_config: DownloadConfig | None = None,
        proxy_config: ProxyConfig | None = None,
        ssl_config: SSLConfig | None = None,
        backend: str = "requests",
    ):
        """Initialize download manager.

        Args:
            config: Repository configuration
            download_config: Download configuration (timeout, retries, etc.)
            proxy_config: Optional proxy configuration (overrides repo config)
            ssl_config: Optional SSL/TLS configuration (overrides repo config)
            backend: Download backend to use (default: "requests")

        Raises:
            ValueError: If backend is not supported
        """
        self.config = config
        self.download_config = download_config or DownloadConfig()
        self.backend_impl = self._init_backend(
            backend, config, download_config, proxy_config, ssl_config
        )

    def _init_backend(
        self,
        backend: str,
        config: RepositoryConfig,
        download_config: DownloadConfig | None,
        proxy_config: ProxyConfig | None,
        ssl_config: SSLConfig | None,
    ) -> DownloadBackend:
        """Initialize download backend.

        Args:
            backend: Backend name
            config: Repository configuration
            download_config: Download configuration
            proxy_config: Optional proxy configuration
            ssl_config: Optional SSL/TLS configuration

        Returns:
            Download backend instance

        Raises:
            ValueError: If backend is not supported
        """
        if backend == "requests":
            return RequestsBackend(config, download_config, proxy_config, ssl_config)
        elif backend == "aria2c":
            raise NotImplementedError("aria2c backend not yet implemented")
        else:
            raise ValueError(f"Unknown download backend: {backend}")

    def download_file(self, url: str, dest: Path, expected_sha256: str | None = None) -> Path:
        """Download a single file.

        Args:
            url: Source URL
            dest: Destination path
            expected_sha256: Expected SHA256 checksum (optional)

        Returns:
            Path to downloaded file

        Raises:
            requests.RequestException: On download errors
            ValueError: On checksum mismatch
        """
        return self.backend_impl.download_file(url, dest, expected_sha256)

    def download_batch(self, tasks: list[DownloadTask]) -> list[Path]:
        """Download multiple files.

        Args:
            tasks: List of download tasks

        Returns:
            List of paths to downloaded files

        Raises:
            requests.RequestException: On download errors
            ValueError: On checksum mismatch
        """
        return self.backend_impl.download_batch(tasks)

    @property
    def session(self) -> requests.Session:
        """Get underlying requests session (for compatibility).

        Returns:
            Requests session

        Raises:
            AttributeError: If backend doesn't use requests
        """
        if isinstance(self.backend_impl, RequestsBackend):
            return self.backend_impl.session
        raise AttributeError("Current backend does not provide a requests session")
