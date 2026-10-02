import gc
from pathlib import Path
import sys
import threading
import time
import weakref

from PySide6.QtWidgets import QApplication
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'taggui'))
from utils.latest_task import LatestTask
from utils.image_decode import decode_image

APP = QApplication.instance() or QApplication([])


def pump_until(predicate):
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        APP.processEvents()
        time.sleep(.002)
    assert predicate()


def test_latest_pending_only_runs_and_is_delivered_on_gui_thread():
    started, release = threading.Event(), threading.Event()
    calls, results, owners = [], [], []
    task = LatestTask()
    def work(payload, cancelled):
        calls.append(payload)
        if payload == 'first':
            started.set()
            assert release.wait(2)
        return payload
    task.completed.connect(lambda token, result, error: (
        results.append(result), owners.append(threading.get_ident())))
    try:
        task.submit(work, 'first')
        assert started.wait(1)
        for i in range(100):
            task.submit(work, i)
        release.set()
        pump_until(lambda: results == [99])
        assert calls == ['first',99]
        assert owners == [threading.get_ident()]
    finally:
        release.set()
        task.drain()
        task.close()


def test_replaced_pending_payload_released_without_waiting_for_running_job():
    started, release = threading.Event(), threading.Event()
    class Payload: pass
    task = LatestTask()
    def work(payload, cancelled):
        started.set()
        release.wait(2)
    try:
        task.submit(work, None)
        assert started.wait(1)
        payload = Payload()
        retained = weakref.ref(payload)
        task.submit(work,payload)
        del payload
        assert retained() is not None
        task.cancel()
        gc.collect()
        assert retained() is None
    finally:
        release.set()
        task.drain()
        task.close()
        APP.processEvents()


def test_closed_worker_releases_active_payload_after_native_work_finishes():
    started, release = threading.Event(), threading.Event()
    class Payload:
        pass
    task = LatestTask()
    def work(payload, cancelled):
        started.set()
        assert release.wait(2)
    payload = Payload()
    retained = weakref.ref(payload)
    try:
        task.submit(work, payload)
        del payload
        assert started.wait(1)
        task.close()
        assert retained() is not None  # Running native work still owns it.
        release.set()
        task.drain()
        gc.collect()
        assert retained() is None  # No GUI completion required after close.
    finally:
        release.set()
        task.drain()
        task.close()


def test_decode_keeps_full_dimensions_and_corrupt_file_is_an_error(tmp_path, monkeypatch):
    from PySide6.QtGui import QImage, QColor
    from models import image_list_model
    path = tmp_path / 'image.png'
    pixels = QImage(1024,768,QImage.Format_RGB32)
    pixels.fill(QColor('blue'))
    assert pixels.save(str(path))
    result = decode_image(path,threading.Event())
    assert result.image.size().toTuple() == (1024,768)
    assert result.image.pixelColor(100,100) == QColor('blue')
    assert result.requested_path == result.resolved_path == path
    cancelled = threading.Event()
    cancelled.set()
    assert decode_image(path,cancelled) is None
    corrupt = tmp_path / 'bad.png'
    corrupt.write_bytes(b'corrupt')
    monkeypatch.setattr(image_list_model,'fallback_decode_qimage',lambda p:(None,None,p))
    import pytest
    with pytest.raises(OSError):
        decode_image(corrupt,threading.Event())
