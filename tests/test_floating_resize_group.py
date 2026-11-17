"""Synchronized border input through real viewer opening and wall reflow."""
import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QGraphicsView, QPushButton

from qt_test_helpers import APP, dispose_widget, pump
from test_floating_wall_reflow import opened_wall, finish_reflow, resize_gesture
from utils.settings import settings
from utils.latest_task import LatestTask
from widgets.floating_wall_packing import valid_layout


def begin_resize(window, zone='bottom_right', modifiers=Qt.ControlModifier):
    rect = window.rect()
    x = 3 if 'left' in zone else rect.right()-3 if 'right' in zone else rect.center().x()
    y = 3 if 'top' in zone else rect.bottom()-3 if 'bottom' in zone else rect.center().y()
    target = window.viewer.view.viewport()
    position = window.mapToGlobal(QPoint(x, y))
    QTest.mousePress(target, Qt.LeftButton, modifiers, target.mapFromGlobal(position))
    assert window._resize_active and window._resize_group_active
    assert window._wall_controller().anchors.drag is None
    return position


def move_resize(window, position):
    QTest.mouseMove(window, window.mapFromGlobal(position))


def release_resize(window, position, modifiers=Qt.ControlModifier):
    QTest.mouseRelease(window, Qt.LeftButton, modifiers, window.mapFromGlobal(position))
    assert not window._resize_active and not window._resize_group_active


@pytest.mark.parametrize('zone', ['left', 'right', 'top', 'bottom',
                                'top_left', 'top_right', 'bottom_left', 'bottom_right'])
def test_all_borders_match_sizes_live_and_repack_once(opened_wall, zone, monkeypatch):
    host, windows = opened_wall
    wall = host._wall_layout
    settings.setValue('floating_resize_preserve_aspect_by_default', False)
    settings.setValue('floating_wall_preserve_manual_sizes', False)
    for index, window in enumerate(windows):
        window.setGeometry(25+index*175, 30, 150+index*10, 120+index*5)
    # Include a sibling already at the target size; it must remain fixed too.
    source = windows[0]
    calls = []
    original_request = wall.request_reflow
    monkeypatch.setattr(wall, 'request_reflow', lambda *args, **kwargs:
                        (calls.append(kwargs), original_request(*args, **kwargs))[-1])
    dx = 15 if 'left' in zone else -15 if 'right' in zone else 0
    dy = 10 if 'top' in zone else -10 if 'bottom' in zone else 0
    expected = source.size()
    expected.setWidth(expected.width()-abs(dx))
    expected.setHeight(expected.height()-abs(dy))
    windows[-1].resize(expected)
    before = [QRect(w.geometry()) for w in windows]
    position = begin_resize(source, zone)
    destination = position + QPoint(dx, dy)
    move_resize(source, destination)
    assert all(w.size() == expected for w in windows)
    assert [w.pos() for w in windows[1:]] == [r.topLeft() for r in before[1:]]
    assert not wall.resize_preview.timer.isActive()
    assert not wall.resize_preview.overlay.isVisible()
    release_resize(source, destination)
    finish_reflow(wall)
    assert len(calls) == 1
    assert all(w.size() == expected for w in windows)
    assert valid_layout([w.geometry() for w in windows], source.screen().availableGeometry(), 6)


@pytest.mark.parametrize('default_preserve,shift', [(False, False), (False, True),
                                                 (True, False), (True, True)])
def test_aspect_toggle_and_minimum_size_apply_to_whole_group(opened_wall, default_preserve, shift, monkeypatch):
    host, windows = opened_wall
    settings.setValue('floating_wall_reflow_after_resize', False)
    settings.setValue('floating_resize_preserve_aspect_by_default', default_preserve)
    windows[0].resize(240, 160)
    windows[1].setMinimumSize(90, 75)
    modifiers = Qt.ControlModifier | (Qt.ShiftModifier if shift else Qt.NoModifier)
    # QTest.mouseMove cannot carry held modifiers. Supply the same keyboard
    # query used by the existing aspect toggle; border input remains real Qt input.
    monkeypatch.setattr(QApplication, 'keyboardModifiers', lambda: modifiers)
    position = begin_resize(windows[0], modifiers=modifiers)
    destination = position-QPoint(60, 15)
    move_resize(windows[0], destination)
    expected = windows[0].size()
    if default_preserve != shift:
        assert expected.width() == 180 and expected.height() == 120
    else:
        assert expected.width() == 180 and expected.height() == 145
    assert all(w.size() == expected for w in windows)
    destination = position-QPoint(400, 400)
    move_resize(windows[0], destination)
    assert all(w.size() == windows[0].size() for w in windows)
    assert all(w.width() >= 90 and w.height() >= 75 for w in windows)
    release_resize(windows[0], destination, modifiers)


def test_regular_spawn_drives_wall_and_normal_resize_is_independent_afterward(opened_wall):
    host, windows = opened_wall
    settings.setValue('floating_resize_preserve_aspect_by_default', False)
    source = host.spawn_floating_viewer_at(host.proxy_image_list_model.index(0, 0),
                                         geometry_override=QRect(40, 40, 220, 160))
    windows.append(source)
    pump(lambda: source.viewer.current_media is not None and source.viewer.scene.sceneRect().width() > 0)
    assert not getattr(source, '_selection_masonry_wall_window', False)
    position = begin_resize(source)
    destination = position-QPoint(80, 50)
    move_resize(source, destination)
    assert all(w.size() == source.size() for w in windows)
    release_resize(source, destination)
    finish_reflow(host._wall_layout)
    assert all(w.size() == source.size() for w in windows)
    before = [QRect(w.geometry()) for w in windows[:-1]]
    resize_gesture(source, QPoint(20, 15))
    assert [w.geometry() for w in windows[:-1]] == before
    assert source.size() != before[0].size()
    # Ctrl inside the wall still pins, including after a group and regular resize.
    target = windows[0].viewer.view.viewport()
    point = target.rect().center()
    QTest.mousePress(target, Qt.LeftButton, Qt.ControlModifier, point)
    assert host._wall_layout.anchors.drag is not None
    QTest.keyClick(target, Qt.Key_Escape)
    QTest.mouseRelease(target, Qt.LeftButton, Qt.ControlModifier, point)
    # Returning to ordinary wall resize must restore ghosts and release-time layout.
    wall_source = windows[0]
    target = wall_source.viewer.view.viewport()
    point = target.rect().bottomRight()-QPoint(3, 3)
    before_siblings = [QRect(w.geometry()) for w in windows[1:-1]]
    QTest.mousePress(target, Qt.LeftButton, Qt.NoModifier, point)
    assert wall_source._resize_active and not getattr(wall_source, '_resize_group_active', False)
    destination = target.mapToGlobal(point)-QPoint(20, 15)
    move_resize(wall_source, destination)
    pump(lambda: host._wall_layout.resize_preview.overlay.isVisible(), seconds=10)
    assert [w.geometry() for w in windows[1:-1]] == before_siblings
    chosen = wall_source.size()
    QTest.mouseRelease(wall_source, Qt.LeftButton, Qt.NoModifier, wall_source.mapFromGlobal(destination))
    finish_reflow(host._wall_layout)
    assert wall_source.size() == chosen
    assert not host._wall_layout.resize_preview.overlay.isVisible()


def test_regular_viewers_resize_together_and_hidden_windows_are_untouched(opened_wall):
    host, windows = opened_wall
    settings.setValue('floating_resize_preserve_aspect_by_default', False)
    before = [QRect(w.geometry()) for w in windows]
    for window in windows:
        window.hide()
    regular = []
    for index in range(3):
        window = host.spawn_floating_viewer_at(host.proxy_image_list_model.index(index, 0),
                                             geometry_override=QRect(20+index*200, 30, 180+index*20, 150))
        regular.append(window)
        windows.append(window)
    pump(lambda: all(w.viewer.current_media is not None and w.viewer.scene.sceneRect().width() > 0
                     for w in regular))
    position = begin_resize(regular[0])
    destination = position-QPoint(60, 50)
    move_resize(regular[0], destination)
    # Releasing Ctrl before the button must not split the group.
    release_resize(regular[0], destination, Qt.NoModifier)
    assert all(w.size() == regular[0].size() for w in regular)
    assert [w.geometry() for w in windows[:len(before)]] == before
    assert host._wall_layout._pending is None


@pytest.mark.parametrize('mode', ['alt', 'manual'])
def test_group_resize_keeps_positions_when_wall_arrangement_is_bypassed(opened_wall, mode):
    host, windows = opened_wall
    if mode == 'manual':
        host._wall_layout.auto_arrange_action.setChecked(False)
    before = [w.pos() for w in windows]
    modifiers = Qt.ControlModifier | (Qt.AltModifier if mode == 'alt' else Qt.NoModifier)
    position = begin_resize(windows[0], modifiers=modifiers)
    move_resize(windows[0], position-QPoint(50, 30))
    release_resize(windows[0], position-QPoint(50, 30), modifiers)
    assert all(w.size() == windows[0].size() for w in windows)
    assert [w.pos() for w in windows] == before
    assert host._wall_layout._pending is None
    assert all(w._wall_fixed_size == (w.width(), w.height()) for w in windows)


@pytest.mark.parametrize('cancel', ['escape', 'deactivate', 'close'])
def test_cancel_restores_group_geometry_and_manual_zoom(opened_wall, cancel):
    host, windows = opened_wall
    windows[1].viewer._apply_uniform_zoom_scale(2, zoom_to_fit_state=False)
    before = [QRect(w.geometry()) for w in windows]
    scale = windows[1].viewer.view.transform().m11()
    windows[0].viewer.view.setResizeAnchor(QGraphicsView.AnchorViewCenter)
    position = begin_resize(windows[0])
    move_resize(windows[0], position-QPoint(50, 30))
    if cancel == 'escape':
        QTest.keyClick(windows[0], Qt.Key_Escape)
    elif cancel == 'deactivate':
        from PySide6.QtCore import QEvent
        APP.sendEvent(APP, QEvent(QEvent.ApplicationDeactivate))
    else:
        windows[0].close()
    assert host._wall_layout.resize_input.active is None
    assert not host._wall_layout.resize_input.group.entries
    assert [w.geometry() for w in windows] == before
    assert windows[1].viewer.view.transform().m11() == pytest.approx(scale)
    assert windows[0].viewer.view.resizeAnchor() == QGraphicsView.AnchorViewCenter
    assert host._wall_layout._pending is None
    QTest.mouseRelease(windows[0], Qt.LeftButton, Qt.NoModifier)


def test_ctrl_border_respects_top_level_dialog_and_closed_sibling(opened_wall):
    host, windows = opened_wall
    source = windows[0]
    dialog = QDialog(source)
    button = QPushButton('Independent', dialog)
    dialog.setGeometry(source.geometry())
    button.setGeometry(dialog.width()-60, dialog.height()-30, 60, 30)
    dialog.show()
    clicks = []
    button.clicked.connect(lambda: clicks.append(True))
    try:
        QTest.mouseClick(button, Qt.LeftButton, Qt.ControlModifier, button.rect().bottomRight()-QPoint(2, 2))
        assert clicks == [True]
        assert host._wall_layout.resize_input.active is None
    finally:
        dispose_widget(dialog)
    position = begin_resize(source)
    for task in windows[-1].viewer.findChildren(LatestTask):
        task.drain()
    windows[-1].viewer.close()
    dispose_widget(windows.pop())
    move_resize(source, position-QPoint(50, 30))
    release_resize(source, position-QPoint(50, 30))
    finish_reflow(host._wall_layout)
    assert all(w.size() == source.size() for w in windows)
