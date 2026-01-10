# Chantal Documentation

This directory contains the Sphinx documentation for Chantal.

## Building Locally

### Prerequisites

```bash
pip install sphinx sphinx-rtd-theme sphinx-autobuild myst-parser linkify-it-py
```

### Build HTML Documentation

```bash
cd docs
make html
```

Output will be in `_build/html/`. Open `_build/html/index.html` in your browser.

### Live Reload (Development)

```bash
cd docs
sphinx-autobuild . _build/html
```

Then open http://127.0.0.1:8000 in your browser. Pages will auto-reload on changes.

### Clean Build

```bash
cd docs
make clean
make html
```

## Documentation Structure

```
docs/
├── index.rst                    # Main documentation page
├── user-guide/                  # User guides
│   ├── installation.md
│   ├── quickstart.md
│   ├── cli-commands.md
│   ├── views.md
│   └── workflows.md
├── configuration/               # Configuration guides
│   ├── overview.md
│   ├── repositories.md
│   ├── filters.md
│   └── ssl-authentication.md
├── architecture/                # Architecture documentation
│   ├── overview.md
│   ├── content-addressed-storage.md
│   ├── database-schema.md
│   └── plugin-system.md
├── plugins/                     # Plugin documentation
│   ├── overview.md
│   ├── rpm-plugin.md
│   └── custom-plugins.md
└── api/                         # API reference (auto-generated)
    └── modules.rst
```

## GitHub Pages Deployment

Documentation is automatically built and deployed to GitHub Pages on every push to `main` that modifies:
- `docs/**` files
- `src/chantal/**/*.py` files (for API docs)
- `.github/workflows/docs.yml`

**Workflow:** `.github/workflows/docs.yml`

**URL:** https://slauger.github.io/chantal/

## Format

- **Markdown** (`.md`) - Used for most documentation (via MyST parser)
- **reStructuredText** (`.rst`) - Used for index and API reference

## MyST Markdown Features

Chantal's documentation uses MyST (Markedly Structured Text) parser, which extends standard Markdown:

```markdown
# Standard Markdown
**Bold**, *italic*, `code`, [links](url)

# MyST Extensions
:::{note}
This is a note
:::

:::{warning}
This is a warning
:::

```python
# Code blocks with syntax highlighting
def hello():
    print("Hello")
```
