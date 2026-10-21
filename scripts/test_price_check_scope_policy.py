import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts.price_check_scope_policy import allowed_price_check_files, validate_price_check_transports
from scripts.price_check_sources import load_provider_sources

ROOT = Path(__file__).resolve().parents[1]


def _all_provider_files() -> list[str]:
    return sorted(path.relative_to(ROOT).as_posix() for path in (ROOT / 'prices/providers').glob('*.yml'))


def _pending(provider_id: str) -> list[dict[str, str]]:
    return [
        {
            'request_id': 'a-request-id',
            'target_model': 'vendor/model',
            'provider_id': provider_id,
            'source': 'ignored source text',
        }
    ]


def test_weekly_scope_keeps_25_manifest_files_and_non_provider_paths() -> None:
    all_provider_files = list(reversed(_all_provider_files()))
    weekly_manifest = yaml.safe_load((ROOT / '.github/agentic-price-check-providers.yml').read_text())
    expected_weekly_files = {provider['file'] for provider in weekly_manifest['providers']}
    allowed_files = ['README.md', *all_provider_files, 'tests/test_price_calc.py']

    filtered = allowed_price_check_files(ROOT, allowed_files, 'agentic-price-check.md', [])

    provider_files = [path for path in filtered if path.startswith('prices/providers/')]
    assert set(provider_files) == expected_weekly_files
    assert provider_files == [path for path in all_provider_files if path in expected_weekly_files]
    assert filtered == [
        path for path in allowed_files if not path.startswith('prices/providers/') or path in expected_weekly_files
    ]
    assert 'prices/providers/quicksilverpro.yml' not in filtered
    assert 'prices/providers/aws.yml' not in filtered
    assert 'README.md' in filtered
    assert 'tests/test_price_calc.py' in filtered


def test_pending_provider_adds_only_that_provider_to_weekly_scope() -> None:
    filtered = allowed_price_check_files(ROOT, _all_provider_files(), 'agentic-price-check.md', _pending('aws'))

    assert 'prices/providers/aws.yml' in filtered
    assert 'prices/providers/azure.yml' not in filtered
    assert 'prices/providers/quicksilverpro.yml' not in filtered


def test_discovery_sentinel_allows_every_existing_provider_file() -> None:
    all_provider_files = _all_provider_files()

    filtered = allowed_price_check_files(ROOT, all_provider_files, 'agentic-price-check.md', _pending('_discovery'))

    assert filtered == all_provider_files
    assert set(filtered) == {provider.file for provider in load_provider_sources(ROOT)}


def test_targeted_workflow_keeps_its_supplied_allowlist_unchanged() -> None:
    allowed_files = ['prices/providers/aws.yml', 'tests/test_price_calc.py', 'prices/providers/openai.yml']

    assert allowed_price_check_files(ROOT, allowed_files, 'agentic-model-price-check.md', []) == allowed_files


@pytest.mark.parametrize(
    'pending_backfill',
    [
        None,
        [{'request_id': 'request', 'provider_id': 'aws'}],
        _pending('provider-that-does-not-exist'),
    ],
)
def test_weekly_scope_rejects_invalid_or_unknown_pending_rows(pending_backfill: object) -> None:
    with pytest.raises(ValueError, match='Pending price-check backfill'):
        allowed_price_check_files(ROOT, _all_provider_files(), 'agentic-price-check.md', pending_backfill)


def test_scope_rejects_unknown_workflow_source() -> None:
    with pytest.raises(ValueError, match='Unknown price-check workflow source'):
        allowed_price_check_files(ROOT, [], 'some-other-workflow.md', [])


def _run_git(root: Path, *args: str) -> str:
    result = subprocess.run(['git', *args], cwd=root, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _transport_repo(root: Path) -> tuple[str, Path]:
    root.mkdir()
    _run_git(root, 'init', '-q')
    _run_git(root, 'config', 'user.name', 'Price Check Tests')
    _run_git(root, 'config', 'user.email', 'price-check-tests@example.com')
    (root / '.github/workflows').mkdir(parents=True)
    (root / '.github/workflows/agentic-price-check.md').write_text(
        '---\nsafe-outputs:\n  create-pull-request:\n    allowed-files:\n'
        '      - prices/providers/openai.yml\n      - prices/providers/aws.yml\n'
        '      - prices/providers/quicksilverpro.yml\n---\n'
    )
    (root / '.github/agentic-price-check-providers.yml').write_text(
        'providers:\n  - file: prices/providers/openai.yml\n    sources: []\n'
    )
    providers = root / 'prices/providers'
    providers.mkdir(parents=True)
    for provider_id in ('openai', 'aws', 'quicksilverpro'):
        (providers / f'{provider_id}.yml').write_text(f'id: {provider_id}\nname: {provider_id}\npricing_urls: []\n')
    _run_git(root, 'add', '.')
    _run_git(root, 'commit', '--allow-empty', '-qm', 'trusted history')
    _run_git(root, 'commit', '--allow-empty', '-qm', 'trusted base')
    return _run_git(root, 'rev-parse', 'HEAD'), root.parent / 'artifacts'


def _commit_provider_change(root: Path, provider_id: str, *, rename: bool = False) -> None:
    provider = root / 'prices/providers' / f'{provider_id}.yml'
    if rename:
        _run_git(root, 'mv', str(provider.relative_to(root)), 'prices/providers/renamed.yml')
    else:
        provider.write_text(provider.read_text() + '# changed\n')
    _run_git(root, 'add', '-A')
    _run_git(root, 'commit', '-qm', f'change {provider_id}')


def _write_bundle(root: Path, artifact_dir: Path, name: str = 'aw-output.bundle') -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    _run_git(root, 'bundle', 'create', str(artifact_dir / name), 'HEAD')


def _write_patch(root: Path, artifact_dir: Path, name: str = 'aw-output.patch') -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    patch = subprocess.run(['git', 'format-patch', '-1', '--stdout'], cwd=root, check=True, capture_output=True)
    (artifact_dir / name).write_bytes(patch.stdout)


def test_bundle_rejects_quicksilver_provider_outside_baseline_weekly_scope(tmp_path: Path) -> None:
    repo = tmp_path / 'repo'
    base_sha, artifacts = _transport_repo(repo)
    _commit_provider_change(repo, 'quicksilverpro')
    _write_bundle(repo, artifacts)

    with pytest.raises(ValueError, match=r'outside weekly scope: prices/providers/quicksilverpro.yml'):
        validate_price_check_transports(repo, artifacts, base_sha, [])


def test_patch_allows_pending_aws_but_rejects_unrequested_provider(tmp_path: Path) -> None:
    repo = tmp_path / 'repo'
    base_sha, artifacts = _transport_repo(repo)
    _commit_provider_change(repo, 'aws')
    _write_patch(repo, artifacts)
    pending = _pending('aws')

    assert validate_price_check_transports(repo, artifacts, base_sha, pending) == ['prices/providers/aws.yml']

    _commit_provider_change(repo, 'quicksilverpro')
    _write_patch(repo, artifacts, 'aw-unrequested.patch')
    with pytest.raises(ValueError, match=r'outside weekly scope: prices/providers/quicksilverpro.yml'):
        validate_price_check_transports(repo, artifacts, base_sha, pending)


def test_discovery_sentinel_allows_existing_provider_changes_in_bundle(tmp_path: Path) -> None:
    repo = tmp_path / 'repo'
    base_sha, artifacts = _transport_repo(repo)
    _commit_provider_change(repo, 'quicksilverpro')
    _write_bundle(repo, artifacts)

    assert validate_price_check_transports(repo, artifacts, base_sha, _pending('_discovery')) == [
        'prices/providers/quicksilverpro.yml'
    ]


def test_bundle_gate_handles_the_default_shallow_trusted_checkout(tmp_path: Path) -> None:
    source = tmp_path / 'source'
    _transport_repo(source)
    repo = tmp_path / 'shallow'
    subprocess.run(
        ['git', 'clone', '--depth=1', f'file://{source}', str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    _run_git(repo, 'config', 'user.name', 'Price Check Tests')
    _run_git(repo, 'config', 'user.email', 'price-check-tests@example.com')
    base_sha = _run_git(repo, 'rev-parse', 'HEAD')
    artifacts = tmp_path / 'artifacts'
    _commit_provider_change(repo, 'openai')
    _write_bundle(repo, artifacts)

    assert validate_price_check_transports(repo, artifacts, base_sha, []) == ['prices/providers/openai.yml']


def test_bundle_detects_rename_and_delete_provider_paths(tmp_path: Path) -> None:
    repo = tmp_path / 'repo'
    base_sha, artifacts = _transport_repo(repo)
    _commit_provider_change(repo, 'quicksilverpro', rename=True)
    _write_bundle(repo, artifacts)

    with pytest.raises(ValueError, match=r'outside weekly scope: .*quicksilverpro.yml.*renamed.yml'):
        validate_price_check_transports(repo, artifacts, base_sha, [])


def test_invalid_bundle_and_symlink_are_rejected(tmp_path: Path) -> None:
    repo = tmp_path / 'repo'
    base_sha, artifacts = _transport_repo(repo)
    artifacts.mkdir()
    (artifacts / 'aw-malformed.bundle').write_bytes(b'not a bundle')

    with pytest.raises(ValueError, match=r'Git command failed \(bundle\)'):
        validate_price_check_transports(repo, artifacts, base_sha, [])

    (artifacts / 'aw-malformed.bundle').unlink()
    target = tmp_path / 'outside.patch'
    target.write_text('')
    (artifacts / 'aw-link.patch').symlink_to(target)
    with pytest.raises(ValueError, match='not a regular file'):
        validate_price_check_transports(repo, artifacts, base_sha, [])


def test_transport_cli_uses_contract_environment_and_reports_scope_failure(tmp_path: Path) -> None:
    repo = tmp_path / 'repo'
    base_sha, artifacts = _transport_repo(repo)
    _commit_provider_change(repo, 'quicksilverpro')
    _write_bundle(repo, artifacts)
    environment = os.environ.copy()
    environment['GITHUB_SHA'] = base_sha
    environment['PRICE_CHECK_PENDING_BACKFILL'] = json.dumps([])

    result = subprocess.run(
        [
            sys.executable,
            '-m',
            'scripts.price_check_scope_policy',
            '--validate-transports',
            '--repo-root',
            str(repo),
            '--artifact-dir',
            str(artifacts),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert result.stderr.startswith('Price-check transport scope validation failed: ')
    assert 'outside weekly scope: prices/providers/quicksilverpro.yml' in result.stderr

    environment['PRICE_CHECK_PENDING_BACKFILL'] = json.dumps(_pending('quicksilverpro'))
    allowed_result = subprocess.run(
        [
            sys.executable,
            '-m',
            'scripts.price_check_scope_policy',
            '--validate-transports',
            '--repo-root',
            str(repo),
            '--artifact-dir',
            str(artifacts),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert allowed_result.returncode == 0
    assert 'Price-check transport scope validation passed.' in allowed_result.stdout
