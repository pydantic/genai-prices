from decimal import Decimal

import pytest
from inline_snapshot import snapshot

import genai_prices.sources
from genai_prices import Usage, calc_price_async, calc_price_sync, prefetch_async, prefetch_sync

pytestmark = pytest.mark.anyio


@pytest.mark.default_cassette('default.yaml')
@pytest.mark.vcr()
def test_sync_auto_update():
    assert genai_prices.sources._cached_auto_update_snapshot is None
    price = calc_price_sync(
        Usage(input_tokens=1000, output_tokens=100), model_ref='gpt-4o', provider_id='openai', auto_update=True
    )
    assert price.price == snapshot(Decimal('0.0035'))
    assert price.provider.id == snapshot('openai')

    assert genai_prices.sources._cached_auto_update_snapshot is not None


@pytest.mark.default_cassette('default.yaml')
@pytest.mark.vcr()
def test_sync_prefetch():
    assert genai_prices.sources._cached_auto_update_snapshot is None
    assert genai_prices.sources.auto_update_sync_source._pre_fetch_task is None

    prefetch_sync()

    assert genai_prices.sources.auto_update_sync_source._pre_fetch_task is not None

    price = calc_price_sync(
        Usage(input_tokens=1000, output_tokens=100), model_ref='gpt-4o', provider_id='openai', auto_update=True
    )
    assert price.price == snapshot(Decimal('0.0035'))
    assert price.provider.id == snapshot('openai')

    assert genai_prices.sources._cached_auto_update_snapshot is not None
    assert genai_prices.sources.auto_update_sync_source._pre_fetch_task is None


@pytest.mark.default_cassette('default.yaml')
@pytest.mark.vcr()
async def test_async_auto_update():
    assert genai_prices.sources._cached_auto_update_snapshot is None
    price = await calc_price_async(
        Usage(input_tokens=1000, output_tokens=100), model_ref='gpt-4o', provider_id='openai', auto_update=True
    )
    assert price.price == snapshot(Decimal('0.0035'))
    assert price.provider.id == snapshot('openai')

    assert genai_prices.sources._cached_auto_update_snapshot is not None


@pytest.mark.default_cassette('default.yaml')
@pytest.mark.vcr()
async def test_async_prefetch():
    assert genai_prices.sources._cached_auto_update_snapshot is None
    assert genai_prices.sources.auto_update_async_source._pre_fetch_task is None

    prefetch_async()

    assert genai_prices.sources.auto_update_async_source._pre_fetch_task is not None

    price = await calc_price_async(
        Usage(input_tokens=1000, output_tokens=100), model_ref='gpt-4o', provider_id='openai', auto_update=True
    )
    assert price.price == snapshot(Decimal('0.0035'))
    assert price.provider.id == snapshot('openai')

    assert genai_prices.sources._cached_auto_update_snapshot is not None
    assert genai_prices.sources.auto_update_async_source._pre_fetch_task is None
