import os
from pathlib import Path
from types import SimpleNamespace
import sys


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
TAGGUI_ROOT = ROOT / "taggui"
sys.path.insert(0, str(TAGGUI_ROOT))

from PySide6.QtWidgets import QApplication
from widgets.auto_markings import AutoMarkings, MarkingSettingsForm


APP = QApplication.instance() or QApplication([])


class _Button:
    def __init__(self):
        self.enabled = None

    def setEnabled(self, enabled):
        self.enabled = bool(enabled)


class _ClassTable:
    def __init__(self):
        self.row_count = None

    def setRowCount(self, row_count):
        self.row_count = row_count


def test_marking_directory_scan_waits_for_selector(monkeypatch):
    scans = []
    monkeypatch.setattr(
        MarkingSettingsForm,
        "get_local_model_paths",
        lambda self: scans.append("scan"),
    )

    form = MarkingSettingsForm()

    assert scans == []
    form.model_combo_box.showPopup()
    APP.processEvents()
    assert scans == ["scan"]
    form.model_combo_box.hidePopup()
    form.deleteLater()


def test_model_selection_change_does_not_prepare_model(tmp_path):
    model_path = tmp_path / "model.onnx"
    model_path.touch()
    prepared = []
    table = _ClassTable()
    auto_markings = AutoMarkings.__new__(AutoMarkings)
    auto_markings.is_marking = False
    auto_markings.marking_thread = None
    auto_markings.start_cancel_button = _Button()
    auto_markings.prepare_generation = lambda *args, **kwargs: prepared.append(
        (args, kwargs)
    )
    auto_markings.marking_settings_form = SimpleNamespace(
        reset_class_labels_button=_Button(),
        model_combo_box=SimpleNamespace(currentData=lambda: model_path),
        class_table=table,
        set_class_count=lambda count: None,
    )

    auto_markings._on_model_selection_changed(True)

    assert prepared == []
    assert auto_markings.start_cancel_button.enabled
    assert table.row_count == 0


def test_first_panel_interaction_restores_model_categories():
    actions = []
    auto_markings = AutoMarkings.__new__(AutoMarkings)
    auto_markings._first_interaction_preparation_scheduled = True
    auto_markings._first_interaction_handled = False
    auto_markings.is_marking = False
    auto_markings.marking_settings_form = SimpleNamespace(
        _ensure_local_model_paths=lambda: actions.append("scan"),
        model_combo_box=SimpleNamespace(currentData=lambda: Path("model.onnx")),
    )
    auto_markings.prepare_generation = lambda: actions.append("prepare")

    auto_markings._prepare_saved_model_on_first_interaction()

    assert actions == ["scan", "prepare"]
    assert auto_markings._first_interaction_handled
    assert not auto_markings._first_interaction_preparation_scheduled


def test_prepare_generation_reuses_matching_model(tmp_path):
    model_path = tmp_path / "model.onnx"
    model_path.touch()
    existing_thread = SimpleNamespace(
        model=object(),
        model_path=model_path,
        selected_image_indices=[],
        marking_settings={},
    )
    expected_settings = {
        "model_path": model_path,
        "requested_model_path": model_path,
    }
    auto_markings = AutoMarkings.__new__(AutoMarkings)
    auto_markings.marking_thread = existing_thread
    auto_markings.image_list = SimpleNamespace(
        get_selected_image_indices=lambda: ["selected"]
    )
    auto_markings.start_cancel_button = _Button()
    auto_markings.marking_settings_form = SimpleNamespace(
        get_marking_settings=lambda: dict(expected_settings)
    )

    auto_markings.prepare_generation()

    assert auto_markings.marking_thread is existing_thread
    assert existing_thread.selected_image_indices == ["selected"]
    assert existing_thread.marking_settings == expected_settings
    assert auto_markings.start_cancel_button.enabled
