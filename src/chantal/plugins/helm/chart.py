from __future__ import annotations

"""
Pure-Python reader for the ``Chart.yaml`` metadata of a Helm chart archive.

A packaged Helm chart is a gzipped tarball containing ``<chart>/Chart.yaml``
(plus ``templates/``, ``values.yaml`` and optionally ``charts/<dep>/...`` for
bundled subcharts). We read the top-level ``Chart.yaml`` directly with the
standard library; no ``helm`` binary is required.
"""

import tarfile
from pathlib import Path

import yaml


class ChartFormatError(Exception):
    """Raised when the bytes are not a parseable Helm chart archive."""


# A real Chart.yaml is a few KB. Cap the member well above any legitimate value
# so a crafted archive declaring a huge Chart.yaml cannot exhaust memory when we
# read it.
_MAX_CHART_YAML_BYTES = 1 * 1024 * 1024


def parse_chart_metadata(path: Path) -> dict:
    """Extract the ``Chart.yaml`` metadata from a packaged chart ``.tgz``.

    Args:
        path: Path to the ``.tgz`` chart archive.

    Returns:
        The parsed ``Chart.yaml`` as a dict.

    Raises:
        ChartFormatError: If the file is not a valid chart archive or has no
            usable ``Chart.yaml``.
    """
    try:
        with tarfile.open(path, "r:gz") as tar:
            members = [
                m for m in tar.getmembers() if m.isfile() and Path(m.name).name == "Chart.yaml"
            ]
            if not members:
                raise ChartFormatError("no Chart.yaml found in chart archive")
            # The top-level Chart.yaml is the shallowest ("<chart>/Chart.yaml");
            # deeper ones belong to bundled subcharts (charts/<dep>/Chart.yaml).
            member = min(members, key=lambda m: m.name.count("/"))
            # Reject an oversized Chart.yaml before reading it into memory so a
            # crafted archive cannot exhaust memory. ``extractfile().read()`` is
            # bounded by the (now-capped) member size.
            if member.size > _MAX_CHART_YAML_BYTES:
                raise ChartFormatError(
                    f"Chart.yaml is too large ({member.size} bytes; "
                    f"limit {_MAX_CHART_YAML_BYTES})"
                )
            extracted = tar.extractfile(member)
            if extracted is None:
                raise ChartFormatError("could not read Chart.yaml from chart archive")
            data = yaml.safe_load(extracted.read())
    except ChartFormatError:
        raise
    except tarfile.ReadError as exc:
        raise ChartFormatError(f"not a valid gzipped chart archive (.tgz): {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - normalize any tar/yaml error
        raise ChartFormatError(f"could not read chart archive: {exc}") from exc

    if not isinstance(data, dict) or not data.get("name") or not data.get("version"):
        raise ChartFormatError("Chart.yaml is missing required 'name'/'version' fields")
    return data
