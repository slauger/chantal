"""Plugin system for Chantal repository types."""

from chantal.plugins.base import PublisherPlugin
from chantal.plugins.rpm import RpmPublisher

__all__ = [
    "PublisherPlugin",
    "RpmPublisher",
]
