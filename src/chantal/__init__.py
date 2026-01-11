from __future__ import annotations

"""
Chantal - Unified Offline Repository Mirroring

A CLI tool for offline mirroring of RPM and APT repositories with support for
Red Hat Subscription authentication, content-addressed storage, and immutable
snapshots.
"""

__version__ = "0.1.0"
__author__ = "Simon Lauger"
__license__ = "MIT"

# Make version accessible
from importlib.metadata import version as _version

try:
    __version__ = _version("chantal")
except Exception:
    # Package not installed yet
    pass
