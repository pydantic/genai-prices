from .test_price_update_workflows import read_workflow


def test_finisher_waits_from_trusted_code_and_repair_completion_resumes_it() -> None:
    workflow = read_workflow('finish-price-update.yml')
    producers = [
        read_workflow(name)['name']
        for name in ('update-prices.yml', 'repair-price-update.md', 'agentic-model-price-check.md')
    ]
    assert workflow['on']['workflow_run'] == {'workflows': producers, 'types': ['completed'], 'branches': ['main']}
    assert workflow['on']['repository_dispatch'] == {'types': ['genie-pricer-repair-request']}
    jobs = workflow['jobs']
    assert "github.ref == 'refs/heads/main'" in jobs['select']['if']
    assert "github.event.sender.login == 'pydanty[bot]'" in jobs['select']['if']
    assert jobs['select']['permissions'] == {'contents': 'read', 'pull-requests': 'read'}
    assert jobs['watch']['needs'] == 'select'
    assert jobs['watch']['strategy'] == {
        'fail-fast': False,
        'matrix': {'pr': '${{ fromJSON(needs.select.outputs.prs) }}'},
    }
    for job in jobs.values():
        assert job['steps'][0]['with'] == {'ref': '${{ github.sha }}', 'persist-credentials': False}
    assert workflow['concurrency'] == {'group': 'finish-price-update', 'cancel-in-progress': False, 'queue': 'max'}


def test_repair_uses_existing_model_and_has_no_github_write_tool() -> None:
    source = read_workflow('repair-price-update.md')
    compiled = read_workflow('repair-price-update.lock.yml')
    assert source['engine']['model'] == read_workflow('agentic-price-check.md')['engine']['model']
    assert source['checkout']['ref'] == '${{ needs.claim.outputs.head }}'
    assert source['safe-outputs']['scripts']['repair-staged']['script'] == 'return { success: true };'
    assert 'create-issue' not in source['safe-outputs']
    agent = compiled['jobs']['agent']
    assert 'claim' in agent['needs']
    assert all(value != 'write' for value in agent['permissions'].values())
    safe = compiled['jobs']['safe_outputs']
    assert all(value != 'write' for value in safe.get('permissions', {}).values())
    assert all(value != 'write' for value in compiled['jobs']['conclusion'].get('permissions', {}).values())
    handlers = [step for step in safe['steps'] if 'Create issue' in step.get('name', '')]
    assert handlers == []


def test_only_trusted_publisher_receives_app_key_after_independent_validation() -> None:
    workflow = read_workflow('repair-price-update.lock.yml')
    jobs = workflow['jobs']
    assert set(jobs['validate']['needs']) == {'claim', 'agent'}
    assert jobs['validate']['permissions'] == {'contents': 'read'}
    assert jobs['validate']['env']['OTEL_EXPORTER_OTLP_HEADERS'] == "${{ '' }}"
    assert {'claim', 'agent', 'validate', 'safe_outputs'} <= set(jobs['publish']['needs'])
    for name, job in jobs.items():
        steps = job.get('steps', [])
        tokens = [step for step in steps if step.get('id') == 'app-token']
        if name == 'publish':
            assert len(tokens) == 1
            assert tokens[0]['with']['permission-contents'] == 'write'
            assert tokens[0]['with']['repositories'] == 'genai-prices'
            assert next(i for i, step in enumerate(steps) if step.get('id') == 'policy') < steps.index(tokens[0])
            push = next(step for step in steps if step.get('id') == 'push')['run']
            assert 'core.hooksPath=/dev/null' in push
            assert '--force' not in push
        else:
            assert tokens == []


def test_importer_validation_precedes_token_and_branch_publication() -> None:
    steps = read_workflow('update-prices.yml')['jobs']['pull-request']['steps']
    validation = next(
        i for i, step in enumerate(steps) if step.get('name') == 'Validate the proposal before publication'
    )
    token = next(i for i, step in enumerate(steps) if step.get('id') == 'app-token')
    assert steps[validation]['run'] == 'make test test-js test-go'
    assert validation < token
    publication = next(step['run'] for step in steps if step.get('id') == 'pr')
    assert '--force' not in publication
