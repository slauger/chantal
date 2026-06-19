from __future__ import annotations

"""
GPG verification of upstream repository authenticity.

This is the counterpart to :class:`chantal.core.gpg.GpgSigner`: instead of a
*private* key used to re-sign regenerated metadata, the verifier imports the
upstream vendor's *public* key(s) into an isolated keyring and checks detached
OpenPGP signatures (e.g. RPM ``repomd.xml.asc``, APT ``Release.gpg``, and RPM
package header signatures).

Wraps the ``gpg`` binary via ``python-gnupg`` (already a dependency).
"""

import os
import tempfile
from pathlib import Path
from types import TracebackType

import gnupg

from chantal.core.config import SignatureVerificationConfig


class GpgVerificationError(Exception):
    """Raised when verification cannot be performed (setup/import problems)."""


class GpgVerifier:
    """Verify detached OpenPGP signatures against configured trusted keys.

    The trusted public keys are imported into an isolated keyring on first use.
    A temporary keyring is created (and removed on close) unless ``gnupg_home``
    is configured.
    """

    def __init__(self, config: SignatureVerificationConfig):
        self.config = config
        self._imported = False

        self._tempdir: tempfile.TemporaryDirectory[str] | None = None
        if config.gnupg_home:
            self._gnupg_home = Path(config.gnupg_home)
            self._gnupg_home.mkdir(parents=True, exist_ok=True)
        else:
            self._tempdir = tempfile.TemporaryDirectory(prefix="chantal-verify-")
            self._gnupg_home = Path(self._tempdir.name)

        os.chmod(self._gnupg_home, 0o700)
        self.gpg = gnupg.GPG(gnupghome=str(self._gnupg_home))
        self.gpg.encoding = "utf-8"

    def __enter__(self) -> GpgVerifier:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Remove the temporary keyring, if one was created."""
        if self._tempdir is not None:
            self._tempdir.cleanup()
            self._tempdir = None

    def import_trusted_keys(self) -> list[str]:
        """Import all configured trust anchors into the keyring.

        Returns:
            The fingerprints of the imported keys.

        Raises:
            GpgVerificationError: If a key file is missing or no key imported.
        """
        fingerprints: list[str] = []

        for key_file in self.config.key_files:
            path = Path(key_file)
            if not path.exists():
                raise GpgVerificationError(f"Trusted key file not found: {path}")
            result = self.gpg.import_keys(path.read_text(encoding="utf-8"))
            fingerprints.extend(result.fingerprints)

        for key in self.config.keys:
            result = self.gpg.import_keys(key)
            fingerprints.extend(result.fingerprints)

        if not fingerprints:
            raise GpgVerificationError("No trusted keys could be imported for verification")

        self._imported = True
        return fingerprints

    def _ensure_keys(self) -> None:
        if not self._imported:
            self.import_trusted_keys()

    def verify_detached(self, data: bytes, signature: bytes) -> bool:
        """Verify a detached OpenPGP signature over ``data``.

        Args:
            data: The signed payload (e.g. the raw ``repomd.xml`` bytes).
            signature: The detached signature (ASCII-armored or binary).

        Returns:
            True if the signature is valid AND made by a trusted key (and, when
            ``trusted_fingerprints`` is set, by a pinned key); False otherwise.
        """
        self._ensure_keys()

        # python-gnupg verifies a detached signature from a file against data.
        sig_file = Path(
            tempfile.mkstemp(prefix="sig-", suffix=".asc", dir=str(self._gnupg_home))[1]
        )
        try:
            sig_file.write_bytes(signature)
            verified = self.gpg.verify_data(str(sig_file), data)
        finally:
            sig_file.unlink(missing_ok=True)

        if not verified.valid:
            return False

        if self.config.trusted_fingerprints:
            return self._fingerprint_pinned(verified.fingerprint)
        return True

    def _fingerprint_pinned(self, fingerprint: str | None) -> bool:
        """Check the signing key fingerprint against the pin allow-list.

        Matches the full fingerprint exactly, or a long key-id suffix (>= 16
        hex chars). Short (32-bit) key ids are not accepted as they are trivial
        to forge. Empty pin entries are ignored.
        """
        if not fingerprint:
            return False
        actual = fingerprint.replace(" ", "").upper()
        for pinned in self.config.trusted_fingerprints:
            wanted = pinned.replace(" ", "").upper()
            if not wanted:
                continue
            if actual == wanted:
                return True
            if len(wanted) >= 16 and actual.endswith(wanted):
                return True
        return False
