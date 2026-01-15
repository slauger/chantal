from __future__ import annotations

"""
Update information (errata) handling for RPM repositories.

This module provides parsing and filtering for updateinfo.xml files,
which contain security advisories, bug fixes, and enhancement information.
"""

import bz2
import gzip
import lzma
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


@dataclass
class UpdatePackage:
    """Package reference in an update/errata."""

    name: str
    version: str
    release: str
    epoch: str
    arch: str
    filename: str


@dataclass
class Update:
    """Errata/update information."""

    update_id: str
    title: str
    update_type: str  # "security", "bugfix", "enhancement"
    status: str
    issued_date: str
    updated_date: str | None
    severity: str | None
    summary: str | None
    description: str | None
    packages: list[UpdatePackage]
    # Store original XML element for regeneration
    _xml_element: ET.Element | None = None


class UpdateInfoParser:
    """Parser for updateinfo.xml files."""

    def parse_file(self, file_path: Path) -> list[Update]:
        """Parse updateinfo.xml file.

        Supports .xml, .xml.gz, .xml.bz2, and .xml.xz compression.

        Args:
            file_path: Path to updateinfo file

        Returns:
            List of Update objects
        """
        # Decompress based on extension
        if file_path.suffix == ".bz2":
            with bz2.open(file_path, "rt", encoding="utf-8") as f:
                xml_content = f.read()
        elif file_path.suffix == ".gz":
            with gzip.open(file_path, "rt", encoding="utf-8") as f:
                xml_content = f.read()
        elif file_path.suffix == ".xz":
            with lzma.open(file_path, "rt", encoding="utf-8") as f:
                xml_content = f.read()
        else:
            with open(file_path, encoding="utf-8") as f:
                xml_content = f.read()

        # Parse XML
        root = ET.fromstring(xml_content)

        return self._parse_updates(root)

    def _parse_updates(self, root: ET.Element) -> list[Update]:
        """Parse <updates> root element.

        Args:
            root: XML root element

        Returns:
            List of Update objects
        """
        updates = []

        # Find all <update> elements
        update_elems = root.findall("update")

        for update_elem in update_elems:
            try:
                update = self._parse_update(update_elem)
                if update:
                    updates.append(update)
            except Exception as e:
                print(f"Warning: Failed to parse update: {e}")
                continue

        return updates

    def _parse_update(self, update_elem: ET.Element) -> Update | None:
        """Parse single <update> element.

        Args:
            update_elem: XML update element

        Returns:
            Update object or None if parsing fails
        """
        # Get basic attributes
        update_type = update_elem.get("type", "bugfix")
        status = update_elem.get("status", "")

        # Parse child elements
        id_elem = update_elem.find("id")
        if id_elem is None or not id_elem.text:
            return None

        title_elem = update_elem.find("title")
        issued_elem = update_elem.find("issued")
        updated_elem = update_elem.find("updated")
        severity_elem = update_elem.find("severity")
        summary_elem = update_elem.find("summary")
        desc_elem = update_elem.find("description")

        # Parse package list
        packages = self._parse_pkglist(update_elem)

        # Get title, use empty string as fallback
        title = (title_elem.text if title_elem is not None else "") or ""

        return Update(
            update_id=id_elem.text,
            title=title,
            update_type=update_type,
            status=status,
            issued_date=issued_elem.get("date", "") if issued_elem is not None else "",
            updated_date=updated_elem.get("date", "") if updated_elem is not None else None,
            severity=severity_elem.text if severity_elem is not None else None,
            summary=summary_elem.text if summary_elem is not None else None,
            description=desc_elem.text if desc_elem is not None else None,
            packages=packages,
            _xml_element=update_elem,  # Store for regeneration
        )

    def _parse_pkglist(self, update_elem: ET.Element) -> list[UpdatePackage]:
        """Parse <pkglist> from update element.

        Args:
            update_elem: XML update element

        Returns:
            List of UpdatePackage objects
        """
        packages: list[UpdatePackage] = []

        pkglist_elem = update_elem.find("pkglist")
        if pkglist_elem is None:
            return packages

        # Find all collections and packages
        for collection_elem in pkglist_elem.findall("collection"):
            for pkg_elem in collection_elem.findall("package"):
                try:
                    name = pkg_elem.get("name")
                    version = pkg_elem.get("version")
                    release = pkg_elem.get("release")
                    epoch = pkg_elem.get("epoch", "0")
                    arch = pkg_elem.get("arch")

                    filename_elem = pkg_elem.find("filename")
                    filename = (filename_elem.text if filename_elem is not None else "") or ""

                    if name and version and release and arch:
                        packages.append(
                            UpdatePackage(
                                name=name,
                                version=version,
                                release=release,
                                epoch=epoch,
                                arch=arch,
                                filename=filename,
                            )
                        )
                except Exception:
                    continue

        return packages


class UpdateInfoFilter:
    """Filter updateinfo based on available packages."""

    def filter_updates(self, updates: list[Update], available_packages: set[str]) -> list[Update]:
        """Filter updates to only include those with available packages.

        Args:
            updates: List of Update objects
            available_packages: Set of package NVRAs (name-version-release.arch)

        Returns:
            Filtered list of Update objects
        """
        filtered = []

        for update in updates:
            # Check if at least one package in the update is available
            has_available_package = False

            for pkg in update.packages:
                # Build NVRA key: name-version-release.arch
                nvra = f"{pkg.name}-{pkg.version}-{pkg.release}.{pkg.arch}"

                if nvra in available_packages:
                    has_available_package = True
                    break

            # Keep update if it has at least one available package
            if has_available_package:
                filtered.append(update)

        return filtered


class UpdateInfoGenerator:
    """Generate updateinfo.xml from Update objects."""

    def generate_xml(self, updates: list[Update]) -> bytes:
        """Generate updateinfo.xml content.

        Args:
            updates: List of Update objects

        Returns:
            XML bytes (uncompressed)
        """
        # Create root element
        root = ET.Element("updates")

        # Add each update (use stored XML elements if available)
        for update in updates:
            if update._xml_element is not None:
                # Use original XML element
                root.append(update._xml_element)
            else:
                # Generate new XML element (fallback)
                root.append(self._generate_update_element(update))

        # Generate XML
        tree = ET.ElementTree(root)

        # Pretty print
        ET.indent(tree, space="  ")

        # Convert to bytes
        import io

        output = io.BytesIO()
        tree.write(output, encoding="UTF-8", xml_declaration=True)

        return output.getvalue()

    def _generate_update_element(self, update: Update) -> ET.Element:
        """Generate XML element for an update.

        This is a fallback when original XML is not available.

        Args:
            update: Update object

        Returns:
            XML Element
        """
        update_elem = ET.Element("update")
        update_elem.set("type", update.update_type)
        update_elem.set("status", update.status)
        update_elem.set("version", "2.0")

        # Add child elements
        id_elem = ET.SubElement(update_elem, "id")
        id_elem.text = update.update_id

        title_elem = ET.SubElement(update_elem, "title")
        title_elem.text = update.title

        issued_elem = ET.SubElement(update_elem, "issued")
        issued_elem.set("date", update.issued_date)

        if update.updated_date:
            updated_elem = ET.SubElement(update_elem, "updated")
            updated_elem.set("date", update.updated_date)

        if update.severity:
            severity_elem = ET.SubElement(update_elem, "severity")
            severity_elem.text = update.severity

        if update.summary:
            summary_elem = ET.SubElement(update_elem, "summary")
            summary_elem.text = update.summary

        if update.description:
            desc_elem = ET.SubElement(update_elem, "description")
            desc_elem.text = update.description

        # Add package list
        pkglist_elem = ET.SubElement(update_elem, "pkglist")
        collection_elem = ET.SubElement(pkglist_elem, "collection")

        for pkg in update.packages:
            pkg_elem = ET.SubElement(collection_elem, "package")
            pkg_elem.set("name", pkg.name)
            pkg_elem.set("version", pkg.version)
            pkg_elem.set("release", pkg.release)
            pkg_elem.set("epoch", pkg.epoch)
            pkg_elem.set("arch", pkg.arch)

            filename_elem = ET.SubElement(pkg_elem, "filename")
            filename_elem.text = pkg.filename

        return update_elem
