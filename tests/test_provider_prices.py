from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any

import pytest

from genai_prices import Usage, calc_price
from genai_prices.data_snapshot import DataSnapshot, set_custom_snapshot
from genai_prices.types import (
    ClauseEquals,
    ClauseStartsWith,
    ConditionalPrice,
    ModelInfo,
    ModelPrice,
    Provider,
)

pytestmark = pytest.mark.anyio


@contextmanager
def _snapshot(provider_prices: Any, model_prices: Any, model_id: str = 'gpt-x') -> Iterator[None]:
    snapshot = DataSnapshot(
        providers=[
            Provider(
                id='testing',
                name='Testing',
                api_pattern='testing',
                prices=provider_prices,
                models=[ModelInfo(id=model_id, match=ClauseEquals(model_id), prices=model_prices)],
            )
        ],
        from_auto_update=False,
    )
    try:
        set_custom_snapshot(snapshot)
        yield
    finally:
        set_custom_snapshot(None)


def _calc(model_ref: str = 'gpt-x') -> Any:
    return calc_price(
        Usage(input_tokens=1_000_000, output_tokens=1_000_000),
        model_ref=model_ref,
        provider_id='testing',
    )


def test_model_inherits_provider_price() -> None:
    # Model prices only output; input comes from the provider-level price.
    with _snapshot(
        provider_prices=ModelPrice(input_mtok=Decimal('7')),
        model_prices=ModelPrice(output_mtok=Decimal('3')),
    ):
        result = _calc()
        assert result.input_price == Decimal('7')
        assert result.output_price == Decimal('3')
        assert result.total_price == Decimal('10')


def test_model_overrides_provider_price() -> None:
    with _snapshot(
        provider_prices=ModelPrice(input_mtok=Decimal('7'), output_mtok=Decimal('9')),
        model_prices=ModelPrice(input_mtok=Decimal('2')),
    ):
        result = _calc()
        # input from model (2, overriding provider 7), output inherited from provider (9)
        assert result.input_price == Decimal('2')
        assert result.output_price == Decimal('9')


def test_provider_model_matching_when() -> None:
    provider_prices = [
        ConditionalPrice(
            when={'model': ClauseStartsWith('gpt-5')},
            values=ModelPrice(input_mtok=Decimal('25')),
        ),
        ConditionalPrice(values=ModelPrice(input_mtok=Decimal('10'))),
    ]
    with _snapshot(
        provider_prices=provider_prices, model_prices=ModelPrice(output_mtok=Decimal('1')), model_id='gpt-5-turbo'
    ):
        result = _calc('gpt-5-turbo')
        assert result.input_price == Decimal('25')

    with _snapshot(
        provider_prices=provider_prices, model_prices=ModelPrice(output_mtok=Decimal('1')), model_id='gpt-4o'
    ):
        result = _calc('gpt-4o')
        assert result.input_price == Decimal('10')


def test_no_provider_prices_unchanged() -> None:
    with _snapshot(provider_prices=[], model_prices=ModelPrice(input_mtok=Decimal('2'), output_mtok=Decimal('4'))):
        result = _calc()
        assert result.total_price == Decimal('6')


def test_provider_prices_from_raw_json() -> None:
    from genai_prices.types import _providers_from_raw

    raw = [
        {
            'id': 'testing',
            'name': 'Testing',
            'api_pattern': 'testing',
            'prices': [
                {'when': {'model': {'starts_with': 'gpt-5'}}, 'values': {'input_mtok': 25}},
                {'values': {'input_mtok': 10}},
            ],
            'models': [
                {'id': 'gpt-5-turbo', 'match': {'equals': 'gpt-5-turbo'}, 'prices': {'output_mtok': 1}},
            ],
        }
    ]
    snapshot = DataSnapshot(providers=_providers_from_raw(raw), from_auto_update=False)
    try:
        set_custom_snapshot(snapshot)
        result = _calc('gpt-5-turbo')
        assert result.input_price == Decimal('25')
        assert result.output_price == Decimal('1')
    finally:
        set_custom_snapshot(None)


def test_build_schema_accepts_provider_model_matching_prices() -> None:
    from prices.prices_types import providers_schema

    raw = [
        {
            'id': 'testing',
            'name': 'Testing',
            'api_pattern': 'testing',
            'prices': [
                {'when': {'model': {'starts_with': 'gpt-5'}}, 'values': {'input_mtok': 25}},
                {'values': {'input_mtok': 10, 'output_mtok': 5}},
            ],
            'models': [{'id': 'gpt-5-turbo', 'match': {'equals': 'gpt-5-turbo'}, 'prices': {'output_mtok': 1}}],
        }
    ]
    providers = providers_schema.validate_python(raw)
    assert isinstance(providers[0].prices, list)


def test_build_schema_rejects_provider_prices_without_unconditional() -> None:
    import pytest as _pytest

    from prices.prices_types import providers_schema

    raw = [
        {
            'id': 'testing',
            'name': 'Testing',
            'api_pattern': 'testing',
            'prices': [{'when': {'model': {'starts_with': 'gpt-5'}}, 'values': {'input_mtok': 25}}],
            'models': [{'id': 'gpt-5-turbo', 'match': {'equals': 'gpt-5-turbo'}, 'prices': {'output_mtok': 1}}],
        }
    ]
    with _pytest.raises(ValueError, match='exactly one price must be unconditional'):
        providers_schema.validate_python(raw)
