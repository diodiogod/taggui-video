from widgets.image_list_shared import *  # noqa: F401,F403
from widgets.image_list_masonry_context import MasonryContext
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

    def _create_masonry_context(self) -> MasonryContext:
        source_model = self.model().sourceModel() if hasattr(self.model(), "sourceModel") else self.model()
        strategy = self._get_masonry_strategy(source_model) if source_model else "full_compat"
        strict_mode = strategy == "windowed_strict"
        column_width = self.current_thumbnail_size
        spacing = 2
        viewport_width = self.viewport().width()
        # viewport().width() is already the drawable area (excluding scrollbars),
        # so only apply explicit masonry side padding here.
        horizontal_padding = int(getattr(self, "_masonry_horizontal_padding", 0) or 0)
        avail_width = viewport_width - horizontal_padding
        num_columns = max(1, avail_width // (column_width + spacing))
        return MasonryContext(
            source_model=source_model,
            strategy=strategy,
            strict_mode=strict_mode,
            column_width=column_width,
            spacing=spacing,
            viewport_width=viewport_width,
            num_columns=num_columns,
        )

    def _clear_enrichment_pause(self, source_model):
        if source_model and hasattr(source_model, "_enrichment_paused"):
            source_model._enrichment_paused.clear()

    def _wait_and_retry_masonry(self, source_model, *, delay_ms: int):
        self._masonry_calculating = False
        self._clear_enrichment_pause(source_model)
        QTimer.singleShot(delay_ms, self._calculate_masonry_layout)

    def _prepare_buffered_window_items(self, ctx: MasonryContext) -> bool:
        source_model = ctx.source_model
        planner = self._get_masonry_window_planner_service()
        local_anchor_mode = self._use_local_anchor_masonry(source_model)

        ctx.page_size = source_model.PAGE_SIZE if hasattr(source_model, "PAGE_SIZE") else 1000
        ctx.total_items = source_model._total_count if hasattr(source_model, "_total_count") else 0

        ctx.current_page = planner.resolve_current_page(
            source_model=source_model,
            page_size=ctx.page_size,
            total_items=ctx.total_items,
            strict_mode=ctx.strict_mode,
            local_anchor_mode=local_anchor_mode,
        )
        ctx.window_buffer = planner.get_window_buffer()
        window_info = planner.compute_window_bounds(
            total_items=ctx.total_items,
            page_size=ctx.page_size,
            current_page=ctx.current_page,
            strategy=ctx.strategy,
            loaded_count=len(ctx.items_data),
            window_buffer=ctx.window_buffer,
        )
        ctx.max_page = window_info["max_page"]
        ctx.full_layout_mode = window_info["full_layout_mode"]
        ctx.window_start_page = window_info["window_start_page"]
        ctx.window_end_page = window_info["window_end_page"]
        ctx.min_idx = window_info["min_idx"]
        ctx.max_idx = window_info["max_idx"]

        if ctx.strict_mode:
            seed = getattr(self, "_stable_avg_item_height", 0.0)
            if (
                getattr(self, "_strict_virtual_avg_height", 0.0) <= 1.0
                and isinstance(seed, (int, float))
                and 10.0 < float(seed) < 5000.0
            ):
                self._strict_virtual_avg_height = float(seed)
            ctx.avg_h = self._get_strict_virtual_avg_height()
            self._strict_masonry_avg_h = float(ctx.avg_h)
        else:
            ctx.avg_h = getattr(self, "_stable_avg_item_height", 100.0)
            if ctx.avg_h < 1:
                ctx.avg_h = 100.0

        horizontal_padding = int(getattr(self, "_masonry_horizontal_padding", 0) or 0)
        ctx.avail_width = ctx.viewport_width - horizontal_padding
        ctx.num_cols_est = max(1, ctx.avail_width // (ctx.column_width + ctx.spacing))

        if ctx.strict_mode and (not ctx.full_layout_mode) and hasattr(source_model, "_pages"):
            loaded_pages_now = set(source_model._pages.keys())
            target_ready = int(ctx.current_page) in loaded_pages_now
            if target_ready:
                try:
                    target_ready = len(source_model._pages.get(int(ctx.current_page), [])) > 0
                except Exception:
                    target_ready = False
            if not target_ready:
                self._strict_waiting_target_page = int(ctx.current_page)
                self._strict_waiting_window_pages = (int(ctx.window_start_page), int(ctx.window_end_page))
                resize_anchor_live = (
                    getattr(self, '_resize_anchor_page', None) is not None
                    and time.time() <= float(getattr(self, '_resize_anchor_until', 0.0) or 0.0)
                )
                wait_count = getattr(self, "_strict_wait_count", 0) + 1
                self._strict_wait_count = wait_count
                snapped_to_loaded_page = False
                if wait_count > 20 and not resize_anchor_live:
                    loaded_list = sorted(loaded_pages_now) if loaded_pages_now else []
                    sb = self.verticalScrollBar()
                    sb_val = int(sb.value())
                    sb_max = int(sb.maximum())
                    last_page = max(0, int(ctx.max_page) - 1)
                    at_top_edge = (
                        sb_val <= 2
                        or int(ctx.current_page) <= 0
                        or getattr(self, '_stick_to_edge', None) == "top"
                    )
                    at_bottom_edge = (
                        (sb_max > 0 and sb_val >= sb_max - 2)
                        or int(ctx.current_page) >= last_page
                        or getattr(self, '_stick_to_edge', None) == "bottom"
                    )
                    release_lock_live = (
                        getattr(self, '_release_page_lock_page', None) is not None
                        and time.time() < float(getattr(self, '_release_page_lock_until', 0.0) or 0.0)
                    )
                    restore_lock_live = getattr(self, '_restore_target_page', None) is not None
                    # Avoid snap-back teleports while user is intentionally at edges
                    # or when restore/release lock is steering ownership.
                    if loaded_list and not (at_top_edge or at_bottom_edge or release_lock_live or restore_lock_live):
                        old_page = int(ctx.current_page)
                        ctx.current_page = min(loaded_list, key=lambda p: abs(int(p) - old_page))
                        ctx.window_start_page = max(0, ctx.current_page - ctx.window_buffer)
                        ctx.window_end_page = min(ctx.max_page - 1, ctx.current_page + ctx.window_buffer)
                        ctx.min_idx = ctx.window_start_page * ctx.page_size
                        ctx.max_idx = min(ctx.total_items, (ctx.window_end_page + 1) * ctx.page_size)
                        print(
                            f"[MASONRY] Snap to loaded page {ctx.current_page} after "
                            f"{wait_count} retries (scroll-derived: {old_page}, "
                            f"loaded: {loaded_list[0]}-{loaded_list[-1]})"
                        )
                        self._strict_wait_count = 0
                        snapped_to_loaded_page = True
                    else:
                        # Keep retrying the target edge page instead of teleporting.
                        self._strict_wait_count = min(wait_count, 80)
                if not snapped_to_loaded_page:
                    if wait_count > 40:
                        # Keep waiting while resize anchor is active; avoid snapping
                        # to a different loaded page and losing viewport context.
                        self._strict_wait_count = 20
                    try:
                        if hasattr(source_model, "ensure_pages_for_range"):
                            start_row = ctx.window_start_page * ctx.page_size
                            end_row = min(ctx.total_items - 1, ((ctx.window_end_page + 1) * ctx.page_size) - 1)
                            source_model.ensure_pages_for_range(start_row, end_row)
                        else:
                            for p in range(ctx.window_start_page, ctx.window_end_page + 1):
                                if p not in source_model._pages and p not in source_model._loading_pages:
                                    source_model._request_page_load(p)
                    except Exception:
                        pass
                    self._log_flow(
                        "MASONRY",
                        f"Waiting target page {ctx.current_page} before strict calc "
                        f"(window {ctx.window_start_page}-{ctx.window_end_page}, retry {wait_count})",
                        throttle_key="strict_wait_target_page",
                        every_s=0.5,
                    )
                    self._wait_and_retry_masonry(source_model, delay_ms=120)
                    return False
            else:
                self._strict_wait_count = 0
                self._strict_waiting_target_page = None
                self._strict_waiting_window_pages = None
        elif getattr(self, "_strict_waiting_target_page", None) is not None:
            self._strict_waiting_target_page = None
            self._strict_waiting_window_pages = None

        loaded_pages_sig = tuple(sorted(source_model._pages.keys())) if hasattr(source_model, "_pages") else ()
        window_signature = (
            ctx.window_start_page,
            ctx.window_end_page,
            loaded_pages_sig,
            ctx.num_columns,
            self.current_thumbnail_size,
            self.viewport().width(),
            ctx.full_layout_mode,
        )
        if (
            window_signature == self._last_masonry_window_signature
            and self._last_masonry_signal != "enrichment_complete"
        ):
            self._log_flow(
                "MASONRY",
                "Skipping calc: unchanged window signature",
                throttle_key="masonry_same_window",
                every_s=0.8,
            )
            self._masonry_calculating = False
            self._clear_enrichment_pause(source_model)
            return False
        self._last_masonry_window_signature = window_signature

        for p in range(
            max(0, ctx.current_page - ctx.window_buffer),
            min(ctx.max_page, ctx.current_page + ctx.window_buffer + 1),
        ):
            if p not in source_model._pages and p not in source_model._loading_pages:
                source_model._request_page_load(p)

        filtered_items = [item for item in ctx.items_data if ctx.min_idx <= item[0] < ctx.max_idx]
        if ctx.strict_mode and (not ctx.full_layout_mode) and not filtered_items:
            try:
                if hasattr(source_model, "ensure_pages_for_range"):
                    start_row = ctx.window_start_page * ctx.page_size
                    end_row = min(ctx.total_items - 1, ((ctx.window_end_page + 1) * ctx.page_size) - 1)
                    source_model.ensure_pages_for_range(start_row, end_row)
                else:
                    for p in range(ctx.window_start_page, ctx.window_end_page + 1):
                        if p not in source_model._pages and p not in source_model._loading_pages:
                            source_model._request_page_load(p)
            except Exception:
                pass
            self._log_flow(
                "MASONRY",
                f"Waiting window items for strict calc (window {ctx.window_start_page}-{ctx.window_end_page})",
                throttle_key="strict_wait_window_items",
                every_s=0.5,
            )
            self._wait_and_retry_masonry(source_model, delay_ms=120)
            return False

        ctx.items_data = planner.build_items_with_spacers(
            filtered_items=filtered_items,
            min_idx=ctx.min_idx,
            max_idx=ctx.max_idx,
            total_items=ctx.total_items,
            num_cols_est=ctx.num_cols_est,
            avg_h=ctx.avg_h,
            avail_width=ctx.avail_width,
            column_width=ctx.column_width,
            spacing=ctx.spacing,
        )

        mode = "full" if ctx.full_layout_mode else ctx.strategy
        self._log_flow(
            "MASONRY",
            f"Calc start: tokens={len(ctx.items_data)} window_pages={ctx.window_start_page}-{ctx.window_end_page} "
            f"current_page={ctx.current_page} mode={mode}",
        )
        return True

    def _calculate_masonry_layout(self):
        """Calculate masonry layout positions for all items (async with thread)."""
        if not self.use_masonry or not self.model():
            return
        if self.model().rowCount() == 0:
            return

        ctx = self._create_masonry_context()
        source_model = ctx.source_model

        if ctx.strict_mode and self._scrollbar_dragging:
            self._masonry_recalc_pending = True
            return
        if source_model and hasattr(source_model, "_paginated_mode") and source_model._paginated_mode:
            if not source_model._pages:
                self._log_flow(
                    "MASONRY",
                    "Skipping calc: no pages loaded yet",
                    throttle_key="masonry_no_pages",
                    every_s=1.0,
                )
                return

        if self._masonry_calculating:
            self._masonry_recalc_pending = True
            return
        self._masonry_recalc_pending = False

        current_time = time.time()
        if hasattr(self, "_last_masonry_done_time") and self._last_masonry_done_time > 0:
            time_since_done = (current_time - self._last_masonry_done_time) * 1000
            if time_since_done < 500:
                remaining = int(500 - time_since_done)
                self._log_flow(
                    "MASONRY",
                    f"Grace period active: {remaining}ms remaining",
                    throttle_key="masonry_grace",
                    every_s=0.5,
                )
                QTimer.singleShot(remaining, self._calculate_masonry_layout)
                return

        self._get_masonry_submission_service().prepare_executor()
        self._masonry_calculating = True
        self._masonry_start_time = time.time()
        self._log_diag(
            "calc.begin",
            source_model=source_model,
            throttle_key="diag_calc_begin",
            every_s=0.25,
            extra=(
                f"signal={getattr(self, '_last_masonry_signal', None)} "
                f"strict={ctx.strict_mode}"
            ),
        )

        # NOTE: Do NOT invalidate the incremental cache here.  The cache will
        # be rebuilt from the full result on completion (completion_service line
        # ~367).  Keeping the old cache valid during the async computation
        # window allows _on_pages_updated to use the "no new pages → skip"
        # fast path, preventing cascading recalcs that cause layout drift
        # after zoom/resize.
        # (Previous code called invalidate() here, which broke the fast path.)

        if source_model and hasattr(source_model, "_enrichment_paused"):
            source_model._enrichment_paused.set()
            self._log_flow(
                "MASONRY",
                "Paused enrichment for recalculation",
                throttle_key="masonry_pause",
                every_s=0.5,
            )

        if ctx.viewport_width <= 0:
            self._masonry_calculating = False
            return

        try:
            ctx.items_data = self.model().get_filtered_aspect_ratios()
            if not ctx.items_data:
                self._log_flow(
                    "MASONRY",
                    "Skipping calc: no items loaded yet",
                    throttle_key="masonry_no_items",
                    every_s=1.0,
                )
                self._masonry_calculating = False
                self._clear_enrichment_pause(source_model)
                return

            if source_model and hasattr(source_model, "_paginated_mode") and source_model._paginated_mode:
                if not self._prepare_buffered_window_items(ctx):
                    return
            else:
                self._log_flow("MASONRY", f"Calc start (normal mode): items={len(ctx.items_data)}")
        except Exception as e:
            print(f"[MASONRY] Failed to get aspect ratios: {e}")
            import traceback

            traceback.print_exc()
            self._masonry_calculating = False
            self._clear_enrichment_pause(source_model)
            return

        try:
            cache_key = self._get_masonry_cache_key()
        except Exception as e:
            print(f"[MASONRY] CRITICAL ERROR starting calculation: {e}")
            import traceback

            traceback.print_exc()
            self._masonry_calculating = False
            return

        # Capture mode generation so completion can ignore stale results
        # from calculations submitted before a List/Icon mode flip.
        self._masonry_calc_mode_generation = int(
            getattr(self, "_masonry_mode_generation", 0)
        )

        if not self._get_masonry_submission_service().submit_layout_job(
            items_data=ctx.items_data,
            column_width=ctx.column_width,
            spacing=ctx.spacing,
            num_columns=ctx.num_columns,
            cache_key=cache_key,
        ):
            return

        self._check_masonry_completion()
