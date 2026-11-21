"""Streaming processing of large RPM repository metadata XML.

primary/filelists/other/updateinfo of large repositories (e.g. RHEL BaseOS,
AppStream) decompress to more than a gigabyte. Building a full ElementTree of
them needs several times that in memory, so these helpers walk the document
with ``iterparse`` and release every item (``<package>``/``<update>``) once it
has been handled. Memory then depends on the largest single item, not on the
size of the repository.
"""

from __future__ import annotations

import gzip
import os
import shutil
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import BinaryIO, cast
from xml.sax.saxutils import escape, quoteattr

from chantal.plugins.rpm.compression import open_compressed_writer, open_decompressed

_XML_NS = "http://www.w3.org/XML/1998/namespace"


def local_name(tag: str) -> str:
    """Return ``tag`` without its ``{namespace}`` part."""
    return tag.rsplit("}", 1)[-1]


def iter_items(stream: BinaryIO, item: str) -> Iterator[ET.Element]:
    """Yield each direct child of the root whose local name is ``item``.

    The element is complete when yielded and is cleared as soon as the caller
    asks for the next one, so callers must copy what they need out of it.
    Matching by local name accepts both namespaced and plain documents.
    """
    depth = 0
    root: ET.Element | None = None
    for event, elem in ET.iterparse(stream, events=("start", "end")):
        if event == "start":
            depth += 1
            if root is None:
                root = elem
            continue
        depth -= 1
        if depth != 1 or root is None:
            continue
        if local_name(elem.tag) == item:
            yield elem
        elem.clear()
        del root[:]


def filter_metadata_file(
    src: Path,
    dest: Path,
    item: str,
    keep: Callable[[ET.Element], bool],
    *,
    count_attr: str | None = "packages",
    compression_level: int | None = None,
) -> tuple[int, int]:
    """Copy the metadata file ``src`` to ``dest``, keeping only some items.

    ``keep`` is called with every ``item`` element (it may modify it, e.g. to
    rewrite a ``<location>``) and returns whether it is written to ``dest``.
    Other direct children of the root are copied unchanged. The root's
    ``count_attr`` attribute, if given, is set to the number of kept items.

    Compression of ``src`` and ``dest`` follows their file suffixes. ``dest``
    is replaced atomically, so it may be the same path as ``src`` (a published
    hardlink to the pool is replaced, not written through).

    Returns:
        ``(total_items, kept_items)``
    """
    # The kept items are staged (lightly compressed: a full mirror-mode
    # filelists is ~2 GB uncompressed) because the root's count attribute is
    # only known once the whole document has been read.
    body_path = dest.with_name(f".{dest.name}.body.tmp")
    out_path = dest.with_name(f".{dest.name}.tmp")
    try:
        with open_decompressed(src) as stream, gzip.open(body_path, "wb", compresslevel=1) as w:
            root_tag, root_attrib, namespaces, total, kept = _write_body(
                stream, cast(BinaryIO, w), item, keep
            )
        with gzip.open(body_path, "rb") as body:
            with open_compressed_writer(out_path, dest.suffix, compression_level) as out:
                out.write(
                    _render_header(root_tag, root_attrib, namespaces, count_attr, kept).encode(
                        "utf-8"
                    )
                )
                shutil.copyfileobj(body, out, 1024 * 1024)
                out.write(f"</{_qname(root_tag, namespaces)}>\n".encode())
        os.replace(out_path, dest)
    finally:
        body_path.unlink(missing_ok=True)
        out_path.unlink(missing_ok=True)
    return total, kept


def _write_body(
    stream: BinaryIO,
    body: BinaryIO,
    item: str,
    keep: Callable[[ET.Element], bool],
) -> tuple[str, dict[str, str], list[tuple[str, str]], int, int]:
    """Serialize the kept root children of ``stream`` into ``body``.

    Returns the root tag, the root attributes, the namespace declarations made
    on the root (as ``(prefix, uri)``), and the total and kept item counts.
    """
    depth = 0
    root: ET.Element | None = None
    root_attrib: dict[str, str] = {}
    namespaces: list[tuple[str, str]] = []
    total = kept = 0

    for event, data in ET.iterparse(stream, events=("start-ns", "start", "end")):
        if event == "start-ns":
            if root is None:
                # typeshed types every iterparse item as an Element; for
                # "start-ns" it is a (prefix, uri) tuple.
                namespaces.append(cast(tuple[str, str], data))
            continue
        elem = data
        if event == "start":
            depth += 1
            if root is None:
                root = elem
                # Copied now: the root is emptied while streaming.
                root_attrib = dict(elem.attrib)
                # Serialize children with the document's own prefixes (dnf and
                # libsolv match e.g. "rpm:entry" literally, not ns0:entry).
                for ns_prefix, ns_uri in namespaces:
                    ET.register_namespace(ns_prefix, ns_uri)
            continue

        depth -= 1
        if depth != 1 or root is None:
            continue
        is_item = local_name(elem.tag) == item
        if is_item:
            total += 1
        if not is_item or keep(elem):
            if is_item:
                kept += 1
            elem.tail = None
            text = _strip_root_namespaces(ET.tostring(elem, encoding="unicode"), namespaces)
            body.write(f"{text}\n".encode())
        elem.clear()
        del root[:]

    if root is None:
        raise ValueError("empty XML document")
    return root.tag, root_attrib, namespaces, total, kept


def _strip_root_namespaces(text: str, namespaces: list[tuple[str, str]]) -> str:
    """Drop the root's namespace declarations that tostring() repeats on a child."""
    end = text.index(">")
    head = text[:end]
    for prefix, uri in namespaces:
        attr = "xmlns" if not prefix else f"xmlns:{prefix}"
        head = head.replace(f' {attr}="{escape(uri, {chr(34): "&quot;"})}"', "", 1)
    return head + text[end:]


def _qname(tag: str, namespaces: list[tuple[str, str]]) -> str:
    """Render a ``{uri}local`` name with the prefix the document declared."""
    if not tag.startswith("{"):
        return tag
    uri, local = tag[1:].split("}", 1)
    if uri == _XML_NS:
        return f"xml:{local}"  # e.g. xml:lang; predeclared, never declared on the root
    for prefix, declared in namespaces:
        if declared == uri:
            return f"{prefix}:{local}" if prefix else local
    raise ValueError(f"namespace {uri!r} is not declared on the root element")


def _render_header(
    root_tag: str,
    root_attrib: dict[str, str],
    namespaces: list[tuple[str, str]],
    count_attr: str | None,
    kept: int,
) -> str:
    attrs = dict(root_attrib)
    if count_attr is not None:
        attrs[count_attr] = str(kept)
    parts = [f"<{_qname(root_tag, namespaces)}"]
    for prefix, uri in namespaces:
        parts.append(f" xmlns:{prefix}={quoteattr(uri)}" if prefix else f" xmlns={quoteattr(uri)}")
    for name, value in attrs.items():
        parts.append(f" {_qname(name, namespaces)}={quoteattr(value)}")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + "".join(parts) + ">\n"
