"""Visible annotations must stay above the actual playing MPV surface.

Native check: TAGGUI_TEST_NATIVE_EXTRACT=1 QT_QPA_PLATFORM=windows, then run
through tests/run_isolated.py to isolate settings and cache roots first.
"""
import json
import os
import shutil
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPen, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView, QLabel, QWidget

from qt_test_helpers import APP, assert_capture_contains_color, dispose_qobject, dispose_widget, pump
from test_extract_playback import opened_video
from utils.image import ImageMarking
from utils.sidecar import taggui_sidecar_path
from widgets.scene_foreground_overlay import SceneForegroundOverlay


def test_foreground_tracks_geometry_visibility_and_cover_stacking():
    scene = QGraphicsScene()
    view = QGraphicsView(scene)
    view.setViewport(QWidget())
    view.resize(340, 280)
    scene.setSceneRect(0, 0, 320, 240)
    pixmap = QPixmap(320, 240)
    pixmap.fill(QColor('red'))
    media = QGraphicsPixmapItem(pixmap)
    scene.addItem(media)
    marking = QGraphicsRectItem(50, 40, 160, 120)
    marking.setPen(QPen(QColor('blue'), 4))
    marking.setZValue(2)
    scene.addItem(marking)
    child = QGraphicsRectItem(60, 50, 10, 10, marking)
    child.setBrush(QColor('green'))
    cover = QLabel(view.viewport())
    cover.setPixmap(pixmap)
    cover.setScaledContents(True)
    cover.setAttribute(Qt.WA_TransparentForMouseEvents)
    overlay = SceneForegroundOverlay(view, lambda item: item is marking or item.parentItem() is marking)
    view.image_viewer = SimpleNamespace(raise_viewport_overlays=lambda: overlay.sync_surfaces([cover]))

    def color_at(scene_x, scene_y):
        point = view.mapFromScene(scene_x, scene_y)
        capture = view.viewport().grab().toImage().scaled(view.viewport().size())
        return capture.pixelColor(point)

    try:
        view.show()
        cover.setGeometry(view.viewport().rect())
        cover.show()
        overlay.sync_surfaces([cover])
        QTest.qWait(50)
        assert overlay.isVisible() and overlay.testAttribute(Qt.WA_TransparentForMouseEvents)
        assert color_at(50, 100) == QColor('blue')
        assert color_at(65, 55) == QColor('green')
        assert color_at(150, 100) == QColor('red'), 'Foreground painted over the video pixels'
        marking.setPos(20, 0)
        QTest.qWait(50)
        assert color_at(50, 100) == QColor('red') and color_at(70, 100) == QColor('blue')
        marking.setVisible(False)
        QTest.qWait(50)
        assert color_at(70, 100) == QColor('red')
        marking.setVisible(True)
        view.scale(1.1, 1.1)
        view.centerOn(160, 120)
        cover.raise_()
        QTest.qWait(50)
        assert color_at(70, 100).blue() > 200
        assert overlay.geometry() == view.viewport().rect()
        cover.hide()
        QTest.qWait(20)
        assert not overlay.isVisible()
        assert scene.items() == [child, marking, media]
    finally:
        dispose_widget(view)
        dispose_qobject(scene)


def test_foreground_deletion_retires_pending_scene_updates():
    scene = QGraphicsScene()
    sibling = QGraphicsView(scene)
    view = QGraphicsView(scene)
    overlay = SceneForegroundOverlay(view, lambda item: True)
    cover = QLabel(view.viewport())
    cover.resize(100, 100)
    view.image_viewer = SimpleNamespace(raise_viewport_overlays=lambda: overlay.sync_surfaces([cover]))
    try:
        view.show()
        cover.show()
        overlay.sync_surfaces([cover])
        scene.addRect(1, 1, 20, 20)
        # Delete the observer before queued scene.changed/viewport paints run.
        dispose_widget(view)
        APP.processEvents()
        scene.addRect(40, 40, 20, 20)
        APP.processEvents()
        assert len(sibling.scene().items()) == 2
    finally:
        dispose_widget(sibling)
        dispose_qobject(scene)


def visible_capture(viewer):
    viewport = viewer.view.viewport()
    screen = viewport.screen()
    origin = viewport.mapToGlobal(QPoint()) - screen.geometry().topLeft()
    capture = screen.grabWindow(0, origin.x(), origin.y(), viewport.width(), viewport.height()).toImage()
    # Desktop captures use physical pixels on high-DPI screens, while scene
    # mapping and mouse input use logical viewport coordinates.
    capture = capture.scaled(viewport.size())
    capture.setDevicePixelRatio(1.0)
    return capture


def assert_crop_pixels(viewer, output):
    try:
        pixels = wait_for_visible_frame(viewer)
    except AssertionError:
        visible_capture(viewer).save(str(output))
        raise
    pixels.save(str(output))
    assert_capture_contains_color(pixels, (229, 57, 53))
    rect = viewer.view.mapFromScene(viewer.crop_marking.rect()).boundingRect()
    # Check the middle of each edge, away from the size HUD and resize handles.
    checked = 0
    for point in (QPoint(rect.left(), rect.center().y()),
                  QPoint(rect.right(), rect.center().y()),
                  QPoint(rect.center().x(), rect.top()),
                  QPoint(rect.center().x(), rect.bottom())):
        if not pixels.rect().contains(point):
            continue
        checked += 1
        blue = sum(
            pixels.pixelColor(x, y).blue() > 200
            and pixels.pixelColor(x, y).red() < 60
            and pixels.pixelColor(x, y).green() < 60
            for y in range(max(0, point.y() - 5), min(pixels.height(), point.y() + 6))
            for x in range(max(0, point.x() - 5), min(pixels.width(), point.x() + 6))
        )
        assert blue >= 4, f'Crop edge missing on visible video at {point}'
    assert checked >= 2, 'Too few crop edges are visible to check their alignment'


def wait_for_visible_frame(viewer):
    captured = None
    def visible():
        nonlocal captured
        try:
            captured = visible_capture(viewer)
            assert_capture_contains_color(captured, (229, 57, 53))
            return True
        except AssertionError:
            return False
    pump(visible, seconds=3)
    return captured


@pytest.mark.skipif(os.environ.get('TAGGUI_TEST_NATIVE_EXTRACT') != '1',
                    reason='Requires visible native Windows playback')
@pytest.mark.parametrize('initial_play', [False, True])
def test_native_playing_crop_draw_resize_and_surface_transitions(opened_video, initial_play):
    host, path, errors = opened_video
    viewer, player = host.image_viewer, host.image_viewer.video_player
    # Place the window on one screen so capture coordinates are unambiguous.
    available = host.screen().availableGeometry()
    host.resize(min(1000, available.width()), min(750, available.height()))
    host.move(available.topLeft() + QPoint(12, 12))
    host.raise_()
    host.activateWindow()
    if initial_play:
        host.toggle_viewer_play_pause(viewer)
        pump(lambda: player.mpv_player is not None and player._mpv_surface_active, seconds=15)
    QTest.qWait(600)
    initial = visible_capture(viewer)
    initial.save(str(path.parent / 'playing-before-crop.png'))
    assert_capture_contains_color(initial, (229, 57, 53))
    before = player.get_current_frame_number()
    view, viewport = viewer.view, viewer.view.viewport()
    viewer.add_marking(ImageMarking.CROP)
    start = view.mapFromScene(40, 40)
    end = view.mapFromScene(240, 180)

    def move(pos, buttons=Qt.NoButton):
        # Deliver motion synchronously through Qt's real input path. The native
        # QTest.mouseMove moves the OS cursor and can arrive after the press.
        APP.sendEvent(viewport, QMouseEvent(
            QEvent.MouseMove, QPointF(pos), QPointF(viewport.mapToGlobal(pos)),
            Qt.NoButton, buttons, Qt.NoModifier,
        ))

    # Starting insertion must use the press itself, even without a preceding
    # hover event (common immediately after changing the selected video).
    view.last_pos = None
    QTest.mousePress(viewport, Qt.LeftButton, pos=start)
    move(end, Qt.LeftButton)
    QTest.qWait(120)
    assert_crop_pixels(viewer, path.parent / 'drawing-crop.png')
    host.toggle_viewer_play_pause(viewer)
    if not initial_play:
        pump(lambda: player.mpv_player is not None and player._mpv_surface_active, seconds=15)
    QTest.qWait(150)
    assert_crop_pixels(viewer, path.parent / 'drawing-after-toggle.png')
    QTest.mouseRelease(viewport, Qt.LeftButton, pos=end)
    QTest.qWait(250)
    assert viewer.current_media.crop is not None
    assert_crop_pixels(viewer, path.parent / 'drawn-crop.png')
    assert player.is_playing is not initial_play
    if initial_play:
        host.toggle_viewer_play_pause(viewer)
        pump(lambda: player._mpv_surface_active, seconds=15)
    native = player.mpv_player
    assert player.is_playing
    pump(lambda: player.get_current_frame_number() > before, seconds=5)
    assert json.loads(taggui_sidecar_path(path).read_text())['crop'] == list(viewer.current_media.crop.getRect())

    # Resize through the scene item while the external renderer is playing.
    old_crop = QRect(viewer.current_media.crop)
    corner = view.mapFromScene(viewer.crop_marking.rect().bottomRight())
    resized = view.mapFromScene(260, 200)
    move(corner)
    QTest.mousePress(viewport, Qt.LeftButton, pos=corner)
    move(resized, Qt.LeftButton)
    QTest.mouseRelease(viewport, Qt.LeftButton, pos=resized)
    QTest.qWait(150)
    assert viewer.current_media.crop != old_crop
    assert_crop_pixels(viewer, path.parent / 'resized-crop.png')
    viewer.zoom_in()
    view.centerOn(viewer.scene.sceneRect().center())
    QTest.qWait(150)
    assert_crop_pixels(viewer, path.parent / 'zoomed-crop.png')
    viewer.zoom_fit()
    QTest.qWait(100)

    # Covers used by actual reverse playback must not hide the annotations.
    player.set_playback_speed(-1.0)
    pump(lambda: player._opencv_cover_label is not None and player._opencv_cover_label.isVisible())
    assert_crop_pixels(viewer, path.parent / 'reverse-crop.png')
    player.set_playback_speed(1.0)
    pump(lambda: player._mpv_surface_active)
    assert_crop_pixels(viewer, path.parent / 'forward-crop.png')

    # Include the same ordered-view refresh used when an extraction completes.
    ready = []
    host.image_list_model.ordered_view_ready.connect(ready.append)
    host.image_list_model.prepare_ordered_view(reason='refresh')
    pump(lambda: bool(ready))
    QTest.qWait(600)
    assert_crop_pixels(viewer, path.parent / 'refreshed-crop.png')
    assert player.mpv_player is native and player.is_playing and player.video_path == path
    assert viewer.current_media.path == path

    # Switching media must clear the old layer and rebuild the saved crop on
    # return, through the real player load/initialization path.
    other = path.with_name('other.mp4')
    shutil.copy2(path, other)
    previous_ready = len(ready)
    assert host.video_editing_controller._register_generated_media(other, select=False)
    pump(lambda: len(ready) > previous_ready)
    QTest.qWait(250)

    def select(media_path):
        model = host.image_list_model
        index = model.index(model.get_index_for_path(media_path), 0)
        host.image_list.list_view.setCurrentIndex(host.proxy_image_list_model.mapFromSource(index))
        pump(lambda: viewer.current_media.path == media_path and player.video_path == media_path,
             seconds=15)
        QTest.qWait(400)

    select(other)
    assert viewer.crop_marking is None and viewer.current_media.crop is None
    select(path)
    assert viewer.crop_marking is not None
    if not player.is_playing:
        host.toggle_viewer_play_pause(viewer)
    pump(lambda: player._mpv_surface_active, seconds=15)
    assert_crop_pixels(viewer, path.parent / 'returned-crop.png')
    assert not errors
