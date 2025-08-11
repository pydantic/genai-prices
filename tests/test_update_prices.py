from decimal import Decimal

import httpx
import pytest
from inline_snapshot import snapshot

from genai_prices import UpdatePrices, Usage, calc, calc_price, wait_prices_updated_async, wait_prices_updated_sync

pytestmark = pytest.mark.anyio


@pytest.mark.default_cassette('success.yaml')
@pytest.mark.vcr()
def test_update_prices_wait_on_start():
    assert calc._custom_snapshot is None
    with UpdatePrices(wait_on_start=True):
        assert calc._custom_snapshot is not None
        price = calc_price(Usage(input_tokens=1000, output_tokens=100), model_ref='gpt-4o', provider_id='openai')
        assert price.input_price == snapshot(Decimal('0.0025'))
        assert price.output_price == snapshot(Decimal('0.001'))
        assert price.total_price == snapshot(Decimal('0.0035'))
        assert price.provider.id == snapshot('openai')
        assert price.auto_update_timestamp is not None


@pytest.mark.default_cassette('success.yaml')
@pytest.mark.vcr()
def test_wait_prices_updated_sync():
    assert calc._custom_snapshot is None
    with UpdatePrices():
        assert calc._custom_snapshot is None
        wait_prices_updated_sync()
        assert calc._custom_snapshot is not None
        price = calc_price(Usage(input_tokens=1000, output_tokens=100), model_ref='gpt-4o', provider_id='openai')
        assert price.input_price == snapshot(Decimal('0.0025'))
        assert price.output_price == snapshot(Decimal('0.001'))
        assert price.total_price == snapshot(Decimal('0.0035'))
        assert price.provider.id == snapshot('openai')
        assert price.auto_update_timestamp is not None


@pytest.mark.default_cassette('success.yaml')
@pytest.mark.vcr()
async def test_wait_prices_updated_async():
    assert calc._custom_snapshot is None
    with UpdatePrices():
        assert calc._custom_snapshot is None
        await wait_prices_updated_async()
        assert calc._custom_snapshot is not None
        price = calc_price(Usage(input_tokens=1000, output_tokens=100), model_ref='gpt-4o', provider_id='openai')
        assert price.input_price == snapshot(Decimal('0.0025'))
        assert price.output_price == snapshot(Decimal('0.001'))
        assert price.total_price == snapshot(Decimal('0.0035'))
        assert price.provider.id == snapshot('openai')
        assert price.auto_update_timestamp is not None


@pytest.mark.default_cassette('fail.yaml')
@pytest.mark.vcr()
def test_update_prices_failed():
    assert calc._custom_snapshot is None
    with pytest.raises(httpx.HTTPStatusError):
        with UpdatePrices(wait_on_start=True, url='https://demo-endpoints.pydantic.workers.dev/bin?status=404'):
            assert calc._custom_snapshot is not None


@pytest.mark.default_cassette('fail.yaml')
@pytest.mark.vcr()
def test_update_prices_failed_stop():
    assert calc._custom_snapshot is None
    update_prices = UpdatePrices(url='https://demo-endpoints.pydantic.workers.dev/bin?status=404')
    update_prices.start()
    with pytest.raises(httpx.HTTPStatusError):
        update_prices.stop()
    assert calc._custom_snapshot is None
