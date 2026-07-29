from __future__ import annotations

import ast
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock, patch

import pytest

from genai_prices import data
from genai_prices.data_units import unit_data
from genai_prices.types import (
    ModelPrice,
    TieredPrices,
    Usage,
    _collect_resolved_model_prices,
    _compute_registry_priced_counts,
)
from genai_prices.units import UnitDef, UnitRegistry, _get_registry
from prices import package_data, prices_types as build_types
from prices.export_validation import validate_units

from .unit_registry_helpers import load_units

TOKEN_USAGE_KEYS = {
    'input_tokens',
    'output_tokens',
    'cache_read_tokens',
    'cache_write_tokens',
    'input_text_tokens',
    'output_text_tokens',
    'cache_text_read_tokens',
    'cache_text_write_tokens',
    'input_audio_tokens',
    'output_audio_tokens',
    'cache_audio_read_tokens',
    'cache_audio_write_tokens',
    'input_image_tokens',
    'output_image_tokens',
    'cache_image_read_tokens',
    'cache_image_write_tokens',
    'input_video_tokens',
    'output_video_tokens',
    'cache_video_read_tokens',
    'cache_video_write_tokens',
    'input_tool_tokens',
    'input_text_tool_tokens',
    'input_audio_tool_tokens',
    'input_image_tool_tokens',
    'input_video_tool_tokens',
    'output_reasoning_tokens',
    'output_text_reasoning_tokens',
    'output_audio_reasoning_tokens',
    'output_image_reasoning_tokens',
    'output_video_reasoning_tokens',
    'output_citation_tokens',
    'output_text_citation_tokens',
    'output_audio_citation_tokens',
    'output_image_citation_tokens',
    'output_video_citation_tokens',
}

TOKEN_PRICE_KEYS = {
    'input_mtok',
    'output_mtok',
    'cache_read_mtok',
    'cache_write_mtok',
    'input_text_mtok',
    'output_text_mtok',
    'cache_text_read_mtok',
    'cache_text_write_mtok',
    'input_audio_mtok',
    'output_audio_mtok',
    'cache_audio_read_mtok',
    'cache_audio_write_mtok',
    'input_image_mtok',
    'output_image_mtok',
    'cache_image_read_mtok',
    'cache_image_write_mtok',
    'input_video_mtok',
    'output_video_mtok',
    'cache_video_read_mtok',
    'cache_video_write_mtok',
    'input_tool_mtok',
    'input_text_tool_mtok',
    'input_audio_tool_mtok',
    'input_image_tool_mtok',
    'input_video_tool_mtok',
    'output_reasoning_mtok',
    'output_text_reasoning_mtok',
    'output_audio_reasoning_mtok',
    'output_image_reasoning_mtok',
    'output_video_reasoning_mtok',
    'output_citation_mtok',
    'output_text_citation_mtok',
    'output_audio_citation_mtok',
    'output_image_citation_mtok',
    'output_video_citation_mtok',
}

REPORTABLE_USAGE_KEYS = TOKEN_USAGE_KEYS | {'web_searches'}
ALL_USAGE_KEYS = REPORTABLE_USAGE_KEYS | {'requests'}
ALL_PRICE_KEYS = TOKEN_PRICE_KEYS | {'web_searches_kcount', 'requests_kcount'}


def _custom_price_key_units() -> dict[str, Any]:
    return {
        'input_tokens': {
            'per': 1_000_000,
            'price_key': 'input_mtok',
            'dimensions': {'family': 'tokens', 'direction': 'input'},
        },
        'sausage_tokens': {
            'per': 1_000_000,
            'price_key': 'sausage_mtok',
            'dimensions': {'family': 'tokens', 'direction': 'input', 'ingredient': 'sausage'},
        },
    }


def _custom_price_key_registry() -> UnitRegistry:
    return UnitRegistry(_custom_price_key_units())


@contextmanager
def _use_registry(raw_units: dict[str, Any]) -> Iterator[UnitRegistry]:
    registry = UnitRegistry(raw_units)
    with patch('genai_prices.units._get_registry', return_value=registry):
        yield registry


def _build_provider_prices(
    prices: build_types.ModelPrice | list[build_types.ConditionalPrice],
    *,
    extractors: list[build_types.UsageExtractor] | None = None,
    model_id: str = 'model',
) -> build_types.Provider:
    return build_types.Provider(
        id='testing',
        name='Testing',
        api_pattern='testing',
        extractors=extractors,
        models=[
            build_types.ModelInfo(
                id=model_id,
                match=build_types.ClauseEquals(equals=model_id),
                prices=prices,
            )
        ],
    )


def _build_extractor(dest: str) -> build_types.UsageExtractor:
    return build_types.UsageExtractor.model_construct(
        root='usage',
        mappings=[_build_extractor_mapping('value', dest)],
        api_flavor='default',
        model_path='model',
    )


def _build_extractor_mapping(path: str, dest: str, *, required: bool = True) -> build_types.UsageExtractorMapping:
    return build_types.UsageExtractorMapping.model_construct(path=path, dest=dest, required=required)


def test_units_yml_defines_current_python_unit_surface() -> None:
    raw_units = load_units()

    assert set(raw_units) == ALL_USAGE_KEYS

    token_units = {usage_key: raw_units[usage_key] for usage_key in TOKEN_USAGE_KEYS}
    assert {unit['per'] for unit in token_units.values()} == {1_000_000}
    assert {unit['dimensions']['family'] for unit in token_units.values()} == {'tokens'}
    assert {unit['price_key'] for unit in token_units.values()} == TOKEN_PRICE_KEYS

    request_unit = raw_units['requests']
    assert request_unit['per'] == 1_000
    assert request_unit['dimensions'] == {'family': 'requests'}
    assert request_unit['price_key'] == 'requests_kcount'

    web_search_unit = raw_units['web_searches']
    assert web_search_unit['per'] == 1_000
    assert web_search_unit['dimensions'] == {'family': 'tool_calls'}
    assert web_search_unit['price_key'] == 'web_searches_kcount'


def test_units_yml_token_unit_names_follow_builtin_conventions() -> None:
    raw_units = load_units()

    for usage_key, unit in raw_units.items():
        dimensions = unit['dimensions']
        if dimensions['family'] != 'tokens':
            continue

        price_key = unit['price_key']
        assert usage_key.endswith('_tokens')
        assert price_key.endswith('_mtok')

        direction = dimensions['direction']
        modality = dimensions.get('modality')
        token_type = dimensions.get('token_type')
        if token_type is None:
            expected_stem = f'{direction}_{modality}' if modality is not None else direction
        elif token_type in {'cache_read', 'cache_write'}:
            assert direction == 'input'
            cache_operation = token_type.removeprefix('cache_')
            expected_stem = (
                f'cache_{modality}_{cache_operation}' if modality is not None else f'cache_{cache_operation}'
            )
        else:
            expected_stem = (
                f'{direction}_{modality}_{token_type}' if modality is not None else f'{direction}_{token_type}'
            )

        assert usage_key == f'{expected_stem}_tokens'
        assert price_key == f'{expected_stem}_mtok'


def test_repo_prices_omit_redundant_equal_rate_descendants() -> None:
    registry = UnitRegistry(load_units())
    redundant_prices: list[str] = []

    for provider in data.providers:
        for model in provider.models:
            model_prices = (
                [price.prices for price in model.prices] if isinstance(model.prices, list) else [model.prices]
            )
            for price_index, model_price in enumerate(model_prices):
                resolved_prices = _collect_resolved_model_prices(model_price, registry)
                prices_by_usage_key = {unit.usage_key: (unit, price_value) for unit, price_value in resolved_prices}

                for unit, price_value in resolved_prices:
                    ancestor_prices = [
                        prices_by_usage_key[ancestor_key]
                        for ancestor_key in registry.ancestor_usage_keys(unit.usage_key)
                        if ancestor_key in prices_by_usage_key
                    ]
                    if not ancestor_prices:
                        continue

                    closest_depth = max(len(ancestor.dimensions) for ancestor, _ in ancestor_prices)
                    if not any(
                        ancestor_price == price_value
                        for ancestor, ancestor_price in ancestor_prices
                        if len(ancestor.dimensions) == closest_depth
                    ):
                        continue

                    required_by_descendant = any(
                        unit.usage_key in registry.ancestor_usage_keys(other.usage_key)
                        for other, _ in resolved_prices
                        if other is not unit
                    )
                    other_units = [other for other, _ in resolved_prices if other is not unit]
                    required_as_join = any(
                        registry.find_join(left, right) is unit
                        for left_index, left in enumerate(other_units)
                        for right in other_units[left_index + 1 :]
                    )
                    if not required_by_descendant and not required_as_join:
                        redundant_prices.append(  # pragma: no cover
                            f'{provider.id}/{model.id}[{price_index}]:{unit.price_key}'
                        )

    assert redundant_prices == []


def test_generated_unit_modules_are_separate_from_provider_data() -> None:
    python_provider_data = Path('packages/python/genai_prices/data.py').read_text()
    python_unit_data = Path('packages/python/genai_prices/data_units.py').read_text()
    typescript_provider_data = Path('packages/js/src/data.ts').read_text()
    typescript_unit_data = Path('packages/js/src/dataUnits.ts').read_text()

    assert 'unit_data' not in python_provider_data
    assert 'unitData' not in typescript_provider_data
    assert ast.literal_eval(python_unit_data.split('unit_data: dict[str, Any] = ', 1)[1]) == load_units()
    assert all(usage_key in typescript_unit_data for usage_key in load_units())


def test_generated_unit_modules_contain_only_raw_data_types() -> None:
    assert 'UnitRegistry' not in Path('packages/python/genai_prices/data_units.py').read_text()
    assert 'UnitRegistry' not in Path('packages/js/src/dataUnits.ts').read_text()


def test_unit_registry_indexes_bundled_units() -> None:
    registry = UnitRegistry(unit_data)

    assert set(registry.units) == ALL_USAGE_KEYS
    assert registry._all_usage_keys == frozenset(ALL_USAGE_KEYS)
    assert registry._all_price_keys == frozenset(ALL_PRICE_KEYS)
    assert registry._reported_usage_keys == frozenset(REPORTABLE_USAGE_KEYS)
    assert registry.unit_for_price_key('input_mtok') is registry.units['input_tokens']
    assert registry.unit_for_price_key('web_searches_kcount') is registry.units['web_searches']
    assert registry.unit_for_price_key('requests_kcount') is registry.units['requests']
    assert registry.ancestor_usage_keys('cache_audio_read_tokens') == frozenset(
        {'input_tokens', 'cache_read_tokens', 'input_audio_tokens'}
    )
    assert (
        registry.find_join(registry.units['cache_read_tokens'], registry.units['input_audio_tokens'])
        is registry.units['cache_audio_read_tokens']
    )
    assert not registry.units['cache_read_tokens'].is_compatible_with(registry.units['input_tool_tokens'])
    assert not registry.units['output_reasoning_tokens'].is_compatible_with(registry.units['output_citation_tokens'])
    assert (
        registry.find_join(registry.units['output_text_tokens'], registry.units['output_reasoning_tokens'])
        is registry.units['output_text_reasoning_tokens']
    )
    assert registry.ancestor_usage_keys('output_text_reasoning_tokens') == frozenset(
        {'output_tokens', 'output_text_tokens', 'output_reasoning_tokens'}
    )
    assert registry.find_join(registry.units['input_tokens'], registry.units['output_tokens']) is None


def test_unit_registry_units_mapping_is_immutable() -> None:
    registry = UnitRegistry(unit_data)

    with pytest.raises(TypeError, match="'mappingproxy' object does not support item assignment"):
        cast(dict[str, Any], registry.units)['new_unit'] = registry.units['input_tokens']


@pytest.mark.parametrize('per', [0, -1, 1.5, True, '1000000'])
def test_validate_units_rejects_invalid_per(per: Any) -> None:
    with pytest.raises(ValueError, match='expected a positive integer'):
        validate_units(
            {
                'input_tokens': {
                    'per': per,
                    'price_key': 'input_mtok',
                    'dimensions': {'family': 'tokens', 'direction': 'input'},
                },
            }
        )


def test_validate_units_accepts_bundled_token_type_units() -> None:
    registry = validate_units(load_units())

    assert registry.units['cache_audio_read_tokens'].dimensions == {
        'family': 'tokens',
        'direction': 'input',
        'modality': 'audio',
        'token_type': 'cache_read',
    }


def test_compute_registry_priced_counts_handles_reasoning_modality_overlap() -> None:
    registry = UnitRegistry(load_units())
    resolved_prices = _collect_resolved_model_prices(
        ModelPrice(
            output_mtok=Decimal('1'),
            output_text_mtok=Decimal('2'),
            output_reasoning_mtok=Decimal('3'),
            output_text_reasoning_mtok=Decimal('4'),
        ),
        registry,
    )

    assert _compute_registry_priced_counts(
        resolved_prices,
        Usage(
            output_tokens=100,
            output_text_tokens=60,
            output_reasoning_tokens=30,
            output_text_reasoning_tokens=20,
        ),
    ) == {
        'output_tokens': 30,
        'output_text_tokens': 40,
        'output_reasoning_tokens': 10,
        'output_text_reasoning_tokens': 20,
    }


def test_unit_registry_definitions_are_immutable() -> None:
    registry = UnitRegistry(unit_data)
    unit = registry.units['input_tokens']

    with pytest.raises(FrozenInstanceError, match='cannot assign to field'):
        cast(Any, unit).per = 1
    with pytest.raises(TypeError, match="'mappingproxy' object does not support item assignment"):
        cast(dict[str, str], unit.dimensions)['modality'] = 'audio'


def test_unit_definition_copies_dimensions_before_freezing() -> None:
    dimensions = {'family': 'tokens'}
    unit = UnitDef('tokens', 'mtok', 1_000_000, dimensions)

    dimensions['direction'] = 'input'

    assert unit.dimensions == {'family': 'tokens'}


def test_model_price_str_includes_unregistered_candidate_keys() -> None:
    assert str(ModelPrice(hovercraft_mtok=Decimal('1'))) == '$1/hovercraft MTok'


def test_package_python_data_accepts_separated_inputs_without_units_yml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from genai_prices import types as runtime_types

    units = {
        'transient_tokens': {
            'per': 1_000_000,
            'price_key': 'transient_mtok',
            'dimensions': {'family': 'transient'},
        },
    }
    provider = _build_provider_prices(
        build_types.ModelPrice.model_validate({'transient_mtok': '1'}),
        extractors=[_build_extractor('transient_tokens')],
    )
    provider_data = build_types.providers_schema.dump_python(
        [provider],
        mode='json',
        by_alias=True,
        exclude_none=True,
        warnings=False,
    )

    py_package_dir = tmp_path / 'genai_prices'
    py_package_dir.mkdir()
    monkeypatch.setattr(runtime_types, '__file__', str(py_package_dir / 'types.py'))
    monkeypatch.setattr(package_data, 'root_dir', tmp_path)

    def skip_format_generated_python_data(_path: Path, *, post_process_provider_reprs: bool = False) -> None:
        _ = post_process_provider_reprs

    monkeypatch.setattr(package_data, '_format_generated_python_data', skip_format_generated_python_data)

    package_data.package_python_data(provider_data, units)

    assert (py_package_dir / 'data.py').exists()
    unit_data_content = (py_package_dir / 'data_units.py').read_text()
    generated_units = ast.literal_eval(unit_data_content.split('unit_data: dict[str, Any] = ', 1)[1])
    assert generated_units == units


def test_runtime_provider_registry_injection_preserves_malformed_shapes_for_schema_validation() -> None:
    from genai_prices import types as runtime_types

    registry = UnitRegistry({})
    invalid_provider = object()
    invalid_extractor = object()
    raw_providers: list[Any] = [
        invalid_provider,
        {'id': 'without-extractors'},
        {'id': 'with-extractors', 'extractors': [invalid_extractor, {'mappings': []}]},
    ]

    assert runtime_types._inject_extractor_registry({}, registry) == {}
    injected = runtime_types._inject_extractor_registry(raw_providers, registry)
    assert injected[0] is invalid_provider
    assert injected[1] == {'id': 'without-extractors'}
    assert injected[2]['extractors'][0] is invalid_extractor
    assert injected[2]['extractors'][1] == {'mappings': [], '_registry': registry}


def test_package_python_data_preserves_bundled_registry_if_runtime_provider_validation_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from genai_prices import types as runtime_types

    class RuntimeProviderValidationError(RuntimeError):
        pass

    bundled_registry = _get_registry()
    units = {
        'transient_tokens': {
            'per': 1_000_000,
            'price_key': 'transient_mtok',
            'dimensions': {'family': 'transient'},
        },
    }
    py_package_dir = tmp_path / 'genai_prices'
    py_package_dir.mkdir()
    monkeypatch.setattr(runtime_types, '__file__', str(py_package_dir / 'types.py'))

    def fail_runtime_provider_validation(_provider_data: Any, _registry: UnitRegistry) -> list[runtime_types.Provider]:
        raise RuntimeProviderValidationError('sentinel runtime provider validation failure')

    monkeypatch.setattr(runtime_types, '_providers_from_raw', fail_runtime_provider_validation)

    with pytest.raises(RuntimeProviderValidationError, match='sentinel runtime provider validation failure'):
        package_data.package_python_data([], units)

    assert _get_registry() is bundled_registry
    assert 'transient_tokens' not in bundled_registry.units


def test_runtime_provider_parsing_uses_supplied_extractor_registry() -> None:
    from genai_prices import types as runtime_types

    registry = UnitRegistry(
        {
            'transient_tokens': {
                'per': 1_000_000,
                'price_key': 'transient_mtok',
                'dimensions': {'family': 'transient'},
            },
        }
    )
    provider = runtime_types._providers_from_raw(
        [
            {
                'id': 'testing',
                'name': 'Testing',
                'api_pattern': 'testing',
                'extractors': [
                    {
                        'root': 'usage',
                        'mappings': [{'path': 'value', 'dest': 'transient_tokens', 'required': True}],
                    },
                ],
            },
        ],
        registry,
    )[0]

    assert provider.extractors is not None
    assert provider.extractors[0]._reported_usage_keys == frozenset({'transient_tokens'})


def test_package_data_accepts_current_provider_extractor_destinations() -> None:
    registry = UnitRegistry(load_units())

    package_data.validate_provider_extractor_destinations(data.providers, registry)


def test_unit_registry_sets_unit_per_and_family_dimension() -> None:
    registry = UnitRegistry(load_units())

    input_unit = registry.units['input_tokens']

    assert input_unit.dimensions['family'] == 'tokens'
    assert input_unit.per == 1_000_000


def test_unit_registry_defaults_missing_price_key_to_usage_key() -> None:
    registry = UnitRegistry(
        {
            'input_characters': {
                'per': 1_000,
                'dimensions': {'family': 'characters', 'direction': 'input'},
            },
        }
    )

    assert registry.units['input_characters'].price_key == 'input_characters'
    assert registry.unit_for_price_key('input_characters') is registry.units['input_characters']


def test_unit_registry_indexes_units_by_dimension_set() -> None:
    registry = UnitRegistry(load_units())

    assert (
        registry._units_by_dimension[frozenset({('family', 'tokens'), ('direction', 'input')})]
        is registry.units['input_tokens']
    )
    assert (
        registry._units_by_dimension[frozenset({('family', 'tokens'), ('direction', 'input'), ('modality', 'audio')})]
        is registry.units['input_audio_tokens']
    )


def test_unit_registry_compatibility_rejects_cross_family_units() -> None:
    registry = UnitRegistry(load_units())

    assert not registry.units['input_tokens'].is_compatible_with(registry.units['requests'])


def test_unit_registry_compatibility_rejects_conflicting_dimensions() -> None:
    registry = UnitRegistry(load_units())

    assert not registry.units['input_tokens'].is_compatible_with(registry.units['output_tokens'])


def test_unit_registry_compatibility_accepts_parent_child_pairs() -> None:
    registry = UnitRegistry(load_units())

    assert registry.units['input_tokens'].is_compatible_with(registry.units['cache_read_tokens'])
    assert registry.units['cache_read_tokens'].is_compatible_with(registry.units['input_tokens'])


def test_unit_registry_compatibility_accepts_overlapping_pairs() -> None:
    registry = UnitRegistry(load_units())

    assert registry.units['cache_read_tokens'].is_compatible_with(registry.units['input_audio_tokens'])
    assert registry.units['input_audio_tokens'].is_compatible_with(registry.units['cache_read_tokens'])


def test_unit_registry_join_lookup_returns_descendant_for_parent_child_pair() -> None:
    registry = UnitRegistry(load_units())

    assert (
        registry.find_join(registry.units['input_tokens'], registry.units['cache_audio_read_tokens'])
        is registry.units['cache_audio_read_tokens']
    )


def test_unit_registry_join_lookup_returns_registered_cache_write_overlap() -> None:
    registry = UnitRegistry(load_units())

    assert (
        registry.find_join(registry.units['cache_write_tokens'], registry.units['input_audio_tokens'])
        is registry.units['cache_audio_write_tokens']
    )


def test_unit_registry_key_indexes_are_immutable_and_reused() -> None:
    raw_units = load_units()
    registry = UnitRegistry(raw_units)

    assert isinstance(registry._all_usage_keys, frozenset)
    assert isinstance(registry._all_price_keys, frozenset)
    assert isinstance(registry._reported_usage_keys, frozenset)
    assert isinstance(registry._reported_usage_keys_in_order, tuple)
    assert registry._reported_usage_keys_in_order == tuple(key for key in raw_units if key != 'requests')
    assert registry._reported_usage_keys is registry._reported_usage_keys
    assert registry._reported_usage_keys_in_order is registry._reported_usage_keys_in_order


def test_validate_units_rejects_missing_family_dimension() -> None:
    with pytest.raises(ValueError, match='Missing required family dimension for unit input_tokens'):
        validate_units(
            {
                'input_tokens': {
                    'per': 1_000_000,
                    'dimensions': {'direction': 'input'},
                },
            }
        )


def test_validate_units_rejects_inconsistent_per_within_family_dimension() -> None:
    with pytest.raises(ValueError, match='Inconsistent per for family dimension tokens'):
        validate_units(
            {
                'input_tokens': {
                    'per': 1_000_000,
                    'price_key': 'input_mtok',
                    'dimensions': {'family': 'tokens', 'direction': 'input'},
                },
                'output_tokens': {
                    'per': 1_000,
                    'price_key': 'output_mtok',
                    'dimensions': {'family': 'tokens', 'direction': 'output'},
                },
            }
        )


def test_validate_units_rejects_duplicate_price_keys() -> None:
    with pytest.raises(ValueError, match='Duplicate unit price key: input_mtok'):
        validate_units(
            {
                'input_tokens': {
                    'per': 1_000_000,
                    'price_key': 'input_mtok',
                    'dimensions': {'family': 'tokens', 'direction': 'input'},
                },
                'input_audio_tokens': {
                    'per': 1_000_000,
                    'price_key': 'input_mtok',
                    'dimensions': {'family': 'tokens', 'direction': 'input', 'modality': 'audio'},
                },
            }
        )


def test_validate_units_rejects_duplicate_dimension_sets_within_family_dimension() -> None:
    with pytest.raises(
        ValueError,
        match='Duplicate unit dimensions: input_tokens and prompt_tokens',
    ):
        validate_units(
            {
                'input_tokens': {
                    'per': 1_000_000,
                    'price_key': 'input_mtok',
                    'dimensions': {'family': 'tokens', 'direction': 'input'},
                },
                'prompt_tokens': {
                    'per': 1_000_000,
                    'price_key': 'prompt_mtok',
                    'dimensions': {'family': 'tokens', 'direction': 'input'},
                },
            }
        )


def test_unit_registry_allows_same_dimension_set_across_families() -> None:
    registry = UnitRegistry(
        {
            'input_tokens': {
                'per': 1_000_000,
                'price_key': 'input_mtok',
                'dimensions': {'family': 'tokens', 'direction': 'input'},
            },
            'input_characters': {
                'per': 1_000,
                'price_key': 'input_kchar',
                'dimensions': {'family': 'characters', 'direction': 'input'},
            },
        }
    )

    assert (
        registry.units['input_tokens'].dimensions['direction']
        == registry.units['input_characters'].dimensions['direction']
    )
    assert (
        registry.units['input_tokens'].dimensions['family'] != registry.units['input_characters'].dimensions['family']
    )


def test_validate_units_rejects_skipped_intermediate_dimension_sets() -> None:
    with pytest.raises(
        ValueError,
        match='Missing intermediate unit dimensions between input_tokens and cache_video_read_tokens',
    ):
        validate_units(
            {
                'input_tokens': {
                    'per': 1_000_000,
                    'price_key': 'input_mtok',
                    'dimensions': {'family': 'tokens', 'direction': 'input'},
                },
                'cache_read_tokens': {
                    'per': 1_000_000,
                    'price_key': 'cache_read_mtok',
                    'dimensions': {'family': 'tokens', 'direction': 'input', 'cache': 'read'},
                },
                'cache_video_read_tokens': {
                    'per': 1_000_000,
                    'price_key': 'cache_video_read_mtok',
                    'dimensions': {'family': 'tokens', 'direction': 'input', 'modality': 'video', 'cache': 'read'},
                },
            }
        )


def test_validate_units_rejects_compatible_pair_with_missing_join() -> None:
    with pytest.raises(
        ValueError,
        match='Missing join unit dimensions between cache_write_tokens and input_audio_tokens',
    ):
        validate_units(
            {
                'input_tokens': {
                    'per': 1_000_000,
                    'price_key': 'input_mtok',
                    'dimensions': {'family': 'tokens', 'direction': 'input'},
                },
                'cache_write_tokens': {
                    'per': 1_000_000,
                    'price_key': 'cache_write_mtok',
                    'dimensions': {'family': 'tokens', 'direction': 'input', 'cache': 'write'},
                },
                'input_audio_tokens': {
                    'per': 1_000_000,
                    'price_key': 'input_audio_mtok',
                    'dimensions': {'family': 'tokens', 'direction': 'input', 'modality': 'audio'},
                },
            }
        )


@pytest.mark.parametrize(
    ('usage_key', 'price_key', 'message'),
    [
        ('_private_name', 'private_mtok', "Invalid unit usage key: '_private_name' must not start"),
        ('$input_tokens', 'input_mtok', r"Invalid unit usage key: '\$input_tokens' is not a public identifier"),
        ('class', 'class_mtok', "Invalid unit usage key: 'class' is a reserved keyword"),
        ('def', 'def_mtok', "Invalid unit usage key: 'def' is a reserved keyword"),
        ('function', 'function_mtok', "Invalid unit usage key: 'function' is a reserved keyword"),
        ('café_tokens', 'cafe_mtok', "Invalid unit usage key: 'café_tokens' is not a public identifier"),
        ('valid_usage', '_private_name', "Invalid unit price key: '_private_name' must not start"),
        ('valid_usage', '$input_mtok', r"Invalid unit price key: '\$input_mtok' is not a public identifier"),
        ('valid_usage', 'class', "Invalid unit price key: 'class' is a reserved keyword"),
        ('valid_usage', 'lambda', "Invalid unit price key: 'lambda' is a reserved keyword"),
        ('valid_usage', 'function', "Invalid unit price key: 'function' is a reserved keyword"),
        ('valid_usage', 'café_mtok', "Invalid unit price key: 'café_mtok' is not a public identifier"),
    ],
)
def test_validate_units_rejects_unsafe_public_keys(usage_key: str, price_key: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        validate_units(
            {
                usage_key: {
                    'per': 1_000_000,
                    'price_key': price_key,
                    'dimensions': {'family': 'tokens', 'direction': 'input'},
                },
            }
        )


def test_model_price_stores_dynamic_prices_as_attributes() -> None:
    price = ModelPrice(input_mtok=Decimal('1'))

    assert price.__dict__ == {'input_mtok': Decimal('1')}
    assert '_extra_prices' not in price.__dict__


def test_model_price_getattr_returns_none_for_absent_registered_price_keys() -> None:
    with _use_registry(_custom_price_key_units()):
        assert ModelPrice().sausage_mtok is None


def test_model_price_getattr_rejects_unknown_attributes() -> None:
    with pytest.raises(AttributeError, match='imaginary_price'):
        _ = ModelPrice().imaginary_price


def test_model_price_getattr_preserves_subclass_only_fields() -> None:
    class CustomModelPrice(ModelPrice):
        pass

    assert CustomModelPrice(sausage_price=Decimal('3')).sausage_price == Decimal('3')


def test_model_price_getattr_does_not_change_string_rendering() -> None:
    assert str(ModelPrice(input_mtok=Decimal('1'))) == '$1/input MTok'


def test_model_price_str_includes_dynamic_extras() -> None:
    price = ModelPrice(
        input_mtok=Decimal('1'),
        cache_image_read_mtok=Decimal('0.5'),
    )

    assert str(price) == '$1/input MTok, $0.5/cache image read MTok'


def test_collect_resolved_model_prices_handles_empty_price() -> None:
    registry = UnitRegistry(load_units())

    assert _collect_resolved_model_prices(ModelPrice(), registry) == ()


def test_collect_resolved_model_prices_retains_units_and_current_values() -> None:
    registry = UnitRegistry(load_units())

    resolved_prices = _collect_resolved_model_prices(
        ModelPrice(input_mtok=Decimal('1'), output_mtok=Decimal('2')),
        registry,
    )

    assert resolved_prices == (
        (registry.units['input_tokens'], Decimal('1')),
        (registry.units['output_tokens'], Decimal('2')),
    )


def test_collect_resolved_model_prices_handles_dynamic_registered_price() -> None:
    registry = UnitRegistry(load_units())

    assert _collect_resolved_model_prices(ModelPrice(cache_image_read_mtok=Decimal('0.5')), registry) == (
        (registry.units['cache_image_read_tokens'], Decimal('0.5')),
    )


def test_collect_resolved_model_prices_ignores_none_values() -> None:
    registry = UnitRegistry(load_units())

    assert _collect_resolved_model_prices(ModelPrice(input_mtok=None), registry) == ()


def test_collect_resolved_model_prices_warns_and_ignores_unknown_base_price() -> None:
    registry = UnitRegistry(load_units())

    with pytest.warns(UserWarning, match='Unsupported price key for standard pricing: hovercraft_mtok'):
        resolved_prices = _collect_resolved_model_prices(ModelPrice(hovercraft_mtok=Decimal('1')), registry)

    assert resolved_prices == ()


def test_collect_resolved_model_prices_handles_request_price() -> None:
    registry = UnitRegistry(load_units())

    assert _collect_resolved_model_prices(ModelPrice(requests_kcount=Decimal('3')), registry) == (
        (registry.units['requests'], Decimal('3')),
    )


def test_collect_resolved_model_prices_retains_tiered_price() -> None:
    registry = UnitRegistry(load_units())
    tiered_price = TieredPrices(base=Decimal('1'), tiers=[])

    assert _collect_resolved_model_prices(ModelPrice(input_mtok=tiered_price), registry) == (
        (registry.units['input_tokens'], tiered_price),
    )


def test_collect_resolved_model_prices_includes_registered_subclass_price() -> None:
    registry = _custom_price_key_registry()

    class CustomModelPrice(ModelPrice):
        pass

    assert _collect_resolved_model_prices(CustomModelPrice(sausage_mtok=Decimal('2')), registry) == (
        (registry.units['sausage_tokens'], Decimal('2')),
    )


def test_collect_resolved_model_prices_excludes_subclass_only_state() -> None:
    registry = UnitRegistry(load_units())

    class CustomModelPrice(ModelPrice):
        pass

    assert _collect_resolved_model_prices(
        CustomModelPrice(input_mtok=Decimal('1'), sausage_price=Decimal('2')),
        registry,
    ) == ((registry.units['input_tokens'], Decimal('1')),)


def test_compute_registry_priced_counts_handles_parent_child_token_counts() -> None:
    registry = UnitRegistry(load_units())
    resolved_prices = _collect_resolved_model_prices(
        ModelPrice(input_mtok=Decimal('1'), cache_read_mtok=Decimal('2')), registry
    )

    assert _compute_registry_priced_counts(
        resolved_prices,
        Usage(input_tokens=1_000, cache_read_tokens=250),
    ) == {'cache_read_tokens': 250, 'input_tokens': 750}


def test_compute_registry_priced_counts_handles_cached_audio_overlap() -> None:
    registry = UnitRegistry(load_units())
    resolved_prices = _collect_resolved_model_prices(
        ModelPrice(
            input_mtok=Decimal('1'),
            cache_read_mtok=Decimal('2'),
            input_audio_mtok=Decimal('3'),
            cache_audio_read_mtok=Decimal('4'),
        ),
        registry,
    )

    assert _compute_registry_priced_counts(
        resolved_prices,
        Usage(
            input_tokens=1_000,
            cache_read_tokens=400,
            input_audio_tokens=300,
            cache_audio_read_tokens=100,
        ),
    ) == {
        'cache_audio_read_tokens': 100,
        'cache_read_tokens': 300,
        'input_audio_tokens': 200,
        'input_tokens': 400,
    }


def test_compute_registry_priced_counts_handles_one_request_count() -> None:
    registry = UnitRegistry(load_units())
    resolved_prices = _collect_resolved_model_prices(ModelPrice(requests_kcount=Decimal('1')), registry)

    assert _compute_registry_priced_counts(resolved_prices, Usage()) == {'requests': 1}


def test_compute_registry_priced_counts_does_not_add_token_counts_for_request_only_prices() -> None:
    registry = UnitRegistry(load_units())
    resolved_prices = _collect_resolved_model_prices(ModelPrice(requests_kcount=Decimal('1')), registry)

    assert set(_compute_registry_priced_counts(resolved_prices, Usage(input_tokens=100))) == {'requests'}


def test_model_price_calculation_resolves_each_stored_price_once(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = UnitRegistry(load_units())
    unit_lookup = Mock(wraps=registry.unit_for_price_key)
    monkeypatch.setattr(registry, 'unit_for_price_key', unit_lookup)

    with patch('genai_prices.units._get_registry', return_value=registry):
        assert ModelPrice(input_mtok=Decimal('2')).calc_price(Usage(input_tokens=1_000_000)) == {
            'input_price': Decimal('2'),
            'output_price': Decimal('0'),
            'total_price': Decimal('2'),
        }

    unit_lookup.assert_called_once_with('input_mtok')
