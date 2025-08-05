#!/bin/bash

# sync versions from package json to pyproject.toml
uvx --from=toml-cli toml set --toml-path=pyproject.toml project.version $(jq -r '.version' <package.json)
