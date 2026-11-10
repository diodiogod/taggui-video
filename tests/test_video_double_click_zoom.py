"""Check double-click detail positioning on the visible, playing MPV surface.

Run with TAGGUI_TEST_NATIVE_EXTRACT=1 and QT_QPA_PLATFORM=windows through
tests/run_isolated.py on a visible Windows desktop.
"""

import os
import subprocess
import sys

import pytest
from PySide6.QtCore import QPoint, QPointF, QThreadPool, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QToolTip

from qt_test_helpers import APP, dispose_widget, pump
from test_video_marking_overlay import visible_capture
from test_viewer_double_click_zoom import _wheel_in
from utils.latest_task import LatestTask
from utils.settings import settings
from widgets.main_window import MainWindow


def _has_blue_pixel(viewer, point):
    image = visible_capture(viewer)
    if not image.rect().contains(point):
        return False
    color = image.pixelColor(point)
    return color.blue() > 180 and color.red() < 80 and color.green() < 80


@pytest.fixture
def patterned_video(monkeypatch, tmp_path):
    path = tmp_path / 'pattern.mp4'
    subprocess.run([
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
        'color=c=0xe53935:s=320x240:r=24:d=30', '-vf',
        'drawbox=x=210:y=75:w=20:h=20:color=blue:t=fill', '-c:v', 'libx264',
        '-pix_fmt', 'yuv420p', '-y', str(path),
    ], check=True, capture_output=True, timeout=20)
    monkeypatch.setenv('TAGGUI_FORCE_CLEAN_EXIT_ON_CLOSE', '0')
    monkeypatch.setattr(MainWindow, 'restore', lambda self: None)
    errors = []
    monkeypatch.setattr(sys, 'excepthook', lambda *error: errors.append(error))
    settings.setValue('video_playback_backend', 'mpv_experimental')
    settings.setValue('video_auto_play', False)
    settings.setValue('video_controls_visibility_mode', 'always')
    settings.setValue('pagination_threshold', 0)
    host = MainWindow(APP)
    source = host.image_list_model
    executor = host.image_list.list_view._masonry_executor
    host.setWindowFlag(Qt.WindowStaysOnTopHint)
    host.resize(1100, 800)
    host.show()
    host.move(host.screen().availableGeometry().topLeft() + QPoint(12, 12))
    host.raise_()
    host.activateWindow()
    host.load_directory(tmp_path, select_path=str(path))
    viewer = host.image_viewer
    try:
        pump(lambda: viewer._is_video_loaded and viewer.current_media is not None
             and viewer.current_media.path == path, seconds=25)
        pump(lambda: source._view_prepare_owner is None
             and not source._initial_page_load_pending, seconds=15)
        player = viewer.video_player
        pump(lambda: not player._runtime_pending, seconds=15)
        QTest.qWait(500)
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
            dispose_widget(player._mpv_parking_widget)
        dispose_widget(host)
        APP.processEvents()


@pytest.mark.skipif(os.environ.get('TAGGUI_TEST_NATIVE_EXTRACT') != '1',
                    reason='Requires visible native Windows playback')
def test_native_playback_centers_clicked_detail_and_can_keep_it_under_pointer(patterned_video):
    host, path, errors = patterned_video
    source = host.image_list_model
    ready = []
    source.ordered_view_ready.connect(ready.append)
    viewer, player = host.image_viewer, host.image_viewer.video_player
    host.toggle_viewer_play_pause(viewer)
    pump(lambda: player.is_playing and player.mpv_player is not None
         and player._mpv_surface_active, seconds=15)
    viewport = viewer.view.viewport()
    scene_detail = QPointF(220, 85)

    # Establish that the actual visible playback surface shows the target
    # before drawing any conclusions from a post-zoom capture.
    point = viewer.view.mapFromScene(scene_detail)
    try:
        pump(lambda: _has_blue_pixel(viewer, point), seconds=5)
    except AssertionError:
        image = visible_capture(viewer)
        image.save(str(path.parent / 'before-double-click.png'))
        print('Expected blue at', point, 'viewport', viewport.size(),
              'captured color', image.pixelColor(point).name())
        raise
    settings.setValue('viewer_double_click_zoom_center_on_click', True)
    QTest.mouseDClick(viewport, Qt.LeftButton, Qt.NoModifier, point)
    # The first action can fill an aspect-ratio gap. Wheel zoom further so the
    # remembered scale permits centering on both axes.
    for _ in range(6):
        _wheel_in(viewer, viewport.rect().center())
    remembered = viewer.view.transform().m11()
    QTest.mouseDClick(viewport, Qt.LeftButton, Qt.NoModifier, viewport.rect().center())
    assert viewer.is_zoom_to_fit
    point = viewer.view.mapFromScene(scene_detail)
    clicked_scene = viewer.view.mapToScene(point)
    QTest.mouseDClick(viewport, Qt.LeftButton, Qt.NoModifier, point)
    assert viewer.view.transform().m11() == pytest.approx(remembered)
    center = viewport.rect().center()
    pump(lambda: _has_blue_pixel(viewer, center), seconds=5)
    assert (viewer.view.mapFromScene(clicked_scene) - center).manhattanLength() <= 3
    assert player.is_playing

    QTest.mouseDClick(viewport, Qt.LeftButton, Qt.NoModifier, center)
    assert viewer.is_zoom_to_fit
    point = viewer.view.mapFromScene(scene_detail)
    clicked_scene = viewer.view.mapToScene(point)
    settings.setValue('viewer_double_click_zoom_center_on_click', False)
    QTest.mouseDClick(viewport, Qt.LeftButton, Qt.NoModifier, point)
    pump(lambda: _has_blue_pixel(viewer, point), seconds=5)
    assert (viewer.view.mapFromScene(clicked_scene) - point).manhattanLength() <= 3
    assert player.is_playing

    # Exercise the normal model refresh while the same native player is active.
    native_player = player.mpv_player
    previous_ready = len(ready)
    source.prepare_ordered_view(reason='refresh')
    pump(lambda: len(ready) > previous_ready, seconds=20)
    QTest.qWait(400)
    assert viewer.current_media.path == path and player.mpv_player is native_player
    assert player.is_playing
    if not viewer.is_zoom_to_fit:
        QTest.mouseDClick(viewport, Qt.LeftButton, Qt.NoModifier, center)
    assert viewer.is_zoom_to_fit
    settings.setValue('viewer_double_click_zoom_center_on_click', True)
    point = viewer.view.mapFromScene(scene_detail)
    pump(lambda: _has_blue_pixel(viewer, point), seconds=5)
    for _ in range(6):
        _wheel_in(viewer, center)
    QTest.mouseDClick(viewport, Qt.LeftButton, Qt.NoModifier, center)
    assert viewer.is_zoom_to_fit
    point = viewer.view.mapFromScene(scene_detail)
    clicked_scene = viewer.view.mapToScene(point)
    QTest.mouseDClick(viewport, Qt.LeftButton, Qt.NoModifier, point)
    pump(lambda: _has_blue_pixel(viewer, center), seconds=5)
    assert (viewer.view.mapFromScene(clicked_scene) - center).manhattanLength() <= 3
    assert player.is_playing
    assert not errors
