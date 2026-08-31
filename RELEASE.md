# Release Workflow

Keep it simple!

1. Create a [GitHub release](https://github.com/pydantic/genai-prices/releases/new) with a new tag
   `vX.Y.Z` (plain semver, no pre-release suffix) and let GitHub generate the changelog
2. That's it: the `vX.Y.Z` tag runs CI, and once it's green the release jobs publish `genai-prices`
   X.Y.Z to PyPI and `@pydantic/genai-prices` X.Y.Z to npm and create the matching
   `packages/go/vX.Y.Z` tag for the Go module

Nothing in the repo holds the version. Python reads it from the tag at build time via
`uv-dynamic-versioning` (commits between tags build as `X.Y.(Z+1).devN+g<sha>`), and the release job
writes it into `packages/js/package.json` with `npm version` right before building the npm tarball -
the `0.0.0` committed there is a placeholder. Go resolves the matching `packages/go/vX.Y.Z` tag directly.
