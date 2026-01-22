import shutil
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

        # Check if we're in IconMode (compact view without text)
        is_icon_mode = isinstance(self.parent(), QListView) and self.parent().viewMode() == QListView.ViewMode.IconMode

        if is_icon_mode:
            # In IconMode: paint only the icon, no text
            try:
                icon = index.data(Qt.ItemDataRole.DecorationRole)
                if icon and not icon.isNull():
                    # Paint background if selected
                    if option.state & QStyle.StateFlag.State_Selected:
                        painter.fillRect(option.rect, option.palette.highlight())

                    # Paint just the icon, centered
                    icon_size = self.parent().iconSize()
                    x = option.rect.x() + (option.rect.width() - icon_size.width()) // 2
                    y = option.rect.y() + (option.rect.height() - icon_size.height()) // 2
                    icon.paint(painter, x, y, icon_size.width(), icon_size.height())
            except RuntimeError:
                return
        else:
            # In ListMode: manually paint instead of calling super() to avoid pixmap allocation issues
            # Paint background if selected
            if option.state & QStyle.StateFlag.State_Selected:
                painter.fillRect(option.rect, option.palette.highlight())
            else:
                painter.fillRect(option.rect, option.palette.base())

            # Paint the icon/decoration
            icon = index.data(Qt.ItemDataRole.DecorationRole)
            if icon and not icon.isNull():
                # Use the actual icon size instead of hardcoded 34px
                icon_size = self.parent().iconSize()
                icon_rect = option.rect.adjusted(2, 2, -option.rect.width() + icon_size.width() + 4, -2)
                icon.paint(painter, icon_rect.x(), icon_rect.y(), icon_rect.width(), icon_rect.height())

            # Paint the text
            text = index.data(Qt.ItemDataRole.DisplayRole)
            if text:
                # Position text after the icon (which now uses actual icon_size.width())
                icon_size = self.parent().iconSize()
                text_x = 2 + icon_size.width() + 6  # 2px margin + icon width + 6px gap
                text_rect = option.rect.adjusted(text_x, 2, -2, -2)
                painter.setPen(option.palette.text().color())
                painter.drawText(text_rect, Qt.AlignVCenter, str(text))

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


class ImageListView(QListView):
    tags_paste_requested = Signal(list, list)
    directory_reload_requested = Signal()
    layout_ready = Signal()  # Emitted when masonry layout is fully calculated and applied


    def __init__(self, parent, proxy_image_list_model: ProxyImageListModel,
                 tag_separator: str, image_width: int):
        super().__init__(parent)
        self.proxy_image_list_model = proxy_image_list_model
        self.tag_separator = tag_separator
        self.setModel(proxy_image_list_model)
        self.delegate = ImageDelegate(self)
        self.setItemDelegate(self.delegate)

        # Get source model for signal connections
        source_model = proxy_image_list_model.sourceModel()

        # Clear delegate labels when model resets to avoid painting stale indexes
        source_model.modelReset.connect(self.delegate.clear_labels)

        # Disable updates during model reset to prevent paint errors
        # Use source model signals since proxy may not forward modelAboutToBeReset
        source_model.modelAboutToBeReset.connect(self._disable_updates)
        source_model.modelReset.connect(self._enable_updates)

        # Recalculate masonry layout when model changes (including filter changes)
        proxy_image_list_model.modelReset.connect(lambda: self._recalculate_masonry_if_needed("modelReset"))
        proxy_image_list_model.layoutChanged.connect(lambda: self._recalculate_masonry_if_needed("layoutChanged"))
        proxy_image_list_model.filter_changed.connect(lambda: self._recalculate_masonry_if_needed("filter_changed"))

        self.setWordWrap(True)
        self.setDragEnabled(True)

        # Optimize viewport updates to reduce unnecessary repaints during video playback
        # Only update items that actually changed, not entire viewport
        self.viewport().setUpdatesEnabled(True)  # Ensure updates are enabled
        self.setUniformItemSizes(False)  # We use masonry, sizes vary

        # Masonry layout for icon mode
        self.use_masonry = False
        self._masonry_calculating = False  # Re-entry guard for layout calculation
        self._masonry_calc_future = None  # Multiprocessing future
        self._masonry_executor = ThreadPoolExecutor(max_workers=1)  # Single worker thread (ProcessPoolExecutor fails on Windows with heavy threading)
        self._masonry_items = []  # Positioned items from multiprocessing
        self._masonry_total_height = 0  # Total layout height

        # Debounce timer for masonry recalculation (separate from filter debounce)
        self._masonry_recalc_timer = QTimer(self)
        self._masonry_recalc_timer.setSingleShot(True)
        self._masonry_recalc_timer.timeout.connect(self._do_recalculate_masonry)
        self._masonry_recalc_delay = 500  # Base delay
        self._masonry_recalc_min_delay = 500
        self._masonry_recalc_max_delay = 2000  # Max delay for rapid key holds
        self._last_filter_keystroke_time = 0
        self._rapid_input_detected = False
        self._last_masonry_signal = "unknown"  # Track which signal triggered masonry

        # Idle preloading timer for smooth scrolling
        self._idle_preload_timer = QTimer(self)
        self._idle_preload_timer.setSingleShot(True)
        self._idle_preload_timer.timeout.connect(self._preload_all_thumbnails)

        # Page indicator overlay for pagination mode
        self._page_indicator_label = None
        self._page_indicator_timer = QTimer(self)
        self._page_indicator_timer.setSingleShot(True)
        self._page_indicator_timer.timeout.connect(self._fade_out_page_indicator)
        self._preload_index = 0  # Track preload progress
        self._preload_complete = False  # Track if all thumbnails loaded
        self._thumbnails_loaded = set()  # Track which thumbnails are loaded (by index)
        self._thumbnail_cache_hits = set()  # Track unique cache hits by index
        self._thumbnail_cache_misses = set()  # Track unique cache misses by index

        # Loading progress bar for thumbnail preloading
        self._thumbnail_progress_bar = None  # Created on demand

        # Zoom settings
        # Note: Thumbnails are always generated at 512px (max quality)
        # Display size can match generation size since we have the quality
        self.min_thumbnail_size = 64
        self.max_thumbnail_size = 512  # Can display at full 512px since generated at 512px
        self.column_switch_threshold = 150  # Below this size, switch to multi-column

        # Load saved zoom level or use default
        # Since thumbnails are generated at 512px, default to showing them at full size
        default_display_size = 512
        self.current_thumbnail_size = settings.value('image_list_thumbnail_size', default_display_size, type=int)
        self.current_thumbnail_size = max(self.min_thumbnail_size,
                                          min(self.max_thumbnail_size, self.current_thumbnail_size))

        # If the actual height of the image is greater than 3 times the width,
        # the image will be scaled down to fit.
        self.setIconSize(QSize(self.current_thumbnail_size, self.current_thumbnail_size * 3))

        # Set initial view mode based on size
        self._update_view_mode()

        invert_selection_action = self.addAction('Invert Selection')
        invert_selection_action.setShortcut('Ctrl+I')
        invert_selection_action.triggered.connect(self.invert_selection)
        copy_tags_action = self.addAction('Copy Tags')
        copy_tags_action.setShortcut('Ctrl+C')
        copy_tags_action.triggered.connect(
            self.copy_selected_image_tags)
        paste_tags_action = self.addAction('Paste Tags')
        paste_tags_action.setShortcut('Ctrl+V')
        paste_tags_action.triggered.connect(
            self.paste_tags)
        self.copy_file_names_action = self.addAction('Copy File Name')
        self.copy_file_names_action.setShortcut('Ctrl+Alt+C')
        self.copy_file_names_action.triggered.connect(
            self.copy_selected_image_file_names)
        self.copy_paths_action = self.addAction('Copy Path')
        self.copy_paths_action.setShortcut('Ctrl+Shift+C')
        self.copy_paths_action.triggered.connect(
            self.copy_selected_image_paths)
        self.move_images_action = self.addAction('Move Images to...')
        self.move_images_action.setShortcut('Ctrl+M')
        self.move_images_action.triggered.connect(
            self.move_selected_images)
        self.copy_images_action = self.addAction('Copy Images to...')
        self.copy_images_action.setShortcut('Ctrl+Shift+M')
        self.copy_images_action.triggered.connect(
            self.copy_selected_images)
        self.duplicate_images_action = self.addAction('Duplicate Images')
        self.duplicate_images_action.triggered.connect(
            self.duplicate_selected_images)
        self.delete_images_action = self.addAction('Delete Images')
        # Setting the shortcut to `Del` creates a conflict with tag deletion.
        self.delete_images_action.setShortcut('Ctrl+Del')
        self.delete_images_action.triggered.connect(
            self.delete_selected_images)
        self.open_image_action = self.addAction('Open Image in Default App')
        self.open_image_action.setShortcut('Ctrl+O')
        self.open_image_action.triggered.connect(self.open_image)
        self.open_folder_action = self.addAction('Open on Windows Explorer')
        self.open_folder_action.triggered.connect(self.open_folder)
        self.restore_backup_action = self.addAction('Restore from Backup')
        self.restore_backup_action.triggered.connect(self.restore_backup)

        self.context_menu = QMenu(self)
        self.context_menu.addAction('Select All Images', self.selectAll,
                                    shortcut='Ctrl+A')
        self.context_menu.addAction(invert_selection_action)
        self.context_menu.addSeparator()
        self.context_menu.addAction(copy_tags_action)
        self.context_menu.addAction(paste_tags_action)
        self.context_menu.addAction(self.copy_file_names_action)
        self.context_menu.addAction(self.copy_paths_action)
        self.context_menu.addSeparator()
        self.context_menu.addAction(self.move_images_action)
        self.context_menu.addAction(self.copy_images_action)
        self.context_menu.addAction(self.duplicate_images_action)
        self.context_menu.addAction(self.delete_images_action)
        self.context_menu.addAction(self.open_image_action)
        self.context_menu.addAction(self.open_folder_action)
        self.context_menu.addSeparator()
        self.context_menu.addAction(self.restore_backup_action)
        self.selectionModel().selectionChanged.connect(
            self.update_context_menu_actions)

    def contextMenuEvent(self, event):
        self.context_menu.exec_(event.globalPos())

    def wheelEvent(self, event):
        """Handle Ctrl+scroll wheel for zooming thumbnails."""
        if event.modifiers() == Qt.ControlModifier:
            # Get scroll direction
            delta = event.angleDelta().y()

            # Adjust thumbnail size
            zoom_step = 20  # Pixels per scroll step
            if delta > 0:
                # Scroll up = zoom in (larger thumbnails)
                new_size = min(self.current_thumbnail_size + zoom_step, self.max_thumbnail_size)
            else:
                # Scroll down = zoom out (smaller thumbnails)
                new_size = max(self.current_thumbnail_size - zoom_step, self.min_thumbnail_size)

            if new_size != self.current_thumbnail_size:
                self.current_thumbnail_size = new_size
                self.setIconSize(QSize(self.current_thumbnail_size, self.current_thumbnail_size * 3))

                # Update view mode (single column vs multi-column)
                self._update_view_mode()

                # Save to settings
                settings.setValue('image_list_thumbnail_size', self.current_thumbnail_size)

            event.accept()
        else:
            # Normal scroll behavior - but boost scroll speed in IconMode
            if self.viewMode() == QListView.ViewMode.IconMode:
                # In icon mode, manually scroll by a reasonable pixel amount
                delta = event.angleDelta().y()
                scroll_amount = delta * 2  # Multiply by 2 for faster scrolling
                current_value = self.verticalScrollBar().value()
                self.verticalScrollBar().setValue(current_value - scroll_amount)
                event.accept()
            else:
                # Default scroll behavior in ListMode
                super().wheelEvent(event)

    def on_filter_keystroke(self):
        """Called on every filter keystroke (before debounce) to detect rapid input."""
        import time
        current_time = time.time()
        timestamp = time.strftime("%H:%M:%S.") + f"{int(current_time * 1000) % 1000:03d}"

        if self._last_filter_keystroke_time > 0:
            time_since_last = (current_time - self._last_filter_keystroke_time) * 1000

            if time_since_last < 100:  # Less than 100ms = rapid typing/deletion
                self._rapid_input_detected = True
                # print(f"[{timestamp}]   🚀 RAPID: {time_since_last:.0f}ms since last key")
            else:
                self._rapid_input_detected = False
                # print(f"[{timestamp}]   📝 Normal: {time_since_last:.0f}ms since last key")
        else:
            # First keystroke - assume normal
            self._rapid_input_detected = False
            # print(f"[{timestamp}]   📝 First keystroke")

        self._last_filter_keystroke_time = current_time

    def _recalculate_masonry_if_needed(self, signal_name="unknown"):
        """Recalculate masonry layout if in masonry mode (debounced with adaptive delay)."""
        import time
        if not self.use_masonry:
            return

        current_time = time.time()
        timestamp = time.strftime("%H:%M:%S.") + f"{int(current_time * 1000) % 1000:03d}"

        # Store signal name for _do_recalculate_masonry to check
        self._last_masonry_signal = signal_name

        # Adaptive delay: check if rapid input was detected at keystroke level
        if self._rapid_input_detected:
            self._masonry_recalc_delay = self._masonry_recalc_max_delay
            # print(f"[MASONRY {timestamp}] SIGNAL: {signal_name}, RAPID INPUT FLAG SET - using max delay {self._masonry_recalc_delay}ms")
        elif signal_name == "layoutChanged" or signal_name == "user_click":
            # For layoutChanged (from page load or enrichment) or user clicks, use shorter delay for faster updates
            self._masonry_recalc_delay = 100
            # print(f"[MASONRY {timestamp}] SIGNAL: {signal_name}, using fast delay {self._masonry_recalc_delay}ms")
        else:
            # Reset to base delay if typing slowed down
            self._masonry_recalc_delay = self._masonry_recalc_min_delay
            # print(f"[MASONRY {timestamp}] SIGNAL: {signal_name}, normal input - delay={self._masonry_recalc_delay}ms")

        # Cancel any in-flight masonry calculation (futures can't be cancelled once started)
        # Just let it finish in background, newer calculation will override results
        if self._masonry_calc_future and not self._masonry_calc_future.done():
            pass
            # print(f"[{timestamp}]   -> Previous calculation still running (will be ignored)")

        # Restart debounce timer
        if self._masonry_recalc_timer.isActive():
            self._masonry_recalc_timer.stop()
            # print(f"[{timestamp}]   -> Restarting {self._masonry_recalc_delay}ms countdown")
        else:
            pass
            # print(f"[{timestamp}]   -> Starting {self._masonry_recalc_delay}ms countdown")
        self._masonry_recalc_timer.start(self._masonry_recalc_delay)

    def _do_recalculate_masonry(self):
        """Actually perform the masonry recalculation (called after debounce)."""
        import time
        timestamp = time.strftime("%H:%M:%S.") + f"{int(time.time() * 1000) % 1000:03d}"

        # Check if more keystrokes came in while timer was running (race condition)
        current_time = time.time()
        time_since_last_key = (current_time - self._last_filter_keystroke_time) * 1000
        if time_since_last_key < 50:  # Keystroke came in very recently (< 50ms ago)
            # print(f"[{timestamp}] ⚠️ SKIP: Keystroke {time_since_last_key:.0f}ms ago, user still typing")
            # Restart timer to wait for user to finish
            self._masonry_recalc_timer.start(self._masonry_recalc_delay)
            return

        # CRITICAL: Skip calculation entirely if already calculating
        # Even spawning threads can block the UI due to Qt/GIL overhead
        if self._masonry_calculating:
            # print(f"[{timestamp}] ⚠️ SKIP: Already calculating, will retry in 100ms")
            self._masonry_recalc_timer.start(100)
            return

        # CRITICAL: Skip ALL masonry calculations until user stops typing completely
        # Python's GIL means ANY computation in ANY thread blocks keyboard input
        # Even with time.sleep(0) every 10 items, 385-1147 items still blocks for 900ms
        # Solution: Keep showing old layout, only recalculate after typing stops for 3+ seconds
        # EXCEPTION: layoutChanged and user_click signals bypass this check (not related to typing)
        if hasattr(self, '_last_masonry_signal') and self._last_masonry_signal not in ['layoutChanged', 'user_click']:
            if time_since_last_key < 3000:
                # print(f"[{timestamp}] ⚠️ SKIP: Only {time_since_last_key:.0f}ms since last key, waiting for typing to fully stop")
                # Check again in 1 second
                self._masonry_recalc_timer.start(1000)
                return

        # Clear rapid input flag since user has stopped typing
        if self._rapid_input_detected:
            # print(f"[{timestamp}] ✓ User stopped typing for 3+ seconds, clearing rapid input flag")
            self._rapid_input_detected = False

        # Check if in pagination mode with large dataset - skip heavy recalculations
        source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else None
        if source_model and hasattr(source_model, '_paginated_mode') and source_model._paginated_mode:
            # In pagination mode, masonry calculation for 32K+ items is too heavy and crashes
            # TODO: Implement per-page masonry layouts instead of global layout
            print(f"[{timestamp}] ⚠️ SKIP: Pagination mode - masonry recalc disabled (would crash with 32K items)")
            print(f"[{timestamp}]        Need per-page masonry architecture for proper fix")
            return

        # print(f"[{timestamp}] ⚡ EXECUTE: Timer expired, starting masonry calculation")
        if self.use_masonry:
            self._calculate_masonry_layout()
            # Don't call scheduleDelayedItemsLayout() or update() here!
            # They block the UI thread and should only be called when calculation completes
        # print(f"[{timestamp}] ⚡ Masonry thread spawned (async)")

    def _calculate_masonry_layout(self):
        """Calculate masonry layout positions for all items (async with thread)."""
        if not self.use_masonry or not self.model():
            return

        # Skip if model is empty
        if self.model().rowCount() == 0:
            return

        # Don't start if we're already calculating
        if self._masonry_calculating:
            return

        self._masonry_calculating = True

        # Initialize parameters
        column_width = self.current_thumbnail_size
        spacing = 2
        viewport_width = self.viewport().width()

        if viewport_width <= 0:
            self._masonry_calculating = False
            return

        # Calculate number of columns
        num_columns = max(1, (viewport_width + spacing) // (column_width + spacing))

        # Get aspect ratios from cache (fast, no Qt model iteration)
        items_data = self.model().get_filtered_aspect_ratios()

        # Generate cache key
        cache_key = self._get_masonry_cache_key()

        # Submit to worker process (NO GIL BLOCKING!)
        self._masonry_calc_future = self._masonry_executor.submit(
            calculate_masonry_layout,
            items_data,
            column_width,
            spacing,
            num_columns,
            cache_key
        )

        # Poll for completion using QTimer
        self._check_masonry_completion()

    def _check_masonry_completion(self):
        """Check if multiprocessing calculation is complete (non-blocking poll)."""
        if self._masonry_calc_future and self._masonry_calc_future.done():
            try:
                result = self._masonry_calc_future.result()
                self._on_masonry_calculation_complete(result)
            except Exception as e:
                # print(f"Masonry calculation error: {e}")
                import traceback
                traceback.print_exc()
                self._masonry_calculating = False
        else:
            # Check again in 50ms
            QTimer.singleShot(50, self._check_masonry_completion)

    def _on_masonry_calculation_progress(self, current, total):
        """Update progress bar during calculation."""
        if hasattr(self, '_masonry_progress_bar'):
            self._masonry_progress_bar.setValue(current)

    def _on_masonry_calculation_complete(self, result_dict):
        """Called when multiprocessing calculation completes."""
        import time
        timestamp = time.strftime("%H:%M:%S.") + f"{int(time.time() * 1000) % 1000:03d}"

        self._masonry_calculating = False

        if result_dict is None:
            return

        # Check if another calculation is pending (user is still typing)
        if self._masonry_recalc_timer.isActive():
            # print(f"[{timestamp}] ⏭️  SKIP UI UPDATE: Another calculation pending")
            return

        # print(f"[{timestamp}] 🎨 APPLYING LAYOUT to UI...")

        # Store results for paintEvent to use
        self._masonry_items = result_dict['items']
        self._masonry_total_height = result_dict['total_height']

        # Update scroll area to accommodate total height
        total_height = result_dict['total_height']
        viewport_height = self.viewport().height()
        max_scroll = max(0, total_height - viewport_height)

        self.verticalScrollBar().setRange(0, max_scroll)
        self.verticalScrollBar().setPageStep(viewport_height)

        # Defer expensive UI update to next event loop iteration
        # This prevents blocking keyboard events that are already queued
        from PySide6.QtCore import QTimer
        def apply_and_signal():
            self._apply_layout_to_ui(timestamp)
            # Emit signal that layout is ready for scrolling
            self.layout_ready.emit()

        QTimer.singleShot(0, apply_and_signal)

        # Start thumbnail preloading after layout is ready
        if not self._preload_complete:
            self._idle_preload_timer.start(100)  # Start preloading after 100ms

    def _get_masonry_item_rect(self, index):
        """Get QRect for item at given index from masonry results."""
        if index < len(self._masonry_items):
            item = self._masonry_items[index]
            # Validate rect dimensions to prevent crashes with corrupted data
            width = item.get('width', 0)
            height = item.get('height', 0)
            if width > 0 and height > 0 and width < 100000 and height < 100000:
                return QRect(item['x'], item['y'], width, height)
        return QRect()

    def _get_masonry_visible_items(self, viewport_rect):
        """Get masonry items that intersect with viewport_rect."""
        visible = []
        for item in self._masonry_items:
            item_rect = QRect(item['x'], item['y'], item['width'], item['height'])
            if item_rect.intersects(viewport_rect):
                # Return dict with index and rect (matching old MasonryItem structure)
                visible.append({
                    'index': item['index'],
                    'rect': item_rect
                })
        return visible

    def _get_masonry_total_height(self):
        """Get total height from masonry results."""
        return self._masonry_total_height

    def _get_masonry_total_size(self):
        """Get total size from masonry results."""
        if not self._masonry_items:
            return QSize(0, 0)
        # Calculate width from columns
        column_width = self.current_thumbnail_size
        spacing = 2
        viewport_width = self.viewport().width()
        num_columns = max(1, (viewport_width + spacing) // (column_width + spacing))
        width = num_columns * (column_width + spacing) - spacing
        return QSize(width, self._masonry_total_height)

    def _apply_layout_to_ui(self, timestamp):
        """Apply masonry layout to UI (deferred to avoid blocking keyboard events)."""
        import time
        t1 = time.time()

        # Trigger UI update (EXPENSIVE - can block for 900ms)
        self.scheduleDelayedItemsLayout()
        self.viewport().update()

        # elapsed = (time.time() - t1) * 1000
        # print(f"[{timestamp}] ✓ UI UPDATE DONE in {elapsed:.0f}ms")

    def _get_masonry_cache_key(self) -> str:
        """Generate a unique cache key for current directory and settings."""
        # Get directory from model
        dir_path = "default"
        if self.model() and hasattr(self.model(), 'sourceModel'):
            source_model = self.model().sourceModel()
            # Handle both regular and paginated modes
            if hasattr(source_model, '_directory_path') and source_model._directory_path:
                dir_path = str(source_model._directory_path)
            elif hasattr(source_model, 'images') and len(source_model.images) > 0:
                # Fallback for regular mode
                dir_path = str(source_model.images[0].path.parent)

        # Round viewport width to nearest 100px to avoid cache misses from small resizes
        viewport_width = (self.viewport().width() // 100) * 100

        # Include sort order in cache key - different orders need different layouts!
        sort_order = settings.value('image_list_sort_by', 'Name', type=str)

        # Include filter state in cache key - different filters show different images!
        filter_key = "no_filter"
        try:
            if self.model() and hasattr(self.model(), 'filter') and self.model().filter is not None:
                # Convert filter to a stable string representation (use hash for complex filters)
                filter_str = str(self.model().filter)
                if len(filter_str) > 100:  # If filter string is too long, hash it
                    import hashlib
                    filter_key = hashlib.md5(filter_str.encode()).hexdigest()[:16]
                else:
                    filter_key = filter_str.replace('/', '_').replace('\\', '_')  # Sanitize for filename
        except Exception:
            # If anything goes wrong getting filter, use timestamp to avoid cache collision
            import time
            filter_key = f"filter_{int(time.time())}"

        return f"{dir_path}_{self.current_thumbnail_size}_{viewport_width}_{sort_order}_{filter_key}"

    def _preload_nearby_thumbnails(self):
        """Preload thumbnails for items near viewport for smoother scrolling."""
        if not self.use_masonry or not self._masonry_items or not self.model():
            return

        # Get viewport bounds with large buffer for preloading
        scroll_offset = self.verticalScrollBar().value()
        viewport_height = self.viewport().height()

        # Preload items within 2 screens above and below
        preload_buffer = viewport_height * 2
        preload_rect = QRect(0, scroll_offset - preload_buffer,
                            self.viewport().width(), viewport_height + (preload_buffer * 2))

        # Get items in preload range
        items_to_preload = self._get_masonry_visible_items(preload_rect)

        # Trigger thumbnail loading by accessing decoration data
        for item in items_to_preload:
            index = self.model().index(item['index'], 0)
            if index.isValid():
                # This triggers thumbnail generation if not cached
                _ = index.data(Qt.ItemDataRole.DecorationRole)
                # Track this thumbnail as loaded
                if item['index'] not in self._thumbnails_loaded:
                    self._thumbnails_loaded.add(item['index'])
                    # Update progress if progress bar is visible
                    if self._thumbnail_progress_bar and self._thumbnail_progress_bar.isVisible():
                        self._update_thumbnail_progress(len(self._thumbnails_loaded),
                                                       self.model().rowCount())

    def _preload_all_thumbnails(self):
        """Aggressively preload ALL thumbnails when idle for buttery smooth scrolling."""
        if not self.use_masonry or not self.model() or self._preload_complete:
            return

        total_items = self.model().rowCount()
        if total_items == 0:
            return

        # Show progress bar (either first run or resuming after scroll)
        if not self._thumbnail_progress_bar or not self._thumbnail_progress_bar.isVisible():
            self._show_thumbnail_progress(total_items)

        # Preload in smaller batches to avoid blocking UI
        # Smaller batch = more responsive UI, especially for videos
        batch_size = 3  # Reduced from 10 - videos can take time to extract frames
        start_index = self._preload_index
        end_index = min(start_index + batch_size, total_items)

        # Preload batch with UI updates between each item
        for i in range(start_index, end_index):
            index = self.model().index(i, 0)
            if index.isValid():
                # Trigger thumbnail generation
                _ = index.data(Qt.ItemDataRole.DecorationRole)

                # Track cache hit/miss (only count each thumbnail once)
                if i not in self._thumbnail_cache_hits and i not in self._thumbnail_cache_misses:
                    source_index = self.model().mapToSource(index)
                    # Get image via data() instead of direct array access (pagination-safe)
                    image = self.model().sourceModel().data(
                        self.model().sourceModel().index(source_index.row(), 0),
                        Qt.ItemDataRole.UserRole
                    )
                    if image and hasattr(image, '_last_thumbnail_was_cached'):
                        if image._last_thumbnail_was_cached:
                            self._thumbnail_cache_hits.add(i)
                        else:
                            self._thumbnail_cache_misses.add(i)

                # Track this thumbnail as loaded (even if already loaded via scroll)
                was_new = i not in self._thumbnails_loaded
                self._thumbnails_loaded.add(i)
                # Process events after each thumbnail to keep UI responsive
                QApplication.processEvents()

        # Update progress to show actual loaded count (not sequential index)
        self._preload_index = end_index
        self._update_thumbnail_progress(len(self._thumbnails_loaded), total_items)

        # Continue preloading if more items remain
        if self._preload_index < total_items:
            # Schedule next batch with minimal delay for responsiveness
            QTimer.singleShot(10, self._preload_all_thumbnails)  # Reduced from 50ms to 10ms
        else:
            # Silently complete
            self._preload_index = 0  # Reset for next time
            self._preload_complete = True  # Mark as complete
            self._hide_thumbnail_progress()

    def _show_thumbnail_progress(self, total_items):
        """Show progress bar for thumbnail loading."""
        if not self._thumbnail_progress_bar:
            self._thumbnail_progress_bar = QProgressBar(self.viewport())
            self._thumbnail_progress_bar.setStyleSheet("""
                QProgressBar {
                    border: 2px solid #555;
                    border-radius: 5px;
                    background-color: rgba(0, 0, 0, 180);
                    text-align: center;
                    color: white;
                    font-size: 12px;
                    min-height: 20px;
                }
                QProgressBar::chunk {
                    background-color: #4CAF50;
                    border-radius: 3px;
                }
            """)

        self._thumbnail_progress_bar.setMaximum(total_items)
        self._thumbnail_progress_bar.setValue(0)
        # Initial message - will update based on cache hit rate
        self._thumbnail_progress_bar.setFormat("Loading thumbnails: %v/%m")
        self._update_progress_bar_position()
        self._thumbnail_progress_bar.show()
        self._thumbnail_progress_bar.raise_()

    def _update_progress_bar_position(self):
        """Update progress bar position to follow viewport (stick to bottom)."""
        if self._thumbnail_progress_bar and self._thumbnail_progress_bar.isVisible():
            # Position at bottom of viewport (follows scroll)
            bar_width = min(300, self.viewport().width() - 20)
            self._thumbnail_progress_bar.setGeometry(
                (self.viewport().width() - bar_width) // 2,
                self.viewport().height() - 40,
                bar_width,
                25
            )
            self._thumbnail_progress_bar.raise_()  # Keep on top

    def _update_thumbnail_progress(self, current, total):
        """Update progress bar value and message based on cache performance."""
        if self._thumbnail_progress_bar:
            self._thumbnail_progress_bar.setValue(current)

            # Update message based on cache hit rate
            total_processed = len(self._thumbnail_cache_hits) + len(self._thumbnail_cache_misses)
            if total_processed > 10:  # Wait for at least 10 samples
                cache_rate = (len(self._thumbnail_cache_hits) / total_processed) * 100

                # Calculate how many are loading vs generating
                cached_count = len(self._thumbnail_cache_hits)
                generating_count = len(self._thumbnail_cache_misses)

                if cache_rate > 95:
                    # Almost all cached - fast loading
                    self._thumbnail_progress_bar.setFormat("Updating dimensions: %v/%m")
                elif cache_rate < 20:
                    # Almost all generating - slow
                    self._thumbnail_progress_bar.setFormat("Generating: %v/%m")
                else:
                    # Mixed - show both counts with color coding
                    self._thumbnail_progress_bar.setFormat(
                        f"Updating dimensions: {cached_count} | Generating: {generating_count} (%v/%m)"
                    )
            else:
                # Not enough data yet, use neutral message
                self._thumbnail_progress_bar.setFormat("Updating dimensions: %v/%m")

    def _hide_thumbnail_progress(self):
        """Hide progress bar when complete."""
        if self._thumbnail_progress_bar:
            # Fade out effect
            QTimer.singleShot(500, self._thumbnail_progress_bar.hide)  # Hide after 500ms

    def _update_view_mode(self):
        """Switch between single column (ListMode) and multi-column (IconMode) based on thumbnail size."""
        if self.current_thumbnail_size >= self.column_switch_threshold:
            # Large thumbnails: single column list view
            self.use_masonry = False
            self.setViewMode(QListView.ViewMode.ListMode)
            self.setFlow(QListView.Flow.TopToBottom)
            self.setResizeMode(QListView.ResizeMode.Adjust)
            self.setWrapping(False)
            self.setSpacing(0)
            self.setGridSize(QSize(-1, -1))  # Reset grid size to default
        else:
            # Small thumbnails: masonry grid view (Pinterest-style)
            self.use_masonry = True
            self.setViewMode(QListView.ViewMode.IconMode)
            self.setFlow(QListView.Flow.LeftToRight)
            self.setResizeMode(QListView.ResizeMode.Fixed)
            self.setWrapping(True)
            self.setSpacing(2)
            self.setUniformItemSizes(False)  # Allow varying sizes
            # Disable default grid - we'll handle positioning with masonry
            self.setGridSize(QSize(-1, -1))
            # Calculate masonry layout
            self._calculate_masonry_layout()
            # Force item delegate to recalculate sizes and update viewport
            self.scheduleDelayedItemsLayout()
            self.viewport().update()

    def startDrag(self, supportedActions: Qt.DropAction):
        indices = self.selectedIndexes()
        if not indices:
            return

        # Use mimeData from the model.
        mime_data = self.model().mimeData(indices)
        if not mime_data:
            return

        # The pixmap is just the icon of the first selected item.
        # This avoids including the text.
        icon = indices[0].data(Qt.ItemDataRole.DecorationRole)
        pixmap = icon.pixmap(self.iconSize())

        # Create a new pixmap with transparency for the drag image.
        drag_pixmap = QPixmap(pixmap.size())
        drag_pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(drag_pixmap)
        painter.setOpacity(0.7)
        painter.drawPixmap(0, 0, pixmap)
        painter.end()

        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag.setPixmap(drag_pixmap)
        drag.setHotSpot(drag_pixmap.rect().center())
        drag.exec(supportedActions)

    def resizeEvent(self, event):
        """Recalculate masonry layout on resize."""
        super().resizeEvent(event)
        if self.use_masonry:
            # Recalculate layout with new width
            self._calculate_masonry_layout()
            self.viewport().update()

    def viewportSizeHint(self):
        """Return the size hint for masonry layout."""
        if self.use_masonry and self._masonry_items:
            size = self._get_masonry_total_size()
            return size
        return super().viewportSizeHint()

    def visualRect(self, index):
        """Return the visual rectangle for an index, using masonry positions."""
        if self.use_masonry and self._masonry_items and index.isValid():
            # Get masonry position (absolute coordinates)
            rect = self._get_masonry_item_rect(index.row())
            if rect.isValid():
                # Create new rect adjusted for scroll position (viewport coordinates)
                scroll_offset = self.verticalScrollBar().value()
                return QRect(rect.x(), rect.y() - scroll_offset, rect.width(), rect.height())
            return QRect()
        else:
            # Use default positioning
            return super().visualRect(index)

    def indexAt(self, point):
        """Return the index at the given point, using masonry positions."""
        if self.use_masonry and self._masonry_items:
            # Adjust point for scroll offset
            scroll_offset = self.verticalScrollBar().value()
            adjusted_point = QPoint(point.x(), point.y() + scroll_offset)

            # Debug: find ALL rects that contain this point
            matching_rows = []
            for row in range(self.model().rowCount() if self.model() else 0):
                rect = self._get_masonry_item_rect(row)
                if rect.contains(adjusted_point):
                    matching_rows.append((row, rect))

            if matching_rows:
                # Show matching info (limit rect output for readability)
                # match_info = [(r, f"({rect.x()},{rect.y()} {rect.width()}x{rect.height()})") for r, rect in matching_rows]
                # print(f"[DEBUG] indexAt: click at ({adjusted_point.x()},{adjusted_point.y()}) matches {len(matching_rows)} items: {match_info}")
                # Return the last one (topmost painted item)
                last_row, last_rect = matching_rows[-1]
                found_index = self.model().index(last_row, 0)
                # print(f"[DEBUG] indexAt returning row={last_row}")
                return found_index
            else:
                # print(f"[DEBUG] indexAt found no match at {adjusted_point}")
                return QModelIndex()
        else:
            return super().indexAt(point)

    def mousePressEvent(self, event):
        """Override mouse press to fix selection in masonry mode."""
        # Pause enrichment during interaction to prevent crashes
        source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else None
        if source_model and hasattr(source_model, '_enrichment_timer') and source_model._enrichment_timer:
            source_model._enrichment_timer.stop()
            # Will resume after 500ms idle (see mouseReleaseEvent)

        if self.use_masonry and self._masonry_items:
            # Get the index at click position
            index = self.indexAt(event.pos())

            if index.isValid():
                # Check modifiers
                modifiers = event.modifiers()

                if modifiers & Qt.ControlModifier:
                    # Ctrl+Click: toggle selection WITHOUT clearing others
                    was_selected = self.selectionModel().isSelected(index)

                    # First, set as current index
                    self.selectionModel().setCurrentIndex(index, QItemSelectionModel.NoUpdate)

                    # Then toggle its selection state
                    if was_selected:
                        # print(f"[DEBUG] Ctrl+Click: deselecting row={index.row()}")
                        self.selectionModel().select(index, QItemSelectionModel.Deselect)
                    else:
                        # print(f"[DEBUG] Ctrl+Click: selecting row={index.row()}")
                        self.selectionModel().select(index, QItemSelectionModel.Select)

                    # Debug: show all selected indices
                    # all_selected = [idx.row() for idx in self.selectionModel().selectedIndexes()]
                    # print(f"[DEBUG] After Ctrl+Click, all selected rows: {all_selected}")

                    # Force repaint to show selection changes
                    self.viewport().update()
                elif modifiers & Qt.ShiftModifier:
                    # Shift+Click: range selection
                    current = self.currentIndex()
                    if current.isValid():
                        # Select all items between current and clicked index
                        start_row = min(current.row(), index.row())
                        end_row = max(current.row(), index.row())

                        # print(f"[DEBUG] Shift+Click: selecting range from row {start_row} to {end_row}")

                        # Build selection range
                        selection = QItemSelection()
                        for row in range(start_row, end_row + 1):
                            item_index = self.model().index(row, 0)
                            selection.select(item_index, item_index)

                        # Apply selection (add to existing if Ctrl also held)
                        self.selectionModel().select(selection, QItemSelectionModel.Select)
                        self.selectionModel().setCurrentIndex(index, QItemSelectionModel.NoUpdate)

                        # Debug: show all selected indices
                        # all_selected = [idx.row() for idx in self.selectionModel().selectedIndexes()]
                        # print(f"[DEBUG] After Shift+Click, all selected rows: {all_selected}")
                    else:
                        # No current index, just select this one
                        self.selectionModel().select(index, QItemSelectionModel.Select)
                        self.selectionModel().setCurrentIndex(index, QItemSelectionModel.NoUpdate)

                    # Force repaint
                    self.viewport().update()
                else:
                    # Normal click: clear and select only this item
                    self.selectionModel().clearSelection()
                    self.selectionModel().select(index, QItemSelectionModel.Select)
                    self.setCurrentIndex(index)

                # Accept the event to prevent further processing
                event.accept()
            else:
                # Click on empty space: clear selection
                self.selectionModel().clearSelection()
                event.accept()
        else:
            # Use default behavior in list mode
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Prevent Qt's rubber-band selection in masonry mode."""
        if self.use_masonry and self._masonry_items:
            # Don't call super() - it triggers rubber-band selection
            # Just accept the event to prevent default behavior
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event):
        """Handle double-click events."""
        # Alt+double-click opens image in default app
        if event.modifiers() & Qt.AltModifier:
            index = self.indexAt(event.pos())
            if index.isValid():
                # Get the image at this index
                image = index.data(Qt.ItemDataRole.UserRole)
                if image:
                    QDesktopServices.openUrl(QUrl.fromLocalFile(str(image.path)))
                event.accept()
                return

        # Default behavior for other double-clicks
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event):
        """Override mouse release to prevent Qt from changing selection."""
        # Resume enrichment after 500ms idle
        source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else None
        if source_model and hasattr(source_model, '_enrichment_timer') and source_model._enrichment_timer:
            source_model._enrichment_timer.start(500)

        if self.use_masonry and self._masonry_items:
            # Just accept the event, don't let Qt handle it
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def scrollContentsBy(self, dx, dy):
        """Handle scrolling and update viewport."""
        super().scrollContentsBy(dx, dy)
        if self.use_masonry:
            # Force viewport update when scrolling in masonry mode
            self.viewport().update()

            # Preload thumbnails for smoother scrolling (only nearby items)
            self._preload_nearby_thumbnails()

            # Update progress bar position to follow scroll
            self._update_progress_bar_position()

            # Trigger page loading for paginated models
            self._check_and_load_pages()

            # Show page indicator in pagination mode
            self._show_page_indicator()

            # Restart idle timer - will start/resume aggressive preload when user stops scrolling
            # Only if not already complete
            if not self._preload_complete:
                self._idle_preload_timer.stop()
                self._idle_preload_timer.start(500)  # 500ms after scrolling stops

    def _check_and_load_pages(self):
        """Check if we need to load more pages based on scroll position."""
        # Check if model supports pagination
        source_model = self.model().sourceModel() if hasattr(self.model(), 'sourceModel') else self.model()
        if not hasattr(source_model, 'ensure_pages_for_range'):
            return  # Not a paginated model

        if not self._masonry_items:
            return

        # Get current scroll position and viewport
        scroll_offset = self.verticalScrollBar().value()
        viewport_height = self.viewport().height()

        # Calculate buffer (2 screens ahead/behind)
        buffer = viewport_height * 2
        start_y = max(0, scroll_offset - buffer)
        end_y = scroll_offset + viewport_height + buffer

        # Find item indices in this range
        visible_items = self._get_masonry_visible_items(
            QRect(0, start_y, self.viewport().width(), end_y - start_y)
        )

        if visible_items:
            start_idx = min(item['index'] for item in visible_items)
            end_idx = max(item['index'] for item in visible_items)

            # Request pages for this range
            source_model.ensure_pages_for_range(start_idx, end_idx)

    def paintEvent(self, event):
        """Override paint to handle masonry layout rendering."""
        if self.use_masonry and self._masonry_items and self.model():
            try:
                import time
                paint_start = time.time()

                # Paint background
                painter = QPainter(self.viewport())
                painter.fillRect(self.viewport().rect(), self.palette().base())

                # Get visible viewport rect in absolute coordinates
                scroll_offset = self.verticalScrollBar().value()
                viewport_height = self.viewport().height()
                viewport_rect = QRect(0, scroll_offset, self.viewport().width(), viewport_height)

                # Add buffer zone for smooth scrolling (render items slightly outside viewport)
                buffer = 200  # pixels
                expanded_viewport = viewport_rect.adjusted(0, -buffer, 0, buffer)

                # Use masonry layout to get only visible items (OPTIMIZATION!)
                visible_items = self._get_masonry_visible_items(expanded_viewport)

                # Auto-correct scroll bounds if needed
                max_allowed = self._get_masonry_total_height() - viewport_height
                if scroll_offset > max_allowed and max_allowed > 0:
                    self.verticalScrollBar().setMaximum(max_allowed)
                    self.verticalScrollBar().setValue(max_allowed)

                items_painted = 0
                # Paint only visible items
                for item in visible_items:
                    index = self.model().index(item['index'], 0)
                    if not index.isValid():
                        continue

                    # Adjust rect to viewport coordinates
                    visual_rect = QRect(
                        item['rect'].x(),
                        item['rect'].y() - scroll_offset,
                        item['rect'].width(),
                        item['rect'].height()
                    )

                    # Skip if completely outside viewport (after buffer)
                    if visual_rect.bottom() < -buffer or visual_rect.top() > viewport_height + buffer:
                        continue

                    # Create option for delegate using QStyleOptionViewItem
                    option = QStyleOptionViewItem()
                    option.rect = visual_rect
                    option.decorationSize = QSize(item['rect'].width(), item['rect'].height())
                    option.decorationAlignment = Qt.AlignCenter
                    option.palette = self.palette()  # Set palette for stamp drawing

                    # Set state flags
                    is_selected = self.selectionModel() and self.selectionModel().isSelected(index)
                    is_current = self.currentIndex() == index

                    # Debug: log selection state for visible items
                    # if is_selected or is_current:
                    #     print(f"[DEBUG] Painting row={item.index}, is_selected={is_selected}, is_current={is_current}")

                    if is_selected:
                        option.state |= QStyle.StateFlag.State_Selected
                    if is_current:
                        option.state |= QStyle.StateFlag.State_HasFocus

                    # Paint using delegate
                    self.itemDelegate().paint(painter, option, index)

                    # Draw selection border on top in masonry mode (delegate doesn't show it clearly in IconMode)
                    if is_selected or is_current:
                        painter.save()
                        if is_current:
                            # Current item: thicker blue border
                            pen = QPen(QColor(0, 120, 215), 4)  # Windows blue
                        else:
                            # Just selected: thinner blue border
                            pen = QPen(QColor(0, 120, 215), 2)
                        painter.setPen(pen)
                        painter.setBrush(Qt.BrushStyle.NoBrush)
                        painter.drawRect(visual_rect.adjusted(2, 2, -2, -2))
                        painter.restore()
                        # Debug: show rect for selected items
                        # print(f"[DEBUG] Painted selected item row={item.index}, visual_rect={visual_rect}, original_rect={item.rect}")

                    items_painted += 1

                painter.end()
            except Exception as e:
                # Catch any crashes during masonry painting to prevent segfaults
                print(f"[PAINT ERROR] Masonry paint crashed: {e}")
                import traceback
                traceback.print_exc()
                # Fall back to default painting
                super().paintEvent(event)
        else:
            # Use default painting
            super().paintEvent(event)

    @Slot(Grid)
    def show_crop_size(self, grid):
        index = self.currentIndex()
        if index.isValid():
            image = index.data(Qt.ItemDataRole.UserRole)
            if grid is None:
                self.delegate.remove_label(index)
            else:
                crop_delta = grid.screen.size() - grid.visible.size()
                crop_fit = max(crop_delta.width(), crop_delta.height())
                crop_fit_text = f' (-{crop_fit})' if crop_fit > 0 else ''
                label = f'image: {image.dimensions[0]}x{image.dimensions[1]}\n'\
                        f'crop: {grid.screen.width()}x{grid.screen.height()}{crop_fit_text}\n'\
                        f'target: {grid.target.width()}x{grid.target.height()}'
                if grid.aspect_ratio is not None:
                    label += '✅' if grid.aspect_ratio[2] else ''
                    label += f'  {grid.aspect_ratio[0]}:{grid.aspect_ratio[1]}'
                self.delegate.update_label(index, label)

    def _disable_updates(self):
        """Disable widget updates during model reset."""
        self.setUpdatesEnabled(False)
        self.viewport().setUpdatesEnabled(False)

    def _enable_updates(self):
        """Re-enable widget updates after model reset."""
        # Defer re-enabling updates to next event loop iteration
        # This ensures the view's internal state is fully updated before repainting
        QTimer.singleShot(0, self._do_enable_updates)

    def _do_enable_updates(self):
        """Actually re-enable updates (called after event loop processes)."""
        self.setUpdatesEnabled(True)
        self.viewport().setUpdatesEnabled(True)

        # Reset preload state and start thumbnail loading immediately
        self._preload_index = 0
        self._preload_complete = False
        self._thumbnails_loaded.clear()
        self._thumbnail_cache_hits.clear()
        self._thumbnail_cache_misses.clear()
        # Start preloading immediately so users see progress bar right away
        QTimer.singleShot(100, self._preload_all_thumbnails)

    @Slot()
    def invert_selection(self):
        selected_proxy_rows = {index.row() for index in self.selectedIndexes()}
        all_proxy_rows = set(range(self.proxy_image_list_model.rowCount()))
        unselected_proxy_rows = all_proxy_rows - selected_proxy_rows
        first_unselected_proxy_row = min(unselected_proxy_rows, default=0)
        item_selection = QItemSelection()
        for row in unselected_proxy_rows:
            item_selection.append(
                QItemSelectionRange(self.proxy_image_list_model.index(row, 0)))
        self.setCurrentIndex(self.model().index(first_unselected_proxy_row, 0))
        self.selectionModel().select(
            item_selection, QItemSelectionModel.SelectionFlag.ClearAndSelect)

    def get_selected_images(self) -> list[Image]:
        selected_image_proxy_indices = self.selectedIndexes()
        selected_images = [index.data(Qt.ItemDataRole.UserRole)
                           for index in selected_image_proxy_indices]
        return selected_images

    @Slot()
    def copy_selected_image_tags(self):
        selected_images = self.get_selected_images()
        selected_image_captions = [self.tag_separator.join(image.tags)
                                   for image in selected_images]
        QApplication.clipboard().setText('\n'.join(selected_image_captions))

    def get_selected_image_indices(self) -> list[QModelIndex]:
        selected_image_proxy_indices = self.selectedIndexes()
        # print(f"[DEBUG] get_selected_image_indices: proxy indices = {[idx.row() for idx in selected_image_proxy_indices]}")
        selected_image_indices = [
            self.proxy_image_list_model.mapToSource(proxy_index)
            for proxy_index in selected_image_proxy_indices]
        # print(f"[DEBUG] get_selected_image_indices: source indices = {[idx.row() for idx in selected_image_indices]}")
        return selected_image_indices

    @Slot()
    def paste_tags(self):
        selected_image_count = len(self.selectedIndexes())
        if selected_image_count > 1:
            reply = get_confirmation_dialog_reply(
                title='Paste Tags',
                question=f'Paste tags to {selected_image_count} selected '
                         f'images?')
            if reply != QMessageBox.StandardButton.Yes:
                return
        tags = QApplication.clipboard().text().split(self.tag_separator)
        selected_image_indices = self.get_selected_image_indices()
        self.tags_paste_requested.emit(tags, selected_image_indices)

    @Slot()
    def copy_selected_image_file_names(self):
        selected_images = self.get_selected_images()
        selected_image_file_names = [image.path.name
                                     for image in selected_images]
        QApplication.clipboard().setText('\n'.join(selected_image_file_names))

    @Slot()
    def copy_selected_image_paths(self):
        selected_images = self.get_selected_images()
        selected_image_paths = [str(image.path) for image in selected_images]
        QApplication.clipboard().setText('\n'.join(selected_image_paths))

    @Slot()
    def move_selected_images(self):
        selected_images = self.get_selected_images()
        selected_image_count = len(selected_images)
        caption = (f'Select directory to move {selected_image_count} selected '
                   f'{pluralize("Image", selected_image_count)} and '
                   f'{pluralize("caption", selected_image_count)} to')
        move_directory_path = QFileDialog.getExistingDirectory(
            parent=self, caption=caption,
            dir=settings.value('directory_path', type=str))
        if not move_directory_path:
            return
        move_directory_path = Path(move_directory_path)

        # Check if any selected videos are currently loaded and unload them
        # Hierarchy: ImageListView -> container -> ImageList (QDockWidget) -> MainWindow
        main_window = self.parent().parent().parent()  # Get main window reference
        video_was_cleaned = False
        if hasattr(main_window, 'image_viewer') and hasattr(main_window.image_viewer, 'video_player'):
            video_player = main_window.image_viewer.video_player
            if video_player.video_path:
                currently_loaded_path = Path(video_player.video_path)
                # Check if we're moving the currently loaded video
                for image in selected_images:
                    if image.path == currently_loaded_path:
                        # Unload the video first (stop playback and release resources)
                        video_player.cleanup()
                        video_was_cleaned = True
                        break

        # Clear thumbnails for all selected videos to release graphics resources
        for image in selected_images:
            if hasattr(image, 'is_video') and image.is_video and image.thumbnail:
                image.thumbnail = None

        # If we cleaned up a video, give Qt/Windows a moment to release file handles
        if video_was_cleaned:
            from PySide6.QtCore import QThread
            QThread.msleep(100)  # 100ms delay
            QApplication.processEvents()  # Process pending events to ensure cleanup completes

        # Force garbage collection to release any remaining file handles
        import gc
        gc.collect()

        for image in selected_images:
            try:
                image.path.replace(move_directory_path / image.path.name)
                caption_file_path = image.path.with_suffix('.txt')
                if caption_file_path.exists():
                    caption_file_path.replace(
                        move_directory_path / caption_file_path.name)
                # Also move JSON metadata if it exists
                json_file_path = image.path.with_suffix('.json')
                if json_file_path.exists():
                    json_file_path.replace(
                        move_directory_path / json_file_path.name)
            except OSError as e:
                QMessageBox.critical(self, 'Error',
                                     f'Failed to move {image.path} to '
                                     f'{move_directory_path}.\n{str(e)}')
        self.directory_reload_requested.emit()

    @Slot()
    def copy_selected_images(self):
        selected_images = self.get_selected_images()
        selected_image_count = len(selected_images)
        caption = (f'Select directory to copy {selected_image_count} selected '
                   f'{pluralize("Image", selected_image_count)} and '
                   f'{pluralize("caption", selected_image_count)} to')
        copy_directory_path = QFileDialog.getExistingDirectory(
            parent=self, caption=caption,
            dir=settings.value('directory_path', type=str))
        if not copy_directory_path:
            return
        copy_directory_path = Path(copy_directory_path)
        for image in selected_images:
            try:
                shutil.copy(image.path, copy_directory_path)
                caption_file_path = image.path.with_suffix('.txt')
                if caption_file_path.exists():
                    shutil.copy(caption_file_path, copy_directory_path)
            except OSError:
                QMessageBox.critical(self, 'Error',
                                     f'Failed to copy {image.path} to '
                                     f'{copy_directory_path}.')

    @Slot()
    def duplicate_selected_images(self):
        selected_images = self.get_selected_images()
        selected_image_count = len(selected_images)
        if selected_image_count == 0:
            return

        # Get the source model to add duplicated images
        source_model = self.proxy_image_list_model.sourceModel()

        duplicated_count = 0
        for image in selected_images:
            try:
                # Generate unique name for duplicate
                original_path = image.path
                directory = original_path.parent
                stem = original_path.stem
                suffix = original_path.suffix

                # Find a unique name by appending "_copy" or "_copy2", etc.
                counter = 1
                new_stem = f"{stem}_copy"
                new_path = directory / f"{new_stem}{suffix}"
                while new_path.exists():
                    counter += 1
                    new_stem = f"{stem}_copy{counter}"
                    new_path = directory / f"{new_stem}{suffix}"

                # Copy the media file
                shutil.copy2(original_path, new_path)

                # Copy caption file if it exists
                caption_file_path = original_path.with_suffix('.txt')
                if caption_file_path.exists():
                    new_caption_path = new_path.with_suffix('.txt')
                    shutil.copy2(caption_file_path, new_caption_path)

                # Copy JSON metadata file if it exists
                json_file_path = original_path.with_suffix('.json')
                if json_file_path.exists():
                    new_json_path = new_path.with_suffix('.json')
                    shutil.copy2(json_file_path, new_json_path)

                # Add the new image to the model
                source_model.add_image(new_path)

                duplicated_count += 1

            except OSError as e:
                QMessageBox.critical(self, 'Error',
                                     f'Failed to duplicate {image.path}: {str(e)}')

        if duplicated_count > 0:
            # Emit signal to reload directory (this will refresh the list)
            self.directory_reload_requested.emit()

    @Slot()
    def delete_selected_images(self):
        selected_images = self.get_selected_images()
        selected_image_count = len(selected_images)
        title = f'Delete {pluralize("Image", selected_image_count)}'
        question = (f'Delete {selected_image_count} selected '
                    f'{pluralize("image", selected_image_count)} and '
                    f'{"its" if selected_image_count == 1 else "their"} '
                    f'{pluralize("caption", selected_image_count)}?')
        reply = get_confirmation_dialog_reply(title, question)
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Check if any selected videos are currently loaded and unload them
        # Hierarchy: ImageListView -> container -> ImageList (QDockWidget) -> MainWindow
        main_window = self.parent().parent().parent()  # Get main window reference
        video_was_cleaned = False
        if hasattr(main_window, 'image_viewer') and hasattr(main_window.image_viewer, 'video_player'):
            video_player = main_window.image_viewer.video_player
            if video_player.video_path:
                currently_loaded_path = Path(video_player.video_path)
                # Check if we're deleting the currently loaded video
                for image in selected_images:
                    if image.path == currently_loaded_path:
                        # Unload the video first (stop playback and release resources)
                        video_player.cleanup()
                        video_was_cleaned = True
                        break

        # Clear thumbnails for all selected videos to release graphics resources
        for image in selected_images:
            if hasattr(image, 'is_video') and image.is_video and image.thumbnail:
                image.thumbnail = None

        # If we cleaned up a video, give Qt/Windows a moment to release file handles
        if video_was_cleaned:
            from PySide6.QtCore import QThread
            QThread.msleep(100)  # 100ms delay
            QApplication.processEvents()  # Process pending events to ensure cleanup completes

        # Force garbage collection to release any remaining file handles
        import gc
        gc.collect()

        from PySide6.QtCore import QThread
        import time

        for image in selected_images:
            success = False

            # For videos, try multiple times with delays (Windows file handle release is async)
            max_retries = 3 if (hasattr(image, 'is_video') and image.is_video) else 1

            for attempt in range(max_retries):
                if attempt > 0:
                    # Wait and retry
                    QThread.msleep(150)  # Wait 150ms between retries
                    QApplication.processEvents()
                    gc.collect()

                # Try Qt's moveToTrash first
                image_file = QFile(str(image.path))
                if image_file.moveToTrash():
                    success = True
                    break
                elif attempt == max_retries - 1:
                    # Last attempt - ask user for permanent deletion
                    reply = QMessageBox.question(
                        self, 'Trash Failed',
                        f'Could not move {image.path.name} to trash.\nDelete permanently?',
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No  # Default to No for safety
                    )
                    if reply == QMessageBox.Yes:
                        if image_file.remove():
                            success = True

            if not success:
                QMessageBox.critical(self, 'Error', f'Failed to delete {image.path}.')
                continue

            # Also try to delete caption file
            caption_file_path = image.path.with_suffix('.txt')
            if caption_file_path.exists():
                caption_file = QFile(caption_file_path)
                if not caption_file.moveToTrash():
                    # For caption files, try permanent deletion without asking again
                    caption_file.remove()  # Silent operation for captions
        self.directory_reload_requested.emit()

    @Slot()
    def open_image(self):
        selected_images = self.get_selected_images()
        image_path = selected_images[0].path
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(image_path)))

    @Slot()
    def open_folder(self):
        selected_images = self.get_selected_images()
        if selected_images:
            folder_path = selected_images[0].path.parent
            file_path = selected_images[0].path
            # Use explorer.exe with /select flag to highlight the file
            QProcess.startDetached('explorer.exe', ['/select,', str(file_path)])

    @Slot()
    def restore_backup(self):
        """Restore selected images/videos from their .backup files."""
        from PySide6.QtWidgets import QMessageBox
        import shutil

        selected_images = self.get_selected_images()
        if not selected_images:
            return

        # Find which images have backups
        images_with_backups = []
        for img in selected_images:
            backup_path = Path(str(img.path) + '.backup')
            if backup_path.exists():
                images_with_backups.append((img, backup_path))

        if not images_with_backups:
            QMessageBox.information(None, "No Backups", "No backup files found for selected images.")
            return

        # Confirm restoration
        count = len(images_with_backups)
        reply = QMessageBox.question(
            None,
            "Restore from Backup",
            f"Restore {count} {'file' if count == 1 else 'files'} from backup?\n\n"
            f"This will replace the current {'file' if count == 1 else 'files'} with the backup version.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Restore files
        restored = 0
        for img, backup_path in images_with_backups:
            try:
                shutil.copy2(str(backup_path), str(img.path))
                restored += 1
            except Exception as e:
                QMessageBox.warning(None, "Restore Error", f"Failed to restore {img.path.name}:\n{str(e)}")

        if restored > 0:
            QMessageBox.information(None, "Restore Complete", f"Successfully restored {restored} {'file' if restored == 1 else 'files'}.")
            # Trigger reload to update thumbnails
            self.directory_reload_requested.emit()

    @Slot()
    def update_context_menu_actions(self):
        selected_image_count = len(self.selectedIndexes())
        copy_file_names_action_name = (
            f'Copy File {pluralize("Name", selected_image_count)}')
        copy_paths_action_name = (f'Copy '
                                  f'{pluralize("Path", selected_image_count)}')
        move_images_action_name = (
            f'Move {pluralize("Image", selected_image_count)} to...')
        copy_images_action_name = (
            f'Copy {pluralize("Image", selected_image_count)} to...')
        duplicate_images_action_name = (
            f'Duplicate {pluralize("Image", selected_image_count)}')
        delete_images_action_name = (
            f'Delete {pluralize("Image", selected_image_count)}')
        self.copy_file_names_action.setText(copy_file_names_action_name)
        self.copy_paths_action.setText(copy_paths_action_name)
        self.move_images_action.setText(move_images_action_name)
        self.copy_images_action.setText(copy_images_action_name)
        self.duplicate_images_action.setText(duplicate_images_action_name)
        self.delete_images_action.setText(delete_images_action_name)
        self.open_image_action.setVisible(selected_image_count == 1)
        self.open_folder_action.setVisible(selected_image_count >= 1)

        # Check if any selected images have backups
        has_backup = False
        if selected_image_count > 0:
            selected_images = self.get_selected_images()
            has_backup = any((Path(str(img.path) + '.backup')).exists() for img in selected_images if img is not None)
        restore_action_name = f'Restore {pluralize("Backup", selected_image_count)}'
        self.restore_backup_action.setText(restore_action_name)
        self.restore_backup_action.setVisible(has_backup)

    def _show_page_indicator(self):
        """Show page indicator overlay when scrolling in pagination mode."""
        source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else None
        if not source_model or not hasattr(source_model, '_paginated_mode') or not source_model._paginated_mode:
            return

        # Get current visible page from first visible item (use masonry if available)
        visible_items = self._get_masonry_visible_items(self.viewport().rect())
        if visible_items and len(visible_items) > 0:
            first_visible_idx = visible_items[0]['index']
        else:
            # Fallback: estimate from scroll position
            scrollbar = self.verticalScrollBar()
            scroll_value = scrollbar.value()
            scroll_max = scrollbar.maximum()
            scroll_ratio = scroll_value / max(scroll_max, 1) if scroll_max > 0 else 0
            first_visible_idx = int(scroll_ratio * source_model._total_count)

        current_page = source_model._get_page_for_index(first_visible_idx)
        total_pages = (source_model._total_count + source_model.PAGE_SIZE - 1) // source_model.PAGE_SIZE

        # Create label if needed
        if not self._page_indicator_label:
            from PySide6.QtWidgets import QLabel
            from PySide6.QtCore import Qt
            self._page_indicator_label = QLabel(self.viewport())
            self._page_indicator_label.setStyleSheet("""
                QLabel {
                    background-color: rgba(0, 0, 0, 180);
                    color: white;
                    padding: 10px 20px;
                    border-radius: 8px;
                    font-size: 16px;
                    font-weight: bold;
                }
            """)
            self._page_indicator_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Update text and position
        self._page_indicator_label.setText(f"Page {current_page + 1} / {total_pages}")
        self._page_indicator_label.adjustSize()

        # Position at top-right corner
        viewport_rect = self.viewport().rect()
        label_x = viewport_rect.width() - self._page_indicator_label.width() - 20
        label_y = 20
        self._page_indicator_label.move(label_x, label_y)

        # Show and reset fade timer
        self._page_indicator_label.setWindowOpacity(1.0)
        self._page_indicator_label.show()
        self._page_indicator_timer.stop()
        self._page_indicator_timer.start(1500)  # Fade after 1.5s

    def _fade_out_page_indicator(self):
        """Fade out page indicator after delay."""
        if not self._page_indicator_label:
            return

        from PySide6.QtCore import QPropertyAnimation, QEasingCurve

        # Animate opacity from 1.0 to 0.0
        self._page_fade_animation = QPropertyAnimation(self._page_indicator_label, b"windowOpacity")
        self._page_fade_animation.setDuration(500)  # 500ms fade
        self._page_fade_animation.setStartValue(1.0)
        self._page_fade_animation.setEndValue(0.0)
        self._page_fade_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._page_fade_animation.finished.connect(self._page_indicator_label.hide)
        self._page_fade_animation.start()


class ImageList(QDockWidget):
    def __init__(self, proxy_image_list_model: ProxyImageListModel,
                 tag_separator: str, image_width: int):
        super().__init__()
        self.proxy_image_list_model = proxy_image_list_model
        # Each `QDockWidget` needs a unique object name for saving its state.
        self.setObjectName('image_list')
        self.setWindowTitle('Images')
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea
                             | Qt.DockWidgetArea.RightDockWidgetArea)

        self.filter_line_edit = FilterLineEdit()

        # Selection mode and Sort on same row
        selection_sort_layout = QHBoxLayout()
        selection_mode_label = QLabel('Selection')
        self.selection_mode_combo_box = SettingsComboBox(
            key='image_list_selection_mode')
        self.selection_mode_combo_box.addItems(list(SelectionMode))

        sort_label = QLabel('Sort')
        self.sort_combo_box = SettingsComboBox(key='image_list_sort_by')
        self.sort_combo_box.addItems(['Default', 'Name', 'Modified', 'Created',
                                       'Size', 'Type', 'Random'])

        selection_sort_layout.addWidget(selection_mode_label)
        selection_sort_layout.addWidget(self.selection_mode_combo_box, stretch=1)
        selection_sort_layout.addWidget(sort_label)
        selection_sort_layout.addWidget(self.sort_combo_box, stretch=1)

        self.list_view = ImageListView(self, proxy_image_list_model,
                                       tag_separator, image_width)
        self.image_index_label = QLabel()
        # A container widget is required to use a layout with a `QDockWidget`.
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.addWidget(self.filter_line_edit)
        layout.addLayout(selection_sort_layout)
        layout.addWidget(self.list_view)
        layout.addWidget(self.image_index_label)
        self.setWidget(container)

        self.selection_mode_combo_box.currentTextChanged.connect(
            self.set_selection_mode)
        self.set_selection_mode(self.selection_mode_combo_box.currentText())

        # Connect sort signal
        self.sort_combo_box.currentTextChanged.connect(self._on_sort_changed)

    def set_selection_mode(self, selection_mode: str):
        if selection_mode == SelectionMode.DEFAULT:
            self.list_view.setSelectionMode(
                QAbstractItemView.SelectionMode.ExtendedSelection)
        elif selection_mode == SelectionMode.TOGGLE:
            self.list_view.setSelectionMode(
                QAbstractItemView.SelectionMode.MultiSelection)

    @Slot()
    def update_image_index_label(self, proxy_image_index: QModelIndex):
        image_count = self.proxy_image_list_model.rowCount()
        unfiltered_image_count = (self.proxy_image_list_model.sourceModel()
                                  .rowCount())
        label_text = f'Image {proxy_image_index.row() + 1} / {image_count}'
        if image_count != unfiltered_image_count:
            label_text += f' ({unfiltered_image_count} total)'
        self.image_index_label.setText(label_text)

    @Slot()
    def go_to_previous_image(self):
        if self.list_view.selectionModel().currentIndex().row() == 0:
            return
        self.list_view.clearSelection()
        previous_image_index = self.proxy_image_list_model.index(
            self.list_view.selectionModel().currentIndex().row() - 1, 0)
        self.list_view.setCurrentIndex(previous_image_index)

    @Slot()
    def go_to_next_image(self):
        if (self.list_view.selectionModel().currentIndex().row()
                == self.proxy_image_list_model.rowCount() - 1):
            return
        self.list_view.clearSelection()
        next_image_index = self.proxy_image_list_model.index(
            self.list_view.selectionModel().currentIndex().row() + 1, 0)
        self.list_view.setCurrentIndex(next_image_index)

    @Slot()
    def jump_to_first_untagged_image(self):
        """
        Select the first image that has no tags, or the last image if all
        images are tagged.
        """
        proxy_image_index = None
        for proxy_image_index in range(self.proxy_image_list_model.rowCount()):
            image: Image = self.proxy_image_list_model.data(
                self.proxy_image_list_model.index(proxy_image_index, 0),
                Qt.ItemDataRole.UserRole)
            if not image.tags:
                break
        if proxy_image_index is None:
            return
        self.list_view.clearSelection()
        self.list_view.setCurrentIndex(
            self.proxy_image_list_model.index(proxy_image_index, 0))

    def get_selected_image_indices(self) -> list[QModelIndex]:
        return self.list_view.get_selected_image_indices()

    @Slot(str)
    def _on_sort_changed(self, sort_by: str):
        """Sort images when sort option changes."""
        # Get the source model
        source_model = self.proxy_image_list_model.sourceModel()
        if not source_model or not hasattr(source_model, 'images'):
            return

        # Cancel any ongoing background enrichment (indices will be invalid after sort)
        if hasattr(source_model, '_enrichment_cancelled'):
            source_model._enrichment_cancelled.set()
            print("[SORT] Cancelled background enrichment (reordering images)")

        # Safe file stat getter with fallback
        def safe_stat(img, attr, default=0):
            try:
                return getattr(img.path.stat(), attr)
            except (OSError, AttributeError):
                return default

        # Sort the images list
        try:
            # Emit layoutAboutToBeChanged before sorting
            source_model.layoutAboutToBeChanged.emit()

            if sort_by == 'Default':
                # Use natural sort from image_list_model (same as initial load)
                source_model.images.sort(key=lambda img: natural_sort_key(img.path))
            elif sort_by == 'Name':
                # Natural sort by filename only (not full path)
                source_model.images.sort(key=lambda img: natural_sort_key(Path(img.path.name)))
            elif sort_by == 'Modified':
                source_model.images.sort(key=lambda img: safe_stat(img, 'st_mtime'), reverse=True)
            elif sort_by == 'Created':
                source_model.images.sort(key=lambda img: safe_stat(img, 'st_ctime'), reverse=True)
            elif sort_by == 'Size':
                source_model.images.sort(key=lambda img: safe_stat(img, 'st_size'), reverse=True)
            elif sort_by == 'Type':
                source_model.images.sort(key=lambda img: (img.path.suffix.lower(), natural_sort_key(img.path.name)))
            elif sort_by == 'Random':
                import random
                random.shuffle(source_model.images)

            # Rebuild aspect ratio cache after reordering
            if hasattr(source_model, '_rebuild_aspect_ratio_cache'):
                source_model._rebuild_aspect_ratio_cache()

            # Emit layoutChanged after sorting
            source_model.layoutChanged.emit()

            # Restart background enrichment with new sorted order
            if hasattr(source_model, '_restart_enrichment'):
                source_model._restart_enrichment()
        except Exception as e:
            import traceback
            print(f"Sort error: {e}")
            traceback.print_exc()
            # Ensure layoutChanged is emitted even on error
            source_model.layoutChanged.emit()

