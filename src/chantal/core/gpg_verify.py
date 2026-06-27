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

import logging
import os
import tempfile
from pathlib import Path
from types import TracebackType

import gnupg

from chantal.core.config import SignatureVerificationConfig

logger = logging.getLogger(__name__)


class GpgVerificationError(Exception):
    """Raised when verification cannot be performed (setup/import problems)."""


class SignatureVerificationError(Exception):
    """Raised to abort a sync when a signature check fails under a 'fail' policy."""


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

        # A signature is accepted if it's valid AND made by any key in the
        # keyring. With the default temp keyring that's only the configured trust
        # anchors. But a configured (possibly pre-existing/shared) gnupg_home may
        # already contain other keys, so without fingerprint pinning any of them
        # would be trusted. Warn so the operator pins via trusted_fingerprints.
        if config.gnupg_home and not config.trusted_fingerprints:
            logger.warning(
                "Signature verification uses a configured gnupg_home (%s) without "
                "trusted_fingerprints: any key already in that keyring will be "
                "trusted. Set verify.trusted_fingerprints to pin the upstream key.",
                config.gnupg_home,
            )

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

    def verify_clearsigned(self, blob: bytes) -> bytes | None:
        """Verify an inline-clearsigned document (e.g. APT ``InRelease``).

        Unlike a detached signature, a clearsigned document embeds both the
        payload and the signature. Verifying and then re-extracting the payload
        separately would be a TOCTOU gap, so this returns the exact bytes that
        were covered by the verified signature.

        Args:
            blob: The full ASCII-armored clearsigned document.

        Returns:
            The verified signed payload bytes if the signature is valid AND made
            by a trusted (and, when pinned, allow-listed) key; otherwise None.
        """
        self._ensure_keys()

        # For a sign-only (clearsigned) message, python-gnupg's ``decrypt``
        # performs signature verification and returns the canonical signed
        # payload in ``.data``.
        result = self.gpg.decrypt(blob)
        if not getattr(result, "valid", False):
            return None
        if self.config.trusted_fingerprints and not self._fingerprint_pinned(result.fingerprint):
            return None
        return bytes(result.data)

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
