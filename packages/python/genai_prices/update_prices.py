from __future__ import annotations as _annotations

import asyncio
import json
import logging
import os
import threading
import warnings
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

# All instances share one worker so libraries can opt in independently without duplicate threads.
# The one lock guards the worker reference, its reference count, and snapshot install/restore, and is
# never held across anything that blocks — stop() signals the worker instead of joining it — so
# lifecycle calls never wait for the worker.
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
    # stop() never blocks under this lock, so every fork origin can inherit complete ownership.
    _lock.acquire()


def _fork_after_in_parent() -> None:
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

    # Do not log from this callback; handler locks may have been held by threads that vanished at fork.
    from_worker = getattr(_fork_state, 'from_worker', False)
    _fork_state.from_worker = False
    # The inherited lock is held by the pre-fork callback and cannot safely be reused.
    _lock = threading.Lock()
    worker = _worker
    if worker is None:
        return

    if from_worker:
        # The current _run() survives a worker-origin fork. Stop it instead of starting a second
        # loop; the before hook already serialized its inherited ownership state.
        _invalidate_inherited_worker(worker)
        return

    if not worker.restart_after_fork:
        # An overridden fetch may close over application locks held by vanished threads. Only the
        # built-in fetch has lifecycle state we can replace completely and safely.
        _invalidate_inherited_worker(worker)
        return

    try:
        worker.revive_after_fork()
    except BaseException:
        # A public instance may still point at this worker. Make that reference inert; start(),
        # stop(), and wait() compare it with the process-global worker before using it.
        _invalidate_inherited_worker(worker)


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
    calls join it, and the last `stop()` shuts it down and restores the bundled prices. The worker
    fetches through the instance that started it — using its settings and `fetch()` exactly as if
    it were the only instance — so joining with different settings warns and keeps the first
    instance's.

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
        dead_worker_warning = False
        config_warning: str | None = None
        with _lock:
            if self._worker is not None:
                if self._worker is _worker:
                    raise RuntimeError('UpdatePrices background task already started')
                # Failed fork revival leaves inherited instance references inert in the child.
                self._worker = None

            worker = _worker
            if worker is not None and worker.dead:
                # Don't join a worker that died unexpectedly; start a replacement.
                dead_worker_warning = True
                worker = None
            if worker is None:
                _register_fork_hooks()
                worker = _Worker(self)
                worker.ref_count = 1
                try:
                    _worker = worker
                    self._worker = worker
                    worker.thread.start()
                except BaseException as e:
                    # Thread.start() can fail after the OS thread launched; a shut-down worker
                    # exits on its own once ownership rollback completes.
                    def rollback() -> None:
                        global _worker

                        worker.shutdown()
                        _worker = None
                        self._worker = None

                    interrupted = _finish_despite_interruption(rollback)
                    raise interrupted or e
            else:
                owner = worker.owner
                if (self.url, self.update_interval, self.request_timeout) != (
                    owner.url,
                    owner.update_interval,
                    owner.request_timeout,
                ):
                    config_warning = (
                        'UpdatePrices background task is already running with different configuration; keeping '
                        f'url={owner.url!r}, update_interval={owner.update_interval!r}, '
                        f'request_timeout={owner.request_timeout!r}'
                    )
                worker.ref_count += 1
                self._worker = worker

        # Logging and warning hooks are arbitrary application code; never call them while holding the lock.
        if dead_worker_warning:
            try:
                logger.warning('UpdatePrices background task terminated unexpectedly; starting a new one')
            except BaseException:
                self.stop()
                raise
        if config_warning is not None:
            try:
                warnings.warn(config_warning, stacklevel=2)
            except BaseException:
                # A warning promoted to an exception means start() failed; release the reference it just took.
                self.stop()
                raise
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
        if worker is None or worker is not _worker:
            return False
        return worker.wait(timeout)

    def stop(self):
        """Stop the background task, or release this instance's reference to it.

        The last `stop()` restores the bundled prices and signals the worker, which discards any
        in-flight fetch and exits on its own; fetch failures never make `stop()` raise.
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
            remaining_references = worker.ref_count - 1

            def cleanup() -> None:
                global _worker

                # Fixed target values make retries idempotent at every interruption point.
                worker.ref_count = remaining_references
                self._worker = None
                if remaining_references == 0:
                    try:
                        worker.shutdown()
                    finally:
                        if _worker is worker:
                            # A dead worker may already have been replaced; only the current worker's
                            # retirement restores the bundled prices.
                            data_snapshot.set_custom_snapshot(None)
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
        from .types import _providers_from_raw  # pyright: ignore[reportPrivateUsage]

        r = httpx2.get(self.url, timeout=self.request_timeout)
        r.raise_for_status()
        raw_payload = json.loads(r.content)
        if not isinstance(raw_payload, list):
            raise ValueError('Expected fetched prices payload to be a provider array')

        providers = _providers_from_raw(raw_payload)
        return data_snapshot.DataSnapshot(providers, from_auto_update=True)


def _check_not_worker_thread(action: str) -> None:
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

    def __init__(self, owner: UpdatePrices) -> None:
        # The worker fetches through the instance that started it; later instances only add references.
        self.owner = owner
        self.ref_count = 0
        self.dead = False
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True, name='genai_prices:update')
        # `ready` is set once there is an outcome to report (or the worker was stopped without
        # one); `_outcome` is a single reference so it can be published and read atomically.
        self.ready = threading.Event()
        self._outcome: tuple[Exception | None, TracebackType | None] | None = None

    @property
    def restart_after_fork(self) -> bool:
        return getattr(self.owner.fetch, '__func__', None) is UpdatePrices.fetch

    def revive_after_fork(self) -> None:
        """Replace inherited synchronization state and restart this worker in the child."""
        stop_event = threading.Event()
        thread = threading.Thread(target=self._run, daemon=True, name='genai_prices:update')
        ready = threading.Event()

        self.dead = False
        self.stop_event = stop_event
        self.thread = thread
        self.ready = ready
        self._outcome = None
        try:
            thread.start()
        except BaseException:
            # Thread.start() can fail after launching; signal it using only child-local primitives.
            self.shutdown()
            raise

    def invalidate_after_fork(self) -> None:
        """Make inherited references inert after child revival fails."""
        self.ref_count = 0
        self.dead = True
        self.stop_event = threading.Event()
        self.stop_event.set()
        self.ready = threading.Event()
        self.ready.set()
        self._outcome = None

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

        def cleanup() -> None:
            self.stop_event.set()
            # Wake waiters blocked before the first fetch; with no outcome, wait() returns False.
            self.ready.set()

        interrupted = _finish_despite_interruption(cleanup)
        if interrupted is not None:
            raise interrupted

    def _publish(self, error: Exception | None) -> None:
        self._outcome = (error, error.__traceback__ if error is not None else None)
        self.ready.set()

    def _run(self) -> None:
        try:
            logger.info('Starting genai-prices background task')
            while not self.stop_event.is_set():
                try:
                    self._update_prices()
                except Exception as e:
                    with _lock:
                        if self.stop_event.is_set():
                            break
                        self._publish(e)
                    try:
                        logger.error('Error updating genai-prices in the background (%s): %s', type(e).__name__, e)
                    except Exception:
                        # A logging failure must not replace the fetch failure already published to waiters.
                        pass
                if self.stop_event.wait(self.owner.update_interval):
                    break
        except BaseException as e:
            # Serialize terminal publication with new references; a stop that already won suppresses it.
            with _lock:
                if self.stop_event.is_set():
                    return
                self.dead = True
                error = RuntimeError('UpdatePrices background task terminated unexpectedly')
                error.__cause__ = e
                self._publish(error)
        finally:
            logger.info('genai-prices background task stopped')

    def _update_prices(self) -> None:
        start = time()
        snapshot = self.owner.fetch()
        interval = time() - start
        if snapshot:
            logger.info('Successfully fetched %d providers in %.2f seconds', len(snapshot.providers), interval)
        else:
            logger.info('Successfully fetched null snapshot in %.2f seconds', interval)

        with _lock:
            if self.stop_event.is_set():
                # A stop() already won: its discarded fetch is not an update, so install and publish nothing.
                return
            data_snapshot.set_custom_snapshot(snapshot)
            self._publish(None)
