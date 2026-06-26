"""Tests for the atomic staged_publish context manager.

A failed publish must never corrupt or remove the existing published repository;
a successful publish replaces it wholesale.
"""

from __future__ import annotations

import pytest

from chantal.cli.publish_commands import staged_publish


def _leftovers(parent):
    """Staging/backup helper directories that must not be left behind."""
    return [p.name for p in parent.iterdir() if p.name.startswith(".")]


def test_successful_publish_into_fresh_target(tmp_path):
    target = tmp_path / "repo"
    with staged_publish(target) as stage:
        (stage / "Packages").mkdir()
        (stage / "Packages" / "a.rpm").write_text("new")
    assert (target / "Packages" / "a.rpm").read_text() == "new"
    assert _leftovers(tmp_path) == []  # no .staging/.old residue


def test_failed_publish_into_fresh_target_leaves_no_repo(tmp_path):
    target = tmp_path / "repo"
    with pytest.raises(RuntimeError):
        with staged_publish(target) as stage:
            (stage / "half.rpm").write_text("partial")
            raise RuntimeError("sign failed")
    assert not target.exists()  # the failed publish produced nothing
    assert _leftovers(tmp_path) == []


def test_failed_publish_leaves_existing_repo_untouched(tmp_path):
    target = tmp_path / "repo"
    target.mkdir()
    (target / "old.rpm").write_text("old-content")

    with pytest.raises(RuntimeError):
        with staged_publish(target) as stage:
            (stage / "new.rpm").write_text("new-content")
            raise RuntimeError("publish blew up")

    # The previously-published repo is intact; nothing from the failed run leaked.
    assert (target / "old.rpm").read_text() == "old-content"
    assert not (target / "new.rpm").exists()
    assert _leftovers(tmp_path) == []


def test_successful_republish_replaces_existing_repo(tmp_path):
    target = tmp_path / "repo"
    target.mkdir()
    (target / "old.rpm").write_text("old")

    with staged_publish(target) as stage:
        (stage / "new.rpm").write_text("new")

    # Old content is fully gone, replaced by the new tree.
    assert not (target / "old.rpm").exists()
    assert (target / "new.rpm").read_text() == "new"
    assert _leftovers(tmp_path) == []


def test_swap_failure_restores_existing_repo(tmp_path, monkeypatch):
    """If the final staging->target rename fails, the previous tree is restored."""
    import os as _os

    target = tmp_path / "repo"
    target.mkdir()
    (target / "old.rpm").write_text("old")

    real_replace = _os.replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        # First call moves target -> backup; second (staging -> target) fails.
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("simulated rename failure")
        return real_replace(src, dst)

    monkeypatch.setattr("chantal.cli.publish_commands.os.replace", flaky_replace)

    with pytest.raises(OSError, match="simulated rename failure"):
        with staged_publish(target) as stage:
            (stage / "new.rpm").write_text("new")

    # The previous published tree is back; nothing half-swapped.
    assert (target / "old.rpm").read_text() == "old"
    assert not (target / "new.rpm").exists()
