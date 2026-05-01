from decimal import Decimal

import pytest

from genai_prices import Usage
from genai_prices.types import ModelPrice

pytestmark = pytest.mark.anyio


def test_model_price_decomposition_matches_current_text_cache_pricing() -> None:
    price = ModelPrice(
        input_mtok=Decimal('2'),
        cache_write_mtok=Decimal('0.5'),
        cache_read_mtok=Decimal('0.25'),
        output_mtok=Decimal('10'),
    ).calc_price(Usage(input_tokens=1_000, cache_write_tokens=20, cache_read_tokens=30, output_tokens=100))

    assert price == {
        'input_price': Decimal('0.0019175'),
        'output_price': Decimal('0.001'),
        'total_price': Decimal('0.0029175'),
    }


def test_standard_price_parity_handles_simple_input_output_tokens() -> None:
    price = ModelPrice(input_mtok=Decimal('1.25'), output_mtok=Decimal('3')).calc_price(
        Usage(input_tokens=2_000, output_tokens=500)
    )

    assert price == {
        'input_price': Decimal('0.0025'),
        'output_price': Decimal('0.0015'),
        'total_price': Decimal('0.0040'),
    }


def test_standard_price_parity_handles_cache_read_write_tokens() -> None:
    price = ModelPrice(
        input_mtok=Decimal('2'),
        cache_write_mtok=Decimal('0.5'),
        cache_read_mtok=Decimal('0.25'),
    ).calc_price(Usage(input_tokens=1_000, cache_write_tokens=200, cache_read_tokens=300))

    assert price == {
        'input_price': Decimal('0.001175'),
        'output_price': Decimal('0'),
        'total_price': Decimal('0.001175'),
    }


def test_model_price_decomposition_handles_audio_cache_overlap() -> None:
    price = ModelPrice(
        input_mtok=Decimal('1'),
        cache_read_mtok=Decimal('2'),
        input_audio_mtok=Decimal('3'),
        cache_audio_read_mtok=Decimal('4'),
    ).calc_price(
        Usage(
            input_tokens=1_000,
            cache_read_tokens=400,
            input_audio_tokens=300,
            cache_audio_read_tokens=100,
        )
    )

    assert price == {
        'input_price': Decimal('0.002'),
        'output_price': Decimal('0'),
        'total_price': Decimal('0.002'),
    }


def test_overlap_price_parity_handles_cached_audio_overlap() -> None:
    price = ModelPrice(
        input_mtok=Decimal('1'),
        cache_read_mtok=Decimal('0.25'),
        input_audio_mtok=Decimal('2'),
        cache_audio_read_mtok=Decimal('0.5'),
    ).calc_price(
        Usage(
            input_tokens=1_000,
            cache_read_tokens=400,
            input_audio_tokens=300,
            cache_audio_read_tokens=100,
        )
    )

    assert price == {
        'input_price': Decimal('0.000925'),
        'output_price': Decimal('0'),
        'total_price': Decimal('0.000925'),
    }


def test_model_price_decomposition_handles_output_audio() -> None:
    price = ModelPrice(output_mtok=Decimal('5'), output_audio_mtok=Decimal('10')).calc_price(
        Usage(output_tokens=700, output_audio_tokens=200)
    )

    assert price == {
        'input_price': Decimal('0'),
        'output_price': Decimal('0.0045'),
        'total_price': Decimal('0.0045'),
    }


def test_overlap_price_parity_handles_output_audio() -> None:
    price = ModelPrice(output_mtok=Decimal('5'), output_audio_mtok=Decimal('9')).calc_price(
        Usage(output_tokens=800, output_audio_tokens=300)
    )

    assert price == {
        'input_price': Decimal('0'),
        'output_price': Decimal('0.0052'),
        'total_price': Decimal('0.0052'),
    }


def test_model_price_prices_requests_only_in_total() -> None:
    price = ModelPrice(requests_kcount=Decimal('12')).calc_price(Usage(input_tokens=1_000))

    assert price == {
        'input_price': Decimal('0'),
        'output_price': Decimal('0'),
        'total_price': Decimal('0.012'),
    }


def test_request_price_regression_counts_one_request_per_price_calculation() -> None:
    price = ModelPrice(requests_kcount=Decimal('12')).calc_price(Usage(input_tokens=1_000, output_tokens=500))

    assert price == {
        'input_price': Decimal('0'),
        'output_price': Decimal('0'),
        'total_price': Decimal('0.012'),
    }


def test_request_price_regression_contributes_only_to_total_price() -> None:
    price = ModelPrice(input_mtok=Decimal('1'), requests_kcount=Decimal('12')).calc_price(Usage(input_tokens=1_000))

    assert price == {
        'input_price': Decimal('0.001'),
        'output_price': Decimal('0'),
        'total_price': Decimal('0.013'),
    }
