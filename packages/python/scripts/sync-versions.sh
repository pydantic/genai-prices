#!/bin/bash

# Exit on any error, undefined variables, and pipe failures
set -euo pipefail

# sync versions from package.json to pyproject.toml
version=$(jq -r '.version' <package.json)

# Validate that we got a non-empty version
if [[ -z "$version" ]]; then
  echo "Error: Failed to extract version from package.json" >&2
  exit 1
fi

# Validate version format (basic check for semantic versioning)
if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+ ]]; then
  echo "Error: Invalid version format: $version" >&2
  exit 1
fi

echo "Syncing version: $version"

# Update pyproject.toml with the extracted version
uvx --from=toml-cli toml set --toml-path=pyproject.toml project.version "$version"

echo "Successfully updated pyproject.toml to version: $version"
