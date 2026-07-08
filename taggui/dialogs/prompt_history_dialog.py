"""
Prompt history browser dialog.

Allows users to browse, search, and select prompts from history.
"""

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QLabel, QTextEdit, QSplitter
)
import time

from utils.prompt_history import get_prompt_history


class PromptHistoryDialog(QDialog):
    """Dialog for browsing and selecting prompts from history."""

    prompt_selected = Signal(str)  # Emitted when user selects a prompt

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Prompt History")
        self.resize(800, 600)

        self.history_manager = get_prompt_history()

        # Layout
        layout = QVBoxLayout(self)

        # Search bar
        search_layout = QHBoxLayout()
        search_label = QLabel("Search:")
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter prompts...")
        self.search_input.textChanged.connect(self.on_search_changed)
        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)

        # Splitter for list and preview
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Prompt list
        self.prompt_list = QListWidget()
        self.prompt_list.currentItemChanged.connect(self.on_item_selected)
        self.prompt_list.itemDoubleClicked.connect(self.on_item_double_clicked)
        splitter.addWidget(self.prompt_list)

        # Preview pane
        preview_container = QVBoxLayout()
        preview_label = QLabel("Preview:")
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setMaximumHeight(150)
        preview_container.addWidget(preview_label)
        preview_container.addWidget(self.preview_text)

        preview_widget = QLabel()  # Container for layout
        from PySide6.QtWidgets import QWidget
        preview_widget = QWidget()
        preview_widget.setLayout(preview_container)
        splitter.addWidget(preview_widget)

        splitter.setSizes([400, 200])
        layout.addWidget(splitter)

        # Stats label
        self.stats_label = QLabel()
        layout.addWidget(self.stats_label)

        # Buttons
        button_layout = QHBoxLayout()
        self.use_button = QPushButton("Use This Prompt")
        self.use_button.clicked.connect(self.on_use_clicked)
        self.use_button.setEnabled(False)

        self.clear_button = QPushButton("Clear History")
        self.clear_button.clicked.connect(self.on_clear_clicked)

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)

        button_layout.addWidget(self.use_button)
        button_layout.addStretch()
        button_layout.addWidget(self.clear_button)
        button_layout.addWidget(close_button)
        layout.addLayout(button_layout)

        # Load initial prompts
        self.refresh_list()

    def refresh_list(self, search_query: str = ""):
        """Refresh the prompt list with optional search filter."""
        self.prompt_list.clear()
        prompts = self.history_manager.get_all_prompts(search_query)

        for prompt_data in prompts:
            prompt = prompt_data['prompt']
            last_used = prompt_data['last_used']
            hits = prompt_data['hits']

            # Format timestamp
            if last_used > 0:
                time_str = time.strftime('%d %b %H:%M', time.localtime(last_used))
            else:
                time_str = 'Never'

            # Create display text (truncated preview)
            display = prompt.replace('\n', ' ')
            if len(display) > 80:
                display = display[:80] + '...'

            label = f"{time_str} • {hits} uses • {display}"

            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, prompt)  # Store full prompt
            self.prompt_list.addItem(item)

        # Update stats
        total = len(prompts)
        if search_query:
            self.stats_label.setText(f"Found {total} matching prompts")
        else:
            self.stats_label.setText(f"Total: {total} prompts")

    @Slot(str)
    def on_search_changed(self, text: str):
        """Handle search text changes."""
        self.refresh_list(text)

    @Slot(QListWidgetItem, QListWidgetItem)
    def on_item_selected(self, current, previous):
        """Handle item selection - show preview."""
        if current:
            prompt = current.data(Qt.ItemDataRole.UserRole)
            self.preview_text.setPlainText(prompt)
            self.use_button.setEnabled(True)
        else:
            self.preview_text.clear()
            self.use_button.setEnabled(False)

    @Slot(QListWidgetItem)
    def on_item_double_clicked(self, item):
        """Handle double-click - use the prompt."""
        self.on_use_clicked()

    @Slot()
    def on_use_clicked(self):
        """Emit signal with selected prompt and close dialog."""
        current = self.prompt_list.currentItem()
        if current:
            prompt = current.data(Qt.ItemDataRole.UserRole)
            self.prompt_selected.emit(prompt)
            self.accept()

    @Slot()
    def on_clear_clicked(self):
        """Clear all history after confirmation."""
        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self,
            "Clear History",
            "Are you sure you want to clear all prompt history?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.history_manager.clear_history()
            self.refresh_list()
