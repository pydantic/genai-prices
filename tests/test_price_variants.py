from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from genai_prices import Usage, calc_price
from genai_prices.data_snapshot import DataSnapshot, set_custom_snapshot
from genai_prices.types import PriceCalculation, PriceContext, _providers_from_raw
from genai_prices.units import UnitRegistry
from prices import package_data, prices_types as build_types
from prices.build import load_units

USAGE = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
# below the 272K-token long-context tier OpenAI's models price separately
SHORT_CONTEXT_USAGE = Usage(input_tokens=100_000, output_tokens=100_000)


def _provider(model: dict[str, Any], *, id: str = 'testing', **extra: Any) -> dict[str, Any]:
    return {'id': id, 'name': id, 'api_pattern': id, 'models': [model], **extra}


def _model(**extra: Any) -> dict[str, Any]:
    return {
        'id': 'model',
        'match': {'equals': 'model'},
        'prices': {'input_mtok': 2, 'output_mtok': 8, 'requests_kcount': 1000},
        **extra,
    }


def _calc(
    providers: list[dict[str, Any]],
    price_context: PriceContext | None,
    *,
    provider_id: str = 'testing',
    timestamp: datetime | None = None,
) -> PriceCalculation:
    set_custom_snapshot(DataSnapshot(_providers_from_raw(providers), from_auto_update=False))
    try:
        return calc_price(
            USAGE,
            'model',
            provider_id=provider_id,
            genai_request_timestamp=timestamp,
            price_context=price_context,
        )
    finally:
        set_custom_snapshot(None)


FLEX = {'when': {'service_tier': 'flex'}, 'prices': {'input_mtok': 1, 'output_mtok': 4}}
FAST = {'when': {'service_tier': ['priority', 'fast']}, 'prices': {'input_mtok': 4, 'output_mtok': 16}}


def test_variant_overrides_only_the_keys_it_lists():
    # a null price, which the build never publishes, leaves the standard rate in place like an omitted one
    flex = {**FLEX, 'prices': {**FLEX['prices'], 'requests_kcount': None}}
    price = _calc([_provider(_model(price_variants=[flex]))], {'service_tier': 'flex'})

    # input and output at the flex rate, the request fee at the standard rate
    assert price.total_price == Decimal('6')
    assert price.price_variant is not None
    assert price.price_variant.when == {'service_tier': 'flex'}


@pytest.mark.parametrize('tier', ['priority', 'fast'])
def test_list_matches_any_of_its_values(tier: str):
    price = _calc([_provider(_model(price_variants=[FLEX, FAST]))], {'service_tier': tier})

    assert price.total_price == Decimal('21')


@pytest.mark.parametrize(
    'price_context',
    [None, {}, {'service_tier': None}, {'service_tier': 'default'}, {'service_tier': 'auto'}, {'speed': 'flex'}],
)
def test_unmatched_context_charges_standard_prices(price_context: PriceContext | None):
    price = _calc([_provider(_model(price_variants=[FLEX, FAST]))], price_context)

    assert price.total_price == Decimal('11')
    assert price.price_variant is None


def test_matching_variants_are_resolved_together_like_prices():
    """The build rejects variants that can match the same request, but newer data may have them: the last active wins."""
    later_flex = {'when': {'service_tier': ['flex', 'other']}, 'prices': {'input_mtok': 0.5}}
    price = _calc([_provider(_model(price_variants=[FLEX, later_flex]))], {'service_tier': 'flex'})

    assert price.total_price == Decimal('9.5')


def test_variant_with_only_dated_entries_applies_from_its_first_start_date():
    dated_flex = {**FLEX, 'constraint': {'start_date': '2026-01-01'}}
    cheaper_flex = {**FLEX, 'constraint': {'start_date': '2026-06-01'}, 'prices': {'input_mtok': 0.5}}
    providers = [_provider(_model(price_variants=[dated_flex, cheaper_flex]))]

    def total(day: str) -> Decimal:
        timestamp = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
        return _calc(providers, {'service_tier': 'flex'}, timestamp=timestamp).total_price

    assert total('2025-12-31') == Decimal('11')
    assert total('2026-01-01') == Decimal('6')
    # the later entry replaces the whole variant, so output falls back to the standard rate
    assert total('2026-06-01') == Decimal('9.5')


def test_variants_do_not_apply_to_models_borrowed_through_fallback():
    providers = [
        _provider(_model(price_variants=[FLEX])),
        {
            'id': 'reseller',
            'name': 'Reseller',
            'api_pattern': 'reseller',
            'models': [],
            'fallback_model_providers': ['testing'],
        },
    ]

    assert _calc(providers, {'service_tier': 'flex'}, provider_id='testing').total_price == Decimal('6')
    reseller = _calc(providers, {'service_tier': 'flex'}, provider_id='reseller')
    assert reseller.total_price == Decimal('11')
    assert reseller.price_variant is None


@pytest.mark.parametrize(
    'when',
    [
        {'service_tier': 'flex', 'speed': 'fast'},
        {'service_tier': True},
        {'service_tier': {'any_of': ['flex']}},
        {'service_tier': [1, None]},
        {},
    ],
    ids=['unknown-parameter', 'bool-value', 'object-value', 'non-string-list', 'empty'],
)
def test_when_shapes_from_newer_data_never_match(when: dict[str, Any]):
    """A newer feed can add `when` parameters or value types; this version must parse it and charge standard prices."""
    variant = {'when': when, 'prices': {'input_mtok': 1}}
    price = _calc([_provider(_model(price_variants=[variant]))], {'service_tier': 'flex'})

    assert price.total_price == Decimal('11')


def test_extracted_usage_and_get_prices_accept_price_context():
    [provider] = _providers_from_raw([_provider(_model(price_variants=[FLEX]))])
    [model] = provider.models
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)

    assert model.get_prices(timestamp, price_context={'service_tier': 'flex'}) != model.get_prices(timestamp)
    calculation = model.calc_price(USAGE, provider, price_context={'service_tier': 'flex'})
    assert calculation.total_price == Decimal('6')
    assert 'price_variant=PriceVariant(' in repr(calculation)


@pytest.mark.parametrize(
    'model_ref, price_context, expected',
    [
        # gpt-5.4 per 1M tokens: $2.50 in / $15 out standard, flex $1.25 / $7.50, fast $5 / $30
        ('gpt-5.4', None, Decimal('1.75')),
        ('gpt-5.4', {'service_tier': 'flex'}, Decimal('0.875')),
        ('gpt-5.4', {'service_tier': 'priority'}, Decimal('3.5')),
        ('gpt-5.4', {'service_tier': 'fast'}, Decimal('3.5')),
        ('gpt-5.4', {'service_tier': 'default'}, Decimal('1.75')),
        # gpt-5.4-nano has no fast rates
        ('gpt-5.4-nano', {'service_tier': 'priority'}, Decimal('0.145')),
    ],
)
def test_openai_service_tier_prices(model_ref: str, price_context: PriceContext | None, expected: Decimal):
    price = calc_price(SHORT_CONTEXT_USAGE, model_ref, provider_id='openai', price_context=price_context)

    assert price.total_price == expected


def test_openai_tier_rates_start_with_the_current_standard_rates():
    """gpt-5.6-sol's flex rates are only published for its prices from 2026-08-21, so earlier requests pay standard."""

    def total(timestamp: datetime) -> Decimal:
        return calc_price(
            SHORT_CONTEXT_USAGE,
            'gpt-5.6-sol',
            provider_id='openai',
            genai_request_timestamp=timestamp,
            price_context={'service_tier': 'flex'},
        ).total_price

    assert total(datetime(2026, 8, 20, tzinfo=timezone.utc)) == Decimal('3.5')
    assert total(datetime(2026, 8, 21, tzinfo=timezone.utc)) == Decimal('1.2')


def _build_model(**extra: Any) -> build_types.ModelInfo:
    return build_types.ModelInfo.model_validate({'id': 'model', 'match': {'equals': 'model'}, **extra})


DATED_PRICES = [
    {'prices': {'input_mtok': 2}},
    {'constraint': {'start_date': '2026-06-01'}, 'prices': {'input_mtok': 1}},
]


INVALID_VARIANTS: list[tuple[Any, list[Any], str]] = [
    ({'input_mtok': 2}, [], '`price_variants` may not be empty'),
    ({'input_mtok': 2}, [{'when': {}, 'prices': {'input_mtok': 1}}], 'at least 1 item'),
    (
        {'input_mtok': 2},
        [{'when': {'batch': 'yes'}, 'prices': {'input_mtok': 1}}],
        "Input should be 'service_tier'",
    ),
    ({'input_mtok': 2}, [{'when': {'service_tier': []}, 'prices': {'input_mtok': 1}}], 'at least one value'),
    (
        {'input_mtok': 2},
        [{'when': {'service_tier': ['flex', 'flex']}, 'prices': {'input_mtok': 1}}],
        'each only once',
    ),
    ({'input_mtok': 2}, [{'when': {'service_tier': 'flex'}, 'prices': {}}], 'needs at least one price'),
    ({'input_mtok': 2}, [FLEX, FLEX], 'needs one entry without a constraint'),
    (
        {'input_mtok': 2},
        [{**FLEX, 'constraint': {'start_time': '00:00:00Z', 'end_time': '08:00:00Z'}}],
        'needs one entry without a constraint',
    ),
    (
        {'input_mtok': 2},
        [{**FLEX, 'constraint': {'start_date': '2026-06-01'}}, FLEX],
        'unconstrained first, then by ascending `start_date`',
    ),
    (
        {'input_mtok': 2},
        [{**FLEX, 'constraint': {'start_date': '2026-06-01'}}, {**FLEX, 'constraint': {'start_date': '2026-01-01'}}],
        'unconstrained first, then by ascending `start_date`',
    ),
    (
        {'input_mtok': 2},
        [
            {**FLEX, 'constraint': {'start_date': '2026-06-01'}},
            {**FLEX, 'constraint': {'start_time': '00:00:00Z', 'end_time': '08:00:00Z'}},
        ],
        'or only entries with a `start_date`',
    ),
    (
        {'input_mtok': 2},
        [FLEX, {'when': {'service_tier': ['priority', 'flex']}, 'prices': {'input_mtok': 1}}],
        "`when: {service_tier: flex}` and `when: {service_tier: ['priority', 'flex']}` can match the same request",
    ),
    (DATED_PRICES, [FLEX], 'must repeat the constraints used by `prices`, missing: start_date=2026-06-01'),
    (
        DATED_PRICES,
        [{**FLEX, 'constraint': {'start_date': '2026-01-01'}}],
        'missing: start_date=2026-06-01',
    ),
]


@pytest.mark.parametrize('prices, price_variants, error', INVALID_VARIANTS)
def test_build_rejects_invalid_price_variants(prices: Any, price_variants: list[Any], error: str):
    with pytest.raises(ValidationError, match=re.escape(error)):
        _build_model(prices=prices, price_variants=price_variants)


@pytest.mark.parametrize(
    'price_variants',
    [
        [
            FLEX,
            {**FLEX, 'constraint': {'start_date': '2026-06-01'}},
            {**FAST, 'constraint': {'start_date': '2026-06-01'}},
        ],
        # starting on or after the dated change, only the changes from then on need repeating
        [{**FLEX, 'constraint': {'start_date': '2026-06-01'}}],
        [{**FLEX, 'constraint': {'start_date': '2026-07-01'}}],
    ],
)
def test_build_accepts_variants_repeating_the_dated_standard_prices(price_variants: list[Any]):
    assert _build_model(prices=DATED_PRICES, price_variants=price_variants).price_variants


def test_package_data_validates_variant_prices_laid_over_the_standard_prices():
    registry = UnitRegistry(load_units())
    valid = _build_model(
        prices=DATED_PRICES, price_variants=[FLEX, {**FLEX, 'constraint': {'start_date': '2026-06-01'}}]
    )
    package_data.validate_provider_model_prices(
        [build_types.Provider(id='testing', name='Testing', api_pattern='testing', models=[valid])], registry
    )

    # a cached-input price needs an input price, which neither the variant nor the standard prices has
    model = _build_model(
        prices={'output_mtok': 2}, price_variants=[{'when': {'service_tier': 'flex'}, 'prices': {'cache_read_mtok': 1}}]
    )
    provider = build_types.Provider(id='testing', name='Testing', api_pattern='testing', models=[model])

    with pytest.raises(ValueError, match=re.escape('testing/model.price_variants[0] over prices: Missing ancestor')):
        package_data.validate_provider_model_prices([provider], registry)
