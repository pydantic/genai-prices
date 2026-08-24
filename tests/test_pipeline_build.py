from __future__ import annotations

import json
import subprocess
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pydantic_core
import pytest

from genai_prices.units import UnitDef
from prices import build, export_validation, package_data, prices_types, utils


def _units() -> dict[str, dict[str, object]]:
    return {
        'input_tokens': {
            'per': 1_000_000,
            'price_key': 'input_mtok',
            'dimensions': {'family': 'tokens', 'direction': 'input'},
        }
    }


def _provider(*, price: Decimal = Decimal('1')) -> prices_types.Provider:
    return prices_types.Provider(
        id='testing',
        name='Testing',
        api_pattern='testing',
        description='Provider description',
        price_comments='Provider price comments',
        models=[
            prices_types.ModelInfo(
                id='model',
                name='Model',
                description='Model description',
                price_comments='Model price comments',
                match=prices_types.ClauseEquals(equals='model'),
                prices=prices_types.ModelPrice(input_mtok=price),
            )
        ],
    )


def _patch_build_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    prices_dir = tmp_path / 'prices'
    monkeypatch.setattr(build, 'package_dir', prices_dir)
    monkeypatch.setattr(build, 'root_dir', tmp_path)
    return prices_dir


def test_build_writes_full_and_slim_exports(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    prices_dir = _patch_build_paths(monkeypatch, tmp_path)
    providers_dir = prices_dir / 'providers'
    providers_dir.mkdir(parents=True)
    (prices_dir / 'units.yml').write_text(
        """\
input_tokens:
  per: 1000000
  price_key: input_mtok
  dimensions:
    family: tokens
    direction: input
"""
    )
    (providers_dir / 'testing.yml').write_text(
        """\
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
    )
    (providers_dir / 'ignored.txt').write_text('not yaml')

    build.build()

    assert json.loads((providers_dir / '.schema.json').read_bytes())['$defs']['ModelPrice']['properties']['input_mtok']
    assert json.loads((prices_dir / 'new_data' / 'v2' / 'data.json').read_bytes()) == [
        {
            'id': 'testing',
            'name': 'Testing',
            'api_pattern': 'testing',
            'models': [{'id': 'model', 'match': {'equals': 'model'}, 'prices': {'input_mtok': 1.25}}],
        }
    ]
    assert (prices_dir / 'new_data' / 'v2' / 'data_slim.json').exists()


def test_build_reports_invalid_provider(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    prices_dir = _patch_build_paths(monkeypatch, tmp_path)
    providers_dir = prices_dir / 'providers'
    providers_dir.mkdir(parents=True)
    (prices_dir / 'units.yml').write_text(
        """\
input_tokens:
  per: 1000000
  dimensions:
    family: tokens
"""
    )
    (providers_dir / 'broken.yaml').write_text('id: broken\n')

    with pytest.raises(ValueError, match='Error validating provider broken.yaml'):
        build.build()


def test_write_prices_reports_updates_diffs_whitespace_and_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    prices_dir = _patch_build_paths(monkeypatch, tmp_path)
    units = _units()
    provider = _provider()

    build.write_prices([provider], units, 'new_data/v2/data.json')
    prices_path = prices_dir / 'new_data' / 'v2' / 'data.json'
    compact_data = prices_path.read_bytes()
    build.write_prices([provider], units, 'new_data/v2/data.json')

    prices_path.write_text(''.join(build.pretty_providers_json(compact_data)))
    build.write_prices([provider], units, 'new_data/v2/data.json')

    provider.models[0].prices = prices_types.ModelPrice(input_mtok=Decimal('2'))
    build.write_prices([provider], units, 'new_data/v2/data.json')
    build.write_prices([provider], units, 'new_data/v2/data_slim.json', slim=True)

    output = capsys.readouterr().out
    assert 'unchanged' in output
    assert 'Prices have whitespace/dict ordering changes' in output
    assert 'Prices have the following changes:' in output
    assert 'updated' in output
    slim_data = json.loads((prices_dir / 'new_data' / 'v2' / 'data_slim.json').read_bytes())
    assert slim_data == [
        {
            'id': 'testing',
            'name': 'Testing',
            'api_pattern': 'testing',
            'models': [{'id': 'model', 'match': {'equals': 'model'}, 'prices': {'input_mtok': 2}}],
        }
    ]
    slim_schema = json.loads((prices_dir / 'new_data' / 'v2' / 'data_slim.schema.json').read_bytes())
    assert 'description' not in slim_schema['$defs']['Provider']['properties']
    assert 'name' not in slim_schema['$defs']['ModelInfo']['properties']


def test_unit_price_schema_descriptions() -> None:
    additional_price_schema = {'anyOf': [{'type': 'number'}]}

    duration = build._unit_price_schema(
        UnitDef('audio_seconds', 'audio_hours', 3_600, {'family': 'audio'}), additional_price_schema
    )
    cache = build._unit_price_schema(
        UnitDef(
            'cache_write_day_tokens',
            'cache_write_day_mtok',
            1_000_000,
            {'family': 'tokens', 'token_type': 'cache_write', 'cache_ttl': 'day'},
        ),
        additional_price_schema,
    )
    normal = build._unit_price_schema(UnitDef('widgets', 'widgets', 12, {'family': 'widgets'}), additional_price_schema)

    assert duration['description'] == 'price in USD per audio hour'
    assert cache['description'] == 'price in USD per million tokens written to the cache with a day TTL'
    assert normal['description'] == 'price in USD per 12 widgets'
    assert additional_price_schema == {'anyOf': [{'type': 'number'}]}


def test_pipeline_utils_cover_sizes_prices_duplicates_and_schema_simplification() -> None:
    assert [utils.pretty_size(size) for size in (1, 1_024, 1_024 * 1_024)] == ['1 bytes', '1.00 KB', '1.00 MB']
    assert utils.mtok(None) is None
    assert utils.mtok(Decimal('0')) is None
    assert utils.mtok(Decimal('0.5')) == Decimal('500000.0')
    assert utils.distinct_mtok(Decimal('1'), Decimal('1')) is None
    assert utils.distinct_mtok(Decimal('1'), Decimal('2')) == Decimal('1000000')
    assert utils.check_unique([1, 2]) == [1, 2]
    with pytest.raises(ValueError, match='Duplicates found: 1'):
        utils.check_unique([1, '1'])

    object_schema = {
        '$defs': {'child': {'type': 'string'}},
        'type': 'object',
        'properties': {'value': {'type': 'array', 'prefixItems': [{'type': 'integer'}], 'items': {'type': 'string'}}},
        'additionalProperties': {'anyOf': [{'type': 'number'}, {'type': 'null'}], 'default': None},
        'patternProperties': {'^x': {'type': 'array'}},
    }
    simplified = utils.simplify_json_schema(object_schema)
    assert simplified['additionalProperties'] == {'type': 'number'}
    assert simplified['properties']['value']['prefixItems'] == [{'type': 'integer'}]
    assert simplified['patternProperties']['^x'] == {'type': 'array'}

    assert utils.simplify_json_schema({'type': 'object', 'additionalProperties': True})['additionalProperties'] is True
    assert utils.simplify_json_schema({'type': 'object'}) == {'type': 'object'}
    assert utils.simplify_json_schema({'type': 'array', 'prefixItems': [], 'items': {'type': 'string'}}) == {
        'type': 'array',
        'prefixItems': [],
        'items': {'type': 'string'},
    }
    assert utils.simplify_json_schema({'oneOf': [{'type': 'string'}, {'type': 'null'}], 'title': 'Nullable'}) == {
        'type': 'string',
        'title': 'Nullable',
    }
    assert utils.simplify_json_schema(
        {'anyOf': [{'type': 'string'}, {'type': 'integer'}, {'type': 'null'}], 'default': None}
    ) == {'anyOf': [{'type': 'string'}, {'type': 'integer'}]}
    assert utils.simplify_json_schema({'type': 'string'}) == {'type': 'string'}


@pytest.mark.parametrize(
    ('raw_units', 'message'),
    [
        ({'tokens': {'dimensions': {'family': 'tokens'}}}, 'Missing per for unit tokens'),
        ({'tokens': {'per': 1, 'dimensions': {}}}, 'Missing required family dimension for unit tokens'),
        (
            {
                'first': {'per': 1, 'dimensions': {'family': 'tokens'}},
                'second': {'per': 2, 'dimensions': {'family': 'tokens', 'direction': 'input'}},
            },
            'Inconsistent per for family dimension tokens',
        ),
        ({'constructor': {'per': 1, 'dimensions': {'family': 'tokens'}}}, 'is reserved'),
    ],
)
def test_validate_units_covers_remaining_validation_errors(
    raw_units: dict[str, dict[str, object]], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        export_validation.validate_units(raw_units)


def test_validate_export_payload_delegates_to_all_provider_validators(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def record_model_prices(*_args: object) -> None:
        calls.append('model_prices')

    def record_destinations(*_args: object) -> None:
        calls.append('destinations')

    def record_reasoning(*_args: object) -> None:
        calls.append('reasoning')

    monkeypatch.setattr(package_data, 'validate_provider_model_prices', record_model_prices)
    monkeypatch.setattr(package_data, 'validate_provider_extractor_destinations', record_destinations)
    monkeypatch.setattr(package_data, 'validate_provider_extractor_reasoning_coverage', record_reasoning)

    registry = export_validation.validate_export_payload([], _units())

    assert set(registry.units) == {'input_tokens'}
    assert calls == ['model_prices', 'destinations', 'reasoning']


def test_package_data_loads_and_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, object]] = []
    provider_data: list[package_data.JsonData] = [{'id': 'testing'}]
    units = _units()

    def load_provider_data(_path: Path) -> list[package_data.JsonData]:
        return provider_data

    def load_pipeline_units() -> dict[str, dict[str, object]]:
        return units

    def record_python_data(data: list[package_data.JsonData], raw_units: dict[str, dict[str, object]]) -> None:
        calls.append(('python', (data, raw_units)))

    def record_ts_data(data: list[package_data.JsonData], raw_units: dict[str, dict[str, object]]) -> None:
        calls.append(('typescript', (data, raw_units)))

    monkeypatch.setattr(package_data, '_load_provider_data', load_provider_data)
    monkeypatch.setattr(package_data, 'load_units', load_pipeline_units)
    monkeypatch.setattr(package_data, 'package_python_data', record_python_data)
    monkeypatch.setattr(package_data, 'package_ts_data', record_ts_data)

    package_data.package_data()

    assert calls == [('python', (provider_data, units)), ('typescript', (provider_data, units))]


def test_package_data_loader_and_python_formatter(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data_path = tmp_path / 'data.json'
    data_path.write_text('[{"id": "testing"}]')
    assert package_data._load_provider_data(data_path) == [{'id': 'testing'}]
    data_path.write_text('{"id": "testing"}')
    with pytest.raises(ValueError, match='provider array'):
        package_data._load_provider_data(data_path)

    commands: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(args)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, 'run', fake_run)
    generated_path = tmp_path / 'data.py'
    generated_path.write_text('  output_mtok=None,\nTzInfo(UTC)\n')
    package_data._format_generated_python_data(generated_path, post_process_provider_reprs=True)
    package_data._format_generated_python_data(generated_path)

    assert generated_path.read_text() == '\ndatetime.timezone.utc\n'
    assert len(commands) == 4
    assert commands[1][-2:] == ['lint.isort.split-on-trailing-comma = false', str(generated_path)]


def test_package_data_validation_helpers_cover_errors_and_iterators() -> None:
    registry = export_validation.validate_units(_units())
    price = prices_types.ModelPrice(input_mtok=Decimal('1'))
    conditional = prices_types.ConditionalPrice(prices=price)
    model = SimpleNamespace(id='model', prices=[conditional])
    valid_extractor = SimpleNamespace(mappings=[SimpleNamespace(path='value', dest='input_tokens')])
    provider = SimpleNamespace(id='testing', models=[model], extractors=[valid_extractor])

    package_data.validate_provider_model_prices([provider], registry)
    package_data.validate_provider_extractor_destinations([provider], registry)
    package_data.validate_provider_extractor_reasoning_coverage([provider])
    assert list(package_data._iter_provider_extractors([SimpleNamespace(id='without', extractors=None), provider])) == [
        ('testing', 0, valid_extractor)
    ]
    assert list(package_data._iter_model_prices(price)) == [('', price)]
    assert package_data._collect_model_price_keys(price) == {'input_mtok'}
    with pytest.raises(TypeError, match='Unsupported model price type: object'):
        package_data._collect_model_price_keys(object())

    invalid_model = SimpleNamespace(id='bad-model', prices=prices_types.ModelPrice(output_mtok=Decimal('1')))
    with pytest.raises(ValueError, match='Invalid model price for testing/bad-model'):
        package_data.validate_provider_model_prices([SimpleNamespace(id='testing', models=[invalid_model])], registry)
    invalid_extractor = SimpleNamespace(mappings=[SimpleNamespace(path='value', dest='unknown_tokens')])
    with pytest.raises(ValueError, match='Invalid extractor destination for testing/0'):
        package_data.validate_provider_extractor_destinations(
            [SimpleNamespace(id='testing', models=[], extractors=[invalid_extractor])], registry
        )
    reasoning_extractor = SimpleNamespace(
        mappings=[
            SimpleNamespace(path='completion_tokens', dest='output_tokens'),
        ]
    )
    with pytest.raises(ValueError, match='Invalid extractor for testing/0'):
        package_data.validate_provider_extractor_reasoning_coverage(
            [SimpleNamespace(id='testing', models=[], extractors=[reasoning_extractor])]
        )


def test_package_ts_data_renders_constraints_and_runtime_units(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    js_src = tmp_path / 'packages' / 'js' / 'src'
    js_src.mkdir(parents=True)
    monkeypatch.setattr(package_data, 'root_dir', tmp_path)
    formatter_calls: list[tuple[list[str], str | None]] = []

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        cwd = kwargs.get('cwd')
        formatter_calls.append((args, cwd if isinstance(cwd, str) else None))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, 'run', fake_run)
    provider_data: package_data.JsonData = [
        {'constraint': {'start_date': '2026-01-01'}},
        {'constraint': {'start_time': '00:00', 'end_time': '01:00'}},
        {'constraint': {'type': 'existing', 'start_date': '2026-01-01'}},
        {'constraint': {'other': True}},
        {'constraint': None},
    ]
    units = {
        'input_tokens': {'per': 1_000_000, 'dimensions': {'family': 'tokens'}},
        'requests': {'per': 1_000, 'price_key': 'requests_kcount', 'dimensions': {'family': 'requests'}},
    }

    package_data.package_ts_data(provider_data, units)

    rendered_data = (js_src / 'data.ts').read_text()
    assert '"type": "start_date"' in rendered_data
    assert '"type": "time_of_date"' in rendered_data
    assert '"type": "existing"' in rendered_data
    assert package_data._runtime_unit_data(units) == {
        'input_tokens': {'per': 1_000_000, 'dimensions': {'family': 'tokens'}},
        'requests': {
            'per': 1_000,
            'price_key': 'requests_kcount',
            'dimensions': {'family': 'requests'},
        },
    }
    assert formatter_calls == [
        (
            ['npx', '--', 'prettier', '--write', 'src/data.ts', 'src/dataUnits.ts'],
            str(tmp_path / 'packages' / 'js'),
        )
    ]


def test_pretty_providers_json_round_trips() -> None:
    assert build.pretty_providers_json(pydantic_core.to_json([{'id': 'testing'}])) == [
        '[\n',
        '  {\n',
        '    "id": "testing"\n',
        '  }\n',
        ']',
    ]
