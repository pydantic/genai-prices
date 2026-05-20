import threading
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

PROVIDER_ARRAY_PAYLOAD = (
    b'[{"id":"openai","name":"OpenAI","api_pattern":"https://api\\\\.openai\\\\.com",'
    b'"models":[{"id":"gpt-4o","match":{"equals":"gpt-4o"},'
    b'"prices":{"input_mtok":2.5,"output_mtok":10}}]}]'
)


def _mock_update_prices_get(monkeypatch: pytest.MonkeyPatch, content: bytes = PROVIDER_ARRAY_PAYLOAD) -> None:
    class Response:
        def __init__(self, content: bytes) -> None:
            self.content = content

        def raise_for_status(self) -> None:
            pass

    def fake_get(url: str, timeout: httpx.Timeout) -> Response:
        assert url in {
            'https://example.test/prices.json',
            'https://raw.githubusercontent.com/pydantic/genai-prices/refs/heads/main/prices/data.json',
        }
        assert timeout is not None
        return Response(content)

    monkeypatch.setattr(httpx, 'get', fake_get)


def test_update_prices_fetch_parses_provider_array(monkeypatch: pytest.MonkeyPatch):
    content = (
        b'[{"id":"openai","name":"OpenAI","api_pattern":"https://api\\\\.openai\\\\.com",'
        b'"models":[{"id":"gpt-4o-mini","match":{"equals":"gpt-4o-mini"},'
        b'"prices":{"input_mtok":0.15,"output_mtok":0.6}}]}]'
    )

    _mock_update_prices_get(monkeypatch, content)

    snapshot = UpdatePrices(url='https://example.test/prices.json').fetch()

    assert snapshot is not None
    assert snapshot.from_auto_update is True
    provider, model = snapshot.find_provider_model('gpt-4o-mini', None, 'openai', None)
    assert provider.id == 'openai'
    assert model.id == 'gpt-4o-mini'


def test_update_prices_wait_on_start(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    assert data_snapshot._custom_snapshot is None
    with UpdatePrices() as update_prices:
        update_prices.wait()
        assert data_snapshot._custom_snapshot is not None
        price = calc_price(Usage(input_tokens=1000, output_tokens=100), model_ref='gpt-4o', provider_id='openai')
        assert price.input_price == snapshot(Decimal('0.0025'))
        assert price.output_price == snapshot(Decimal('0.001'))
        assert price.total_price == snapshot(Decimal('0.0035'))
        assert price.provider.id == snapshot('openai')
        assert price.auto_update_timestamp is not None


def test_wait_prices_updated_sync(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    assert data_snapshot._custom_snapshot is None
    with UpdatePrices():
        wait_prices_updated_sync()
        assert data_snapshot._custom_snapshot is not None
        price = calc_price(Usage(input_tokens=1000, output_tokens=100), model_ref='gpt-4o', provider_id='openai')
        assert price.input_price == snapshot(Decimal('0.0025'))
        assert price.output_price == snapshot(Decimal('0.001'))
        assert price.total_price == snapshot(Decimal('0.0035'))
        assert price.provider.id == snapshot('openai')
        assert price.auto_update_timestamp is not None


async def test_wait_prices_updated_async(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    assert data_snapshot._custom_snapshot is None
    with UpdatePrices():
        await wait_prices_updated_async()
        assert data_snapshot._custom_snapshot is not None
        price = calc_price(Usage(input_tokens=1000, output_tokens=100), model_ref='gpt-4o', provider_id='openai')
        assert price.input_price == snapshot(Decimal('0.0025'))
        assert price.output_price == snapshot(Decimal('0.001'))
        assert price.total_price == snapshot(Decimal('0.0035'))
        assert price.provider.id == snapshot('openai')
        assert price.auto_update_timestamp is not None


def test_update_prices_stop_clears_snapshot_after_in_flight_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    fetch_started = threading.Event()
    allow_fetch_return = threading.Event()
    stop_errors: list[BaseException] = []

    class Response:
        content = PROVIDER_ARRAY_PAYLOAD

        def raise_for_status(self) -> None:
            pass

    def fake_get(url: str, timeout: httpx.Timeout) -> Response:
        assert url == 'https://example.test/prices.json'
        assert timeout is not None
        fetch_started.set()
        assert allow_fetch_return.wait(timeout=5)
        return Response()

    def stop_update_prices(update_prices: UpdatePrices) -> None:
        try:
            update_prices.stop()
        except BaseException as exc:
            stop_errors.append(exc)

    monkeypatch.setattr(httpx, 'get', fake_get)
    update_prices = UpdatePrices(url='https://example.test/prices.json', update_interval=3600)
    update_prices.start()
    try:
        assert fetch_started.wait(timeout=5)

        stop_thread = threading.Thread(target=stop_update_prices, args=(update_prices,))
        stop_thread.start()
        assert update_prices._stop_event.wait(timeout=5)
        allow_fetch_return.set()
        stop_thread.join(timeout=5)

        assert not stop_thread.is_alive()
        if stop_errors:
            raise stop_errors[0]
        assert data_snapshot._custom_snapshot is None
    finally:
        allow_fetch_return.set()
        update_prices.stop()
        data_snapshot.set_custom_snapshot(None)


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


def test_update_prices_multiple(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    with UpdatePrices():
        with pytest.raises(
            RuntimeError,
            match='UpdatePrices global task already started, only one UpdatePrices can be active at a time',
        ):
            with UpdatePrices():
                pass
