from __future__ import annotations

"""
APT/DEB repository plugin for Chantal.

Provides support for Debian/Ubuntu APT repositories with mirror mode support.
"""

from chantal.plugins.apt.models import DebMetadata, ReleaseMetadata, SourcesMetadata
from chantal.plugins.apt.sync import AptSyncPlugin

__all__ = [
    "DebMetadata",
    "ReleaseMetadata",
    "SourcesMetadata",
    "AptSyncPlugin",
]
