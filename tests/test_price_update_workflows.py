import json
import os
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest
from ruamel.yaml import YAML

WORKFLOWS = Path(__file__).resolve().parents[1] / '.github/workflows'


def read_workflow(filename: str) -> dict[str, Any]:
    content = (WORKFLOWS / filename).read_text()
    if filename.endswith('.md'):
        content = content.split('---', 2)[1]
    yaml: Any = YAML(typ='safe')
    return cast(dict[str, Any], yaml.load(content))


@pytest.mark.parametrize('group', ['openai-anthropic', 'google-mistral', 'direct-providers'])
def test_daily_price_updates_create_pr_before_notifying_slack(group: str) -> None:
    source = read_workflow(f'agentic-price-check-{group}.md')
    compiled = read_workflow(f'agentic-price-check-{group}.lock.yml')
    assert source['on']['schedule'] == 'daily'
    assert 'is:pr is:open' in source['on']['skip-if-match']
    assert compiled['on']['schedule'][0]['cron'].split()[2:] == ['*', '*', '*']
    assert source['concurrency']['cancel-in-progress'] is False
    assert 'create-issue' not in source['safe-outputs']
    assert source['safe-outputs']['report-failure-as-issue'] is False
    pr = source['safe-outputs']['create-pull-request']
    assert pr['max'] == 1
    assert pr['draft'] is False
    assert pr['fallback-as-issue'] is False
    assert 'github-token' not in pr
    assert 'PRICE_UPDATE_TOKEN' not in json.dumps(compiled)
    app = read_workflow('shared/price-update.md')['safe-outputs']['github-app']
    assert app == {
        'client-id': '${{ vars.PRICE_UPDATE_APP_CLIENT_ID }}',
        'private-key': '${{ secrets.PRICE_UPDATE_APP_PRIVATE_KEY }}',
        'owner': 'pydantic',
        'repositories': ['genai-prices'],
    }
    token_step = next(
        step for step in compiled['jobs']['safe_outputs']['steps'] if step.get('id') == 'safe-outputs-app-token'
    )
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
    assert notify['if'] == (
        "${{ !cancelled() && needs.safe_outputs.result == 'success' && needs.safe_outputs.outputs.created_pr_url != '' }}"
    )
    assert notify['uses'] == './.github/workflows/price-update-slack.yml'
    assert notify['with'] == {'pr-url': '${{ needs.safe_outputs.outputs.created_pr_url }}'}
    assert notify['secrets'] == {'SLACK_WEBHOOK_URL': '${{ secrets.SLACK_WEBHOOK_URL }}'}
    assert 'notify_auth_failure' not in source['jobs']
    assert 'notify_auth_failure' not in compiled['jobs']


def test_direct_provider_allowlist_matches_manifest() -> None:
    manifest = read_workflow('../agentic-price-check-providers.yml')
    source = read_workflow('agentic-price-check-direct-providers.md')
    allowed = source['safe-outputs']['create-pull-request']['allowed-files']
    assert {path for path in allowed if path.endswith('.yml')} == {
        provider['file'] for provider in manifest['providers']
    }


def test_slack_payload_escapes_url_without_interpreting_shell() -> None:
    workflow = read_workflow('price-update-slack.yml')
    assert workflow['permissions'] == {}
    assert workflow['on']['workflow_call']['secrets']['SLACK_WEBHOOK_URL']['required'] is True
    step = workflow['jobs']['notify']['steps'][0]
    assert step['env']['SLACK_WEBHOOK_URL'] == '${{ secrets.SLACK_WEBHOOK_URL }}'
    script = step['run']
    assert '--fail' in script
    assert '--connect-timeout 10 --max-time 30' in script
    payload_script = script.split('| curl', 1)[0]
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
