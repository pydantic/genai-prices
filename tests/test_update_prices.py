import concurrent.futures
import threading
from decimal import Decimal
from time import monotonic, sleep

import httpx2
import pytest
from inline_snapshot import snapshot

from genai_prices import (
    UpdatePrices,
    Usage,
    calc_price,
    data_snapshot,
    update_prices as update_prices_module,
    wait_prices_updated_async,
    wait_prices_updated_sync,
)
from genai_prices.update_prices import DEFAULT_UPDATE_URL

pytestmark = pytest.mark.anyio

PROVIDER_ARRAY_PAYLOAD = (
    b'[{"id":"openai","name":"OpenAI","api_pattern":"https://api\\\\.openai\\\\.com",'
    b'"models":[{"id":"gpt-4o","match":{"equals":"gpt-4o"},'
    b'"prices":{"input_mtok":2.5,"output_mtok":10}}]}]'
)


class NullUpdatePrices(UpdatePrices):
    def fetch(self) -> data_snapshot.DataSnapshot | None:
        return None


class CountingNullUpdatePrices(UpdatePrices):
    count = 0

    def fetch(self) -> data_snapshot.DataSnapshot | None:
        self.count += 1
        return None


def _mock_update_prices_get(monkeypatch: pytest.MonkeyPatch, content: bytes = PROVIDER_ARRAY_PAYLOAD) -> None:
    class Response:
        def __init__(self, content: bytes) -> None:
            self.content = content

        def raise_for_status(self) -> None:
            pass

    def fake_get(url: str, timeout: httpx2.Timeout) -> Response:
        assert url in {
            'https://example.test/prices.json',
            DEFAULT_UPDATE_URL,
        }
        assert timeout is not None
        return Response(content)

    monkeypatch.setattr(httpx2, 'get', fake_get)


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
    assert data_snapshot._custom_snapshot is None


def test_wait_prices_updated_sync(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    assert data_snapshot._custom_snapshot is None
    with UpdatePrices():
        assert wait_prices_updated_sync(timeout=5)
        assert data_snapshot._custom_snapshot is not None
    assert data_snapshot._custom_snapshot is None


async def test_wait_prices_updated_async(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    assert data_snapshot._custom_snapshot is None
    with UpdatePrices():
        assert await wait_prices_updated_async(timeout=5)
        assert data_snapshot._custom_snapshot is not None
    assert data_snapshot._custom_snapshot is None


def test_wait_prices_updated_sync_without_active_updater():
    assert wait_prices_updated_sync(timeout=0) is False


def test_update_prices_start_waits_and_rejects_second_start():
    update_prices = NullUpdatePrices(update_interval=3600)
    update_prices.start(wait=True)
    try:
        assert data_snapshot._custom_snapshot is None
        with pytest.raises(RuntimeError, match='UpdatePrices background task already started'):
            update_prices.start()
    finally:
        update_prices.stop()


def test_update_prices_continues_after_interval_until_stopped():
    update_prices = CountingNullUpdatePrices(update_interval=0.001)
    update_prices.start(wait=True)
    try:
        deadline = monotonic() + 1
        while update_prices.count < 2 and monotonic() < deadline:
            sleep(0.01)
        assert update_prices.count >= 2
    finally:
        update_prices.stop()


def test_update_prices_stop_clears_snapshot_after_in_flight_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    fetch_started = threading.Event()
    allow_fetch_return = threading.Event()

    class Response:
        content = PROVIDER_ARRAY_PAYLOAD

        def raise_for_status(self) -> None:
            pass

    def fake_get(url: str, timeout: httpx2.Timeout) -> Response:
        assert url == DEFAULT_UPDATE_URL
        assert timeout is not None
        fetch_started.set()
        assert allow_fetch_return.wait(timeout=5)
        return Response()

    monkeypatch.setattr(httpx2, 'get', fake_get)
    update_prices = UpdatePrices()
    update_prices.start()
    try:
        assert fetch_started.wait(timeout=5)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            stop_future = executor.submit(update_prices.stop)
            assert update_prices._stop_event.wait(timeout=5)
            allow_fetch_return.set()
            stop_future.result(timeout=5)
        assert data_snapshot._custom_snapshot is None
    finally:
        allow_fetch_return.set()
        update_prices.stop()
        data_snapshot.set_custom_snapshot(None)


@pytest.mark.default_cassette('fail.yaml')
@pytest.mark.vcr()
def test_wait_raises_on_failed_fetch():
    assert data_snapshot._custom_snapshot is None
    with UpdatePrices(url='https://demo-endpoints.pydantic.workers.dev/bin?status=404') as update_prices:
        with pytest.raises(httpx2.HTTPStatusError):
            update_prices.wait(timeout=5)
    assert data_snapshot._custom_snapshot is None


def test_stop_logs_and_does_not_raise_after_failed_fetch(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    def fake_get(*_args: object, **_kwargs: object) -> object:
        raise httpx2.ConnectError('network down')

    monkeypatch.setattr(httpx2, 'get', fake_get)
    update_prices = UpdatePrices()
    update_prices.start()
    try:
        # Wait on the internal event rather than wait(), which would consume and raise the stored
        # exception that stop() is expected to log instead.
        updater = update_prices_module._updater
        assert updater is not None
        assert updater._prices_updated.wait(timeout=5)
    finally:
        with caplog.at_level('ERROR', logger='genai-prices'):
            update_prices.stop()  # never raises
        data_snapshot.set_custom_snapshot(None)
    assert any('while stopping' in record.message for record in caplog.records)


def test_wait_prices_updated_sync_returns_false_on_failed_fetch(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    def fake_get(*_args: object, **_kwargs: object) -> object:
        raise httpx2.ConnectError('network down')

    monkeypatch.setattr(httpx2, 'get', fake_get)
    update_prices = UpdatePrices()
    update_prices.start()
    try:
        # Never raises and returns False on failure, for every waiter — not just the first.
        assert wait_prices_updated_sync(timeout=5) is False
        assert wait_prices_updated_sync(timeout=0) is False
        assert data_snapshot._custom_snapshot is None
    finally:
        with caplog.at_level('ERROR', logger='genai-prices'):
            update_prices.stop()
        data_snapshot.set_custom_snapshot(None)
    # The stored exception is not consumed by the waiters above, so stop() still logs it.
    assert any('while stopping' in record.message for record in caplog.records)


def test_concurrent_start_stop(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    barrier = threading.Barrier(16)
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            barrier.wait(timeout=5)
            for _ in range(10):
                update_prices = UpdatePrices()
                update_prices.start()
                update_prices.stop()
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(16)]
    try:
        for thread in threads:
            thread.start()
    finally:
        for thread in threads:
            thread.join(timeout=30)

    assert not [t for t in threads if t.is_alive()]
    assert not errors
    assert update_prices_module._updater is None
    assert update_prices_module._ref_count == 0
    assert not [t for t in threading.enumerate() if t.name == 'genai_prices:update']
    assert data_snapshot._custom_snapshot is None

    # The shared updater can still be acquired cleanly after the churn.
    update_prices = UpdatePrices()
    update_prices.start()
    try:
        assert wait_prices_updated_sync(timeout=5)
        assert data_snapshot._custom_snapshot is not None
    finally:
        update_prices.stop()
        data_snapshot.set_custom_snapshot(None)
