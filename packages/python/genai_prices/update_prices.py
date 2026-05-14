from __future__ import annotations as _annotations

import asyncio
import json
import logging
import threading
from dataclasses import dataclass, field
from time import time
from typing import Any, cast

import httpx

from . import data_snapshot

__all__ = (
    'DEFAULT_UPDATE_URL',
    'UpdatePrices',
    'wait_prices_updated_sync',
    'wait_prices_updated_async',
)

logger = logging.getLogger('genai-prices')
DEFAULT_UPDATE_URL = 'https://raw.githubusercontent.com/pydantic/genai-prices/refs/heads/main/prices/data.json'
_global_update_prices: UpdatePrices | None = None


def wait_prices_updated_sync(timeout: float | None = None) -> bool:
    """Synchronously wait for prices to be updated.

    Args:
        timeout: The maximum time to wait for prices to be updated. Defaults to None which waits indefinitely.

    Returns:
        True if prices were updated, False otherwise.
    """
    if _global_update_prices:
        return _global_update_prices.wait(timeout)
    return False


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

        if self._thread is not None:
            raise RuntimeError('UpdatePrices background task already started')

        if _global_update_prices is not None:
            raise RuntimeError(
                'UpdatePrices global task already started, only one UpdatePrices can be active at a time'
            )

        _global_update_prices = self
        self._prices_updated.clear()
        self._stop_event.clear()
        self._background_exc = None
        self._thread = threading.Thread(target=self._background_task, daemon=True, name='genai_prices:update')
        self._thread.start()
        if wait:
            self.wait(timeout=30 if wait is True else wait)

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
        global _global_update_prices

        _global_update_prices = None
        if self._thread is not None:
            self._stop_event.set()
            self._thread.join()
            self._thread = None
        # Clear after the thread exits so an in-flight fetch cannot reinstall fetched state after stop().
        data_snapshot.set_custom_snapshot(None)
        from .units import _set_registry  # pyright: ignore[reportPrivateUsage]

        _set_registry(None)
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
        from .types import _providers_from_raw  # pyright: ignore[reportPrivateUsage]
        from .units import UnitRegistry, _get_registry, _set_registry  # pyright: ignore[reportPrivateUsage]

        r = httpx.get(self.url, timeout=self.request_timeout)
        r.raise_for_status()
        raw_payload = json.loads(r.content)
        if not isinstance(raw_payload, dict) or 'units' not in raw_payload or 'providers' not in raw_payload:
            raise ValueError('Expected fetched prices payload to contain units and providers')

        # Published unit data is trusted to evolve compatibly. We only need rollback
        # if this payload's providers fail to parse; no registry-history diff is enforced.
        candidate_registry = UnitRegistry(cast(dict[str, Any], raw_payload['units']))
        previous_registry = _get_registry()
        _set_registry(candidate_registry)
        try:
            providers = _providers_from_raw(raw_payload['providers'])
        except Exception:
            _set_registry(previous_registry)
            raise

        return data_snapshot.DataSnapshot(providers, from_auto_update=True)
