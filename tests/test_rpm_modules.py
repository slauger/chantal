"""Tests for filtered-mode modulemd (modules.yaml) handling."""

from __future__ import annotations

import yaml

from chantal.plugins.rpm.modules import (
    compress_bytes,
    decompress_bytes,
    filter_modules_yaml,
)

# A representative multi-document modules.yaml: one stream with four RPM
# artifacts, a defaults document, and a translations document.
_MODULES_YAML = """\
---
document: modulemd
version: 2
data:
  name: nodejs
  stream: "18"
  version: 8060020221108134933
  context: a51a2f8e
  arch: x86_64
  summary: Javascript runtime
  description: >-
    Node.js runtime.
  license:
    module:
      - MIT
  dependencies:
    - platform: [el9]
  profiles:
    common:
      rpms:
        - nodejs
  artifacts:
    rpms:
      - nodejs-1:18.12.1-1.module_el9.x86_64
      - nodejs-devel-1:18.12.1-1.module_el9.x86_64
      - npm-1:8.19.2-1.18.12.1.1.module_el9.x86_64
      - nodejs-docs-1:18.12.1-1.module_el9.noarch
...
---
document: modulemd-defaults
version: 1
data:
  module: nodejs
  stream: "18"
  profiles:
    "18": [common]
...
---
document: modulemd-translations
version: 1
data:
  module: nodejs
  modified: 201810081407
...
"""


def _docs(yaml_bytes: bytes) -> list[dict]:
    return list(yaml.safe_load_all(yaml_bytes.decode("utf-8")))


def _stream(docs: list[dict]) -> dict | None:
    return next((d for d in docs if d.get("document") == "modulemd"), None)


class TestFilterModulesYaml:
    def test_prunes_artifacts_to_available(self):
        available = {
            "nodejs-1:18.12.1-1.module_el9.x86_64",
            "npm-1:8.19.2-1.18.12.1.1.module_el9.x86_64",
        }
        out = filter_modules_yaml(_MODULES_YAML.encode("utf-8"), available)
        assert out is not None
        stream = _stream(_docs(out))
        assert stream is not None
        assert set(stream["data"]["artifacts"]["rpms"]) == available

    def test_preserves_non_artifact_fields(self):
        available = {"nodejs-1:18.12.1-1.module_el9.x86_64"}
        out = filter_modules_yaml(_MODULES_YAML.encode("utf-8"), available)
        stream = _stream(_docs(out))
        # Profiles, dependencies, license, context, etc. must survive untouched.
        assert stream["data"]["profiles"] == {"common": {"rpms": ["nodejs"]}}
        assert stream["data"]["dependencies"] == [{"platform": ["el9"]}]
        assert stream["data"]["license"] == {"module": ["MIT"]}
        assert stream["data"]["context"] == "a51a2f8e"

    def test_stream_pruned_to_zero_is_dropped_with_its_defaults(self):
        # None of the available packages belong to the module.
        available = {"unrelated-0:1.0-1.el9.x86_64"}
        out = filter_modules_yaml(_MODULES_YAML.encode("utf-8"), available)
        # Every document referenced the (now-gone) nodejs module -> nothing left.
        assert out is None

    def test_defaults_and_translations_kept_when_stream_survives(self):
        available = {"nodejs-1:18.12.1-1.module_el9.x86_64"}
        out = filter_modules_yaml(_MODULES_YAML.encode("utf-8"), available)
        docs = _docs(out)
        types = [d.get("document") for d in docs]
        assert "modulemd" in types
        assert "modulemd-defaults" in types
        assert "modulemd-translations" in types

    def test_epoch_is_significant(self):
        # Same NVRA but wrong epoch must NOT match.
        available = {"nodejs-0:18.12.1-1.module_el9.x86_64"}  # epoch 0, not 1
        out = filter_modules_yaml(_MODULES_YAML.encode("utf-8"), available)
        assert out is None

    def test_multiple_modules_independent(self):
        two = _MODULES_YAML + (
            "---\n"
            "document: modulemd\n"
            "version: 2\n"
            "data:\n"
            "  name: ruby\n"
            "  stream: '3.1'\n"
            "  artifacts:\n"
            "    rpms:\n"
            "      - ruby-0:3.1.2-1.module_el9.x86_64\n"
            "...\n"
            "---\n"
            "document: modulemd-defaults\n"
            "version: 1\n"
            "data:\n"
            "  module: ruby\n"
            "...\n"
        )
        # Keep only ruby; nodejs streams all vanish.
        available = {"ruby-0:3.1.2-1.module_el9.x86_64"}
        out = filter_modules_yaml(two.encode("utf-8"), available)
        docs = _docs(out)
        stream_names = {d["data"]["name"] for d in docs if d.get("document") == "modulemd"}
        default_modules = {
            d["data"]["module"] for d in docs if d.get("document") == "modulemd-defaults"
        }
        assert stream_names == {"ruby"}
        assert default_modules == {"ruby"}

    def test_stream_without_artifacts_is_kept(self):
        doc = "---\ndocument: modulemd\nversion: 2\ndata:\n  name: empty\n  stream: x\n...\n"
        out = filter_modules_yaml(doc.encode("utf-8"), set())
        assert out is not None
        assert _stream(_docs(out))["data"]["name"] == "empty"


class TestCompressionHelpers:
    def test_roundtrip_gz(self):
        data = b"document: modulemd\n" * 50
        assert decompress_bytes(compress_bytes(data, ".gz"), ".gz") == data

    def test_roundtrip_zst(self):
        data = b"document: modulemd\n" * 50
        assert decompress_bytes(compress_bytes(data, ".zst"), ".zst") == data

    def test_roundtrip_uncompressed(self):
        data = b"document: modulemd\n"
        assert decompress_bytes(compress_bytes(data, ".yaml"), ".yaml") == data
