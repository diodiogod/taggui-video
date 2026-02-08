from widgets.image_list_shared import *  # noqa: F401,F403
from widgets.image_list_masonry_submission_service import MasonrySubmissionService

class ImageListViewCalculationMixin:
    def _get_masonry_submission_service(self) -> MasonrySubmissionService:
        service = getattr(self, "_masonry_submission_service", None)
        if service is None:
            service = MasonrySubmissionService(self)
            self._masonry_submission_service = service
        return service

    def _calculate_masonry_layout(self):
        """Calculate masonry layout positions for all items (async with thread)."""
        if not self.use_masonry or not self.model():
            return

        # Skip if model is empty
        if self.model().rowCount() == 0:
            return

        # In buffered pagination mode, skip if no pages loaded yet
        source_model = self.model().sourceModel() if hasattr(self.model(), 'sourceModel') else self.model()
        strategy = self._get_masonry_strategy(source_model) if source_model else "full_compat"
        strict_mode = strategy == "windowed_strict"
        # Strict-mode drag: defer costly/mutating recalcs until release.
        # This prevents scrollbar domain churn while user is selecting a page.
        if strict_mode and self._scrollbar_dragging:
            self._masonry_recalc_pending = True
            return
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
    
        # Recreate executor periodically to prevent thread-pool degradation.
        self._get_masonry_submission_service().prepare_executor()

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
                strategy = self._get_masonry_strategy(source_model)
                strict_mode = strategy == "windowed_strict"
                local_anchor_mode = self._use_local_anchor_masonry(source_model)
            
                # CRITICAL FIX: Compute current page DIRECTLY from scroll position
                # Prefer visible masonry top index (stable), fallback to scroll fraction.
                scroll_val = self.verticalScrollBar().value()
                scroll_max = self.verticalScrollBar().maximum()
                dragging_mode = self._scrollbar_dragging or self._drag_preview_mode
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
                elif strict_mode:
                    if dragging_mode and self._drag_target_page is not None:
                        strict_page = max(0, min(max(0, (total_items - 1) // page_size) if total_items > 0 else 0, int(self._drag_target_page)))
                    elif dragging_mode:
                        slider_pos = int(self.verticalScrollBar().sliderPosition())
                        strict_page = self._strict_page_from_position(slider_pos, source_model)
                    else:
                        strict_page = self._strict_page_from_position(scroll_val, source_model)
                    source_idx = max(0, min(total_items - 1, strict_page * page_size))

                if (not strict_mode) and local_anchor_mode and total_items > 0 and scroll_max > 0:
                    scroll_fraction = max(0.0, min(1.0, scroll_val / scroll_max))
                    source_idx = int(scroll_fraction * total_items)
                elif (not strict_mode) and (not anchor_active) and (not stick_bottom) and (not stick_top) and self._masonry_items:
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
                if (not local_anchor_mode) and (not anchor_active) and (not stick_bottom) and (not stick_top) and total_items > 0 and candidate_page != prev_page:
                    half_page = max(1, page_size // 2)
                    if candidate_page > prev_page:
                        if source_idx < ((prev_page + 1) * page_size + half_page):
                            current_page = prev_page
                    else:
                        if source_idx > (prev_page * page_size - half_page):
                            current_page = prev_page

                # Sticky window right after enrichment/layout refresh.
                if (not local_anchor_mode) and (not anchor_active) and (not stick_bottom) and (not stick_top) and time.time() < getattr(self, '_masonry_sticky_until', 0.0):
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
                if total_items > 0 and strategy != "windowed_strict":
                    coverage = loaded_count / total_items
                    if coverage >= 0.95 and total_items <= 50000:
                        full_layout_mode = True

                # Estimate row/column metrics for spacer heights once
                if strict_mode:
                    seed = getattr(self, "_stable_avg_item_height", 0.0)
                    if getattr(self, "_strict_virtual_avg_height", 0.0) <= 1.0 and isinstance(seed, (int, float)) and 10.0 < float(seed) < 5000.0:
                        self._strict_virtual_avg_height = float(seed)
                    avg_h = self._get_strict_virtual_avg_height()
                    # Store the avg_h used to BUILD this masonry layout so
                    # _strict_canonical_domain_max() uses the same value.
                    # This prevents the coordinate-space mismatch where the
                    # domain uses post-completion avg_h but spacers use this one.
                    self._strict_masonry_avg_h = float(avg_h)
                else:
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

                # Strict mode guard: do not build a spacer-only layout for an unloaded target window.
                # Wait until the target page is resident to avoid empty-list regressions.
                if strict_mode and (not full_layout_mode) and hasattr(source_model, "_pages"):
                    loaded_pages_now = set(source_model._pages.keys())
                    target_ready = int(current_page) in loaded_pages_now
                    if target_ready:
                        try:
                            target_ready = len(source_model._pages.get(int(current_page), [])) > 0
                        except Exception:
                            target_ready = False
                    if not target_ready:
                        wait_count = getattr(self, '_strict_wait_count', 0) + 1
                        self._strict_wait_count = wait_count

                        # Safety net: after many retries, snap to loaded pages to
                        # break deadlocks (e.g. domain mismatch causing page drift).
                        if wait_count > 20:
                            loaded_list = sorted(loaded_pages_now) if loaded_pages_now else []
                            if loaded_list:
                                old_page = int(current_page)
                                current_page = loaded_list[len(loaded_list) // 2]
                                window_start_page = max(0, current_page - window_buffer)
                                window_end_page = min(max_page - 1, current_page + window_buffer)
                                min_idx = window_start_page * page_size
                                max_idx = min(total_items, (window_end_page + 1) * page_size)
                                print(f"[MASONRY] Snap to loaded page {current_page} after "
                                      f"{wait_count} retries (scroll-derived: {old_page}, "
                                      f"loaded: {loaded_list[0]}-{loaded_list[-1]})")
                                self._strict_wait_count = 0
                            # Fall through to proceed with layout
                        else:
                            # Request page loads and wait for them
                            try:
                                if hasattr(source_model, 'ensure_pages_for_range'):
                                    start_row = window_start_page * page_size
                                    end_row = min(total_items - 1, ((window_end_page + 1) * page_size) - 1)
                                    source_model.ensure_pages_for_range(start_row, end_row)
                                else:
                                    for p in range(window_start_page, window_end_page + 1):
                                        if p not in source_model._pages and p not in source_model._loading_pages:
                                            source_model._request_page_load(p)
                            except Exception:
                                pass
                            self._log_flow(
                                "MASONRY",
                                f"Waiting target page {current_page} before strict calc "
                                f"(window {window_start_page}-{window_end_page}, retry {wait_count})",
                                throttle_key="strict_wait_target_page",
                                every_s=0.5,
                            )
                            self._masonry_calculating = False
                            if source_model and hasattr(source_model, '_enrichment_paused'):
                                source_model._enrichment_paused.clear()
                            from PySide6.QtCore import QTimer
                            QTimer.singleShot(120, self._calculate_masonry_layout)
                            return
                    else:
                        self._strict_wait_count = 0

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

                # Strict mode guard (secondary): if the target window still has no real items,
                # keep current layout and retry after requesting pages.
                if strict_mode and (not full_layout_mode) and not filtered_items:
                    try:
                        if hasattr(source_model, 'ensure_pages_for_range'):
                            start_row = window_start_page * page_size
                            end_row = min(total_items - 1, ((window_end_page + 1) * page_size) - 1)
                            source_model.ensure_pages_for_range(start_row, end_row)
                        else:
                            for p in range(window_start_page, window_end_page + 1):
                                if p not in source_model._pages and p not in source_model._loading_pages:
                                    source_model._request_page_load(p)
                    except Exception:
                        pass
                    self._log_flow(
                        "MASONRY",
                        f"Waiting window items for strict calc (window {window_start_page}-{window_end_page})",
                        throttle_key="strict_wait_window_items",
                        every_s=0.5,
                    )
                    self._masonry_calculating = False
                    if source_model and hasattr(source_model, '_enrichment_paused'):
                        source_model._enrichment_paused.clear()
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(120, self._calculate_masonry_layout)
                    return
            
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
                        f"current_page={current_page} mode={strategy}"
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
            cache_key = self._get_masonry_cache_key()
        except Exception as e:
            print(f"[MASONRY] CRITICAL ERROR starting calculation: {e}")
            import traceback
            traceback.print_exc()
            self._masonry_calculating = False
            return

        if not self._get_masonry_submission_service().submit_layout_job(
            items_data=items_data,
            column_width=column_width,
            spacing=spacing,
            num_columns=num_columns,
            cache_key=cache_key,
        ):
            return

        # Poll for completion using QTimer
        self._check_masonry_completion()
