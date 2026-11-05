"""Exercise prompt actions after real video loading and during playback.

Set TAGGUI_TEST_NATIVE_PROMPT=1 and QT_QPA_PLATFORM=windows to check the
visible MPV surface. Run through tests/run_isolated.py.
"""

import os
import sys

import pytest
from PySide6.QtCore import QPoint, QThreadPool, QTimer, Qt
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu, QToolTip
from shiboken6 import isValid

from qt_test_helpers import APP, assert_capture_contains_color, dispose_widget, pump
from test_generation_prompt_video import make_video, requires_ffmpeg
from utils.latest_task import LatestTask
from utils.settings import settings
from widgets.generation_prompt_dialog import GenerationPromptDialog
from widgets.main_window import MainWindow


NATIVE = os.environ.get('TAGGUI_TEST_NATIVE_PROMPT') == '1'


@pytest.fixture
def opened_prompt_videos(tmp_path, monkeypatch):
    paths = [tmp_path / 'a.mp4', tmp_path / 'b.mp4']
    for path, prompt in zip(paths, ('prompt A', 'prompt B')):
        make_video(path, {'parameters': f'{prompt}\nNegative prompt: bad\nSteps: 20'}, duration=20)
    originals = {path: path.read_bytes() for path in paths}
    monkeypatch.setenv('TAGGUI_FORCE_CLEAN_EXIT_ON_CLOSE', '0')
    monkeypatch.setattr(MainWindow, 'restore', lambda self: None)
    errors = []
    monkeypatch.setattr(sys, 'excepthook', lambda *error: errors.append(error))
    settings.setValue('video_playback_backend', 'mpv_experimental' if NATIVE else 'qt_hybrid')
    settings.setValue('video_auto_play', False)
    settings.setValue('secondary_browser_restore_on_startup', False)
    settings.setValue('secondary_browser_visible', False)
    settings.setValue('pagination_threshold', 0)
    host = MainWindow(APP)
    source = host.image_list_model
    executor = host.image_list.list_view._masonry_executor
    if NATIVE:
        host.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
    host.resize(1050, 750)
    host.show()
    if NATIVE:
        available = host.screen().availableGeometry()
        host.move(available.topLeft() + QPoint(12, 12))
        host.raise_()
        host.activateWindow()
    host.load_directory(tmp_path, select_path=str(paths[0]))
    try:
        pump(lambda: host.image_viewer._is_video_loaded
             and host.image_viewer.current_media is not None
             and host.image_viewer.current_media.path == paths[0], seconds=25)
        pump(lambda: source._view_prepare_owner is None and not source._initial_page_load_pending,
             seconds=15)
        pump(lambda: not host.image_viewer.video_player._runtime_pending, seconds=15)
        QTest.qWait(300)
        yield host, paths
        assert all(path.read_bytes() == originals[path] for path in paths)
        assert not errors
    finally:
        QThreadPool.globalInstance().waitForDone(20000)
        APP.processEvents()
        QToolTip.hideText()
        windows = [window for window in getattr(host, '_floating_viewers', []) if isValid(window)]
        for dialog in host.findChildren(GenerationPromptDialog):
            if isValid(dialog):
                dialog._worker.drain()
                dispose_widget(dialog)
        for window in windows:
            for task in window.viewer.findChildren(LatestTask):
                task.drain()
            player = window.viewer.video_player
            if player is not None:
                player.cleanup(force_gc=False)
                if isValid(player._mpv_parking_widget):
                    dispose_widget(player._mpv_parking_widget)
            window.viewer.close()
            dispose_widget(window)
        for task in host.findChildren(LatestTask):
            task.drain()
        host.shutdown_background_workers()
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
        player = host.image_viewer.video_player
        if player is not None:
            player.cleanup(force_gc=False)
            if isValid(player._mpv_parking_widget):
                dispose_widget(player._mpv_parking_widget)
        dispose_widget(host)
        APP.processEvents()


def choose_context_action(host, target, label, *, before_click=None):
    point = target.rect().center()
    failures = []
    watchdog = QTimer(host)
    watchdog.setSingleShot(True)

    def close_stuck_menu():
        failures.append(AssertionError('The context menu did not complete its action'))
        menu = QApplication.activePopupWidget()
        if isinstance(menu, QMenu):
            menu.close()
    watchdog.timeout.connect(close_stuck_menu)

    def click_action():
        try:
            if before_click:
                before_click()
            menu = QApplication.activePopupWidget()
            assert isinstance(menu, QMenu)
            action = next(item for item in menu.actions() if item.text() == label)
            assert action.isEnabled()
            QTest.mouseClick(menu, Qt.MouseButton.LeftButton,
                             pos=menu.actionGeometry(action).center())
        except Exception as error:
            failures.append(error)
            menu = QApplication.activePopupWidget()
            if isinstance(menu, QMenu):
                menu.close()

    QTimer.singleShot(0, host, click_action)
    watchdog.start(3000)
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, target.mapToGlobal(point))
    QApplication.sendEvent(target, event)
    watchdog.stop()
    watchdog.deleteLater()
    assert not failures, failures


def visible_video(viewer):
    viewport = viewer.view.viewport()
    screen = viewport.screen()
    origin = viewport.mapToGlobal(QPoint()) - screen.geometry().topLeft()
    return screen.grabWindow(0, origin.x(), origin.y(), viewport.width(), viewport.height()).toImage()


@requires_ffmpeg
@pytest.mark.parametrize('initial_play', [False, True])
def test_browser_prompt_action_preserves_loaded_video_and_playback(opened_prompt_videos, initial_play):
    host, paths = opened_prompt_videos
    viewer, view = host.image_viewer, host.image_list.list_view
    player = viewer.video_player
    if initial_play:
        if not NATIVE:
            # The offscreen Qt multimedia service may not play forward; use
            # the real OpenCV reverse-playback path and check advancing frames.
            player.seek_to_frame(200)
            player.set_playback_speed(-1)
            start_frame = player.get_current_frame_number()
        host.toggle_viewer_play_pause(viewer)
        pump(lambda: player.is_playing)
        if NATIVE:
            pump(lambda: player.mpv_player is not None and player._mpv_surface_active, seconds=15)
            pump(lambda: player.mpv_player.time_pos is not None, seconds=5)
        else:
            pump(lambda: player.get_current_frame_number() < start_frame, seconds=10)
            assert_capture_contains_color(player.pixmap_item.pixmap().toImage(), (253, 0, 0))
    if NATIVE:
        pump(lambda: _visible_red(viewer), seconds=5)
    assert viewer.current_media.path == paths[0]
    before_frame = player.get_current_frame_number()
    native_player = player.mpv_player
    before_native_position = native_player.time_pos if NATIVE and initial_play else None
    QApplication.clipboard().setText('before')
    choose_context_action(host, view.viewport(), 'Copy Positive Prompt')
    pump(lambda: QApplication.clipboard().text() == 'prompt A', seconds=10)
    assert viewer.current_media.path == paths[0]
    assert player.video_path == paths[0]
    assert player.is_playing is initial_play
    assert player.mpv_player is native_player
    if NATIVE:
        pump(lambda: _visible_red(viewer), seconds=5)
        if initial_play:
            pump(lambda: player.mpv_player.time_pos is not None
                 and player.mpv_player.time_pos > before_native_position + 0.1, seconds=5)
    elif initial_play:
        pump(lambda: player.get_current_frame_number() < before_frame, seconds=10)
        assert_capture_contains_color(player.pixmap_item.pixmap().toImage(), (253, 0, 0))


def _visible_red(viewer):
    try:
        assert_capture_contains_color(visible_video(viewer), (253, 0, 0))
        return True
    except AssertionError:
        return False


@requires_ffmpeg
def test_floating_video_prompt_uses_clicked_viewer_with_sibling_playing(opened_prompt_videos):
    host, paths = opened_prompt_videos
    main = host.image_viewer
    proxy = host.proxy_image_list_model
    index = next(proxy.index(row, 0) for row in range(proxy.rowCount())
                 if proxy.index(row, 0).data(Qt.UserRole).path == paths[1])
    floating = host.spawn_floating_viewer_at(index)
    pump(lambda: floating.viewer.current_media is not None
         and floating.viewer.current_media.path == paths[1], seconds=15)
    player = floating.viewer.video_player
    pump(lambda: not player._runtime_pending, seconds=15)
    if not NATIVE:
        player.seek_to_frame(200)
        player.set_playback_speed(-1)
        start_frame = player.get_current_frame_number()
    host.toggle_viewer_play_pause(floating.viewer)
    pump(lambda: player.is_playing)
    if NATIVE:
        pump(lambda: player.mpv_player is not None and player._mpv_surface_active, seconds=15)
        pump(lambda: player.mpv_player.time_pos is not None and _visible_red(floating.viewer), seconds=5)
    else:
        pump(lambda: player.get_current_frame_number() < start_frame, seconds=10)
        assert_capture_contains_color(player.pixmap_item.pixmap().toImage(), (253, 0, 0))
    before_frame = player.get_current_frame_number()
    before_native_position = player.mpv_player.time_pos if NATIVE else None
    assert not main.video_player.is_playing
    target = player.mpv_widget if NATIVE and player._mpv_surface_active else floating.viewer.view.viewport()
    choose_context_action(host, target, 'View / Copy Generation Prompt...',
                          before_click=lambda: host.set_active_viewer(main))
    pump(lambda: any(dialog.isVisible() for dialog in floating.findChildren(GenerationPromptDialog)))
    dialog = next(dialog for dialog in floating.findChildren(GenerationPromptDialog) if dialog.isVisible())
    pump(lambda: dialog.copy_button.isEnabled(), seconds=10)
    assert dialog.path == paths[1]
    assert dialog.text.toPlainText() == 'prompt B'
    QTest.mouseClick(dialog.copy_button, Qt.MouseButton.LeftButton)
    assert QApplication.clipboard().text() == 'prompt B'
    assert floating.viewer.current_media.path == paths[1] and player.is_playing
    assert main.current_media.path == paths[0] and not main.video_player.is_playing
    if NATIVE:
        dialog.close()
        pump(lambda: _visible_red(floating.viewer), seconds=5)
        pump(lambda: player.mpv_player.time_pos is not None
             and player.mpv_player.time_pos > before_native_position + 0.1, seconds=5)
    else:
        pump(lambda: player.get_current_frame_number() < before_frame, seconds=10)
        assert_capture_contains_color(player.pixmap_item.pixmap().toImage(), (253, 0, 0))
