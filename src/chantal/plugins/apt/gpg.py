from __future__ import annotations

"""
GPG signing support for APT repository metadata.

In filtered mode the APT publisher regenerates the ``Release`` file, which
invalidates the upstream GPG signatures. This module signs the regenerated
``Release`` so that clients can verify the repository without ``[trusted=yes]``:

- ``InRelease``   - inline (clearsigned) ``Release``
- ``Release.gpg`` - detached ASCII-armored signature of ``Release``
- ``key.gpg``     - exported public key for client distribution

The implementation wraps the ``gpg`` binary through the ``python-gnupg``
library. The signing key can be imported from a file, referenced by key ID in
an existing keyring, or generated on demand.
"""

import os
import tempfile
from pathlib import Path
from types import TracebackType

import gnupg

from chantal.core.config import GpgConfig


class GpgSigningError(Exception):
    """Raised when a GPG operation (import, generate, sign, export) fails."""


class GpgSigner:
    """Sign APT ``Release`` metadata using a configured GPG key.

    The signer lazily resolves the signing key on first use. When no
    ``gnupg_home`` is configured, an isolated temporary keyring is created and
    removed when the signer is closed.
    """

    def __init__(self, config: GpgConfig, *, default_name: str | None = None):
        """Initialize the signer.

        Args:
            config: GPG configuration.
            default_name: Fallback "real name" used when generating a key and
                ``config.key_name`` is not set (typically the repository name).
        """
        self.config = config
        self._default_name = default_name
        self._key_id: str | None = None
        self._passphrase = config.read_passphrase()

        # Resolve the keyring location. Use a private temporary directory when
        # none is configured so generated keys never leak into the user keyring.
        self._tempdir: tempfile.TemporaryDirectory[str] | None = None
        if config.gnupg_home:
            self._gnupg_home = Path(config.gnupg_home)
            self._gnupg_home.mkdir(parents=True, exist_ok=True)
        else:
            self._tempdir = tempfile.TemporaryDirectory(prefix="chantal-gpg-")
            self._gnupg_home = Path(self._tempdir.name)

        # GnuPG requires the home directory to be private.
        os.chmod(self._gnupg_home, 0o700)

        self.gpg = gnupg.GPG(gnupghome=str(self._gnupg_home))
        self.gpg.encoding = "utf-8"

    def __enter__(self) -> GpgSigner:
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

    @property
    def key_id(self) -> str:
        """Fingerprint of the signing key (resolved lazily)."""
        if self._key_id is None:
            self._key_id = self._resolve_key()
        return self._key_id

    def _resolve_key(self) -> str:
        """Resolve the signing key, importing or generating it if necessary.

        Returns:
            The fingerprint of the signing key.

        Raises:
            GpgSigningError: If no usable key can be resolved.
        """
        # 1. Import a private key from a file.
        if self.config.key_file:
            key_path = Path(self.config.key_file)
            if not key_path.exists():
                raise GpgSigningError(f"GPG key file not found: {key_path}")
            result = self.gpg.import_keys(key_path.read_text(encoding="utf-8"))
            if not result.fingerprints:
                raise GpgSigningError(f"Failed to import GPG key from {key_path}: {result.stderr}")
            # Prefer an explicitly configured key_id, else the first imported key.
            if self.config.key_id:
                return self._find_secret_key(self.config.key_id)
            return str(result.fingerprints[0])

        # 2. Use a key already present in the keyring.
        if self.config.key_id:
            return self._find_secret_key(self.config.key_id)

        # 3. Generate a fresh keypair.
        if self.config.generate_key:
            return self._generate_key()

        raise GpgSigningError(
            "No GPG key source configured (set key_file, key_id, or generate_key)."
        )

    def _find_secret_key(self, identifier: str) -> str:
        """Find a secret key by key ID, fingerprint, or uid substring.

        Args:
            identifier: Key ID, fingerprint, or uid fragment to match.

        Returns:
            The matching key's fingerprint.

        Raises:
            GpgSigningError: If no secret key matches.
        """
        identifier_lower = identifier.lower()
        for key in self.gpg.list_keys(secret=True):
            candidates = {
                str(key.get("keyid", "")).lower(),
                str(key.get("fingerprint", "")).lower(),
            }
            if identifier_lower in candidates or any(
                identifier_lower in uid.lower() for uid in key.get("uids", [])
            ):
                return str(key["fingerprint"])
        raise GpgSigningError(f"Signing key '{identifier}' not found in keyring {self._gnupg_home}")

    def _generate_key(self) -> str:
        """Generate a new RSA signing keypair in the keyring.

        Returns:
            The fingerprint of the generated key.

        Raises:
            GpgSigningError: If key generation fails.
        """
        name = self.config.key_name or self._default_name or "Chantal Repository Signing Key"
        email = self.config.key_email or "chantal@localhost"

        input_data = self.gpg.gen_key_input(
            name_real=name,
            name_email=email,
            key_type="RSA",
            key_length=3072,
            expire_date=0,
            passphrase=self._passphrase or "",
            no_protection=not self._passphrase,
        )
        key = self.gpg.gen_key(input_data)
        if not key.fingerprint:
            raise GpgSigningError(f"Failed to generate GPG key: {key.stderr}")
        return str(key.fingerprint)

    def clearsign(self, data: bytes) -> bytes:
        """Produce a clearsigned (inline) signature for InRelease.

        Args:
            data: The Release file contents.

        Returns:
            The clearsigned message as bytes.
        """
        signed = self.gpg.sign(
            data,
            keyid=self.key_id,
            passphrase=self._passphrase,
            clearsign=True,
            detach=False,
        )
        if not signed.data:
            raise GpgSigningError(f"Failed to clearsign Release: {signed.stderr}")
        return bytes(signed.data)

    def detach_sign(self, data: bytes) -> bytes:
        """Produce a detached ASCII-armored signature for Release.gpg.

        Args:
            data: The Release file contents.

        Returns:
            The detached signature as bytes.
        """
        signed = self.gpg.sign(
            data,
            keyid=self.key_id,
            passphrase=self._passphrase,
            clearsign=False,
            detach=True,
        )
        if not signed.data:
            raise GpgSigningError(f"Failed to detach-sign Release: {signed.stderr}")
        return bytes(signed.data)

    def export_public_key(self) -> bytes:
        """Export the public signing key (ASCII-armored) for client distribution.

        Returns:
            The ASCII-armored public key as bytes.
        """
        if self.config.public_key_file:
            return Path(self.config.public_key_file).read_bytes()
        armored: str = self.gpg.export_keys(self.key_id)
        if not armored:
            raise GpgSigningError(f"Failed to export public key {self.key_id}")
        return armored.encode("utf-8")

    def sign_release(self, release_path: Path, repo_root: Path | None = None) -> dict[str, Path]:
        """Sign a Release file, writing InRelease, Release.gpg, and the public key.

        Args:
            release_path: Path to the existing ``Release`` file.
            repo_root: Repository root where the public key is published. If
                None, the public key is not exported.

        Returns:
            Mapping of output name to the path that was written.
        """
        release_data = release_path.read_bytes()
        outputs: dict[str, Path] = {}

        inrelease_path = release_path.parent / "InRelease"
        inrelease_path.write_bytes(self.clearsign(release_data))
        outputs["InRelease"] = inrelease_path

        release_gpg_path = release_path.parent / "Release.gpg"
        release_gpg_path.write_bytes(self.detach_sign(release_data))
        outputs["Release.gpg"] = release_gpg_path

        if repo_root is not None:
            pubkey_path = repo_root / self.config.public_key_name
            pubkey_path.write_bytes(self.export_public_key())
            outputs[self.config.public_key_name] = pubkey_path

        return outputs
