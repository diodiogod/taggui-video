import os
from pathlib import Path
import sys

import pytest


os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'taggui'))

from PySide6.QtWidgets import QApplication, QLineEdit

from widgets.image_list_shared import (
    FilterSuggestionPopup,
    HoverSelectableListWidget,
)


def _app():
    return QApplication.instance() or QApplication([])


def test_hover_selection_does_not_change_scroll_position():
    app = _app()
    widget = HoverSelectableListWidget()
    widget.resize(220, 100)
    for index in range(24):
        widget.addItem(f'Item {index}')

    widget.show()
    app.processEvents()
    assert not widget.hasAutoScroll()
    scrollbar = widget.verticalScrollBar()
    scrollbar.setValue(scrollbar.maximum())
    scroll_position = scrollbar.value()

    widget._select_hovered_item(widget.item(0))
    app.processEvents()

    assert widget.currentRow() == 0
    assert scrollbar.value() == scroll_position

    widget.deleteLater()
    app.processEvents()


def test_filter_popup_reuses_resized_session_size():
    app = _app()
    line_edit = QLineEdit()
    line_edit.resize(400, 32)
    line_edit.show()

    popup = FilterSuggestionPopup(line_edit)
    popup.set_history_items(['first', 'second', 'third', 'fourth'])
    popup.show_for(line_edit)
    app.processEvents()

    assert popup._size_grip is not None
    assert popup._size_grip.size().width() == popup._SIZE_GRIP_SIZE
    assert popup.history_list_widget.minimumHeight() >= popup._HISTORY_MINIMUM_HEIGHT

    popup.resize(520, 620)
    app.processEvents()
    popup.hide()
    popup.show_for(line_edit)
    app.processEvents()

    assert popup.size().width() == 520
    assert popup.size().height() == 620
    assert popup.list_widget.height() > popup._FILTER_MINIMUM_HEIGHT
    assert popup.history_list_widget.height() > popup._HISTORY_MINIMUM_HEIGHT

    popup._splitter.moveSplitter(180, 1)
    app.processEvents()
    splitter_ratio = popup._session_splitter_ratio
    assert splitter_ratio is not None

    popup.hide()
    popup.show_for(line_edit)
    app.processEvents()
    sizes = popup._splitter.sizes()
    assert sizes[0] / sum(sizes) == pytest.approx(splitter_ratio)

    popup.hide()
    popup.deleteLater()
    line_edit.deleteLater()
    app.processEvents()
