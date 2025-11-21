"""
Simple popup menu for selecting from field history.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QMenu, QLineEdit, QVBoxLayout, QWidget
from PySide6.QtGui import QAction

from utils.field_history import get_field_history


class FieldHistoryPopup(QMenu):
    """Simple popup menu for browsing and selecting field values from history."""

    value_selected = Signal(str)

    def __init__(self, field_key: str, parent=None):
        super().__init__(parent)
        self.field_key = field_key
        self.history_manager = get_field_history()

        # Search box at top
        search_container = QWidget()
        search_layout = QVBoxLayout(search_container)
        search_layout.setContentsMargins(4, 4, 4, 4)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search...")
        self.search_box.textChanged.connect(self.on_search_changed)
        search_layout.addWidget(self.search_box)

        # Add search widget as custom widget action
        from PySide6.QtWidgets import QWidgetAction
        search_widget_action = QWidgetAction(self)
        search_widget_action.setDefaultWidget(search_container)
        self.addAction(search_widget_action)

        self.addSeparator()

        # Load initial items
        self.refresh_items()

    def refresh_items(self, search_query: str = ""):
        """Refresh menu items based on search query."""
        # Remove all actions except search widget and separator
        actions = self.actions()
        for action in actions[2:]:  # Keep first 2 (search widget + separator)
            self.removeAction(action)

        values = self.history_manager.get_values(self.field_key, search_query)

        if not values:
            no_items = QAction("(No history)", self)
            no_items.setEnabled(False)
            self.addAction(no_items)
            return

        # Add up to 20 most recent values
        for value in values[:20]:
            # Truncate long values
            display = value
            if len(display) > 60:
                display = display[:60] + '...'

            action = QAction(display, self)
            action.setData(value)  # Store full value
            action.triggered.connect(lambda checked, v=value: self.on_value_selected(v))
            self.addAction(action)

    def on_search_changed(self, text: str):
        """Handle search text changes."""
        self.refresh_items(text)

    def on_value_selected(self, value: str):
        """Emit signal when value is selected."""
        self.value_selected.emit(value)
