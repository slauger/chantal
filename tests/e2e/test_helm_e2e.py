"""End-to-end sync->publish test for the Helm plugin."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.e2e, pytest.mark.helm]


def _build_helm_upstream(root: Path, revision: int = 1) -> None:
    """Create a minimal Helm chart repository (index.yaml + one chart).

    ``revision`` is woven into the chart payload (and thus its digest) so calling
    this twice models an upstream that repackaged demo 0.1.0 with new bytes — a
    fresh ContentItem sharing the published ``demo-0.1.0.tgz`` filename.
    """
    root.mkdir(parents=True, exist_ok=True)
    chart = b"dummy helm chart tgz payload" * 8 + f" rev{revision}".encode()
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


def test_helm_resync_does_not_duplicate_chart(tmp_path, serve, chantal_env):
    """Re-syncing a repackaged demo 0.1.0 must leave exactly one index entry.

    When upstream repackages a chart (same name+version, new digest), the stale
    ContentItem must not stay associated and get republished: the regenerated
    index.yaml would then list demo 0.1.0 twice and the pool would grow unbounded.
    """
    upstream = tmp_path / "upstream"
    _build_helm_upstream(upstream, revision=1)
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

    chantal_env.sync_and_publish("demo-helm")

    # Upstream repackages demo 0.1.0 with new bytes (fresh digest).
    _build_helm_upstream(upstream, revision=2)
    target = chantal_env.sync_and_publish("demo-helm")

    index = yaml.safe_load(next(iter(target.rglob("index.yaml"))).read_text())
    demo_entries = index.get("entries", {}).get("demo", [])
    assert len(demo_entries) == 1, f"re-sync left duplicate demo entries: {demo_entries}"
    charts = list(target.rglob("demo-0.1.0.tgz"))
    assert len(charts) == 1, f"re-sync published duplicate chart files: {charts}"
