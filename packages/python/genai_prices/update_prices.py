from __future__ import annotations as _annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from time import time

import httpx2

from . import data_snapshot

__all__ = (
    'DEFAULT_UPDATE_URL',
    'UpdatePrices',
    'wait_prices_updated_sync',
    'wait_prices_updated_async',
)

logger = logging.getLogger('genai-prices')
DEFAULT_UPDATE_URL = 'https://raw.githubusercontent.com/pydantic/genai-prices/refs/heads/main/prices/data.json'
DEFAULT_UPDATE_INTERVAL = 3600.0


def _default_request_timeout() -> httpx2.Timeout:
    return httpx2.Timeout(timeout=10, connect=5)


# Price calculations use one process-wide snapshot, so independent consumers must share the
# updater that owns it. The lock only protects updater lifecycle; calculating prices is unaffected.
_global_update_prices: UpdatePrices | None = None
_lock = threading.Lock()


def wait_prices_updated_sync(timeout: float | None = None) -> bool:
    """Synchronously wait for prices to be updated by the shared background updater.

    Args:
        timeout: The maximum time to wait for prices to be updated. Defaults to None which waits indefinitely.

    Returns:
        True if prices were updated. False if no updater is running, the timeout elapsed, or
        another waiter already observed the current failure.
    """
    with _lock:
        update_prices = _global_update_prices
        if update_prices is None:
            return False
        state = update_prices._state  # pyright: ignore[reportPrivateUsage]

    return update_prices._wait_for_update(state, timeout)  # pyright: ignore[reportPrivateUsage]


async def wait_prices_updated_async(timeout: float | None = None) -> bool:
    """Asynchronously wait for prices to be updated by the shared background updater.

    Args:
        timeout: The maximum time to wait for prices to be updated. Defaults to None which waits indefinitely.

    Returns:
        True if prices were updated. False if no updater is running, the timeout elapsed, or
        another waiter already observed the current failure.
    """
    return await asyncio.to_thread(wait_prices_updated_sync, timeout)


@dataclass
class _UpdateState:
    """Outcome state for one start/stop lifecycle, kept separate so old waiters cannot cross a restart."""

    prices_updated: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    background_exc: Exception | None = None
    failed: bool = False


@dataclass
class UpdatePrices:
    """Periodically update price data by downloading it in a background daemon thread.

    A single process-wide updater backs every compatible `UpdatePrices` instance. The first
    `start()` starts it, later calls from other instances acquire shared ownership, and the last
    matching `stop()` stops it. Starting an instance twice or starting one with configuration that
    differs from the active updater raises `RuntimeError`.

    Can be used as a context manager (`with UpdatePrices(): ...`) or by calling `start()`/`stop()`.
    """

    update_interval: float = DEFAULT_UPDATE_INTERVAL
    """How often to update prices in seconds."""
    url: str = DEFAULT_UPDATE_URL
    """The URL to fetch prices from."""
    request_timeout: httpx2.Timeout = field(default_factory=_default_request_timeout)
    """The timeout for HTTP requests."""
    _stop_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _updater: UpdatePrices | None = field(default=None, init=False, repr=False)
    _claims: int = field(default=0, init=False, repr=False)
    _state: _UpdateState = field(default_factory=_UpdateState, init=False, repr=False)
    _active_config: tuple[str, float, httpx2.Timeout] | None = field(default=None, init=False, repr=False)

    def start(self, *, wait: bool | float = False):
        """Acquire shared ownership of the process-wide background updater.

        Args:
            wait: Whether to wait for prices to be updated before returning; if an int/float is
                passed wait that many seconds, if `True` wait for 30 seconds.
        """
        global _global_update_prices

        with _lock:
            if self._updater is not None:
                raise RuntimeError('UpdatePrices background task already started')

            update_prices = _global_update_prices
            if update_prices is None:
                self._start_background_task()
                update_prices = _global_update_prices = self
            elif update_prices._active_config != (self.url, self.update_interval, self.request_timeout):
                assert update_prices._active_config is not None
                url, update_interval, request_timeout = update_prices._active_config
                raise RuntimeError(
                    'UpdatePrices background task already started with different configuration: '
                    f'url={url!r}, update_interval={update_interval!r}, request_timeout={request_timeout!r}'
                )

            update_prices._claims += 1
            self._updater = update_prices

        if wait:
            self.wait(timeout=30 if wait is True else wait)

    def stop(self):
        """Release this instance's ownership of the shared background updater.

        The updater stops and bundled prices are restored only after the last owner releases it.
        This is a no-op if this instance is not started. An unobserved background exception is
        raised once process-wide; the last owner also waits for an in-flight fetch to finish.
        """
        global _global_update_prices

        with _lock:
            update_prices = self._updater
            if update_prices is None:
                return

            state = update_prices._state
            self._updater = None
            update_prices._claims -= 1

            if update_prices._claims == 0:
                assert _global_update_prices is update_prices
                try:
                    # Keep ownership published until the thread exits. This makes a concurrent start
                    # wait instead of creating a second worker while the first is still fetching.
                    update_prices._stop_background_task()
                finally:
                    _global_update_prices = None

            update_prices._raise_background_failure(state)

    def wait(self, timeout: float | None = None) -> bool:
        """Wait for the shared background updater's first completed attempt.

        A failed attempt is raised once process-wide. Returns `False` if this instance is not
        started, the timeout elapses, or another waiter already observed the current failure.

        Args:
            timeout: The maximum time to wait for prices to be updated in seconds.
        """
        with _lock:
            update_prices = self._updater
            if update_prices is None:
                return False
            state = update_prices._state

        return update_prices._wait_for_update(state, timeout)

    def fetch(self) -> data_snapshot.DataSnapshot | None:
        """Fetches the latest provider data from the configured URL."""
        from . import data

        if self._active_config is None:
            url, request_timeout = self.url, self.request_timeout
        else:
            url, _, request_timeout = self._active_config

        r = httpx2.get(url, timeout=request_timeout)
        r.raise_for_status()
        return data_snapshot.DataSnapshot(data.providers_schema.validate_json(r.content), from_auto_update=True)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_args: object):
        self.stop()

    def _start_background_task(self) -> None:
        assert self._thread is None
        self._stop_event.clear()
        self._active_config = (self.url, self.update_interval, httpx2.Timeout(self.request_timeout))
        self._state = state = _UpdateState()
        self._thread = threading.Thread(
            target=self._background_task, args=(state,), daemon=True, name='genai_prices:update'
        )
        try:
            self._thread.start()
        except Exception:
            self._thread = None
            self._active_config = None
            raise

    def _stop_background_task(self) -> None:
        self._stop_event.set()
        assert self._thread is not None
        self._thread.join()
        self._thread = None
        self._active_config = None

        # Clear after the thread exits so an in-flight fetch cannot reinstall a snapshot after stop().
        data_snapshot.set_custom_snapshot(None)

    @staticmethod
    def _wait_for_update(state: _UpdateState, timeout: float | None) -> bool:
        prices_updated = state.prices_updated.wait(timeout=timeout)
        with state.lock:
            exc = state.background_exc
            state.background_exc = None
            failed = state.failed
        if exc is not None:
            raise exc
        return prices_updated and not failed

    @staticmethod
    def _raise_background_failure(state: _UpdateState) -> None:
        with state.lock:
            exc = state.background_exc
            state.background_exc = None
        if exc is not None:
            raise exc

    def _background_task(self, state: _UpdateState) -> None:
        logger.info('Starting genai-prices background task')
        try:
            while True:
                try:
                    self._update_prices()
                    with state.lock:
                        state.background_exc = None
                        state.failed = False
                        state.prices_updated.set()
                except Exception as e:
                    with state.lock:
                        state.background_exc = e
                        state.failed = True
                        state.prices_updated.set()
                    logger.error('Error updating genai-prices in the background (%s): %s', type(e).__name__, e)
                assert self._active_config is not None
                if self._stop_event.wait(self._active_config[1]):
                    break
        finally:
            logger.info('genai-prices background task stopped')

    def _update_prices(self):
        start = time()
        snapshot = self.fetch()
        interval = time() - start
        if snapshot:
            logger.info('Successfully fetched %d providers in %.2f seconds', len(snapshot.providers), interval)
        else:
            logger.info('Successfully fetched null snapshot in %.2f seconds', interval)

        data_snapshot.set_custom_snapshot(snapshot)
