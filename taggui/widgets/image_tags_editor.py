from PySide6.QtCore import (QItemSelectionModel, QModelIndex, QStringListModel,
                            QTimer, Qt, Signal, Slot)
from PySide6.QtGui import QKeyEvent, QIcon
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QCompleter, QDockWidget,
                               QHBoxLayout, QLabel, QLineEdit, QListView, QMessageBox,
                               QPushButton, QStyle, QToolButton, QVBoxLayout, QWidget)
from transformers import PreTrainedTokenizerBase

from models.proxy_image_list_model import ProxyImageListModel
from models.tag_counter_model import TagCounterModel
from utils.image import Image
from utils.settings import DEFAULT_SETTINGS, settings
from utils.text_edit_item_delegate import TextEditItemDelegate
from utils.utils import get_confirmation_dialog_reply
from widgets.image_list import ImageList
from widgets.descriptive_text_edit import DescriptiveTextEdit

MAX_TOKEN_COUNT = 75


class TagInputBox(QLineEdit):
    tags_addition_requested = Signal(list, list)

    def __init__(self, image_tag_list_model: QStringListModel,
                 tag_counter_model: TagCounterModel, image_list: ImageList,
                 tag_separator: str):
        super().__init__()
        self.image_tag_list_model = image_tag_list_model
        self.image_list = image_list
        self.tag_separator = tag_separator

        self.setPlaceholderText('Add Tag')
        self.setStyleSheet('padding: 8px;')
        autocomplete_tags = settings.value(
            'autocomplete_tags',
            defaultValue=DEFAULT_SETTINGS['autocomplete_tags'], type=bool)
        if autocomplete_tags:
            self.completer = QCompleter(tag_counter_model)
            self.setCompleter(self.completer)
            self.completer.activated.connect(lambda text: self.add_tag(text))
            # Clear the input box after the completer inserts the tag into it.
            self.completer.activated.connect(
                lambda: QTimer.singleShot(0, self.clear))
        else:
            self.completer = None

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() not in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            super().keyPressEvent(event)
            return
        # If Ctrl+Enter is pressed and the completer is visible, add the first
        # tag in the completer popup.
        if (event.modifiers() == Qt.KeyboardModifier.ControlModifier
                and self.completer is not None
                and self.completer.popup().isVisible()):
            first_tag = self.completer.popup().model().data(
                self.completer.model().index(0, 0), Qt.ItemDataRole.EditRole)
            self.add_tag(first_tag)
        # Otherwise, add the tag in the input box.
        else:
            self.add_tag(self.text())
        self.clear()
        if self.completer is not None:
            self.completer.popup().hide()

    def add_tag(self, tag: str):
        if not tag:
            return
        tags = tag.split(self.tag_separator)
        selected_image_indices = self.image_list.get_selected_image_indices()
        selected_image_count = len(selected_image_indices)
        if len(tags) == 1 and selected_image_count == 1:
            # Add an empty tag and set it to the new tag.
            self.image_tag_list_model.insertRow(
                self.image_tag_list_model.rowCount())
            new_tag_index = self.image_tag_list_model.index(
                self.image_tag_list_model.rowCount() - 1)
            self.image_tag_list_model.setData(new_tag_index, tag)
            return
        if selected_image_count > 1:
            if len(tags) > 1:
                question = (f'Add tags to {selected_image_count} selected '
                            f'images?')
            else:
                question = (f'Add tag "{tags[0]}" to {selected_image_count} '
                            f'selected images?')
            reply = get_confirmation_dialog_reply(title='Add Tag',
                                                  question=question)
            if reply != QMessageBox.StandardButton.Yes:
                return
        self.tags_addition_requested.emit(tags, selected_image_indices)


class ImageTagsList(QListView):
    def __init__(self, image_tag_list_model: QStringListModel):
        super().__init__()
        self.image_tag_list_model = image_tag_list_model
        self.setModel(self.image_tag_list_model)
        self.setItemDelegate(TextEditItemDelegate(self))
        self.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setWordWrap(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)

    def keyPressEvent(self, event: QKeyEvent):
        """
        Delete selected tags when the delete key or backspace key is pressed.
        """
        if event.key() not in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            super().keyPressEvent(event)
            return
        rows_to_remove = [index.row() for index in self.selectedIndexes()]
        if not rows_to_remove:
            return
        remaining_tags = [tag for i, tag
                          in enumerate(self.image_tag_list_model.stringList())
                          if i not in rows_to_remove]
        self.image_tag_list_model.setStringList(remaining_tags)
        min_removed_row = min(rows_to_remove)
        remaining_row_count = self.image_tag_list_model.rowCount()
        if min_removed_row < remaining_row_count:
            self.select_tag(min_removed_row)
        elif remaining_row_count:
            # Select the last tag.
            self.select_tag(remaining_row_count - 1)

    def select_tag(self, row: int):
        # If the current index is not set, using the arrow keys to navigate
        # through the tags after selecting the tag will not work.
        self.setCurrentIndex(self.image_tag_list_model.index(row))
        self.selectionModel().select(
            self.image_tag_list_model.index(row),
            QItemSelectionModel.SelectionFlag.ClearAndSelect)


class ImageTagsEditor(QDockWidget):
    def __init__(self, proxy_image_list_model: ProxyImageListModel,
                 tag_counter_model: TagCounterModel,
                 image_tag_list_model: QStringListModel, image_list: ImageList,
                 tokenizer: PreTrainedTokenizerBase, tag_separator: str):
        super().__init__()
        self.proxy_image_list_model = proxy_image_list_model
        self.image_tag_list_model = image_tag_list_model
        self.tokenizer = tokenizer
        self.tag_separator = tag_separator
        self.image_index = None

        # Each `QDockWidget` needs a unique object name for saving its state.
        self.setObjectName('image_tags_editor')
        self.setWindowTitle('Image Tags')
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea
                             | Qt.DockWidgetArea.RightDockWidgetArea)

        # Create custom title bar with checkbox and standard buttons
        title_widget = QWidget()
        title_layout = QHBoxLayout(title_widget)
        title_layout.setContentsMargins(6, 2, 6, 2)
        title_layout.setSpacing(4)

        title_label = QLabel('Image Tags')
        self.descriptive_mode_checkbox = QCheckBox('Desc')
        self.descriptive_mode_checkbox.setToolTip('Descriptive Mode')

        # Grammar check button (hidden by default, shown in descriptive mode)
        self.grammar_check_button = QPushButton('✓')
        self.grammar_check_button.setToolTip('Check Grammar')
        self.grammar_check_button.setMaximumSize(24, 20)
        self.grammar_check_button.setFlat(True)
        self.grammar_check_button.setStyleSheet("""
            QPushButton {
                font-size: 16px;
                font-weight: bold;
                border: 1px solid #555;
                border-radius: 3px;
                background-color: #3a3a3a;
                padding: 2px;
                color: #4CAF50;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
                border-color: #4CAF50;
            }
            QPushButton:pressed {
                background-color: #2a2a2a;
            }
        """)
        self.grammar_check_button.hide()

        # Don't connect signals yet - will do it after creating all widgets

        # Create float and close buttons
        float_button = QPushButton()
        float_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarNormalButton))
        float_button.setFlat(True)
        float_button.setMaximumSize(16, 16)
        float_button.clicked.connect(lambda: self.setFloating(not self.isFloating()))

        close_button = QPushButton()
        close_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarCloseButton))
        close_button.setFlat(True)
        close_button.setMaximumSize(16, 16)
        close_button.clicked.connect(self.close)

        title_layout.addWidget(title_label)
        title_layout.addStretch()
        title_layout.addWidget(self.descriptive_mode_checkbox)
        title_layout.addWidget(self.grammar_check_button)
        title_layout.addWidget(float_button)
        title_layout.addWidget(close_button)

        self.setTitleBarWidget(title_widget)

        self.tag_input_box = TagInputBox(self.image_tag_list_model,
                                         tag_counter_model, image_list,
                                         tag_separator)
        self.image_tags_list = ImageTagsList(self.image_tag_list_model)

        # Descriptive text editor with spell/grammar checking (hidden by default)
        self.descriptive_text_edit = DescriptiveTextEdit()
        self.descriptive_text_edit.setPlaceholderText('Enter descriptive text with commas...')
        self.descriptive_text_edit.textChanged.connect(self.on_descriptive_text_changed)
        self.descriptive_text_edit.hide()

        self.token_count_label = QLabel()
        # A container widget is required to use a layout with a `QDockWidget`.
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.addWidget(self.tag_input_box)
        layout.addWidget(self.image_tags_list)
        layout.addWidget(self.descriptive_text_edit)
        layout.addWidget(self.token_count_label)
        self.setWidget(container)

        # When a tag is added, select it and scroll to the bottom of the list.
        self.image_tag_list_model.rowsInserted.connect(
            lambda _, __, last_index:
            self.image_tags_list.selectionModel().select(
                self.image_tag_list_model.index(last_index),
                QItemSelectionModel.SelectionFlag.ClearAndSelect))
        self.image_tag_list_model.rowsInserted.connect(
            self.image_tags_list.scrollToBottom)
        # `rowsInserted` does not have to be connected because `dataChanged`
        # is emitted when a tag is added.
        self.image_tag_list_model.modelReset.connect(self.count_tokens)
        self.image_tag_list_model.dataChanged.connect(self.count_tokens)

        # Now connect descriptive mode signals and load persistent state
        self.descriptive_mode_checkbox.toggled.connect(self.toggle_display_mode)
        self.descriptive_mode_checkbox.toggled.connect(self.save_descriptive_mode_state)

        # Connect grammar check button
        self.grammar_check_button.clicked.connect(self.descriptive_text_edit.check_grammar)

        # Load persistent state after all widgets are created and signals connected
        desc_mode_enabled = settings.value('descriptive_mode_enabled', False, type=bool)
        if desc_mode_enabled:
            # Setting checked will trigger toggle_display_mode via the signal
            self.descriptive_mode_checkbox.setChecked(True)

    @Slot()
    def count_tokens(self):
        caption = self.tag_separator.join(
            self.image_tag_list_model.stringList())
        # Subtract 2 for the `<|startoftext|>` and `<|endoftext|>` tokens.
        caption_token_count = len(self.tokenizer(caption).input_ids) - 2
        if caption_token_count > MAX_TOKEN_COUNT:
            self.token_count_label.setStyleSheet('color: red;')
        else:
            self.token_count_label.setStyleSheet('')
        self.token_count_label.setText(f'{caption_token_count} / '
                                       f'{MAX_TOKEN_COUNT} Tokens')

    @Slot()
    def select_first_tag(self):
        if self.image_tag_list_model.rowCount() == 0:
            return
        self.image_tags_list.select_tag(0)

    def select_last_tag(self):
        tag_count = self.image_tag_list_model.rowCount()
        if tag_count == 0:
            return
        self.image_tags_list.select_tag(tag_count - 1)

    @Slot()
    def load_image_tags(self, proxy_image_index: QModelIndex):
        self.image_index = self.proxy_image_list_model.mapToSource(
            proxy_image_index)
        image: Image = self.proxy_image_list_model.data(
            proxy_image_index, Qt.ItemDataRole.UserRole)
        # Safety check: if no image is selected or available, clear the tags
        if image is None:
            self.image_tag_list_model.setStringList([])
            return
        # If the string list already contains the image's tags, do not reload
        # them. This is the case when the tags are edited directly through the
        # image tags editor. Removing this check breaks the functionality of
        # reordering multiple tags at the same time because it gets interrupted
        # after one tag is moved.
        current_string_list = self.image_tag_list_model.stringList()
        if current_string_list == image.tags:
            return
        self.image_tag_list_model.setStringList(image.tags)
        self.count_tokens()
        # Update descriptive text if in descriptive mode
        if self.descriptive_mode_checkbox.isChecked():
            tags_text = self.tag_separator.join(image.tags)
            self.descriptive_text_edit.blockSignals(True)
            self.descriptive_text_edit.setPlainText(tags_text)
            self.descriptive_text_edit.blockSignals(False)
        if self.image_tags_list.hasFocus():
            self.select_first_tag()

    @Slot()
    def reload_image_tags_if_changed(self, first_changed_index: QModelIndex,
                                     last_changed_index: QModelIndex):
        """
        Reload the tags for the current image if its index is in the range of
        changed indices.
        """
        if (self.image_index and
            first_changed_index.row() <= self.image_index.row()
                <= last_changed_index.row()):
            proxy_image_index = self.proxy_image_list_model.mapFromSource(
                self.image_index)
            self.load_image_tags(proxy_image_index)

    @Slot(bool)
    def save_descriptive_mode_state(self, enabled: bool):
        """Save descriptive mode state to settings."""
        settings.setValue('descriptive_mode_enabled', enabled)

    @Slot(bool)
    def toggle_display_mode(self, descriptive_mode: bool):
        """Switch between tag list view and descriptive text view."""
        if descriptive_mode:
            # Switch to descriptive mode
            # Convert tag list to comma-separated text
            tags_text = self.tag_separator.join(
                self.image_tag_list_model.stringList())
            # Block signals to avoid triggering textChanged
            self.descriptive_text_edit.blockSignals(True)
            self.descriptive_text_edit.setPlainText(tags_text)
            self.descriptive_text_edit.blockSignals(False)
            # Hide tag list and input, show text edit
            self.tag_input_box.hide()
            self.image_tags_list.hide()
            self.descriptive_text_edit.show()

            # Always show grammar check button in descriptive mode
            # (will show error if grammar checker not available when clicked)
            self.grammar_check_button.show()
        else:
            # Switch to tag mode
            # Hide text edit and grammar button, show tag list and input
            self.descriptive_text_edit.hide()
            self.grammar_check_button.hide()
            self.tag_input_box.show()
            self.image_tags_list.show()

    @Slot()
    def on_descriptive_text_changed(self):
        """Sync changes from descriptive text back to tag list model."""
        if not self.descriptive_mode_checkbox.isChecked():
            return
        text = self.descriptive_text_edit.toPlainText()
        # Split by separator to get tags
        # Don't strip or filter - preserve exact user input
        if text:
            tags = text.split(self.tag_separator)
        else:
            tags = []
        # Update the model - this will trigger dataChanged and save to disk
        self.image_tag_list_model.setStringList(tags)
