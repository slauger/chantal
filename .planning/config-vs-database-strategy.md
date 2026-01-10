# Config vs Database State Management

## Overview

Chantal uses a **dual-source architecture** where configuration files and database serve different purposes.

## Principles

### Config File is the Source of Truth

The YAML configuration file defines **what repositories exist** and their **static metadata**:

- Repository ID, name, type
- Feed URL
- Enabled/disabled status
- Filters and processing rules
- Storage paths
- Database connection

**Key Point:** If a repository is not in the config, it doesn't exist from the user's perspective.

### Database is the Runtime State

The database stores **dynamic runtime information** only:

- Synced packages (content-addressed by SHA256)
- Last sync timestamp
- Sync history (success/failure, statistics)
- Snapshots created from synced packages
- Published snapshot status

**Key Point:** Database records without corresponding config entries are ignored.

## Implementation

### `repo list` command

Shows **all repositories from config**, merged with DB status:

```
For each repository in config:
  1. Load repository config
  2. Query database for matching repo_id
  3. Display:
     - Config metadata (id, name, type, enabled)
     - DB status (package_count, last_sync_at) if exists
     - "Not synced" if no DB record exists
```

### `repo sync` command

Sync updates **both config and database**:

```
1. Create or get repository record in DB
2. Sync packages (downloads, stores, links to repo)
3. Update repository.last_sync_at timestamp
4. Create SyncHistory record
```

### `repo show` command

Shows merged view:

```
- Config: name, type, feed, filters
- DB: package count, last sync, sync history
- Error if repo_id not in config
```

## Examples

### Scenario 1: Fresh Repository

**Config:** `rhel9-baseos-vim-latest` exists with `enabled: true`
**Database:** No record yet

**Result:**
```
repo list shows: rhel9-baseos-vim-latest | Not synced
```

### Scenario 2: After First Sync

**Config:** Same as above
**Database:** Repository record exists, packages synced, last_sync_at set

**Result:**
```
repo list shows: rhel9-baseos-vim-latest | 16 packages | 2026-01-10 13:04
```

### Scenario 3: Repository Removed from Config

**Config:** `rhel9-baseos-vim-latest` removed
**Database:** Repository record still exists with packages

**Result:**
```
repo list shows: (repository not shown)
Packages remain in pool (can be cleaned up later)
```

### Scenario 4: Repository Re-added to Config

**Config:** `rhel9-baseos-vim-latest` added back with same ID
**Database:** Old repository record and packages still exist

**Result:**
```
repo list shows: rhel9-baseos-vim-latest | 16 packages | 2026-01-10 13:04
Next sync will update/add packages as needed
```

## Benefits

### 1. Configuration as Code

- Repository definitions live in version-controlled YAML
- Easy to add/remove/modify repositories
- No need to manually update database

### 2. Declarative Management

- Define what should exist, not how to create it
- Idempotent operations
- Clear separation of concerns

### 3. Safe Operations

- Removing from config doesn't delete synced data
- Can re-add with same ID to restore
- Orphaned packages can be cleaned up separately

### 4. Clear Ownership

- Config: What the user wants
- Database: What has been synced
- No confusion about source of truth

## Trade-offs

### Configuration Changes Require File Edit

- Cannot add repositories via CLI alone
- Must edit config file and re-run commands
- **Rationale:** Ensures all changes are tracked in version control

### Orphaned Database Records

- Removing repo from config leaves DB records
- May accumulate over time
- **Solution:** Planned `cleanup` command to remove orphaned data

### Potential Config/DB Drift

- Config can define repos that don't exist in DB
- DB can have repos that don't exist in config
- **Mitigation:** `repo list` clearly shows sync status

## Future Enhancements

### Planned Features

1. **Orphan Cleanup Command**
   ```bash
   chantal storage cleanup --orphaned
   ```
   Remove packages and snapshots not linked to any configured repository

2. **Config Validation**
   ```bash
   chantal config validate
   ```
   Check that all DB repos have matching config entries

3. **Migration Tool**
   ```bash
   chantal config import-from-db
   ```
   Generate config from existing database (for migration)

## Related Files

- `/Users/simon/git/chantal/src/chantal/cli/main.py:100-165` - `repo list` implementation
- `/Users/simon/git/chantal/src/chantal/cli/main.py:168-282` - `repo sync` implementation
- `/Users/simon/git/chantal/src/chantal/core/config.py` - Configuration models
- `/Users/simon/git/chantal/src/chantal/db/models.py` - Database models
