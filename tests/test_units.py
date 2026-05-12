from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, fields
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest

from genai_prices import calc_price, data, data_units
from genai_prices.data_snapshot import DataSnapshot, get_snapshot, set_custom_snapshot
from genai_prices.types import (
    ClauseEquals,
    ModelInfo,
    ModelPrice,
    Provider,
    Usage,
    _collect_effective_model_price_keys,
    _compute_registry_priced_counts,
    _group_model_price_units_by_family,
)
from genai_prices.units import UnitDef, UnitFamily, UnitRegistry, _get_registry, _set_registry
from prices import package_data, prices_types as build_types
from prices.export_validation import validate_unit_families

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


def _custom_price_key_unit_families() -> dict[str, Any]:
    return {
        'tokens': {
            'per': 1_000_000,
            'units': {
                'input_tokens': {
                    'price_key': 'input_mtok',
                    'dimensions': {'direction': 'input'},
                },
                'sausage_tokens': {
                    'price_key': 'sausage_mtok',
                    'dimensions': {'direction': 'input', 'ingredient': 'sausage'},
                },
            },
        },
    }


def _custom_price_key_registry() -> UnitRegistry:
    return UnitRegistry(_custom_price_key_unit_families())


@contextmanager
def _active_registry(raw_families: dict[str, Any]) -> Iterator[UnitRegistry]:
    registry = UnitRegistry(raw_families)
    with patch('genai_prices.units._get_registry', return_value=registry):
        yield registry


def _usage_keys_by_family(groups: dict[UnitFamily, set[UnitDef]]) -> dict[str, set[str]]:
    return {family.id: {unit.usage_key for unit in units} for family, units in groups.items()}


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
    raw_families = load_units()

    assert set(raw_families) == {'tokens', 'requests'}

    token_family = raw_families['tokens']
    assert token_family['per'] == 1_000_000
    assert set(token_family['units']) == TOKEN_USAGE_KEYS
    assert {unit['price_key'] for unit in token_family['units'].values()} == TOKEN_PRICE_KEYS

    request_family = raw_families['requests']
    assert request_family['per'] == 1_000
    assert set(request_family['units']) == {'requests'}
    assert request_family['units']['requests']['price_key'] == 'requests_kcount'


def test_unit_registry_constructs_current_units() -> None:
    registry = UnitRegistry(load_units())

    assert set(registry.families) == {'tokens', 'requests'}
    assert set(registry.units) == TOKEN_USAGE_KEYS | {'requests'}
    assert len(registry.units) == 21
    assert registry.unit_for_price_key('input_mtok') is registry.units['input_tokens']
    assert registry.unit_for_price_key('cache_image_write_mtok').usage_key == 'cache_image_write_tokens'
    assert registry.unit_for_price_key('requests_kcount') is registry.units['requests']


def test_unit_registry_sets_family_and_unit_backrefs() -> None:
    registry = UnitRegistry(load_units())

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
    assert registry.unit_for_price_key('input_characters') is registry.units['input_characters']


def test_unit_registry_indexes_units_by_dimension_set() -> None:
    registry = UnitRegistry(load_units())

    token_units_by_dimension = registry.families['tokens'].units_by_dimension

    assert token_units_by_dimension[frozenset({('direction', 'input')})] is registry.units['input_tokens']
    assert (
        token_units_by_dimension[frozenset({('direction', 'input'), ('modality', 'audio')})]
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
    token_family = registry.families['tokens']

    assert (
        token_family.find_join(registry.units['cache_read_tokens'], registry.units['input_audio_tokens'])
        is registry.units['cache_audio_read_tokens']
    )


def test_unit_registry_join_lookup_returns_descendant_for_parent_child_pair() -> None:
    registry = UnitRegistry(load_units())
    token_family = registry.families['tokens']

    assert (
        token_family.find_join(registry.units['input_tokens'], registry.units['cache_audio_read_tokens'])
        is registry.units['cache_audio_read_tokens']
    )


def test_unit_registry_join_lookup_returns_none_for_incompatible_units() -> None:
    registry = UnitRegistry(load_units())

    assert (
        registry.families['tokens'].find_join(registry.units['input_tokens'], registry.units['output_tokens']) is None
    )


def test_unit_registry_join_lookup_returns_registered_cache_write_overlap() -> None:
    registry = UnitRegistry(load_units())

    assert (
        registry.families['tokens'].find_join(
            registry.units['cache_write_tokens'], registry.units['input_audio_tokens']
        )
        is registry.units['cache_audio_write_tokens']
    )


def test_unit_registry_reported_usage_keys_include_public_token_keys() -> None:
    registry = UnitRegistry(load_units())

    assert registry.reported_usage_keys() == frozenset(TOKEN_USAGE_KEYS)


def test_unit_registry_reported_usage_keys_exclude_pricing_only_requests() -> None:
    registry = UnitRegistry(load_units())

    assert 'requests' not in registry.reported_usage_keys()


def test_validate_unit_families_rejects_duplicate_usage_keys_across_families() -> None:
    with pytest.raises(ValueError, match='Duplicate unit usage key: input_tokens'):
        validate_unit_families(
            {
                'tokens': {
                    'per': 1_000_000,
                    'units': {
                        'input_tokens': {
                            'dimensions': {'direction': 'input'},
                        },
                    },
                },
                'characters': {
                    'per': 1_000,
                    'units': {
                        'input_tokens': {
                            'dimensions': {'direction': 'input'},
                        },
                    },
                },
            }
        )


def test_validate_unit_families_rejects_duplicate_price_keys() -> None:
    with pytest.raises(ValueError, match='Duplicate unit price key: input_mtok'):
        validate_unit_families(
            {
                'tokens': {
                    'per': 1_000_000,
                    'units': {
                        'input_tokens': {
                            'price_key': 'input_mtok',
                            'dimensions': {'direction': 'input'},
                        },
                        'input_audio_tokens': {
                            'price_key': 'input_mtok',
                            'dimensions': {'direction': 'input', 'modality': 'audio'},
                        },
                    },
                },
            }
        )


def test_validate_unit_families_rejects_duplicate_dimension_sets_within_family() -> None:
    with pytest.raises(
        ValueError,
        match='Duplicate dimensions in unit family tokens: input_tokens and prompt_tokens',
    ):
        validate_unit_families(
            {
                'tokens': {
                    'per': 1_000_000,
                    'units': {
                        'input_tokens': {
                            'price_key': 'input_mtok',
                            'dimensions': {'direction': 'input'},
                        },
                        'prompt_tokens': {
                            'price_key': 'prompt_mtok',
                            'dimensions': {'direction': 'input'},
                        },
                    },
                },
            }
        )


def test_unit_registry_allows_same_dimension_set_across_families() -> None:
    registry = UnitRegistry(
        {
            'tokens': {
                'per': 1_000_000,
                'units': {
                    'input_tokens': {
                        'price_key': 'input_mtok',
                        'dimensions': {'direction': 'input'},
                    },
                },
            },
            'characters': {
                'per': 1_000,
                'units': {
                    'input_characters': {
                        'price_key': 'input_kchar',
                        'dimensions': {'direction': 'input'},
                    },
                },
            },
        }
    )

    assert registry.units['input_tokens'].dimensions == registry.units['input_characters'].dimensions


def test_validate_unit_families_rejects_skipped_intermediate_dimension_sets() -> None:
    with pytest.raises(
        ValueError,
        match=(
            'Missing intermediate unit dimensions in family tokens between input_tokens and cache_video_read_tokens'
        ),
    ):
        validate_unit_families(
            {
                'tokens': {
                    'per': 1_000_000,
                    'units': {
                        'input_tokens': {
                            'price_key': 'input_mtok',
                            'dimensions': {'direction': 'input'},
                        },
                        'cache_read_tokens': {
                            'price_key': 'cache_read_mtok',
                            'dimensions': {'direction': 'input', 'cache': 'read'},
                        },
                        'cache_video_read_tokens': {
                            'price_key': 'cache_video_read_mtok',
                            'dimensions': {'direction': 'input', 'modality': 'video', 'cache': 'read'},
                        },
                    },
                },
            }
        )


def test_validate_unit_families_accepts_bundled_units() -> None:
    registry = validate_unit_families(load_units())

    assert registry.units['cache_audio_read_tokens'].dimensions == {
        'direction': 'input',
        'modality': 'audio',
        'cache': 'read',
    }


@pytest.mark.parametrize(
    ('usage_key', 'price_key', 'message'),
    [
        ('_private_name', 'private_mtok', "Invalid unit usage key: '_private_name' must not start"),
        ('class', 'class_mtok', "Invalid unit usage key: 'class' is a reserved keyword"),
        ('valid_usage', '_private_name', "Invalid unit price key: '_private_name' must not start"),
        ('valid_usage', 'class', "Invalid unit price key: 'class' is a reserved keyword"),
    ],
)
def test_validate_unit_families_rejects_unsafe_public_keys(usage_key: str, price_key: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        validate_unit_families(
            {
                'tokens': {
                    'per': 1_000_000,
                    'units': {
                        usage_key: {
                            'price_key': price_key,
                            'dimensions': {'direction': 'input'},
                        },
                    },
                },
            }
        )


def test_unit_registry_allows_compatible_pair_with_missing_join() -> None:
    registry = UnitRegistry(
        {
            'tokens': {
                'per': 1_000_000,
                'units': {
                    'input_tokens': {
                        'price_key': 'input_mtok',
                        'dimensions': {'direction': 'input'},
                    },
                    'cache_write_tokens': {
                        'price_key': 'cache_write_mtok',
                        'dimensions': {'direction': 'input', 'cache': 'write'},
                    },
                    'input_audio_tokens': {
                        'price_key': 'input_audio_mtok',
                        'dimensions': {'direction': 'input', 'modality': 'audio'},
                    },
                },
            },
        }
    )

    assert (
        registry.families['tokens'].find_join(
            registry.units['cache_write_tokens'], registry.units['input_audio_tokens']
        )
        is None
    )


def test_collect_effective_model_price_keys_reads_base_fields() -> None:
    registry = UnitRegistry(load_units())

    assert _collect_effective_model_price_keys(
        ModelPrice(input_mtok=Decimal('1'), output_mtok=Decimal('2')), registry
    ) == {'input_mtok', 'output_mtok'}


def test_collect_effective_model_price_keys_ignores_none_values() -> None:
    registry = UnitRegistry(load_units())

    assert _collect_effective_model_price_keys(ModelPrice(input_mtok=Decimal('1'), output_mtok=None), registry) == {
        'input_mtok'
    }


def test_collect_effective_model_price_keys_reads_registered_subclass_fields() -> None:
    registry = _custom_price_key_registry()

    @dataclass
    class CustomModelPrice(ModelPrice):
        sausage_mtok: Decimal | None = None
        sausage_price: Decimal | None = None

    price = CustomModelPrice(input_mtok=Decimal('1'), sausage_mtok=Decimal('2'), sausage_price=Decimal('3'))

    assert _collect_effective_model_price_keys(price, registry) == {'input_mtok', 'sausage_mtok'}


def test_model_price_getattr_returns_none_for_absent_registered_price_keys() -> None:
    with _active_registry(_custom_price_key_unit_families()):
        assert ModelPrice().sausage_mtok is None


def test_model_price_getattr_rejects_unknown_attributes() -> None:
    with pytest.raises(AttributeError, match='imaginary_price'):
        _ = ModelPrice().imaginary_price


def test_model_price_getattr_preserves_subclass_only_fields() -> None:
    @dataclass
    class CustomModelPrice(ModelPrice):
        sausage_price: Decimal | None = None

    assert CustomModelPrice(sausage_price=Decimal('3')).sausage_price == Decimal('3')


def test_model_price_getattr_does_not_change_string_rendering() -> None:
    assert str(ModelPrice(input_mtok=Decimal('1'))) == '$1/input MTok'


def test_group_model_price_units_by_family_handles_token_prices() -> None:
    registry = UnitRegistry(load_units())

    groups = _group_model_price_units_by_family(
        ModelPrice(input_mtok=Decimal('1'), cache_read_mtok=Decimal('2')), registry
    )

    assert _usage_keys_by_family(groups) == {'tokens': {'input_tokens', 'cache_read_tokens'}}


def test_group_model_price_units_by_family_handles_request_prices() -> None:
    registry = UnitRegistry(load_units())

    groups = _group_model_price_units_by_family(ModelPrice(requests_kcount=Decimal('1')), registry)

    assert _usage_keys_by_family(groups) == {'requests': {'requests'}}


def test_group_model_price_units_by_family_handles_mixed_families_in_field_order() -> None:
    registry = UnitRegistry(load_units())

    groups = _group_model_price_units_by_family(
        ModelPrice(input_mtok=Decimal('1'), requests_kcount=Decimal('2')), registry
    )

    assert list(groups) == [registry.families['tokens'], registry.families['requests']]
    assert _usage_keys_by_family(groups) == {'tokens': {'input_tokens'}, 'requests': {'requests'}}


def test_group_model_price_units_by_family_ignores_subclass_only_fields() -> None:
    registry = UnitRegistry(load_units())

    @dataclass
    class CustomModelPrice(ModelPrice):
        sausage_price: Decimal | None = None

    groups = _group_model_price_units_by_family(
        CustomModelPrice(input_mtok=Decimal('1'), sausage_price=Decimal('2')), registry
    )

    assert _usage_keys_by_family(groups) == {'tokens': {'input_tokens'}}


def test_group_model_price_units_by_family_handles_registered_custom_fields() -> None:
    registry = _custom_price_key_registry()

    @dataclass
    class CustomModelPrice(ModelPrice):
        sausage_mtok: Decimal | None = None

    groups = _group_model_price_units_by_family(
        CustomModelPrice(input_mtok=Decimal('1'), sausage_mtok=Decimal('2')), registry
    )

    assert list(groups) == [registry.families['tokens']]
    assert _usage_keys_by_family(groups) == {'tokens': {'input_tokens', 'sausage_tokens'}}


def test_compute_registry_priced_counts_handles_parent_child_token_counts() -> None:
    registry = UnitRegistry(load_units())
    grouped_units = _group_model_price_units_by_family(
        ModelPrice(input_mtok=Decimal('1'), cache_read_mtok=Decimal('2')), registry
    )

    assert _compute_registry_priced_counts(
        grouped_units,
        Usage(input_tokens=1_000, cache_read_tokens=250),
    ) == {'cache_read_tokens': 250, 'input_tokens': 750}


def test_compute_registry_priced_counts_handles_cached_audio_overlap() -> None:
    registry = UnitRegistry(load_units())
    grouped_units = _group_model_price_units_by_family(
        ModelPrice(
            input_mtok=Decimal('1'),
            cache_read_mtok=Decimal('2'),
            input_audio_mtok=Decimal('3'),
            cache_audio_read_mtok=Decimal('4'),
        ),
        registry,
    )

    assert _compute_registry_priced_counts(
        grouped_units,
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
    grouped_units = _group_model_price_units_by_family(ModelPrice(requests_kcount=Decimal('1')), registry)

    assert _compute_registry_priced_counts(grouped_units, Usage()) == {'requests': 1}


def test_compute_registry_priced_counts_does_not_add_token_counts_for_request_only_prices() -> None:
    registry = UnitRegistry(load_units())
    grouped_units = _group_model_price_units_by_family(ModelPrice(requests_kcount=Decimal('1')), registry)

    assert set(_compute_registry_priced_counts(grouped_units, Usage(input_tokens=100))) == {'requests'}


def test_package_data_loads_unit_families() -> None:
    assert set(package_data.load_unit_families()) == {'tokens', 'requests'}


def test_package_data_surfaces_registry_structural_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / 'units.yml').write_text(
        """\
tokens:
  per: 1_000_000
  units:
    input_tokens:
      price_key: input_mtok
      dimensions: {direction: input}
    prompt_tokens:
      price_key: prompt_mtok
      dimensions: {direction: input}
"""
    )
    monkeypatch.setattr(package_data, 'this_package_dir', tmp_path)

    with pytest.raises(
        ValueError,
        match='Duplicate dimensions in unit family tokens: input_tokens and prompt_tokens',
    ):
        package_data.load_unit_registry(package_data.load_unit_families())


def test_package_data_accepts_valid_provider_model_prices() -> None:
    registry = UnitRegistry(load_units())
    provider = _build_provider_prices(
        build_types.ModelPrice(input_mtok=Decimal('1'), cache_read_mtok=Decimal('0.5'), requests_kcount=Decimal('1'))
    )

    package_data.validate_provider_model_prices([provider], registry)


def test_package_data_validates_conditional_model_prices() -> None:
    registry = UnitRegistry(load_units())
    provider = _build_provider_prices(
        [build_types.ConditionalPrice(prices=build_types.ModelPrice(input_mtok=Decimal('1'), output_mtok=Decimal('2')))]
    )

    package_data.validate_provider_model_prices([provider], registry)


def test_package_data_model_price_validation_rejects_unknown_price_keys() -> None:
    registry = UnitRegistry(
        {
            'tokens': {
                'per': 1_000_000,
                'units': {
                    'input_tokens': {
                        'price_key': 'input_mtok',
                        'dimensions': {'direction': 'input'},
                    },
                },
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
            'tokens': {
                'per': 1_000_000,
                'units': {
                    'input_tokens': {
                        'price_key': 'input_mtok',
                        'dimensions': {'direction': 'input'},
                    },
                    'cache_write_tokens': {
                        'price_key': 'cache_write_mtok',
                        'dimensions': {'direction': 'input', 'cache': 'write'},
                    },
                    'input_audio_tokens': {
                        'price_key': 'input_audio_mtok',
                        'dimensions': {'direction': 'input', 'modality': 'audio'},
                    },
                },
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


def test_generated_python_unit_families_data_builds_registry() -> None:
    registry = UnitRegistry(data_units.unit_families_data)

    assert set(registry.families) == {'tokens', 'requests'}
    assert set(registry.units) == TOKEN_USAGE_KEYS | {'requests'}
    assert len(registry.units) == 21
    assert registry.unit_for_price_key('cache_image_write_mtok').usage_key == 'cache_image_write_tokens'


@pytest.mark.parametrize('filename', ['prices/data.json', 'prices/data_slim.json'])
def test_remote_payload_roots_remain_provider_arrays(filename: str) -> None:
    payload_obj = json.loads(Path(filename).read_text())

    assert isinstance(payload_obj, list)
    payload = cast(list[object], payload_obj)
    assert payload
    assert all(isinstance(provider, dict) for provider in payload)
    first_provider = cast(dict[str, object], payload[0])
    assert 'providers' not in first_provider
    assert 'unit_families' not in first_provider


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
    _set_registry(None)
    registry = _get_registry()

    assert isinstance(registry, UnitRegistry)
    assert set(registry.families) == set(data_units.unit_families_data)
    assert registry.unit_for_price_key('input_mtok').usage_key == 'input_tokens'
    assert _get_registry() is registry


def test_set_registry_swaps_and_restores_bundled_registry() -> None:
    _set_registry(None)
    bundled = _get_registry()
    custom = _custom_price_key_registry()

    try:
        _set_registry(custom)
        assert _get_registry() is custom

        _set_registry(None)
        assert _get_registry() is bundled
    finally:
        _set_registry(None)


def test_get_registry_does_not_call_data_snapshot_get_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_get_snapshot() -> None:
        raise AssertionError('get_snapshot should not be called')

    monkeypatch.setattr('genai_prices.data_snapshot.get_snapshot', fail_get_snapshot)
    _set_registry(None)
    registry = _get_registry()

    assert isinstance(registry, UnitRegistry)


def test_unit_registry_construction_avoids_active_snapshot_import_cycle() -> None:
    subprocess.run(
        [
            sys.executable,
            '-c',
            ("from genai_prices.units import UnitRegistry; UnitRegistry({'tokens': {'per': 1, 'units': {}}})"),
        ],
        check=True,
    )


def test_custom_snapshots_do_not_borrow_active_registry() -> None:
    snapshot = DataSnapshot(providers=data.providers, from_auto_update=False)

    assert not hasattr(snapshot, 'unit_registry')


def test_set_custom_snapshot_does_not_validate_model_prices() -> None:
    snapshot = DataSnapshot(providers=data.providers, from_auto_update=False)

    try:
        set_custom_snapshot(snapshot)
        assert get_snapshot() is snapshot
    finally:
        set_custom_snapshot(None)


def test_set_custom_snapshot_does_not_touch_active_registry_cache() -> None:
    _set_registry(None)
    registry = _get_registry()
    snapshot = DataSnapshot(providers=data.providers, from_auto_update=False)

    try:
        set_custom_snapshot(snapshot)
        assert _get_registry() is registry

        set_custom_snapshot(None)
        assert _get_registry() is registry
    finally:
        set_custom_snapshot(None)
        _set_registry(None)


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
