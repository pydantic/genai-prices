"""Guard against accidental package-version downgrades in a PR.

Motivating incident: PR #428 accidentally replayed an old release-prep commit on
top of `main`, silently downgrading the package version 0.0.69 -> 0.0.67 across
`packages/python/pyproject.toml`, `packages/js/package.json` and the lockfiles.
A human caught it by eye; this script lets CI catch it automatically.

The check:
  1. Reads the version from `packages/python/pyproject.toml` and
     `packages/js/package.json` in the working tree; they must match.
  2. Reads the version `main` currently ships from the same two files.
  3. Fails if the PR version is a downgrade relative to `main`.

Unchanged versions (the common case) and legitimate bumps (release PRs) pass.
"""

from __future__ import annotations as _annotations

import json
import subprocess
import sys
from pathlib import Path

import tomllib
from packaging.version import InvalidVersion, Version

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT_PATH = 'packages/python/pyproject.toml'
PACKAGE_JSON_PATH = 'packages/js/package.json'


def _parse_pyproject(text: str) -> str:
    return str(tomllib.loads(text)['project']['version'])


def _parse_package_json(text: str) -> str:
    return str(json.loads(text)['version'])


def _read_working_tree(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text()


def _read_from_ref(ref: str, rel_path: str) -> str:
    return subprocess.run(
        ['git', 'show', f'{ref}:{rel_path}'],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
        text=True,
    ).stdout


def _matched_version(pyproject_text: str, package_json_text: str, source: str) -> Version:
    py_version = _parse_pyproject(pyproject_text)
    js_version = _parse_package_json(package_json_text)
    if py_version != js_version:
        sys.exit(
            f'::error::Version mismatch in {source}: '
            f'{PYPROJECT_PATH} is {py_version!r} but {PACKAGE_JSON_PATH} is {js_version!r}. '
            f'These two files must always declare the same version.'
        )
    try:
        return Version(py_version)
    except InvalidVersion as exc:
        sys.exit(f'::error::Invalid version {py_version!r} in {source}: {exc}')


def main(base_ref: str) -> None:
    pr_version = _matched_version(
        _read_working_tree(PYPROJECT_PATH),
        _read_working_tree(PACKAGE_JSON_PATH),
        source='this PR',
    )
    base_version = _matched_version(
        _read_from_ref(base_ref, PYPROJECT_PATH),
        _read_from_ref(base_ref, PACKAGE_JSON_PATH),
        source=f'base branch ({base_ref})',
    )

    if pr_version < base_version:
        sys.exit(
            f'::error::Package version was downgraded: base branch has {base_version} '
            f'but this PR has {pr_version}. This usually means an old release-prep commit '
            f'was accidentally replayed on top of an advanced `main` (see PR #428). '
            f'If this downgrade is intentional, adjust the version manually.'
        )

    if pr_version == base_version:
        print(f'Version unchanged at {pr_version} - ok.')
    else:
        print(f'Version bumped {base_version} -> {pr_version} - ok.')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit('usage: check_version_not_downgraded.py <base-ref>')
    main(sys.argv[1])
