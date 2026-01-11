"""
Tests for RPM sync plugin.

This module tests the RpmSyncPlugin implementation, focusing on kickstart support.
"""

from chantal.plugins.rpm import parsers


class TestTreeInfoParsing:
    """Tests for .treeinfo parsing."""

    def test_parse_treeinfo_basic(self):
        """Test parsing basic .treeinfo file."""
        treeinfo_content = """
[general]
arch = x86_64
family = CentOS Stream
version = 9

[checksums]
images/boot.iso = sha256:7fa5f43a19f85cfc87dd1f09ea023762ea44eeec79e7e7b13f286fcfe39bb6a8
images/pxeboot/vmlinuz = sha256:5b55ab14126b2979ce37a36ecb8dedd9a4dbb4e4de7f69488923aed0611ae8a0
images/pxeboot/initrd.img = sha256:95b778a741fd237d7daf982989ceaafa4496c3ed23376e734f0410c78b09781b

[images-x86_64]
boot.iso = images/boot.iso
kernel = images/pxeboot/vmlinuz
initrd = images/pxeboot/initrd.img
"""

        installer_files = parsers.parse_treeinfo(treeinfo_content)

        # Verify we got 3 files
        assert len(installer_files) == 3

        # Verify boot.iso
        boot_iso = next(f for f in installer_files if f["file_type"] == "boot.iso")
        assert boot_iso["path"] == "images/boot.iso"
        assert (
            boot_iso["sha256"] == "7fa5f43a19f85cfc87dd1f09ea023762ea44eeec79e7e7b13f286fcfe39bb6a8"
        )

        # Verify kernel (vmlinuz)
        kernel = next(f for f in installer_files if f["file_type"] == "kernel")
        assert kernel["path"] == "images/pxeboot/vmlinuz"
        assert (
            kernel["sha256"] == "5b55ab14126b2979ce37a36ecb8dedd9a4dbb4e4de7f69488923aed0611ae8a0"
        )

        # Verify initrd
        initrd = next(f for f in installer_files if f["file_type"] == "initrd")
        assert initrd["path"] == "images/pxeboot/initrd.img"
        assert (
            initrd["sha256"] == "95b778a741fd237d7daf982989ceaafa4496c3ed23376e734f0410c78b09781b"
        )

    def test_parse_treeinfo_no_checksums(self):
        """Test parsing .treeinfo without checksums section."""
        treeinfo_content = """
[general]
arch = x86_64

[images-x86_64]
boot.iso = images/boot.iso
kernel = images/pxeboot/vmlinuz
"""

        installer_files = parsers.parse_treeinfo(treeinfo_content)

        # Verify we got 2 files
        assert len(installer_files) == 2

        # Verify files have no checksums
        for file_info in installer_files:
            assert file_info["sha256"] is None

    def test_parse_treeinfo_different_arch(self):
        """Test parsing .treeinfo with different architecture."""
        treeinfo_content = """
[general]
arch = aarch64

[checksums]
images/boot.iso = sha256:abc123

[images-aarch64]
boot.iso = images/boot.iso
kernel = images/pxeboot/vmlinuz

[images-x86_64]
boot.iso = images/boot-x86.iso
"""

        installer_files = parsers.parse_treeinfo(treeinfo_content)

        # Should only parse images-aarch64 section
        assert len(installer_files) == 2

        # Verify paths are from aarch64 section
        paths = {f["path"] for f in installer_files}
        assert "images/boot.iso" in paths
        assert "images/pxeboot/vmlinuz" in paths
        assert "images/boot-x86.iso" not in paths

    def test_parse_treeinfo_empty(self):
        """Test parsing empty .treeinfo file."""
        treeinfo_content = "[general]\narch = x86_64\n"

        installer_files = parsers.parse_treeinfo(treeinfo_content)

        # Should return empty list
        assert installer_files == []

    def test_parse_treeinfo_no_arch(self):
        """Test parsing .treeinfo without arch specification (defaults to x86_64)."""
        treeinfo_content = """
[general]
family = CentOS

[checksums]
images/boot.iso = sha256:abc123

[images-x86_64]
boot.iso = images/boot.iso
"""

        installer_files = parsers.parse_treeinfo(treeinfo_content)

        # Should default to x86_64
        assert len(installer_files) == 1
        assert installer_files[0]["path"] == "images/boot.iso"

    def test_parse_treeinfo_real_centos_stream(self):
        """Test parsing real CentOS Stream .treeinfo format."""
        treeinfo_content = """
[checksums]
images/boot.iso = sha256:7fa5f43a19f85cfc87dd1f09ea023762ea44eeec79e7e7b13f286fcfe39bb6a8
images/install.img = sha256:e67e72d5f8a3b0c2e6ed5b8c8d6f9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e2f
images/pxeboot/initrd.img = sha256:95b778a741fd237d7daf982989ceaafa4496c3ed23376e734f0410c78b09781b
images/pxeboot/vmlinuz = sha256:5b55ab14126b2979ce37a36ecb8dedd9a4dbb4e4de7f69488923aed0611ae8a0
images/efiboot.img = sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef

[general]
; WARNING.0 = THIS SECTION IS KEPT ONLY FOR COMPATIBILITY REASONS
; WARNING.1 = Consider using a .discinfo file or other mechanism
arch = x86_64
family = CentOS Stream
name = CentOS Stream 9
timestamp = 1704672000
variant = BaseOS
version = 9

[header]
type = productmd.treeinfo
version = 1.2

[images-x86_64]
boot.iso = images/boot.iso
initrd = images/pxeboot/initrd.img
kernel = images/pxeboot/vmlinuz
efiboot.img = images/efiboot.img

[stage2]
instimage = images/install.img
mainimage = images/install.img
"""

        installer_files = parsers.parse_treeinfo(treeinfo_content)

        # Verify we got all 4 files from images-x86_64 section
        assert len(installer_files) == 4

        # Verify file types
        file_types = {f["file_type"] for f in installer_files}
        assert file_types == {"boot.iso", "initrd", "kernel", "efiboot.img"}

        # Verify all have checksums
        for file_info in installer_files:
            assert file_info["sha256"] is not None
            assert len(file_info["sha256"]) == 64  # SHA256 hex length
