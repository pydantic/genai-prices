from pathlib import Path
from typing import Any, cast

import pytest
import ruamel.yaml

from genai_prices.units import UnitRegistry
from genai_prices.validation import validate_ancestor_coverage, validate_join_coverage, validate_price_keys


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


def test_unit_registry_indexes_units_by_dimension_set() -> None:
    registry = UnitRegistry(_load_units())

    token_units_by_dimension = registry._units_by_dimension['tokens']

    assert token_units_by_dimension[frozenset({('direction', 'input')})] is registry.units['input_tokens']
    assert (
        token_units_by_dimension[frozenset({('direction', 'input'), ('modality', 'audio')})]
        is registry.units['input_audio_tokens']
    )


def test_unit_registry_indexes_ancestor_usage_keys() -> None:
    registry = UnitRegistry(_load_units())

    assert registry._ancestor_usage_keys['cache_audio_read_tokens'] == frozenset(
        {'input_tokens', 'cache_read_tokens', 'input_audio_tokens'}
    )
    assert registry._ancestor_usage_keys['requests'] == frozenset()


def test_unit_registry_compatibility_rejects_cross_family_units() -> None:
    registry = UnitRegistry(_load_units())

    assert not UnitRegistry.are_compatible(registry.units['input_tokens'], registry.units['requests'])


def test_unit_registry_compatibility_rejects_conflicting_dimensions() -> None:
    registry = UnitRegistry(_load_units())

    assert not UnitRegistry.are_compatible(registry.units['input_tokens'], registry.units['output_tokens'])


def test_unit_registry_compatibility_accepts_parent_child_pairs() -> None:
    registry = UnitRegistry(_load_units())

    assert UnitRegistry.are_compatible(registry.units['input_tokens'], registry.units['cache_read_tokens'])
    assert UnitRegistry.are_compatible(registry.units['cache_read_tokens'], registry.units['input_tokens'])


def test_unit_registry_compatibility_accepts_overlapping_pairs() -> None:
    registry = UnitRegistry(_load_units())

    assert UnitRegistry.are_compatible(registry.units['cache_read_tokens'], registry.units['input_audio_tokens'])
    assert UnitRegistry.are_compatible(registry.units['input_audio_tokens'], registry.units['cache_read_tokens'])


def test_unit_registry_ancestor_helper_accepts_self() -> None:
    registry = UnitRegistry(_load_units())

    assert UnitRegistry.is_ancestor_or_self(registry.units['input_tokens'], registry.units['input_tokens'])


def test_unit_registry_ancestor_helper_accepts_parent_child_pairs() -> None:
    registry = UnitRegistry(_load_units())

    assert UnitRegistry.is_ancestor_or_self(registry.units['input_tokens'], registry.units['cache_read_tokens'])
    assert not UnitRegistry.is_ancestor_or_self(registry.units['cache_read_tokens'], registry.units['input_tokens'])


def test_unit_registry_ancestor_helper_rejects_siblings() -> None:
    registry = UnitRegistry(_load_units())

    assert not UnitRegistry.is_ancestor_or_self(
        registry.units['cache_read_tokens'], registry.units['input_audio_tokens']
    )


def test_unit_registry_ancestor_helper_rejects_incompatible_units() -> None:
    registry = UnitRegistry(_load_units())

    assert not UnitRegistry.is_ancestor_or_self(registry.units['input_tokens'], registry.units['output_tokens'])


def test_unit_registry_ancestor_helper_rejects_cross_family_units() -> None:
    registry = UnitRegistry(_load_units())

    assert not UnitRegistry.is_ancestor_or_self(registry.units['requests'], registry.units['input_tokens'])


def test_unit_registry_join_lookup_returns_registered_overlap() -> None:
    registry = UnitRegistry(_load_units())

    assert (
        registry.find_join(registry.units['cache_read_tokens'], registry.units['input_audio_tokens'])
        is registry.units['cache_audio_read_tokens']
    )


def test_unit_registry_join_lookup_returns_descendant_for_parent_child_pair() -> None:
    registry = UnitRegistry(_load_units())

    assert (
        registry.find_join(registry.units['input_tokens'], registry.units['cache_audio_read_tokens'])
        is registry.units['cache_audio_read_tokens']
    )


def test_unit_registry_join_lookup_returns_none_for_incompatible_units() -> None:
    registry = UnitRegistry(_load_units())

    assert registry.find_join(registry.units['input_tokens'], registry.units['output_tokens']) is None


def test_unit_registry_join_lookup_returns_none_for_missing_compatible_join() -> None:
    registry = UnitRegistry(_load_units())

    assert registry.find_join(registry.units['cache_write_tokens'], registry.units['input_audio_tokens']) is None


def test_unit_registry_reported_usage_keys_include_public_token_keys() -> None:
    registry = UnitRegistry(_load_units())

    assert registry.reported_usage_keys() == frozenset(
        {
            'input_tokens',
            'output_tokens',
            'cache_read_tokens',
            'cache_write_tokens',
            'input_audio_tokens',
            'cache_audio_read_tokens',
            'output_audio_tokens',
        }
    )


def test_unit_registry_reported_usage_keys_exclude_pricing_only_requests() -> None:
    registry = UnitRegistry(_load_units())

    assert 'requests' not in registry.reported_usage_keys()


def test_unit_registry_rejects_duplicate_usage_keys_across_families() -> None:
    with pytest.raises(ValueError, match='Duplicate unit usage key: input_tokens'):
        UnitRegistry(
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


def test_unit_registry_rejects_duplicate_price_keys() -> None:
    with pytest.raises(ValueError, match='Duplicate unit price key: input_mtok'):
        UnitRegistry(
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


def test_unit_registry_rejects_duplicate_dimension_sets_within_family() -> None:
    with pytest.raises(
        ValueError,
        match='Duplicate dimensions in unit family tokens: input_tokens and prompt_tokens',
    ):
        UnitRegistry(
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


def test_unit_registry_rejects_skipped_intermediate_dimension_sets() -> None:
    with pytest.raises(
        ValueError,
        match=(
            'Missing intermediate unit dimensions in family tokens between input_tokens and cache_video_read_tokens'
        ),
    ):
        UnitRegistry(
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


def test_unit_registry_current_token_subset_satisfies_interval_closure() -> None:
    registry = UnitRegistry(_load_units())

    assert registry.units['cache_audio_read_tokens'].dimensions == {
        'direction': 'input',
        'modality': 'audio',
        'cache': 'read',
    }


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

    assert registry.find_join(registry.units['cache_write_tokens'], registry.units['input_audio_tokens']) is None


def test_validate_price_keys_accepts_current_price_keys() -> None:
    registry = UnitRegistry(_load_units())

    validate_price_keys(set(registry.price_keys), registry.price_keys)


def test_validate_price_keys_rejects_unknown_price_key() -> None:
    registry = UnitRegistry(_load_units())

    with pytest.raises(ValueError, match='Unknown price key: inptu_mtok'):
        validate_price_keys({'input_mtok', 'inptu_mtok'}, registry.price_keys)


def test_validate_ancestor_coverage_accepts_parent_child_pricing() -> None:
    registry = UnitRegistry(_load_units())

    validate_ancestor_coverage(
        {'input_tokens', 'cache_read_tokens'},
        registry.families['tokens'],
        registry,
    )


def test_validate_ancestor_coverage_rejects_missing_ancestor_price() -> None:
    registry = UnitRegistry(_load_units())

    with pytest.raises(ValueError, match='Missing ancestor price for cache_read_tokens: input_tokens'):
        validate_ancestor_coverage(
            {'cache_read_tokens'},
            registry.families['tokens'],
            registry,
        )


def test_validate_join_coverage_rejects_missing_join_price() -> None:
    registry = UnitRegistry(_load_units())

    with pytest.raises(
        ValueError,
        match='Missing join price for cache_read_tokens and input_audio_tokens: cache_audio_read_tokens',
    ):
        validate_join_coverage(
            {'input_tokens', 'cache_read_tokens', 'input_audio_tokens'},
            registry.families['tokens'],
            registry,
        )


def test_validate_join_coverage_rejects_missing_registered_join_unit() -> None:
    registry = UnitRegistry(_load_units())

    with pytest.raises(
        ValueError,
        match='Missing registered join unit for priced units cache_write_tokens and input_audio_tokens',
    ):
        validate_join_coverage(
            {'input_tokens', 'cache_write_tokens', 'input_audio_tokens'},
            registry.families['tokens'],
            registry,
        )


def test_validate_join_coverage_accepts_priced_join() -> None:
    registry = UnitRegistry(_load_units())

    validate_join_coverage(
        {'input_tokens', 'cache_read_tokens', 'input_audio_tokens', 'cache_audio_read_tokens'},
        registry.families['tokens'],
        registry,
    )
