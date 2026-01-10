---
description: Updates ROADMAP.md after milestone completion. Moves completed items, integrates new GitHub issues, and updates project status.
allowed-tools: Bash(git *), Bash(gh *), Read, Edit
---

# Update ROADMAP.md

You are tasked with updating `ROADMAP.md` to reflect the current project status after completing milestones or planning new features.

## Steps to Follow:

### 1. Analyze Current Status

Check what's been completed recently:
```bash
# Check recent commits
git log --oneline -20

# Check closed GitHub issues
gh issue list --state closed --limit 20

# Check open issues with labels
gh issue list --label enhancement --limit 20
gh issue list --label milestone --limit 20
```

Look for:
- Completed milestones
- Closed feature issues
- New planned features
- Changed priorities

### 2. Read Current ROADMAP.md

```bash
# Read the current roadmap
cat ROADMAP.md
```

Identify:
- What's marked as "In Progress"
- What's marked as "Completed"
- What's in "Planned"
- Current milestone status

### 3. Update Roadmap Sections

**Move Completed Items:**
- Find items in "In Progress" or "Planned" that are now done
- Move them to "Completed" section
- Add completion date if available
- Link to relevant PRs/commits

**Update In Progress:**
- Remove completed items
- Add items currently being worked on
- Reference GitHub issues or PRs

**Update Planned:**
- Add new features from GitHub issues
- Organize by priority or milestone
- Link to GitHub issues for tracking

**Update Milestones:**
- Mark completed milestones as ✅
- Update current milestone status
- Add new milestones if defined

### 4. Roadmap Structure

The ROADMAP.md should follow this structure:

```markdown
# Chantal Roadmap

**Last Updated:** [Date]
**Current Version:** v0.x.x
**Current Milestone:** Milestone X - [Name]

---

## ✅ Completed

### Milestone 1: [Name] (v0.1.0) - Completed [Date]
- ✅ Feature A
- ✅ Feature B
- ✅ Feature C

### Milestone 2: [Name] (v0.2.0) - Completed [Date]
- ✅ Feature D
- ✅ Feature E

---

## 🚧 In Progress

### Current Milestone: Milestone X - [Name]
- ⏳ Feature being worked on ([#123](link))
- ⏳ Another active feature ([#124](link))

**Target:** v0.x.0
**Status:** X% complete

---

## 📋 Planned

### Next Milestone: Milestone Y - [Name]
- 📝 Planned Feature A ([#125](link))
- 📝 Planned Feature B ([#126](link))

### Future Milestones
- Milestone Z - [Name]
  - Feature ideas
  - Improvements

---

## 🎯 Long-term Vision

[Long-term goals and vision]

---

## Repository Type Support Roadmap

| Type | Status | Target Milestone | Issue |
|------|--------|-----------------|-------|
| RPM | ✅ Available | v0.1.0 | - |
| APT/DEB | 🚧 In Progress | v0.3.0 | [#XX](link) |
| PyPI | 📋 Planned | v0.4.0 | [#XX](link) |
| Helm | 📋 Planned | v0.5.0 | [#XX](link) |
```

### 5. Cross-Reference with Other Files

Ensure consistency with:
- `README.md` Status section
- `pyproject.toml` version
- GitHub Milestones
- GitHub Issues

### 6. Validate Changes

Check:
- All completed items are marked ✅
- All in-progress items have issue links
- Milestones are accurate
- Dates are correct
- Links work (especially GitHub issue links)
- No duplicate entries

### 7. Commit Changes

```bash
git add ROADMAP.md
git commit -m "Update ROADMAP.md - [brief description]

Completed:
- [List completed items moved to ✅]

In Progress:
- [List current work items]

Planned:
- [List newly added planned features]

Updated milestone status: [Milestone X]"
```

## Important Notes:

- **Be accurate**: Only move items to Completed if they're truly done (merged, tested, documented)
- **Link GitHub issues**: Every planned/in-progress item should link to a GitHub issue
- **Update dates**: Add completion dates to finished milestones
- **Keep it clean**: Remove outdated items, consolidate similar features
- **Sync with README**: Status in ROADMAP should match README Status section

## Integration with GitHub

Use GitHub CLI to:
- Check milestone progress: `gh issue list --milestone "Milestone X"`
- List planned features: `gh issue list --label enhancement`
- Check closed items: `gh issue list --state closed`
- Link issues in roadmap: Use `[#123](https://github.com/user/repo/issues/123)` format

## Output Format:

Provide a summary:
1. What items were moved to Completed
2. What's currently In Progress
3. What new items were added to Planned
4. Current milestone status
5. Any changes to target versions

Start by analyzing recent commits and GitHub issues to understand what needs updating.
