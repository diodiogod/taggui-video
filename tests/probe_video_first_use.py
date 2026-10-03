"""Opt-in generated-video load profile, through tests/run_isolated.py only.

Measures paused preview construction/loading, not native playback visibility.
"""
import json
import cProfile
import pstats
import time
import sys
import linecache

from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtGui import QImage, QPixmap, QColor
from PySide6.QtWidgets import QGraphicsScene

from qt_test_helpers import APP, dispose_widget, pump
from utils.settings import settings


def test_generated_video_first_use_and_preview_paths(tmp_path):
    import cv2
    import numpy as np
    # Fixture generation warms OpenCV; decoder import latency is not measured.
    path = tmp_path / 'generated-preview.avi'
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), 24, (1920, 1080))
    assert writer.isOpened()
    try:
        for value in range(12):
            writer.write(np.full((1080, 1920, 3), value * 15, np.uint8))
    finally:
        writer.release()
    settings.setValue('video_playback_backend', 'mpv_experimental')
    start = time.perf_counter()
    from widgets.video_player import VideoPlayerWidget
    imported = time.perf_counter()
    construction_profile = cProfile.Profile()
    line_costs = {}
    previous_line = None
    previous_time = None
    def trace_constructor(frame, event, arg):
        nonlocal previous_line, previous_time
        if frame.f_code is not VideoPlayerWidget.__init__.__code__:
            return None
        now = time.perf_counter()
        if previous_line is not None:
            line_costs[previous_line] = line_costs.get(previous_line, 0) + now - previous_time
        previous_line = frame.f_lineno if event == 'line' else None
        previous_time = now
        return trace_constructor
    construction_profile.enable()
    old_trace = sys.gettrace()
    try:
        sys.settrace(trace_constructor)
        player = VideoPlayerWidget()
    finally:
        sys.settrace(old_trace)
    construction_profile.disable()
    constructed = time.perf_counter()
    scene = QGraphicsScene()
    item = scene.addPixmap(QPixmap())
    preview = QImage(512, 288, QImage.Format_RGB32)
    preview.fill(QColor('red'))
    timer = QTimer()
    timer.setInterval(1)
    ticks = []
    timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
    results = {'module_import_ms': (imported-start)*1000,
               'player_construction_ms': (constructed-imported)*1000,
               'fixture': '1920x1080 MJPEG AVI / 12 frames, generated; OpenCV warm',
               'configured_backend': player.configured_playback_backend}
    results['construction_lines'] = [
        {'line': line, 'ms': round(seconds * 1000, 3),
         'code': linecache.getline(VideoPlayerWidget.__init__.__code__.co_filename, line).strip()}
        for line, seconds in sorted(line_costs.items(), key=lambda pair: pair[1], reverse=True)[:8]]
    results['construction_top_self_costs'] = [
        {'file': key[0].rsplit('\\', 1)[-1], 'line': key[1], 'function': key[2],
         'calls': data[1], 'self_ms': round(data[2]*1000, 3)}
        for key, data in sorted(pstats.Stats(construction_profile).stats.items(),
                                key=lambda item: item[1][2], reverse=True)[:5]]
    profile = cProfile.Profile()
    try:
        for label, metadata, pixels in (
            ('metadata_and_preview', {'fps': 24, 'frame_count': 12, 'duration': .5}, preview),
            ('warm_metadata_and_preview', {'fps': 24, 'frame_count': 12, 'duration': .5}, preview),
            ('metadata_without_preview', {'fps': 24, 'frame_count': 12, 'duration': .5}, None),
            ('without_metadata_or_preview', None, None),
        ):
            ticks.clear()
            timer.start()
            begin = time.perf_counter()
            if label == 'metadata_and_preview':
                profile.enable()
            assert player.load_video(path, item, metadata, pixels, (1920, 1080))
            if label == 'metadata_and_preview':
                profile.disable()
            installed = time.perf_counter()
            pump(lambda: bool(ticks), seconds=10)
            timer.stop()
            assert not item.pixmap().isNull()
            assert not player.is_playing
            results[label] = {'handler_ms': (installed-begin)*1000,
                              'first_timer_ms': (ticks[0]-begin)*1000,
                              'capture_opened': player.cap is not None,
                              'runtime_backend': player.runtime_playback_backend}
        results['first_load_top_self_costs'] = [
            {'file': key[0].rsplit('\\', 1)[-1], 'line': key[1], 'function': key[2],
             'calls': data[1], 'self_ms': round(data[2]*1000, 3),
             'cumulative_ms': round(data[3]*1000, 3)}
            for key, data in sorted(pstats.Stats(profile).stats.items(),
                                    key=lambda item: item[1][2], reverse=True)[:10]]
        assert player.audio_output is None, 'External preview should not initialize Qt audio'
        begin = time.perf_counter()
        player._ensure_qt_audio_output()
        results['deferred_qt_audio_setup_ms'] = (time.perf_counter() - begin) * 1000
        assert player.audio_output.isMuted()
        assert not player.is_playing
        print('VIDEO_FIRST_USE', json.dumps(results))
    finally:
        timer.stop()
        player.cleanup(force_gc=False)
        # These current Qt resources have no native parent. Explicitly destroy
        # them while their receiver and the scene remain alive in this fixture.
        for owner in (player.media_player, player.position_timer):
            owner.deleteLater()
            QCoreApplication.sendPostedEvents(owner, QEvent.DeferredDelete)
        dispose_widget(player._mpv_parking_widget)
        dispose_widget(player)
        scene.clear()
        APP.processEvents()
