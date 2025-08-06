# Release Workflow

This project uses [changesets](https://github.com/changesets/changesets) to manage releases across both JavaScript and Python packages in this monorepo.

## Release Process

### 1. Initiating a Change

When making changes that should trigger a release:

```bash
npm run changeset-add
```

This command can be run in any developer branch. It will:

- Prompt you to select which packages have changed
- Ask for the type of change (major, minor, patch)
- Create a markdown file describing the changes

After adding the changeset:

- Commit the changes
- Push to your branch
- Create a Pull Request

### 2. Automated Actions on PR Merge to Main

When a PR containing changesets is merged to `main`, the changesets GitHub Action automatically:

a. **Creates a new PR with version updates** - Instead of committing directly to main
b. **Updates package versions** (e.g., `0.0.8` → `0.0.9`) based on the changeset types
c. **Updates CHANGELOG.md files** with the new changes and versions
d. **Does NOT commit directly to main** - All changes go through the new PR

### 3. Merging the Release PR

The automatically generated "Release PR" (from step 2a) should be:

- Reviewed for accuracy
- Merged to `main`

Once merged, the updated package versions and changelog entries are officially integrated into the `main` branch.

### 4. Publishing and Releasing

After the Release PR is merged, the changesets tool automatically:

- **Publishes packages to npm/PyPI** - JavaScript packages to npm, Python packages to PyPI
- **Creates GitHub release** with release notes generated from the CHANGELOG.md updates

## Manual Commands

If you need to run changeset commands manually:

```bash
# Add a new changeset
npm run changeset-add

# Version packages (creates PR)
npm run changeset-version

# Publish packages (usually done by CI)
npm run changeset-publish
```
