from widgets.image_list_shared import *  # noqa: F401,F403

class ImageListViewPreloadMixin:
    def _proxy_index_from_global(self, global_idx: int):
        """Map a masonry global index to a valid proxy index for thumbnail prefetch."""
        model = self.model()
        if not model:
            return QModelIndex()
        source_model = model.sourceModel() if hasattr(model, 'sourceModel') else model

        try:
            gidx = int(global_idx)
        except Exception:
            return QModelIndex()
        if gidx < 0:
            return QModelIndex()

        # Paginated masonry stores global indices; convert to loaded source row first.
        if (
            source_model
            and hasattr(source_model, '_paginated_mode')
            and source_model._paginated_mode
            and hasattr(source_model, 'get_loaded_row_for_global_index')
        ):
            loaded_row = source_model.get_loaded_row_for_global_index(gidx)
            if loaded_row < 0:
                return QModelIndex()
            src_idx = source_model.index(loaded_row, 0)
            if hasattr(model, 'mapFromSource'):
                return model.mapFromSource(src_idx)
            return src_idx

        return model.index(gidx, 0)

    def _get_masonry_total_size(self):
        """Get total size from masonry results."""
        if not self._masonry_items:
            return QSize(0, 0)
        # Calculate width from columns (scrollbar-aware to match worker)
        column_width = self.current_thumbnail_size
        spacing = 2
        viewport_width = self.viewport().width()
        sb_w = self.verticalScrollBar().width() if self.verticalScrollBar().isVisible() else 15
        avail_w = viewport_width - sb_w - 24
        num_columns = max(1, avail_w // (column_width + spacing))
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
        if self._scrollbar_dragging:
            return

        # Load visible + buffer (2 screens above/below) during scroll
        # Background preloading is paused during scroll, so this has priority
        scroll_offset = self.verticalScrollBar().value()
        viewport_height = self.viewport().height()

        # Keep this lightweight during active wheel scrolling.
        preload_buffer = viewport_height if self._mouse_scrolling else (viewport_height * 2)
        preload_rect = QRect(0, scroll_offset - preload_buffer,
                            self.viewport().width(), viewport_height + (preload_buffer * 2))

        # Get items in preload range
        items_to_preload = self._get_masonry_visible_items(preload_rect)
        real_items = [it for it in items_to_preload if it.get('index', -1) >= 0]
        if not real_items:
            return

        center_y = scroll_offset + (viewport_height // 2)
        real_items.sort(key=lambda it: abs(int(it['rect'].center().y()) - center_y))
        max_requests = 24 if self._mouse_scrolling else 80

        # Trigger thumbnail loading (async, non-blocking)
        loaded_now = 0
        for item in real_items:
            if loaded_now >= max_requests:
                break
            index = self._proxy_index_from_global(item['index'])
            if index.isValid():
                # This triggers thumbnail generation if not cached
                _ = index.data(Qt.ItemDataRole.DecorationRole)
                loaded_now += 1
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
        import time
        self._scrollbar_dragging = True
        # Cancel any running enrichment so it restarts scoped to the new location
        source_model_pre = self.model().sourceModel() if hasattr(self.model(), 'sourceModel') else self.model()
        if source_model_pre and hasattr(source_model_pre, '_enrichment_cancelled'):
            source_model_pre._enrichment_cancelled.set()
        self._enrich_first_refresh_done = False
        sb = self.verticalScrollBar()
        source_model = self.model().sourceModel() if hasattr(self.model(), 'sourceModel') else self.model()
        old_max = max(1, int(sb.maximum()))
        old_pos = max(0, int(sb.sliderPosition()))
        strict_mode = self._use_local_anchor_masonry(source_model)
        if strict_mode:
            baseline_max = self._strict_canonical_domain_max(source_model)
        else:
            baseline_max = max(old_max, int(getattr(self, '_strict_scroll_max_floor', 0) or 0),
                               int(sb.value()), old_pos)
            self._strict_scroll_max_floor = max(int(getattr(self, '_strict_scroll_max_floor', 0) or 0), baseline_max)
        self._drag_scroll_max_baseline = baseline_max
        self._strict_drag_frozen_until = time.time() + 10.0
        # Preserve current fraction when entering strict drag domain.
        ratio = max(0.0, min(1.0, old_pos / old_max))
        if strict_mode and source_model and hasattr(source_model, '_total_count') and hasattr(source_model, 'PAGE_SIZE'):
            try:
                total_items = int(getattr(source_model, '_total_count', 0) or 0)
                page_size = int(getattr(source_model, 'PAGE_SIZE', 0) or 0)
                total_pages = max(1, (total_items + page_size - 1) // page_size) if page_size > 0 else 1
                cur_page = int(getattr(self, '_current_page', 0) or 0)
                if total_items > 0 and page_size > 0 and 0 <= cur_page < total_pages:
                    # Item-based fraction for consistency with masonry coordinates.
                    ratio = max(0.0, min(1.0, (cur_page * page_size) / max(1, total_items)))
            except Exception:
                pass
        self._strict_drag_live_fraction = ratio
        target_pos = int(round(ratio * baseline_max))
        prev_block = sb.blockSignals(True)
        try:
            sb.setRange(0, baseline_max)
            sb.setValue(max(0, min(target_pos, baseline_max)))
        finally:
            sb.blockSignals(prev_block)
        self._drag_target_page = None
        self._release_page_lock_page = None
        self._release_page_lock_until = 0.0
        self._drag_release_anchor_active = False
        self._drag_release_anchor_idx = None
        self._drag_release_anchor_until = 0.0
        self._stick_to_edge = None
        self._pending_edge_snap = None
        self._pending_edge_snap_until = 0.0

        # Pause thumbnail loading in model
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
        strategy = self._get_masonry_strategy(source_model) if source_model else "full_compat"
        release_fraction = 0.0
        max_v = sb.maximum()
        if strategy == "windowed_strict":
            baseline_max = self._strict_canonical_domain_max(source_model)
            # Keep virtual domain frozen through immediate post-release relayout bursts.
            self._strict_drag_frozen_until = time.time() + 2.0
        else:
            baseline_max = max(1, int(getattr(self, "_drag_scroll_max_baseline", 0) or 0))
        slider_pos = int(sb.sliderPosition())
        if strategy == "windowed_strict":
            release_fraction = max(0.0, min(1.0, slider_pos / max(1, baseline_max)))
            self._strict_drag_live_fraction = release_fraction
        else:
            release_fraction = max(0.0, min(1.0, slider_pos / baseline_max))
        if source_model and hasattr(source_model, '_paginated_mode') and source_model._paginated_mode:
            total_items = getattr(source_model, '_total_count', 0)
            if total_items > 0:
                total_pages = max(1, (total_items + source_model.PAGE_SIZE - 1) // source_model.PAGE_SIZE)
                if strategy == "windowed_strict":
                    slider_target_page = self._strict_page_from_position(slider_pos, source_model)
                else:
                    slider_target_page = self._drag_target_page
                    if slider_target_page is None:
                        slider_target_page = max(0, min(total_pages - 1, int(round(release_fraction * (total_pages - 1)))))
                    else:
                        slider_target_page = max(0, min(total_pages - 1, int(slider_target_page)))
                if strategy == "windowed_strict":
                    # Item-based fraction for consistency with masonry coordinates.
                    release_fraction = max(0.0, min(1.0, (slider_target_page * source_model.PAGE_SIZE) / max(1, total_items)))
                elif total_pages > 1:
                    release_fraction = slider_target_page / (total_pages - 1)
                self._drag_target_page = slider_target_page
                at_bottom_strict = max_v > 0 and sb.value() >= max_v - 2
                at_top_strict = sb.value() <= 2
                # Intent thresholds for drag preview: if user releases very low/high, snap to edge.
                # Keep this strict: broad thresholds caused accidental snaps near the lower region.
                if strategy == "windowed_strict":
                    # In strict mode, detect intent from raw slider position vs domain
                    # (not item-based fraction, which doesn't reach 1.0 for the last page).
                    raw_frac = max(0.0, min(1.0, slider_pos / max(1, baseline_max)))
                    bottom_intent = raw_frac >= 0.98
                    top_intent = raw_frac <= 0.02
                else:
                    bottom_intent = at_bottom_strict or (self._drag_preview_mode and release_fraction >= 0.99)
                    top_intent = at_top_strict or (self._drag_preview_mode and release_fraction <= 0.02)

                if bottom_intent:
                    self._drag_release_anchor_idx = total_items - 1
                    self._stick_to_edge = "bottom"
                elif top_intent:
                    self._drag_release_anchor_idx = 0
                    self._stick_to_edge = "top"
                elif self._drag_target_page is not None and hasattr(source_model, 'PAGE_SIZE') and source_model.PAGE_SIZE > 0:
                    page_anchor = max(0, int(self._drag_target_page))
                    self._drag_release_anchor_idx = max(0, min(total_items - 1, page_anchor * source_model.PAGE_SIZE))
                    self._stick_to_edge = None
                else:
                    self._drag_release_anchor_idx = max(0, min(total_items - 1, int(release_fraction * (total_items - 1))))
                    self._stick_to_edge = None
                if strategy == "windowed_strict":
                    # Preserve explicit edge intent in strict mode so zoom/domain
                    # recalculations keep ownership at real dataset edges.
                    # Only clear when release wasn't an edge-intent gesture.
                    if bottom_intent:
                        self._stick_to_edge = "bottom"
                    elif top_intent:
                        self._stick_to_edge = "top"
                    else:
                        self._stick_to_edge = None
                self._drag_release_anchor_active = True
                # Strict mode needs a longer lock to survive post-release relayout/page-load bursts.
                self._drag_release_anchor_until = time.time() + (8.0 if self._use_local_anchor_masonry(source_model) else 8.0)
                if hasattr(source_model, 'PAGE_SIZE') and source_model.PAGE_SIZE > 0:
                    self._current_page = self._drag_release_anchor_idx // source_model.PAGE_SIZE
                    # Lock owner briefly so async range updates cannot steal page ownership.
                    self._release_page_lock_page = int(self._current_page)
                    self._release_page_lock_until = time.time() + (4.0 if strategy == "windowed_strict" else 0.0)
                    # Eagerly request the target window immediately on release so strict
                    # mode does not paint an empty "loading target" frame for long.
                    try:
                        page_size = int(source_model.PAGE_SIZE)
                        total_items_i = int(total_items)
                        if page_size > 0 and total_items_i > 0 and hasattr(source_model, 'ensure_pages_for_range'):
                            target_page = max(0, min(total_pages - 1, int(self._current_page)))
                            try:
                                buffer_pages = int(settings.value('thumbnail_eviction_pages', 3, type=int))
                            except Exception:
                                buffer_pages = 3
                            buffer_pages = max(1, min(buffer_pages, 6))
                            start_page = max(0, target_page - buffer_pages)
                            end_page = min(total_pages - 1, target_page + buffer_pages)
                            start_row = start_page * page_size
                            end_row = min(total_items_i - 1, ((end_page + 1) * page_size) - 1)
                            source_model.ensure_pages_for_range(start_row, end_row)
                    except Exception:
                        pass
                    # Keep scrollbar value aligned to the strict virtual domain for this page.
                    if strategy == "windowed_strict":
                        # Item-based fraction to match masonry spacer positions.
                        page_fraction = max(0.0, min(1.0, (self._current_page * source_model.PAGE_SIZE) / max(1, total_items)))
                        if bottom_intent:
                            target_slider = baseline_max
                        elif top_intent:
                            target_slider = 0
                        else:
                            target_slider = int(round(page_fraction * baseline_max))
                        sb.setRange(0, baseline_max)
                        target_slider = max(0, min(target_slider, baseline_max))
                        sb.setValue(target_slider)
                        self._last_stable_scroll_value = target_slider
                if self._use_local_anchor_masonry(source_model):
                    self._log_flow(
                        "STRICT",
                        f"Release slider={slider_pos}/{baseline_max} frac={release_fraction:.3f} page={self._current_page}",
                        level="INFO",
                        throttle_key="strict_release",
                        every_s=0.2,
                    )
            else:
                self._drag_release_anchor_active = False
                self._drag_release_anchor_idx = None
                self._drag_release_anchor_until = 0.0
                self._release_page_lock_page = None
                self._release_page_lock_until = 0.0
            self._drag_scroll_max_baseline = 0
            self._strict_drag_live_fraction = release_fraction

        if strategy == "windowed_strict":
            self._pending_edge_snap = None
            self._pending_edge_snap_until = 0.0
        else:
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
            # Force immediate page-ownership refresh on release (bypass 100ms throttle).
            self._last_page_check_time = 0
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
        # Dragging the scrollbar must stay latency-free.
        # Wheel/trackpad scrolling can still preload with small batches.
        if self._scrollbar_dragging:
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
            # During active scrolling: prioritize visible and a tiny near-buffer.
            # This reduces temporary empty spots while still keeping UI responsive.
            urgent_batch = 10   # Visible items
            high_batch = 3      # Small near-buffer
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
                # Trigger DecorationRole for mapped proxy index; this reuses the
                # model's async thumbnail pipeline and de-duping futures map.
                proxy_index = self._proxy_index_from_global(idx)
                if proxy_index.isValid():
                    _ = proxy_index.data(Qt.ItemDataRole.DecorationRole)
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
                cadence = 45   # Faster refills during scroll
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
