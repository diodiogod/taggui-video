import os
import sys
from copy import deepcopy
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "taggui"))

from PySide6.QtCore import QPoint, QPointF, QObject, Qt, Signal
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QMainWindow

import widgets.quick_sort_panel as quick_sort_panel_module
from utils.quick_sort import QuickSortMapping, QuickSortProfile
from widgets.quick_sort_panel import QuickSortPanel


APP = QApplication.instance() or QApplication([])


def _profile(name: str, key: str, folder: str) -> QuickSortProfile:
    return QuickSortProfile(
        name=name,
        destinations=[QuickSortMapping(folder, key, folder)],
    )


class _Store:
    def __init__(self, profiles):
        self.profiles = deepcopy(profiles)
        self.saved = []

    def load(self):
        return deepcopy(self.profiles)

    def save(self, profiles):
        snapshot = deepcopy(profiles)
        self.saved.append(snapshot)
        self.profiles = snapshot


class _Settings:
    def __init__(self):
        self.values = {"quick_sort_ui_zoom": 100}

    def value(self, key, defaultValue=None, *, type=None):
        value = self.values.get(key, defaultValue)
        return type(value) if type is not None and value is not None else value

    def setValue(self, key, value):
        self.values[key] = value


class _Model(QObject):
    modelReset = Signal()
    rowsInserted = Signal()
    rowsRemoved = Signal()

    def __init__(self, directory: Path, count: int = 6):
        super().__init__()
        self._directory_path = directory
        self._paginated_mode = False
        self._total_count = count
        self._scope_sql = ""
        self._scope_bindings = ()
        self._filter_sql = ""
        self._filter_bindings = ()
        self._count = count

    def rowCount(self):
        return self._count


class _Proxy(QObject):
    filter_changed = Signal()
    modelReset = Signal()

    def __init__(self, count: int = 6):
        super().__init__()
        self._count = count

    def rowCount(self):
        return self._count


class _ImageList:
    def get_selected_image_count(self):
        return 0


class _Window(QMainWindow):
    def __init__(self, directory: Path):
        super().__init__()
        self.image_list_model = _Model(directory)
        self.proxy_image_list_model = _Proxy()
        self.image_list = _ImageList()


class _Controller(QObject):
    active_changed = Signal(bool)
    session_finished = Signal(dict)

    def __init__(self, window: _Window, count: int = 6, all_loaded_count: int | None = None):
        super().__init__(window)
        self.window = window
        self.active = False
        self.count = count
        self.all_loaded_count = count if all_loaded_count is None else all_loaded_count
        self.estimate_calls = 0

    def resolve_browser_context(self):
        return {
            "name": "primary",
            "model": self.window.image_list_model,
            "proxy": self.window.proxy_image_list_model,
            "image_list": self.window.image_list,
            "owner": self.window,
        }

    def estimate_queue_count(self, profile, _context):
        self.estimate_calls += 1
        return self.all_loaded_count if profile.source_scope == "all_loaded" else self.count

    def start_session(self, _profile):
        return True


def _make_panel(monkeypatch, tmp_path, profiles):
    store = _Store(profiles)
    fake_settings = _Settings()
    monkeypatch.setattr(
        quick_sort_panel_module,
        "QuickSortProfileStore",
        lambda: store,
    )
    monkeypatch.setattr(quick_sort_panel_module, "settings", fake_settings)
    window = _Window(tmp_path)
    panel = QuickSortPanel(window)
    window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, panel)
    return window, panel, store


def _dispose(window, panel):
    panel._save_timer.stop()
    panel._count_refresh_timer.stop()
    panel.close()
    window.close()
    APP.processEvents()


def test_mapping_cards_fit_a_narrow_dock_and_keep_dynamic_zoom(monkeypatch, tmp_path):
    window, panel, _store = _make_panel(
        monkeypatch,
        tmp_path,
        [_profile("Body parts", "R", "Right Arm")],
    )
    try:
        panel.setFloating(True)
        panel.show()
        for width in (260, 280, 300):
            panel.resize(width, 760)
            APP.processEvents()
            assert panel.scroll.horizontalScrollBar().maximum() == 0
            assert panel.scroll.widget().width() <= panel.scroll.viewport().width()
            assert panel.destination_cards[0].width() <= panel.scroll.viewport().width()
            assert panel.qualifier_enabled_check.isVisible()
            assert panel.qualifier_enabled_check.width() > 80

        card = panel.destination_cards[0]
        initial_zoom = panel._ui_zoom
        wheel = QWheelEvent(
            QPointF(4, 4),
            QPointF(4, 4),
            QPoint(),
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.ControlModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        QApplication.sendEvent(card.destination_edit, wheel)
        assert panel._ui_zoom == initial_zoom + 10
    finally:
        _dispose(window, panel)


def test_qualifier_setup_is_visible_and_expands_from_its_switch(monkeypatch, tmp_path):
    window, panel, _store = _make_panel(
        monkeypatch,
        tmp_path,
        [_profile("Body parts", "R", "Right Arm")],
    )
    try:
        panel.setFloating(True)
        panel.resize(360, 760)
        panel.show()
        APP.processEvents()

        assert panel.qualifier_enabled_check.isVisible()
        assert not panel.qualifier_options.isVisible()

        panel.qualifier_enabled_check.setChecked(True)
        APP.processEvents()

        assert panel.qualifier_options.isVisible()
        assert panel.qualifier_name_edit.isVisible()
        assert panel.add_qualifier_button.isVisible()
    finally:
        _dispose(window, panel)


def test_new_overrides_receive_distinct_automatic_colors(monkeypatch, tmp_path):
    window, panel, _store = _make_panel(
        monkeypatch,
        tmp_path,
        [_profile("Body parts", "R", "Right Arm")],
    )
    try:
        existing_colors = {card.color.casefold() for card in panel.destination_cards}
        panel._add_destination()
        first_color = panel.destination_cards[-1].color.casefold()
        panel._add_destination()
        second_color = panel.destination_cards[-1].color.casefold()

        assert first_color not in existing_colors
        assert second_color not in existing_colors | {first_color}
    finally:
        _dispose(window, panel)


def test_destination_field_drives_both_label_and_folder(monkeypatch, tmp_path):
    legacy = QuickSortProfile(
        name="Legacy",
        destinations=[
            QuickSortMapping(
                name="Friendly label",
                key="R",
                folder="Right_Arm",
            )
        ],
    )
    window, panel, _store = _make_panel(monkeypatch, tmp_path, [legacy])
    try:
        card = panel.destination_cards[0]
        # Preserve the actual route when collapsing a legacy two-field row.
        assert card.destination_edit.text() == "Right_Arm"

        card.destination_edit.setText("People/Right Arm")
        mapping = card.mapping()
        assert mapping.name == "People/Right Arm"
        assert mapping.folder == "People/Right Arm"
    finally:
        _dispose(window, panel)


def test_advanced_file_controls_remain_visible_when_expanded(monkeypatch, tmp_path):
    window, panel, _store = _make_panel(
        monkeypatch,
        tmp_path,
        [_profile("Body parts", "R", "Right Arm")],
    )
    try:
        panel.setFloating(True)
        panel.resize(360, 760)
        panel.show()
        panel.advanced_toggle.setChecked(True)
        APP.processEvents()

        assert panel.scroll.horizontalScrollBar().maximum() == 0
        for control in (
            panel.operation_combo,
            panel.collision_combo,
            panel.sidecars_check,
            panel.fullscreen_check,
        ):
            assert control.isVisible()
            assert control.width() > 40
            assert control.height() > 10
    finally:
        _dispose(window, panel)


def test_profile_switch_persists_valid_draft_and_rejects_invalid_draft(
    monkeypatch,
    tmp_path,
):
    first = _profile("First", "A", "Folder A")
    second = _profile("Second", "B", "Folder B")
    window, panel, store = _make_panel(monkeypatch, tmp_path, [first, second])
    try:
        panel.destination_cards[0].destination_edit.setText("Edited A")
        second_index = panel.profile_combo.findData(second.id)
        panel.profile_combo.setCurrentIndex(second_index)

        assert panel.current_profile_id == second.id
        assert store.saved[-1][0].destinations[0].name == "Edited A"

        first_index = panel.profile_combo.findData(first.id)
        panel.profile_combo.setCurrentIndex(first_index)
        saves_before_invalid_switch = len(store.saved)
        panel.destination_cards[0].destination_edit.clear()
        panel.profile_combo.setCurrentIndex(second_index)

        assert panel.current_profile_id == first.id
        assert panel.profile_combo.currentData() == first.id
        assert panel.destination_cards[0].destination_edit.text() == ""
        assert len(store.saved) == saves_before_invalid_switch
        assert panel.validation_chip.text() == "CHECK"
    finally:
        _dispose(window, panel)


def test_selecting_builtin_preset_loads_its_routes_instead_of_custom_profile(
    monkeypatch,
    tmp_path,
):
    custom = _profile("My destinations", "R", "Right Arm")
    window, panel, store = _make_panel(monkeypatch, tmp_path, [custom])
    try:
        preset = panel._builtin_profiles[0]
        preset_index = panel.profile_combo.findData(f"__builtin__:{preset.id}")

        panel.profile_combo.setCurrentIndex(preset_index)

        assert panel.current_profile_id != custom.id
        assert panel.profile_combo.currentText() == f"{preset.name} (custom)"
        assert [card.mapping().folder for card in panel.destination_cards] == [
            mapping.folder for mapping in preset.destinations
        ]
        assert store.saved[-1][-1].template_key == "composition_shot_sizes"
    finally:
        _dispose(window, panel)


def test_mapping_edits_reuse_count_cache_and_readiness_tracks_recounts(
    monkeypatch,
    tmp_path,
):
    window, panel, _store = _make_panel(
        monkeypatch,
        tmp_path,
        [_profile("Body parts", "R", "Right Arm")],
    )
    controller = _Controller(window, count=6)
    readiness = []
    panel.readiness_changed.connect(readiness.append)
    try:
        panel.bind_controller(controller)
        panel._count_refresh_timer.stop()
        panel._refresh_eligible_count()

        assert controller.estimate_calls == 2
        assert panel.is_ready
        assert readiness == [True]

        panel.destination_cards[0].destination_edit.setText("Renamed route")
        assert controller.estimate_calls == 2
        assert not panel._count_refresh_timer.isActive()
        assert panel.is_ready

        panel.include_videos_check.toggle()
        assert not panel.is_ready
        panel._count_refresh_timer.stop()
        panel._refresh_eligible_count()
        assert controller.estimate_calls == 4
        assert panel.is_ready

        controller.count = 0
        controller.all_loaded_count = 0
        panel.source_combo.setCurrentIndex(
            panel.source_combo.findData("all_loaded")
        )
        panel._count_refresh_timer.stop()
        panel._refresh_eligible_count()
        assert controller.estimate_calls == 5
        assert not panel.is_ready
        assert readiness == [True, False, True, False]
    finally:
        _dispose(window, panel)


def test_current_folder_scope_reveals_hidden_subfolder_media(monkeypatch, tmp_path):
    window, panel, _store = _make_panel(
        monkeypatch,
        tmp_path,
        [_profile("Body parts", "R", "Right Arm")],
    )
    controller = _Controller(window, count=5, all_loaded_count=148)
    try:
        panel.bind_controller(controller)
        panel._count_refresh_timer.stop()
        panel._refresh_eligible_count()
        panel.show()
        APP.processEvents()

        assert not panel.scope_notice.isHidden()
        assert panel.scope_notice_label.text() == (
            "143 more media available in subfolders."
        )
        assert panel.include_all_loaded_button.text() == "Include all 148"
        assert panel.start_button.text() == "Start with 5 media"

        panel.include_all_loaded_button.click()
        panel._count_refresh_timer.stop()
        panel._refresh_eligible_count()

        assert panel.source_combo.currentData() == "all_loaded"
        assert panel.scope_notice.isHidden()
        assert panel.start_button.text() == "Start with 148 media"
    finally:
        _dispose(window, panel)
