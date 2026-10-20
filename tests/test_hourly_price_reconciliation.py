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
        'view) if [[ "$*" = *"--json state"* ]]; then echo OPEN; else cat "$PREVIOUS_BODY"; echo; fi ;;\n'
        'create) echo https://github.com/test/repo/123 ;;\n'
        'esac\n'
    )
    fake_gh.chmod(0o755)
    (tmp_path / 'previous-body').write_text('')
    (tmp_path / 'calls').write_text('')
    (tmp_path / 'issues').write_text('[]')
    return {
        'PATH': f'{tmp_path}:{os.environ["PATH"]}',
        'RUNNER_TEMP': str(tmp_path),
        'GITHUB_OUTPUT': str(tmp_path / 'output'),
        'GITHUB_STEP_SUMMARY': str(tmp_path / 'summary'),
        'GITHUB_REPOSITORY': 'test/repo',
        'GITHUB_WORKSPACE': str(Path(__file__).parents[1]),
        'BRANCH': 'automation/hourly-price-update',
        'GH_TOKEN': 'token',
        'GH_CALLS': str(tmp_path / 'calls'),
        'PREVIOUS_BODY': str(tmp_path / 'previous-body'),
        'EXISTING': '',
        'ISSUES': str(tmp_path / 'issues'),
        'IMPORT_RESULT': 'success',
        'EXPECTED_COUNT': '1',
        'COMPLETE': 'true',
        'PREVIOUS_HEAD': '',
        'PREVIOUS_PR': '',
    }


@pytest.mark.parametrize('evidence', ['complete-empty', 'complete-change', 'failed', 'missing', 'conflict'])
def test_publisher_applies_available_patches_and_reports_completeness(
    tmp_path: Path, workflow_env: dict[str, str], evidence: str
) -> None:
    git(tmp_path, 'init', '-b', 'main')
    git(tmp_path, 'config', 'user.name', 'Test')
    git(tmp_path, 'config', 'user.email', 'test@example.com')
    (tmp_path / 'price').write_text('old\n')
    git(tmp_path, 'add', 'price')
    git(tmp_path, 'commit', '-m', 'base')
    patch = ''
    if evidence in {'complete-change', 'failed', 'conflict'}:
        (tmp_path / 'price').write_text('new\n')
        patch = git(tmp_path, 'diff', '--', 'price') + '\n'
        (tmp_path / 'price').write_text('conflict\n' if evidence == 'conflict' else 'old\n')
        git(tmp_path, 'add', 'price')
    if evidence != 'missing':
        (tmp_path / 'patches/source.patch').write_text(patch)
        (tmp_path / 'patches/source.notes').write_text('')
    if evidence == 'failed':
        # Another importer failed; this one's patch still publishes.
        workflow_env['IMPORT_RESULT'] = 'failure'
    result = run_script(script('pull-request', 'apply'), tmp_path, workflow_env)
    assert (result.returncode == 0) == (evidence != 'conflict')
    if evidence == 'conflict':
        assert not (tmp_path / 'output').exists()
    else:
        complete = 'true' if evidence.startswith('complete') else 'false'
        importers = 'source' if patch else ''
        assert (tmp_path / 'output').read_text() == f'complete={complete}\nimporters={importers}\n'
        assert (git(tmp_path, 'diff', '--cached', '--name-only') == 'price') == bool(patch)


@pytest.mark.parametrize('complete', ['true', 'false'])
@pytest.mark.parametrize('existing', ['', '123'])
def test_only_a_complete_empty_result_closes_the_stale_pr(
    tmp_path: Path, workflow_env: dict[str, str], existing: str, complete: str
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
    workflow_env.update({'EXISTING': existing, 'PREVIOUS_PR': existing, 'COMPLETE': complete})
    result = run_script(script('pull-request', 'pr'), repo, workflow_env)
    assert result.returncode == 0, result.stderr
    assert git(repo, 'rev-parse', 'HEAD') == before
    calls = (tmp_path / 'calls').read_text()
    assert ('pr close 123' in calls) == (bool(existing) and complete == 'true')
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
    git(repo, 'config', 'user.email', 'genai-prices-automation[bot]@users.noreply.github.com')
    git(repo, 'commit', '-m', 'Update provider prices from official sources')
    remote_head = git(repo, 'rev-parse', 'HEAD')
    git(repo, 'remote', 'add', 'origin', str(remote))
    if publication != 'new-pr':
        git(repo, 'push', str(remote), 'HEAD:automation/hourly-price-update')
    git(repo, 'reset', '--hard', base)
    (repo / 'price').write_text('new\n')
    (tmp_path / 'pr-body.md').write_text('Run https://github.com/test/repo/actions/runs/42\n\nNew notes\n')
    (tmp_path / 'previous-body').write_text(
        'Run https://github.com/test/repo/actions/runs/41\n\n' + ('Old notes\n' if changed_notes else 'New notes\n')
    )
    workflow_env.update(
        {
            'EXISTING': '' if publication == 'new-pr' else '123',
            'PREVIOUS_PR': '' if publication == 'new-pr' else '123',
            'PREVIOUS_HEAD': '' if publication == 'new-pr' else remote_head,
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


NEW_FINDING = 'Source: kept a unchanged; update them by hand'
OLD_FINDING = 'Other: kept b unchanged; update them by hand'


def manual_body(*findings: str) -> str:
    return (
        'The hourly price importers reported changes that need manual review.\n\n'
        'A run where every importer succeeds replaces this list; a run with failing importers only adds to it. '
        'New findings are also posted as comments.\n\n' + ''.join(f'- {finding}\n' for finding in sorted(findings))
    )


# report: (findings this run, None for a missing artifact; findings already listed, None for no issue;
#          import result; issue actions; findings listed afterwards)
MANUAL_REPORTS: dict[str, tuple[list[str] | None, list[str] | None, str, set[str], list[str] | None]] = {
    'new': ([NEW_FINDING], None, 'success', {'create'}, [NEW_FINDING]),
    'unchanged': ([NEW_FINDING], [NEW_FINDING], 'success', set(), [NEW_FINDING]),
    'replaced': ([NEW_FINDING], [OLD_FINDING], 'success', {'edit', 'comment'}, [NEW_FINDING]),
    'resolved': ([], [OLD_FINDING], 'success', {'close'}, None),
    'empty': ([], None, 'success', set(), None),
    'partial-new': ([NEW_FINDING], [OLD_FINDING], 'failure', {'edit', 'comment'}, [NEW_FINDING, OLD_FINDING]),
    'partial-missing': (None, [OLD_FINDING], 'failure', set(), [OLD_FINDING]),
}


@pytest.mark.parametrize('report', MANUAL_REPORTS)
@pytest.mark.parametrize('actor', ['github-actions[bot]', 'app/github-actions'])
def test_manual_reports_reconcile_on_complete_runs_and_only_add_on_partial_runs(
    tmp_path: Path, workflow_env: dict[str, str], report: str, actor: str
) -> None:
    findings, listed, import_result, actions, expected = MANUAL_REPORTS[report]
    if findings is not None:
        (tmp_path / 'patches/source.notes').write_text(''.join(f'{finding}\n' for finding in findings))
    workflow_env['IMPORT_RESULT'] = import_result
    (tmp_path / 'issues').write_text(
        json.dumps(
            [{'number': 123, 'title': 'Provider prices needing manual review', 'author': {'login': actor}}]
            if listed is not None
            else []
        )
    )
    # Bodies edited in the GitHub UI come back with CRLF line endings.
    (tmp_path / 'previous-body').write_text(manual_body(*listed).replace('\n', '\r\n') if listed is not None else '')
    result = run_script(script('manual-updates', 'report'), tmp_path, workflow_env)
    assert result.returncode == 0, result.stderr
    calls = (tmp_path / 'calls').read_text()
    assert {action for action in ['create', 'edit', 'comment', 'close'] if f'issue {action}' in calls} == actions
    if expected is not None:
        assert (tmp_path / 'manual-body.md').read_text() == manual_body(*expected)
    if 'comment' in actions:
        assert (
            tmp_path / 'manual-comment.md'
        ).read_text() == f'New findings since the last report:\n\n- {NEW_FINDING}\n'


def test_status_functions_and_token_boundaries() -> None:
    workflow = read_workflow('update-prices.yml')
    jobs = workflow['jobs']
    for name in ['notify', 'notify-failure', 'notify-manual']:
        assert '!cancelled()' in jobs[name]['if']
    assert jobs['manual-updates']['if'] == '${{ !cancelled() }}'
    assert jobs['manual-updates']['permissions'] == {'issues': 'write'}
    assert jobs['import']['permissions'] == {'contents': 'read'}
    assert jobs['pull-request']['permissions'] == {'contents': 'read', 'pull-requests': 'read'}
    steps = jobs['pull-request']['steps']
    build = next(i for i, step in enumerate(steps) if 'make collapse-models build' in step.get('run', ''))
    token = next(i for i, step in enumerate(steps) if step.get('id') == 'app-token')
    assert build < token
