"""One running operation and one replaceable request, with GUI-owned delivery."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import threading
import weakref

from PySide6.QtCore import QObject, Signal, Slot


@dataclass(frozen=True)
class _Request:
    token: int
    function: object
    payload: object
    cancelled: threading.Event


class LatestTask(QObject):
    """Worker functions receive only a payload and cooperative cancellation event.

    Submission, cancellation and accepted-result installation belong to the
    object's Qt thread. Replacing pending work releases its arguments promptly;
    cancellation does not promise to interrupt an already-running decoder.
    """
    completed = Signal(int, object, object)
    _finished = Signal(object)

    def __init__(self, parent=None, *, name='taggui-worker'):
        super().__init__(parent)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=name)
        self._token = 0
        self._active = None
        self._pending = None
        self._closed = False
        self._future = None
        self._finished.connect(self._receive)
        self.destroyed.connect(lambda: self.close())

    @property
    def token(self):
        return self._token

    def submit(self, function, payload):
        if self._closed:
            raise RuntimeError('Worker is closed')
        self.cancel()
        request = _Request(self._token, function, payload, threading.Event())
        if self._active is None:
            self._start(request)
        else:
            self._pending = request
        return request.token

    def cancel(self):
        self._token += 1
        self._pending = None
        if self._active is not None:
            self._active.cancelled.set()

    def _start(self, request):
        self._active = request
        owner = weakref.ref(self)

        def run():
            try:
                value, error = request.function(request.payload, request.cancelled), None
            except Exception as exception:
                value, error = None, exception
            receiver = owner()
            if receiver is not None and not receiver._closed:
                try:
                    receiver._finished.emit((request.token, value, error))
                except RuntimeError:
                    pass  # The Qt owner was destroyed during native work.

        self._future = self._executor.submit(run)

    def drain(self):
        """Release native/file handles for a controlled relocation boundary."""
        self.cancel()
        if self._future is not None:
            self._future.result()

    @Slot(object)
    def _receive(self, result):
        if self._closed:
            return
        self._active = None
        token, value, error = result
        if token == self._token:
            self.completed.emit(token, value, error)
        # completed slots may themselves replace or start work.
        if self._active is None and self._pending is not None:
            request, self._pending = self._pending, None
            self._start(request)

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.cancel()
        # The running closure keeps its payload until native work finishes.
        # Closed QObjects receive no completion, so don't retain a second copy
        # indefinitely (comparison payloads can contain cached pixel buffers).
        self._active = None
        self._executor.shutdown(wait=False, cancel_futures=True)
