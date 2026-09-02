import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest

from prices import build as build_module, v3_compatibility
from prices.build import v3_data_schema
from prices.export_validation import RuntimeUnitProjection, normalize_conditional_implications, runtime_unit_projection
from prices.v3_compatibility import JsonData, validate_v3_compatibility, validate_v3_schema_evolution

BOOTSTRAP_UNITS = """\
events:
  per: 1
  dimensions: {family: events}
"""


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(['git', *args], cwd=repo, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _init_git_repo(tmp_path: Path, units_yaml: str = BOOTSTRAP_UNITS) -> tuple[Path, str]:
    repo = tmp_path / 'repo'
    units_path = repo / 'prices' / 'units.yml'
    units_path.parent.mkdir(parents=True)
    units_path.write_text(units_yaml)
    _git(repo, 'init', '-b', 'main')
    _git(repo, 'config', 'user.email', 'test@example.com')
    _git(repo, 'config', 'user.name', 'Test User')
    _git(repo, 'add', 'prices/units.yml')
    _git(repo, 'commit', '-m', 'baseline')
    return repo, _git(repo, 'rev-parse', 'HEAD')


def _candidate(source_units: dict[str, dict[str, object]]) -> tuple[RuntimeUnitProjection, dict[str, Any]]:
    runtime_units = runtime_unit_projection(source_units)
    return runtime_units, {'units': runtime_units, 'providers': []}


def _write_v3_artifacts(repo: Path, payload: object, schema: object) -> None:
    data_dir = repo / 'prices' / 'new_data' / 'v3'
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / 'data.json').write_text(json.dumps(payload))
    (data_dir / 'data.schema.json').write_text(json.dumps(schema))


def _definition(schema: dict[str, Any], name: str) -> dict[str, Any]:
    return cast(dict[str, Any], schema['$defs'][name])


def test_validate_v3_schema_evolution_accepts_identical_and_additive_schema_changes() -> None:
    previous = v3_data_schema()
    candidate = copy.deepcopy(previous)
    runtime_unit = _definition(candidate, 'RuntimeUnitData')
    runtime_unit['properties']['future_annotation'] = {'type': 'string'}
    runtime_unit['properties']['per']['minimum'] = 0
    runtime_unit['properties']['per']['maximum'] = 9_007_199_254_740_992

    validate_v3_schema_evolution(previous, previous)
    validate_v3_schema_evolution(previous, candidate)


def test_validate_v3_schema_evolution_allows_added_enum_values_and_distinguishable_variants() -> None:
    previous: dict[str, Any] = {
        'additionalProperties': False,
        'properties': {
            'kind': {'enum': ['known'], 'type': 'string'},
            'capability': {
                'oneOf': [
                    {
                        'additionalProperties': False,
                        'properties': {'equals': {'type': 'string'}},
                        'required': ['equals'],
                        'type': 'object',
                    }
                ]
            },
        },
        'required': ['kind', 'capability'],
        'type': 'object',
    }
    candidate = copy.deepcopy(previous)
    candidate['properties']['kind']['enum'].append('future')
    candidate['properties']['capability']['oneOf'].append(
        {
            'additionalProperties': False,
            'properties': {'glob': {'type': 'string'}},
            'required': ['glob'],
            'type': 'object',
        }
    )

    validate_v3_schema_evolution(previous, candidate)


@pytest.mark.parametrize(
    ('mutation', 'message'),
    [
        ('remove property', 'removed property'),
        ('new required', 'newly requires'),
        ('remove required', 'no longer requires'),
        ('narrow type', 'narrowed type'),
        ('narrow lower bound', 'narrowed lower bound'),
        ('narrow upper bound', 'narrowed upper bound'),
        ('change default', 'changed default'),
        ('remove variant', 'removed or narrowed oneOf variant'),
        ('change reference', 'changed reference'),
    ],
)
def test_validate_v3_schema_evolution_rejects_stable_core_changes(mutation: str, message: str) -> None:
    previous = v3_data_schema()
    candidate = copy.deepcopy(previous)
    runtime_unit = _definition(candidate, 'RuntimeUnitData')
    if mutation == 'remove property':
        candidate['properties'].pop('units')
    elif mutation == 'new required':
        runtime_unit['properties']['future'] = {'type': 'string'}
        runtime_unit['required'].append('future')
    elif mutation == 'remove required':
        runtime_unit['required'].remove('dimensions')
    elif mutation == 'narrow type':
        runtime_unit['properties']['per']['type'] = 'string'
    elif mutation == 'narrow lower bound':
        runtime_unit['properties']['per']['minimum'] = 2
    elif mutation == 'narrow upper bound':
        runtime_unit['properties']['per']['maximum'] = 100
    elif mutation == 'change default':
        _definition(candidate, 'UsageExtractor')['properties']['api_flavor']['default'] = 'future'
    elif mutation == 'remove variant':
        _definition(candidate, 'ModelInfo')['properties']['match']['oneOf'].pop()
    else:
        _definition(candidate, 'Provider')['properties']['models']['items']['$ref'] = '#/$defs/Provider'

    with pytest.raises(ValueError, match=message):
        validate_v3_schema_evolution(previous, candidate)


def test_validate_v3_schema_evolution_rejects_removed_enum_values() -> None:
    previous: dict[str, JsonData] = {'enum': ['one', 'two'], 'type': 'string'}
    candidate: dict[str, JsonData] = {'enum': ['one'], 'type': 'string'}

    with pytest.raises(ValueError, match='removed enum values'):
        validate_v3_schema_evolution(previous, candidate)


def test_validate_v3_schema_evolution_checks_new_properties_against_previous_catchall() -> None:
    previous: dict[str, JsonData] = {'additionalProperties': {'type': 'string'}, 'type': 'object'}
    compatible: dict[str, JsonData] = {
        'additionalProperties': {'type': 'string'},
        'properties': {'future': {'type': 'string'}},
        'type': 'object',
    }
    narrowed = copy.deepcopy(compatible)
    cast(dict[str, JsonData], narrowed['properties'])['future'] = {'type': 'integer'}

    validate_v3_schema_evolution(previous, compatible)
    with pytest.raises(ValueError, match=r'properties\.future.*narrowed type'):
        validate_v3_schema_evolution(previous, narrowed)


@pytest.mark.parametrize(
    ('previous', 'candidate'),
    [
        ({}, {'default': None}),
        ({'default': None}, {}),
        ({'default': 1}, {'default': True}),
    ],
)
def test_validate_v3_schema_evolution_compares_default_presence_and_json_identity(
    previous: dict[str, JsonData], candidate: dict[str, JsonData]
) -> None:
    with pytest.raises(ValueError, match='changed default'):
        validate_v3_schema_evolution(previous, candidate)

    validate_v3_schema_evolution({'default': {'a': 1, 'b': 2}}, {'default': {'b': 2, 'a': 1}})


def test_validate_v3_schema_evolution_rejects_ambiguous_behavior_changing_variant() -> None:
    previous = v3_data_schema()
    candidate = copy.deepcopy(previous)
    candidate['$defs']['ClauseCaseSensitiveEquals'] = {
        'additionalProperties': False,
        'properties': {
            'equals': {'type': 'string'},
            'case_sensitive': {'type': 'boolean'},
        },
        'required': ['equals', 'case_sensitive'],
        'type': 'object',
    }
    _definition(candidate, 'ModelInfo')['properties']['match']['oneOf'].append(
        {'$ref': '#/$defs/ClauseCaseSensitiveEquals'}
    )

    with pytest.raises(ValueError, match='ambiguous behavior-changing oneOf variant'):
        validate_v3_schema_evolution(previous, candidate)


@pytest.mark.parametrize(
    ('previous', 'candidate', 'message'),
    [
        ({}, {'type': 'string'}, 'narrowed unconstrained type'),
        ({}, {'enum': ['one']}, 'added an enum restriction'),
        ({}, {'const': 'one'}, 'added a const restriction'),
        ({'const': 'one'}, {'const': 'two'}, 'changed const'),
        ({}, {'minimum': 0}, 'added lower bound'),
        ({}, {'maximum': 1}, 'added upper bound'),
        ({}, {'pattern': 'x'}, 'added pattern restriction'),
        ({'pattern': 'x'}, {'pattern': 'y'}, 'changed pattern restriction'),
        ({}, {'uniqueItems': True}, 'newly requires unique array items'),
        ({'additionalProperties': True}, {'additionalProperties': False}, 'narrowed additional properties'),
        (
            {'additionalProperties': True},
            {'additionalProperties': {'type': 'string'}},
            'schema restriction for additional properties',
        ),
        ({}, {'items': {'type': 'string'}}, 'added items restriction'),
        ({}, {'anyOf': [{'type': 'string'}]}, 'added anyOf restriction'),
        ({'anyOf': [{'type': 'string'}]}, {}, 'removed anyOf variants'),
        ({}, {'$defs': {'Value': {}}, '$ref': '#/$defs/Value'}, 'replaced an inline schema with a reference'),
        ({'x-unsupported': 1}, {}, 'changed unsupported schema keywords'),
        ({'x-unsupported': 1}, {'x-unsupported': 2}, 'changed unsupported schema keyword'),
    ],
)
def test_validate_v3_schema_evolution_rejects_restricted_schema_narrowing(
    previous: dict[str, Any], candidate: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_v3_schema_evolution(previous, candidate)


def test_validate_v3_schema_evolution_accepts_supported_schema_widening() -> None:
    accepted_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = [
        ({'type': ['integer', 'string']}, {}),
        ({'enum': ['one']}, {}),
        ({'const': 'one'}, {}),
        ({'minimum': 1, 'maximum': 2}, {}),
        ({'pattern': 'x'}, {}),
        ({'additionalProperties': {'type': 'string'}}, {'additionalProperties': True}),
        ({'items': {'type': 'string'}}, {}),
        ({'enum': [['nested'], {'key': 'value'}]}, {'enum': [['nested'], {'key': 'value'}, 'future']}),
        ({'x-first': 1, 'x-second': 2}, {'x-first': 1, 'x-second': 2}),
    ]

    for previous, candidate in accepted_pairs:
        validate_v3_schema_evolution(previous, candidate)


def test_validate_v3_schema_evolution_accepts_reordered_and_disjoint_variants() -> None:
    string_variant = {'type': 'string'}
    integer_variant = {'type': 'integer'}
    previous: dict[str, Any] = {'oneOf': [string_variant, integer_variant]}
    reordered_candidate: dict[str, Any] = {'oneOf': [integer_variant, string_variant, {'type': 'object'}]}
    validate_v3_schema_evolution(previous, reordered_candidate)

    old_tagged: dict[str, Any] = {
        'properties': {'type': {'enum': ['old'], 'type': 'string'}},
        'required': ['type'],
        'type': 'object',
    }
    new_tagged: dict[str, Any] = {
        'properties': {'type': {'const': 'new', 'type': 'string'}},
        'required': ['type'],
        'type': 'object',
    }
    validate_v3_schema_evolution({'oneOf': [old_tagged]}, {'oneOf': [old_tagged, new_tagged]})


@pytest.mark.parametrize(
    ('previous', 'candidate', 'message'),
    [
        ([], {}, 'previous schema.*object schema'),
        ({1: {}}, {}, 'previous schema.*object schema'),
        ({'properties': {'value': []}}, {'properties': {'value': []}}, 'object schema'),
        ({'oneOf': {}}, {'oneOf': {}}, 'schema array'),
        ({'type': 1}, {'type': 1}, 'type string or string array'),
        ({'type': ['string', 1]}, {'type': ['string', 1]}, 'type string or string array'),
        ({'required': 'value'}, {'required': 'value'}, 'string array'),
        ({'enum': 'value'}, {'enum': 'value'}, 'expected an array'),
        ({'minimum': True}, {'minimum': True}, 'expected a number'),
        (
            {'$defs': {}, '$ref': 'https://example.com/schema'},
            {'$defs': {}, '$ref': 'https://example.com/schema'},
            'only local.*references',
        ),
        (
            {'$defs': {}, '$ref': '#/$defs/Missing'},
            {'$defs': {}, '$ref': '#/$defs/Missing'},
            'missing definition',
        ),
    ],
)
def test_validate_v3_schema_evolution_rejects_malformed_normal_form(
    previous: Any, candidate: Any, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_v3_schema_evolution(previous, candidate)


def test_validate_v3_compatibility_bootstraps_from_exact_target_and_ignores_working_tree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, target_oid = _init_git_repo(tmp_path)
    monkeypatch.setattr(v3_compatibility, 'root_dir', repo)
    source_units: dict[str, dict[str, object]] = {
        'events': {'per': 1, 'dimensions': {'family': 'events'}},
        'special_events': {'per': 1, 'dimensions': {'family': 'events', 'kind': 'special'}},
    }
    runtime_units, payload = _candidate(source_units)

    (repo / 'prices' / 'units.yml').write_text('working_tree_only: invalid')
    working_v3 = repo / 'prices' / 'new_data' / 'v3'
    working_v3.mkdir(parents=True)
    (working_v3 / 'data.json').write_text('not target data')
    validate_v3_compatibility(
        'HEAD',
        candidate_runtime_units=runtime_units,
        candidate_implications=normalize_conditional_implications(source_units),
        candidate_schema=v3_data_schema(),
        candidate_payload=payload,
    )

    assert capsys.readouterr().out == f'Validating v3 compatibility against target {target_oid}\n'


def test_resolve_compatibility_target_defaults_to_head(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo, target_oid = _init_git_repo(tmp_path)
    monkeypatch.setattr(v3_compatibility, 'root_dir', repo)

    assert v3_compatibility.resolve_compatibility_target() == target_oid
    assert v3_compatibility.resolve_compatibility_target('HEAD') == target_oid


def test_validate_v3_compatibility_compares_later_target_artifacts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo, _ = _init_git_repo(tmp_path)
    source_units: dict[str, dict[str, object]] = {'events': {'per': 1, 'dimensions': {'family': 'events'}}}
    runtime_units, payload = _candidate(source_units)
    schema = v3_data_schema()
    _write_v3_artifacts(repo, payload, schema)
    _git(repo, 'add', 'prices/new_data/v3/data.json', 'prices/new_data/v3/data.schema.json')
    _git(repo, 'commit', '-m', 'publish v3')
    target_oid = _git(repo, 'rev-parse', 'HEAD')
    monkeypatch.setattr(v3_compatibility, 'root_dir', repo)

    candidate_schema = copy.deepcopy(schema)
    _definition(candidate_schema, 'RuntimeUnitData')['properties']['extension'] = {'type': 'string'}
    validate_v3_compatibility(
        target_oid,
        candidate_runtime_units=runtime_units,
        candidate_implications=normalize_conditional_implications(source_units),
        candidate_schema=candidate_schema,
        candidate_payload=payload,
    )

    incompatible_schema = copy.deepcopy(schema)
    _definition(incompatible_schema, 'RuntimeUnitData')['properties'].pop('price_key')
    with pytest.raises(ValueError, match='removed property'):
        validate_v3_compatibility(
            target_oid,
            candidate_runtime_units=runtime_units,
            candidate_implications=normalize_conditional_implications(source_units),
            candidate_schema=incompatible_schema,
            candidate_payload=payload,
        )


@pytest.mark.parametrize(
    ('baseline_kind', 'message'),
    [
        ('mixed artifacts', 'mixed v3 artifacts'),
        ('malformed data', 'malformed prices/new_data/v3/data.json'),
        ('invalid schema', 'Invalid target v3 payload schema'),
        ('mixed source', 'published units do not match target source units'),
    ],
)
def test_validate_v3_compatibility_rejects_invalid_later_baselines(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, baseline_kind: str, message: str
) -> None:
    repo, _ = _init_git_repo(tmp_path)
    source_units: dict[str, dict[str, object]] = {'events': {'per': 1, 'dimensions': {'family': 'events'}}}
    runtime_units, payload = _candidate(source_units)
    candidate_payload: dict[str, Any] = {'units': runtime_units, 'providers': []}
    schema: object = v3_data_schema()
    if baseline_kind == 'mixed source':
        payload = cast(
            dict[str, Any],
            {
                'units': {'other_events': {'per': 1, 'dimensions': {'family': 'other_events'}}},
                'providers': [],
            },
        )
    _write_v3_artifacts(repo, payload, schema)
    if baseline_kind == 'mixed artifacts':
        (repo / 'prices/new_data/v3/data.schema.json').write_text('')
        _git(repo, 'add', 'prices/new_data/v3/data.json')
    else:
        if baseline_kind == 'malformed data':
            (repo / 'prices/new_data/v3/data.json').write_text('{')
        elif baseline_kind == 'invalid schema':
            (repo / 'prices/new_data/v3/data.schema.json').write_text('{"type": "invalid"}')
        _git(repo, 'add', 'prices/new_data/v3/data.json', 'prices/new_data/v3/data.schema.json')
    _git(repo, 'commit', '-m', baseline_kind)
    monkeypatch.setattr(v3_compatibility, 'root_dir', repo)

    with pytest.raises(ValueError, match=message):
        validate_v3_compatibility(
            'HEAD',
            candidate_runtime_units=runtime_units,
            candidate_implications=normalize_conditional_implications(source_units),
            candidate_schema=v3_data_schema(),
            candidate_payload=candidate_payload,
        )


def test_validate_v3_compatibility_rejects_stale_and_invalid_targets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo, _ = _init_git_repo(tmp_path)
    _git(repo, 'switch', '-c', 'stale')
    (repo / 'stale.txt').write_text('stale')
    _git(repo, 'add', 'stale.txt')
    _git(repo, 'commit', '-m', 'stale side')
    stale_oid = _git(repo, 'rev-parse', 'HEAD')
    _git(repo, 'switch', 'main')
    (repo / 'current.txt').write_text('current')
    _git(repo, 'add', 'current.txt')
    _git(repo, 'commit', '-m', 'current side')
    monkeypatch.setattr(v3_compatibility, 'root_dir', repo)
    source_units: dict[str, dict[str, object]] = {'events': {'per': 1, 'dimensions': {'family': 'events'}}}
    runtime_units, payload = _candidate(source_units)

    with pytest.raises(ValueError, match='expected a Git commit'):
        validate_v3_compatibility(
            'missing',
            candidate_runtime_units=runtime_units,
            candidate_implications=normalize_conditional_implications(source_units),
            candidate_schema=v3_data_schema(),
            candidate_payload=payload,
        )
    with pytest.raises(ValueError, match='Stale v3 compatibility target'):
        validate_v3_compatibility(
            stale_oid,
            candidate_runtime_units=runtime_units,
            candidate_implications=normalize_conditional_implications(source_units),
            candidate_schema=v3_data_schema(),
            candidate_payload=payload,
        )


@pytest.mark.parametrize(
    ('units_content', 'message'),
    [
        (None, 'missing prices/units.yml'),
        ('events: [', 'malformed prices/units.yml'),
    ],
)
def test_validate_v3_compatibility_rejects_missing_or_malformed_target_units(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, units_content: str | None, message: str
) -> None:
    repo = tmp_path / 'repo'
    repo.mkdir()
    _git(repo, 'init', '-b', 'main')
    _git(repo, 'config', 'user.email', 'test@example.com')
    _git(repo, 'config', 'user.name', 'Test User')
    tracked_path = repo / ('prices/units.yml' if units_content is not None else 'placeholder.txt')
    tracked_path.parent.mkdir(parents=True, exist_ok=True)
    tracked_path.write_text(units_content or 'placeholder')
    _git(repo, 'add', str(tracked_path.relative_to(repo)))
    _git(repo, 'commit', '-m', 'invalid baseline')
    monkeypatch.setattr(v3_compatibility, 'root_dir', repo)
    source_units: dict[str, dict[str, object]] = {'events': {'per': 1, 'dimensions': {'family': 'events'}}}
    runtime_units, payload = _candidate(source_units)

    with pytest.raises(ValueError, match=message):
        validate_v3_compatibility(
            'HEAD',
            candidate_runtime_units=runtime_units,
            candidate_implications=normalize_conditional_implications(source_units),
            candidate_schema=v3_data_schema(),
            candidate_payload=payload,
        )


def test_validate_v3_compatibility_rejects_candidate_mismatches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo, _ = _init_git_repo(tmp_path)
    monkeypatch.setattr(v3_compatibility, 'root_dir', repo)
    source_units: dict[str, dict[str, object]] = {'events': {'per': 1, 'dimensions': {'family': 'events'}}}
    runtime_units, payload = _candidate(source_units)
    invalid_payload: dict[str, Any] = {'units': runtime_units}

    with pytest.raises(ValueError, match='units do not match the supplied in-memory candidate'):
        validate_v3_compatibility(
            'HEAD',
            candidate_runtime_units=runtime_units,
            candidate_implications=normalize_conditional_implications(source_units),
            candidate_schema=v3_data_schema(),
            candidate_payload={'units': {}, 'providers': []},
        )
    with pytest.raises(ValueError, match='keys do not match candidate runtime units'):
        validate_v3_compatibility(
            'HEAD',
            candidate_runtime_units=runtime_units,
            candidate_implications={},
            candidate_schema=v3_data_schema(),
            candidate_payload=payload,
        )
    with pytest.raises(ValueError, match='Invalid candidate v3 payload'):
        validate_v3_compatibility(
            'HEAD',
            candidate_runtime_units=runtime_units,
            candidate_implications=normalize_conditional_implications(source_units),
            candidate_schema=v3_data_schema(),
            candidate_payload=invalid_payload,
        )
    with pytest.raises(ValueError, match='expected an object units member'):
        validate_v3_compatibility(
            'HEAD',
            candidate_runtime_units=runtime_units,
            candidate_implications=normalize_conditional_implications(source_units),
            candidate_schema=v3_data_schema(),
            candidate_payload={'units': [], 'providers': []},
        )
    with pytest.raises(ValueError, match='Invalid candidate v3 payload schema'):
        validate_v3_compatibility(
            'HEAD',
            candidate_runtime_units=runtime_units,
            candidate_implications=normalize_conditional_implications(source_units),
            candidate_schema={'type': 'invalid'},
            candidate_payload=payload,
        )
    with pytest.raises(ValueError, match='conflicting kind'):
        validate_v3_compatibility(
            'HEAD',
            candidate_runtime_units=runtime_units,
            candidate_implications={'events': (('family', 'kind', 'first'), ('family', 'kind', 'second'))},
            candidate_schema=v3_data_schema(),
            candidate_payload=payload,
        )


def test_validate_v3_compatibility_enforces_bootstrap_unit_evolution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    baseline_yaml = """\
special_events:
  per: 1
  dimensions: {family: events, kind: special}
  dimension_requirements: {kind: {family: events}}
"""
    repo, _ = _init_git_repo(tmp_path, baseline_yaml)
    monkeypatch.setattr(v3_compatibility, 'root_dir', repo)
    baseline_source: dict[str, dict[str, object]] = {
        'special_events': {
            'per': 1,
            'dimensions': {'family': 'events', 'kind': 'special'},
            'dimension_requirements': {'kind': {'family': 'events'}},
        }
    }

    cases: list[tuple[dict[str, dict[str, object]], dict[str, tuple[tuple[str, str, str], ...]], str]] = [
        ({}, {}, 'Removed published unit'),
        (
            {'special_events': {'per': 2, 'dimensions': {'family': 'events', 'kind': 'special'}}},
            {'special_events': (('kind', 'family', 'events'),)},
            'Redefined published unit',
        ),
        (
            {'special_events': {'per': 1, 'dimensions': {'family': 'events', 'kind': 'special'}}},
            {'special_events': ()},
            'Changed published conditional implications',
        ),
        (
            {
                **baseline_source,
                'events': {'per': 1, 'dimensions': {'family': 'events'}},
            },
            {
                'special_events': (('kind', 'family', 'events'),),
                'events': (),
            },
            'New unit events is an ancestor',
        ),
    ]
    for candidate_source, candidate_implications, message in cases:
        runtime_units, payload = _candidate(candidate_source)
        with pytest.raises(ValueError, match=message):
            validate_v3_compatibility(
                'HEAD',
                candidate_runtime_units=runtime_units,
                candidate_implications=candidate_implications,
                candidate_schema=v3_data_schema(),
                candidate_payload=payload,
            )


def test_validate_v3_compatibility_enforces_bootstrap_unit_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    baseline_yaml = (
        BOOTSTRAP_UNITS
        + """\
special_events:
  per: 1
  dimensions: {family: events, kind: special}
"""
    )
    repo, _ = _init_git_repo(tmp_path, baseline_yaml)
    monkeypatch.setattr(v3_compatibility, 'root_dir', repo)
    candidate_source: dict[str, dict[str, object]] = {
        'special_events': {'per': 1, 'dimensions': {'family': 'events', 'kind': 'special'}},
        'events': {'per': 1, 'dimensions': {'family': 'events'}},
    }
    runtime_units, payload = _candidate(candidate_source)

    with pytest.raises(ValueError, match='Reordered published units'):
        validate_v3_compatibility(
            'HEAD',
            candidate_runtime_units=runtime_units,
            candidate_implications=normalize_conditional_implications(candidate_source),
            candidate_schema=v3_data_schema(),
            candidate_payload=payload,
        )


def test_v3_compatibility_main_prepares_candidate_without_writing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    units_yaml = """\
input_tokens:
  per: 1000000
  price_key: input_mtok
  dimensions: {family: tokens, direction: input}
"""
    repo, target_oid = _init_git_repo(tmp_path, units_yaml)
    providers_dir = repo / 'prices' / 'providers'
    providers_dir.mkdir()
    (providers_dir / 'testing.yml').write_text(
        """\
id: testing
name: Testing
api_pattern: testing
models:
  - id: model
    match: {equals: model}
    prices: {input_mtok: 1}
"""
    )
    monkeypatch.setattr(v3_compatibility, 'root_dir', repo)
    monkeypatch.setattr(build_module, 'package_dir', repo / 'prices')
    monkeypatch.setattr(build_module, 'root_dir', repo)
    monkeypatch.setattr(sys, 'argv', ['v3_compatibility', target_oid])

    v3_compatibility.main()

    assert not (repo / 'prices' / 'new_data').exists()
