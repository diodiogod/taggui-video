import os
from pathlib import Path
from types import SimpleNamespace
import sys


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
TAGGUI_ROOT = ROOT / "taggui"
sys.path.insert(0, str(TAGGUI_ROOT))

from PySide6.QtWidgets import QApplication
import widgets.auto_markings as auto_markings_module
from widgets.auto_markings import AutoMarkings, MarkingSettingsForm


APP = QApplication.instance() or QApplication([])


class _Button:
    def __init__(self):
        self.enabled = None

    def setEnabled(self, enabled):
        self.enabled = bool(enabled)


class _Label:
    def __init__(self):
        self.text = ""
        self.visible = False

    def setText(self, text):
        self.text = text

    def show(self):
        self.visible = True


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
    auto_markings._model_preparation_future = None
    auto_markings._model_preparation_path = None
    auto_markings._model_preparation_token = 0
    auto_markings._start_after_model_preparation = False
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


def test_first_panel_interaction_uses_cached_categories(monkeypatch):
    actions = []
    monkeypatch.setattr(
        auto_markings_module,
        "get_cached_model_classes",
        lambda path: {0: "person", 1: "hand"},
    )
    auto_markings = AutoMarkings.__new__(AutoMarkings)
    auto_markings._first_interaction_preparation_scheduled = True
    auto_markings._first_interaction_handled = False
    auto_markings.is_marking = False
    auto_markings.marking_settings_form = SimpleNamespace(
        _ensure_local_model_paths=lambda: actions.append("scan"),
        model_combo_box=SimpleNamespace(currentData=lambda: Path("model.onnx")),
    )
    auto_markings._populate_model_categories = (
        lambda classes: actions.append(("categories", classes))
    )
    auto_markings.prepare_generation = lambda: actions.append("prepare")

    auto_markings._prepare_saved_model_on_first_interaction()

    assert actions == [
        "scan",
        ("categories", {0: "person", 1: "hand"}),
    ]


def test_repeated_prepare_requests_share_one_background_load(tmp_path):
    model_path = tmp_path / "model.onnx"
    model_path.touch()

    class PendingFuture:
        def done(self):
            return False

    class Executor:
        def __init__(self):
            self.submissions = []

        def submit(self, callback):
            self.submissions.append(callback)
            return PendingFuture()

    executor = Executor()
    auto_markings = AutoMarkings.__new__(AutoMarkings)
    auto_markings.marking_thread = None
    auto_markings._model_preparation_executor = executor
    auto_markings._model_preparation_future = None
    auto_markings._model_preparation_path = None
    auto_markings._model_preparation_token = 0
    auto_markings._start_after_model_preparation = False
    auto_markings.image_list = SimpleNamespace(
        get_selected_image_indices=lambda: []
    )
    auto_markings.marking_settings_form = SimpleNamespace(
        get_marking_settings=lambda: {
            "model_path": model_path,
            "requested_model_path": model_path,
        }
    )
    auto_markings.start_cancel_button = _Button()
    auto_markings.result_label = _Label()
    auto_markings._create_marking_thread = (
        lambda selected, settings: SimpleNamespace(preload_model=lambda: None)
    )

    assert not auto_markings.prepare_generation()
    assert not auto_markings.prepare_generation(start_after_prepare=True)

    assert len(executor.submissions) == 1
    assert auto_markings._start_after_model_preparation


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
