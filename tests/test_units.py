from pathlib import Path
from typing import Any, cast

import ruamel.yaml

from genai_prices.units import UnitRegistry


def _load_units() -> dict[str, Any]:
    yaml = ruamel.yaml.YAML(typ='safe')
    with Path('prices/units.yml').open() as f:
        return cast(dict[str, Any], yaml.load(f))  # pyright: ignore[reportUnknownMemberType]


def test_units_yml_defines_current_python_unit_surface() -> None:
    raw_families = _load_units()

    assert set(raw_families) == {'tokens', 'requests'}

    token_family = raw_families['tokens']
    assert token_family['per'] == 1_000_000
    assert set(token_family['units']) == {
        'input_tokens',
        'output_tokens',
        'cache_read_tokens',
        'cache_write_tokens',
        'input_audio_tokens',
        'cache_audio_read_tokens',
        'output_audio_tokens',
    }
    assert {unit['price_key'] for unit in token_family['units'].values()} == {
        'input_mtok',
        'output_mtok',
        'cache_read_mtok',
        'cache_write_mtok',
        'input_audio_mtok',
        'cache_audio_read_mtok',
        'output_audio_mtok',
    }

    request_family = raw_families['requests']
    assert request_family['per'] == 1_000
    assert set(request_family['units']) == {'requests'}
    assert request_family['units']['requests']['price_key'] == 'requests_kcount'


def test_unit_registry_constructs_current_units() -> None:
    registry = UnitRegistry(_load_units())

    assert set(registry.families) == {'tokens', 'requests'}
    assert set(registry.units) == {
        'input_tokens',
        'output_tokens',
        'cache_read_tokens',
        'cache_write_tokens',
        'input_audio_tokens',
        'cache_audio_read_tokens',
        'output_audio_tokens',
        'requests',
    }
    assert registry.price_keys['input_mtok'] == 'input_tokens'
    assert registry.price_keys['requests_kcount'] == 'requests'


def test_unit_registry_sets_family_and_unit_backrefs() -> None:
    registry = UnitRegistry(_load_units())

    token_family = registry.families['tokens']
    input_unit = registry.units['input_tokens']

    assert input_unit.family is token_family
    assert input_unit.family_id == 'tokens'
    assert token_family.units['input_tokens'] is input_unit
    assert token_family.per == 1_000_000


def test_unit_registry_defaults_missing_price_key_to_usage_key() -> None:
    registry = UnitRegistry(
        {
            'characters': {
                'per': 1_000,
                'units': {
                    'input_characters': {
                        'dimensions': {'direction': 'input'},
                    },
                },
            },
        }
    )

    assert registry.units['input_characters'].price_key == 'input_characters'
    assert registry.price_keys['input_characters'] == 'input_characters'
