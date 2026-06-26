import shutil
import time
from enum import Enum
from functools import reduce
from operator import or_
from pathlib import Path

from PySide6.QtCore import (QFile, QItemSelection, QItemSelectionModel,
                            QItemSelectionRange, QModelIndex, QSize, QUrl, Qt, QMimeData,
                            Signal, Slot, QPersistentModelIndex, QProcess, QTimer, QRect, QEvent, QPoint)
from PySide6.QtGui import (QDesktopServices, QColor, QPen, QPixmap, QPainter, QDrag,
                           QPolygon, QCursor, QIcon, QPainterPath)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDockWidget,
                               QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QListView, QListWidget, QListWidgetItem,
                               QMenu, QMessageBox, QVBoxLayout, QFrame, QPushButton,
                               QWidget, QStyledItemDelegate, QToolTip, QStyle, QStyleOptionViewItem,
                               QProgressBar)
from pyparsing import (CaselessKeyword, CaselessLiteral, Combine, Group, OpAssoc,
                       Optional, ParseException, QuotedString, Suppress, Word,
                       infix_notation, nums, one_of, printables)

from models.proxy_image_list_model import ProxyImageListModel
from models.image_list_model import natural_sort_key
from utils.image import Image
from utils.review_marks import (
    ReviewFlag,
    get_review_badge_corner_radius,
    get_review_badge_font_size,
    get_review_badge_spec_for_flag,
    get_review_badge_spec_for_rank,
    get_review_badge_text_color,
    iter_review_flags,
)
from utils.settings import (
    settings,
    get_thumbnail_reaction_badge_style_spec,
    get_thumbnail_review_badge_style_spec,
    get_thumbnail_star_badge_style_spec,
    normalize_thumbnail_badge_side,
    normalize_thumbnail_reaction_badge_style,
    normalize_thumbnail_review_badge_style,
    normalize_thumbnail_star_badge_style,
)
from utils.settings_widgets import SettingsComboBox
from utils.utils import get_confirmation_dialog_reply, pluralize
from utils.grid import Grid
from widgets.masonry_worker import calculate_masonry_layout
from concurrent.futures import ThreadPoolExecutor


def replace_filter_wildcards(filter_: str | list) -> str | list:
    """
    Replace escaped wildcard characters to make them compatible with the
    `fnmatch` module.
    """
    if isinstance(filter_, str):
        filter_ = filter_.replace(r'\*', '[*]').replace(r'\?', '[?]')
        return filter_
    replaced_filter = []
    for element in filter_:
        replaced_element = replace_filter_wildcards(element)
        replaced_filter.append(replaced_element)
    return replaced_filter


FILTER_TEMPLATE_SPECS = [
    ('Tag', 'Filter by tag', 'tag:"{cursor}"', True),
    ('Caption', 'Filter by caption text', 'caption:"{cursor}"', True),
    ('Ideogram', 'Filter by Ideogram JSON caption text', 'ideogram:"{cursor}"', True),
    ('Marking', 'Filter by marking label', 'marking:"{cursor}"', True),
    ('Marking Type', 'Filter by marking kind', 'marking_type:hint', False),
    ('Stars', 'Filter by star rating', 'stars:>={cursor}', True),
    ('Love', 'Filter loved items', 'love:true', False),
    ('Bomb', 'Filter bombed items', 'bomb:true', False),
    ('Review', 'Filter reviewed items', 'review:true', False),
    ('Review Rank', 'Filter by review rank', 'review_rank:>={cursor}', True),
    ('Rejected', 'Filter rejected items', 'review:reject', False),
    ('Width', 'Filter by image width', 'width:>1024', False),
    ('Height', 'Filter by image height', 'height:>1024', False),
    ('Name', 'Filter by file name', 'name:"{cursor}"', True),
    ('AND', 'Combine two predicates', 'AND', True),
    ('OR', 'Match either predicate', 'OR', True),
    ('NOT', 'Invert the next predicate', 'NOT {cursor}', True),
]


class HoverSelectableListWidget(QListWidget):
    """QListWidget that keeps its current item aligned with hover movement."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.itemEntered.connect(self._set_hover_current_item)

    def mouseMoveEvent(self, event):
        try:
            hover_pos = event.position().toPoint()
        except Exception:
            hover_pos = event.pos()
        hovered_item = self.itemAt(hover_pos)
        if hovered_item is not None:
            self.setCurrentItem(hovered_item)
        super().mouseMoveEvent(event)

    def _set_hover_current_item(self, item):
        if item is not None:
            self.setCurrentItem(item)


class FilterSuggestionPopup(QFrame):
    template_selected = Signal(str, bool)
    history_selected = Signal(str)
    clear_history_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName('filterSuggestionPopup')
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            """
            QFrame#filterSuggestionPopup {
                background-color: palette(base);
                border: 1px solid palette(mid);
                border-radius: 8px;
            }
            QListWidget {
                background: transparent;
                border: none;
                outline: none;
                padding: 4px;
            }
            QListWidget::item {
                padding: 8px;
                margin: 2px 0px;
                border-radius: 6px;
            }
            QListWidget::item:hover {
                background: palette(highlight);
                color: palette(highlighted-text);
            }
            QListWidget::item:selected {
                background: palette(highlight);
                color: palette(highlighted-text);
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        filters_label = QLabel('Filters', self)
        filters_label.setStyleSheet('font-weight: 600; padding: 2px 4px;')
        layout.addWidget(filters_label)

        self.list_widget = HoverSelectableListWidget(self)
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_widget.setUniformItemSizes(False)
        self.list_widget.itemClicked.connect(self._choose_item)
        self.list_widget.itemActivated.connect(self._choose_item)
        self._template_row_height = 44
        self.list_widget.setStyleSheet('margin-left: 10px;')
        layout.addWidget(self.list_widget)

        for title, description, template, defer_filter in FILTER_TEMPLATE_SPECS:
            item = QListWidgetItem(f'{title}\n{description}')
            item.setData(Qt.ItemDataRole.UserRole, (template, defer_filter))
            item.setSizeHint(QSize(0, 44))
            self.list_widget.addItem(item)

        self.history_header_widget = QWidget(self)
        history_header = QHBoxLayout(self.history_header_widget)
        history_header.setContentsMargins(0, 0, 0, 0)
        history_label = QLabel('History', self)
        history_label.setStyleSheet('font-weight: 600; padding: 2px 4px;')
        history_header.addWidget(history_label)
        history_header.addStretch()
        self.clear_history_button = QPushButton('Clear', self)
        self.clear_history_button.setFlat(True)
        self.clear_history_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_history_button.clicked.connect(self.clear_history_requested.emit)
        history_header.addWidget(self.clear_history_button)
        layout.addWidget(self.history_header_widget)

        self.history_list_widget = HoverSelectableListWidget(self)
        self.history_list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.history_list_widget.setUniformItemSizes(True)
        self.history_list_widget.itemClicked.connect(self._choose_history_item)
        self.history_list_widget.itemActivated.connect(self._choose_history_item)
        self._history_row_height = 28
        self.history_list_widget.setStyleSheet('margin-left: 10px;')
        layout.addWidget(self.history_list_widget)

    def _choose_item(self, item: QListWidgetItem):
        payload = item.data(Qt.ItemDataRole.UserRole)
        if payload:
            template, defer_filter = payload
            self.template_selected.emit(template, bool(defer_filter))
        self.hide()

    def _choose_history_item(self, item: QListWidgetItem):
        text = item.data(Qt.ItemDataRole.UserRole)
        if text:
            self.history_selected.emit(str(text))
        self.hide()

    def set_history_items(self, items: list[str]):
        self.history_list_widget.clear()
        for text in items:
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, text)
            self.history_list_widget.addItem(item)
        has_items = bool(items)
        self.history_header_widget.setVisible(has_items)
        self.history_list_widget.setVisible(has_items)
        self.clear_history_button.setVisible(has_items)

    def show_for(self, line_edit: QLineEdit):
        width = max(line_edit.width(), 300)
        anchor = line_edit.mapToGlobal(QPoint(0, line_edit.height() + 4))
        screen = QApplication.screenAt(anchor) or line_edit.screen() or QApplication.primaryScreen()
        available_geometry = screen.availableGeometry() if screen is not None else QRect(anchor.x(), anchor.y(), width, 700)

        template_rows = min(self.list_widget.count(), 7)
        preferred_filters_height = max(140, template_rows * self._template_row_height + 10)

        history_height = 0
        if self.history_list_widget.isVisible():
            visible_history_rows = max(2, min(self.history_list_widget.count(), 4))
            history_height = max(70, visible_history_rows * self._history_row_height + 8)

        preferred_height = 24 + preferred_filters_height + 16
        if self.history_list_widget.isVisible():
            preferred_height += 28 + history_height + 8

        available_below = max(160, available_geometry.bottom() - anchor.y() - 8)
        available_above = max(160, line_edit.mapToGlobal(QPoint(0, 0)).y() - available_geometry.top() - 8)
        show_above = available_below < preferred_height and available_above > available_below
        available_height = available_above if show_above else available_below

        base_height_without_history = 24 + 120 + 16
        if self.history_list_widget.isVisible():
            base_height_without_history += 28 + 60 + 8
        popup_height = min(preferred_height, max(base_height_without_history, available_height))

        reserved_history_height = 0
        if self.history_list_widget.isVisible():
            reserved_history_height = min(history_height, max(60, popup_height - (24 + 120 + 16 + 28 + 8)))
            filters_height = max(120, popup_height - (24 + 16 + 28 + 8 + reserved_history_height))
        else:
            filters_height = max(120, popup_height - (24 + 16))

        self.list_widget.setMinimumHeight(filters_height)
        self.list_widget.setMaximumHeight(filters_height)

        if self.history_list_widget.isVisible():
            self.history_list_widget.setMinimumHeight(reserved_history_height)
            self.history_list_widget.setMaximumHeight(reserved_history_height)

        self.resize(width, popup_height)
        if show_above:
            popup_pos = line_edit.mapToGlobal(QPoint(0, -self.height() - 4))
        else:
            popup_pos = anchor
        popup_x = max(available_geometry.left(), min(popup_pos.x(), available_geometry.right() - self.width()))
        popup_y = max(available_geometry.top(), min(popup_pos.y(), available_geometry.bottom() - self.height()))
        self.move(QPoint(popup_x, popup_y))
        self.show()
        self.raise_()
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)
            self.list_widget.setFocus()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            event.accept()
            return
        super().keyPressEvent(event)


class FilterLineEdit(QLineEdit):
    apply_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setPlaceholderText('Filter Images')
        self.setStyleSheet('padding: 8px;')
        self.setClearButtonEnabled(True)
        optionally_quoted_string = (QuotedString(quote_char='"', esc_char='\\')
                                    | QuotedString(quote_char="'",
                                                   esc_char='\\')
                                    | Word(printables, exclude_chars='()'))
        string_filter_keys = ['tag', 'caption', 'ideogram', 'marking', 'marking_type', 'crops', 'visible',
                              'name', 'path', 'size', 'target', 'love', 'bomb', 'review']
        string_filter_expressions = [Group(CaselessLiteral(key) + Suppress(':')
                                           + optionally_quoted_string)
                                     for key in string_filter_keys]
        comparison_operator = one_of('= == != < > <= >=')
        number_value = Combine(Word(nums) + Optional('.' + Word(nums)))
        number_filter_keys = ['tags', 'chars', 'tokens', 'stars', 'review_rank', 'width',
                              'height', 'area']
        number_filter_expressions = [Group(CaselessLiteral(key) + Suppress(':')
                                           + comparison_operator + number_value)
                                     for key in number_filter_keys]
        string_filter_expressions = reduce(or_, string_filter_expressions)
        number_filter_expressions = reduce(or_, number_filter_expressions)
        filter_expressions = (string_filter_expressions
                              | number_filter_expressions
                              | optionally_quoted_string)
        self.filter_text_parser = infix_notation(
            filter_expressions,
            # Operator, number of operands, associativity.
            [(CaselessKeyword('NOT'), 1, OpAssoc.RIGHT),
             (CaselessKeyword('AND'), 2, OpAssoc.LEFT),
             (CaselessKeyword('OR'), 2, OpAssoc.LEFT)])
        self._suggestion_popup = FilterSuggestionPopup(self)
        self._suggestion_popup.template_selected.connect(
            self._insert_filter_template)
        self._suggestion_popup.history_selected.connect(
            self._apply_history_item)
        self._suggestion_popup.clear_history_requested.connect(
            self.clear_filter_history)
        self._pending_history_text = ''
        self._history_timer = QTimer(self)
        self._history_timer.setSingleShot(True)
        self._history_timer.setInterval(1400)
        self._history_timer.timeout.connect(self._commit_pending_history)
        self.textChanged.connect(self._cancel_pending_history)
        suggestion_icon = self._build_suggestion_icon()
        self._suggestion_action = self.addAction(
            suggestion_icon,
            QLineEdit.ActionPosition.TrailingPosition)
        self._suggestion_action.triggered.connect(
            self.toggle_suggestion_popup)
        self._suggestion_action.setToolTip('Show filter suggestions')

    def _build_suggestion_icon(self) -> QIcon:
        device_ratio = max(1.0, self.devicePixelRatioF())
        logical_size = 16
        pixmap = QPixmap(int(logical_size * device_ratio), int(logical_size * device_ratio))
        pixmap.setDevicePixelRatio(device_ratio)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        color = self.palette().color(self.foregroundRole())
        color.setAlpha(190)
        pen = QPen(color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(4, 6, 8, 10)
        painter.drawLine(8, 10, 12, 6)
        painter.end()

        return QIcon(pixmap)

    def toggle_suggestion_popup(self):
        if self._suggestion_popup.isVisible():
            self._suggestion_popup.hide()
            return
        self._suggestion_popup.set_history_items(self.get_filter_history())
        self._suggestion_popup.show_for(self)

    def _insert_filter_template(self, template: str, defer_filter: bool):
        cursor_token = '{cursor}'
        cursor_index = template.find(cursor_token)
        clean_template = template.replace(cursor_token, '')

        cursor = self.cursorPosition()
        current_text = self.text()
        prefix = ''
        suffix = ''

        if cursor > 0 and not current_text[cursor - 1].isspace() and current_text[cursor - 1] not in '([':
            prefix = ' '
        if cursor < len(current_text) and not current_text[cursor].isspace() and current_text[cursor] not in ')]':
            suffix = ' '

        insertion = prefix + clean_template + suffix
        if defer_filter:
            old_block = self.blockSignals(True)
            self.insert(insertion)
            self.blockSignals(old_block)
        else:
            self.insert(insertion)

        if cursor_index >= 0:
            self.setCursorPosition(cursor + len(prefix) + cursor_index)

        self.setFocus()

    def _apply_history_item(self, filter_text: str):
        self.setText(filter_text)
        self.apply_requested.emit()

    def get_filter_history(self) -> list[str]:
        values = settings.value('image_list_filter_history', defaultValue=[], type=list)
        if isinstance(values, list):
            return [str(item) for item in values if str(item).strip()]
        return []

    def remember_filter_history(self, filter_text: str):
        text = str(filter_text or '').strip()
        if not text:
            return
        self._pending_history_text = text
        self._history_timer.start()

    def _cancel_pending_history(self, *_args):
        if self._history_timer.isActive():
            self._history_timer.stop()

    def _commit_pending_history(self):
        text = str(self._pending_history_text or '').strip()
        if not text:
            return
        if text != self.text().strip():
            return
        history = [item for item in self.get_filter_history() if item != text]
        history.insert(0, text)
        history = history[:12]
        settings.setValue('image_list_filter_history', history)
        self._suggestion_popup.set_history_items(history)

    def clear_filter_history(self):
        settings.setValue('image_list_filter_history', [])
        self._suggestion_popup.set_history_items([])

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._suggestion_popup.isVisible():
            self._suggestion_popup.show_for(self)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.apply_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def parse_filter_text(self) -> list | str | None:
        filter_text = self.text()
        if not filter_text:
            self.setStyleSheet('padding: 8px;')
            return None
        try:
            filter_ = self.filter_text_parser.parse_string(
                filter_text, parse_all=True).as_list()[0]
            filter_ = replace_filter_wildcards(filter_)
            self.setStyleSheet('padding: 8px;')
            return filter_
        except ParseException:
            # Change the background color when the filter text is invalid.
            if self.palette().color(self.backgroundRole()).lightness() < 128:
                # Dark red for dark mode.
                self.setStyleSheet('padding: 8px; background-color: #442222;')
            else:
                # Light red for light mode.
                self.setStyleSheet('padding: 8px; background-color: #ffdddd;')
            return None


class SelectionMode(str, Enum):
    DEFAULT = 'Default'
    TOGGLE = 'Toggle'


class ImageDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.labels = {}
        self._paint_cache = {}  # Cache to skip redundant paint operations
        self._paint_version = 0  # Increment when cache should be invalidated
        self._video_stamp_margin = 5
        self._video_stamp_diameter = 18
        self._filename_tooltip_delay_ms = 1300
        self._filename_tooltip_max_chars = 80
        # Logical pixels in viewport coordinates; tuned higher to avoid jitter.
        self._filename_tooltip_move_tolerance_px = 12
        # Keep visible until movement/leave logic dismisses it.
        self._filename_tooltip_display_ms = 600000
        self._filename_tooltip_token = 0
        self._last_hover_move_monotonic = time.monotonic()
        self._filename_tooltip_anchor_pos = None
        self._tracked_viewport = None
        self._review_badge_margin = 5
        self._review_badge_size = 18
        self._review_badge_gap = 4
        self._reaction_badge_margin = 5
        self._reaction_badge_size = 18
        self._reaction_badge_gap = 4
        self._star_badge_margin = 5
        self._star_badge_height = 18
        self._star_badge_vertical_gap = 4
        self.refresh_thumbnail_badge_settings()

    def refresh_thumbnail_badge_settings(self):
        self._show_review_badges = settings.value(
            'thumbnail_show_review_badges',
            defaultValue=True,
            type=bool,
        )
        self._show_reaction_badges = settings.value(
            'thumbnail_show_reaction_badges',
            defaultValue=True,
            type=bool,
        )
        self._show_star_rating_badge = settings.value(
            'thumbnail_show_star_rating_badge',
            defaultValue=True,
            type=bool,
        )
        self._review_badge_style = normalize_thumbnail_review_badge_style(
            settings.value(
                'thumbnail_review_badge_style',
                defaultValue='Review Tile',
                type=str,
            )
        )
        self._reaction_badge_position = normalize_thumbnail_badge_side(
            settings.value(
                'thumbnail_reaction_badge_position',
                defaultValue='Left',
                type=str,
            )
        )
        self._reaction_badge_style = normalize_thumbnail_reaction_badge_style(
            settings.value(
                'thumbnail_reaction_badge_style',
                defaultValue='Review Tile',
                type=str,
            )
        )
        self._star_badge_position = normalize_thumbnail_badge_side(
            settings.value(
                'thumbnail_star_rating_badge_position',
                defaultValue='Right',
                type=str,
            )
        )
        self._star_badge_style = normalize_thumbnail_star_badge_style(
            settings.value(
                'thumbnail_star_rating_badge_style',
                defaultValue='Halo Tag: 3★',
                type=str,
            )
        )

    def _event_pos(self, event):
        try:
            if hasattr(event, 'position'):
                position = event.position()
                if position is not None:
                    return position.toPoint()
        except Exception:
            pass
        try:
            return event.pos()
        except Exception:
            return None

    def _format_file_size(self, size_bytes):
        if size_bytes is None or size_bytes < 0:
            return None
        size = float(size_bytes)
        for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
            if size < 1024 or unit == 'TB':
                return f"{int(size)} {unit}" if unit == 'B' else f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"

    def _build_filename_size_tooltip(self, image):
        file_name = getattr(getattr(image, 'path', None), 'name', None)
        if not file_name:
            return None
        if len(file_name) > self._filename_tooltip_max_chars:
            suffix = Path(file_name).suffix
            head_max = self._filename_tooltip_max_chars - len(suffix) - 3
            if suffix and head_max > 0:
                file_name = file_name[:head_max] + '...' + suffix
            else:
                file_name = file_name[:self._filename_tooltip_max_chars - 3] + '...'

        size_bytes = getattr(image, 'file_size', None)
        if size_bytes is None:
            path = getattr(image, 'path', None)
            if path:
                try:
                    size_bytes = path.stat().st_size
                    image.file_size = size_bytes
                except OSError:
                    size_bytes = None

        size_text = self._format_file_size(size_bytes)
        if size_text:
            return f"{file_name} - {size_text}"
        return str(file_name)

    def clear_labels(self):
        """Clear all stored labels (called on model reset)."""
        self.labels.clear()
        self._paint_cache.clear()
        self._paint_version += 1

    def sizeHint(self, option, index):
        # Check if parent is using masonry layout
        if isinstance(self.parent(), QListView):
            parent_view = self.parent()
            virtual_list_mode = bool(
                hasattr(parent_view, "use_virtual_list")
                and parent_view.use_virtual_list
            )
            if (hasattr(parent_view, '_drag_preview_mode') and parent_view._drag_preview_mode):
                icon_size = parent_view.iconSize()
                return QSize(icon_size.width() + 6, icon_size.width() + 6)
            if hasattr(parent_view, 'use_masonry') and parent_view.use_masonry and parent_view._masonry_items:
                # Return the actual masonry size for this item
                rect = parent_view._get_masonry_item_rect(index.row())
                if rect.isValid():
                    return rect.size()
            elif parent_view.viewMode() == QListView.ViewMode.IconMode and not virtual_list_mode:
                # Regular icon mode (not masonry)
                icon_size = parent_view.iconSize()
                return QSize(icon_size.width() + 10, icon_size.height() + 10)

            # In ListMode, keep a classic list row: thumbnail at left + text at right.
            # Preserve zoom-driven row height while allowing style-driven width.
            base_hint = super().sizeHint(option, index)
            icon_size = parent_view.iconSize()
            row_height = max(base_hint.height(), icon_size.width() + 4)
            row_width = max(base_hint.width(), 320)
            return QSize(row_width, row_height)

        return super().sizeHint(option, index)

    def paint(self, painter, option, index):
        # Validate painter state before any painting operations
        if not painter or not painter.isActive():
            return

        # Validate index and painter before painting
        if not index.isValid():
            return

        # Additional safety: check if model and data are valid
        try:
            if not index.model():
                return
            # Try to access data to ensure index is truly valid
            index.data(Qt.ItemDataRole.DisplayRole)
        except (RuntimeError, AttributeError):
            return

        parent_view = self.parent() if isinstance(self.parent(), QListView) else None
        list_mode = (
            parent_view is not None
            and not (hasattr(parent_view, "use_masonry") and parent_view.use_masonry)
            and (
                parent_view.viewMode() == QListView.ViewMode.ListMode
                or (hasattr(parent_view, "use_virtual_list") and parent_view.use_virtual_list)
            )
        )

        if list_mode:
            # Use native delegate paint in list mode so thumbnail/text layout matches
            # the classic TagGUI behavior (icon left, filename/tags on the right).
            try:
                list_option = QStyleOptionViewItem(option)
                self.initStyleOption(list_option, index)
                list_option.displayAlignment = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                list_option.decorationAlignment = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                list_option.textElideMode = Qt.TextElideMode.ElideRight
                super().paint(painter, list_option, index)
            except RuntimeError:
                return
        else:
            # MASONRY/GRID PAINTING LOGIC
            # Always paint the icon filling the entire rect provided by the layout.
            if option.state & QStyle.StateFlag.State_Selected:
                painter.fillRect(option.rect, option.palette.highlight())
            else:
                painter.fillRect(option.rect, option.palette.base())

            try:
                icon = index.data(Qt.ItemDataRole.DecorationRole)
                if icon and not icon.isNull():
                    icon.paint(painter, option.rect, Qt.AlignmentFlag.AlignCenter)
            except RuntimeError:
                return

        # Paint custom labels if any
        if painter.isActive():
            p_index = QPersistentModelIndex(index)
            if p_index.isValid() and p_index in self.labels:
                label_text = self.labels[p_index]
                painter.setBrush(QColor(255, 255, 255, 163))
                painter.drawRect(option.rect)
                painter.drawText(option.rect, label_text, Qt.AlignCenter)

        # Draw N*4+1 stamp for video files (in both modes)
        self._draw_n4_plus_1_stamp(painter, option, index)
        self._draw_review_badges(painter, option, index)
        self._draw_reaction_badges(painter, option, index)
        self._draw_star_rating_badge(painter, option, index)

        # Draw red border for images marked for deletion (thick, appears below blue border)
        try:
            image = index.data(Qt.ItemDataRole.UserRole)
            if image and hasattr(image, 'marked_for_deletion') and image.marked_for_deletion:
                painter.save()
                pen = QPen(QColor(255, 0, 0), 8)  # Thick border (8px)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(option.rect.adjusted(2, 2, -2, -2))
                painter.restore()
        except (RuntimeError, AttributeError):
            pass

    def update_label(self, index: QModelIndex, label: str):
        p_index = QPersistentModelIndex(index)
        self.labels[p_index] = label
        self.parent().update(p_index)

    def remove_label(self, index: QPersistentModelIndex):
        p_index = QPersistentModelIndex(index)
        if p_index in self.labels:
            del self.labels[p_index]
            self.parent().update(index)

    def _video_stamp_rect(self, option):
        return self._video_stamp_rect_from_rect(option.rect)

    def _video_stamp_rect_from_rect(self, rect):
        return QRect(
            rect.left() + self._video_stamp_margin,
            rect.top() + self._video_stamp_margin,
            self._video_stamp_diameter,
            self._video_stamp_diameter,
        )

    def _show_delayed_filename_tooltip(self, view, p_index, token):
        if token != self._filename_tooltip_token:
            return
        try:
            if not p_index.isValid():
                return
            viewport = view.viewport()
            if viewport is None:
                return

            cursor_pos = viewport.mapFromGlobal(QCursor.pos())
            if not viewport.rect().contains(cursor_pos):
                return

            current_index = view.indexAt(cursor_pos)
            if not current_index.isValid() or QPersistentModelIndex(current_index) != p_index:
                return

            # Do not override badge hover; badge tooltip should stay primary/fast.
            item_rect = view.visualRect(current_index)
            badge_rect = self._video_stamp_rect_from_rect(item_rect).adjusted(-2, -2, 2, 2)
            if badge_rect.contains(cursor_pos):
                return

            image = p_index.data(Qt.ItemDataRole.UserRole)
            if not image:
                return
            tooltip_text = self._build_filename_size_tooltip(image)
            if tooltip_text:
                # Keep tooltip active across tiny cursor drift; we control dismissal
                # in eventFilter using a movement threshold from anchor_pos.
                QToolTip.showText(
                    QCursor.pos(),
                    tooltip_text,
                    viewport,
                    viewport.rect(),
                    self._filename_tooltip_display_ms,
                )
                self._filename_tooltip_anchor_pos = cursor_pos
        except Exception:
            pass

    def _ensure_hover_tracking(self, view):
        try:
            viewport = view.viewport()
            if viewport is None:
                return
            if self._tracked_viewport is viewport:
                return
            if self._tracked_viewport is not None:
                self._tracked_viewport.removeEventFilter(self)
            viewport.setMouseTracking(True)
            viewport.installEventFilter(self)
            self._tracked_viewport = viewport
        except Exception:
            pass

    def eventFilter(self, watched, event):
        if watched is self._tracked_viewport:
            event_type = event.type()
            if event_type in (QEvent.MouseMove, QEvent.HoverMove):
                cursor_pos = self._event_pos(event)
                if (
                    QToolTip.isVisible()
                    and cursor_pos is not None
                    and self._filename_tooltip_anchor_pos is not None
                ):
                    move_distance = (cursor_pos - self._filename_tooltip_anchor_pos).manhattanLength()
                    if move_distance <= self._filename_tooltip_move_tolerance_px:
                        return super().eventFilter(watched, event)

                    # Cursor moved beyond tolerance: dismiss now and restart delay.
                    QToolTip.hideText()
                    self._last_hover_move_monotonic = time.monotonic()
                    self._filename_tooltip_token += 1
                    self._filename_tooltip_anchor_pos = None
                    return super().eventFilter(watched, event)
                self._last_hover_move_monotonic = time.monotonic()
                self._filename_tooltip_token += 1
                self._filename_tooltip_anchor_pos = None
            elif event_type in (QEvent.Leave, QEvent.Wheel, QEvent.MouseButtonPress):
                self._last_hover_move_monotonic = time.monotonic()
                self._filename_tooltip_token += 1
                self._filename_tooltip_anchor_pos = None
                QToolTip.hideText()
        return super().eventFilter(watched, event)

    def helpEvent(self, event, view, option, index):
        """Show filename on hover and keep video stamp tooltip behavior."""
        self._ensure_hover_tracking(view)
        if event.type() == QEvent.ToolTip and index.isValid():
            try:
                image = index.data(Qt.ItemDataRole.UserRole)
                if not image:
                    return super().helpEvent(event, view, option, index)

                # Keep existing N*4+1 stamp tooltip when hovering the stamp.
                if (
                    hasattr(image, 'is_video')
                    and image.is_video
                ):
                    stamp_rect = self._video_stamp_rect(option).adjusted(-2, -2, 2, 2)
                    if stamp_rect.contains(event.pos()):
                        self._filename_tooltip_token += 1
                        tooltip_text = self._build_video_stamp_tooltip(image)
                        if tooltip_text:
                            QToolTip.showText(event.globalPos(), tooltip_text, view, option.rect, 2000)
                            self._filename_tooltip_anchor_pos = None
                            return True

                # Default hover tooltip for all items: filename only.
                file_name = getattr(getattr(image, 'path', None), 'name', None)
                if file_name:
                    self._filename_tooltip_token += 1
                    token = self._filename_tooltip_token
                    p_index = QPersistentModelIndex(index)
                    elapsed_ms = int((time.monotonic() - self._last_hover_move_monotonic) * 1000)
                    delay_ms = max(0, self._filename_tooltip_delay_ms - elapsed_ms)
                    QTimer.singleShot(
                        delay_ms,
                        lambda: self._show_delayed_filename_tooltip(view, p_index, token),
                    )
                    return True
            except Exception:
                pass
        return super().helpEvent(event, view, option, index)

    def _get_video_stamp_status(self, image) -> tuple[QColor, str | None]:
        """Return badge color and tooltip text for a video thumbnail stamp."""
        if not getattr(image, 'is_video', False):
            return QColor(255, 255, 255, 0), None

        video_metadata = getattr(image, 'video_metadata', None) or {}
        try:
            frame_count = int(video_metadata.get('frame_count') or 0)
        except (TypeError, ValueError):
            frame_count = 0

        if frame_count > 0:
            is_valid = (frame_count - 1) % 4 == 0
            color = QColor(76, 175, 80, 235) if is_valid else QColor(244, 67, 54, 235)
            tooltip = (
                f"N*4+1 validation: {'Valid' if is_valid else 'Invalid'}\n"
                f"Frame count: {frame_count}"
            )
            return color, tooltip

        return QColor(71, 85, 105, 235), "Video"

    def _build_video_stamp_tooltip(self, image) -> str | None:
        """Build tooltip text for the video stamp."""
        _color, tooltip = self._get_video_stamp_status(image)
        return tooltip

    def _draw_n4_plus_1_stamp(self, painter, option, index):
        """Draw the video stamp, with validation color when frame metadata is available."""
        try:
            # Validate painter state
            if not painter or not painter.isActive():
                return

            # Get the image data
            image = index.data(Qt.ItemDataRole.UserRole)
            if not image or not hasattr(image, 'is_video') or not image.is_video:
                return

            # Draw a neutral video badge until frame metadata is available.
            badge_color, _tooltip = self._get_video_stamp_status(image)

            # Skip stamp drawing when items are too small for the badge.
            if option.rect.width() < 26 or option.rect.height() < 26:
                return

            # Set up painter for stamp
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            # Reuse cached pens/brushes to keep paint lightweight.
            if not hasattr(self, '_stamp_outline_pen'):
                self._stamp_outline_pen = QPen(QColor(255, 255, 255, 235), 1.3)
                self._stamp_shadow_pen = QPen(QColor(0, 0, 0, 70), 1.3)
                self._stamp_green_brush = QColor(76, 175, 80, 235)
                self._stamp_red_brush = QColor(244, 67, 54, 235)
                self._stamp_shadow_brush = QColor(0, 0, 0, 65)
                self._stamp_play_color = QColor(255, 255, 255, 240)

            stamp_rect = self._video_stamp_rect(option)
            shadow_rect = stamp_rect.translated(1, 1)

            # Shadow pass
            painter.setPen(self._stamp_shadow_pen)
            painter.setBrush(self._stamp_shadow_brush)
            painter.drawEllipse(shadow_rect)

            # Colored status badge
            painter.setPen(self._stamp_outline_pen)
            painter.setBrush(badge_color)
            painter.drawEllipse(stamp_rect)

            # Play triangle
            cx = stamp_rect.center().x()
            cy = stamp_rect.center().y()
            triangle = QPolygon([
                QPoint(cx - 2, cy - 4),
                QPoint(cx - 2, cy + 4),
                QPoint(cx + 4, cy),
            ])
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._stamp_play_color)
            painter.drawPolygon(triangle)

            painter.restore()

        except Exception:
            # Silently ignore any errors in stamp drawing
            pass

    def _draw_review_badges(self, painter, option, index):
        """Draw compact review-mark badges on the top-right corner."""
        try:
            if not painter or not painter.isActive():
                return
            if not bool(getattr(self, '_show_review_badges', True)):
                return

            image = index.data(Qt.ItemDataRole.UserRole)
            if not image:
                return

            review_rank = int(getattr(image, 'review_rank', 0) or 0)
            review_flags = int(getattr(image, 'review_flags', 0) or 0)
            if review_rank <= 0 and review_flags == 0:
                return

            if option.rect.width() < 32 or option.rect.height() < 26:
                return

            badges: list[tuple[str, QColor]] = []
            if review_rank > 0:
                spec = get_review_badge_spec_for_rank(review_rank)
                if spec is not None:
                    badges.append((str(spec.label), QColor(spec.color)))
            for flag in iter_review_flags(review_flags):
                spec = get_review_badge_spec_for_flag(flag)
                if spec is not None:
                    badges.append((str(spec.label), QColor(spec.color)))

            if not badges:
                return

            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            font = painter.font()
            font.setBold(True)
            font.setPointSizeF(float(get_review_badge_font_size()))
            painter.setFont(font)
            text_color = QColor(get_review_badge_text_color())
            text_color.setAlpha(245)
            style_spec = self._review_badge_style_spec()
            radius = float(get_review_badge_corner_radius())

            badge_size = self._review_badge_size
            gap = self._review_badge_gap
            x = option.rect.right() - self._review_badge_margin - badge_size + 1
            y = option.rect.top() + self._review_badge_margin

            for label, color in badges:
                badge_rect = QRect(x, y, badge_size, badge_size)
                fill, outline = self._review_badge_palette(color, style_spec)
                self._draw_overlay_chip(
                    painter,
                    badge_rect,
                    fill=fill,
                    outline=outline,
                    radius=radius,
                    shadow=QColor(style_spec.get('shadow', QColor(0, 0, 0, 60))),
                    variant=str(style_spec.get('variant', 'solid') or 'solid'),
                    glass_highlight=QColor(style_spec.get('glass_highlight', QColor(255, 255, 255, 68))),
                    text=label,
                    text_color=text_color,
                )
                x -= badge_size + gap

            painter.restore()
        except Exception:
            pass

    def _reaction_icon_path(self, kind: str, rect: QRect) -> QPainterPath:
        icon_rect = rect.adjusted(3, 3, -3, -3)
        left = float(icon_rect.left())
        top = float(icon_rect.top())
        right = float(icon_rect.right())
        bottom = float(icon_rect.bottom())
        width = float(icon_rect.width())
        height = float(icon_rect.height())

        if str(kind or "").strip().lower() == 'love':
            path = QPainterPath()
            path.moveTo(left + 0.5 * width, bottom - 0.12 * height)
            path.cubicTo(
                left + 0.12 * width, top + 0.62 * height,
                left + 0.04 * width, top + 0.24 * height,
                left + 0.28 * width, top + 0.16 * height,
            )
            path.cubicTo(
                left + 0.42 * width, top + 0.10 * height,
                left + 0.50 * width, top + 0.20 * height,
                left + 0.50 * width, top + 0.28 * height,
            )
            path.cubicTo(
                left + 0.50 * width, top + 0.20 * height,
                left + 0.58 * width, top + 0.10 * height,
                left + 0.72 * width, top + 0.16 * height,
            )
            path.cubicTo(
                left + 0.96 * width, top + 0.24 * height,
                left + 0.88 * width, top + 0.62 * height,
                left + 0.50 * width, bottom - 0.12 * height,
            )
            path.closeSubpath()
            return path

        path = QPainterPath()
        center_x = left + 0.5 * width
        center_y = top + 0.5 * height
        radius = min(width, height) * 0.27
        path.addEllipse(QRect(int(center_x - radius), int(center_y - radius), int(radius * 2), int(radius * 2)))
        fuse_start_x = center_x + radius * 0.45
        fuse_start_y = center_y - radius * 0.85
        fuse_mid_x = right - width * 0.18
        fuse_mid_y = top + height * 0.20
        fuse_end_x = right - width * 0.10
        fuse_end_y = top + height * 0.08
        path.moveTo(fuse_start_x, fuse_start_y)
        path.cubicTo(fuse_mid_x, fuse_mid_y, fuse_mid_x, fuse_mid_y, fuse_end_x, fuse_end_y)
        spark_radius = radius * 0.16
        path.addEllipse(
            QRect(
                int(center_x + radius * 0.22 - spark_radius),
                int(center_y - radius * 0.12 - spark_radius),
                max(1, int(spark_radius * 2)),
                max(1, int(spark_radius * 2)),
            )
        )
        return path

    @staticmethod
    def _color_with_alpha(color: QColor, alpha: int) -> QColor:
        result = QColor(color)
        result.setAlpha(max(0, min(255, int(alpha))))
        return result

    @staticmethod
    def _blend_colors(first: QColor, second: QColor, ratio: float, alpha: int | None = None) -> QColor:
        ratio = max(0.0, min(1.0, float(ratio)))
        mixed = QColor(
            int(first.red() * (1.0 - ratio) + second.red() * ratio),
            int(first.green() * (1.0 - ratio) + second.green() * ratio),
            int(first.blue() * (1.0 - ratio) + second.blue() * ratio),
            int(first.alpha() * (1.0 - ratio) + second.alpha() * ratio),
        )
        if alpha is not None:
            mixed.setAlpha(max(0, min(255, int(alpha))))
        return mixed

    def _review_badge_style_spec(self) -> dict:
        return get_thumbnail_review_badge_style_spec(
            str(getattr(self, '_review_badge_style', 'review_tile') or 'review_tile')
        )

    def _reaction_badge_style_spec(self) -> dict:
        return get_thumbnail_reaction_badge_style_spec(
            str(getattr(self, '_reaction_badge_style', 'review_tile') or 'review_tile')
        )

    def _review_badge_palette(self, base_color: QColor, style_spec: dict) -> tuple[QColor, QColor]:
        fill_mode = str(style_spec.get('fill_mode', 'base') or 'base')
        if fill_mode == 'dark':
            fill = QColor(style_spec.get('dark_fill', QColor(27, 30, 37, 236)))
        elif fill_mode == 'base_soft':
            fill = QColor(base_color)
            fill.setAlpha(int(style_spec.get('fill_alpha', 120)))
        elif fill_mode == 'warm_base':
            fill = self._blend_colors(
                QColor(base_color),
                QColor(style_spec.get('warm_tint', QColor(255, 162, 102, 255))),
                float(style_spec.get('warm_ratio', 0.16)),
                alpha=QColor(base_color).alpha(),
            )
        else:
            fill = QColor(base_color)

        if str(style_spec.get('outline_mode', 'fixed') or 'fixed') == 'base':
            outline = self._color_with_alpha(QColor(base_color), int(style_spec.get('outline_alpha', 230)))
        else:
            outline = QColor(style_spec.get('outline', QColor(255, 255, 255, 235)))
        return fill, outline

    def _reaction_badge_palette(self, kind: str, style_spec: dict) -> tuple[QColor, QColor, QColor]:
        prefix = 'love' if str(kind or '').strip().lower() == 'love' else 'bomb'
        fill = QColor(style_spec.get(f'{prefix}_fill', QColor(255, 255, 255, 240)))
        outline = QColor(style_spec.get(f'{prefix}_outline', style_spec.get('outline', QColor(255, 255, 255, 235))))
        icon = QColor(style_spec.get(f'{prefix}_icon', QColor(255, 255, 255, 255)))
        return fill, outline, icon

    def _draw_overlay_chip(
        self,
        painter,
        rect: QRect,
        *,
        fill: QColor,
        outline: QColor,
        radius: float,
        shadow: QColor,
        variant: str = 'solid',
        glass_highlight: QColor | None = None,
        text: str | None = None,
        text_color: QColor | None = None,
        path: QPainterPath | None = None,
        icon_color: QColor | None = None,
    ):
        shadow_rect = rect.translated(1, 1)
        shadow_pen = QColor(0, 0, 0, min(255, shadow.alpha() + 6))
        painter.setPen(QPen(shadow_pen, 1.1))
        painter.setBrush(shadow)
        painter.drawRoundedRect(shadow_rect, radius, radius)
        painter.setPen(QPen(outline, 1.1))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, radius, radius)

        if variant == 'glass':
            highlight = QRect(
                rect.left() + 1,
                rect.top() + 1,
                max(6, rect.width() - 2),
                max(4, int(rect.height() * 0.45)),
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(glass_highlight or QColor(255, 255, 255, 68)))
            painter.drawRoundedRect(highlight, max(3.0, radius - 2.0), max(3.0, radius - 2.0))

        if path is not None and icon_color is not None:
            painter.setPen(
                QPen(
                    icon_color,
                    1.3,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                    Qt.PenJoinStyle.RoundJoin,
                )
            )
            painter.setBrush(icon_color)
            painter.drawPath(path)
            return

        if text is not None and text_color is not None:
            painter.setPen(text_color)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _star_rating_value_text(self, image) -> str | None:
        try:
            rating_value = float(getattr(image, 'rating', 0.0) or 0.0)
        except Exception:
            rating_value = 0.0
        if rating_value <= 0.0:
            return None
        stars = max(0.0, min(5.0, rating_value * 5.0))
        rounded_half = round(stars * 2.0) / 2.0
        if rounded_half <= 0.0:
            return None
        if abs(rounded_half - round(rounded_half)) < 0.001:
            return str(int(round(rounded_half)))
        return f"{rounded_half:.1f}".rstrip('0').rstrip('.')

    def _star_badge_style_spec(self) -> dict:
        return get_thumbnail_star_badge_style_spec(
            str(getattr(self, '_star_badge_style', 'halo_tag_star_right') or 'halo_tag_star_right')
        )

    def _star_badge_label(self, image) -> str | None:
        value_text = self._star_rating_value_text(image)
        if not value_text:
            return None
        style_spec = self._star_badge_style_spec()
        if style_spec.get('label_order') == 'star_right':
            return f"{value_text}★"
        return f"★{value_text}"

    def _bottom_badge_group_offsets(self, option, image) -> dict[str, int]:
        offsets = {
            'left': 0,
            'right': 0,
        }
        if (
            bool(getattr(self, '_show_reaction_badges', True))
            and bool(getattr(image, 'love', False) or getattr(image, 'bomb', False))
            and getattr(self, '_reaction_badge_position', 'left') == getattr(self, '_star_badge_position', 'right')
            and bool(getattr(self, '_show_star_rating_badge', True))
            and self._star_rating_value_text(image)
        ):
            offsets[str(getattr(self, '_star_badge_position', 'right'))] = (
                self._star_badge_height + self._star_badge_vertical_gap
            )
        return offsets

    def _star_badge_rect(self, option, image, label: str, font_metrics):
        style_spec = self._star_badge_style_spec()
        variant = str(style_spec.get('variant', 'pill') or 'pill')
        value_text = self._star_rating_value_text(image) or label.replace('★', '').strip()
        if variant == 'halo':
            halo_diameter = max(16, min(self._star_badge_height + 2, int(style_spec.get('halo_diameter', 18))))
            badge_width = int(font_metrics.horizontalAdvance(value_text)) + halo_diameter + int(style_spec.get('padding_x', 18))
        elif variant == 'split':
            accent_width = max(16, int(style_spec.get('accent_width', 20)))
            badge_width = int(font_metrics.horizontalAdvance(value_text)) + accent_width + int(style_spec.get('padding_x', 16))
        else:
            badge_width = int(font_metrics.horizontalAdvance(label)) + int(style_spec.get('padding_x', 12))
        badge_width = max(self._star_badge_height + 8, int(badge_width))
        side = str(getattr(self, '_star_badge_position', 'right'))
        y = (
            option.rect.bottom()
            - self._star_badge_margin
            - self._star_badge_height
            + 1
            - self._bottom_badge_group_offsets(option, image).get(side, 0)
        )
        if side == 'left':
            x = option.rect.left() + self._star_badge_margin
        else:
            x = option.rect.right() - self._star_badge_margin - badge_width + 1
        return QRect(int(x), int(y), int(badge_width), int(self._star_badge_height))

    def _draw_star_badge_pill(self, painter, badge_rect: QRect, label: str, style_spec: dict):
        shadow_rect = badge_rect.translated(1, 1)
        radius = float(style_spec.get('radius', 5.0))
        painter.setPen(QPen(QColor(0, 0, 0, 55), 1.2))
        painter.setBrush(QColor(style_spec.get('shadow', QColor(0, 0, 0, 60))))
        painter.drawRoundedRect(shadow_rect, radius, radius)
        painter.setPen(QPen(QColor(style_spec.get('outline', QColor(255, 255, 255, 235))), 1.2))
        painter.setBrush(QColor(style_spec.get('fill', QColor(255, 233, 166, 245))))
        painter.drawRoundedRect(badge_rect, radius, radius)
        painter.setPen(QColor(style_spec.get('text', QColor(122, 82, 0, 255))))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, label)

    def _draw_star_badge_glass(self, painter, badge_rect: QRect, label: str, style_spec: dict):
        shadow_rect = badge_rect.translated(1, 1)
        radius = float(style_spec.get('radius', 7.0))
        painter.setPen(QPen(QColor(0, 0, 0, 35), 1.0))
        painter.setBrush(QColor(style_spec.get('shadow', QColor(0, 0, 0, 38))))
        painter.drawRoundedRect(shadow_rect, radius, radius)
        painter.setPen(QPen(QColor(style_spec.get('outline', QColor(255, 255, 255, 165))), 1.1))
        painter.setBrush(QColor(style_spec.get('fill', QColor(255, 252, 243, 112))))
        painter.drawRoundedRect(badge_rect, radius, radius)
        highlight = QRect(
            badge_rect.left() + 1,
            badge_rect.top() + 1,
            max(6, badge_rect.width() - 2),
            max(4, int(badge_rect.height() * 0.45)),
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(style_spec.get('glass_highlight', QColor(255, 255, 255, 68))))
        painter.drawRoundedRect(highlight, max(3.0, radius - 2.0), max(3.0, radius - 2.0))
        painter.setPen(QColor(style_spec.get('text', QColor(255, 247, 230, 255))))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, label)

    def _draw_star_badge_split(self, painter, badge_rect: QRect, label: str, style_spec: dict):
        shadow_rect = badge_rect.translated(1, 1)
        radius = float(style_spec.get('radius', 7.0))
        painter.setPen(QPen(QColor(0, 0, 0, 50), 1.1))
        painter.setBrush(QColor(style_spec.get('shadow', QColor(0, 0, 0, 54))))
        painter.drawRoundedRect(shadow_rect, radius, radius)
        painter.setPen(QPen(QColor(style_spec.get('outline', QColor(255, 255, 255, 220))), 1.1))
        painter.setBrush(QColor(style_spec.get('fill', QColor(255, 244, 217, 228))))
        painter.drawRoundedRect(badge_rect, radius, radius)

        star_right = style_spec.get('label_order') == 'star_right'
        accent_width = max(16, min(badge_rect.width() - 10, int(style_spec.get('accent_width', 20))))
        if star_right:
            accent_rect = QRect(badge_rect.right() - accent_width + 1, badge_rect.top(), accent_width, badge_rect.height())
            value_rect = QRect(badge_rect.left(), badge_rect.top(), badge_rect.width() - accent_width + 1, badge_rect.height())
        else:
            accent_rect = QRect(badge_rect.left(), badge_rect.top(), accent_width, badge_rect.height())
            value_rect = QRect(badge_rect.left() + accent_width - 1, badge_rect.top(), badge_rect.width() - accent_width + 1, badge_rect.height())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(style_spec.get('accent_fill', QColor(245, 185, 54, 246))))
        painter.drawRoundedRect(accent_rect.adjusted(0, 0, 0, 0), radius, radius)
        painter.setPen(QPen(QColor(style_spec.get('divider', QColor(172, 115, 0, 70))), 1.0))
        divider_x = accent_rect.right() if not star_right else accent_rect.left()
        painter.drawLine(divider_x, badge_rect.top() + 2, divider_x, badge_rect.bottom() - 2)
        painter.setPen(QColor(style_spec.get('accent_text', QColor(255, 255, 255, 255))))
        painter.drawText(accent_rect, Qt.AlignmentFlag.AlignCenter, '★')
        painter.setPen(QColor(style_spec.get('text', QColor(92, 54, 0, 255))))
        value_text = label.replace('★', '').strip()
        painter.drawText(value_rect, Qt.AlignmentFlag.AlignCenter, value_text)

    def _draw_star_badge_halo(self, painter, badge_rect: QRect, label: str, style_spec: dict):
        shadow_rect = badge_rect.translated(1, 1)
        radius = float(style_spec.get('radius', 7.0))
        halo_diameter = max(16, min(badge_rect.height() + 2, int(style_spec.get('halo_diameter', 18))))
        star_right = style_spec.get('label_order') == 'star_right'
        value_text = label.replace('★', '').strip()
        painter.setPen(QPen(QColor(0, 0, 0, 55), 1.1))
        painter.setBrush(QColor(style_spec.get('shadow', QColor(0, 0, 0, 60))))
        painter.drawRoundedRect(shadow_rect, radius, radius)
        painter.setPen(QPen(QColor(style_spec.get('outline', QColor(255, 214, 124, 170))), 1.1))
        painter.setBrush(QColor(style_spec.get('fill', QColor(40, 34, 26, 176))))
        painter.drawRoundedRect(badge_rect, radius, radius)
        halo_y = badge_rect.center().y() - halo_diameter / 2.0
        gap = 2
        if star_right:
            halo_x = badge_rect.right() - halo_diameter + 1
            value_rect = QRect(
                badge_rect.left() + 4,
                badge_rect.top(),
                max(10, badge_rect.width() - halo_diameter - gap - 5),
                badge_rect.height(),
            )
        else:
            halo_x = badge_rect.left()
            value_rect = QRect(
                badge_rect.left() + halo_diameter + gap - 2,
                badge_rect.top(),
                max(10, badge_rect.width() - halo_diameter - gap - 5),
                badge_rect.height(),
            )
        halo_rect = QRect(
            int(halo_x),
            int(badge_rect.top() + max(0, (badge_rect.height() - halo_diameter) // 2)),
            int(halo_diameter),
            int(halo_diameter),
        )
        painter.setPen(QPen(QColor(255, 255, 255, 220), 1.0))
        painter.setBrush(QColor(style_spec.get('halo_fill', QColor(255, 210, 94, 245))))
        painter.drawEllipse(halo_rect)
        painter.setPen(QColor(style_spec.get('halo_text', QColor(92, 42, 0, 255))))
        painter.drawText(halo_rect, Qt.AlignmentFlag.AlignCenter, '★')
        painter.setPen(QColor(style_spec.get('text', QColor(255, 240, 199, 255))))
        if star_right:
            text_rect = value_rect.adjusted(1, 0, -1, 0)
            text_align = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        else:
            text_rect = value_rect.adjusted(1, 0, -1, 0)
            text_align = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
        painter.drawText(text_rect, text_align, value_text)

    def _draw_reaction_badges(self, painter, option, index):
        """Draw love/bomb reaction badges on the thumbnail's bottom-left corner."""
        try:
            if not painter or not painter.isActive():
                return
            if not bool(getattr(self, '_show_reaction_badges', True)):
                return

            image = index.data(Qt.ItemDataRole.UserRole)
            if not image:
                return

            badges: list[tuple[str, QColor, QColor]] = []
            if bool(getattr(image, 'love', False)):
                badges.append((
                    'love',
                    QColor(255, 221, 226, 245),
                    QColor(214, 54, 82, 255),
                ))
            if bool(getattr(image, 'bomb', False)):
                badges.append((
                    'bomb',
                    QColor(36, 36, 40, 240),
                    QColor(255, 181, 97, 255),
                ))

            if not badges:
                return

            if option.rect.width() < 30 or option.rect.height() < 30:
                return

            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            style_spec = self._reaction_badge_style_spec()

            badge_size = self._reaction_badge_size
            gap = self._reaction_badge_gap
            radius = float(style_spec.get('radius', 5.0))
            side = str(getattr(self, '_reaction_badge_position', 'left'))
            y = option.rect.bottom() - self._reaction_badge_margin - badge_size + 1
            if side == 'left':
                x = option.rect.left() + self._reaction_badge_margin
            else:
                total_width = len(badges) * badge_size + max(0, len(badges) - 1) * gap
                x = option.rect.right() - self._reaction_badge_margin - total_width + 1

            for kind, _background_color, _icon_color in badges:
                badge_rect = QRect(x, y, badge_size, badge_size)
                fill, outline, icon_color = self._reaction_badge_palette(kind, style_spec)
                self._draw_overlay_chip(
                    painter,
                    badge_rect,
                    fill=fill,
                    outline=outline,
                    radius=radius,
                    shadow=QColor(style_spec.get('shadow', QColor(0, 0, 0, 60))),
                    variant=str(style_spec.get('variant', 'solid') or 'solid'),
                    glass_highlight=QColor(style_spec.get('glass_highlight', QColor(255, 255, 255, 68))),
                    path=self._reaction_icon_path(kind, badge_rect),
                    icon_color=icon_color,
                )
                x += badge_size + gap

            painter.restore()
        except Exception:
            pass

    def _draw_star_rating_badge(self, painter, option, index):
        """Draw a compact bottom-corner star badge such as ★3 or ★4.5."""
        try:
            if not painter or not painter.isActive():
                return
            if not bool(getattr(self, '_show_star_rating_badge', True)):
                return

            image = index.data(Qt.ItemDataRole.UserRole)
            if not image:
                return

            label = self._star_badge_label(image)
            if not label:
                return

            if option.rect.width() < 34 or option.rect.height() < 30:
                return

            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            style_spec = self._star_badge_style_spec()
            font = painter.font()
            font.setBold(True)
            font.setPointSizeF(float(style_spec.get('font_size', 9.0)))
            painter.setFont(font)
            fm = painter.fontMetrics()
            badge_rect = self._star_badge_rect(option, image, label, fm)
            variant = str(style_spec.get('variant', 'pill') or 'pill')
            if variant == 'glass':
                self._draw_star_badge_glass(painter, badge_rect, label, style_spec)
            elif variant == 'split':
                self._draw_star_badge_split(painter, badge_rect, label, style_spec)
            elif variant == 'halo':
                self._draw_star_badge_halo(painter, badge_rect, label, style_spec)
            else:
                self._draw_star_badge_pill(painter, badge_rect, label, style_spec)
            painter.restore()
        except Exception:
            pass
