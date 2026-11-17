"""Opt-in Windows MPV probe: real opening, visible output, resize and global pause."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys
import traceback

import cv2
import numpy as np
import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest

from qt_test_helpers import APP, assert_capture_contains_color, dispose_qobject, dispose_widget, pump
from test_floating_resize_group import begin_resize, move_resize, release_resize
from test_floating_wall_reflow import finish_reflow, resize_gesture
from utils.image import Image
from utils.image_index_db import ImageIndexDB
from utils.latest_task import LatestTask
from utils.settings import settings
from widgets.floating_wall_packing import valid_layout
from widgets.main_window import MainWindow


@pytest.mark.parametrize('initial_paused', [False, True])
def test_native_group_resize_and_global_toggle(tmp_path, monkeypatch, initial_paused):
    assert APP.platformName() == 'windows'
    monkeypatch.setenv('TAGGUI_FORCE_CLEAN_EXIT_ON_CLOSE', '0')
    monkeypatch.setattr(MainWindow, 'restore', lambda self: None)
    for key, value in {
        'video_playback_backend': 'mpv_experimental',
        'floating_wall_reflow_after_resize': True,
        'floating_wall_automatic_sizing': True,
        'floating_wall_preserve_manual_sizes': False,
        'floating_resize_preserve_aspect_by_default': False,
        'floating_viewer_rearrange_preserve_screen_order': False,
        'floating_wall_algorithm': 'MaxRects',
    }.items():
        settings.setValue(key, value)
    errors = []
    monkeypatch.setattr(sys, 'excepthook', lambda *error: errors.append(error))
    images = []
    colors = [(140, 95, 55+index*30) for index in range(4)]
    for index, (width, height) in enumerate([(320, 240), (180, 320), (400, 240), (240, 240)]):
        path = tmp_path / f'group-{index}.avi'
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), 24, (width, height))
        assert writer.isOpened()
        try:
            for frame in range(720):
                pixels = np.full((height, width, 3), colors[index][::-1], np.uint8)
                pixels[:, (frame*3) % (width-16):(frame*3) % (width-16)+16] = 230
                writer.write(pixels)
        finally:
            writer.release()
        preview = QImage(width, height, QImage.Format_RGB32)
        preview.fill(QColor(*colors[index]))
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

    def visible_frames(label):
        QTest.qWait(200)
        for index, window in enumerate(windows):
            screen = window.screen()
            rect = window.geometry()
            capture = screen.grabWindow(0, rect.x()-screen.geometry().x(), rect.y()-screen.geometry().y(),
                                        rect.width(), rect.height()).toImage()
            output = os.environ.get('TAGGUI_WALL_PROBE_OUTPUT')
            if output:
                directory = Path(output)
                directory.mkdir(parents=True, exist_ok=True)
                capture.save(str(directory / f'group-{initial_paused}-{label}-{index}.png'))
            try:
                assert_capture_contains_color(capture, colors[index], minimum_fraction=.08)
            except AssertionError as error:
                raise AssertionError(f'{label}, window {index}, {rect}: {error}') from None

    try:
        host.show()
        windows = host.open_selection_masonry_wall([proxy.index(i, 0) for i in range(4)])
        assert len(windows) == 4
        # Establish visible native output before asserting anything about resize.
        position_window = ctypes.windll.user32.SetWindowPos
        position_window.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        position_window.restype = wintypes.BOOL
        for window in windows:
            assert position_window(int(window.winId()), wintypes.HWND(-1), 0, 0, 0, 0, 0x0013)
        windows[0].raise_()
        windows[0].activateWindow()
        pump(lambda: all(w.viewer._is_video_loaded for w in windows), seconds=30)
        players = [w.viewer.video_player for w in windows]
        pump(lambda: all(p.is_playing and not p._runtime_pending and p.mpv_widget is not None
                         and (p._get_mpv_position_ms() or 0) > 300 for p in players), seconds=30)
        assert all(p.runtime_playback_backend == 'mpv_experimental' for p in players)
        coordinator = host._sync_coordinator
        if initial_paused:
            host._toggle_selection_wall_play_pause()
            pump(lambda: all(not p.is_playing for p in players))
        refreshed = []
        source.ordered_view_ready.connect(refreshed.append)
        source.prepare_ordered_view(reason='refresh')
        pump(lambda: bool(refreshed))
        visible_frames('before')
        original = [QRect(w.geometry()) for w in windows]
        point = begin_resize(windows[0])
        destination = point+QPoint(96-windows[0].width(), 96-windows[0].height())
        move_resize(windows[0], destination)
        assert all(w.width() == 96 and w.height() == 96 for w in windows)
        assert [w.pos() for w in windows[1:]] == [r.topLeft() for r in original[1:]]
        assert all(p.is_playing != initial_paused for p in players)
        visible_frames('during')
        host._toggle_selection_wall_play_pause()
        pump(lambda: all(p.is_playing == initial_paused for p in players))
        release_resize(windows[0], destination)
        finish_reflow(host._wall_layout)
        assert all(w.width() == 96 and w.height() == 96 for w in windows)
        assert valid_layout([w.geometry() for w in windows], windows[0].screen().availableGeometry(), 6)
        assert host._sync_coordinator is coordinator and coordinator.is_paused() != initial_paused
        assert all(p.is_playing == initial_paused for p in players)
        visible_frames('after')
        # Return to ordinary resizing after the shared gesture and async repack.
        siblings = [w.size() for w in windows[1:]]
        resize_gesture(windows[0], QPoint(-10, -10), Qt.AltModifier)
        finish_reflow(host._wall_layout)
        assert [w.size() for w in windows[1:]] == siblings
        assert windows[0].width() == 86 and windows[0].height() == 86
        assert all(p.is_playing == initial_paused for p in players)
        visible_frames('ordinary')
    finally:
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
