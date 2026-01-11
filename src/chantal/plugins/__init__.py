"""Plugin system for Chantal repository types."""

from chantal.plugins.base import PublisherPlugin
from chantal.plugins.rpm.publisher import RpmPublisher
from chantal.plugins.rpm.sync import RpmSyncPlugin

__all__ = [
    "PublisherPlugin",
    "RpmPublisher",
    "RpmSyncPlugin",
]
