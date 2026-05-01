import genai_prices
from genai_prices import UpdatePrices, Usage, calc_price, wait_prices_updated_async, wait_prices_updated_sync


def test_top_level_exports_remain_stable() -> None:
    assert genai_prices.__all__ == (
        'Usage',
        'calc_price',
        'UpdatePrices',
        'wait_prices_updated_sync',
        'wait_prices_updated_async',
        '__version__',
    )
    assert genai_prices.Usage is Usage
    assert genai_prices.calc_price is calc_price
    assert genai_prices.UpdatePrices is UpdatePrices
    assert genai_prices.wait_prices_updated_sync is wait_prices_updated_sync
    assert genai_prices.wait_prices_updated_async is wait_prices_updated_async
    assert isinstance(genai_prices.__version__, str)
