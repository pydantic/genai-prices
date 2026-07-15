import concurrent.futures
import threading
from collections.abc import Callable
from decimal import Decimal
from time import monotonic, sleep

import httpx2
import pytest
from inline_snapshot import snapshot

import genai_prices.update_prices as update_prices_module
from genai_prices import (
    UpdatePrices,
    Usage,
    calc_price,
    data_snapshot,
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
        assert url in {'https://example.test/prices.json', DEFAULT_UPDATE_URL}
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

    prices = UpdatePrices(url='https://example.test/prices.json').fetch()

    assert prices is not None
    assert prices.from_auto_update is True
    provider, model = prices.find_provider_model('gpt-4o-mini', None, 'openai', None)
    assert provider.id == 'openai'
    assert model.id == 'gpt-4o-mini'


def test_update_prices_context_manager_updates_and_restores_snapshot(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    assert data_snapshot._custom_snapshot is None

    with UpdatePrices() as update_prices:
        assert update_prices.wait(timeout=5)
        price = calc_price(Usage(input_tokens=1000, output_tokens=100), model_ref='gpt-4o', provider_id='openai')
        assert price.input_price == snapshot(Decimal('0.0025'))
        assert price.output_price == snapshot(Decimal('0.001'))
        assert price.total_price == snapshot(Decimal('0.0035'))
        assert price.provider.id == snapshot('openai')
        assert price.auto_update_timestamp is not None

    assert data_snapshot._custom_snapshot is None


def test_wait_prices_updated_sync(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    with UpdatePrices():
        assert wait_prices_updated_sync(timeout=5)
        assert data_snapshot._custom_snapshot is not None

    assert wait_prices_updated_sync(timeout=0) is False


def test_wait_prices_updated_sync_reports_failure_once(monkeypatch: pytest.MonkeyPatch):
    def fail(*_args: object, **_kwargs: object) -> None:
        raise httpx2.ConnectError('down')

    monkeypatch.setattr(httpx2, 'get', fail)
    first = UpdatePrices()
    second = UpdatePrices()
    first.start()
    second.start()
    try:
        with pytest.raises(httpx2.ConnectError, match='down'):
            wait_prices_updated_sync(timeout=5)
        assert wait_prices_updated_sync(timeout=0) is False
    finally:
        # The process-wide wait consumed the shared failure before either owner stopped.
        first.stop()
        second.stop()


def test_unstarted_instance_wait_returns_false():
    assert UpdatePrices().wait(timeout=0) is False


async def test_wait_prices_updated_async(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    with UpdatePrices():
        assert await wait_prices_updated_async(timeout=5)
        assert data_snapshot._custom_snapshot is not None


def test_distinct_instances_share_ownership(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    first = UpdatePrices()
    second = UpdatePrices()
    first.start(wait=True)
    second.start()

    try:
        assert second.wait(timeout=0)
        first.stop()
        first.stop()
        assert data_snapshot._custom_snapshot is not None
        assert second.wait(timeout=0)
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


def test_unstarted_instance_cannot_release_another_owner(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    with UpdatePrices() as update_prices:
        assert update_prices.wait(timeout=5)
        UpdatePrices().stop()
        assert data_snapshot._custom_snapshot is not None


def test_overridden_fetch_drives_shared_updater():
    first = CountingNullUpdatePrices()
    second = CountingNullUpdatePrices()
    first.start(wait=True)
    second.start()
    try:
        assert first.count == 1
        assert second.wait(timeout=0)
        assert second.count == 0
    finally:
        first.stop()
        second.stop()


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


def test_shared_failure_is_observed_once(monkeypatch: pytest.MonkeyPatch):
    def fail(*_args: object, **_kwargs: object) -> None:
        raise httpx2.ConnectError('down')

    monkeypatch.setattr(httpx2, 'get', fail)
    first = UpdatePrices()
    second = UpdatePrices()
    first.start()
    second.start()
    try:
        with pytest.raises(httpx2.ConnectError, match='down'):
            first.wait(timeout=5)
        assert second.wait(timeout=0) is False
        assert first.wait(timeout=0) is False
    finally:
        first.stop()
        second.stop()


def test_repeated_failure_with_same_exception_is_observed_each_time():
    shared_error = RuntimeError('reused failure')
    second_fetch_started = threading.Event()
    release_second_fetch = threading.Event()

    class RepeatedFailureUpdatePrices(UpdatePrices):
        attempts = 0

        def fetch(self) -> data_snapshot.DataSnapshot | None:
            self.attempts += 1
            if self.attempts == 2:
                second_fetch_started.set()
                assert release_second_fetch.wait(timeout=5)
                self._stop_event.set()
            raise shared_error

    update_prices = RepeatedFailureUpdatePrices(update_interval=0.001)
    update_prices.start()
    try:
        with pytest.raises(RuntimeError) as first_error:
            update_prices.wait(timeout=5)
        assert first_error.value is shared_error

        assert second_fetch_started.wait(timeout=5)
        update_prices._state.prices_updated.clear()
        release_second_fetch.set()

        with pytest.raises(RuntimeError) as second_error:
            update_prices.wait(timeout=5)
        assert second_error.value is shared_error
    finally:
        release_second_fetch.set()
        update_prices.stop()


def test_last_stop_raises_unobserved_failure(monkeypatch: pytest.MonkeyPatch):
    fetch_started = threading.Event()

    def fail(*_args: object, **_kwargs: object) -> None:
        fetch_started.set()
        raise httpx2.ConnectError('network down')

    monkeypatch.setattr(httpx2, 'get', fail)
    update_prices = UpdatePrices()
    update_prices.start()
    assert fetch_started.wait(timeout=5)

    with pytest.raises(httpx2.ConnectError, match='network down'):
        update_prices.stop()


def test_non_last_stop_raises_unobserved_failure_and_releases_owner(monkeypatch: pytest.MonkeyPatch):
    def fail(*_args: object, **_kwargs: object) -> None:
        raise httpx2.ConnectError('down')

    monkeypatch.setattr(httpx2, 'get', fail)
    first = UpdatePrices()
    second = UpdatePrices()
    first.start()
    second.start()

    with pytest.raises(httpx2.ConnectError, match='down'):
        first.stop()
    assert first.wait(timeout=0) is False

    try:
        assert second.wait(timeout=0) is False
    finally:
        second.stop()


def test_released_worker_owner_cannot_change_active_configuration():
    first = NullUpdatePrices()
    second = NullUpdatePrices()
    third = NullUpdatePrices()
    first.start(wait=True)
    second.start()
    first.stop()
    first.url = 'https://example.test/changed.json'
    first.request_timeout.read = 777

    try:
        third.start()
        third.stop()
    finally:
        second.stop()


def test_wait_does_not_cross_same_instance_restart(monkeypatch: pytest.MonkeyPatch):
    old_error = RuntimeError('old lifecycle failed')
    wait_returned = threading.Event()
    release_old_wait = threading.Event()
    new_fetch_started = threading.Event()
    release_new_fetch = threading.Event()

    class RestartableUpdatePrices(UpdatePrices):
        fail = True

        def fetch(self) -> data_snapshot.DataSnapshot | None:
            if self.fail:
                raise old_error
            new_fetch_started.set()
            assert release_new_fetch.wait(timeout=5)
            return None

    class PausedEvent:
        def __init__(self, event: threading.Event) -> None:
            self.event = event

        def wait(self, timeout: float | None = None) -> bool:
            result = self.event.wait(timeout)
            wait_returned.set()
            assert release_old_wait.wait(timeout=5)
            return result

    update_prices = RestartableUpdatePrices()
    update_prices.start()
    old_state = update_prices._state
    assert old_state.prices_updated.wait(timeout=5)
    monkeypatch.setattr(old_state, 'prices_updated', PausedEvent(old_state.prices_updated))

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            old_wait = executor.submit(update_prices.wait, 5)
            assert wait_returned.wait(timeout=5)
            with pytest.raises(RuntimeError) as stop_error:
                update_prices.stop()
            assert stop_error.value is old_error

            update_prices.fail = False
            update_prices.start()
            assert new_fetch_started.wait(timeout=5)
            release_old_wait.set()
            assert old_wait.result(timeout=5) is False

        release_new_fetch.set()
        assert update_prices.wait(timeout=5)
    finally:
        release_old_wait.set()
        release_new_fetch.set()
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


def test_stop_does_not_deadlock_when_fetch_reenters_start() -> None:
    fetch_started = threading.Event()
    allow_reentry = threading.Event()
    other = NullUpdatePrices()

    class ReentrantUpdatePrices(UpdatePrices):
        def fetch(self) -> data_snapshot.DataSnapshot | None:
            fetch_started.set()
            assert allow_reentry.wait(timeout=5)
            with pytest.raises(RuntimeError, match='background task is stopping'):
                other.start()
            return None

    update_prices = ReentrantUpdatePrices()
    update_prices.start()
    assert fetch_started.wait(timeout=5)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            stop_future = executor.submit(update_prices.stop)
            assert update_prices._stop_event.wait(timeout=5)
            allow_reentry.set()
            stop_future.result(timeout=5)

        # The rejected re-entrant claim must not poison a normal restart after shutdown.
        other.start(wait=True)
    finally:
        allow_reentry.set()
        update_prices.stop()
        other.stop()


def test_fetch_cannot_release_its_own_last_claim() -> None:
    class SelfStoppingUpdatePrices(UpdatePrices):
        def fetch(self) -> data_snapshot.DataSnapshot | None:
            with pytest.raises(RuntimeError, match='background task cannot stop itself'):
                self.stop()
            return None

    update_prices = SelfStoppingUpdatePrices()
    other = SelfStoppingUpdatePrices()
    update_prices.start(wait=True)

    try:
        assert update_prices._updater is update_prices
        other.start()
        assert other._updater is update_prices
        assert sum(thread.name == 'genai_prices:update' for thread in threading.enumerate()) == 1
    finally:
        update_prices.stop()
        other.stop()

    # Rejecting self-stop must leave the instance reusable after a normal shutdown.
    update_prices.start(wait=True)
    update_prices.stop()


def test_same_instance_cannot_claim_twice_after_waiting_for_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    fetch_started = threading.Event()
    allow_fetch_return = threading.Event()
    both_starts_waiting = threading.Event()
    waiting_count = 0

    class BlockingUpdatePrices(UpdatePrices):
        def fetch(self) -> data_snapshot.DataSnapshot | None:
            fetch_started.set()
            assert allow_fetch_return.wait(timeout=5)
            return None

    original_wait = update_prices_module._lifecycle.wait

    def tracked_wait(timeout: float | None = None) -> bool:
        nonlocal waiting_count
        waiting_count += 1
        if waiting_count == 2:
            both_starts_waiting.set()
        return original_wait(timeout)

    monkeypatch.setattr(update_prices_module._lifecycle, 'wait', tracked_wait)
    first = BlockingUpdatePrices()
    second = NullUpdatePrices()
    first.start()
    assert fetch_started.wait(timeout=5)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            stop_future = executor.submit(first.stop)
            assert first._stop_event.wait(timeout=5)
            starts = [executor.submit(second.start) for _ in range(2)]
            assert both_starts_waiting.wait(timeout=5)
            allow_fetch_return.set()
            stop_future.result(timeout=5)

            errors: list[RuntimeError] = []
            for start in starts:
                try:
                    start.result(timeout=5)
                except RuntimeError as exc:
                    errors.append(exc)

        assert len(errors) == 1
        assert str(errors[0]) == 'UpdatePrices background task already started'
    finally:
        allow_fetch_return.set()
        first.stop()
        second.stop()

    assert wait_prices_updated_sync(timeout=0) is False


def test_interrupted_stop_finishes_cleanup_before_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    fetch_started = threading.Event()
    allow_fetch_return = threading.Event()
    interruption_observed = threading.Event()
    join_interruption_observed = threading.Event()

    class BlockingUpdatePrices(UpdatePrices):
        def fetch(self) -> data_snapshot.DataSnapshot | None:
            fetch_started.set()
            assert allow_fetch_return.wait(timeout=5)
            return None

    update_prices = BlockingUpdatePrices()
    update_prices.start()
    assert fetch_started.wait(timeout=5)
    state = update_prices._state
    assert update_prices._thread is not None
    thread = update_prices._thread
    original_wait = state.background_stopped.wait
    original_join = thread.join

    def interrupt_once(timeout: float | None = None) -> bool:
        if not interruption_observed.is_set():
            interruption_observed.set()
            raise RuntimeError('wait interrupted')
        return original_wait(timeout)

    def interrupt_join_once(timeout: float | None = None) -> None:
        if not join_interruption_observed.is_set():
            join_interruption_observed.set()
            raise RuntimeError('join interrupted')
        original_join(timeout)

    monkeypatch.setattr(state.background_stopped, 'wait', interrupt_once)
    monkeypatch.setattr(thread, 'join', interrupt_join_once)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            stop_future = executor.submit(update_prices.stop)
            assert interruption_observed.wait(timeout=5)
            allow_fetch_return.set()
            with pytest.raises(RuntimeError, match='join interrupted'):
                stop_future.result(timeout=5)
            assert join_interruption_observed.is_set()

        assert update_prices._thread is None
        assert update_prices._active_config is None
        assert wait_prices_updated_sync(timeout=0) is False

        replacement = NullUpdatePrices()
        replacement.start(wait=True)
        replacement.stop()
    finally:
        allow_fetch_return.set()
        update_prices.stop()


def test_logging_failure_cannot_strand_stopping_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_logging(_message: str) -> None:
        raise RuntimeError('logging failed')

    def ignore_thread_exception(_args: threading.ExceptHookArgs) -> None:
        pass

    monkeypatch.setattr(update_prices_module.logger, 'info', fail_logging)
    monkeypatch.setattr(threading, 'excepthook', ignore_thread_exception)
    update_prices = NullUpdatePrices()
    update_prices.start()
    assert update_prices._state.background_stopped.wait(timeout=5)

    update_prices.stop()
    assert update_prices._thread is None
    assert wait_prices_updated_sync(timeout=0) is False


def test_concurrent_ownership(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch)
    barrier = threading.Barrier(8)

    def acquire_and_release() -> None:
        update_prices = UpdatePrices()
        barrier.wait(timeout=5)
        update_prices.start()
        update_prices.stop()

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(acquire_and_release) for _ in range(8)]
        for future in futures:
            future.result(timeout=10)

    assert wait_prices_updated_sync(timeout=0) is False
    assert data_snapshot._custom_snapshot is None
