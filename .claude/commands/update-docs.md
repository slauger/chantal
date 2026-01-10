# Update Sphinx Documentation

You are tasked with updating the Sphinx documentation in `docs/` to reflect recent code changes.

## Steps to Follow:

### 1. Analyze Recent Changes
- Check recent commits with `git log --oneline -10` to understand what changed
- Look for new features, configuration options, CLI commands, or architectural changes
- Review modified Python files to identify documentation needs

### 2. Identify Affected Documentation Files

Map changes to these documentation areas:

**User Guide** (`docs/user-guide/`):
- `installation.md` - New dependencies, requirements
- `quickstart.md` - Basic usage examples
- `cli-commands.md` - New CLI commands or changed syntax
- `workflows.md` - New workflow examples
- `views.md` - View-related features

**Configuration** (`docs/configuration/`):
- `overview.md` - New config structure or global settings
- `repositories.md` - Repository configuration changes
- `filters.md` - New filter options
- `ssl-authentication.md` - SSL/TLS changes

**Architecture** (`docs/architecture/`):
- `overview.md` - System architecture changes
- `content-addressed-storage.md` - Storage design changes
- `database-schema.md` - New models or schema changes
- `plugin-system.md` - Plugin architecture changes

**Plugins** (`docs/plugins/`):
- `overview.md` - Plugin system overview
- `rpm-plugin.md` - RPM plugin documentation
- `custom-plugins.md` - Plugin development guide
- Create new plugin docs as needed (e.g., `deb-plugin.md`, `helm-plugin.md`)

### 3. Update Documentation

For each affected file:
- Read the current content
- Add/update sections for new features
- Update examples with correct paths (production paths: `/etc/chantal/`, `/var/lib/chantal/`)
- Ensure code examples are accurate and tested
- Add cross-references to related documentation
- Keep the tone consistent with existing docs

### 4. Rebuild and Test

```bash
cd docs
make clean
make html
```

Check for:
- Build warnings or errors
- Broken links
- Formatting issues
- Missing references

### 5. Review Changes

- Verify all new features are documented
- Check that examples match current code behavior
- Ensure configuration examples are complete and accurate
- Confirm API documentation is auto-generated correctly

### 6. Commit Changes

```bash
git add docs/
git commit -m "Update documentation for [feature/change]

- Updated docs/[affected-files]
- Added examples for [new features]
- Fixed [issues]

Rebuilt HTML documentation successfully."
```

## Important Notes:

- **Use production paths** in all examples: `/etc/chantal/config.yaml`, `/var/lib/chantal/`, `/var/www/repos/`
- **No development paths**: Avoid `.dev/` references
- **Complete examples**: Show full YAML configs, not just snippets
- **Link to related docs**: Use Sphinx cross-references
- **Keep README.md minimal**: Detailed docs go in Sphinx, README links to them

## Output Format:

Provide a summary of:
1. What files were updated
2. What new content was added
3. Build status (warnings/errors)
4. Commit message used

Start by analyzing recent changes and identifying which documentation needs updating.
