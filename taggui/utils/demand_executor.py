"""Prioritized thumbnail demand without an unbounded executor work queue."""
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
import threading


class DemandExecutor:
    """Keep only active jobs in the pool and removable arguments in pending demand.

    Ordinary submit calls are never discarded under pressure. Thumbnail callers
    explicitly use submit_priority: obsolete cache/preload hints may be dropped
    and requested again. Running native work is never forcibly interrupted.
    """
    def __init__(self, max_workers=6, max_pending=256, thread_name_prefix='thumb_load'):
        self._pool = ThreadPoolExecutor(max_workers=max_workers,
                                        thread_name_prefix=thread_name_prefix)
        self._workers = max_workers
        self._limit = max_pending
        self._pending = OrderedDict()
        self._lock = threading.RLock()
        self._active = 0
        self._closed = False
        self._idle = threading.Event()
        self._idle.set()

    def submit(self, function, /, *args, **kwargs):
        return self._submit(20, False, function, args, kwargs)

    def submit_priority(self, priority, function, /, *args, **kwargs):
        return self._submit(priority, True, function, args, kwargs)

    def _submit(self, priority, disposable, function, args, kwargs):
        future = Future()
        future.add_done_callback(self._forget_cancelled)
        discarded = []
        with self._lock:
            if self._closed:
                raise RuntimeError('Executor is shut down')
            self._idle.clear()
            self._pending[future] = (priority, disposable, function, args, kwargs)
            while sum(job[1] for job in self._pending.values()) > self._limit:
                candidates = [(key, job) for key, job in self._pending.items() if job[1]]
                victim, _ = max(candidates, key=lambda item: item[1][0])
                del self._pending[victim]
                discarded.append(victim)
            self._pump_locked()
        # Future callbacks may acquire model locks. Never call them under ours.
        for victim in discarded:
            victim.cancel()
        return future

    def promote(self, future, priority=0):
        with self._lock:
            job = self._pending.get(future)
            if job is not None and priority < job[0]:
                self._pending[future] = (priority, *job[1:])

    def _forget_cancelled(self, future):
        if future.cancelled():
            with self._lock:
                self._pending.pop(future, None)

    def _pump_locked(self):
        while self._active < self._workers and self._pending:
            future = min(self._pending, key=lambda key: self._pending[key][0])
            _, _, function, args, kwargs = self._pending.pop(future)
            if not future.set_running_or_notify_cancel():
                continue
            self._active += 1
            self._pool.submit(self._run, future, function, args, kwargs)
        if not self._active and not self._pending:
            self._idle.set()

    def _run(self, future, function, args, kwargs):
        try:
            try:
                result = function(*args, **kwargs)
            except BaseException as exception:
                future.set_exception(exception)
            else:
                future.set_result(result)
        finally:
            with self._lock:
                self._active -= 1
                self._pump_locked()
                finished = self._closed and self._idle.is_set()
            if finished:
                self._pool.shutdown(wait=False)

    @property
    def pending_count(self):
        with self._lock:
            return len(self._pending)

    def shutdown(self, wait=True, *, cancel_futures=False):
        with self._lock:
            self._closed = True
            pending = list(self._pending) if cancel_futures else []
            if cancel_futures:
                self._pending.clear()
            self._pump_locked()
        for future in pending:
            future.cancel()
        if wait:
            self._idle.wait()
            self._pool.shutdown(wait=True)
        elif self._idle.is_set():
            self._pool.shutdown(wait=False)

