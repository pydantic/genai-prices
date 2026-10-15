import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from ruamel.yaml import YAML

WORKFLOWS = Path(__file__).resolve().parents[1] / '.github/workflows'


def read_workflow(filename: str) -> dict[str, Any]:
    content = (WORKFLOWS / filename).read_text()
    if filename.endswith('.md'):
        content = content.split('---', 2)[1]
    yaml: Any = YAML(typ='safe')
    return cast(dict[str, Any], yaml.load(content))


def test_price_updates_create_pr_before_notifying_slack() -> None:
    source = read_workflow('agentic-price-check.md')
    compiled = read_workflow('agentic-price-check.lock.yml')
    expected_schedule = [{'cron': '0 6-18 * * 1-5', 'timezone': 'America/Los_Angeles'}]
    assert source['on']['schedule'] == expected_schedule
    assert compiled['on']['schedule'] == expected_schedule
    assert 'workflow_dispatch' in source['on']
    assert 'workflow_dispatch' in compiled['on']
    assert source['if'] == "${{ vars.AGENTIC_WORKFLOWS_ENABLED == 'true' }}"
    assert compiled['jobs']['pre_activation']['if'] == "vars.AGENTIC_WORKFLOWS_ENABLED == 'true'"
    assert source['on']['permissions'] == {'pull-requests': 'read'}
    assert compiled['jobs']['pre_activation']['permissions'] == {'pull-requests': 'read'}
    assert 'Bash(git diff:*)' in json.dumps(compiled['jobs']['agent'])
    assert source['on']['skip-if-match'] == 'is:pr is:open author:app/genai-prices-automation'
    expected_concurrency = {
        'group': '${{ github.workflow }}',
        'cancel-in-progress': False,
        'queue': 'max',
    }
    assert source['concurrency'] == expected_concurrency
    assert compiled['concurrency'] == expected_concurrency
    assert 'create-issue' not in source['safe-outputs']
    assert source['safe-outputs']['report-failure-as-issue'] is False
    pr = source['safe-outputs']['create-pull-request']
    assert pr['max'] == 1
    assert pr['draft'] is False
    assert pr['base-branch'] == '${{ github.ref_name }}'
    assert pr['fallback-as-issue'] is False
    assert pr['max-patch-size'] == 10240
    assert 'github-token' not in pr
    assert 'PRICE_UPDATE_TOKEN' not in json.dumps(compiled)
    shared = read_workflow('shared/price-update.md')
    go_setup = next(step for step in shared['pre-agent-steps'] if step.get('uses', '').startswith('actions/setup-go@'))
    assert go_setup['with'] == {'go-version': '1.25.x', 'cache': False}
    app = shared['safe-outputs']['github-app']
    assert app == {
        'client-id': '${{ vars.PRICE_UPDATE_APP_CLIENT_ID }}',
        'private-key': '${{ secrets.PRICE_UPDATE_APP_PRIVATE_KEY }}',
        'owner': 'pydantic',
        'repositories': ['genai-prices'],
    }
    token_step = next(
        step for step in compiled['jobs']['safe_outputs']['steps'] if step.get('id') == 'safe-outputs-app-token'
    )
    handler_config_step = next(
        step
        for step in compiled['jobs']['safe_outputs']['steps']
        if 'GH_AW_SAFE_OUTPUTS_HANDLER_CONFIG' in step.get('env', {})
    )
    handler_config = json.loads(handler_config_step['env']['GH_AW_SAFE_OUTPUTS_HANDLER_CONFIG'])
    assert handler_config['create_pull_request']['base_branch'] == pr['base-branch']
    assert handler_config['create_pull_request']['max_patch_size'] == 10240
    assert token_step['with'] == {
        'client-id': app['client-id'],
        'private-key': app['private-key'],
        'owner': 'pydantic',
        'repositories': 'genai-prices',
        'github-api-url': '${{ github.api_url }}',
        'permission-contents': 'write',
        'permission-pull-requests': 'write',
    }
    assert pr['protected-files'] == {'policy': 'blocked', 'exclude': ['README.md']}
    assert 'prices/providers/.schema.json' not in pr['allowed-files']
    assert 'prices/units.yml' not in pr['allowed-files']
    assert 'prices/data.json' not in pr['allowed-files']
    assert 'prices/new_data/v2/data.json' in pr['allowed-files']
    assert 'prices/new_data/v2/data_slim.json' in pr['allowed-files']
    assert 'prices/new_data/v2/*.json' not in pr['allowed-files']
    assert 'packages/go/internal/data/prices.json' in pr['allowed-files']
    assert source['permissions'] == {'contents': 'read', 'pull-requests': 'read'}
    assert source['imports'] == ['shared/price-update.md']
    assert 'SLACK_WEBHOOK_URL' not in json.dumps(compiled['jobs']['agent'])
    assert 'PRICE_UPDATE_APP_PRIVATE_KEY' not in json.dumps(compiled['jobs']['agent'])
    assert compiled['jobs']['agent']['needs'] == 'activation'
    assert 'notify_slack' not in compiled['jobs']['safe_outputs']['needs']
    assert 'created_pr_url' in compiled['jobs']['safe_outputs']['outputs']
    notify = compiled['jobs']['notify_slack']
    assert set(notify['needs']) == {'agent', 'safe_outputs'}
    assert notify['if'] == "${{ !cancelled() && needs.safe_outputs.outputs.created_pr_url != '' }}"
    assert notify['uses'] == './.github/workflows/price-update-slack.yml'
    assert notify['with'] == {'pr-url': '${{ needs.safe_outputs.outputs.created_pr_url }}'}
    assert notify['secrets'] == {'SLACK_WEBHOOK_URL': '${{ secrets.SLACK_WEBHOOK_URL }}'}
    assert 'notify_auth_failure' not in source['jobs']
    assert 'notify_auth_failure' not in compiled['jobs']


def test_provider_allowlist_matches_manifest() -> None:
    manifest = read_workflow('../agentic-price-check-providers.yml')
    source = read_workflow('agentic-price-check.md')
    allowed = source['safe-outputs']['create-pull-request']['allowed-files']
    assert {path for path in allowed if path.endswith('.yml')} == {
        provider['file'] for provider in manifest['providers']
    }
    assert len(manifest['providers']) == 25
    assert len({provider['file'] for provider in manifest['providers']}) == 25
    provider_names = {provider['name'] for provider in manifest['providers']}
    required_names = {
        'OpenAI',
        'OpenAI Decisions',
        'Anthropic',
        'Google (Gemini)',
        'Mistral',
        'TypeSafe',
        'Z.AI',
        'Meta',
        'Modal',
    }
    assert required_names <= provider_names
    assert 'QuickSilver Pro' not in provider_names
    assert 'prices/providers/quicksilverpro.yml' not in {provider['file'] for provider in manifest['providers']}
    for provider in manifest['providers']:
        for url in provider['sources']:
            assert urlparse(cast(str, url)).netloc in source['network']['allowed']


def test_price_checks_use_one_scheduled_workflow() -> None:
    assert {path.name for path in WORKFLOWS.glob('agentic-price-check*.md')} == {'agentic-price-check.md'}
    assert {path.name for path in WORKFLOWS.glob('agentic-price-check*.lock.yml')} == {'agentic-price-check.lock.yml'}


def test_price_update_validation_commands_stop_on_failure(tmp_path: Path) -> None:
    shared_path = WORKFLOWS / 'shared/price-update.md'
    shared = shared_path.read_text()
    step5 = shared.split('## Step 5 - build, test, and create one PR\n', maxsplit=1)
    assert len(step5) == 2
    step5_content = step5[1].split('\n## ', maxsplit=1)[0]
    validation = re.search(r'```bash\n(.*?)\n```', step5_content, flags=re.DOTALL)
    assert validation is not None
    script = validation.group(1)
    command_log = tmp_path / 'commands.log'
    stub = tmp_path / 'command'
    stub.write_text(
        '#!/bin/sh\n'
        'printf \'%s %s\\n\' "${0##*/}" "$*" >> "$COMMAND_LOG"\n'
        'if [ "${FAIL_COMMAND:-}" = "${0##*/} $*" ]; then exit 17; fi\n'
    )
    stub.chmod(0o755)
    for command in ('make', 'npm'):
        (tmp_path / command).symlink_to(stub)

    expected_commands = [
        'make build',
        'make lint',
        'make typecheck',
        'make lint-go',
        'make test',
        'npm run ci',
        'make test-go',
    ]
    env = {**os.environ, 'PATH': f'{tmp_path}{os.pathsep}{os.environ["PATH"]}', 'COMMAND_LOG': str(command_log)}
    result = subprocess.run(['bash', '-o', 'pipefail', '-c', script], env=env, capture_output=True, text=True)
    assert result.returncode == 0
    assert command_log.read_text().splitlines() == expected_commands

    command_log.write_text('')
    failing_env = {**env, 'FAIL_COMMAND': 'make test'}
    result = subprocess.run(['bash', '-o', 'pipefail', '-c', script], env=failing_env, capture_output=True, text=True)
    assert result.returncode == 17
    assert command_log.read_text().splitlines() == expected_commands[:5]


def test_slack_payload_escapes_url_without_interpreting_shell() -> None:
    workflow = read_workflow('price-update-slack.yml')
    assert workflow['permissions'] == {}
    assert workflow['on']['workflow_call']['secrets']['SLACK_WEBHOOK_URL']['required'] is True
    step = workflow['jobs']['notify']['steps'][0]
    assert step['shell'] == 'bash'
    assert step['env']['SLACK_WEBHOOK_URL'] == '${{ secrets.SLACK_WEBHOOK_URL }}'
    script = step['run']
    assert '--fail' in script
    assert '--connect-timeout 10 --max-time 30' in script
    payload_script, _ = re.split(r'\|\s*curl\b', script, maxsplit=1)
    url = 'https://github.com/pydantic/genai-prices/pull/123?quote="\n$(exit 99)'
    result = subprocess.run(
        ['bash', '-e', '-o', 'pipefail', '-c', payload_script],
        env={**os.environ, 'PR_URL': url, 'SLACK_WEBHOOK_URL': 'unused'},
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout) == {
        'text': f'Review the GenAI Prices update: {url}',
        'unfurl_links': False,
        'unfurl_media': False,
    }
