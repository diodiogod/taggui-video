from typing import TYPE_CHECKING

from PySide6.QtCore import (QEvent, QItemSelectionModel, QModelIndex, QStringListModel,
                            QPoint, QRectF, QTimer, Qt, Signal, Slot)
from PySide6.QtGui import (QColor, QCloseEvent, QKeyEvent, QIcon, QFont,
                           QMouseEvent, QPainter, QPalette, QPen, QTextCursor,
                           QWheelEvent)
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QCompleter, QDockWidget,
                               QHBoxLayout, QLabel, QLineEdit, QListView,
                               QMenu, QMessageBox, QPushButton, QStackedWidget, QStyle,
                               QStyleOptionViewItem, QToolButton, QVBoxLayout, QWidget)

if TYPE_CHECKING:
    from transformers import PreTrainedTokenizerBase
else:
    PreTrainedTokenizerBase = object

from models.proxy_image_list_model import ProxyImageListModel
from models.tag_counter_model import TagCounterModel
from utils.image import Image
from utils.caption_annotations import (
    caption_attention_counts,
    included_caption_tags,
    load_caption_workspace,
    merge_caption_entries_with_disk_tags,
    normalize_caption_entries,
)
from utils.ideogram_caption import (
    IdeogramCaptionError,
    discover_ideogram_caption,
    ideogram_caption_chips,
    ideogram_caption_path,
)
from utils.settings import DEFAULT_SETTINGS, settings
from utils.spatial_caption import (
    apply_spatial_action,
    has_spatial_expression,
    spatial_expression_spans,
    spatial_gesture_actions,
    spatial_reference_label,
)
from utils.text_transform import TextTransformOptions, transform_text
from utils.text_edit_item_delegate import TextEditItemDelegate
from utils.utils import get_confirmation_dialog_reply
from widgets.image_list import ImageList
from widgets.descriptive_text_edit import DescriptiveTextEdit

MAX_TOKEN_COUNT = 75
INTERNAL_HIDDEN_TAGS = {"__no_tags__"}


class TagInputBox(QLineEdit):
    tags_addition_requested = Signal(list, object)
    ideogram_tags_addition_requested = Signal(list)

    def __init__(self, image_tag_list_model: QStringListModel,
                 tag_counter_model: TagCounterModel, image_list: ImageList,
                 tag_separator: str):
        super().__init__()
        self.image_tag_list_model = image_tag_list_model
        self.image_list = image_list
        self.tag_separator = tag_separator
        self.current_image_reference_getter = None
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
        selected_images = self.image_list.list_view.get_selected_image_batch()
        selected_image_count = len(selected_images)
        if selected_image_count == 0:
            # The displayed image may have just left an active filter (for
            # example tags:=0) after the previous tag was saved. Continue
            # editing the panel's stable image instead of dropping the tag
            # because the filtered list no longer reports a selection.
            getter = self.current_image_reference_getter
            current_image = getter() if callable(getter) else None
            if current_image is not None:
                current_tags = self.image_tag_list_model.stringList()
                additions = [
                    value for value in tags
                    if value and value not in current_tags
                ]
                if additions:
                    self.image_tag_list_model.setStringList(
                        current_tags + additions
                    )
                return
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
        self.tags_addition_requested.emit(tags, selected_images)


class IdeogramCaptionItemDelegate(TextEditItemDelegate):
    PLACEHOLDERS = {
        'High-level description...',
        'Background...',
    }

    def paint(self, painter, option, index):
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or '')
        if text not in self.PLACEHOLDERS:
            super().paint(painter, option, index)
            return

        paint_option = QStyleOptionViewItem(option)
        paint_option.font.setItalic(True)
        paint_option.palette.setColor(QPalette.ColorRole.Text, QColor('#8a8f98'))
        paint_option.palette.setColor(
            QPalette.ColorRole.HighlightedText,
            QColor('#c2c7d0'),
        )
        super().paint(painter, paint_option, index)


class CaptionStatusItemDelegate(TextEditItemDelegate):
    """Keep ordinary tags unchanged and style only explicitly classified rows."""

    def paint(self, painter, option, index):
        owner = self.parent()
        status_getter = getattr(owner, 'caption_status_for_row', None)
        status = status_getter(index.row()) if callable(status_getter) else {}
        if not status or not (
            status.get('needs_review')
            or status.get('excluded')
            or status.get('directional_attention')
        ):
            super().paint(painter, option, index)
            return
        paint_option = QStyleOptionViewItem(option)
        if status.get('excluded'):
            font = QFont(paint_option.font)
            font.setStrikeOut(True)
            paint_option.font = font
            paint_option.palette.setColor(QPalette.ColorRole.Text, QColor('#8a8f98'))
            paint_option.palette.setColor(QPalette.ColorRole.HighlightedText, QColor('#c2c7d0'))
        elif status.get('needs_review') or status.get('directional_attention'):
            paint_option.palette.setColor(QPalette.ColorRole.Text, QColor('#F59E0B'))
            paint_option.palette.setColor(QPalette.ColorRole.HighlightedText, QColor('#FFE0A3'))
        super().paint(painter, paint_option, index)
        if (status.get('directional_attention') and settings.value(
                'spatial_gestures_enabled',
                DEFAULT_SETTINGS['spatial_gestures_enabled'],
                type=bool)):
            painter.save()
            painter.setPen(QPen(QColor('#F59E0B'), 1.5))
            handle_rect = QRectF(
                option.rect.right() - 19,
                option.rect.center().y() - 8,
                16,
                16,
            )
            painter.drawEllipse(handle_rect)
            painter.drawText(handle_rect, Qt.AlignmentFlag.AlignCenter, '↔')
            painter.restore()


class SpatialGestureOverlay(QWidget):
    LABELS = {
        'word_left': 'BODY LEFT',
        'word_right': 'BODY RIGHT',
        'frame_left': 'FRAME LEFT',
        'frame_right': 'FRAME RIGHT',
        'background': 'BACKGROUND',
        'foreground': 'FOREGROUND',
        'background_left': 'BACKGROUND · FRAME LEFT',
        'background_right': 'BACKGROUND · FRAME RIGHT',
        'foreground_left': 'FOREGROUND · FRAME LEFT',
        'foreground_right': 'FOREGROUND · FRAME RIGHT',
    }

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.center = QPoint()
        self.action = None
        self.preview = ''
        self.allowed_actions = set()
        self.hide()

    def begin(self, center: QPoint, allowed_actions: set[str]):
        self.center = center
        self.allowed_actions = allowed_actions
        self.action = None
        self.preview = ''
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self.update()

    def choose(self, position: QPoint, source_text: str) -> str | None:
        dx = position.x() - self.center.x()
        dy = position.y() - self.center.y()
        distance = (dx * dx + dy * dy) ** 0.5
        action = None
        if distance >= 14:
            horizontal = abs(dx) > abs(dy) * 1.45
            vertical = abs(dy) > abs(dx) * 1.45
            if 'word_left' in self.allowed_actions and horizontal:
                if distance < 68:
                    action = 'word_right' if dx > 0 else 'word_left'
                else:
                    action = 'frame_right' if dx > 0 else 'frame_left'
            elif horizontal:
                action = 'frame_right' if dx > 0 else 'frame_left'
            elif vertical:
                action = 'foreground' if dy > 0 else 'background'
            else:
                depth = 'foreground' if dy > 0 else 'background'
                side = 'right' if dx > 0 else 'left'
                action = f'{depth}_{side}'
        if action not in self.allowed_actions:
            action = None
        self.action = action
        self.preview = apply_spatial_action(source_text, action) if action else ''
        self.update()
        return action

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(245, 158, 11, 210), 2))
        painter.setBrush(QColor(25, 25, 25, 225))
        painter.drawEllipse(self.center, 104, 104)
        painter.setPen(QPen(QColor(115, 115, 115, 210), 1))
        painter.drawEllipse(self.center, 68, 68)
        painter.drawEllipse(self.center, 14, 14)

        painter.setPen(QColor('#f2f2f2'))
        font = painter.font()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        reference = spatial_reference_label()
        labels = [
            (f'{reference}-L', -87, 4), (f'{reference}-R', 87, 4),
        ]
        if 'word_left' in self.allowed_actions:
            labels.extend([('LEFT', -44, 4), ('RIGHT', 44, 4)])
        if 'background' in self.allowed_actions:
            labels.append(('BACKGROUND', 0, -84))
        if 'foreground' in self.allowed_actions:
            labels.append(('FOREGROUND', 0, 88))
        for label, x, y in labels:
            painter.drawText(
                QRectF(self.center.x() + x - 35, self.center.y() + y - 10, 70, 20),
                Qt.AlignmentFlag.AlignCenter,
                label,
            )
        if self.action:
            painter.setPen(QPen(QColor('#8ab4f8'), 4))
            painter.drawEllipse(self.center, 108, 108)
            preview_rect = QRectF(
                max(4, self.center.x() - 180),
                max(4, self.center.y() - 142),
                360,
                42,
            )
            painter.setPen(QColor('#ffffff'))
            painter.setBrush(QColor(20, 20, 20, 235))
            painter.drawRoundedRect(preview_rect, 5, 5)
            preview = self.preview
            if len(preview) > 90:
                preview = preview[:87] + '…'
            painter.drawText(
                preview_rect.adjusted(6, 3, -6, -3),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                f'{self._action_label(self.action)}\n{preview}',
            )

    def _action_label(self, action: str) -> str:
        label = self.LABELS[action]
        return label.replace('FRAME', spatial_reference_label())


class ImageTagsList(QListView):
    spatial_gesture_requested = Signal(int, str)

    def __init__(
        self,
        image_tag_list_model: QStringListModel,
        deletion_requested=None,
        *,
        lightweight_zoom: bool = False,
        delegate_cls=TextEditItemDelegate,
    ):
        super().__init__()
        self.image_tag_list_model = image_tag_list_model
        self.deletion_requested = deletion_requested
        self.lightweight_zoom = lightweight_zoom
        self.setModel(self.image_tag_list_model)
        self.delegate = delegate_cls(self)
        self.setItemDelegate(self.delegate)
        self.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setWordWrap(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._spatial_gesture_row = -1
        self._spatial_gesture_source = ''
        self._spatial_gesture_overlay = SpatialGestureOverlay(self.viewport())

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

    def _direction_handle_hit(self, position: QPoint):
        if not settings.value(
            'spatial_gestures_enabled',
            DEFAULT_SETTINGS['spatial_gestures_enabled'],
            type=bool,
        ):
            return QModelIndex()
        index = self.indexAt(position)
        if not index.isValid():
            return QModelIndex()
        status_getter = getattr(self, 'caption_status_for_row', None)
        status = status_getter(index.row()) if callable(status_getter) else {}
        if not status.get('directional_attention'):
            return QModelIndex()
        rect = self.visualRect(index)
        if position.x() < rect.right() - 26:
            return QModelIndex()
        return index

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            position = event.position().toPoint()
            index = self._direction_handle_hit(position)
            if index.isValid():
                source = str(index.data(Qt.ItemDataRole.DisplayRole) or '')
                allowed = spatial_gesture_actions(source)
                if allowed:
                    self._spatial_gesture_row = index.row()
                    self._spatial_gesture_source = source
                    self._spatial_gesture_overlay.begin(position, allowed)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._spatial_gesture_row >= 0:
            self._spatial_gesture_overlay.choose(
                event.position().toPoint(),
                self._spatial_gesture_source,
            )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._spatial_gesture_row >= 0:
            row = self._spatial_gesture_row
            action = self._spatial_gesture_overlay.action
            self._spatial_gesture_row = -1
            self._spatial_gesture_source = ''
            self._spatial_gesture_overlay.hide()
            if action:
                self.spatial_gesture_requested.emit(row, action)
            event.accept()
            return
        super().mouseReleaseEvent(event)

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


class IdeogramCaptionList(ImageTagsList):
    element_drop_requested = Signal(int, int)

    def dropEvent(self, event):
        selected_indexes = self.selectedIndexes()
        if len(selected_indexes) != 1:
            event.ignore()
            return
        source_row = selected_indexes[0].row()
        target_row = self._drop_target_row(event)
        self.element_drop_requested.emit(source_row, target_row)
        event.acceptProposedAction()

    def _drop_target_row(self, event) -> int:
        try:
            position = event.position().toPoint()
        except AttributeError:
            position = event.pos()
        index = self.indexAt(position)
        if not index.isValid():
            return self.model().rowCount()

        row = index.row()
        indicator = self.dropIndicatorPosition()
        if indicator == QAbstractItemView.DropIndicatorPosition.BelowItem:
            return row + 1
        if indicator == QAbstractItemView.DropIndicatorPosition.OnViewport:
            return self.model().rowCount()
        return row


class ImageTagsEditor(QDockWidget):
    ideogram_element_selected = Signal(int)
    ideogram_caption_create_requested = Signal()
    ideogram_region_add_requested = Signal(str, str)
    ideogram_element_text_changed = Signal(int, str, str)
    ideogram_element_type_change_requested = Signal(int, str)
    ideogram_element_move_requested = Signal(int, int)
    ideogram_elements_delete_requested = Signal(list)
    ideogram_json_text_changed = Signal(str)
    ideogram_global_field_changed = Signal(str, str)
    ideogram_editor_open_requested = Signal(int)
    caption_workspace_changed = Signal(object, list)

    HIGH_LEVEL_PLACEHOLDER = 'High-level description...'
    BACKGROUND_PLACEHOLDER = 'Background...'

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
        # Stable reference for the displayed image when a filter reset
        # invalidates its source model index.
        self.image_reference: Image | None = None
        self._pending_descriptive_tags: list[str] | None = None
        self._descriptive_dirty = False
        self._descriptive_sync_delay_ms = 450
        self._loading_ideogram_chips = False
        self._ideogram_entries: list[tuple[str, int | None, str | None]] = []
        self._caption_mode = 'tags'
        self._ideogram_available = False
        self._ideogram_has_media = False
        self._ideogram_json_dirty = False
        self._caption_entries: list[dict] = []
        self._caption_workspace_active = False
        self._loading_tags = False
        self.open_text_transform_requested = None
        self.apply_last_text_transform_requested = None

        # Each `QDockWidget` needs a unique object name for saving its state.
        self.setObjectName('image_tags_editor')
        self.setWindowTitle('Image Tags')
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea
                             | Qt.DockWidgetArea.RightDockWidgetArea)

        # Create custom title bar with checkbox and standard buttons
        title_widget = QWidget()
        self._title_widget = title_widget
        title_widget.installEventFilter(self)
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
        self.create_ideogram_button = QPushButton('+ ID4')
        self.create_ideogram_button.setFlat(True)
        self.create_ideogram_button.hide()
        self.create_ideogram_button.setToolTip('Create an Ideogram 4 JSON caption')
        self.create_ideogram_button.setStyleSheet("""
            QPushButton {
                padding: 1px 5px;
                border: none;
                border-radius: 3px;
                background: transparent;
                color: #9aa0a6;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #303030;
                color: #ffffff;
            }
        """)
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

        self.text_transform_button = QPushButton('⇄')
        self.text_transform_button.setToolTip(
            'Open Text Transform (replace or swap caption text)'
        )
        self.text_transform_button.setAccessibleName('Open Text Transform')
        self.text_transform_button.setMaximumSize(24, 20)
        self.text_transform_button.setFlat(True)
        self.text_transform_button.setStyleSheet("""
            QPushButton {
                font-size: 15px;
                border: 1px solid #555;
                border-radius: 3px;
                background-color: #3a3a3a;
                padding: 1px;
                color: #d0d0d0;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
                border-color: #8ab4f8;
                color: #ffffff;
            }
            QPushButton:pressed {
                background-color: #2a2a2a;
            }
        """)
        self.text_transform_button.clicked.connect(
            self._request_open_text_transform
        )

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
        title_layout.addWidget(self.create_ideogram_button)
        title_layout.addStretch()
        title_layout.addWidget(self.descriptive_mode_checkbox)
        title_layout.addWidget(self.grammar_check_button)
        title_layout.addWidget(self.text_transform_button)
        title_layout.addWidget(float_button)
        title_layout.addWidget(close_button)

        self.setTitleBarWidget(title_widget)

        self.tag_input_box = TagInputBox(self.image_tag_list_model,
                                         tag_counter_model, image_list,
                                         tag_separator)
        self.tag_input_box.current_image_reference_getter = (
            lambda: self.image_reference
        )
        self.image_tags_list = ImageTagsList(
            self.image_tag_list_model,
            delegate_cls=CaptionStatusItemDelegate,
        )
        self.image_tags_list.caption_status_for_row = self.caption_status_for_row
        self.image_tags_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.image_tags_list.customContextMenuRequested.connect(
            self._show_caption_status_menu
        )
        self.image_tags_list.spatial_gesture_requested.connect(
            lambda row, action: self._apply_spatial_action_to_rows(
                [row], action
            )
        )
        self.ideogram_tag_list_model = QStringListModel()
        self.ideogram_caption_list = IdeogramCaptionList(
            self.ideogram_tag_list_model,
            deletion_requested=self._request_ideogram_rows_delete,
            lightweight_zoom=True,
            delegate_cls=IdeogramCaptionItemDelegate,
        )
        self.ideogram_caption_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.ideogram_caption_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.ideogram_caption_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.ideogram_caption_list.setDropIndicatorShown(True)
        self.ideogram_caption_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.ideogram_tag_list_model.dataChanged.connect(
            self._on_ideogram_caption_model_changed
        )

        # Descriptive text editor with spell/grammar checking (hidden by default)
        self.descriptive_text_edit = DescriptiveTextEdit()
        self.descriptive_text_edit.set_spatial_review_enabled(
            settings.value(
                'spatial_review_enabled',
                DEFAULT_SETTINGS['spatial_review_enabled'],
                type=bool,
            )
        )
        self.descriptive_text_edit.spatial_correction_requested = (
            self._apply_descriptive_spatial_action
        )
        self.descriptive_text_edit.spatial_span_reviewed = (
            self._descriptive_direction_reviewed_at
        )
        self.descriptive_text_edit.setPlaceholderText('Enter descriptive text with commas...')
        self.descriptive_text_edit.textChanged.connect(self.on_descriptive_text_changed)
        self.descriptive_text_edit.hide()
        self.descriptive_text_edit.installEventFilter(self)
        self.descriptive_text_edit.viewport().installEventFilter(self)
        self._descriptive_gesture_candidate = None
        self._descriptive_gesture_active = False
        self._descriptive_gesture_overlay = SpatialGestureOverlay(
            self.descriptive_text_edit.viewport()
        )
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
        input_layout = QHBoxLayout()
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.addWidget(self.tag_input_box)
        layout.addLayout(input_layout)
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
        self.image_tag_list_model.dataChanged.connect(self._on_caption_text_rows_changed)
        self.image_tag_list_model.modelReset.connect(self._reconcile_caption_entries)
        self.image_tag_list_model.rowsMoved.connect(self._reconcile_caption_entries)
        self.tag_input_box.ideogram_tags_addition_requested.connect(
            self._request_ideogram_object_add
        )
        self.tags_mode_button.clicked.connect(lambda: self.set_caption_mode('tags'))
        self.ideogram_mode_button.clicked.connect(lambda: self.set_caption_mode('ideogram'))
        self.create_ideogram_button.clicked.connect(
            self._request_ideogram_caption_creation
        )
        self.ideogram_caption_list.selectionModel().currentChanged.connect(
            self._on_ideogram_caption_current_changed
        )
        self.ideogram_caption_list.customContextMenuRequested.connect(
            self._show_ideogram_caption_row_menu
        )
        self.ideogram_caption_list.element_drop_requested.connect(
            self._request_ideogram_element_move
        )

        # Now connect descriptive mode signals and load persistent state
        self.descriptive_mode_checkbox.toggled.connect(self.toggle_display_mode)
        self.descriptive_mode_checkbox.toggled.connect(self.save_descriptive_mode_state)
        settings.change.connect(self._on_spatial_setting_changed)

        # Connect grammar check button
        self.grammar_check_button.clicked.connect(self.descriptive_text_edit.check_grammar)

        # Load persistent state after all widgets are created and signals connected
        desc_mode_enabled = settings.value('descriptive_mode_enabled', False, type=bool)
        if desc_mode_enabled:
            # Setting checked will trigger toggle_display_mode via the signal
            self.descriptive_mode_checkbox.setChecked(True)

    @property
    def is_loading_tags(self) -> bool:
        return self._loading_tags

    def caption_entries(self) -> list[dict]:
        self._reconcile_caption_entries()
        return [dict(entry) for entry in self._caption_entries]

    def included_tags(self) -> list[str]:
        return included_caption_tags(self.caption_entries())

    def has_caption_classifications(self) -> bool:
        return (
            any(caption_attention_counts(self._caption_entries))
            or any(
                entry.get('direction_reviewed_phrases')
                for entry in self._caption_entries
            )
        )

    def should_persist_caption_workspace(self) -> bool:
        return self._caption_workspace_active or self.has_caption_classifications()

    def mark_caption_workspace_persisted(self, active: bool):
        self._caption_workspace_active = bool(active)

    def caption_status_for_row(self, row: int) -> dict:
        if 0 <= row < len(self._caption_entries):
            status = dict(self._caption_entries[row])
            status['directional_attention'] = bool(
                settings.value(
                    'spatial_review_enabled',
                    DEFAULT_SETTINGS['spatial_review_enabled'],
                    type=bool,
                )
                and self._unreviewed_spatial_phrases(status)
            )
            return status
        return {}

    @staticmethod
    def _unreviewed_spatial_phrases(entry: dict) -> list[str]:
        text = str(entry.get('text') or '')
        reviewed = {
            str(value).casefold()
            for value in entry.get('direction_reviewed_phrases', [])
        }
        if '*' in reviewed:
            return []
        return [
            text[start:end]
            for start, end, _kind in spatial_expression_spans(text)
            if text[start:end].casefold() not in reviewed
        ]

    def _reconcile_caption_entries(self, *_args):
        if self._loading_tags:
            return
        texts = self.image_tag_list_model.stringList()
        pools: dict[str, list[dict]] = {}
        for entry in self._caption_entries:
            pools.setdefault(str(entry.get('text') or ''), []).append(entry)
        reconciled = []
        for text in texts:
            candidates = pools.get(text) or []
            entry = candidates.pop(0) if candidates else {
                'text': text,
                'needs_review': False,
                'excluded': False,
                'direction_reviewed_phrases': [],
            }
            entry['text'] = text
            reconciled.append(entry)
        self._caption_entries = normalize_caption_entries(reconciled)
        self.image_tags_list.viewport().update()

    def _on_caption_text_rows_changed(self, top_left, bottom_right, *_args):
        if self._loading_tags:
            return
        texts = self.image_tag_list_model.stringList()
        while len(self._caption_entries) < len(texts):
            self._caption_entries.append({
                'text': texts[len(self._caption_entries)],
                'needs_review': False,
                'excluded': False,
                'direction_reviewed_phrases': [],
            })
        for row in range(top_left.row(), bottom_right.row() + 1):
            if 0 <= row < len(texts) and row < len(self._caption_entries):
                self._caption_entries[row]['text'] = texts[row]
        self._reconcile_caption_entries()

    def _show_caption_status_menu(self, position: QPoint):
        indexes = self.image_tags_list.selectedIndexes()
        clicked = self.image_tags_list.indexAt(position)
        if clicked.isValid() and clicked not in indexes:
            self.image_tags_list.setCurrentIndex(clicked)
            indexes = [clicked]
        rows = sorted({index.row() for index in indexes if index.isValid()})
        if not rows:
            return

        menu = QMenu(self.image_tags_list)
        transform_action = menu.addAction('Send to Text Transform…')
        apply_transform_action = menu.addAction('Apply Last Text Transform')
        menu.addSeparator()
        spatial_actions = {}
        selected_spatial_texts = [
            str(self.image_tag_list_model.data(
                self.image_tag_list_model.index(row),
                Qt.ItemDataRole.DisplayRole,
            ) or '')
            for row in rows
        ]
        allowed_spatial_actions = set().union(*(
            spatial_gesture_actions(text) for text in selected_spatial_texts
        )) if selected_spatial_texts else set()
        if any(has_spatial_expression(text) for text in selected_spatial_texts):
            spatial_menu = menu.addMenu('Spatial Correction')
            reference = spatial_reference_label().title()
            spatial_actions['word_left'] = spatial_menu.addAction(
                'Set Body Direction to Left'
            )
            spatial_actions['word_right'] = spatial_menu.addAction(
                'Set Body Direction to Right'
            )
            spatial_menu.addSeparator()
            spatial_actions['frame_left'] = spatial_menu.addAction(
                f'Convert to {reference} Left'
            )
            spatial_actions['frame_right'] = spatial_menu.addAction(
                f'Convert to {reference} Right'
            )
            spatial_menu.addSeparator()
            spatial_actions['background'] = spatial_menu.addAction(
                'Set Position to Background'
            )
            spatial_actions['foreground'] = spatial_menu.addAction(
                'Set Position to Foreground'
            )
            for action_name, action in spatial_actions.items():
                action.setEnabled(action_name in allowed_spatial_actions)
            spatial_menu.addSeparator()
            direction_checked_action = spatial_menu.addAction(
                'Mark Direction as Checked / Ignore Highlight'
            )
            direction_unchecked_action = spatial_menu.addAction(
                'Restore Direction Highlight'
            )
            menu.addSeparator()
        else:
            direction_checked_action = None
            direction_unchecked_action = None
        needs_review_action = menu.addAction('Mark as Needing Review')
        reviewed_action = menu.addAction('Clear Needs Review')
        menu.addSeparator()
        exclude_action = menu.addAction('Exclude from Final Caption')
        include_action = menu.addAction('Include in Final Caption')
        menu.addSeparator()
        clear_action = menu.addAction('Clear Caption Classifications')
        chosen = menu.exec(self.image_tags_list.viewport().mapToGlobal(position))
        if chosen is None:
            return
        if chosen is transform_action:
            if callable(self.open_text_transform_requested):
                self.open_text_transform_requested()
            return
        if chosen is apply_transform_action:
            if callable(self.apply_last_text_transform_requested):
                self.apply_last_text_transform_requested()
            return
        for action_name, action in spatial_actions.items():
            if chosen is action:
                self._apply_spatial_action_to_rows(rows, action_name)
                return
        if chosen is direction_checked_action:
            self._set_direction_reviewed(rows, True)
            return
        if chosen is direction_unchecked_action:
            self._set_direction_reviewed(rows, False)
            return
        self._reconcile_caption_entries()
        for row in rows:
            if row < 0 or row >= len(self._caption_entries):
                continue
            entry = self._caption_entries[row]
            if chosen is needs_review_action:
                entry['needs_review'] = True
            elif chosen is reviewed_action:
                entry['needs_review'] = False
            elif chosen is exclude_action:
                entry['excluded'] = True
            elif chosen is include_action:
                entry['excluded'] = False
            elif chosen is clear_action:
                entry['needs_review'] = False
                entry['excluded'] = False
        self.image_tags_list.viewport().update()
        if self.image_reference is not None:
            self._caption_workspace_active = True
            self.caption_workspace_changed.emit(
                self.image_reference,
                self.caption_entries(),
            )

    def _apply_spatial_action_to_rows(self, rows: list[int], action: str):
        self._reconcile_caption_entries()
        tags = self.image_tag_list_model.stringList()
        changed = False
        for row in rows:
            if not 0 <= row < len(tags):
                continue
            updated = apply_spatial_action(tags[row], action)
            if updated == tags[row]:
                continue
            tags[row] = updated
            changed = True
            if row < len(self._caption_entries):
                self._caption_entries[row]['text'] = updated
                self._caption_entries[row]['direction_reviewed_phrases'] = [
                    updated[start:end].casefold()
                    for start, end, _kind in spatial_expression_spans(updated)
                ]
        if not changed:
            return
        self._caption_workspace_active = True
        self.image_tag_list_model.setStringList(tags)
        self.image_tags_list.viewport().update()
        if self.image_reference is not None:
            self.caption_workspace_changed.emit(
                self.image_reference,
                self.caption_entries(),
            )

    def _set_direction_reviewed(self, rows: list[int], reviewed: bool):
        self._reconcile_caption_entries()
        changed = False
        for row in rows:
            if not 0 <= row < len(self._caption_entries):
                continue
            new_value = ['*'] if reviewed else []
            if (self._caption_entries[row].get('direction_reviewed_phrases', [])
                    == new_value):
                continue
            self._caption_entries[row]['direction_reviewed_phrases'] = new_value
            changed = True
        if not changed:
            return
        self._caption_workspace_active = True
        self.image_tags_list.viewport().update()
        self.descriptive_text_edit._refresh_spatial_highlights()
        if self.image_reference is not None:
            self.caption_workspace_changed.emit(
                self.image_reference,
                self.caption_entries(),
            )

    def _descriptive_direction_reviewed_at(self, position: int) -> bool:
        text = self.descriptive_text_edit.toPlainText()
        row = text[:position].count(self.tag_separator)
        if not 0 <= row < len(self._caption_entries):
            return False
        reviewed = {
            str(value).casefold()
            for value in self._caption_entries[row].get(
                'direction_reviewed_phrases', []
            )
        }
        if '*' in reviewed:
            return True
        for start, end, _kind in spatial_expression_spans(text):
            if start <= position <= end:
                return text[start:end].casefold() in reviewed
        return False

    def _mark_direction_phrase_reviewed(self, row: int, phrase: str):
        self._reconcile_caption_entries()
        if not 0 <= row < len(self._caption_entries):
            return
        reviewed = self._caption_entries[row].setdefault(
            'direction_reviewed_phrases', []
        )
        normalized = phrase.strip().casefold()
        if not normalized or normalized in reviewed:
            return
        reviewed.append(normalized)
        self._caption_workspace_active = True
        self.image_tags_list.viewport().update()
        self.descriptive_text_edit._refresh_spatial_highlights()
        if self.image_reference is not None:
            self.caption_workspace_changed.emit(
                self.image_reference,
                self.caption_entries(),
            )

    def _apply_descriptive_spatial_action(
        self,
        action: str,
        start: int,
        end: int,
    ):
        text = self.descriptive_text_edit.toPlainText()
        phrase = text[start:end]
        updated_phrase = apply_spatial_action(phrase, action)
        if updated_phrase == phrase:
            return
        row = text[:start].count(self.tag_separator)
        cursor = self.descriptive_text_edit.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cursor.beginEditBlock()
        cursor.insertText(updated_phrase)
        cursor.endEditBlock()
        self.descriptive_text_edit.setTextCursor(cursor)
        self._flush_descriptive_sync()
        self._mark_direction_phrase_reviewed(row, updated_phrase)

    def selected_descriptive_text(self) -> str:
        if not self.descriptive_mode_checkbox.isChecked():
            return ''
        return self.descriptive_text_edit.textCursor().selectedText()

    def _request_open_text_transform(self):
        if callable(self.open_text_transform_requested):
            self.open_text_transform_requested()

    def apply_text_transform(
        self,
        scope: str,
        options: TextTransformOptions,
        *,
        preview: bool = False,
    ) -> tuple[int, int]:
        """Preview or apply a transform to the active caption editor."""
        if self._caption_mode != 'tags':
            raise ValueError('Text Transform is only available for normal captions.')

        if scope == 'Selected text':
            if not self.descriptive_mode_checkbox.isChecked():
                raise ValueError('Enable Desc mode and select caption text first.')
            cursor = self.descriptive_text_edit.textCursor()
            if not cursor.hasSelection():
                raise ValueError('Select caption text first.')
            updated, count_a, count_b = transform_text(
                cursor.selectedText(), options
            )
            replacements = count_a + count_b
            if replacements and not preview:
                cursor.beginEditBlock()
                cursor.insertText(updated)
                cursor.endEditBlock()
                self.descriptive_text_edit.setTextCursor(cursor)
                self._flush_descriptive_sync()
            return (1 if replacements else 0), replacements

        if self.descriptive_mode_checkbox.isChecked():
            self._flush_descriptive_sync()
        tags = self.image_tag_list_model.stringList()
        if scope == 'Selected caption rows':
            rows = sorted({
                index.row() for index in self.image_tags_list.selectedIndexes()
                if index.isValid()
            })
            if not rows:
                raise ValueError('Select one or more caption rows first.')
        elif scope == 'Current media caption':
            rows = list(range(len(tags)))
        else:
            raise ValueError(f'Unsupported editor scope: {scope}')

        changed = False
        replacements = 0
        updated_tags = list(tags)
        for row in rows:
            if row < 0 or row >= len(updated_tags):
                continue
            updated, count_a, count_b = transform_text(updated_tags[row], options)
            if updated != updated_tags[row]:
                changed = True
                updated_tags[row] = updated
            replacements += count_a + count_b
        if changed and not preview:
            self.image_tag_list_model.setStringList(updated_tags)
        return (1 if changed else 0), replacements

    @Slot()
    def count_tokens(self):
        caption = self.tag_separator.join(self.included_tags())
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
        self._ideogram_has_media = image is not None
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
        rows.append(caption.high_level_description or self.HIGH_LEVEL_PLACEHOLDER)
        self._ideogram_entries.append(('high_level', None, 'high_level_description'))
        rows.append(caption.compositional_background or self.BACKGROUND_PLACEHOLDER)
        self._ideogram_entries.append(('background', None, 'background'))
        for chip in ideogram_caption_chips(caption):
            if chip.kind in {'high_level', 'background'}:
                continue
            rows.append(chip.text)
            self._ideogram_entries.append((chip.kind, chip.element_index, None))
        self.ideogram_tag_list_model.setStringList(rows)
        self.ideogram_json_text_edit.blockSignals(True)
        self.ideogram_json_text_edit.setPlainText(caption.to_json(pretty=True))
        self.ideogram_json_text_edit.blockSignals(False)
        self._set_ideogram_available(True)
        self._loading_ideogram_chips = False

    def _set_ideogram_available(self, available: bool):
        self._ideogram_available = bool(available)
        self.ideogram_mode_button.setVisible(self._ideogram_available)
        self.create_ideogram_button.setVisible(
            self._ideogram_has_media and not self._ideogram_available
        )
        self._apply_caption_mode_title_style()
        if not self._ideogram_available and self._caption_mode == 'ideogram':
            self.set_caption_mode('tags')
        else:
            self._sync_caption_mode_widgets()

    def _request_ideogram_caption_creation(self):
        self.ideogram_caption_create_requested.emit()
        if self._ideogram_available:
            self.set_caption_mode('ideogram')

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
        _, element_index, _field = self._ideogram_entries[current.row()]
        if element_index is not None:
            self.ideogram_element_selected.emit(int(element_index))

    def _on_ideogram_caption_model_changed(self, top_left: QModelIndex, bottom_right: QModelIndex):
        if self._loading_ideogram_chips:
            return
        rows = self.ideogram_tag_list_model.stringList()
        for row in range(top_left.row(), bottom_right.row() + 1):
            if row < 0 or row >= len(self._ideogram_entries) or row >= len(rows):
                continue
            kind, element_index, field = self._ideogram_entries[row]
            value = rows[row].strip()
            if field is not None:
                if field == 'high_level_description' and value == self.HIGH_LEVEL_PLACEHOLDER:
                    value = ''
                if field == 'background' and value == self.BACKGROUND_PLACEHOLDER:
                    value = ''
                self.ideogram_global_field_changed.emit(field, value)
                continue
            if element_index is None or kind not in {'object', 'text'}:
                continue
            self.ideogram_element_text_changed.emit(
                int(element_index),
                str(kind),
                value,
            )

    def _show_ideogram_caption_row_menu(self, position: QPoint):
        index = self.ideogram_caption_list.indexAt(position)
        if not index.isValid():
            return
        row = index.row()

        self.ideogram_caption_list.setCurrentIndex(index)
        menu = QMenu(self.ideogram_caption_list)
        open_action = menu.addAction('Open in Ideogram Caption Editor')
        convert_action = None
        element_index = None
        target_type = None
        if 0 <= row < len(self._ideogram_entries):
            kind, element_index, field = self._ideogram_entries[row]
            if (
                field is None
                and element_index is not None
                and kind in {'object', 'text'}
            ):
                menu.addSeparator()
                target_type = 'text' if kind == 'object' else 'obj'
                label = (
                    'Convert to Text region'
                    if target_type == 'text'
                    else 'Convert to Object region'
                )
                convert_action = menu.addAction(label)
        chosen = menu.exec(self.ideogram_caption_list.viewport().mapToGlobal(position))
        if chosen is open_action:
            self.ideogram_editor_open_requested.emit(
                int(element_index) if element_index is not None else -1
            )
        elif chosen is convert_action and element_index is not None:
            self.ideogram_element_type_change_requested.emit(
                int(element_index),
                target_type,
            )

    def _request_ideogram_element_move(self, source_row: int, target_row: int):
        if source_row < 0 or source_row >= len(self._ideogram_entries):
            return
        kind, source_element_index, source_field = self._ideogram_entries[source_row]
        if source_field is not None or source_element_index is None or kind not in {'object', 'text'}:
            return

        target_row = max(0, min(int(target_row), len(self._ideogram_entries)))
        target_element_index = self._element_insert_index_for_row(
            target_row,
            moving_element_index=int(source_element_index),
        )
        if target_element_index is None:
            return
        self.ideogram_element_move_requested.emit(
            int(source_element_index),
            int(target_element_index),
        )

    def _element_insert_index_for_row(
        self,
        row: int,
        *,
        moving_element_index: int,
    ) -> int | None:
        if not self._ideogram_entries:
            return None
        if row <= 0:
            return 0

        element_rows = [
            entry for entry in self._ideogram_entries
            if entry[1] is not None and entry[2] is None
        ]
        if not element_rows:
            return None

        if row >= len(self._ideogram_entries):
            target = max(int(entry[1]) for entry in element_rows) + 1
        else:
            target = None
            for candidate_row in range(row, len(self._ideogram_entries)):
                _kind, element_index, field = self._ideogram_entries[candidate_row]
                if element_index is not None and field is None:
                    target = int(element_index)
                    break
            if target is None:
                target = max(int(entry[1]) for entry in element_rows) + 1

        if moving_element_index < target:
            target -= 1
        return max(0, target)

    def _request_ideogram_object_add(self, tags: list[str]):
        for tag in tags:
            text = str(tag).strip()
            if text:
                self.ideogram_region_add_requested.emit('obj', text)

    def _request_ideogram_rows_delete(self, rows: list[int]):
        element_indices = []
        for row in rows:
            if row < 0 or row >= len(self._ideogram_entries):
                continue
            _, element_index, _field = self._ideogram_entries[row]
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
        self._apply_descriptive_tags_to_workspace(tags)

    def _apply_descriptive_tags_to_workspace(self, tags: list[str]):
        """Replace included entries while retaining excluded workspace entries."""
        if not self._caption_workspace_active:
            if tags != self.image_tag_list_model.stringList():
                self.image_tag_list_model.setStringList(tags)
            return

        existing_entries = self.caption_entries()
        pools: dict[str, list[dict]] = {}
        for entry in existing_entries:
            pools.setdefault(entry['text'], []).append(entry)
        mixed_status_texts = {
            text
            for text, candidates in pools.items()
            if any(entry.get('excluded') for entry in candidates)
            and any(not entry.get('excluded') for entry in candidates)
        }
        for candidates in pools.values():
            candidates.sort(key=lambda entry: bool(entry.get('excluded')))
        merged_entries: list[dict] = []
        for tag in tags:
            if tag in mixed_status_texts:
                # Repair duplicates created by the previous Description-mode
                # merge: retain the excluded original below and discard the
                # accidental included copy.
                continue
            candidates = pools.get(tag) or []
            if candidates:
                entry = candidates.pop(0)
                entry['excluded'] = False
            else:
                entry = {
                    'text': tag,
                    'needs_review': False,
                    'excluded': False,
                }
            merged_entries.append(entry)
        for position, entry in enumerate(existing_entries):
            if entry.get('excluded'):
                merged_entries.insert(min(position, len(merged_entries)), entry)

        self._caption_entries = normalize_caption_entries(merged_entries)
        working_tags = [entry['text'] for entry in self._caption_entries]
        if working_tags != self.image_tag_list_model.stringList():
            self.image_tag_list_model.setStringList(working_tags)

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
    def load_image_tags(
        self,
        proxy_image_index: QModelIndex,
        *,
        image_override: Image | None = None,
        source_index_override: QModelIndex | None = None,
    ):
        # Persist pending edits for the previous image before switching index.
        self._flush_descriptive_sync()
        self._flush_ideogram_json_sync()
        self.image_index = (
            source_index_override
            if source_index_override is not None
            else self.proxy_image_list_model.mapToSource(proxy_image_index)
        )
        source_model = self.proxy_image_list_model.sourceModel()
        image: Image = (
            image_override
            if image_override is not None
            else self.proxy_image_list_model.data(
                proxy_image_index, Qt.ItemDataRole.UserRole)
        )
        self.image_reference = image
        # Safety check: if no image is selected or available, clear the tags
        if image is None:
            self._caption_entries = []
            self._caption_workspace_active = False
            self.image_tag_list_model.setStringList([])
            self._set_ideogram_caption_chips_for_image(None)
            return
        self._set_ideogram_caption_chips_for_image(image)
        caption_text = self._read_caption_text_from_disk(image)
        stored_workspace = load_caption_workspace(image.path)
        if stored_workspace is not None:
            self._caption_workspace_active = True
            disk_tags = (
                self._tags_from_descriptive_text(caption_text)
                if caption_text is not None else included_caption_tags(stored_workspace)
            )
            stored_included = included_caption_tags(stored_workspace)
            if disk_tags != stored_included:
                self._caption_entries = merge_caption_entries_with_disk_tags(
                    stored_workspace,
                    disk_tags,
                )
            else:
                self._caption_entries = stored_workspace
            tags_from_source = [entry['text'] for entry in self._caption_entries]
        else:
            self._caption_workspace_active = False
            tags_from_source = (
                self._tags_from_descriptive_text(caption_text)
                if caption_text is not None
                else self._filter_internal_tags(image.tags)
            )
            self._caption_entries = [
                {'text': tag, 'needs_review': False, 'excluded': False}
                for tag in tags_from_source
            ]
        included_tags = included_caption_tags(self._caption_entries)
        should_refresh_source_row = False
        # Keep the in-memory image tags aligned with the sidecar source of truth.
        if image.tags != included_tags:
            image.tags = included_tags
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
                        included_tags,
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
            description_text = (
                self.tag_separator.join(included_tags)
                if stored_workspace is not None
                else caption_text
            )
            if (self.descriptive_mode_checkbox.isChecked()
                    and description_text is not None
                    and self.descriptive_text_edit.toPlainText() != description_text):
                self.descriptive_text_edit.blockSignals(True)
                self.descriptive_text_edit.setPlainText(description_text)
                self.descriptive_text_edit.blockSignals(False)
            if should_refresh_source_row:
                self._emit_source_row_data_changed(source_model)
            return
        self._loading_tags = True
        try:
            self.image_tag_list_model.setStringList(tags_from_source)
        finally:
            self._loading_tags = False
        self.count_tokens()
        self._pending_descriptive_tags = None
        self._descriptive_dirty = False
        # Update descriptive text if in descriptive mode
        if self.descriptive_mode_checkbox.isChecked():
            tags_text = (
                self.tag_separator.join(included_tags)
                if stored_workspace is not None
                else caption_text
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

    @Slot(object)
    def load_image_tags_for_reference(self, image_reference):
        """Load tags from a stable image reference after a filter reset."""
        source_model = self.proxy_image_list_model.sourceModel()
        resolver = getattr(source_model, 'resolve_image_reference', None)
        image = (
            resolver(image_reference)
            if callable(resolver) else image_reference
        )
        if image is None:
            self.load_image_tags(QModelIndex())
            return

        source_index = QModelIndex()
        loaded_index_getter = getattr(
            source_model,
            'get_loaded_index_for_reference',
            None,
        )
        if callable(loaded_index_getter):
            try:
                loaded_index = loaded_index_getter(image)
                if loaded_index.isValid():
                    source_index = loaded_index
            except (RuntimeError, AttributeError, TypeError):
                pass
        self.load_image_tags(
            QModelIndex(),
            image_override=image,
            source_index_override=source_index,
        )

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
            tags_text = self.tag_separator.join(self.included_tags())
            if self.image_index and self.image_index.isValid():
                proxy_index = self.proxy_image_list_model.mapFromSource(self.image_index)
                image: Image = self.proxy_image_list_model.data(
                    proxy_index, Qt.ItemDataRole.UserRole)
                if image is not None:
                    caption_text = self._read_caption_text_from_disk(image)
                    if caption_text is not None and not self.has_caption_classifications():
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
            self._apply_descriptive_tags_to_workspace(tags)
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
        if watched is getattr(self, '_title_widget', None):
            if event.type() == QEvent.Type.Enter:
                if (not self._ideogram_available
                        and self.image_index is not None
                        and self.image_index.isValid()):
                    self.create_ideogram_button.show()
            elif event.type() == QEvent.Type.Leave:
                self.create_ideogram_button.hide()
        descriptive_text_edit = getattr(self, 'descriptive_text_edit', None)
        ideogram_json_text_edit = getattr(self, 'ideogram_json_text_edit', None)
        if watched is getattr(descriptive_text_edit, 'viewport', lambda: None)():
            if self._handle_descriptive_spatial_gesture_event(event):
                return True
        if (watched is descriptive_text_edit
                and event.type() == QEvent.Type.FocusOut):
            self._flush_descriptive_sync()
        if (watched is ideogram_json_text_edit
                and event.type() == QEvent.Type.FocusOut):
            self._flush_ideogram_json_sync()
        return super().eventFilter(watched, event)

    def _handle_descriptive_spatial_gesture_event(self, event) -> bool:
        if not settings.value(
            'spatial_gestures_enabled',
            DEFAULT_SETTINGS['spatial_gestures_enabled'],
            type=bool,
        ):
            return False
        event_type = event.type()
        if event_type == QEvent.Type.MouseButtonPress:
            if event.button() != Qt.MouseButton.LeftButton:
                return False
            position = event.position().toPoint()
            cursor = self.descriptive_text_edit.cursorForPosition(position)
            text = self.descriptive_text_edit.toPlainText()
            for start, end, _kind in spatial_expression_spans(text):
                if not start <= cursor.position() <= end:
                    continue
                if self._descriptive_direction_reviewed_at(start):
                    continue
                phrase = text[start:end]
                allowed = spatial_gesture_actions(phrase)
                if allowed:
                    self._descriptive_gesture_candidate = (
                        position, start, end, phrase, allowed
                    )
                break
            return False

        if event_type == QEvent.Type.MouseMove and self._descriptive_gesture_candidate:
            origin, start, end, phrase, allowed = self._descriptive_gesture_candidate
            position = event.position().toPoint()
            dx = position.x() - origin.x()
            dy = position.y() - origin.y()
            if not self._descriptive_gesture_active and dx * dx + dy * dy < 144:
                return False
            if not self._descriptive_gesture_active:
                self._descriptive_gesture_active = True
                self._descriptive_gesture_overlay.begin(origin, allowed)
            self._descriptive_gesture_overlay.choose(position, phrase)
            return True

        if event_type == QEvent.Type.MouseButtonRelease and self._descriptive_gesture_candidate:
            _origin, start, end, _phrase, _allowed = self._descriptive_gesture_candidate
            action = self._descriptive_gesture_overlay.action
            was_active = self._descriptive_gesture_active
            self._descriptive_gesture_candidate = None
            self._descriptive_gesture_active = False
            self._descriptive_gesture_overlay.hide()
            if was_active and action:
                self._apply_descriptive_spatial_action(action, start, end)
            return was_active
        return False

    @Slot(str, object)
    def _on_spatial_setting_changed(self, key: str, _value):
        if key == 'spatial_review_enabled':
            enabled = settings.value(
                key, DEFAULT_SETTINGS[key], type=bool
            )
            self.descriptive_text_edit.set_spatial_review_enabled(enabled)
            self.image_tags_list.viewport().update()
        elif key in {
            'spatial_reference_noun',
            'spatial_highlight_depth_expressions',
            'spatial_gestures_enabled',
        }:
            if key == 'spatial_highlight_depth_expressions':
                self.descriptive_text_edit._refresh_spatial_highlights()
            self.image_tags_list.viewport().update()

    def closeEvent(self, event: QCloseEvent):
        self._flush_descriptive_sync()
        self._flush_ideogram_json_sync()
        super().closeEvent(event)
