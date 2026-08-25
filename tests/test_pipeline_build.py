from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from genai_prices import types as runtime_types
from prices import build, package_data

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
    return providers_dir


def test_build_writes_and_updates_published_data(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    providers_dir = prepare_build(monkeypatch, tmp_path)
    provider_path = providers_dir / 'testing.yml'
    provider_path.write_text(PROVIDER_YAML)
    (providers_dir / 'ignored.txt').write_text('not yaml')

    build.build()
    build.build()

    prices_path = tmp_path / 'prices' / 'new_data' / 'v2' / 'data.json'
    prices_path.write_text(json.dumps(json.loads(prices_path.read_bytes()), indent=4))
    build.build()

    provider_path.write_text(PROVIDER_YAML.replace('1.25', '2.5'))
    build.build()

    assert json.loads(prices_path.read_bytes()) == [
        {
            'id': 'testing',
            'name': 'Testing',
            'api_pattern': 'testing',
            'models': [{'id': 'model', 'match': {'equals': 'model'}, 'prices': {'input_mtok': 2.5}}],
        }
    ]
    schema = json.loads((providers_dir / '.schema.json').read_bytes())
    assert schema['$defs']['ModelPrice']['properties']['input_mtok']['description'] == (
        'price in USD per million uncached text input/prompt token'
    )
    output = capsys.readouterr().out
    assert 'unchanged' in output
    assert 'Prices have whitespace/dict ordering changes' in output
    assert 'Prices have the following changes:' in output


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
    ],
)
def test_build_reports_invalid_units(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, units_yaml: str, message: str
) -> None:
    providers_dir = prepare_build(monkeypatch, tmp_path, units=units_yaml)
    (providers_dir / 'testing.yml').write_text(PROVIDER_YAML)

    with pytest.raises(ValueError, match=message):
        build.build()


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
    units = UNITS_YAML + 'requests:\n  per: 1000\n  dimensions: {family: requests}\n'
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
    python_dir.mkdir(parents=True)
    javascript_dir.mkdir(parents=True)
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
    assert [call[0] for call in calls] == ['uv', 'uv', 'uv', 'uv', 'npx']


def test_package_data_rejects_a_non_array_payload(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data_dir = tmp_path / 'prices' / 'new_data' / 'v2'
    data_dir.mkdir(parents=True)
    (data_dir / 'data.json').write_text('{}')
    monkeypatch.setattr(package_data, 'this_package_dir', tmp_path / 'prices')

    with pytest.raises(ValueError, match='provider array'):
        package_data.package_data()
