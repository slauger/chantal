from __future__ import annotations

"""
RSA signing for APK repository indexes (``APKINDEX.tar.gz``).

APK does not use GPG. A signed ``APKINDEX.tar.gz`` is the concatenation of two
gzip members (apk reads them as one continuous tar stream):

1. A *cut* tar (no trailing zero blocks) holding a single file
   ``.SIGN.RSA256.<keyname>`` whose content is the RSA signature.
2. The unsigned ``APKINDEX.tar.gz`` (the index segment).

The signature is an RSA PKCS#1 v1.5 signature (SHA-256) over the raw bytes of
the unsigned index segment - exactly what ``abuild-sign`` produces. The public
key is published in PEM form; clients install it into ``/etc/apk/keys/``.

Configuration reuses :class:`chantal.core.config.GpgConfig`:
- ``key_file``        - path to an RSA private key (PEM)
- ``generate_key``    - generate an RSA keypair on demand
- ``passphrase`` / ``passphrase_file`` - private key passphrase
- ``public_key_name`` - published public key filename (defaults to
  ``<key_name>.rsa.pub``)
"""

import gzip
import io
import math
import tarfile
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from chantal.core.config import GpgConfig

_TAR_BLOCK = 512


class ApkSigningError(Exception):
    """Raised when an APK signing operation fails."""


class ApkSigner:
    """Sign ``APKINDEX.tar.gz`` with an RSA key (abuild-compatible)."""

    def __init__(self, config: GpgConfig, *, default_name: str | None = None):
        """Initialize the signer.

        Args:
            config: Signing configuration (GpgConfig, reused for APK).
            default_name: Fallback base name for a generated key / public key
                filename (typically the repository id).
        """
        self.config = config
        self._default_name = default_name
        self._passphrase = config.read_passphrase()
        self._private_key: RSAPrivateKey | None = None
        self._key_name: str | None = None

    @property
    def key_name(self) -> str:
        """Public key filename used in the ``.SIGN.RSA256.<name>`` entry."""
        if self._key_name is None:
            self._load_key()
        assert self._key_name is not None
        return self._key_name

    def _private(self) -> RSAPrivateKey:
        if self._private_key is None:
            self._load_key()
        assert self._private_key is not None
        return self._private_key

    def _load_key(self) -> None:
        """Load the RSA private key (from file) or generate one."""
        if self.config.key_file:
            key_path = Path(self.config.key_file)
            if not key_path.exists():
                raise ApkSigningError(f"APK signing key file not found: {key_path}")
            password = self._passphrase.encode("utf-8") if self._passphrase else None
            try:
                loaded = load_pem_private_key(key_path.read_bytes(), password=password)
            except Exception as exc:  # noqa: BLE001
                raise ApkSigningError(f"Failed to load RSA key from {key_path}: {exc}") from exc
            if not isinstance(loaded, RSAPrivateKey):
                raise ApkSigningError(f"Key in {key_path} is not an RSA private key")
            self._private_key = loaded
            self._key_name = self._resolve_public_name(default_base=key_path.stem)
        elif self.config.generate_key:
            self._private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            self._key_name = self._resolve_public_name(default_base=None)
        else:
            raise ApkSigningError("No APK signing key configured (set key_file or generate_key).")

    def _resolve_public_name(self, *, default_base: str | None) -> str:
        """Resolve the published public key filename.

        ``GpgConfig.public_key_name`` defaults to ``key.gpg`` (the GPG default),
        which is meaningless for APK; treat that as unset and derive a
        ``<base>.rsa.pub`` name instead.
        """
        configured = self.config.public_key_name
        if configured and configured != "key.gpg":
            return configured
        base = default_base or self.config.key_name or self._default_name or "chantal"
        # Keep the filename safe and apk-friendly.
        base = "".join(c if c.isalnum() or c in "-._" else "-" for c in base)
        return f"{base}.rsa.pub"

    def sign_index(self, unsigned_index: bytes) -> bytes:
        """Sign an unsigned ``APKINDEX.tar.gz`` byte string.

        Args:
            unsigned_index: The bytes of the unsigned ``APKINDEX.tar.gz``.

        Returns:
            The signed ``APKINDEX.tar.gz`` bytes (signature segment + index).
        """
        signature = self._private().sign(unsigned_index, padding.PKCS1v15(), hashes.SHA256())
        entry_name = f".SIGN.RSA256.{self.key_name}"
        signature_segment = self._cut_tar_gz(entry_name, signature)
        return signature_segment + unsigned_index

    @staticmethod
    def _cut_tar_gz(name: str, data: bytes) -> bytes:
        """Build a gzip member holding a single *cut* tar entry.

        "Cut" means the trailing zero blocks are removed so apk reads the next
        gzip member as a continuation of the same tar stream (cf.
        ``abuild-tar --cut``).
        """
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = 0
            tar.addfile(info, io.BytesIO(data))

        # Keep only header (one block) + data padded to the block size.
        padded = math.ceil(len(data) / _TAR_BLOCK) * _TAR_BLOCK
        cut = buf.getvalue()[: _TAR_BLOCK + padded]

        out = io.BytesIO()
        with gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as gz:
            gz.write(cut)
        return out.getvalue()

    def export_public_key(self) -> bytes:
        """Export the RSA public key in PEM form for client distribution."""
        if self.config.public_key_file:
            return Path(self.config.public_key_file).read_bytes()
        return (
            self._private()
            .public_key()
            .public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )

    def sign_index_file(self, index_path: Path, repo_root: Path | None = None) -> dict[str, Path]:
        """Sign an ``APKINDEX.tar.gz`` in place and publish the public key.

        Args:
            index_path: Path to the unsigned ``APKINDEX.tar.gz`` (overwritten).
            repo_root: Repository root where the public key is published. If
                None, the public key is not exported.

        Returns:
            Mapping of output name to the written path.
        """
        signed = self.sign_index(index_path.read_bytes())
        index_path.write_bytes(signed)
        outputs: dict[str, Path] = {"APKINDEX.tar.gz": index_path}

        if repo_root is not None:
            pubkey_path = repo_root / self.key_name
            pubkey_path.write_bytes(self.export_public_key())
            outputs[self.key_name] = pubkey_path

        return outputs
