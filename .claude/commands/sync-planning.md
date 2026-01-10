---
description: Synchronizes .planning/ markdown files with GitHub Issues. Creates missing issues, updates existing ones, and ensures consistency between planning docs and issue tracker.
allowed-tools: Bash(gh *), Bash(git *), Read, Edit, Write
---

# Sync Planning Docs with GitHub Issues

Synchronize `.planning/` markdown files with GitHub Issues to ensure consistency between local planning and the issue tracker.

## Steps to Follow:

### 1. Analyze Planning Documents

Read all planning files:
```bash
ls -la .planning/
```

Check these files for actionable items:
- `.planning/task_plan.md` - Phases and milestones
- `.planning/findings.md` - Implementation decisions and TODOs
- `.planning/progress.md` - Current progress and next steps
- `.planning/status.md` - Feature status
- Any other `.planning/*.md` files

Look for:
- **TODO items** (marked with `[ ]` or `- [ ]`)
- **Planned features** (🚧 Planned, In Progress)
- **Design decisions** that need tracking
- **Next steps** sections
- **Milestone goals** not yet in issues

### 2. Get Current GitHub Issues

Fetch all issues:
```bash
gh issue list --limit 100 --state all --json number,title,state,labels,body
```

Group issues by:
- Open issues
- Closed issues
- Labels (enhancement, bug, documentation, etc.)

### 3. Compare Planning Docs vs GitHub Issues

**Find gaps:**
- Items in planning docs WITHOUT corresponding GitHub issues
- GitHub issues WITHOUT reference in planning docs
- Closed issues that should be updated in planning docs
- Completed planning items that should close issues

**Check consistency:**
- Are milestone statuses aligned?
- Are feature statuses (✅ Complete, 🚧 Planned) matching issue states?
- Are design decisions documented in both places?

### 4. Create Missing GitHub Issues

For each item in planning docs without a GitHub issue:

```bash
gh issue create \
  --title "Feature: [Title from planning doc]" \
  --body "[Context from planning doc]" \
  --label "enhancement"
```

**Use appropriate labels:**
- `enhancement` - New features
- `documentation` - Docs work
- `research` - Investigation needed
- `plugin` - Plugin-related
- `milestone-X` - Milestone tracking

**Link to planning docs:**
Include references like:
```markdown
See `.planning/task_plan.md` Phase 3 for details.
Related to design decision in `.planning/findings.md` Section X.
```

### 5. Update Planning Docs

Add GitHub issue references to planning docs:

**Before:**
```markdown
- [ ] Implement DEB/APT support
```

**After:**
```markdown
- [ ] Implement DEB/APT support (#42)
```

**Track completion:**
```markdown
### Milestone 6: Database Management
- [x] Database stats command (#14) ✅ Complete
- [ ] Database cleanup command (#15) 🚧 In Progress
- [ ] Database verify command (#16)
```

### 6. Update GitHub Issues

For issues that need updates:

```bash
# Add comment with status update
gh issue comment 42 --body "Status update: Implementation started. See .planning/progress.md for details."

# Close completed issues
gh issue close 14 --comment "Completed in commit abc123. See .planning/task_plan.md Milestone 6."

# Update labels
gh issue edit 15 --add-label "in-progress"
```

### 7. Generate Sync Report

Create a summary showing:

**Created Issues:**
- Issue #XX: Feature Y (from .planning/task_plan.md Phase 3)
- Issue #YY: Research Z (from .planning/findings.md)

**Updated Planning Docs:**
- .planning/task_plan.md: Added issue references to 5 items
- .planning/progress.md: Updated status based on closed issues

**Found Inconsistencies:**
- Issue #42 is closed but still marked as TODO in task_plan.md
- Feature X in findings.md has no issue tracker

**Recommendations:**
- Consider closing issue #30 (completed in .planning/status.md)
- Create milestone for Phase 4 items

### 8. Commit Changes

```bash
git add .planning/
git commit -m "Sync planning docs with GitHub issues

Created issues:
- #XX: Feature Y
- #YY: Research Z

Updated planning docs:
- Added issue references to task_plan.md
- Updated status based on closed issues

Synchronized .planning/ with GitHub issue tracker."
```

## Sync Rules:

**Planning Docs → GitHub Issues:**
- ✅ Create issue for planned features without issues
- ✅ Create issue for design decisions that need tracking
- ✅ Create issue for TODO items in findings.md
- ❌ Don't create issues for completed items (✅)

**GitHub Issues → Planning Docs:**
- ✅ Add issue references (#XX) to planning docs
- ✅ Update status based on closed issues
- ✅ Mark items complete when issues are closed
- ❌ Don't remove completed items from planning docs (keep history)

**Bidirectional Sync:**
- Milestone status must match in both places
- Feature status (🚧 Planned, ✅ Complete) must match issue state
- Design decisions should be documented in both

## Important Notes:

**What to Create Issues For:**
- New repository type support (DEB, Helm, PyPI)
- Major features (scheduled sync, web UI, API)
- Database/storage enhancements
- Plugin system improvements
- Documentation tasks

**What NOT to Create Issues For:**
- Small refactorings
- Typo fixes
- Internal implementation details
- Completed work (already ✅)

**Issue Naming Convention:**
- Features: `Feature: Add DEB/APT repository support`
- Bugs: `Bug: Snapshot copy fails with views`
- Docs: `Docs: Add Helm plugin documentation`
- Research: `Research: APT repository format`

## Output Format:

Provide a summary:
1. **Planning Docs Analyzed**: List of files checked
2. **GitHub Issues Created**: Number and titles
3. **Planning Docs Updated**: Files modified with issue refs
4. **Inconsistencies Found**: Items needing manual review
5. **Recommendations**: Suggested next steps

Start by reading all `.planning/*.md` files and fetching GitHub issues.
