from widgets.image_list_shared import *  # noqa: F401,F403
from widgets.image_list_masonry_submission_service import MasonrySubmissionService
from widgets.image_list_masonry_window_planner_service import MasonryWindowPlannerService

class ImageListViewCalculationMixin:
    def _get_masonry_submission_service(self) -> MasonrySubmissionService:
        service = getattr(self, "_masonry_submission_service", None)
        if service is None:
            service = MasonrySubmissionService(self)
            self._masonry_submission_service = service
        return service

    def _get_masonry_window_planner_service(self) -> MasonryWindowPlannerService:
        service = getattr(self, "_masonry_window_planner_service", None)
        if service is None:
            service = MasonryWindowPlannerService(self)
            self._masonry_window_planner_service = service
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
            
                planner = self._get_masonry_window_planner_service()
                current_page = planner.resolve_current_page(
                    source_model=source_model,
                    page_size=page_size,
                    total_items=total_items,
                    strict_mode=strict_mode,
                    local_anchor_mode=local_anchor_mode,
                )

                window_buffer = planner.get_window_buffer()
                max_page = (total_items + page_size - 1) // page_size
                window_info = planner.compute_window_bounds(
                    total_items=total_items,
                    page_size=page_size,
                    current_page=current_page,
                    strategy=strategy,
                    loaded_count=len(items_data),
                    window_buffer=window_buffer,
                )
                full_layout_mode = window_info["full_layout_mode"]
                window_start_page = window_info["window_start_page"]
                window_end_page = window_info["window_end_page"]
                min_idx = window_info["min_idx"]
                max_idx = window_info["max_idx"]

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
            
                items_data = planner.build_items_with_spacers(
                    filtered_items=filtered_items,
                    min_idx=min_idx,
                    max_idx=max_idx,
                    total_items=total_items,
                    num_cols_est=num_cols_est,
                    avg_h=avg_h,
                    avail_width=avail_width,
                    column_width=column_width,
                    spacing=spacing,
                )
 

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
