"""snapshot diff must distinguish architectures, not collapse by name.

Grouping by name alone reports a per-arch update as a spurious add+remove and
can miss/duplicate updates on multi-arch (and multi-version) repositories.
"""

from __future__ import annotations

from chantal.cli.snapshot_commands import _diff_package_sets
from chantal.db.models import ContentItem


def _pkg(name: str, arch: str, sha: str) -> ContentItem:
    return ContentItem(
        content_type="rpm",
        name=name,
        version="1.0",
        sha256=sha,
        size_bytes=1,
        pool_path=f"{sha[:2]}/{sha[2:4]}/{name}.rpm",
        filename=f"{name}.rpm",
        content_metadata={"arch": arch},
    )


def test_diff_distinguishes_arches():
    a, b, c = "a" * 64, "b" * 64, "c" * 64
    # x86_64 changed (a -> c); i686 unchanged (b in both).
    snap1 = {a: _pkg("foo", "x86_64", a), b: _pkg("foo", "i686", b)}
    snap2 = {c: _pkg("foo", "x86_64", c), b: _pkg("foo", "i686", b)}

    added, removed, updated = _diff_package_sets(snap1, snap2)

    # Name-only grouping would leak the x86_64 change into added+removed; per-arch
    # grouping reports it as a single update and the i686 as unchanged.
    assert added == []
    assert removed == []
    assert len(updated) == 1
    old, new = updated[0]
    assert old.content_metadata["arch"] == "x86_64"
    assert old.sha256 == a and new.sha256 == c


def test_diff_added_and_removed():
    a, b = "a" * 64, "b" * 64
    snap1 = {a: _pkg("foo", "x86_64", a)}
    snap2 = {b: _pkg("bar", "x86_64", b)}

    added, removed, updated = _diff_package_sets(snap1, snap2)

    assert [p.name for p in added] == ["bar"]
    assert [p.name for p in removed] == ["foo"]
    assert updated == []
