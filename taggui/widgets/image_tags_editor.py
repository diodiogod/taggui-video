from typing import TYPE_CHECKING

from PySide6.QtCore import (QEvent, QItemSelectionModel, QModelIndex, QStringListModel,
                            QTimer, Qt, Signal, Slot)
from PySide6.QtGui import QCloseEvent, QKeyEvent, QIcon, QFont, QWheelEvent
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QCompleter, QDockWidget,
                               QHBoxLayout, QLabel, QLineEdit, QListView, QMessageBox,
                               QPushButton, QStackedWidget, QStyle, QToolButton,
                               QVBoxLayout, QWidget)

if TYPE_CHECKING:
    from transformers import PreTrainedTokenizerBase
else:
    PreTrainedTokenizerBase = object

from models.proxy_image_list_model import ProxyImageListModel
from models.tag_counter_model import TagCounterModel
from utils.image import Image
from utils.ideogram_caption import (
    IdeogramCaptionError,
    discover_ideogram_caption,
    ideogram_caption_chips,
    ideogram_caption_path,
)
from utils.settings import DEFAULT_SETTINGS, settings
from utils.text_edit_item_delegate import TextEditItemDelegate
from utils.utils import get_confirmation_dialog_reply
from widgets.image_list import ImageList
from widgets.descriptive_text_edit import DescriptiveTextEdit

MAX_TOKEN_COUNT = 75
INTERNAL_HIDDEN_TAGS = {"__no_tags__"}


class TagInputBox(QLineEdit):
    tags_addition_requested = Signal(list, list)
    ideogram_tags_addition_requested = Signal(list)

    def __init__(self, image_tag_list_model: QStringListModel,
                 tag_counter_model: TagCounterModel, image_list: ImageList,
                 tag_separator: str):
        super().__init__()
        self.image_tag_list_model = image_tag_list_model
        self.image_list = image_list
        self.tag_separator = tag_separator
        self.caption_mode = 'tags'

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

    def set_caption_mode(self, caption_mode: str):
        self.caption_mode = caption_mode
        if caption_mode == 'ideogram':
            self.setPlaceholderText('Add Ideogram object caption')
        else:
            self.setPlaceholderText('Add Tag')

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
        if self.caption_mode == 'ideogram':
            normalized_tags = [tag.strip() for tag in tags if tag.strip()]
            if normalized_tags:
                self.ideogram_tags_addition_requested.emit(normalized_tags)
            return
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
    def __init__(
        self,
        image_tag_list_model: QStringListModel,
        deletion_requested=None,
        *,
        lightweight_zoom: bool = False,
    ):
        super().__init__()
        self.image_tag_list_model = image_tag_list_model
        self.deletion_requested = deletion_requested
        self.lightweight_zoom = lightweight_zoom
        self.setModel(self.image_tag_list_model)
        self.delegate = TextEditItemDelegate(self)
        self.setItemDelegate(self.delegate)
        self.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setWordWrap(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)

        # Initialize tag list zoom level from settings
        self.min_zoom = 50  # Percent
        self.max_zoom = 300  # Percent
        self.zoom_step = 10  # Percent per scroll step
        self.current_zoom = settings.value(
            'tag_list_zoom',
            defaultValue=DEFAULT_SETTINGS.get('tag_list_zoom', 100),
            type=int)
        self.current_zoom = max(self.min_zoom,
                                min(self.max_zoom, self.current_zoom))
        self._apply_zoom(self.current_zoom)

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
        if self.deletion_requested is not None:
            self.deletion_requested(sorted(set(rows_to_remove)))
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

    def wheelEvent(self, event: QWheelEvent):
        """Handle Ctrl+scroll wheel for zooming tag list (font and row height)."""
        if event.modifiers() == Qt.ControlModifier:
            # Get scroll direction
            delta = event.angleDelta().y()

            # Adjust zoom level
            if delta > 0:
                # Scroll up = zoom in (larger tags)
                new_zoom = min(self.current_zoom + self.zoom_step, self.max_zoom)
            else:
                # Scroll down = zoom out (smaller tags)
                new_zoom = max(self.current_zoom - self.zoom_step, self.min_zoom)

            if new_zoom != self.current_zoom:
                self.current_zoom = new_zoom
                self._apply_zoom(self.current_zoom)
                # Save to settings
                settings.setValue('tag_list_zoom', self.current_zoom)
            event.accept()
        else:
            super().wheelEvent(event)

    def _apply_zoom(self, zoom_percent: int):
        """Apply zoom level to tag list (scales font and row heights)."""
        # Scale font size based on zoom percentage
        base_font_size = 10
        scaled_font_size = int(base_font_size * zoom_percent / 100)
        font = QFont(self.font())
        font.setPointSize(max(8, min(32, scaled_font_size)))
        self.setFont(font)

        # Update delegate's zoom multiplier for row height scaling
        self.delegate.set_zoom_multiplier(zoom_percent)

        if self.lightweight_zoom:
            self.doItemsLayout()
            self.viewport().update()
            return

        # Reset all row heights to trigger recalculation with new zoom
        for row in range(self.model().rowCount()):
            self.openPersistentEditor(self.model().index(row, 0))
            self.closePersistentEditor(self.model().index(row, 0))


class ImageTagsEditor(QDockWidget):
    ideogram_element_selected = Signal(int)
    ideogram_object_add_requested = Signal(str)
    ideogram_element_text_changed = Signal(int, str, str)
    ideogram_elements_delete_requested = Signal(list)
    ideogram_json_text_changed = Signal(str)

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
        self._pending_descriptive_tags: list[str] | None = None
        self._descriptive_dirty = False
        self._descriptive_sync_delay_ms = 450
        self._loading_ideogram_chips = False
        self._ideogram_entries: list[tuple[str, int | None]] = []
        self._caption_mode = 'tags'
        self._ideogram_available = False
        self._ideogram_json_dirty = False

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

        self.tags_mode_button = QPushButton('Image Tags')
        self.tags_mode_button.setCheckable(True)
        self.tags_mode_button.setChecked(True)
        self.tags_mode_button.setFlat(True)
        self.tags_mode_button.setCursor(Qt.CursorShape.ArrowCursor)
        self.ideogram_mode_button = QPushButton('Ideogram')
        self.ideogram_mode_button.setCheckable(True)
        self.ideogram_mode_button.setFlat(True)
        self.ideogram_mode_button.hide()
        self._apply_caption_mode_title_style()
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

        title_layout.addWidget(self.tags_mode_button)
        title_layout.addWidget(self.ideogram_mode_button)
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
        self.ideogram_tag_list_model = QStringListModel()
        self.ideogram_caption_list = ImageTagsList(
            self.ideogram_tag_list_model,
            deletion_requested=self._request_ideogram_rows_delete,
            lightweight_zoom=True,
        )
        self.ideogram_caption_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.ideogram_caption_list.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.ideogram_tag_list_model.dataChanged.connect(
            self._on_ideogram_caption_model_changed
        )

        # Descriptive text editor with spell/grammar checking (hidden by default)
        self.descriptive_text_edit = DescriptiveTextEdit()
        self.descriptive_text_edit.setPlaceholderText('Enter descriptive text with commas...')
        self.descriptive_text_edit.textChanged.connect(self.on_descriptive_text_changed)
        self.descriptive_text_edit.hide()
        self.descriptive_text_edit.installEventFilter(self)
        self._descriptive_sync_timer = QTimer(self)
        self._descriptive_sync_timer.setSingleShot(True)
        self._descriptive_sync_timer.timeout.connect(self._apply_pending_descriptive_sync)
        self.ideogram_json_text_edit = DescriptiveTextEdit()
        self.ideogram_json_text_edit.setPlaceholderText('Ideogram JSON caption')
        self.ideogram_json_text_edit.textChanged.connect(self.on_ideogram_json_text_changed)
        self.ideogram_json_text_edit.installEventFilter(self)
        self._ideogram_json_sync_timer = QTimer(self)
        self._ideogram_json_sync_timer.setSingleShot(True)
        self._ideogram_json_sync_timer.timeout.connect(self._apply_pending_ideogram_json_sync)

        self.caption_stack = QStackedWidget()
        self.caption_stack.addWidget(self.image_tags_list)
        self.caption_stack.addWidget(self.descriptive_text_edit)
        self.caption_stack.addWidget(self.ideogram_caption_list)
        self.caption_stack.addWidget(self.ideogram_json_text_edit)

        self.token_count_label = QLabel()
        # A container widget is required to use a layout with a `QDockWidget`.
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.addWidget(self.tag_input_box)
        layout.addWidget(self.caption_stack)
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
        self.tag_input_box.ideogram_tags_addition_requested.connect(
            self._request_ideogram_object_add
        )
        self.tags_mode_button.clicked.connect(lambda: self.set_caption_mode('tags'))
        self.ideogram_mode_button.clicked.connect(lambda: self.set_caption_mode('ideogram'))
        self.ideogram_caption_list.selectionModel().currentChanged.connect(
            self._on_ideogram_caption_current_changed
        )

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
        caption = self.tag_separator.join(self.image_tag_list_model.stringList())
        self._set_token_count_from_caption(caption)

    def _set_token_count_from_caption(self, caption: str):
        # Subtract 2 for the `<|startoftext|>` and `<|endoftext|>` tokens.
        caption_token_count = len(self.tokenizer(caption).input_ids) - 2
        if caption_token_count > MAX_TOKEN_COUNT:
            self.token_count_label.setStyleSheet('color: red;')
        else:
            self.token_count_label.setStyleSheet('')
        self.token_count_label.setText(f'{caption_token_count} / '
                                       f'{MAX_TOKEN_COUNT} Tokens')

    def _tags_from_descriptive_text(self, text: str) -> list[str]:
        if text:
            return self._filter_internal_tags(text.split(self.tag_separator))
        return []

    def _filter_internal_tags(self, tags: list[str] | None) -> list[str]:
        """Remove internal sentinel tags from the user-visible editor."""
        if not tags:
            return []
        normalized_tags: list[str] = []
        for tag in tags:
            cleaned = str(tag).strip()
            if not cleaned or cleaned in INTERNAL_HIDDEN_TAGS:
                continue
            normalized_tags.append(cleaned)
        return normalized_tags

    def _read_caption_text_from_disk(self, image: Image) -> str | None:
        """Read the sidecar caption text exactly as stored on disk."""
        text_file_path = image.path.with_suffix('.txt')
        if not text_file_path.exists():
            return None
        try:
            return text_file_path.read_text(encoding='utf-8', errors='replace')
        except OSError:
            return None

    def _read_ideogram_json_text_from_disk(self, image: Image) -> str:
        try:
            caption = discover_ideogram_caption(image.path)
        except IdeogramCaptionError:
            path = ideogram_caption_path(image.path)
            if path.exists():
                try:
                    return path.read_text(encoding='utf-8', errors='replace')
                except OSError:
                    return ''
            return ''
        if caption is None:
            return ''
        return caption.to_json(pretty=True)

    def _set_ideogram_caption_chips_for_image(self, image: Image | None):
        self._loading_ideogram_chips = True
        self._ideogram_entries = []
        self.ideogram_tag_list_model.setStringList([])
        self.ideogram_json_text_edit.blockSignals(True)
        self.ideogram_json_text_edit.setPlainText('')
        self.ideogram_json_text_edit.blockSignals(False)
        if image is None:
            self._set_ideogram_available(False)
            self._loading_ideogram_chips = False
            return

        try:
            caption = discover_ideogram_caption(image.path)
        except IdeogramCaptionError as exc:
            self.ideogram_tag_list_model.setStringList([f'Invalid Ideogram JSON: {exc}'])
            self.ideogram_json_text_edit.blockSignals(True)
            self.ideogram_json_text_edit.setPlainText(self._read_ideogram_json_text_from_disk(image))
            self.ideogram_json_text_edit.blockSignals(False)
            self._set_ideogram_available(True)
            self._loading_ideogram_chips = False
            return

        if caption is None:
            self._set_ideogram_available(False)
            self._loading_ideogram_chips = False
            return

        rows: list[str] = []
        for chip in ideogram_caption_chips(caption):
            rows.append(chip.text)
            self._ideogram_entries.append((chip.kind, chip.element_index))
        self.ideogram_tag_list_model.setStringList(rows)
        self.ideogram_json_text_edit.blockSignals(True)
        self.ideogram_json_text_edit.setPlainText(caption.to_json(pretty=True))
        self.ideogram_json_text_edit.blockSignals(False)
        self._set_ideogram_available(True)
        self._loading_ideogram_chips = False

    def _set_ideogram_available(self, available: bool):
        self._ideogram_available = bool(available)
        self.ideogram_mode_button.setVisible(self._ideogram_available)
        self._apply_caption_mode_title_style()
        if not self._ideogram_available and self._caption_mode == 'ideogram':
            self.set_caption_mode('tags')
        else:
            self._sync_caption_mode_widgets()

    def _apply_caption_mode_title_style(self):
        if not getattr(self, '_ideogram_available', False):
            self.tags_mode_button.setStyleSheet("""
                QPushButton {
                    padding: 0 2px;
                    border: none;
                    background: transparent;
                    font-weight: 600;
                    text-align: left;
                }
                QPushButton:hover {
                    background: transparent;
                }
            """)
            self.tags_mode_button.setCursor(Qt.CursorShape.ArrowCursor)
            self.ideogram_mode_button.setStyleSheet("")
            return

        tab_style = """
            QPushButton {
                padding: 2px 8px;
                border: none;
                border-bottom: 2px solid transparent;
                background: transparent;
                font-weight: 600;
            }
            QPushButton:checked {
                border-bottom-color: #7a7a7a;
            }
            QPushButton:hover {
                background: #2d2d2d;
            }
        """
        self.tags_mode_button.setStyleSheet(tab_style)
        self.ideogram_mode_button.setStyleSheet(tab_style)
        self.tags_mode_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ideogram_mode_button.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_caption_mode(self, caption_mode: str):
        if caption_mode == 'ideogram' and not self._ideogram_available:
            caption_mode = 'tags'
        self._caption_mode = caption_mode
        self.tags_mode_button.setChecked(caption_mode == 'tags')
        self.ideogram_mode_button.setChecked(caption_mode == 'ideogram')
        self.tag_input_box.set_caption_mode(caption_mode)
        self._sync_caption_mode_widgets()

    def _sync_caption_mode_widgets(self):
        descriptive_mode = self.descriptive_mode_checkbox.isChecked()
        if self._caption_mode == 'ideogram':
            self.descriptive_mode_checkbox.setText('JSON')
            self.descriptive_mode_checkbox.setToolTip('Show raw Ideogram JSON')
            self.caption_stack.setCurrentWidget(
                self.ideogram_json_text_edit
                if descriptive_mode
                else self.ideogram_caption_list
            )
            self.grammar_check_button.setVisible(False)
            return
        self.descriptive_mode_checkbox.setText('Desc')
        self.descriptive_mode_checkbox.setToolTip('Descriptive Mode')
        self.caption_stack.setCurrentWidget(
            self.descriptive_text_edit
            if descriptive_mode
            else self.image_tags_list
        )
        self.grammar_check_button.setVisible(descriptive_mode)

    def _on_ideogram_caption_current_changed(self, current: QModelIndex, _previous: QModelIndex):
        if not current.isValid():
            return
        if current.row() >= len(self._ideogram_entries):
            return
        _, element_index = self._ideogram_entries[current.row()]
        if element_index is not None:
            self.ideogram_element_selected.emit(int(element_index))

    def _on_ideogram_caption_model_changed(self, top_left: QModelIndex, bottom_right: QModelIndex):
        if self._loading_ideogram_chips:
            return
        rows = self.ideogram_tag_list_model.stringList()
        for row in range(top_left.row(), bottom_right.row() + 1):
            if row < 0 or row >= len(self._ideogram_entries) or row >= len(rows):
                continue
            kind, element_index = self._ideogram_entries[row]
            if element_index is None or kind not in {'object', 'text'}:
                continue
            self.ideogram_element_text_changed.emit(
                int(element_index),
                str(kind),
                rows[row].strip(),
            )

    def _request_ideogram_object_add(self, tags: list[str]):
        for tag in tags:
            text = str(tag).strip()
            if text:
                self.ideogram_object_add_requested.emit(text)

    def _request_ideogram_rows_delete(self, rows: list[int]):
        element_indices = []
        for row in rows:
            if row < 0 or row >= len(self._ideogram_entries):
                continue
            _, element_index = self._ideogram_entries[row]
            if element_index is not None and element_index not in element_indices:
                element_indices.append(element_index)
        if element_indices:
            self.ideogram_elements_delete_requested.emit(element_indices)

    def _emit_source_row_data_changed(self, source_model):
        """Refresh the current row after a passive sidecar sync."""
        if source_model is None or not self.image_index.isValid():
            return
        try:
            source_model.dataChanged.emit(
                self.image_index,
                self.image_index,
                [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.UserRole],
            )
        except Exception:
            pass

    def _apply_pending_descriptive_sync(self):
        """Apply staged descriptive-text edits to the tag list model."""
        if not self._descriptive_dirty or self._pending_descriptive_tags is None:
            return
        tags = self._pending_descriptive_tags
        self._pending_descriptive_tags = None
        self._descriptive_dirty = False
        if tags != self.image_tag_list_model.stringList():
            self.image_tag_list_model.setStringList(tags)

    def _flush_descriptive_sync(self):
        """Force-apply staged descriptive edits immediately."""
        if self._descriptive_sync_timer.isActive():
            self._descriptive_sync_timer.stop()
        self._apply_pending_descriptive_sync()

    def _apply_pending_ideogram_json_sync(self):
        if not self._ideogram_json_dirty:
            return
        self._ideogram_json_dirty = False
        self.ideogram_json_text_changed.emit(
            self.ideogram_json_text_edit.toPlainText()
        )

    def _flush_ideogram_json_sync(self):
        if self._ideogram_json_sync_timer.isActive():
            self._ideogram_json_sync_timer.stop()
        self._apply_pending_ideogram_json_sync()

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
        # Persist pending edits for the previous image before switching index.
        self._flush_descriptive_sync()
        self._flush_ideogram_json_sync()
        self.image_index = self.proxy_image_list_model.mapToSource(
            proxy_image_index)
        source_model = self.proxy_image_list_model.sourceModel()
        image: Image = self.proxy_image_list_model.data(
            proxy_image_index, Qt.ItemDataRole.UserRole)
        # Safety check: if no image is selected or available, clear the tags
        if image is None:
            self.image_tag_list_model.setStringList([])
            self._set_ideogram_caption_chips_for_image(None)
            return
        self._set_ideogram_caption_chips_for_image(image)
        caption_text = self._read_caption_text_from_disk(image)
        tags_from_source = (
            self._tags_from_descriptive_text(caption_text)
            if caption_text is not None
            else self._filter_internal_tags(image.tags)
        )
        should_refresh_source_row = False
        # Keep the in-memory image tags aligned with the sidecar source of truth.
        if image.tags != tags_from_source:
            image.tags = tags_from_source
            should_refresh_source_row = bool(self.image_index.isValid())
            if (source_model is not None
                    and getattr(source_model, '_paginated_mode', False)
                    and hasattr(source_model, '_sync_paginated_db_tags_for_rel_path')
                    and getattr(source_model, '_directory_path', None) is not None):
                try:
                    rel_path = str(image.path.relative_to(source_model._directory_path))
                    # Selection-time sidecar sync should only refresh this row.
                    # Full paginated reloads are reserved for bulk tag edits.
                    source_model._sync_paginated_db_tags_for_rel_path(
                        rel_path,
                        tags_from_source,
                        txt_path=image.path.with_suffix('.txt'),
                    )
                except Exception:
                    pass
        # If the string list already contains the image's tags, do not reload
        # them. This is the case when the tags are edited directly through the
        # image tags editor. Removing this check breaks the functionality of
        # reordering multiple tags at the same time because it gets interrupted
        # after one tag is moved.
        current_string_list = self.image_tag_list_model.stringList()
        if current_string_list == tags_from_source:
            if self.descriptive_mode_checkbox.isChecked() and caption_text is not None:
                self.descriptive_text_edit.blockSignals(True)
                self.descriptive_text_edit.setPlainText(caption_text)
                self.descriptive_text_edit.blockSignals(False)
            if should_refresh_source_row:
                self._emit_source_row_data_changed(source_model)
            return
        self.image_tag_list_model.setStringList(tags_from_source)
        self.count_tokens()
        self._pending_descriptive_tags = None
        self._descriptive_dirty = False
        # Update descriptive text if in descriptive mode
        if self.descriptive_mode_checkbox.isChecked():
            tags_text = (
                caption_text
                if caption_text is not None
                else self.tag_separator.join(tags_from_source)
            )
            self.descriptive_text_edit.blockSignals(True)
            self.descriptive_text_edit.setPlainText(tags_text)
            self.descriptive_text_edit.blockSignals(False)
        if self.image_tags_list.hasFocus():
            self.select_first_tag()
        if should_refresh_source_row:
            self._emit_source_row_data_changed(source_model)

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

    def reload_ideogram_caption_for_current_image(self):
        if not self.image_index or not self.image_index.isValid():
            self._set_ideogram_caption_chips_for_image(None)
            return
        proxy_index = self.proxy_image_list_model.mapFromSource(self.image_index)
        image: Image = self.proxy_image_list_model.data(
            proxy_index,
            Qt.ItemDataRole.UserRole,
        )
        self._set_ideogram_caption_chips_for_image(image)

    @Slot(bool)
    def save_descriptive_mode_state(self, enabled: bool):
        """Save descriptive mode state to settings."""
        settings.setValue('descriptive_mode_enabled', enabled)

    @Slot(bool)
    def toggle_display_mode(self, descriptive_mode: bool):
        """Switch between tag list view and descriptive text view."""
        if descriptive_mode:
            self._pending_descriptive_tags = None
            self._descriptive_dirty = False
            self._descriptive_sync_timer.stop()
            # Switch to descriptive mode
            # Prefer exact sidecar caption text to avoid any model-order drift.
            tags_text = self.tag_separator.join(self.image_tag_list_model.stringList())
            if self.image_index and self.image_index.isValid():
                proxy_index = self.proxy_image_list_model.mapFromSource(self.image_index)
                image: Image = self.proxy_image_list_model.data(
                    proxy_index, Qt.ItemDataRole.UserRole)
                if image is not None:
                    caption_text = self._read_caption_text_from_disk(image)
                    if caption_text is not None:
                        tags_text = caption_text
            # Block signals to avoid triggering textChanged
            self.descriptive_text_edit.blockSignals(True)
            self.descriptive_text_edit.setPlainText(tags_text)
            self.descriptive_text_edit.blockSignals(False)
        else:
            # Switch to tag mode
            # Sync descriptive text back to tags before hiding
            self._flush_descriptive_sync()
            self._flush_ideogram_json_sync()
            tags = self._tags_from_descriptive_text(
                self.descriptive_text_edit.toPlainText()
            )
            if tags != self.image_tag_list_model.stringList():
                self.image_tag_list_model.setStringList(tags)
        self._sync_caption_mode_widgets()

    @Slot()
    def on_descriptive_text_changed(self):
        """Stage descriptive text changes for later sync."""
        if (not self.descriptive_mode_checkbox.isChecked()
                or self._caption_mode != 'tags'):
            return
        text = self.descriptive_text_edit.toPlainText()
        tags = self._tags_from_descriptive_text(text)
        self._pending_descriptive_tags = tags
        self._descriptive_dirty = True
        # Keep other caption views coherent while avoiding per-keystroke churn.
        self._descriptive_sync_timer.start(self._descriptive_sync_delay_ms)

    @Slot()
    def on_ideogram_json_text_changed(self):
        if (not self.descriptive_mode_checkbox.isChecked()
                or self._caption_mode != 'ideogram'):
            return
        self._ideogram_json_dirty = True
        self._ideogram_json_sync_timer.start(self._descriptive_sync_delay_ms)

    def eventFilter(self, watched, event):
        if (watched is self.descriptive_text_edit
                and event.type() == QEvent.Type.FocusOut):
            self._flush_descriptive_sync()
        if (watched is self.ideogram_json_text_edit
                and event.type() == QEvent.Type.FocusOut):
            self._flush_ideogram_json_sync()
        return super().eventFilter(watched, event)

    def closeEvent(self, event: QCloseEvent):
        self._flush_descriptive_sync()
        self._flush_ideogram_json_sync()
        super().closeEvent(event)
