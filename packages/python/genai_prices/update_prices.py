from __future__ import annotations as _annotations

import asyncio
import json
import logging
import threading
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

# All instances share one background thread, so libraries can opt in independently without duplicate
# threads. The thread runs while any instance is started and uses the settings and `fetch()` of the
# last one started. The one lock guards this state and is never held across anything that blocks.
_lock = threading.Lock()
_ref_count = 0
"""How many instances are started."""
_fetcher: UpdatePrices | None = None
"""The instance whose settings and `fetch()` the thread uses; None once no instance is started."""
_thread: threading.Thread | None = None
"""The thread doing the work, if any."""
_wake = threading.Event()
"""Set by the last `stop()` so a sleeping thread notices it is no longer needed."""
_ready = threading.Event()
"""Set once the thread has an outcome to report, or exited without one."""
_outcome: tuple[Exception | None, TracebackType | None] | None = None
"""A single reference so it can be published and read atomically."""


def wait_prices_updated_sync(timeout: float | None = None) -> bool:
    """Synchronously wait for prices to be updated by the shared background updater.

    A fetch failure is raised to every waiter until a later fetch succeeds.

    Args:
        timeout: The maximum time to wait for prices to be updated. Defaults to None which waits indefinitely.

    Returns:
        True if prices were updated, False otherwise.
    """
    with _lock:
        if _ref_count == 0:
            return False
    return _wait(timeout)


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

    All instances share one process-wide thread. It runs while any instance is started: the first
    `start()` launches it, later `start()` calls join it, and the last `stop()` lets it exit. It uses
    the settings and `fetch()` of the instance started most recently, from the next fetch on.
    Prices already fetched stay in use after `stop()`.

    Can be used either as a context manager or as a simple class, where you'll need to call start() and stop() manually.
    """

    update_interval: float = 3600
    """How often to update prices in seconds."""
    url: str = DEFAULT_UPDATE_URL
    """The URL to fetch prices from."""
    request_timeout: httpx2.Timeout = field(default_factory=lambda: httpx2.Timeout(timeout=10, connect=5))
    """The timeout for HTTP requests."""
    _started: bool = field(default=False, init=False, repr=False)

    def start(self, *, wait: bool | float = False):
        """Start the background task, or join the one already running with this instance's settings.

        Args:
            wait: Whether to wait for the prices to be updated before returning, if an int is passed
                wait for that many seconds, if `True` wait for 30 seconds.
        """
        global _ref_count, _fetcher, _thread, _outcome

        with _lock:
            if self._started:
                raise RuntimeError('UpdatePrices background task already started')

            previous = _fetcher
            if previous is not None and (self.url, self.update_interval, self.request_timeout) != (
                previous.url,
                previous.update_interval,
                previous.request_timeout,
            ):
                logger.info(
                    'genai-prices background task now using url=%r, update_interval=%r, request_timeout=%r',
                    self.url,
                    self.update_interval,
                    self.request_timeout,
                )
            _fetcher = self
            self._started = True
            _ref_count += 1

            if _thread is None:
                # A new run: waiters see only what this thread reports.
                _outcome = None
                _ready.clear()
                _thread = threading.Thread(target=_run, daemon=True, name='genai_prices:update')
                try:
                    _thread.start()
                except BaseException:
                    # Thread.start() can fail after the OS thread launched; it exits on its own once
                    # it sees it is not the current thread.
                    _thread = None
                    _fetcher = previous
                    self._started = False
                    _ref_count -= 1
                    raise

        if wait:
            self.wait(timeout=30 if wait is True else wait)

    def wait(self, timeout: float | None = None) -> bool:
        """Wait for the prices to be updated in the background task.

        A fetch failure is raised to every waiter until a later fetch succeeds.

        Args:
            timeout: The maximum time to wait for the prices to be updated in seconds.

        Returns:
            True if prices were updated, False otherwise.
        """
        if not self._started:
            return False
        return _wait(timeout)

    def stop(self):
        """Stop the background task, or release this instance's reference to it.

        The last `stop()` never blocks: the thread finishes any in-flight fetch, whose prices are
        used, and exits on its own.
        Prices already fetched stay in use; they never revert to the bundled data. Fetch failures
        never make `stop()` raise, and `stop()` on a never-started instance does nothing.
        """
        global _ref_count, _fetcher

        with _lock:
            if not self._started:
                return
            self._started = False
            _ref_count -= 1
            if _ref_count == 0:
                _fetcher = None
                _wake.set()

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


def _wait(timeout: float | None) -> bool:
    if threading.current_thread() is _thread:
        raise RuntimeError('UpdatePrices background task cannot wait for itself')
    if not _ready.wait(timeout=timeout):
        return False
    outcome = _outcome
    if outcome is None:
        # Stopped before any fetch finished.
        return False
    error, error_traceback = outcome
    if error is not None:
        # Re-raise with the original traceback so waiters don't accumulate each other's frames.
        raise error.with_traceback(error_traceback)
    return True


def _publish(error: Exception | None) -> None:
    global _outcome
    _outcome = (error, error.__traceback__ if error is not None else None)
    _ready.set()


def _run() -> None:
    """The shared background thread: fetch while any instance is started, then exit."""
    global _thread

    me = threading.current_thread()
    try:
        logger.info('Starting genai-prices background task')
        while True:
            with _lock:
                if _thread is not me:
                    # This launch was interrupted and another thread does the work now.
                    return
                fetcher = _fetcher
                if fetcher is None:
                    _thread = None
                    # Release any waiter still blocked before the first fetch; with no outcome, wait() returns False.
                    _ready.set()
                    return
                _wake.clear()
            try:
                _update_prices(fetcher)
            except Exception as e:
                _publish(e)
                logger.error('Error updating genai-prices in the background (%s): %s', type(e).__name__, e)
            _wake.wait(fetcher.update_interval)
    except BaseException as e:
        # Nothing above should raise this; if it does, fail waiters instead of hanging them.
        with _lock:
            if _thread is me:  # pragma: no branch - a superseded launch exits before it can raise
                _thread = None
        error = RuntimeError('UpdatePrices background task terminated unexpectedly')
        error.__cause__ = e
        _publish(error)
    finally:
        logger.info('genai-prices background task stopped')


def _update_prices(fetcher: UpdatePrices) -> None:
    start = time()
    snapshot = fetcher.fetch()
    interval = time() - start
    if snapshot:
        logger.info('Successfully fetched %d providers in %.2f seconds', len(snapshot.providers), interval)
    else:
        logger.info('Successfully fetched null snapshot in %.2f seconds', interval)

    data_snapshot.set_custom_snapshot(snapshot)
    _publish(None)
