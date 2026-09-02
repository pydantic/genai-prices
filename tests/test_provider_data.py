from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from decimal import Decimal
from typing import cast

import pytest

from genai_prices.provider_data import _decode_provider_data
from genai_prices.types import Usage
from genai_prices.units import UnitRegistry, _get_registry

_UNIT_DATA = {
    'input_tokens': {
        'per': 1_000_000,
        'price_key': 'input_mtok',
        'dimensions': {'family': 'tokens', 'direction': 'input'},
    },
    'output_tokens': {
        'per': 1_000_000,
        'price_key': 'output_mtok',
        'dimensions': {'family': 'tokens', 'direction': 'output'},
    },
}


def _registry() -> UnitRegistry:
    return UnitRegistry(_UNIT_DATA)


def _provider() -> dict[str, object]:
    return {
        'id': 'testing',
        'name': 'Testing',
        'api_pattern': r'https://testing\.example',
        'provider_match': {'equals': 'testing'},
        'extractors': [
            {
                'root': 'usage',
                'mappings': [
                    {'path': 'input_tokens', 'dest': 'input_tokens'},
                    {'path': 'output_tokens', 'dest': 'output_tokens'},
                ],
            }
        ],
        'models': [
            {
                'id': 'model-a',
                'match': {'equals': 'model-a'},
                'prices': {'input_mtok': 1, 'output_mtok': 2},
            },
            {
                'id': 'model-b',
                'match': {'equals': 'model-b'},
                'prices': {'input_mtok': 3, 'output_mtok': 4},
            },
        ],
    }


def _wrapped(provider: object | None = None) -> dict[str, object]:
    return {
        'units': deepcopy(_UNIT_DATA),
        'providers': [_provider() if provider is None else provider],
    }


def test_decode_provider_data_accepts_both_roots_and_ignores_extensions() -> None:
    compatibility_registry = _registry()
    provider = _provider()
    provider['future_provider_note'] = {'anything': True}
    provider['provider_match'] = {'future_match_note': True, 'equals': 'testing'}
    models = cast(list[object], provider['models'])
    cast(dict[str, object], models[0])['match'] = {'future_match_note': True, 'equals': 'model-a'}
    extractors = cast(list[object], provider['extractors'])
    extractor = cast(dict[str, object], extractors[0])
    mappings = cast(list[object], extractor['mappings'])
    cast(dict[str, object], mappings[0])['path'] = [
        {
            'future_array_match_note': True,
            'type': 'array-match',
            'field': 'kind',
            'match': {'future_match_note': True, 'equals': 'tokens'},
        },
        'count',
    ]
    wrapped = _wrapped(provider)
    wrapped['future_wrapper_note'] = ['anything']
    units = wrapped['units']
    assert isinstance(units, dict)
    cast(dict[str, dict[str, object]], units)['input_tokens']['future_unit_note'] = 'anything'

    decoded_wrapped = _decode_provider_data(wrapped, compatibility_registry)
    decoded_legacy = _decode_provider_data([_provider()], compatibility_registry)

    assert decoded_wrapped.registry is not None
    assert list(decoded_wrapped.registry.units) == ['input_tokens', 'output_tokens']
    assert decoded_wrapped.providers[0].models[0].id == 'model-a'
    assert decoded_wrapped.providers[0].provider_match is not None
    assert decoded_wrapped.providers[0].provider_match.is_match('testing')
    assert decoded_wrapped.compatibility_warnings == ()
    assert decoded_legacy.registry is None
    assert decoded_legacy.providers[0].models[1].id == 'model-b'
    assert decoded_legacy.compatibility_warnings == ()


@pytest.mark.parametrize('raw', [None, 'providers', 1, (), True])
def test_decode_provider_data_rejects_invalid_roots(raw: object) -> None:
    with pytest.raises(ValueError, match='provider data root'):
        _decode_provider_data(raw, _registry())


@pytest.mark.parametrize(
    ('raw', 'message'),
    [
        ({'providers': []}, 'missing units'),
        ({'units': {}}, 'missing providers'),
        ({'units': {}, 'providers': {}}, 'providers: expected an array'),
        ({'units': [], 'providers': []}, 'Invalid units: expected an object'),
    ],
)
def test_decode_wrapped_provider_data_validates_recognized_wrapper_members(
    raw: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _decode_provider_data(raw, UnitRegistry())


def test_decode_wrapped_provider_data_validates_evolution_without_changing_active_state() -> None:
    active_registry = _get_registry()
    wrapped = _wrapped()
    units = wrapped['units']
    assert isinstance(units, dict)
    cast(dict[str, object], units).pop('input_tokens')

    with pytest.raises(ValueError, match='Removed published unit: input_tokens'):
        _decode_provider_data(wrapped, _registry())

    assert _get_registry() is active_registry


def test_decode_wrapped_provider_data_projects_unsupported_capabilities_in_order() -> None:
    provider = _provider()
    provider['provider_match'] = {'future_match': 'testing'}
    extractors = provider['extractors']
    assert isinstance(extractors, list)
    extractors = cast(list[object], extractors)
    extractors.insert(0, {'type': 'future-extractor', 'config': {}})
    models = provider['models']
    assert isinstance(models, list)
    models = cast(list[object], models)
    models.insert(0, {'id': 'future-model', 'match': {'future_match': 'x'}, 'prices': {'input_mtok': 10}})
    model_a = models[1]
    assert isinstance(model_a, dict)
    cast(dict[str, object], model_a)['prices'] = [
        {'constraint': {'type': 'future-constraint'}, 'prices': {'input_mtok': 99}},
        {'prices': {'input_mtok': {'type': 'future-price'}, 'output_mtok': 2}},
    ]

    decoded = _decode_provider_data(_wrapped(provider), _registry())

    decoded_provider = decoded.providers[0]
    assert decoded_provider.provider_match is None
    assert decoded_provider.extractors is not None
    assert len(decoded_provider.extractors) == 1
    assert [model.id for model in decoded_provider.models] == ['model-a', 'model-b']
    model_price = decoded_provider.models[0].prices
    assert isinstance(model_price, list)
    assert model_price[0].prices.__dict__ == {'output_mtok': Decimal('2')}
    assert decoded.compatibility_warnings == (
        "Unsupported match variant at providers[0].provider_match for provider 'testing'; "
        'upgrade genai-prices for full support',
        "Unsupported extractor variant at providers[0].extractors[0] for provider 'testing'; "
        'upgrade genai-prices for full support',
        "Unsupported match variant at providers[0].models[0].match for provider 'testing', model 'future-model'; "
        'upgrade genai-prices for full support',
        "Unsupported constraint variant at providers[0].models[1].prices[0].constraint for provider 'testing', "
        "model 'model-a'; upgrade genai-prices for full support",
        "Unsupported price variant at providers[0].models[1].prices[1].prices.input_mtok for provider 'testing', "
        "model 'model-a'; upgrade genai-prices for full support",
    )


def test_decode_wrapped_provider_data_projects_typed_future_constraint_with_known_fields() -> None:
    provider = _provider()
    models = provider['models']
    assert isinstance(models, list)
    model = cast(dict[str, object], models[0])
    model['prices'] = [
        {'prices': {'input_mtok': 1}},
        {'constraint': {'type': 'weekday', 'start_date': '2026-01-01'}, 'prices': {'input_mtok': 99}},
    ]

    decoded = _decode_provider_data(_wrapped(provider), _registry())

    prices = decoded.providers[0].models[0].prices
    assert isinstance(prices, list)
    assert len(prices) == 1
    assert prices[0].prices.input_mtok == 1
    assert decoded.compatibility_warnings == (
        "Unsupported constraint variant at providers[0].models[0].prices[1].constraint for provider 'testing', "
        "model 'model-a'; upgrade genai-prices for full support",
    )


def test_decode_wrapped_provider_data_projects_non_string_constraint_type() -> None:
    provider = _provider()
    models = provider['models']
    assert isinstance(models, list)
    model = cast(dict[str, object], models[0])
    model['prices'] = [
        {'prices': {'input_mtok': 1}},
        {'constraint': {'type': ['future-constraint'], 'start_date': '2026-01-01'}, 'prices': {'input_mtok': 99}},
    ]

    decoded = _decode_provider_data(_wrapped(provider), _registry())

    prices = decoded.providers[0].models[0].prices
    assert isinstance(prices, list)
    assert len(prices) == 1
    assert prices[0].prices.input_mtok == 1
    assert decoded.compatibility_warnings == (
        "Unsupported constraint variant at providers[0].models[0].prices[1].constraint for provider 'testing', "
        "model 'model-a'; upgrade genai-prices for full support",
    )


def test_decode_wrapped_provider_data_projects_typed_future_price_with_known_fields() -> None:
    provider = _provider()
    models = provider['models']
    assert isinstance(models, list)
    model = cast(dict[str, object], models[0])
    model['prices'] = [
        {'prices': {'input_mtok': {'type': 'future-price', 'base': 99}, 'output_mtok': 2}},
    ]

    decoded = _decode_provider_data(_wrapped(provider), _registry())

    prices = decoded.providers[0].models[0].prices
    assert isinstance(prices, list)
    assert prices[0].prices.__dict__ == {'output_mtok': Decimal('2')}
    assert decoded.compatibility_warnings == (
        "Unsupported price variant at providers[0].models[0].prices[0].prices.input_mtok for provider 'testing', "
        "model 'model-a'; upgrade genai-prices for full support",
    )


def test_decode_wrapped_provider_data_drops_model_with_only_future_conditional_prices() -> None:
    provider = _provider()
    models = provider['models']
    assert isinstance(models, list)
    model = cast(dict[str, object], models[0])
    model['prices'] = [{'constraint': {'type': 'weekday'}, 'prices': {'input_mtok': 99}}]

    decoded = _decode_provider_data(_wrapped(provider), _registry())

    assert [decoded_model.id for decoded_model in decoded.providers[0].models] == ['model-b']
    assert decoded.compatibility_warnings == (
        "Unsupported constraint variant at providers[0].models[0].prices[0].constraint for provider 'testing', "
        "model 'model-a'; upgrade genai-prices for full support",
    )


def test_decode_wrapped_provider_data_projects_unsupported_extractor_paths_and_price_entries() -> None:
    provider = _provider()
    extractors = provider['extractors']
    assert isinstance(extractors, list)
    extractor = cast(list[object], extractors)[0]
    assert isinstance(extractor, dict)
    extractor['mappings'] = [
        {'path': [{'type': 'future-path'}], 'dest': 'input_tokens'},
        {
            'path': ['usage', {'type': 'array-match', 'field': 'kind', 'match': {'equals': 'tokens'}}],
            'dest': 'input_tokens',
        },
        {'future_mapping': True},
        {'path': 'output_tokens', 'dest': 'output_tokens'},
    ]
    models = provider['models']
    assert isinstance(models, list)
    model = cast(list[object], models)[0]
    assert isinstance(model, dict)
    model['prices'] = [{'type': 'future-conditional-price'}, {'prices': {'output_mtok': 2}}]

    decoded = _decode_provider_data(_wrapped(provider), _registry())

    decoded_extractor = decoded.providers[0].extractors
    assert decoded_extractor is not None
    assert [mapping.dest for mapping in decoded_extractor[0].mappings] == ['input_tokens', 'output_tokens']
    prices = decoded.providers[0].models[0].prices
    assert isinstance(prices, list)
    assert len(prices) == 1
    assert [warning.split(' for ')[0] for warning in decoded.compatibility_warnings] == [
        'Unsupported extractor mapping variant at providers[0].extractors[0].mappings[0].path',
        'Unsupported extractor mapping variant at providers[0].extractors[0].mappings[2]',
        'Unsupported price variant at providers[0].models[0].prices[0]',
    ]


def test_decode_wrapped_provider_data_projects_typed_future_mapping_with_known_fields() -> None:
    provider = _provider()
    provider['extractors'] = [
        {
            'root': 'usage',
            'mappings': [
                {'type': 'future-mapping', 'path': 'input_tokens', 'dest': 'input_tokens'},
                {'path': 'output_tokens', 'dest': 'output_tokens'},
            ],
        }
    ]

    decoded = _decode_provider_data(_wrapped(provider), _registry())

    extractors = decoded.providers[0].extractors
    assert extractors is not None
    assert [mapping.dest for mapping in extractors[0].mappings] == ['output_tokens']
    assert len(decoded.compatibility_warnings) == 1


def test_decode_wrapped_provider_data_drops_extractor_without_usable_mappings() -> None:
    provider = _provider()
    provider['extractors'] = [
        {'root': 'usage', 'mappings': [{'path': [{'type': 'future-path'}], 'dest': 'input_tokens'}]}
    ]

    decoded = _decode_provider_data(_wrapped(provider), _registry())

    assert decoded.providers[0].extractors == []


def test_decode_wrapped_provider_data_skips_extractors_with_unsupported_root_or_array_match() -> None:
    provider = _provider()
    provider['extractors'] = [
        {'root': {'type': 'future-path'}, 'mappings': []},
        {
            'root': 'usage',
            'mappings': [
                {
                    'path': [
                        {'type': 'array-match', 'field': 'kind', 'match': {'future_match': 'tokens'}},
                        'tokens',
                    ],
                    'dest': 'input_tokens',
                },
                {'path': 'output_tokens', 'dest': 'output_tokens'},
            ],
        },
    ]

    decoded = _decode_provider_data(_wrapped(provider), _registry())

    extractors = decoded.providers[0].extractors
    assert extractors is not None
    assert [[mapping.dest for mapping in extractor.mappings] for extractor in extractors] == [['output_tokens']]
    assert [warning.split(' for ')[0] for warning in decoded.compatibility_warnings] == [
        'Unsupported extractor variant at providers[0].extractors[0].root',
        'Unsupported extractor mapping variant at providers[0].extractors[1].mappings[0].path',
    ]


def test_decode_wrapped_provider_data_supports_nested_known_matches_and_skips_unknown_nested_matches() -> None:
    provider = _provider()
    provider['model_match'] = {'or': [{'contains': 'model'}, {'equals': 'alias'}]}
    models = cast(list[object], provider['models'])
    model_a = cast(dict[str, object], models[0])
    model_a['match'] = {'or': [{'equals': 'model-a'}, {'future_match': 'model-a-alias'}]}

    decoded = _decode_provider_data(_wrapped(provider), _registry())

    assert decoded.providers[0].model_match is not None
    assert [model.id for model in decoded.providers[0].models] == ['model-b']
    assert decoded.compatibility_warnings == (
        "Unsupported match variant at providers[0].models[0].match for provider 'testing', model 'model-a'; "
        'upgrade genai-prices for full support',
    )


def test_decode_wrapped_provider_data_skips_empty_match_signature() -> None:
    provider = _provider()
    models = cast(list[object], provider['models'])
    cast(dict[str, object], models[0])['match'] = {}

    decoded = _decode_provider_data(_wrapped(provider), _registry())

    assert [model.id for model in decoded.providers[0].models] == ['model-b']
    assert len(decoded.compatibility_warnings) == 1


@pytest.mark.parametrize('target', ['provider', 'model'])
def test_decode_wrapped_provider_data_rejects_ambiguous_recognized_matches(target: str) -> None:
    provider = _provider()
    ambiguous_match = {'contains': 'model', 'equals': 'model'}
    if target == 'provider':
        provider['provider_match'] = ambiguous_match
    else:
        model = cast(dict[str, object], cast(list[object], provider['models'])[0])
        model['match'] = ambiguous_match

    with pytest.raises(ValueError, match='exactly one recognized discriminator'):
        _decode_provider_data(_wrapped(provider), _registry())


def _malformed_extractor(provider: dict[str, object]) -> None:
    provider['extractors'] = [{'root': 3, 'mappings': []}]


def _malformed_match(provider: dict[str, object]) -> None:
    provider['provider_match'] = {'equals': 3}


def _malformed_constraint(provider: dict[str, object]) -> None:
    model = cast(dict[str, object], cast(list[object], provider['models'])[0])
    model['prices'] = [{'constraint': {'start_date': 3}, 'prices': {'input_mtok': 1}}]


def _malformed_price(provider: dict[str, object]) -> None:
    model = cast(dict[str, object], cast(list[object], provider['models'])[0])
    model['prices'] = {'input_mtok': {'base': 'bad', 'tiers': []}}


def _malformed_provider_match_type(provider: dict[str, object]) -> None:
    provider['provider_match'] = 3


def _malformed_extractor_collection(provider: dict[str, object]) -> None:
    provider['extractors'] = {}


def _malformed_model_collection(provider: dict[str, object]) -> None:
    provider['models'] = {}


def _malformed_extractor_mapping_collection(provider: dict[str, object]) -> None:
    provider['extractors'] = [{'root': 'usage', 'mappings': {}}]


def _malformed_extractor_mapping(provider: dict[str, object]) -> None:
    provider['extractors'] = [{'root': 'usage', 'mappings': [3]}]


def _malformed_extractor_mapping_without_path(provider: dict[str, object]) -> None:
    provider['extractors'] = [{'root': 'usage', 'mappings': [{'dest': 'input_tokens'}]}]


def _malformed_extractor_path(provider: dict[str, object]) -> None:
    provider['extractors'] = [{'root': 'usage', 'mappings': [{'path': 3, 'dest': 'input_tokens'}]}]


def _malformed_extractor_path_step(provider: dict[str, object]) -> None:
    provider['extractors'] = [{'root': 'usage', 'mappings': [{'path': [3], 'dest': 'input_tokens'}]}]


def _malformed_array_match_without_match(provider: dict[str, object]) -> None:
    provider['extractors'] = [
        {
            'root': 'usage',
            'mappings': [
                {'path': [{'type': 'array-match', 'field': 'kind'}, 'count'], 'dest': 'input_tokens'},
            ],
        }
    ]


def _malformed_model(provider: dict[str, object]) -> None:
    provider['models'] = [3]


def _malformed_model_without_match(provider: dict[str, object]) -> None:
    model = cast(dict[str, object], cast(list[object], provider['models'])[0])
    model.pop('match')


def _malformed_model_without_prices(provider: dict[str, object]) -> None:
    model = cast(dict[str, object], cast(list[object], provider['models'])[0])
    model.pop('prices')


def _malformed_prices_type(provider: dict[str, object]) -> None:
    model = cast(dict[str, object], cast(list[object], provider['models'])[0])
    model['prices'] = 3


def _malformed_conditional_price(provider: dict[str, object]) -> None:
    model = cast(dict[str, object], cast(list[object], provider['models'])[0])
    model['prices'] = [3]


@pytest.mark.parametrize(
    ('mutate', 'error_fragment'),
    [
        (_malformed_extractor, 'extractors.0.root'),
        (_malformed_match, 'provider_match.equals'),
        (_malformed_constraint, 'start_date'),
        (_malformed_price, 'input_mtok.*base'),
        (_malformed_provider_match_type, 'provider_match'),
        (_malformed_extractor_collection, 'extractors'),
        (_malformed_model_collection, 'models'),
        (_malformed_extractor_mapping_collection, 'mappings'),
        (_malformed_extractor_mapping, 'mappings.0'),
        (_malformed_extractor_mapping_without_path, 'path'),
        (_malformed_extractor_path, 'path'),
        (_malformed_extractor_path_step, r'path.*\.0'),
        (_malformed_array_match_without_match, 'match'),
        (_malformed_model, 'models.0'),
        (_malformed_model_without_match, 'match'),
        (_malformed_prices_type, 'prices'),
        (_malformed_conditional_price, 'prices'),
    ],
)
def test_decode_wrapped_provider_data_defers_to_baseline_for_malformed_recognized_forms(
    mutate: Callable[[dict[str, object]], object], error_fragment: str
) -> None:
    provider = _provider()
    mutate(provider)

    with pytest.raises(ValueError, match=error_fragment):
        _decode_provider_data(_wrapped(provider), _registry())


def test_decode_wrapped_provider_data_preserves_baseline_default_for_missing_prices() -> None:
    provider = _provider()
    _malformed_model_without_prices(provider)

    decoded = _decode_provider_data(_wrapped(provider), _registry())

    assert decoded.providers[0].models[0].prices == []


def test_decode_wrapped_provider_data_defers_price_and_extractor_destination_validation() -> None:
    provider = _provider()
    extractors = provider['extractors']
    assert isinstance(extractors, list)
    extractor = cast(list[object], extractors)[0]
    assert isinstance(extractor, dict)
    mappings = cast(dict[str, object], extractor)['mappings']
    assert isinstance(mappings, list)
    mappings = cast(list[object], mappings)
    mappings.append({'path': 'remote_tokens', 'dest': 'remote_tokens', 'required': False})
    models = provider['models']
    assert isinstance(models, list)
    model = cast(list[object], models)[0]
    assert isinstance(model, dict)
    prices = cast(dict[str, object], model)['prices']
    assert isinstance(prices, dict)
    prices['remote_mtok'] = 5

    decoded = _decode_provider_data(_wrapped(provider), _registry())
    decoded_provider = decoded.providers[0]
    decoded_model = decoded_provider.models[0]
    assert decoded_model.prices.__dict__['remote_mtok'] == Decimal('5')
    assert decoded_provider.extractors is not None

    with pytest.warns(UserWarning, match='Unsupported price key.*remote_mtok'):
        calculation = decoded_model.calc_price(Usage(input_tokens=1), decoded_provider)
    assert calculation.total_price == Decimal('0.000001')
    with pytest.warns(UserWarning, match='Unsupported extractor destination.*remote_tokens'):
        _, usage = decoded_provider.extract_usage(
            {'usage': {'input_tokens': 1, 'output_tokens': 2, 'remote_tokens': 3}}
        )
    assert usage.input_tokens == 1
    assert usage.output_tokens == 2


def test_decode_wrapped_provider_data_leaves_malformed_non_variant_values_for_baseline() -> None:
    provider = _provider()
    provider['extractors'] = [3]

    with pytest.raises(ValueError, match='extractors.0'):
        _decode_provider_data(_wrapped(provider), _registry())


def test_decode_wrapped_provider_data_error_context_falls_back_to_indexes() -> None:
    provider = _provider()
    provider.pop('id')
    provider['provider_match'] = {'future_match': 'testing'}
    models = cast(list[object], provider['models'])
    model = cast(dict[str, object], models[0])
    model.pop('id')
    model['prices'] = {'input_mtok': {'type': 'future-price'}, 'output_mtok': 2}

    with pytest.raises(ValueError, match='id'):
        _decode_provider_data(_wrapped(provider), _registry())


def test_decode_wrapped_provider_data_leaves_non_object_provider_for_baseline() -> None:
    with pytest.raises(ValueError, match=r'providers.*\n0\n'):
        _decode_provider_data(_wrapped(3), _registry())
