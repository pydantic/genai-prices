from __future__ import annotations as _annotations

import asyncio
import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from time import time
from types import TracebackType

import httpx2

from . import data_snapshot

__all__ = (
    'DEFAULT_UPDATE_URL',
    'UpdatePrices',
    'wait_prices_updated_sync',
    'wait_prices_updated_async',
)

logger = logging.getLogger('genai-prices')
DEFAULT_UPDATE_URL = (
    'https://raw.githubusercontent.com/pydantic/genai-prices/refs/heads/main/prices/new_data/v2/data.json'
)
DEFAULT_UPDATE_INTERVAL = 3600.0


def _default_request_timeout() -> httpx2.Timeout:
    return httpx2.Timeout(timeout=10, connect=5)


@dataclass(frozen=True)
class _UpdateConfig:
    url: str
    update_interval: float
    request_timeout: httpx2.Timeout

    @classmethod
    def from_values(cls, url: str, update_interval: float, request_timeout: httpx2.Timeout) -> _UpdateConfig:
        # Timeout is mutable, so the worker needs a launch-time copy.
        return cls(url, update_interval, httpx2.Timeout(request_timeout))


def _fetch_prices(config: _UpdateConfig) -> data_snapshot.DataSnapshot:
    from .types import _providers_from_raw  # pyright: ignore[reportPrivateUsage]

    response = httpx2.get(config.url, timeout=config.request_timeout)
    response.raise_for_status()
    raw_payload = json.loads(response.content)
    if not isinstance(raw_payload, list):
        raise ValueError('Expected fetched prices payload to be a provider array')

    providers = _providers_from_raw(raw_payload)
    return data_snapshot.DataSnapshot(providers, from_auto_update=True)


@dataclass
class _UpdateOutcome:
    """Latest fetch outcome for one shared-updater lifecycle."""

    ready: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    error: Exception | None = None
    error_traceback: TracebackType | None = None
    succeeded: bool = False

    def publish_success(self) -> None:
        with self.lock:
            self.error = None
            self.error_traceback = None
            self.succeeded = True
            self.ready.set()

    def publish_failure(self, error: Exception) -> None:
        with self.lock:
            self.error = error
            self.error_traceback = error.__traceback__
            self.succeeded = False
            self.ready.set()

    def read(self) -> bool:
        with self.lock:
            error = self.error
            error_traceback = self.error_traceback
            succeeded = self.succeeded
        if error is not None:
            raise error.with_traceback(error_traceback)
        return succeeded


class _UpdaterPhase(Enum):
    ACTIVE = 'active'
    STOPPING = 'stopping'
    DEAD = 'dead'


# Price calculations use one process-wide snapshot, so independent consumers must share the
# updater that owns it. The condition protects lifecycle publication; calculations never acquire it.
_global_update_prices: _SharedUpdater | None = None
_lifecycle = threading.Condition()


def wait_prices_updated_sync(timeout: float | None = None) -> bool:
    """Synchronously wait for an outcome from the shared background updater.

    A fetch failure is raised to every waiter until a later fetch succeeds. Returns `False` if no
    updater is active or the timeout elapses.
    """
    with _lifecycle:
        update_prices = _global_update_prices
        if update_prices is None or update_prices.phase is _UpdaterPhase.STOPPING:
            return False
    return update_prices.wait(timeout)


async def wait_prices_updated_async(timeout: float | None = None) -> bool:
    """Asynchronously wait for an outcome from the shared background updater.

    Cancelling this coroutine does not consume or alter the shared outcome.
    """
    with _lifecycle:
        update_prices = _global_update_prices
        if update_prices is None or update_prices.phase is _UpdaterPhase.STOPPING:
            return False
    return await asyncio.to_thread(update_prices.wait, timeout)


@dataclass
class UpdatePrices:
    """Own a claim on the process-wide background price updater.

    Compatible instances share one worker. The first `start()` launches it, and the last `stop()`
    shuts it down and restores bundled prices. Starting twice, or joining with different
    configuration, raises `RuntimeError`.
    """

    update_interval: float = DEFAULT_UPDATE_INTERVAL
    """How often to update prices in seconds."""
    url: str = DEFAULT_UPDATE_URL
    """The URL to fetch prices from."""
    request_timeout: httpx2.Timeout = field(default_factory=_default_request_timeout)
    """The timeout for HTTP requests."""
    _updater: _SharedUpdater | None = field(default=None, init=False, repr=False)
    _fetch_updater: _SharedUpdater | None = field(default=None, init=False, repr=False)

    def start(self, *, wait: bool | float = False):
        """Acquire a claim on the process-wide background updater.

        Args:
            wait: Whether to wait for the first fetch outcome; if a number is passed, wait that
                many seconds, and if `True`, wait for 30 seconds.
        """
        global _global_update_prices

        failed_worker: _SharedUpdater | None = None
        start_error: BaseException | None = None
        with _lifecycle:
            while (
                update_prices := _global_update_prices
            ) is not None and update_prices.phase is _UpdaterPhase.STOPPING:
                if threading.current_thread() is update_prices.thread:
                    raise RuntimeError('UpdatePrices background task is stopping')
                _lifecycle.wait()

            if self._updater is not None:
                raise RuntimeError('UpdatePrices background task already started')

            config = _UpdateConfig.from_values(self.url, self.update_interval, self.request_timeout)
            if update_prices is None:
                update_prices = _SharedUpdater(config, self)
                try:
                    _global_update_prices = update_prices
                    update_prices.claims = 1
                    self._updater = update_prices
                    update_prices.start()
                except BaseException as exc:
                    # The thread may already be alive even if Thread.start() raised after delegating.
                    # Publish a stopping state before releasing the condition so no caller can join it.
                    update_prices.phase = _UpdaterPhase.STOPPING
                    update_prices.claims = 0
                    self._updater = None
                    failed_worker = update_prices
                    start_error = exc
            else:
                if update_prices.phase is _UpdaterPhase.DEAD:
                    raise RuntimeError('UpdatePrices background task terminated unexpectedly')
                if update_prices.config != config:
                    raise RuntimeError(
                        'UpdatePrices background task already started with different configuration: '
                        f'url={update_prices.config.url!r}, '
                        f'update_interval={update_prices.config.update_interval!r}, '
                        f'request_timeout={update_prices.config.request_timeout!r}'
                    )
                update_prices.claims += 1
                self._updater = update_prices

        if failed_worker is not None:
            _finish_shutdown(failed_worker)
            assert start_error is not None
            raise start_error

        if wait:
            self.wait(timeout=30 if wait is True else wait)

    def stop(self):
        """Release this instance's claim on the shared updater.

        The last release waits for an in-flight fetch, stops the worker, and restores bundled
        prices. Fetch failures are logged and reported by `wait()`; they never make `stop()` fail.
        Lifecycle interruptions such as `KeyboardInterrupt` are preserved after cleanup completes.
        """
        update_prices: _SharedUpdater | None = None
        remaining_claims: int | None = None
        release_prepared = False

        def release_claim() -> None:
            nonlocal update_prices, remaining_claims, release_prepared
            with _lifecycle:
                if not release_prepared:
                    update_prices = self._updater
                    if update_prices is not None:
                        if update_prices.claims == 1 and threading.current_thread() is update_prices.thread:
                            raise RuntimeError('UpdatePrices background task cannot stop itself')
                        remaining_claims = update_prices.claims - 1
                    # A retry must finish the same release instead of decrementing twice.
                    release_prepared = True

                if update_prices is not None:
                    assert remaining_claims is not None
                    self._updater = None
                    update_prices.claims = remaining_claims
                    if remaining_claims == 0:
                        update_prices.phase = _UpdaterPhase.STOPPING

        release_interrupted: BaseException | None = None
        shutdown_interrupted: BaseException | None = None
        try:
            release_interrupted = _finish_despite_interruption(release_claim)
        finally:
            # Once the last release starts, no interruption may leave it stuck in STOPPING.
            if update_prices is not None and update_prices.claims == 0:
                shutdown_interrupted = _finish_shutdown(update_prices)
        interrupted = shutdown_interrupted or release_interrupted
        if interrupted is not None:
            raise interrupted

    def wait(self, timeout: float | None = None) -> bool:
        """Wait for the shared updater's latest fetch outcome.

        A fetch failure is raised to every waiter until a later fetch succeeds. Returns `False` if
        this instance is not started or the timeout elapses.
        """
        with _lifecycle:
            update_prices = self._updater
            if update_prices is None:
                return False
        return update_prices.wait(timeout)

    def fetch(self) -> data_snapshot.DataSnapshot | None:
        """Fetch the latest provider data from this instance's configured URL."""
        worker = self._fetch_updater
        if worker is not None and threading.current_thread() is worker.thread:
            # A subclass calling super() must use the settings accepted when its worker started.
            config = worker.config
        else:
            config = _UpdateConfig.from_values(self.url, self.update_interval, self.request_timeout)
        return _fetch_prices(config)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_args: object):
        self.stop()


class _SharedUpdater:
    """Private worker shared by public `UpdatePrices` ownership claims."""

    def __init__(self, config: _UpdateConfig, owner: UpdatePrices) -> None:
        self.config = config
        # The base fetch uses frozen lifecycle settings; subclasses keep their supported override hook.
        fetch = owner.fetch
        if getattr(fetch, '__func__', None) is UpdatePrices.fetch:
            self.fetch: Callable[[], data_snapshot.DataSnapshot | None] = lambda: _fetch_prices(config)
        else:
            self.fetch = fetch
        self.claims = 0
        self.phase = _UpdaterPhase.ACTIVE
        self.stop_event = threading.Event()
        self.run_event = threading.Event()
        self.outcome = _UpdateOutcome()
        self.thread = threading.Thread(target=self._run, daemon=True, name='genai_prices:update')
        self.owner = owner
        owner._fetch_updater = self  # pyright: ignore[reportPrivateUsage]

    def start(self) -> None:
        self.thread.start()
        # Thread.start() can be interrupted after OS launch, so a late worker needs this gate to
        # observe cleanup before it can publish prices.
        self.run_event.set()

    def wait(self, timeout: float | None) -> bool:
        if threading.current_thread() is self.thread:
            raise RuntimeError('UpdatePrices background task cannot wait for itself')
        if not self.outcome.ready.wait(timeout=timeout):
            return False
        return self.outcome.read()

    def stop(self) -> BaseException | None:
        self.stop_event.set()
        self.run_event.set()

        def cleanup() -> None:
            # An interrupted Thread.start() can publish ident before join() becomes legal.
            if self.thread.is_alive():
                self.thread.join()
            # A worker stopped before its first fetch has no outcome of its own to wake waiters with.
            self.outcome.ready.set()
            data_snapshot.set_custom_snapshot(None)
            self.owner._fetch_updater = None  # pyright: ignore[reportPrivateUsage]

        return _finish_despite_interruption(cleanup)

    def _run(self) -> None:
        terminal_error: BaseException | None = None
        try:
            self.run_event.wait()
            if self.stop_event.is_set():
                return
            self._log(logger.info, 'Starting genai-prices background task')
            while True:
                try:
                    self._update_prices()
                except Exception as exc:
                    self.outcome.publish_failure(exc)
                    self._log(
                        logger.error,
                        'Error updating genai-prices in the background (%s): %s',
                        type(exc).__name__,
                        exc,
                    )
                else:
                    self.outcome.publish_success()

                if self.stop_event.wait(self.config.update_interval):
                    break
        except BaseException as exc:
            terminal_error = exc
            error = RuntimeError('UpdatePrices background task terminated unexpectedly')
            error.__cause__ = exc
            self.outcome.publish_failure(error)
        finally:
            with _lifecycle:
                if self.phase is _UpdaterPhase.ACTIVE and terminal_error is not None:
                    self.phase = _UpdaterPhase.DEAD
                _lifecycle.notify_all()
            self._log(logger.info, 'genai-prices background task stopped')

    def _update_prices(self) -> None:
        started = time()
        snapshot = self.fetch()
        interval = time() - started
        if snapshot:
            self._log(
                logger.info,
                'Successfully fetched %d providers in %.2f seconds',
                len(snapshot.providers),
                interval,
            )
        else:
            self._log(logger.info, 'Successfully fetched null snapshot in %.2f seconds', interval)
        data_snapshot.set_custom_snapshot(snapshot)

    @staticmethod
    def _log(log: Callable[..., None], message: str, *args: object) -> None:
        try:
            log(message, *args)
        except Exception:
            # Logging must not terminate the updater or strand lifecycle publication.
            pass


def _publish_idle(update_prices: _SharedUpdater) -> None:
    global _global_update_prices

    with _lifecycle:
        # A retry must not clear a replacement installed after the first publication succeeded.
        if _global_update_prices is update_prices:
            _global_update_prices = None
        _lifecycle.notify_all()


def _finish_shutdown(update_prices: _SharedUpdater) -> BaseException | None:
    """Drain one worker and always publish the final idle state."""
    stopped = False
    stop_interrupted: BaseException | None = None

    def finish() -> None:
        nonlocal stopped, stop_interrupted
        if not stopped:
            stop_interrupted = update_prices.stop()
            stopped = True
        _publish_idle(update_prices)

    finish_interrupted = _finish_despite_interruption(finish)
    return finish_interrupted or stop_interrupted


def _finish_despite_interruption(action: Callable[[], None]) -> BaseException | None:
    """Finish lifecycle cleanup before propagating Ctrl-C or process exit."""
    interrupted: BaseException | None = None
    while True:
        try:
            action()
            return interrupted
        except (KeyboardInterrupt, SystemExit) as exc:
            interrupted = exc
