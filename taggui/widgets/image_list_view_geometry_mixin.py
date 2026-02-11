from widgets.image_list_shared import *  # noqa: F401,F403

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
            import time
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
                # Block signals through the entire strict correction to prevent
                # _on_scroll_value_changed from recording transient values.
                saved_val = self.verticalScrollBar().value()
                saved_max = max(1, self.verticalScrollBar().maximum())
                self.verticalScrollBar().blockSignals(True)
                try:
                    super().updateGeometries()
                    keep_max = self._strict_canonical_domain_max(source_model)
                    if self._scrollbar_dragging or self._drag_preview_mode:
                        self._restore_strict_drag_domain(source_model=source_model)
                    else:
                        self.verticalScrollBar().setRange(0, keep_max)
                        # Re-anchor to locked page so thumb stays put when domain grows.
                        _rl_page = getattr(self, '_release_page_lock_page', None)
                        _rl_live = (
                            _rl_page is not None
                            and time.time() < float(getattr(self, '_release_page_lock_until', 0.0) or 0.0)
                        )
                        if _rl_live and keep_max > 0:
                            _ps = int(getattr(source_model, 'PAGE_SIZE', 1000) or 1000)
                            _lock_idx = int(_rl_page) * _ps
                            _lock_it = None
                            for _it in self._masonry_items:
                                if _it.get('index', -1) >= _lock_idx:
                                    _lock_it = _it
                                    break
                            if _lock_it is not None:
                                restored_val = max(0, min(int(_lock_it['y']), keep_max))
                            else:
                                _ti = int(getattr(source_model, '_total_count', 0) or 0)
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
                            else:
                                # Ratio-preserving: keep thumb at the same visual fraction.
                                ratio = saved_val / saved_max
                                restored_val = max(0, min(int(round(ratio * keep_max)), keep_max))
                        if self.verticalScrollBar().value() != restored_val:
                            self.verticalScrollBar().setValue(restored_val)
                finally:
                    self.verticalScrollBar().blockSignals(False)
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
                self.verticalScrollBar().setValue(max(0, self.verticalScrollBar().maximum()))
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
                    # Map global index → source row → source index → proxy index.
                    # Must go through mapFromSource; using self.model().index(row)
                    # directly would create a proxy index at the source row number,
                    # which is wrong when filtering shifts proxy rows.
                    if hasattr(source_model, 'get_loaded_row_for_global_index'):
                         row = source_model.get_loaded_row_for_global_index(global_idx)
                    else:
                         row = global_idx

                    if row != -1:
                        src_index = source_model.index(row, 0)
                        proxy_index = self.model().mapFromSource(src_index) if hasattr(self.model(), 'mapFromSource') else src_index
                        if proxy_index.isValid():
                            return proxy_index
                        # Fallback if mapFromSource fails (item filtered out)
                        return self.model().index(row, 0)
        
            return QModelIndex()
        else:
            return super().indexAt(point)
