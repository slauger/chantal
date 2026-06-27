# Contributing to Chantal

First off, thank you for considering contributing to Chantal!

## Project Status

**✅ Chantal is an actively maintained, released project (available on [PyPI](https://pypi.org/project/chantal/)).**

Contributions are welcome - bug reports, feature requests, documentation improvements, and pull requests.

## How to Contribute

### 1. Report Bugs and Request Features

Found a bug or have an idea? Open an issue:

- **Bug reports:** Include your Chantal version (`chantal --version`), repository type, config snippet (redact secrets), and the full error output.
- **Feature requests:** Open an issue with the `enhancement` label describing the use case.

**How:** Use the [GitHub Issues](https://github.com/slauger/chantal/issues) tracker.

### 2. Submit Pull Requests

Code contributions are welcome. Good first areas include new plugins (package formats), additional repository types, test coverage, and documentation.

1. Fork the repository and create a feature branch
2. Make your change with tests and type annotations
3. Run the local checks (`make lint`, `make pytest`) - see [Development Guidelines](#development-guidelines)
4. Open a pull request referencing any related issue

### 3. Share Your Experience

Have you worked with repository mirroring tools (apt-mirror, aptly, reposync, bandersnatch, devpi)? Production experience, pain points, scale challenges, and unusual use cases all help shape the roadmap.

**How:** Open a [GitHub Discussion](https://github.com/slauger/chantal/discussions) or an issue with the `research` label.

### 4. Improve the Documentation

Documentation lives in `docs/` (Sphinx) and is published to [GitHub Pages](https://slauger.github.io/chantal/). Corrections and additions are very welcome.

**How:** Edit the relevant files under `docs/` and open a pull request.

## Development Guidelines

### Code Quality Requirements

All code contributions must pass the following checks:

#### 1. Type Checking (mypy)

```bash
mypy src/chantal
```

**Strict typing rules:**
- ✅ All functions MUST have type annotations
- ✅ Use `| None` syntax (PEP 604) for Optional types
- ✅ Add None checks before accessing Optional attributes
- ✅ Use type narrowing with assertions after validation
- ❌ No `Any` types without documentation

**Example:**
```python
# ✅ Correct
def sync_repository(
    session: Session,
    repo_config: RepositoryConfig,
    storage: StorageManager | None = None
) -> SyncResult:
    if storage is None:
        storage = StorageManager(config)
    return SyncResult(success=True)

# ❌ Wrong - missing types, no None check
def sync_repository(session, repo_config, storage=None):
    return SyncResult(success=storage.ready)  # Crashes if storage is None!
```

#### 2. Code Formatting (black)

```bash
black src/ tests/
```

- Line length: 100 characters
- Auto-formatted before commit
- No manual formatting needed

#### 3. Linting (ruff)

```bash
ruff check src/ tests/
ruff check --fix src/  # Auto-fix issues
```

- No unused imports
- No undefined variables
- Follow PEP 8 naming

#### 4. Testing (pytest)

```bash
# Unit tests (fast, no external tools)
pytest tests/ -v -m "not e2e"

# End-to-end tests (build a fixture repo, sync, publish, and consume with a
# real client). These require docker and gpg; without them the docker/gpg-gated
# tests skip. Select a single plugin's e2e with its marker:
pytest tests/e2e -v -m "e2e and rpm"   # or apt / helm / apk
```

- Write tests for new features
- All tests must pass
- CI sets `CHANTAL_REQUIRE_DOCKER=1` / `CHANTAL_REQUIRE_GPG=1` so a missing tool
  **fails** (rather than silently skips) the e2e suite — install docker and gpg
  to run the real-client tests locally.

### Common Type Patterns

#### Optional Parameters with Defaults

```python
# ✅ Correct - type includes | None
def publish(
    packages: list[ContentItem],
    repository_files: list[RepositoryFile] | None = None
) -> None:
    if repository_files is None:
        repository_files = []

# ❌ Wrong - type mismatch
def publish(
    packages: list[ContentItem],
    repository_files: list[RepositoryFile] = None  # mypy error!
) -> None:
    pass
```

#### None Checks for Optional Objects

```python
# ✅ Correct
repository: Repository | None = session.query(Repository).get(repo_id)
if repository is not None:
    print(repository.name)
else:
    raise ValueError("Repository not found")

# ❌ Wrong - no None check
repository: Repository | None = session.query(Repository).get(repo_id)
print(repository.name)  # mypy error: Item "None" has no attribute "name"
```

#### Type Narrowing After Validation

```python
package = stanza.get("Package")  # str | None
version = stanza.get("Version")  # str | None

# Validate
if not all([package, version]):
    logger.warning("Missing fields")
    continue

# Type narrowing
assert package is not None
assert version is not None

# Now mypy knows these are str, not str | None
metadata = DebMetadata(package=package, version=version)
```

#### Index Operations

```python
# ✅ Correct
index: int | None = find_index(items, "updateinfo")
if index is not None:
    item = items[index]

# ❌ Wrong
index: int | None = find_index(items, "updateinfo")
item = items[index]  # mypy error: Invalid index type "int | None"
```

### Pre-commit Checklist

Before pushing code:

1. ✅ `black src/ tests/` - Format code
2. ✅ `ruff check --fix src/` - Fix linting
3. ✅ `mypy src/chantal` - Check types (must pass!)
4. ✅ `pytest tests/` - Run tests
5. ✅ All new functions have type annotations
6. ✅ All Optional parameters have None checks

### CI Pipeline

Pull requests must pass all checks:

- ✅ Black formatting
- ✅ Ruff linting
- ✅ **mypy type checking (strict, no failures allowed)**
- ✅ pytest tests

The CI pipeline will reject code with type errors.

## Communication

- **GitHub Issues**: Bug reports, feature requests
- **GitHub Discussions**: Questions, ideas, experience sharing
- **Email**: simon@lauger.de for private/security matters

## Code of Conduct

Be respectful, constructive, and professional. We're all here to build something useful.

Detailed Code of Conduct coming soon.

## License

By contributing to Chantal, you agree that your contributions will be licensed under the MIT License.

---

See [ROADMAP.md](ROADMAP.md) for current priorities and planned work.
