class StrictScrollDomainService:
    """Owns strict-mode virtual-domain math for ImageListView."""

    def __init__(self, view):
        self._view = view

    def _resolve_source_model(self, source_model=None):
        if source_model is not None:
            return source_model
        model = self._view.model()
        if model and hasattr(model, "sourceModel"):
            return model.sourceModel()
        return model

    def get_strict_virtual_avg_height(self) -> float:
        """Return a stable virtual row height used by strict windowed masonry."""
        value = float(getattr(self._view, "_strict_virtual_avg_height", 0.0) or 0.0)
        if value > 1.0:
            return value
        # Deterministic fallback tied to thumbnail size; avoids thumb drift.
        value = max(32.0, float(self._view.current_thumbnail_size) + 2.0)
        self._view._strict_virtual_avg_height = value
        return value

    def estimate_strict_virtual_scroll_max(self, source_model=None) -> int:
        """Estimate a stable virtual scrollbar max for strict mode drag mapping."""
        try:
            source_model = self._resolve_source_model(source_model)
            if not source_model or not hasattr(source_model, "_paginated_mode") or not source_model._paginated_mode:
                return max(1, int(self._view.verticalScrollBar().maximum()))

            total_items = int(getattr(source_model, "_total_count", 0) or 0)
            if total_items <= 0:
                return max(1, int(self._view.verticalScrollBar().maximum()))

            spacing = 2
            viewport_width = max(1, int(self._view.viewport().width()))
            col_w = max(16, int(self._view.current_thumbnail_size))
            sb_width = self._view.verticalScrollBar().width() if self._view.verticalScrollBar().isVisible() else 15
            avail_width = viewport_width - sb_width - 24
            num_cols = max(1, avail_width // (col_w + spacing))

            import math
            rows = max(1, math.ceil(total_items / num_cols))
            avg_h = float(self.get_strict_virtual_avg_height())
            est_total_h = int(rows * max(10.0, avg_h))
            return max(1, est_total_h - max(1, int(self._view.viewport().height())))
        except Exception:
            return max(1, int(self._view.verticalScrollBar().maximum()))

    def get_strict_min_domain(self, source_model=None) -> int:
        """Return a stable strict domain aligned with virtual masonry height."""
        try:
            source_model = self._resolve_source_model(source_model)
            est = int(self.estimate_strict_virtual_scroll_max(source_model))
            # Keep small headroom to absorb minor relayout changes without collapsing.
            return max(10000, int(est * 1.10))
        except Exception:
            return max(10000, int(self._view.verticalScrollBar().maximum()))

    def get_strict_scroll_domain_max(self, source_model=None, *, include_drag_baseline: bool = False) -> int:
        """Return a robust strict-mode virtual scroll max used for page ownership mapping."""
        domain_max = max(
            1,
            int(self.get_strict_min_domain(source_model)),
            int(self.estimate_strict_virtual_scroll_max(source_model)),
            int(getattr(self._view, "_strict_scroll_max_floor", 0) or 0),
            int(getattr(self._view, "_strict_drag_frozen_max", 0) or 0),
        )
        if include_drag_baseline:
            domain_max = max(domain_max, int(getattr(self._view, "_drag_scroll_max_baseline", 0) or 0))
        return max(1, domain_max)

    def strict_canonical_domain_max(self, source_model=None) -> int:
        """Single source of truth for the strict-mode scrollbar domain."""
        try:
            source_model = self._resolve_source_model(source_model)
            if (
                not source_model
                or not hasattr(source_model, "_paginated_mode")
                or not source_model._paginated_mode
            ):
                return max(1, int(self._view.verticalScrollBar().maximum()))

            total_items = int(getattr(source_model, "_total_count", 0) or 0)
            if total_items <= 0:
                return max(1, int(self._view.verticalScrollBar().maximum()))

            import math
            spacing = 2
            viewport_width = max(1, int(self._view.viewport().width()))
            col_w = max(16, int(self._view.current_thumbnail_size))
            # Match masonry's column calculation (subtracts scrollbar + margins).
            # Always assume scrollbar visible to prevent column count drift.
            sb_width = self._view.verticalScrollBar().width() if self._view.verticalScrollBar().isVisible() else 15
            avail_width = viewport_width - sb_width - 24
            num_cols = max(1, avail_width // (col_w + spacing))
            rows = max(1, math.ceil(total_items / num_cols))
            # Keep canonical domain aligned with the avg_h used to build masonry items.
            avg_h = float(getattr(self._view, "_strict_masonry_avg_h", 0.0) or 0.0)
            if avg_h <= 1.0:
                avg_h = float(self.get_strict_virtual_avg_height())
            est_total_h = int(rows * max(10.0, avg_h))
            viewport_height = max(1, int(self._view.viewport().height()))
            return max(10000, est_total_h - viewport_height)
        except Exception:
            return max(10000, int(self._view.verticalScrollBar().maximum()))

    def strict_page_from_position(self, scroll_value: int, source_model=None) -> int:
        """Derive page index from scroll position."""
        source_model = self._resolve_source_model(source_model)
        total_items = int(getattr(source_model, "_total_count", 0) or 0)
        page_size = int(getattr(source_model, "PAGE_SIZE", 1000) or 1000)
        if total_items <= 0 or page_size <= 0:
            return 0
        last_page = max(0, (total_items - 1) // page_size)
        # Use actual scrollbar maximum; value is relative to it.
        sb_max = self._view.verticalScrollBar().maximum()
        domain = max(1, sb_max if sb_max > 0 else self.strict_canonical_domain_max(source_model))
        frac = max(0.0, min(1.0, int(scroll_value) / domain))
        item_idx = int(frac * total_items)
        page = item_idx // page_size
        return max(0, min(last_page, page))
