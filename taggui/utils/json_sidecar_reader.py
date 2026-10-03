"""Classify ambiguous JSON siblings without retaining foreign object graphs."""

from collections import OrderedDict
import json
from pathlib import Path
from threading import Lock


JSON_OBJECT = object()
_NEGATIVE_LIMIT = 256
_negative = OrderedDict()
_lock = Lock()


def _signature(path):
    stat = path.stat()
    return (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size,
            stat.st_dev, stat.st_ino)


def read_matching_json_object(path: Path, accepts_reduced_root):
    """Fully decode only roots accepted by a conservative schema prefilter.

    Nested objects become JSON_OBJECT; arrays and scalars keep their JSON
    types. The predicate must accept every valid document of its schema.
    Callers still validate the full result. Only negative file signatures are
    cached, never text or mutable metadata. IO/parse failures are not cached.
    """
    path = Path(path).absolute()
    signature = _signature(path)
    key = (path, accepts_reduced_root)
    with _lock:
        if _negative.get(key) == signature:
            _negative.move_to_end(key)
            return None
        _negative.pop(key, None)

    text = path.read_text(encoding='utf-8')
    last_object = None

    def reduce_object(obj):
        nonlocal last_object
        last_object = obj
        return JSON_OBJECT

    root = json.loads(text, object_hook=reduce_object)
    if root is not JSON_OBJECT or not accepts_reduced_root(last_object):
        # A concurrent edit must not publish a rejection for the new file.
        if _signature(path) == signature:
            with _lock:
                _negative[key] = signature
                _negative.move_to_end(key)
                while len(_negative) > _NEGATIVE_LIMIT:
                    _negative.popitem(last=False)
        return None
    return json.loads(text)
