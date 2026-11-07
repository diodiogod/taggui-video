"""Queued selection history callbacks must respect their view's lifetime."""

import sys

from PySide6.QtCore import QItemSelectionModel, Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QListView
from shiboken6 import isValid

from qt_test_helpers import APP, dispose_widget
from utils.image import Image
from widgets.image_list_view_paint_selection_mixin import ImageListViewPaintSelectionMixin


def test_selection_history_callback_is_cancelled_with_its_view(tmp_path, monkeypatch):
    errors = []
    monkeypatch.setattr(sys, 'excepthook', lambda *error: errors.append(error))
    model = QStandardItemModel()
    for name in ('first.png', 'second.png'):
        item = QStandardItem()
        item.setData(Image(tmp_path / name, (1, 1), []), Qt.ItemDataRole.UserRole)
        model.appendRow(item)

    class HistoryView(ImageListViewPaintSelectionMixin, QListView):
        selection_history_changed = Signal()
        selection_summary_changed = Signal()

    def make_view():
        view = HistoryView()
        view.setModel(model)
        view._virtual_select_all_active = False
        view._virtual_selection_mode = None
        view._virtual_selection_paths = {}
        view._model_resetting = False
        view._selection_history = []
        view._selection_redo_history = []
        view._selection_history_current = view._capture_selection_snapshot()
        view._selection_history_pending_before = None
        view._selection_history_pending_after = None
        view._selection_history_flush_scheduled = False
        view._selection_history_suspended = False
        view.selectionModel().selectionChanged.connect(view._on_selection_history_changed)
        return view

    first, sibling = make_view(), make_view()
    try:
        first.selectionModel().select(model.index(0, 0), QItemSelectionModel.SelectionFlag.Select)
        assert first._selection_history_flush_scheduled
        dispose_widget(first)
        sibling.selectionModel().select(model.index(1, 0), QItemSelectionModel.SelectionFlag.Select)
        APP.processEvents()
        assert not isValid(first) and isValid(sibling)
        assert len(sibling._selection_history) == 1
        assert not errors
    finally:
        if isValid(first):
            dispose_widget(first)
        dispose_widget(sibling)
