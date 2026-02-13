from widgets.image_list_shared import *  # noqa: F401,F403


class _SpawnDragArrowOverlay(QWidget):
    """Top-level transparent overlay that draws a directional drag arrow."""

    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._start_global = QPoint()
        self._end_global = QPoint()
        self._local_start = QPoint()
        self._local_end = QPoint()

    def set_points(self, start_global: QPoint, end_global: QPoint):
        self._start_global = QPoint(start_global)
        self._end_global = QPoint(end_global)

        margin = 24
        min_x = min(self._start_global.x(), self._end_global.x()) - margin
        min_y = min(self._start_global.y(), self._end_global.y()) - margin
        max_x = max(self._start_global.x(), self._end_global.x()) + margin
        max_y = max(self._start_global.y(), self._end_global.y()) + margin
        width = max(1, max_x - min_x)
        height = max(1, max_y - min_y)
        self.setGeometry(min_x, min_y, width, height)

        self._local_start = QPoint(self._start_global.x() - min_x, self._start_global.y() - min_y)
        self._local_end = QPoint(self._end_global.x() - min_x, self._end_global.y() - min_y)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        line_color = QColor(255, 92, 92, 230)
        glow_color = QColor(255, 60, 60, 120)

        # Soft glow under stroke
        glow_pen = QPen(glow_color, 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(glow_pen)
        painter.drawLine(self._local_start, self._local_end)

        # Main stroke
        pen = QPen(line_color, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(self._local_start, self._local_end)

        # Arrow head at current cursor side
        dx = float(self._local_end.x() - self._local_start.x())
        dy = float(self._local_end.y() - self._local_start.y())
        length = max(1.0, (dx * dx + dy * dy) ** 0.5)
        ux = dx / length
        uy = dy / length
        px = -uy
        py = ux

        head_len = 14.0
        head_half = 6.0
        tip = QPoint(int(self._local_end.x()), int(self._local_end.y()))
        back = QPoint(
            int(round(tip.x() - (ux * head_len))),
            int(round(tip.y() - (uy * head_len))),
        )
        left = QPoint(
            int(round(back.x() + (px * head_half))),
            int(round(back.y() + (py * head_half))),
        )
        right = QPoint(
            int(round(back.x() - (px * head_half))),
            int(round(back.y() - (py * head_half))),
        )

        painter.setBrush(line_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(QPolygon([tip, left, right]))
        super().paintEvent(event)


class _DragIndicatorWidget(QWidget):
    """Drag indicator styled like hidden window markers, sized to match thumbnail."""
    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Semi-transparent dark background
        painter.setBrush(QColor(40, 40, 40, 200))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self.rect(), 6, 6)

        # Bright border
        painter.setPen(QPen(QColor(100, 180, 255), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 5, 5)

        # Inner glow
        painter.setPen(QPen(QColor(150, 200, 255, 100), 1))
        painter.drawRoundedRect(self.rect().adjusted(3, 3, -3, -3), 3, 3)


class ImageListViewGeometryMixin:
    def _build_queues_async(self):
        """Build priority queues asynchronously (runs on next event loop to avoid blocking UI)."""
        source_model = self.model().sourceModel()
        if not source_model or not hasattr(source_model, 'PAGE_SIZE'):
            self._queue_building = False
            return
        is_paginated = bool(
            hasattr(source_model, '_paginated_mode') and source_model._paginated_mode
        )
        total_count = (
            int(getattr(source_model, '_total_count', 0) or 0)
            if is_paginated
            else int(source_model.rowCount())
        )
        if total_count <= 0:
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
        for i in range(max_visible + 1, min(max_visible + near_buffer_below + 1, total_count)):
            if i not in visited:
                self._high_queue.append(i)
                visited.add(i)
        for i in range(min_visible - 1, max(0, min_visible - near_buffer_above) - 1, -1):
            if i not in visited:
                self._high_queue.append(i)
                visited.add(i)

        # ZONE 3: Low (far buffer)
        far_start_below = max_visible + near_buffer_below + 1
        for i in range(far_start_below, min(far_start_below + far_buffer_below, total_count)):
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
        page_size = int(getattr(source_model, 'PAGE_SIZE', 1000) or 1000)
        is_paginated = bool(
            hasattr(source_model, '_paginated_mode') and source_model._paginated_mode
        )
        total_count = (
            int(getattr(source_model, '_total_count', 0) or 0)
            if is_paginated
            else int(source_model.rowCount())
        )
        if total_count <= 0:
            return

        keep_range_start = max(0, min_visible - page_size * eviction_pages)
        keep_range_end = min(total_count - 1, max_visible + page_size * eviction_pages)

        # Evict thumbnails outside keep range
        evicted_count = 0
        if is_paginated and hasattr(source_model, '_pages'):
            lock = getattr(source_model, '_page_load_lock', None)
            if lock:
                with lock:
                    pages_snapshot = list(source_model._pages.items())
            else:
                pages_snapshot = list(source_model._pages.items())

            for page_num, page in pages_snapshot:
                if not page:
                    continue
                base_idx = int(page_num) * page_size
                for offset, image in enumerate(page):
                    if image is None:
                        continue
                    global_idx = base_idx + offset
                    if global_idx < keep_range_start or global_idx > keep_range_end:
                        if image.thumbnail or image.thumbnail_qimage:
                            image.thumbnail = None
                            image.thumbnail_qimage = None
                            evicted_count += 1
                            # Pagination preload tracks global indices.
                            if hasattr(self, '_pagination_loaded_items'):
                                self._pagination_loaded_items.discard(global_idx)
        else:
            for i, image in enumerate(source_model.images):
                if i < keep_range_start or i > keep_range_end:
                    if image.thumbnail or image.thumbnail_qimage:
                        image.thumbnail = None
                        image.thumbnail_qimage = None
                        evicted_count += 1
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

    def _invalidate_pending_masonry_for_mode_switch(self):
        """Invalidate in-flight masonry work when switching List/Icon mode."""
        self._masonry_mode_generation = int(getattr(self, "_masonry_mode_generation", 0)) + 1
        self._masonry_calculating = False
        self._masonry_recalc_pending = False
        if hasattr(self, "_masonry_recalc_timer"):
            self._masonry_recalc_timer.stop()
        if hasattr(self, "_resize_timer"):
            self._resize_timer.stop()


    def _apply_startup_view_mode_seed(self):
        """Seed startup mode before hysteresis logic runs."""
        saved_mode = str(settings.value("image_list_view_mode", "", type=str) or "").strip().lower()
        if saved_mode == "list":
            self.setViewMode(QListView.ViewMode.ListMode)
            return
        if saved_mode == "icon":
            self.setViewMode(QListView.ViewMode.IconMode)
            return

        threshold = int(getattr(self, "column_switch_threshold", 150) or 150)
        if int(getattr(self, "current_thumbnail_size", 0) or 0) >= threshold:
            self.setViewMode(QListView.ViewMode.ListMode)
        else:
            self.setViewMode(QListView.ViewMode.IconMode)


    def _persist_current_view_mode(self):
        """Persist active mode so startup hysteresis can use the right prior mode."""
        mode_value = (
            "list"
            if self.viewMode() == QListView.ViewMode.ListMode
            else "icon"
        )
        try:
            existing = str(settings.value("image_list_view_mode", "", type=str) or "")
            if existing != mode_value:
                settings.setValue("image_list_view_mode", mode_value)
        except Exception:
            pass


    def _update_view_mode(self):
        """Switch between single column (ListMode) and multi-column (IconMode) based on thumbnail size."""
        import time
        previous_mode = self.viewMode()
        now = time.time()
        hysteresis = int(getattr(self, "_view_mode_hysteresis_px", 30) or 30)
        cooldown_s = float(getattr(self, "_view_mode_switch_cooldown_s", 0.35) or 0.35)
        threshold = int(getattr(self, "column_switch_threshold", 150) or 150)

        # Use hysteresis to avoid rapid toggling around threshold.
        if previous_mode == QListView.ViewMode.ListMode:
            switch_to_list = self.current_thumbnail_size > max(self.min_thumbnail_size, threshold - hysteresis)
        else:
            switch_to_list = self.current_thumbnail_size >= threshold

        desired_mode = QListView.ViewMode.ListMode if switch_to_list else QListView.ViewMode.IconMode
        if desired_mode != previous_mode:
            if (now - float(getattr(self, "_last_view_mode_switch_time", 0.0) or 0.0)) < cooldown_s:
                # Keep current mode during cooldown to avoid unsafe mode churn.
                self.use_masonry = (previous_mode == QListView.ViewMode.IconMode)
                self._persist_current_view_mode()
                return
            self._last_view_mode_switch_time = now

        if switch_to_list:
            # Large thumbnails: single column list view
            self.use_masonry = False
            if previous_mode != QListView.ViewMode.ListMode:
                self._invalidate_pending_masonry_for_mode_switch()
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
            if previous_mode != QListView.ViewMode.IconMode:
                self._invalidate_pending_masonry_for_mode_switch()
                self.setViewMode(QListView.ViewMode.IconMode)
            self.setFlow(QListView.Flow.LeftToRight)
            self.setResizeMode(QListView.ResizeMode.Fixed)
            self.setWrapping(True)
            self.setSpacing(2)
            self.setUniformItemSizes(False)  # Allow varying sizes
            # Disable default grid - we'll handle positioning with masonry
            self.setGridSize(QSize(-1, -1))
            # Calculate masonry layout (will re-center via flag)
            self._recenter_after_layout = (previous_mode != QListView.ViewMode.IconMode)
            self._calculate_masonry_layout()
            # Force item delegate to recalculate sizes and update viewport
            self.scheduleDelayedItemsLayout()
            self.viewport().update()

        self._persist_current_view_mode()


    def _resolve_live_spawn_index(self, dragged_index: QPersistentModelIndex, dragged_path) -> QModelIndex:
        """Resolve a live proxy index after drag, with path fallback for churn."""
        try:
            live_index = self.model().index(dragged_index.row(), dragged_index.column())
        except Exception:
            live_index = QModelIndex()

        if (not live_index.isValid()) and dragged_path is not None:
            try:
                proxy_model = self.model()
                source_model = proxy_model.sourceModel() if hasattr(proxy_model, "sourceModel") else None
                if source_model is not None and hasattr(source_model, "get_index_for_path"):
                    src_row = source_model.get_index_for_path(dragged_path)
                    if isinstance(src_row, int) and src_row >= 0:
                        src_idx = source_model.index(src_row, 0)
                        if src_idx.isValid() and hasattr(proxy_model, "mapFromSource"):
                            live_index = proxy_model.mapFromSource(src_idx)
            except Exception:
                live_index = QModelIndex()
        return live_index

    def _spawn_floating_from_drag_index(
        self,
        live_index: QModelIndex,
        source_pixmap: QPixmap,
        spawn_global_pos: QPoint | None = None,
    ):
        """Spawn one floating viewer from resolved proxy index."""
        if not live_index.isValid():
            return
        try:
            self._flash_drag_drop_preview(source_pixmap)
        except Exception:
            pass
        main_window = self.window()
        if main_window and hasattr(main_window, 'spawn_floating_viewer_at'):
            try:
                main_window.spawn_floating_viewer_at(
                    target_index=live_index,
                    spawn_global_pos=spawn_global_pos if spawn_global_pos is not None else QCursor.pos(),
                )
            except Exception as e:
                print(f"[DRAG-SPAWN] Spawn warning: {e}")

    def _build_spawn_drag_source_pixmap(self, model_index: QModelIndex) -> QPixmap:
        """Build a best-effort thumbnail pixmap for drag ghost/preview."""
        source_pixmap = QPixmap()
        try:
            icon = model_index.data(Qt.ItemDataRole.DecorationRole)
            if icon is not None:
                source_pixmap = icon.pixmap(self.iconSize())
        except Exception:
            source_pixmap = QPixmap()
        if source_pixmap.isNull():
            try:
                item_rect = self.visualRect(model_index)
                if item_rect.isValid() and item_rect.width() > 0 and item_rect.height() > 0:
                    source_pixmap = self.viewport().grab(item_rect)
            except Exception:
                source_pixmap = QPixmap()
        if source_pixmap.isNull():
            fallback_side = max(48, int(self.iconSize().width() or 96))
            source_pixmap = QPixmap(fallback_side, fallback_side)
            source_pixmap.fill(Qt.GlobalColor.transparent)
        return source_pixmap

    def _show_spawn_drag_ghost(self, model_index: QModelIndex):
        """Show drag indicator sized to match thumbnail."""
        if not model_index.isValid():
            return
        source_pixmap = self._build_spawn_drag_source_pixmap(model_index)
        if source_pixmap.isNull():
            return

        ghost = getattr(self, "_spawn_drag_ghost_widget", None)
        if ghost is None:
            ghost = _DragIndicatorWidget(None)
            self._spawn_drag_ghost_widget = ghost

        # Size to match the thumbnail
        ghost.resize(source_pixmap.size())
        self._spawn_drag_ghost_size = source_pixmap.size()
        ghost.show()
        ghost.raise_()
        self._update_spawn_drag_ghost_pos()

    def _update_spawn_drag_ghost_pos(self, global_pos: QPoint | None = None):
        ghost = getattr(self, "_spawn_drag_ghost_widget", None)
        if ghost is None:
            return
        cursor_global = global_pos if global_pos is not None else QCursor.pos()
        # Center the top-level indicator on the global cursor position.
        size = getattr(self, '_spawn_drag_ghost_size', QSize(40, 40))
        ghost.move(cursor_global.x() - size.width() // 2, cursor_global.y() - size.height() // 2)

        try:
            self._spawn_drag_last_global_pos = QPoint(cursor_global)
        except Exception:
            pass

    def _hide_spawn_drag_ghost(self):
        ghost = getattr(self, "_spawn_drag_ghost_widget", None)
        if ghost is not None:
            ghost.hide()

    def _show_spawn_drag_arrow(self, start_global: QPoint, end_global: QPoint):
        overlay = getattr(self, "_spawn_drag_arrow_overlay", None)
        if overlay is None:
            overlay = _SpawnDragArrowOverlay()
            self._spawn_drag_arrow_overlay = overlay
        overlay.set_points(start_global, end_global)
        overlay.show()

    def _update_spawn_drag_arrow(self, start_global: QPoint, end_global: QPoint):
        overlay = getattr(self, "_spawn_drag_arrow_overlay", None)
        if overlay is None:
            return
        overlay.set_points(start_global, end_global)

    def _hide_spawn_drag_arrow(self):
        overlay = getattr(self, "_spawn_drag_arrow_overlay", None)
        if overlay is not None:
            overlay.hide()

    def _spawn_floating_for_index_at_cursor(
        self,
        model_index: QModelIndex,
        spawn_global_pos: QPoint | None = None,
    ):
        """Spawn directly at cursor from one explicit index (no Qt drag loop)."""
        if not model_index.isValid():
            return
        dragged_index = QPersistentModelIndex(model_index)
        dragged_path = None
        try:
            image = model_index.data(Qt.ItemDataRole.UserRole)
            dragged_path = getattr(image, "path", None)
        except Exception:
            dragged_path = None

        source_pixmap = self._build_spawn_drag_source_pixmap(model_index)

        live_index = self._resolve_live_spawn_index(dragged_index, dragged_path)
        self._spawn_floating_from_drag_index(live_index, source_pixmap, spawn_global_pos=spawn_global_pos)

    def _start_spawn_drag_for_index(self, model_index: QModelIndex, supportedActions: Qt.DropAction):
        """Start drag/spawn flow from one explicit index (selection-independent)."""
        if not model_index.isValid():
            return
        indices = [model_index]
        dragged_index = QPersistentModelIndex(model_index)
        dragged_path = None
        try:
            image = model_index.data(Qt.ItemDataRole.UserRole)
            dragged_path = getattr(image, "path", None)
        except Exception:
            dragged_path = None

        # Use mimeData from the model.
        mime_data = self.model().mimeData(indices)
        if not mime_data:
            return

        # Build a reliable visual preview pixmap.
        source_pixmap = QPixmap()
        icon = model_index.data(Qt.ItemDataRole.DecorationRole)
        if icon is not None:
            try:
                source_pixmap = icon.pixmap(self.iconSize())
            except Exception:
                source_pixmap = QPixmap()
        if source_pixmap.isNull():
            try:
                item_rect = self.visualRect(indices[0])
                if item_rect.isValid() and item_rect.width() > 0 and item_rect.height() > 0:
                    source_pixmap = self.viewport().grab(item_rect)
            except Exception:
                source_pixmap = QPixmap()
        if source_pixmap.isNull():
            fallback_side = max(48, int(self.iconSize().width() or 96))
            source_pixmap = QPixmap(fallback_side, fallback_side)
            source_pixmap.fill(Qt.GlobalColor.transparent)

        # Drag pixmap is slightly translucent for ghosting.
        drag_pixmap = QPixmap(source_pixmap.size())
        drag_pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(drag_pixmap)
        painter.setOpacity(0.86)
        painter.drawPixmap(0, 0, source_pixmap)
        painter.end()

        # Ultra-fast drag/release race: if button is already up by the time we
        # reach drag start, skip QDrag.exec() and spawn immediately.
        if not (QApplication.mouseButtons() & Qt.MouseButton.LeftButton):
            live_index = self._resolve_live_spawn_index(dragged_index, dragged_path)
            self._spawn_floating_from_drag_index(live_index, source_pixmap)
            return

        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag.setPixmap(drag_pixmap)
        drag.setHotSpot(drag_pixmap.rect().center())
        drop_action = drag.exec(supportedActions)

        # If dropped onto no external target, spawn a floating viewer at cursor.
        if drop_action == Qt.DropAction.IgnoreAction and dragged_index.isValid():
            live_index = self._resolve_live_spawn_index(dragged_index, dragged_path)
            self._spawn_floating_from_drag_index(live_index, source_pixmap)

    def startDrag(self, supportedActions: Qt.DropAction):
        indices = self.selectedIndexes()
        if not indices:
            return
        # Keep Qt override behavior, but route through explicit-index path.
        self._start_spawn_drag_for_index(indices[0], supportedActions)

    def _flash_drag_drop_preview(self, pixmap: QPixmap):
        """Show a short glow/fade animation at drop position using drag ghost."""
        if pixmap is None or pixmap.isNull():
            return

        from PySide6.QtCore import QPropertyAnimation, QEasingCurve, QRect, QParallelAnimationGroup
        from PySide6.QtWidgets import QLabel, QGraphicsOpacityEffect

        framed_pixmap = QPixmap(pixmap.width() + 4, pixmap.height() + 4)
        framed_pixmap.fill(Qt.GlobalColor.transparent)
        framed_painter = QPainter(framed_pixmap)
        framed_painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        framed_painter.drawPixmap(2, 2, pixmap)
        framed_painter.setPen(QPen(QColor(255, 255, 255, 180), 1))
        framed_painter.drawRect(framed_pixmap.rect().adjusted(0, 0, -1, -1))
        framed_painter.end()

        overlay = QLabel(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        overlay.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        overlay.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        overlay.setPixmap(framed_pixmap)
        overlay.resize(framed_pixmap.size())

        center_pos = QCursor.pos()
        start_rect = QRect(
            center_pos.x() - framed_pixmap.width() // 2,
            center_pos.y() - framed_pixmap.height() // 2,
            framed_pixmap.width(),
            framed_pixmap.height(),
        )
        grow_w = int(framed_pixmap.width() * 1.12)
        grow_h = int(framed_pixmap.height() * 1.12)
        grown_rect = QRect(
            center_pos.x() - grow_w // 2,
            center_pos.y() - grow_h // 2,
            grow_w,
            grow_h,
        )
        overlay.setGeometry(start_rect)
        overlay.show()

        opacity_effect = QGraphicsOpacityEffect(overlay)
        overlay.setGraphicsEffect(opacity_effect)

        animation_group = QParallelAnimationGroup(self)

        fade_animation = QPropertyAnimation(opacity_effect, b"opacity")
        fade_animation.setDuration(220)
        fade_animation.setStartValue(1.0)
        fade_animation.setEndValue(0.0)
        fade_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        scale_animation = QPropertyAnimation(overlay, b"geometry")
        scale_animation.setDuration(220)
        scale_animation.setStartValue(start_rect)
        scale_animation.setKeyValueAt(0.45, grown_rect)
        scale_animation.setEndValue(start_rect)
        scale_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        animation_group.addAnimation(fade_animation)
        animation_group.addAnimation(scale_animation)
        if not hasattr(self, "_active_drag_preview_animations"):
            self._active_drag_preview_animations = []
        self._active_drag_preview_animations.append(animation_group)

        def _cleanup():
            try:
                if animation_group in self._active_drag_preview_animations:
                    self._active_drag_preview_animations.remove(animation_group)
            except Exception:
                pass
            overlay.deleteLater()

        animation_group.finished.connect(_cleanup)
        animation_group.start()


    def resizeEvent(self, event):
        """Recalculate masonry layout on resize (debounced)."""
        super().resizeEvent(event)
        if self.use_masonry:
            if getattr(self, '_skip_next_resize_recalc', False):
                # This flag is meant to skip one stale *queued* recalc after a
                # click/zoom anchor cancellation. If we keep returning here, all
                # future resize-driven recalcs can be blocked until Ctrl+wheel
                # clears the flag. Consume it and continue with this real resize.
                self._skip_next_resize_recalc = False
            import time
            if time.time() <= float(getattr(self, '_restore_anchor_until', 0.0) or 0.0):
                # Startup restore in progress: skip resize-driven recalc churn.
                return
            source_model = (
                self.model().sourceModel()
                if self.model() and hasattr(self.model(), 'sourceModel')
                else self.model()
            )
            if hasattr(self, '_activate_resize_anchor'):
                self._activate_resize_anchor(source_model=source_model, hold_s=3.0)
            # Debounce resize-triggered masonry recalcs enough to avoid
            # repeated strict-window ownership churn while dragging.
            self._resize_timer.stop()
            self._resize_timer.start(140)


    def _on_resize_finished(self):
        """Called after resize stops (debounced)."""
        if self.use_masonry:
            if getattr(self, '_skip_next_resize_recalc', False):
                self._skip_next_resize_recalc = False
                print("[RESIZE] Skipped stale queued recalc after user click")
                return
            import time
            if time.time() <= float(getattr(self, '_restore_anchor_until', 0.0) or 0.0):
                return
            source_model = (
                self.model().sourceModel()
                if self.model() and hasattr(self.model(), 'sourceModel')
                else self.model()
            )
            strategy = self._get_masonry_strategy(source_model) if source_model else "full_compat"
            strict_paginated = bool(
                source_model
                and hasattr(source_model, '_paginated_mode')
                and source_model._paginated_mode
                and strategy == "windowed_strict"
            )

            if strict_paginated:
                if hasattr(self, '_activate_resize_anchor'):
                    self._activate_resize_anchor(source_model=source_model, hold_s=2.0)
            else:
                self._resize_anchor_page = None
                self._resize_anchor_until = 0.0

            print("[RESIZE] Window resize finished, recalculating masonry...")
            # In strict paginated mode, explicit page/global anchoring above is
            # more stable than recentering via possibly stale proxy row index.
            self._recenter_after_layout = not strict_paginated
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
        strategy = self._get_masonry_strategy(source_model) if source_model else "full_compat"
        strict_mode = strategy == "windowed_strict"

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

            if strict_mode:
                _log_idle_strict = (not self._mouse_scrolling) and (not self._scrollbar_dragging)
                def _strict_tail_scroll_target():
                    try:
                        total_items_i = int(getattr(source_model, '_total_count', 0) or 0)
                        if total_items_i <= 0 or not self._masonry_items:
                            return None
                        tail_idx = total_items_i - 1
                        tail_item = None
                        for _it in self._masonry_items:
                            if int(_it.get('index', -1)) == tail_idx:
                                tail_item = _it
                                break
                        if tail_item is None:
                            return None
                        tail_bottom = int(tail_item.get('y', 0)) + int(tail_item.get('height', 0))
                        return max(0, tail_bottom - max(1, self.viewport().height()))
                    except Exception:
                        return None

                # Block signals through the entire strict correction to prevent
                # _on_scroll_value_changed from recording transient values.
                saved_val = self.verticalScrollBar().value()
                saved_max = max(1, self.verticalScrollBar().maximum())
                _click_scroll_freeze = (
                    time.time()
                    < float(getattr(self, '_user_click_selection_frozen_until', 0.0) or 0.0)
                )
                self.verticalScrollBar().blockSignals(True)
                try:
                    super().updateGeometries()
                    keep_max = self._strict_canonical_domain_max(source_model)
                    if self._scrollbar_dragging or self._drag_preview_mode:
                        self._restore_strict_drag_domain(source_model=source_model)
                    elif _click_scroll_freeze:
                        # User recently clicked — update range but keep value.
                        self.verticalScrollBar().setRange(0, keep_max)
                        if getattr(self, '_stick_to_edge', None) == "bottom":
                            _tail_target = _strict_tail_scroll_target()
                            if _tail_target is not None:
                                self.verticalScrollBar().setValue(max(0, min(_tail_target, keep_max)))
                            else:
                                self.verticalScrollBar().setValue(max(0, min(saved_val, keep_max)))
                        elif getattr(self, '_stick_to_edge', None) == "top":
                            self.verticalScrollBar().setValue(0)
                        else:
                            self.verticalScrollBar().setValue(max(0, min(saved_val, keep_max)))
                    else:
                        self.verticalScrollBar().setRange(0, keep_max)
                        # Re-anchor to locked page so thumb stays put when domain grows.
                        _rl_page = getattr(self, '_release_page_lock_page', None)
                        _rl_live = (
                            _rl_page is not None
                            and time.time() < float(getattr(self, '_release_page_lock_until', 0.0) or 0.0)
                        )
                        _ps = int(getattr(source_model, 'PAGE_SIZE', 1000) or 1000)
                        _ti = int(getattr(source_model, '_total_count', 0) or 0)
                        _last_page = max(0, (_ti - 1) // max(1, _ps)) if _ti > 0 else 0
                        if _rl_live and keep_max > 0:
                            if getattr(self, '_stick_to_edge', None) == "bottom" or int(_rl_page) >= _last_page:
                                _tail_target = _strict_tail_scroll_target()
                                if _tail_target is not None:
                                    restored_val = max(0, min(_tail_target, keep_max))
                                else:
                                    restored_val = keep_max
                            elif getattr(self, '_stick_to_edge', None) == "top":
                                restored_val = 0
                            else:
                                _lock_idx = int(_rl_page) * _ps
                                _lock_it = None
                                for _it in self._masonry_items:
                                    if _it.get('index', -1) >= _lock_idx:
                                        _lock_it = _it
                                        break
                                if _lock_it is not None:
                                    restored_val = max(0, min(int(_lock_it['y']), keep_max))
                                else:
                                    _pf = max(0.0, min(1.0, _lock_idx / max(1, _ti)))
                                    restored_val = max(0, min(int(round(_pf * keep_max)), keep_max))
                        else:
                            restore_target = (
                                self._get_restore_anchor_scroll_value(source_model, keep_max)
                                if hasattr(self, '_get_restore_anchor_scroll_value')
                                else None
                            )
                            if restore_target is not None:
                                restored_val = max(0, min(int(restore_target), keep_max))
                            elif getattr(self, '_stick_to_edge', None) == "bottom":
                                _tail_target = _strict_tail_scroll_target()
                                if _tail_target is not None:
                                    restored_val = max(0, min(_tail_target, keep_max))
                                else:
                                    restored_val = keep_max
                            elif getattr(self, '_stick_to_edge', None) == "top":
                                restored_val = 0
                            else:
                                # Preserve absolute scroll value (clamped).
                                restored_val = max(0, min(saved_val, keep_max))
                        if self.verticalScrollBar().value() != restored_val:
                            self.verticalScrollBar().setValue(restored_val)
                finally:
                    self.verticalScrollBar().blockSignals(False)
                if _log_idle_strict and hasattr(self, "_log_diag"):
                    _sb = self.verticalScrollBar()
                    new_val = int(_sb.value())
                    new_max = int(_sb.maximum())
                    if abs(new_val - int(old_value)) > 1 or abs(new_max - int(old_max)) > 1:
                        self._log_diag(
                            "geom.strict_adjust",
                            source_model=source_model,
                            throttle_key="diag_geom_strict_adjust",
                            every_s=0.15,
                            extra=(
                                f"old={int(old_value)}/{int(old_max)} "
                                f"new={new_val}/{new_max} "
                                f"correct_max={int(correct_max)}"
                            ),
                        )
            else:
                super().updateGeometries()
                new_max = self.verticalScrollBar().maximum()
                if correct_max > 0 and new_max != correct_max:
                    self.verticalScrollBar().setRange(0, correct_max)
                    # Restore scroll position using STABLE memory
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
                    # Restore scroll position if Qt clamped it during range reduction (fallback)
                    elif (not suppress_restore) and self.verticalScrollBar().value() != old_value and old_value <= correct_max:
                        self.verticalScrollBar().blockSignals(True)
                        self.verticalScrollBar().setValue(old_value)
                        self.verticalScrollBar().blockSignals(False)

            # Enforce explicit edge lock even when range didn't change.
            if getattr(self, '_stick_to_edge', None) == "bottom":
                if strict_mode:
                    try:
                        _tail_target = None
                        _ti = int(getattr(source_model, '_total_count', 0) or 0)
                        if _ti > 0 and self._masonry_items:
                            _tail_idx = _ti - 1
                            _tail_item = None
                            for _it in self._masonry_items:
                                if int(_it.get('index', -1)) == _tail_idx:
                                    _tail_item = _it
                                    break
                            if _tail_item is not None:
                                _tail_bottom = int(_tail_item.get('y', 0)) + int(_tail_item.get('height', 0))
                                _tail_target = max(0, _tail_bottom - max(1, self.viewport().height()))
                        if _tail_target is not None:
                            self.verticalScrollBar().setValue(max(0, min(_tail_target, self.verticalScrollBar().maximum())))
                        else:
                            self.verticalScrollBar().setValue(max(0, self.verticalScrollBar().maximum()))
                    except Exception:
                        self.verticalScrollBar().setValue(max(0, self.verticalScrollBar().maximum()))
                else:
                    self.verticalScrollBar().setValue(max(0, self.verticalScrollBar().maximum()))
            elif getattr(self, '_stick_to_edge', None) == "top":
                self.verticalScrollBar().setValue(0)
        else:
            # Normal mode: let Qt manage scrollbar
            super().updateGeometries()


    def scrollTo(self, index, hint=None):
        """Override scrollTo to use masonry positions instead of Qt's row-based layout.

        Qt calls this internally from setCurrentIndex(), which knows nothing
        about masonry coordinates.  Without this override, clicking an item
        triggers scrollTo → Qt computes scroll from row number → viewport
        jumps to the wrong position.
        """
        if hint is None:
            hint = QAbstractItemView.ScrollHint.EnsureVisible

        if not (self.use_masonry and self._masonry_items and index.isValid()):
            super().scrollTo(index, hint)
            return

        # Map proxy row → global index → masonry rect.
        global_idx = index.row()
        source_model = (
            self.model().sourceModel()
            if hasattr(self.model(), 'sourceModel')
            else self.model()
        )
        if source_model and hasattr(source_model, 'get_global_index_for_row'):
            global_idx = source_model.get_global_index_for_row(index.row())
        elif source_model and getattr(source_model, '_paginated_mode', False):
            global_idx = self._map_row_to_global_index_safely(index.row())

        rect = self._get_masonry_item_rect(global_idx)
        if not rect.isValid():
            return  # Item not in current masonry window — don't jump blindly.

        sb = self.verticalScrollBar()
        scroll_val = sb.value()
        vh = self.viewport().height()
        item_top = rect.y()
        item_bot = rect.y() + rect.height()

        if hint == QAbstractItemView.ScrollHint.EnsureVisible:
            # Already fully visible → do nothing.
            if item_top >= scroll_val and item_bot <= scroll_val + vh:
                return
            # Partially above → scroll up just enough.
            if item_top < scroll_val:
                sb.setValue(max(0, item_top))
            # Partially below → scroll down just enough.
            elif item_bot > scroll_val + vh:
                sb.setValue(max(0, item_bot - vh))
        elif hint == QAbstractItemView.ScrollHint.PositionAtCenter:
            center_y = item_top + rect.height() // 2
            target = max(0, center_y - vh // 2)
            sb.setValue(min(target, sb.maximum()))
        elif hint == QAbstractItemView.ScrollHint.PositionAtTop:
            sb.setValue(max(0, min(item_top, sb.maximum())))
        elif hint == QAbstractItemView.ScrollHint.PositionAtBottom:
            sb.setValue(max(0, min(item_bot - vh, sb.maximum())))

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
        """Return the index at the given point, using masonry positions.

        Prefers the painted-geometry snapshot when fresh so that hit-testing
        matches what the user actually sees (immune to async recalc swaps).
        """
        if self.use_masonry and self._drag_preview_mode:
            return super().indexAt(point)
        if self.use_masonry and self._masonry_items:
            import time as _t
            source_model = self.model().sourceModel() if hasattr(self.model(), 'sourceModel') else self.model()

            hit_global = -1

            # 1. Try painted snapshot first (matches what user sees).
            #    Use the scroll offset captured at paint time, not the current
            #    value — updateGeometries() can shift it between paints.
            painted = getattr(self, '_painted_hit_regions', None)
            painted_age = _t.time() - float(getattr(self, '_painted_hit_regions_time', 0.0) or 0.0)
            if painted and painted_age < 2.0:
                snap_scroll = int(getattr(self, '_painted_hit_regions_scroll_offset', 0) or 0)
                adjusted_point = QPoint(point.x(), point.y() + snap_scroll)
                for g_idx, rect in painted.items():
                    if rect.contains(adjusted_point):
                        hit_global = int(g_idx)
                        break

            # 2. Fallback to live masonry index map.
            if hit_global < 0:
                scroll_offset = self.verticalScrollBar().value()
                adjusted_point = QPoint(point.x(), point.y() + scroll_offset)
                if not hasattr(self, '_masonry_index_map') or self._masonry_index_map is None:
                    self._rebuild_masonry_index_map()
                for global_idx, item in self._masonry_index_map.items():
                    item_rect = QRect(item['x'], item['y'], item['width'], item['height'])
                    if item_rect.contains(adjusted_point):
                        hit_global = int(global_idx)
                        break

            if hit_global >= 0:
                # Map global index → source row → source index → proxy index.
                if hasattr(source_model, 'get_loaded_row_for_global_index'):
                    row = source_model.get_loaded_row_for_global_index(hit_global)
                else:
                    row = hit_global
                if row != -1:
                    src_index = source_model.index(row, 0)
                    if not src_index.isValid():
                        return QModelIndex()
                    proxy_index = self.model().mapFromSource(src_index) if hasattr(self.model(), 'mapFromSource') else src_index
                    if proxy_index.isValid():
                        return proxy_index
                    return QModelIndex()

            return QModelIndex()
        else:
            return super().indexAt(point)
