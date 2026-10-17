"""Filter and verify a price-check workflow's safe file list."""

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictStr
from pydantic_core import ValidationError

from scripts.price_check_sources import (
    DISCOVERY_PROVIDER_ID,
    load_provider_sources,
    pending_backfill_rows,
    weekly_provider_sources,
)

_TARGETED_SOURCE = 'agentic-model-price-check.md'
_WEEKLY_SOURCE = 'agentic-price-check.md'
_PROVIDER_FILE_PREFIX = 'prices/providers/'
_DEFAULT_ARTIFACT_DIR = Path('/tmp/gh-aw')
_MAX_TRANSPORT_BYTES = 10 * 1024 * 1024
_OBJECT_ID = re.compile(r'^[0-9a-f]{40}$|^[0-9a-f]{64}$')


class _CreatePullRequestConfig(BaseModel):
    model_config = ConfigDict(extra='ignore', strict=True)

    allowed_files: list[StrictStr] = Field(alias='allowed-files')


class _SafeOutputsConfig(BaseModel):
    model_config = ConfigDict(extra='ignore', strict=True)

    create_pull_request: _CreatePullRequestConfig = Field(alias='create-pull-request')


class _WorkflowConfig(BaseModel):
    model_config = ConfigDict(extra='ignore', strict=True)

    safe_outputs: _SafeOutputsConfig = Field(alias='safe-outputs')


def _is_provider_yaml(path: str) -> bool:
    return path.startswith(_PROVIDER_FILE_PREFIX) and path.endswith(('.yml', '.yaml'))


def allowed_price_check_files(
    root: Path,
    allowed_files: list[str],
    workflow_source: str,
    pending_backfill: object,
) -> list[str]:
    """Narrow weekly provider writes while preserving the workflow's safe allowlist."""
    if workflow_source not in {_TARGETED_SOURCE, _WEEKLY_SOURCE}:
        raise ValueError(f'Unknown price-check workflow source: {workflow_source!r}')
    if any(not path for path in allowed_files):
        raise ValueError('Price-check allowed files must be non-empty paths')
    if workflow_source == _TARGETED_SOURCE:
        return allowed_files.copy()

    provider_sources = load_provider_sources(root)
    files_by_id: dict[str, str] = {}
    files_by_path: dict[str, str] = {}
    for provider in provider_sources:
        if provider.id in files_by_id or provider.file in files_by_path:
            raise ValueError('Provider source IDs and file paths must be unique')
        files_by_id[provider.id] = provider.file
        files_by_path[provider.file] = provider.id

    ordinary_files = {provider.file for provider in weekly_provider_sources(root)}
    pending_ids = {row.provider_id for row in pending_backfill_rows(pending_backfill, set(files_by_id))}
    if DISCOVERY_PROVIDER_ID in pending_ids:
        allowed_provider_files = set(files_by_path)
    else:
        allowed_provider_files = ordinary_files | {files_by_id[provider_id] for provider_id in pending_ids}

    return [path for path in allowed_files if not _is_provider_yaml(path) or path in allowed_provider_files]


def _git(
    root: Path,
    args: list[str],
    *,
    git_dir: Path | None = None,
    index_file: Path | None = None,
    timeout: int = 60,
) -> bytes:
    """Run built-in Git plumbing with ambient Git config and hooks disabled."""
    environment = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    environment.update(
        {
            'GIT_CONFIG_GLOBAL': os.devnull,
            'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_NO_REPLACE_OBJECTS': '1',
            'GIT_OPTIONAL_LOCKS': '0',
            'GIT_TERMINAL_PROMPT': '0',
            'GIT_ATTR_NOSYSTEM': '1',
        }
    )
    command = ['git', '-c', f'core.hooksPath={os.devnull}', '-c', 'core.fsmonitor=false']
    if git_dir is not None:
        environment['GIT_DIR'] = str(git_dir)
    if index_file is not None:
        environment['GIT_INDEX_FILE'] = str(index_file)
    try:
        result = subprocess.run(
            [*command, *args],
            cwd=root,
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f'Git command timed out: {args[0]}') from exc
    if result.returncode:
        detail = result.stderr.decode('utf-8', errors='replace').strip()
        raise ValueError(f'Git command failed ({args[0]}): {detail or result.returncode}')
    return result.stdout


def _weekly_allowed_provider_files(root: Path, pending_backfill: object, workflow_source: str) -> set[str]:
    source_path = root / '.github/workflows' / workflow_source
    source = source_path.read_text()
    frontmatter, separator, _ = source.partition('\n---\n')
    if not separator or not frontmatter.startswith('---\n'):
        raise ValueError(f'Invalid price-check workflow frontmatter: {source_path}')
    raw: object = yaml.safe_load(frontmatter.removeprefix('---\n'))
    try:
        workflow = _WorkflowConfig.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f'Workflow is missing a valid create-pull-request file allowlist: {source_path}') from exc
    allowed_files = workflow.safe_outputs.create_pull_request.allowed_files
    filtered = allowed_price_check_files(root, allowed_files, workflow_source, pending_backfill)
    return {path for path in filtered if _is_provider_yaml(path)}


def _changed_paths(output: bytes) -> set[str]:
    try:
        return {path.decode('utf-8') for path in output.split(b'\0') if path}
    except UnicodeDecodeError as exc:
        raise ValueError('Transport changes a path that is not valid UTF-8') from exc


def _provider_changes(paths: set[str], allowed_provider_files: set[str]) -> list[str]:
    return sorted(path for path in paths if _is_provider_yaml(path) and path not in allowed_provider_files)


def _check_transport_file(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise ValueError(f'Cannot inspect safe-output transport {path.name}: {exc}') from exc
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f'Safe-output transport is not a regular file: {path.name}')
    if info.st_size > _MAX_TRANSPORT_BYTES:
        raise ValueError(f'Safe-output transport is too large: {path.name}')


def _validate_bundle(root: Path, path: Path, base_sha: str, allowed_provider_files: set[str]) -> set[str]:
    heads_text = _git(root, ['bundle', 'list-heads', str(path)])
    heads: set[str] = set()
    for line in heads_text.splitlines():
        parts = line.split()
        if len(parts) != 2:
            raise ValueError(f'Malformed Git bundle head in {path.name}')
        object_id = parts[0].decode('ascii', errors='strict')
        if not _OBJECT_ID.fullmatch(object_id):
            raise ValueError(f'Malformed Git bundle object ID in {path.name}')
        heads.add(object_id)
    if not heads:
        raise ValueError(f'Git bundle has no advertised heads: {path.name}')

    object_format = _git(root, ['rev-parse', '--show-object-format']).decode('ascii').strip()
    object_directory = (
        _git(root, ['rev-parse', '--path-format=absolute', '--git-path', 'objects']).decode('utf-8').strip()
    )
    with tempfile.TemporaryDirectory(prefix='price-check-bundle-') as temporary:
        git_dir = Path(temporary) / 'repository.git'
        _git(root, ['init', '--bare', '--quiet', '--object-format', object_format, str(git_dir)])
        (git_dir / 'objects/info/alternates').write_text(f'{object_directory}\n')
        shallow_path = Path(
            _git(root, ['rev-parse', '--path-format=absolute', '--git-path', 'shallow']).decode('utf-8').strip()
        )
        if shallow_path.is_file():
            shutil.copyfile(shallow_path, git_dir / 'shallow')
        _git(root, ['cat-file', '-e', f'{base_sha}^{{commit}}'])
        all_changes: set[str] = set()
        for head in sorted(heads):
            _git(
                root,
                ['fetch', '--no-tags', '--no-recurse-submodules', '--no-write-fetch-head', str(path), head],
                git_dir=git_dir,
            )
            _git(root, ['cat-file', '-e', f'{head}^{{commit}}'], git_dir=git_dir)
            paths = _changed_paths(
                _git(
                    root,
                    [
                        'diff',
                        '--no-renames',
                        '--name-only',
                        '-z',
                        '--no-ext-diff',
                        '--no-textconv',
                        base_sha,
                        head,
                    ],
                    git_dir=git_dir,
                )
            )
            illegal = _provider_changes(paths, allowed_provider_files)
            if illegal:
                raise ValueError(f'{path.name} changes provider files outside weekly scope: {", ".join(illegal)}')
            all_changes.update(paths)
    return all_changes


def _validate_patch(root: Path, path: Path, base_sha: str, allowed_provider_files: set[str]) -> set[str]:
    with tempfile.TemporaryDirectory(prefix='price-check-patch-') as temporary:
        git_dir = Path(temporary) / 'repository.git'
        object_format = _git(root, ['rev-parse', '--show-object-format']).decode('ascii').strip()
        _git(root, ['init', '--bare', '--quiet', '--object-format', object_format, str(git_dir)])
        object_directory = (
            _git(root, ['rev-parse', '--path-format=absolute', '--git-path', 'objects']).decode('utf-8').strip()
        )
        (git_dir / 'objects/info/alternates').write_text(f'{object_directory}\n')
        _git(root, ['cat-file', '-e', f'{base_sha}^{{commit}}'])
        index_file = Path(temporary) / 'index'
        _git(root, ['read-tree', base_sha], git_dir=git_dir, index_file=index_file)
        _git(root, ['apply', '--cached', '--binary', str(path)], git_dir=git_dir, index_file=index_file)
        paths = _changed_paths(
            _git(
                root,
                ['diff', '--cached', '--no-renames', '--name-only', '-z', '--no-ext-diff', '--no-textconv', base_sha],
                git_dir=git_dir,
                index_file=index_file,
            )
        )
        illegal = _provider_changes(paths, allowed_provider_files)
        if illegal:
            raise ValueError(f'{path.name} changes provider files outside weekly scope: {", ".join(illegal)}')
        return paths


def validate_price_check_transports(
    root: Path,
    artifact_dir: Path,
    base_sha: str,
    pending_backfill: object,
    workflow_source: str = _WEEKLY_SOURCE,
) -> list[str]:
    """Verify provider-file changes in safe-output bundles and patches."""
    if not _OBJECT_ID.fullmatch(base_sha):
        raise ValueError('GITHUB_SHA must be a full lowercase Git object ID')
    if workflow_source not in {_TARGETED_SOURCE, _WEEKLY_SOURCE}:
        raise ValueError(f'Unknown price-check workflow source: {workflow_source!r}')
    allowed_provider_files = _weekly_allowed_provider_files(root, pending_backfill, workflow_source)
    bundle_files = sorted(artifact_dir.glob('aw-*.bundle'))
    patch_files = sorted(artifact_dir.glob('aw-*.patch'))
    files = [*bundle_files, *patch_files]
    changed: set[str] = set()
    for path in files:
        _check_transport_file(path)
        if path in bundle_files:
            changed.update(_validate_bundle(root, path, base_sha, allowed_provider_files))
        else:
            changed.update(_validate_patch(root, path, base_sha, allowed_provider_files))
    return sorted(changed)


def _main() -> int:
    parser = argparse.ArgumentParser(
        description='Validate safe-output Git transports against the weekly price-check provider scope.'
    )
    parser.add_argument(
        '--validate-transports', action='store_true', help='inspect downloaded aw-*.bundle and aw-*.patch files'
    )
    parser.add_argument('--base-sha', default=os.environ.get('GITHUB_SHA'))
    parser.add_argument('--pending-backfill', default=os.environ.get('PRICE_CHECK_PENDING_BACKFILL'))
    parser.add_argument('--workflow-source', default=_WEEKLY_SOURCE)
    parser.add_argument('--artifact-dir', type=Path, default=_DEFAULT_ARTIFACT_DIR)
    parser.add_argument('--repo-root', type=Path, default=Path.cwd())
    args = parser.parse_args()
    if not args.validate_transports:
        parser.error('pass --validate-transports to inspect safe-output artifacts')
    try:
        if args.base_sha is None:
            raise ValueError('GITHUB_SHA is required')
        if args.pending_backfill is None:
            raise ValueError('PRICE_CHECK_PENDING_BACKFILL is required')
        pending_backfill = json.loads(args.pending_backfill)
        validate_price_check_transports(
            args.repo_root,
            args.artifact_dir,
            args.base_sha,
            pending_backfill,
            args.workflow_source,
        )
    except Exception as exc:
        print(f'Price-check transport scope validation failed: {exc}', file=sys.stderr)
        return 1
    print('Price-check transport scope validation passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(_main())
