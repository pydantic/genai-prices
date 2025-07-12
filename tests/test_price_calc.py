from decimal import Decimal

import pytest
from inline_snapshot import snapshot

from genai_prices import Usage, calc_price_async, calc_price_sync

pytestmark = pytest.mark.anyio


def test_sync_success_with_provider():
    price = calc_price_sync(Usage(input_tokens=1000, output_tokens=100), model_ref='gpt-4o', provider_id='openai')
    assert price.price == snapshot(Decimal('0.0035'))
    assert price.model.name == snapshot('gpt 4o')
    assert price.provider.id == snapshot('openai')
    assert price.auto_update_timestamp is None


def test_sync_success_with_url():
    price = calc_price_sync(
        Usage(input_tokens=1000, output_tokens=100, cache_write_tokens=1000, cache_read_tokens=1000),
        model_ref='claude-3.5-sonnet@abc',
        provider_api_url='https://api.anthropic.com/foo/bar',
    )
    assert price.price == snapshot(Decimal('0.00855'))
    assert price.model.name == snapshot('Claude Sonnet 3.5')
    assert price.provider.name == snapshot('Anthropic')
    assert price.auto_update_timestamp is None


async def test_async_success_with_provider():
    price = await calc_price_async(
        Usage(input_tokens=1000, output_tokens=100), model_ref='gpt-4o', provider_id='openai'
    )
    assert price.price == snapshot(Decimal('0.0035'))
    assert price.model.name == snapshot('gpt 4o')
    assert price.provider.id == snapshot('openai')
    assert price.auto_update_timestamp is None


def test_tiered_prices():
    price = calc_price_sync(Usage(input_tokens=500_000), model_ref='gemini-1.5-flash', provider_id='google')
    # from providers/google.yml: (0.075 * 128000 + 0.15 * (500000 - 128000)) / 1_000_000 = 0.0654
    assert price.price == snapshot(Decimal('0.0654'))
    assert price.model.name == snapshot('gemini 1.5 flash')
    assert price.provider.id == snapshot('google')
    assert price.auto_update_timestamp is None


def test_provider_not_found():
    with pytest.raises(LookupError, match="Unable to find provider provider_id='foobar'"):
        calc_price_sync(Usage(input_tokens=500_000), model_ref='gemini-1.5-flash', provider_id='foobar')


def test_model_not_found():
    with pytest.raises(LookupError, match="Unable to find model with model_ref='wrong' in google"):
        calc_price_sync(Usage(input_tokens=500_000), model_ref='wrong', provider_id='google')
