from decimal import Decimal

import httpx
import pytest
from inline_snapshot import snapshot

from genai_prices import (
    UpdatePrices,
    Usage,
    calc_price,
    data_snapshot,
    wait_prices_updated_async,
    wait_prices_updated_sync,
)

pytestmark = pytest.mark.anyio


def test_update_prices_fetch_borrows_active_registry_for_provider_array(monkeypatch: pytest.MonkeyPatch):
    active_registry = data_snapshot.get_snapshot().unit_registry
    content = (
        b'[{"id":"openai","name":"OpenAI","api_pattern":"https://api\\\\.openai\\\\.com",'
        b'"models":[{"id":"gpt-4o-mini","match":{"equals":"gpt-4o-mini"},'
        b'"prices":{"input_mtok":0.15,"output_mtok":0.6}}]}]'
    )

    class Response:
        def __init__(self, content: bytes) -> None:
            self.content = content

        def raise_for_status(self) -> None:
            pass

    def fake_get(url: str, timeout: httpx.Timeout) -> Response:
        assert url == 'https://example.test/prices.json'
        assert timeout is not None
        return Response(content)

    monkeypatch.setattr(httpx, 'get', fake_get)

    snapshot = UpdatePrices(url='https://example.test/prices.json').fetch()

    assert snapshot is not None
    assert snapshot.from_auto_update is True
    assert snapshot.unit_registry is active_registry


@pytest.mark.default_cassette('success.yaml')
@pytest.mark.vcr()
def test_update_prices_wait_on_start():
    assert data_snapshot._custom_snapshot is None
    with UpdatePrices() as update_prices:
        assert data_snapshot._custom_snapshot is None
        update_prices.wait()
        assert data_snapshot._custom_snapshot is not None
        price = calc_price(Usage(input_tokens=1000, output_tokens=100), model_ref='gpt-4o', provider_id='openai')
        assert price.input_price == snapshot(Decimal('0.0025'))
        assert price.output_price == snapshot(Decimal('0.001'))
        assert price.total_price == snapshot(Decimal('0.0035'))
        assert price.provider.id == snapshot('openai')
        assert price.auto_update_timestamp is not None


@pytest.mark.default_cassette('success.yaml')
@pytest.mark.vcr()
def test_wait_prices_updated_sync():
    assert data_snapshot._custom_snapshot is None
    with UpdatePrices():
        assert data_snapshot._custom_snapshot is None
        wait_prices_updated_sync()
        assert data_snapshot._custom_snapshot is not None
        price = calc_price(Usage(input_tokens=1000, output_tokens=100), model_ref='gpt-4o', provider_id='openai')
        assert price.input_price == snapshot(Decimal('0.0025'))
        assert price.output_price == snapshot(Decimal('0.001'))
        assert price.total_price == snapshot(Decimal('0.0035'))
        assert price.provider.id == snapshot('openai')
        assert price.auto_update_timestamp is not None


@pytest.mark.default_cassette('success.yaml')
@pytest.mark.vcr()
async def test_wait_prices_updated_async():
    assert data_snapshot._custom_snapshot is None
    with UpdatePrices():
        assert data_snapshot._custom_snapshot is None
        await wait_prices_updated_async()
        assert data_snapshot._custom_snapshot is not None
        price = calc_price(Usage(input_tokens=1000, output_tokens=100), model_ref='gpt-4o', provider_id='openai')
        assert price.input_price == snapshot(Decimal('0.0025'))
        assert price.output_price == snapshot(Decimal('0.001'))
        assert price.total_price == snapshot(Decimal('0.0035'))
        assert price.provider.id == snapshot('openai')
        assert price.auto_update_timestamp is not None


@pytest.mark.default_cassette('fail.yaml')
@pytest.mark.vcr()
def test_update_prices_failed():
    assert data_snapshot._custom_snapshot is None
    with UpdatePrices(url='https://demo-endpoints.pydantic.workers.dev/bin?status=404') as update_prices:
        with pytest.raises(httpx.HTTPStatusError):
            update_prices.wait()
    assert data_snapshot._custom_snapshot is None


@pytest.mark.default_cassette('fail.yaml')
@pytest.mark.vcr()
def test_update_prices_failed_stop():
    assert data_snapshot._custom_snapshot is None
    update_prices = UpdatePrices(url='https://demo-endpoints.pydantic.workers.dev/bin?status=404')
    update_prices.start()
    with pytest.raises(httpx.HTTPStatusError):
        update_prices.stop()
    assert data_snapshot._custom_snapshot is None


@pytest.mark.default_cassette('success.yaml')
@pytest.mark.vcr()
def test_update_prices_multiple():
    with UpdatePrices():
        with pytest.raises(
            RuntimeError,
            match='UpdatePrices global task already started, only one UpdatePrices can be active at a time',
        ):
            with UpdatePrices():
                pass
