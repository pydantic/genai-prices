from __future__ import annotations as _annotations

import asyncio
import json
import logging
import os
import threading
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
# `_lock` guards `_worker` and is held for all of start()/stop(), including the final join, so
# lifecycle transitions never overlap.
_lock = threading.Lock()
_worker: _Worker | None = None
_fork_hooks_registered = False
_fork_state = threading.local()


def _register_fork_hooks() -> None:
    """Restart an active inherited worker after ``os.fork()``."""
    global _fork_hooks_registered

    if _fork_hooks_registered or not hasattr(os, 'register_at_fork'):
        return
    os.register_at_fork(
        before=_fork_before,
        after_in_parent=_fork_after_in_parent,
        after_in_child=_fork_after_in_child,
    )
    _fork_hooks_registered = True


def _fork_before() -> None:
    worker = _worker
    from_worker = worker is not None and threading.current_thread() is worker.thread
    _fork_state.from_worker = from_worker
    if not from_worker:
        # Serialize ordinary forks with start()/stop(), so the child inherits complete ownership.
        _lock.acquire()


def _fork_after_in_parent() -> None:
    if not getattr(_fork_state, 'from_worker', False):
        _lock.release()
    _fork_state.from_worker = False


def _invalidate_inherited_worker(worker: _Worker) -> None:
    global _worker

    def cleanup() -> None:
        global _worker

        worker.invalidate_after_fork()
        data_snapshot.set_custom_snapshot(None)
        _worker = None

    _finish_despite_interruption(cleanup)


def _fork_after_in_child() -> None:
    global _lock, _worker

    from_worker = getattr(_fork_state, 'from_worker', False)
    _fork_state.from_worker = False
    # The inherited lock is held by the pre-fork callback and cannot safely be reused.
    _lock = threading.Lock()
    worker = _worker
    if worker is None:
        return

    if from_worker:
        # The current _run() survives a worker-origin fork. Stop it instead of starting a second
        # loop, and never acquire a lock that a vanished stop() thread may have owned.
        _invalidate_inherited_worker(worker)
        _log(logger.warning, 'Disabled the genai-prices background updater after it forked from its worker')
        return

    if not worker.restart_after_fork:
        # An overridden fetch may close over application locks held by vanished threads. Only the
        # built-in fetch has lifecycle state we can replace completely and safely.
        _invalidate_inherited_worker(worker)
        _log(logger.warning, 'Custom genai-prices updater fetch must be restarted explicitly after fork')
        return

    try:
        worker.revive_after_fork()
    except BaseException:
        # A public instance may still point at this worker. Make that claim inert; start(),
        # stop(), and wait() compare it with the process-global worker before using it.
        _invalidate_inherited_worker(worker)
        _log(logger.exception, 'Failed to restart the genai-prices background updater after fork')


def wait_prices_updated_sync(timeout: float | None = None) -> bool:
    """Synchronously wait for prices to be updated by the shared background updater.

    A fetch failure is raised to every waiter until a later fetch succeeds.

    Args:
        timeout: The maximum time to wait for prices to be updated. Defaults to None which waits indefinitely.

    Returns:
        True if prices were updated, False if no updater is active or the timeout elapses.
    """
    # Not under `_lock`: the last stop() holds it while joining, so a `fetch()` override calling
    # this would deadlock. Safe because every published worker sets `ready` on every exit path.
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
    Starting with different configuration than the running worker raises `RuntimeError`. The worker
    captures `url` and `request_timeout` at `start()`; changing them afterwards has no effect on it.

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
                if self._worker is _worker:
                    raise RuntimeError('UpdatePrices background task already started')
                # Failed fork revival leaves inherited instance claims inert in the child.
                self._worker = None

            # Copy the mutable Timeout so the worker's configuration is frozen at launch.
            config = _Config(self.url, self.update_interval, httpx2.Timeout(self.request_timeout))
            worker = _worker
            if worker is None:
                _register_fork_hooks()
                worker = _Worker(config, self.fetch)
                worker.claims = 1
                try:
                    # Publish before starting so the worker-thread guards see it from the first
                    # fetch; inside the try so an interrupt can't leave a published worker that never runs.
                    _worker = worker
                    self._worker = worker
                    worker.thread.start()
                except BaseException:
                    # Thread.start() can fail after the OS thread launched; drain it so no orphan keeps fetching.
                    try:
                        worker.shutdown()
                    finally:
                        _worker = None
                        self._worker = None
                    raise
            else:
                if worker.dead:
                    raise RuntimeError('UpdatePrices background task terminated unexpectedly')
                if worker.config != config:
                    raise RuntimeError(
                        'UpdatePrices background task already started with different configuration: '
                        f'url={worker.config.url!r}, update_interval={worker.config.update_interval!r}, '
                        f'request_timeout={worker.config.request_timeout!r}'
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
        if worker is None or worker is not _worker:
            return False
        return worker.wait(timeout)

    def stop(self):
        """Stop the background task, or release this instance's claim on it.

        The last `stop()` waits for any in-flight fetch, stops the worker and restores the bundled
        prices. Fetch failures never make `stop()` raise; they are reported by `wait()`. A Ctrl-C
        while waiting is re-raised once shutdown finishes; a second one stops the waiting early.
        """
        global _worker

        _check_not_worker_thread('stop')
        with _lock:
            worker = self._worker
            if worker is None:
                return
            if worker is not _worker:
                self._worker = None
                return
            remaining_claims = worker.claims - 1
            shutdown_finished = remaining_claims != 0

            def cleanup() -> None:
                global _worker
                nonlocal shutdown_finished

                # Idempotent assignments: a Ctrl-C retry can resume anywhere without double-releasing the claim.
                worker.claims = remaining_claims
                self._worker = None
                if not shutdown_finished:
                    try:
                        worker.shutdown()
                    finally:
                        # shutdown() finishes its cleanup even when interrupted; never repeat an abandoned join.
                        shutdown_finished = True
                if remaining_claims == 0:
                    # Clear only after shutdown so a reentrant worker-thread guard never reads None mid-join.
                    _worker = None

            interrupted = _finish_despite_interruption(cleanup)
            if interrupted is not None:
                raise interrupted

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


def _check_not_worker_thread(action: str) -> None:
    # start() and stop() block on `_lock`, which the last stop() holds while joining the worker,
    # so calling them from a `fetch()` override would deadlock.
    worker = _worker
    if worker is not None and threading.current_thread() is worker.thread:
        raise RuntimeError(f'UpdatePrices background task cannot call {action} from its worker')


def _finish_despite_interruption(action: Callable[[], None]) -> BaseException | None:
    """Finish idempotent lifecycle bookkeeping before propagating an interruption."""
    interrupted: BaseException | None = None
    while True:
        try:
            action()
        except (KeyboardInterrupt, SystemExit) as e:
            interrupted = e
        else:
            return interrupted


class _Worker:
    """The process-wide background thread shared by all started `UpdatePrices` instances."""

    def __init__(self, config: _Config, fetch: Callable[[], data_snapshot.DataSnapshot | None]) -> None:
        self.config = config
        if getattr(fetch, '__func__', None) is UpdatePrices.fetch:
            self.restart_after_fork = True
            # The default fetch uses the frozen launch config; an overridden fetch controls what it reads.
            self.fetch: Callable[[], data_snapshot.DataSnapshot | None] = lambda: _fetch_prices(
                config.url, config.request_timeout
            )
        else:
            self.restart_after_fork = False
            self.fetch = fetch
        self.claims = 0
        self.dead = False
        self.stop_event = threading.Event()
        # Makes check-stop-then-install atomic with shutdown's restore, so a late fetch can never
        # reinstall data after stop() cleaned up.
        self._install_lock = threading.Lock()
        self.thread = threading.Thread(target=self._run, daemon=True, name='genai_prices:update')
        # The latest fetch outcome, reported to every waiter.
        self.ready = threading.Event()
        self._outcome_lock = threading.Lock()
        self._error: Exception | None = None
        self._error_traceback: TracebackType | None = None
        self._succeeded = False

    def revive_after_fork(self) -> None:
        """Replace inherited synchronization state and restart this worker in the child."""
        stop_event = threading.Event()
        install_lock = threading.Lock()
        thread = threading.Thread(target=self._run, daemon=True, name='genai_prices:update')
        ready = threading.Event()
        outcome_lock = threading.Lock()

        self.dead = False
        self.stop_event = stop_event
        self._install_lock = install_lock
        self.thread = thread
        self.ready = ready
        self._outcome_lock = outcome_lock
        self._error = None
        self._error_traceback = None
        self._succeeded = False
        try:
            thread.start()
        except BaseException:
            # Thread.start() can fail after launching; drain it using only child-local primitives.
            self.shutdown()
            raise

    def invalidate_after_fork(self) -> None:
        """Make inherited claims inert after child revival fails."""
        self.claims = 0
        self.dead = True
        self.stop_event = threading.Event()
        self.stop_event.set()
        self._install_lock = threading.Lock()
        self.ready = threading.Event()
        self.ready.set()
        self._outcome_lock = threading.Lock()
        self._error = None
        self._error_traceback = None
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
        """Stop the thread and restore the bundled prices, staying responsive to Ctrl-C.

        A first Ctrl-C during the join finishes the shutdown before being re-raised; a second stops
        waiting — the daemon thread discards its result and exits on its own.
        """
        interrupted: BaseException | None = None
        for _ in range(2):
            try:
                self.stop_event.set()
                # There is nothing to join when Thread.start() failed before the thread ran.
                if self.thread.is_alive():
                    self.thread.join()
                break
            except (KeyboardInterrupt, SystemExit) as e:
                interrupted = e

        def cleanup() -> None:
            # Safe even if the join was abandoned: with stop_event set, the install lock keeps a
            # still-running fetch from reinstalling data after this restore.
            with self._install_lock:
                data_snapshot.set_custom_snapshot(None)
            # Wake any waiter still blocked before the first fetch; with no outcome, wait() returns False.
            self.ready.set()

        cleanup_interruption = _finish_despite_interruption(cleanup)
        if cleanup_interruption is not None:
            interrupted = cleanup_interruption
        if interrupted is not None:
            raise interrupted

    def _publish(self, error: Exception | None) -> None:
        with self._outcome_lock:
            self._error = error
            self._error_traceback = error.__traceback__ if error is not None else None
            self._succeeded = error is None
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
            # Nothing above should raise this; if it does, fail waiters and joiners instead of hanging them.
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

        with self._install_lock:
            if self.stop_event.is_set():
                # A concurrent stop() wins: its discarded fetch is not an update, so install and publish nothing.
                return
            data_snapshot.set_custom_snapshot(snapshot)
        self._publish(None)


def _log(log: Callable[..., None], message: str, *args: object) -> None:
    try:
        log(message, *args)
    except Exception:
        # A broken logging handler must not kill background updates or dump thread tracebacks.
        pass
