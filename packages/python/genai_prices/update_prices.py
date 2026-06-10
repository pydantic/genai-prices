from __future__ import annotations as _annotations

import asyncio
import logging
import os
import threading
from dataclasses import dataclass, field
from time import time

import httpx2

from . import data_snapshot

__all__ = (
    'DEFAULT_UPDATE_URL',
    'UpdatePrices',
    'UpdatePricesHandle',
    'update_prices_in_background',
    'wait_prices_updated_sync',
    'wait_prices_updated_async',
)

logger = logging.getLogger('genai-prices')
DEFAULT_UPDATE_URL = 'https://raw.githubusercontent.com/pydantic/genai-prices/refs/heads/main/prices/data.json'
_global_update_prices: UpdatePrices | None = None
_managed_update_prices: UpdatePrices | None = None
_managed_update_prices_ref_count = 0
_global_update_prices_lock = threading.RLock()


def wait_prices_updated_sync(timeout: float | None = None) -> bool:
    """Synchronously wait for prices to be updated.

    Args:
        timeout: The maximum time to wait for prices to be updated. Defaults to None which waits indefinitely.

    Returns:
        True if prices were updated, False otherwise.
    """
    with _global_update_prices_lock:
        update_prices = _global_update_prices

    if update_prices is not None:
        return update_prices.wait(timeout)
    return False


async def wait_prices_updated_async(timeout: float | None = None) -> bool:
    """Asynchronously wait for prices to be updated.

    Args:
        timeout: The maximum time to wait for prices to be updated. Defaults to None which waits indefinitely.

    Returns:
        True if prices were updated, False otherwise.
    """
    return await asyncio.to_thread(wait_prices_updated_sync, timeout)


def update_prices_in_background() -> UpdatePricesHandle:
    """Update prices in the background using a shared, process-wide daemon thread.

    The first call starts the shared updater; later calls reuse it and return independent handles.
    The updater is stopped when the last handle is closed, at which point prices revert to the
    data bundled with the installed package.

    This function returns immediately and never blocks on the download: until the first fetch
    completes, price calculations keep using the bundled data, and prices computed before then
    are not recalculated once fresh data lands. Use `wait_prices_updated_sync` or
    `wait_prices_updated_async` if you need fresh prices before calculating.

    If an `UpdatePrices` instance has already been started manually, no second updater is started
    and the returned handle does nothing on close — prices are already being kept up to date. Such
    a handle stays inert: if the manual updater is later stopped, background updates stop with it,
    and a new handle must be acquired to restart them.

    Set the `GENAI_PRICES_DISABLE_AUTO_UPDATE` environment variable to any non-empty value to
    disable this function entirely: it returns a do-nothing handle and no updater is started.

    Returns:
        A handle that stops the shared background updater when all handles have been closed.
    """
    global _global_update_prices, _managed_update_prices, _managed_update_prices_ref_count

    if os.environ.get('GENAI_PRICES_DISABLE_AUTO_UPDATE'):
        return UpdatePricesHandle()

    with _global_update_prices_lock:
        if _managed_update_prices is not None:
            _managed_update_prices_ref_count += 1
            return UpdatePricesHandle(_managed_update_prices)

        if _global_update_prices is not None:
            # A manually started UpdatePrices is already keeping prices fresh; don't start a
            # second updater and don't claim the manual one — its owner controls its lifetime.
            return UpdatePricesHandle()

        update_prices = UpdatePrices()
        _global_update_prices = update_prices
        _managed_update_prices = update_prices
        _managed_update_prices_ref_count = 1
        try:
            update_prices._start_thread()  # pyright: ignore[reportPrivateUsage]
        except Exception:
            _global_update_prices = None
            _managed_update_prices = None
            _managed_update_prices_ref_count = 0
            raise

        return UpdatePricesHandle(update_prices)


@dataclass
class UpdatePricesHandle:
    """A claim on the shared background updater started by `update_prices_in_background`.

    A handle only releases the updater it was created for: handles constructed directly, or
    outliving the updater they belong to, are inert and closing them does nothing.
    """

    _update_prices: UpdatePrices | None = None
    _closed: bool = field(default=False, init=False)

    def close(self):
        """Release this handle's claim on the shared updater.

        Stops the updater if this was the last open handle. Idempotent, and never raises:
        errors from the background updater are logged instead.
        """
        global _global_update_prices, _managed_update_prices, _managed_update_prices_ref_count

        with _global_update_prices_lock:
            if self._closed:
                return

            self._closed = True
            if self._update_prices is None or _managed_update_prices is not self._update_prices:
                return

            _managed_update_prices_ref_count -= 1
            if _managed_update_prices_ref_count > 0:
                return

            update_prices = self._update_prices
            _global_update_prices = None
            _managed_update_prices = None
            _managed_update_prices_ref_count = 0
            try:
                update_prices._stop_thread()  # pyright: ignore[reportPrivateUsage]
            except Exception as e:
                logger.error('Error from genai-prices background updater while closing (%s): %s', type(e).__name__, e)


@dataclass
class UpdatePrices:
    """Update prices in the background using a daemon thread.

    Can be used either as a context manager or as a simple class, where you'll need to call start() and stop() manually.
    """

    update_interval: float = 3600
    """How often to update prices in seconds."""
    url: str = DEFAULT_UPDATE_URL
    """The URL to fetch prices from."""
    request_timeout: httpx2.Timeout = field(default_factory=lambda: httpx2.Timeout(timeout=10, connect=5))
    """The timeout for HTTP requests."""
    _stop_event: threading.Event = field(default_factory=threading.Event)
    _prices_updated: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = field(default=None, init=False)
    _background_exc: Exception | None = field(default=None, init=False)

    def start(self, *, wait: bool | float = False):
        """Start the background task.

        Args:
            wait: Whether to wait for the prices to be updated before returning, if an int is passed
                wait for that many seconds, if `True` wait for 30 seconds.
        """
        global _global_update_prices

        with _global_update_prices_lock:
            if self._thread is not None:
                raise RuntimeError('UpdatePrices background task already started')

            if _global_update_prices is not None:
                raise RuntimeError(
                    'UpdatePrices global task already started, only one UpdatePrices can be active at a time'
                )

            _global_update_prices = self
            try:
                self._start_thread()
            except Exception:
                _global_update_prices = None
                raise

        if wait:
            self.wait(timeout=30 if wait is True else wait)

    def _start_thread(self) -> None:
        if self._thread is not None:
            raise RuntimeError('UpdatePrices background task already started')

        self._prices_updated.clear()
        self._stop_event.clear()
        self._background_exc = None
        self._thread = threading.Thread(target=self._background_task, daemon=True, name='genai_prices:update')
        self._thread.start()

    def wait(self, timeout: float | None = None) -> bool:
        """Wait for the prices to be updated in the background task.

        Args:
            timeout: The maximum time to wait for the prices to be updated in seconds.
        """
        prices_updated = self._prices_updated.wait(timeout=timeout)
        exc = self._background_exc
        if exc:
            self._background_exc = None
            raise exc
        return prices_updated

    def stop(self):
        """Stop the background task."""
        global _global_update_prices, _managed_update_prices, _managed_update_prices_ref_count

        with _global_update_prices_lock:
            if self._thread is None:
                return

            if _global_update_prices is self:
                _global_update_prices = None
            if _managed_update_prices is self:
                _managed_update_prices = None
                _managed_update_prices_ref_count = 0
            self._stop_thread()

    def _stop_thread(self) -> None:
        if self._thread is not None:
            self._stop_event.set()
            self._thread.join()
            self._thread = None
        # Clear after the thread exits so an in-flight fetch cannot reinstall a snapshot after stop().
        data_snapshot.set_custom_snapshot(None)
        if self._background_exc:
            exc = self._background_exc
            self._background_exc = None
            raise exc

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_args: object):
        self.stop()

    def _background_task(self) -> None:
        logger.info('Starting genai-prices background task')
        try:
            while True:
                try:
                    self._update_prices()
                    self._prices_updated.set()
                    self._background_exc = None
                except Exception as e:
                    self._background_exc = e
                    self._prices_updated.set()
                    logger.error('Error updating genai-prices in the background (%s): %s', type(e).__name__, e)
                if self._stop_event.wait(self.update_interval):
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

    def fetch(self) -> data_snapshot.DataSnapshot | None:
        """Fetches the latest provider data from the configured URL."""
        from . import data

        r = httpx2.get(self.url, timeout=self.request_timeout)
        r.raise_for_status()
        return data_snapshot.DataSnapshot(data.providers_schema.validate_json(r.content), from_auto_update=True)
