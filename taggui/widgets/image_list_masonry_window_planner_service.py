import math
import time

from PySide6.QtCore import QRect

try:
    from utils.settings import settings
except ModuleNotFoundError:
    from taggui.utils.settings import settings


class MasonryWindowPlannerService:
    """Plans current-page window and spacer token layout for masonry buffering."""

    def __init__(self, view):
        self._view = view

    def resolve_current_page(
        self,
        *,
        source_model,
        page_size: int,
        total_items: int,
        strict_mode: bool,
        local_anchor_mode: bool,
    ) -> int:
        scroll_val = self._view.verticalScrollBar().value()
        scroll_max = self._view.verticalScrollBar().maximum()
        dragging_mode = self._view._scrollbar_dragging or self._view._drag_preview_mode
        source_idx = None

        anchor_active = (
            getattr(self._view, "_drag_release_anchor_active", False)
            and self._view._drag_release_anchor_idx is not None
            and time.time() < getattr(self._view, "_drag_release_anchor_until", 0.0)
        )
        stick_bottom = getattr(self._view, "_stick_to_edge", None) == "bottom"
        stick_top = getattr(self._view, "_stick_to_edge", None) == "top"

        # Restore override: main_window scroll restore sets this to bypass
        # scrollbar-to-page derivation (which drifts through competing writers).
        restore_page = getattr(self._view, '_restore_target_page', None)
        if restore_page is not None and not dragging_mode:
            return max(0, min(max(0, (total_items - 1) // page_size) if total_items > 0 else 0, int(restore_page)))

        # Resize/zoom anchor override: keep strict ownership stable while the
        # viewport geometry changes and scrollbar domains are re-derived.
        resize_page = getattr(self._view, '_resize_anchor_page', None)
        resize_until = float(getattr(self._view, '_resize_anchor_until', 0.0) or 0.0)
        if resize_page is not None and (not dragging_mode):
            if time.time() <= resize_until:
                return max(0, min(max(0, (total_items - 1) // page_size) if total_items > 0 else 0, int(resize_page)))
            self._view._resize_anchor_page = None
            self._view._resize_anchor_until = 0.0

        if stick_bottom and total_items > 0:
            source_idx = total_items - 1
        elif stick_top:
            source_idx = 0
        elif anchor_active:
            source_idx = int(self._view._drag_release_anchor_idx)
        elif strict_mode:
            if dragging_mode and self._view._drag_target_page is not None:
                strict_page = max(
                    0,
                    min(max(0, (total_items - 1) // page_size) if total_items > 0 else 0, int(self._view._drag_target_page)),
                )
            elif dragging_mode:
                slider_pos = int(self._view.verticalScrollBar().sliderPosition())
                strict_page = self._view._strict_page_from_position(slider_pos, source_model)
            else:
                strict_page = self._view._strict_page_from_position(scroll_val, source_model)
            source_idx = max(0, min(total_items - 1, strict_page * page_size))

        if (not strict_mode) and local_anchor_mode and total_items > 0 and scroll_max > 0:
            scroll_fraction = max(0.0, min(1.0, scroll_val / scroll_max))
            source_idx = int(scroll_fraction * total_items)
        elif (
            (not strict_mode)
            and (not anchor_active)
            and (not stick_bottom)
            and (not stick_top)
            and self._view._masonry_items
        ):
            viewport_height = self._view.viewport().height()
            viewport_rect = QRect(0, scroll_val, self._view.viewport().width(), viewport_height)
            visible_now = self._view._get_masonry_visible_items(viewport_rect)
            if visible_now:
                real_visible = [it for it in visible_now if it.get("index", -1) >= 0]
                if real_visible:
                    top_item = min(real_visible, key=lambda x: x["rect"].y())
                    source_idx = top_item["index"]

        if total_items > 0 and scroll_val <= 2:
            source_idx = 0
        elif total_items > 0 and scroll_max > 0 and scroll_val >= scroll_max - 2:
            source_idx = total_items - 1

        if source_idx is None and hasattr(self._view, "_current_page"):
            source_idx = max(0, int(self._view._current_page) * page_size)

        if source_idx is None and scroll_max > 0 and total_items > 0:
            scroll_fraction = scroll_val / scroll_max
            source_idx = int(scroll_fraction * total_items)

        if source_idx is None:
            source_idx = 0

        candidate_page = max(0, min((total_items - 1) // page_size if total_items > 0 else 0, source_idx // page_size))
        prev_page = self._view._current_page if hasattr(self._view, "_current_page") else candidate_page

        current_page = candidate_page
        if (
            (not local_anchor_mode)
            and (not anchor_active)
            and (not stick_bottom)
            and (not stick_top)
            and total_items > 0
            and candidate_page != prev_page
        ):
            half_page = max(1, page_size // 2)
            if candidate_page > prev_page:
                if source_idx < ((prev_page + 1) * page_size + half_page):
                    current_page = prev_page
            else:
                if source_idx > (prev_page * page_size - half_page):
                    current_page = prev_page

        if (
            (not local_anchor_mode)
            and (not anchor_active)
            and (not stick_bottom)
            and (not stick_top)
            and time.time() < getattr(self._view, "_masonry_sticky_until", 0.0)
        ):
            current_page = getattr(self._view, "_masonry_sticky_page", current_page)

        self._view._current_page = current_page
        return current_page

    def get_window_buffer(self) -> int:
        try:
            window_buffer = int(settings.value("thumbnail_eviction_pages", 3, type=int))
        except Exception:
            window_buffer = 3
        return max(1, min(window_buffer, 6))

    def compute_window_bounds(
        self,
        *,
        total_items: int,
        page_size: int,
        current_page: int,
        strategy: str,
        loaded_count: int,
        window_buffer: int,
    ):
        max_page = (total_items + page_size - 1) // page_size
        full_layout_mode = False
        if total_items > 0 and strategy != "windowed_strict":
            coverage = loaded_count / total_items
            if coverage >= 0.95 and total_items <= 50000:
                full_layout_mode = True

        if full_layout_mode:
            window_start_page = 0
            window_end_page = max_page - 1
            min_idx = 0
            max_idx = total_items
        else:
            window_start_page = max(0, current_page - window_buffer)
            window_end_page = min(max_page - 1, current_page + window_buffer)
            min_idx = window_start_page * page_size
            max_idx = min(total_items, (window_end_page + 1) * page_size)

        return {
            "max_page": max_page,
            "full_layout_mode": full_layout_mode,
            "window_start_page": window_start_page,
            "window_end_page": window_end_page,
            "min_idx": min_idx,
            "max_idx": max_idx,
        }

    def build_items_with_spacers(
        self,
        *,
        filtered_items,
        min_idx: int,
        max_idx: int,
        total_items: int,
        num_cols_est: int,
        avg_h: float,
        avail_width: int,
        column_width: int,
        spacing: int,
    ):
        items_data = []
        if filtered_items:
            filtered_items.sort(key=lambda x: x[0])

            if min_idx > 0:
                prefix_rows = math.ceil(min_idx / num_cols_est)
                prefix_h = int(prefix_rows * avg_h)
                items_data.append((-3, ("SPACER", prefix_h)))

            last_idx = min_idx - 1
            for item in filtered_items:
                curr_idx = item[0]
                gap = curr_idx - last_idx - 1
                if gap > 0:
                    gap_rows = math.ceil(gap / num_cols_est)
                    spacer_h = int(gap_rows * avg_h)
                    items_data.append((-1, ("SPACER", spacer_h)))
                items_data.append(item)
                last_idx = curr_idx

            if total_items > 0:
                last_item_idx = filtered_items[-1][0]
                target_end_idx = min(max_idx, total_items)
                gap = target_end_idx - last_item_idx - 1
                if gap > 0:
                    gap_rows = math.ceil(gap / num_cols_est)
                    spacer_h = int(gap_rows * avg_h)
                    items_data.append((-2, ("SPACER", spacer_h)))
        else:
            if total_items > 0:
                start = min(min_idx, total_items)
                end = min(max_idx, total_items)
                count = end - start
                if count > 0:
                    num_cols_est = max(1, avail_width // (column_width + spacing))
                    rows = math.ceil(count / num_cols_est)
                    spacer_h = int(rows * avg_h)
                    if min_idx > 0:
                        prefix_rows = math.ceil(min_idx / num_cols_est)
                        prefix_h = int(prefix_rows * avg_h)
                        items_data = [(-3, ("SPACER", prefix_h)), (min_idx, ("SPACER", spacer_h))]
                    else:
                        items_data = [(min_idx, ("SPACER", spacer_h))]

        if not items_data and total_items > 0:
            start = min(min_idx, total_items)
            end = min(max_idx, total_items)
            count = end - start
            if count > 0:
                num_cols_est = max(1, avail_width // (column_width + spacing))
                rows = math.ceil(count / num_cols_est)
                safe_avg = avg_h if avg_h > 1 else 100.0
                spacer_h = int(rows * safe_avg)
                if min_idx > 0:
                    prefix_rows = math.ceil(min_idx / num_cols_est)
                    prefix_h = int(prefix_rows * avg_h)
                    items_data = [(-3, ("SPACER", prefix_h)), (min_idx, ("SPACER", spacer_h))]
                else:
                    items_data = [(min_idx, ("SPACER", spacer_h))]

        return items_data
