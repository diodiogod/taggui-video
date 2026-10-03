"""Separate bounded caches for TagGUI metadata and foreign sidecar identities.

The owning model supplies synchronization. Foreign entries retain only file
signatures, so page churn can reuse classifications without retaining workflows.
"""
from collections import OrderedDict
from collections.abc import MutableMapping
import sys


MetadataEntry = tuple[float, int, dict | None]


class SidecarMetadataCache(MutableMapping[str, MetadataEntry]):
    def __init__(self, positive_limit=2048, negative_limit=32768,
                 negative_byte_limit=16 * 1024 * 1024):
        self._positive: OrderedDict[str, MetadataEntry] = OrderedDict()
        self._negative: OrderedDict[str, MetadataEntry] = OrderedDict()
        self._positive_limit = max(0, int(positive_limit))
        self._negative_limit = max(0, int(negative_limit))
        self._negative_byte_limit = max(0, int(negative_byte_limit))
        self.estimated_negative_bytes = 0

    @staticmethod
    def _entry_bytes(key, value):
        # Include key/signature objects and a conservative per-entry allowance
        # for the mapping node. This is an estimate, not process memory usage.
        return (sys.getsizeof(key) + sys.getsizeof(value)
                + sys.getsizeof(value[0]) + sys.getsizeof(value[1]) + 128)

    def __getitem__(self, key):
        cache = self._positive if key in self._positive else self._negative
        value = cache[key]
        cache.move_to_end(key)
        return value

    def __setitem__(self, key, value):
        self.pop(key, None)
        if value[2] is not None:
            self._positive[key] = value
            while len(self._positive) > self._positive_limit:
                self._positive.popitem(last=False)
            return
        self._negative[key] = value
        self.estimated_negative_bytes += self._entry_bytes(key, value)
        while (len(self._negative) > self._negative_limit
               or self.estimated_negative_bytes > self._negative_byte_limit):
            old_key, old_value = self._negative.popitem(last=False)
            self.estimated_negative_bytes -= self._entry_bytes(old_key, old_value)

    def __delitem__(self, key):
        if key in self._positive:
            del self._positive[key]
        else:
            value = self._negative.pop(key)
            self.estimated_negative_bytes -= self._entry_bytes(key, value)

    def __iter__(self):
        yield from self._positive
        yield from self._negative

    def __len__(self):
        return len(self._positive) + len(self._negative)

    def clear(self):
        self._positive.clear()
        self._negative.clear()
        self.estimated_negative_bytes = 0
