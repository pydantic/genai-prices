import json
from pathlib import Path
from typing import Any, cast

import pytest
import ruamel.yaml

from genai_prices import data
from genai_prices.data_snapshot import get_snapshot
from genai_prices.decompose import compute_leaf_values, is_descendant_or_self
from genai_prices.types import Usage
from genai_prices.units import UnitRegistry
from genai_prices.validation import (
    validate_ancestor_coverage,
    validate_extractor_destinations,
    validate_join_coverage,
    validate_model_price,
    validate_price_keys,
)
from prices import package_data


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


def test_validate_model_price_accepts_valid_current_price_sets() -> None:
    registry = UnitRegistry(_load_units())

    validate_model_price({'input_mtok', 'cache_read_mtok', 'requests_kcount'}, registry)


def test_validate_model_price_rejects_unknown_price_keys() -> None:
    registry = UnitRegistry(_load_units())

    with pytest.raises(ValueError, match='Unknown price key: inptu_mtok'):
        validate_model_price({'input_mtok', 'inptu_mtok'}, registry)


def test_validate_model_price_rejects_missing_ancestor_prices() -> None:
    registry = UnitRegistry(_load_units())

    with pytest.raises(ValueError, match='Missing ancestor price for cache_read_tokens: input_tokens'):
        validate_model_price({'cache_read_mtok'}, registry)


def test_validate_model_price_rejects_required_join_prices() -> None:
    registry = UnitRegistry(_load_units())

    with pytest.raises(
        ValueError,
        match='Missing join price for cache_read_tokens and input_audio_tokens: cache_audio_read_tokens',
    ):
        validate_model_price({'input_mtok', 'cache_read_mtok', 'input_audio_mtok'}, registry)


def test_validate_model_price_rejects_missing_join_units() -> None:
    registry = UnitRegistry(_load_units())

    with pytest.raises(
        ValueError,
        match='Missing registered join unit for priced units cache_write_tokens and input_audio_tokens',
    ):
        validate_model_price({'input_mtok', 'cache_write_mtok', 'input_audio_mtok'}, registry)


def test_validate_extractor_destinations_accepts_current_reported_usage_keys() -> None:
    registry = UnitRegistry(_load_units())

    validate_extractor_destinations(
        {'input_tokens', 'cache_read_tokens', 'cache_audio_read_tokens'},
        registry.reported_usage_keys(),
    )


def test_validate_extractor_destinations_rejects_price_keys() -> None:
    registry = UnitRegistry(_load_units())

    with pytest.raises(ValueError, match='Invalid extractor destination: input_mtok'):
        validate_extractor_destinations({'input_mtok'}, registry.reported_usage_keys())


def test_validate_extractor_destinations_rejects_unknown_strings() -> None:
    registry = UnitRegistry(_load_units())

    with pytest.raises(ValueError, match='Invalid extractor destination: imaginary_tokens'):
        validate_extractor_destinations({'imaginary_tokens'}, registry.reported_usage_keys())


def test_validate_extractor_destinations_rejects_pricing_only_requests() -> None:
    registry = UnitRegistry(_load_units())

    with pytest.raises(ValueError, match='Invalid extractor destination: requests'):
        validate_extractor_destinations({'requests'}, registry.reported_usage_keys())


def test_decomposition_descendant_helper_accepts_self() -> None:
    registry = UnitRegistry(_load_units())

    assert is_descendant_or_self(registry.units['input_tokens'], registry.units['input_tokens'])


def test_decomposition_descendant_helper_accepts_parent_child_pairs() -> None:
    registry = UnitRegistry(_load_units())

    assert is_descendant_or_self(registry.units['input_tokens'], registry.units['cache_read_tokens'])
    assert not is_descendant_or_self(registry.units['cache_read_tokens'], registry.units['input_tokens'])


def test_decomposition_descendant_helper_rejects_siblings() -> None:
    registry = UnitRegistry(_load_units())

    assert not is_descendant_or_self(registry.units['cache_read_tokens'], registry.units['input_audio_tokens'])


def test_decomposition_descendant_helper_rejects_cross_family_units() -> None:
    registry = UnitRegistry(_load_units())

    assert not is_descendant_or_self(registry.units['requests'], registry.units['input_tokens'])


def test_decomposition_descendant_helper_rejects_incompatible_units() -> None:
    registry = UnitRegistry(_load_units())

    assert not is_descendant_or_self(registry.units['input_tokens'], registry.units['output_tokens'])


def test_compute_leaf_values_handles_parent_child_decomposition() -> None:
    registry = UnitRegistry(_load_units())

    assert compute_leaf_values(
        {'input_tokens', 'cache_read_tokens'},
        Usage(input_tokens=1_000, cache_read_tokens=250),
        registry.families['tokens'],
    ) == {'cache_read_tokens': 250, 'input_tokens': 750}


def test_compute_leaf_values_handles_cached_audio_overlap() -> None:
    registry = UnitRegistry(_load_units())

    assert compute_leaf_values(
        {'input_tokens', 'cache_read_tokens', 'input_audio_tokens', 'cache_audio_read_tokens'},
        Usage(
            input_tokens=1_000,
            cache_read_tokens=400,
            input_audio_tokens=300,
            cache_audio_read_tokens=100,
        ),
        registry.families['tokens'],
    ) == {
        'cache_audio_read_tokens': 100,
        'cache_read_tokens': 300,
        'input_audio_tokens': 200,
        'input_tokens': 400,
    }


def test_compute_leaf_values_handles_output_audio_decomposition() -> None:
    registry = UnitRegistry(_load_units())

    assert compute_leaf_values(
        {'output_tokens', 'output_audio_tokens'},
        Usage(output_tokens=700, output_audio_tokens=200),
        registry.families['tokens'],
    ) == {'output_audio_tokens': 200, 'output_tokens': 500}


def test_compute_leaf_values_ignores_unpriced_reported_descendants() -> None:
    registry = UnitRegistry(_load_units())

    assert compute_leaf_values(
        {'input_tokens'},
        Usage(input_tokens=100, cache_read_tokens=80),
        registry.families['tokens'],
    ) == {'input_tokens': 100}


def test_compute_leaf_values_rejects_negative_leaf_values() -> None:
    registry = UnitRegistry(_load_units())

    with pytest.raises(ValueError, match='Impossible usage data for input_tokens'):
        compute_leaf_values(
            {'input_tokens', 'cache_read_tokens'},
            Usage(input_tokens=100, cache_read_tokens=200),
            registry.families['tokens'],
        )


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
        package_data.load_unit_families()


def test_generated_python_unit_families_data_builds_registry() -> None:
    registry = UnitRegistry(data.unit_families_data)

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


def test_remote_payload_roots_remain_provider_arrays() -> None:
    assert isinstance(json.loads(Path('prices/data.json').read_text()), list)
    assert isinstance(json.loads(Path('prices/data_slim.json').read_text()), list)


def test_bundled_snapshot_carries_unit_registry() -> None:
    snapshot = get_snapshot()

    assert isinstance(snapshot.unit_registry, UnitRegistry)
    assert set(snapshot.unit_registry.families) == {'tokens', 'requests'}


def test_bundled_snapshot_lookup_helpers_still_work() -> None:
    snapshot = get_snapshot()

    provider, model = snapshot.find_provider_model('gpt-4o-mini', None, 'openai', None)

    assert provider.id == 'openai'
    assert model.id == 'gpt-4o-mini'
