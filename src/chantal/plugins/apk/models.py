from __future__ import annotations

"""
Alpine APK metadata models.

This module contains Pydantic models for APK package metadata
parsed from APKINDEX files.
"""

from pydantic import BaseModel, Field


class ApkMetadata(BaseModel):
    """APK package metadata from APKINDEX.

    Maps APKINDEX field prefixes to Pydantic fields:
    - C: checksum (SHA1, base64-encoded with Q1 prefix)
    - P: name
    - V: version
    - A: architecture
    - S: size (bytes)
    - I: installed_size (bytes)
    - T: description
    - U: url
    - L: license
    - D: dependencies (space-separated)
    - p: provides (space-separated)
    - o: origin
    - m: maintainer
    - t: build_time (Unix timestamp)
    """

    name: str = Field(..., description="Package name")
    version: str = Field(..., description="Package version")
    architecture: str = Field(..., description="Architecture (x86_64, aarch64, etc.)")
    checksum: str = Field(..., description="SHA1 checksum (base64, Q1-prefixed)")
    size: int = Field(..., description="Package size in bytes")

    installed_size: int | None = Field(None, description="Installed size in bytes")
    description: str | None = Field(None, description="Package description")
    url: str | None = Field(None, description="Upstream URL")
    license: str | None = Field(None, description="Package license")
    dependencies: list[str] | None = Field(None, description="Runtime dependencies")
    provides: list[str] | None = Field(None, description="Virtual packages provided")
    origin: str | None = Field(None, description="Origin package name")
    maintainer: str | None = Field(None, description="Package maintainer")
    build_time: int | None = Field(None, description="Build timestamp (Unix)")

    @classmethod
    def from_apkindex_entry(cls, entry: dict) -> ApkMetadata:
        """Create ApkMetadata from parsed APKINDEX entry.

        Args:
            entry: Dictionary with APKINDEX fields

        Returns:
            ApkMetadata instance
        """
        # Parse dependencies and provides (space-separated strings)
        dependencies = None
        if entry.get("dependencies"):
            dependencies = [dep.strip() for dep in entry["dependencies"].split() if dep.strip()]

        provides = None
        if entry.get("provides"):
            provides = [prov.strip() for prov in entry["provides"].split() if prov.strip()]

        return cls(
            name=entry["name"],
            version=entry["version"],
            architecture=entry["architecture"],
            checksum=entry["checksum"],
            size=int(entry["size"]),
            installed_size=int(entry["installed_size"]) if entry.get("installed_size") else None,
            description=entry.get("description"),
            url=entry.get("url"),
            license=entry.get("license"),
            dependencies=dependencies,
            provides=provides,
            origin=entry.get("origin"),
            maintainer=entry.get("maintainer"),
            build_time=int(entry["build_time"]) if entry.get("build_time") else None,
        )

    def to_apkindex_entry(self) -> str:
        """Convert to APKINDEX entry format (text).

        Returns:
            APKINDEX entry as text (prefix:value lines)
        """
        lines = []

        # Required fields
        lines.append(f"C:{self.checksum}")
        lines.append(f"P:{self.name}")
        lines.append(f"V:{self.version}")
        lines.append(f"A:{self.architecture}")
        lines.append(f"S:{self.size}")

        # Optional fields
        if self.installed_size is not None:
            lines.append(f"I:{self.installed_size}")
        if self.description:
            lines.append(f"T:{self.description}")
        if self.url:
            lines.append(f"U:{self.url}")
        if self.license:
            lines.append(f"L:{self.license}")
        if self.dependencies:
            lines.append(f"D:{' '.join(self.dependencies)}")
        if self.provides:
            lines.append(f"p:{' '.join(self.provides)}")
        if self.origin:
            lines.append(f"o:{self.origin}")
        if self.maintainer:
            lines.append(f"m:{self.maintainer}")
        if self.build_time is not None:
            lines.append(f"t:{self.build_time}")

        return "\n".join(lines)

    def get_filename(self) -> str:
        """Get APK package filename.

        Returns:
            Filename in format: name-version.apk
        """
        return f"{self.name}-{self.version}.apk"
