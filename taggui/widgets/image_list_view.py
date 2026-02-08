from widgets.image_list_shared import *  # noqa: F401,F403
from widgets.image_list_view_strategy_mixin import ImageListViewStrategyMixin
from widgets.image_list_view_recalc_mixin import ImageListViewRecalcMixin
from widgets.image_list_view_calculation_mixin import ImageListViewCalculationMixin
from widgets.image_list_view_layout_mixin import ImageListViewLayoutMixin
from widgets.image_list_view_preload_mixin import ImageListViewPreloadMixin
from widgets.image_list_view_geometry_mixin import ImageListViewGeometryMixin
from widgets.image_list_view_interaction_mixin import ImageListViewInteractionMixin
from widgets.image_list_view_scroll_mixin import ImageListViewScrollMixin
from widgets.image_list_view_paint_selection_mixin import ImageListViewPaintSelectionMixin
from widgets.image_list_view_file_ops_mixin import ImageListViewFileOpsMixin
from widgets.image_list_strict_domain_service import StrictScrollDomainService
from widgets.image_list_masonry_lifecycle_service import MasonryLifecycleService

class ImageListView(
    ImageListViewStrategyMixin,
    ImageListViewRecalcMixin,
    ImageListViewCalculationMixin,
    ImageListViewLayoutMixin,
    ImageListViewPreloadMixin,
    ImageListViewGeometryMixin,
    ImageListViewInteractionMixin,
    ImageListViewScrollMixin,
    ImageListViewPaintSelectionMixin,
    ImageListViewFileOpsMixin,
    QListView,
):
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
        self._masonry_strategy_logged = None
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
        self._drag_scroll_max_baseline = 0
        self._drag_target_page = None
        self._release_page_lock_page = None
        self._release_page_lock_until = 0.0
        self._strict_virtual_avg_height = 0.0
        self._strict_masonry_avg_h = 0.0  # avg_h used to BUILD current masonry items
        self._strict_drag_frozen_max = 0
        self._strict_drag_frozen_until = 0.0
        self._strict_scroll_max_floor = 0
        self._strict_drag_live_fraction = 0.0
        self._strict_range_guard = False
        self._strict_domain_service = StrictScrollDomainService(self)
        self._masonry_lifecycle_service = MasonryLifecycleService(self)

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
        self.verticalScrollBar().sliderMoved.connect(self._on_scrollbar_slider_moved)
        self.verticalScrollBar().rangeChanged.connect(self._on_scrollbar_range_changed)

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

__all__ = ["ImageListView"]
