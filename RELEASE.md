# Release Process

This document describes the unified release process for both Python and JavaScript packages.

## Overview

Both packages (`genai-prices` for Python and `@pydantic/genai-prices` for JavaScript) are released together with the same version number. This ensures consistency and simplifies dependency management.

## Release Workflow

### 1. Automatic Release (Recommended)

Use the provided release script:

```bash
# Using npm script (recommended)
npm run release <version>

# Or directly with Python
python scripts/release.py <version>
```

Example:

```bash
npm run release 1.0.0
# or
python scripts/release.py 1.0.0
```

This script will:

- Update the version in `packages/python/pyproject.toml`
- Update the version in `packages/js/package.json`
- Commit the version changes
- Create a git tag `v<version>`
- Push both the commit and tag to trigger CI

### 2. Manual Release

If you prefer to do it manually:

```bash
# Update Python version
cd packages/python
uv run python -c "
import tomllib
import tomli_w

with open('pyproject.toml', 'rb') as f:
    data = tomllib.load(f)

data['project']['version'] = '1.0.0'

with open('pyproject.toml', 'wb') as f:
    tomli_w.dump(data, f)
"

# Update JavaScript version
cd packages/js
npm version 1.0.0 --no-git-tag-version

# Commit and tag
cd ../..
git add packages/python/pyproject.toml packages/js/package.json
git commit -m "Bump version to 1.0.0"
git tag v1.0.0
git push origin main
git push origin v1.0.0
```

## CI Automation

When a tag is pushed, the CI will automatically:

1. **Extract version** from the git tag
2. **Update both package versions** to match the tag
3. **Run tests** for both packages
4. **Build both packages**
5. **Publish to PyPI** (Python package)
6. **Publish to npm** (JavaScript package)
7. **Create GitHub Release** with installation instructions

## Version Consistency

**Important**: Both packages always have the same version number, even if only one package has changes. This ensures:

- Consistent versioning across the ecosystem
- Easier dependency management
- Clear relationship between Python and JavaScript implementations

## Version Format

Use semantic versioning: `X.Y.Z`

- `X` - Major version (breaking changes)
- `Y` - Minor version (new features, backward compatible)
- `Z` - Patch version (bug fixes, backward compatible)

## Testing the Release Process

Before making an actual release, you can test the process:

### Local Testing

```bash
# Test the release script without making changes
npm run release:dry-run 1.0.0
# or
python scripts/release.py 1.0.0 --dry-run
```

This will:

- Update both package versions
- Show what would be committed
- Revert all changes automatically
- Not create any git commits or tags

### CI Testing

Use the "Test Release" workflow in GitHub Actions:

1. Go to Actions → Test Release
2. Click "Run workflow"
3. Enter a version (e.g., `0.0.1`)
4. Choose dry run mode
5. The workflow will test the entire release process

## Prerequisites

Before releasing, ensure:

1. All tests pass: `npm run ci`
2. Code is formatted: `npm run format`
3. Linting passes: `npm run lint`
4. You have the necessary permissions to:
   - Push to the main branch
   - Create tags
   - Access PyPI and npm publishing tokens

## Troubleshooting

### Release fails in CI

If the release workflow fails:

1. Check the CI logs for specific errors
2. Ensure all required secrets are configured:
   - `PYPI_TOKEN` for Python package publishing
   - `NPM_TOKEN` for JavaScript package publishing
3. Verify the version format is correct (X.Y.Z)
4. Check that both packages build successfully locally

### Version mismatch

If you notice version mismatches:

1. Both packages should always have the same version
2. The git tag should match the package versions
3. Use the release script to ensure consistency

## Rollback

If a release needs to be rolled back:

1. **Do not delete the git tag** - this can cause issues
2. **Create a new patch release** with fixes
3. **Contact package registry support** if immediate removal is needed
