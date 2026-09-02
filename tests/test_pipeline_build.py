from __future__ import annotations

import ast
import copy
import json
import subprocess
from pathlib import Path
from typing import Any, cast

import jsonschema
import pytest
from jsonschema.validators import validator_for

from genai_prices import types as runtime_types
from prices import build, package_data
from prices.export_validation import runtime_unit_projection, validate_runtime_unit_projection
from prices.go_identifiers import go_usage_key_identifier
from prices.prices_types import Provider

UNITS_YAML = """\
input_tokens:
  per: 1000000
  price_key: input_mtok
  dimensions:
    family: tokens
    direction: input
output_tokens:
  per: 1000000
  price_key: output_mtok
  dimensions:
    family: tokens
    direction: output
"""

PROVIDER_YAML = """\
id: testing
name: Testing
api_pattern: testing
models:
  - id: model
    match:
      equals: model
    prices:
      input_mtok: 1.25
"""


def prepare_build(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, units: str = UNITS_YAML) -> Path:
    prices_dir = tmp_path / 'prices'
    providers_dir = prices_dir / 'providers'
    providers_dir.mkdir(parents=True)
    (prices_dir / 'units.yml').write_text(units)
    monkeypatch.setattr(build, 'package_dir', prices_dir)
    monkeypatch.setattr(build, 'root_dir', tmp_path)

    def resolve_compatibility_target(_target_oid: str | None = None) -> str:
        return '1' * 40

    def accept_compatibility(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(build, 'resolve_compatibility_target', resolve_compatibility_target)
    monkeypatch.setattr(build, 'validate_frozen_v2_artifacts', lambda: None)
    monkeypatch.setattr(build, 'validate_v3_compatibility', accept_compatibility)
    return providers_dir


def test_build_writes_and_updates_v3_without_touching_v2(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    providers_dir = prepare_build(monkeypatch, tmp_path)
    provider_path = providers_dir / 'testing.yml'
    provider_path.write_text(PROVIDER_YAML)
    (providers_dir / 'ignored.txt').write_text('not yaml')
    frozen_v2 = {
        relative_path: f'frozen {relative_path}'.encode()
        for relative_path in (
            'data.json',
            'data.schema.json',
            'data_slim.json',
            'data_slim.schema.json',
        )
    }
    for relative_path, content in frozen_v2.items():
        path = tmp_path / 'prices' / 'new_data' / 'v2' / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    build.build()
    build.build()

    prices_path = tmp_path / 'prices' / 'new_data' / 'v3' / 'data.json'
    prices_path.write_text(json.dumps(json.loads(prices_path.read_bytes()), indent=4))
    build.build()

    provider_path.write_text(PROVIDER_YAML.replace('1.25', '2.5'))
    build.build()

    payload = json.loads(prices_path.read_bytes())
    assert payload['units'] == runtime_unit_projection(build.load_units())
    assert payload['providers'] == [
        {
            'id': 'testing',
            'name': 'Testing',
            'api_pattern': 'testing',
            'models': [{'id': 'model', 'match': {'equals': 'model'}, 'prices': {'input_mtok': 2.5}}],
        }
    ]
    data_schema = json.loads((tmp_path / 'prices' / 'new_data' / 'v3' / 'data.schema.json').read_bytes())
    validator_cls = validator_for(data_schema, default=jsonschema.Draft202012Validator)
    validator_cls.check_schema(data_schema)
    validator_cls(data_schema).validate(payload)
    schema = json.loads((providers_dir / '.schema.json').read_bytes())
    assert schema['$defs']['ModelPrice']['properties']['input_mtok']['description'] == (
        'price in USD per million uncached text input/prompt token'
    )
    assert {
        relative_path: (tmp_path / 'prices' / 'new_data' / 'v2' / relative_path).read_bytes()
        for relative_path in frozen_v2
    } == frozen_v2
    output = capsys.readouterr().out
    assert 'unchanged' in output
    assert 'updated' in output


def test_build_rejects_compatibility_before_writing_any_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    providers_dir = prepare_build(monkeypatch, tmp_path)
    (providers_dir / 'testing.yml').write_text(PROVIDER_YAML)
    artifacts = {
        providers_dir / '.schema.json': b'authoring schema sentinel',
        tmp_path / 'prices' / 'new_data' / 'v3' / 'data.schema.json': b'v3 schema sentinel',
        tmp_path / 'prices' / 'new_data' / 'v3' / 'data.json': b'v3 data sentinel',
    }
    for path, content in artifacts.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    validation_order: list[str] = []

    def validate_frozen_v2_artifacts() -> None:
        validation_order.append('frozen-v2')

    def reject_compatibility(
        target_oid: str,
        *,
        candidate_runtime_units: object,
        candidate_implications: object,
        candidate_schema: object,
        candidate_payload: object,
    ) -> None:
        _ = candidate_runtime_units, candidate_implications, candidate_schema
        validation_order.append('v3-compatibility')
        assert target_oid == '1' * 40
        assert cast(dict[str, object], candidate_payload)['providers']
        raise ValueError('incompatible candidate')

    monkeypatch.setattr(build, 'validate_frozen_v2_artifacts', validate_frozen_v2_artifacts)
    monkeypatch.setattr(build, 'validate_v3_compatibility', reject_compatibility)

    with pytest.raises(ValueError, match='incompatible candidate'):
        build.build('base-ref')

    assert validation_order == ['frozen-v2', 'v3-compatibility']
    assert {path: path.read_bytes() for path in artifacts} == artifacts


@pytest.mark.parametrize(
    ('provider_yaml', 'message'),
    [
        ('id: broken\n', 'Error validating provider broken.yml'),
        (
            PROVIDER_YAML.replace(
                'models:\n',
                """\
extractors:
  - root: usage
    mappings: [{path: input_tokens, dest: input_tokens}]
  - root: result
    mappings: [{path: output_tokens, dest: output_tokens}]
models:
""",
            ),
            'Duplicate extraction api_flavor',
        ),
        (
            """\
id: testing
name: Testing
api_pattern: testing
models:
  - id: model
    match: {equals: first}
    prices: {input_mtok: 1}
  - id: model
    match: {equals: second}
    prices: {input_mtok: 1}
""",
            'Duplicate model ids',
        ),
        (
            PROVIDER_YAML.replace(
                '  - id: model\n',
                '  - id: zebra\n    match: {equals: zebra}\n    prices: {input_mtok: 1}\n  - id: ant\n',
            ),
            'Models are not sorted by ID',
        ),
        (PROVIDER_YAML.replace('prices:\n      input_mtok: 1.25', 'prices: []'), 'model prices may not be empty'),
        (
            PROVIDER_YAML.replace(
                'prices:\n      input_mtok: 1.25',
                """\
prices:
      - constraint: {start_date: 2026-01-01}
        prices: {input_mtok: 1}
""",
            ),
            'exactly one price must not have a constraint',
        ),
        (
            PROVIDER_YAML.replace(
                'prices:\n      input_mtok: 1.25',
                """\
prices:
      input_mtok:
        base: 1
        tiers:
          - {start: 2, price: 2}
          - {start: 1, price: 3}
""",
            ),
            'Tiers must be in ascending order',
        ),
        (
            """\
id: testing
name: Testing
api_pattern: testing
models:
  - id: first
    match: {equals: shared}
    prices: {input_mtok: 1}
  - id: second
    match: {equals: shared}
    prices: {input_mtok: 1}
""",
            'matches other model ids',
        ),
        (
            PROVIDER_YAML.replace(
                'prices:\n      input_mtok: 1.25',
                'prices: {input_mtok: 1.25}\n    price_discrepancies: {source: different}\n    prices_checked: 2026-01-01',
            ),
            'price_discrepancies.*should be removed',
        ),
        (
            PROVIDER_YAML.replace(
                'prices:\n      input_mtok: 1.25',
                """\
prices:
      - prices: {input_mtok: 1}
      - constraint: {start_time: '00:00:00', end_time: '01:00:00'}
        prices: {input_mtok: 2}
""",
            ),
            'Times must be timezone aware',
        ),
        (
            PROVIDER_YAML.replace(
                'api_pattern: testing\n', 'api_pattern: testing\nextractors: [{root: [], mappings: []}]\n'
            ),
            'ExtractPath should not be empty',
        ),
        (
            PROVIDER_YAML.replace(
                'api_pattern: testing\n',
                """\
api_pattern: testing
extractors:
  - root:
      - type: array-match
        field: choices
        match: {equals: choice}
    mappings: []
""",
            ),
            'ExtractPath should not end',
        ),
        (
            PROVIDER_YAML.replace(
                'match:\n      equals: model',
                'match:\n      or: [{equals: model}, {equals: model}]',
            ),
            'Duplicates found',
        ),
        (PROVIDER_YAML.replace('match:\n      equals: model', 'match: invalid'), 'union_tag_not_found'),
    ],
)
def test_build_reports_invalid_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, provider_yaml: str, message: str
) -> None:
    providers_dir = prepare_build(monkeypatch, tmp_path)
    (providers_dir / 'broken.yml').write_text(provider_yaml)

    with pytest.raises(ValueError, match=message):
        build.build()


def test_build_accepts_composite_model_matching(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    units = (
        UNITS_YAML
        + """\
widgets:
  per: 1
  price_key: widget_price
  dimensions:
    family: widgets
"""
    )
    providers_dir = prepare_build(monkeypatch, tmp_path, units=units)
    (providers_dir / 'testing.yml').write_text(
        """\
id: testing
name: Testing
api_pattern: testing
models:
  - id: composite
    match:
      and:
        - contains: composite
        - ends_with: -latest
    prices: {widget_price: 1}
  - id: other
    match: {equals: other}
    prices: {input_mtok: 1}
"""
    )

    build.build()


@pytest.mark.parametrize(
    ('units_yaml', 'message'),
    [
        ('tokens:\n  dimensions: {family: tokens}\n', 'Missing per for unit tokens'),
        ('tokens:\n  per: 1\n  dimensions: {}\n', 'Missing required family dimension'),
        (
            'first:\n  per: 1\n  dimensions: {family: tokens}\n'
            'second:\n  per: 2\n  dimensions: {family: tokens, direction: input}\n',
            'Inconsistent per for family dimension tokens',
        ),
        ('constructor:\n  per: 1\n  dimensions: {family: tokens}\n', 'is reserved'),
        ('tokens:\n  per: 1\n  dimensions: {family: tokens, Å: ring}\n', 'Invalid unit dimension key'),
    ],
)
def test_build_reports_invalid_units(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, units_yaml: str, message: str
) -> None:
    providers_dir = prepare_build(monkeypatch, tmp_path, units=units_yaml)
    (providers_dir / 'testing.yml').write_text(PROVIDER_YAML)

    with pytest.raises(ValueError, match=message):
        build.build()


def _v3_test_provider(*, price_key: str = 'input_mtok', extractor_dest: str = 'input_tokens') -> Provider:
    return Provider.model_validate(
        {
            'id': 'testing',
            'name': 'Testing',
            'api_pattern': 'testing',
            'extractors': [
                {
                    'root': 'usage',
                    'mappings': [{'path': 'count', 'dest': extractor_dest}],
                }
            ],
            'models': [
                {
                    'id': 'model',
                    'match': {'equals': 'model'},
                    'prices': {price_key: 1},
                }
            ],
        }
    )


def test_prepare_v3_data_builds_a_runtime_only_wrapper_with_dynamic_unit_keys() -> None:
    raw_units: dict[str, Any] = {
        'future_events': {
            'per': 1,
            'price_key': 'future_event_price',
            'dimensions': {'family': 'events', 'kind': 'future'},
            'dimension_requirements': {'kind': {'family': 'events'}},
            'source_annotation': 'publisher only',
        }
    }
    schema, payload = build.prepare_v3_data(
        [_v3_test_provider(price_key='future_event_price', extractor_dest='future_events')], raw_units
    )
    validator_cls = validator_for(schema, default=jsonschema.Draft202012Validator)
    validator_cls.check_schema(schema)
    validator_cls(schema).validate(payload)

    assert list(payload['units']) == ['future_events']
    assert payload['units'] == {
        'future_events': {
            'per': 1,
            'price_key': 'future_event_price',
            'dimensions': {'family': 'events', 'kind': 'future'},
        }
    }
    assert 'enum' not in schema['$defs']['UsageExtractorMapping']['properties']['dest']
    assert isinstance(schema['$defs']['ModelPrice']['additionalProperties'], dict)


@pytest.mark.parametrize('mutation', ['zero per', 'missing dimensions', 'invalid family', 'missing provider name'])
def test_v3_schema_rejects_malformed_stable_core(mutation: str) -> None:
    raw_units = {
        'input_tokens': {
            'per': 1_000_000,
            'price_key': 'input_mtok',
            'dimensions': {'family': 'tokens', 'direction': 'input'},
        }
    }
    schema, payload = build.prepare_v3_data([_v3_test_provider()], raw_units)
    unit = cast(dict[str, Any], payload['units']['input_tokens'])
    provider = cast(dict[str, Any], payload['providers'][0])
    if mutation == 'zero per':
        unit['per'] = 0
    elif mutation == 'missing dimensions':
        unit.pop('dimensions')
    elif mutation == 'invalid family':
        cast(dict[str, Any], unit['dimensions'])['family'] = 1
    else:
        provider.pop('name')

    validator_cls = validator_for(schema, default=jsonschema.Draft202012Validator)
    assert not validator_cls(schema).is_valid(payload)


def test_v3_schema_unit_key_constraints_match_runtime_validation() -> None:
    schema = build.v3_data_schema()
    validator_cls = validator_for(schema, default=jsonschema.Draft202012Validator)
    validator = validator_cls(schema)
    payload: dict[str, Any] = {
        'providers': [],
        'units': {'events': {'dimensions': {'_internal': 'allowed', 'family': 'events'}, 'per': 1}},
    }
    validator.validate(payload)

    for invalid_key in ['_internal', 'await', 'class', 'constructor', '__proto__', 'valid-key', 'valid\n']:
        invalid_usage_payload = copy.deepcopy(payload)
        unit = cast(dict[str, Any], invalid_usage_payload['units']).pop('events')
        cast(dict[str, Any], invalid_usage_payload['units'])[invalid_key] = unit
        assert not validator.is_valid(invalid_usage_payload)
        with pytest.raises(ValueError, match='Invalid unit usage key'):
            validate_runtime_unit_projection(cast(dict[str, dict[str, object]], invalid_usage_payload['units']))

        invalid_price_payload = copy.deepcopy(payload)
        cast(dict[str, Any], invalid_price_payload['units']['events'])['price_key'] = invalid_key
        assert not validator.is_valid(invalid_price_payload)
        with pytest.raises(ValueError, match='Invalid unit price key'):
            validate_runtime_unit_projection(cast(dict[str, dict[str, object]], invalid_price_payload['units']))


def test_prepare_v3_data_rejects_unsafe_normalization() -> None:
    with pytest.raises(ValueError, match='expected a positive integer from 1 to 9007199254740991'):
        build.prepare_v3_data(
            [_v3_test_provider(price_key='event_price', extractor_dest='events')],
            {
                'events': {
                    'per': 9_007_199_254_740_992,
                    'price_key': 'event_price',
                    'dimensions': {'family': 'events'},
                }
            },
        )


def test_v3_behavior_changing_variant_remains_distinguishable_when_extended() -> None:
    raw_units = {
        'input_tokens': {
            'per': 1_000_000,
            'price_key': 'input_mtok',
            'dimensions': {'family': 'tokens', 'direction': 'input'},
        }
    }
    schema, payload = build.prepare_v3_data([_v3_test_provider()], raw_units)
    extended_schema = copy.deepcopy(schema)
    extended_schema['$defs']['ClauseGlob'] = {
        'additionalProperties': False,
        'properties': {'glob': {'type': 'string'}},
        'required': ['glob'],
        'type': 'object',
    }
    match_variants = cast(
        list[dict[str, object]], extended_schema['$defs']['ModelInfo']['properties']['match']['oneOf']
    )
    match_variants.append({'$ref': '#/$defs/ClauseGlob'})

    model = payload['providers'][0]['models'][0]
    model['match'] = {'glob': 'model-*'}
    validator_cls = validator_for(extended_schema, default=jsonschema.Draft202012Validator)
    validator = validator_cls(extended_schema)
    assert validator.is_valid(payload)

    model['match'] = {}
    assert not validator.is_valid(payload)


@pytest.mark.parametrize(
    ('provider_yaml', 'message'),
    [
        (PROVIDER_YAML.replace('input_mtok', 'unknown_mtok'), 'Invalid model price for testing/model'),
        (
            PROVIDER_YAML.replace(
                'models:\n',
                """\
extractors:
  - root: usage
    mappings: [{path: input_tokens, dest: unknown_tokens}]
models:
""",
            ),
            'Invalid extractor destination for testing/default',
        ),
        (
            PROVIDER_YAML.replace(
                'models:\n',
                """\
extractors:
  - root: usage
    mappings: [{path: completion_tokens, dest: output_tokens}]
models:
""",
            ),
            'Invalid extractor for testing/default',
        ),
    ],
)
def test_build_reports_invalid_export(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, provider_yaml: str, message: str
) -> None:
    providers_dir = prepare_build(monkeypatch, tmp_path)
    (providers_dir / 'testing.yml').write_text(provider_yaml)

    with pytest.raises(ValueError, match=message):
        build.build()


def test_package_data_generates_both_runtime_packages(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    units = (
        UNITS_YAML
        + 'input_5m_tokens:\n'
        + '  per: 1000000\n'
        + '  price_key: input_5m_mtok\n'
        + '  dimensions: {family: tokens, direction: input, cache_ttl: 5m}\n'
        + '  dimension_requirements: {cache_ttl: {family: tokens}}\n'
        + 'request__count:\n'
        + '  per: 1000\n'
        + '  dimensions: {family: request_counts}\n'
        + 'requests:\n  per: 1000\n  dimensions: {family: requests}\n'
    )
    providers_dir = prepare_build(monkeypatch, tmp_path, units=units)
    provider_yaml = PROVIDER_YAML.replace(
        'prices:\n      input_mtok: 1.25',
        """\
prices:
      - prices: {input_mtok: 1.25}
      - constraint: {start_date: 2026-01-01}
        prices: {input_mtok: 1}
      - constraint: {start_time: '00:00:00Z', end_time: '01:00:00Z'}
        prices: {input_mtok: 0.5}
""",
    )
    (providers_dir / 'testing.yml').write_text(provider_yaml)
    build.build()

    python_dir = tmp_path / 'packages' / 'python' / 'genai_prices'
    javascript_dir = tmp_path / 'packages' / 'js' / 'src'
    go_dir = tmp_path / 'packages' / 'go'
    python_dir.mkdir(parents=True)
    javascript_dir.mkdir(parents=True)
    go_dir.mkdir(parents=True)
    monkeypatch.setattr(runtime_types, '__file__', str(python_dir / 'types.py'))
    monkeypatch.setattr(package_data, 'this_package_dir', tmp_path / 'prices')
    monkeypatch.setattr(package_data, 'root_dir', tmp_path)

    calls: list[list[str]] = []

    def run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, 'run', run)

    package_data.package_data()

    assert (python_dir / 'data.py').is_file()
    assert (python_dir / 'data_units.py').is_file()
    assert (javascript_dir / 'data.ts').is_file()
    assert (javascript_dir / 'dataUnits.ts').is_file()
    assert (go_dir / 'data_units.go').is_file()
    assert 'UsageInput5MTokens' in (go_dir / 'data_units.go').read_text()
    assert 'UsageRequest_Count' in (go_dir / 'data_units.go').read_text()
    assert (go_dir / 'internal' / 'data' / 'prices.json').is_file()
    assert [call[0] for call in calls] == ['uv', 'uv', 'uv', 'uv', 'gofmt', 'npx']

    expected_units = runtime_unit_projection(build.load_units())
    python_content = (python_dir / 'data_units.py').read_text()
    python_units = ast.literal_eval(python_content.split('unit_data: dict[str, Any] = ', 1)[1])
    typescript_content = (javascript_dir / 'dataUnits.ts').read_text()
    typescript_units = json.loads(
        typescript_content.split('export const unitData: RawUnitsDict = ', 1)[1].removesuffix(';\n')
    )
    go_content = (go_dir / 'data_units.go').read_text()
    go_order = go_content.split('var bundledUnitOrder = []UsageKey{', 1)[1].split('}', 1)[0]

    assert python_units == expected_units
    assert typescript_units == expected_units
    assert list(python_units) == list(typescript_units) == list(expected_units)
    assert [go_order.index(go_usage_key_identifier(key)) for key in expected_units] == sorted(
        go_order.index(go_usage_key_identifier(key)) for key in expected_units
    )
    assert 'dimension_requirements' not in python_content
    assert 'dimension_requirements' not in typescript_content
    assert 'dimension_requirements' not in go_content


def test_package_data_rejects_a_non_object_v3_payload(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data_dir = tmp_path / 'prices' / 'new_data' / 'v3'
    data_dir.mkdir(parents=True)
    (data_dir / 'data.json').write_text('[]')
    monkeypatch.setattr(package_data, 'this_package_dir', tmp_path / 'prices')

    with pytest.raises(ValueError, match='v3 payload object'):
        package_data.package_data()


def test_load_v3_payload_splits_and_preserves_publication_order(tmp_path: Path) -> None:
    providers = [{'id': 'testing'}]
    units = {
        'z_events': {'per': 1_000, 'dimensions': {'family': 'z_events'}},
        'a_events': {'per': 1_000, 'dimensions': {'family': 'a_events'}},
    }
    data_path = tmp_path / 'data.json'
    data_path.write_text(json.dumps({'units': units, 'providers': providers}))

    loaded_providers, loaded_units = package_data.load_v3_payload(data_path)

    assert loaded_providers == providers
    assert loaded_units == units
    assert list(loaded_units) == ['z_events', 'a_events']


@pytest.mark.parametrize(
    ('payload', 'message'),
    [
        ([], 'v3 payload object'),
        ({}, 'providers to be an array'),
        ({'providers': {}, 'units': {}}, 'providers to be an array'),
        ({'providers': []}, 'units to be an object'),
        ({'providers': [], 'units': []}, 'units to be an object'),
    ],
)
def test_load_v3_payload_rejects_invalid_roots(tmp_path: Path, payload: object, message: str) -> None:
    data_path = tmp_path / 'data.json'
    data_path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match=message):
        package_data.load_v3_payload(data_path)
