from __future__ import annotations

import asyncio
import concurrent.futures
import threading
import traceback
from collections.abc import Callable
from decimal import Decimal
from time import monotonic, sleep

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


class InterruptingOwnershipUpdatePrices(NullUpdatePrices):
    interrupt_on: str | None = None

    def __setattr__(self, name: str, value: object) -> None:
        assignment = 'clear' if value is None else 'set'
        if name == '_updater' and self.interrupt_on == assignment:
            self.interrupt_on = None
            raise KeyboardInterrupt
        super().__setattr__(name, value)


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
    _mock_update_prices_get(monkeypatch, b'[{"id":"missing-required-fields"}]')

    with pytest.raises(ValidationError):
        UpdatePrices(url='https://example.test/prices.json').fetch()

    assert _get_registry() is previous


def test_update_prices_fetch_rejects_non_array_payload_without_registry_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = _get_registry()
    _mock_update_prices_get(monkeypatch, b'{"providers":[]}')

    with pytest.raises(ValueError, match='Expected fetched prices payload to be a provider array'):
        UpdatePrices(url='https://example.test/prices.json').fetch()

    assert _get_registry() is previous


def test_update_prices_fetch_parses_provider_array_without_registry_change(monkeypatch: pytest.MonkeyPatch) -> None:
    bundled = _get_registry()
    _mock_update_prices_get(monkeypatch)

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
    _mock_update_prices_get(monkeypatch, providers_json.encode())

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
    _mock_update_prices_get(monkeypatch, providers_json.encode())

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


def test_interrupted_start_rollback_finishes_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    update_prices = InterruptingOwnershipUpdatePrices()
    update_prices.interrupt_on = 'clear'

    def fail_start(_thread: threading.Thread) -> None:
        raise RuntimeError('failed')

    with monkeypatch.context() as context:
        context.setattr(threading.Thread, 'start', fail_start)
        with pytest.raises(KeyboardInterrupt):
            update_prices.start()

    with NullUpdatePrices() as replacement:
        assert replacement.wait(timeout=5)


def test_interrupted_shared_claim_is_rolled_back() -> None:
    first = NullUpdatePrices()
    first.start(wait=True)
    second = InterruptingOwnershipUpdatePrices()
    second.interrupt_on = 'set'
    try:
        with pytest.raises(KeyboardInterrupt):
            second.start()
        first.stop()
        assert wait_prices_updated_sync(timeout=0) is False
    finally:
        second.stop()
        first.stop()


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


def test_overridden_fetch_super_uses_launch_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    fetch_started = threading.Event()
    allow_fetch = threading.Event()

    class SuperFetchUpdatePrices(UpdatePrices):
        def fetch(self) -> data_snapshot.DataSnapshot | None:
            fetch_started.set()
            assert allow_fetch.wait(timeout=5)
            return super().fetch()

    _mock_update_prices_get(monkeypatch, expected_url='https://example.test/prices.json')
    update_prices = SuperFetchUpdatePrices(url='https://example.test/prices.json')
    update_prices.start()
    try:
        assert fetch_started.wait(timeout=5)
        update_prices.url = 'https://changed.test/prices.json'
        allow_fetch.set()
        assert update_prices.wait(timeout=5)
    finally:
        allow_fetch.set()
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
    assert update_prices._updater is not None
    worker = update_prices._updater
    try:
        assert fetch_started.wait(timeout=5)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            stop_future = executor.submit(update_prices.stop)
            assert worker.stop_event.wait(timeout=5)
            allow_fetch_return.set()
            stop_future.result(timeout=5)
        assert data_snapshot._custom_snapshot is None
    finally:
        allow_fetch_return.set()
        update_prices.stop()
        data_snapshot.set_custom_snapshot(None)


def test_start_waits_for_in_flight_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
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
    assert first._updater is not None
    worker = first._updater
    start_waiting = threading.Event()
    original_wait = update_prices_module._lifecycle.wait

    def tracked_wait(timeout: float | None = None) -> bool:
        start_waiting.set()
        return original_wait(timeout)

    monkeypatch.setattr(update_prices_module._lifecycle, 'wait', tracked_wait)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        stop_future = executor.submit(first.stop)
        assert worker.stop_event.wait(timeout=5)
        start_future = executor.submit(second.start)
        # Wait until the replacement is blocked behind the old worker.
        assert start_waiting.wait(timeout=5)
        allow_fetch_return.set()
        stop_future.result(timeout=5)
        start_future.result(timeout=5)

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
    assert update_prices._updater is not None
    worker = update_prices._updater
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


def test_interrupted_stop_finishes_cleanup_before_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    update_prices = NullUpdatePrices()
    update_prices.start(wait=True)
    finish_despite_interruption = update_prices_module._finish_despite_interruption

    def interrupt_each_cleanup_once(action: Callable[[], None]) -> BaseException | None:
        interrupted = False

        def interrupt_after_action() -> None:
            nonlocal interrupted
            action()
            if not interrupted:
                interrupted = True
                raise KeyboardInterrupt

        return finish_despite_interruption(interrupt_after_action)

    # Exercise retries after both ownership release and worker cleanup have changed state.
    with monkeypatch.context() as context:
        context.setattr(update_prices_module, '_finish_despite_interruption', interrupt_each_cleanup_once)
        with pytest.raises(KeyboardInterrupt):
            update_prices.stop()

    with NullUpdatePrices() as replacement:
        assert replacement.wait(timeout=5)


def test_idle_publication_retry_cannot_clear_replacement() -> None:
    first = NullUpdatePrices()
    first.start(wait=True)
    assert first._updater is not None
    stopped_worker = first._updater
    first.stop()

    with NullUpdatePrices() as replacement:
        assert replacement.wait(timeout=5)
        # A delayed cleanup retry belongs to the old lifecycle, not its replacement.
        update_prices_module._publish_idle(stopped_worker)
        assert wait_prices_updated_sync(timeout=0)


def test_logging_failure_cannot_strand_stopping_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_logging(_message: str, *_args: object) -> None:
        raise RuntimeError('logging failed')

    monkeypatch.setattr(update_prices_module.logger, 'info', fail_logging)
    with NullUpdatePrices() as update_prices:
        assert update_prices.wait(timeout=5)


def test_interrupted_start_does_not_orphan_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    update_prices = NullUpdatePrices()
    original_start = threading.Thread.start

    def start_then_interrupt(thread: threading.Thread) -> None:
        original_start(thread)
        raise KeyboardInterrupt

    with monkeypatch.context() as context:
        context.setattr(threading.Thread, 'start', start_then_interrupt)
        with pytest.raises(KeyboardInterrupt):
            update_prices.start()

    assert not any(t.name == 'genai_prices:update' and t.is_alive() for t in threading.enumerate())
    with NullUpdatePrices() as replacement:
        assert replacement.wait(timeout=5)


def test_interrupted_start_cannot_publish_from_a_late_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    allow_worker_start = threading.Event()
    worker_started = threading.Event()
    worker_thread: threading.Thread | None = None
    update_prices = CountingNullUpdatePrices()
    initial_fetch_count = update_prices.count

    original_start = threading.Thread.start

    def start_later_then_interrupt(thread: threading.Thread) -> None:
        nonlocal worker_thread
        worker_thread = thread

        # Model an OS thread that appears only after interrupted-start cleanup has run.
        def start_worker() -> None:
            assert allow_worker_start.wait(timeout=5)
            original_start(thread)
            worker_started.set()

        starter = threading.Thread(target=start_worker)
        original_start(starter)
        raise KeyboardInterrupt

    with monkeypatch.context() as context:
        context.setattr(threading.Thread, 'start', start_later_then_interrupt)
        with pytest.raises(KeyboardInterrupt):
            update_prices.start()

    with NullUpdatePrices() as replacement:
        assert replacement.wait(timeout=5)
        allow_worker_start.set()
        assert worker_started.wait(timeout=5)
        assert worker_thread is not None
        worker_thread.join(timeout=5)
        assert not worker_thread.is_alive()
        assert update_prices.count == initial_fetch_count


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
    assert update_prices._updater is not None
    outcome = update_prices._updater.outcome
    original_wait = outcome.ready.wait

    def tracked_wait(timeout: float | None = None) -> bool:
        waiter_started.set()
        return original_wait(timeout)

    # Cancellation matters only after asyncio.to_thread has entered the blocking wait.
    monkeypatch.setattr(outcome.ready, 'wait', tracked_wait)
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
    original_run = update_prices_module._SharedUpdater._run

    # Pause before the worker body so shutdown wins before the first fetch.
    def paused_run(worker: update_prices_module._SharedUpdater) -> None:
        worker_started.set()
        assert allow_worker_run.wait(timeout=5)
        original_run(worker)

    monkeypatch.setattr(update_prices_module._SharedUpdater, '_run', paused_run)
    update_prices = NullUpdatePrices()
    update_prices.start()
    assert worker_started.wait(timeout=5)
    assert update_prices._updater is not None
    worker = update_prices._updater
    original_wait = worker.outcome.ready.wait

    def tracked_wait(timeout: float | None = None) -> bool:
        waiter_started.set()
        return original_wait(timeout)

    monkeypatch.setattr(worker.outcome.ready, 'wait', tracked_wait)
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
