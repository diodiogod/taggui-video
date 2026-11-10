"""Double-click zoom through the main and floating viewer input paths."""

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QPointF, QSettings, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor, QImage, QStandardItem, QStandardItemModel, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGroupBox

from qt_test_helpers import APP, dispose_widget, pump
from utils.image import Image
from utils.settings import DEFAULT_SETTINGS, settings
from widgets.floating_viewer_window import FloatingViewerWindow
from widgets.image_viewer import ImageViewer


ZOOM_CENTER_KEY = 'viewer_double_click_zoom_center_on_click'


@pytest.fixture(params=['main', 'floating'])
def opened_viewer(tmp_path, request):
    keys = (ZOOM_CENTER_KEY, 'video_playback_backend')
    previous = {key: (settings.contains(key), settings.value(key)) for key in keys}
    settings.remove(ZOOM_CENTER_KEY)
    # A regular QWidget viewport allows mouse input testing on Qt's offscreen platform.
    settings.setValue('video_playback_backend', 'vlc_experimental')

    source = QStandardItemModel()
    source._directory_path = tmp_path
    path = tmp_path / 'detail.png'
    pixels = QImage(1200, 900, QImage.Format_RGB32)
    pixels.fill(QColor('cornflowerblue'))
    assert pixels.save(str(path))
    media = Image(path, (1200, 900))
    item = QStandardItem()
    item.setData(media, Qt.UserRole)
    source.appendRow(item)
    proxy = QSortFilterProxyModel()
    proxy.setSourceModel(source)
    viewer = ImageViewer(proxy, is_spawned_viewer=request.param == 'floating')
    host = (FloatingViewerWindow(viewer, 'Detail zoom')
            if request.param == 'floating' else viewer)
    host.resize(640, 480)
    host.show()
    try:
        viewer.load_image(proxy.index(0, 0))
        pump(lambda: viewer.current_image_item is not None
             and viewer._image_decode_owner is None)
        APP.processEvents()
        yield viewer, proxy, source, media
    finally:
        viewer._compare_prepare_task.drain()
        viewer._image_decode_task.drain()
        if host is not viewer:
            viewer.close()
        dispose_widget(host)
        APP.processEvents()
        for key, (existed, value) in previous.items():
            if existed:
                settings.setValue(key, value)
            else:
                settings.remove(key)


def _double_click(viewer, point):
    QTest.mouseDClick(viewer.view.viewport(), Qt.LeftButton, Qt.NoModifier, point)
    APP.processEvents()


def _wheel_in(viewer, point):
    viewport = viewer.view.viewport()
    event = QWheelEvent(
        QPointF(point), QPointF(viewport.mapToGlobal(point)), QPoint(), QPoint(0, 120),
        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False,
    )
    QApplication.sendEvent(viewport, event)
    APP.processEvents()


def _assert_detail_at(viewer, scene_pos, expected_view_pos):
    actual = viewer.view.mapFromScene(scene_pos)
    assert abs(actual.x() - expected_view_pos.x()) <= 2
    assert abs(actual.y() - expected_view_pos.y()) <= 2


@pytest.mark.parametrize('center_detail', [True, False])
def test_remembered_zoom_places_the_clicked_detail(opened_viewer, center_detail):
    viewer, _, _, _ = opened_viewer
    if not center_detail:
        settings.setValue(ZOOM_CENTER_KEY, False)
    else:
        assert not settings.contains(ZOOM_CENTER_KEY)
        assert DEFAULT_SETTINGS[ZOOM_CENTER_KEY] is True

    viewport = viewer.view.viewport()
    center = viewport.rect().center()
    for _ in range(4):
        _wheel_in(viewer, center)
    remembered_scale = viewer.view.transform().m11()
    _double_click(viewer, center)
    assert viewer.is_zoom_to_fit
    assert viewer._floating_double_click_return_scale == pytest.approx(remembered_scale)

    # Double-click away from the center but far enough from the image edges to
    # allow both center and cursor-anchored positioning at the remembered zoom.
    point = QPoint(viewport.width() * 3 // 5, viewport.height() * 2 // 5)
    scene_pos = viewer.view.mapToScene(point)
    _double_click(viewer, point)
    assert viewer.view.transform().m11() == pytest.approx(remembered_scale)
    _assert_detail_at(viewer, scene_pos, center if center_detail else point)

    # Toggling back out and returning again keeps the original manual zoom.
    _double_click(viewer, center)
    assert viewer.is_zoom_to_fit
    another_point = QPoint(viewport.width() * 2 // 5, viewport.height() * 3 // 5)
    scene_pos = viewer.view.mapToScene(another_point)
    _double_click(viewer, another_point)
    assert viewer.view.transform().m11() == pytest.approx(remembered_scale)
    _assert_detail_at(viewer, scene_pos, center if center_detail else another_point)


def test_fallback_zoom_uses_live_setting_after_model_refresh(opened_viewer):
    viewer, proxy, source, media = opened_viewer
    source.beginResetModel()
    source.endResetModel()
    viewer.load_image(proxy.index(0, 0))
    pump(lambda: viewer.current_media is media and viewer.current_image_item is not None
         and viewer._image_decode_owner is None)

    viewport = viewer.view.viewport()
    center = viewport.rect().center()
    point = QPoint(viewport.width() * 3 // 5, viewport.height() * 2 // 5)
    scene_pos = viewer.view.mapToScene(point)
    _double_click(viewer, point)
    assert viewer.is_content_pannable()
    _assert_detail_at(viewer, scene_pos, center)

    _double_click(viewer, center)
    assert viewer.is_zoom_to_fit
    settings.setValue(ZOOM_CENTER_KEY, False)
    scene_pos = viewer.view.mapToScene(point)
    _double_click(viewer, point)
    _assert_detail_at(viewer, scene_pos, point)

    # Wheel zoom stays cursor-anchored regardless of the double-click setting.
    settings.setValue(ZOOM_CENTER_KEY, True)
    wheel_point = QPoint(viewport.width() * 11 // 20, viewport.height() * 9 // 20)
    scene_pos = viewer.view.mapToScene(wheel_point)
    _wheel_in(viewer, wheel_point)
    _assert_detail_at(viewer, scene_pos, wheel_point)


@pytest.mark.parametrize('dimensions', [(1200, 600), (600, 900)])
@pytest.mark.parametrize('center_detail', [True, False])
def test_fill_zoom_positions_detail_on_the_pannable_axis(
        opened_viewer, dimensions, center_detail):
    viewer, proxy, source, _ = opened_viewer
    settings.setValue(ZOOM_CENTER_KEY, center_detail)
    path = source._directory_path / 'other-aspect.png'
    pixels = QImage(*dimensions, QImage.Format_RGB32)
    pixels.fill(QColor('cornflowerblue'))
    assert pixels.save(str(path))
    media = Image(path, dimensions)
    item = QStandardItem()
    item.setData(media, Qt.UserRole)
    source.appendRow(item)
    viewer.load_image(proxy.index(1, 0))
    pump(lambda: viewer.current_media is media and viewer._image_decode_owner is None)

    viewport = viewer.view.viewport()
    center = viewport.rect().center()
    wide = dimensions[0] > dimensions[1]
    point = (QPoint(viewport.width() * 3 // 5, center.y()) if wide else
             QPoint(center.x(), viewport.height() * 3 // 5))
    scene_pos = viewer.view.mapToScene(point)
    old_scale = viewer.view.transform().m11()
    _double_click(viewer, point)
    assert viewer.view.transform().m11() > old_scale
    actual = viewer.view.mapFromScene(scene_pos)
    expected = center if center_detail else point
    assert abs((actual.x() - expected.x()) if wide else (actual.y() - expected.y())) <= 2


def test_centering_stops_at_image_edges(opened_viewer):
    viewer, _, _, _ = opened_viewer
    viewport = viewer.view.viewport()
    point = QPoint(viewport.width() // 20, viewport.height() // 20)
    scene_pos = viewer.view.mapToScene(point)
    _double_click(viewer, point)
    image_rect = viewer.view.mapFromScene(viewer.scene.sceneRect()).boundingRect()
    assert image_rect.contains(viewport.rect())
    assert viewport.rect().contains(viewer.view.mapFromScene(scene_pos))
    assert viewer.view.mapFromScene(scene_pos) != viewport.rect().center()


def test_advanced_checkbox_persists_and_restores():
    from dialogs.settings_dialog import SettingsDialog

    existed, previous = settings.contains(ZOOM_CENTER_KEY), settings.value(ZOOM_CENTER_KEY)
    settings.remove(ZOOM_CENTER_KEY)
    dialogs = []
    try:
        for expected in (True, False):
            dialog = SettingsDialog(None)
            dialogs.append(dialog)
            group = next(group for group in dialog.findChildren(QGroupBox)
                         if group.title() == 'Image List Display')
            checkbox = group.layout().itemAtPosition(7, 1).widget()
            assert checkbox.isChecked() is expected
            if expected:
                checkbox.setChecked(False)
                settings.sync()
                reloaded = QSettings(settings.fileName(), QSettings.IniFormat)
                assert Path(reloaded.fileName()).resolve() == Path(settings.fileName()).resolve()
                assert reloaded.value(ZOOM_CENTER_KEY, type=bool) is False
    finally:
        for dialog in dialogs:
            dispose_widget(dialog)
        if existed:
            settings.setValue(ZOOM_CENTER_KEY, previous)
        else:
            settings.remove(ZOOM_CENTER_KEY)
