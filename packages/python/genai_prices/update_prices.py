from __future__ import annotations as _annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from time import time

import httpx

from . import calc

__all__ = (
    'DEFAULT_UPDATE_URL',
    'UpdatePrices',
    'wait_prices_updated_sync',
    'wait_prices_updated_async',
)

logger = logging.getLogger('genai-prices')
DEFAULT_UPDATE_URL = 'https://raw.githubusercontent.com/pydantic/genai-prices/refs/heads/main/prices/data.json'
_prices_updated = threading.Event()


def wait_prices_updated_sync(timeout: float | None = None) -> bool:
    """Synchronously wait for prices to be updated.

    Args:
        timeout: The maximum time to wait for prices to be updated. Defaults to None which waits indefinitely.

    Returns:
        True if prices were updated, False otherwise.
    """
    return _prices_updated.wait(timeout)


async def wait_prices_updated_async(timeout: float | None = None) -> bool:
    """Asynchronously wait for prices to be updated.

    Args:
        timeout: The maximum time to wait for prices to be updated. Defaults to None which waits indefinitely.

    Returns:
        True if prices were updated, False otherwise.
    """
    return await asyncio.to_thread(wait_prices_updated_sync, timeout)


@dataclass
class UpdatePrices:
    """Update prices in the background using a daemon thread.

    Can be used either as a context manager or as a simple class, where you'll need to call start() and stop() manually.
    """

    update_interval: float = 3600
    """How often to update prices in seconds."""
    url: str = DEFAULT_UPDATE_URL
    """The URL to fetch prices from."""
    request_timeout: httpx.Timeout = field(default_factory=lambda: httpx.Timeout(timeout=10, connect=5))
    """The timeout for HTTP requests."""
    wait: bool = False
    """Whether to wait for the prices to be updated before returning from `start` or `__enter__`."""
    _stop_event: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = field(default=None, init=False)
    _background_exc: Exception | None = field(default=None, init=False)

    def start(self, wait: bool = False):
        """Start the background task."""
        if self._thread is not None:
            raise RuntimeError('UpdatePrices background task already started')

        _prices_updated.clear()
        self._stop_event.clear()
        self._background_exc = None
        self._thread = threading.Thread(target=self._background_task, daemon=True, name='genai_prices:update')
        self._thread.start()
        if wait or self.wait:
            _prices_updated.wait()
            if self._background_exc:
                raise self._background_exc

    def stop(self):
        """Stop the background task."""
        calc.set_custom_snapshot(None)
        if self._thread is not None:
            self._stop_event.set()
            self._thread.join()
            self._thread = None
            if self._background_exc:
                raise self._background_exc

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_args: object):
        self.stop()

    def _background_task(self) -> None:
        try:
            self._update_prices()
            _prices_updated.set()
            while True:
                if self._stop_event.wait(self.update_interval):
                    break
                self._update_prices()
        except Exception as e:
            _prices_updated.set()
            logger.error('Error updating genai-prices in the background (%s): %s', type(e).__name__, e)
            self._background_exc = e

    def _update_prices(self):
        start = time()
        snapshot = self.fetch()
        interval = time() - start
        if snapshot:
            logger.info('Successfully fetched %d providers in %.2f seconds', len(snapshot.providers), interval)
        else:
            logger.info('Successfully fetched null snapshot in %.2f seconds', interval)

        calc.set_custom_snapshot(snapshot)

    def fetch(self) -> calc.DataSnapshot | None:
        """Fetches the latest provider data from the configured URL."""
        from . import data

        r = httpx.get(self.url, timeout=self.request_timeout)
        r.raise_for_status()
        return calc.DataSnapshot(data.providers_schema.validate_json(r.content), from_auto_update=True)
