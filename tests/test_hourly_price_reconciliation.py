import json
import os
import subprocess
from pathlib import Path

import pytest

from .test_price_update_workflows import read_workflow


def script(job: str, step_id: str) -> str:
    return next(s['run'] for s in read_workflow('update-prices.yml')['jobs'][job]['steps'] if s.get('id') == step_id)


def run_script(code: str, path: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ['bash', '-e', '-o', 'pipefail', '-c', code],
        cwd=path,
        env={**os.environ, **env},
        text=True,
        capture_output=True,
    )


def git(path: Path, *args: str) -> str:
    return subprocess.check_output(['git', '-C', str(path), *args], text=True, stderr=subprocess.DEVNULL).strip()


@pytest.fixture
def workflow_env(tmp_path: Path) -> dict[str, str]:
    (tmp_path / 'patches').mkdir()
    fake_gh = tmp_path / 'gh'
    fake_gh.write_text(
        '#!/bin/bash\n'
        'echo "$*" >> "$GH_CALLS"\n'
        'case "$2" in\n'
        'list) if [ "$1" = issue ]; then cat "$ISSUES"; else printf %s "$EXISTING"; fi ;;\n'
        'view) cat "$PREVIOUS_BODY"; echo ;;\n'
        'create) echo https://github.com/test/repo/123 ;;\n'
        'esac\n'
    )
    fake_gh.chmod(0o755)
    (tmp_path / 'previous-body').write_text('')
    (tmp_path / 'issues').write_text('[]')
    return {
        'PATH': f'{tmp_path}:{os.environ["PATH"]}',
        'RUNNER_TEMP': str(tmp_path),
        'GITHUB_OUTPUT': str(tmp_path / 'output'),
        'GITHUB_STEP_SUMMARY': str(tmp_path / 'summary'),
        'GITHUB_REPOSITORY': 'test/repo',
        'BRANCH': 'automation/hourly-price-update',
        'GH_TOKEN': 'token',
        'GH_CALLS': str(tmp_path / 'calls'),
        'PREVIOUS_BODY': str(tmp_path / 'previous-body'),
        'EXISTING': '',
        'ISSUES': str(tmp_path / 'issues'),
        'IMPORT_RESULT': 'success',
        'EXPECTED_COUNT': '1',
    }


@pytest.mark.parametrize('evidence', ['complete-empty', 'complete-change', 'failed', 'missing', 'conflict'])
def test_publisher_requires_complete_applicable_evidence(
    tmp_path: Path, workflow_env: dict[str, str], evidence: str
) -> None:
    git(tmp_path, 'init', '-b', 'main')
    git(tmp_path, 'config', 'user.name', 'Test')
    git(tmp_path, 'config', 'user.email', 'test@example.com')
    (tmp_path / 'price').write_text('old\n')
    git(tmp_path, 'add', 'price')
    git(tmp_path, 'commit', '-m', 'base')
    patch = ''
    if evidence in {'complete-change', 'conflict'}:
        (tmp_path / 'price').write_text('new\n')
        patch = git(tmp_path, 'diff', '--', 'price') + '\n'
        (tmp_path / 'price').write_text('conflict\n' if evidence == 'conflict' else 'old\n')
    if evidence != 'missing':
        (tmp_path / 'patches/source.patch').write_text(patch)
        (tmp_path / 'patches/source.notes').write_text('')
    if evidence == 'failed':
        workflow_env['IMPORT_RESULT'] = 'failure'
    result = run_script(script('pull-request', 'apply'), tmp_path, workflow_env)
    assert (result.returncode == 0) == evidence.startswith('complete')
    if evidence.startswith('complete'):
        assert (tmp_path / 'output').read_text() == ('importers=source\n' if patch else 'importers=\n')
    else:
        assert not (tmp_path / 'output').exists()
        assert not (tmp_path / 'calls').exists()


@pytest.mark.parametrize('existing', ['', '123'])
def test_authoritative_empty_result_closes_stale_pr_without_an_empty_commit(
    tmp_path: Path, workflow_env: dict[str, str], existing: str
) -> None:
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, 'init', '-b', 'main')
    git(repo, 'config', 'user.name', 'Test')
    git(repo, 'config', 'user.email', 'test@example.com')
    (repo / 'price').write_text('main\n')
    git(repo, 'add', 'price')
    git(repo, 'commit', '-m', 'base')
    before = git(repo, 'rev-parse', 'HEAD')
    workflow_env['EXISTING'] = existing
    result = run_script(script('pull-request', 'pr'), repo, workflow_env)
    assert result.returncode == 0, result.stderr
    assert git(repo, 'rev-parse', 'HEAD') == before
    calls = (tmp_path / 'calls').read_text()
    assert ('pr close 123' in calls) == bool(existing)
    assert 'pr create' not in calls and 'pr edit' not in calls


@pytest.mark.parametrize('changed_notes', [False, True])
@pytest.mark.parametrize('publication', ['same-tree', 'changed-tree', 'new-pr'])
def test_same_tree_still_refreshes_changed_notes_without_run_url_churn(
    tmp_path: Path, workflow_env: dict[str, str], changed_notes: bool, publication: str
) -> None:
    repo = tmp_path / 'repo'
    repo.mkdir()
    remote = tmp_path / 'remote'
    git(tmp_path, 'init', '--bare', str(remote))
    git(repo, 'init', '-b', 'main')
    git(repo, 'config', 'user.name', 'Test')
    git(repo, 'config', 'user.email', 'test@example.com')
    (repo / 'price').write_text('old\n')
    git(repo, 'add', 'price')
    git(repo, 'commit', '-m', 'base')
    base = git(repo, 'rev-parse', 'HEAD')
    (repo / 'price').write_text('newer\n' if publication == 'changed-tree' else 'new\n')
    git(repo, 'add', 'price')
    git(repo, 'commit', '-m', 'proposal')
    git(repo, 'push', str(remote), 'HEAD:automation/hourly-price-update')
    remote_head = git(remote, 'rev-parse', 'refs/heads/automation/hourly-price-update')
    git(repo, 'reset', '--hard', base)
    (repo / 'price').write_text('new\n')
    (tmp_path / 'pr-body.md').write_text('Run https://github.com/test/repo/actions/runs/42\n\nNew notes\n')
    (tmp_path / 'previous-body').write_text(
        'Run https://github.com/test/repo/actions/runs/41\n\n' + ('Old notes\n' if changed_notes else 'New notes\n')
    )
    workflow_env.update(
        {
            'EXISTING': '' if publication == 'new-pr' else '123',
            'GIT_CONFIG_COUNT': '1',
            'GIT_CONFIG_KEY_0': f'url.{remote}.insteadOf',
            'GIT_CONFIG_VALUE_0': 'https://x-access-token:token@github.com/test/repo.git',
        }
    )
    result = run_script(script('pull-request', 'pr'), repo, workflow_env)
    assert result.returncode == 0, result.stderr
    assert (git(remote, 'rev-parse', 'refs/heads/automation/hourly-price-update') == remote_head) == (
        publication == 'same-tree'
    )
    calls = (tmp_path / 'calls').read_text()
    assert ('pr edit 123' in calls) == (changed_notes and publication != 'new-pr')
    assert ('pr create' in calls) == (publication == 'new-pr')
    if publication == 'new-pr':
        assert (tmp_path / 'output').read_text() == 'created-pr-url=https://github.com/test/repo/123\n'


@pytest.mark.parametrize('report', ['new', 'unchanged', 'changed', 'resolved', 'empty', 'incomplete'])
@pytest.mark.parametrize('actor', ['github-actions[bot]', 'app/github-actions'])
def test_manual_only_reports_are_durable_and_deduplicated(
    tmp_path: Path, workflow_env: dict[str, str], report: str, actor: str
) -> None:
    notes = '' if report in {'resolved', 'empty', 'incomplete'} else 'Source: kept m unchanged; update them by hand\n'
    if report != 'incomplete':
        (tmp_path / 'patches/source.notes').write_text(notes)
    existing = report in {'unchanged', 'changed', 'resolved', 'incomplete'}
    workflow_env['EXISTING'] = '123' if existing else ''
    (tmp_path / 'issues').write_text(
        json.dumps(
            [{'number': 123, 'title': 'Provider prices needing manual review', 'author': {'login': actor}}]
            if existing
            else []
        )
    )
    body = (
        'The hourly price importers reported changes that need manual review.\n\n'
        'This report is refreshed after a complete successful import; unchanged reports do not notify again.\n\n'
        '- Source: kept m unchanged; update them by hand\n'
    )
    (tmp_path / 'previous-body').write_text(body if report == 'unchanged' else 'Previous notes\n')
    result = run_script(script('manual-updates', 'report'), tmp_path, workflow_env)
    assert (result.returncode == 0) == (report != 'incomplete')
    calls = (tmp_path / 'calls').read_text() if (tmp_path / 'calls').exists() else ''
    assert ('issue create' in calls) == (report == 'new')
    assert ('issue edit' in calls) == (report == 'changed')
    assert ('issue close' in calls) == (report == 'resolved')
    if report == 'incomplete':
        assert not calls
    if notes:
        assert (tmp_path / 'manual-body.md').read_text() == body


def test_status_functions_and_token_boundaries() -> None:
    workflow = read_workflow('update-prices.yml')
    jobs = workflow['jobs']
    for name in ['notify', 'notify-failure', 'notify-manual']:
        assert '!cancelled()' in jobs[name]['if']
    assert jobs['manual-updates']['if'] == "${{ !cancelled() && needs.import.result == 'success' }}"
    assert jobs['manual-updates']['permissions'] == {'issues': 'write'}
    assert jobs['import']['permissions'] == {'contents': 'read'}
    assert jobs['pull-request']['permissions'] == {'contents': 'read'}
    steps = jobs['pull-request']['steps']
    build = next(i for i, step in enumerate(steps) if 'make collapse-models build' in step.get('run', ''))
    token = next(i for i, step in enumerate(steps) if step.get('id') == 'app-token')
    assert build < token
    assert workflow['on']['schedule'] == [{'cron': '17 * * * *'}]
