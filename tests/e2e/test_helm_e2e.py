"""End-to-end sync->publish test for the Helm plugin."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.e2e


def _build_helm_upstream(root: Path) -> None:
    """Create a minimal Helm chart repository (index.yaml + one chart)."""
    root.mkdir(parents=True, exist_ok=True)
    chart = b"dummy helm chart tgz payload" * 8
    (root / "demo-0.1.0.tgz").write_bytes(chart)
    index = {
        "apiVersion": "v1",
        "entries": {
            "demo": [
                {
                    "name": "demo",
                    "version": "0.1.0",
                    "digest": hashlib.sha256(chart).hexdigest(),
                    "urls": ["demo-0.1.0.tgz"],
                }
            ]
        },
        "generated": "2026-01-01T00:00:00Z",
    }
    (root / "index.yaml").write_text(yaml.safe_dump(index), encoding="utf-8")


def test_helm_sync_and_publish(tmp_path, serve, chantal_env):
    upstream = tmp_path / "upstream"
    _build_helm_upstream(upstream)
    base_url = serve(upstream)

    chantal_env.write_config(
        {
            "id": "demo-helm",
            "name": "Demo Helm",
            "type": "helm",
            "feed": base_url,
            "enabled": True,
            "mode": "filtered",
        }
    )

    target = chantal_env.sync_and_publish("demo-helm")

    # The chart was downloaded into the pool and published.
    assert list(target.rglob("demo-0.1.0.tgz")), "published chart .tgz not found"

    # A regenerated index.yaml lists the chart.
    indexes = list(target.rglob("index.yaml"))
    assert indexes, "published index.yaml not found"
    index = yaml.safe_load(indexes[0].read_text())
    assert "demo" in index.get("entries", {})
