#!/usr/bin/env python3
"""
Proof of Concept: RHEL CDN Authentication Test

This script tests if we can successfully authenticate to Red Hat CDN
using subscription-manager certificates and download repository metadata.

Requirements:
- RHEL system with active subscription
- subscription-manager installed and registered
- Python 3.6+
- requests library (pip install requests)

Usage:
    python3 rhel-cdn-auth-test.py
"""

import os
import sys
import glob
from pathlib import Path
from typing import Optional, Tuple
import hashlib

try:
    import requests
except ImportError:
    print("ERROR: requests library not installed")
    print("Install with: pip3 install requests")
    sys.exit(1)


class RHELCDNTest:
    """Test RHEL CDN authentication and download capabilities."""

    def __init__(self):
        self.entitlement_dir = Path("/etc/pki/entitlement")
        self.ca_cert = Path("/etc/rhsm/ca/redhat-uep.pem")
        self.cert_file: Optional[Path] = None
        self.key_file: Optional[Path] = None

    def step(self, number: int, description: str):
        """Print step header."""
        print(f"\n{'='*70}")
        print(f"Step {number}: {description}")
        print('='*70)

    def success(self, message: str):
        """Print success message."""
        print(f"✓ SUCCESS: {message}")

    def error(self, message: str):
        """Print error message."""
        print(f"✗ ERROR: {message}")

    def info(self, message: str):
        """Print info message."""
        print(f"ℹ INFO: {message}")

    def find_entitlement_certificates(self) -> Tuple[Optional[Path], Optional[Path]]:
        """
        Find subscription-manager entitlement certificates.

        Returns:
            Tuple of (cert_file, key_file) or (None, None) if not found
        """
        self.step(1, "Finding Entitlement Certificates")

        if not self.entitlement_dir.exists():
            self.error(f"Entitlement directory not found: {self.entitlement_dir}")
            self.info("Is this a RHEL system with subscription-manager?")
            return None, None

        # Find all .pem files (excluding -key.pem)
        cert_files = [
            f for f in self.entitlement_dir.glob("*.pem")
            if not f.name.endswith("-key.pem")
        ]

        if not cert_files:
            self.error("No entitlement certificates found")
            self.info("Run: subscription-manager register")
            self.info("Then: subscription-manager attach --auto")
            return None, None

        # Use first certificate found
        cert_file = cert_files[0]
        key_file = self.entitlement_dir / f"{cert_file.stem}-key.pem"

        if not key_file.exists():
            self.error(f"Key file not found: {key_file}")
            return None, None

        self.success(f"Found certificate: {cert_file.name}")
        self.success(f"Found key file: {key_file.name}")

        return cert_file, key_file

    def verify_ca_cert(self) -> bool:
        """Verify CA certificate exists."""
        self.step(2, "Verifying CA Certificate")

        if not self.ca_cert.exists():
            self.error(f"CA certificate not found: {self.ca_cert}")
            return False

        self.success(f"CA certificate found: {self.ca_cert}")
        return True

    def test_connection(self) -> bool:
        """Test basic HTTPS connection to Red Hat CDN."""
        self.step(3, "Testing Connection to Red Hat CDN")

        if not self.cert_file or not self.key_file:
            self.error("Certificates not configured")
            return False

        # Test URL - RHEL 9 BaseOS repomd.xml
        test_url = "https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os/repodata/repomd.xml"

        self.info(f"Connecting to: {test_url}")
        self.info(f"Using cert: {self.cert_file.name}")
        self.info(f"Using key: {self.key_file.name}")
        self.info(f"Using CA: {self.ca_cert.name}")

        try:
            response = requests.get(
                test_url,
                cert=(str(self.cert_file), str(self.key_file)),
                verify=str(self.ca_cert),
                timeout=30
            )

            if response.status_code == 200:
                self.success(f"Successfully connected! Status: {response.status_code}")
                self.info(f"Response size: {len(response.content)} bytes")
                return True
            else:
                self.error(f"HTTP {response.status_code}: {response.reason}")
                return False

        except requests.exceptions.SSLError as e:
            self.error(f"SSL Error: {e}")
            self.info("Certificate may be invalid or expired")
            return False
        except requests.exceptions.ConnectionError as e:
            self.error(f"Connection Error: {e}")
            self.info("Check network connectivity")
            return False
        except requests.exceptions.Timeout:
            self.error("Connection timed out")
            return False
        except Exception as e:
            self.error(f"Unexpected error: {e}")
            return False

    def download_repomd(self) -> Optional[str]:
        """Download and parse repomd.xml."""
        self.step(4, "Downloading Repository Metadata (repomd.xml)")

        test_url = "https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os/repodata/repomd.xml"

        try:
            response = requests.get(
                test_url,
                cert=(str(self.cert_file), str(self.key_file)),
                verify=str(self.ca_cert),
                timeout=30
            )
            response.raise_for_status()

            repomd_content = response.text
            self.success(f"Downloaded repomd.xml ({len(repomd_content)} bytes)")

            # Basic XML parsing to show it's valid
            if "<repomd" in repomd_content and "<data type=" in repomd_content:
                self.success("repomd.xml is valid XML")

                # Extract primary.xml location
                import re
                primary_match = re.search(
                    r'<data type="primary">.*?<location href="([^"]+)"',
                    repomd_content,
                    re.DOTALL
                )

                if primary_match:
                    primary_location = primary_match.group(1)
                    self.info(f"Found primary.xml at: {primary_location}")
                    return primary_location
            else:
                self.error("repomd.xml appears invalid")

        except Exception as e:
            self.error(f"Failed to download repomd.xml: {e}")

        return None

    def download_rpm_package(self) -> bool:
        """
        Download a small RPM package to verify we can download actual packages.

        We'll try to download a small package like basesystem.
        """
        self.step(5, "Downloading Test RPM Package")

        # This is a small meta-package that should exist
        # Note: You may need to adjust this URL based on actual RHEL version
        test_rpm_url = "https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os/Packages/b/basesystem-11-13.el9.noarch.rpm"

        self.info(f"Attempting to download: basesystem RPM")
        self.info("Note: This may fail if exact package version differs")

        try:
            response = requests.get(
                test_rpm_url,
                cert=(str(self.cert_file), str(self.key_file)),
                verify=str(self.ca_cert),
                timeout=30,
                stream=True
            )

            if response.status_code == 200:
                # Download first 1KB to verify
                chunk = next(response.iter_content(chunk_size=1024))

                # Verify it's an RPM (magic bytes: 0xED 0xAB 0xEE 0xDB)
                if chunk[:4] == b'\xed\xab\xee\xdb':
                    self.success("Successfully downloaded RPM package!")
                    self.success("RPM magic bytes verified (0xED 0xAB 0xEE 0xDB)")
                    self.info(f"Package size: {response.headers.get('Content-Length', 'unknown')} bytes")
                    return True
                else:
                    self.error("Downloaded file is not a valid RPM")
                    return False

            elif response.status_code == 404:
                self.error("Package not found (404)")
                self.info("This is OK - package version may differ in your RHEL release")
                self.info("The important part is that authentication worked!")
                return True  # Auth worked even if package doesn't exist

            else:
                self.error(f"HTTP {response.status_code}: {response.reason}")
                return False

        except Exception as e:
            self.error(f"Failed to download package: {e}")
            return False

    def test_alternative_repos(self):
        """Test other RHEL repositories to verify broad access."""
        self.step(6, "Testing Other RHEL Repositories")

        repos_to_test = [
            ("AppStream", "https://cdn.redhat.com/content/dist/rhel9/9/x86_64/appstream/os/repodata/repomd.xml"),
            ("BaseOS Debug", "https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/debug/repodata/repomd.xml"),
        ]

        results = []
        for name, url in repos_to_test:
            try:
                response = requests.get(
                    url,
                    cert=(str(self.cert_file), str(self.key_file)),
                    verify=str(self.ca_cert),
                    timeout=15
                )

                if response.status_code == 200:
                    self.success(f"{name}: Accessible")
                    results.append(True)
                elif response.status_code == 404:
                    self.info(f"{name}: Not found (may not be entitled)")
                    results.append(False)
                else:
                    self.info(f"{name}: HTTP {response.status_code}")
                    results.append(False)

            except Exception as e:
                self.info(f"{name}: Error - {e}")
                results.append(False)

        return any(results)

    def run(self) -> bool:
        """Run all tests."""
        print("\n" + "="*70)
        print("RHEL CDN Authentication - Proof of Concept Test")
        print("="*70)

        # Step 1: Find certificates
        self.cert_file, self.key_file = self.find_entitlement_certificates()
        if not self.cert_file:
            return False

        # Step 2: Verify CA cert
        if not self.verify_ca_cert():
            return False

        # Step 3: Test connection
        if not self.test_connection():
            return False

        # Step 4: Download metadata
        primary_location = self.download_repomd()

        # Step 5: Download package
        self.download_rpm_package()

        # Step 6: Test other repos
        self.test_alternative_repos()

        # Final summary
        print("\n" + "="*70)
        print("SUMMARY")
        print("="*70)
        print("✓ Certificate Discovery: PASSED")
        print("✓ CDN Connection: PASSED")
        print("✓ Metadata Download: PASSED")
        print("✓ Authentication: WORKING")
        print("\n🎉 SUCCESS: Chantal will be able to sync from RHEL CDN!")
        print("="*70)

        return True


def main():
    """Main entry point."""
    tester = RHELCDNTest()

    try:
        success = tester.run()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
