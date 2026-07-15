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
        True if prices were updated, False if no updater is running or the timeout elapsed.
    """
    with _lock:
        update_prices = _global_update_prices

    if update_prices is not None:
        return update_prices._wait_for_global_update(timeout)  # pyright: ignore[reportPrivateUsage]
    return False


async def wait_prices_updated_async(timeout: float | None = None) -> bool:
    """Asynchronously wait for prices to be updated by the shared background updater.

    Args:
        timeout: The maximum time to wait for prices to be updated. Defaults to None which waits indefinitely.

    Returns:
        True if prices were updated, False if no updater is running or the timeout elapsed.
    """
    return await asyncio.to_thread(wait_prices_updated_sync, timeout)


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
    _prices_updated: threading.Event = field(default_factory=threading.Event, repr=False)
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _background_exc: Exception | None = field(default=None, init=False, repr=False)
    _outcome_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _updater: UpdatePrices | None = field(default=None, init=False, repr=False)
    _owners: list[UpdatePrices] = field(default_factory=list, init=False, repr=False)
    _observed_background_exc: Exception | None = field(default=None, init=False, repr=False)
    _global_observed_background_exc: Exception | None = field(default=None, init=False, repr=False)
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

            update_prices._owners.append(self)
            self._updater = update_prices
            self._observed_background_exc = None

        if wait:
            self.wait(timeout=30 if wait is True else wait)

    def stop(self):
        """Release this instance's ownership of the shared background updater.

        The updater stops and bundled prices are restored only after the last owner releases it.
        This is a no-op if this instance is not started. Each owner raises a background exception
        it has not already observed; the last owner also waits for an in-flight fetch to finish.
        """
        global _global_update_prices

        exc: Exception | None = None
        with _lock:
            update_prices = self._updater
            if update_prices is None:
                return

            self._updater = None
            update_prices._owners = [owner for owner in update_prices._owners if owner is not self]
            if update_prices._owners:
                exc = update_prices._unobserved_failure(self)
            else:
                assert _global_update_prices is update_prices
                try:
                    # Keep ownership published until the thread exits. This makes a concurrent start
                    # wait instead of creating a second worker while the first is still fetching.
                    update_prices._stop_background_task()
                    exc = update_prices._unobserved_failure(self)
                finally:
                    _global_update_prices = None

        if exc is not None:
            raise exc

    def wait(self, timeout: float | None = None) -> bool:
        """Wait for the shared background updater's first completed attempt.

        A failed attempt is raised once by each owning instance. Returns `False` if this instance
        is not started or the timeout elapses.

        Args:
            timeout: The maximum time to wait for prices to be updated in seconds.
        """
        update_prices = self._updater
        if update_prices is None:
            return False

        return update_prices._wait_for_owner(self, timeout)

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
        self._prices_updated.clear()
        self._stop_event.clear()
        self._active_config = (self.url, self.update_interval, self.request_timeout)
        with self._outcome_lock:
            self._background_exc = None
            self._global_observed_background_exc = None
        self._thread = threading.Thread(target=self._background_task, daemon=True, name='genai_prices:update')
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

    def _wait_for_global_update(self, timeout: float | None) -> bool:
        prices_updated = self._prices_updated.wait(timeout=timeout)
        with self._outcome_lock:
            exc = self._background_exc
            if exc is not None:
                if exc is self._global_observed_background_exc:
                    return False
                self._global_observed_background_exc = exc
                # The process-wide helper observes the failure on behalf of all current owners.
                for owner in self._owners:
                    owner._observed_background_exc = exc
                raise exc
        return prices_updated

    def _wait_for_owner(self, owner: UpdatePrices, timeout: float | None) -> bool:
        prices_updated = self._prices_updated.wait(timeout=timeout)
        with self._outcome_lock:
            exc = self._background_exc
            if exc is not None:
                if exc is owner._observed_background_exc:
                    return False
                owner._observed_background_exc = exc
                self._global_observed_background_exc = exc
                raise exc
        return prices_updated

    def _unobserved_failure(self, owner: UpdatePrices) -> Exception | None:
        with self._outcome_lock:
            exc = self._background_exc
            if exc is None or exc is owner._observed_background_exc:
                return None
            owner._observed_background_exc = exc
            # Preserve the original relationship where an instance wait also consumed the
            # process-wide helper's view of that failure.
            self._global_observed_background_exc = exc
            return exc

    def _background_task(self) -> None:
        logger.info('Starting genai-prices background task')
        try:
            while True:
                try:
                    self._update_prices()
                    with self._outcome_lock:
                        self._background_exc = None
                        self._prices_updated.set()
                except Exception as e:
                    with self._outcome_lock:
                        self._background_exc = e
                        self._prices_updated.set()
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
