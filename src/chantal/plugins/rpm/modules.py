"""
Filtering of AppStream modularity metadata (``modules.yaml`` / modulemd).

``modules.yaml`` is a multi-document YAML stream. Only ``modulemd`` (stream)
documents bind a module stream to concrete RPMs, via ``data.artifacts.rpms`` --
a list of full NEVRA strings ``name-epoch:version-release.arch`` (the epoch is
always explicit). The other document types (``modulemd-defaults``,
``modulemd-translations``, ``modulemd-obsoletes``) are keyed by module *name*,
not by RPM.

When a repository is mirrored in *filtered* mode the published package set is a
subset of upstream, so the artifact lists must be pruned to the surviving
packages -- otherwise the published modules document references RPMs that are no
longer present, breaking downstream ``dnf module`` operations.

This module is intentionally free of any I/O so the filtering logic can be unit
tested in isolation; the compression helpers operate on bytes.
"""

from __future__ import annotations

import bz2
import gzip
import logging
import lzma
import zlib

import yaml

logger = logging.getLogger(__name__)


class DecompressionLimitError(ValueError):
    """Raised when decompressed output exceeds the requested ``max_output_bytes``."""


# modulemd stream document -- the only type that binds RPM artifacts.
_STREAM_DOCUMENT = "modulemd"

# Documents scoped to a module *name* rather than to individual RPMs.
_MODULE_SCOPED_DOCUMENTS = {
    "modulemd-defaults",
    "modulemd-translations",
    "modulemd-obsoletes",
}


def filter_modules_yaml(yaml_bytes: bytes, available_nevras: set[str]) -> bytes | None:
    """Prune modulemd documents to the available package set.

    For each ``modulemd`` stream document the ``data.artifacts.rpms`` list is
    intersected with ``available_nevras``. A stream whose artifacts are entirely
    absent is dropped. Module-scoped documents (defaults/translations/obsoletes)
    are kept only while their module still has a surviving stream.

    Args:
        yaml_bytes: Raw (decompressed) ``modules.yaml`` content.
        available_nevras: Published-package NEVRAs in modulemd form
            (``name-epoch:version-release.arch``, epoch always explicit).

    Returns:
        The filtered multi-document YAML as bytes, or ``None`` if no document
        survives (the caller should then drop ``modules.yaml`` entirely).
    """
    documents = list(yaml.safe_load_all(yaml_bytes.decode("utf-8")))

    surviving_modules: set[str] = set()
    stream_survives: dict[int, bool] = {}

    # Pass 1: prune stream artifacts and record which modules keep a stream.
    for index, doc in enumerate(documents):
        if not isinstance(doc, dict) or doc.get("document") != _STREAM_DOCUMENT:
            continue

        data = doc.get("data")
        if not isinstance(data, dict):
            stream_survives[index] = False
            continue

        artifacts = data.get("artifacts")
        if isinstance(artifacts, dict) and isinstance(artifacts.get("rpms"), list):
            # Only the ``artifacts.rpms`` NEVRA list is pruned. The rarely-used
            # ``artifacts.rpm-map`` form is left untouched.
            kept = [nevra for nevra in artifacts["rpms"] if nevra in available_nevras]
            artifacts["rpms"] = kept
            survives = bool(kept)
        else:
            # No RPM artifact list to prune -- keep the stream as-is.
            survives = True

        stream_survives[index] = survives
        name = data.get("name")
        if survives and isinstance(name, str):
            surviving_modules.add(name)

    # Pass 2: rebuild the document stream in its original order.
    result: list[object] = []
    for index, doc in enumerate(documents):
        if not isinstance(doc, dict):
            # Preserve anything we do not understand.
            result.append(doc)
            continue

        doc_type = doc.get("document")
        if doc_type == _STREAM_DOCUMENT:
            if stream_survives.get(index):
                result.append(doc)
        elif doc_type in _MODULE_SCOPED_DOCUMENTS:
            data = doc.get("data")
            module = data.get("module") if isinstance(data, dict) else None
            # Drop only when we can positively tie it to a vanished module.
            if not isinstance(module, str) or module in surviving_modules:
                result.append(doc)
        else:
            result.append(doc)

    if not result:
        return None

    dumped = yaml.safe_dump_all(
        result,
        default_flow_style=False,
        sort_keys=False,
        explicit_start=True,
        allow_unicode=True,
    )
    return dumped.encode("utf-8")


def _bounded(out: bytes, finished: bool, limit: int) -> bytes:
    """Reject output that is over ``limit`` or not yet exhausted at ``limit``."""
    if len(out) > limit or not finished:
        raise DecompressionLimitError(
            f"decompressed size exceeds {limit} bytes (decompression bomb?)"
        )
    return out


def decompress_bytes(data: bytes, suffix: str, *, max_output_bytes: int | None = None) -> bytes:
    """Decompress ``data`` according to a file-name ``suffix`` (e.g. ``.gz``).

    When ``max_output_bytes`` is given the output is bounded incrementally and a
    :class:`DecompressionLimitError` is raised as soon as it would exceed the
    limit, so a small but highly-compressible input cannot expand into a memory
    bomb. ``None`` (the default) decompresses without a cap.
    """
    if max_output_bytes is None:
        if suffix == ".gz":
            return gzip.decompress(data)
        if suffix == ".xz":
            return lzma.decompress(data)
        if suffix == ".bz2":
            return bz2.decompress(data)
        if suffix == ".zst":
            import io

            import zstandard as zstd

            # Use the streaming reader: the one-shot decompress() requires the
            # frame to embed its content size, which streaming producers omit.
            return zstd.ZstdDecompressor().stream_reader(io.BytesIO(data)).read()
        return data

    limit = max_output_bytes
    if suffix == ".gz":
        decomp = zlib.decompressobj(wbits=31)  # 31 = gzip header
        out = decomp.decompress(data, limit + 1)
        return _bounded(out, decomp.eof, limit)
    if suffix == ".xz":
        xz = lzma.LZMADecompressor()
        out = xz.decompress(data, max_length=limit + 1)
        return _bounded(out, xz.eof, limit)
    if suffix == ".bz2":
        bz = bz2.BZ2Decompressor()
        out = bz.decompress(data, max_length=limit + 1)
        return _bounded(out, bz.eof, limit)
    if suffix == ".zst":
        import io

        import zstandard as zstd

        reader = zstd.ZstdDecompressor().stream_reader(io.BytesIO(data))
        out = reader.read(limit + 1)
        # A well-formed frame shorter than the cap stops at EOF; if we filled the
        # whole (limit + 1) budget there is at least one byte too many.
        return _bounded(out, len(out) <= limit, limit)
    if len(data) > limit:
        raise DecompressionLimitError(f"size exceeds {limit} bytes")
    return data


def compress_bytes(data: bytes, suffix: str) -> bytes:
    """Compress ``data`` according to a file-name ``suffix`` (e.g. ``.gz``)."""
    if suffix == ".gz":
        return gzip.compress(data)
    if suffix == ".xz":
        return lzma.compress(data)
    if suffix == ".bz2":
        return bz2.compress(data)
    if suffix == ".zst":
        import zstandard as zstd

        return zstd.ZstdCompressor().compress(data)
    return data
