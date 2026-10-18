import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

import pytest
from ruamel.yaml import YAML

from scripts.price_check_sources import load_provider_sources, official_source_hosts

WORKFLOWS = Path(__file__).resolve().parents[1] / '.github/workflows'
ROOT = WORKFLOWS.parents[1]
ENGINE_IMPORT_PIN = '94fc592c15981441d462ee213859da0a18170d15'
ENGINE_IMPORT_CACHE = (
    ROOT / '.github/aw/imports/pydantic/pydantic-ai' / ENGINE_IMPORT_PIN / 'src_pydantic_ai_harness_gh-aw_pydantic.md'
)


def read_workflow(filename: str) -> dict[str, Any]:
    content = (WORKFLOWS / filename).read_text()
    if filename.endswith('.md'):
        content = content.partition('\n---\n')[0].removeprefix('---\n')
    yaml: Any = YAML(typ='safe')
    return cast(dict[str, Any], yaml.load(content))


def test_price_updates_create_pr_before_notifying_slack() -> None:
    source = read_workflow('agentic-price-check.md')
    compiled = read_workflow('agentic-price-check.lock.yml')
    expected_schedule = [{'cron': '0 6 * * 1', 'timezone': 'UTC'}]
    assert source['on']['schedule'] == expected_schedule
    assert compiled['on']['schedule'] == expected_schedule
    assert 'workflow_dispatch' in source['on']
    assert 'workflow_dispatch' in compiled['on']
    assert source['if'] == "${{ vars.AGENTIC_WORKFLOWS_ENABLED == 'true' }}"
    assert compiled['jobs']['pre_activation']['if'] == "vars.AGENTIC_WORKFLOWS_ENABLED == 'true'"
    assert source['on']['permissions'] == {'pull-requests': 'read'}
    assert compiled['jobs']['pre_activation']['permissions'] == {'pull-requests': 'read'}
    proposal_query = 'is:pr is:open author:app/genai-prices-automation -head:automation/hourly-price-update'
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
    assert {path for path in pr['allowed-files'] if path.startswith('tests/')} == {
        'tests/test_price_calc.py',
        'tests/test_price_regressions.py',
        'tests/test_price_check_additions.py',
        'tests/dataset/usages.json',
    }
    assert source['permissions'] == {'contents': 'read', 'pull-requests': 'read'}
    assert source['imports'] == [
        'shared/price-check-engine.md',
        f'pydantic/pydantic-ai/src/pydantic_ai_harness/gh-aw/pydantic.md@{ENGINE_IMPORT_PIN}',
        'shared/price-update.md',
        'shared/price-check-runtime.md',
        'shared/price-check-observability.md',
        'shared/price-check-network.md',
    ]
    assert ENGINE_IMPORT_CACHE.is_file()
    runtime = read_workflow('shared/price-check-runtime.md')
    assert [step['name'] for step in runtime['pre-agent-steps']] == [
        'Install the gh-aw fetch transport',
        'Install the price-check scope preflight',
        'Snapshot trusted provider sources',
    ]
    observability = read_workflow('shared/price-check-observability.md')
    assert [step['name'] for step in observability['post-steps']] == [
        'Export price-check telemetry',
        'Stage the model price-check report',
        'Upload the model price-check report',
    ]
    assert read_workflow('shared/price-check-network.md')['network']['allowed']
    backfill = source['jobs']['report_backfill']
    assert backfill['needs'] == ['backfill_requests', 'agent', 'safe_outputs']
    assert "needs.backfill_requests.outputs.pending != '[]'" in backfill['if']
    assert source['jobs']['agent']['needs'] == ['backfill_requests']
    backfill_text = (
        (WORKFLOWS / 'agentic-price-check.md').read_text().split('## Requested-model rollout backfill\n', maxsplit=1)[1]
    )
    assert 'For backlog providers outside the weekly manifest, check only the specified model' in backfill_text
    assert 'without sweeping unrelated models at those providers' in backfill_text
    assert 'SLACK_WEBHOOK_URL' not in json.dumps(compiled['jobs']['agent'])
    assert 'PRICE_UPDATE_APP_PRIVATE_KEY' not in json.dumps(compiled['jobs']['agent'])
    assert compiled['jobs']['agent']['needs'] == ['activation', 'backfill_requests']
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
    manifest_files = {provider['file'] for provider in manifest['providers']}
    assert manifest_files <= {path for path in allowed if path.endswith('.yml')}
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
    assert 'prices/providers/quicksilverpro.yml' not in manifest_files
    provider_files = {provider.file for provider in load_provider_sources(ROOT)}
    assert {
        path for path in allowed if path.startswith('prices/providers/') and path.endswith('.yml')
    } == provider_files
    assert 'prices/providers/quicksilverpro.yml' in provider_files
    network_hosts = set(read_workflow('shared/price-check-network.md')['network']['allowed'])
    for provider in manifest['providers']:
        for url in provider['sources']:
            assert urlparse(cast(str, url)).netloc in network_hosts


def test_targeted_request_uses_all_provider_files_and_the_trusted_host_set() -> None:
    source = read_workflow('agentic-model-price-check.md')
    allowed = source['safe-outputs']['create-pull-request']['allowed-files']
    provider_files = {provider.file for provider in load_provider_sources(ROOT)}
    assert {
        path for path in allowed if path.startswith('prices/providers/') and path.endswith('.yml')
    } == provider_files
    assert {path for path in allowed if path.startswith('tests/')} == {
        'tests/test_price_calc.py',
        'tests/test_price_regressions.py',
        'tests/test_price_check_additions.py',
        'tests/dataset/usages.json',
    }
    network = read_workflow('shared/price-check-network.md')['network']['allowed']
    assert set(network) == set(official_source_hosts(ROOT)) | {'defaults', 'api.z.ai'}
    assert 'shared/price-check-network.md' in source['imports']
    assert (
        'Read `$RUNNER_TEMP/gh-aw/price-check/provider-sources.json`'
        in (WORKFLOWS / 'agentic-model-price-check.md').read_text()
    )


def test_weekly_publication_scope_gate_runs_before_safe_outputs() -> None:
    gate_name = 'Verify weekly provider scope before publication'
    gate_command = 'uv run --frozen python -m scripts.price_check_scope_policy --validate-transports'
    gate_env = {'PRICE_CHECK_PENDING_BACKFILL': "${{ needs.backfill_requests.outputs.pending || '[]' }}"}
    weekly_source = read_workflow('agentic-price-check.md')
    weekly_compiled = read_workflow('agentic-price-check.lock.yml')
    source_safe_outputs = weekly_source['safe-outputs']
    compiled_safe_outputs = weekly_compiled['jobs']['safe_outputs']

    assert source_safe_outputs['needs'] == ['backfill_requests']
    source_steps = source_safe_outputs['steps']
    assert [step['name'] for step in source_steps] == [
        'Check out the policy source when the publisher checkout was skipped',
        'Set up uv for the trusted provider scope check',
        gate_name,
    ]
    assert source_steps[0]['if'] == "${{ !contains(needs.agent.outputs.output_types, 'create_pull_request') }}"
    assert source_steps[0]['with'] == {'ref': '${{ github.sha }}', 'persist-credentials': False}
    source_gate = source_steps[2]
    assert source_gate['run'] == gate_command
    assert source_gate['env'] == gate_env
    assert 'if' not in source_gate
    assert 'continue-on-error' not in source_gate

    assert 'backfill_requests' in compiled_safe_outputs['needs']
    compiled_steps = compiled_safe_outputs['steps']
    compiled_gate_index = next(i for i, step in enumerate(compiled_steps) if step.get('name') == gate_name)
    compiled_gate = compiled_steps[compiled_gate_index]
    assert compiled_gate['run'] == gate_command
    assert compiled_gate['env'] == gate_env
    assert 'if' not in compiled_gate
    assert 'continue-on-error' not in compiled_gate
    checkout_indices = [
        i for i, step in enumerate(compiled_steps) if step.get('uses', '').startswith('actions/checkout@')
    ]
    download_indices = [
        i for i, step in enumerate(compiled_steps) if step.get('uses', '').startswith('actions/download-artifact@')
    ]
    process_index = next(i for i, step in enumerate(compiled_steps) if step.get('id') == 'process_safe_outputs')
    assert checkout_indices
    assert download_indices
    assert max(checkout_indices + download_indices) < compiled_gate_index < process_index

    targeted_source = read_workflow('agentic-model-price-check.md')
    targeted_compiled = read_workflow('agentic-model-price-check.lock.yml')
    assert 'backfill_requests' not in targeted_source['safe-outputs'].get('needs', [])
    assert not any(step.get('name') == gate_name for step in targeted_source['safe-outputs'].get('steps', []))
    assert 'backfill_requests' not in targeted_compiled['jobs']['safe_outputs']['needs']
    assert not any(step.get('name') == gate_name for step in targeted_compiled['jobs']['safe_outputs']['steps'])
    provider_files = {provider.file for provider in load_provider_sources(ROOT)}
    targeted_allowed = targeted_source['safe-outputs']['create-pull-request']['allowed-files']
    assert {
        path for path in targeted_allowed if path.startswith('prices/providers/') and path.endswith('.yml')
    } == provider_files


def test_model_price_check_report_artifact_connects_upload_and_callbacks() -> None:
    artifact_name = 'model-price-check-report'
    report_path = '/tmp/gh-aw/agent/model-check-report.json'
    download_path = '${{ runner.temp }}/genie-pricer-artifacts'
    staged_report_path = '${{ steps.stage-model-price-report.outputs.path }}'
    observability = read_workflow('shared/price-check-observability.md')
    stage_steps = [
        step for step in observability['post-steps'] if step.get('name') == 'Stage the model price-check report'
    ]
    assert len(stage_steps) == 1
    stage = stage_steps[0]
    assert stage['id'] == 'stage-model-price-report'
    stage_script = stage['with']['script']
    assert f"fs.openSync('{report_path}'" in stage_script
    assert 'fs.constants.O_NOFOLLOW' in stage_script
    assert 'fs.fstatSync(descriptor)' in stage_script
    assert 'stats.isFile()' in stage_script
    assert 'stats.size > 32 * 1024' in stage_script
    uploads = [
        step for step in observability['post-steps'] if step.get('name') == 'Upload the model price-check report'
    ]
    assert [(step['if'], step['with']['name'], step['with']['path']) for step in uploads] == [
        (
            "${{ always() && steps.stage-model-price-report.outputs.path != '' }}",
            artifact_name,
            staged_report_path,
        )
    ]

    for source_file, compiled_file, callback_job in (
        ('agentic-price-check.md', 'agentic-price-check.lock.yml', 'report_backfill'),
        ('agentic-model-price-check.md', 'agentic-model-price-check.lock.yml', 'report_result'),
    ):
        source = read_workflow(source_file)
        compiled = read_workflow(compiled_file)
        assert 'shared/price-check-observability.md' in source['imports']
        compiled_stages = [
            step for step in compiled['jobs']['agent']['steps'] if step.get('id') == 'stage-model-price-report'
        ]
        assert len(compiled_stages) == 1
        compiled_stage_script = compiled_stages[0]['with']['script']
        assert f"fs.openSync('{report_path}'" in compiled_stage_script
        assert 'fs.constants.O_NOFOLLOW' in compiled_stage_script
        for workflow in (source, compiled):
            downloads = [
                step
                for step in workflow['jobs'][callback_job]['steps']
                if step.get('uses', '').startswith('actions/download-artifact@')
            ]
            assert [(step['with']['name'], step['with']['path']) for step in downloads] == [
                (artifact_name, download_path)
            ]
        compiled_uploads = [
            step
            for step in compiled['jobs']['agent']['steps']
            if step.get('name') == 'Upload the model price-check report'
        ]
        assert [(step['with']['name'], step['with']['path']) for step in compiled_uploads] == [
            (artifact_name, staged_report_path)
        ]


def test_model_price_check_report_staging_rejects_untrusted_files(tmp_path: Path) -> None:
    observability = read_workflow('shared/price-check-observability.md')
    stage_script = next(
        step['with']['script'] for step in observability['post-steps'] if step.get('id') == 'stage-model-price-report'
    )
    valid_report = tmp_path / 'valid-report.json'
    valid_contents = json.dumps({'status': 'complete', 'providers': []})
    valid_report.write_text(valid_contents)
    symlink_report = tmp_path / 'symlink-report.json'
    symlink_report.symlink_to(valid_report)
    oversized_report = tmp_path / 'oversized-report.json'
    oversized_report.write_bytes(b'x' * (32 * 1024 + 1))
    special_report = tmp_path / 'special-report'
    os.mkfifo(special_report)
    runner_temp = tmp_path / 'runner-temp'
    runner_temp.mkdir()
    fixtures = [
        {'name': 'regular', 'path': str(valid_report)},
        {'name': 'symlink', 'path': str(symlink_report)},
        {'name': 'oversized', 'path': str(oversized_report)},
        {'name': 'special', 'path': str(special_report)},
    ]
    driver = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const sourcePath = '/tmp/gh-aw/agent/model-check-report.json';
const script = JSON.parse(process.env.STAGE_SCRIPT);
const fixtures = JSON.parse(process.env.FIXTURES);
const output = {};
for (const fixture of fixtures) {
  let stagedPath = '';
  const warnings = [];
  const proxiedFs = new Proxy(fs, {
    get(target, property) {
      if (property === 'openSync') {
        return (file, ...args) => target.openSync(
          file === sourcePath ? fixture.path : file, ...args
        );
      }
      const value = Reflect.get(target, property, target);
      return typeof value === 'function' ? value.bind(target) : value;
    }
  });
  const localRequire = (name) => name === 'node:fs' ? proxiedFs : require(name);
  const core = {
    setOutput(name, value) {
      if (name !== 'path') throw new Error(`unexpected output ${name}`);
      stagedPath = value;
    },
    warning(message) { warnings.push(message); }
  };
  vm.runInNewContext(script, {
    require: localRequire,
    process: {env: {RUNNER_TEMP: process.env.RUNNER_TEMP}},
    Buffer,
    core
  });
  output[fixture.name] = {
    path: stagedPath,
    contents: stagedPath ? fs.readFileSync(stagedPath, 'utf8') : '',
    warnings
  };
}
console.log(JSON.stringify(output));
"""
    result = subprocess.run(
        ['node', '-e', driver],
        env={
            **os.environ,
            'STAGE_SCRIPT': json.dumps(stage_script),
            'FIXTURES': json.dumps(fixtures),
            'RUNNER_TEMP': str(runner_temp),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    outcomes = json.loads(result.stdout)
    staged_path = Path(outcomes['regular']['path'])
    assert staged_path.name == 'model-check-report.json'
    assert staged_path.parent.parent == runner_temp
    assert staged_path.read_text() == valid_contents
    warning = 'Model price-check report is missing or invalid; callback will retain unresolved discovery.'
    for name in ('symlink', 'oversized', 'special'):
        assert outcomes[name]['path'] == ''
        assert outcomes[name]['contents'] == ''
        assert outcomes[name]['warnings'] == [warning]


def test_targeted_request_is_claimed_before_a_read_only_agent() -> None:
    source = read_workflow('agentic-model-price-check.md')
    source_text = (WORKFLOWS / 'agentic-model-price-check.md').read_text()
    assert source['permissions'] == {'contents': 'read', 'pull-requests': 'read'}
    assert source['run-name'] == 'Model prices ${{ github.event.client_payload.request_id }}'
    assert source['jobs']['claim_request']['needs'] == 'activation'
    assert source['jobs']['agent']['needs'] == ['claim_request']
    assert source['jobs']['agent']['if'] == "needs.claim_request.outputs.claimed == 'true'"
    assert '${{ needs.claim_request.outputs.request }}' in source_text
    assert '${{ github.event.client_payload.target_model }}' not in source_text

    targeted = read_workflow('agentic-model-price-check.lock.yml')
    weekly = read_workflow('agentic-price-check.lock.yml')
    targeted_jobs = targeted['jobs']
    weekly_jobs = weekly['jobs']
    assert targeted_jobs['agent']['permissions'] == {
        'contents': 'read',
        'pull-requests': 'read',
    }
    assert targeted_jobs['claim_request']['needs'] == 'activation'
    assert targeted_jobs['claim_request']['permissions'] == {
        'contents': 'read',
        'id-token': 'write',
    }
    assert targeted_jobs['agent']['needs'] == ['activation', 'claim_request']
    assert targeted_jobs['agent']['if'] == "needs.claim_request.outputs.claimed == 'true'"
    assert targeted_jobs['report_result']['needs'] == ['agent', 'claim_request', 'safe_outputs']
    assert targeted_jobs['report_result']['permissions'] == {
        'contents': 'read',
        'id-token': 'write',
    }
    assert weekly_jobs['agent']['permissions'] == targeted_jobs['agent']['permissions']
    assert weekly_jobs['backfill_requests']['permissions'] == {
        'contents': 'read',
        'id-token': 'write',
    }
    assert weekly_jobs['report_backfill']['permissions'] == {
        'contents': 'read',
        'id-token': 'write',
    }

    secret_references = re.compile(r'\$\{\{\s*secrets\.([A-Z0-9_]+)\s*\}\}')
    targeted_agent_secrets = set(secret_references.findall(json.dumps(targeted_jobs['agent'])))
    weekly_agent_secrets = set(secret_references.findall(json.dumps(weekly_jobs['agent'])))
    assert targeted_agent_secrets == weekly_agent_secrets
    assert not {'SLACK_WEBHOOK_URL', 'SLACK_BOT_TOKEN'} & targeted_agent_secrets


def test_price_checks_use_one_scheduled_workflow() -> None:
    source_workflows = {path.name: read_workflow(path.name) for path in WORKFLOWS.glob('agentic-*.md')}
    assert {name for name, workflow in source_workflows.items() if 'schedule' in workflow['on']} == {
        'agentic-price-check.md'
    }
    assert source_workflows['agentic-price-check.md']['on']['schedule'] == [{'cron': '0 6 * * 1', 'timezone': 'UTC'}]
    targeted = source_workflows['agentic-model-price-check.md']
    assert targeted['on']['repository_dispatch']['types'] == ['genie-pricer-model-request']
    assert targeted['on']['bots'] == ['pydanty']
    assert 'skip-if-match' not in targeted['on']

    weekly_compiled = read_workflow('agentic-price-check.lock.yml')
    targeted_compiled = read_workflow('agentic-model-price-check.lock.yml')
    assert weekly_compiled['on']['schedule'] == source_workflows['agentic-price-check.md']['on']['schedule']
    assert 'schedule' not in targeted_compiled['on']
    assert targeted_compiled['on']['repository_dispatch']['types'] == ['genie-pricer-model-request']
    assert {path.name for path in WORKFLOWS.glob('agentic-*.lock.yml')} == {
        'agentic-price-check.lock.yml',
        'agentic-model-price-check.lock.yml',
    }


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
    assert workflow['on']['workflow_call']['inputs']['message']['default'] == 'Review the GenAI Prices update:'
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
        env={**os.environ, 'PR_URL': url, 'MESSAGE': 'Review the GenAI Prices update:', 'SLACK_WEBHOOK_URL': 'unused'},
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
    for filename in ('agentic-price-check.lock.yml', 'agentic-model-price-check.lock.yml'):
        compiled = read_workflow(filename)
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
    observability = read_workflow('shared/price-check-observability.md')
    script = observability['post-steps'][0]['with']['script']
    driver = r"""
const script = JSON.parse(process.env.EXPORT_SCRIPT);
const files = {
  '/tmp/gh-aw/agent-session.jsonl': [
    'debug output', 'null',
    JSON.stringify({type: 'tool.execution_start', data: {toolName: 'web_fetch'}}),
    JSON.stringify({type: 'session.result', data: {status: 'success'}})
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
  const resource = Object.fromEntries(agent.resourceAttributes.map(({key, value}) => [key, value]));
  const toolCounts = JSON.parse(agent.attributes.find(({key}) => key === 'price_check.tool_counts').value);
  const terminalEmitted = agent.attributes.find(({key}) => key === 'price_check.terminal_output_emitted').value;
  const marker = JSON.parse(files['/tmp/gh-aw/mcp-logs/price-check-telemetry.json']);
  files['/tmp/gh-aw/agent_output.json'] = JSON.stringify({items: [{type: 'report_incomplete'}]});
  files['/tmp/gh-aw/agent-session.jsonl'] = files['/tmp/gh-aw/agent-session.jsonl'].replace('"status":"success"', '"status":"error"');
  await run(fakeRequire, {env: {RUNNER_TEMP: '/runner'}}, core);
  const partialStatus = payload.resourceSpans.find((span) => span.spanName === 'invoke_agent').statusCode;
  let incomplete = false;
  files['/tmp/gh-aw/agent_usage.json'] = '{}';
  try { await run(fakeRequire, {env: {RUNNER_TEMP: '/runner'}}, core); } catch { incomplete = true; }
  console.log(JSON.stringify({endpoint: payload.endpoint, names: spans.map((span) => span.spanName),
    usage, toolCounts, terminalEmitted, marker, requestId: resource['price_check.request_id'],
    completedStatus: agent.statusCode, partialStatus, incomplete, summaries}));
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
    assert output['terminalEmitted'] is True
    assert output['marker']['exported_request_spans'] == 1
    assert output['requestId'] == ''
    assert any('telemetry incomplete' in summary for summary in output['summaries'])


def test_hourly_importer_failures_alert_slack_once() -> None:
    workflow = read_workflow('update-prices.yml')
    check = workflow['jobs']['importer-failure']
    assert check['needs'] == 'import'
    assert check['if'] == "${{ !cancelled() && needs.import.result == 'failure' && github.event_name == 'schedule' }}"
    assert check['permissions'] == {'actions': 'read'}
    notify = workflow['jobs']['notify-failure']
    assert notify['if'] == "needs.importer-failure.outputs.newly-failing == 'true'"
    assert notify['uses'] == './.github/workflows/price-update-slack.yml'
    assert notify['with']['message'] == 'A GenAI Prices importer started failing:'


@pytest.mark.parametrize(
    ('previous_run', 'previous_import_conclusions', 'newly_failing'),
    [
        ('', '', 'true'),
        ('41', 'success\nsuccess', 'true'),
        ('41', 'success\nfailure', 'false'),
    ],
)
def test_importer_failure_alerts_only_after_a_scheduled_run_whose_importers_passed(
    tmp_path: Path, previous_run: str, previous_import_conclusions: str, newly_failing: str
) -> None:
    fake_gh = tmp_path / 'gh'
    fake_gh.write_text(
        '#!/bin/bash\n'
        'echo "$*" >> "$GH_CALLS"\n'
        'if [ "$2" = list ]; then printf %s "$PREVIOUS_RUN"; else printf "$PREVIOUS_IMPORTS\\n"; fi\n'
    )
    fake_gh.chmod(0o755)
    output = tmp_path / 'output'
    calls = tmp_path / 'calls'
    script = read_workflow('update-prices.yml')['jobs']['importer-failure']['steps'][0]['run']

    subprocess.run(
        ['bash', '-e', '-o', 'pipefail', '-c', script],
        env={
            **os.environ,
            'PATH': f'{tmp_path}:{os.environ["PATH"]}',
            'GITHUB_OUTPUT': str(output),
            'GITHUB_REPOSITORY': 'pydantic/genai-prices',
            'GH_CALLS': str(calls),
            'PREVIOUS_RUN': previous_run,
            'PREVIOUS_IMPORTS': previous_import_conclusions,
        },
        check=True,
    )

    assert output.read_text() == f'newly-failing={newly_failing}\n'
    assert '--event schedule --status completed --limit 1' in calls.read_text()
    assert ('run view 41 ' in calls.read_text()) == bool(previous_run)


def test_importer_failure_lookup_error_fails_instead_of_alerting(tmp_path: Path) -> None:
    fake_gh = tmp_path / 'gh'
    fake_gh.write_text('#!/bin/bash\nif [ "$2" = list ]; then printf 41; else exit 1; fi\n')
    fake_gh.chmod(0o755)
    output = tmp_path / 'output'
    script = read_workflow('update-prices.yml')['jobs']['importer-failure']['steps'][0]['run']

    result = subprocess.run(
        ['bash', '-e', '-o', 'pipefail', '-c', script],
        env={
            **os.environ,
            'PATH': f'{tmp_path}:{os.environ["PATH"]}',
            'GITHUB_OUTPUT': str(output),
            'GITHUB_REPOSITORY': 'pydantic/genai-prices',
        },
        check=False,
    )

    assert result.returncode != 0
    assert not output.exists()
