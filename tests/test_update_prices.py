import os
import threading
from decimal import Decimal
from time import monotonic

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


def test_ref_counted_across_instances(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    up1 = UpdatePrices()
    up2 = UpdatePrices()
    up1.start()
    up2.start()
    try:
        assert wait_prices_updated_sync(timeout=5)
        assert data_snapshot._custom_snapshot is not None

        # Releasing one claim keeps the updater alive for the other.
        up1.stop()
        assert wait_prices_updated_sync(timeout=0)
        assert data_snapshot._custom_snapshot is not None

        up1.stop()  # idempotent no-op
        assert data_snapshot._custom_snapshot is not None

        up2.stop()
        assert data_snapshot._custom_snapshot is None
        assert not wait_prices_updated_sync(timeout=0)
    finally:
        up1.stop()
        up2.stop()
        data_snapshot.set_custom_snapshot(None)


def test_first_wins_config(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    _mock_update_prices_get(monkeypatch)
    up1 = UpdatePrices(url='https://example.test/prices.json')
    up1.start()
    try:
        with caplog.at_level('WARNING', logger='genai-prices'):
            up2 = UpdatePrices(url=DEFAULT_UPDATE_URL, update_interval=1)
            up2.start()
        try:
            # The first instance's configuration wins; the second joins the running updater.
            assert update_prices_module._updater is not None
            assert update_prices_module._updater.url == 'https://example.test/prices.json'
            assert update_prices_module._updater.update_interval == 3600
            assert any('already running' in record.message for record in caplog.records)
            assert wait_prices_updated_sync(timeout=5)
        finally:
            up2.stop()
    finally:
        up1.stop()
        data_snapshot.set_custom_snapshot(None)
    assert data_snapshot._custom_snapshot is None


def test_double_start_same_instance_raises(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    update_prices = UpdatePrices()
    update_prices.start()
    try:
        with pytest.raises(RuntimeError, match='already started'):
            update_prices.start()
    finally:
        update_prices.stop()
        data_snapshot.set_custom_snapshot(None)


def test_stop_on_unstarted_instance_is_noop(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    with UpdatePrices() as update_prices:
        assert update_prices.wait(timeout=5)
        # stop() on a never-started instance does not touch the live updater.
        UpdatePrices().stop()
        assert update_prices_module._updater is not None
        assert data_snapshot._custom_snapshot is not None
    assert data_snapshot._custom_snapshot is None


def test_restopping_does_not_affect_a_new_updater(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    up1 = UpdatePrices()
    up1.start()
    assert wait_prices_updated_sync(timeout=5)
    stale_updater = update_prices_module._updater
    up1.stop()
    assert data_snapshot._custom_snapshot is None

    up2 = UpdatePrices()
    up2.start()
    try:
        assert wait_prices_updated_sync(timeout=5)
        new_updater = update_prices_module._updater
        assert new_updater is not None and new_updater is not stale_updater

        # up1 was already released; stopping it again must not release up2's claim.
        up1.stop()
        assert update_prices_module._updater is new_updater
        assert update_prices_module._ref_count == 1
        assert data_snapshot._custom_snapshot is not None
    finally:
        up2.stop()
        data_snapshot.set_custom_snapshot(None)
    assert data_snapshot._custom_snapshot is None


def test_stop_does_not_block_on_in_flight_fetch_and_discards_result(
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

    update_prices = UpdatePrices()
    update_prices.start()
    try:
        assert fetch_started.wait(timeout=5)
        (thread,) = [t for t in threading.enumerate() if t.name == 'genai_prices:update']

        start = monotonic()
        with caplog.at_level('WARNING', logger='genai-prices'):
            update_prices.stop()
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
        update_prices.stop()
        data_snapshot.set_custom_snapshot(None)


def test_waiter_gets_false_when_stop_discards_in_flight_fetch(monkeypatch: pytest.MonkeyPatch):
    # A fetch discarded by the stop fence must not be reported to waiters as a successful update.
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

    update_prices = UpdatePrices()
    update_prices.start()
    try:
        assert fetch_started.wait(timeout=5)
        # A waiter that captured the updater before stop() observes this instance directly.
        updater = update_prices_module._updater
        assert updater is not None

        update_prices.stop()  # sets the stop fence and reverts before the fetch returns
        allow_fetch_return.set()  # the in-flight fetch now completes but must be discarded

        # The background loop signals the event but must report the discarded fetch as not-updated.
        assert updater._prices_updated.wait(timeout=5)
        assert updater._update_succeeded is False
        assert updater._wait_updated(0) is False
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


@pytest.mark.skipif(not hasattr(os, 'fork'), reason='requires os.fork')
def test_forked_child_restarts_shared_updater(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    update_prices = UpdatePrices()
    update_prices.start()
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
        update_prices.stop()
        data_snapshot.set_custom_snapshot(None)


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
