import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "taggui"))

from PySide6.QtCore import (
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    Qt,
)
from PySide6.QtGui import QKeyEvent, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QGraphicsView,
    QLineEdit,
    QListView,
    QMainWindow,
    QWidget,
)

from controllers.quick_sort_controller import (
    QuickSortController,
    QuickSortHistoryRecord,
    QuickSortHud,
    QuickSortQueueSnapshot,
)
from utils.quick_sort import (
    QuickSortMapping,
    QuickSortProfile,
    QuickSortSessionStore,
)
from utils.quick_sort_file_service import QuickSortFileOperation


def _application():
    return QApplication.instance() or QApplication([])


class _ControllerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        view = QGraphicsView(self)
        self.loaded_viewer_indices = []
        owner = self

        class _Viewer:
            def __init__(self):
                self.view = view
                self.proxy_image_index = QPersistentModelIndex()

            def load_image(self, index):
                owner.loaded_viewer_indices.append(QModelIndex(index))
                self.proxy_image_index = QPersistentModelIndex(index)

        self.image_viewer = _Viewer()


class _PathModel(QStandardItemModel):
    def __init__(self, paths):
        super().__init__()
        self.paths = [Path(path) for path in paths]
        for path in self.paths:
            self.appendRow(QStandardItem(path.name))

    def get_index_for_path(self, path):
        target = Path(path)
        return next(
            (index for index, candidate in enumerate(self.paths) if candidate == target),
            -1,
        )


def _key_event(key: Qt.Key, text: str) -> QKeyEvent:
    return QKeyEvent(
        QEvent.Type.KeyPress,
        key,
        Qt.KeyboardModifier.NoModifier,
        text,
    )


def _profile() -> tuple[QuickSortProfile, QuickSortMapping, QuickSortMapping]:
    destination = QuickSortMapping("Right Arm", "R", "Right Arm")
    high = QuickSortMapping("High", "1", "High")
    medium = QuickSortMapping("Medium", "2", "Medium")
    return (
        QuickSortProfile(
            name="Body parts",
            destinations=[destination],
            qualifiers=[high, medium],
            qualifier_enabled=True,
        ),
        high,
        medium,
    )


@pytest.mark.parametrize("normal_selection_signal", [False, True])
def test_quick_sort_loads_once_and_falls_back_when_selection_signal_is_suppressed(
    tmp_path,
    normal_selection_signal,
):
    _application()
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.write_bytes(b"image")
    second.write_bytes(b"image")
    model = _PathModel([first, second])
    proxy = QSortFilterProxyModel()
    proxy.setSourceModel(model)
    list_view = QListView()
    list_view.setModel(proxy)
    window = _ControllerWindow()
    if normal_selection_signal:
        list_view.selectionModel().currentChanged.connect(
            lambda current, _previous: window.image_viewer.load_image(current)
        )
    controller = QuickSortController(window)
    controller._browser_context = {
        "name": "primary",
        "model": model,
        "proxy": proxy,
        "image_list": SimpleNamespace(list_view=list_view),
        "owner": window,
    }
    controller.profile = QuickSortProfile(name="Instant sort")
    controller.queue = QuickSortQueueSnapshot(paths=(first, second))
    controller.active = True
    try:
        controller._show_current()
        controller.skip_current()
        assert [index.row() for index in window.loaded_viewer_indices] == [0, 1]
    finally:
        controller.hud.hide()
        list_view.close()
        window.close()


def test_saved_skip_is_restored_and_next_run_starts_at_unreviewed_item(tmp_path):
    _application()
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.write_bytes(b"image")
    second.write_bytes(b"image")
    profile = QuickSortProfile(name="Resume", id="resume-profile")
    queue = QuickSortQueueSnapshot(paths=(first, second), directory_path=tmp_path)
    store = QuickSortSessionStore(tmp_path / "sessions.json")

    first_window = _ControllerWindow()
    first_controller = QuickSortController(first_window)
    first_controller.session_store = store
    first_controller.profile = profile
    first_controller.queue = queue
    first_controller._resume_session_key = first_controller._session_key(
        profile,
        tmp_path,
    )
    identity = first_controller._record_source_identity(0)
    first_controller._decisions[0] = QuickSortHistoryRecord(
        index=0,
        label="Skip",
        color="#999999",
        skipped=True,
        **identity,
    )
    first_controller._persist_session_state()
    first_controller.hud.hide()
    first_window.close()

    model = _PathModel([first, second])
    proxy = QSortFilterProxyModel()
    proxy.setSourceModel(model)
    list_view = QListView()
    list_view.setModel(proxy)
    window = _ControllerWindow()
    controller = QuickSortController(window)
    controller.session_store = store
    controller.profile = profile
    controller.queue = queue
    controller._resume_session_key = controller._session_key(profile, tmp_path)
    controller._browser_context = {
        "name": "primary",
        "model": model,
        "proxy": proxy,
        "image_list": SimpleNamespace(list_view=list_view),
        "owner": window,
    }
    controller.active = True
    try:
        controller._restore_session_state()
        controller._show_current()

        assert controller._decisions[0].skipped is True
        assert controller.position == 1
        assert [index.row() for index in window.loaded_viewer_indices] == [1]
    finally:
        controller.hud.hide()
        list_view.close()
        window.close()


def test_pending_qualifier_can_be_replaced_before_destination(tmp_path):
    _application()
    window = _ControllerWindow()
    controller = QuickSortController(window)
    profile, high, medium = _profile()
    controller.profile = profile
    controller.queue = QuickSortQueueSnapshot(paths=(tmp_path / "image.png",))
    controller.active = True
    chosen = []
    controller.classify_current = chosen.append
    try:
        assert controller.handle_key_event(
            _key_event(Qt.Key.Key_1, "1"),
            QEvent.Type.KeyPress,
        )
        assert controller.pending_qualifier_id == high.id

        controller.handle_key_event(
            _key_event(Qt.Key.Key_2, "2"),
            QEvent.Type.KeyPress,
        )
        assert controller.pending_qualifier_id == medium.id

        controller.handle_key_event(
            _key_event(Qt.Key.Key_R, "r"),
            QEvent.Type.KeyPress,
        )
        assert chosen == [profile.destinations[0]]
    finally:
        controller.hud.hide()
        window.close()


def test_redo_clears_qualifier_before_next_image(tmp_path):
    _application()
    window = _ControllerWindow()
    controller = QuickSortController(window)
    profile, high, _medium = _profile()
    record = QuickSortHistoryRecord(
        index=0,
        label="Skip collision",
        color="#62E7D8",
        qualifier_id=high.id,
        skipped=True,
    )
    controller.profile = profile
    controller.queue = QuickSortQueueSnapshot(
        paths=(tmp_path / "one.png", tmp_path / "two.png")
    )
    controller.active = True
    controller.history = [record]
    controller.history_cursor = 0
    controller.pending_qualifier_id = high.id
    controller._show_current = lambda: None
    try:
        controller.redo()
        assert controller.history_cursor == 1
        assert controller.pending_qualifier_id is None
        assert controller.position == 1
        assert controller._decision_at(0) is record
    finally:
        controller.hud.hide()
        window.close()


def test_non_linear_navigation_wraps_to_remaining_unreviewed_item(tmp_path):
    _application()
    paths = tuple(tmp_path / f"{index}.png" for index in range(3))
    for path in paths:
        path.write_bytes(b"image")
    window = _ControllerWindow()
    controller = QuickSortController(window)
    profile, _high, _medium = _profile()
    controller.profile = profile
    controller.queue = QuickSortQueueSnapshot(paths=paths)
    controller.active = True
    controller.position = 2
    selected = []
    controller._select_media_by_path = lambda path: selected.append(path) or True
    try:
        controller._advance_after_record(
            QuickSortHistoryRecord(
                index=2,
                label="Right Arm",
                color="#62E7D8",
                skipped=True,
            )
        )
        assert controller.position == 0
        assert selected[-1] == paths[0]
        assert controller._progress_text() == "2 / 3"
    finally:
        controller.hud.hide()
        window.close()


def test_background_file_worker_is_retained_until_ui_callback():
    app = _application()
    window = _ControllerWindow()
    controller = QuickSortController(window)
    finished = []
    try:
        controller._run_worker(
            lambda: "complete",
            lambda result, error: finished.append((result, error)),
        )
        deadline = time.monotonic() + 5.0
        while not finished and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)

        assert finished == [("complete", None)]
        assert controller.busy is False
        assert controller._workers == set()
    finally:
        controller.hud.hide()
        window.close()


def test_escape_clears_qualifier_before_exiting(tmp_path):
    _application()
    window = _ControllerWindow()
    controller = QuickSortController(window)
    profile, high, _medium = _profile()
    controller.profile = profile
    controller.queue = QuickSortQueueSnapshot(paths=(tmp_path / "image.png",))
    controller.active = True
    controller.pending_qualifier_id = high.id
    controller._update_hud = lambda: None
    controller.hud.show_feedback = lambda *_args: None
    exit_requests = []
    controller.finish_session = lambda **_kwargs: exit_requests.append(True)
    try:
        assert controller.handle_key_event(
            _key_event(Qt.Key.Key_Escape, ""),
            QEvent.Type.KeyPress,
        )
        assert controller.pending_qualifier_id is None
        assert exit_requests == []

        assert controller.handle_key_event(
            _key_event(Qt.Key.Key_Escape, ""),
            QEvent.Type.KeyPress,
        )
        assert exit_requests == [True]
    finally:
        controller.hud.hide()
        window.close()


def test_restore_layout_reenters_preexisting_viewer_fullscreen():
    _application()
    window = _ControllerWindow()
    controller = QuickSortController(window)
    filter_widget = QLineEdit()
    media_widget = QComboBox()
    media_widget.addItem("All")
    context = {
        "image_list": SimpleNamespace(
            filter_line_edit=filter_widget,
            media_type_combo_box=media_widget,
        )
    }
    fullscreen = {"active": False, "entered": 0, "restored": 0}
    window._main_viewer_visible = True
    window._viewer_is_fullscreen = lambda _viewer: fullscreen["active"]
    window._enter_viewer_fullscreen = lambda _viewer: (
        fullscreen.update(active=True, entered=fullscreen["entered"] + 1)
        or True
    )
    window._restore_fullscreen_viewer = lambda *_args, **_kwargs: (
        fullscreen.update(active=False, restored=fullscreen["restored"] + 1)
        or True
    )
    window.set_main_viewer_visible = lambda *_args, **_kwargs: None
    controller._browser_context = context
    controller._apply_browser_filter = lambda: None
    controller._saved_layout = {
        "viewer_fullscreen": True,
        "main_viewer_visible": True,
        "menu_visible": True,
        "filter_text": "",
        "media_type": "All",
    }
    try:
        controller._restore_layout()
        assert fullscreen == {"active": True, "entered": 1, "restored": 0}

        controller._saved_layout = {
            "viewer_fullscreen": True,
            "main_viewer_visible": True,
            "menu_visible": True,
            "filter_text": "",
            "media_type": "All",
        }
        controller._restore_layout()
        assert fullscreen == {"active": True, "entered": 1, "restored": 0}
    finally:
        controller.hud.hide()
        window.close()


class _FakeMediaIndex:
    def __init__(self, row: int, path: Path):
        self._row = row
        self._image = SimpleNamespace(path=path)

    def isValid(self):
        return True

    def row(self):
        return self._row

    def data(self, _role):
        return self._image


def test_secondary_reload_restores_filter_media_type_and_selection(tmp_path):
    _application()
    window = _ControllerWindow()
    controller = QuickSortController(window)
    filter_widget = QLineEdit()
    filter_widget.setText("rating:5")
    media_widget = QComboBox()
    media_widget.addItems(["All", "Images"])
    media_widget.setCurrentText("Images")
    selected_path = tmp_path / "selected.png"
    current_index = _FakeMediaIndex(7, selected_path)
    image_list = SimpleNamespace(
        filter_line_edit=filter_widget,
        media_type_combo_box=media_widget,
        list_view=SimpleNamespace(currentIndex=lambda: current_index),
    )
    model = SimpleNamespace(_directory_path=tmp_path)
    load_calls = []
    apply_calls = []

    def load_directory(path):
        load_calls.append(path)
        filter_widget.clear()
        media_widget.setCurrentText("All")

    owner = SimpleNamespace(
        load_directory=load_directory,
        _apply_filter_now=lambda: apply_calls.append(True),
    )
    restored = []
    window._restore_refresh_selection = lambda target, **state: restored.append(
        (target, state)
    )
    context = {
        "name": "secondary",
        "model": model,
        "proxy": object(),
        "image_list": image_list,
        "owner": owner,
    }
    try:
        controller._reload_browser(context)
        assert load_calls == [tmp_path.absolute()]
        assert media_widget.currentText() == "Images"
        assert filter_widget.text() == "rating:5"
        assert apply_calls == [True]
        assert restored[0][1] == {
            "select_index": 7,
            "select_path": str(selected_path.absolute()),
        }
    finally:
        controller.hud.hide()
        window.close()


def test_reconcile_surfaces_failed_database_rename(tmp_path):
    _application()
    window = _ControllerWindow()
    controller = QuickSortController(window)
    source = tmp_path / "source.png"
    destination = tmp_path / "sorted" / "source.png"

    class _FailingDatabase:
        def get_image_id(self, relative_path):
            return 1 if relative_path == "source.png" else None

        def rename_image_path(self, *_args, **_kwargs):
            return False

        def invalidate_order_cache(self):
            return None

    context = {
        "name": "primary",
        "model": SimpleNamespace(
            _directory_path=tmp_path,
            _db=_FailingDatabase(),
        ),
    }
    operation = QuickSortFileOperation(
        mode="move",
        source=source,
        destination=destination,
        bundle_pairs=(),
    )
    try:
        with pytest.raises(RuntimeError, match="failed to rename"):
            controller._reconcile_browser_model([operation], context)
    finally:
        controller.hud.hide()
        window.close()


def test_reconcile_registers_move_entering_another_browser_root(tmp_path):
    _application()
    window = _ControllerWindow()
    controller = QuickSortController(window)
    source = tmp_path / "source" / "image.png"
    target_root = tmp_path / "target"
    destination = target_root / "image.png"
    rows = set()

    class _Database:
        def get_image_id(self, relative_path):
            return 1 if relative_path in rows else None

        def invalidate_order_cache(self):
            return None

    database = _Database()

    def add_generated_media_batch(paths):
        for path in paths:
            rows.add(str(path.relative_to(target_root)))
        return len(paths)

    context = {
        "name": "secondary",
        "model": SimpleNamespace(
            _directory_path=target_root,
            _db=database,
            add_generated_media_batch=add_generated_media_batch,
        ),
    }
    operation = QuickSortFileOperation(
        mode="move",
        source=source,
        destination=destination,
        bundle_pairs=(),
    )
    try:
        controller._reconcile_browser_model([operation], context)
        assert rows == {"image.png"}
    finally:
        controller.hud.hide()
        window.close()


def test_finish_retries_pending_main_window_close(monkeypatch):
    app = _application()
    window = _ControllerWindow()
    controller = QuickSortController(window)
    model = SimpleNamespace(_directory_path=None)
    context = {
        "name": "primary",
        "model": model,
        "proxy": object(),
        "image_list": object(),
        "owner": window,
    }
    controller.active = True
    controller.queue = QuickSortQueueSnapshot()
    controller._browser_context = context
    controller._restore_layout = lambda: None
    controller._contexts_overlapping_paths = lambda _paths: []
    controller._reconcile_browser_models = lambda _operations, _contexts: None
    controller.hud.hide = lambda: None
    window._quick_sort_close_pending = True
    close_requests = []
    monkeypatch.setattr(window, "close", lambda: close_requests.append(True))
    try:
        controller.finish_session()
        app.processEvents()
        assert close_requests == [True]
        assert window._quick_sort_close_pending is False
    finally:
        QMainWindow.close(window)


def test_absolute_path_keeps_symlink_identity(tmp_path):
    target = tmp_path / "target.png"
    target.write_bytes(b"image")
    link = tmp_path / "link.png"
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"Symlink creation is unavailable: {exc}")

    absolute_link = QuickSortController._absolute_path(link)
    assert absolute_link == link.absolute()
    assert absolute_link != target.absolute()

    _application()
    window = _ControllerWindow()
    controller = QuickSortController(window)
    profile, _high, _medium = _profile()
    profile.include_subfolders = True
    context = {
        "model": SimpleNamespace(
            _directory_path=tmp_path,
            _paginated_mode=False,
            iter_all_images=lambda: [
                SimpleNamespace(path=link, is_video=False)
            ],
        ),
        "image_list": object(),
        "proxy": object(),
    }
    try:
        queue = controller.build_queue(profile, context)
        assert queue.paths == (link.absolute(),)
    finally:
        controller.hud.hide()
        window.close()


def test_hud_geometry_stays_inside_narrow_viewport():
    app = _application()
    viewport = QWidget()
    viewport.resize(190, 260)
    viewport.show()
    hud = QuickSortHud(viewport)
    mappings = [
        QuickSortMapping(f"Long destination {index}", str(index), f"Folder {index}")
        for index in range(8)
    ]
    try:
        hud.show()
        hud.set_state(
            stage="Choose a quality or destination (unclassified)",
            progress="1 / 10",
            mappings=mappings,
        )
        hud.show_feedback(
            "A VERY LONG DESTINATION NAME",
            "This feedback detail should wrap instead of extending past the viewport.",
            "#62E7D8",
        )
        app.processEvents()
        hud.reposition()
        for widget in (hud.status_bar, hud.legend, hud.feedback):
            geometry = widget.geometry()
            assert geometry.left() >= 0
            assert geometry.top() >= 0
            assert geometry.right() < viewport.width()
            assert geometry.bottom() < viewport.height()
    finally:
        hud.hide()
        viewport.close()


def test_completion_feedback_offers_persistent_start_fresh_action():
    app = _application()
    viewport = QWidget()
    viewport.resize(640, 480)
    viewport.show()
    hud = QuickSortHud(viewport)
    requested = []
    hud.start_fresh_requested.connect(lambda: requested.append(True))
    try:
        hud.show()
        hud.show_feedback(
            "SORT COMPLETE",
            "12 moved · 3 skipped",
            "#62E7D8",
            action_text="Start fresh",
            persistent=True,
        )
        app.processEvents()

        assert hud.feedback.isVisible()
        assert hud.feedback_action.isVisible()
        assert hud.feedback_effect.opacity() == pytest.approx(1.0)
        hud.feedback_action.click()
        assert requested == [True]
    finally:
        hud.hide()
        viewport.close()


def test_primary_quick_sort_reload_does_not_recenter_to_moved_path(tmp_path):
    _application()
    window = _ControllerWindow()
    calls = []
    window._reload_directory_from_state = lambda **state: calls.append(state)
    controller = QuickSortController(window)
    filter_widget = QLineEdit()
    filter_widget.setText("rating:5")
    context = {
        "name": "primary",
        "model": SimpleNamespace(_directory_path=tmp_path),
        "image_list": SimpleNamespace(filter_line_edit=filter_widget),
    }
    try:
        controller._reload_browser(context)
        assert calls == [
            {
                "filter_text": "rating:5",
                "select_index": 0,
                "select_path": None,
            }
        ]
    finally:
        controller.hud.hide()
        window.close()
