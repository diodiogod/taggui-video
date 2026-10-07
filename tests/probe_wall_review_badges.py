"""Opt-in native four-video wall reproduction, through run_isolated.py only.

Run with QT_QPA_PLATFORM=windows. Generates its own media and database; uses
the real wall opener, asynchronous backend, shared play and browser refresh.
"""
import json
import sys
import traceback

import cv2
import numpy as np
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QImage, QColor
from PySide6.QtTest import QTest

from qt_test_helpers import APP, dispose_widget, dispose_qobject, pump
from utils.image import Image
from utils.image_index_db import ImageIndexDB
from utils.latest_task import LatestTask
from utils.review_marks import ReviewFlag
from utils.settings import settings
from utils.sidecar import taggui_sidecar_path
from widgets.main_window import MainWindow
from widgets.video_player import MpvGlWidget


def test_native_four_video_wall_badges(tmp_path, monkeypatch):
    assert APP.platformName() == 'windows', 'This probe needs the native Windows Qt platform'
    monkeypatch.setenv('TAGGUI_FORCE_CLEAN_EXIT_ON_CLOSE', '0')
    monkeypatch.setattr(MainWindow, 'restore', lambda self: None)
    settings.setValue('video_playback_backend', 'mpv_experimental')
    painted_widgets = set()
    original_paint = MpvGlWidget.paintGL

    def observe_paint(widget):
        can_render = (widget._render_ready and widget._mpv_render_ctx is not None
                      and not widget._application_render_suspended)
        original_paint(widget)
        if can_render:
            painted_widgets.add(id(widget))

    monkeypatch.setattr(MpvGlWidget, 'paintGL', observe_paint)
    errors = []
    monkeypatch.setattr(sys, 'excepthook', lambda *error: errors.append(error))
    images = []
    for i in range(4):
        path = tmp_path / f'wall-{i}.avi'
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), 24, (320, 240))
        assert writer.isOpened()
        try:
            for frame in range(720):
                pixels = np.full((240, 320, 3), (40 + i * 30, 65, 85), np.uint8)
                pixels[:, (frame * 4) % 300:((frame * 4) % 300) + 20] = 200
                writer.write(pixels)
        finally:
            writer.release()
        preview = QImage(320, 240, QImage.Format_RGB32)
        preview.fill(QColor(85, 65, 40 + i * 30))
        images.append(Image(path, (320, 240), is_video=True, thumbnail_qimage=preview,
                            video_metadata={'fps': 24, 'frame_count': 720, 'duration': 30}))
    images[0].review_flags = int(ReviewFlag.REJECT)
    host = MainWindow(APP)
    source, proxy = host.image_list_model, host.proxy_image_list_model
    source._directory_path = tmp_path
    source._db = ImageIndexDB(tmp_path)
    source.beginResetModel()
    source._paginated_mode = True
    source.images = images
    source._pages = {0: images}
    source._total_count = 4
    source.endResetModel()
    for image in images:
        source.save_review_state_to_db(image)
    windows, players = [], []
    try:
        host.show()
        windows = host.open_selection_masonry_wall([proxy.index(row, 0) for row in range(4)])
        assert len(windows) == 4
        pump(lambda: all(window.viewer._is_video_loaded for window in windows), seconds=30)
        players = [window.viewer.video_player for window in windows]
        pump(lambda: all(not player._runtime_pending for player in players), seconds=30)
        assert all(player.runtime_playback_backend == 'mpv_experimental' for player in players)
        try:
            pump(lambda: all(player.is_playing and player.mpv_widget is not None
                             and id(player.mpv_widget) in painted_widgets
                             for player in players), seconds=30)
        except AssertionError:
            print('NATIVE_START_FAILURE', json.dumps({
                'application_state': str(APP.applicationState()),
                'sync_scope': host._sync_scope,
                'players': [{'playing': p.is_playing, 'position': p._get_mpv_position_ms(),
                             'surface_active': p._mpv_surface_active,
                             'render_ready': getattr(p.mpv_widget, '_render_ready', None)}
                            for p in players]}))
            raise
        pump(lambda: all((player._get_mpv_position_ms() or 0) > 300 for player in players), seconds=30)
        existing = windows[0]._review_slots_overlay
        existing.set_hover_active(False)
        assert existing._current_review_state() == (0, int(ReviewFlag.REJECT))
        ready = []
        source.ordered_view_ready.connect(ready.append)
        source.prepare_ordered_view(reason='refresh')
        pump(lambda: bool(ready))
        assert existing._current_review_state() == (0, int(ReviewFlag.REJECT))
        target = windows[-1]._review_slots_overlay
        target.set_hover_active(True)
        slot = next(i for i, item in enumerate(target._slot_items()) if item.badge_id == 'flag_warning')
        QTest.mouseClick(target, Qt.LeftButton, pos=target._slot_rect(slot).center())
        APP.processEvents()
        target.set_hover_active(False)
        QTest.qWait(250)
        assert target.isVisible() and existing.isVisible()
        assert target._current_review_state() == (0, int(ReviewFlag.WARNING))
        assert json.loads(taggui_sidecar_path(images[-1].path).read_text())['review_flags'] == ['warning']
        # Exercise the shared control while both badges remain installed.
        host._toggle_selection_wall_play_pause()
        pump(lambda: all(not player.is_playing for player in players))
        host._toggle_selection_wall_play_pause()
        pump(lambda: all(player.is_playing for player in players))
        # Move the actual cursor to a sibling, letting normal wall hover
        # callbacks collapse the clicked tile's palette to its active badge.
        QTest.mouseMove(windows[0].viewer.view.viewport(), QPoint(40, 120))
        QTest.qWait(500)
        assert target._current_review_state() == (0, int(ReviewFlag.WARNING))
        assert not target._hover_active
        assert [spec.badge_id for _, spec in target._display_items()] == ['flag_warning']
        positions = [player._get_mpv_position_ms() for player in players]
        QTest.qWait(250)
        assert all(player._get_mpv_position_ms() > position + 100
                   for player, position in zip(players, positions)), 'Native playback did not advance'
        for label, window in [('existing-reject', windows[0]), ('new-warning', windows[-1])]:
            screenshot = tmp_path / f'{label}.png'
            # Windows cannot grab a translucent layered HWND reliably. Grab
            # only this tile's desktop rectangle, in screen-local Qt units.
            screen = window.screen()
            origin = window.mapToGlobal(QPoint(0, 0)) - screen.geometry().topLeft()
            capture = screen.grabWindow(0, origin.x(), origin.y(), window.width(), window.height())
            assert capture.save(str(screenshot))
            print('CAPTURE_CONTEXT', label, window.geometry(), screen.geometry(),
                  window.isVisible(), APP.applicationState())
            pixels = capture.toImage().convertToFormat(QImage.Format_RGBA8888)
            rgba = np.frombuffer(pixels.constBits(), np.uint8).reshape(
                pixels.height(), pixels.bytesPerLine())[:, :pixels.width() * 4].reshape(
                    pixels.height(), pixels.width(), 4)
            red, green, blue = rgba[:, :, 0], rgba[:, :, 1], rgba[:, :, 2]
            active_color = ((red > 180) & (green < 100) & (blue < 100)
                            if label == 'existing-reject' else
                            (red > 180) & (green > 80) & (green < 190) & (blue < 80))
            print('CAPTURE_PIXELS', label, int(np.count_nonzero(active_color)),
                  int(rgba[:, :, :3].max()), str(screenshot))
            assert np.count_nonzero(active_color) > 100, 'Active badge missing from composited pixels'
            print('WALL_BADGE_SCREENSHOT', str(screenshot))
        print('NATIVE_WALL', json.dumps({'backend': [p.runtime_playback_backend for p in players],
              'positions_ms': [p._get_mpv_position_ms() for p in players],
              'states': [w._review_slots_overlay._current_review_state() for w in windows]}))
    finally:
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
        if errors:
            print('NATIVE_CALLBACK_ERRORS', '\n'.join(
                ''.join(traceback.format_exception(*error)) for error in errors))
        assert not errors, [''.join(traceback.format_exception(*error)) for error in errors]
