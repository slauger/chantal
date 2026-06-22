"""
Shared harness for end-to-end sync->publish tests.

These tests build a minimal upstream repository (one package) with pure Python,
serve it over a local HTTP server, then drive the real `chantal` CLI through
`db init` -> `repo sync` -> `publish repo` against a temporary SQLite database,
and assert on the published output.

No native build tools and no committed binaries are required: the "package"
files are dummy byte strings whose checksums are computed and embedded in the
generated metadata, which is exactly what Chantal verifies during sync.
"""

from __future__ import annotations

import functools
import http.server
import socketserver
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def serve() -> Callable[[Path], str]:
    """Serve a directory over HTTP on localhost; returns the base URL.

    Multiple directories can be served; all servers are shut down on teardown.
    """
    servers: list[socketserver.TCPServer] = []

    def _serve(directory: Path) -> str:
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
        httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        servers.append(httpd)
        return f"http://127.0.0.1:{port}"

    yield _serve

    for httpd in servers:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture
def chantal_env(tmp_path: Path):
    """Provide a configured Chantal environment driver.

    Returns a helper object with:
    - ``write_config(repo)``: write a config.yaml with sqlite + temp storage
      and a single repository definition, then run ``db init``.
    - ``run(*args)``: run the chantal CLI with ``--config`` and return the
      CompletedProcess (asserting success).
    - ``published`` / ``pool``: the published and pool target paths.
    """

    class _Env:
        def __init__(self) -> None:
            self.config_path = tmp_path / "config.yaml"
            self.db_path = tmp_path / "chantal.db"
            self.base = tmp_path / "data"
            self.pool = self.base / "pool"
            self.published = tmp_path / "published"

        def run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
            cmd = [
                sys.executable,
                "-m",
                "chantal.cli.main",
                "--config",
                str(self.config_path),
                *args,
            ]
            # Echo the command and its output so the CI log shows what the
            # end-to-end test actually does (run pytest with -s to stream it).
            print(f"\n$ chantal {' '.join(args)}", flush=True)
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.stdout:
                print(result.stdout, end="", flush=True)
            if result.stderr:
                print(result.stderr, end="", flush=True)
            if check and result.returncode != 0:
                raise AssertionError(f"command failed ({' '.join(args)}): rc={result.returncode}")
            return result

        def write_config(self, repo: dict, extra: dict | None = None) -> None:
            config = {
                "database": {"url": f"sqlite:///{self.db_path}"},
                "storage": {
                    "base_path": str(self.base),
                    "pool_path": str(self.pool),
                    "published_path": str(self.published),
                },
                "repositories": [repo],
            }
            if extra:
                config.update(extra)
            self.config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
            self.run("db", "init")

        def sync_and_publish(self, repo_id: str) -> Path:
            """Run sync + publish for repo_id; return the published target dir."""
            self.run("repo", "sync", "--repo-id", repo_id, "-v")
            target = self.published / repo_id
            self.run("publish", "repo", "--repo-id", repo_id, "--target", str(target))
            self._print_tree(target)
            return target

        def _print_tree(self, target: Path) -> None:
            print(f"\n=== published tree: {target} ===", flush=True)
            for path in sorted(target.rglob("*")):
                if path.is_file():
                    print(
                        f"  {path.relative_to(target)}  ({path.stat().st_size} bytes)", flush=True
                    )

    return _Env()
