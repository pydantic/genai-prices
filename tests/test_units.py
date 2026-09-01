import ast
import json
import subprocess
from dataclasses import FrozenInstanceError
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

from genai_prices import data
from genai_prices.data_units import unit_data
from genai_prices.types import (
    ModelPrice,
    Usage,
    _collect_resolved_model_prices,
    _compute_registry_priced_counts,
)
from genai_prices.units import UnitDef, UnitRegistry, _get_registry
from prices import package_data, prices_types as build_types
from prices.build import load_units
from prices.export_validation import (
    RuntimeUnitProjection,
    normalize_conditional_implications,
    runtime_unit_projection,
    validate_runtime_unit_projection,
    validate_unit_evolution,
    validate_units,
)

TOKEN_USAGE_KEYS = {
    'input_tokens',
    'output_tokens',
    'cache_read_tokens',
    'cache_write_tokens',
    'cache_write_5m_tokens',
    'cache_write_1h_tokens',
    'input_text_tokens',
    'output_text_tokens',
    'cache_text_read_tokens',
    'cache_text_write_tokens',
    'cache_text_write_5m_tokens',
    'cache_text_write_1h_tokens',
    'input_audio_tokens',
    'output_audio_tokens',
    'cache_audio_read_tokens',
    'cache_audio_write_tokens',
    'cache_audio_write_5m_tokens',
    'cache_audio_write_1h_tokens',
    'input_image_tokens',
    'output_image_tokens',
    'cache_image_read_tokens',
    'cache_image_write_tokens',
    'cache_image_write_5m_tokens',
    'cache_image_write_1h_tokens',
    'input_video_tokens',
    'output_video_tokens',
    'cache_video_read_tokens',
    'cache_video_write_tokens',
    'cache_video_write_5m_tokens',
    'cache_video_write_1h_tokens',
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
    'cache_write_5m_mtok',
    'cache_write_1h_mtok',
    'input_text_mtok',
    'output_text_mtok',
    'cache_text_read_mtok',
    'cache_text_write_mtok',
    'cache_text_write_5m_mtok',
    'cache_text_write_1h_mtok',
    'input_audio_mtok',
    'output_audio_mtok',
    'cache_audio_read_mtok',
    'cache_audio_write_mtok',
    'cache_audio_write_5m_mtok',
    'cache_audio_write_1h_mtok',
    'input_image_mtok',
    'output_image_mtok',
    'cache_image_read_mtok',
    'cache_image_write_mtok',
    'cache_image_write_5m_mtok',
    'cache_image_write_1h_mtok',
    'input_video_mtok',
    'output_video_mtok',
    'cache_video_read_mtok',
    'cache_video_write_mtok',
    'cache_video_write_5m_mtok',
    'cache_video_write_1h_mtok',
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

NON_TOKEN_REPORTABLE_UNITS: dict[str, dict[str, Any]] = {
    'input_characters': {
        'per': 1_000_000,
        'price_key': 'input_mchars',
        'dimensions': {'family': 'characters', 'direction': 'input'},
    },
    'input_text_messages': {
        'per': 1_000,
        'price_key': 'input_text_messages_kcount',
        'dimensions': {'family': 'messages', 'direction': 'input', 'modality': 'text'},
    },
    'audio_seconds': {
        'per': 3_600,
        'price_key': 'audio_hours',
        'dimensions': {'family': 'durations', 'modality': 'audio'},
    },
    'input_audio_seconds': {
        'per': 3_600,
        'price_key': 'input_audio_hours',
        'dimensions': {'family': 'durations', 'direction': 'input', 'modality': 'audio'},
    },
    'output_audio_seconds': {
        'per': 3_600,
        'price_key': 'output_audio_hours',
        'dimensions': {'family': 'durations', 'direction': 'output', 'modality': 'audio'},
    },
    'input_pixels': {
        'per': 1_000_000_000,
        'price_key': 'input_gpixels',
        'dimensions': {'family': 'pixels', 'direction': 'input'},
    },
    'input_document_pages': {
        'per': 1_000,
        'price_key': 'input_document_kpages',
        'dimensions': {'family': 'document_pages', 'direction': 'input'},
    },
    'input_annotated_document_pages': {
        'per': 1_000,
        'price_key': 'input_annotated_document_kpages',
        'dimensions': {'family': 'document_pages', 'direction': 'input', 'page_type': 'annotated'},
    },
    'rerank_searches': {
        'per': 1_000,
        'price_key': 'rerank_searches_kcount',
        'dimensions': {'family': 'rerank'},
    },
    'web_searches': {
        'per': 1_000,
        'price_key': 'web_searches_kcount',
        'dimensions': {'family': 'tool_calls', 'tool_type': 'web_search'},
    },
    'social_searches': {
        'per': 1_000,
        'price_key': 'social_searches_kcount',
        'dimensions': {'family': 'tool_calls', 'tool_type': 'social_search'},
    },
    'storage_searches': {
        'per': 1_000,
        'price_key': 'storage_searches_kcount',
        'dimensions': {'family': 'tool_calls', 'tool_type': 'storage_search'},
    },
    'code_executions': {
        'per': 1_000,
        'price_key': 'code_executions_kcount',
        'dimensions': {'family': 'tool_calls', 'tool_type': 'code_execution'},
    },
}

REPORTABLE_USAGE_KEYS = TOKEN_USAGE_KEYS | set(NON_TOKEN_REPORTABLE_UNITS)
ALL_USAGE_KEYS = REPORTABLE_USAGE_KEYS | {'requests'}
ALL_PRICE_KEYS = TOKEN_PRICE_KEYS | {
    *(unit['price_key'] for unit in NON_TOKEN_REPORTABLE_UNITS.values()),
    'requests_kcount',
}


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

    assert {usage_key: raw_units[usage_key] for usage_key in NON_TOKEN_REPORTABLE_UNITS} == NON_TOKEN_REPORTABLE_UNITS


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
        cache_ttl = dimensions.get('cache_ttl')
        if token_type is None:
            expected_stem = f'{direction}_{modality}' if modality is not None else direction
        elif token_type in {'cache_read', 'cache_write'}:
            assert direction == 'input'
            cache_operation = token_type.removeprefix('cache_')
            expected_stem = (
                f'cache_{modality}_{cache_operation}' if modality is not None else f'cache_{cache_operation}'
            )
            if cache_ttl is not None:
                expected_stem = f'{expected_stem}_{cache_ttl}'
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
                    equal_rate_ancestors = [
                        ancestor
                        for ancestor, ancestor_price in ancestor_prices
                        if len(ancestor.dimensions) == closest_depth and ancestor_price == price_value
                    ]
                    if not equal_rate_ancestors:
                        continue
                    if any(
                        ancestor.dimensions.get('direction') != unit.dimensions.get('direction')
                        for ancestor in equal_rate_ancestors
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
    assert ast.literal_eval(python_unit_data.split('unit_data: dict[str, Any] = ', 1)[1]) == runtime_unit_projection(
        load_units()
    )
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
    assert registry.unit_for_price_key('input_text_messages_kcount') is registry.units['input_text_messages']
    assert registry.unit_for_price_key('input_audio_hours') is registry.units['input_audio_seconds']
    assert (
        registry.unit_for_price_key('input_annotated_document_kpages')
        is registry.units['input_annotated_document_pages']
    )
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


def test_bundled_non_token_unit_relationships() -> None:
    registry = UnitRegistry(load_units())

    assert registry.ancestor_usage_keys('input_audio_seconds') == frozenset({'audio_seconds'})
    assert registry.ancestor_usage_keys('output_audio_seconds') == frozenset({'audio_seconds'})
    assert registry.ancestor_usage_keys('input_annotated_document_pages') == frozenset({'input_document_pages'})
    assert registry.ancestor_usage_keys('web_searches') == frozenset()
    assert not registry.units['input_audio_seconds'].is_compatible_with(registry.units['output_audio_seconds'])
    assert not registry.units['web_searches'].is_compatible_with(registry.units['social_searches'])
    assert not registry.units['storage_searches'].is_compatible_with(registry.units['code_executions'])


def test_unit_registry_units_mapping_is_immutable() -> None:
    registry = UnitRegistry(unit_data)

    with pytest.raises(TypeError, match="'mappingproxy' object does not support item assignment"):
        cast(dict[str, Any], registry.units)['new_unit'] = registry.units['input_tokens']


def test_runtime_unit_projection_is_ordered_canonical_and_runtime_only() -> None:
    projection = runtime_unit_projection(
        {
            'matching_key': {
                'per': 1,
                'price_key': 'matching_key',
                'dimensions': {'family': 'events'},
                'dimension_requirements': {'kind': {'family': 'events'}},
                'source_annotation': 'publisher only',
            },
            'different_key': {
                'per': 1,
                'price_key': 'different_price',
                'dimensions': {'family': 'events', 'kind': 'different'},
            },
        }
    )

    assert list(projection) == ['matching_key', 'different_key']
    assert projection == {
        'matching_key': {'per': 1, 'dimensions': {'family': 'events'}},
        'different_key': {
            'per': 1,
            'price_key': 'different_price',
            'dimensions': {'family': 'events', 'kind': 'different'},
        },
    }


@pytest.mark.parametrize('per', [1, 9_007_199_254_740_991])
def test_validate_runtime_unit_projection_accepts_safe_integer_boundaries(per: int) -> None:
    registry = validate_runtime_unit_projection(
        {'events': {'per': per, 'dimensions': {'family': f'events_{per}'}, 'extension': object()}}
    )

    assert registry.units['events'].per == per


@pytest.mark.parametrize('per', [0, -1, True, 1.5, 9_007_199_254_740_992])
def test_validate_runtime_unit_projection_rejects_invalid_normalization(per: Any) -> None:
    with pytest.raises(ValueError, match='expected a positive integer from 1 to 9007199254740991'):
        validate_runtime_unit_projection({'events': {'per': per, 'dimensions': {'family': 'events'}}})


@pytest.mark.parametrize(
    ('raw_units', 'message'),
    [
        ([], 'Invalid units: expected a mapping'),
        ({1: {'per': 1, 'dimensions': {'family': 'events'}}}, 'usage key.*is not a string'),
        ({'events': []}, 'Invalid unit events: expected a mapping'),
        ({'events': {'dimensions': {'family': 'events'}}}, 'Missing per for unit events'),
        ({'events': {'per': 1, 'price_key': 1, 'dimensions': {'family': 'events'}}}, 'price key.*expected a string'),
        ({'events': {'per': 1}}, 'Missing dimensions for unit events'),
        ({'events': {'per': 1, 'dimensions': []}}, 'dimensions.*expected a mapping'),
        ({'events': {'per': 1, 'dimensions': {1: 'events'}}}, 'keys must be non-empty strings'),
        ({'events': {'per': 1, 'dimensions': {'': 'events'}}}, 'keys must be non-empty strings'),
        ({'events': {'per': 1, 'dimensions': {'family': 1}}}, 'values must be non-empty strings'),
        ({'events': {'per': 1, 'dimensions': {'family': ''}}}, 'values must be non-empty strings'),
        ({'events': {'per': 1, 'dimensions': {'kind': 'event'}}}, 'Missing required family dimension'),
    ],
)
def test_validate_runtime_unit_projection_rejects_malformed_core(raw_units: Any, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        validate_runtime_unit_projection(raw_units)


def test_validate_runtime_unit_projection_enforces_identities_families_and_joins() -> None:
    with pytest.raises(ValueError, match='Duplicate unit price key: event_price'):
        validate_runtime_unit_projection(
            {
                'events': {'per': 1, 'price_key': 'event_price', 'dimensions': {'family': 'events'}},
                'special_events': {
                    'per': 1,
                    'price_key': 'event_price',
                    'dimensions': {'family': 'events', 'kind': 'special'},
                },
            }
        )

    with pytest.raises(ValueError, match='Duplicate unit dimensions: events and event_count'):
        validate_runtime_unit_projection(
            {
                'events': {'per': 1, 'dimensions': {'family': 'events'}},
                'event_count': {'per': 1, 'dimensions': {'family': 'events'}},
            }
        )

    with pytest.raises(ValueError, match='Inconsistent per for family dimension events'):
        validate_runtime_unit_projection(
            {
                'events': {'per': 1, 'dimensions': {'family': 'events'}},
                'special_events': {'per': 1_000, 'dimensions': {'family': 'events', 'kind': 'special'}},
            }
        )

    with pytest.raises(ValueError, match='Missing join unit dimensions between special_events and batch_events'):
        validate_runtime_unit_projection(
            {
                'events': {'per': 1, 'dimensions': {'family': 'events'}},
                'special_events': {'per': 1, 'dimensions': {'family': 'events', 'kind': 'special'}},
                'batch_events': {'per': 1, 'dimensions': {'family': 'events', 'mode': 'batch'}},
            }
        )


def test_validate_runtime_unit_projection_ignores_extensions_and_does_not_require_intervals() -> None:
    registry = validate_runtime_unit_projection(
        {
            'events': {'per': 1, 'dimensions': {'family': 'events'}},
            'special_batch_events': {
                'per': 1,
                'dimensions': {'family': 'events', 'kind': 'special', 'mode': 'batch'},
                'dimension_requirements': [],
                'future_extension': object(),
            },
        }
    )

    assert registry.ancestor_usage_keys('special_batch_events') == frozenset({'events'})


def _published_evolution_source() -> dict[str, dict[str, Any]]:
    return {
        'events': {'per': 1, 'dimensions': {'family': 'events'}},
        'special_events': {
            'per': 1,
            'dimensions': {'family': 'events', 'kind': 'special'},
            'dimension_requirements': {'kind': {'family': 'events'}},
        },
    }


def test_validate_unit_evolution_accepts_appended_descendants_intersections_and_families() -> None:
    previous_source = _published_evolution_source()
    candidate_source = {
        **previous_source,
        'vip_events': {'per': 1, 'dimensions': {'family': 'events', 'audience': 'vip'}},
        'vip_special_events': {
            'per': 1,
            'dimensions': {'family': 'events', 'kind': 'special', 'audience': 'vip'},
        },
        'seconds': {'per': 1, 'dimensions': {'family': 'durations'}},
    }

    validate_unit_evolution(
        runtime_unit_projection(previous_source),
        normalize_conditional_implications(previous_source),
        candidate_source,
    )
    assert list(runtime_unit_projection(candidate_source))[-3:] == [
        'vip_events',
        'vip_special_events',
        'seconds',
    ]


def test_validate_unit_evolution_accepts_additive_replacement_for_mistaken_unit() -> None:
    previous_source = {
        'mistaken_events': {'per': 1, 'dimensions': {'family': 'events', 'kind': 'mistaken'}},
    }
    candidate_source = {
        **previous_source,
        'corrected_events': {
            'per': 1,
            'dimensions': {'family': 'events', 'kind': 'mistaken', 'correction': 'v2'},
        },
    }

    validate_unit_evolution(
        runtime_unit_projection(previous_source),
        normalize_conditional_implications(previous_source),
        candidate_source,
    )


def test_validate_unit_evolution_rejects_removal_reordering_and_insertion() -> None:
    previous_source = _published_evolution_source()
    previous_projection = runtime_unit_projection(previous_source)
    previous_implications = normalize_conditional_implications(previous_source)

    with pytest.raises(ValueError, match='Removed published unit: special_events'):
        validate_unit_evolution(previous_projection, previous_implications, {'events': previous_source['events']})

    with pytest.raises(ValueError, match='Reordered published units'):
        validate_unit_evolution(
            previous_projection,
            previous_implications,
            {
                'special_events': previous_source['special_events'],
                'events': previous_source['events'],
            },
        )

    with pytest.raises(ValueError, match='New unit seconds must be appended'):
        validate_unit_evolution(
            previous_projection,
            previous_implications,
            {
                'events': previous_source['events'],
                'seconds': {'per': 1, 'dimensions': {'family': 'durations'}},
                'special_events': previous_source['special_events'],
            },
        )


@pytest.mark.parametrize(
    ('field', 'replacement'),
    [
        ('per', 2),
        ('price_key', 'replacement_price'),
        ('dimensions', {'family': 'events', 'kind': 'corrected'}),
    ],
)
def test_validate_unit_evolution_rejects_redefinitions(field: str, replacement: object) -> None:
    previous_source = {
        'published_events': {
            'per': 1,
            'price_key': 'published_price',
            'dimensions': {'family': 'events', 'kind': 'original'},
        }
    }
    candidate_unit: dict[str, object] = dict(previous_source['published_events'])
    candidate_unit[field] = replacement

    with pytest.raises(ValueError, match='Redefined published unit: published_events'):
        validate_unit_evolution(
            runtime_unit_projection(previous_source),
            normalize_conditional_implications(previous_source),
            {'published_events': candidate_unit},
        )


def test_validate_unit_evolution_rejects_changed_implications_and_new_ancestors() -> None:
    previous_source = _published_evolution_source()
    with pytest.raises(ValueError, match='Missing published conditional implications for unit special_events'):
        validate_unit_evolution(
            runtime_unit_projection(previous_source),
            {'events': ()},
            previous_source,
        )

    candidate_source = {
        'events': previous_source['events'],
        'special_events': {
            'per': 1,
            'dimensions': {'family': 'events', 'kind': 'special'},
        },
    }
    with pytest.raises(ValueError, match='Changed published conditional implications for unit special_events'):
        validate_unit_evolution(
            runtime_unit_projection(previous_source),
            normalize_conditional_implications(previous_source),
            candidate_source,
        )

    ancestor_previous_source = {
        'special_events': {'per': 1, 'dimensions': {'family': 'events', 'kind': 'special'}},
    }
    with pytest.raises(ValueError, match='New unit events is an ancestor.*special_events'):
        validate_unit_evolution(
            runtime_unit_projection(ancestor_previous_source),
            normalize_conditional_implications(ancestor_previous_source),
            {
                **ancestor_previous_source,
                'events': {'per': 1, 'dimensions': {'family': 'events'}},
            },
        )


def test_normalize_conditional_implications_is_transitive_and_canonical() -> None:
    factored = {
        'special_events': {
            'per': 1,
            'dimensions': {'family': 'events', 'category': 'special', 'mode': 'batch'},
            'dimension_requirements': {
                'mode': {'category': 'special'},
                'category': {'family': 'events'},
            },
        }
    }
    flattened_and_reordered = {
        'special_events': {
            'dimensions': {'mode': 'batch', 'category': 'special', 'family': 'events'},
            'dimension_requirements': {
                'category': {'family': 'events'},
                'mode': {'family': 'events', 'category': 'special'},
            },
            'per': 1,
        }
    }

    expected = {
        'special_events': (
            ('category', 'family', 'events'),
            ('mode', 'category', 'special'),
            ('mode', 'family', 'events'),
        )
    }
    assert normalize_conditional_implications(factored) == expected
    assert normalize_conditional_implications(flattened_and_reordered) == expected


def test_normalize_conditional_implications_tolerates_conflict_free_cycles() -> None:
    normalized = normalize_conditional_implications(
        {
            'cyclic_events': {
                'per': 1,
                'dimensions': {'family': 'events', 'a': 'on', 'b': 'set'},
                'dimension_requirements': {'a': {'b': 'set'}, 'b': {'a': 'on'}},
            }
        }
    )

    assert normalized == {
        'cyclic_events': (
            ('a', 'a', 'on'),
            ('a', 'b', 'set'),
            ('b', 'a', 'on'),
            ('b', 'b', 'set'),
        )
    }


def test_normalize_conditional_implications_rejects_conflicts() -> None:
    with pytest.raises(ValueError, match='Conflicting implied dimension assignment.*tier=two.*tier=one'):
        normalize_conditional_implications(
            {
                'conflicting_events': {
                    'per': 1,
                    'dimensions': {'family': 'events', 'mode': 'batch', 'category': 'special', 'tier': 'one'},
                    'dimension_requirements': {
                        'mode': {'category': 'special', 'tier': 'one'},
                        'category': {'tier': 'two'},
                    },
                }
            }
        )


@pytest.mark.parametrize(
    ('usage_key', 'price_key', 'message'),
    [
        ('_private_name', 'private_mtok', 'must not start'),
        ('$input_tokens', 'input_mtok', 'is not a public identifier'),
        ('class', 'class_mtok', 'is a reserved keyword'),
        ('valid_usage', 'function', 'is a reserved keyword'),
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


def test_validate_units_rejects_duplicate_price_keys_and_dimensions() -> None:
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

    with pytest.raises(ValueError, match='Duplicate unit dimensions: input_tokens and prompt_tokens'):
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


def test_validate_units_rejects_open_intervals_and_missing_joins() -> None:
    with pytest.raises(ValueError, match='Missing intermediate unit dimensions'):
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


def test_validate_units_skips_intermediate_sets_for_unsatisfied_dimension_requirements() -> None:
    registry = validate_units(
        {
            'input_tokens': {
                'per': 1_000_000,
                'dimensions': {'family': 'tokens', 'direction': 'input'},
            },
            'cache_write_tokens': {
                'per': 1_000_000,
                'dimensions': {'family': 'tokens', 'direction': 'input', 'token_type': 'cache_write'},
            },
            'cache_write_1h_tokens': {
                'per': 1_000_000,
                'dimensions': {
                    'family': 'tokens',
                    'direction': 'input',
                    'token_type': 'cache_write',
                    'cache_ttl': '1h',
                },
                'dimension_requirements': {'cache_ttl': {'token_type': 'cache_write'}},
            },
        }
    )

    assert registry.ancestor_usage_keys('cache_write_1h_tokens') == frozenset({'input_tokens', 'cache_write_tokens'})


@pytest.mark.parametrize(
    ('dimensions', 'requirements', 'message'),
    [
        (
            {'family': 'tokens', 'direction': 'input'},
            {'cache_ttl': {'token_type': 'cache_write'}},
            'Dimension requirement trigger cache_ttl is not a dimension of unit cache_write_1h_tokens',
        ),
        (
            {'family': 'tokens', 'direction': 'input', 'cache_ttl': '1h'},
            {'cache_ttl': {'token_type': 'cache_write'}},
            'Unsatisfied dimension requirement for unit cache_write_1h_tokens: token_type=cache_write',
        ),
    ],
)
def test_validate_units_rejects_invalid_dimension_requirements(
    dimensions: dict[str, str], requirements: dict[str, dict[str, str]], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_units(
            {
                'cache_write_1h_tokens': {
                    'per': 1_000_000,
                    'dimensions': dimensions,
                    'dimension_requirements': requirements,
                }
            }
        )


@pytest.mark.parametrize(
    ('requirements', 'message'),
    [
        ([], 'expected a mapping'),
        ({1: {'token_type': 'cache_write'}}, 'trigger keys must be strings'),
        ({'cache_ttl': []}, "requirement for 'cache_ttl' must be a mapping"),
        ({'cache_ttl': {1: 'cache_write'}}, 'must map string dimension keys to string values'),
        ({'cache_ttl': {'token_type': 1}}, 'must map string dimension keys to string values'),
    ],
)
def test_validate_units_rejects_malformed_dimension_requirements(requirements: Any, message: str) -> None:
    with pytest.raises(
        ValueError,
        match=message,
    ):
        validate_units(
            {
                'cache_write_1h_tokens': {
                    'per': 1_000_000,
                    'dimensions': {
                        'family': 'tokens',
                        'direction': 'input',
                        'token_type': 'cache_write',
                        'cache_ttl': '1h',
                    },
                    'dimension_requirements': requirements,
                }
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
    raw_units = load_units()
    registry = validate_units(raw_units)

    assert registry.units['cache_audio_read_tokens'].dimensions == {
        'family': 'tokens',
        'direction': 'input',
        'modality': 'audio',
        'token_type': 'cache_read',
    }
    assert registry.units['cache_audio_write_1h_tokens'].dimensions == {
        'family': 'tokens',
        'direction': 'input',
        'modality': 'audio',
        'token_type': 'cache_write',
        'cache_ttl': '1h',
    }
    assert raw_units['cache_audio_write_1h_tokens']['dimension_requirements'] == {
        'cache_ttl': {'token_type': 'cache_write'}
    }
    assert not hasattr(registry.units['cache_audio_write_1h_tokens'], 'dimension_requirements')


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

    units: RuntimeUnitProjection = {
        'transient_tokens': {
            'per': 1_000_000,
            'price_key': 'transient_mtok',
            'dimensions': {'family': 'transient', 'tier': 'fast'},
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
    assert generated_units == {
        'transient_tokens': {
            'per': 1_000_000,
            'price_key': 'transient_mtok',
            'dimensions': {'family': 'transient', 'tier': 'fast'},
        }
    }


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
    units: RuntimeUnitProjection = {
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


def test_package_ts_data_accepts_separated_inputs_without_units_yml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    units: RuntimeUnitProjection = {
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
    prettier_calls: list[tuple[list[str], str | None]] = []

    def skip_prettier(
        args: list[str],
        *,
        cwd: str | None = None,
        check: bool = False,
        stdout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        _ = check, stdout
        prettier_calls.append((args, cwd))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, 'run', skip_prettier)

    package_data.package_ts_data(provider_data, units)

    assert (js_src_dir / 'data.ts').exists()
    unit_data_content = (js_src_dir / 'dataUnits.ts').read_text()
    generated_json = unit_data_content.split('export const unitData: RawUnitsDict = ', 1)[1].removesuffix(';\n')
    assert json.loads(generated_json) == {
        'input_tokens': {
            'per': 1_000_000,
            'price_key': 'input_mtok',
            'dimensions': {'family': 'tokens', 'direction': 'input'},
        }
    }
    assert prettier_calls == [
        (
            ['npx', '--', 'prettier', '--write', 'src/data.ts', 'src/dataUnits.ts'],
            str(tmp_path / 'packages' / 'js'),
        )
    ]


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


def test_package_data_accepts_current_provider_extractor_reasoning_coverage() -> None:
    package_data.validate_provider_extractor_reasoning_coverage(data.providers)


def test_package_data_extractor_validation_rejects_unmapped_reasoning_tokens() -> None:
    provider = _build_provider_prices(
        build_types.ModelPrice(input_mtok=Decimal('1'), output_mtok=Decimal('2')),
        extractors=[
            build_types.UsageExtractor.model_construct(
                root='usage',
                mappings=[
                    _build_extractor_mapping('prompt_tokens', 'input_tokens'),
                    _build_extractor_mapping('completion_tokens', 'output_tokens'),
                ],
                api_flavor='chat',
                model_path='model',
            )
        ],
    )

    with pytest.raises(
        ValueError,
        match=(
            'Invalid extractor for testing/chat: Missing output_reasoning_tokens mapping: '
            'extractors reading completion_tokens must also map reasoning tokens'
        ),
    ):
        package_data.validate_provider_extractor_reasoning_coverage([provider])
