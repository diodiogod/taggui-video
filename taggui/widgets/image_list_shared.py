import shutil
import time
from enum import Enum
from functools import reduce
from operator import or_
from pathlib import Path

from PySide6.QtCore import (QFile, QItemSelection, QItemSelectionModel,
                            QItemSelectionRange, QModelIndex, QSize, QUrl, Qt,
                            Signal, Slot, QPersistentModelIndex, QProcess, QTimer, QRect, QEvent, QPoint)
from PySide6.QtGui import QDesktopServices, QColor, QPen, QPixmap, QPainter, QDrag
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

    def helpEvent(self, event, view, option, index):
        """Provide tooltip for N*4+1 stamp on hover."""
        if event.type() == QEvent.ToolTip and index.isValid():
            try:
                # Get the image data
                image = index.data(Qt.ItemDataRole.UserRole)
                if not image or not hasattr(image, 'is_video') or not image.is_video:
                    return False

                # Check if video has metadata with frame count
                if not hasattr(image, 'video_metadata') or not image.video_metadata:
                    return False

                frame_count = image.video_metadata.get('frame_count', 0)
                if frame_count <= 0:
                    return False

                # Check N*4+1 rule: (frame_count - 1) % 4 == 0
                is_valid = (frame_count - 1) % 4 == 0

                # Stamp position: top-left corner
                margin = 2
                stamp_rect = QRect(option.rect.left() + margin,
                                  option.rect.top() + margin,
                                  80, 20)

                # Check if mouse is over the stamp
                if stamp_rect.contains(event.pos()):
                    tooltip_text = f"N*4+1 validation: {'Valid' if is_valid else 'Invalid'}\nFrame count: {frame_count}"
                    QToolTip.showText(event.globalPos(), tooltip_text, view, 2000)  # 2 second duration
                    return True
                else:
                    # Hide tooltip if not over stamp
                    QToolTip.hideText()
                    return False
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

            # OPTIMIZATION: Skip stamp drawing if item rect is very small (zoomed out)
            # Stamp is unreadable below 50px anyway
            if option.rect.width() < 50:
                return

            # Set up painter for stamp
            painter.save()

            # Stamp position: top-left corner
            margin = 2
            text_rect = QRect(option.rect.left() + margin,
                              option.rect.top() + margin,
                              80, 20)  # Width and height for text

            # OPTIMIZATION: Use static font instead of creating new one each paint
            if not hasattr(self, '_stamp_font'):
                self._stamp_font = painter.font()
                self._stamp_font.setPointSize(10)
                self._stamp_font.setBold(True)
                # Precompute colors
                self._stamp_green_pen = QPen(QColor(76, 175, 80), 2)
                self._stamp_red_pen = QPen(QColor(244, 67, 54), 2)
                self._stamp_shadow_pen = QPen(QColor(0, 0, 0, 100), 1)

            painter.setFont(self._stamp_font)

            # Draw subtle glow (shadow)
            painter.setPen(self._stamp_shadow_pen)
            glow_text = "✓N*4+1" if is_valid else "✗N*4+1"
            painter.drawText(text_rect.adjusted(1, 1, 1, 1), Qt.AlignLeft | Qt.AlignTop, glow_text)

            # Set text color
            painter.setPen(self._stamp_green_pen if is_valid else self._stamp_red_pen)

            # Draw text
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignTop, glow_text)

            painter.restore()

        except Exception:
            # Silently ignore any errors in stamp drawing
            pass
