"""Per-file locks for operations that read or replace media in place."""

from __future__ import annotations

from functools import wraps
from pathlib import Path
import threading
from weakref import WeakValueDictionary


_registry_lock = threading.Lock()
_file_locks = WeakValueDictionary()


def get_media_file_lock(file_path: Path | str) -> threading.RLock:
    """Return the shared lock for one normalized media path."""
    try:
        key = str(Path(file_path).resolve()).casefold()
    except (OSError, RuntimeError):
        key = str(file_path).casefold()
    with _registry_lock:
        lock = _file_locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _file_locks[key] = lock
        # Every active holder/waiter owns a strong reference. An idle lock can
        # disappear without allowing two active operations to use different locks.
        return lock


def synchronized_media_file(function):
    """Serialize calls that read or replace the same media file."""
    @wraps(function)
    def wrapper(file_path, *args, **kwargs):
        with get_media_file_lock(file_path):
            return function(file_path, *args, **kwargs)

    return wrapper
