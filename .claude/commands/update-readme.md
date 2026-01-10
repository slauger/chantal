# Update README.md

You are tasked with updating the `README.md` in the repository root to reflect recent changes.

## Important Principles:

**Keep README.md SHORT and focused!** The detailed documentation lives in Sphinx at https://slauger.github.io/chantal/

The README should only contain:
- Project overview with emoji features
- Quick installation (Container + Python)
- Basic usage (5 steps max)
- Key features (compact)
- Status & roadmap (high-level)
- Links to full Sphinx documentation

**DO NOT add:**
- ❌ Detailed CLI reference (→ link to Sphinx)
- ❌ Complete configuration examples (→ link to Sphinx)
- ❌ Long workflow tutorials (→ link to Sphinx)
- ❌ Extensive output examples (→ link to Sphinx)

## Steps to Follow:

### 1. Analyze Recent Changes

Check what changed:
```bash
git log --oneline -10
git diff HEAD~5..HEAD --stat
```

Look for:
- New features implemented
- New repository types supported
- Changed CLI commands
- New configuration options
- Updated dependencies
- Version changes

### 2. Identify What Needs Updating in README.md

**Section: Features (Emoji Block)**
- Update feature list if new major features added
- Keep emojis and short descriptions
- Maximum 10 features

**Section: Supported Repository Types**
- Move items from 🚧 Planned → ✅ Available when implemented
- Add new planned types if discussed

**Section: Installation**
- Update container image tags if version changed
- Update Python/dependency requirements
- Keep both Container and Python options

**Section: Basic Usage**
- Update CLI commands if syntax changed
- Keep it to 5 steps maximum
- Use generic examples

**Section: Status**
- Update "Current Release" version
- Move completed items from "Next Up" to "Completed"
- Update test count
- Update milestone references

**Section: Roadmap Links**
- Ensure links to ROADMAP.md and GitHub Issues are correct

### 3. Update README.md

For each section that needs updates:
- Read current README.md
- Make minimal, targeted changes
- Keep the tone consistent (friendly, technical, concise)
- Preserve emoji usage
- Ensure all Sphinx doc links are working
- Use production paths in examples (not `.dev/`)

### 4. Validate Changes

Check:
- **Length**: README should be ~250-300 lines maximum
- **Links**: All Sphinx documentation links work
- **Badges**: Documentation, Container, License badges are correct
- **Formatting**: Proper Markdown (code blocks, lists, headings)
- **Accuracy**: Examples match current behavior
- **Emojis**: Feature list has emojis, formatting is clean

### 5. Build Test (Optional)

If you made significant changes, render the Markdown locally to verify:
- Code blocks render correctly
- Links work
- Formatting is clean

### 6. Commit Changes

```bash
git add README.md
git commit -m "Update README.md - [brief description]

[What was updated]
- Updated [section] with [changes]
- Fixed [issues]
- Added [new content]

[Why]
Reflects recent changes in [feature/area]."
```

## What NOT to Do:

- ❌ Don't bloat the README with detailed documentation
- ❌ Don't duplicate content that's in Sphinx docs
- ❌ Don't add long configuration examples (just link to docs)
- ❌ Don't add detailed CLI command reference (link to Sphinx)
- ❌ Don't add extensive workflow examples (show 2-3 max, link to docs)
- ❌ Don't remove the emoji features block (user likes it!)
- ❌ Don't use development paths (`.dev/`)

## Key Sections to Preserve:

These sections must stay:
1. **Title + badges** (Documentation, Container, License)
2. **What is Chantal?** (Problem/Solution)
3. **Features** (Emoji list - user's favorite!)
4. **Supported Repository Types** (with ✅ and 🚧)
5. **Quick Start** (Installation + Basic Usage)
6. **Key Features** (compact explanations)
7. **Architecture** (minimal diagram + links)
8. **Documentation** (links to Sphinx)
9. **Common Workflows** (2-3 examples max)
10. **Status** (current version + roadmap)
11. **Contributing** (brief)
12. **Footer** (Container, Docs, Issues links)

## Output Format:

Provide a summary:
1. What sections were updated
2. What specific changes were made
3. Why these changes were needed
4. Confirmation that README is still concise (~250-300 lines)

Start by analyzing recent commits and identifying what needs updating in README.md.
