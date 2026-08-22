from decimal import Decimal

from prices.price_discrepancies import prices_conflict
from prices.prices_types import ModelPrice


def test_prices_conflict_false_when_identical() -> None:
    price = ModelPrice(input_mtok=Decimal('1'), output_mtok=Decimal('2'))
    assert prices_conflict(price, price) is False


def test_prices_conflict_true_when_values_differ() -> None:
    current = ModelPrice(input_mtok=Decimal('1'), output_mtok=Decimal('2'))
    source = ModelPrice(input_mtok=Decimal('1'), output_mtok=Decimal('3'))
    assert prices_conflict(current, source) is True


def test_prices_conflict_does_not_raise_on_extra_source_key() -> None:
    """`ModelPrice` is extra='allow'; a key our YAML doesn't carry is absent, not None."""
    current = ModelPrice(input_mtok=Decimal('1'), output_mtok=Decimal('2'))
    source = ModelPrice.model_validate(
        {'input_mtok': Decimal('1'), 'output_mtok': Decimal('2'), 'output_reasoning_mtok': Decimal('5')}
    )
    assert prices_conflict(current, source) is True
