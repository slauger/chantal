# Contributing to Chantal

First off, thank you for considering contributing to Chantal!

## Project Status

**⚠️ Chantal is currently in the Research & Design phase.**

We're not ready for code contributions yet, but there are other valuable ways to contribute right now.

## How to Contribute (Current Phase)

### 1. Share Your Experience

Have you worked with repository mirroring tools? We'd love to hear about:

- **Production experience** with apt-mirror, aptly, reposync, bandersnatch, or devpi
- **Pain points** you've encountered
- **Scale challenges** (repo size, package count, bandwidth)
- **Use cases** we might not have considered

**How:** Open a [GitHub Discussion](https://github.com/yourusername/chantal/discussions) in the "Experience Reports" category.

### 2. Review Design Documents

We're making architectural decisions right now. Your input is valuable:

- Read [CONTEXT.md](CONTEXT.md) for full requirements
- Check [.planning/findings.md](.planning/findings.md) for our tool analysis
- Review [ROADMAP.md](ROADMAP.md) for our roadmap

**How:** Comment on open issues tagged with `architecture` or `design`.

### 3. Suggest Improvements

Have ideas about:
- CLI design?
- Configuration format?
- Plugin architecture?
- Storage strategy?

**How:** Open an issue with the `enhancement` label.

### 4. Report Issues with Existing Tools

Found bugs or limitations in apt-mirror, aptly, reposync, etc. that Chantal should avoid?

**How:** Open an issue with the `research` label.

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
pytest tests/ -v
```

- Write tests for new features
- All tests must pass

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

**Current Focus:** Phase 1 - Research & Tool Analysis

See [ROADMAP.md](ROADMAP.md) for current priorities.
