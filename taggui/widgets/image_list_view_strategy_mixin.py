from widgets.image_list_shared import *  # noqa: F401,F403
from widgets.image_list_strict_domain_service import StrictScrollDomainService
from widgets.image_list_masonry_incremental_service import MasonryIncrementalService

class ImageListViewStrategyMixin:
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

        anchor_global = getattr(self, '_selected_global_index', None)
        if not (isinstance(anchor_global, int) and anchor_global >= 0):
            cur = self.currentIndex()
            if cur.isValid():
                try:
                    src_idx = (
                        self.model().mapToSource(cur)
                        if self.model() and hasattr(self.model(), 'mapToSource')
                        else cur
                    )
                    if src_idx.isValid() and hasattr(source_model, 'get_global_index_for_row'):
                        mapped = source_model.get_global_index_for_row(src_idx.row())
                        if isinstance(mapped, int) and mapped >= 0:
                            anchor_global = mapped
                except Exception:
                    anchor_global = None
        if not (isinstance(anchor_global, int) and anchor_global >= 0):
            return False

        page_size = int(getattr(source_model, 'PAGE_SIZE', 1000) or 1000)
        anchor_page = max(0, int(anchor_global // max(1, page_size)))
        until = time.time() + max(0.2, float(hold_s))
        self._resize_anchor_page = anchor_page
        self._resize_anchor_until = until
        try:
            total_items = int(getattr(source_model, '_total_count', 0) or 0)
            last_page = max(0, (total_items - 1) // max(1, page_size))
            sb = self.verticalScrollBar()
            sb_val = int(sb.value())
            sb_max = int(sb.maximum())
            near_bottom = sb_max > 0 and sb_val >= int(sb_max * 0.80)
            near_top = sb_val <= 2
            current_page = int(getattr(self, '_current_page', 0) or 0)
            # Preserve edge intent through zoom/resize relayout.
            if anchor_page >= last_page and (near_bottom or current_page >= max(0, last_page - 1)):
                self._stick_to_edge = "bottom"
            elif anchor_page <= 0 and (near_top or current_page <= 1):
                self._stick_to_edge = "top"
        except Exception:
            pass
        # Do NOT set _release_page_lock here.  That lock snaps scroll to the
        # first masonry item of the page (y≈0 for page 0), which destroys the
        # user's viewport position during zoom.  The resize anchor +
        # _ensure_selected_anchor_if_needed handle post-zoom centering instead.
        return True

    def _log_flow(self, component: str, message: str, *, level: str = "DEBUG",
                  throttle_key: str | None = None, every_s: float | None = None):
        """Timestamped, optionally throttled flow logging for masonry/pagination diagnostics."""
        # TRACE_RESTORE: temporary minimal diagnostics filter for strict drag debugging.
        # Set `minimal_trace_logs` to False in settings to restore full flow logs.
        try:
            minimal_trace = bool(settings.value("minimal_trace_logs", True, type=bool))
        except Exception:
            minimal_trace = True
        if minimal_trace:
            keep = False
            if component == "STRICT":
                keep = True
            elif component == "MASONRY" and (
                message.startswith("Calc start")
                or message.startswith("Strategy=")
                or message.startswith("Waiting target page")
                or message.startswith("Waiting window items")
            ):
                keep = True
            elif component == "PAGINATION" and message.startswith("Triggered loads"):
                keep = True
            if not keep:
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


    def _use_local_anchor_masonry(self, source_model=None) -> bool:
        """Enable local-anchor/windowed masonry when strict strategy is requested."""
        return self._get_masonry_strategy(source_model) == "windowed_strict"


    def _get_masonry_strategy(self, source_model=None) -> str:
        """Return active masonry strategy for paginated mode control."""
        strategy = "full_compat"
        try:
            raw = settings.value("masonry_strategy", "full_compat", type=str)
            if raw:
                strategy = str(raw).strip().lower()
        except Exception:
            strategy = "full_compat"

        if strategy not in {"full_compat", "windowed_strict"}:
            strategy = "full_compat"

        is_paginated = bool(
            source_model
            and hasattr(source_model, "_paginated_mode")
            and source_model._paginated_mode
        )
        if not is_paginated:
            strategy = "full_compat"

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
        if getattr(self, "_model_resetting", False):
            return False
        if hasattr(source_model, "_loading_pages"):
            try:
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
            return False

        # Guard against stale mapping windows during rapid buffered updates.
        if proxy_model and target_row >= proxy_model.rowCount():
            return False

        # Rebind mutation was a startup crash source on some Windows/PySide builds.
        # Keep global target tracking, but avoid forcing current-index mutation here.
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
        return

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

        for item in (self._masonry_items or []):
            if int(item.get("index", -1)) == target_global:
                item_center_y = int(item.get("y", 0)) + int(item.get("height", 0)) // 2
                target = item_center_y - (self.viewport().height() // 2)
                return max(0, min(target, domain_max))

        # Fallback until target item is materialized: keep target page ownership.
        restore_page = getattr(self, "_restore_target_page", None)
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
            if getattr(self, '_resize_anchor_page', None) is not None:
                self._resize_anchor_page = None
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
                        if max_v > 0 and value >= max_v - 2:
                            self._stick_to_edge = "bottom"
                            self._current_page = last_page
                        elif value <= 2:
                            self._stick_to_edge = "top"
                            self._current_page = 0
                except Exception:
                    pass

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
        if not (self._scrollbar_dragging and self._use_local_anchor_masonry(source_model)):
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
        if not (self._scrollbar_dragging and self._use_local_anchor_masonry(source_model)):
            return
        baseline = self._strict_canonical_domain_max(source_model)
        pos = max(0, min(int(position), baseline))
        self._strict_drag_live_fraction = max(0.0, min(1.0, pos / baseline))


    def _on_scrollbar_range_changed(self, _min_v, max_v):
        """Prevent strict drag range collapse caused by Qt relayout updates."""
        source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else self.model()
        if not (self._scrollbar_dragging and self._use_local_anchor_masonry(source_model)):
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

        cur_page = int(getattr(self, '_current_page', 0) or 0)
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
            # More window work — silently re-trigger without any UI change
            source_model._start_paginated_enrichment(
                window_pages=range(ws, we + 1), scope='window',
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

        def silent_refresh():
            if not hasattr(source_model, '_pages'):
                return

            # Keep the same logical item anchored through enrichment-only refreshes.
            sb = self.verticalScrollBar()
            old_scroll = int(sb.value())
            anchor_global = getattr(self, '_selected_global_index', None)
            if not (isinstance(anchor_global, int) and anchor_global >= 0):
                anchor_global = None
                cur_idx = self.currentIndex()
                if cur_idx.isValid():
                    try:
                        src_idx = (
                            self.model().mapToSource(cur_idx)
                            if self.model() and hasattr(self.model(), 'mapToSource')
                            else cur_idx
                        )
                        if src_idx.isValid() and hasattr(source_model, 'get_global_index_for_row'):
                            mapped = source_model.get_global_index_for_row(src_idx.row())
                            if isinstance(mapped, int) and mapped >= 0:
                                anchor_global = mapped
                    except Exception:
                        pass

            # Reload window pages to pick up enriched dimensions
            for p in range(ws, we + 1):
                if p in source_model._pages:
                    source_model._load_page_sync(p)

            # Compute masonry synchronously
            page_size = source_model.PAGE_SIZE if hasattr(source_model, 'PAGE_SIZE') else 1000
            total_items = int(getattr(source_model, '_total_count', 0) or 0)
            col_w = self.current_thumbnail_size
            spacing = 2
            sb = self.verticalScrollBar()
            sb_width = sb.width() if sb.isVisible() else 15
            avail_width = self.viewport().width() - sb_width - 24
            num_cols = max(1, avail_width // (col_w + spacing))

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
            elif anchor_global is not None:
                for _it in result:
                    if int(_it.get('index', -1)) == int(anchor_global):
                        target_scroll = int(_it.get('y', 0)) + int(_it.get('height', 0)) // 2 - (self.viewport().height() // 2)
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
            print(f"[ENRICH] Masonry refreshed ({len(new_items)} items)")

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
        if not self.use_masonry:
            return

        source_model = self.proxy_image_list_model.sourceModel()
        is_paginated = (
            source_model
            and hasattr(source_model, '_paginated_mode')
            and source_model._paginated_mode
        )

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

            # Try incremental extend for each new page
            extended = []
            for page_num in sorted(new_pages):
                if incremental.can_extend_down(page_num):
                    if self._try_incremental_extend(page_num, source_model, direction="down"):
                        extended.append(page_num)
                elif incremental.can_extend_up(page_num):
                    if self._try_incremental_extend(page_num, source_model, direction="up"):
                        extended.append(page_num)

            if extended:
                # Purge far pages from cache to respect memory limits
                cur_page = int(getattr(self, '_current_page', 0) or 0)
                incremental.purge_far_pages(cur_page)
                # Assemble items from cache (no worker needed)
                self._masonry_items = incremental.assemble_items()
                self._masonry_index_map = None
                self.viewport().update()
                self._check_and_enrich_loaded_pages()
                return

            # New pages aren't adjacent — this is a jump or gap. Full recalc.

        # Enrichment-complete forces full recalc (aspect ratios changed).
        if self._last_masonry_signal == "enrichment_complete":
            incremental.invalidate("enrichment")

        self._log_flow("PAGES", f"Pages updated ({len(loaded_pages)} loaded); full masonry recalc",
                       throttle_key="pages_updated", every_s=0.3)
        self._last_masonry_window_signature = None
        self._recalculate_masonry_if_needed("pages_updated")
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

        print(f"[MASONRY-INCR] Extended {direction}: page {page_num}, +{len(new_items)} items")
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

        # Only check pages in the current masonry window (not all loaded pages)
        cur_page = int(getattr(self, '_current_page', 0) or 0)
        window_buffer = 3
        window_start = max(0, cur_page - window_buffer)
        window_end = cur_page + window_buffer

        # Compare current window to what enrichment is targeting (if anything).
        now = time.time()
        current_window = set(range(window_start, window_end + 1))
        target = getattr(source_model, '_enrichment_target_pages', None)
        window_changed = target is None or not (current_window & target)

        if getattr(source_model, '_enrichment_running', False):
            if not window_changed:
                # Enrichment is already working on our window — let it finish
                return
            # Enrichment is targeting a different location — cancel + restart below

        # Debounce: only when enrichment targets the same window (prevents re-trigger
        # while cycles are still processing). Skip debounce after a jump (window changed).
        if not window_changed:
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
                    if not dims or dims[0] is None or dims[1] is None:
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
                f"Window pages {window_start}-{window_end} have unenriched images, triggering enrichment",
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
        if self._masonry_recalc_timer.isActive():
            self._masonry_recalc_timer.stop()
            # print(f"[{timestamp}]   -> Restarting {self._masonry_recalc_delay}ms countdown")
        else:
            pass
            # print(f"[{timestamp}]   -> Starting {self._masonry_recalc_delay}ms countdown")
        self._masonry_recalc_timer.start(self._masonry_recalc_delay)
