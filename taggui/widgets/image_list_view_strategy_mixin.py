from widgets.image_list_shared import *  # noqa: F401,F403
from widgets.image_list_strict_domain_service import StrictScrollDomainService
from widgets.image_list_masonry_incremental_service import MasonryIncrementalService
from utils.diagnostic_logging import diagnostic_print, should_emit_trace_log

class ImageListViewStrategyMixin:
    def _get_live_restore_target_page(self, *, last_page: int | None = None) -> int | None:
        """Return the active restore-owned page while its hold window is still live."""
        restore_page = getattr(self, "_restore_target_page", None)
        if restore_page is None:
            return None

        try:
            restore_until = float(getattr(self, "_restore_anchor_until", 0.0) or 0.0)
        except Exception:
            restore_until = 0.0

        if time.time() > restore_until:
            self._restore_target_page = None
            self._restore_target_global_index = None
            self._restore_anchor_until = 0.0
            return None

        try:
            restore_page = int(restore_page)
        except Exception:
            return None

        if isinstance(last_page, int):
            restore_page = max(0, min(int(last_page), restore_page))
        return restore_page

    def _get_preferred_enrichment_window_pages(
        self,
        source_model,
        *,
        window_buffer: int = 3,
    ) -> tuple[int, int] | None:
        """Prefer the visible masonry window when choosing paginated repair pages."""
        if not source_model or not getattr(source_model, "_paginated_mode", False):
            return None

        try:
            total_items = int(getattr(source_model, "_total_count", 0) or 0)
            page_size = int(getattr(source_model, "PAGE_SIZE", 1000) or 1000)
        except Exception:
            total_items = 0
            page_size = 1000
        if total_items <= 0 or page_size <= 0:
            return None

        last_page = max(0, (total_items - 1) // page_size)
        window_buffer = max(1, int(window_buffer))

        visible_pages = set()
        try:
            if self.use_masonry and self._masonry_items:
                scroll_offset = int(self.verticalScrollBar().value())
                viewport_rect = QRect(
                    0,
                    scroll_offset,
                    self.viewport().width(),
                    max(1, self.viewport().height()),
                )
                for item in self._get_masonry_visible_items(viewport_rect):
                    idx = int(item.get("index", -1))
                    if idx >= 0:
                        visible_pages.add(max(0, min(last_page, idx // page_size)))
        except Exception:
            visible_pages = set()

        if visible_pages:
            base_start = min(visible_pages)
            base_end = max(visible_pages)
            return (
                max(0, base_start - window_buffer),
                min(last_page, base_end + window_buffer),
            )

        target_global = self._get_current_or_selected_global_index(source_model=source_model)
        if isinstance(target_global, int) and target_global >= 0:
            target_page = max(0, min(last_page, int(target_global // page_size)))
            return (
                max(0, target_page - window_buffer),
                min(last_page, target_page + window_buffer),
            )

        restore_page = self._get_live_restore_target_page(last_page=last_page)
        if isinstance(restore_page, int):
            return (
                max(0, restore_page - window_buffer),
                min(last_page, restore_page + window_buffer),
            )

        cur_page = max(0, min(last_page, int(getattr(self, "_current_page", 0) or 0)))
        return (
            max(0, cur_page - window_buffer),
            min(last_page, cur_page + window_buffer),
        )

    def _image_dimensions_need_enrichment(self, image) -> bool:
        """Return True when an image still has placeholder or missing dimensions."""
        if not image:
            return False
        try:
            dims = getattr(image, 'dimensions', None)
            return (
                not dims
                or dims[0] is None
                or dims[1] is None
                or dims == (512, 512)
            )
        except Exception:
            return False

    def _page_needs_enrichment(self, page_images) -> bool:
        """Return True when any image in the page still needs real dimensions."""
        if not page_images:
            return False
        try:
            return any(self._image_dimensions_need_enrichment(image) for image in page_images if image)
        except Exception:
            return False

    def _window_unenriched_count(self, source_model, window_start: int, window_end: int, *, cap: int = 5) -> int:
        """Count placeholder/missing dimensions in a strict masonry window."""
        count = 0
        try:
            lock = getattr(source_model, '_page_load_lock', None)
            pages = getattr(source_model, '_pages', {})
            if lock is not None:
                with lock:
                    for page_num in range(int(window_start), int(window_end) + 1):
                        for image in pages.get(page_num, []):
                            if image and self._image_dimensions_need_enrichment(image):
                                count += 1
                                if count >= int(cap):
                                    return count
            else:
                for page_num in range(int(window_start), int(window_end) + 1):
                    for image in pages.get(page_num, []):
                        if image and self._image_dimensions_need_enrichment(image):
                            count += 1
                            if count >= int(cap):
                                return count
        except Exception:
            return count
        return count

    def _hold_strict_layout_for_window_enrichment(
        self,
        source_model,
        window_start: int,
        window_end: int,
        *,
        reason: str,
        retry_limit: int = 16,
    ) -> bool:
        """Delay strict masonry layout until the cold window gets one real enriched settle."""
        window_sig = (int(window_start), int(window_end), reason)
        if getattr(self, '_strict_enrich_wait_signature', None) == window_sig:
            self._strict_enrich_wait_count = int(getattr(self, '_strict_enrich_wait_count', 0) or 0) + 1
        else:
            self._strict_enrich_wait_signature = window_sig
            self._strict_enrich_wait_count = 1

        wait_count = int(getattr(self, '_strict_enrich_wait_count', 1) or 1)
        if wait_count > int(retry_limit):
            self._strict_enrich_wait_signature = None
            self._strict_enrich_wait_count = 0
            return False

        try:
            self._check_and_enrich_loaded_pages()
        except Exception:
            pass
        self._log_flow(
            "MASONRY",
            f"Holding strict layout for window enrichment ({reason}: pages {int(window_start)}-{int(window_end)}, retry {wait_count})",
            throttle_key=f"strict_wait_enrich_{reason}",
            every_s=0.5,
        )
        source_model_local = (
            self.model().sourceModel()
            if self.model() and hasattr(self.model(), 'sourceModel')
            else self.model()
        )
        self._wait_and_retry_masonry(source_model_local, delay_ms=140)
        return True

    def _apply_incremental_cache_refresh(self, source_model, *, anchor_global=None, anchor_old_y=None):
        """Rebuild visible masonry items from the incremental page cache."""
        incremental = self._get_masonry_incremental_service()
        self._masonry_items = incremental.assemble_items()
        self._masonry_index_map = None

        if isinstance(anchor_global, int) and anchor_global >= 0 and anchor_old_y is not None:
            try:
                new_anchor_item = self._get_masonry_item_for_global_index(anchor_global)
                if new_anchor_item is not None:
                    new_anchor_y = int(new_anchor_item.get('y', 0))
                    delta_y = int(new_anchor_y) - int(anchor_old_y)
                    if abs(delta_y) > 1:
                        sb = self.verticalScrollBar()
                        target_val = max(0, min(int(sb.value()) + int(delta_y), int(sb.maximum())))
                        prev_block = sb.blockSignals(True)
                        try:
                            sb.setValue(target_val)
                        finally:
                            sb.blockSignals(prev_block)
                        self._last_stable_scroll_value = int(sb.value())
            except Exception:
                pass

        self.viewport().update()

    def _get_current_or_selected_global_index(self, source_model=None) -> int | None:
        """Resolve the current stable global index without mutating selection."""
        target_global = getattr(self, '_selected_global_index', None)
        if isinstance(target_global, int) and target_global >= 0:
            return int(target_global)

        if source_model is None:
            source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else self.model()
        cur = self.currentIndex()
        if not cur.isValid():
            return None
        try:
            src_idx = (
                self.model().mapToSource(cur)
                if self.model() and hasattr(self.model(), 'mapToSource')
                else cur
            )
            if src_idx.isValid() and hasattr(source_model, 'get_global_index_for_row'):
                mapped = source_model.get_global_index_for_row(src_idx.row())
                if isinstance(mapped, int) and mapped >= 0:
                    return int(mapped)
        except Exception:
            return None
        return None

    def _get_active_exact_target_global(self, source_model=None) -> int | None:
        """Return the exact-image target while an exact jump/restore still owns the viewport."""
        now = time.time()

        try:
            settle_until = float(getattr(self, "_exact_jump_settle_until", 0.0) or 0.0)
            settle_target = getattr(self, "_exact_jump_settle_target_global", None)
            if now <= settle_until and isinstance(settle_target, int) and settle_target >= 0:
                return int(settle_target)
        except Exception:
            pass

        try:
            jump_kind = getattr(self, "_last_explicit_jump_kind", None)
            jump_until = float(getattr(self, "_last_explicit_jump_until", 0.0) or 0.0)
            jump_target = getattr(self, "_last_explicit_jump_target_global", None)
            if (
                jump_kind == "index_input"
                and now <= jump_until
                and isinstance(jump_target, int)
                and jump_target >= 0
            ):
                return int(jump_target)
        except Exception:
            pass

        try:
            mw = self.window()
            restore_target = int(getattr(mw, "_restore_target_global_rank", -1) or -1) if mw is not None else -1
            if mw is not None and getattr(mw, "_restore_in_progress", False) and restore_target >= 0:
                return int(restore_target)
        except Exception:
            pass

        return None

    def _get_masonry_item_for_global_index(self, global_index: int):
        """Return the masonry item for a stable global index, if loaded."""
        if not (isinstance(global_index, int) and global_index >= 0):
            return None
        try:
            masonry_map = getattr(self, "_masonry_index_map", None)
            if isinstance(masonry_map, dict):
                item = masonry_map.get(int(global_index))
                if item is not None:
                    return item
            for item in (self._masonry_items or []):
                if int(item.get('index', -1)) == int(global_index):
                    return item
        except Exception:
            return None
        return None

    def _is_masonry_item_near_viewport(self, item, *, margin_px: int | None = None) -> bool:
        """Return True when the masonry item is in or near the current viewport."""
        if not item:
            return False
        try:
            top = int(item.get('y', 0))
            bottom = top + int(item.get('height', 0))
            viewport_top = int(self.verticalScrollBar().value())
            viewport_height = max(1, int(self.viewport().height()))
            viewport_bottom = viewport_top + viewport_height
            if margin_px is None:
                margin_px = max(120, min(360, int(viewport_height * 0.25)))
            expanded_top = viewport_top - max(0, int(margin_px))
            expanded_bottom = viewport_bottom + max(0, int(margin_px))
            return bottom > expanded_top and top < expanded_bottom
        except Exception:
            return False

    def _get_non_restore_reflow_anchor_global(self, source_model=None) -> int | None:
        """Anchor non-startup masonry reflows to nearby selection or viewport center."""
        if source_model is None:
            source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else self.model()
        selected_global = self._get_current_or_selected_global_index(source_model=source_model)
        signal = getattr(self, "_last_masonry_signal", None)
        if signal in {"resize", "resize_drag", "zoom_resize", "thumbnail_size_button"}:
            if isinstance(selected_global, int) and selected_global >= 0:
                return int(selected_global)

        selected_item = self._get_masonry_item_for_global_index(selected_global) if isinstance(selected_global, int) else None
        if selected_item is not None and self._is_masonry_item_near_viewport(selected_item):
            return int(selected_global)

        center_global = self._get_viewport_center_anchor_global()
        if isinstance(center_global, int) and center_global >= 0:
            return int(center_global)

        if isinstance(selected_global, int) and selected_global >= 0:
            return int(selected_global)
        return None

    def _get_transient_owner_anchor_global(self, source_model=None) -> int | None:
        """Return the short-lived anchor item that should own strict page selection."""
        if source_model is None:
            source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else self.model()
        if (
            getattr(self, "_mouse_scrolling", False)
            or getattr(self, "_scrollbar_dragging", False)
            or getattr(self, "_drag_preview_mode", False)
        ):
            return None

        now = time.time()
        strict_jump_until = float(getattr(self, "_strict_jump_until", 0.0) or 0.0)
        if now <= strict_jump_until:
            target_global = getattr(self, "_strict_jump_target_global", None)
            if isinstance(target_global, int) and target_global >= 0:
                return int(target_global)

        idle_until = float(getattr(self, "_idle_anchor_until", 0.0) or 0.0)
        if now <= idle_until:
            target_global = getattr(self, "_idle_anchor_target_global", None)
            if isinstance(target_global, int) and target_global >= 0:
                return int(target_global)

        click_freeze_until = float(getattr(self, "_user_click_selection_frozen_until", 0.0) or 0.0)
        if now < click_freeze_until:
            target_global = self._get_current_or_selected_global_index(source_model=source_model)
            if isinstance(target_global, int) and target_global >= 0:
                return int(target_global)

        return None

    def _get_transient_owner_anchor_page(self, source_model=None, *, last_page: int | None = None) -> int | None:
        """Resolve a temporary strict owner page from the local clicked/idle anchor item."""
        if source_model is None:
            source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else self.model()
        if source_model is None:
            return None

        target_global = self._get_transient_owner_anchor_global(source_model=source_model)
        if not (isinstance(target_global, int) and target_global >= 0):
            return None

        try:
            page_size = int(getattr(source_model, "PAGE_SIZE", 1000) or 1000)
        except Exception:
            page_size = 1000
        if page_size <= 0:
            return None

        target_page = max(0, int(target_global // page_size))
        if isinstance(last_page, int):
            target_page = max(0, min(int(last_page), target_page))
        return target_page

    def _get_viewport_center_anchor_global(self) -> int | None:
        """Return the masonry item nearest the viewport center, if any."""
        try:
            center_y = int(self.verticalScrollBar().value()) + (self.viewport().height() // 2)
            best_idx = None
            best_dist = None
            for item in (self._masonry_items or []):
                idx = int(item.get('index', -1))
                if idx < 0:
                    continue
                item_center = int(item.get('y', 0)) + int(item.get('height', 0)) // 2
                dist = abs(item_center - center_y)
                if best_dist is None or dist < best_dist:
                    best_dist = dist
                    best_idx = idx
            return best_idx
        except Exception:
            return None

    def _activate_selected_idle_anchor(self, source_model=None, hold_s: float = 1.5) -> bool:
        """Temporarily anchor idle masonry settle passes around the local viewport."""
        import time
        if source_model is None:
            source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else self.model()
        if not source_model or not hasattr(source_model, '_paginated_mode') or not source_model._paginated_mode:
            return False
        if self._get_masonry_strategy(source_model) != "windowed_strict":
            return False
        if self._scrollbar_dragging or self._mouse_scrolling:
            return False

        target_global = self._get_non_restore_reflow_anchor_global(source_model=source_model)
        if not (isinstance(target_global, int) and target_global >= 0):
            return False

        page_size = int(getattr(source_model, 'PAGE_SIZE', 1000) or 1000)
        target_page = max(0, int(target_global // max(1, page_size)))
        current_page = max(0, int(getattr(self, '_current_page', 0) or 0))
        window_buffer = 3
        if abs(target_page - current_page) > window_buffer:
            return False
        self._idle_anchor_target_global = int(target_global)
        self._idle_anchor_until = time.time() + max(0.2, float(hold_s))
        return True

    def _activate_resize_anchor(self, source_model=None, hold_s: float = 2.0) -> bool:
        """Anchor strict paginated resize/zoom around current selected global item."""
        import time
        if source_model is None:
            source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else self.model()
        if not source_model or not hasattr(source_model, '_paginated_mode') or not source_model._paginated_mode:
            return False
        if self._get_masonry_strategy(source_model) != "windowed_strict":
            return False
        # Never override startup restore ownership.
        if time.time() <= float(getattr(self, '_restore_anchor_until', 0.0) or 0.0):
            return False

        anchor_global = self._get_non_restore_reflow_anchor_global(source_model=source_model)
        if not (isinstance(anchor_global, int) and anchor_global >= 0):
            return False

        page_size = int(getattr(source_model, 'PAGE_SIZE', 1000) or 1000)
        anchor_page = max(0, int(anchor_global // max(1, page_size)))
        until = time.time() + max(0.2, float(hold_s))
        self._resize_anchor_page = anchor_page
        self._resize_anchor_target_global = int(anchor_global)
        self._resize_anchor_until = until
        try:
            total_items = int(getattr(source_model, '_total_count', 0) or 0)
            last_page = max(0, (total_items - 1) // max(1, page_size))
            sb = self.verticalScrollBar()
            sb_val = int(sb.value())
            sb_max = int(sb.maximum())
            edge_tol = max(2, int(sb.singleStep()) + 8)
            near_bottom = sb_max > 0 and sb_val >= max(0, sb_max - edge_tol)
            near_top = sb_val <= edge_tol
            # Preserve edge intent only when the viewport is physically near
            # that edge right now. Being on page 0/last page is not enough;
            # otherwise clicking image 200 on page 0 gets reinterpreted as
            # "pin to top" and resize snaps back to page 1.
            if anchor_page >= last_page and near_bottom:
                self._stick_to_edge = "bottom"
            elif anchor_page <= 0 and near_top:
                self._stick_to_edge = "top"
            elif getattr(self, '_stick_to_edge', None) in {"top", "bottom"}:
                self._stick_to_edge = None
        except Exception:
            pass
        # Do NOT set _release_page_lock here.  That lock snaps scroll to the
        # first masonry item of the page (y≈0 for page 0), which destroys the
        # user's viewport position during zoom.  The resize anchor +
        # _ensure_selected_anchor_if_needed handle post-zoom centering instead.
        return True

    def _get_masonry_column_metrics(self) -> dict[str, int]:
        """Return stable width/column math shared by all masonry code paths."""
        spacing = 2
        column_width = max(16, int(getattr(self, "current_thumbnail_size", 0) or 16))
        viewport_width = max(1, int(self.viewport().width()))
        horizontal_padding = max(0, int(getattr(self, "_masonry_horizontal_padding", 0) or 0))
        sb = self.verticalScrollBar()
        try:
            sb_width = int(sb.width())
        except Exception:
            sb_width = 0
        # `viewport().width()` is already the drawable content width inside the
        # scroll area. Subtracting the scrollbar/gutter again creates a false
        # dead strip on the right and delays the next column from fitting while
        # the splitter is dragged.
        avail_width = max(1, viewport_width - horizontal_padding)
        num_columns = max(1, avail_width // (column_width + spacing))
        content_width = max(column_width, (num_columns * (column_width + spacing)) - spacing)
        return {
            "column_width": column_width,
            "spacing": spacing,
            "viewport_width": viewport_width,
            "horizontal_padding": horizontal_padding,
            "scrollbar_width": sb_width,
            "avail_width": avail_width,
            "num_columns": num_columns,
            "content_width": content_width,
        }

    def _log_flow(self, component: str, message: str, *, level: str = "DEBUG",
                  throttle_key: str | None = None, every_s: float | None = None):
        """Timestamped, optionally throttled flow logging for masonry/pagination diagnostics."""
        if not should_emit_trace_log(component, message, level=level):
            return

        now = time.time()
        if throttle_key and every_s is not None:
            last = self._flow_log_last.get(throttle_key, 0.0)
            if (now - last) < every_s:
                return
            self._flow_log_last[throttle_key] = now
        ts = time.strftime("%H:%M:%S", time.localtime(now)) + f".{int((now % 1) * 1000):03d}"
        line = f"[{ts}][TRACE][{component}][{level}] {message}"
        print(line)
        # Persist runtime trace for post-mortem without requiring console capture.
        try:
            with open("taggui_runtime_trace.log", "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:
            pass

    def _diag_snapshot(self, source_model=None) -> str:
        """Return a compact state snapshot for strict masonry diagnostics."""
        try:
            if source_model is None:
                source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), "sourceModel") else self.model()

            sb = self.verticalScrollBar()
            scroll_val = int(sb.value())
            scroll_max = int(sb.maximum())
            slider_pos = int(sb.sliderPosition())
            current_page = getattr(self, "_current_page", None)
            stick = getattr(self, "_stick_to_edge", None)
            calc = bool(getattr(self, "_masonry_calculating", False))
            pending = bool(getattr(self, "_masonry_recalc_pending", False))
            timer_active = bool(getattr(self, "_masonry_recalc_timer", None) and self._masonry_recalc_timer.isActive())
            signal = getattr(self, "_last_masonry_signal", None)
            items = len(getattr(self, "_masonry_items", []) or [])
            loaded_pages = len(getattr(source_model, "_pages", {}) or {})
            total_items = int(getattr(source_model, "_total_count", 0) or 0)
            page_size = int(getattr(source_model, "PAGE_SIZE", 1000) or 1000)
            last_page = max(0, (total_items - 1) // max(1, page_size)) if total_items > 0 else 0
            return (
                f"scroll={scroll_val}/{scroll_max} slider={slider_pos} "
                f"page={current_page}/{last_page} stick={stick} "
                f"drag={self._scrollbar_dragging} preview={self._drag_preview_mode} "
                f"calc={calc} pending={pending} timer={timer_active} signal={signal} "
                f"items={items} loaded_pages={loaded_pages} total={total_items}"
            )
        except Exception:
            return "snapshot=unavailable"

    def _log_diag(
        self,
        label: str,
        *,
        source_model=None,
        throttle_key: str | None = None,
        every_s: float | None = None,
        extra: str | None = None,
        level: str = "INFO",
        dedupe: bool = True,
    ):
        """Emit a compact strict-mode diagnostic line."""
        message = f"{label} | {self._diag_snapshot(source_model)}"
        if extra:
            message = f"{message} | {extra}"
        if dedupe:
            key = throttle_key or f"diag:{label}"
            cache = getattr(self, "_diag_last_message", None)
            if cache is None:
                cache = {}
                self._diag_last_message = cache
            if cache.get(key) == message:
                return
            cache[key] = message
        self._log_flow(
            "STRICT",
            message,
            level=level,
            throttle_key=throttle_key,
            every_s=every_s,
        )


    def _use_local_anchor_masonry(self, source_model=None) -> bool:
        """Enable local-anchor/windowed masonry when strict strategy is requested."""
        return self._get_masonry_strategy(source_model) == "windowed_strict"


    def _get_masonry_strategy(self, source_model=None) -> str:
        """Return the active masonry strategy for the current model."""
        is_paginated = bool(
            source_model
            and hasattr(source_model, "_paginated_mode")
            and source_model._paginated_mode
        )
        strategy = "windowed_strict" if is_paginated else "full_compat"

        if strategy != self._masonry_strategy_logged:
            self._masonry_strategy_logged = strategy
            self._log_flow("MASONRY", f"Strategy={strategy}", level="INFO")

        return strategy


    def _page_from_scroll_fraction(self, total_items: int, page_size: int, scroll_value: int,
                                   scroll_max: int, *, use_slider: bool = False) -> int:
        """Map scrollbar fraction to page index deterministically."""
        if total_items <= 0 or page_size <= 0:
            return 0
        last_page = max(0, (total_items - 1) // page_size)
        if use_slider:
            baseline_max = max(1, int(getattr(self, '_drag_scroll_max_baseline', scroll_max if scroll_max > 0 else 1)))
            slider_pos = int(self.verticalScrollBar().sliderPosition())
            frac = max(0.0, min(1.0, slider_pos / baseline_max))
        else:
            frac = max(0.0, min(1.0, (scroll_value / scroll_max) if scroll_max > 0 else 0.0))
        return max(0, min(last_page, int(round(frac * last_page))))


    def _get_strict_domain_service(self) -> StrictScrollDomainService:
        service = getattr(self, "_strict_domain_service", None)
        if service is None:
            service = StrictScrollDomainService(self)
            self._strict_domain_service = service
        return service


    def _get_strict_virtual_avg_height(self) -> float:
        return self._get_strict_domain_service().get_strict_virtual_avg_height()


    def _estimate_strict_virtual_scroll_max(self, source_model=None) -> int:
        return self._get_strict_domain_service().estimate_strict_virtual_scroll_max(source_model)


    def _get_strict_min_domain(self, source_model=None) -> int:
        return self._get_strict_domain_service().get_strict_min_domain(source_model)


    def _get_strict_scroll_domain_max(self, source_model=None, *, include_drag_baseline: bool = False) -> int:
        return self._get_strict_domain_service().get_strict_scroll_domain_max(
            source_model,
            include_drag_baseline=include_drag_baseline,
        )

    # ── Canonical strict-mode domain controller ──────────────────────────

    def _strict_canonical_domain_max(self, source_model=None) -> int:
        return self._get_strict_domain_service().strict_canonical_domain_max(source_model)


    def _strict_page_from_position(self, scroll_value: int, source_model=None) -> int:
        return self._get_strict_domain_service().strict_page_from_position(scroll_value, source_model)
    # ────────────────────────────────────────────────────────────────────

    def _strict_tail_scroll_target(self, source_model=None, *, domain_max=None):
        """Return scroll value that aligns the real last item with viewport bottom."""
        try:
            if source_model is None:
                source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), "sourceModel") else self.model()
            total_items = int(getattr(source_model, "_total_count", 0) or 0)
            if total_items <= 0:
                return None

            tail_idx = total_items - 1
            tail_item = None
            masonry_map = getattr(self, "_masonry_index_map", None)
            if isinstance(masonry_map, dict):
                tail_item = masonry_map.get(tail_idx)
            if tail_item is None:
                for item in (self._masonry_items or []):
                    if int(item.get("index", -1)) == tail_idx:
                        tail_item = item
                        break
            if tail_item is None:
                return None

            tail_bottom = int(tail_item.get("y", 0)) + int(tail_item.get("height", 0))
            target = max(0, tail_bottom - max(1, self.viewport().height()))
            if domain_max is None:
                return int(target)
            return max(0, min(int(target), int(domain_max)))
        except Exception:
            return None

    def _get_masonry_incremental_service(self) -> MasonryIncrementalService:
        service = getattr(self, "_masonry_incremental_service", None)
        if service is None:
            service = MasonryIncrementalService(self)
            self._masonry_incremental_service = service
        return service

    def _rebind_current_index_to_selected_global(self, source_model=None) -> bool:
        """Re-map selection to stable global index after buffered page set changes."""
        target_global = getattr(self, "_selected_global_index", None)
        if target_global is None:
            return False
        try:
            target_global = int(target_global)
        except Exception:
            return False
        if target_global < 0:
            return False

        if source_model is None:
            model = self.model()
            source_model = model.sourceModel() if model and hasattr(model, "sourceModel") else model
        if not source_model or not hasattr(source_model, "get_loaded_row_for_global_index"):
            return False
        virtual_list_active = bool(
            hasattr(self, "_virtual_list_is_active") and self._virtual_list_is_active(source_model)
        )
        if getattr(self, "_model_resetting", False):
            return False
        if hasattr(source_model, "_loading_pages"):
            try:
                if not virtual_list_active:
                    load_lock = getattr(source_model, "_page_load_lock", None)
                    if load_lock is not None:
                        with load_lock:
                            if source_model._loading_pages:
                                self._schedule_rebind_current_index_to_selected_global()
                                return False
                    elif source_model._loading_pages:
                        self._schedule_rebind_current_index_to_selected_global()
                        return False
            except Exception:
                pass

        loaded_row = source_model.get_loaded_row_for_global_index(target_global)
        if loaded_row < 0:
            return False

        src_idx = source_model.index(loaded_row, 0)
        proxy_model = self.model()
        proxy_idx = (
            proxy_model.mapFromSource(src_idx)
            if proxy_model and hasattr(proxy_model, "mapFromSource")
            else src_idx
        )
        if not proxy_idx.isValid():
            return False
        target_row = int(proxy_idx.row())
        if target_row < 0:
            return False

        # Never mutate current index while paint/layout interaction is active.
        if (
            getattr(self, "_painting", False)
            or getattr(self, "_masonry_calculating", False)
            or getattr(self, "_scrollbar_dragging", False)
            or getattr(self, "_mouse_scrolling", False)
        ):
            self._schedule_rebind_current_index_to_selected_global()
            return False

        # If already on the same proxy row, no rebind needed.
        current = self.currentIndex()
        if current.isValid() and current.row() == target_row:
            if virtual_list_active:
                self._selected_rows_cache = {int(target_row)}
                self._selected_global_rows_cache = {int(target_global)}
                self._current_proxy_row_cache = int(target_row)
                self._current_global_row_cache = int(target_global)
                self.viewport().update()
                return True
            return False

        # Guard against stale mapping windows during rapid buffered updates.
        if proxy_model and target_row >= proxy_model.rowCount():
            return False

        if virtual_list_active:
            sel_model = self.selectionModel()
            if sel_model is not None:
                self._suppress_virtual_auto_scroll_once = True
                prev_block = sel_model.blockSignals(True)
                try:
                    sel_model.setCurrentIndex(
                        proxy_idx,
                        QItemSelectionModel.SelectionFlag.ClearAndSelect,
                    )
                finally:
                    sel_model.blockSignals(prev_block)
                self._suppress_virtual_auto_scroll_once = False
            else:
                self._suppress_virtual_auto_scroll_once = True
                self.setCurrentIndex(proxy_idx)
                self._suppress_virtual_auto_scroll_once = False
            self._selected_rows_cache = {int(target_row)}
            self._selected_global_rows_cache = {int(target_global)}
            self._current_proxy_row_cache = int(target_row)
            self._current_global_row_cache = int(target_global)
            self.viewport().update()
            return True

        current_global = None
        resolve_current_global = getattr(self, "_current_global_from_current_index", None)
        if callable(resolve_current_global):
            try:
                current_global = resolve_current_global(source_model)
            except Exception:
                current_global = None

        explicit_jump_rebind_live = False
        if self.use_masonry:
            now = time.time()
            lock_until = float(getattr(self, "_selected_global_lock_until", 0.0) or 0.0)
            strict_jump_until = float(getattr(self, "_strict_jump_until", 0.0) or 0.0)
            restore_until = float(getattr(self, "_restore_anchor_until", 0.0) or 0.0)
            locked_global = getattr(self, "_selected_global_lock_value", None)
            jump_global = getattr(self, "_strict_jump_target_global", None)
            restore_global = getattr(self, "_restore_target_global_index", None)
            explicit_jump_rebind_live = bool(
                (
                    now < lock_until
                    and isinstance(locked_global, int)
                    and int(locked_global) == int(target_global)
                )
                or (
                    now < strict_jump_until
                    and isinstance(jump_global, int)
                    and int(jump_global) == int(target_global)
                )
                or (
                    now < restore_until
                    and isinstance(restore_global, int)
                    and int(restore_global) == int(target_global)
                )
            )

        enrichment_rebind_live = bool(
            self.use_masonry
            and getattr(source_model, "_paginated_mode", False)
            and isinstance(current_global, int)
            and int(current_global) != int(target_global)
            and not getattr(self, "_scrollbar_dragging", False)
            and not getattr(self, "_mouse_scrolling", False)
            and not getattr(self, "_drag_preview_mode", False)
            and (
                bool(getattr(source_model, "_enrichment_running", False))
                or getattr(self, "_last_masonry_signal", None) in {"pages_updated", "enrichment_complete", "scroll_idle"}
            )
        )

        if explicit_jump_rebind_live or enrichment_rebind_live:
            # Exact index jumps need the volatile Qt row handle rebound after
            # buffered pages are inserted ahead of the target page. Keep this
            # narrow to explicit jump/restore or active enrichment remap churn.
            sel_model = self.selectionModel()
            if sel_model is not None:
                prev_block = sel_model.blockSignals(True)
                try:
                    sel_model.setCurrentIndex(
                        proxy_idx,
                        QItemSelectionModel.SelectionFlag.ClearAndSelect,
                    )
                finally:
                    sel_model.blockSignals(prev_block)
            else:
                self.setCurrentIndex(proxy_idx)
            self._selected_rows_cache = {int(target_row)}
            self._selected_global_rows_cache = {int(target_global)}
            self._current_proxy_row_cache = int(target_row)
            self._current_global_row_cache = int(target_global)
            self.viewport().update()
            return True

        # Rebind mutation was a startup crash source on some Windows/PySide builds.
        # Keep global target tracking, but avoid forcing current-index mutation for
        # normal masonry churn outside explicit jump/restore states.
        return False

    def _enforce_locked_selected_global(self, source_model=None) -> bool:
        """While drag-jump lock is active, keep current index bound to locked global item."""
        now = time.time()
        lock_until = float(getattr(self, "_selected_global_lock_until", 0.0) or 0.0)
        if now >= lock_until:
            return False
        if getattr(self, "_scrollbar_dragging", False) or getattr(self, "_drag_preview_mode", False):
            return False

        target_global = getattr(self, "_selected_global_lock_value", None)
        if not (isinstance(target_global, int) and target_global >= 0):
            target_global = getattr(self, "_selected_global_index", None)
        if not (isinstance(target_global, int) and target_global >= 0):
            return False

        if source_model is None:
            model = self.model()
            source_model = model.sourceModel() if model and hasattr(model, "sourceModel") else model
        if not source_model or not hasattr(source_model, "get_loaded_row_for_global_index"):
            return False
        virtual_list_active = bool(
            hasattr(self, "_virtual_list_is_active") and self._virtual_list_is_active(source_model)
        )

        # In masonry drag-jump mode the lock exists only to preserve selection
        # identity, not to pull the viewport back to the old selected item.
        # Forcing page loads or scrollTo() here can yank the user back to the
        # previous page while a far jump is still stabilizing.
        if self.use_masonry and not virtual_list_active:
            try:
                cur = self.currentIndex()
                if cur.isValid():
                    proxy_model = self.model()
                    cur_src = (
                        proxy_model.mapToSource(cur)
                        if proxy_model and hasattr(proxy_model, "mapToSource")
                        else cur
                    )
                    if cur_src.isValid() and hasattr(source_model, "get_global_index_for_row"):
                        cur_global = source_model.get_global_index_for_row(cur_src.row())
                        if isinstance(cur_global, int) and int(cur_global) == int(target_global):
                            self._selected_global_index = int(target_global)
            except Exception:
                pass
            return False

        # Request the target page eagerly if not loaded yet.
        try:
            if hasattr(source_model, "ensure_pages_for_range"):
                source_model.ensure_pages_for_range(int(target_global), int(target_global) + 1)
        except Exception:
            pass

        loaded_row = source_model.get_loaded_row_for_global_index(int(target_global))
        if loaded_row < 0:
            return False

        src_idx = source_model.index(loaded_row, 0)
        proxy_model = self.model()
        proxy_idx = (
            proxy_model.mapFromSource(src_idx)
            if proxy_model and hasattr(proxy_model, "mapFromSource")
            else src_idx
        )
        if not proxy_idx.isValid():
            return False

        try:
            cur = self.currentIndex()
            if cur.isValid() and proxy_model and hasattr(proxy_model, "mapToSource"):
                cur_src = proxy_model.mapToSource(cur)
                if cur_src.isValid() and hasattr(source_model, "get_global_index_for_row"):
                    cur_global = source_model.get_global_index_for_row(cur_src.row())
                    if isinstance(cur_global, int) and int(cur_global) == int(target_global):
                        self._selected_global_index = int(target_global)
                        return False
        except Exception:
            pass

        sel_model = self.selectionModel()
        if sel_model is not None:
            sel_model.setCurrentIndex(proxy_idx, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        else:
            self.setCurrentIndex(proxy_idx)
        try:
            self.scrollTo(proxy_idx, QAbstractItemView.ScrollHint.PositionAtCenter)
        except Exception:
            pass
        self._selected_global_index = int(target_global)
        return True

    def _schedule_rebind_current_index_to_selected_global(self):
        """Queue a single rebind attempt on the next event-loop tick."""
        source_model = (
            self.model().sourceModel()
            if self.model() and hasattr(self.model(), "sourceModel")
            else self.model()
        )
        virtual_list_active = bool(
            hasattr(self, "_virtual_list_is_active")
            and self._virtual_list_is_active(source_model)
        )
        paginated_masonry_active = bool(
            self.use_masonry
            and source_model is not None
            and getattr(source_model, "_paginated_mode", False)
        )
        if not (virtual_list_active or paginated_masonry_active):
            return
        if bool(getattr(self, "_rebind_selected_global_pending", False)):
            return
        self._rebind_selected_global_pending = True

        def _run_rebind():
            self._rebind_selected_global_pending = False
            try:
                self._rebind_current_index_to_selected_global(source_model=source_model)
            except Exception:
                pass

        QTimer.singleShot(0, _run_rebind)

    def _get_strict_canonical_scroll_for_global(self, target_global, source_model=None, domain_max=None):
        """Map a global index into strict canonical scroll space."""
        try:
            target_global = int(target_global)
        except Exception:
            return None
        if target_global < 0:
            return None

        if source_model is None:
            model = self.model()
            source_model = model.sourceModel() if model and hasattr(model, "sourceModel") else model
        if source_model is None:
            return None

        try:
            total_items = int(getattr(source_model, "_total_count", 0) or 0)
        except Exception:
            total_items = 0
        if total_items <= 0:
            return None

        if domain_max is None:
            domain_max = self.verticalScrollBar().maximum()
        domain_max = max(0, int(domain_max))

        target_global = max(0, min(total_items - 1, target_global))
        if total_items <= 1 or domain_max <= 0:
            return 0

        ratio = target_global / max(1, total_items - 1)
        return max(0, min(int(round(ratio * domain_max)), domain_max))

    def _get_restore_anchor_scroll_value(self, source_model=None, domain_max=None):
        """Resolve restore-time scroll anchor from target global index (fallback: target page)."""
        try:
            until = float(getattr(self, "_restore_anchor_until", 0.0) or 0.0)
        except Exception:
            until = 0.0
        if until <= 0.0 or time.time() > until:
            return None

        target_global = getattr(self, "_restore_target_global_index", None)
        if target_global is None:
            return None
        try:
            target_global = int(target_global)
        except Exception:
            return None
        if target_global < 0:
            return None

        if source_model is None:
            model = self.model()
            source_model = model.sourceModel() if model and hasattr(model, "sourceModel") else model

        if domain_max is None:
            domain_max = self.verticalScrollBar().maximum()
        domain_max = max(0, int(domain_max))

        prefer_exact_item_anchor = False
        try:
            now = time.time()
            jump_kind = getattr(self, "_last_explicit_jump_kind", None)
            jump_until = float(getattr(self, "_last_explicit_jump_until", 0.0) or 0.0)
            jump_target = getattr(self, "_last_explicit_jump_target_global", None)
            if (
                jump_kind == "index_input"
                and now <= jump_until
                and isinstance(jump_target, int)
                and int(jump_target) == int(target_global)
            ):
                prefer_exact_item_anchor = True
            settle_until = float(getattr(self, "_exact_jump_settle_until", 0.0) or 0.0)
            settle_target = getattr(self, "_exact_jump_settle_target_global", None)
            if (
                now <= settle_until
                and isinstance(settle_target, int)
                and int(settle_target) == int(target_global)
            ):
                prefer_exact_item_anchor = True
        except Exception:
            prefer_exact_item_anchor = False

        if prefer_exact_item_anchor:
            for item in (self._masonry_items or []):
                if int(item.get("index", -1)) == int(target_global):
                    item_center_y = int(item.get("y", 0)) + int(item.get("height", 0)) // 2
                    target = item_center_y - (self.viewport().height() // 2)
                    return max(0, min(target, domain_max))

        strict_mode = (
            bool(getattr(self, "use_masonry", False))
            and source_model is not None
            and getattr(source_model, "_paginated_mode", False)
            and self._get_masonry_strategy(source_model) == "windowed_strict"
        )
        if strict_mode:
            return self._get_strict_canonical_scroll_for_global(
                target_global,
                source_model=source_model,
                domain_max=domain_max,
            )

        for item in (self._masonry_items or []):
            if int(item.get("index", -1)) == target_global:
                item_center_y = int(item.get("y", 0)) + int(item.get("height", 0)) // 2
                target = item_center_y - (self.viewport().height() // 2)
                return max(0, min(target, domain_max))

        # Fallback until target item is materialized: keep target page ownership.
        restore_page = self._get_live_restore_target_page()
        if restore_page is None or not source_model:
            return None
        try:
            total_items = int(getattr(source_model, "_total_count", 0) or 0)
            page_size = int(getattr(source_model, "PAGE_SIZE", 1000) or 1000)
            max_page = max(1, (total_items + page_size - 1) // page_size) - 1
            if max_page > 0:
                return max(0, min(int(int(restore_page) / max_page * domain_max), domain_max))
            return 0
        except Exception:
            return None

    def contextMenuEvent(self, event):
        self.context_menu.exec_(event.globalPos())


    def _on_scroll_value_changed(self, value):
        """Track valid scroll positions to enable restoration after layout resets."""
        sb = self.verticalScrollBar()
        max_v = sb.maximum()
        source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else self.model()
        virtual_list_active = bool(
            hasattr(self, '_virtual_list_is_active') and self._virtual_list_is_active(source_model)
        )
        if self._scrollbar_dragging and self._use_local_anchor_masonry(source_model):
            baseline = self._strict_canonical_domain_max(source_model)
            slider_pos = max(0, min(int(sb.sliderPosition()), baseline))
            self._strict_drag_live_fraction = max(0.0, min(1.0, slider_pos / baseline))
            self._restore_strict_drag_domain(sb=sb, source_model=source_model)
            max_v = sb.maximum()
            value = sb.value()

        user_driven = self._scrollbar_dragging or self._mouse_scrolling
        if user_driven:
            # User is actively navigating: drop startup restore override.
            if getattr(self, '_restore_target_page', None) is not None:
                self._restore_target_page = None
                self._restore_target_global_index = None
                self._restore_anchor_until = 0.0
            if hasattr(self, '_cancel_exact_jump_settle'):
                try:
                    self._cancel_exact_jump_settle()
                except Exception:
                    pass
            if hasattr(self, '_clear_pending_target_reflow_guide'):
                try:
                    self._clear_pending_target_reflow_guide()
                except Exception:
                    pass
            self._suppress_masonry_auto_scroll_until = 0.0
            self._strict_jump_target_global = None
            self._strict_jump_until = 0.0
            self._idle_anchor_target_global = None
            self._idle_anchor_until = 0.0
            if getattr(self, '_resize_anchor_page', None) is not None:
                self._resize_anchor_page = None
                self._resize_anchor_target_global = None
                self._resize_anchor_until = 0.0
            # User moved after drag-release: release temporary anchor so
            # ownership follows current scroll immediately (prevents stale
            # page lock from making tail items unreachable).
            if getattr(self, '_drag_release_anchor_active', False):
                self._drag_release_anchor_active = False
                self._drag_release_anchor_idx = None
                self._drag_release_anchor_until = 0.0
            # User moved again: clear temporary strict post-release ownership lock.
            if self._use_local_anchor_masonry(source_model):
                self._release_page_lock_page = None
                self._release_page_lock_until = 0.0
                # Persist explicit edge intent while user is actively scrolling.
                # This prevents strict-domain recalcs from dropping ownership
                # away from the dataset tail during zoom/resize bursts.
                try:
                    total_items = int(getattr(source_model, '_total_count', 0) or 0)
                    page_size = int(getattr(source_model, 'PAGE_SIZE', 1000) or 1000)
                    if total_items > 0 and page_size > 0:
                        last_page = max(0, (total_items - 1) // page_size)
                        tail_target = self._strict_tail_scroll_target(
                            source_model=source_model,
                            domain_max=max_v,
                        )
                        near_bottom = (
                            value >= max(0, int(tail_target) - 2)
                            if tail_target is not None
                            else (max_v > 0 and value >= max_v - 2)
                        )
                        if near_bottom:
                            self._stick_to_edge = "bottom"
                            self._current_page = last_page
                        elif value <= 2:
                            self._stick_to_edge = "top"
                            self._current_page = 0
                except Exception:
                    pass

        if virtual_list_active:
            # In virtual fixed-row list mode, always track latest scrollbar
            # value so follow-up geometry passes cannot replay stale offsets.
            self._last_stable_scroll_value = max(0, int(value))
            return

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


    def _restore_strict_drag_domain(self, sb=None, source_model=None) -> bool:
        """Keep strict drag domain stable while Qt mutates scrollbar ranges."""
        if sb is None:
            sb = self.verticalScrollBar()
        if source_model is None:
            source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else self.model()
        if not (self.use_masonry and self._scrollbar_dragging and self._use_local_anchor_masonry(source_model)):
            return False
        if self._strict_range_guard:
            return False

        baseline = self._strict_canonical_domain_max(source_model)
        self._drag_scroll_max_baseline = baseline

        frac = float(getattr(self, "_strict_drag_live_fraction", 0.0) or 0.0)
        if not (0.0 <= frac <= 1.0):
            frac = 0.0
        # Prefer live slider ratio when available to avoid replaying stale fractions
        # from a previous drag gesture after async range churn.
        try:
            live_frac = max(0.0, min(1.0, int(sb.sliderPosition()) / baseline))
            if abs(live_frac - frac) > 0.12:
                frac = live_frac
                self._strict_drag_live_fraction = live_frac
        except Exception:
            pass
        target_pos = int(round(frac * baseline))
        target_pos = max(0, min(target_pos, baseline))

        self._strict_range_guard = True
        prev_block = sb.blockSignals(True)
        try:
            if sb.maximum() != baseline:
                sb.setRange(0, baseline)
            if sb.sliderPosition() != target_pos:
                sb.setSliderPosition(target_pos)
            if sb.value() != target_pos:
                sb.setValue(target_pos)
        finally:
            sb.blockSignals(prev_block)
            self._strict_range_guard = False
        return True


    def _on_scrollbar_slider_moved(self, position):
        """Track drag fraction in strict mode before Qt can clamp range."""
        source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else self.model()
        if not (self.use_masonry and self._scrollbar_dragging and self._use_local_anchor_masonry(source_model)):
            return
        baseline = self._strict_canonical_domain_max(source_model)
        pos = max(0, min(int(position), baseline))
        self._strict_drag_live_fraction = max(0.0, min(1.0, pos / baseline))


    def _on_scrollbar_range_changed(self, _min_v, max_v):
        """Prevent strict drag range collapse caused by Qt relayout updates."""
        source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else self.model()
        if not (self.use_masonry and self._scrollbar_dragging and self._use_local_anchor_masonry(source_model)):
            return
        baseline = max(1, int(getattr(self, "_drag_scroll_max_baseline", 0) or 0))
        if baseline > 1 and int(max_v) < baseline:
            self._restore_strict_drag_domain(source_model=source_model)


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
        """Handle completion of background enrichment in paginated mode.

        Uses scope-based routing to prevent infinite loops:
        - scope='window' + not exhausted: retrigger window enrichment
        - scope='window' + exhausted: masonry refresh → start preload
        - scope='preload' + not exhausted: continue preload (no refresh)
        - scope='preload' + exhausted: stop (all done)
        """
        source_model = self.proxy_image_list_model.sourceModel()
        if not source_model:
            return

        scope = getattr(source_model, '_enrichment_scope', 'window')
        exhausted = getattr(source_model, '_enrichment_exhausted', True)
        target_pages = sorted(getattr(source_model, '_enrichment_target_pages', ()) or ())

        cur_page = int(getattr(self, '_current_page', 0) or 0)
        try:
            last_page = max(
                0,
                (
                    int(getattr(source_model, '_total_count', 0) or 0) - 1
                ) // max(1, int(getattr(source_model, 'PAGE_SIZE', 1000) or 1000)),
            )
        except Exception:
            last_page = 0
        transient_owner_page = self._get_transient_owner_anchor_page(
            source_model=source_model,
            last_page=last_page,
        )
        if isinstance(transient_owner_page, int):
            cur_page = int(transient_owner_page)
        window_buffer = 3
        ws = max(0, cur_page - window_buffer)
        we = cur_page + window_buffer

        if scope == 'preload':
            # Pre-enrichment: never do masonry refresh, never retrigger window
            if not exhausted:
                # More preload work — continue with same scope
                self._last_enrich_trigger_time = time.time()
                source_model._start_paginated_enrichment(
                    window_pages=getattr(source_model, '_enrichment_target_pages', None),
                    scope='preload',
                )
            # else: preload exhausted — all done, stop silently
            return

        # scope == 'window'
        self._last_enrich_trigger_time = time.time()

        if not exhausted:
            # Continue the exact target that started this repair batch.
            next_target = target_pages if target_pages else range(ws, we + 1)
            source_model._start_paginated_enrichment(
                window_pages=next_target,
                scope='window',
            )
            return

        # Skip masonry refresh if nothing was actually enriched (no data changed).
        # This prevents a startup race where enrichment for page 0 fires before
        # restore completes, and the masonry refresh overwrites the scroll position.
        actual = getattr(source_model, '_enrichment_actual_count', -1)
        if actual == 0:
            return

        # ALL window images enriched — do a single masonry refresh
        self._enrich_first_refresh_done = True

        incremental = self._get_masonry_incremental_service()
        if incremental.is_active and target_pages:
            anchor_global = None
            anchor_old_y = None
            try:
                anchor_global = self._get_non_restore_reflow_anchor_global(source_model=source_model)
                if isinstance(anchor_global, int) and anchor_global >= 0:
                    anchor_item = self._get_masonry_item_for_global_index(anchor_global)
                    if anchor_item is not None:
                        anchor_old_y = int(anchor_item.get('y', 0))
            except Exception:
                anchor_global = None
                anchor_old_y = None

            extended_pages = []
            for page_num in target_pages:
                if page_num in incremental.get_cached_pages():
                    continue
                page_images = getattr(source_model, '_pages', {}).get(page_num)
                if not page_images or self._page_needs_enrichment(page_images):
                    continue
                if incremental.can_extend_down(page_num):
                    if self._try_incremental_extend(page_num, source_model, direction="down"):
                        extended_pages.append(page_num)
                elif incremental.can_extend_up(page_num):
                    if self._try_incremental_extend(page_num, source_model, direction="up"):
                        extended_pages.append(page_num)

            if extended_pages:
                self._apply_incremental_cache_refresh(
                    source_model,
                    anchor_global=anchor_global,
                    anchor_old_y=anchor_old_y,
                )
                self._check_and_enrich_loaded_pages()
                return

        def silent_refresh():
            if not hasattr(source_model, '_pages'):
                return

            # Keep the same logical item anchored through enrichment-only refreshes.
            sb = self.verticalScrollBar()
            old_scroll = int(sb.value())
            anchor_global = self._get_non_restore_reflow_anchor_global(source_model=source_model)
            anchor_offset = None
            if isinstance(anchor_global, int) and anchor_global >= 0:
                old_anchor_item = self._get_masonry_item_for_global_index(anchor_global)
                if old_anchor_item is not None:
                    anchor_offset = int(old_anchor_item.get('y', 0)) - int(old_scroll)
            reflow_guide_snapshot = None
            capture_reflow_guide = getattr(self, "_capture_selected_reflow_guide_snapshot", None)
            if callable(capture_reflow_guide):
                try:
                    reflow_guide_snapshot = capture_reflow_guide(source_model=source_model)
                except Exception:
                    reflow_guide_snapshot = None

            # Reload the exact enriched target pages when known. Falling back
            # to the derived visible window is less stable on deep jumps
            # because `_current_page` can drift before repair finishes.
            pages_to_refresh = target_pages if target_pages else list(range(ws, we + 1))
            for p in pages_to_refresh:
                if p in source_model._pages:
                    source_model._load_page_sync(p)

            # Compute masonry synchronously
            page_size = source_model.PAGE_SIZE if hasattr(source_model, 'PAGE_SIZE') else 1000
            total_items = int(getattr(source_model, '_total_count', 0) or 0)
            metrics = self._get_masonry_column_metrics()
            col_w = int(metrics["column_width"])
            spacing = int(metrics["spacing"])
            num_cols = int(metrics["num_columns"])

            items_data = []
            for p in range(ws, we + 1):
                page = source_model._pages.get(p)
                if not page:
                    continue
                start_idx = p * page_size
                for i, img in enumerate(page):
                    if img:
                        items_data.append((start_idx + i, img.aspect_ratio))

            if not items_data:
                return

            import math
            min_idx = ws * page_size
            avg_h = getattr(self, '_strict_virtual_avg_height', 100.0)
            if avg_h < 1:
                avg_h = 100.0
            prefix_h = int(math.ceil(min_idx / max(1, num_cols)) * avg_h) if min_idx > 0 else 0
            if avg_h > 1.0:
                self._strict_masonry_avg_h = float(avg_h)

            column_heights = [prefix_h] * num_cols
            incr = self._get_masonry_incremental_service()
            new_items = incr._layout_items(items_data, column_heights, col_w, spacing, num_cols)

            result = []
            full_width = (col_w + spacing) * num_cols - spacing
            if prefix_h > 0:
                result.append({
                    'index': -2, 'x': 0, 'y': 0,
                    'width': int(full_width), 'height': prefix_h,
                    'aspect_ratio': 1.0,
                })
            result.extend(new_items)

            max_idx = min(total_items, (we + 1) * page_size)
            remaining_items = total_items - max_idx
            if remaining_items > 0:
                suffix_rows = math.ceil(remaining_items / max(1, num_cols))
                suffix_h = int(suffix_rows * avg_h)
                max_y = max(column_heights) if column_heights else 0
                result.append({
                    'index': -3, 'x': 0, 'y': max_y,
                    'width': int(full_width), 'height': suffix_h,
                    'aspect_ratio': 1.0,
                })

            self._masonry_items = result
            self._masonry_index_map = None
            self._last_masonry_window_signature = None
            # NOTE: Do NOT set _masonry_recalc_pending here.  silent_refresh
            # already computes masonry synchronously and rebuilds the
            # incremental cache.  Setting the pending flag would trigger a
            # redundant full async recalc on the next completion, feeding
            # the cascading-recalc loop that causes post-zoom layout drift.

            # Keep total height in sync with refreshed virtual window so later
            # geometry/range updates don't clamp against stale heights.
            try:
                max_real_y = 0
                for _it in result:
                    max_real_y = max(max_real_y, int(_it.get('y', 0)) + int(_it.get('height', 0)))
                self._masonry_total_height = max(
                    int(getattr(self, '_masonry_total_height', 0) or 0),
                    max_real_y,
                    self.viewport().height() + 1,
                )
            except Exception:
                pass

            # Populate incremental cache so subsequent page loads extend
            # from correct (enriched) positions instead of stale 1:1 cache.
            incr.cache_from_full_result(result, page_size, col_w, spacing, num_cols, avg_h)

            # Rebind selection after buffered row shifts on next tick
            # to avoid re-entrancy while model updates are still propagating.
            self._schedule_rebind_current_index_to_selected_global()

            target_scroll = None
            restore_target = self._get_restore_anchor_scroll_value(source_model, sb.maximum())
            if restore_target is not None:
                target_scroll = int(restore_target)
            elif isinstance(anchor_global, int) and anchor_offset is not None:
                for _it in result:
                    if int(_it.get('index', -1)) == int(anchor_global):
                        target_scroll = int(_it.get('y', 0)) - int(anchor_offset)
                        break

            # Apply range/value atomically in strict mode to prevent transient writer races.
            strict_mode = self._get_masonry_strategy(source_model) == "windowed_strict"
            prev_block = sb.blockSignals(True)
            try:
                if strict_mode:
                    keep_max = self._strict_canonical_domain_max(source_model)
                    sb.setRange(0, keep_max)
                if target_scroll is not None:
                    sb.setValue(max(0, min(int(target_scroll), sb.maximum())))
                else:
                    sb.setValue(max(0, min(old_scroll, sb.maximum())))
            finally:
                sb.blockSignals(prev_block)

            self.viewport().update()
            if reflow_guide_snapshot is not None:
                show_reflow_guide = getattr(self, "_show_selected_reflow_guide_from_snapshot", None)
                if callable(show_reflow_guide):
                    try:
                        show_reflow_guide(reflow_guide_snapshot)
                    except Exception:
                        pass
            diagnostic_print(f"[ENRICH] Masonry refreshed ({len(new_items)} items)", detail="verbose")

            # Start pre-enrichment for fringe pages (±15 ahead) with 'preload' scope
            pre_enrich_buffer = 15
            total_pages = 1
            if hasattr(source_model, '_total_count') and hasattr(source_model, 'PAGE_SIZE'):
                tc = int(getattr(source_model, '_total_count', 0) or 0)
                ps = int(getattr(source_model, 'PAGE_SIZE', 1000) or 1000)
                total_pages = max(1, (tc + ps - 1) // ps)
            pre_start = max(0, ws - pre_enrich_buffer)
            pre_end = min(total_pages - 1, we + pre_enrich_buffer)
            if pre_start < ws or pre_end > we:
                self._last_enrich_trigger_time = time.time()
                source_model._start_paginated_enrichment(
                    window_pages=range(pre_start, pre_end + 1),
                    scope='preload',
                )

        from PySide6.QtCore import QTimer
        QTimer.singleShot(250, silent_refresh)


    def _on_pages_updated(self, loaded_pages: list):
        """Handle page load/eviction in buffered mode (safe alternative to layoutChanged).

        Tries incremental masonry first (append new pages without disturbing existing
        item positions). Falls back to full recalc only when necessary (jump, resize,
        enrichment, or no prior cache).
        """
        source_model = self.proxy_image_list_model.sourceModel()
        if (
            hasattr(self, "_virtual_list_is_active")
            and self._virtual_list_is_active(source_model)
        ):
            sb = self.verticalScrollBar()
            current_scroll = int(sb.value())
            viewport_h = max(1, int(self.viewport().height()))
            expected_max = max(
                0,
                int(self._virtual_list_total_height(source_model)) - viewport_h,
            )
            if int(sb.maximum()) != expected_max:
                prev_block = sb.blockSignals(True)
                try:
                    sb.setSingleStep(max(8, self._virtual_list_row_height() // 3))
                    sb.setPageStep(viewport_h)
                    sb.setRange(0, expected_max)
                    sb.setValue(max(0, min(current_scroll, expected_max)))
                finally:
                    sb.blockSignals(prev_block)
                current_scroll = int(sb.value())
            self._ensure_virtual_list_visible_range_loaded(source_model=source_model)
            self._rebind_current_index_to_selected_global(source_model=source_model)
            target_scroll = max(0, min(current_scroll, int(sb.maximum())))
            if int(sb.value()) != target_scroll:
                prev_block = sb.blockSignals(True)
                try:
                    sb.setValue(target_scroll)
                finally:
                    sb.blockSignals(prev_block)
            self._last_stable_scroll_value = int(sb.value())
            self.viewport().update()
            return
        if not self.use_masonry:
            return
        is_paginated = (
            source_model
            and hasattr(source_model, '_paginated_mode')
            and source_model._paginated_mode
        )
        strategy = self._get_masonry_strategy(source_model) if source_model else "full_compat"
        strict_mode = strategy == "windowed_strict"

        if not is_paginated:
            # Non-paginated: always full recalc
            self._last_masonry_window_signature = None
            self._recalculate_masonry_if_needed("pages_updated")
            self.viewport().update()
            return

        # During drag-jump lock, keep current selection identity pinned to the
        # locked global item despite buffered row remaps.
        try:
            self._enforce_locked_selected_global(source_model)
        except Exception:
            pass

        # In buffered mode, source rows can shift when pages are inserted.
        # Queue rebind by global id to keep list/viewer aligned safely.
        self._schedule_rebind_current_index_to_selected_global()

        if strict_mode and getattr(self, "_masonry_calculating", False):
            self._masonry_recalc_pending = True
            self._log_diag(
                "pages.defer_calc_active",
                source_model=source_model,
                throttle_key="diag_pages_defer_calc_active",
                every_s=0.2,
                extra=(
                    f"signal={getattr(self, '_last_masonry_signal', None)} "
                    f"loaded={len(loaded_pages)}"
                ),
            )
            self._check_and_enrich_loaded_pages()
            return

        incremental = self._get_masonry_incremental_service()
        loaded_set = set(loaded_pages)
        cached_pages = incremental.get_cached_pages()

        # If incremental cache is active, check for extensions
        if incremental.is_active and cached_pages:
            new_pages = loaded_set - cached_pages
            if not new_pages:
                # No new pages — just a re-emit. Repaint but skip recalc.
                self.viewport().update()
                self._check_and_enrich_loaded_pages()
                return

            extendable_pages = {
                p for p in new_pages
                if incremental.can_extend_down(p) or incremental.can_extend_up(p)
            }
            if strict_mode and not extendable_pages:
                try:
                    cur_page = int(getattr(self, "_current_page", 0) or 0)
                except Exception:
                    cur_page = 0
                cached_min = min(cached_pages)
                cached_max = max(cached_pages)
                in_cached_band = (cached_min - 1) <= cur_page <= (cached_max + 1)
                if in_cached_band:
                    self._log_diag(
                        "pages.skip_far_new",
                        source_model=source_model,
                        throttle_key="diag_pages_skip_far_new",
                        every_s=0.2,
                        extra=(
                            f"current={cur_page} cached={cached_min}-{cached_max} "
                            f"new={min(new_pages)}-{max(new_pages)} count={len(new_pages)}"
                        ),
                    )
                    self._check_and_enrich_loaded_pages()
                    return

            # Prepend-extension guard: when pages are inserted above current
            # window, masonry y-coordinates shift downward. Preserve viewport
            # ownership by compensating scroll against a stable anchor item.
            anchor_global = None
            old_anchor_y = None
            if strict_mode:
                try:
                    anchor_global = self._get_non_restore_reflow_anchor_global(source_model=source_model)

                    if isinstance(anchor_global, int) and anchor_global >= 0:
                        old_map = getattr(self, '_masonry_index_map', None)
                        old_item = old_map.get(anchor_global) if isinstance(old_map, dict) else None
                        if old_item is None:
                            for _it in (self._masonry_items or []):
                                if int(_it.get('index', -1)) == anchor_global:
                                    old_item = _it
                                    break
                        if old_item is not None:
                            old_anchor_y = int(old_item.get('y', 0))
                except Exception:
                    anchor_global = None
                    old_anchor_y = None

            # Try incremental extend for each new page
            extended = []
            extended_up = False
            blocked_unenriched_pages = set()
            for page_num in sorted(new_pages):
                page_images = getattr(source_model, '_pages', {}).get(page_num)
                if page_images and self._page_needs_enrichment(page_images):
                    blocked_unenriched_pages.add(int(page_num))
                    continue
                if incremental.can_extend_down(page_num):
                    if self._try_incremental_extend(page_num, source_model, direction="down"):
                        extended.append(page_num)
                elif incremental.can_extend_up(page_num):
                    if self._try_incremental_extend(page_num, source_model, direction="up"):
                        extended.append(page_num)
                        extended_up = True

            if extended:
                # Purge far pages from cache to respect memory limits
                cur_page = int(getattr(self, '_current_page', 0) or 0)
                incremental.purge_far_pages(cur_page)
                # Assemble items from cache (no worker needed)
                self._masonry_items = incremental.assemble_items()
                self._masonry_index_map = None
                if strict_mode and extended_up and isinstance(anchor_global, int) and old_anchor_y is not None:
                    try:
                        new_anchor_item = None
                        for _it in (self._masonry_items or []):
                            if int(_it.get('index', -1)) == anchor_global:
                                new_anchor_item = _it
                                break
                        if new_anchor_item is not None:
                            new_anchor_y = int(new_anchor_item.get('y', 0))
                            delta_y = new_anchor_y - int(old_anchor_y)
                            if abs(delta_y) > 1:
                                sb = self.verticalScrollBar()
                                target_val = max(0, min(int(sb.value()) + int(delta_y), int(sb.maximum())))
                                prev_block = sb.blockSignals(True)
                                try:
                                    sb.setValue(target_val)
                                finally:
                                    sb.blockSignals(prev_block)
                    except Exception:
                        pass
                self.viewport().update()
                self._check_and_enrich_loaded_pages()
                return

            if strict_mode and blocked_unenriched_pages and blocked_unenriched_pages == set(new_pages):
                self._log_flow(
                    "PAGES",
                    f"Deferring incremental layout for unenriched pages {min(blocked_unenriched_pages)}-{max(blocked_unenriched_pages)}",
                    throttle_key="pages_wait_enriched_extend",
                    every_s=0.4,
                )
                self._check_and_enrich_loaded_pages()
                self.viewport().update()
                return

            # New pages aren't adjacent — this is a jump or gap. Full recalc.

        # Enrichment-complete forces full recalc (aspect ratios changed).
        if self._last_masonry_signal == "enrichment_complete":
            incremental.invalidate("enrichment")

        if strict_mode:
            waiting_target = getattr(self, "_strict_waiting_target_page", None)
            if isinstance(waiting_target, int) and waiting_target >= 0:
                try:
                    target_items = source_model._pages.get(int(waiting_target), [])
                except Exception:
                    target_items = []
                if not target_items:
                    waiting_window = getattr(self, "_strict_waiting_window_pages", None)
                    if isinstance(waiting_window, tuple) and len(waiting_window) == 2:
                        wait_window_str = f"{int(waiting_window[0])}-{int(waiting_window[1])}"
                    else:
                        wait_window_str = "?"
                    self._log_diag(
                        "pages.defer_wait_target",
                        source_model=source_model,
                        throttle_key="diag_pages_defer_wait_target",
                        every_s=0.2,
                        extra=(
                            f"signal={getattr(self, '_last_masonry_signal', None)} "
                            f"target={int(waiting_target)} window={wait_window_str} "
                            f"loaded={len(loaded_pages)}"
                        ),
                    )
                    self._check_and_enrich_loaded_pages()
                    return

        self._log_flow("PAGES", f"Pages updated ({len(loaded_pages)} loaded); full masonry recalc",
                       throttle_key="pages_updated", every_s=0.3)
        self._log_diag(
            "pages.full_recalc",
            source_model=source_model,
            throttle_key="diag_pages_full_recalc",
            every_s=0.2,
            extra=(
                f"signal={getattr(self, '_last_masonry_signal', None)} "
                f"loaded={len(loaded_pages)}"
            ),
        )
        self._last_masonry_window_signature = None
        self._recalculate_masonry_if_needed("pages_updated")
        if not strict_mode:
            self.viewport().update()
        self._check_and_enrich_loaded_pages()

    def _try_incremental_extend(self, page_num, source_model, *, direction="down"):
        """Compute masonry for a single new page and add to incremental cache.

        Returns True on success, False if we need to fall back to full recalc.
        """
        incremental = self._get_masonry_incremental_service()
        page_size = source_model.PAGE_SIZE
        total_items = int(getattr(source_model, '_total_count', 0) or 0)

        # Get page images from model
        page_images = source_model._pages.get(page_num)
        if not page_images:
            return False

        # Build items_data for this page
        items_data = []
        start_idx = page_num * page_size
        for i, image in enumerate(page_images):
            if not image:
                continue
            idx = start_idx + i
            ar = image.aspect_ratio
            items_data.append((idx, ar))

        if not items_data:
            return False

        if direction == "down":
            new_items = incremental.compute_page_down(page_num, items_data)
        else:
            new_items = incremental.compute_page_up(page_num, items_data, total_items)

        if new_items is None:
            return False

        diagnostic_print(
            f"[MASONRY-INCR] Extended {direction}: page {page_num}, +{len(new_items)} items",
            detail="verbose",
        )
        return True

    def _check_and_enrich_loaded_pages(self):
        """Detect unenriched images on current WINDOW pages and trigger enrichment.

        Only checks the pages in the active masonry window (current_page ± buffer),
        not all loaded pages, to avoid an enrichment loop when distant pages are also
        loaded but unenriched.
        """
        source_model = self.proxy_image_list_model.sourceModel()
        if not source_model or not hasattr(source_model, '_paginated_mode') or not source_model._paginated_mode:
            return
        if not hasattr(source_model, '_pages') or not source_model._pages:
            return

        preferred_window = self._get_preferred_enrichment_window_pages(
            source_model,
            window_buffer=3,
        )
        if preferred_window is None:
            return
        window_start, window_end = preferred_window

        # Compare current window to what enrichment is targeting (if anything).
        now = time.time()
        current_window = set(range(window_start, window_end + 1))
        target = getattr(source_model, '_enrichment_target_pages', None)
        target_window = set(target) if target is not None else set()
        target_scope = getattr(source_model, '_enrichment_scope', 'window')
        same_window_target = (
            target_scope == 'window'
            and bool(target_window)
            and target_window == current_window
        )

        if getattr(source_model, '_enrichment_running', False):
            if same_window_target:
                # Enrichment is already repairing exactly this window — let it finish.
                return
            # Otherwise allow a retarget below, even for nearby page shifts.

        # Debounce only when the current window exactly matches the last window-repair target.
        if same_window_target:
            last_trigger = getattr(self, '_last_enrich_trigger_time', 0.0)
            if now - last_trigger < 5.0:
                return

        unenriched_count = 0
        with source_model._page_load_lock:
            for page_num in range(window_start, window_end + 1):
                page = source_model._pages.get(page_num)
                if not page:
                    continue
                for image in page:
                    if not image:
                        continue
                    dims = image.dimensions
                    if (
                        not dims
                        or dims[0] is None
                        or dims[1] is None
                        or dims == (512, 512)
                    ):
                        unenriched_count += 1
                        if unenriched_count >= 5:
                            break
                if unenriched_count >= 5:
                    break

        if unenriched_count >= 5:
            self._last_enrich_trigger_time = now
            # New scroll position needs masonry refresh after enrichment
            self._enrich_first_refresh_done = False
            self._log_flow(
                "ENRICH",
                f"Window pages {window_start}-{window_end} have unenriched images, triggering window repair",
                level="INFO",
                throttle_key="enrich_trigger",
                every_s=5.0,
            )
            if hasattr(source_model, '_start_paginated_enrichment'):
                # Pass window range so enrichment targets ONLY these pages
                source_model._start_paginated_enrichment(
                    window_pages=range(window_start, window_end + 1)
                )

    def _recalculate_masonry_if_needed(self, signal_name="unknown"):
        """Recalculate masonry layout if in masonry mode (debounced with adaptive delay)."""
        import time
        if not self.use_masonry:
            return

        current_time = time.time()
        timestamp = time.strftime("%H:%M:%S.") + f"{int(current_time * 1000) % 1000:03d}"

        # Store signal name for _do_recalculate_masonry to check
        self._last_masonry_signal = signal_name
        source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else self.model()

        # Low-priority signals: don't pile up timers when a recalc is already
        # queued/running.  For pages_updated, set the pending flag so the
        # current calc's completion handler starts a follow-up (instead of
        # spawning a competing timer that causes cascading recalcs / drift).
        if signal_name in ("dimensions_updated", "pages_updated"):
            if self._masonry_calculating:
                self._masonry_recalc_pending = True
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
        restarted = self._masonry_recalc_timer.isActive()
        if self._masonry_recalc_timer.isActive():
            self._masonry_recalc_timer.stop()
            # print(f"[{timestamp}]   -> Restarting {self._masonry_recalc_delay}ms countdown")
        else:
            pass
            # print(f"[{timestamp}]   -> Starting {self._masonry_recalc_delay}ms countdown")
        self._masonry_recalc_timer.start(self._masonry_recalc_delay)
        self._log_diag(
            "recalc.timer_start",
            source_model=source_model,
            throttle_key="diag_recalc_timer_start",
            every_s=0.2,
            extra=(
                f"signal={signal_name} delay_ms={int(self._masonry_recalc_delay)} "
                f"restarted={restarted}"
            ),
        )
