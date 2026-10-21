"""Real still-image wall opening, resize gestures, settings and worker lifetime."""
import sys
import threading
import traceback

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMenu, QStatusBar, QToolTip
from shiboken6 import isValid

from qt_test_helpers import APP, dispose_widget, pump
from utils.image import Image
from utils.image_index_db import ImageIndexDB
from utils.latest_task import LatestTask
from utils.settings import DEFAULT_SETTINGS, settings
from widgets.main_window import MainWindow
from widgets.video_player import VideoPlayerWidget
from widgets.floating_wall_packing import valid_layout
from controllers import floating_wall_controller as controller_module


@pytest.fixture
def opened_wall(monkeypatch, tmp_path, request):
    monkeypatch.setenv('TAGGUI_FORCE_CLEAN_EXIT_ON_CLOSE', '0')
    monkeypatch.setattr(MainWindow, 'restore', lambda self: None)
    monkeypatch.setattr(VideoPlayerWidget, 'prewarm_gl_widget', lambda *args: None)
    errors = []
    monkeypatch.setattr(sys, 'excepthook', lambda *error: errors.append(error))
    keys = [key for key in DEFAULT_SETTINGS if key.startswith('floating_wall_')]
    keys += ['floating_viewer_rearrange_preserve_screen_order', 'floating_resize_preserve_aspect_by_default']
    for key in keys:
        settings.setValue(key, DEFAULT_SETTINGS[key])
    settings.setValue('floating_resize_preserve_aspect_by_default', True)
    settings.setValue('floating_wall_algorithm', getattr(request, 'param', 'Best fit'))
    images = []
    for index, size in enumerate([(320, 240), (180, 320), (300, 200), (240, 240)]):
        path = tmp_path / f'image-{index}.png'
        image = QImage(*size, QImage.Format_RGB32)
        image.fill(QColor(50 + index * 40, 90, 160))
        assert image.save(str(path))
        images.append(Image(path, size, thumbnail_qimage=image))
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
    windows = []
    try:
        host.show()
        windows = host.open_selection_masonry_wall([proxy.index(i, 0) for i in range(len(images))])
        assert len(windows) == len(images)
        pump(lambda: all(w.viewer.current_media is image and w.viewer.scene.sceneRect().width() > 0
                         for w, image in zip(windows, images)), seconds=10)
        QTest.qWait(180)
        yield host, windows
    finally:
        host._wall_layout.cancel()
        for window in windows:
            if not isValid(window):
                continue
            for task in window.viewer.findChildren(LatestTask):
                task.drain()
            window.viewer.close()
            dispose_widget(window)
        for task in host.findChildren(LatestTask):
            task.drain()
        source.shutdown_background_workers()
        executor = host.image_list.list_view._masonry_executor
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
        QTest.qWait(180)
        dispose_widget(host)
        APP.processEvents()
        assert source is proxy.sourceModel()
        assert not errors, [''.join(traceback.format_exception(*error)) for error in errors]


def resize_gesture(window, delta=QPoint(-35, -25), modifiers=Qt.KeyboardModifier.NoModifier):
    target = window.viewer.view.viewport()
    point = target.rect().bottomRight() - QPoint(2, 2)
    QTest.mousePress(target, Qt.MouseButton.LeftButton, modifiers, point)
    assert window._resize_active, 'The real edge/corner resize handler was not entered'
    QTest.mouseMove(target, point + delta)
    QTest.mouseRelease(target, Qt.MouseButton.LeftButton, modifiers, point + delta)
    assert not window._resize_active


def finish_reflow(controller):
    pump(lambda: controller._pending is None and controller.worker._active is None, seconds=10)


@pytest.mark.parametrize('opened_wall', ['Masonry', 'MaxRects'], indirect=True)
def test_real_opening_uses_the_selected_algorithm(opened_wall):
    host, windows = opened_wall
    assert host._wall_layout.last_result.algorithm == settings.value('floating_wall_algorithm')
    assert valid_layout([w.geometry() for w in windows], windows[0].screen().availableGeometry(), 6)
    for window in windows:
        width, height = window.viewer.current_media.dimensions
        assert abs(window.width() - window.height() * width / height) <= max(1, width / height)


def test_real_open_resize_reflow_keeps_three_chosen_sizes_without_media_reads(opened_wall, monkeypatch):
    host, windows = opened_wall
    controller = host._wall_layout
    for window in windows:
        state = host._snapshot_window_arrangement_state(window)
        assert len(state['viewer_states']) == 1
        assert state['viewer_states'][0][0] is window.viewer
    source = host.image_list_model
    original_data = source.data

    def guarded_data(*args, **kwargs):
        assert not controller._applying, 'Geometry-only reflow requested media from the model'
        return original_data(*args, **kwargs)

    monkeypatch.setattr(source, 'data', guarded_data)
    chosen = {}
    for window in windows[:3]:
        previous = controller.last_result
        resize_gesture(window)
        chosen[window] = window.size()
        finish_reflow(controller)
        assert controller.last_result is not previous
        assert all(w.size() == size for w, size in chosen.items())
        bounds = window.screen().availableGeometry().adjusted(6, 6, -6, -6)
        assert valid_layout([w.geometry() for w in windows], bounds, 6)
    assert host._selection_wall_controls_active
    assert all(w._review_slots_enabled for w in windows)


@pytest.mark.parametrize('mode', ['alt', 'manual', 'disabled'])
def test_user_can_resize_without_reflow(opened_wall, mode):
    host, windows = opened_wall
    controller = host._wall_layout
    if mode == 'manual':
        controller.manual_action.setChecked(True)
    elif mode == 'disabled':
        settings.setValue('floating_wall_reflow_after_resize', False)
    before = [QRect(w.geometry()) for w in windows]
    resize_gesture(windows[0], modifiers=Qt.AltModifier if mode == 'alt' else Qt.NoModifier)
    finish_reflow(controller)
    assert windows[0].geometry().size() != before[0].size()
    assert [w.geometry() for w in windows[1:]] == before[1:]
    assert windows[0]._wall_fixed_size == (windows[0].width(), windows[0].height())


def test_position_only_reflow_preserves_every_size(opened_wall):
    host, windows = opened_wall
    settings.setValue('floating_wall_automatic_sizing', False)
    # Fixed sizes must fit; reduce the wall first using bypass gestures.
    for window in windows:
        resize_gesture(window, QPoint(-45, -35), Qt.AltModifier)
    sizes = [w.size() for w in windows]
    host._wall_layout.request_reflow(force=True)
    finish_reflow(host._wall_layout)
    assert [w.size() for w in windows] == sizes
    assert valid_layout([w.geometry() for w in windows], windows[0].screen().availableGeometry(), 6)


def test_preservation_can_be_disabled_and_reset_releases_all_sizes(opened_wall):
    host, windows = opened_wall
    controller = host._wall_layout
    resize_gesture(windows[0], QPoint(-55, -45), Qt.AltModifier)
    original_manual_size = windows[0].size()
    settings.setValue('floating_wall_preserve_manual_sizes', False)
    assert controller._fixed_size(windows[0]) is None
    controller.request_reflow(force=True)
    finish_reflow(controller)
    assert windows[0].size() != original_manual_size
    controller._keep_size(windows[1], True)
    controller.manual_action.setChecked(True)
    controller.request_reflow(force=True, reset_sizes=True)
    finish_reflow(controller)
    assert all(controller._fixed_size(w) is None for w in windows)
    assert controller.manual_action.isChecked()
    assert valid_layout([w.geometry() for w in windows], windows[0].screen().availableGeometry(), 6)


def test_enlarged_manual_window_keeps_its_size_while_other_windows_fit(opened_wall):
    host, windows = opened_wall
    settings.setValue('floating_viewer_rearrange_preserve_screen_order', False)
    settings.setValue('floating_wall_algorithm', 'MaxRects')
    before = [w.size() for w in windows]
    resize_gesture(windows[0], QPoint(45, 35))
    enlarged = windows[0].size()
    assert enlarged.width() > before[0].width()
    finish_reflow(host._wall_layout)
    assert windows[0].size() == enlarged
    assert any(w.size() != size for w, size in zip(windows[1:], before[1:]))
    assert valid_layout([w.geometry() for w in windows], windows[0].screen().availableGeometry(), 6)


@pytest.mark.parametrize('mode', ['alt', 'manual'])
def test_manual_drag_moves_only_its_window_and_suppresses_compare_merge(opened_wall, mode):
    host, windows = opened_wall
    controller = host._wall_layout
    if mode == 'manual':
        controller.manual_action.setChecked(True)
    before = [QRect(w.geometry()) for w in windows]
    started = []
    windows[0].compare_drag_started.connect(lambda *args: started.append(args))
    viewport = windows[0].viewer.view.viewport()
    point = viewport.rect().center()
    modifiers = Qt.AltModifier if mode == 'alt' else Qt.NoModifier
    QTest.mousePress(viewport, Qt.MiddleButton, modifiers, point)
    assert windows[0]._window_drag_active
    QTest.mouseMove(viewport, point + QPoint(25, 15))
    QTest.mouseRelease(viewport, Qt.MiddleButton, modifiers, point + QPoint(25, 15))
    finish_reflow(controller)
    assert windows[0].pos() != before[0].topLeft()
    assert [w.geometry() for w in windows[1:]] == before[1:]
    assert not started


def test_custom_zoom_is_restored_with_proportional_scale_on_resized_siblings(opened_wall):
    host, windows = opened_wall
    sibling = windows[-1].viewer
    sibling._apply_uniform_zoom_scale(2.0, zoom_to_fit_state=False,
                                     focus_scene_pos=sibling.scene.sceneRect().center())
    state = host._snapshot_viewer_arrangement_state(sibling)
    resize_gesture(windows[0], QPoint(-80, -50))
    finish_reflow(host._wall_layout)
    viewport = sibling.view.viewport()
    expected = state['scale'] * min(viewport.width() / state['viewport_width'],
                                     viewport.height() / state['viewport_height'])
    assert not sibling.is_zoom_to_fit
    assert sibling.view.transform().m11() == pytest.approx(expected)


def test_live_menu_keeps_defaults_and_session_override_separate(opened_wall):
    host, windows = opened_wall
    controller = host._wall_layout
    controller.manual_action.setChecked(True)
    menu = QMenu(host)
    try:
        submenu = controller.add_menu(menu, windows[0])
        actions = {action.text(): action for action in submenu.actions()}
        actions['Automatically size other windows'].trigger()
        assert not settings.value('floating_wall_automatic_sizing', type=bool)
        settings.setValue('floating_wall_automatic_sizing', True)
        assert actions['Automatically size other windows'].isChecked()
        algorithms = actions['Packing algorithm (this session)'].menu()
        next(a for a in algorithms.actions() if a.text() == 'Masonry').trigger()
        assert controller.algorithm == 'Masonry'
        assert settings.value('floating_wall_algorithm') == 'Best fit'
        assert len([action for action in algorithms.actions() if action.isChecked()]) == 1
        actions["Keep this window's size"].trigger()
        assert controller._fixed_size(windows[0]) == (windows[0].width(), windows[0].height())
        assert all(controller._fixed_size(w) is None for w in windows[1:])
        actions["Keep this window's size"].trigger()
        assert controller._fixed_size(windows[0]) is None
        settings.setValue('floating_wall_manual_shortcut', 'Ctrl+Alt+J')
        assert controller.manual_action.shortcut().toString() == 'Ctrl+Alt+J'
    finally:
        dispose_widget(menu)


def test_manual_shortcut_works_from_a_floating_viewer(opened_wall):
    host, windows = opened_wall
    windows[-1].activateWindow()
    APP.processEvents()
    QTest.keyClick(windows[-1], Qt.Key_M, Qt.ControlModifier | Qt.AltModifier)
    assert host._wall_layout.manual_action.isChecked()
    QTest.keyClick(windows[-1], Qt.Key_M, Qt.ControlModifier | Qt.AltModifier)
    assert not host._wall_layout.manual_action.isChecked()


def test_wall_settings_controls_persist_their_actual_values():
    from dialogs.settings_dialog import SettingsDialog
    from PySide6.QtGui import QKeySequence
    settings.setValue('floating_wall_algorithm', 'Best fit')
    group = SettingsDialog._create_wall_layout_settings(None)
    try:
        grid = group.layout()
        grid.itemAtPosition(0, 1).widget().setCurrentText('MaxRects')
        assert settings.value('floating_wall_algorithm') == 'MaxRects'
        for row, key in ((1, 'floating_wall_reflow_after_resize'),
                         (2, 'floating_wall_automatic_sizing'),
                         (3, 'floating_wall_preserve_manual_sizes')):
            control = grid.itemAtPosition(row, 1).widget()
            control.setChecked(False)
            assert not settings.value(key, type=bool)
            control.setChecked(True)
            assert settings.value(key, type=bool)
        shortcut = grid.itemAtPosition(4, 1).widget()
        shortcut.setKeySequence(QKeySequence('Ctrl+Alt+J'))
        shortcut.editingFinished.emit()
        assert settings.value('floating_wall_manual_shortcut') == 'Ctrl+Alt+J'
    finally:
        dispose_widget(group)


def test_alt_is_latched_even_when_released_before_the_mouse(opened_wall):
    host, windows = opened_wall
    window = windows[0]
    others = [QRect(w.geometry()) for w in windows[1:]]
    target = window.viewer.view.viewport()
    point = target.rect().bottomRight() - QPoint(2, 2)
    QTest.mousePress(target, Qt.LeftButton, Qt.NoModifier, point)
    QTest.keyPress(target, Qt.Key_Alt)
    QTest.mouseMove(target, point - QPoint(40, 30))
    QTest.keyRelease(target, Qt.Key_Alt)
    QTest.mouseRelease(target, Qt.LeftButton, Qt.NoModifier, point - QPoint(40, 30))
    finish_reflow(host._wall_layout)
    assert window._wall_skip_reflow
    assert [w.geometry() for w in windows[1:]] == others


@pytest.mark.parametrize('default_preserve, shift', [(False, False), (False, True), (True, False), (True, True)])
def test_aspect_setting_and_shift_override_remain_independent_of_alt(opened_wall, monkeypatch, default_preserve, shift):
    _, windows = opened_wall
    settings.setValue('floating_resize_preserve_aspect_by_default', default_preserve)
    window = windows[0]
    ratio = window.width() / window.height()
    modifiers = Qt.AltModifier | (Qt.ShiftModifier if shift else Qt.NoModifier)
    # QTest.mouseMove does not maintain physical keyboard state. Supply that
    # input at Qt's modifier boundary while exercising the real resize events.
    from PySide6.QtWidgets import QApplication
    monkeypatch.setattr(QApplication, 'keyboardModifiers', lambda: modifiers)
    resize_gesture(window, QPoint(-50, -5), modifiers)
    error = abs(window.width() - window.height() * ratio)
    assert (error <= max(1, ratio)) == (default_preserve != shift)


def test_infeasible_sizes_do_not_change_siblings_or_undo_manual_size(opened_wall):
    host, windows = opened_wall
    assert host.findChild(QStatusBar) is None
    central_geometry = QRect(host.centralWidget().geometry())
    source = windows[0]
    available = source.screen().availableGeometry()
    # Each of the two chosen sizes fits individually, but their combined area
    # exceeds the screen. This is the user's multi-resize failure case.
    for window in windows[:2]:
        window.resize(int(available.width() * .75), int(available.height() * .75))
        host._wall_layout.resize_finished(window, True)
    before = [QRect(w.geometry()) for w in windows]
    host._wall_layout.resize_finished(source, False)
    finish_reflow(host._wall_layout)
    assert [w.geometry() for w in windows] == before
    assert 'do not fit' in QToolTip.text()
    assert host.findChild(QStatusBar) is None
    assert host.centralWidget().geometry() == central_geometry
    QTest.qWait(5200)
    assert not QToolTip.isVisible()
    assert host.findChild(QStatusBar) is None
    assert host.centralWidget().geometry() == central_geometry
    QToolTip.hideText()


def test_manual_feedback_and_explicit_arrange_failure_never_add_a_status_row(opened_wall):
    host, windows = opened_wall
    assert host.findChild(QStatusBar) is None
    central_geometry = QRect(host.centralWidget().geometry())
    host._wall_layout.manual_action.setChecked(True)
    assert 'Manual wall layout' in QToolTip.text()
    host._wall_layout.manual_action.setChecked(False)
    windows[0].resize(windows[0].screen().availableGeometry().width() + 100, windows[0].height())
    host._wall_layout.resize_finished(windows[0], True)
    assert host.arrange_floating_windows_as_masonry() == []
    assert 'do not fit' in QToolTip.text()
    assert host.findChild(QStatusBar) is None
    assert host.centralWidget().geometry() == central_geometry
    QToolTip.hideText()


@pytest.mark.parametrize('interrupt', ['manual', 'move', 'close'])
def test_late_worker_result_cannot_override_manual_changes_or_deleted_window(opened_wall, monkeypatch, interrupt):
    host, windows = opened_wall
    controller = host._wall_layout
    started, release = threading.Event(), threading.Event()
    original = controller_module._calculate

    def held(payload, cancelled):
        started.set()
        assert release.wait(5)
        return original(payload, cancelled)

    monkeypatch.setattr(controller_module, '_calculate', held)
    controller.request_reflow(force=True)
    pump(started.is_set)
    try:
        if interrupt == 'manual':
            controller.manual_action.setChecked(True)
        elif interrupt == 'move':
            windows[0].move(windows[0].pos() + QPoint(20, 10))
        else:
            for task in windows[0].viewer.findChildren(LatestTask):
                task.drain()
            windows[0].viewer.close()
            dispose_widget(windows[0])
        survivors = [w for w in windows if isValid(w)]
        previous = [QRect(w.geometry()) for w in survivors]
    finally:
        release.set()
    finish_reflow(controller)
    assert [w.geometry() for w in survivors] == previous
