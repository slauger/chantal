# GitHub Issue: Database Management Commands

## Title
Add `chantal db` command group for database management

## Labels
- enhancement
- breaking-change
- database

## Description

### Problem
Currently, database initialization is done via `chantal init`, but there's no way for users to:
- Upgrade database schema after installing new Chantal version
- Check current database schema version
- View migration history
- Verify database compatibility with installed Chantal version

This becomes critical when users run:
```bash
pip install --upgrade chantal
chantal repo sync --repo-id xyz  # May fail with schema mismatch!
```

### Proposed Solution

Add a `chantal db` command group with dedicated database management commands:

```bash
# Database management commands
chantal db init                 # Initialize database (replaces 'chantal init')
chantal db upgrade              # Upgrade to latest schema version
chantal db status               # Show database status and pending migrations
chantal db current              # Show current schema revision
chantal db history              # Show migration history
chantal db downgrade [revision] # Rollback to specific revision (emergency only)
```

### User Workflow

**After upgrading Chantal:**
```bash
pip install --upgrade chantal

chantal db status
# Output: ⚠️  Database is 2 revisions behind current version
#         Current: 3c10bed2aae6
#         Latest:  6a05c207d0bd
#
#         Pending migrations:
#         - 20260110_2030_add_views (Add Views support)
#         - 20260110_2135_add_helm_charts (Add Helm Charts support)
#
#         Run 'chantal db upgrade' to update.

chantal db upgrade
# Output: Running migrations...
#         ✓ 20260110_2030_add_views
#         ✓ 20260110_2135_add_helm_charts
#         Database successfully upgraded to 6a05c207d0bd

chantal repo sync --repo-id xyz  # ✅ Works!
```

### Implementation Tasks

- [ ] Create `@cli.group()` for `db` commands
- [ ] Implement `chantal db init` (wrapper for current `init` logic)
- [ ] Implement `chantal db upgrade` (wrapper for `alembic upgrade head`)
- [ ] Implement `chantal db status` (check current vs latest revision)
- [ ] Implement `chantal db current` (show current revision)
- [ ] Implement `chantal db history` (show migration history)
- [ ] Add schema version check before repo/snapshot/publish commands
- [ ] Deprecate `chantal init` with warning pointing to `chantal db init`
- [ ] Update documentation
- [ ] Update README.md with new commands
- [ ] Add tests for DB commands

### Breaking Changes

**`chantal init` → `chantal db init`**

Migration strategy:
1. Keep `chantal init` as deprecated alias (hidden in `--help`)
2. Show deprecation warning when used:
   ```
   ⚠️  'chantal init' is deprecated and will be removed in v2.0.0
   Please use 'chantal db init' instead.
   ```
3. Remove in next major version (2.0.0)

### Auto-Check Schema Version

Add automatic schema version check before critical operations:

```python
@cli.command()
@click.option("--repo-id", required=True)
def sync(repo_id: str):
    """Sync repository."""
    # Check schema version first
    if db_needs_upgrade():
        click.echo("⚠️  Database schema is outdated!", err=True)
        click.echo("Run 'chantal db upgrade' to update.", err=True)
        sys.exit(1)

    # Continue with sync...
```

Commands that should check:
- `repo sync`
- `repo add`
- `snapshot create`
- `publish repo`
- `publish snapshot`
- `view create`

Commands that should NOT check (read-only):
- `repo list`
- `snapshot list`
- `db status` (obviously)

### Example Output

**`chantal db status`**
```
Database Schema Status
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Database:  /Users/user/.chantal/chantal.db
Current:   3c10bed2aae6 (Add Views support)
Latest:    6a05c207d0bd (Add Helm Charts support)

Status:    ⚠️  2 migrations pending

Pending Migrations:
  • 20260110_2135 - Add Helm Charts support

Run 'chantal db upgrade' to apply pending migrations.
```

**`chantal db history`**
```
Migration History
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✓ 20260101_1200_initial (Initial schema)
✓ 20260105_1500_add_storage (Add content-addressed storage)
✓ 20260108_1800_add_snapshots (Add snapshot support)
✓ 20260110_2030_add_views (Add Views support)
⧗ 20260110_2135_add_helm_charts (Add Helm Charts support) [PENDING]

Legend: ✓ Applied  ⧗ Pending
```

### Related Issues

This will be especially important when implementing:
- #5 (Generic ContentItem model) - Major schema migration
- Future plugin additions (Helm, APT, PyPI, etc.)

### References

Similar implementations:
- Alembic CLI: `alembic upgrade`, `alembic current`, `alembic history`
- Django: `python manage.py migrate`, `python manage.py showmigrations`
- Pulp: `pulpcore-manager migrate`
