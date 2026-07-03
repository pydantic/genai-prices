from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any

import pytest

from genai_prices import Usage, calc_price
from genai_prices.data_snapshot import DataSnapshot, set_custom_snapshot
from genai_prices.types import (
    ClauseEquals,
    ConditionalPrice,
    ConditionOperators,
    ModelInfo,
    ModelPrice,
    Provider,
)

pytestmark = pytest.mark.anyio


@contextmanager
def _snapshot_with_prices(prices: Any) -> Iterator[None]:
    snapshot = DataSnapshot(
        providers=[
            Provider(
                id='testing',
                name='Testing',
                api_pattern='testing',
                models=[ModelInfo(id='cond', match=ClauseEquals('cond'), prices=prices)],
            )
        ],
        from_auto_update=False,
    )
    try:
        set_custom_snapshot(snapshot)
        yield
    finally:
        set_custom_snapshot(None)


def _calc(price_context: dict[str, Any] | None = None) -> Any:
    return calc_price(
        Usage(input_tokens=1_000_000, output_tokens=1_000_000),
        model_ref='cond',
        provider_id='testing',
        price_context=price_context,
    )


def test_when_selects_matching_entry() -> None:
    prices = [
        ConditionalPrice(
            when={'service_tier': 'batch'},
            values=ModelPrice(input_mtok=Decimal('1'), output_mtok=Decimal('2')),
        ),
        ConditionalPrice(values=ModelPrice(input_mtok=Decimal('2'), output_mtok=Decimal('4'))),
    ]
    with _snapshot_with_prices(prices):
        batch = _calc({'service_tier': 'batch'})
        assert batch.total_price == Decimal('3')
        assert batch.price_context == {'service_tier': 'batch'}

        default = _calc({'service_tier': 'standard'})
        assert default.total_price == Decimal('6')

        no_context = _calc()
        assert no_context.total_price == Decimal('6')


def test_per_unit_fall_through() -> None:
    # Only output_mtok changes under batch; input_mtok falls through to the default entry.
    prices = [
        ConditionalPrice(when={'service_tier': 'batch'}, values=ModelPrice(output_mtok=Decimal('1'))),
        ConditionalPrice(values=ModelPrice(input_mtok=Decimal('2'), output_mtok=Decimal('4'))),
    ]
    with _snapshot_with_prices(prices):
        batch = _calc({'service_tier': 'batch'})
        # input from default (2), output from batch entry (1)
        assert batch.input_price == Decimal('2')
        assert batch.output_price == Decimal('1')
        assert batch.total_price == Decimal('3')


def test_unlisted_unit_is_zero() -> None:
    # cache_read_mtok is never priced by any entry -> zero, no crash.
    prices = [
        ConditionalPrice(values=ModelPrice(input_mtok=Decimal('2'), output_mtok=Decimal('4'))),
    ]
    with _snapshot_with_prices(prices):
        result = calc_price(
            Usage(input_tokens=1_000_000, cache_read_tokens=500_000, output_tokens=1_000_000),
            model_ref='cond',
            provider_id='testing',
        )
        assert result.total_price == Decimal('6')


def test_in_operator() -> None:
    prices = [
        ConditionalPrice(
            when={'region': ConditionOperators(in_=['us-east-1', 'us-west-2'])},
            values=ModelPrice(input_mtok=Decimal('1'), output_mtok=Decimal('1')),
        ),
        ConditionalPrice(values=ModelPrice(input_mtok=Decimal('5'), output_mtok=Decimal('5'))),
    ]
    with _snapshot_with_prices(prices):
        assert _calc({'region': 'us-east-1'}).total_price == Decimal('2')
        assert _calc({'region': 'eu-west-1'}).total_price == Decimal('10')


def test_range_operator() -> None:
    prices = [
        ConditionalPrice(
            when={'inference_geo': ConditionOperators(gte=10, lte=20)},
            values=ModelPrice(input_mtok=Decimal('1'), output_mtok=Decimal('1')),
        ),
        ConditionalPrice(values=ModelPrice(input_mtok=Decimal('5'), output_mtok=Decimal('5'))),
    ]
    with _snapshot_with_prices(prices):
        assert _calc({'inference_geo': 15}).total_price == Decimal('2')
        assert _calc({'inference_geo': 25}).total_price == Decimal('10')
        assert _calc({'inference_geo': 5}).total_price == Decimal('10')


def test_bool_condition_type_strict() -> None:
    # 1 must not match a boolean True condition.
    prices = [
        ConditionalPrice(when={'batch': True}, values=ModelPrice(input_mtok=Decimal('1'), output_mtok=Decimal('1'))),
        ConditionalPrice(values=ModelPrice(input_mtok=Decimal('5'), output_mtok=Decimal('5'))),
    ]
    with _snapshot_with_prices(prices):
        assert _calc({'batch': True}).total_price == Decimal('2')
        assert _calc({'batch': 1}).total_price == Decimal('10')
        assert _calc({'batch': False}).total_price == Decimal('10')


def test_from_raw_when_values_json() -> None:
    from genai_prices.types import _providers_from_raw

    raw = [
        {
            'id': 'testing',
            'name': 'Testing',
            'api_pattern': 'testing',
            'models': [
                {
                    'id': 'cond',
                    'match': {'equals': 'cond'},
                    'prices': [
                        {'when': {'region': {'in': ['us-east-1']}}, 'values': {'input_mtok': 1, 'output_mtok': 1}},
                        {'values': {'input_mtok': 5, 'output_mtok': 5}},
                    ],
                }
            ],
        }
    ]
    providers = _providers_from_raw(raw)
    snapshot = DataSnapshot(providers=providers, from_auto_update=False)
    try:
        set_custom_snapshot(snapshot)
        assert _calc({'region': 'us-east-1'}).total_price == Decimal('2')
        assert _calc({'region': 'eu-west-1'}).total_price == Decimal('10')
    finally:
        set_custom_snapshot(None)
