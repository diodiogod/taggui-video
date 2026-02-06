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
                # Paint icon filling the rect (maintaining aspect ratio is handled by QIcon.paint if modes used, 
                # but here we just fill the target rect which masonry already calculated)
                
                # Draw centered and scaled to fit (QIcon.paint does this automatically usually)
                # But to be safe and crisp:
                # We can just pass the rect.
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
        proxy_image_list_model.layoutChanged.connect(lambda: self._on_layout_changed())
        proxy_image_list_model.filter_changed.connect(lambda: self._recalculate_masonry_if_needed("filter_changed"))

        # Handle dimension updates from enrichment (no layout invalidation)
        source_model.dimensions_updated.connect(lambda: self._recalculate_masonry_if_needed("dimensions_updated"))
        
        # Handle full paginated enrichment completion (requires reloading pages)
        if hasattr(source_model, 'enrichment_complete'):
            source_model.enrichment_complete.connect(self._on_paginated_enrichment_complete)

        # Handle buffered mode page updates (avoids layoutChanged crash!)
        proxy_image_list_model.pages_updated.connect(self._on_pages_updated)

        # Cache status now shown in main window status bar (not floating labels here)

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
        self._last_known_total_count = 0 # Cache for total items count to prevent collapse during model updates
        self._painting = False  # Flag to prevent layout changes during paint (prevents re-entrancy)
        self._last_stable_scroll_value = 0 # Track stable scroll position to survive layout resets
        self.verticalScrollBar().valueChanged.connect(self._on_scroll_value_changed)
        
        # Setup signals
        self.verticalScrollBar().valueChanged.connect(self._check_and_load_pages)
        self.horizontalScrollBar().valueChanged.connect(self._check_and_load_pages)
        source_model.layoutChanged.connect(self._on_layout_changed)
        self.proxy_image_list_model.layoutChanged.connect(self._on_layout_changed)
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
        self._last_loaded_pages = set()  # Track which pages have thumbnails loaded
        self._scrollbar_dragging = False  # Track if user is dragging scrollbar

        # Cache status is now shown in main window status bar (removed floating labels)

        # DISABLED: Cache warming causes UI blocking
        # self._cache_warm_idle_timer = QTimer(self)
        # self._cache_warm_idle_timer.setSingleShot(True)
        # self._cache_warm_idle_timer.timeout.connect(self._start_cache_warming)

        # Idle timer for flushing cache saves (2 seconds after scroll stops)
        self._cache_flush_timer = QTimer(self)
        self._cache_flush_timer.setSingleShot(True)
        self._cache_flush_timer.timeout.connect(self._flush_cache_saves)

        # Resize debounce timer for smooth resizing with large datasets
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._on_resize_finished)

        # Mouse scroll detection timer (pause loading during scroll)
        self._mouse_scroll_timer = QTimer(self)
        self._mouse_scroll_timer.setSingleShot(True)
        self._mouse_scroll_timer.timeout.connect(self._on_mouse_scroll_stopped)
        self._mouse_scrolling = False
        self._page_indicator_timer.setSingleShot(True)
        self._page_indicator_timer.timeout.connect(self._fade_out_page_indicator)
        self._preload_index = 0  # Track preload progress
        self._preload_complete = False  # Track if all thumbnails loaded
        self._thumbnails_loaded = set()  # Track which thumbnails are loaded (by index)
        self._thumbnail_cache_hits = set()  # Track unique cache hits by index
        self._thumbnail_cache_misses = set()  # Track unique cache misses by index
        self._flow_log_last: dict[str, float] = {}
        self._masonry_sticky_until = 0.0
        self._masonry_sticky_page = 0
        self._last_masonry_window_signature = None
        self._drag_preview_mode = False
        self._suppress_anchor_until = 0.0
        self._pending_edge_snap = None
        self._pending_edge_snap_until = 0.0
        self._stick_to_edge = None
        self._drag_release_anchor_idx = None
        self._drag_release_anchor_until = 0.0
        self._drag_release_anchor_active = False

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

        # Connect scrollbar events to detect dragging
        self.verticalScrollBar().sliderPressed.connect(self._on_scrollbar_pressed)
        self.verticalScrollBar().sliderReleased.connect(self._on_scrollbar_released)

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

    def _log_flow(self, component: str, message: str, *, level: str = "DEBUG",
                  throttle_key: str | None = None, every_s: float | None = None):
        """Timestamped, optionally throttled flow logging for masonry/pagination diagnostics."""
        now = time.time()
        if throttle_key and every_s is not None:
            last = self._flow_log_last.get(throttle_key, 0.0)
            if (now - last) < every_s:
                return
            self._flow_log_last[throttle_key] = now
        ts = time.strftime("%H:%M:%S", time.localtime(now)) + f".{int((now % 1) * 1000):03d}"
        print(f"[{ts}][{component}][{level}] {message}")

    def _use_local_anchor_masonry(self, source_model=None) -> bool:
        """Enable local-anchor masonry for large paginated datasets."""
        if source_model is None:
            source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else None
        if not source_model or not hasattr(source_model, '_paginated_mode') or not source_model._paginated_mode:
            return False
        total_items = getattr(source_model, '_total_count', 0)
        # Local anchor mode is intended for large folders where smoothness > global perfect continuity.
        return total_items >= 10000

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

    def _on_scroll_value_changed(self, value):
        """Track valid scroll positions to enable restoration after layout resets."""
        sb = self.verticalScrollBar()
        max_v = sb.maximum()
        user_driven = self._scrollbar_dragging or self._mouse_scrolling
        if user_driven:
            if self._stick_to_edge == "bottom":
                if max_v > 0 and value < max_v - 200:
                    self._stick_to_edge = None
            elif self._stick_to_edge == "top":
                if value > 200:
                    self._stick_to_edge = None

        # Only record if scrollbar is "healthy" (not collapsed)
        # If internal height is huge (22M) but scrollbar max is tiny (195k), we are collapsed.
        if hasattr(self, '_masonry_total_height') and self._masonry_total_height > 50000:
            current_max = max_v
            # Loose check: if max is decent sized, we trust the value
            if current_max > 50000:
                self._last_stable_scroll_value = value

        # Keep page indicator live while dragging (acts as a page chooser overlay).
        if self._scrollbar_dragging or self._drag_preview_mode:
            import time
            now = time.time()
            if not hasattr(self, '_last_page_indicator_drag_update'):
                self._last_page_indicator_drag_update = 0.0
            if now - self._last_page_indicator_drag_update >= 0.05:  # 20 FPS
                self._last_page_indicator_drag_update = now
                self._show_page_indicator()

    def on_filter_keystroke(self):
        """Called on every filter keystroke (before debounce) to detect rapid input."""
        import time
        current_time = time.time()
        
        if self._last_filter_keystroke_time > 0:
            time_since_last = (current_time - self._last_filter_keystroke_time) * 1000
            if time_since_last < 100:  # Less than 100ms = rapid typing/deletion
                self._rapid_input_detected = True
            else:
                self._rapid_input_detected = False
        else:
            # First keystroke - assume normal
            self._rapid_input_detected = False

        self._last_filter_keystroke_time = current_time

    def _on_layout_changed(self):
        """Handle layoutChanged signal - skip post-bootstrap in buffered mode to prevent crashes."""
        source_model = self.model().sourceModel() if hasattr(self.model(), 'sourceModel') else self.model()
        
        # CRITICAL: In buffered mode AFTER bootstrap, layoutChanged is dangerous - use pages_updated instead
        # But DURING bootstrap, we need layoutChanged to display initial images!
        if source_model and hasattr(source_model, '_paginated_mode') and source_model._paginated_mode:
            # Check if bootstrap is complete
            bootstrap_complete = getattr(source_model, '_bootstrap_complete', False)
            if bootstrap_complete:
                # Post-bootstrap: ignore layoutChanged from dynamic page loads
                # Only respond to pages_updated signal
                self._log_flow("LAYOUT", "Skipping post-bootstrap layoutChanged; pages_updated drives masonry",
                               throttle_key="layout_skip", every_s=0.5)
                return
            else:
                # Bootstrap phase: allow layoutChanged to display initial images
                self._log_flow("LAYOUT", "Allowing bootstrap layoutChanged",
                               throttle_key="layout_bootstrap", every_s=0.5)
        
        # CRITICAL: Skip layout changes during painting to prevent re-entrancy crash
        # Page loading can trigger layoutChanged while we're in paintEvent
        if hasattr(self, '_painting') and self._painting:
            # Defer this layout change until after paint completes
            from PySide6.QtCore import QTimer
            QTimer.singleShot(50, lambda: self._on_layout_changed())
            return

        # DON'T clear masonry items here - keep old positions for painting
        # until the recalculation completes and atomically replaces them.
        # Clearing here causes blank viewport during the 100ms+ recalc delay!

        # Don't clear _masonry_total_height in buffered mode - keep estimated value for scrollbar
        # Use stable proxy reference
        is_buffered_safe = False
        if hasattr(self, 'proxy_image_list_model') and self.proxy_image_list_model:
             src = self.proxy_image_list_model.sourceModel()
             if src and hasattr(src, '_paginated_mode') and src._paginated_mode:
                 is_buffered_safe = True

        if not is_buffered_safe:
            # COLLAPSE GUARD: If we were previously huge, don't reset to 0 just because mode check failed
            if self._masonry_total_height > 50000:
                 pass # print(f"[LAYOUT] ⚠️ CRITICAL: Prevented height reset in _on_layout_changed! prev={self._masonry_total_height}")
            else:
                 self._masonry_total_height = 0

        # Now trigger recalculation (will replace _masonry_items when done)
        self._recalculate_masonry_if_needed("layoutChanged")


    def _on_paginated_enrichment_complete(self):
        """Handle completion of background enrichment in paginated mode."""
        self._log_flow("ENRICH", "Paginated enrichment complete; reloading active pages", level="INFO")
        self._masonry_sticky_page = getattr(self, '_current_page', 0)
        self._masonry_sticky_until = time.time() + 0.5  # Prevent immediate window rebasing/jitter
        self._last_masonry_window_signature = None  # Force recalc with enriched dimensions
        
        # CRITICAL FIX: Defer to avoid race with masonry cleanup
        def reload_pages():
            source_model = self.proxy_image_list_model.sourceModel()
            if hasattr(source_model, '_pages'):
                 for page_num in list(source_model._pages.keys()):
                     source_model._load_page_sync(page_num)
            self._last_masonry_signal = "enrichment_complete"
            source_model._emit_pages_updated()
        
        from PySide6.QtCore import QTimer
        QTimer.singleShot(250, reload_pages)
        # source_model.layoutChanged.emit() # Optional, already covered by pages_updated logic if connected

    def _on_pages_updated(self, loaded_pages: list):
        """Handle page load/eviction in buffered mode (safe alternative to layoutChanged)."""
        if not self.use_masonry:
            return
        
        self._log_flow("PAGES", f"Pages updated ({len(loaded_pages)} loaded); scheduling masonry recalc",
                       throttle_key="pages_updated", every_s=0.3)
        
        # Recalculate masonry for currently loaded pages
        # This is safe because it doesn't emit layoutChanged
        self._last_masonry_window_signature = None
        self._recalculate_masonry_if_needed("pages_updated")
        
        # Request viewport repaint (safe, doesn't invalidate model)
        self.viewport().update()


    def _recalculate_masonry_if_needed(self, signal_name="unknown"):
        """Recalculate masonry layout if in masonry mode (debounced with adaptive delay)."""
        import time
        if not self.use_masonry:
            return

        current_time = time.time()
        timestamp = time.strftime("%H:%M:%S.") + f"{int(current_time * 1000) % 1000:03d}"

        # Store signal name for _do_recalculate_masonry to check
        self._last_masonry_signal = signal_name

        # Low-priority signal: don't keep restarting the timer if dimensions updates
        # are arriving continuously and a recalc is already queued/running.
        if signal_name == "dimensions_updated":
            if self._masonry_calculating:
                return
            if self._masonry_recalc_timer.isActive():
                return

        # Adaptive delay: check if rapid input was detected at keystroke level
        if self._rapid_input_detected:
            self._masonry_recalc_delay = self._masonry_recalc_max_delay
            # print(f"[MASONRY {timestamp}] SIGNAL: {signal_name}, RAPID INPUT FLAG SET - using max delay {self._masonry_recalc_delay}ms")
        elif signal_name == "pages_updated":
            # Batch page load updates (prevents recalc for every single page in a sequence)
            self._masonry_recalc_delay = 300
        elif signal_name in ["layoutChanged", "user_click"]:
            # For layoutChanged or user clicks, use shorter delay for faster updates
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

        # Pagination mode with buffered masonry - only calculates for loaded pages
        source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else None
        if source_model and hasattr(source_model, '_paginated_mode') and source_model._paginated_mode:
            # Buffered mode - will only calculate for loaded pages
            loaded_pages = len(source_model._pages) if hasattr(source_model, '_pages') else 0
            self._log_flow("MASONRY", f"Recalc requested; buffered pages loaded={loaded_pages}",
                           throttle_key="masonry_recalc_req", every_s=0.5)

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

        # In buffered pagination mode, skip if no pages loaded yet
        source_model = self.model().sourceModel() if hasattr(self.model(), 'sourceModel') else self.model()
        if source_model and hasattr(source_model, '_paginated_mode') and source_model._paginated_mode:
            if not source_model._pages:
                self._log_flow("MASONRY", "Skipping calc: no pages loaded yet",
                               throttle_key="masonry_no_pages", every_s=1.0)
                return

        # If already calculating, mark as pending and return
        if self._masonry_calculating:
            self._masonry_recalc_pending = True
            # print("[MASONRY] Calculation in progress, marking new one as pending")
            return
        
        self._masonry_recalc_pending = False
        
        # CRITICAL FIX: Always check grace period after masonry completion
        # Check timestamp independently of future reference (which might be None)
        import time
        current_time = time.time()
        
        if hasattr(self, '_last_masonry_done_time') and self._last_masonry_done_time > 0:
            time_since_done = (current_time - self._last_masonry_done_time) * 1000
            
            if time_since_done < 500:  # 500ms grace period for thread cleanup
                remaining = int(500 - time_since_done)
                self._log_flow("MASONRY", f"Grace period active: {remaining}ms remaining",
                               throttle_key="masonry_grace", every_s=0.5)
                # Schedule retry after grace period
                from PySide6.QtCore import QTimer
                QTimer.singleShot(remaining, self._calculate_masonry_layout)
                return
        
        # CRITICAL FIX: Recreate executor periodically to prevent thread pool exhaustion
        # After many rapid operations, thread state can accumulate and cause crashes
        if not hasattr(self, '_masonry_calc_count'):
            self._masonry_calc_count = 0
        
        self._masonry_calc_count += 1
        if self._masonry_calc_count % 20 == 0:  # Reset every 20 calculations
            print(f"[MASONRY] Recreating executor after {self._masonry_calc_count} calculations")
            try:
                old_executor = self._masonry_executor
                from concurrent.futures import ThreadPoolExecutor
                self._masonry_executor = ThreadPoolExecutor(max_workers=1)
                # Shut down old executor in background
                import threading
                threading.Thread(target=lambda: old_executor.shutdown(wait=True), daemon=True).start()
            except Exception as e:
                print(f"[MASONRY] Failed to recreate executor: {e}")

        self._masonry_calculating = True
        import time
        self._masonry_start_time = time.time() # Start watchdog timer

        # Pause enrichment during masonry calculation to prevent race conditions
        source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else self.model()
        if source_model and hasattr(source_model, '_enrichment_paused'):
            source_model._enrichment_paused.set()
            self._log_flow("MASONRY", "Paused enrichment for recalculation",
                           throttle_key="masonry_pause", every_s=0.5)

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
        # Wrap in try/except to prevent crashes from concurrent cache rebuilds
        try:
            items_data = self.model().get_filtered_aspect_ratios()

            # Safety check: skip if no items
            if not items_data:
                self._log_flow("MASONRY", "Skipping calc: no items loaded yet",
                               throttle_key="masonry_no_items", every_s=1.0)
                self._masonry_calculating = False
                if source_model and hasattr(source_model, '_enrichment_paused'):
                    source_model._enrichment_paused.clear()
                return

            # Debug: show item count
            if source_model and hasattr(source_model, '_paginated_mode') and source_model._paginated_mode:
                # OPTIMIZATION: In buffered mode, only layout items near current scroll position
                # This prevents Page 0 (if still loaded) from being included when we are at Page 1000,
                # which would break the Y-offset shift logic (which depends on first_index).
                page_size = source_model.PAGE_SIZE if hasattr(source_model, 'PAGE_SIZE') else 1000
                total_items = source_model._total_count if hasattr(source_model, '_total_count') else 0
                
                # CRITICAL FIX: Compute current page DIRECTLY from scroll position
                # Prefer visible masonry top index (stable), fallback to scroll fraction.
                scroll_val = self.verticalScrollBar().value()
                scroll_max = self.verticalScrollBar().maximum()
                source_idx = None
                anchor_active = (
                    getattr(self, '_drag_release_anchor_active', False)
                    and self._drag_release_anchor_idx is not None
                    and time.time() < getattr(self, '_drag_release_anchor_until', 0.0)
                )
                stick_bottom = getattr(self, '_stick_to_edge', None) == "bottom"
                stick_top = getattr(self, '_stick_to_edge', None) == "top"
                if stick_bottom and total_items > 0:
                    source_idx = total_items - 1
                elif stick_top:
                    source_idx = 0
                elif anchor_active:
                    source_idx = int(self._drag_release_anchor_idx)

                if (not anchor_active) and (not stick_bottom) and (not stick_top) and self._masonry_items:
                    viewport_height = self.viewport().height()
                    viewport_rect = QRect(0, scroll_val, self.viewport().width(), viewport_height)
                    visible_now = self._get_masonry_visible_items(viewport_rect)
                    if visible_now:
                        # Ignore spacer tokens (negative indices) when estimating current page.
                        real_visible = [it for it in visible_now if it.get('index', -1) >= 0]
                        if real_visible:
                            top_item = min(real_visible, key=lambda x: x['rect'].y())
                            source_idx = top_item['index']

                # If no real visible item is available (e.g. viewport currently on spacers),
                # prefer the tracked current page from scroll logic to avoid oscillation.
                if total_items > 0 and scroll_val <= 2:
                    source_idx = 0
                elif total_items > 0 and scroll_max > 0 and scroll_val >= scroll_max - 2:
                    source_idx = total_items - 1

                if source_idx is None and hasattr(self, '_current_page'):
                    source_idx = max(0, int(self._current_page) * page_size)

                if source_idx is None and scroll_max > 0 and total_items > 0:
                    scroll_fraction = scroll_val / scroll_max
                    source_idx = int(scroll_fraction * total_items)

                if source_idx is None:
                    source_idx = 0

                candidate_page = max(0, min((total_items - 1) // page_size if total_items > 0 else 0, source_idx // page_size))
                prev_page = self._current_page if hasattr(self, '_current_page') else candidate_page

                # Hysteresis: avoid page flapping near boundaries.
                current_page = candidate_page
                if (not anchor_active) and (not stick_bottom) and (not stick_top) and total_items > 0 and candidate_page != prev_page:
                    half_page = max(1, page_size // 2)
                    if candidate_page > prev_page:
                        if source_idx < ((prev_page + 1) * page_size + half_page):
                            current_page = prev_page
                    else:
                        if source_idx > (prev_page * page_size - half_page):
                            current_page = prev_page

                # Sticky window right after enrichment/layout refresh.
                if (not anchor_active) and (not stick_bottom) and (not stick_top) and time.time() < getattr(self, '_masonry_sticky_until', 0.0):
                    current_page = getattr(self, '_masonry_sticky_page', current_page)
                
                # Update cached value for other uses
                self._current_page = current_page
                
                # Keep masonry calculations local to the current region.
                # This is intentionally small for responsive correction on large folders.
                try:
                    window_buffer = int(settings.value('thumbnail_eviction_pages', 3, type=int))
                except Exception:
                    window_buffer = 3
                window_buffer = max(1, min(window_buffer, 6))
                max_page = (total_items + page_size - 1) // page_size
                full_layout_mode = False
                local_anchor_mode = self._use_local_anchor_masonry(source_model)

                # Accuracy mode: when most/all items are loaded, compute full masonry to preserve
                # true column state. Windowed spacer mode cannot reproduce exact column heights.
                loaded_count = len(items_data)
                if total_items > 0 and not local_anchor_mode:
                    coverage = loaded_count / total_items
                    if coverage >= 0.95 and total_items <= 50000:
                        full_layout_mode = True

                # Estimate row/column metrics for spacer heights once
                avg_h = getattr(self, '_stable_avg_item_height', 100.0)
                if avg_h < 1:
                    avg_h = 100.0
                scroll_bar_width = self.verticalScrollBar().width() if self.verticalScrollBar().isVisible() else 0
                avail_width = viewport_width - scroll_bar_width - 24  # margins
                num_cols_est = max(1, avail_width // (column_width + spacing))

                if full_layout_mode:
                    window_start_page = 0
                    window_end_page = max_page - 1
                    min_idx = 0
                    max_idx = total_items
                else:
                    # Window layout around current page (not full 0..N), with prefix/suffix spacers
                    # to preserve absolute Y positioning while keeping token count small.
                    window_start_page = max(0, current_page - window_buffer)
                    window_end_page = min(max_page - 1, current_page + window_buffer)
                    min_idx = window_start_page * page_size
                    max_idx = min(total_items, (window_end_page + 1) * page_size)

                loaded_pages_sig = tuple(sorted(source_model._pages.keys())) if hasattr(source_model, '_pages') else ()
                window_signature = (
                    window_start_page,
                    window_end_page,
                    loaded_pages_sig,
                    num_columns,
                    self.current_thumbnail_size,
                    self.viewport().width(),
                    full_layout_mode,
                )
                if window_signature == self._last_masonry_window_signature and self._last_masonry_signal not in {"resize", "enrichment_complete"}:
                    self._log_flow("MASONRY", "Skipping calc: unchanged window signature",
                                   throttle_key="masonry_same_window", every_s=0.8)
                    self._masonry_calculating = False
                    if source_model and hasattr(source_model, '_enrichment_paused'):
                        source_model._enrichment_paused.clear()
                    return
                self._last_masonry_window_signature = window_signature
                
                # CRITICAL FIX: Proactively load pages in the masonry window
                # Without this, the layout runs before pages are loaded, resulting in empty display
                for p in range(max(0, current_page - window_buffer), min(max_page, current_page + window_buffer + 1)):
                    if p not in source_model._pages and p not in source_model._loading_pages:
                        source_model._request_page_load(p)

                
                # Filter loaded items to the active window only
                original_count = len(items_data)
                filtered_items = [item for item in items_data if min_idx <= item[0] < max_idx]
                
                # GAP FILLING: Detect missing index ranges and insert spacers
                # This ensures consistent Y-coordinates even if pages are missing
                items_data = []
                if filtered_items:
                    # Sort by index just in case
                    filtered_items.sort(key=lambda x: x[0])
                    
                    # Insert prefix spacer for pages before the window so layout coordinates remain absolute.
                    if min_idx > 0:
                        import math
                        prefix_rows = math.ceil(min_idx / num_cols_est)
                        prefix_h = int(prefix_rows * avg_h)
                        items_data.append((-3, ('SPACER', prefix_h)))

                    # Initialize last_idx to start of window (minus 1)
                    # This ensures we insert a spacer if the first loaded item is NOT min_idx
                    last_idx = min_idx - 1
                    
                    for item in filtered_items:
                        curr_idx = item[0]
                        gap = curr_idx - last_idx - 1
                        if gap > 0:
                            # Found a gap (missing items)
                            # Convert item count to approximate pixel height
                            # Each row has 'num_cols_est' items.
                            # height = (gap / cols) * row_height
                            import math
                            gap_rows = math.ceil(gap / num_cols_est)
                            spacer_h = int(gap_rows * avg_h)
                            
                            # Insert spacer token
                            # print(f"[MASONRY] Inserting spacer for gap {last_idx+1}-{curr_idx-1} ({gap} items, ~{spacer_h}px)")
                            items_data.append((-1, ('SPACER', spacer_h))) 
                            
                        items_data.append(item)
                        last_idx = curr_idx
                    
                    # TAIL GAP FILLER: Check if the window extends beyond the last loaded item
                    # This ensures we reserve space for missing pages at the bottom of the window
                    if total_items > 0: # Ensure we have a valid total count
                         last_item_idx = filtered_items[-1][0]
                         # Our window goes up to max_idx (exclusive).
                         # But the dataset might end before max_idx.
                         # We want to fill up to the smaller of (window_end, dataset_end).
                         
                         target_end_idx = min(max_idx, total_items)
                         gap = target_end_idx - last_item_idx - 1
                         
                         if gap > 0:
                            import math
                            gap_rows = math.ceil(gap / num_cols_est)
                            spacer_h = int(gap_rows * avg_h)
                            
                            # items_data.append((-1, ('SPACER', spacer_h))) 
                            # We use a special index for the tail spacer so it doesn't conflict
                            items_data.append((-2, ('SPACER', spacer_h))) 
                            
                else:
                    # Window is outside currently loaded items (e.g. jumped to Page 50, only Page 0-5 loaded)
                    # We need to insert a spacer for this entire window so the user sees "something" (blank space)
                    # and the scrollbar maintains its size/position while we wait for loads.
                    if total_items > 0:
                         # Calculate how many items *should* be in this window
                         # min_idx to max_idx, clamped to total_items
                         start = min(min_idx, total_items)
                         end = min(max_idx, total_items)
                         count = end - start
                         
                         if count > 0:
                            # Insert a single spacer for this block
                             import math
                             # Estimate how many rows this missing block would take
                             num_cols_est = max(1, avail_width // (column_width + spacing))
                             rows = math.ceil(count / num_cols_est)
                             spacer_h = int(rows * avg_h)
                             
                             # We use a special index structure: (-1, ('SPACER', h))
                             # But let's use a unique index based on the window start to avoid collisions if we merge
                             if min_idx > 0:
                                 import math
                                 prefix_rows = math.ceil(min_idx / num_cols_est)
                                 prefix_h = int(prefix_rows * avg_h)
                                 items_data = [(-3, ('SPACER', prefix_h)), (min_idx, ('SPACER', spacer_h))]
                             else:
                                 items_data = [(min_idx, ('SPACER', spacer_h))]
                             # print(f"[MASONRY] Buffered: Inserted full-window spacer for indices {start}-{end} ({spacer_h}px)")
                    else:
                        items_data = []

                # FINAL SAFETY/BLIND SPOT HANDLER
                # If we still have no items, but we are within the dataset range, we MUST insert a spacer.
                # This handles cases where filtered_items was empty, or checks failed.
                if not items_data and total_items > 0:
                     start = min(min_idx, total_items)
                     end = min(max_idx, total_items)
                     count = end - start
                     
                     if count > 0:
                         import math
                         num_cols_est = max(1, avail_width // (column_width + spacing))
                         rows = math.ceil(count / num_cols_est)
                         
                         # Robust avg height (fallback to 100 if invalid)
                         safe_avg = avg_h if avg_h > 1 else 100.0
                         spacer_h = int(rows * safe_avg)
                         
                         if min_idx > 0:
                             import math
                             prefix_rows = math.ceil(min_idx / num_cols_est)
                             prefix_h = int(prefix_rows * avg_h)
                             items_data = [(-3, ('SPACER', prefix_h)), (min_idx, ('SPACER', spacer_h))]
                         else:
                             items_data = [(min_idx, ('SPACER', spacer_h))]
                         # print(f"[MASONRY] Buffered: Inserted SAFETY spacer for indices {start}-{end} ({spacer_h}px) due to empty items")

                if not items_data:
                     # print(f"[MASONRY] Buffered: No items in visible window (Page {current_page} +/- {window_buffer})")
                     pass 
 

                if full_layout_mode:
                    self._log_flow(
                        "MASONRY",
                        f"Calc start: tokens={len(items_data)} window_pages={window_start_page}-{window_end_page} "
                        f"current_page={current_page} mode=full"
                    )
                else:
                    self._log_flow(
                        "MASONRY",
                        f"Calc start: tokens={len(items_data)} window_pages={window_start_page}-{window_end_page} "
                        f"current_page={current_page}"
                    )
            else:
                self._log_flow("MASONRY", f"Calc start (normal mode): items={len(items_data)}")
        except Exception as e:
            print(f"[MASONRY] Failed to get aspect ratios: {e}")
            import traceback
            traceback.print_exc()
            self._masonry_calculating = False
            if source_model and hasattr(source_model, '_enrichment_paused'):
                source_model._enrichment_paused.clear()
            return
            self._masonry_calculating = False
            # Resume enrichment
            if source_model and hasattr(source_model, '_enrichment_paused'):
                source_model._enrichment_paused.clear()
            return

        try:
            # Generate cache key
            cache_key = self._get_masonry_cache_key()
            
            # CRITICAL: Make a defensive copy of items_data to prevent race conditions
            # If the main thread modifies items_data while the worker is iterating,
            # it can cause crashes. This was causing the second masonry call to fail.
            items_data_copy = list(items_data)
            
            # Validate data before sending to worker
            if not all(isinstance(item, (tuple, list)) and len(item) >= 2 for item in items_data_copy[:10]):
                print(f"[MASONRY] WARNING: items_data contains invalid entries, skipping calculation")
                self._masonry_calculating = False
                return

            # Submit to worker process (NO GIL BLOCKING!)
            self._masonry_calc_future = self._masonry_executor.submit(
                calculate_masonry_layout,
                items_data_copy,  # Pass the copy, not the original!
                column_width,
                spacing,
                num_columns,
                cache_key
            )
        except Exception as e:
            print(f"[MASONRY] CRITICAL ERROR starting calculation: {e}")
            import traceback
            traceback.print_exc()
            self._masonry_calculating = False
            return

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

                # Resume enrichment even on error
                source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else self.model()
                if source_model and hasattr(source_model, '_enrichment_paused'):
                    source_model._enrichment_paused.clear()
                    print("[MASONRY] Resumed enrichment after error")
        else:
            # WATCHDOG: Check if we've been calculating for too long (e.g. > 5 seconds)
            # This handles cases where the future silently hangs or the worker died uniquely
            import time
            current_time = time.time()
            start_time = getattr(self, '_masonry_start_time', 0)
            if self._masonry_calculating and (current_time - start_time > 5.0):
                print(f"[MASONRY] ⚠️ Watchdog triggered: Calculation stuck for {current_time - start_time:.1f}s. Resetting state.")
                self._masonry_calculating = False
                self._masonry_calc_future = None # Abandon broken future
                if hasattr(source_model, '_enrichment_paused'):
                     source_model._enrichment_paused.clear()
                return # Stop polling this dead task

            # Check again in 50ms
            QTimer.singleShot(50, self._check_masonry_completion)
            
            # Heartbeat logging (every 2 seconds approx)
            if not hasattr(self, '_masonry_poll_counter'):
                self._masonry_poll_counter = 0
            self._masonry_poll_counter += 1
            if self._masonry_poll_counter % 40 == 0:
                 # print("[MASONRY] Waiting for worker...")
                 pass

    def _on_masonry_calculation_progress(self, current, total):
        """Update progress bar during calculation."""
        if hasattr(self, '_masonry_progress_bar'):
            self._masonry_progress_bar.setValue(current)

    def _on_masonry_calculation_complete(self, result):
        """Called when multiprocessing calculation completes."""
        try:
            import time
            timestamp = time.strftime("%H:%M:%S.") + f"{int(time.time() * 1000) % 1000:03d}"

            self._masonry_calculating = False
            self._last_masonry_done_time = time.time()

            if result is None:
                source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else self.model()
                if source_model and hasattr(source_model, '_enrichment_paused'):
                    source_model._enrichment_paused.clear()
                    print("[MASONRY] Resumed enrichment (null result)")
                return

            # result is the dict returned by worker
            result_dict = result
            
            # 1. ANCHORING: Capture current view position before updating data
            anchor_index = -1
            anchor_offset = 0
            scroll_val = self.verticalScrollBar().value()
            viewport_height = self.viewport().height()

            if self._masonry_items:
                initial_viewport = self.viewport().rect().translated(0, scroll_val)
                visible_before = self._get_masonry_visible_items(initial_viewport)
                if visible_before:
                    visible_before.sort(key=lambda x: x['rect'].y())
                    anchor_index = visible_before[0]['index']
                    anchor_offset = visible_before[0]['rect'].y() - scroll_val

            # 2. Update model data
            self._masonry_items = result_dict.get('items', [])
            self._masonry_index_map = None
            total_height_chunk = result_dict.get('total_height', 0)

            # 3. Determine if buffered mode
            source_model = self.proxy_image_list_model.sourceModel()
            is_buffered = source_model and hasattr(source_model, '_paginated_mode') and source_model._paginated_mode
            total_items = source_model._total_count if is_buffered else (self.model().rowCount() if self.model() else 0)

            # 4. CALIBRATION & ESTIMATION
            avg_height = getattr(self, '_stable_avg_item_height', 100.0)
            import math
            
            if self._masonry_items:
                # Real data refined average (row-based, not item-based).
                # Dividing by item count severely underestimates virtual height in multi-column grids.
                chunk_items = len([it for it in self._masonry_items if it.get('index', -1) >= 0])
                if chunk_items > 0 and total_height_chunk > 0:
                    column_width_for_avg = self.current_thumbnail_size
                    spacing_for_avg = 2
                    viewport_width_for_avg = self.viewport().width()
                    num_columns_for_avg = max(1, (viewport_width_for_avg + spacing_for_avg) // (column_width_for_avg + spacing_for_avg))
                    chunk_rows = max(1, math.ceil(chunk_items / num_columns_for_avg))
                    real_avg = total_height_chunk / chunk_rows
                    if 10.0 < real_avg < 5000.0:
                        if not hasattr(self, '_stable_avg_item_height'):
                            self._stable_avg_item_height = real_avg
                        else:
                            # Use a slower moving average to prevent oscillation loops
                            self._stable_avg_item_height = (self._stable_avg_item_height * 0.9) + (real_avg * 0.1)
                        
            # Use the most up-to-date stable average
            avg_height = getattr(self, '_stable_avg_item_height', 100.0)

            # Final total height estimation
            if math.isnan(avg_height): avg_height = 100.0

            # Calculate actual columns to fix estimation error
            # (Previously assumed 1 column, causing massive overestimation with many columns)
            column_width = self.current_thumbnail_size
            spacing = 2
            viewport_width = self.viewport().width()
            num_columns = max(1, (viewport_width + spacing) // (column_width + spacing))
            
            estimated_rows = math.ceil(total_items / num_columns)
            self._masonry_total_height = int(estimated_rows * avg_height)
            self._masonry_total_height = max(self._masonry_total_height, estimated_rows * 10)

            # 5. BUFFER MODE SHIFTING & RESCUE
            # Buffer mode logic
            if is_buffered and self._masonry_items:
                first_item_idx = self._masonry_items[0]['index']
                
                # DEFAULT OFFSET: 0 (Cumulative Layout)
                # Since min_idx=0 and we use spacers, the item['y'] is already absolute.
                y_offset = 0
                
                # VISUAL ANCHORING (Blind Spot Fix):
                # If we don't have a visual anchor (jumped into void), 
                # align the content to where the user is LOOKING, not where theory says it should be.
                if anchor_index == -1 and first_item_idx > 0:
                    # User is at 'scroll_val'.
                    # Based on our PREVIOUS estimate (which led the user to drag here),
                    # they expect to see 'target_idx'.
                    # target_idx = scroll_val / old_avg (We don't have old_avg easily, but we know scroll_val)
                    
                    # We can reverse it: Find the item in our new batch that SHOULD be at scroll_val
                    # matching the 'percentage' of the scrollbar? 
                    # Simpler: Just align the first visible loaded item to the top?
                    # No, that might shift Page 20 to top even if we scrolled to Page 21.

                    # Better: Calculate offset delta to minimize jump.
                    # The user is at `scroll_val`.
                    # We want the items to cover `scroll_val`.
                    # Currently they start at `result.y` (relative 0).
                    # If we use `y_offset = scroll_val`, then `item[0]` starts at `scroll_val`.
                    # This works if `item[0]` is roughly what corresponds to `scroll_val`.
                    
                    # Let's try to match the 'expected index' to the scroll position
                    # This matches the paintEvent logic that requested these pages
                    expected_idx_at_top = int(scroll_val / avg_height) # Use CURRENT avg as best guess
                    
                    # Find item in masonry list closest to this index
                    closest_item = min(self._masonry_items, key=lambda x: abs(x['index'] - expected_idx_at_top))
                    
                    if abs(closest_item['index'] - expected_idx_at_top) < 2000: # Safety: only if reasonably close
                        # Align this item to the scroll top
                        # current_absolute_y = closest_item.y + y_offset
                        # target_absolute_y = scroll_val
                        # So: closest_item.y + new_offset = scroll_val
                        # new_offset = scroll_val - closest_item.y
                        
                        proposed_offset = scroll_val - closest_item['y']
                        
                        # Only apply if it doesn't deviate INSANELY from theory (e.g. +/- 50%)
                        # This prevents breaking the scrollbar physics completely
                        if 0.5 * y_offset < proposed_offset < 1.5 * y_offset:
                            y_offset = proposed_offset
                            # print(f"[ANCHOR] Blind Jump: Aligned item {closest_item['index']} to scroll {scroll_val}")

                if first_item_idx == 0:
                     y_offset = 0

                # Shift all items to absolute y
                max_actual_y = 0
                has_first_item = False
                has_last_item = False
                for item in self._masonry_items:
                    item['y'] += y_offset
                    max_actual_y = max(max_actual_y, item['y'] + item['height'])
                    if item.get('index', -1) == 0:
                        has_first_item = True
                    if total_items > 0 and item.get('index', -1) == (total_items - 1):
                        has_last_item = True

                # CRITICAL FIX: Reconcile virtual height with actual rendered extent.
                # If the true last item is present, we can trust the rendered bottom and shrink
                # oversized virtual tails that make scrollbar position look far from bottom.
                if has_last_item:
                    self._masonry_total_height = max(max_actual_y, viewport_height + 1)
                elif max_actual_y > self._masonry_total_height:
                    self._masonry_total_height = max_actual_y
                
                # RE-ALIGN VIEW (ANCHOR OR RESCUE)
                anchor_suppressed = self._scrollbar_dragging or (time.time() < getattr(self, '_suppress_anchor_until', 0.0))
                release_anchor_active = (
                    getattr(self, '_drag_release_anchor_active', False)
                    and self._drag_release_anchor_idx is not None
                    and time.time() < getattr(self, '_drag_release_anchor_until', 0.0)
                )
                if release_anchor_active:
                    release_anchor_found = False
                    target_idx = int(self._drag_release_anchor_idx)
                    for item in self._masonry_items:
                        if item['index'] == target_idx:
                            sb = self.verticalScrollBar()
                            sb.setRange(0, max(0, self._masonry_total_height - viewport_height))
                            target_y = max(0, min(item['y'], sb.maximum()))
                            sb.setValue(target_y)
                            self._last_stable_scroll_value = target_y
                            release_anchor_found = True
                            break
                    if release_anchor_found:
                        if getattr(self, '_stick_to_edge', None) in {"top", "bottom"}:
                            self._drag_release_anchor_until = time.time() + 4.0
                        else:
                            self._drag_release_anchor_active = False
                            self._drag_release_anchor_until = 0.0
                            self._pending_edge_snap = None
                            self._pending_edge_snap_until = 0.0
                if self._pending_edge_snap == "bottom":
                    sb = self.verticalScrollBar()
                    sb.setRange(0, max(0, self._masonry_total_height - viewport_height))
                    sb.setValue(sb.maximum())
                    self._current_page = max(0, (total_items - 1) // source_model.PAGE_SIZE) if source_model else self._current_page
                elif self._pending_edge_snap == "top":
                    sb = self.verticalScrollBar()
                    sb.setRange(0, max(0, self._masonry_total_height - viewport_height))
                    sb.setValue(0)
                    self._current_page = 0
                if anchor_index != -1 and not anchor_suppressed and not release_anchor_active:
                    found_anchor = False
                    for item in self._masonry_items:
                        if item['index'] == anchor_index:
                            new_scroll_y = item['y'] - anchor_offset
                            new_scroll_y = max(0, min(new_scroll_y, self._masonry_total_height - viewport_height))
                            
                            self.verticalScrollBar().setRange(0, self._masonry_total_height - viewport_height)
                            self.verticalScrollBar().setValue(new_scroll_y)
                            found_anchor = True
                            break
                    
                    # If anchor not found, might be a drag into void - Rescue will handle it if above
                    if not found_anchor:
                        pass
                
                # RESCUE ONE-WAY (Avoid violent snap-back when scrolling down)
                min_y = self._masonry_items[0]['y']
                if (not release_anchor_active) and scroll_val + viewport_height < min_y:
                    # Viewport is stuck ABOVE the current loaded block. Snap down to start.
                    print(f"[RESCUE] Viewport {scroll_val} above block {min_y}. Snapping down.")
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(0, lambda: self.verticalScrollBar().setValue(min_y))
            
            elif not is_buffered:
                self._masonry_total_height = total_height_chunk

            # 6. ASYNC UI UPDATE
            from PySide6.QtCore import QTimer
            def apply_and_signal():
                try:
                    self._apply_layout_to_ui(timestamp)
                    self.layout_ready.emit()
                    
                    if self._recenter_after_layout:
                        self._recenter_after_layout = False
                        idx = self.currentIndex()
                        if idx.isValid():
                            # Manual scrollTo for masonry to ensure robust centering
                            # (Standard scrollTo fails with custom layout/buffered data)
                            try:
                                # Get global index
                                global_idx = idx.row()
                                if hasattr(self.model(), 'mapToSource'):
                                    src_idx = self.model().mapToSource(idx)
                                    if hasattr(source_model, 'get_global_index_for_row'):
                                        global_idx = source_model.get_global_index_for_row(src_idx.row())
                                    else:
                                        global_idx = src_idx.row()

                                # Find item rect in masonry map
                                item_rect = self._get_masonry_item_rect(global_idx)
                                
                                if not item_rect.isNull():
                                    # Scroll to center
                                    target_y = item_rect.center().y() - (self.viewport().height() // 2)
                                    target_y = max(0, min(target_y, self.verticalScrollBar().maximum()))
                                    self.verticalScrollBar().setValue(target_y)
                                else:
                                    # Fallback if item not found (e.g. not loaded yet)
                                    self.scrollTo(idx, QAbstractItemView.ScrollHint.PositionAtCenter)
                            except Exception as e:
                                print(f"[MASONRY] Manual scrollTo failed: {e}")
                                self.scrollTo(idx, QAbstractItemView.ScrollHint.PositionAtCenter)

                    # Resume enrichment
                    def resume_enrichment_delayed():
                        model_for_resume = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else self.model()
                        if model_for_resume and hasattr(model_for_resume, '_enrichment_paused'):
                            model_for_resume._enrichment_paused.clear()
                    QTimer.singleShot(200, resume_enrichment_delayed)

                except Exception as e:
                    print(f"[MASONRY] UI update crashed: {e}")
                    model_for_error = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else self.model()
                    if model_for_error and hasattr(model_for_error, '_enrichment_paused'):
                        model_for_error._enrichment_paused.clear()

            QTimer.singleShot(0, apply_and_signal)
            
            if not self._preload_complete:
                self._idle_preload_timer.start(100)

            # CRITICAL FIX: Check if a new calculation was requested while we were busy
            # This handles the case where pages loaded WHILE we were calculating spacers
            if getattr(self, '_masonry_recalc_pending', False):
                self._masonry_recalc_pending = False
                # print("[MASONRY] Triggering PENDING recalculation (pages loaded during calc)")
                QTimer.singleShot(50, self._calculate_masonry_layout)


        except Exception as e:
            print(f"[MASONRY] CRASH in completion handler: {e}")
            import traceback
            traceback.print_exc()
            self._masonry_calculating = False
            source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else self.model()
            if source_model and hasattr(source_model, '_enrichment_paused'):
                source_model._enrichment_paused.clear()

    def _map_row_to_global_index_safely(self, row: int) -> int:
        """Fallback mapping if model lacks the direct method."""
        try:
            model = self.model().sourceModel() if hasattr(self.model(), 'sourceModel') else self.model()
            if not model: return row
            
            if hasattr(model, 'get_global_index_for_row'):
                return model.get_global_index_for_row(row)
            
            # Manual fallback logic if model is busy/reset
            return row # In normal mode row == global index
        except Exception:
            return row

    def _get_masonry_item_rect(self, index):
        """Get QRect for item at given index from masonry results."""
        # Build lookup dict if not exists or stale
        if not hasattr(self, '_masonry_index_map') or self._masonry_index_map is None:
            self._rebuild_masonry_index_map()
        
        # Lookup by global index (not list position!)
        item = self._masonry_index_map.get(index)
        if item:
            width = item.get('width', 0)
            height = item.get('height', 0)
            if width > 0 and height > 0 and width < 100000 and height < 100000:
                return QRect(item['x'], item['y'], width, height)
        return QRect()
    
    def _rebuild_masonry_index_map(self):
        """Build a dict mapping global index -> item for O(1) lookup."""
        self._masonry_index_map = {}
        if self._masonry_items:
            for item in self._masonry_items:
                self._masonry_index_map[item['index']] = item


    def _get_masonry_visible_items(self, viewport_rect):
        """Get masonry items that intersect with viewport_rect."""
        if not self._masonry_items:
            return []

        viewport_top = viewport_rect.top()
        viewport_bottom = viewport_rect.bottom()

        # Linear search: masonry items are NOT sorted by Y (columns interleave Y values)
        # Binary search was incorrectly assuming sorted order
        visible = []
        for item in self._masonry_items:
            item_y = item['y']
            item_bottom = item_y + item['height']
            
            # Check if item overlaps with viewport vertically
            if item_bottom >= viewport_top and item_y <= viewport_bottom:
                item_rect = QRect(item['x'], item_y, item['width'], item['height'])
                if item_rect.intersects(viewport_rect):
                    visible.append({
                        'index': item['index'],
                        'rect': item_rect
                    })

        # DEBUG: Log when no visible items found at deep scroll
        if not visible and viewport_top > 50000:
            # Find Y range of all items
            if self._masonry_items:
                min_y = min(item['y'] for item in self._masonry_items)
                max_y = max(item['y'] + item['height'] for item in self._masonry_items)
                # print(f"[VISIBLE_DEBUG] viewport={viewport_top}-{viewport_bottom}, items Y range={min_y}-{max_y}, count={len(self._masonry_items)}")

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

        try:
            # Verify model is still valid before updating UI
            if not self.model():
                print(f"[MASONRY] Skipping UI update - model invalid")
                return
                
            # Allow empty items for buffered mode (to set scrollbar range)
            if not self._masonry_items and not (hasattr(self.model(), 'sourceModel') and 
                                              getattr(self.model().sourceModel(), '_paginated_mode', False)):
                print(f"[MASONRY] Skipping UI update - items empty (normal mode)")
                return

            # Check if buffered pagination mode
            source_model = self.model().sourceModel() if hasattr(self.model(), 'sourceModel') else self.model()
            is_buffered = source_model and hasattr(source_model, '_paginated_mode') and source_model._paginated_mode

            # Trigger UI update (EXPENSIVE - can block for 900ms)
            # In buffered mode, skip scheduleDelayedItemsLayout as it resets scrollbar to rowCount() range
            if not is_buffered:
                self.scheduleDelayedItemsLayout()
                self.viewport().update()
            else:
                # Buffered mode: Must manually update geometries to set scrollbar range
                # (Qt layout update would reset it wrongly)
                self.updateGeometries()
                # Force repaint to show new items (clears "stuck" persistence)
                self.viewport().update()

            # elapsed = (time.time() - t1) * 1000
            # print(f"[{timestamp}] ✓ UI UPDATE DONE in {elapsed:.0f}ms")
        except Exception as e:
            print(f"[MASONRY] scheduleDelayedItemsLayout crashed: {e}")
            import traceback
            traceback.print_exc()

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

        # Load visible + buffer (2 screens above/below) during scroll
        # Background preloading is paused during scroll, so this has priority
        scroll_offset = self.verticalScrollBar().value()
        viewport_height = self.viewport().height()

        # Preload items within 2 screens above and below
        preload_buffer = viewport_height * 2
        preload_rect = QRect(0, scroll_offset - preload_buffer,
                            self.viewport().width(), viewport_height + (preload_buffer * 2))

        # Get items in preload range
        items_to_preload = self._get_masonry_visible_items(preload_rect)

        # Trigger thumbnail loading (async, non-blocking)
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
        """Aggressively preload thumbnails when idle for buttery smooth scrolling."""
        if not self.use_masonry or not self.model():
            return

        source_model = self.model().sourceModel() if hasattr(self.model(), 'sourceModel') else None

        # Pagination mode: Use smart preload (visible + buffer only)
        if source_model and hasattr(source_model, '_paginated_mode') and source_model._paginated_mode:
            self._preload_pagination_pages()
            return

        # Normal mode: Preload all (< 10K images)
        if self._preload_complete:
            return

        # Pause background preloading during scroll (both modes)
        if self._scrollbar_dragging or self._mouse_scrolling:
            return

        total_items = self.model().rowCount()
        if total_items == 0:
            return

        # Show progress bar (either first run or resuming after scroll)
        if not self._thumbnail_progress_bar or not self._thumbnail_progress_bar.isVisible():
            self._show_thumbnail_progress(total_items)

        # Preload in smaller batches to avoid blocking UI
        # Smaller batch = more responsive UI, especially for videos
        batch_size = 3  # Small batches with processEvents after each item
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
                    image = self.model().sourceModel().data(
                        self.model().sourceModel().index(source_index.row(), 0),
                        Qt.ItemDataRole.UserRole
                    )
                    if image and hasattr(image, '_last_thumbnail_was_cached'):
                        if image._last_thumbnail_was_cached:
                            self._thumbnail_cache_hits.add(i)
                        else:
                            self._thumbnail_cache_misses.add(i)

                # Track this thumbnail as loaded
                self._thumbnails_loaded.add(i)
                # Process events after each thumbnail to keep UI responsive
                QApplication.processEvents()

        # Update progress to show actual loaded count
        self._preload_index = end_index
        self._update_thumbnail_progress(len(self._thumbnails_loaded), total_items)

        # Continue preloading if more items remain
        if self._preload_index < total_items:
            # Schedule next batch with minimal delay for responsiveness
            QTimer.singleShot(10, self._preload_all_thumbnails)
        else:
            # Silently complete
            self._preload_index = 0  # Reset for next time
            self._preload_complete = True  # Mark as complete
            self._hide_thumbnail_progress()

    def _on_scrollbar_pressed(self):
        """Called when user starts dragging scrollbar."""
        self._scrollbar_dragging = True
        # New drag gesture should not inherit prior edge lock.
        self._stick_to_edge = None
        self._drag_release_anchor_active = False
        self._drag_release_anchor_idx = None
        self._drag_release_anchor_until = 0.0
        self._pending_edge_snap = None
        self._pending_edge_snap_until = 0.0

        # Pause thumbnail loading in model
        source_model = self.model().sourceModel() if hasattr(self.model(), 'sourceModel') else self.model()
        if source_model:
            source_model._pause_thumbnail_loading = True

        # Large dataset strategy: show fast stable preview while dragging.
        if self.use_masonry and self._use_local_anchor_masonry(source_model):
            self._drag_preview_mode = True
            self.setUniformItemSizes(True)
            icon_w = max(16, self.iconSize().width())
            self.setGridSize(QSize(icon_w + 6, icon_w + 6))
            self.viewport().update()

        # print("[SCROLL] Scrollbar drag started - pausing ALL thumbnail loading")

    def _on_scrollbar_released(self):
        """Called when user releases scrollbar."""
        import time
        self._scrollbar_dragging = False
        self._last_stable_scroll_value = self.verticalScrollBar().value()
        sb = self.verticalScrollBar()
        source_model = self.model().sourceModel() if hasattr(self.model(), 'sourceModel') else self.model()
        release_fraction = 0.0
        max_v = sb.maximum()
        if max_v > 0:
            release_fraction = max(0.0, min(1.0, sb.value() / max_v))
        if source_model and hasattr(source_model, '_paginated_mode') and source_model._paginated_mode:
            total_items = getattr(source_model, '_total_count', 0)
            if total_items > 0:
                at_bottom_strict = max_v > 0 and sb.value() >= max_v - 2
                at_top_strict = sb.value() <= 2
                # Intent thresholds for drag preview: snap only when user is very close to edges.
                # Keep this strict so near-bottom targets (e.g. pages 17-20) remain reachable.
                bottom_intent = at_bottom_strict or (self._drag_preview_mode and release_fraction >= 0.985)
                top_intent = at_top_strict or (self._drag_preview_mode and release_fraction <= 0.015)

                if bottom_intent:
                    self._drag_release_anchor_idx = total_items - 1
                    self._stick_to_edge = "bottom"
                elif top_intent:
                    self._drag_release_anchor_idx = 0
                    self._stick_to_edge = "top"
                else:
                    self._drag_release_anchor_idx = max(0, min(total_items - 1, int(release_fraction * (total_items - 1))))
                    self._stick_to_edge = None
                self._drag_release_anchor_active = True
                self._drag_release_anchor_until = time.time() + 8.0
                if hasattr(source_model, 'PAGE_SIZE') and source_model.PAGE_SIZE > 0:
                    self._current_page = self._drag_release_anchor_idx // source_model.PAGE_SIZE
            else:
                self._drag_release_anchor_active = False
                self._drag_release_anchor_idx = None
                self._drag_release_anchor_until = 0.0

        if (max_v > 0 and sb.value() >= max_v - 2) or (self._stick_to_edge == "bottom"):
            self._pending_edge_snap = "bottom"
            self._pending_edge_snap_until = time.time() + 2.0
        elif sb.value() <= 2 or (self._stick_to_edge == "top"):
            self._pending_edge_snap = "top"
            self._pending_edge_snap_until = time.time() + 2.0
        else:
            self._pending_edge_snap = None
            self._pending_edge_snap_until = 0.0

        # Resume thumbnail loading in model
        if source_model:
            source_model._pause_thumbnail_loading = False

        if self._drag_preview_mode:
            self._drag_preview_mode = False
            self.setUniformItemSizes(False)
            self.setGridSize(QSize(-1, -1))
            # Prevent immediate anchor snap-back during the first relayout after drag release.
            self._suppress_anchor_until = time.time() + 0.8
            # Re-anchor masonry at release position.
            self._last_masonry_window_signature = None
            self._last_masonry_signal = "drag_release"
            self._check_and_load_pages()
            self._calculate_masonry_layout()

        # print("[SCROLL] Scrollbar drag ended - resuming thumbnail loading")

        # Force repaint to trigger loading of newly visible items
        self.viewport().update()

        # Trigger immediate preload of current page
        self._idle_preload_timer.stop()
        self._idle_preload_timer.start(100)  # Start preloading after 100ms

    def _preload_pagination_pages(self):
        """Smart preload: prioritize visible items, then expand outward (pagination mode)."""
        # Don't preload while user is scrolling (keeps scroll smooth)
        if self._scrollbar_dragging or self._mouse_scrolling:
            return

        source_model = self.model().sourceModel()
        if not source_model or not hasattr(source_model, 'PAGE_SIZE'):
            return

        # Initialize preload tracking if needed
        if not hasattr(self, '_pagination_preload_queue'):
            self._pagination_preload_queue = []  # Queue of indices to preload (LEGACY - for compatibility)
            self._pagination_loaded_items = set()  # Track loaded items
            # Multi-priority queues for smart preloading
            self._urgent_queue = []    # Visible items - load immediately
            self._high_queue = []      # Near buffer - load with medium priority
            self._low_queue = []       # Far buffer - load with low priority
            self._scroll_direction = None  # Track scroll direction for predictive loading

        # Build multi-priority preload queues if empty OR if we scrolled far away
        # Check if current visible area overlaps with what's already queued
        needs_rebuild = not self._urgent_queue and not self._high_queue and not self._low_queue

        if not needs_rebuild and hasattr(self, '_last_queue_center'):
            # Check if we scrolled far from last queue build (> 2 screens)
            scroll_offset = self.verticalScrollBar().value()
            viewport_height = self.viewport().height()
            current_center = scroll_offset + viewport_height // 2
            scroll_distance = abs(current_center - self._last_queue_center)
            # Rebuild if scrolled more than 2 screen heights
            needs_rebuild = scroll_distance > (viewport_height * 2)

        # ASYNC QUEUE BUILDING: Don't block main thread with expensive calculation
        # Defer queue building to next event loop iteration using QTimer
        if needs_rebuild and not hasattr(self, '_queue_building'):
            self._queue_building = True
            # Build queue asynchronously (0ms delay = next event loop)
            QTimer.singleShot(0, self._build_queues_async)
            # Continue with old queues (if any) while new ones build
            # This prevents UI freeze - better to show placeholders than freeze

        # Queues are now built asynchronously in _build_queues_async()
        # Just proceed with batch loading from existing queues

        # === PRIORITY-BASED BATCH LOADING ===
        # Determine batch sizes based on scroll state
        if self._scrollbar_dragging or self._mouse_scrolling:
            # During active scrolling: ONLY load urgent (visible) items
            # Keep batch small to avoid lock contention on main thread
            urgent_batch = 5    # Load visible items (small batches = less blocking)
            high_batch = 0      # Pause near buffer
            low_batch = 0       # Pause far buffer
        else:
            # Idle state: Larger batches (6 workers can process these quickly)
            urgent_batch = 20   # Moderate loading of visible
            high_batch = 15     # Fast loading of near buffer
            low_batch = 10      # Moderate loading of far buffer

        # Process queues in priority order
        def process_queue(queue, batch_size):
            """Load batch_size items from queue, skip already loaded."""
            loaded = 0
            while queue and loaded < batch_size:
                idx = queue.pop(0)
                if idx in self._pagination_loaded_items:
                    continue  # Already loaded, skip
                # Queue thumbnail load asynchronously
                source_model = self.model().sourceModel()
                if source_model and hasattr(source_model, 'queue_thumbnail_load'):
                    source_model.queue_thumbnail_load(idx)
                    self._pagination_loaded_items.add(idx)
                    loaded += 1
            return loaded

        # Load from each queue in priority order
        total_loaded = 0
        total_loaded += process_queue(self._urgent_queue, urgent_batch)
        total_loaded += process_queue(self._high_queue, high_batch)
        total_loaded += process_queue(self._low_queue, low_batch)

        # Update legacy queue for compatibility
        self._pagination_preload_queue = self._urgent_queue + self._high_queue + self._low_queue

        # Continue preloading if any queue has items
        if self._urgent_queue or self._high_queue or self._low_queue:
            # Adaptive cadence: slower during scroll to reduce main thread overhead
            if self._scrollbar_dragging or self._mouse_scrolling:
                cadence = 100  # 100ms during scroll (reduce overhead)
            elif self._urgent_queue:
                cadence = 30   # 30ms for urgent when idle (fast)
            elif self._high_queue:
                cadence = 50   # 50ms for high priority when idle
            else:
                cadence = 100  # 100ms for low priority
            self._idle_preload_timer.start(cadence)

        # Evict thumbnails far from current view (keep VRAM under control)
        # Only evict every 10th preload call to avoid overhead
        if not hasattr(self, '_eviction_counter'):
            self._eviction_counter = 0
        self._eviction_counter += 1

        if self._eviction_counter >= 10:
            self._eviction_counter = 0
            self._evict_distant_thumbnails()

    def _build_queues_async(self):
        """Build priority queues asynchronously (runs on next event loop to avoid blocking UI)."""
        source_model = self.model().sourceModel()
        if not source_model or not hasattr(source_model, 'PAGE_SIZE'):
            self._queue_building = False
            return

        # Get visible items
        scroll_offset = self.verticalScrollBar().value()
        viewport_height = self.viewport().height()
        viewport_rect = QRect(0, scroll_offset, self.viewport().width(), viewport_height)
        visible_items = self._get_masonry_visible_items(viewport_rect)

        if not visible_items:
            self._queue_building = False
            return

        visible_indices = [item['index'] for item in visible_items]
        min_visible = min(visible_indices)
        max_visible = max(visible_indices)
        mid_visible = (min_visible + max_visible) // 2
        visible_count = len(visible_indices)

        # Update model with visible indices for enrichment prioritization
        source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else self.model()
        if source_model and hasattr(source_model, 'set_visible_indices'):
            source_model.set_visible_indices(set(visible_indices))

        # Buffer sizes
        near_buffer_size = max(visible_count * 2, 100)
        far_buffer_size = max(visible_count * 3, 150)

        # Predictive loading based on scroll direction
        if self._scroll_direction == 'down':
            near_buffer_below = int(near_buffer_size * 1.5)
            near_buffer_above = int(near_buffer_size * 0.5)
            far_buffer_below = int(far_buffer_size * 1.5)
            far_buffer_above = int(far_buffer_size * 0.5)
        elif self._scroll_direction == 'up':
            near_buffer_below = int(near_buffer_size * 0.5)
            near_buffer_above = int(near_buffer_size * 1.5)
            far_buffer_below = int(far_buffer_size * 0.5)
            far_buffer_above = int(far_buffer_size * 1.5)
        else:
            near_buffer_below = near_buffer_above = near_buffer_size // 2
            far_buffer_below = far_buffer_above = far_buffer_size // 2

        # Clear old queues and build new ones
        self._urgent_queue = []
        self._high_queue = []
        self._low_queue = []
        visited = set()

        # ZONE 1: Urgent (visible items, center-outward)
        self._urgent_queue.append(mid_visible)
        visited.add(mid_visible)
        offset = 1
        while len(visited) < visible_count:
            if mid_visible + offset <= max_visible and mid_visible + offset not in visited:
                self._urgent_queue.append(mid_visible + offset)
                visited.add(mid_visible + offset)
            if mid_visible - offset >= min_visible and mid_visible - offset not in visited:
                self._urgent_queue.append(mid_visible - offset)
                visited.add(mid_visible - offset)
            offset += 1
            if offset > visible_count + 10:
                break

        # ZONE 2: High (near buffer)
        for i in range(max_visible + 1, min(max_visible + near_buffer_below + 1, source_model.rowCount())):
            if i not in visited:
                self._high_queue.append(i)
                visited.add(i)
        for i in range(min_visible - 1, max(0, min_visible - near_buffer_above) - 1, -1):
            if i not in visited:
                self._high_queue.append(i)
                visited.add(i)

        # ZONE 3: Low (far buffer)
        far_start_below = max_visible + near_buffer_below + 1
        for i in range(far_start_below, min(far_start_below + far_buffer_below, source_model.rowCount())):
            if i not in visited:
                self._low_queue.append(i)
                visited.add(i)
        far_start_above = min_visible - near_buffer_above - 1
        for i in range(far_start_above, max(0, far_start_above - far_buffer_above) - 1, -1):
            if i not in visited:
                self._low_queue.append(i)
                visited.add(i)

        # Update legacy queue
        self._pagination_preload_queue = self._urgent_queue + self._high_queue + self._low_queue

        # Track queue center
        self._last_queue_center = scroll_offset + viewport_height // 2

        # Mark building complete
        self._queue_building = False

        # Trigger immediate preload
        self._idle_preload_timer.stop()
        self._idle_preload_timer.start(0)

    def _evict_distant_thumbnails(self):
        """Evict thumbnails that are far from current viewport (VRAM management)."""
        source_model = self.model().sourceModel()
        if not source_model:
            return

        # Get current visible range
        scroll_offset = self.verticalScrollBar().value()
        viewport_height = self.viewport().height()
        viewport_rect = QRect(0, scroll_offset, self.viewport().width(), viewport_height)
        visible_items = self._get_masonry_visible_items(viewport_rect)

        if not visible_items:
            return

        visible_indices = set(item['index'] for item in visible_items)
        min_visible = min(visible_indices)
        max_visible = max(visible_indices)

        # Keep items within N pages of visible area (configurable for VRAM management)
        eviction_pages = settings.value('thumbnail_eviction_pages', defaultValue=3, type=int)
        eviction_pages = max(1, min(eviction_pages, 5))  # Clamp to 1-5
        keep_range_start = max(0, min_visible - source_model.PAGE_SIZE * eviction_pages)
        keep_range_end = min(max_visible + source_model.PAGE_SIZE * eviction_pages, source_model.rowCount())

        # Evict thumbnails outside keep range
        evicted_count = 0
        for i in range(len(source_model.images)):
            if i < keep_range_start or i > keep_range_end:
                image = source_model.images[i]
                if image.thumbnail or image.thumbnail_qimage:
                    image.thumbnail = None
                    image.thumbnail_qimage = None
                    evicted_count += 1
                    # Remove from loaded tracking
                    if hasattr(self, '_pagination_loaded_items'):
                        self._pagination_loaded_items.discard(i)

        if evicted_count > 0:
            print(f"[EVICT] Evicted {evicted_count} distant thumbnails (keeping indices {keep_range_start}-{keep_range_end})")

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
        previous_mode = self.viewMode()

        if self.current_thumbnail_size >= self.column_switch_threshold:
            # Large thumbnails: single column list view
            self.use_masonry = False
            self.setViewMode(QListView.ViewMode.ListMode)
            self.setFlow(QListView.Flow.TopToBottom)
            self.setResizeMode(QListView.ResizeMode.Adjust)
            self.setWrapping(False)
            self.setSpacing(0)
            self.setGridSize(QSize(-1, -1))  # Reset grid size to default

            # Re-center selected item when switching to ListMode
            if previous_mode != QListView.ViewMode.ListMode:
                QTimer.singleShot(0, lambda: self.scrollTo(
                    self.currentIndex(), QAbstractItemView.ScrollHint.PositionAtCenter))
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
            # Calculate masonry layout (will re-center via flag)
            self._recenter_after_layout = True
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
        """Recalculate masonry layout on resize (debounced)."""
        super().resizeEvent(event)
        if self.use_masonry:
            # Debounce: recalculate 50ms after last resize event
            # Fast enough to feel live, but prevents recalc on every pixel
            self._resize_timer.stop()
            self._resize_timer.start(50)

    def _on_resize_finished(self):
        """Called after resize stops (debounced)."""
        if self.use_masonry:
            print("[RESIZE] Window resize finished, recalculating masonry...")
            self._recenter_after_layout = True
            self._last_masonry_window_signature = None
            self._last_masonry_signal = "resize"
            self._calculate_masonry_layout()
            self.viewport().update()

    def viewportSizeHint(self):
        """Return the size hint for masonry layout."""
        if self.use_masonry and self._masonry_items:
            size = self._get_masonry_total_size()
            # Debug: check if Qt is using this to calculate scrollbar
            # print(f"[VIEWPORT HINT] Returning size: {size.width()}x{size.height()}")
            return size
        return super().viewportSizeHint()

    def updateGeometries(self):
        """Override to prevent Qt from resetting scrollbar in buffered pagination mode."""
        import time
        # Use stable proxy reference
        source_model = None
        if hasattr(self, 'proxy_image_list_model') and self.proxy_image_list_model:
             source_model = self.proxy_image_list_model.sourceModel()
        
        if not source_model:
             source_model = self.model().sourceModel() if hasattr(self.model(), 'sourceModel') else self.model()
             
        is_buffered = source_model and hasattr(source_model, '_paginated_mode') and source_model._paginated_mode

        # If we have a huge height calculated, assume buffered mode even if check fails transiently
        force_buffered = hasattr(self, '_masonry_total_height') and self._masonry_total_height > 50000
        
        # print(f"[TEMP_DEBUG] UpdateGeom: is_buffered={is_buffered}, force={force_buffered}, height={getattr(self, '_masonry_total_height', '?')}")

        if (is_buffered or force_buffered) and self.use_masonry:
            # Buffered mode: preserve our manually-set scrollbar range
            # Qt would reset it based on rowCount(), which is wrong for virtual pagination
            old_max = self.verticalScrollBar().maximum()
            old_value = self.verticalScrollBar().value()

            # Store the correct range before Qt messes with it
            if hasattr(self, '_masonry_total_height') and self._masonry_total_height > 0:
                viewport_height = self.viewport().height()
                correct_max = max(0, self._masonry_total_height - viewport_height)
            else:
                correct_max = old_max
            
            # print(f"[TEMP_DEBUG] UpdateGeom: CorrectMax={correct_max}, OldMax={old_max}")

            super().updateGeometries()
            new_max = self.verticalScrollBar().maximum()
            
            # print(f"[TEMP_DEBUG] UpdateGeom: AfterSuper NewMax={new_max}")

            # Always restore in buffered mode, even if Qt didn't change it
            if correct_max > 0 and new_max != correct_max:
                self.verticalScrollBar().setRange(0, correct_max)
                
                # Restore scroll position using STABLE memory
                # This fixes the "Jump to 50" bug where clamp happens before we get here
                suppress_restore = time.time() < getattr(self, '_suppress_anchor_until', 0.0)
                if getattr(self, '_stick_to_edge', None) == "bottom":
                    self.verticalScrollBar().setValue(correct_max)
                elif getattr(self, '_stick_to_edge', None) == "top":
                    self.verticalScrollBar().setValue(0)
                elif suppress_restore:
                    pass
                elif hasattr(self, '_last_stable_scroll_value') and self._last_stable_scroll_value > 0 and self._last_stable_scroll_value <= correct_max:
                     if abs(self.verticalScrollBar().value() - self._last_stable_scroll_value) > 10:
                          self.verticalScrollBar().setValue(self._last_stable_scroll_value)
                          # print(f"[UPDATEGEOM] Restored stable pos: {self._last_stable_scroll_value}")
                
                # Restore scroll position if Qt clamped it during range reduction (fallback)
                elif (not suppress_restore) and self.verticalScrollBar().value() != old_value and old_value <= correct_max:
                    # Block signals to prevent spurious scroll events during restoration
                    self.verticalScrollBar().blockSignals(True)
                    self.verticalScrollBar().setValue(old_value)
                    self.verticalScrollBar().blockSignals(False)

            # Enforce explicit edge lock even when range didn't change.
            if getattr(self, '_stick_to_edge', None) == "bottom":
                self.verticalScrollBar().setValue(max(0, correct_max))
            elif getattr(self, '_stick_to_edge', None) == "top":
                self.verticalScrollBar().setValue(0)
        else:
            # Normal mode: let Qt manage scrollbar
            super().updateGeometries()

    def visualRect(self, index):
        """Return the visual rectangle for an index, using masonry positions."""
        if self.use_masonry and self._drag_preview_mode:
            return super().visualRect(index)
        if self.use_masonry and self._masonry_items and index.isValid():
            # In masonry mode, we map rows to global indices
            global_idx = index.row()
            if hasattr(self.model(), 'sourceModel'):
                source_model = self.model().sourceModel()
                if hasattr(source_model, 'get_global_index_for_row'):
                    global_idx = source_model.get_global_index_for_row(index.row())
                elif getattr(source_model, '_paginated_mode', False):
                    # Fallback mapping for paginated mode
                    global_idx = self._map_row_to_global_index_safely(index.row())

            # Get masonry position (absolute coordinates)
            rect = self._get_masonry_item_rect(global_idx)
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
        if self.use_masonry and self._drag_preview_mode:
            return super().indexAt(point)
        if self.use_masonry and self._masonry_items:
            # Adjust point for scroll offset
            scroll_offset = self.verticalScrollBar().value()
            adjusted_point = QPoint(point.x(), point.y() + scroll_offset)

            source_model = self.model().sourceModel() if hasattr(self.model(), 'sourceModel') else self.model()
            
            # Use the optimized map for fast lookup
            if not hasattr(self, '_masonry_index_map') or self._masonry_index_map is None:
                self._rebuild_masonry_index_map()
            
            # Linear search in the map rects (could be optimized with spatial index if 32k+)
            for global_idx, item in self._masonry_index_map.items():
                item_rect = QRect(item['x'], item['y'], item['width'], item['height'])
                if item_rect.contains(adjusted_point):
                    # Map global index to row
                    if hasattr(source_model, 'get_loaded_row_for_global_index'):
                         row = source_model.get_loaded_row_for_global_index(global_idx)
                    else:
                         row = global_idx
                         
                    if row != -1:
                        return self.model().index(row, 0)
            
            return QModelIndex()
        else:
            return super().indexAt(point)

    def mousePressEvent(self, event):
        """Override mouse press to fix selection in masonry mode."""
        # DIAGNOSTIC LOG (Requested by user for deep page debugging)
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        pos = event.pos()
        val = self.verticalScrollBar().value()
        row_idx = -1
        
        # Identify what was clicked
        index = self.indexAt(pos)
        if index.isValid():
            row_idx = index.row()
            
        source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else self.model()
        page_size = source_model.PAGE_SIZE if hasattr(source_model, 'PAGE_SIZE') else 1000
        page_num = row_idx // page_size if row_idx >= 0 else -1
        
        # Check if index is in current masonry layout
        in_layout = any(item['index'] == row_idx for item in self._masonry_items) if hasattr(self, '_masonry_items') else False
        layout_count = len(self._masonry_items) if hasattr(self, '_masonry_items') else 0
        


        source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else None
        
        # Pause enrichment during interaction to prevent crashes
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
        # Double-click opens image in default app
        index = self.indexAt(event.pos())
        if index.isValid():
            # Get the image at this index
            image = index.data(Qt.ItemDataRole.UserRole)
            if image:
                # Visual feedback: flash the thumbnail
                self._flash_thumbnail(index)
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(image.path)))
                event.accept()
                return

        # Default behavior for other double-clicks
        super().mouseDoubleClickEvent(event)

    def _flash_thumbnail(self, index):
        """Create a quick flash and scale effect on thumbnail before opening."""
        from PySide6.QtCore import QPropertyAnimation, QEasingCurve, QRect, QParallelAnimationGroup
        from PySide6.QtWidgets import QGraphicsOpacityEffect

        # Get the viewport rect for this index
        rect = self.visualRect(index)

        # Create a temporary white overlay widget
        overlay = QWidget(self.viewport())
        overlay.setGeometry(rect)
        overlay.setStyleSheet("background-color: rgba(255, 255, 255, 180); border-radius: 4px;")
        overlay.show()

        # Opacity effect for fade
        opacity_effect = QGraphicsOpacityEffect(overlay)
        overlay.setGraphicsEffect(opacity_effect)

        # Create animation group for parallel animations
        animation_group = QParallelAnimationGroup(self)

        # Fade out animation
        fade_animation = QPropertyAnimation(opacity_effect, b"opacity")
        fade_animation.setDuration(250)
        fade_animation.setStartValue(1.0)
        fade_animation.setEndValue(0.0)
        fade_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Scale animation (grow slightly then shrink back)
        scale_animation = QPropertyAnimation(overlay, b"geometry")
        scale_animation.setDuration(250)

        # Calculate scaled rect (10% larger)
        center = rect.center()
        scaled_width = int(rect.width() * 1.1)
        scaled_height = int(rect.height() * 1.1)
        scaled_rect = QRect(
            center.x() - scaled_width // 2,
            center.y() - scaled_height // 2,
            scaled_width,
            scaled_height
        )

        scale_animation.setStartValue(rect)
        scale_animation.setKeyValueAt(0.4, scaled_rect)  # Peak at 40%
        scale_animation.setEndValue(rect)  # Back to original
        scale_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Add both animations to group
        animation_group.addAnimation(fade_animation)
        animation_group.addAnimation(scale_animation)

        # Clean up overlay when done
        animation_group.finished.connect(overlay.deleteLater)
        animation_group.start()

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

    def keyPressEvent(self, event):
        """Handle keyboard events in the image list."""
        is_home_end = event.key() in (Qt.Key.Key_Home, Qt.Key.Key_End)
        if is_home_end:
            # If user explicitly navigates to edges via keyboard, drop any drag-anchor locks
            # so default Home/End refocus + scroll behavior is not overridden by sticky state.
            self._stick_to_edge = None
            self._pending_edge_snap = None
            self._pending_edge_snap_until = 0.0
            self._scrollbar_dragging = False
            self._drag_preview_mode = False
            self._drag_release_anchor_active = False
            self._drag_release_anchor_idx = None
            self._drag_release_anchor_until = 0.0

            source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else self.model()
            is_paginated = bool(source_model and getattr(source_model, '_paginated_mode', False))
            if is_paginated and hasattr(source_model, '_total_count') and source_model._total_count > 0:
                total_items = int(source_model._total_count)
                page_size = int(getattr(source_model, 'PAGE_SIZE', 1000))
                target_global_idx = 0 if event.key() == Qt.Key.Key_Home else (total_items - 1)
                target_edge = "top" if event.key() == Qt.Key.Key_Home else "bottom"

                # Prime page loading around the requested edge so row mapping can succeed quickly.
                target_page = target_global_idx // page_size
                range_start = max(0, (target_page - 1) * page_size)
                range_end = min(total_items - 1, ((target_page + 1) * page_size) - 1)
                if hasattr(source_model, 'ensure_pages_for_range'):
                    source_model.ensure_pages_for_range(range_start, range_end)

                def _focus_target(attempt=0):
                    row = -1
                    if hasattr(source_model, 'get_loaded_row_for_global_index'):
                        row = source_model.get_loaded_row_for_global_index(target_global_idx)

                    if row >= 0 and self.model():
                        idx = self.model().index(row, 0)
                        if idx.isValid():
                            self.setCurrentIndex(idx)
                            self._stick_to_edge = target_edge
                            sb = self.verticalScrollBar()
                            if target_edge == "top":
                                sb.setValue(0)
                            else:
                                sb.setValue(sb.maximum())
                            self.viewport().update()
                            return

                    if attempt < 20:
                        QTimer.singleShot(50, lambda: _focus_target(attempt + 1))

                QTimer.singleShot(0, _focus_target)
                event.accept()
                return

        if event.key() == Qt.Key.Key_Delete:
            # Toggle deletion marking for selected images
            selected_indices = self.selectedIndexes()
            if selected_indices:
                # Walk up the parent chain to find ImageList
                parent = self.parent()
                if parent:
                    parent = parent.parent()
                try:
                    parent.toggle_deletion_marking()
                    event.accept()
                    return
                except Exception as e:
                    print(f"[ERROR] Failed to toggle deletion marking: {e}")

        # Default behavior for other keys
        super().keyPressEvent(event)

        # In local-anchor masonry, default Qt Home/End may update selection without moving
        # viewport because the selected row can be outside current masonry window.
        # Force an explicit edge jump so list refocus always matches viewer/index.
        if is_home_end:
            go_home = event.key() == Qt.Key.Key_Home
            def _force_edge_refocus():
                sb = self.verticalScrollBar()
                if go_home:
                    self._stick_to_edge = "top"
                    sb.setValue(0)
                else:
                    self._stick_to_edge = "bottom"
                    sb.setValue(sb.maximum())
                self.viewport().update()

            QTimer.singleShot(0, _force_edge_refocus)

    def wheelEvent(self, event):
        """Handle Ctrl+scroll for zooming thumbnails."""
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

                # If masonry, recalculate layout and re-center after zoom stops
                if self.use_masonry:
                    # Debounce: recalculate and re-center after user stops zooming
                    self._resize_timer.stop()
                    self._resize_timer.start(300)

                # Save to settings
                settings.setValue('image_list_thumbnail_size', self.current_thumbnail_size)

            event.accept()
            return

        # Mark as mouse scrolling and restart timer (for pagination preloading)
        if not self._mouse_scrolling:
            self._mouse_scrolling = True
            # print("[SCROLL] Mouse scroll started - pausing background preloading")

        # Reset timer - will fire 150ms after last scroll event
        self._mouse_scroll_timer.stop()
        self._mouse_scroll_timer.start(150)  # Shorter delay for faster resume

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

    def _on_mouse_scroll_stopped(self):
        """Called when mouse scrolling stops (200ms after last wheel event)."""
        self._mouse_scrolling = False
        # print("[SCROLL] Mouse scroll stopped")

        # DON'T flush cache saves immediately - still might be scrolling
        # Just mark that scroll detection stopped (200ms is too short for flush)

        # DON'T clear queues - rebuilding is expensive and causes freeze
        # Just let the preload continue from where it left off
        # Queues will self-correct as items get loaded

        # Trigger preload immediately (no delay)
        self._idle_preload_timer.stop()
        self._idle_preload_timer.start(0)  # Immediate start - no delay

        # DON'T force repaint - let Qt do it naturally to avoid blocking during disk I/O
        # self.viewport().update()

        # Start cache flush timer (2 seconds = truly idle)
        self._cache_flush_timer.stop()
        self._cache_flush_timer.start(2000)  # 2 seconds idle before flush

        # DISABLED: Cache warming causes UI blocking
        # self._cache_warm_idle_timer.stop()
        # self._cache_warm_idle_timer.start(5000)  # 5 seconds idle

    def scrollContentsBy(self, dx, dy):
        """Handle scrolling and update viewport."""
        super().scrollContentsBy(dx, dy)

        # Notify model that scrolling started (defer cache writes)
        source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else None
        if source_model and hasattr(source_model, 'set_scrolling_state'):
            source_model.set_scrolling_state(True)

        # Cancel cache flush and warming timers when scrolling starts
        self._cache_flush_timer.stop()
        # DISABLED: Cache warming causes UI blocking
        # self._cache_warm_idle_timer.stop()
        # self._stop_cache_warming()

        # Track scroll direction for predictive preloading
        if dy != 0:
            self._scroll_direction = 'down' if dy < 0 else 'up'

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
        """Update current page tracking and trigger page loading based on scroll position."""
        source_model = self.model().sourceModel() if hasattr(self.model(), 'sourceModel') else self.model()

        # Only for pagination mode
        if not source_model or not hasattr(source_model, '_paginated_mode') or not source_model._paginated_mode:
            return

        if not hasattr(source_model, '_total_count') or source_model._total_count == 0:
            return

        # Throttle: Don't spam page loads on every pixel of scroll
        import time
        current_time = time.time()
        if not hasattr(self, '_last_page_check_time'):
            self._last_page_check_time = 0
        if current_time - self._last_page_check_time < 0.1:  # 100ms throttle
            return
        self._last_page_check_time = current_time

        scroll_offset = self.verticalScrollBar().value()
        scroll_max = self.verticalScrollBar().maximum()
        # print(f"[LOAD_CHECK] Offset={scroll_offset}, Max={scroll_max}, Page={self._current_page if hasattr(self, '_current_page') else '?'}, Total={source_model._total_count if hasattr(source_model, '_total_count') else '?'}")

        if scroll_max <= 0:
            # Can't determine position yet
            return

        total_pages = (source_model._total_count + source_model.PAGE_SIZE - 1) // source_model.PAGE_SIZE
        last_page = max(0, total_pages - 1)
        edge_snap_active = self._pending_edge_snap is not None and current_time < getattr(self, '_pending_edge_snap_until', 0.0)
        anchor_active = (
            getattr(self, '_drag_release_anchor_active', False)
            and self._drag_release_anchor_idx is not None
            and current_time < getattr(self, '_drag_release_anchor_until', 0.0)
        )
        stick_bottom = getattr(self, '_stick_to_edge', None) == "bottom"
        stick_top = getattr(self, '_stick_to_edge', None) == "top"
        if not anchor_active and getattr(self, '_drag_release_anchor_active', False):
            self._drag_release_anchor_active = False
            self._drag_release_anchor_idx = None
            self._drag_release_anchor_until = 0.0

        # Prefer visible global indices (stable), fallback to scrollbar fraction.
        # During drag/preview, masonry visibility can be stale (old window), so use scrollbar mapping directly.
        dragging_mode = self._scrollbar_dragging or self._drag_preview_mode
        current_page = None
        if stick_top:
            current_page = 0
            if scroll_offset > 0:
                self.verticalScrollBar().setValue(0)
                scroll_offset = 0
        elif stick_bottom:
            current_page = last_page
            if scroll_max > 0 and scroll_offset < scroll_max:
                self.verticalScrollBar().setValue(scroll_max)
                scroll_offset = scroll_max
        elif anchor_active:
            current_page = max(0, min(last_page, int(self._drag_release_anchor_idx // source_model.PAGE_SIZE)))
        elif edge_snap_active and self._pending_edge_snap == "top":
            current_page = 0
            if scroll_offset > 0:
                self.verticalScrollBar().setValue(0)
                scroll_offset = 0
        elif edge_snap_active and self._pending_edge_snap == "bottom":
            current_page = last_page
            if scroll_max > 0 and scroll_offset < scroll_max:
                self.verticalScrollBar().setValue(scroll_max)
                scroll_offset = scroll_max
        if current_page is None and (not dragging_mode) and self.use_masonry and self._masonry_items:
            viewport_h = self.viewport().height()
            viewport_rect = QRect(0, scroll_offset, self.viewport().width(), viewport_h)
            visible_items = self._get_masonry_visible_items(viewport_rect)
            real_items = [it for it in visible_items if it.get('index', -1) >= 0]
            if real_items:
                top_idx = min(real_items, key=lambda x: x['rect'].y())['index']
                current_page = max(0, min(last_page, top_idx // source_model.PAGE_SIZE))

        # Edge clamp must win at top/bottom to avoid regressions after jump/release.
        if scroll_offset <= 2:
            current_page = 0
            if not edge_snap_active:
                self._pending_edge_snap = None
                self._pending_edge_snap_until = 0.0
        elif scroll_max > 0 and scroll_offset >= scroll_max - 2:
            current_page = last_page
            if not edge_snap_active:
                self._pending_edge_snap = None
                self._pending_edge_snap_until = 0.0

        if self._pending_edge_snap is not None and not edge_snap_active:
            self._pending_edge_snap = None
            self._pending_edge_snap_until = 0.0

        if current_page is None:
            # NAVIGATION FIX: Use internal height estimate if scrollbar is collapsed
            # This prevents jumping to "Page 1000" if scrollbar logic momentarily lags
            virtual_max = scroll_max
            if (not dragging_mode) and hasattr(self, '_masonry_total_height') and self._masonry_total_height > scroll_max:
                 virtual_max = self._masonry_total_height

            if scroll_offset <= 2:
                current_page = 0
            elif scroll_max > 0 and scroll_offset >= scroll_max - 2:
                current_page = last_page
            else:
                scroll_fraction = scroll_offset / virtual_max if virtual_max > 0 else 0
                estimated_item_idx = int(scroll_fraction * source_model._total_count)
                current_page = estimated_item_idx // source_model.PAGE_SIZE
                current_page = max(0, min(last_page, current_page))
        self._current_page = current_page

        # Load current page + a small local buffer for responsive pagination.
        try:
            buffer_pages = int(settings.value('thumbnail_eviction_pages', 3, type=int))
        except Exception:
            buffer_pages = 3
        buffer_pages = max(1, min(buffer_pages, 6))
        start_page = max(0, current_page - buffer_pages)
        end_page = min((source_model._total_count + source_model.PAGE_SIZE - 1) // source_model.PAGE_SIZE - 1,
                       current_page + buffer_pages)

        # Trigger page loads for this range using DEBOUNCER
        if hasattr(source_model, 'ensure_pages_for_range'):
            start_row = start_page * source_model.PAGE_SIZE
            end_row = (end_page + 1) * source_model.PAGE_SIZE
            source_model.ensure_pages_for_range(start_row, end_row)
        else:
            # Fallback for old model versions
            for page_num in range(start_page, end_page + 1):
                if page_num not in source_model._pages and page_num not in source_model._loading_pages:
                    source_model._request_page_load(page_num)

    def paintEvent(self, event):
        """Override paint to handle masonry layout rendering."""
        if self.use_masonry and self._drag_preview_mode:
            super().paintEvent(event)
            return
        # THROTTLE painting during active scrolling to prevent UI blocking
        # Skip paint if we painted too recently (< 16ms ago = faster than 60fps)
        if self.use_masonry:
            import time
            current_time = time.time()
            if not hasattr(self, '_last_paint_time'):
                self._last_paint_time = 0

            # During scrolling, throttle to max 30fps (33ms between paints)
            # This prevents overwhelming the GPU with too many repaints
            if self._scrollbar_dragging or self._mouse_scrolling:
                time_since_paint = (current_time - self._last_paint_time) * 1000
                if time_since_paint < 33:  # 33ms = 30fps
                    event.accept()
                    return  # Skip this paint, too soon

            self._last_paint_time = current_time

        if self.use_masonry and self._masonry_items and self.model():
            # Set flag to prevent layout changes during paint (prevents re-entrancy crash)
            self._painting = True
            try:
                import time
                paint_start = time.time()

                # Safety check: ensure model is valid
                if not self.model() or self.model().rowCount() == 0:
                    super().paintEvent(event)
                    return

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

                # Keep page loading aligned with what is actually visible.
                # Paint-time fallback exists only for blind-spot recovery during drag jumps.
                source_model = self.model().sourceModel() if hasattr(self.model(), 'sourceModel') else self.model()
                if source_model and hasattr(source_model, '_paginated_mode') and source_model._paginated_mode:

                    total_items = source_model._total_count if hasattr(source_model, '_total_count') else 0
                    page_size = source_model.PAGE_SIZE if hasattr(source_model, 'PAGE_SIZE') else 1000

                    real_visible = [it for it in visible_items if it.get('index', -1) >= 0]
                    req_start = None
                    req_end = None

                    if real_visible:
                        real_visible.sort(key=lambda x: x['index'])
                        req_start = max(0, int(real_visible[0]['index']))
                        req_end = min(total_items - 1, int(real_visible[-1]['index']))
                    elif total_items > 0 and self._scrollbar_dragging:
                        # Blind spot while dragging: estimate by scrollbar fraction to recover quickly.
                        scroll_max = self.verticalScrollBar().maximum()
                        if scroll_max > 0:
                            scroll_fraction = max(0.0, min(1.0, scroll_offset / scroll_max))
                            est_idx = int(scroll_fraction * (total_items - 1))
                        else:
                            est_idx = 0
                        est_span = max(page_size, viewport_height // 32)
                        req_start = max(0, est_idx - (est_span // 2))
                        req_end = min(total_items - 1, est_idx + (est_span // 2))

                    if req_start is not None and req_end is not None:
                        if self._scrollbar_dragging and page_size > 0:
                            self._current_page = max(0, min((total_items - 1) // page_size, req_start // page_size))
                        if hasattr(source_model, 'ensure_pages_for_range'):
                            source_model.ensure_pages_for_range(req_start, req_end)

                    # If nothing is visible after a jump, force-load around current page immediately.
                    if not visible_items and total_items > 0 and page_size > 0:
                        cur_page = max(0, min((total_items - 1) // page_size, int(getattr(self, '_current_page', 0))))
                        force_start = max(0, (cur_page - 1) * page_size)
                        force_end = min(total_items - 1, (cur_page + 2) * page_size - 1)
                        if hasattr(source_model, 'ensure_pages_for_range'):
                            source_model.ensure_pages_for_range(force_start, force_end)

                # Auto-correct scroll bounds if needed
                max_allowed = self._get_masonry_total_height() - viewport_height
                if scroll_offset > max_allowed and max_allowed > 0:
                    self.verticalScrollBar().setMaximum(max_allowed)
                    self.verticalScrollBar().setValue(max_allowed)

                items_painted = 0
                # Paint only visible items
                # Paint only visible items
                source_model = self.model().sourceModel() if hasattr(self.model(), 'sourceModel') else self.model()
                is_buffered = source_model and hasattr(source_model, '_paginated_mode') and source_model._paginated_mode

                # DEBUG: Track items that fail mapping
                skipped_count = 0
                first_skipped = []
                painted_count = 0
                
                # Check if filtering is active
                is_filtered = hasattr(self.model(), 'filter') and self.model().filter is not None

                if not visible_items and is_buffered:
                    painter.setPen(Qt.GlobalColor.lightGray)
                    painter.drawText(self.viewport().rect(), Qt.AlignmentFlag.AlignCenter, "Loading target window...")
                for item in visible_items:
                    # Draw spacers (negative index)
                    if item['index'] < 0:
                        # Spacer tokens keep Y continuity for windowed masonry.
                        # Avoid painting a full opaque block; it can appear as a giant gray square.
                        continue

                    # Construct valid index for painting
                    # ALWAYS map global index to loaded row in masonry mode
                    if hasattr(source_model, 'get_loaded_row_for_global_index'):
                        src_row = source_model.get_loaded_row_for_global_index(item['index'])
                    else:
                        src_row = item['index']
                        
                    if src_row == -1:
                        # Not loaded or belongs to a different view state
                        skipped_count += 1
                        continue
                        
                        
                    src_index = source_model.index(src_row, 0)
                    index = self.model().mapFromSource(src_index)

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
                        
                    # SMART FAST SCROLL: Always show loaded thumbnails
                    # Only skip delegate for items that aren't loaded yet
                    has_thumbnail = False
                    if is_buffered and not is_filtered:
                         # Unfiltered buffered mode: use global index
                         image = source_model._get_image_at_index(item['index'])
                         if image:
                             has_thumbnail = bool(image.thumbnail or image.thumbnail_qimage)
                    else:
                         # Normal mode or filtered mode: get via proxy index
                         image = self.model().data(index, Qt.ItemDataRole.UserRole)
                         if image:
                             has_thumbnail = bool(getattr(image, 'thumbnail', None) or getattr(image, 'thumbnail_qimage', None))

                    # Create option for delegate using QStyleOptionViewItem
                    option = QStyleOptionViewItem()
                    option.rect = visual_rect
                    option.decorationSize = QSize(item['rect'].width(), item['rect'].height())
                    option.decorationAlignment = Qt.AlignCenter
                    option.palette = self.palette()  # Set palette for stamp drawing

                    # Set state flags
                    is_selected = self.selectionModel() and self.selectionModel().isSelected(index)
                    is_current = self.currentIndex() == index

                    # DEBUG: Report skipped items (only at deep scroll to avoid spam)
                    # if skipped_count > 0 and scroll_offset > 50000:
                    #    pass
                    # print(f"[PAINT_DEBUG] scroll={scroll_offset}, visible={len(visible_items)}, painted={items_painted}, skipped={skipped_count}, first_skipped={first_skipped}")

                    # Debug: log selection state for visible items
                    # if is_selected or is_current:
                    #     print(f"[DEBUG] Painting row={item.index}, is_selected={is_selected}, is_current={is_current}")

                    if is_selected:
                        option.state |= QStyle.StateFlag.State_Selected
                    if is_current:
                        option.state |= QStyle.StateFlag.State_HasFocus



                    # ALWAYS paint using delegate (it handles placeholders now)
                    # Fast scroll optimization removed because it prevented placeholders from showing
                    self.itemDelegate().paint(painter, option, index)

                    # Draw selection border on top
                    if is_selected or is_current:
                        painter.save()
                        pen = QPen(QColor(0, 120, 215), 4 if is_current else 2)
                        painter.setPen(pen)
                        painter.setBrush(Qt.BrushStyle.NoBrush)
                        painter.drawRect(visual_rect.adjusted(2, 2, -2, -2))
                        painter.restore()
                    
                    # (Fast scroll optimization block removed)
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
            finally:
                # Clear painting flag to allow layout changes again
                self._painting = False
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

        # CRITICAL: Clear stale masonry data so new folder doesn't show old images
        self._masonry_items = []
        self._masonry_total_height = 0
        self._current_page = 0
        self._last_stable_scroll_value = 0
        
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

        # Calculate the index to focus after deletion
        # Get all selected indices and find the maximum (last in sort order)
        selected_indices = sorted([idx.row() for idx in self.selectedIndexes()])
        if selected_indices:
            max_selected_row = selected_indices[-1]
            total_rows = self.proxy_image_list_model.rowCount()
            # Set next index: use the row after the last deleted one, or the one before if it's the last
            next_index = max_selected_row + 1 - len(selected_indices)
            if next_index >= total_rows - len(selected_indices):
                # If we're deleting at the end, focus on the image before the first deleted one
                next_index = max(0, selected_indices[0] - 1)
            # Store in main window for use after reload
            main_window = self.parent().parent().parent()
            main_window.post_deletion_index = next_index

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
        source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else self.model()
        if not source_model or not hasattr(source_model, '_paginated_mode') or not source_model._paginated_mode:
            return

        total_items = source_model._total_count if hasattr(source_model, '_total_count') else source_model.rowCount()
        if total_items <= 0:
            return

        current_page = getattr(self, '_current_page', 0)
        if getattr(self, '_stick_to_edge', None) == "top":
            current_page = 0
        elif getattr(self, '_stick_to_edge', None) == "bottom":
            current_page = max(0, (total_items - 1) // source_model.PAGE_SIZE)
        elif (
            getattr(self, '_drag_release_anchor_active', False)
            and self._drag_release_anchor_idx is not None
            and time.time() < getattr(self, '_drag_release_anchor_until', 0.0)
        ):
            current_page = max(0, min((total_items - 1) // source_model.PAGE_SIZE, self._drag_release_anchor_idx // source_model.PAGE_SIZE))
        if self.use_masonry:
            # In masonry mode, selection can be stale after drag-jumps.
            # Prefer viewport-visible items for page indicator.
            scroll_offset = self.verticalScrollBar().value()
            viewport_rect = self.viewport().rect().translated(0, scroll_offset)
            visible_items = self._get_masonry_visible_items(viewport_rect)
            real_items = [it for it in visible_items if it.get('index', -1) >= 0]
            if real_items and getattr(self, '_stick_to_edge', None) is None and not (
                getattr(self, '_drag_release_anchor_active', False)
                and self._drag_release_anchor_idx is not None
                and time.time() < getattr(self, '_drag_release_anchor_until', 0.0)
            ):
                mid_idx = real_items[len(real_items) // 2]['index']
                current_page = max(0, min((total_items - 1) // source_model.PAGE_SIZE, mid_idx // source_model.PAGE_SIZE))
        else:
            # Non-masonry mode: selection-based indicator is intuitive.
            current_idx = self.currentIndex()
            if current_idx.isValid():
                try:
                    global_idx = current_idx.row()
                    if hasattr(self.model(), 'mapToSource'):
                        src_idx = self.model().mapToSource(current_idx)
                        if src_idx.isValid() and hasattr(source_model, 'get_global_index_for_row'):
                            mapped = source_model.get_global_index_for_row(src_idx.row())
                            if mapped >= 0:
                                global_idx = mapped
                    current_page = max(0, min((total_items - 1) // source_model.PAGE_SIZE, global_idx // source_model.PAGE_SIZE))
                except Exception:
                    pass

        # Use _total_count for buffered mode (rowCount only returns loaded items)
        total_pages = (total_items + source_model.PAGE_SIZE - 1) // source_model.PAGE_SIZE
        total_pages = max(1, total_pages)

        # During scrollbar drag, represent current target page from slider position.
        # Selection often remains on an old item and is misleading in this mode.
        if self._scrollbar_dragging or self._drag_preview_mode:
            scroll_max = self.verticalScrollBar().maximum()
            scroll_val = self.verticalScrollBar().value()
            if scroll_max > 0:
                fraction = max(0.0, min(1.0, scroll_val / scroll_max))
            else:
                fraction = 0.0
            current_page = int(fraction * (total_pages - 1))
            current_page = max(0, min(total_pages - 1, current_page))

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

    # DISABLED: Cache warming causes UI blocking
    # def _start_cache_warming(self):
    #     """Start background cache warming after idle period."""
    #     source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else None
    #     if not source_model or not hasattr(source_model, '_paginated_mode') or not source_model._paginated_mode:
    #         return
    #
    #     # Don't start cache warming while enrichment is running (causes UI blocking)
    #     # Check if any images still need enrichment (have placeholder dimensions)
    #     if hasattr(source_model, 'images') and source_model.images:
    #         needs_enrichment = any(img.dimensions == (512, 512) for img in source_model.images[:100])  # Sample first 100
    #         if needs_enrichment:
    #             print("[CACHE WARM] Skipping - enrichment still in progress")
    #             # Retry in 5 seconds
    #             self._cache_warm_idle_timer.start(5000)
    #             return
    #
    #     # Default to 'down' if never scrolled
    #     if not hasattr(self, '_scroll_direction') or self._scroll_direction is None:
    #         self._scroll_direction = 'down'
    #         print(f"[CACHE WARM] Starting without prior scroll, defaulting to 'down'")
    #
    #     # Get visible items to determine where to start warming
    #     viewport_rect = self.viewport().rect()
    #     visible_items = self._get_masonry_visible_items(viewport_rect)
    #     if not visible_items:
    #         return
    #
    #     # Calculate start index based on scroll direction
    #     if self._scroll_direction == 'down':
    #         # Warm cache ahead (below visible area)
    #         start_idx = max(item['index'] for item in visible_items) + 1
    #     else:
    #         # Warm cache above visible area
    #         start_idx = min(item['index'] for item in visible_items) - 500
    #         start_idx = max(0, start_idx)
    #
    #     # Start cache warming in the model
    #     if hasattr(source_model, 'start_cache_warming'):
    #         source_model.start_cache_warming(start_idx, self._scroll_direction)

    # DISABLED: Cache warming causes UI blocking
    # def _stop_cache_warming(self):
    #     """Stop background cache warming immediately."""
    #     source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else None
    #     if source_model and hasattr(source_model, 'stop_cache_warming'):
    #         source_model.stop_cache_warming()

    def _flush_cache_saves(self):
        """Flush pending cache saves after truly idle (2+ seconds)."""
        source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else None
        if source_model and hasattr(source_model, 'set_scrolling_state'):
            # Tell model scrolling stopped and flush pending saves
            source_model.set_scrolling_state(False)

    # Cache status removed - now shown in main window status bar


class ImageList(QDockWidget):
    deletion_marking_changed = Signal()
    directory_reload_requested = Signal()

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

        # Status bar with image index (left) and cache status (right) on same line
        self.image_index_label = QLabel()
        self.cache_status_label = QLabel()
        status_layout = QHBoxLayout()
        status_layout.setContentsMargins(5, 2, 5, 2)
        status_layout.addWidget(self.image_index_label)
        status_layout.addStretch()  # Push cache label to the right
        status_layout.addWidget(self.cache_status_label)

        # A container widget is required to use a layout with a `QDockWidget`.
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)  # Remove margins
        layout.setSpacing(0)  # Remove spacing between widgets
        layout.addWidget(self.filter_line_edit)
        layout.addLayout(selection_sort_layout)
        layout.addWidget(self.list_view)
        layout.addLayout(status_layout)
        self.setWidget(container)

        self.selection_mode_combo_box.currentTextChanged.connect(
            self.set_selection_mode)
        self.set_selection_mode(self.selection_mode_combo_box.currentText())

        # Connect sort signal
        self.sort_combo_box.currentTextChanged.connect(self._on_sort_changed)

        # DISABLED: Cache warming causes UI blocking
        # Connect cache warming signal to update cache status label
        # source_model = proxy_image_list_model.sourceModel()
        # if hasattr(source_model, 'cache_warm_progress'):
        #     source_model.cache_warm_progress.connect(self._update_cache_status)
        #     # Trigger initial update
        #     QTimer.singleShot(1000, lambda: self._update_cache_status(0, 0))

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
        source_model = self.proxy_image_list_model.sourceModel()

        # In buffered pagination mode, use _total_count instead of rowCount
        if source_model and hasattr(source_model, '_paginated_mode') and source_model._paginated_mode:
            unfiltered_image_count = source_model._total_count if hasattr(source_model, '_total_count') else source_model.rowCount()
        else:
            unfiltered_image_count = source_model.rowCount()

        current_pos = proxy_image_index.row() + 1
        if source_model and hasattr(source_model, '_paginated_mode') and source_model._paginated_mode:
            try:
                src_index = self.proxy_image_list_model.mapToSource(proxy_image_index)
                if src_index.isValid() and hasattr(source_model, 'get_global_index_for_row'):
                    global_idx = source_model.get_global_index_for_row(src_index.row())
                    if global_idx >= 0:
                        current_pos = global_idx + 1
            except Exception:
                pass

        # In buffered mode, denominator should reflect total filtered dataset size, not loaded rowCount.
        denom = image_count
        if source_model and hasattr(source_model, '_paginated_mode') and source_model._paginated_mode:
            denom = unfiltered_image_count

        label_text = f'Image {current_pos} / {denom}'
        if image_count != unfiltered_image_count:
            label_text += f' ({unfiltered_image_count} total)'
        self.image_index_label.setText(label_text)

    # DISABLED: Cache warming causes UI blocking
    # def _update_cache_status(self, progress: int, total: int):
    #     """Update cache status label (right side of status bar)."""
    #     source_model = self.proxy_image_list_model.sourceModel()
    #     if total == 0:
    #         # No warming active, show real cache stats
    #         if hasattr(source_model, 'get_cache_stats'):
    #             cached, total_images = source_model.get_cache_stats()
    #             if total_images > 0:
    #                 percent = int((cached / total_images) * 100)
    #                 self.cache_status_label.setText(f"💾 Cache: {cached:,} / {total_images:,} ({percent}%)")
    #             else:
    #                 self.cache_status_label.setText("")
    #         else:
    #             self.cache_status_label.setText("")
    #     else:
    #         # Warming active, show progress
    #         percent = int((progress / total) * 100) if total > 0 else 0
    #         self.cache_status_label.setText(f"🔥 Building cache: {progress:,} / {total:,} ({percent}%)")

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
            # Get currently selected image BEFORE sorting (to scroll to it after)
            current_index = self.list_view.currentIndex()
            selected_image = None
            if current_index.isValid():
                selected_image = source_model.data(
                    self.proxy_image_list_model.mapToSource(current_index),
                    Qt.ItemDataRole.UserRole
                )
                if selected_image:
                    print(f"[SORT] Will scroll to selected image: {selected_image.path.name}")
                else:
                    print(f"[SORT] Could not get selected image object")
            else:
                print(f"[SORT] No valid current index to scroll to")

            # Emit layoutAboutToBeChanged before sorting
            source_model.layoutAboutToBeChanged.emit()

            # BUFFERED PAGINATION MODE: Update DB sort params and reload pages
            if hasattr(source_model, '_paginated_mode') and source_model._paginated_mode:
                # Map UI sort option to DB field
                sort_map = {
                    'Default': ('file_name', 'ASC'),
                    'Name': ('file_name', 'ASC'),
                    'Modified': ('mtime', 'DESC'),
                    'Created': ('ctime', 'DESC'),
                    'Size': ('file_size', 'DESC'),
                    'Type': ('file_type', 'ASC'),
                    'Random': ('RANDOM()', 'ASC')  # Now supported in DB
                }

                db_sort_field, db_sort_dir = sort_map.get(sort_by, ('file_name', 'ASC'))
                source_model._sort_field = db_sort_field
                source_model._sort_dir = db_sort_dir
                
                # STABLE RANDOM: Generate a new seed if sorting by Random, to shuffle view
                if sort_by == 'Random':
                    import time
                    source_model._random_seed = int(time.time() * 1000) % 1000000
                
                print(f"[SORT] Buffered mode: changed DB sort to {db_sort_field} {db_sort_dir} (Seed: {getattr(source_model, '_random_seed', 0)})")

                # CRITICAL: Inform Qt that the entire model is being reset
                source_model.beginResetModel()
                
                try:
                    # Clear all pages and reload from DB with new sort
                    with source_model._page_load_lock:
                        source_model._pages.clear()
                        source_model._loading_pages.clear()
                        source_model._page_load_order.clear()

                    # Reload first 3 pages with new sort order
                    for page_num in range(3):
                        source_model._load_page_sync(page_num)
                finally:
                    source_model.endResetModel()

                # Trigger layout update - emit pages_updated FIRST so proxy invalidates
                source_model._emit_pages_updated()
                # source_model.layoutChanged.emit() # Redundant with endResetModel()
                
                # Restart background enrichment (essential for updating placeholders)
                if hasattr(source_model, '_start_paginated_enrichment'):
                    source_model._start_paginated_enrichment()

            else:
                # NORMAL MODE: Sort in-memory list
                source_model.beginResetModel()
                try:
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
                finally:
                    source_model.endResetModel()

                # Restart background enrichment with new sorted order
                if hasattr(source_model, '_restart_enrichment'):
                    source_model._restart_enrichment()

            # --- SELECTION RESTORATION ---
            # Use a class-level variable and a single shot timer to avoid multiple connections
            if selected_image:
                self._image_to_scroll_to = selected_image
                
                try:
                    # Disconnect previous if any
                    self.list_view.layout_ready.disconnect(self._do_scroll_after_sort)
                except Exception:
                    pass
                    
                self.list_view.layout_ready.connect(self._do_scroll_after_sort)
                
                # Fallback timer (1s)
                QTimer.singleShot(1000, self._do_scroll_after_sort)
            else:
                 self.list_view.verticalScrollBar().setValue(0)

        except Exception as e:
            import traceback
            print(f"Sort error: {e}")
            traceback.print_exc()
            # Ensure layoutChanged is emitted even on error
            source_model.layoutChanged.emit()

    @Slot()
    def _do_scroll_after_sort(self):
        """Scroll to the previously selected image after a sort operation completes."""
        if not hasattr(self, '_image_to_scroll_to') or not self._image_to_scroll_to:
            return
            
        selected_image = self._image_to_scroll_to
        self._image_to_scroll_to = None  # Clear to prevent multiple triggers
        
        try:
            # Disconnect to prevent re-triggering from future layouts
            try:
                self.list_view.layout_ready.disconnect(self._do_scroll_after_sort)
            except Exception:
                pass
                
            source_model = self.proxy_image_list_model.sourceModel()
            new_proxy_index = QModelIndex()
            
            if hasattr(source_model, '_paginated_mode') and source_model._paginated_mode:
                # OPTIMIZATION: In paginated mode, don't iterate all data
                # Just check the first few rows (usually where it ends up after Name sort if it was near top)
                # For 1600 items, we can iterate, but let's be careful.
                row_count = source_model.rowCount()
                for row in range(min(row_count, 3000)): # Cap at 3k for safety
                    image = source_model.data(source_model.index(row, 0), Qt.ItemDataRole.UserRole)
                    if image and image.path == selected_image.path:
                        new_proxy_index = self.proxy_image_list_model.mapFromSource(source_model.index(row, 0))
                        break
            else:
                try:
                    new_source_row = source_model.images.index(selected_image)
                    new_proxy_index = self.proxy_image_list_model.mapFromSource(source_model.index(new_source_row, 0))
                except (ValueError, AttributeError):
                    pass

            if new_proxy_index.isValid():
                from PySide6.QtWidgets import QAbstractItemView
                self.list_view.setCurrentIndex(new_proxy_index)
                self.list_view.scrollTo(new_proxy_index, QAbstractItemView.ScrollHint.PositionAtCenter)
            else:
                # Not loaded or filtered out
                pass
        except Exception as e:
            print(f"[SORT] Scroll restoration failed: {e}")
            pass

    @Slot()
    def toggle_deletion_marking(self):
        """Toggle the deletion marking for selected images."""
        selected_indices = self.list_view.selectedIndexes()
        print(f"[DEBUG] toggle_deletion_marking called, selected_indices: {len(selected_indices)}")
        if not selected_indices:
            return

        # Get the images and toggle their marking
        for proxy_index in selected_indices:
            source_index = self.proxy_image_list_model.mapToSource(proxy_index)
            image = self.proxy_image_list_model.sourceModel().data(
                source_index, Qt.ItemDataRole.UserRole)
            if image:
                old_value = image.marked_for_deletion
                image.marked_for_deletion = not image.marked_for_deletion
                print(f"[DEBUG] Toggled image {image.path.name}: {old_value} -> {image.marked_for_deletion}")

        # Trigger repaint
        self.list_view.viewport().update()

        # Emit signal to update delete button visibility
        print(f"[DEBUG] Emitting deletion_marking_changed signal")
        self.deletion_marking_changed.emit()

    def get_marked_for_deletion_count(self):
        """Get count of images marked for deletion."""
        source_model = self.proxy_image_list_model.sourceModel()
        count = 0
        for row in range(source_model.rowCount()):
            index = source_model.index(row, 0)
            image = source_model.data(index, Qt.ItemDataRole.UserRole)
            if image and hasattr(image, 'marked_for_deletion') and image.marked_for_deletion:
                count += 1
        return count

    @Slot()
    def unmark_all_images(self):
        """Remove deletion marking from all images."""
        source_model = self.proxy_image_list_model.sourceModel()
        for row in range(source_model.rowCount()):
            index = source_model.index(row, 0)
            image = source_model.data(index, Qt.ItemDataRole.UserRole)
            if image and hasattr(image, 'marked_for_deletion'):
                image.marked_for_deletion = False

        # Trigger repaint
        self.list_view.viewport().update()

        # Emit signal to update delete button visibility
        self.deletion_marking_changed.emit()

    @Slot()
    def delete_marked_images(self):
        """Delete all images marked for deletion."""
        source_model = self.proxy_image_list_model.sourceModel()
        marked_images = []
        marked_indices = []

        # Collect all marked images and their proxy indices
        for row in range(self.proxy_image_list_model.rowCount()):
            proxy_index = self.proxy_image_list_model.index(row, 0)
            image = self.proxy_image_list_model.data(proxy_index, Qt.ItemDataRole.UserRole)
            if image and hasattr(image, 'marked_for_deletion') and image.marked_for_deletion:
                marked_images.append(image)
                marked_indices.append(row)

        if not marked_images:
            return

        marked_count = len(marked_images)
        title = f'Delete {pluralize("Image", marked_count)}'
        question = (f'Delete {marked_count} marked '
                    f'{pluralize("image", marked_count)} and '
                    f'{"its" if marked_count == 1 else "their"} '
                    f'{pluralize("caption", marked_count)}?')
        reply = get_confirmation_dialog_reply(title, question)
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Calculate the index to focus after deletion
        if marked_indices:
            max_marked_row = marked_indices[-1]
            total_rows = self.proxy_image_list_model.rowCount()
            # Set next index: use the row after the last deleted one, or the one before if it's the last
            next_index = max_marked_row + 1 - len(marked_indices)
            if next_index >= total_rows - len(marked_indices):
                # If we're deleting at the end, focus on the image before the first deleted one
                next_index = max(0, marked_indices[0] - 1)
            # Store in main window for use after reload
            main_window = self.parent()
            main_window.post_deletion_index = next_index

        # Similar cleanup logic as delete_selected_images
        main_window = self.parent()
        video_was_cleaned = False
        if hasattr(main_window, 'image_viewer') and hasattr(main_window.image_viewer, 'video_player'):
            video_player = main_window.image_viewer.video_player
            if video_player.video_path:
                currently_loaded_path = Path(video_player.video_path)
                for image in marked_images:
                    if image.path == currently_loaded_path:
                        video_player.cleanup()
                        video_was_cleaned = True
                        break

        # Clear thumbnails
        for image in marked_images:
            if hasattr(image, 'is_video') and image.is_video and image.thumbnail:
                image.thumbnail = None

        if video_was_cleaned:
            from PySide6.QtCore import QThread
            QThread.msleep(100)
            QApplication.processEvents()

        # Delete files with retries
        import gc
        max_retries = 3
        for image in marked_images:
            success = False
            for attempt in range(max_retries):
                if attempt > 0:
                    QThread.msleep(150)
                    QApplication.processEvents()
                    gc.collect()

                image_file = QFile(str(image.path))
                if image_file.moveToTrash():
                    success = True
                    break
                elif attempt == max_retries - 1:
                    reply = QMessageBox.question(
                        self, 'Trash Failed',
                        f'Could not move {image.path.name} to trash.\nDelete permanently?',
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No
                    )
                    if reply == QMessageBox.Yes:
                        if image_file.remove():
                            success = True

            if not success:
                QMessageBox.critical(self, 'Error', f'Failed to delete {image.path}.')
                continue

            # Delete caption file
            caption_file_path = image.path.with_suffix('.txt')
            if caption_file_path.exists():
                caption_file = QFile(caption_file_path)
                if not caption_file.moveToTrash():
                    caption_file.remove()

        self.directory_reload_requested.emit()
