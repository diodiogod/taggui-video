import shutil
import time
from enum import Enum
from functools import reduce
from operator import or_
from pathlib import Path

from PySide6.QtCore import (QFile, QItemSelection, QItemSelectionModel,
                            QItemSelectionRange, QModelIndex, QSize, QUrl, Qt,
                            Signal, Slot, QPersistentModelIndex, QProcess, QTimer, QRect, QEvent, QPoint)
from PySide6.QtGui import QDesktopServices, QColor, QPen, QPixmap, QPainter, QDrag, QPolygon, QCursor
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDockWidget,
                               QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QListView, QMenu, QMessageBox, QVBoxLayout,
                               QWidget, QStyledItemDelegate, QToolTip, QStyle, QStyleOptionViewItem,
                               QProgressBar)
from pyparsing import (CaselessKeyword, CaselessLiteral, Group, OpAssoc,
                       ParseException, QuotedString, Suppress, Word,
                       infix_notation, nums, one_of, printables)

from models.proxy_image_list_model import ProxyImageListModel
from models.image_list_model import natural_sort_key
from utils.image import Image
from utils.settings import settings
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


class FilterLineEdit(QLineEdit):
    def __init__(self):
        super().__init__()
        self.setPlaceholderText('Filter Images')
        self.setStyleSheet('padding: 8px;')
        self.setClearButtonEnabled(True)
        optionally_quoted_string = (QuotedString(quote_char='"', esc_char='\\')
                                    | QuotedString(quote_char="'",
                                                   esc_char='\\')
                                    | Word(printables, exclude_chars='()'))
        string_filter_keys = ['tag', 'caption', 'marking', 'crops', 'visible',
                              'name', 'path', 'size', 'target']
        string_filter_expressions = [Group(CaselessLiteral(key) + Suppress(':')
                                           + optionally_quoted_string)
                                     for key in string_filter_keys]
        comparison_operator = one_of('= == != < > <= >=')
        number_filter_keys = ['tags', 'chars', 'tokens', 'stars', 'width',
                              'height', 'area']
        number_filter_expressions = [Group(CaselessLiteral(key) + Suppress(':')
                                           + comparison_operator + Word(nums))
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
        self._filename_tooltip_token = 0
        self._last_hover_move_monotonic = time.monotonic()
        self._tracked_viewport = None

    def clear_labels(self):
        """Clear all stored labels (called on model reset)."""
        self.labels.clear()
        self._paint_cache.clear()
        self._paint_version += 1

    def sizeHint(self, option, index):
        # Check if parent is using masonry layout
        if isinstance(self.parent(), QListView):
            parent_view = self.parent()
            if (hasattr(parent_view, '_drag_preview_mode') and parent_view._drag_preview_mode):
                icon_size = parent_view.iconSize()
                return QSize(icon_size.width() + 6, icon_size.width() + 6)
            if hasattr(parent_view, 'use_masonry') and parent_view.use_masonry and parent_view._masonry_items:
                # Return the actual masonry size for this item
                rect = parent_view._get_masonry_item_rect(index.row())
                if rect.isValid():
                    return rect.size()
            elif parent_view.viewMode() == QListView.ViewMode.IconMode:
                # Regular icon mode (not masonry)
                icon_size = parent_view.iconSize()
                return QSize(icon_size.width() + 10, icon_size.height() + 10)
        # In ListMode, height should match the icon height for proper scaling with zoom
        icon_size = self.parent().iconSize()
        # Use the icon height (width dimension is stretched) plus text padding
        return QSize(400, icon_size.width() + 4)  # 400px width is arbitrary, height scales with icon

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

        # MASONRY/GRID PAINTING LOGIC
        # Always paint the icon filling the entire rect provided by the layout.
        # We ignore QListView.ViewMode because our masonry layout controls the rects.
        
        # 1. Paint selection/focus background
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        else:
            painter.fillRect(option.rect, option.palette.base())

        # 2. Paint the icon/thumbnail (DecorationRole)
        try:
            icon = index.data(Qt.ItemDataRole.DecorationRole)
            if icon and not icon.isNull():
                icon.paint(painter, option.rect, Qt.AlignmentFlag.AlignCenter)
        except RuntimeError:
            return

        # 3. Paint text (if needed) - Overlay at bottom or tooltips?
        # The original code painted text "after" the icon in ListMode, or "none" in IconMode.
        # In masonry, we usually want just the image. The text is in the tooltip.
        # If text overlay is desired, uncomment below:
        # text = index.data(Qt.ItemDataRole.DisplayRole)
        # if text:
        #     ... text painting logic ...
        
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
            file_name = getattr(getattr(image, 'path', None), 'name', None)
            if file_name:
                QToolTip.showText(QCursor.pos(), str(file_name), view, item_rect, 1500)
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
                self._last_hover_move_monotonic = time.monotonic()
                self._filename_tooltip_token += 1
            elif event_type in (QEvent.Leave, QEvent.Wheel, QEvent.MouseButtonPress):
                self._last_hover_move_monotonic = time.monotonic()
                self._filename_tooltip_token += 1
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
                    and hasattr(image, 'video_metadata')
                    and image.video_metadata
                ):
                    frame_count = image.video_metadata.get('frame_count', 0)
                    if frame_count > 0:
                        is_valid = (frame_count - 1) % 4 == 0
                        stamp_rect = self._video_stamp_rect(option).adjusted(-2, -2, 2, 2)
                        if stamp_rect.contains(event.pos()):
                            self._filename_tooltip_token += 1
                            tooltip_text = (
                                f"N*4+1 validation: {'Valid' if is_valid else 'Invalid'}\n"
                                f"Frame count: {frame_count}"
                            )
                            QToolTip.showText(event.globalPos(), tooltip_text, view, option.rect, 2000)
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

    def _draw_n4_plus_1_stamp(self, painter, option, index):
        """Draw N*4+1 validation stamp on video file previews (optimized)."""
        try:
            # Validate painter state
            if not painter or not painter.isActive():
                return

            # Get the image data
            image = index.data(Qt.ItemDataRole.UserRole)
            if not image or not hasattr(image, 'is_video') or not image.is_video:
                return

            # Check if video has metadata with frame count
            if not hasattr(image, 'video_metadata') or not image.video_metadata:
                return

            frame_count = image.video_metadata.get('frame_count', 0)
            if frame_count <= 0:
                return

            # Check N*4+1 rule: (frame_count - 1) % 4 == 0
            is_valid = (frame_count - 1) % 4 == 0

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
            painter.setBrush(self._stamp_green_brush if is_valid else self._stamp_red_brush)
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
