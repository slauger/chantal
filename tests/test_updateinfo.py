"""Tests for updateinfo parsing and filtering."""

import bz2
import gzip
import xml.etree.ElementTree as ET

import pytest

from chantal.plugins.rpm.updateinfo import (
    Update,
    UpdateInfoFilter,
    UpdateInfoGenerator,
    UpdateInfoParser,
    UpdatePackage,
)


@pytest.fixture
def sample_updateinfo_xml():
    """Sample updateinfo.xml content."""
    return """<?xml version="1.0" encoding="UTF-8"?>
<updates>
  <update type="security" status="stable">
    <id>RHSA-2024:0001</id>
    <title>Important: security update</title>
    <issued date="2024-01-01"/>
    <updated date="2024-01-02"/>
    <severity>Important</severity>
    <summary>Security fix for vulnerability</summary>
    <description>This update fixes a critical security vulnerability.</description>
    <pkglist>
      <collection>
        <package name="httpd" version="2.4.57" release="5.el9" epoch="0" arch="x86_64">
          <filename>httpd-2.4.57-5.el9.x86_64.rpm</filename>
        </package>
        <package name="httpd-tools" version="2.4.57" release="5.el9" epoch="0" arch="x86_64">
          <filename>httpd-tools-2.4.57-5.el9.x86_64.rpm</filename>
        </package>
      </collection>
    </pkglist>
  </update>
  <update type="bugfix" status="stable">
    <id>RHBA-2024:0002</id>
    <title>Bug fix update</title>
    <issued date="2024-01-03"/>
    <severity>Moderate</severity>
    <summary>Bug fixes</summary>
    <description>Various bug fixes.</description>
    <pkglist>
      <collection>
        <package name="vim-enhanced" version="9.0.1" release="1.el9" epoch="2" arch="x86_64">
          <filename>vim-enhanced-9.0.1-1.el9.x86_64.rpm</filename>
        </package>
      </collection>
    </pkglist>
  </update>
  <update type="enhancement" status="stable">
    <id>RHEA-2024:0003</id>
    <title>Enhancement update</title>
    <issued date="2024-01-04"/>
    <pkglist>
      <collection>
        <package name="missing-package" version="1.0.0" release="1.el9" epoch="0" arch="x86_64">
          <filename>missing-package-1.0.0-1.el9.x86_64.rpm</filename>
        </package>
      </collection>
    </pkglist>
  </update>
</updates>
"""


@pytest.fixture
def sample_updates():
    """Sample Update objects."""
    return [
        Update(
            update_id="RHSA-2024:0001",
            title="Important: security update",
            update_type="security",
            status="stable",
            issued_date="2024-01-01",
            updated_date="2024-01-02",
            severity="Important",
            summary="Security fix for vulnerability",
            description="This update fixes a critical security vulnerability.",
            packages=[
                UpdatePackage(
                    name="httpd",
                    version="2.4.57",
                    release="5.el9",
                    epoch="0",
                    arch="x86_64",
                    filename="httpd-2.4.57-5.el9.x86_64.rpm",
                ),
                UpdatePackage(
                    name="httpd-tools",
                    version="2.4.57",
                    release="5.el9",
                    epoch="0",
                    arch="x86_64",
                    filename="httpd-tools-2.4.57-5.el9.x86_64.rpm",
                ),
            ],
        ),
        Update(
            update_id="RHBA-2024:0002",
            title="Bug fix update",
            update_type="bugfix",
            status="stable",
            issued_date="2024-01-03",
            updated_date=None,
            severity="Moderate",
            summary="Bug fixes",
            description="Various bug fixes.",
            packages=[
                UpdatePackage(
                    name="vim-enhanced",
                    version="9.0.1",
                    release="1.el9",
                    epoch="2",
                    arch="x86_64",
                    filename="vim-enhanced-9.0.1-1.el9.x86_64.rpm",
                )
            ],
        ),
    ]


class TestUpdateInfoParser:
    """Tests for UpdateInfoParser."""

    def test_parse_uncompressed_xml(self, sample_updateinfo_xml, tmp_path):
        """Test parsing uncompressed updateinfo.xml."""
        xml_file = tmp_path / "updateinfo.xml"
        xml_file.write_text(sample_updateinfo_xml, encoding="utf-8")

        parser = UpdateInfoParser()
        updates = parser.parse_file(xml_file)

        assert len(updates) == 3
        assert updates[0].update_id == "RHSA-2024:0001"
        assert updates[0].update_type == "security"
        assert updates[0].severity == "Important"
        assert len(updates[0].packages) == 2
        assert updates[0].packages[0].name == "httpd"

    def test_parse_gzipped_xml(self, sample_updateinfo_xml, tmp_path):
        """Test parsing gzipped updateinfo.xml.gz."""
        xml_file = tmp_path / "updateinfo.xml.gz"
        with gzip.open(xml_file, "wt", encoding="utf-8") as f:
            f.write(sample_updateinfo_xml)

        parser = UpdateInfoParser()
        updates = parser.parse_file(xml_file)

        assert len(updates) == 3
        assert updates[1].update_id == "RHBA-2024:0002"
        assert updates[1].update_type == "bugfix"

    def test_parse_bzip2_xml(self, sample_updateinfo_xml, tmp_path):
        """Test parsing bzip2 compressed updateinfo.xml.bz2."""
        xml_file = tmp_path / "updateinfo.xml.bz2"
        with bz2.open(xml_file, "wt", encoding="utf-8") as f:
            f.write(sample_updateinfo_xml)

        parser = UpdateInfoParser()
        updates = parser.parse_file(xml_file)

        assert len(updates) == 3
        assert updates[2].update_id == "RHEA-2024:0003"
        assert updates[2].update_type == "enhancement"

    def test_parse_package_metadata(self, sample_updateinfo_xml, tmp_path):
        """Test parsing package metadata from update."""
        xml_file = tmp_path / "updateinfo.xml"
        xml_file.write_text(sample_updateinfo_xml, encoding="utf-8")

        parser = UpdateInfoParser()
        updates = parser.parse_file(xml_file)

        # Check security update packages
        pkg = updates[0].packages[0]
        assert pkg.name == "httpd"
        assert pkg.version == "2.4.57"
        assert pkg.release == "5.el9"
        assert pkg.epoch == "0"
        assert pkg.arch == "x86_64"
        assert pkg.filename == "httpd-2.4.57-5.el9.x86_64.rpm"

        # Check bugfix update package with epoch
        pkg2 = updates[1].packages[0]
        assert pkg2.epoch == "2"

    def test_parse_preserves_xml_element(self, sample_updateinfo_xml, tmp_path):
        """Test that original XML element is preserved."""
        xml_file = tmp_path / "updateinfo.xml"
        xml_file.write_text(sample_updateinfo_xml, encoding="utf-8")

        parser = UpdateInfoParser()
        updates = parser.parse_file(xml_file)

        # Check that _xml_element is preserved
        assert updates[0]._xml_element is not None
        assert updates[0]._xml_element.tag == "update"
        assert updates[0]._xml_element.get("type") == "security"


class TestUpdateInfoFilter:
    """Tests for UpdateInfoFilter."""

    def test_filter_with_all_packages_available(self, sample_updates):
        """Test filtering when all packages are available."""
        available_packages = {
            "httpd-2.4.57-5.el9.x86_64",
            "httpd-tools-2.4.57-5.el9.x86_64",
            "vim-enhanced-9.0.1-1.el9.x86_64",
        }

        filter_obj = UpdateInfoFilter()
        filtered = filter_obj.filter_updates(sample_updates, available_packages)

        assert len(filtered) == 2
        assert filtered[0].update_id == "RHSA-2024:0001"
        assert filtered[1].update_id == "RHBA-2024:0002"

    def test_filter_with_partial_packages(self, sample_updates):
        """Test filtering when only some packages are available."""
        # Only httpd is available (not httpd-tools)
        available_packages = {
            "httpd-2.4.57-5.el9.x86_64",
        }

        filter_obj = UpdateInfoFilter()
        filtered = filter_obj.filter_updates(sample_updates, available_packages)

        # Should keep RHSA-2024:0001 because at least one package is available
        assert len(filtered) == 1
        assert filtered[0].update_id == "RHSA-2024:0001"

    def test_filter_removes_updates_with_no_available_packages(self, sample_updates):
        """Test filtering removes updates with no available packages."""
        # No matching packages
        available_packages = {
            "other-package-1.0.0-1.el9.x86_64",
        }

        filter_obj = UpdateInfoFilter()
        filtered = filter_obj.filter_updates(sample_updates, available_packages)

        assert len(filtered) == 0

    def test_filter_with_empty_available_set(self, sample_updates):
        """Test filtering with empty available packages set."""
        available_packages = set()

        filter_obj = UpdateInfoFilter()
        filtered = filter_obj.filter_updates(sample_updates, available_packages)

        assert len(filtered) == 0


class TestUpdateInfoGenerator:
    """Tests for UpdateInfoGenerator."""

    def test_generate_xml_basic(self, sample_updates):
        """Test generating updateinfo.xml from Update objects."""
        generator = UpdateInfoGenerator()
        xml_bytes = generator.generate_xml(sample_updates)

        assert xml_bytes.startswith(b"<?xml version=")
        assert b"<updates>" in xml_bytes
        assert b"RHSA-2024:0001" in xml_bytes
        assert b"RHBA-2024:0002" in xml_bytes

    def test_generate_xml_parseable(self, sample_updates):
        """Test that generated XML is parseable."""
        generator = UpdateInfoGenerator()
        xml_bytes = generator.generate_xml(sample_updates)

        # Parse generated XML
        root = ET.fromstring(xml_bytes)
        assert root.tag == "updates"

        # Check updates
        update_elems = root.findall("update")
        assert len(update_elems) == 2

        # Check first update
        assert update_elems[0].find("id").text == "RHSA-2024:0001"
        assert update_elems[0].get("type") == "security"

    def test_generate_xml_with_original_elements(self, sample_updateinfo_xml, tmp_path):
        """Test generating XML using original XML elements."""
        # Parse original XML
        xml_file = tmp_path / "updateinfo.xml"
        xml_file.write_text(sample_updateinfo_xml, encoding="utf-8")

        parser = UpdateInfoParser()
        updates = parser.parse_file(xml_file)

        # Generate new XML (should use original elements)
        generator = UpdateInfoGenerator()
        xml_bytes = generator.generate_xml(updates[:2])

        # Parse and verify
        root = ET.fromstring(xml_bytes)
        update_elems = root.findall("update")
        assert len(update_elems) == 2

    def test_generate_xml_empty_list(self):
        """Test generating XML from empty update list."""
        generator = UpdateInfoGenerator()
        xml_bytes = generator.generate_xml([])

        root = ET.fromstring(xml_bytes)
        assert root.tag == "updates"
        assert len(root.findall("update")) == 0


class TestUpdateInfoIntegration:
    """Integration tests for complete workflow."""

    def test_parse_filter_generate_workflow(self, sample_updateinfo_xml, tmp_path):
        """Test complete parse → filter → generate workflow."""
        # Write sample XML
        xml_file = tmp_path / "updateinfo.xml.gz"
        with gzip.open(xml_file, "wt", encoding="utf-8") as f:
            f.write(sample_updateinfo_xml)

        # Parse
        parser = UpdateInfoParser()
        updates = parser.parse_file(xml_file)
        assert len(updates) == 3

        # Filter (only httpd and vim-enhanced available)
        available_packages = {
            "httpd-2.4.57-5.el9.x86_64",
            "httpd-tools-2.4.57-5.el9.x86_64",
            "vim-enhanced-9.0.1-1.el9.x86_64",
        }
        filter_obj = UpdateInfoFilter()
        filtered_updates = filter_obj.filter_updates(updates, available_packages)
        assert len(filtered_updates) == 2

        # Generate
        generator = UpdateInfoGenerator()
        xml_bytes = generator.generate_xml(filtered_updates)

        # Verify generated XML
        root = ET.fromstring(xml_bytes)
        update_elems = root.findall("update")
        assert len(update_elems) == 2
        assert update_elems[0].find("id").text == "RHSA-2024:0001"
        assert update_elems[1].find("id").text == "RHBA-2024:0002"

    def test_filtered_xml_excludes_unavailable_updates(self, sample_updateinfo_xml, tmp_path):
        """Test that filtered XML excludes updates with unavailable packages."""
        xml_file = tmp_path / "updateinfo.xml"
        xml_file.write_text(sample_updateinfo_xml, encoding="utf-8")

        parser = UpdateInfoParser()
        updates = parser.parse_file(xml_file)

        # Only vim-enhanced is available
        available_packages = {"vim-enhanced-9.0.1-1.el9.x86_64"}

        filter_obj = UpdateInfoFilter()
        filtered_updates = filter_obj.filter_updates(updates, available_packages)

        # Only bugfix update should remain
        assert len(filtered_updates) == 1
        assert filtered_updates[0].update_id == "RHBA-2024:0002"

        generator = UpdateInfoGenerator()
        xml_bytes = generator.generate_xml(filtered_updates)

        # Verify enhancement update is not in generated XML
        assert b"RHSA-2024:0001" not in xml_bytes
        assert b"RHEA-2024:0003" not in xml_bytes
        assert b"RHBA-2024:0002" in xml_bytes
