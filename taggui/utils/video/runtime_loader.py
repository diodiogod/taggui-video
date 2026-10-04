"""Single-flight optional imports, with explicit nonblocking readiness snapshots.

This service owns no settings, media paths or Qt objects. GUI callers must poll
request() and continue only after completion; load() is the synchronous API.
"""
from dataclasses import dataclass
from importlib import import_module
from threading import Event, Lock, Thread


@dataclass(frozen=True)
class RuntimeState:
    status: str
    module: object = None
    error: str = ''


class RuntimeLoader:
    def __init__(self, importer=import_module):
        self._importer = importer
        self._lock = Lock()
        self._states = {}
        self._finished = {}

    def _reserve(self, name):
        with self._lock:
            if name in self._states:
                return False, self._finished[name]
            event = Event()
            self._finished[name] = event
            self._states[name] = RuntimeState('pending')
            return True, event

    def _run(self, name, event):
        try:
            result = RuntimeState('ready', self._importer(name))
        except BaseException as error:
            # Always release waiters, including exceptional import termination.
            result = RuntimeState('failed', error=f'{type(error).__name__}: {error}')
        with self._lock:
            self._states[name] = result
            event.set()

    def snapshot(self, name):
        with self._lock:
            return self._states.get(name, RuntimeState('unrequested'))

    def request(self, name):
        """Start at most one import; never wait for its completion."""
        owner, event = self._reserve(name)
        if owner:
            worker = Thread(target=self._run, args=(name, event),
                            name=f'taggui-runtime-{name}', daemon=False)
            try:
                worker.start()
            except Exception as error:
                with self._lock:
                    self._states[name] = RuntimeState('failed', error=f'{type(error).__name__}: {error}')
                    event.set()
        return self.snapshot(name)

    def load(self, name):
        """Compatibility API: concurrent synchronous callers share one result."""
        owner, event = self._reserve(name)
        if owner:
            self._run(name, event)
        else:
            event.wait()
        return self.snapshot(name)
