# Release Workflow

Keep it simple!

1. Create a [GitHub release](https://github.com/pydantic/genai-prices/releases/new) with a new tag
   `vX.Y.Z` (plain semver, no pre-release suffix) and let GitHub generate the changelog
2. Wait for the tag's CI run to reach the `release-pypi` and `release-npm` jobs. In the run's
   **Review deployments** prompt, select both protected environments and approve them. CI creates
   the matching `packages/go/vX.Y.Z` tag automatically
3. Wait for `check release published` to pass, then confirm that `genai-prices` X.Y.Z is on PyPI
   and `@pydantic/genai-prices` X.Y.Z is on npm

Nothing in the repo holds the version. Python reads it from the tag at build time via
`uv-dynamic-versioning` (commits between tags build as `X.Y.(Z+1).devN+g<sha>`), and the release job
writes it into `packages/js/package.json` with `npm version` right before building the npm tarball -
the `0.0.0` committed there is a placeholder. Go resolves the matching `packages/go/vX.Y.Z` tag directly.
