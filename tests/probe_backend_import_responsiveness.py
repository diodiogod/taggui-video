"""Opt-in, fresh-process runtime-import responsiveness probe; use run_isolated.py."""
import json
import threading
import time

from PySide6.QtCore import QTimer
from qt_test_helpers import APP


def test_background_mpv_import_timer_delivery():
    # Exercise the shared loader without creating Qt playback objects.
    from utils.video.mpv_runtime import bootstrap_mpv_runtime_search_paths
    from utils.video.runtime_loader import RuntimeLoader
    bootstrap_mpv_runtime_search_paths()
    ticks = []
    result = {}
    loader = RuntimeLoader()
    done = threading.Event()
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: ticks.append(time.perf_counter()))

    def load():
        begin = time.perf_counter()
        try:
            state = loader.load('mpv')
            result['available'] = state.status == 'ready'
            result['error'] = state.error
        except Exception as error:
            result['error'] = repr(error)
        finally:
            result['import_ms'] = (time.perf_counter() - begin) * 1000
            done.set()

    worker = threading.Thread(target=load, name='runtime-import-probe')
    begin = time.perf_counter()
    timer.start()
    worker.start()
    try:
        while not done.is_set() and time.perf_counter() - begin < 30:
            APP.processEvents()
            time.sleep(.001)
    finally:
        timer.stop()
        worker.join()
    end = time.perf_counter()
    boundaries = [begin, *ticks, end]
    result['timer_ticks'] = len(ticks)
    result['max_delivery_gap_ms'] = max(b-a for a, b in zip(boundaries, boundaries[1:])) * 1000
    result['first_delivery_ms'] = (ticks[0]-begin)*1000 if ticks else None
    print('BACKGROUND_RUNTIME_IMPORT', json.dumps(result))
    assert result.get('available'), result
