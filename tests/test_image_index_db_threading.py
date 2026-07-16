import sys
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "taggui"))

from taggui.utils.image_index_db import ImageIndexDB


class _BlockingCursor:
    def __init__(self, execute_started: threading.Event, release_execute: threading.Event):
        self._execute_started = execute_started
        self._release_execute = release_execute

    def execute(self, _sql, _bindings):
        self._execute_started.set()
        if not self._release_execute.wait(timeout=2.0):
            raise TimeoutError("test did not release the blocked database write")


class _BlockingConnection:
    def __init__(self, execute_started: threading.Event, release_execute: threading.Event):
        self._execute_started = execute_started
        self._release_execute = release_execute
        self.closed = False

    def cursor(self):
        return _BlockingCursor(self._execute_started, self._release_execute)

    def commit(self):
        return None

    def close(self):
        self.closed = True


def test_close_waits_for_in_flight_dimension_write(tmp_path):
    execute_started = threading.Event()
    release_execute = threading.Event()
    close_started = threading.Event()
    close_finished = threading.Event()
    connection = _BlockingConnection(execute_started, release_execute)

    db = object.__new__(ImageIndexDB)
    db.enabled = True
    db._directory_path = tmp_path
    db._db_lock = threading.RLock()
    db.conn = connection

    writer = threading.Thread(
        target=db.update_image_dimensions,
        args=("image.png", 640, 480),
    )

    def close_database():
        close_started.set()
        db.close()
        close_finished.set()

    closer = threading.Thread(target=close_database)
    writer.start()
    assert execute_started.wait(timeout=1.0)

    closer.start()
    assert close_started.wait(timeout=1.0)
    assert not close_finished.wait(timeout=0.05)

    release_execute.set()
    writer.join(timeout=1.0)
    closer.join(timeout=1.0)

    assert not writer.is_alive()
    assert not closer.is_alive()
    assert close_finished.is_set()
    assert connection.closed is True
    assert db.conn is None
