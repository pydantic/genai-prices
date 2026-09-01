from __future__ import annotations as _annotations

import asyncio
import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
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

_Config = tuple[str, float, httpx2.Timeout]

# All UpdatePrices instances share one worker so that libraries and applications can opt in
# independently without creating duplicate threads. `_lock` guards `_worker` and is held for the
# whole of start() and stop() — including the final join — so lifecycle transitions never overlap.
_lock = threading.Lock()
_worker: _Worker | None = None


def wait_prices_updated_sync(timeout: float | None = None) -> bool:
    """Synchronously wait for prices to be updated by the shared background updater.

    A fetch failure is raised to every waiter until a later fetch succeeds.

    Args:
        timeout: The maximum time to wait for prices to be updated. Defaults to None which waits indefinitely.

    Returns:
        True if prices were updated, False if no updater is active or the timeout elapses.
    """
    worker = _worker
    if worker is None:
        return False
    return worker.wait(timeout)


async def wait_prices_updated_async(timeout: float | None = None) -> bool:
    """Asynchronously wait for prices to be updated by the shared background updater.

    A fetch failure is raised to every waiter until a later fetch succeeds.

    Args:
        timeout: The maximum time to wait for prices to be updated. Defaults to None which waits indefinitely.

    Returns:
        True if prices were updated, False if no updater is active or the timeout elapses.
    """
    return await asyncio.to_thread(wait_prices_updated_sync, timeout)


@dataclass
class UpdatePrices:
    """Update prices in the background using a shared daemon thread.

    All instances share one process-wide worker: the first `start()` launches it, later compatible
    `start()` calls join it, and the last `stop()` shuts it down and restores the bundled prices.
    Starting with different configuration than the running worker raises `RuntimeError`.

    Can be used either as a context manager or as a simple class, where you'll need to call start() and stop() manually.
    """

    update_interval: float = 3600
    """How often to update prices in seconds."""
    url: str = DEFAULT_UPDATE_URL
    """The URL to fetch prices from."""
    request_timeout: httpx2.Timeout = field(default_factory=lambda: httpx2.Timeout(timeout=10, connect=5))
    """The timeout for HTTP requests."""
    _worker: _Worker | None = field(default=None, init=False, repr=False)

    def start(self, *, wait: bool | float = False):
        """Start the background task, or join the one already running.

        Args:
            wait: Whether to wait for the prices to be updated before returning, if an int is passed
                wait for that many seconds, if `True` wait for 30 seconds.
        """
        global _worker

        _check_not_worker_thread('start')
        with _lock:
            if self._worker is not None:
                raise RuntimeError('UpdatePrices background task already started')

            config: _Config = (self.url, self.update_interval, self.request_timeout)
            worker = _worker
            if worker is None:
                worker = _Worker(config, self.fetch)
                worker.claims = 1
                # Publish before starting the thread so the worker-thread guards see it from the
                # very first fetch.
                _worker = worker
                self._worker = worker
                try:
                    worker.thread.start()
                except BaseException:
                    _worker = None
                    self._worker = None
                    raise
            else:
                if worker.dead:
                    raise RuntimeError('UpdatePrices background task terminated unexpectedly')
                if worker.config != config:
                    url, update_interval, request_timeout = worker.config
                    raise RuntimeError(
                        'UpdatePrices background task already started with different configuration: '
                        f'url={url!r}, update_interval={update_interval!r}, request_timeout={request_timeout!r}'
                    )
                worker.claims += 1
                self._worker = worker

        if wait:
            worker.wait(timeout=30 if wait is True else wait)

    def wait(self, timeout: float | None = None) -> bool:
        """Wait for the prices to be updated in the background task.

        A fetch failure is raised to every waiter until a later fetch succeeds.

        Args:
            timeout: The maximum time to wait for the prices to be updated in seconds.

        Returns:
            True if prices were updated, False if this instance is not started or the timeout elapses.
        """
        worker = self._worker
        if worker is None:
            return False
        return worker.wait(timeout)

    def stop(self):
        """Stop the background task, or release this instance's claim on it.

        The last `stop()` waits for any in-flight fetch, stops the worker and restores the bundled
        prices. Fetch failures never make `stop()` raise; they are reported by `wait()`.
        """
        global _worker

        _check_not_worker_thread('stop')
        with _lock:
            worker = self._worker
            if worker is None:
                return
            self._worker = None
            worker.claims -= 1
            if worker.claims == 0:
                worker.shutdown()
                _worker = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_args: object):
        self.stop()

    def fetch(self) -> data_snapshot.DataSnapshot | None:
        """Fetches the latest provider data from the configured URL."""
        from .types import _providers_from_raw  # pyright: ignore[reportPrivateUsage]

        r = httpx2.get(self.url, timeout=self.request_timeout)
        r.raise_for_status()
        raw_payload = json.loads(r.content)
        if not isinstance(raw_payload, list):
            raise ValueError('Expected fetched prices payload to be a provider array')

        providers = _providers_from_raw(raw_payload)
        return data_snapshot.DataSnapshot(providers, from_auto_update=True)


def _check_not_worker_thread(action: str) -> None:
    # start() and stop() block on `_lock`, which the last stop() holds while joining the worker,
    # so calling them from a `fetch()` override would deadlock.
    worker = _worker
    if worker is not None and threading.current_thread() is worker.thread:
        raise RuntimeError(f'UpdatePrices background task cannot call {action} from its worker')


class _Worker:
    """The process-wide background thread shared by all started `UpdatePrices` instances."""

    def __init__(self, config: _Config, fetch: Callable[[], data_snapshot.DataSnapshot | None]) -> None:
        self.config = config
        self.fetch = fetch
        self.claims = 0
        self.dead = False
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True, name='genai_prices:update')
        # The latest fetch outcome, reported to every waiter.
        self.ready = threading.Event()
        self._outcome_lock = threading.Lock()
        self._error: Exception | None = None
        self._error_traceback: TracebackType | None = None
        self._succeeded = False

    def wait(self, timeout: float | None) -> bool:
        if threading.current_thread() is self.thread:
            raise RuntimeError('UpdatePrices background task cannot wait for itself')
        if not self.ready.wait(timeout=timeout):
            return False
        with self._outcome_lock:
            error, error_traceback, succeeded = self._error, self._error_traceback, self._succeeded
        if error is not None:
            # Re-raise with the original traceback so waiters don't accumulate each other's frames.
            raise error.with_traceback(error_traceback)
        return succeeded

    def shutdown(self) -> None:
        self.stop_event.set()
        self.thread.join()
        # Clear after the thread exits so an in-flight fetch cannot reinstall fetched state after stop().
        data_snapshot.set_custom_snapshot(None)
        # Wake any waiter still blocked before the first fetch finished; with no outcome, wait() returns False.
        self.ready.set()

    def _publish(self, error: Exception | None) -> None:
        with self._outcome_lock:
            self._error = error
            self._error_traceback = error.__traceback__ if error is not None else None
            self._succeeded = error is None
            self.ready.set()

    def _run(self) -> None:
        logger.info('Starting genai-prices background task')
        try:
            while not self.stop_event.is_set():
                try:
                    self._update_prices()
                except Exception as e:
                    self._publish(e)
                    logger.error('Error updating genai-prices in the background (%s): %s', type(e).__name__, e)
                else:
                    self._publish(None)
                if self.stop_event.wait(self.config[1]):
                    break
        except BaseException as e:
            # Nothing above should raise this; if it does, fail waiters and joiners instead of hanging them.
            self.dead = True
            error = RuntimeError('UpdatePrices background task terminated unexpectedly')
            error.__cause__ = e
            self._publish(error)
        finally:
            logger.info('genai-prices background task stopped')

    def _update_prices(self) -> None:
        start = time()
        snapshot = self.fetch()
        interval = time() - start
        if snapshot:
            logger.info('Successfully fetched %d providers in %.2f seconds', len(snapshot.providers), interval)
        else:
            logger.info('Successfully fetched null snapshot in %.2f seconds', interval)

        data_snapshot.set_custom_snapshot(snapshot)
