"""User-facing wall menu state, reset scopes and focused settings lifecycle."""
import os
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMenu
from shiboken6 import isValid

from qt_test_helpers import APP, dispose_widget, pump
from test_floating_wall_reflow import opened_wall, finish_reflow
from utils.settings import settings
from widgets.floating_wall_packing import valid_layout


def actions(menu):
    return {a.text(): a for a in menu.actions() if not a.isSeparator()}


def test_compact_menu_modes_use_explicit_owner_and_refresh_sibling_menus(opened_wall):
    host, windows = opened_wall
    wall = host._wall_layout
    root = QMenu(host)
    try:
        first = actions(wall.add_menu(root, windows[0]))
        sibling = actions(wall.add_menu(root, windows[1]))
        assert list(first) == ['Arrange now', 'Arrange automatically after resizing', 'This window',
                               'Reset layout', 'Packing algorithm (this session)', 'Wall settings…']
        one, two = actions(first['This window'].menu()), actions(sibling['This window'].menu())
        assert list(one) == ['Flexible', 'Keep size', 'Pin in place']
        one['Keep size'].trigger()
        two['Pin in place'].trigger()
        assert wall.window_mode(windows[0]) == 'size'
        assert wall.window_mode(windows[1]) == 'pinned'
        assert wall.window_mode(windows[2]) == 'flexible'
        # Active sibling is not the owner of this menu command.
        windows[1].activateWindow()
        one['Pin in place'].trigger()
        assert not windows[0]._wall_size_indicator.isVisible()
        QTest.mouseClick(windows[0]._wall_anchor_indicator, Qt.LeftButton)
        assert wall.window_mode(windows[0]) == 'size'
        assert one['Keep size'].isChecked() and two['Pin in place'].isChecked()
        one['Flexible'].trigger()
        assert wall._fixed_size(windows[0]) is None
        assert not windows[0]._wall_position_anchored
        assert two['Pin in place'].isChecked()
        assert sum(a.isChecked() for a in one.values()) == 1
        wall.resize_finished(windows[0], True)
        assert one['Keep size'].isChecked()
        # Position-only pin retains no size lock when released.
        windows[1]._wall_anchor_indicator.click()
        assert two['Flexible'].isChecked()
    finally:
        dispose_widget(root)


def test_reset_actions_keep_their_promised_scope_and_start_fresh_fits(opened_wall):
    host, windows = opened_wall
    wall = host._wall_layout
    wall.auto_arrange_action.setChecked(False)
    root = QMenu(host)
    try:
        reset = actions(actions(wall.add_menu(root, windows[0]))['Reset layout'].menu())
        assert not reset['Release kept sizes'].isEnabled()
        assert not reset['Unpin all windows'].isEnabled()
        wall.set_window_mode(windows[0], 'size')
        wall.set_window_mode(windows[0], 'pinned')
        wall.set_window_mode(windows[1], 'size')
        geometry = [QRect(w.geometry()) for w in windows]
        reset['Release kept sizes'].trigger()
        assert wall.window_mode(windows[0]) == 'pinned'
        assert wall.window_mode(windows[1]) == 'flexible'
        assert all(wall._fixed_size(w) is None for w in windows)
        assert [w.geometry() for w in windows] == geometry
        wall.set_window_mode(windows[1], 'size')
        reset['Unpin all windows'].trigger()
        assert wall.window_mode(windows[0]) == 'flexible'
        assert wall.window_mode(windows[1]) == 'size'
        assert [w.geometry() for w in windows] == geometry
        wall.set_window_mode(windows[0], 'pinned')
        previous = wall.last_result
        reset['Start fresh — release all locks and arrange'].trigger()
        finish_reflow(wall)
        assert wall.last_result is not previous
        assert all(wall.window_mode(w) == 'flexible' for w in windows)
        assert not wall.automatic_layout_enabled
        assert valid_layout([w.geometry() for w in windows], windows[0].screen().availableGeometry(), 6)
    finally:
        dispose_widget(root)


def test_one_automatic_switch_syncs_panel_menu_shortcut_and_saved_setting(opened_wall):
    host, windows = opened_wall
    wall = host._wall_layout
    wall.open_settings()
    dialog = wall._settings_dialog
    from dialogs.wall_layout_settings import WallLayoutSettings
    panel = dialog.findChild(WallLayoutSettings)
    try:
        assert panel is not None and dialog.isVisible()
        control = panel.controls['floating_wall_reflow_after_resize']
        control.setChecked(False)
        assert not wall.auto_arrange_action.isChecked()
        assert not settings.value('floating_wall_reflow_after_resize', type=bool)
        windows[-1].activateWindow()
        QTest.keyClick(windows[-1], Qt.Key_M, Qt.ControlModifier | Qt.AltModifier)
        assert wall.auto_arrange_action.isChecked() and control.isChecked()
        assert settings.value('floating_wall_reflow_after_resize', type=bool)
        control.setChecked(False)
        assert not panel.controls['floating_wall_resize_preview'].isEnabled()
        panel.controls['floating_wall_anchor_drag'].setChecked(False)
        assert not panel.controls['floating_wall_anchor_snapping'].isEnabled()
        control.setChecked(True)
        # Preserve all algorithm entries for session testing.
        root = QMenu(host)
        try:
            submenu = wall.add_menu(root, windows[0])
            choices = actions(actions(submenu)['Packing algorithm (this session)'].menu())
            assert list(choices) == ['Use settings (Best fit)', 'Best fit', 'Masonry', 'MaxRects']
            output = os.environ.get('TAGGUI_WALL_UI_OUTPUT')
            if output:
                directory = Path(output)
                directory.mkdir(parents=True, exist_ok=True)
                dialog.raise_()
                APP.processEvents()
                assert dialog.grab().save(str(directory/'wall-settings.png'))
                submenu.popup(dialog.mapToGlobal(QPoint(30, 80)))
                APP.processEvents()
                assert submenu.grab().save(str(directory/'wall-menu.png'))
                submenu.hide()
        finally:
            dispose_widget(root)
        wall.open_settings()
        assert wall._settings_dialog is dialog
    finally:
        dispose_widget(dialog)
    assert not isValid(dialog)
    wall.open_settings()
    assert wall._settings_dialog is not dialog
    dispose_widget(wall._settings_dialog)



def test_dismissing_wall_context_menu_does_not_arrange_the_wall(opened_wall, monkeypatch):
    host, windows = opened_wall
    calls, menus = [], []
    monkeypatch.setattr(host, 'arrange_floating_windows_as_masonry', lambda: calls.append(True))
    class CapturingMenu(QMenu):
        def exec(self, *_):
            menus.append([a.text() for a in self.actions()])
            return None
    from widgets import floating_viewer_window
    monkeypatch.setattr(floating_viewer_window, 'QMenu', CapturingMenu)
    windows[0]._show_window_menu(windows[0].pos())
    assert not calls
    assert 'Arrange as Masonry Wall' not in menus[0]
    assert 'Wall layout' in menus[0]
