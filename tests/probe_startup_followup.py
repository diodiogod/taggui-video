"""Opt-in fresh-process startup profile, through tests/run_isolated.py only."""
import cProfile
import json
import pstats
import sys
import time

from PySide6.QtCore import QTimer

from qt_test_helpers import APP, dispose_widget, pump
from utils.latest_task import LatestTask


def test_fresh_main_window_profile(monkeypatch):
    # Disable the application's deliberate process-exit failsafe in this
    # isolated fixture so pytest can finish and verify explicit native teardown.
    monkeypatch.setenv('TAGGUI_FORCE_CLEAN_EXIT_ON_CLOSE', '0')
    APP.setStyle('Fusion')
    profile = cProfile.Profile()
    start = time.perf_counter()
    profile.enable()
    from widgets.main_window import MainWindow
    imported = time.perf_counter()
    window = MainWindow(APP)
    tasks = window.findChildren(LatestTask)
    executor = window.image_list.list_view._masonry_executor
    built = time.perf_counter()
    profile.disable()
    ticks = []
    timer = QTimer()
    timer.setInterval(2)
    timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
    try:
        timer.start()
        window.show()
        pump(lambda: len(ticks) >= 3, seconds=15)
        stats = pstats.Stats(profile)
        rows = [{'file': key[0].rsplit('\\', 1)[-1], 'function': key[2],
                 'calls': data[1], 'self_ms': round(data[2]*1000, 3),
                 'cumulative_ms': round(data[3]*1000, 3)}
                for key, data in sorted(stats.stats.items(), key=lambda item: item[1][2], reverse=True)[:22]]
        style_callers = []
        for key, data in stats.stats.items():
            if 'setStyleSheet' not in key[2]:
                continue
            for caller, cost in data[4].items():
                style_callers.append({'file': caller[0].rsplit('\\', 1)[-1],
                    'line': caller[1], 'function': caller[2], 'cost': cost})
        print('STARTUP_PROFILE', json.dumps({'import_ms': (imported-start)*1000,
            'construction_ms': (built-imported)*1000, 'first_tick_after_build_ms': (ticks[0]-built)*1000,
            'top_self_costs': rows, 'style_callers': style_callers}), file=sys.__stdout__, flush=True)
    finally:
        timer.stop()
        # Closing stops UI timers before worker drainage/native deletion.
        window.close()
        for task in tasks:
            task.drain()
        executor.shutdown(wait=True, cancel_futures=True)
        window.image_list_model.shutdown_background_workers()
        dispose_widget(window)
        APP.processEvents()
