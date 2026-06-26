"""Helm: dedup repackaged charts at publish, and pass OCI registry credentials."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from chantal.core.config import AuthConfig, RepositoryConfig
from chantal.db.models import ContentItem
from chantal.plugins.helm.publisher import HelmPublisher
from chantal.plugins.helm.sync import HelmSyncer


def _chart(item_id: int, sha: str, filename="demo-1.0.0.tgz") -> ContentItem:
    c = ContentItem(
        content_type="helm",
        name="demo",
        version="1.0.0",
        sha256=sha,
        size_bytes=1,
        pool_path=f"{sha[:2]}/{sha[2:4]}/{filename}",
        filename=filename,
        content_metadata={},
    )
    c.id = item_id
    return c


def test_dedup_keeps_highest_id_per_filename():
    """A repackaged chart (same filename, new bytes) must collapse to one entry —
    the most recently synced (highest id), matching the file that wins on disk."""
    older = _chart(1, "a" * 64)
    newer = _chart(2, "b" * 64)
    result = HelmPublisher._dedup_charts_by_filename([older, newer])
    assert len(result) == 1
    assert result[0].sha256 == "b" * 64

    # Distinct filenames are all kept.
    other = _chart(3, "c" * 64, filename="other-2.0.0.tgz")
    result2 = HelmPublisher._dedup_charts_by_filename([older, newer, other])
    assert {c.filename for c in result2} == {"demo-1.0.0.tgz", "other-2.0.0.tgz"}


def test_oci_pull_passes_credentials():
    config = RepositoryConfig(
        id="demo",
        name="Demo",
        type="helm",
        feed="oci://reg.example.com/charts",
        auth=AuthConfig(type="basic", username="user", password="secret"),
    )
    syncer = HelmSyncer(storage=None, config=config)

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        raise subprocess.CalledProcessError(1, cmd, stderr="stop here")

    with patch("chantal.plugins.helm.sync.subprocess.run", side_effect=fake_run):
        try:
            syncer._download_oci_chart("oci://reg.example.com/charts/demo:1.0.0", config)
        except RuntimeError:
            pass  # we only care about the command that was built

    cmd = captured["cmd"]
    assert "--username" in cmd and "user" in cmd
    assert "--password" in cmd and "secret" in cmd
