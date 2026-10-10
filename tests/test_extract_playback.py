"""Range copies must preserve the source viewer across the real model refresh.

Run through tests/run_isolated.py. Set TAGGUI_TEST_NATIVE_EXTRACT=1 and
QT_QPA_PLATFORM=windows to also check the visible MPV output on Windows.
"""
import json
import os
import subprocess
import sys
from dataclasses import replace
from threading import Event

import pytest
from PySide6.QtCore import QItemSelectionModel, QPoint, QPersistentModelIndex, QThreadPool, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox, QToolTip

from qt_test_helpers import APP, assert_capture_contains_color, dispose_qobject, dispose_widget, pump
from models.image_list_model import ImageListModel
from models.proxy_image_list_model import ProxyImageListModel
from utils.image import Image
from utils.latest_task import LatestTask
from utils.settings import settings
from utils.sidecar import taggui_sidecar_path
from controllers import video_editing_controller as editing
from widgets.main_window import MainWindow


NATIVE = os.environ.get('TAGGUI_TEST_NATIVE_EXTRACT') == '1'


@pytest.fixture
def opened_video(monkeypatch, tmp_path):
    path = tmp_path / 'source.mp4'
    subprocess.run([
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
        'color=c=0xe53935:s=320x240:r=24:d=30', '-c:v', 'libx264',
        '-pix_fmt', 'yuv420p', '-y', str(path),
    ], check=True, capture_output=True, timeout=20)
    monkeypatch.setenv('TAGGUI_FORCE_CLEAN_EXIT_ON_CLOSE', '0')
    monkeypatch.setattr(MainWindow, 'restore', lambda self: None)
    errors = []
    monkeypatch.setattr(sys, 'excepthook', lambda *error: errors.append(error))
    settings.setValue('video_playback_backend', 'mpv_experimental' if NATIVE else 'qt_hybrid')
    settings.setValue('video_training_profile', 'h3_minimax')
    settings.setValue('video_auto_play', False)
    settings.setValue('video_extract_as_copy', True)
    settings.setValue('pagination_threshold', 0)
    settings.setValue('video_controls_visibility_mode', 'always')
    host = MainWindow(APP)
    source, proxy = host.image_list_model, host.proxy_image_list_model
    executor = host.image_list.list_view._masonry_executor
    if NATIVE:
        # Keep captures owned by this temporary test window even if another
        # desktop window takes focus while the extraction worker runs.
        host.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
    host.resize(1100, 800)
    host.show()
    if NATIVE:
        host.raise_()
        host.activateWindow()
    host.load_directory(tmp_path, select_path=str(path))
    viewer = host.image_viewer
    try:
        pump(lambda: viewer._is_video_loaded and viewer.current_media is not None
             and viewer.current_media.path == path, seconds=25)
        pump(lambda: source._view_prepare_owner is None
             and not source._initial_page_load_pending, seconds=15)
        QTest.qWait(250)
        player = viewer.video_player
        pump(lambda: not player._runtime_pending, seconds=15)
        assert viewer.current_media.mtime is not None
        yield host, path, errors
    finally:
        QThreadPool.globalInstance().waitForDone(20000)
        APP.processEvents()
        QToolTip.hideText()
        for task in host.findChildren(LatestTask):
            task.drain()
        host.shutdown_background_workers()
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
        player = viewer.video_player
        if player is not None:
            player.cleanup(force_gc=False)
            parking = player._mpv_parking_widget
            dispose_widget(parking)
        dispose_widget(host)
        APP.processEvents()
    assert not errors


def visible_pixels(viewer):
    """Read the currently visible viewport, including native video children."""
    viewport = viewer.view.viewport()
    origin = viewport.mapToGlobal(QPoint(0, 0))
    return viewport.screen().grabWindow(
        0, origin.x(), origin.y(), viewport.width(), viewport.height()).toImage()


def check_visible(viewer, path, pixels=None):
    pixels = visible_pixels(viewer) if pixels is None else pixels
    try:
        assert_capture_contains_color(pixels, (229, 57, 53))
    except AssertionError:
        pixels.save(str(path.parent / 'failed-native.png'))
        visible_pixels(viewer).save(str(path.parent / 'after-native.png'))
        viewer.grab().save(str(path.parent / 'widget-native.png'))
        print('CAPTURE_GEOMETRY', viewer.view.viewport().mapToGlobal(QPoint(0, 0)),
              viewer.view.viewport().geometry(), viewer.window().geometry(),
              viewer.view.viewport().screen().geometry(), viewer.isVisible(),
              viewer.window().isMinimized(), viewer.current_video_item.isVisible())
        raise


@pytest.mark.parametrize('initial_play', [False, True])
@pytest.mark.parametrize('toggle', [False, True])
def test_precise_copy_keeps_playback_and_next_markers(opened_video, monkeypatch, initial_play, toggle):
    host, path, errors = opened_video
    viewer, source = host.image_viewer, host.image_list_model
    player, controls = viewer.video_player, viewer.video_controls
    controller = host.video_editing_controller
    controls.apply_loop_state(24, 96, False, save=True, emit_signals=True)
    if initial_play:
        host.toggle_viewer_play_pause(viewer)
    if NATIVE and initial_play:
        pump(lambda: player.mpv_player is not None and player.mpv_widget.isVisible(), seconds=15)
    player.seek_to_frame(240)
    QTest.qWait(500)
    if NATIVE:
        check_visible(viewer, path)
    item = viewer.current_video_item
    original_load = player.load_video
    loads = []
    def load(*args, **kwargs):
        loads.append(args[0])
        return original_load(*args, **kwargs)
    monkeypatch.setattr(player, 'load_video', load)
    editor = editing._video_editor_class()
    original_extract = editor.extract_range
    started, release = Event(), Event()
    def extract(*args, **kwargs):
        started.set()
        assert release.wait(10)
        return original_extract(*args, **kwargs)
    monkeypatch.setattr(editor, 'extract_range', extract)
    modal_messages = []
    for name in ('information', 'warning', 'critical'):
        monkeypatch.setattr(QMessageBox, name,
                            lambda *args: modal_messages.append(args[1:]))
    QTimer.singleShot(0, host, lambda: APP.activeModalWidget().accept())
    ready = []
    source.ordered_view_ready.connect(ready.append)
    geometry = host.centralWidget().geometry()
    samples = []
    capture_timer = QTimer(host)
    capture_timer.setInterval(40)
    capture_timer.timeout.connect(lambda: samples.append(visible_pixels(viewer).scaled(128, 128)))
    try:
        controller.extract_video_range()
        assert started.wait(3)
        assert controller._video_operation_active
        # User chooses the next range while the previous copy is encoding.
        controls.apply_loop_state(150, 222, False, save=True, emit_signals=True)
        if toggle:
            host.toggle_viewer_play_pause(viewer)
        expected_play = initial_play != toggle
        if NATIVE and expected_play:
            pump(lambda: player.mpv_player is not None and player.mpv_widget.isVisible(), seconds=15)
        QTest.qWait(300)
        native_player = player.mpv_player
        before = player.get_current_frame_number()
        if NATIVE:
            capture_timer.start()
        release.set()
        pump(lambda: not controller._video_operation_active and bool(ready), seconds=25)
        QTest.qWait(350)  # Include queued selection restore/proxy/layout callbacks.
        capture_timer.stop()
        assert not loads, 'Model refresh reopened the source video'
        assert viewer.current_video_item is item
        assert player.mpv_player is native_player
        assert player.video_path == path
        assert player.is_playing is expected_play
        assert player.get_current_frame_number() >= before - 2
        assert controls.get_loop_range() == (150, 222)
        assert controls.current_image is viewer.current_media
        assert viewer.current_media is source.data(
            source.index(source.get_loaded_row_for_path(path), 0), Qt.UserRole)
        assert source._total_count == 2
        output = path.with_name('source_extract_24-96.mp4')
        assert output.exists() and source._db.get_image_id(output.name) is not None
        # Persist another marker after rebinding, through the refreshed model.
        controls.apply_loop_state(240, 312, False, save=True, emit_signals=True)
        saved = json.loads(taggui_sidecar_path(path).read_text())
        assert saved['loop_start_frame'] == 240 and saved['loop_end_frame'] == 312
        assert not modal_messages
        assert host.centralWidget().geometry() == geometry
        QToolTip.hideText()
        APP.processEvents()
        assert host.centralWidget().geometry() == geometry
        if NATIVE:
            assert samples
            for pixels in samples:
                check_visible(viewer, path, pixels)
            check_visible(viewer, path)
            after = player.get_current_frame_number()
            QTest.qWait(300)
            assert (player.get_current_frame_number() > after) is expected_play
        assert not errors
    finally:
        capture_timer.stop()
        release.set()


def test_changed_video_or_folder_requires_reopen(opened_video):
    host, path, _ = opened_video
    viewer, image = host.image_viewer, host.image_viewer.current_media
    assert viewer._can_reuse_loaded_video(image)
    assert not viewer._can_reuse_loaded_video(replace(image, path=path.with_name('other.mp4')))
    assert not viewer._can_reuse_loaded_video(replace(image, is_video=False))
    assert not viewer._can_reuse_loaded_video(replace(image, mtime=None))
    image.mtime += 1
    assert not viewer._can_reuse_loaded_video(image)
    image.mtime -= 1
    old_directory = host.image_list_model._directory_path
    host.image_list_model._directory_path = old_directory / 'other'
    assert not viewer._can_reuse_loaded_video(image)
    host.image_list_model._directory_path = old_directory
    viewer.video_player.cleanup(force_gc=False)
    assert not viewer._can_reuse_loaded_video(image)


@pytest.mark.parametrize('sort_by', ['Name', 'Modified'])
@pytest.mark.parametrize('thumbnail_size', [96, 512])
def test_repeated_copies_keep_source_when_its_list_row_moves(opened_video, monkeypatch, sort_by, thumbnail_size):
    host, path, errors = opened_video
    viewer, source = host.image_viewer, host.image_list_model
    player, controls = viewer.video_player, viewer.video_controls
    ready, loads, modal_messages = [], [], []
    source.ordered_view_ready.connect(ready.append)
    host._set_image_list_thumbnail_size(thumbnail_size)
    QTest.qWait(450)
    assert host.image_list.list_view.use_masonry is (thumbnail_size == 96)
    # Newly generated filenames sort ahead of their source in descending order.
    host.image_list.set_sort_state(sort_by, 'DESC')
    pump(lambda: bool(ready) and source._view_prepare_owner is None)
    QTest.qWait(250)
    assert viewer.current_media.path == path
    host.toggle_viewer_play_pause(viewer)
    player.seek_to_frame(240)
    if NATIVE:
        pump(lambda: player.mpv_player is not None and player.mpv_widget.isVisible(), seconds=15)
    QTest.qWait(400)
    item, native_player = viewer.current_video_item, player.mpv_player
    original_load = player.load_video
    def load(*args, **kwargs):
        loads.append(args[0])
        return original_load(*args, **kwargs)
    monkeypatch.setattr(player, 'load_video', load)
    for name in ('information', 'warning', 'critical'):
        monkeypatch.setattr(QMessageBox, name,
                            lambda *args: modal_messages.append(args[1:]))
    samples = []
    capture_timer = QTimer(host)
    capture_timer.setInterval(40)
    capture_timer.timeout.connect(lambda: samples.append(visible_pixels(viewer).scaled(128, 128)))
    controls.apply_loop_state(24, 96, False, save=True, emit_signals=True)
    try:
        for row, extracted, next_range in (
            (1, (24, 96), (150, 222)),
            (2, (150, 222), (240, 312)),
        ):
            previous_ready = len(ready)
            before = player.get_current_frame_number()
            QTimer.singleShot(0, host, lambda: APP.activeModalWidget().accept())
            host.video_editing_controller.extract_video_range()
            controls.apply_loop_state(*next_range, False, save=True, emit_signals=True)
            if NATIVE:
                capture_timer.start()
            pump(lambda: not host.video_editing_controller._video_operation_active
                 and len(ready) > previous_ready, seconds=25)
            QTest.qWait(1200)
            capture_timer.stop()
            # A later page notification can replay the old global selection;
            # activation then synchronizes the viewer to that browser index.
            source._emit_pages_updated()
            QTest.qWait(150)
            host._restore_active_browser_context_after_activation()
            assert player.video_path == path
            assert source.get_loaded_row_for_path(path) == row
            assert host.image_list.list_view._selected_global_index == row
            assert host.image_list_selection_model.currentIndex().data(Qt.UserRole).path == path
            assert viewer.current_media.path == path
            assert controls.current_image is viewer.current_media
            assert controls.get_loop_range() == next_range
            assert player.is_playing and player.get_current_frame_number() >= before
            assert viewer.current_video_item is item and player.mpv_player is native_player
            assert path.with_name(f'source_extract_{extracted[0]}-{extracted[1]}.mp4').exists()
            assert not loads and not modal_messages and not errors
        if NATIVE:
            assert samples
            for pixels in samples:
                check_visible(viewer, path, pixels)
            check_visible(viewer, path)
    finally:
        capture_timer.stop()


def test_page_layout_refresh_keeps_native_selection_storage(tmp_path):
    source = ImageListModel(120, ',')
    proxy = ProxyImageListModel(source, None, ',')
    selection = QItemSelectionModel(proxy)
    source.proxy_image_list_model = proxy
    source.image_list_selection_model = selection
    image = Image(tmp_path / 'clip.mp4', (320, 240), is_video=True)
    source.beginResetModel()
    source._directory_path, source._paginated_mode = tmp_path, True
    source._pages, source._total_count = {0: [image]}, 1
    source.endResetModel()
    selection.setCurrentIndex(proxy.index(0, 0), QItemSelectionModel.ClearAndSelect)
    persistent = QPersistentModelIndex(selection.currentIndex())
    try:
        for _ in range(3):
            source._emit_paginated_layout_refresh()
            APP.processEvents()
            assert persistent.isValid() and persistent.data(Qt.UserRole) is image
            assert selection.currentIndex().data(Qt.UserRole) is image
            assert selection.selectedIndexes()[0].data(Qt.UserRole) is image
            assert source._capture_selected_image_paths() == (image.path, (image.path,))
    finally:
        source.shutdown_background_workers()
        dispose_qobject(selection)
        dispose_qobject(proxy)
        dispose_qobject(source)
