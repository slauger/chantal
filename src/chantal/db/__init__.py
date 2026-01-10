"""
Database package for Chantal.

This package contains database models, connection management, and migrations.
"""

from chantal.db.connection import DatabaseManager, get_database_manager
from chantal.db.models import (
    Base,
    ContentItem,
    Repository,
    Snapshot,
    SyncHistory,
    View,
    ViewRepository,
    ViewSnapshot,
)

__all__ = [
    "Base",
    "ContentItem",
    "Repository",
    "Snapshot",
    "SyncHistory",
    "View",
    "ViewRepository",
    "ViewSnapshot",
    "DatabaseManager",
    "get_database_manager",
]
