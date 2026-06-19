"""
Tests for the configuration JSON Schema and the bundled example configs.

These guard against two kinds of drift:
- The committed JSON Schema going stale relative to the config models.
- Example configs under ``examples/`` no longer validating against the schema.
"""

import json
from pathlib import Path

import pytest
import yaml

from chantal.core.config import GlobalConfig, generate_json_schema

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_FILE = REPO_ROOT / "docs" / "schema" / "chantal-config.schema.json"
EXAMPLE_FILES = sorted((REPO_ROOT / "examples").rglob("*.yaml"))


def test_committed_schema_is_up_to_date():
    """The committed schema file must match the schema generated from the models.

    If this fails, regenerate it with: ``chantal schema -o docs/schema/chantal-config.schema.json``
    """
    committed = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    assert committed == generate_json_schema(), (
        "docs/schema/chantal-config.schema.json is out of date; regenerate with "
        "'chantal schema -o docs/schema/chantal-config.schema.json'"
    )


def test_examples_exist():
    """Sanity check that example configs are discovered."""
    assert EXAMPLE_FILES, "no example configs found under examples/"


@pytest.mark.parametrize("example", EXAMPLE_FILES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_example_config_validates(example):
    """Every YAML document in every example config validates against the schema."""
    with open(example, encoding="utf-8") as fh:
        documents = list(yaml.safe_load_all(fh))

    validated = 0
    for index, doc in enumerate(documents):
        if not doc:
            continue
        try:
            GlobalConfig(**doc)
        except Exception as exc:  # noqa: BLE001 - surface the file + doc index
            pytest.fail(f"{example} (document {index}) is invalid:\n{exc}")
        validated += 1

    assert validated > 0, f"{example} contained no config documents"
