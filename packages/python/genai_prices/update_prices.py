from __future__ import annotations as _annotations

import asyncio
import json
import logging
import threading
import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from time import time
from types import TracebackType
from typing import NamedTuple

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


class _Config(NamedTuple):
    url: str
    update_interval: float
    request_timeout: httpx2.Timeout


# All instances share one worker so libraries can opt in independently without duplicate threads.
# The one lock guards the worker reference, claim counts, and snapshot install/restore, and is
# never held across anything that blocks — stop() signals the worker instead of joining it — so
# it cannot deadlock and Ctrl-C has nothing to interrupt.
_lock = threading.Lock()
_worker: _Worker | None = None


def wait_prices_updated_sync(timeout: float | None = None) -> bool:
    """Synchronously wait for prices to be updated by the shared background updater.

    A fetch failure is raised to every waiter until a later fetch succeeds.

    Args:
        timeout: The maximum time to wait for prices to be updated. Defaults to None which waits indefinitely.

    Returns:
        True if prices were updated, False otherwise.
    """
    with _lock:
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
        True if prices were updated, False otherwise.
    """
    return await asyncio.to_thread(wait_prices_updated_sync, timeout)


@dataclass
class UpdatePrices:
    """Update prices in the background using a shared daemon thread.

    All instances share one process-wide worker: the first `start()` launches it, later `start()`
    calls join it, and the last `stop()` shuts it down and restores the bundled prices. The first
    configuration wins: joining with a different one warns and keeps the running worker's settings,
    which are captured at `start()` — changing attributes afterwards has no effect on it.

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

        with _lock:
            if self._worker is not None:
                raise RuntimeError('UpdatePrices background task already started')

            # Copy the mutable Timeout so the worker's configuration is frozen at launch.
            config = _Config(self.url, self.update_interval, httpx2.Timeout(self.request_timeout))
            worker = _worker
            if worker is not None and worker.dead:
                # Don't join a worker that died unexpectedly; start a replacement.
                _log(logger.warning, 'UpdatePrices background task terminated unexpectedly; starting a new one')
                worker = None
            if worker is None:
                worker = _Worker(config, self.fetch)
                worker.claims = 1
                try:
                    _worker = worker
                    self._worker = worker
                    worker.thread.start()
                except BaseException:
                    # Thread.start() can fail after the OS thread launched; a shut-down worker
                    # exits on its own, so releasing ownership is the whole rollback.
                    worker.shutdown()
                    _worker = None
                    self._worker = None
                    raise
            else:
                if worker.config != config:
                    warnings.warn(
                        'UpdatePrices background task is already running with different configuration; keeping '
                        f'url={worker.config.url!r}, update_interval={worker.config.update_interval!r}, '
                        f'request_timeout={worker.config.request_timeout!r}',
                        stacklevel=2,
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
            True if prices were updated, False otherwise.
        """
        worker = self._worker
        if worker is None:
            return False
        return worker.wait(timeout)

    def stop(self):
        """Stop the background task, or release this instance's claim on it.

        The last `stop()` restores the bundled prices and signals the worker, which discards any
        in-flight fetch and exits on its own; fetch failures never make `stop()` raise.
        """
        global _worker

        with _lock:
            worker = self._worker
            if worker is None:
                return
            self._worker = None
            worker.claims -= 1
            if worker.claims == 0:
                worker.shutdown()
                if _worker is worker:
                    # A dead worker may already have been replaced; only the current worker's
                    # retirement restores the bundled prices.
                    _worker = None
                    data_snapshot.set_custom_snapshot(None)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_args: object):
        self.stop()

    def fetch(self) -> data_snapshot.DataSnapshot | None:
        """Fetches the latest provider data from the configured URL."""
        return _fetch_prices(self.url, self.request_timeout)


def _fetch_prices(url: str, request_timeout: httpx2.Timeout) -> data_snapshot.DataSnapshot:
    from .types import _providers_from_raw  # pyright: ignore[reportPrivateUsage]

    r = httpx2.get(url, timeout=request_timeout)
    r.raise_for_status()
    raw_payload = json.loads(r.content)
    if not isinstance(raw_payload, list):
        raise ValueError('Expected fetched prices payload to be a provider array')

    providers = _providers_from_raw(raw_payload)
    return data_snapshot.DataSnapshot(providers, from_auto_update=True)


class _Worker:
    """The process-wide background thread shared by all started `UpdatePrices` instances."""

    def __init__(self, config: _Config, fetch: Callable[[], data_snapshot.DataSnapshot | None]) -> None:
        self.config = config
        if getattr(fetch, '__func__', None) is UpdatePrices.fetch:
            # The default fetch uses the frozen launch config; an overridden fetch controls what it reads.
            self.fetch: Callable[[], data_snapshot.DataSnapshot | None] = lambda: _fetch_prices(
                config.url, config.request_timeout
            )
        else:
            self.fetch = fetch
        self.claims = 0
        self.dead = False
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True, name='genai_prices:update')
        # `ready` is set once there is an outcome to report (or the worker was stopped without
        # one); `_outcome` is a single reference so it can be published and read atomically.
        self.ready = threading.Event()
        self._outcome: tuple[Exception | None, TracebackType | None] | None = None

    def wait(self, timeout: float | None) -> bool:
        if threading.current_thread() is self.thread:
            raise RuntimeError('UpdatePrices background task cannot wait for itself')
        if not self.ready.wait(timeout=timeout):
            return False
        outcome = self._outcome
        if outcome is None:
            # Stopped before any fetch finished.
            return False
        error, error_traceback = outcome
        if error is not None:
            # Re-raise with the original traceback so waiters don't accumulate each other's frames.
            raise error.with_traceback(error_traceback)
        return True

    def shutdown(self) -> None:
        """Discard future updates; the thread exits on its own.

        Runs under `_lock` and must not block: an in-flight fetch is not waited for, and its
        result is discarded because installs check `stop_event` under the same lock.
        """
        self.stop_event.set()
        # Wake any waiter still blocked before the first fetch; with no outcome, wait() returns False.
        self.ready.set()

    def _publish(self, error: Exception | None) -> None:
        self._outcome = (error, error.__traceback__ if error is not None else None)
        self.ready.set()

    def _run(self) -> None:
        try:
            _log(logger.info, 'Starting genai-prices background task')
            while not self.stop_event.is_set():
                try:
                    self._update_prices()
                except Exception as e:
                    self._publish(e)
                    _log(logger.error, 'Error updating genai-prices in the background (%s): %s', type(e).__name__, e)
                if self.stop_event.wait(self.config.update_interval):
                    break
        except BaseException as e:
            # Nothing above should raise this; if it does, fail waiters instead of hanging them.
            self.dead = True
            error = RuntimeError('UpdatePrices background task terminated unexpectedly')
            error.__cause__ = e
            self._publish(error)
        finally:
            _log(logger.info, 'genai-prices background task stopped')

    def _update_prices(self) -> None:
        start = time()
        snapshot = self.fetch()
        interval = time() - start
        if snapshot:
            _log(logger.info, 'Successfully fetched %d providers in %.2f seconds', len(snapshot.providers), interval)
        else:
            _log(logger.info, 'Successfully fetched null snapshot in %.2f seconds', interval)

        with _lock:
            if self.stop_event.is_set():
                # A stop() already won: its discarded fetch is not an update, so install and publish nothing.
                return
            data_snapshot.set_custom_snapshot(snapshot)
        self._publish(None)


def _log(log: Callable[..., None], message: str, *args: object) -> None:
    try:
        log(message, *args)
    except Exception:
        # A broken logging handler must not kill background updates or dump thread tracebacks.
        pass
