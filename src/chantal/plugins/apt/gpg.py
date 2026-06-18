from __future__ import annotations

"""
APT GPG signing.

The implementation now lives in :mod:`chantal.core.gpg` so it can be shared with
the RPM publisher. This module re-exports it for backward compatibility.
"""

from chantal.core.gpg import GpgSigner, GpgSigningError

__all__ = ["GpgSigner", "GpgSigningError"]
