"""Bound retained decoded images awaiting optional disk-cache writes."""
from collections import OrderedDict
import threading


class ThumbnailSaveQueue:
    def __init__(self, max_bytes=32 * 1024 * 1024, max_items=128):
        self._items = OrderedDict()
        self._bytes = 0
        self._max_bytes = max_bytes
        self._max_items = max_items
        self._lock = threading.Lock()

    def put(self, key, payload, cost):
        with self._lock:
            old = self._items.pop(key, None)
            if old is not None:
                self._bytes -= old[1]
            if cost > self._max_bytes:
                return  # Disk caching is a hint; keep the displayed thumbnail.
            self._items[key] = (payload, cost)
            self._bytes += cost
            while self._bytes > self._max_bytes or len(self._items) > self._max_items:
                _, (_, size) = self._items.popitem(last=False)
                self._bytes -= size

    def pop(self):
        with self._lock:
            if not self._items:
                return None
            _, (payload, size) = self._items.popitem(last=False)
            self._bytes -= size
            return payload

    def clear(self):
        with self._lock:
            self._items.clear()
            self._bytes = 0

    @property
    def retained_bytes(self):
        with self._lock:
            return self._bytes

    def __len__(self):
        with self._lock:
            return len(self._items)
