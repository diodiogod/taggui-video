from widgets.image_list_shared import *  # noqa: F401,F403

class ImageListViewScrollMixin:
    def _on_mouse_scroll_stopped(self):
        """Called when mouse scrolling stops (200ms after last wheel event)."""
        self._mouse_scrolling = False
        # print("[SCROLL] Mouse scroll stopped")

        # Notify model that scrolling ended (allows deferred background work).
        source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else None
        if source_model and hasattr(source_model, 'set_scrolling_state'):
            source_model.set_scrolling_state(False)

        # DON'T flush cache saves immediately - still might be scrolling
        # Just mark that scroll detection stopped (200ms is too short for flush)

        # DON'T clear queues - rebuilding is expensive and causes freeze
        # Just let the preload continue from where it left off
        # Queues will self-correct as items get loaded

        # Trigger preload immediately (no delay)
        self._idle_preload_timer.stop()
        self._idle_preload_timer.start(0)  # Immediate start - no delay

        # Ensure one repaint after wheel-scroll throttle ends. Without this,
        # the last throttled frame can leave viewport stale/blank until click.
        self.viewport().update()

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
            # Avoid forcing repaint every scroll tick; Qt's native scrolling
            # already repaints. Extra forced updates can block input.
            import time
            now = time.time()

            # Preload thumbnails for smoother scrolling (only nearby items)
            if not hasattr(self, '_last_nearby_preload_time'):
                self._last_nearby_preload_time = 0.0
            if (now - self._last_nearby_preload_time) >= 0.12:  # 120ms cadence
                self._last_nearby_preload_time = now
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
        strategy = self._get_masonry_strategy(source_model)
        strict_mode = strategy == "windowed_strict"
        if strict_mode:
            # Enforce canonical domain to prevent strict owner collapse.
            sb = self.verticalScrollBar()
            canonical = self._strict_canonical_domain_max(source_model)
            if sb.maximum() != canonical:
                old_pos = max(0, int(sb.sliderPosition()))
                old_max_raw = int(sb.maximum())
                old_max_v = max(1, old_max_raw)
                was_at_top = old_pos <= 2
                was_at_bottom = old_max_raw > 0 and old_pos >= old_max_raw - 2
                tail_target = None
                bottom_intent = False
                top_intent = False
                try:
                    total_items = int(getattr(source_model, '_total_count', 0) or 0)
                    page_size = int(getattr(source_model, 'PAGE_SIZE', 1000) or 1000)
                    last_page = max(0, (total_items - 1) // max(1, page_size))
                    cur_page = getattr(self, '_current_page', None)
                    release_lock_page = getattr(self, '_release_page_lock_page', None)
                    bottom_intent = (
                        was_at_bottom
                        or getattr(self, '_stick_to_edge', None) == "bottom"
                        or (
                            isinstance(release_lock_page, int)
                            and release_lock_page >= last_page
                        )
                        or (
                            isinstance(cur_page, int)
                            and cur_page >= last_page
                            and old_max_raw > 0
                            and old_pos >= int(old_max_v * 0.80)
                        )
                    )
                    top_intent = (
                        was_at_top
                        or getattr(self, '_stick_to_edge', None) == "top"
                    )
                    if total_items > 0 and self._masonry_items:
                        tail_idx = total_items - 1
                        tail_item = None
                        for it in self._masonry_items:
                            if int(it.get('index', -1)) == tail_idx:
                                tail_item = it
                                break
                        if tail_item is not None:
                            tail_bottom = int(tail_item.get('y', 0)) + int(tail_item.get('height', 0))
                            tail_target = max(0, min(tail_bottom - max(1, self.viewport().height()), canonical))
                except Exception:
                    bottom_intent = was_at_bottom
                    top_intent = was_at_top
                    tail_target = None
                restore_target = (
                    self._get_restore_anchor_scroll_value(source_model, canonical)
                    if hasattr(self, '_get_restore_anchor_scroll_value')
                    else None
                )
                if restore_target is not None:
                    new_pos = int(restore_target)
                elif bottom_intent:
                    # Don't force canonical max; it can be below/above real tail
                    # during avg-height transitions and causes void-jumps.
                    if tail_target is not None:
                        new_pos = int(tail_target)
                    else:
                        new_pos = max(0, min(old_pos, canonical))
                elif top_intent:
                    new_pos = 0
                else:
                    ratio = max(0.0, min(1.0, old_pos / old_max_v))
                    new_pos = int(round(ratio * canonical))
                prev_block = sb.blockSignals(True)
                try:
                    sb.setRange(0, canonical)
                    sb.setValue(max(0, min(new_pos, canonical)))
                finally:
                    sb.blockSignals(prev_block)
            scroll_offset = sb.value()
            scroll_max = sb.maximum()
        if scroll_max <= 0 and not strict_mode:
            # Can't determine position yet in non-strict mode
            return

        total_pages = (source_model._total_count + source_model.PAGE_SIZE - 1) // source_model.PAGE_SIZE
        last_page = max(0, total_pages - 1)
        prev_stick = getattr(self, '_stick_to_edge', None)
        if strict_mode and (not self._scrollbar_dragging) and (not self._drag_preview_mode):
            if scroll_max > 0 and scroll_offset >= scroll_max - 2:
                self._stick_to_edge = "bottom"
            elif scroll_offset <= 2:
                self._stick_to_edge = "top"
        # Strict tail clamp: when the real last item is materialized, avoid
        # entering void below it (canonical domain can be larger than content).
        if strict_mode and (not self._scrollbar_dragging) and (not self._drag_preview_mode):
            try:
                total_items_i = int(getattr(source_model, '_total_count', 0) or 0)
                if total_items_i > 0 and self._masonry_items:
                    tail_idx = total_items_i - 1
                    tail_item = None
                    for it in self._masonry_items:
                        if int(it.get('index', -1)) == tail_idx:
                            tail_item = it
                            break
                    if tail_item is not None:
                        tail_bottom = int(tail_item.get('y', 0)) + int(tail_item.get('height', 0))
                        tail_scroll = max(0, tail_bottom - max(1, self.viewport().height()))
                        sb = self.verticalScrollBar()
                        if scroll_offset > tail_scroll + 8 and getattr(self, '_stick_to_edge', None) != "bottom":
                            prev_block = sb.blockSignals(True)
                            try:
                                sb.setValue(max(0, min(tail_scroll, sb.maximum())))
                            finally:
                                sb.blockSignals(prev_block)
                            scroll_offset = sb.value()
                            self._stick_to_edge = "bottom"
                        if scroll_offset >= max(0, tail_scroll - 2):
                            self._stick_to_edge = "bottom"
                            self._current_page = last_page
            except Exception:
                pass
        edge_snap_active = (not strict_mode) and self._pending_edge_snap is not None and current_time < getattr(self, '_pending_edge_snap_until', 0.0)
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
        local_anchor_mode = self._use_local_anchor_masonry(source_model)
        release_lock_active = (
            strict_mode
            and (not dragging_mode)
            and self._release_page_lock_page is not None
            and current_time < float(getattr(self, '_release_page_lock_until', 0.0) or 0.0)
        )
        if strict_mode and (not dragging_mode) and (not release_lock_active) and self._release_page_lock_page is not None:
            self._release_page_lock_page = None
            self._release_page_lock_until = 0.0
        current_page = None
        # Restore override from main_window scroll restore
        restore_page = getattr(self, '_restore_target_page', None)
        if restore_page is not None and not dragging_mode:
            current_page = max(0, min(last_page, int(restore_page)))
        # Resize/zoom anchor override keeps ownership stable while viewport
        # geometry and strict domains are being recalculated.
        resize_page = getattr(self, '_resize_anchor_page', None)
        resize_until = float(getattr(self, '_resize_anchor_until', 0.0) or 0.0)
        if current_page is None and resize_page is not None and not dragging_mode:
            if current_time <= resize_until:
                current_page = max(0, min(last_page, int(resize_page)))
            else:
                self._resize_anchor_page = None
                self._resize_anchor_until = 0.0
        if current_page is not None:
            pass  # skip all other derivation
        elif dragging_mode:
            if strict_mode:
                # Strict mode: map using canonical domain.
                slider_pos = int(self.verticalScrollBar().sliderPosition())
                self._drag_target_page = self._strict_page_from_position(slider_pos, source_model)
            else:
                self._drag_target_page = self._page_from_scroll_fraction(
                    source_model._total_count, source_model.PAGE_SIZE, scroll_offset, scroll_max, use_slider=True
                )
            current_page = self._drag_target_page
        if stick_top:
            current_page = 0
            if scroll_offset > 0:
                self.verticalScrollBar().setValue(0)
                scroll_offset = 0
        elif stick_bottom:
            current_page = last_page
            target_bottom_scroll = max(0, min(scroll_offset, scroll_max))
            if strict_mode and self._masonry_items:
                try:
                    total_items_i = int(getattr(source_model, '_total_count', 0) or 0)
                    if total_items_i > 0:
                        tail_idx = total_items_i - 1
                        tail_item = None
                        for it in self._masonry_items:
                            if int(it.get('index', -1)) == tail_idx:
                                tail_item = it
                                break
                        if tail_item is not None:
                            tail_bottom = int(tail_item.get('y', 0)) + int(tail_item.get('height', 0))
                            target_bottom_scroll = max(0, min(tail_bottom - max(1, self.viewport().height()), scroll_max))
                except Exception:
                    target_bottom_scroll = max(0, min(scroll_offset, scroll_max))
            if scroll_offset != target_bottom_scroll:
                self.verticalScrollBar().setValue(target_bottom_scroll)
                scroll_offset = target_bottom_scroll
        elif release_lock_active:
            current_page = max(0, min(last_page, int(self._release_page_lock_page)))
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
        # Prefer viewport-visible masonry ownership in both strict/non-strict modes.
        # Scrollbar-ratio ownership drifts when canonical domain != real tail height.
        if current_page is None and (not dragging_mode) and self.use_masonry and self._masonry_items:
            viewport_h = self.viewport().height()
            viewport_rect = QRect(0, scroll_offset, self.viewport().width(), viewport_h)
            visible_items = self._get_masonry_visible_items(viewport_rect)
            real_items = [it for it in visible_items if it.get('index', -1) >= 0]
            if real_items:
                total_items_i = int(getattr(source_model, '_total_count', 0) or 0)
                tail_idx = total_items_i - 1 if total_items_i > 0 else -1
                head_idx = 0
                indices = [int(it.get('index', -1)) for it in real_items]
                if tail_idx >= 0 and tail_idx in indices:
                    current_page = last_page
                    self._stick_to_edge = "bottom"
                elif head_idx in indices:
                    current_page = 0
                    self._stick_to_edge = "top"
                else:
                    top_idx = min(real_items, key=lambda x: x['rect'].y())['index']
                    current_page = max(0, min(last_page, top_idx // source_model.PAGE_SIZE))

        if current_page is None and strict_mode:
            current_page = self._strict_page_from_position(scroll_offset, source_model)
        # Local-anchor mode fallback: page ownership from scrollbar fraction.
        if current_page is None and local_anchor_mode:
            if dragging_mode:
                baseline_max = max(1, int(getattr(self, '_drag_scroll_max_baseline', scroll_max)))
                slider_pos = int(self.verticalScrollBar().sliderPosition())
                frac = max(0.0, min(1.0, slider_pos / baseline_max))
            else:
                frac = max(0.0, min(1.0, (scroll_offset / scroll_max) if scroll_max > 0 else 0.0))
            current_page = max(0, min(last_page, int(round(frac * last_page))))

        # Edge clamp must win at top/bottom only when NOT actively dragging.
        # During strict drag, transient scrollbar range changes can fake edge states.
        if (not strict_mode) and (not dragging_mode) and (not anchor_active) and (not release_lock_active):
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

        # Expire strict drag frozen domain after release anchoring settles.
        if strict_mode and (not dragging_mode):
            if current_time > float(getattr(self, '_strict_drag_frozen_until', 0.0) or 0.0):
                self._strict_drag_frozen_max = 0

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
        if strict_mode and (not dragging_mode):
            if current_page >= last_page:
                self._stick_to_edge = "bottom"
            elif current_page <= 0 and scroll_offset <= 2:
                self._stick_to_edge = "top"
        if prev_stick != getattr(self, '_stick_to_edge', None):
            self._log_flow(
                "STRICT",
                f"Edge lock {prev_stick} -> {getattr(self, '_stick_to_edge', None)} "
                f"page={current_page} scroll={scroll_offset}/{scroll_max}",
                throttle_key="strict_edge_lock_change",
                every_s=0.1,
            )
        prev_page = getattr(self, "_current_page", None)
        self._current_page = current_page
        if strict_mode and prev_page != current_page and (not dragging_mode):
            self._log_flow(
                "STRICT",
                f"Owner page={current_page} scroll={scroll_offset}/{scroll_max} drag={dragging_mode} anchor={anchor_active}",
                throttle_key="strict_owner_page",
                every_s=0.5,
            )

        # Strict-mode drag must not trigger page-load churn. During drag we only
        # track ownership; actual range loading is done once on release.
        if strict_mode and dragging_mode:
            return

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

        # Strict release lock persists for its full duration (4s) to prevent
        # thumb drift from canonical domain growth during post-release masonry
        # recalculations. Do NOT clear early when the page loads.
