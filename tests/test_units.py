from __future__ import annotations

import ast
import json
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import fields
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock, patch

import pytest

from genai_prices import calc_price, data, data_units
from genai_prices.data_snapshot import DataSnapshot, get_snapshot, set_custom_snapshot
from genai_prices.types import (
    ClauseEquals,
    ModelInfo,
    ModelPrice,
    Provider,
    TieredPrices,
    Usage,
    _collect_resolved_model_prices,
    _compute_registry_priced_counts,
)
from genai_prices.units import UnitRegistry, _get_registry
from prices import build as build_module, export_validation, package_data, prices_types as build_types
from prices.export_validation import validate_export_payload, validate_units

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
}


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

    assert set(raw_units) == TOKEN_USAGE_KEYS | {'requests'}

    token_units = {usage_key: raw_units[usage_key] for usage_key in TOKEN_USAGE_KEYS}
    assert {unit['per'] for unit in token_units.values()} == {1_000_000}
    assert {unit['dimensions']['family'] for unit in token_units.values()} == {'tokens'}
    assert {unit['price_key'] for unit in token_units.values()} == TOKEN_PRICE_KEYS

    request_unit = raw_units['requests']
    assert request_unit['per'] == 1_000
    assert request_unit['dimensions'] == {'family': 'requests'}
    assert request_unit['price_key'] == 'requests_kcount'


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
        cache = dimensions.get('cache')
        modality = dimensions.get('modality')
        if cache is None:
            expected_stem = f'{direction}_{modality}' if modality is not None else direction
        else:
            expected_stem = f'cache_{modality}_{cache}' if modality is not None else f'cache_{cache}'

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


def test_unit_registry_constructs_current_units() -> None:
    registry = UnitRegistry(load_units())

    assert set(registry.units) == TOKEN_USAGE_KEYS | {'requests'}
    assert len(registry.units) == 21
    assert registry.all_usage_keys == frozenset(TOKEN_USAGE_KEYS | {'requests'})
    assert registry.all_price_keys == frozenset(TOKEN_PRICE_KEYS | {'requests_kcount'})
    assert registry.unit_for_price_key('input_mtok') is registry.units['input_tokens']
    assert registry.unit_for_price_key('cache_image_write_mtok').usage_key == 'cache_image_write_tokens'
    assert registry.unit_for_price_key('requests_kcount') is registry.units['requests']


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


def test_unit_registry_indexes_ancestor_usage_keys() -> None:
    registry = UnitRegistry(load_units())

    assert registry._ancestor_usage_keys['cache_audio_read_tokens'] == frozenset(
        {'input_tokens', 'cache_read_tokens', 'input_audio_tokens'}
    )
    assert registry._ancestor_usage_keys['requests'] == frozenset()


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


def test_unit_registry_join_lookup_returns_registered_overlap() -> None:
    registry = UnitRegistry(load_units())

    assert (
        registry.find_join(registry.units['cache_read_tokens'], registry.units['input_audio_tokens'])
        is registry.units['cache_audio_read_tokens']
    )


def test_unit_registry_join_lookup_returns_descendant_for_parent_child_pair() -> None:
    registry = UnitRegistry(load_units())

    assert (
        registry.find_join(registry.units['input_tokens'], registry.units['cache_audio_read_tokens'])
        is registry.units['cache_audio_read_tokens']
    )


def test_unit_registry_join_lookup_returns_none_for_incompatible_units() -> None:
    registry = UnitRegistry(load_units())

    assert registry.find_join(registry.units['input_tokens'], registry.units['output_tokens']) is None


def test_unit_registry_join_lookup_returns_registered_cache_write_overlap() -> None:
    registry = UnitRegistry(load_units())

    assert (
        registry.find_join(registry.units['cache_write_tokens'], registry.units['input_audio_tokens'])
        is registry.units['cache_audio_write_tokens']
    )


def test_unit_registry_reported_usage_keys_include_public_token_keys() -> None:
    registry = UnitRegistry(load_units())

    assert registry.reported_usage_keys == frozenset(TOKEN_USAGE_KEYS)


def test_unit_registry_reported_usage_keys_exclude_pricing_only_requests() -> None:
    registry = UnitRegistry(load_units())

    assert 'requests' not in registry.reported_usage_keys


def test_unit_registry_key_indexes_are_immutable_and_reused() -> None:
    raw_units = load_units()
    registry = UnitRegistry(raw_units)

    assert isinstance(registry.all_usage_keys, frozenset)
    assert isinstance(registry.all_price_keys, frozenset)
    assert isinstance(registry.reported_usage_keys, frozenset)
    assert isinstance(registry.reported_usage_keys_in_order, tuple)
    assert registry.reported_usage_keys_in_order == tuple(key for key in raw_units if key != 'requests')
    assert registry.reported_usage_keys is registry.reported_usage_keys
    assert registry.reported_usage_keys_in_order is registry.reported_usage_keys_in_order


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


def test_validate_units_accepts_bundled_units() -> None:
    registry = validate_units(load_units())

    assert registry.units['cache_audio_read_tokens'].dimensions == {
        'family': 'tokens',
        'direction': 'input',
        'modality': 'audio',
        'cache': 'read',
    }


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


def test_model_price_str_includes_unregistered_candidate_keys() -> None:
    assert str(ModelPrice(hovercraft_mtok=Decimal('1'))) == '$1/hovercraft MTok'


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


def test_collect_resolved_model_prices_rejects_unknown_base_price() -> None:
    registry = UnitRegistry(load_units())

    with pytest.raises(ValueError, match='Unknown price key: hovercraft_mtok'):
        _collect_resolved_model_prices(ModelPrice(hovercraft_mtok=Decimal('1')), registry)


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


def test_build_loads_units() -> None:
    assert set(build_module.load_units()) == TOKEN_USAGE_KEYS | {'requests'}


def test_package_data_surfaces_registry_structural_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / 'units.yml').write_text(
        """\
input_tokens:
  per: 1_000_000
  price_key: input_mtok
  dimensions: {family: tokens, direction: input}
prompt_tokens:
  per: 1_000_000
  price_key: prompt_mtok
  dimensions: {family: tokens, direction: input}
"""
    )
    monkeypatch.setattr(build_module, 'package_dir', tmp_path)

    with pytest.raises(
        ValueError,
        match='Duplicate unit dimensions: input_tokens and prompt_tokens',
    ):
        package_data.load_unit_registry(build_module.load_units())


def test_package_data_load_unit_registry_delegates_to_export_validator(monkeypatch: pytest.MonkeyPatch) -> None:
    raw_units: dict[str, Any] = {
        'widgets': {
            'per': 1_000_000,
            'dimensions': {'family': 'widgets'},
        }
    }
    expected_registry = UnitRegistry(raw_units)
    calls: list[dict[str, Any]] = []

    def validate(raw_units_arg: dict[str, Any]) -> UnitRegistry:
        calls.append(raw_units_arg)
        return expected_registry

    monkeypatch.setattr(export_validation, 'validate_units', validate)

    assert package_data.load_unit_registry(raw_units) is expected_registry
    assert calls == [raw_units]


def test_runtime_packages_do_not_define_unit_publication_validators() -> None:
    runtime_files = [
        *Path('packages/python/genai_prices').glob('*.py'),
        *Path('packages/js/src').glob('*.ts'),
    ]
    forbidden_terms = {'validate_units', 'validateUnits'}
    references = {
        str(path): sorted(term for term in forbidden_terms if term in path.read_text()) for path in runtime_files
    }

    assert {path: terms for path, terms in references.items() if terms} == {}


def test_package_generation_no_longer_reloads_units_yml() -> None:
    references = {
        path
        for path in Path('prices/src/prices').glob('*.py')
        if path.name != 'build.py' and 'units.yml' in path.read_text()
    }

    assert references == set()


def test_package_provider_data_rejects_non_array_root(tmp_path: Path) -> None:
    data_path = tmp_path / 'data_v2.json'
    data_path.write_text('{"providers": []}')

    with pytest.raises(ValueError, match=r'Expected .* to contain a provider array'):
        package_data._load_provider_data(data_path)


def test_package_data_loads_providers_and_units_independently(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    provider_data: list[package_data.JsonData] = [{'id': 'testing', 'name': 'Testing', 'models': []}]
    units: dict[str, Any] = {
        'widgets': {
            'per': 1_000,
            'dimensions': {'family': 'widgets'},
        }
    }
    (tmp_path / 'data_v2.json').write_text(json.dumps(provider_data))
    calls: list[tuple[str, list[package_data.JsonData], dict[str, Any]]] = []

    def generate_python(providers: list[package_data.JsonData], raw_units: dict[str, Any]) -> None:
        calls.append(('python', providers, raw_units))

    def generate_typescript(providers: list[package_data.JsonData], raw_units: dict[str, Any]) -> None:
        calls.append(('typescript', providers, raw_units))

    monkeypatch.setattr(package_data, 'this_package_dir', tmp_path)
    monkeypatch.setattr(package_data, 'load_units', lambda: units)
    monkeypatch.setattr(package_data, 'package_python_data', generate_python)
    monkeypatch.setattr(package_data, 'package_ts_data', generate_typescript)

    package_data.package_data()

    assert calls == [
        ('python', provider_data, units),
        ('typescript', provider_data, units),
    ]


def test_package_data_accepts_valid_provider_model_prices() -> None:
    registry = UnitRegistry(load_units())
    provider = _build_provider_prices(
        build_types.ModelPrice(input_mtok=Decimal('1'), cache_read_mtok=Decimal('0.5'), requests_kcount=Decimal('1'))
    )

    package_data.validate_provider_model_prices([provider], registry)


def test_validate_export_payload_returns_validated_unit_registry() -> None:
    registry = validate_export_payload(
        [_build_provider_prices(build_types.ModelPrice(input_mtok=Decimal('1')))],
        load_units(),
    )

    assert isinstance(registry, UnitRegistry)
    assert registry.unit_for_price_key('cache_image_write_mtok').usage_key == 'cache_image_write_tokens'


def test_validate_export_payload_rejects_unknown_price_key() -> None:
    provider = _build_provider_prices(
        build_types.ModelPrice.model_validate({'hovercraft_mtok': '1'}),
        model_id='unknown-extra-price',
    )

    with pytest.raises(
        ValueError,
        match='Invalid model price for testing/unknown-extra-price: Unknown price key: hovercraft_mtok',
    ):
        validate_export_payload([provider], load_units())


def test_validate_export_payload_rejects_unknown_extractor_destination() -> None:
    provider = _build_provider_prices(
        build_types.ModelPrice(input_mtok=Decimal('1')),
        extractors=[_build_extractor('imaginary_tokens')],
    )

    with pytest.raises(
        ValueError,
        match='Invalid extractor destination for testing/default: Invalid extractor destination: imaginary_tokens',
    ):
        validate_export_payload([provider], load_units())


def test_validate_export_payload_rejects_missing_dynamic_price_ancestor() -> None:
    provider = _build_provider_prices(
        build_types.ModelPrice.model_validate({'cache_image_write_mtok': '1'}),
        model_id='missing-dynamic-ancestor',
    )

    with pytest.raises(
        ValueError,
        match='Invalid model price for testing/missing-dynamic-ancestor: Missing ancestor price for cache_image_write_tokens',
    ):
        validate_export_payload([provider], load_units())


def test_build_propagates_export_payload_validator_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    from prices import build as build_module

    class ExportValidationError(ValueError):
        pass

    def fail_export_validation(_providers: list[build_types.Provider], _units: dict[str, Any]) -> UnitRegistry:
        raise ExportValidationError('sentinel export validation failure')

    monkeypatch.setattr(build_module, 'validate_export_payload', fail_export_validation)

    with pytest.raises(ExportValidationError, match='sentinel export validation failure'):
        build_module.build()


def test_build_writes_only_v2_price_artifacts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    providers_dir = tmp_path / 'providers'
    providers_dir.mkdir()
    writes: list[str] = []

    def record_write(_providers: list[build_types.Provider], _units: dict[str, Any], filename: str) -> None:
        writes.append(filename)

    monkeypatch.setattr(build_module, 'package_dir', tmp_path)
    monkeypatch.setattr(build_module, 'root_dir', tmp_path)
    monkeypatch.setattr(build_module, 'load_units', load_units)
    monkeypatch.setattr(build_module, 'write_prices', record_write)

    build_module.build()

    assert writes == ['data_v2.json']


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


def test_package_ts_data_accepts_separated_inputs_without_units_yml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    units = {
        'input_tokens': {
            'per': 1_000_000,
            'price_key': 'input_mtok',
            'dimensions': {'family': 'tokens', 'direction': 'input'},
        },
    }
    provider = _build_provider_prices(build_types.ModelPrice(input_mtok=Decimal('1')))
    provider_data = build_types.providers_schema.dump_python(
        [provider],
        mode='json',
        by_alias=True,
        exclude_none=True,
        warnings=False,
    )

    js_src_dir = tmp_path / 'packages' / 'js' / 'src'
    js_src_dir.mkdir(parents=True)
    monkeypatch.setattr(package_data, 'root_dir', tmp_path)

    def skip_prettier(
        args: list[str],
        *,
        cwd: str | None = None,
        check: bool = False,
        stdout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        _ = cwd, check, stdout
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, 'run', skip_prettier)

    package_data.package_ts_data(provider_data, units)

    assert (js_src_dir / 'data.ts').exists()
    unit_data_content = (js_src_dir / 'dataUnits.ts').read_text()
    generated_json = unit_data_content.split('export const unitData: RawUnitsDict = ', 1)[1].removesuffix(';\n')
    assert json.loads(generated_json) == units


def test_build_model_price_accepts_typed_extra_price_keys() -> None:
    price = build_types.ModelPrice.model_validate({'input_mtok': '1.0', 'cache_image_write_mtok': '0.5'})

    assert price.input_mtok == Decimal('1.0')
    assert price.model_extra == {'cache_image_write_mtok': Decimal('0.5')}
    assert package_data._collect_model_price_keys(price) == {'input_mtok', 'cache_image_write_mtok'}


def test_runtime_model_price_repr_preserves_dynamic_price_keys() -> None:
    price = ModelPrice(input_mtok=Decimal('2'), output_image_mtok=Decimal('120'))

    assert repr(price) == "ModelPrice(input_mtok=Decimal('2'), output_image_mtok=Decimal('120'))"


def test_build_model_price_extras_affect_is_free() -> None:
    assert not build_types.ModelPrice.model_validate({'cache_image_write_mtok': '0.5'}).is_free()
    assert build_types.ModelPrice().is_free()


def test_extras_only_paid_model_survives_slim_filtering() -> None:
    provider = _build_provider_prices(
        build_types.ModelPrice.model_validate({'cache_image_write_mtok': '0.5'}),
        model_id='extras-only-paid',
    )

    provider.exclude_free()

    assert [model.id for model in provider.models] == ['extras-only-paid']


def test_package_data_validates_conditional_model_prices() -> None:
    registry = UnitRegistry(load_units())
    provider = _build_provider_prices(
        [build_types.ConditionalPrice(prices=build_types.ModelPrice(input_mtok=Decimal('1'), output_mtok=Decimal('2')))]
    )

    package_data.validate_provider_model_prices([provider], registry)


def test_package_data_model_price_validation_rejects_unknown_price_keys() -> None:
    registry = UnitRegistry(
        {
            'input_tokens': {
                'per': 1_000_000,
                'price_key': 'input_mtok',
                'dimensions': {'family': 'tokens', 'direction': 'input'},
            },
        }
    )
    provider = _build_provider_prices(build_types.ModelPrice(output_mtok=Decimal('1')), model_id='unknown-price')

    with pytest.raises(
        ValueError, match='Invalid model price for testing/unknown-price: Unknown price key: output_mtok'
    ):
        package_data.validate_provider_model_prices([provider], registry)


def test_package_data_model_price_validation_rejects_missing_ancestors() -> None:
    registry = UnitRegistry(load_units())
    provider = _build_provider_prices(build_types.ModelPrice(cache_read_mtok=Decimal('1')), model_id='missing-ancestor')

    with pytest.raises(
        ValueError,
        match='Invalid model price for testing/missing-ancestor: Missing ancestor price for cache_read_tokens',
    ):
        package_data.validate_provider_model_prices([provider], registry)


def test_package_data_model_price_validation_rejects_required_joins() -> None:
    registry = UnitRegistry(load_units())
    provider = _build_provider_prices(
        build_types.ModelPrice(
            input_mtok=Decimal('1'),
            cache_read_mtok=Decimal('0.5'),
            input_audio_mtok=Decimal('2'),
        ),
        model_id='missing-join-price',
    )

    with pytest.raises(
        ValueError,
        match='Invalid model price for testing/missing-join-price: Missing join price for cache_read_tokens',
    ):
        package_data.validate_provider_model_prices([provider], registry)


def test_package_data_model_price_validation_rejects_missing_join_units_for_conditional_prices() -> None:
    registry = UnitRegistry(
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
    provider = _build_provider_prices(
        [
            build_types.ConditionalPrice(
                prices=build_types.ModelPrice(
                    input_mtok=Decimal('1'),
                    cache_write_mtok=Decimal('0.5'),
                    input_audio_mtok=Decimal('2'),
                )
            )
        ],
        model_id='missing-join-unit',
    )

    with pytest.raises(
        ValueError,
        match=(
            'Invalid model price for testing/missing-join-unit\\[0\\]: '
            'Missing registered join unit for priced units cache_write_tokens and input_audio_tokens'
        ),
    ):
        package_data.validate_provider_model_prices([provider], registry)


def test_package_data_accepts_current_provider_extractor_destinations() -> None:
    registry = UnitRegistry(load_units())

    package_data.validate_provider_extractor_destinations(data.providers, registry)


def test_package_data_accepts_valid_synthetic_extractor_destinations() -> None:
    registry = UnitRegistry(load_units())
    provider = _build_provider_prices(
        build_types.ModelPrice(input_mtok=Decimal('1')),
        extractors=[_build_extractor('input_tokens')],
    )

    package_data.validate_provider_extractor_destinations([provider], registry)


def test_build_extractor_mapping_accepts_arbitrary_destinations_at_model_layer() -> None:
    mapping = build_types.UsageExtractorMapping.model_validate({'path': 'value', 'dest': 'weird_unit'})

    assert mapping.dest == 'weird_unit'


def test_build_extractor_mapping_still_accepts_known_destinations() -> None:
    mapping = build_types.UsageExtractorMapping.model_validate({'path': 'value', 'dest': 'input_tokens'})

    assert mapping.dest == 'input_tokens'


def test_package_data_extractor_validation_rejects_price_keys() -> None:
    registry = UnitRegistry(load_units())
    provider = _build_provider_prices(
        build_types.ModelPrice(input_mtok=Decimal('1')),
        extractors=[_build_extractor('input_mtok')],
    )

    with pytest.raises(
        ValueError,
        match='Invalid extractor destination for testing/default: Invalid extractor destination: input_mtok',
    ):
        package_data.validate_provider_extractor_destinations([provider], registry)


def test_package_data_extractor_validation_rejects_unknown_destinations() -> None:
    registry = UnitRegistry(load_units())
    provider = _build_provider_prices(
        build_types.ModelPrice(input_mtok=Decimal('1')),
        extractors=[_build_extractor('imaginary_tokens')],
    )

    with pytest.raises(
        ValueError,
        match='Invalid extractor destination for testing/default: Invalid extractor destination: imaginary_tokens',
    ):
        package_data.validate_provider_extractor_destinations([provider], registry)


def test_package_data_extractor_validation_rejects_pricing_only_requests() -> None:
    registry = UnitRegistry(load_units())
    provider = _build_provider_prices(
        build_types.ModelPrice(input_mtok=Decimal('1')),
        extractors=[_build_extractor('requests')],
    )

    with pytest.raises(
        ValueError,
        match='Invalid extractor destination for testing/default: Invalid extractor destination: requests',
    ):
        package_data.validate_provider_extractor_destinations([provider], registry)


def test_package_data_extractor_validation_reports_multiple_invalid_destinations() -> None:
    registry = UnitRegistry(load_units())
    provider = _build_provider_prices(
        build_types.ModelPrice(input_mtok=Decimal('1')),
        extractors=[
            build_types.UsageExtractor.model_construct(
                root='usage',
                mappings=[
                    _build_extractor_mapping('prompt_tokens', 'input_mtok'),
                    _build_extractor_mapping('requests', 'requests'),
                ],
                api_flavor='default',
                model_path='model',
            )
        ],
    )

    with pytest.raises(
        ValueError,
        match='Invalid extractor destination for testing/default: Invalid extractor destination: input_mtok, requests',
    ):
        package_data.validate_provider_extractor_destinations([provider], registry)


def test_generated_python_unit_data_builds_registry() -> None:
    registry = UnitRegistry(data_units.unit_data)

    assert set(registry.units) == TOKEN_USAGE_KEYS | {'requests'}
    assert len(registry.units) == 21
    assert registry.unit_for_price_key('cache_image_write_mtok').usage_key == 'cache_image_write_tokens'


@pytest.mark.parametrize('filename', ['prices/data.json', 'prices/data_slim.json'])
def test_v1_remote_payload_roots_are_provider_arrays(filename: str) -> None:
    payload_obj = json.loads((Path(__file__).parent.parent / filename).read_text())

    assert isinstance(payload_obj, list)
    providers = cast(list[object], payload_obj)
    assert providers
    assert all(isinstance(provider, dict) for provider in providers)


def test_data_snapshot_has_no_unit_registry_field() -> None:
    snapshot = get_snapshot()

    assert 'unit_registry' not in {field.name for field in fields(DataSnapshot)}
    assert not hasattr(snapshot, 'unit_registry')


def test_bundled_snapshot_lookup_helpers_still_work() -> None:
    snapshot = get_snapshot()

    provider, model = snapshot.find_provider_model('gpt-4o-mini', None, 'openai', None)

    assert provider.id == 'openai'
    assert model.id == 'gpt-4o-mini'


def test_get_registry_returns_generated_unit_data_registry() -> None:
    registry = _get_registry()

    assert isinstance(registry, UnitRegistry)
    assert set(registry.units) == set(data_units.unit_data)
    assert registry.unit_for_price_key('input_mtok').usage_key == 'input_tokens'
    assert _get_registry() is registry


def test_constructed_registry_is_independent_from_bundled_singleton() -> None:
    bundled = _get_registry()
    custom = _custom_price_key_registry()

    assert custom is not bundled
    assert custom.units != bundled.units
    assert _get_registry() is bundled


def test_get_registry_does_not_call_data_snapshot_get_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_get_snapshot() -> None:
        raise AssertionError('get_snapshot should not be called')  # pragma: no cover

    monkeypatch.setattr('genai_prices.data_snapshot.get_snapshot', fail_get_snapshot)
    registry = _get_registry()

    assert isinstance(registry, UnitRegistry)


def test_unit_registry_construction_avoids_active_snapshot_import_cycle() -> None:
    subprocess.run(
        [
            sys.executable,
            '-c',
            (
                'from genai_prices.units import UnitRegistry; '
                "UnitRegistry({'widgets': {'per': 1, 'dimensions': {'family': 'widgets'}}})"
            ),
        ],
        check=True,
    )


def test_custom_snapshots_do_not_carry_a_registry() -> None:
    snapshot = DataSnapshot(providers=data.providers, from_auto_update=False)

    assert not hasattr(snapshot, 'unit_registry')


def test_set_custom_snapshot_does_not_validate_model_prices() -> None:
    snapshot = DataSnapshot(providers=data.providers, from_auto_update=False)

    try:
        set_custom_snapshot(snapshot)
        assert get_snapshot() is snapshot
    finally:
        set_custom_snapshot(None)


def test_set_custom_snapshot_does_not_touch_bundled_registry() -> None:
    registry = _get_registry()
    snapshot = DataSnapshot(providers=data.providers, from_auto_update=False)

    try:
        set_custom_snapshot(snapshot)
        assert _get_registry() is registry

        set_custom_snapshot(None)
        assert _get_registry() is registry
    finally:
        set_custom_snapshot(None)


def test_model_price_validation_runs_on_base_calc_not_snapshot_activation() -> None:
    snapshot = DataSnapshot(
        providers=[
            Provider(
                id='testing',
                name='Testing',
                api_pattern='testing',
                models=[
                    ModelInfo(
                        id='bad-cache-price',
                        match=ClauseEquals('bad-cache-price'),
                        prices=ModelPrice(cache_read_mtok=Decimal('1')),
                    )
                ],
            )
        ],
        from_auto_update=False,
    )

    try:
        set_custom_snapshot(snapshot)
        assert get_snapshot() is snapshot

        with pytest.raises(ValueError, match='Missing ancestor price for cache_read_tokens: input_tokens'):
            calc_price(Usage(cache_read_tokens=100), model_ref='bad-cache-price', provider_id='testing')
    finally:
        set_custom_snapshot(None)


def test_inactive_snapshot_lookup_helpers_continue_to_work() -> None:
    snapshot = DataSnapshot(providers=data.providers, from_auto_update=False)

    provider, model = snapshot.find_provider_model('gpt-4o-mini', None, 'openai', None)

    assert provider.id == 'openai'
    assert model.id == 'gpt-4o-mini'
