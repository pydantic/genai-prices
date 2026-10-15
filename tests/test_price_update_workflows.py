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
    proposal_query = 'is:pr is:open author:app/genai-prices-automation'
    assert source['on']['skip-if-match'] == proposal_query
    pre_activation = compiled['jobs']['pre_activation']
    skip_step = next(step for step in pre_activation['steps'] if step.get('id') == 'check_skip_if_match')
    assert skip_step['env']['GH_AW_SKIP_QUERY'] == proposal_query
    assert "steps.check_skip_if_match.outputs.skip_check_ok == 'true'" in pre_activation['outputs']['activated']
    assert "needs.pre_activation.outputs.activated == 'true'" in compiled['jobs']['activation']['if']
    expected_concurrency = {
        'group': '${{ github.workflow }}',
        'cancel-in-progress': False,
        'queue': 'max',
    }
    assert source['concurrency'] == expected_concurrency
    assert compiled['concurrency'] == expected_concurrency
    assert 'create-issue' not in source['safe-outputs']
    assert source['safe-outputs']['report-failure-as-issue'] is False
    assert source['safe-outputs']['report-incomplete'] == {'create-issue': False}
    pr = source['safe-outputs']['create-pull-request']
    assert pr['max'] == 1
    assert pr['draft'] is False
    base_branch = pr.get('base-branch')
    assert base_branch is None or (isinstance(base_branch, str) and '${' not in base_branch)
    assert pr['fallback-as-issue'] is False
    assert pr['max-patch-size'] == 10240
    assert source['engine']['model'] == 'anthropic/glm-5.3-flash'
    engine = read_workflow('shared/price-check-engine.md')['engine']
    assert engine['id'] == 'pydantic-ai'
    assert engine['version'] == '0.56.0'
    assert engine['env'] == {
        'PAI_AGENT': 'scripts.price_check_agent:agent',
        'ANTHROPIC_BASE_URL': 'https://api.z.ai/api/anthropic',
        'ANTHROPIC_API_KEY': '${{ secrets.ZAI_API_KEY }}',
    }
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
    compiled_base_branch = handler_config['create_pull_request'].get('base_branch')
    assert compiled_base_branch == base_branch
    assert handler_config['create_pull_request']['max_patch_size'] == 10240
    execution_step = next(step for step in compiled['jobs']['agent']['steps'] if step.get('id') == 'agentic_execution')
    execution_command = execution_step['run']
    assert 'pydantic-ai_harness.cjs clai2' in execution_command
    assert '--exclude-env ANTHROPIC_API_KEY' in execution_command
    assert '--anthropic-api-base-path /api/anthropic' in execution_command
    assert execution_step['env']['PAI_MODEL'] == 'anthropic/glm-5.3-flash'
    assert execution_step['env']['PAI_AGENT'] == 'scripts.price_check_agent:agent'
    assert execution_step['env']['ANTHROPIC_API_KEY'] == '${{ secrets.ZAI_API_KEY }}'
    assert compiled['jobs']['agent']['env']['GH_AW_ENGINE_VERSION'] == '0.56.0'
    assert 'observability' not in source
    excluded_env = read_workflow('shared/price-check-engine.md')['excluded-env']
    assert excluded_env == [
        'GH_AW_OTLP_ENDPOINTS',
        'OTEL_EXPORTER_OTLP_ENDPOINT',
        'OTEL_EXPORTER_OTLP_HEADERS',
    ]
    for name in excluded_env:
        assert f'--exclude-env {name}' in execution_command
    config_line = next(
        line
        for line in execution_command.splitlines()
        if 'awf-config.json' in line and line.strip().startswith('printf')
    )
    proxy = json.loads(config_line.split("' '", 1)[1].split("' >", 1)[0])['apiProxy']
    assert proxy['maxRuns'] == 500
    assert 'maxAiCredits' not in proxy
    assert proxy['enableTokenSteering'] is False
    assert proxy['modelFallback'] == {'enabled': False}
    assert proxy['targets']['anthropic'] == {'host': 'api.z.ai'}
    assert proxy['defaultAiCreditsPricing'] == {'input': 0.15, 'cachedInput': 0.03, 'output': 0.5}
    assert proxy['providers']['anthropic']['models']['glm-5.3-flash']['cost'] == {
        'input': 0.00000015,
        'cache_read': 0.00000003,
        'output': 0.00000050,
    }
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
    assert source['imports'] == [
        'shared/price-check-engine.md',
        'pydantic/pydantic-ai/src/pydantic_ai_harness/gh-aw/pydantic.md@main',
        'shared/price-update.md',
    ]
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


def test_logfire_credential_is_scoped_to_post_agent_export() -> None:
    compiled = read_workflow('agentic-price-check.lock.yml')
    assert 'LOGFIRE_OTLP_AUTHORIZATION' not in json.dumps(compiled.get('env', {}))
    steps = compiled['jobs']['agent']['steps']
    execution_index = next(i for i, step in enumerate(steps) if step.get('id') == 'agentic_execution')
    export_index = next(i for i, step in enumerate(steps) if step.get('name') == 'Export price-check telemetry')
    assert execution_index < export_index
    for step in steps[:export_index]:
        assert 'LOGFIRE_OTLP_AUTHORIZATION' not in json.dumps(step)
    assert steps[export_index]['env'] == {
        'OTEL_EXPORTER_OTLP_HEADERS': 'Authorization=${{ secrets.LOGFIRE_OTLP_AUTHORIZATION }}'
    }
    assert steps[export_index]['if'] == 'always()'
    assert steps[export_index]['continue-on-error'] is True


def test_logfire_export_uses_whole_run_usage_and_deduplicates_requests() -> None:
    workflow = read_workflow('agentic-price-check.md')
    script = workflow['post-steps'][0]['with']['script']
    driver = r"""
const script = JSON.parse(process.env.EXPORT_SCRIPT);
const files = {
  '/tmp/gh-aw/agent-session.jsonl': [
    'debug output', 'null',
    JSON.stringify({type: 'tool.execution_start', data: {toolName: 'web_fetch'}})
  ].join('\n'),
  '/tmp/gh-aw/agent_usage.json': JSON.stringify({primary_model: 'model', input_tokens: 11,
    cache_read_tokens: 100, cache_write_tokens: 0, output_tokens: 7}),
  '/tmp/gh-aw/agent_output.json': JSON.stringify({items: [{type: 'noop'}]}),
  '/tmp/gh-aw/sandbox/firewall/logs/api-proxy-logs/otel.jsonl': [1, 1].map(() => JSON.stringify({
    spanId: '1234567890abcdef', name: 'api_proxy.anthropic.request', startTimeMs: 1000, endTimeMs: 2000,
    attributes: {'awf.request_id': 'request-1'}, status: {code: 1}, kind: 3
  })).join('\n')
};
let payload;
const summaries = [];
const core = {summary: {addRaw(value) { summaries.push(value); return this; }, async write() {}}};
const fakeRequire = (name) => {
  if (name === 'node:fs') return {
    readFileSync: (file) => files[file], existsSync: () => false,
    mkdirSync: () => {}, writeFileSync: (file, value) => { files[file] = value; }
  };
  if (name.endsWith('send_otlp_span.cjs')) return {
    buildAttr: (key, value) => ({key, value}),
    buildOTLPPayload: (options) => ({resourceSpans: [options]}),
    sendOTLPSpan: async (endpoint, data) => { payload = {endpoint, ...data}; }
  };
  return require(name);
};
const run = new (async () => {}).constructor('require', 'process', 'core', script);
(async () => {
  await run(fakeRequire, {env: {RUNNER_TEMP: '/runner', GITHUB_REPOSITORY: 'pydantic/genai-prices',
    GITHUB_RUN_ID: '123', GITHUB_RUN_ATTEMPT: '1', GITHUB_SHA: 'sha'}}, core);
  const spans = payload.resourceSpans;
  const usage = Object.fromEntries(spans.find((span) => span.spanName === 'price_check.usage').attributes
    .map(({key, value}) => [key, value]));
  const agent = spans.find((span) => span.spanName === 'invoke_agent');
  const toolCounts = JSON.parse(agent.attributes.find(({key}) => key === 'price_check.tool_counts').value);
  files['/tmp/gh-aw/agent_output.json'] = JSON.stringify({items: [{type: 'report_incomplete'}]});
  await run(fakeRequire, {env: {RUNNER_TEMP: '/runner'}}, core);
  const partialStatus = payload.resourceSpans.find((span) => span.spanName === 'invoke_agent').statusCode;
  let incomplete = false;
  files['/tmp/gh-aw/agent_usage.json'] = '{}';
  try { await run(fakeRequire, {env: {RUNNER_TEMP: '/runner'}}, core); } catch { incomplete = true; }
  console.log(JSON.stringify({endpoint: payload.endpoint, names: spans.map((span) => span.spanName),
    usage, toolCounts, completedStatus: agent.statusCode, partialStatus, incomplete, summaries}));
})();
"""
    result = subprocess.run(
        ['node', '-e', driver],
        env={**os.environ, 'EXPORT_SCRIPT': json.dumps(script)},
        capture_output=True,
        text=True,
        check=True,
    )
    output = json.loads(result.stdout)
    assert output['endpoint'] == 'https://logfire-eu.pydantic.info'
    assert output['names'] == ['invoke_agent', 'price_check.usage', 'api_proxy.anthropic.request']
    assert output['usage'] == {
        'gen_ai.request.model': 'model',
        'price_check.usage.source': 'gh-aw.agent_usage',
        'price_check.usage.uncached_input': 11,
        'price_check.usage.cached_input': 100,
        'price_check.usage.cache_creation': 0,
        'price_check.usage.output': 7,
    }
    assert output['incomplete'] is True
    assert output['completedStatus'] == 1
    assert output['partialStatus'] == 2
    assert output['toolCounts'] == {'web_fetch': 1}
    assert any('telemetry incomplete' in summary for summary in output['summaries'])
