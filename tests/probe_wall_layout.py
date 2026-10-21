"""Opt-in native playback/reflow check. Run through run_isolated.py on Windows."""
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback

import cv2
import numpy as np
import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest

from qt_test_helpers import APP, dispose_widget, dispose_qobject, pump, assert_capture_contains_color
from test_floating_wall_reflow import resize_gesture, finish_reflow
from controllers import floating_wall_controller as controller_module
from utils.image import Image
from utils.image_index_db import ImageIndexDB
from utils.latest_task import LatestTask
from utils.settings import settings
from widgets.main_window import MainWindow
from widgets.video_player import MpvGlWidget
from widgets.floating_wall_packing import valid_layout


@pytest.mark.parametrize('initial_paused', [False, True])
def test_native_reflow_preserves_playback_and_toggle_during_pending_layout(tmp_path, monkeypatch, initial_paused):
    assert APP.platformName() == 'windows'
    monkeypatch.setenv('TAGGUI_FORCE_CLEAN_EXIT_ON_CLOSE', '0')
    monkeypatch.setattr(MainWindow, 'restore', lambda self: None)
    settings.setValue('video_playback_backend', 'mpv_experimental')
    settings.setValue('floating_wall_algorithm', 'Best fit')
    settings.setValue('floating_wall_reflow_after_resize', True)
    settings.setValue('floating_wall_automatic_sizing', True)
    settings.setValue('floating_wall_preserve_manual_sizes', True)
    settings.setValue('floating_resize_preserve_aspect_by_default', True)
    settings.setValue('floating_viewer_rearrange_preserve_screen_order', False)
    errors, paints, geometry_decodes = [], {}, []
    monkeypatch.setattr(sys, 'excepthook', lambda *error: errors.append(error))
    original_paint = MpvGlWidget.paintGL

    def observe_paint(widget):
        ready = widget._render_ready and widget._mpv_render_ctx is not None and not widget._application_render_suspended
        original_paint(widget)
        if ready:
            paints[id(widget)] = time.perf_counter()

    monkeypatch.setattr(MpvGlWidget, 'paintGL', observe_paint)
    images = []
    for index, (width, height) in enumerate([(320, 240), (180, 320), (400, 240), (240, 240)]):
        path = tmp_path / f'wall-{index}.avi'
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), 24, (width, height))
        assert writer.isOpened()
        try:
            for frame in range(720):
                pixels = np.full((height, width, 3), (55 + index * 30, 95, 140), np.uint8)
                pixels[:, (frame * 3) % (width - 16):((frame * 3) % (width - 16)) + 16] = 230
                writer.write(pixels)
        finally:
            writer.release()
        preview = QImage(width, height, QImage.Format_RGB32)
        preview.fill(QColor(140, 95, 55 + index * 30))
        images.append(Image(path, (width, height), is_video=True, thumbnail_qimage=preview,
                            video_metadata={'fps': 24, 'frame_count': 720, 'duration': 30}))
    host = MainWindow(APP)
    source, proxy = host.image_list_model, host.proxy_image_list_model
    source._directory_path = tmp_path
    source._db = ImageIndexDB(tmp_path)
    source.beginResetModel()
    source._paginated_mode = True
    source.images = images
    source._pages = {0: images}
    source._total_count = len(images)
    source.endResetModel()
    for image in images:
        source.save_review_state_to_db(image)
    windows, players = [], []
    release = threading.Event()

    def check_visible_frames(label):
        for index, (window, player) in enumerate(zip(windows, players)):
            # A paused viewer can intentionally display its still-frame pixmap.
            # Its hidden MPV surface is then parked at 1x1 and is not the output.
            if player._mpv_surface_active:
                capture = player.mpv_widget.grabFramebuffer()
            else:
                # QWidget.grab() cannot reliably read these native viewport
                # backing stores. Render the active still-frame scene via the
                # QGraphicsView paint path, rather than its parked GL child.
                capture = QImage(window.viewer.view.viewport().size(), QImage.Format_RGB32)
                capture.fill(QColor('black'))
                painter = QPainter(capture)
                try:
                    window.viewer.view.render(painter)
                finally:
                    painter.end()
            output = os.environ.get('TAGGUI_WALL_PROBE_OUTPUT')
            if output:
                directory = Path(output)
                directory.mkdir(parents=True, exist_ok=True)
                capture.save(str(directory / f'framebuffer-{initial_paused}-{label}-{index}.png'))
            assert capture.width() > 16 and capture.height() > 16
            assert_capture_contains_color(capture, (140, 95, 55 + index * 30))

    try:
        host.show()
        windows = host.open_selection_masonry_wall([proxy.index(i, 0) for i in range(4)])
        assert len(windows) == 4
        pump(lambda: all(w.viewer._is_video_loaded for w in windows), seconds=30)
        players = [w.viewer.video_player for w in windows]
        pump(lambda: all(p.is_playing and not p._runtime_pending and p.mpv_widget is not None
                         and id(p.mpv_widget) in paints and (p._get_mpv_position_ms() or 0) > 300
                         for p in players), seconds=30)
        assert all(p.runtime_playback_backend == 'mpv_experimental' for p in players)
        coordinator = host._sync_coordinator
        assert coordinator is not None
        if initial_paused:
            host._toggle_selection_wall_play_pause()
            pump(lambda: all(not p.is_playing for p in players))
        check_visible_frames('before')
        for player in players:
            original_decode = player._show_opencv_frame

            def guarded_decode(*args, decode=original_decode):
                if host._wall_layout._applying:
                    geometry_decodes.append(''.join(traceback.format_stack(limit=14)))
                return decode(*args)

            monkeypatch.setattr(player, '_show_opencv_frame', guarded_decode)
        # Exercise the actual ordered-model refresh before manual manipulation.
        refreshed = []
        source.ordered_view_ready.connect(refreshed.append)
        source.prepare_ordered_view(reason='refresh')
        pump(lambda: bool(refreshed))
        before_positions = [p._get_mpv_position_ms() for p in players]
        started_at = time.perf_counter()
        resize_gesture(windows[0], QPoint(-60, -45))
        chosen_size = windows[0].size()
        finish_reflow(host._wall_layout)
        applied_ms = (time.perf_counter() - started_at) * 1000
        assert windows[0].size() == chosen_size
        assert host._sync_coordinator is coordinator
        assert coordinator.is_paused() == initial_paused
        assert host._selection_wall_controls_active and host._sync_scope == 'selection_wall'
        assert all(p.is_playing != initial_paused for p in players)
        check_visible_frames('after-resize')
        assert valid_layout([w.geometry() for w in windows], windows[0].screen().availableGeometry(), 6)
        if not initial_paused:
            pump(lambda: all(p._get_mpv_position_ms() > before + 100 for p, before in zip(players, before_positions)))
            pump(lambda: all(paints[id(p.mpv_widget)] > started_at for p in players))

        # Keep the real calculation pending long enough to test a global toggle.
        calculation_started = threading.Event()
        original_calculate = controller_module._calculate

        def held(payload, cancelled):
            calculation_started.set()
            assert release.wait(10)
            return original_calculate(payload, cancelled)

        monkeypatch.setattr(controller_module, '_calculate', held)
        resize_gesture(windows[1], QPoint(-35, -35))
        chosen_second = windows[1].size()
        pump(calculation_started.is_set)
        host._toggle_selection_wall_play_pause()
        release.set()
        finish_reflow(host._wall_layout)
        pump(lambda: all(p.is_playing == initial_paused for p in players))
        assert host._sync_coordinator is coordinator
        assert coordinator.is_paused() != initial_paused
        assert windows[0].size() == chosen_size and windows[1].size() == chosen_second
        check_visible_frames('after-toggle')
        assert not geometry_decodes, '\n'.join(geometry_decodes)
        if initial_paused:
            positions = [p._get_mpv_position_ms() for p in players]
            pump(lambda: all(p._get_mpv_position_ms() > before + 100 for p, before in zip(players, positions)))
        output = os.environ.get('TAGGUI_WALL_PROBE_OUTPUT')
        if output:
            path = Path(output)
            path.mkdir(parents=True, exist_ok=True)
            QTest.qWait(200)
            for index, window in enumerate(windows):
                screen = window.screen()
                origin = window.mapToGlobal(QPoint(0, 0)) - screen.geometry().topLeft()
                capture = screen.grabWindow(0, origin.x(), origin.y(), window.width(), window.height())
                assert capture.save(str(path / f'wall-{initial_paused}-{index}.png'))
        print('NATIVE_WALL_LAYOUT', json.dumps({
            'initial_paused': initial_paused, 'final_paused': coordinator.is_paused(),
            'input_to_layout_ms': round(applied_ms, 1),
            'positions_ms': [p._get_mpv_position_ms() for p in players],
            'algorithm': host._wall_layout.last_result.algorithm,
        }))
    finally:
        release.set()
        host._wall_layout.worker.drain()
        host._clear_selection_masonry_wall_state(stop_sync=True)
        for window in windows:
            for task in window.viewer.findChildren(LatestTask):
                task.drain()
            window.viewer.close()
            dispose_widget(window)
        for player in players:
            player.cleanup(force_gc=False)
            dispose_qobject(player.media_player)
            dispose_qobject(player.position_timer)
            dispose_widget(player._mpv_parking_widget)
            dispose_widget(player)
        for task in host.findChildren(LatestTask):
            task.drain()
        source.shutdown_background_workers()
        executor = host.image_list.list_view._masonry_executor
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
        QTest.qWait(180)
        dispose_widget(host)
        APP.processEvents()
        assert not errors, [''.join(traceback.format_exception(*error)) for error in errors]
