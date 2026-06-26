from __future__ import annotations

"""
Pure-Python reader for the control metadata of a Debian ``.deb`` package.

A ``.deb`` is an ``ar`` archive containing ``debian-binary``, a
``control.tar.{gz,xz,zst}`` (the package metadata) and a ``data.tar.*`` (the
payload). The Python standard library has no ``ar`` reader, so we parse the
small, fixed ``ar`` header format directly, then decompress the control tarball
and read its ``./control`` member. No ``dpkg-deb`` binary is required.
"""

import tarfile
from collections.abc import Iterator
from io import BytesIO

from chantal.plugins.apt.parsers import parse_rfc822_stanza
from chantal.plugins.rpm.modules import decompress_bytes

_AR_MAGIC = b"!<arch>\n"
_AR_HEADER_SIZE = 60

# A real Debian control.tar is a few KB and virtually never exceeds a few
# hundred KB. Cap the decompressed size well above any legitimate value so a
# tiny but highly-compressible control.tar.* cannot expand into a memory bomb.
# (Only control.tar is decompressed here; the large data.tar is never touched.)
_MAX_CONTROL_TAR_BYTES = 16 * 1024 * 1024


class DebFormatError(Exception):
    """Raised when the bytes are not a parseable ``.deb`` package."""


def _iter_ar_members(data: bytes) -> Iterator[tuple[str, bytes]]:
    """Yield ``(name, payload)`` for each member of an ``ar`` archive."""
    if data[: len(_AR_MAGIC)] != _AR_MAGIC:
        raise DebFormatError("not a .deb file (bad ar magic)")
    offset = len(_AR_MAGIC)
    while offset + _AR_HEADER_SIZE <= len(data):
        header = data[offset : offset + _AR_HEADER_SIZE]
        if header[58:60] != b"`\n":
            raise DebFormatError("corrupt ar header (bad terminator)")
        # GNU ar pads names to 16 bytes and may append a trailing '/'.
        name = header[0:16].decode("ascii", "replace").rstrip().rstrip("/")
        try:
            size = int(header[48:58].decode("ascii").strip())
        except ValueError as exc:
            raise DebFormatError("corrupt ar header (bad size)") from exc
        start = offset + _AR_HEADER_SIZE
        # A negative size would move ``offset`` backwards and loop forever; an
        # oversized one would yield a silently-truncated payload. Rejecting both
        # also guarantees forward progress (offset advances by >= the header size
        # every iteration), so the loop always terminates.
        if size < 0:
            raise DebFormatError("corrupt ar header (negative size)")
        if start + size > len(data):
            raise DebFormatError("corrupt ar header (size exceeds archive)")
        payload = data[start : start + size]
        yield name, payload
        # Member data is padded to an even byte boundary.
        offset = start + size + (size & 1)


def _control_suffix(name: str) -> str:
    """Map a ``control.tar*`` member name to a ``decompress_bytes`` suffix."""
    if name.endswith(".gz"):
        return ".gz"
    if name.endswith(".xz"):
        return ".xz"
    if name.endswith(".zst"):
        return ".zst"
    if name.endswith(".bz2"):
        return ".bz2"
    return ""  # plain control.tar


def parse_deb_control(data: bytes) -> dict[str, str]:
    """Extract the control fields (``Package``, ``Version``, ...) from a ``.deb``.

    Args:
        data: The full ``.deb`` file bytes.

    Returns:
        The RFC822 control stanza as a field -> value dict.

    Raises:
        DebFormatError: If the bytes are not a parseable ``.deb``.
    """
    control_name: str | None = None
    control_bytes = b""
    for name, payload in _iter_ar_members(data):
        if name.startswith("control.tar"):
            control_name = name
            control_bytes = payload
            break
    if control_name is None:
        raise DebFormatError("no control.tar member found in .deb")

    try:
        tar_bytes = decompress_bytes(
            control_bytes,
            _control_suffix(control_name),
            max_output_bytes=_MAX_CONTROL_TAR_BYTES,
        )
        with tarfile.open(fileobj=BytesIO(tar_bytes)) as tar:
            member = next(
                (m for m in tar.getmembers() if m.name in ("./control", "control")),
                None,
            )
            if member is None:
                raise DebFormatError("no control file in control.tar")
            extracted = tar.extractfile(member)
            if extracted is None:
                raise DebFormatError("could not read control file from control.tar")
            text = extracted.read().decode("utf-8", "replace")
    except DebFormatError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalize any decode/tar error
        raise DebFormatError(f"could not read .deb control archive: {exc}") from exc

    fields = parse_rfc822_stanza(text)
    if not fields.get("Package"):
        raise DebFormatError("control file has no Package field")
    return fields
