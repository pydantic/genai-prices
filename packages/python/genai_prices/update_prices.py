from __future__ import annotations as _annotations

import asyncio
import json
import logging
import threading
from dataclasses import dataclass, field
from time import time

import httpx2

from . import data_snapshot, runtime_state
from .decode_provider_data import decode_v2_payload
from .units import UnitRegistry

__all__ = (
    'DEFAULT_UPDATE_URL',
    'UpdatePrices',
    'wait_prices_updated_sync',
    'wait_prices_updated_async',
)

logger = logging.getLogger('genai-prices')
DEFAULT_UPDATE_URL = 'https://raw.githubusercontent.com/pydantic/genai-prices/refs/heads/main/prices/data_v2.json'
_global_update_prices: UpdatePrices | None = None
_global_update_prices_lock = threading.Lock()


class _UpdaterStoppingError(RuntimeError):
    pass


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
    request_timeout: httpx2.Timeout = field(default_factory=lambda: httpx2.Timeout(timeout=10, connect=5))
    """The timeout for HTTP requests."""
    _stop_event: threading.Event = field(default_factory=threading.Event)
    _prices_updated: threading.Event = field(default_factory=threading.Event)
    _initial_attempt_started: threading.Event = field(default_factory=threading.Event)
    _lifecycle_lock: threading.RLock = field(default_factory=threading.RLock)
    _thread: threading.Thread | None = field(default=None, init=False)
    _background_exc: Exception | None = field(default=None, init=False)
    _initial_attempt_completed: bool = field(default=False, init=False)
    _stopping: bool = field(default=False, init=False)

    def start(self, *, wait: bool | float = False) -> None:
        """Start the background task.

        Args:
            wait: Whether to wait for the prices to be updated before returning, if an int is passed
                wait for that many seconds, if `True` wait for 30 seconds.
        """
        global _global_update_prices

        with self._lifecycle_lock:
            if self._thread is not None:
                raise RuntimeError('UpdatePrices background task already started')

            with _global_update_prices_lock:
                if _global_update_prices is not None:
                    raise RuntimeError(
                        'UpdatePrices global task already started, only one UpdatePrices can be active at a time'
                    )
                _global_update_prices = self

            self._stopping = False
            self._prices_updated.clear()
            self._initial_attempt_started.clear()
            self._stop_event.clear()
            self._background_exc = None
            self._initial_attempt_completed = False
            self._thread = threading.Thread(target=self._background_task, daemon=True, name='genai_prices:update')
            self._thread.start()
        self._initial_attempt_started.wait()
        if wait:
            self.wait(timeout=30 if wait is True else wait)

    def wait(self, timeout: float | None = None) -> bool:
        """Wait for the prices to be updated in the background task.

        Args:
            timeout: The maximum time to wait for the prices to be updated in seconds.
        """
        update_finished = self._prices_updated.wait(timeout=timeout)
        exc = self._background_exc
        if exc:
            self._background_exc = None
            raise exc
        return update_finished and self._initial_attempt_completed

    def stop(self) -> None:
        """Stop the background task."""
        global _global_update_prices

        with self._lifecycle_lock:
            self._stopping = True
            stop_generation = runtime_state.begin_update()
            self._stop_event.set()
            thread = self._thread
            with _global_update_prices_lock:
                if _global_update_prices is self:
                    _global_update_prices = None

        if thread is not None:
            thread.join()

        with self._lifecycle_lock:
            self._thread = None

        runtime_state.restore_bundled_providers(stop_generation)
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
            while not self._stop_event.is_set():
                try:
                    self._update_prices()
                    self._background_exc = None
                    self._initial_attempt_completed = True
                    self._prices_updated.set()
                except _UpdaterStoppingError:
                    self._initial_attempt_started.set()
                    self._prices_updated.set()
                    break
                except Exception as e:
                    self._initial_attempt_started.set()
                    self._background_exc = e
                    self._prices_updated.set()
                    logger.error('Error updating genai-prices in the background (%s): %s', type(e).__name__, e)
                if self._stop_event.wait(self.update_interval):
                    break

        finally:
            logger.info('genai-prices background task stopped')

    def _update_prices(self) -> None:
        start = time()
        if type(self).fetch is UpdatePrices.fetch:
            snapshot = self.fetch()
        else:
            generation = self._begin_fetch()
            snapshot = self.fetch()
            if snapshot is not None:
                active = runtime_state.get_runtime_data()
                runtime_state.activate_runtime_data(
                    generation,
                    runtime_state.RuntimeData(registry=active.registry, snapshot=snapshot),
                )
        interval = time() - start
        if snapshot:
            logger.info('Successfully fetched %d providers in %.2f seconds', len(snapshot.providers), interval)
        else:
            logger.info('Successfully fetched null snapshot in %.2f seconds', interval)

    def fetch(self) -> data_snapshot.DataSnapshot | None:
        """Fetches the latest provider data from the configured URL."""
        from .types import (
            _providers_from_raw,  # pyright: ignore[reportPrivateUsage]
            _validate_provider_price_coverage,  # pyright: ignore[reportPrivateUsage]
        )

        generation = self._begin_fetch()
        r = httpx2.get(self.url, timeout=self.request_timeout)
        r.raise_for_status()
        raw_payload = decode_v2_payload(json.loads(r.content))
        registry = UnitRegistry.from_untrusted(raw_payload['units'])
        providers = _providers_from_raw(raw_payload['providers'], registry)
        _validate_provider_price_coverage(providers, registry)
        snapshot = data_snapshot.DataSnapshot(providers, from_auto_update=True)
        candidate = runtime_state.RuntimeData(registry=registry, snapshot=snapshot)
        if runtime_state.activate_runtime_data(generation, candidate):
            return snapshot
        return runtime_state.get_runtime_data().snapshot

    def _begin_fetch(self) -> int:
        with self._lifecycle_lock:
            if self._stopping:
                raise _UpdaterStoppingError('UpdatePrices is stopping and cannot start another fetch')
            generation = runtime_state.begin_update()
            self._initial_attempt_started.set()
            return generation
