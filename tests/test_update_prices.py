from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
import traceback
from collections.abc import Callable
from decimal import Decimal

import httpx2
import pytest
from inline_snapshot import snapshot
from pydantic import ValidationError

import genai_prices.update_prices as update_prices_module
from genai_prices import (
    UpdatePrices,
    Usage,
    calc_price,
    data_snapshot,
    wait_prices_updated_async,
    wait_prices_updated_sync,
)
from genai_prices.units import _get_registry
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


def _mock_update_prices_get(
    monkeypatch: pytest.MonkeyPatch,
    content: bytes = PROVIDER_ARRAY_PAYLOAD,
    expected_url: str | None = None,
) -> None:
    class Response:
        def __init__(self, content: bytes) -> None:
            self.content = content

        def raise_for_status(self) -> None:
            pass

    def fake_get(url: str, timeout: httpx2.Timeout) -> Response:
        if expected_url is None:
            assert url in {'https://example.test/prices.json', DEFAULT_UPDATE_URL}
        else:
            assert url == expected_url
        assert timeout is not None
        return Response(content)

    monkeypatch.setattr(httpx2, 'get', fake_get)


def test_update_prices_fetch_preserves_registry_when_provider_parsing_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    previous = _get_registry()
    _mock_update_prices_get(
        monkeypatch, b'[{"id":"missing-required-fields"}]', expected_url='https://example.test/prices.json'
    )

    with pytest.raises(ValidationError):
        UpdatePrices(url='https://example.test/prices.json').fetch()

    assert _get_registry() is previous


def test_update_prices_fetch_rejects_non_array_payload_without_registry_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = _get_registry()
    _mock_update_prices_get(monkeypatch, b'{"providers":[]}', expected_url='https://example.test/prices.json')

    with pytest.raises(ValueError, match='Expected fetched prices payload to be a provider array'):
        UpdatePrices(url='https://example.test/prices.json').fetch()

    assert _get_registry() is previous


def test_update_prices_fetch_parses_provider_array_without_registry_change(monkeypatch: pytest.MonkeyPatch) -> None:
    bundled = _get_registry()
    _mock_update_prices_get(monkeypatch, expected_url='https://example.test/prices.json')

    prices = UpdatePrices(url='https://example.test/prices.json').fetch()

    assert prices is not None
    assert prices.from_auto_update is True
    provider, model = prices.find_provider_model('gpt-4o', None, 'openai', None)
    assert provider.id == 'openai'
    assert model.id == 'gpt-4o'
    assert _get_registry() is bundled


def test_update_prices_fetch_provider_array_warns_for_invalid_extractor_without_state_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundled = _get_registry()
    previous_snapshot = data_snapshot.DataSnapshot([], from_auto_update=False)
    data_snapshot.set_custom_snapshot(previous_snapshot)
    providers_json = (
        '[{"id":"broken","name":"Broken","api_pattern":"https://broken\\\\.example",'
        '"extractors":[{"root":"usage","mappings":['
        '{"path":"tokens","dest":"imaginary_tokens","required":false}]}],"models":[]}]'
    )
    _mock_update_prices_get(monkeypatch, providers_json.encode(), expected_url='https://example.test/prices.json')

    try:
        with pytest.warns(
            UserWarning,
            match='Unsupported extractor destination for standard extraction: imaginary_tokens',
        ):
            prices = UpdatePrices(url='https://example.test/prices.json').fetch()

        assert prices is not None
        assert prices.find_provider(None, 'broken', None).id == 'broken'
        assert _get_registry() is bundled
        assert data_snapshot._custom_snapshot is previous_snapshot
    finally:
        data_snapshot.set_custom_snapshot(None)


def test_update_prices_fetch_provider_array_does_not_eagerly_validate_unused_model_prices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    providers_json = (
        '[{"id":"testing","name":"Testing","api_pattern":"https://testing\\\\.example",'
        '"models":[{"id":"unused-invalid-price","match":{"equals":"unused-invalid-price"},'
        '"prices":{"cache_image_write_mtok":1}}]}]'
    )
    _mock_update_prices_get(monkeypatch, providers_json.encode(), expected_url='https://example.test/prices.json')

    prices = UpdatePrices(url='https://example.test/prices.json').fetch()

    assert prices is not None
    _, model = prices.find_provider_model('unused-invalid-price', None, 'testing', None)
    assert model.id == 'unused-invalid-price'


def test_update_prices_context_manager_updates_and_restores_snapshot(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    assert data_snapshot._custom_snapshot is None

    with UpdatePrices() as update_prices:
        assert update_prices.wait(timeout=5)
        price = calc_price(Usage(input_tokens=1000, output_tokens=100), model_ref='gpt-4o', provider_id='openai')
        assert price.total_price == snapshot(Decimal('0.0035'))
        assert price.auto_update_timestamp is not None

    assert data_snapshot._custom_snapshot is None


def test_wait_prices_updated_sync(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    with UpdatePrices():
        assert wait_prices_updated_sync(timeout=5)

    assert wait_prices_updated_sync(timeout=0) is False


def test_unstarted_instance_wait_returns_false():
    assert UpdatePrices().wait(timeout=0) is False


async def test_wait_prices_updated_async(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    with UpdatePrices():
        assert await wait_prices_updated_async(timeout=5)


def test_distinct_instances_share_ownership(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    first = UpdatePrices()
    second = UpdatePrices()
    first.start(wait=True)
    second.start()

    try:
        first.stop()
        # Releasing the same instance twice must not release the second owner's claim.
        first.stop()
        assert data_snapshot._custom_snapshot is not None
    finally:
        first.stop()
        second.stop()

    assert data_snapshot._custom_snapshot is None


@pytest.mark.parametrize(
    'make_update_prices',
    [
        pytest.param(lambda: UpdatePrices(url='https://example.test/prices.json'), id='url'),
        pytest.param(lambda: UpdatePrices(update_interval=1), id='update-interval'),
        pytest.param(lambda: UpdatePrices(request_timeout=httpx2.Timeout(1)), id='request-timeout'),
    ],
)
def test_different_configuration_is_rejected(
    monkeypatch: pytest.MonkeyPatch, make_update_prices: Callable[[], UpdatePrices]
):
    _mock_update_prices_get(monkeypatch)
    with UpdatePrices():
        with pytest.raises(RuntimeError, match='already started with different configuration'):
            make_update_prices().start()


def test_same_instance_cannot_start_twice():
    update_prices = NullUpdatePrices()
    update_prices.start(wait=True)
    try:
        with pytest.raises(RuntimeError, match='background task already started'):
            update_prices.start()
    finally:
        update_prices.stop()


def test_thread_start_failure_does_not_acquire_ownership(monkeypatch: pytest.MonkeyPatch):
    update_prices = NullUpdatePrices()

    def fail(_thread: threading.Thread) -> None:
        raise RuntimeError('start failed')

    with monkeypatch.context() as context:
        context.setattr(threading.Thread, 'start', fail)
        with pytest.raises(RuntimeError, match='start failed'):
            update_prices.start()

    update_prices.start(wait=True)
    update_prices.stop()


def test_overridden_fetch_drives_shared_updater(monkeypatch: pytest.MonkeyPatch) -> None:
    first = NullUpdatePrices()
    second = CountingNullUpdatePrices()
    calls = 0

    def fetch() -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(first, 'fetch', fetch)
    first.start(wait=True)
    second.start()
    try:
        assert calls == 1
        assert second.wait(timeout=0)
        assert second.count == 0
    finally:
        first.stop()
        second.stop()


def test_update_prices_continues_after_interval_until_stopped():
    second_fetch = threading.Event()

    class SecondFetchUpdatePrices(CountingNullUpdatePrices):
        def fetch(self) -> data_snapshot.DataSnapshot | None:
            result = super().fetch()
            if self.count >= 2:
                second_fetch.set()
            return result

    update_prices = SecondFetchUpdatePrices(update_interval=0.001)
    update_prices.start()
    try:
        assert second_fetch.wait(timeout=5)
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
    assert update_prices._worker is not None
    worker = update_prices._worker
    waiter_started = threading.Event()
    original_wait = worker.wait

    def tracked_wait(timeout: float | None) -> bool:
        waiter_started.set()
        return original_wait(timeout)

    monkeypatch.setattr(worker, 'wait', tracked_wait)
    try:
        assert fetch_started.wait(timeout=5)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            stop_future = executor.submit(update_prices.stop)
            assert worker.stop_event.wait(timeout=5)
            wait_future = executor.submit(wait_prices_updated_sync, 5)
            # Ensure this waiter captured the still-published worker before stop() can clear it.
            assert waiter_started.wait(timeout=5)
            allow_fetch_return.set()
            stop_future.result(timeout=5)
            # The fetch that stop() discarded was never installed, so it must not report an update.
            assert wait_future.result(timeout=5) is False
        assert data_snapshot._custom_snapshot is None
    finally:
        allow_fetch_return.set()
        update_prices.stop()
        data_snapshot.set_custom_snapshot(None)


def test_start_waits_for_in_flight_shutdown() -> None:
    fetch_started = threading.Event()
    allow_fetch_return = threading.Event()

    class BlockingUpdatePrices(UpdatePrices):
        def fetch(self) -> data_snapshot.DataSnapshot | None:
            fetch_started.set()
            assert allow_fetch_return.wait(timeout=5)
            return None

    first = BlockingUpdatePrices()
    second = NullUpdatePrices()
    first.start()
    assert fetch_started.wait(timeout=5)
    assert first._worker is not None
    worker = first._worker

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        stop_future = executor.submit(first.stop)
        assert worker.stop_event.wait(timeout=5)
        start_future = executor.submit(second.start)
        allow_fetch_return.set()
        stop_future.result(timeout=5)
        start_future.result(timeout=5)

    # The new start must have waited for shutdown and launched a fresh worker of its own.
    assert second._worker is not None
    assert second._worker is not worker
    assert not worker.thread.is_alive()
    second.stop()


def test_stop_does_not_deadlock_when_fetch_reenters_start() -> None:
    fetch_started = threading.Event()
    allow_reentry = threading.Event()
    other = NullUpdatePrices()

    class ReentrantUpdatePrices(UpdatePrices):
        def fetch(self) -> data_snapshot.DataSnapshot | None:
            fetch_started.set()
            assert allow_reentry.wait(timeout=5)
            with pytest.raises(RuntimeError, match='cannot call start from its worker'):
                other.start()
            return None

    update_prices = ReentrantUpdatePrices()
    update_prices.start()
    assert update_prices._worker is not None
    worker = update_prices._worker
    assert fetch_started.wait(timeout=5)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            stop_future = executor.submit(update_prices.stop)
            assert worker.stop_event.wait(timeout=5)
            allow_reentry.set()
            stop_future.result(timeout=5)

        # The rejected re-entrant claim must not poison a normal restart after shutdown.
        other.start(wait=True)
    finally:
        allow_reentry.set()
        update_prices.stop()
        other.stop()


def test_fetch_cannot_change_its_own_ownership() -> None:
    class SelfStoppingUpdatePrices(UpdatePrices):
        def fetch(self) -> data_snapshot.DataSnapshot | None:
            with pytest.raises(RuntimeError, match='cannot call stop from its worker'):
                self.stop()
            with pytest.raises(RuntimeError, match='cannot call start from its worker'):
                self.start()
            return None

    with SelfStoppingUpdatePrices() as update_prices:
        assert update_prices.wait(timeout=5)


def test_fetch_cannot_wait_for_itself() -> None:
    class ReentrantWaitUpdatePrices(UpdatePrices):
        def fetch(self) -> data_snapshot.DataSnapshot | None:
            with pytest.raises(RuntimeError, match='cannot wait for itself'):
                self.wait(timeout=0)
            with pytest.raises(RuntimeError, match='cannot wait for itself'):
                wait_prices_updated_sync(timeout=0)
            return None

    with ReentrantWaitUpdatePrices() as update_prices:
        assert update_prices.wait(timeout=5)


def test_all_owners_observe_failure_and_stop_is_non_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    error = httpx2.ConnectError('down')

    def fail(*_args: object, **_kwargs: object) -> None:
        raise error

    monkeypatch.setattr(httpx2, 'get', fail)
    first = UpdatePrices()
    second = UpdatePrices()
    first.start()
    second.start()
    try:
        with pytest.raises(httpx2.ConnectError) as first_error:
            first.wait(timeout=5)
        first_traceback = traceback.extract_tb(first_error.value.__traceback__)
        with pytest.raises(httpx2.ConnectError) as second_error:
            second.wait(timeout=0)
        with pytest.raises(httpx2.ConnectError):
            wait_prices_updated_sync(timeout=0)
        assert first_error.value is error
        assert second_error.value is error
        # Re-raising must retain the fetch origin without accumulating waiter frames.
        assert any(frame.name == 'fail' for frame in first_traceback)
        assert len(traceback.extract_tb(error.__traceback__)) == len(first_traceback)
    finally:
        first.stop()
        second.stop()


async def test_cancelled_async_wait_does_not_consume_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    fetch_started = threading.Event()
    release_fetch = threading.Event()
    waiter_started = threading.Event()
    error = RuntimeError('fetch failed')

    class FailingUpdatePrices(UpdatePrices):
        def fetch(self) -> data_snapshot.DataSnapshot | None:
            fetch_started.set()
            assert release_fetch.wait(timeout=5)
            raise error

    update_prices = FailingUpdatePrices()
    update_prices.start()
    assert update_prices._worker is not None
    worker = update_prices._worker
    original_wait = worker.ready.wait

    def tracked_wait(timeout: float | None = None) -> bool:
        waiter_started.set()
        return original_wait(timeout)

    # Cancellation matters only after asyncio.to_thread has entered the blocking wait.
    monkeypatch.setattr(worker.ready, 'wait', tracked_wait)
    task = asyncio.create_task(wait_prices_updated_async())
    try:
        assert await asyncio.to_thread(fetch_started.wait, 5)
        assert await asyncio.to_thread(waiter_started.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        release_fetch.set()
        with pytest.raises(RuntimeError) as observed:
            update_prices.wait(timeout=5)
        assert observed.value is error
    finally:
        release_fetch.set()
        update_prices.stop()


async def test_async_wait_without_active_updater_returns_false() -> None:
    assert await wait_prices_updated_async(timeout=0) is False


def test_wait_returns_false_on_timeout() -> None:
    fetch_started = threading.Event()
    release_fetch = threading.Event()

    class BlockingUpdatePrices(UpdatePrices):
        def fetch(self) -> data_snapshot.DataSnapshot | None:
            fetch_started.set()
            assert release_fetch.wait(timeout=5)
            return None

    update_prices = BlockingUpdatePrices()
    update_prices.start()
    try:
        assert fetch_started.wait(timeout=5)
        assert update_prices.wait(timeout=0) is False
    finally:
        release_fetch.set()
        update_prices.stop()


def test_stop_wakes_waiter_before_first_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    worker_started = threading.Event()
    allow_worker_run = threading.Event()
    waiter_started = threading.Event()
    original_run = update_prices_module._Worker._run

    # Pause before the worker body so shutdown wins before the first fetch.
    def paused_run(worker: update_prices_module._Worker) -> None:
        worker_started.set()
        assert allow_worker_run.wait(timeout=5)
        original_run(worker)

    monkeypatch.setattr(update_prices_module._Worker, '_run', paused_run)
    update_prices = NullUpdatePrices()
    update_prices.start()
    assert worker_started.wait(timeout=5)
    assert update_prices._worker is not None
    worker = update_prices._worker
    original_wait = worker.ready.wait

    def tracked_wait(timeout: float | None = None) -> bool:
        waiter_started.set()
        return original_wait(timeout)

    monkeypatch.setattr(worker.ready, 'wait', tracked_wait)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        wait_future = executor.submit(update_prices.wait)
        assert waiter_started.wait(timeout=5)
        stop_future = executor.submit(update_prices.stop)
        assert worker.stop_event.wait(timeout=5)
        allow_worker_run.set()
        assert wait_future.result(timeout=5) is False
        stop_future.result(timeout=5)


def test_dead_worker_publishes_terminal_failure() -> None:
    class DeadUpdatePrices(UpdatePrices):
        def fetch(self) -> data_snapshot.DataSnapshot | None:
            raise KeyboardInterrupt

    update_prices = DeadUpdatePrices()
    update_prices.start()
    try:
        with pytest.raises(RuntimeError, match='terminated unexpectedly'):
            update_prices.wait(timeout=5)
        with pytest.raises(RuntimeError, match='terminated unexpectedly'):
            NullUpdatePrices().start()
    finally:
        update_prices.stop()

    with NullUpdatePrices() as replacement:
        assert replacement.wait(timeout=5)


def test_interrupted_thread_start_drains_launched_worker(monkeypatch: pytest.MonkeyPatch):
    original_start = threading.Thread.start

    def start_then_interrupt(thread: threading.Thread) -> None:
        # Thread.start() can raise (e.g. Ctrl-C) after the OS thread is already running.
        original_start(thread)
        raise KeyboardInterrupt

    update_prices = NullUpdatePrices()
    with monkeypatch.context() as context:
        context.setattr(threading.Thread, 'start', start_then_interrupt)
        with pytest.raises(KeyboardInterrupt):
            update_prices.start()

    # The launched thread was drained and ownership released, so nothing fetches and a fresh start works.
    assert not any(thread.name == 'genai_prices:update' for thread in threading.enumerate())
    assert update_prices_module._worker is None
    update_prices.start(wait=True)
    update_prices.stop()


def test_worker_keeps_launch_configuration_after_attribute_changes(monkeypatch: pytest.MonkeyPatch):
    fetches: list[tuple[str, httpx2.Timeout]] = []
    second_fetch = threading.Event()

    class Response:
        content = PROVIDER_ARRAY_PAYLOAD

        def raise_for_status(self) -> None:
            pass

    def fake_get(url: str, timeout: httpx2.Timeout) -> Response:
        fetches.append((url, timeout))
        if len(fetches) >= 2:
            second_fetch.set()
        return Response()

    monkeypatch.setattr(httpx2, 'get', fake_get)
    update_prices = UpdatePrices(url='https://example.test/prices.json', update_interval=0.001)
    update_prices.start(wait=True)
    try:
        update_prices.url = 'https://changed.test/prices.json'
        assert second_fetch.wait(timeout=5)
    finally:
        update_prices.stop()

    assert {url for url, _ in fetches} == {'https://example.test/prices.json'}
    # The worker holds a copy, so mutating the instance's timeout cannot leak into it either.
    assert fetches[0][1] is not update_prices.request_timeout


def test_interrupted_final_join_still_finishes_shutdown(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    update_prices = UpdatePrices()
    update_prices.start(wait=True)
    assert data_snapshot._custom_snapshot is not None
    assert update_prices._worker is not None
    worker = update_prices._worker
    original_join = worker.thread.join
    interrupted = False

    def join_then_interrupt(timeout: float | None = None) -> None:
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise KeyboardInterrupt
        original_join(timeout)

    monkeypatch.setattr(worker.thread, 'join', join_then_interrupt)
    with pytest.raises(KeyboardInterrupt):
        update_prices.stop()

    # The interruption is re-raised only after shutdown finished: worker drained, bundled prices
    # restored, and the module released for a fresh start.
    assert not worker.thread.is_alive()
    assert data_snapshot._custom_snapshot is None
    assert update_prices_module._worker is None
    with NullUpdatePrices() as replacement:
        assert replacement.wait(timeout=5)


def test_interrupted_snapshot_restore_still_wakes_waiters(monkeypatch: pytest.MonkeyPatch) -> None:
    worker_started = threading.Event()
    allow_worker_run = threading.Event()
    original_run = update_prices_module._Worker._run

    def paused_run(worker: update_prices_module._Worker) -> None:
        worker_started.set()
        assert allow_worker_run.wait(timeout=5)
        original_run(worker)

    monkeypatch.setattr(update_prices_module._Worker, '_run', paused_run)
    update_prices = NullUpdatePrices()
    update_prices.start()
    assert worker_started.wait(timeout=5)
    assert update_prices._worker is not None
    worker = update_prices._worker
    assert not worker.ready.is_set()
    original_set_custom_snapshot = data_snapshot.set_custom_snapshot
    interrupted = False

    def restore_then_interrupt(snapshot: data_snapshot.DataSnapshot | None) -> None:
        nonlocal interrupted
        original_set_custom_snapshot(snapshot)
        if snapshot is None and not interrupted:
            interrupted = True
            raise KeyboardInterrupt

    monkeypatch.setattr(data_snapshot, 'set_custom_snapshot', restore_then_interrupt)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        stop_future = executor.submit(update_prices.stop)
        assert worker.stop_event.wait(timeout=5)
        allow_worker_run.set()
        with pytest.raises(KeyboardInterrupt):
            stop_future.result(timeout=5)

    assert worker.ready.is_set()
    assert data_snapshot._custom_snapshot is None
    assert update_prices_module._worker is None
    with NullUpdatePrices() as replacement:
        assert replacement.wait(timeout=5)


@pytest.mark.parametrize('shared_owner', [False, True])
def test_interrupted_claim_release_finishes_bookkeeping(shared_owner: bool) -> None:
    class InterruptingUpdatePrices(NullUpdatePrices):
        interrupt_release = False

        def __setattr__(self, name: str, value: object) -> None:
            super().__setattr__(name, value)
            if name == '_worker' and value is None and self.interrupt_release:
                self.interrupt_release = False
                raise KeyboardInterrupt

    first = NullUpdatePrices() if shared_owner else None
    update_prices = InterruptingUpdatePrices()
    if first is not None:
        first.start(wait=True)
    update_prices.start(wait=True)
    assert update_prices._worker is not None
    worker = update_prices._worker

    update_prices.interrupt_release = True
    with pytest.raises(KeyboardInterrupt):
        update_prices.stop()

    assert update_prices._worker is None
    assert worker.claims == int(shared_owner)
    if first is None:
        assert update_prices_module._worker is None
        assert not worker.thread.is_alive()
    else:
        assert update_prices_module._worker is worker
        assert worker.thread.is_alive()
        first.stop()

    with NullUpdatePrices() as replacement:
        assert replacement.wait(timeout=5)


def test_broken_log_handler_does_not_disturb_updating():
    class RaisingHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            raise RuntimeError('broken handler')

    handler = RaisingHandler()
    previous_level = update_prices_module.logger.level
    update_prices_module.logger.setLevel(logging.INFO)
    update_prices_module.logger.addHandler(handler)
    try:
        # Every worker log call raises, yet updating works and no waiter is stranded.
        with NullUpdatePrices() as update_prices:
            assert update_prices.wait(timeout=5)
    finally:
        update_prices_module.logger.removeHandler(handler)
        update_prices_module.logger.setLevel(previous_level)


def test_second_interrupt_abandons_join_without_reinstalling_prices(monkeypatch: pytest.MonkeyPatch):
    fetch_started = threading.Event()
    release_fetch = threading.Event()

    class BlockingUpdatePrices(UpdatePrices):
        def fetch(self) -> data_snapshot.DataSnapshot | None:
            fetch_started.set()
            assert release_fetch.wait(timeout=5)
            return data_snapshot.DataSnapshot([], from_auto_update=True)

    update_prices = BlockingUpdatePrices()
    update_prices.start()
    assert update_prices._worker is not None
    worker = update_prices._worker
    assert fetch_started.wait(timeout=5)

    def always_interrupted_join(_timeout: float | None = None) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(worker.thread, 'join', always_interrupted_join)
    with pytest.raises(KeyboardInterrupt):
        update_prices.stop()

    # The second interruption abandoned the join, but the module is released for a fresh start.
    assert update_prices_module._worker is None
    monkeypatch.undo()
    release_fetch.set()
    worker.thread.join(timeout=5)
    assert not worker.thread.is_alive()
    # The abandoned worker discarded its fetched snapshot instead of resurrecting it after stop().
    assert data_snapshot._custom_snapshot is None
