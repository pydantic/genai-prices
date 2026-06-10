import threading
from decimal import Decimal

import httpx2
import pytest
from inline_snapshot import snapshot

from genai_prices import (
    UpdatePrices,
    UpdatePricesHandle,
    Usage,
    calc_price,
    data_snapshot,
    update_prices as update_prices_module,
    update_prices_in_background,
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

    def fake_get(url: str, timeout: httpx2.Timeout) -> Response:
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

    monkeypatch.setattr(httpx2, 'get', fake_get)
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
        with pytest.raises(httpx2.HTTPStatusError):
            update_prices.wait()
    assert data_snapshot._custom_snapshot is None


@pytest.mark.default_cassette('fail.yaml')
@pytest.mark.vcr()
def test_update_prices_failed_stop():
    assert data_snapshot._custom_snapshot is None
    update_prices = UpdatePrices(url='https://demo-endpoints.pydantic.workers.dev/bin?status=404')
    update_prices.start()
    with pytest.raises(httpx2.HTTPStatusError):
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


def test_update_prices_in_background_inert_when_manual_updater_running(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    _mock_update_prices_get(monkeypatch)
    with UpdatePrices():
        with caplog.at_level('INFO', logger='genai-prices'):
            handle = update_prices_in_background()
        assert any('returning an inert handle' in record.message for record in caplog.records)
        assert wait_prices_updated_sync(timeout=5)
        assert data_snapshot._custom_snapshot is not None

        handle.close()
        assert wait_prices_updated_sync(timeout=0)
        assert data_snapshot._custom_snapshot is not None
    assert data_snapshot._custom_snapshot is None


def test_update_prices_in_background_ref_count(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    handle_1 = update_prices_in_background()
    handle_2 = update_prices_in_background()
    try:
        assert handle_1 is not handle_2
        assert wait_prices_updated_sync(timeout=5)
        assert data_snapshot._custom_snapshot is not None

        handle_1.close()
        assert wait_prices_updated_sync(timeout=0)
        assert data_snapshot._custom_snapshot is not None

        handle_1.close()
        assert wait_prices_updated_sync(timeout=0)
        assert data_snapshot._custom_snapshot is not None

        handle_2.close()
        assert data_snapshot._custom_snapshot is None
        assert not wait_prices_updated_sync(timeout=0)
    finally:
        handle_1.close()
        handle_2.close()
        data_snapshot.set_custom_snapshot(None)


def test_manual_start_takes_over_shared_updater(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    _mock_update_prices_get(monkeypatch)
    handle = update_prices_in_background()
    try:
        assert wait_prices_updated_sync(timeout=5)
        with caplog.at_level('INFO', logger='genai-prices'):
            with UpdatePrices() as manual:
                manual.wait(timeout=5)
                assert data_snapshot._custom_snapshot is not None
                assert update_prices_module._global_update_prices is manual
                assert update_prices_module._managed_update_prices is None

                # the pre-takeover handle is inert: closing it does not stop the manual updater
                handle.close()
                assert data_snapshot._custom_snapshot is not None
                assert update_prices_module._global_update_prices is manual
        assert any('takes over' in record.message for record in caplog.records)
        assert data_snapshot._custom_snapshot is None
        assert not [t for t in threading.enumerate() if t.name == 'genai_prices:update']
    finally:
        handle.close()
        data_snapshot.set_custom_snapshot(None)


def test_background_updater_restarts_after_manual_takeover_stops(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    handle_1 = update_prices_in_background()
    try:
        assert wait_prices_updated_sync(timeout=5)
        with UpdatePrices():
            pass
        assert data_snapshot._custom_snapshot is None

        handle_2 = update_prices_in_background()
        try:
            assert wait_prices_updated_sync(timeout=5)
            assert data_snapshot._custom_snapshot is not None
        finally:
            handle_2.close()
        assert data_snapshot._custom_snapshot is None
    finally:
        handle_1.close()
        data_snapshot.set_custom_snapshot(None)


def test_update_prices_handle_directly_constructed_is_inert(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    handle = update_prices_in_background()
    try:
        assert wait_prices_updated_sync(timeout=5)

        UpdatePricesHandle().close()
        assert wait_prices_updated_sync(timeout=0)
        assert data_snapshot._custom_snapshot is not None
    finally:
        handle.close()
        data_snapshot.set_custom_snapshot(None)
    assert data_snapshot._custom_snapshot is None


def test_update_prices_handle_close_does_not_raise_after_failed_fetch(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    def fake_get(*_args: object, **_kwargs: object) -> object:
        raise httpx2.ConnectError('network down')

    monkeypatch.setattr(httpx2, 'get', fake_get)
    handle = update_prices_in_background()
    try:
        # Wait on the internal event rather than wait_prices_updated_sync, which would
        # consume the stored exception that close() is expected to log instead of raise.
        updater = update_prices_module._managed_update_prices
        assert updater is not None
        assert updater._prices_updated.wait(timeout=5)
    finally:
        with caplog.at_level('ERROR', logger='genai-prices'):
            handle.close()
        data_snapshot.set_custom_snapshot(None)
    assert any('while closing' in record.message for record in caplog.records)


def test_update_prices_in_background_disabled_by_env_var(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv('GENAI_PRICES_DISABLE_AUTO_UPDATE', '1')

    def fail_get(*_args: object, **_kwargs: object) -> object:
        raise AssertionError('no network requests should be made')

    monkeypatch.setattr(httpx2, 'get', fail_get)
    handle = update_prices_in_background()
    assert not wait_prices_updated_sync(timeout=0)
    assert data_snapshot._custom_snapshot is None
    handle.close()
    assert data_snapshot._custom_snapshot is None


def test_disable_env_var_does_not_affect_manual_update_prices(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv('GENAI_PRICES_DISABLE_AUTO_UPDATE', '1')
    _mock_update_prices_get(monkeypatch)
    with UpdatePrices() as update_prices:
        assert update_prices.wait(timeout=5)
        assert data_snapshot._custom_snapshot is not None
    assert data_snapshot._custom_snapshot is None


def test_wait_prices_updated_sync_returns_false_on_failed_fetch(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    def fake_get(*_args: object, **_kwargs: object) -> object:
        raise httpx2.ConnectError('network down')

    monkeypatch.setattr(httpx2, 'get', fake_get)
    handle = update_prices_in_background()
    try:
        # Never raises and returns False on failure, for every waiter — not just the first.
        assert wait_prices_updated_sync(timeout=5) is False
        assert wait_prices_updated_sync(timeout=0) is False
        assert data_snapshot._custom_snapshot is None
    finally:
        with caplog.at_level('ERROR', logger='genai-prices'):
            handle.close()
        data_snapshot.set_custom_snapshot(None)
    # The stored exception is not consumed by the waiters above, so close() still logs it.
    assert any('while closing' in record.message for record in caplog.records)


def test_stale_handle_close_does_not_affect_new_shared_updater(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    handle_1 = update_prices_in_background()
    try:
        assert wait_prices_updated_sync(timeout=5)
        with UpdatePrices():
            pass

        handle_2 = update_prices_in_background()
        try:
            assert wait_prices_updated_sync(timeout=5)
            new_updater = update_prices_module._managed_update_prices
            assert new_updater is not None

            # handle_1 is bound to the pre-takeover updater: closing it while a different
            # shared updater is live must not release handle_2's claim.
            handle_1.close()
            assert update_prices_module._managed_update_prices is new_updater
            assert update_prices_module._managed_update_prices_ref_count == 1
            assert wait_prices_updated_sync(timeout=0)
            assert data_snapshot._custom_snapshot is not None
        finally:
            handle_2.close()
        assert data_snapshot._custom_snapshot is None
    finally:
        handle_1.close()
        data_snapshot.set_custom_snapshot(None)


def test_stop_on_unstarted_instance_is_noop(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    with UpdatePrices() as update_prices:
        assert update_prices.wait(timeout=5)
        UpdatePrices().stop()
        assert update_prices_module._global_update_prices is update_prices
        assert data_snapshot._custom_snapshot is not None
    assert data_snapshot._custom_snapshot is None


def test_update_prices_in_background_concurrent_acquire_close(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    barrier = threading.Barrier(16)
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            barrier.wait(timeout=5)
            for _ in range(10):
                handle = update_prices_in_background()
                handle.close()
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
    assert update_prices_module._global_update_prices is None
    assert update_prices_module._managed_update_prices is None
    assert update_prices_module._managed_update_prices_ref_count == 0
    assert not [t for t in threading.enumerate() if t.name == 'genai_prices:update']
    assert data_snapshot._custom_snapshot is None

    # The shared updater can still be acquired cleanly after the churn.
    handle = update_prices_in_background()
    try:
        assert wait_prices_updated_sync(timeout=5)
        assert data_snapshot._custom_snapshot is not None
    finally:
        handle.close()
        data_snapshot.set_custom_snapshot(None)
