"""
Pydantic models for RPM plugin.

These models define the metadata schema for RPM packages stored in the generic
ContentItem model.
"""

from typing import Optional

from pydantic import BaseModel, Field


class RpmMetadata(BaseModel):
    """Metadata schema for RPM packages.

    This is stored as JSON in ContentItem.metadata field.
    Provides type safety and validation for RPM-specific fields.
    """

    # RPM-specific version fields
    epoch: Optional[str] = Field(None, description="RPM epoch (e.g., '1', '2')")
    release: str = Field(..., description="RPM release (e.g., '1.el9', '2.fc38')")
    arch: str = Field(..., description="Architecture (e.g., 'x86_64', 'noarch', 'aarch64')")

    # Metadata
    summary: Optional[str] = Field(None, description="Short package summary")
    description: Optional[str] = Field(None, description="Detailed package description")

    # Dependencies (optional for now, can be extended later)
    provides: Optional[list[str]] = Field(None, description="List of provides")
    requires: Optional[list[str]] = Field(None, description="List of requires")
    conflicts: Optional[list[str]] = Field(None, description="List of conflicts")
    obsoletes: Optional[list[str]] = Field(None, description="List of obsoletes")

    class Config:
        """Pydantic configuration."""

        # Allow extra fields for forward compatibility
        extra = "allow"

    def get_nevra(self, name: str, version: str) -> str:
        """Get NEVRA string (Name-Epoch:Version-Release.Arch).

        Args:
            name: Package name
            version: Package version

        Returns:
            NEVRA string (e.g., "nginx-1:1.20.1-1.el9.x86_64")
        """
        epoch_str = f"{self.epoch}:" if self.epoch else ""
        return f"{name}-{epoch_str}{version}-{self.release}.{self.arch}"
