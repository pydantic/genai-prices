import os
import threading
from decimal import Decimal
from time import monotonic

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

    # fetch() does not emit a deprecation warning (only start() does).
    snapshot = UpdatePrices(url='https://example.test/prices.json').fetch()

    assert snapshot is not None
    assert snapshot.from_auto_update is True
    provider, model = snapshot.find_provider_model('gpt-4o-mini', None, 'openai', None)
    assert provider.id == 'openai'
    assert model.id == 'gpt-4o-mini'


def test_background_update_and_calc_price(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    assert data_snapshot._custom_snapshot is None
    with update_prices_in_background():
        assert wait_prices_updated_sync(timeout=5)
        assert data_snapshot._custom_snapshot is not None
        price = calc_price(Usage(input_tokens=1000, output_tokens=100), model_ref='gpt-4o', provider_id='openai')
        assert price.input_price == snapshot(Decimal('0.0025'))
        assert price.output_price == snapshot(Decimal('0.001'))
        assert price.total_price == snapshot(Decimal('0.0035'))
        assert price.provider.id == snapshot('openai')
        assert price.auto_update_timestamp is not None
    assert data_snapshot._custom_snapshot is None


async def test_wait_prices_updated_async(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    assert data_snapshot._custom_snapshot is None
    with update_prices_in_background():
        assert await wait_prices_updated_async(timeout=5)
        assert data_snapshot._custom_snapshot is not None
    assert data_snapshot._custom_snapshot is None


def test_first_wins_config(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    _mock_update_prices_get(monkeypatch)
    handle_1 = update_prices_in_background(url='https://example.test/prices.json')
    try:
        with caplog.at_level('WARNING', logger='genai-prices'):
            handle_2 = update_prices_in_background(url=DEFAULT_UPDATE_URL, update_interval=1)
        try:
            # The first caller's configuration wins; the second joins the running updater.
            assert handle_1 is not handle_2
            assert update_prices_module._updater is not None
            assert update_prices_module._updater.url == 'https://example.test/prices.json'
            assert update_prices_module._updater.update_interval == 3600
            assert any('already running' in record.message for record in caplog.records)
            assert wait_prices_updated_sync(timeout=5)
        finally:
            handle_2.close()
    finally:
        handle_1.close()
        data_snapshot.set_custom_snapshot(None)
    assert data_snapshot._custom_snapshot is None


def test_close_does_not_block_on_in_flight_fetch_and_discards_result(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
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
    monkeypatch.setattr(update_prices_module, '_STOPPED_THREAD_JOIN_TIMEOUT', 0.05)

    handle = update_prices_in_background()
    try:
        assert fetch_started.wait(timeout=5)
        (thread,) = [t for t in threading.enumerate() if t.name == 'genai_prices:update']

        start = monotonic()
        with caplog.at_level('WARNING', logger='genai-prices'):
            handle.close()
        assert monotonic() - start < 2  # did not wait for the in-flight fetch
        assert any('abandoning the daemon thread' in record.message for record in caplog.records)
        assert data_snapshot._custom_snapshot is None

        # The drained fetch completes but its snapshot is discarded by the fencing check.
        allow_fetch_return.set()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert data_snapshot._custom_snapshot is None
    finally:
        allow_fetch_return.set()
        handle.close()
        data_snapshot.set_custom_snapshot(None)


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

        handle_1.close()  # idempotent
        assert wait_prices_updated_sync(timeout=0)
        assert data_snapshot._custom_snapshot is not None

        handle_2.close()
        assert data_snapshot._custom_snapshot is None
        assert not wait_prices_updated_sync(timeout=0)
    finally:
        handle_1.close()
        handle_2.close()
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


def test_stale_handle_close_does_not_affect_new_shared_updater(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    handle_1 = update_prices_in_background()
    assert wait_prices_updated_sync(timeout=5)
    stale_updater = update_prices_module._updater
    assert stale_updater is not None

    # Fully release the first updater, then start a fresh one.
    handle_1.close()
    assert data_snapshot._custom_snapshot is None

    handle_2 = update_prices_in_background()
    try:
        assert wait_prices_updated_sync(timeout=5)
        new_updater = update_prices_module._updater
        assert new_updater is not None and new_updater is not stale_updater

        # A handle bound to the now-defunct first updater must not release handle_2's claim.
        UpdatePricesHandle(stale_updater).close()
        assert update_prices_module._updater is new_updater
        assert update_prices_module._ref_count == 1
        assert wait_prices_updated_sync(timeout=0)
        assert data_snapshot._custom_snapshot is not None
    finally:
        handle_2.close()
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
        updater = update_prices_module._updater
        assert updater is not None
        assert updater._prices_updated.wait(timeout=5)
    finally:
        with caplog.at_level('ERROR', logger='genai-prices'):
            handle.close()
        data_snapshot.set_custom_snapshot(None)
    assert any('while closing' in record.message for record in caplog.records)


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


@pytest.mark.skipif(not hasattr(os, 'fork'), reason='requires os.fork')
def test_forked_child_restarts_shared_updater(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    handle = update_prices_in_background()
    try:
        assert wait_prices_updated_sync(timeout=5)

        pid = os.fork()
        if pid == 0:
            # Child: never return into pytest - report via the exit code.
            try:
                ok = (
                    wait_prices_updated_sync(timeout=5)
                    and any(t.name == 'genai_prices:update' and t.is_alive() for t in threading.enumerate())
                    and data_snapshot._custom_snapshot is not None
                    and update_prices_module._updater is not None
                )
                os._exit(0 if ok else 1)
            except BaseException:
                os._exit(2)

        _, status = os.waitpid(pid, 0)
        assert os.waitstatus_to_exitcode(status) == 0
    finally:
        handle.close()
        data_snapshot.set_custom_snapshot(None)


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
    assert update_prices_module._updater is None
    assert update_prices_module._ref_count == 0
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


# --- Deprecated UpdatePrices shim ------------------------------------------------------------


def test_deprecated_update_prices_warns_and_routes_through_shared_updater(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    assert data_snapshot._custom_snapshot is None
    with pytest.warns(DeprecationWarning, match='update_prices_in_background'):
        with UpdatePrices() as update_prices:
            assert update_prices.wait(timeout=5)
            assert data_snapshot._custom_snapshot is not None
    assert data_snapshot._custom_snapshot is None


def test_deprecated_update_prices_multiple_instances_no_longer_raise(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    # Two distinct instances now share the one updater (first-wins) instead of raising.
    with pytest.warns(DeprecationWarning):
        with UpdatePrices():
            with UpdatePrices():
                assert wait_prices_updated_sync(timeout=5)
                assert data_snapshot._custom_snapshot is not None
    assert data_snapshot._custom_snapshot is None


def test_deprecated_update_prices_same_instance_double_start_raises(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    update_prices = UpdatePrices()
    with pytest.warns(DeprecationWarning):
        update_prices.start()
    try:
        with pytest.warns(DeprecationWarning):
            with pytest.raises(RuntimeError, match='already started'):
                update_prices.start()
    finally:
        update_prices.stop()
        data_snapshot.set_custom_snapshot(None)


@pytest.mark.default_cassette('fail.yaml')
@pytest.mark.vcr()
def test_deprecated_update_prices_wait_raises_on_failed_fetch():
    assert data_snapshot._custom_snapshot is None
    update_prices = UpdatePrices(url='https://demo-endpoints.pydantic.workers.dev/bin?status=404')
    with pytest.warns(DeprecationWarning):
        update_prices.start()
    try:
        with pytest.raises(httpx2.HTTPStatusError):
            update_prices.wait(timeout=5)
    finally:
        update_prices.stop()
    assert data_snapshot._custom_snapshot is None


@pytest.mark.default_cassette('fail.yaml')
@pytest.mark.vcr()
def test_deprecated_update_prices_stop_raises_on_failed_fetch():
    # The deprecated stop() preserves the historical behaviour of re-raising a stored fetch error.
    assert data_snapshot._custom_snapshot is None
    update_prices = UpdatePrices(url='https://demo-endpoints.pydantic.workers.dev/bin?status=404')
    with pytest.warns(DeprecationWarning):
        update_prices.start()
    with pytest.raises(httpx2.HTTPStatusError):
        update_prices.stop()
    assert data_snapshot._custom_snapshot is None


def test_deprecated_stop_on_unstarted_instance_is_noop(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    handle = update_prices_in_background()
    try:
        assert wait_prices_updated_sync(timeout=5)
        # stop() on a never-started instance does not warn and does not touch the live updater.
        UpdatePrices().stop()
        assert update_prices_module._updater is not None
        assert data_snapshot._custom_snapshot is not None
    finally:
        handle.close()
        data_snapshot.set_custom_snapshot(None)
    assert data_snapshot._custom_snapshot is None
