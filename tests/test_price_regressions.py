from decimal import Decimal

import pytest

from genai_prices import Usage
from genai_prices.types import ModelPrice, Tier, TieredPrices

pytestmark = pytest.mark.anyio


def test_model_price_registry_decomposition_charges_unpriced_descendants_through_parent() -> None:
    price = ModelPrice(input_mtok=Decimal('5'), output_mtok=Decimal('10')).calc_price(
        Usage(input_tokens=700, input_audio_tokens=200, output_tokens=70, output_audio_tokens=20)
    )

    assert price == {
        'input_price': Decimal('0.0035'),
        'output_price': Decimal('0.0007'),
        'total_price': Decimal('0.0042'),
    }


def test_tiered_price_regression_uses_provided_input_token_threshold() -> None:
    price = ModelPrice(
        output_mtok=TieredPrices(base=Decimal('1'), tiers=[Tier(start=100_000, price=Decimal('2'))])
    ).calc_price(Usage(input_tokens=100_000, input_audio_tokens=200_000, output_tokens=10_000))

    assert price == {
        'input_price': Decimal('0'),
        'output_price': Decimal('0.01'),
        'total_price': Decimal('0.01'),
    }
