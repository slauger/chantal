# Configuration JSON Schema

`chantal-config.schema.json` is a [JSON Schema](https://json-schema.org/)
(draft 2020-12) for Chantal's `config.yaml`. It is generated from the
configuration models, so it always matches what Chantal actually validates.

JSON Schema works for YAML too, so editors can use it to **validate** and
**autocomplete** your configuration.

## Regenerating

The schema is generated from the Pydantic models. After changing any config
model, regenerate it:

```bash
chantal schema -o docs/schema/chantal-config.schema.json
```

A test (`tests/test_schema.py`) fails in CI if the committed schema is stale, and
also validates every example under `examples/` against it.

## Editor integration

### Per-file modeline (works in VS Code, JetBrains, neovim, …)

Add this as the first line of your config file:

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/slauger/chantal/main/docs/schema/chantal-config.schema.json
```

See `examples/config/config.yaml` for a working example.

### VS Code workspace mapping

Alternatively, map the schema to your config files in `.vscode/settings.json`
(requires the **YAML** extension by Red Hat):

```json
{
  "yaml.schemas": {
    "./docs/schema/chantal-config.schema.json": [
      "config.yaml",
      "conf.d/*.yaml",
      "examples/**/*.yaml"
    ]
  }
}
```

## Standalone validation

You can also validate a config with any JSON Schema tooling, e.g.
[`check-jsonschema`](https://github.com/python-jsonschema/check-jsonschema):

```bash
check-jsonschema --schemafile docs/schema/chantal-config.schema.json config.yaml
```
