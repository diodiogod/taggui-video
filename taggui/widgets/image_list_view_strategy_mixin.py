from widgets.image_list_shared import *  # noqa: F401,F403
from widgets.image_list_strict_domain_service import StrictScrollDomainService

class ImageListViewStrategyMixin:
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
        print(f"[{ts}][TRACE][{component}][{level}] {message}")


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
            # User moved again: clear temporary strict post-release ownership lock.
            if self._use_local_anchor_masonry(source_model):
                self._release_page_lock_page = None
                self._release_page_lock_until = 0.0
            if self._stick_to_edge == "bottom":
                if max_v > 0 and value < max_v - 200:
                    self._stick_to_edge = None
            elif self._stick_to_edge == "top":
                if value > 200:
                    self._stick_to_edge = None

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

        Silently reload loaded pages so masonry gets accurate dimensions.
        Anchors scroll + selection so the user isn't disrupted.
        """
        cur_page = int(getattr(self, '_current_page', 0) or 0)
        self._log_flow("ENRICH", f"Paginated enrichment complete; current_page={cur_page}", level="INFO")

        # Snapshot the user's current scroll and selection BEFORE reload
        scroll_val = self.verticalScrollBar().value()
        scroll_max = self.verticalScrollBar().maximum()

        # Lock the viewport to the current page so the masonry recalc
        # doesn't jump somewhere else when avg_height changes.
        self._masonry_sticky_page = cur_page
        self._masonry_sticky_until = time.time() + 5.0
        self._release_page_lock_page = cur_page
        self._release_page_lock_until = time.time() + 8.0
        self._last_masonry_window_signature = None  # Force recalc with enriched dimensions

        def reload_pages():
            source_model = self.proxy_image_list_model.sourceModel()
            if not hasattr(source_model, '_pages'):
                return
            pages_to_reload = list(source_model._pages.keys())
            if not pages_to_reload:
                return
            for page_num in pages_to_reload:
                source_model._load_page_sync(page_num)
            self._last_masonry_signal = "enrichment_complete"
            # Restore scroll position before emitting update to prevent jump
            sb = self.verticalScrollBar()
            sb.blockSignals(True)
            if scroll_max > 0 and sb.maximum() > 0:
                # Preserve same fraction through the domain
                frac = scroll_val / scroll_max
                sb.setValue(int(frac * sb.maximum()))
            sb.blockSignals(False)
            source_model._emit_pages_updated()

        from PySide6.QtCore import QTimer
        QTimer.singleShot(250, reload_pages)


    def _on_pages_updated(self, loaded_pages: list):
        """Handle page load/eviction in buffered mode (safe alternative to layoutChanged)."""
        if not self.use_masonry:
            return
    
        self._log_flow("PAGES", f"Pages updated ({len(loaded_pages)} loaded); scheduling masonry recalc",
                       throttle_key="pages_updated", every_s=0.3)
    
        # Recalculate masonry for currently loaded pages
        # This is safe because it doesn't emit layoutChanged
        self._last_masonry_window_signature = None
        self._recalculate_masonry_if_needed("pages_updated")
    
        # Request viewport repaint (safe, doesn't invalidate model)
        self.viewport().update()



    def _recalculate_masonry_if_needed(self, signal_name="unknown"):
        """Recalculate masonry layout if in masonry mode (debounced with adaptive delay)."""
        import time
        if not self.use_masonry:
            return

        current_time = time.time()
        timestamp = time.strftime("%H:%M:%S.") + f"{int(current_time * 1000) % 1000:03d}"

        # Store signal name for _do_recalculate_masonry to check
        self._last_masonry_signal = signal_name

        # Low-priority signal: don't keep restarting the timer if dimensions updates
        # are arriving continuously and a recalc is already queued/running.
        if signal_name == "dimensions_updated":
            if self._masonry_calculating:
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
