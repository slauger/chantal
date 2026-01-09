"""Plugin system for Chantal repository types."""

from chantal.plugins.base import PublisherPlugin
from chantal.plugins.rpm import RpmPublisher
from chantal.plugins.rpm_sync import RpmSyncPlugin

__all__ = [
    "PublisherPlugin",
    "RpmPublisher",
    "RpmSyncPlugin",
]
