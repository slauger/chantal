from __future__ import annotations

"""Helm chart metadata models.

This module defines Pydantic models for type-safe Helm chart metadata.
The metadata is stored as JSON in the ContentItem.content_metadata field.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class HelmMaintainer(BaseModel):
    """Helm chart maintainer."""

    name: str
    email: str | None = None
    url: str | None = None


class HelmDependency(BaseModel):
    """Helm chart dependency."""

    name: str
    version: str
    repository: str | None = None
    condition: str | None = None
    tags: list[str] | None = None
    enabled: bool | None = None
    import_values: list | None = Field(None, alias="import-values")
    alias: str | None = None


class HelmMetadata(BaseModel):
    """Type-safe Helm chart metadata model.

    This model matches the structure of Helm's index.yaml chart entries.
    It is stored as JSON in ContentItem.content_metadata.

    Example:
        {
            "name": "nginx",
            "version": "15.0.0",
            "app_version": "1.25.0",
            "description": "NGINX Open Source Chart",
            "home": "https://github.com/bitnami/charts",
            ...
        }
    """

    # Required fields
    name: str
    version: str  # Chart version (semantic versioning)

    # Optional fields from index.yaml
    app_version: str | None = Field(None, alias="appVersion")
    description: str | None = None
    home: str | None = None
    icon: str | None = None
    keywords: list[str] | None = None
    sources: list[str] | None = None
    maintainers: list[HelmMaintainer] | None = None
    dependencies: list[HelmDependency] | None = None

    # Metadata
    created: datetime | None = None
    digest: str | None = None  # SHA256 from index.yaml (may differ from actual file SHA256)
    urls: list[str] | None = None  # Download URLs from index.yaml

    # Additional chart metadata
    api_version: str | None = Field(None, alias="apiVersion")  # Chart API version (usually "v2")
    type: str | None = None  # Chart type: application, library
    deprecated: bool | None = None
    annotations: dict[str, str] | None = None
    kube_version: str | None = Field(None, alias="kubeVersion")
    app_version_field: str | None = Field(None, alias="appVersion")

    class Config:
        """Pydantic config."""

        populate_by_name = True  # Allow both 'appVersion' and 'app_version'

    def to_index_entry(self) -> dict:
        """Convert to Helm index.yaml entry format.

        Returns:
            dict: Helm index.yaml compatible dictionary
        """
        entry = {
            "name": self.name,
            "version": self.version,
        }

        # Add optional fields if present
        if self.app_version:
            entry["appVersion"] = self.app_version
        if self.description:
            entry["description"] = self.description
        if self.home:
            entry["home"] = self.home
        if self.icon:
            entry["icon"] = self.icon
        if self.keywords:
            entry["keywords"] = self.keywords
        if self.sources:
            entry["sources"] = self.sources
        if self.maintainers:
            entry["maintainers"] = [m.model_dump(exclude_none=True) for m in self.maintainers]
        if self.dependencies:
            entry["dependencies"] = [
                d.model_dump(exclude_none=True, by_alias=True) for d in self.dependencies
            ]
        if self.created:
            entry["created"] = self.created.isoformat()
        if self.digest:
            entry["digest"] = self.digest
        if self.urls:
            entry["urls"] = self.urls
        if self.api_version:
            entry["apiVersion"] = self.api_version
        if self.type:
            entry["type"] = self.type
        if self.deprecated is not None:
            entry["deprecated"] = self.deprecated
        if self.annotations:
            entry["annotations"] = self.annotations
        if self.kube_version:
            entry["kubeVersion"] = self.kube_version

        return entry
