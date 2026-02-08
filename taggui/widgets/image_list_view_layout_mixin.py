from widgets.image_list_shared import *  # noqa: F401,F403

class ImageListViewLayoutMixin:
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
            old_scroll_max = self.verticalScrollBar().maximum()
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
            strategy = self._get_masonry_strategy(source_model) if source_model else "full_compat"
            strict_mode = strategy == "windowed_strict"
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
                    if strict_mode:
                        # In strict/windowed mode, total_height_chunk includes the
                        # prefix spacer which inflates the average and creates a
                        # runaway growth loop (bigger avg → bigger spacer → bigger
                        # total_height → bigger avg → ...).  Compute real_avg from
                        # only the real items' vertical extent.
                        real_items_for_avg = [it for it in self._masonry_items if it.get('index', -1) >= 0]
                        if len(real_items_for_avg) >= 2:
                            min_real_y = min(it['y'] for it in real_items_for_avg)
                            max_real_y = max(it['y'] + it['height'] for it in real_items_for_avg)
                            content_h = max_real_y - min_real_y
                            real_avg = content_h / chunk_rows
                        else:
                            real_avg = total_height_chunk / chunk_rows
                    else:
                        real_avg = total_height_chunk / chunk_rows
                    if 10.0 < real_avg < 5000.0:
                        if strict_mode:
                            current_strict_avg = float(getattr(self, "_strict_virtual_avg_height", 0.0) or 0.0)
                            if current_strict_avg <= 1.0:
                                self._strict_virtual_avg_height = float(real_avg)
                            elif real_avg > current_strict_avg:
                                # Strict: only grow, never shrink. Keeps canonical domain stable.
                                blended = (current_strict_avg * 0.9) + (float(real_avg) * 0.1)
                                self._strict_virtual_avg_height = max(current_strict_avg, blended)
                        else:
                            if not hasattr(self, '_stable_avg_item_height'):
                                self._stable_avg_item_height = real_avg
                            else:
                                # Use a slower moving average to prevent oscillation loops
                                self._stable_avg_item_height = (self._stable_avg_item_height * 0.9) + (real_avg * 0.1)
                    
            # Use the most up-to-date stable average
            if strict_mode:
                avg_height = self._get_strict_virtual_avg_height()
            else:
                avg_height = getattr(self, '_stable_avg_item_height', 100.0)

            # Final total height estimation
            if math.isnan(avg_height):
                avg_height = self._get_strict_virtual_avg_height() if strict_mode else 100.0

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

                if strict_mode:
                    # Strict mode keeps virtual ownership from scrollbar fraction; avoid
                    # blind re-anchoring offsets that can shift the viewport unexpectedly.
                    y_offset = 0
                elif first_item_idx == 0:
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

                # Reconcile virtual height only in compatibility mode.
                # In strict mode, keeping a stable virtual height prevents thumb jitter.
                if not strict_mode:
                    if has_last_item:
                        self._masonry_total_height = max(max_actual_y, viewport_height + 1)
                    elif max_actual_y > self._masonry_total_height:
                        self._masonry_total_height = max_actual_y
                elif has_last_item and max_actual_y > self._masonry_total_height:
                    # Strict mode: never shrink virtual height, but do grow it when tail content
                    # proves the current estimate is too small (prevents bottom clipping).
                    previous_height = self._masonry_total_height
                    self._masonry_total_height = max(max_actual_y, viewport_height + 1)
                    strict_rows = max(1, math.ceil(total_items / max(1, num_columns)))
                    implied_avg = self._masonry_total_height / strict_rows
                    if 10.0 < implied_avg < 5000.0 and implied_avg > self._get_strict_virtual_avg_height():
                        self._strict_virtual_avg_height = implied_avg
                        # Also grow masonry_avg_h so canonical domain covers
                        # the actual tail content (otherwise the scrollbar max
                        # is too small to reach the true bottom by scrolling).
                        if implied_avg > float(getattr(self, '_strict_masonry_avg_h', 0.0) or 0.0):
                            self._strict_masonry_avg_h = implied_avg
                    self._log_flow(
                        "MASONRY",
                        f"Strict tail extend: total_height {previous_height}->{self._masonry_total_height}",
                        throttle_key="strict_tail_extend",
                        every_s=1.0,
                    )
            
                # RE-ALIGN VIEW (ANCHOR OR RESCUE)
                anchor_suppressed = self._scrollbar_dragging or (time.time() < getattr(self, '_suppress_anchor_until', 0.0))
                release_anchor_active = (
                    getattr(self, '_drag_release_anchor_active', False)
                    and self._drag_release_anchor_idx is not None
                    and time.time() < getattr(self, '_drag_release_anchor_until', 0.0)
                )
                if strict_mode:
                    sb = self.verticalScrollBar()
                    stable_max = self._strict_canonical_domain_max(source_model)
                    old_val = sb.value()
                    old_max = max(1, sb.maximum())
                    print(f"[STRICT-DOMAIN] masonry_avg_h={self._strict_masonry_avg_h:.1f}  virtual_avg_h={self._strict_virtual_avg_height:.1f}  domain={stable_max}  old_max={old_max}  delta={stable_max - old_max}")
                    if self._scrollbar_dragging or self._drag_preview_mode:
                        self._restore_strict_drag_domain(sb=sb, source_model=source_model)
                    else:
                        # Block signals so the range change doesn't corrupt
                        # _last_stable_scroll_value via _on_scroll_value_changed.
                        prev_block = sb.blockSignals(True)
                        sb.setRange(0, stable_max)
                        # If release-lock is active, re-anchor the value to the
                        # locked page so the thumb stays put even if canonical
                        # domain grew (from avg_height adaptation).
                        release_lock_page = getattr(self, '_release_page_lock_page', None)
                        release_lock_live = (
                            release_lock_page is not None
                            and time.time() < float(getattr(self, '_release_page_lock_until', 0.0) or 0.0)
                        )
                        if self._pending_edge_snap == "bottom":
                            sb.setValue(stable_max)
                            self._current_page = max(0, (total_items - 1) // source_model.PAGE_SIZE) if source_model else self._current_page
                        elif self._pending_edge_snap == "top":
                            sb.setValue(0)
                            self._current_page = 0
                        elif release_lock_live:
                            page_size = int(getattr(source_model, 'PAGE_SIZE', 1000) or 1000)
                            # Prefer actual masonry y-coordinate of the locked page's
                            # first item so the viewport aligns with real content
                            # (formula-based fraction drifts when real heights != avg_h).
                            _lock_start_idx = int(release_lock_page) * page_size
                            _lock_item = None
                            for _it in self._masonry_items:
                                if _it.get('index', -1) >= _lock_start_idx:
                                    _lock_item = _it
                                    break
                            if _lock_item is not None:
                                target_val = max(0, min(int(_lock_item['y']), stable_max))
                            else:
                                # Fallback: item-based fraction.
                                page_frac = max(0.0, min(1.0, (_lock_start_idx) / max(1, total_items)))
                                target_val = int(round(page_frac * stable_max))
                            sb.setValue(max(0, min(target_val, stable_max)))
                            self._last_stable_scroll_value = sb.value()
                        else:
                            # Ratio-preserving: keep thumb at the same visual fraction.
                            ratio = old_val / old_max
                            target_val = max(0, min(int(round(ratio * stable_max)), stable_max))
                            sb.setValue(target_val)
                        sb.blockSignals(prev_block)
                elif release_anchor_active:
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
                if (not strict_mode) and self._pending_edge_snap == "bottom":
                    sb = self.verticalScrollBar()
                    sb.setRange(0, max(0, self._masonry_total_height - viewport_height))
                    sb.setValue(sb.maximum())
                    self._current_page = max(0, (total_items - 1) // source_model.PAGE_SIZE) if source_model else self._current_page
                elif (not strict_mode) and self._pending_edge_snap == "top":
                    sb = self.verticalScrollBar()
                    sb.setRange(0, max(0, self._masonry_total_height - viewport_height))
                    sb.setValue(0)
                    self._current_page = 0
                if (not strict_mode) and anchor_index != -1 and not anchor_suppressed and not release_anchor_active:
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
                if not strict_mode:
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

            # Finalize pending Home/End navigation now that masonry items exist.
            if getattr(self, '_pending_home_end_nav', None) is not None:
                self._finish_home_end_nav()

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
