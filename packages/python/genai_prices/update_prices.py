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
    'wait_prices_updated_sync',
    'wait_prices_updated_async',
)

logger = logging.getLogger('genai-prices')
DEFAULT_UPDATE_URL = 'https://raw.githubusercontent.com/pydantic/genai-prices/refs/heads/main/prices/data.json'
DEFAULT_UPDATE_INTERVAL = 3600.0


def _default_request_timeout() -> httpx2.Timeout:
    return httpx2.Timeout(timeout=10, connect=5)


# There is exactly one price snapshot per process (data_snapshot.set_custom_snapshot is a global),
# so "updating prices" is inherently a singleton activity. Every `UpdatePrices` is therefore not an
# updater of its own but a *claim* on one shared, process-wide updater guarded by `_lock`: starting
# any instance acquires a claim (ref-count++), and the background thread stops only when the last
# claim is released.
#
# This module-level state would not survive os.fork() on its own (threads die with the parent, and
# locks can be inherited in a held state, e.g. under gunicorn with preload_app=True). Fork hooks
# registered lazily in _register_fork_hooks() keep it consistent: the lock is held across the fork and
# reinitialized in the child, and a running updater is restarted in place - see _fork_after_in_child.
_updater: _BackgroundUpdater | None = None
_ref_count = 0
_lock = threading.RLock()

_fork_hooks_registered = False


def _register_fork_hooks() -> None:
    """Keep the updater working across os.fork() (e.g. gunicorn with preload_app=True).

    Called under `_lock` from `_BackgroundUpdater._start_thread`, so registration happens at most
    once, and only in processes that actually start an updater.
    """
    global _fork_hooks_registered
    if _fork_hooks_registered or not hasattr(os, 'register_at_fork'):
        return
    _fork_hooks_registered = True
    os.register_at_fork(before=_fork_before, after_in_parent=_fork_after_in_parent, after_in_child=_fork_after_in_child)


def _fork_before() -> None:
    # Hold the lock across the fork so the child inherits consistent bookkeeping rather than a
    # torn, mid-mutation state.
    _lock.acquire()


def _fork_after_in_parent() -> None:
    _lock.release()


def _fork_after_in_child() -> None:
    global _lock, _updater, _ref_count

    # The child inherits the lock acquired in _fork_before; replace it with a fresh one rather
    # than releasing the inherited object.
    _lock = threading.RLock()
    updater = _updater
    if updater is None:
        return
    try:
        # The parent's updater thread does not survive the fork; restart it on the same instance,
        # preserving identity so existing claims remain valid.
        updater._revive_after_fork()  # pyright: ignore[reportPrivateUsage]
    except Exception:
        _updater = None
        _ref_count = 0
        data_snapshot.set_custom_snapshot(None)
        logger.warning('Failed to restart the genai-prices background updater after fork', exc_info=True)


_STOPPED_THREAD_JOIN_TIMEOUT = 5.0


def _join_stopped_updater_thread(thread: threading.Thread | None) -> None:
    """Give a stopped updater thread a short grace period to exit, then abandon it.

    Called outside `_lock` so a thread blocked on an in-flight fetch never stalls other updater
    API calls. Abandonment is safe: the thread is a daemon, it exits as soon as the fetch
    completes, and a stopped updater can never install its result (see `_install_snapshot`).
    """
    if thread is None:
        return
    thread.join(timeout=_STOPPED_THREAD_JOIN_TIMEOUT)
    if thread.is_alive():
        logger.warning(
            'genai-prices background updater thread did not exit within %.0f seconds (a fetch is '
            'likely in flight); abandoning the daemon thread. It will exit once the fetch '
            'completes, without updating prices.',
            _STOPPED_THREAD_JOIN_TIMEOUT,
        )


def wait_prices_updated_sync(timeout: float | None = None) -> bool:
    """Synchronously wait for prices to be updated by the shared background updater.

    Never raises: if the update attempt failed, this returns False - the error is logged on the
    `genai-prices` logger.

    Args:
        timeout: The maximum time to wait for prices to be updated. Defaults to None which waits
            indefinitely.

    Returns:
        True if prices were updated, False otherwise (including when the update failed, or when no
        updater is running).
    """
    with _lock:
        updater = _updater

    if updater is not None:
        return updater._wait_updated(timeout)  # pyright: ignore[reportPrivateUsage]
    return False


async def wait_prices_updated_async(timeout: float | None = None) -> bool:
    """Asynchronously wait for prices to be updated by the shared background updater.

    Never raises: if the update attempt failed, this returns False - the error is logged on the
    `genai-prices` logger.

    Args:
        timeout: The maximum time to wait for prices to be updated. Defaults to None which waits indefinitely.

    Returns:
        True if prices were updated, False otherwise (including when the update failed, or when no
        updater is running).
    """
    return await asyncio.to_thread(wait_prices_updated_sync, timeout)


@dataclass
class UpdatePrices:
    """Periodically update price data by downloading it in a background daemon thread.

    A single shared, process-wide updater backs every `UpdatePrices` instance: starting an instance
    is a *claim* on that one updater, not a private thread. It is therefore safe to create and start
    `UpdatePrices` from anywhere - including from several libraries in the same process. The first
    `start()` launches the updater; later ones join it and bump a reference count; the background
    thread stops (and prices revert to the bundled data) only when the **last** started instance is
    stopped.

    Configuration is first-wins: the first instance to start fixes `url`, `update_interval` and
    `request_timeout` for the updater's lifetime. Starting another instance with different settings
    logs a warning and joins the running updater; its settings are ignored. Application authors who
    need a custom URL should start their instance early, before any library does.

    Can be used as a context manager (`with UpdatePrices(): ...`) or by calling `start()`/`stop()`.
    """

    update_interval: float = DEFAULT_UPDATE_INTERVAL
    """How often to update prices in seconds."""
    url: str = DEFAULT_UPDATE_URL
    """The URL to fetch prices from."""
    request_timeout: httpx2.Timeout = field(default_factory=_default_request_timeout)
    """The timeout for HTTP requests."""
    _claimed: bool = field(default=False, init=False)
    _updater: _BackgroundUpdater | None = field(default=None, init=False)

    def start(self, *, wait: bool | float = False):
        """Acquire this instance's claim on the shared background updater.

        The first claim starts the updater; later claims join it. Starting the same instance twice
        raises `RuntimeError`. This does not wait for the download unless `wait` is passed: until
        the first fetch completes, price calculations keep using the bundled data.

        Args:
            wait: Whether to wait for prices to be updated before returning; if an int/float is
                passed wait that many seconds, if `True` wait for 30 seconds.
        """
        global _updater, _ref_count

        with _lock:
            if self._claimed:
                raise RuntimeError('UpdatePrices background task already started')

            if _updater is None:
                updater = _BackgroundUpdater(
                    url=self.url, update_interval=self.update_interval, request_timeout=self.request_timeout
                )
                _updater = updater
                _ref_count = 1
                try:
                    updater._start_thread()  # pyright: ignore[reportPrivateUsage]
                except Exception:
                    _updater = None
                    _ref_count = 0
                    raise
            else:
                if (
                    _updater.url != self.url
                    or _updater.update_interval != self.update_interval
                    or _updater.request_timeout != self.request_timeout
                ):
                    logger.warning(
                        'A genai-prices background updater is already running (url=%r, update_interval=%r, '
                        'request_timeout=%r); ignoring the different configuration of this UpdatePrices '
                        '(url=%r, update_interval=%r, request_timeout=%r) and joining the existing updater. '
                        'Start the updater before any other caller if you need custom settings.',
                        _updater.url,
                        _updater.update_interval,
                        _updater.request_timeout,
                        self.url,
                        self.update_interval,
                        self.request_timeout,
                    )
                _ref_count += 1

            self._claimed = True
            self._updater = _updater

        if wait:
            self.wait(timeout=30 if wait is True else wait)

    def stop(self):
        """Release this instance's claim on the shared background updater.

        Stops the updater (reverting prices to the bundled data) only if this was the last open
        claim; a claim held by another caller keeps it running. A no-op if this instance was never
        started or has already been stopped.

        Never raises: a stored background fetch error is logged instead - use `wait()` if you want
        the error raised. Returns promptly; if a fetch is in flight the daemon thread is given a
        short grace period to exit before being abandoned with a warning log, and its result is
        discarded - a stopped updater can never install prices afterwards.
        """
        global _updater, _ref_count

        with _lock:
            if not self._claimed:
                return
            self._claimed = False

            updater = self._updater
            self._updater = None
            if updater is None or _updater is not updater:
                return

            _ref_count -= 1
            if _ref_count > 0:
                return

            _updater = None
            _ref_count = 0
            thread = updater._stop_and_detach()  # pyright: ignore[reportPrivateUsage]

        # Join outside the lock so a thread blocked on an in-flight fetch never stalls other
        # updater API calls; re-publication is already fenced off by _stop_and_detach().
        _join_stopped_updater_thread(thread)
        exc = updater._background_exc  # pyright: ignore[reportPrivateUsage]
        if exc:
            updater._background_exc = None  # pyright: ignore[reportPrivateUsage]
            logger.error('Error from genai-prices background updater while stopping', exc_info=exc)

    def wait(self, timeout: float | None = None) -> bool:
        """Wait for prices to be updated by the shared background updater.

        Raises the stored exception if the update attempt failed. Returns False if this instance is
        not currently started.

        Args:
            timeout: The maximum time to wait for the prices to be updated in seconds.
        """
        updater = self._updater
        if updater is None:
            return False
        return updater._wait_raising(timeout)  # pyright: ignore[reportPrivateUsage]

    def fetch(self) -> data_snapshot.DataSnapshot | None:
        """Fetch the latest provider data from the configured URL (does not start a background task)."""
        return _BackgroundUpdater(
            url=self.url, update_interval=self.update_interval, request_timeout=self.request_timeout
        ).fetch()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_args: object):
        self.stop()


@dataclass
class _BackgroundUpdater:
    """The single process-wide updater. Internal: consumers interact via `UpdatePrices`."""

    url: str
    update_interval: float
    request_timeout: httpx2.Timeout
    _stop_event: threading.Event = field(default_factory=threading.Event)
    _prices_updated: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = field(default=None)
    _background_exc: Exception | None = field(default=None)
    _update_succeeded: bool = field(default=False)

    def _start_thread(self) -> None:
        if self._thread is not None:
            raise RuntimeError('genai-prices background task already started')

        _register_fork_hooks()
        self._prices_updated.clear()
        self._stop_event.clear()
        self._background_exc = None
        self._update_succeeded = False
        self._thread = threading.Thread(target=self._background_task, daemon=True, name='genai_prices:update')
        self._thread.start()

    def _wait_updated(self, timeout: float | None) -> bool:
        # Never raises and does not consume the stored background exception: failures are already
        # logged by the background task, and the exception stays stored for stop() to surface.
        return self._prices_updated.wait(timeout=timeout) and self._update_succeeded

    def _wait_raising(self, timeout: float | None) -> bool:
        # Like _wait_updated, but raises (and consumes) the stored background exception - the
        # behaviour of UpdatePrices.wait().
        prices_updated = self._prices_updated.wait(timeout=timeout)
        exc = self._background_exc
        if exc:
            self._background_exc = None
            raise exc
        return prices_updated and self._update_succeeded

    def _revive_after_fork(self) -> None:
        # Threads do not survive fork, and the inherited events may have been captured in an
        # arbitrary state (e.g. mid-install); recreate them and restart the background thread on
        # this same instance. The snapshot is fenced by the module `_lock`, which is itself
        # replaced with a fresh one in `_fork_after_in_child`.
        self._thread = None
        self._stop_event = threading.Event()
        self._prices_updated = threading.Event()
        self._start_thread()

    def _stop_and_detach(self) -> threading.Thread | None:
        """Signal the background thread to stop and revert prices to the bundled data.

        Called with the module `_lock` held. Does not join; returns the (possibly still draining)
        thread so the caller can wait on it after releasing `_lock`. Setting the stop event before
        clearing the snapshot, both ordered against `_install_snapshot` via `_lock`, guarantees an
        in-flight fetch can finish but can never install its result afterwards.
        """
        thread = self._thread
        self._thread = None
        self._stop_event.set()
        data_snapshot.set_custom_snapshot(None)
        return thread

    def _background_task(self) -> None:
        logger.info('Starting genai-prices background task')
        try:
            while True:
                try:
                    installed = self._update_prices()
                    self._background_exc = None
                    # Reflect whether the snapshot was actually installed: a fetch discarded by the
                    # stop fence (see _install_snapshot) must not report success to waiters. Set
                    # before signaling the event so waiters observing the event see the flag.
                    self._update_succeeded = installed
                    self._prices_updated.set()
                except Exception as e:
                    self._background_exc = e
                    self._prices_updated.set()
                    logger.exception('Error updating genai-prices in the background')
                if self._stop_event.wait(self.update_interval):
                    break

        finally:
            logger.info('genai-prices background task stopped')

    def _update_prices(self) -> bool:
        start = time()
        snapshot = self.fetch()
        interval = time() - start
        if snapshot:
            logger.info('Successfully fetched %d providers in %.2f seconds', len(snapshot.providers), interval)
        else:
            logger.info('Successfully fetched null snapshot in %.2f seconds', interval)

        return self._install_snapshot(snapshot)

    def _install_snapshot(self, snapshot: data_snapshot.DataSnapshot | None) -> bool:
        # Fencing check: never publish after stop. The stop path sets _stop_event and then clears
        # the snapshot under `_lock` (see _stop_and_detach), so taking the same lock here and
        # re-checking the event makes publish-after-stop impossible rather than merely unlikely.
        # Returns whether the snapshot was installed, so a discarded fetch is not reported as a
        # successful update to waiters.
        with _lock:
            if self._stop_event.is_set():
                logger.info('genai-prices updater was stopped during the fetch; discarding the fetched snapshot')
                return False
            data_snapshot.set_custom_snapshot(snapshot)
            return True

    def fetch(self) -> data_snapshot.DataSnapshot | None:
        """Fetches the latest provider data from the configured URL."""
        from . import data

        r = httpx2.get(self.url, timeout=self.request_timeout)
        r.raise_for_status()
        return data_snapshot.DataSnapshot(data.providers_schema.validate_json(r.content), from_auto_update=True)
