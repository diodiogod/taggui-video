"""Keep still-image detail when Qt's OpenGL texture limit is exceeded."""

import os
import sys
import threading

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF, QRect, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QStandardItem, QStandardItemModel, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGraphicsItem

from qt_test_helpers import APP, dispose_widget, pump
from utils.image import Image
from utils.settings import settings
from widgets import image_viewer
from widgets.marking import MarkingItem


@pytest.fixture(params=['mpv_experimental', 'vlc_experimental'])
def viewer_and_model(tmp_path, request, monkeypatch):
    read_setting = settings.value

    def setting_value(key, *args, **kwargs):
        if key == 'video_playback_backend':
            return request.param
        return read_setting(key, *args, **kwargs)

    monkeypatch.setattr(settings, 'value', setting_value)
    source = QStandardItemModel()
    source._directory_path = tmp_path
    for index, color in enumerate(('red', 'blue')):
        path = tmp_path / f'{index}.png'
        pixels = QImage(640, 2560, QImage.Format_RGB32)
        pixels.fill(QColor(color))
        assert pixels.save(str(path))
        item = QStandardItem()
        item.setData(Image(path, (640, 2560)), Qt.UserRole)
        source.appendRow(item)
    proxy = QSortFilterProxyModel()
    proxy.setSourceModel(source)
    viewer = image_viewer.ImageViewer(proxy)
    viewer.resize(640, 480)
    try:
        viewer.load_image(proxy.index(0, 0))
        pump(lambda: viewer.current_image_item is not None and viewer._image_decode_owner is None)
        yield viewer, proxy, source, request.param
    finally:
        viewer._compare_prepare_task.drain()
        viewer._image_decode_task.drain()
        dispose_widget(viewer)
        APP.processEvents()


def _press_and_release(viewer, idle_items, idle_filter=Qt.SmoothTransformation):
    viewport = viewer.view.viewport()
    point = QPoint(10, 10)
    QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, point)
    assert viewer.view._manual_pan_active
    assert all(item.cacheMode() == QGraphicsItem.DeviceCoordinateCache for item in idle_items)
    assert all(item.transformationMode() == Qt.FastTransformation for item in idle_items)
    QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, point)
    assert not viewer.view._manual_pan_active
    assert all(item.cacheMode() == QGraphicsItem.NoCache for item in idle_items)
    assert all(item.transformationMode() == idle_filter for item in idle_items)


def test_still_cache_survives_zoom_pan_and_comparison(viewer_and_model):
    viewer, proxy, _, backend = viewer_and_model
    base = viewer.current_image_item
    assert base.cacheMode() == QGraphicsItem.NoCache

    viewer._apply_uniform_zoom_scale(.2, False)
    assert viewer._static_current_mip_divisor == 2
    assert base.pixmap().size().toTuple() == (320, 1280)
    assert base.cacheMode() == QGraphicsItem.NoCache
    _press_and_release(viewer, [base])

    assert viewer.enter_compare_mode(proxy.index(0, 0), proxy.index(1, 0))
    pump(lambda: viewer._compare_prepare_owner is None and viewer._compare_overlay_count() == 1)
    overlay = viewer._compare_layers[0]['overlay_item']
    assert viewer._static_current_mip_divisor == 1
    assert base.cacheMode() == overlay.cacheMode() == QGraphicsItem.NoCache
    _press_and_release(viewer, [base, overlay])
    for zoom, expected in ((.99, Qt.SmoothTransformation), (1., Qt.FastTransformation),
                           (4., Qt.FastTransformation), (.99, Qt.SmoothTransformation)):
        viewer._apply_uniform_zoom_scale(zoom, False)
        assert base.transformationMode() == overlay.transformationMode() == expected
        _press_and_release(viewer, [base, overlay], expected)
    viewer._apply_uniform_zoom_scale(.2, False)
    assert viewer.exit_compare_mode()
    assert viewer._static_current_mip_divisor == 2
    assert base.cacheMode() == QGraphicsItem.NoCache


def test_tall_plot_changes_idle_cache_at_mip_boundary(viewer_and_model):
    viewer, proxy, source, backend = viewer_and_model
    path = source._directory_path / 'plot.png'
    pixels = QImage(64, 16384, QImage.Format_RGB32)
    pixels.fill(QColor('green'))
    assert pixels.save(str(path))
    item = QStandardItem()
    item.setData(Image(path, (64, 16384)), Qt.UserRole)
    source.appendRow(item)
    viewer.load_image(proxy.index(2, 0))
    pump(lambda: viewer.current_image_item is not None and viewer._image_decode_owner is None)
    for scale, height in ((.2, 8192), (1., 16384), (.2, 8192)):
        viewer._apply_uniform_zoom_scale(scale, False)
        active = viewer.current_image_item
        assert active.pixmap().height() == height
        expected = (QGraphicsItem.DeviceCoordinateCache
                    if height > 8192 and backend == 'mpv_experimental' else QGraphicsItem.NoCache)
        assert active.cacheMode() == expected


@pytest.mark.parametrize('has_preview', [False, True])
def test_loading_placeholder_uses_selected_pixels_when_available(viewer_and_model, monkeypatch, has_preview):
    viewer, proxy, _, backend = viewer_and_model
    started, release = threading.Event(), threading.Event()
    decode = image_viewer.decode_image

    def blocked(path, cancelled):
        if path.name == '1.png':
            started.set()
            assert release.wait(5)
        return decode(path, cancelled)

    monkeypatch.setattr(image_viewer, 'decode_image', blocked)
    if has_preview:
        media = proxy.index(1, 0).data(Qt.UserRole)
        media.thumbnail_qimage = QImage(16, 64, QImage.Format_RGB32)
        media.thumbnail_qimage.fill(QColor('blue'))
    try:
        viewer.load_image(proxy.index(1, 0))
        assert started.wait(2)
        assert viewer._loading_image_item is not None
        item = viewer._loading_image_item
        assert item.cacheMode() == QGraphicsItem.NoCache
        assert item.pixmap().toImage().pixelColor(0, 0) == QColor('blue' if has_preview else 'red')
        preview_rect = item.sceneBoundingRect()
        if has_preview:
            viewport = viewer.view.viewport()
            point = viewport.rect().center() + QPoint(0, viewport.height() // 4)
            initial_scale = viewer.view.transform().m11()
            for _ in range(4):
                wheel = QWheelEvent(
                    QPointF(viewer.mapFromGlobal(viewport.mapToGlobal(point))),
                    QPointF(viewport.mapToGlobal(point)), QPoint(), QPoint(0, 120),
                    Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
                QApplication.sendEvent(viewer, wheel)
            zoomed = viewer.view.transform()
            focus = viewer.view.mapToScene(point)
            assert zoomed.m11() > initial_scale
        release.set()
        pump(lambda: viewer.current_image_item is not None and viewer._image_decode_owner is None)
        assert viewer.current_image_item.cacheMode() == QGraphicsItem.NoCache
        if has_preview:
            assert viewer.current_image_item.sceneBoundingRect() == preview_rect
            assert viewer.view.transform() == zoomed
            assert viewer.view.mapToScene(point) == focus
    finally:
        release.set()


@pytest.mark.parametrize(('start', 'delta', 'target', 'before', 'after'), [
    (.3, 120, .375, 2, 1),
    (.375, -120, .3, 1, 2),
])
def test_zoom_during_pan_restores_the_required_mipmap_on_release(
        viewer_and_model, start, delta, target, before, after):
    viewer, _, _, backend = viewer_and_model
    previous_zoom = MarkingItem.zoom_factor
    viewer._apply_uniform_zoom_scale(start, False)
    assert viewer._static_current_mip_divisor == before
    viewport = viewer.view.viewport()
    point = QPoint(10, 10)
    QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, point)
    assert viewer.view._manual_pan_active
    try:
        wheel = QWheelEvent(
            QPointF(point), QPointF(viewport.mapToGlobal(point)), QPoint(),
            QPoint(0, delta), Qt.LeftButton, Qt.NoModifier, Qt.NoScrollPhase, False,
        )
        QApplication.sendEvent(viewport, wheel)
        assert viewer.view.transform().m11() == pytest.approx(target)
        assert viewer._static_current_mip_divisor == before
        # A different viewer can change this shared marking value during a drag.
        MarkingItem.zoom_factor = .1
        QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, point)
        assert viewer._static_current_mip_divisor == after
        assert viewer.current_image_item.pixmap().size().toTuple() == (640 // after, 2560 // after)
        assert viewer.current_image_item.cacheMode() == QGraphicsItem.NoCache
    finally:
        MarkingItem.zoom_factor = previous_zoom


@pytest.mark.skipif(
    os.environ.get('TAGGUI_NATIVE_STILL_VISUAL') != '1',
    reason='Requires a visible desktop and an OpenGL viewport',
)
def test_oversized_image_keeps_visible_source_pixels_while_idle_and_panning(tmp_path, monkeypatch):
    read_setting = settings.value
    monkeypatch.setattr(
        settings, 'value',
        lambda key, *args, **kwargs: (
            'mpv_experimental' if key == 'video_playback_backend'
            else read_setting(key, *args, **kwargs)
        ),
    )
    source = QStandardItemModel()
    source._directory_path = tmp_path
    proxy = QSortFilterProxyModel()
    proxy.setSourceModel(source)
    viewer = image_viewer.ImageViewer(proxy)
    try:
        viewer.resize(256, 160)
        viewer.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        viewer.move(APP.primaryScreen().availableGeometry().topLeft() + QPoint(60, 60))
        viewer.show()
        viewer.raise_()
        viewer.activateWindow()
        assert QTest.qWaitForWindowExposed(viewer, 10000)
        viewport = viewer.view.viewport()

        def grab_visible_viewport():
            viewer.raise_()
            viewer.activateWindow()
            if sys.platform == 'win32':
                import ctypes
                ctypes.windll.user32.SetWindowPos(
                    int(viewer.winId()), -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
            QTest.qWait(250)
            screen = viewport.screen()
            screen_rect = screen.geometry()
            origin = viewport.mapToGlobal(QPoint(0, 0))
            shot = screen.grabWindow(
                0, origin.x() - screen_rect.x(), origin.y() - screen_rect.y(),
                viewport.width(), viewport.height(),
            ).toImage().convertToFormat(QImage.Format_RGBA8888)
            assert not shot.isNull()
            return shot

        # Establish that the desktop capture sees this viewport before testing
        # image pixels; a black or obscured desktop cannot validate rendering.
        previous_background = viewer.view.backgroundBrush()
        sentinel = QColor('#12c65a')
        viewer.view.setBackgroundBrush(sentinel)
        baseline = grab_visible_viewport()
        center = baseline.pixelColor(baseline.width() // 2, baseline.height() // 2)
        assert all(abs(a - b) < 5 for a, b in zip(center.getRgb()[:3], sentinel.getRgb()[:3])), (
            'Desktop capture does not show the test viewport'
        )
        viewer.view.setBackgroundBrush(previous_background)

        viewport.makeCurrent()
        texture_limit = int(viewport.context().functions().glGetIntegerv(0x0D33))
        viewport.doneCurrent()
        assert 0 < texture_limit <= 131072

        height = texture_limit * 4
        image = QImage(64, height, QImage.Format_RGB32)
        assert not image.isNull()
        image.fill(QColor('#b2b2b2'))
        painter = QPainter(image)
        for y in range(height // 2 - 64, height // 2 + 64, 2):
            for x in range(0, 64, 2):
                color = '#f8f8f8' if (x // 2 + y // 2) % 2 else '#182038'
                painter.fillRect(QRect(x, y, 2, 2), QColor(color))
        painter.end()
        path = tmp_path / 'oversized.png'
        assert image.save(str(path))
        del image
        item = QStandardItem()
        item.setData(Image(path, (64, height)), Qt.UserRole)
        source.appendRow(item)
        viewer.load_image(proxy.index(0, 0))
        pump(lambda: viewer.current_image_item is not None and viewer._image_decode_owner is None, seconds=20)
        viewer._apply_uniform_zoom_scale(4.0, False)
        assert viewer._static_current_mip_divisor == 1

        def assert_visible_pixels(*, smooth):
            shot = grab_visible_viewport()
            ratio = shot.width() / viewport.width()
            reference = QImage(shot.size(), QImage.Format_RGBA8888)
            reference.setDevicePixelRatio(ratio)
            reference.fill(QColor('black'))
            p = QPainter(reference)
            p.setRenderHint(QPainter.SmoothPixmapTransform, smooth)
            p.setWorldTransform(viewer.current_image_item.deviceTransform(viewer.view.viewportTransform()))
            p.drawPixmap(0, 0, viewer.current_image_item.pixmap())
            p.end()

            def pixels(img):
                return np.frombuffer(img.bits(), dtype=np.uint8).reshape(
                    img.height(), img.bytesPerLine())[:, :img.width() * 4].reshape(img.height(), img.width(), 4)[:, :, :3]

            expected, actual = pixels(reference), pixels(shot)
            assert expected.max() - expected.min() > 180, 'Expected image detail is absent'
            error = np.abs(expected.astype(np.int16) - actual.astype(np.int16)).mean()
            assert error < 2, (
                f'Visible image lost source detail (mean error {error:.2f}, '
                f'visible range {actual.min()}–{actual.max()})'
            )

        assert_visible_pixels(smooth=False)
        point = viewport.rect().center()
        before_pan = viewer.view.mapToScene(point)
        QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, point)
        assert viewer.view._manual_pan_active
        QTest.mouseMove(viewport, point + QPoint(8, 6), 30)
        after_pan = viewer.view.mapToScene(point)
        assert abs(after_pan.y() - before_pan.y()) > .5
        assert_visible_pixels(smooth=False)
        QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, point + QPoint(8, 6))
        assert not viewer.view._manual_pan_active
        assert_visible_pixels(smooth=False)
    finally:
        viewer._compare_prepare_task.drain()
        viewer._image_decode_task.drain()
        dispose_widget(viewer)
        APP.processEvents()
