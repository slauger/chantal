from __future__ import annotations

"""
Repository / database statistics computed from the live database.

Used by ``chantal stats`` and ``chantal db stats`` so both report real numbers
instead of placeholders.
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Query, Session

from chantal.db.models import (
    ContentItem,
    Repository,
    RepositoryFile,
    Snapshot,
    repository_content_items,
    snapshot_content_items,
)


def unreferenced_content_items(session: Session) -> Query[ContentItem]:
    """Query for ContentItems linked to no repository and no snapshot.

    Returned as a query so callers can ``.count()``, iterate, or delete.
    """
    linked_to_repo = select(repository_content_items.c.content_item_id)
    linked_to_snapshot = select(snapshot_content_items.c.content_item_id)
    return session.query(ContentItem).filter(
        ContentItem.id.notin_(linked_to_repo),
        ContentItem.id.notin_(linked_to_snapshot),
    )


def _sum(session: Session, column: Any) -> int:
    return int(session.query(func.coalesce(func.sum(column), 0)).scalar() or 0)


def gather_global_stats(session: Session) -> dict:
    """Aggregate statistics across all repositories."""
    by_type: dict[str, int] = {
        row[0]: row[1]
        for row in session.query(ContentItem.content_type, func.count())
        .group_by(ContentItem.content_type)
        .all()
    }
    total_items = sum(by_type.values())

    # Physical pool usage = unique content-addressed blobs (sha256 is unique).
    content_bytes = _sum(session, ContentItem.size_bytes)
    file_bytes = _sum(session, RepositoryFile.size_bytes)

    # Logical bytes = what every repository/snapshot reference would cost if the
    # pool were not content-addressed (each link counted separately).
    repo_logical = int(
        session.query(func.coalesce(func.sum(ContentItem.size_bytes), 0))
        .select_from(repository_content_items)
        .join(ContentItem, ContentItem.id == repository_content_items.c.content_item_id)
        .scalar()
        or 0
    )
    snap_logical = int(
        session.query(func.coalesce(func.sum(ContentItem.size_bytes), 0))
        .select_from(snapshot_content_items)
        .join(ContentItem, ContentItem.id == snapshot_content_items.c.content_item_id)
        .scalar()
        or 0
    )
    logical_bytes = repo_logical + snap_logical
    # Deduplication baseline is the unique bytes of blobs that are referenced at
    # least once (unreferenced/GC-able blobs don't count as "saved").
    referenced_ids = select(repository_content_items.c.content_item_id).union(
        select(snapshot_content_items.c.content_item_id)
    )
    referenced_bytes = int(
        session.query(func.coalesce(func.sum(ContentItem.size_bytes), 0))
        .filter(ContentItem.id.in_(referenced_ids))
        .scalar()
        or 0
    )
    saved_bytes = max(0, logical_bytes - referenced_bytes)

    return {
        "repositories": session.query(Repository).count(),
        "snapshots": session.query(Snapshot).count(),
        "content_items": total_items,
        "by_type": by_type,
        "pool_bytes": content_bytes + file_bytes,
        "logical_bytes": logical_bytes,
        "saved_bytes": saved_bytes,
        "dedup_pct": (saved_bytes / logical_bytes * 100) if logical_bytes else 0.0,
    }


def gather_repository_stats(session: Session, repo_id: str) -> dict | None:
    """Statistics for a single repository, or ``None`` if it does not exist."""
    repo = session.query(Repository).filter_by(repo_id=repo_id).first()
    if repo is None:
        return None

    by_type: dict[str, int] = {}
    total_bytes = 0
    for item in repo.content_items:
        by_type[item.content_type] = by_type.get(item.content_type, 0) + 1
        total_bytes += item.size_bytes

    return {
        "repo_id": repo.repo_id,
        "type": repo.type,
        "mode": str(repo.mode),
        "content_items": sum(by_type.values()),
        "by_type": by_type,
        "snapshots": session.query(Snapshot).filter_by(repository_id=repo.id).count(),
        "pool_bytes": total_bytes,
    }


def format_bytes(num: int) -> str:
    """Human-readable byte size."""
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} {unit}"
        value /= 1024
    return f"{value:.1f} TB"
