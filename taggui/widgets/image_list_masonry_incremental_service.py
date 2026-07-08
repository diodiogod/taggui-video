"""Per-page masonry cache for incremental scroll updates.

Instead of recomputing the entire masonry layout every time a new page loads,
this service caches masonry results per page and allows appending new pages
without disturbing existing item positions.

Full recalc only happens on: drag jump, resize, enrichment, or config change.
"""

import math

from utils.diagnostic_logging import diagnostic_print


class MasonryIncrementalService:
    """Manages per-page masonry cache for incremental scroll updates."""

    def __init__(self, view):
        self._view = view
        self._page_cache = {}  # page_num -> {'items': [...], 'end_heights': [...]}
        self._cache_config = None  # (col_w, spacing, num_cols)
        self._prefix_height = 0  # frozen prefix spacer height
        self._cached_avg_h = 0.0
        self._cached_page_size = 0

    def invalidate(self, reason="unknown"):
        """Clear all cached pages (on jump, resize, enrichment)."""
        if self._page_cache:
            diagnostic_print(
                f"[MASONRY-INCR] Cache invalidated ({len(self._page_cache)} pages): {reason}",
                detail="verbose",
            )
        self._page_cache.clear()
        self._prefix_height = 0
        self._cache_config = None

    @property
    def is_active(self):
        """True if we have a valid cache that can be extended."""
        return bool(self._page_cache) and self._cache_config is not None

    def get_cached_pages(self):
        return set(self._page_cache.keys())

    def cache_from_full_result(self, masonry_items, page_size, col_w, spacing, num_cols, avg_h):
        """After a full masonry recalc, cache results per page.

        Splits the masonry items by page and records ending column heights
        for each page so incremental appends can continue seamlessly.
        """
        self._page_cache.clear()
        self._cache_config = (col_w, spacing, num_cols)
        self._cached_avg_h = avg_h
        self._cached_page_size = page_size

        # Find prefix spacer height (spacer items have index < 0)
        self._prefix_height = 0
        for item in masonry_items:
            if item.get('index', 0) == -2 and item.get('y', 0) == 0:
                self._prefix_height = item.get('height', 0)
                break

        # Split real items by page
        pages = {}
        for item in masonry_items:
            idx = item.get('index', -1)
            if idx < 0:
                continue  # skip spacers
            page = idx // page_size
            if page not in pages:
                pages[page] = []
            pages[page].append(item)

        # Compute end_heights for each page
        for page_num in sorted(pages.keys()):
            items = pages[page_num]
            end_heights = self._compute_end_heights(items, col_w, spacing, num_cols)
            self._page_cache[page_num] = {
                'items': items,
                'end_heights': end_heights,
            }

    def _compute_end_heights(self, items, col_w, spacing, num_cols):
        """Compute column heights after all items in a page."""
        end_heights = [0] * num_cols
        for item in items:
            col = item['x'] // (col_w + spacing)
            if 0 <= col < num_cols:
                bottom = item['y'] + item['height'] + spacing
                if bottom > end_heights[col]:
                    end_heights[col] = bottom
        return end_heights

    def can_extend_down(self, page_num):
        """Check if we can incrementally append this page below."""
        if not self.is_active:
            return False
        if page_num in self._page_cache:
            return False  # already cached
        # Must be adjacent to an existing cached page
        return (page_num - 1) in self._page_cache

    def can_extend_up(self, page_num):
        """Check if we can incrementally prepend this page above."""
        if not self.is_active:
            return False
        if page_num in self._page_cache:
            return False
        return (page_num + 1) in self._page_cache

    def compute_page_down(self, page_num, items_data):
        """Compute masonry for a page appended below the current cache.

        Args:
            page_num: The page number to compute.
            items_data: List of (index, aspect_ratio) tuples for this page.

        Returns:
            List of positioned item dicts, or None if can't extend.
        """
        if not self.can_extend_down(page_num):
            return None

        col_w, spacing, num_cols = self._cache_config
        prev_cache = self._page_cache[page_num - 1]
        column_heights = list(prev_cache['end_heights'])

        items = self._layout_items(items_data, column_heights, col_w, spacing, num_cols)

        self._page_cache[page_num] = {
            'items': items,
            'end_heights': list(column_heights),  # modified in-place by _layout_items
        }
        return items

    def compute_page_up(self, page_num, items_data, total_items):
        """Compute masonry for a page prepended above the current cache.

        The existing cached band is treated as authoritative. New pages added
        above must align to that fixed band instead of shifting downstream
        pages, otherwise the landed/anchored item visibly jumps.

        Returns:
            List of positioned item dicts, or None if can't extend.
        """
        if not self.can_extend_up(page_num):
            return None

        col_w, spacing, num_cols = self._cache_config
        page_size = self._cached_page_size

        # Compute the new prefix spacer height (pages 0..page_num-1)
        if page_num > 0:
            prefix_rows = math.ceil((page_num * page_size) / num_cols)
            new_prefix_h = int(prefix_rows * self._cached_avg_h)
        else:
            new_prefix_h = 0

        # Start column heights at the end of the new prefix
        column_heights = [new_prefix_h] * num_cols

        items = self._layout_items(items_data, column_heights, col_w, spacing, num_cols)
        end_heights = list(column_heights)

        # Align the new page to the fixed downstream band.
        next_cache = self._page_cache[page_num + 1]
        next_start_y = min(item['y'] for item in next_cache['items']) if next_cache['items'] else 0
        my_max_y = max(end_heights) if end_heights else 0

        # If there's a gap or overlap between this page and the next, move only
        # the new page and prefix height. Never shift the already-visible band.
        delta = next_start_y - my_max_y
        if abs(delta) > 2:
            for item in items:
                item['y'] += delta
            end_heights = [h + delta for h in end_heights]
            new_prefix_h += delta

        self._page_cache[page_num] = {
            'items': items,
            'end_heights': end_heights,
        }
        self._prefix_height = new_prefix_h
        return items

    def _layout_items(self, items_data, column_heights, col_w, spacing, num_cols):
        """Compute masonry positions for items, modifying column_heights in place."""
        items = []
        for index, aspect_ratio in items_data:
            if isinstance(aspect_ratio, tuple):
                continue  # skip spacers

            aspect_ratio = self._sanitize_aspect_ratio(aspect_ratio)

            item_width = col_w
            item_height = int(item_width / aspect_ratio)

            shortest_col = min(range(num_cols), key=lambda i: column_heights[i])
            x = shortest_col * (col_w + spacing)
            y = column_heights[shortest_col]

            items.append({
                'index': index,
                'x': x,
                'y': y,
                'width': item_width,
                'height': item_height,
                'aspect_ratio': aspect_ratio,
            })

            column_heights[shortest_col] += item_height + spacing

        return items

    def _sanitize_aspect_ratio(self, aspect_ratio):
        if not isinstance(aspect_ratio, (int, float)) or aspect_ratio <= 0:
            aspect_ratio = 1.0
        if aspect_ratio != aspect_ratio:  # NaN
            aspect_ratio = 1.0
        if aspect_ratio > 100:
            aspect_ratio = 100
        if aspect_ratio < 0.01:
            aspect_ratio = 0.01
        return aspect_ratio

    def _layout_items_upward(self, items_data, column_tops, col_w, spacing, num_cols):
        """Compute masonry positions upward, modifying column_tops in place."""
        items = []
        for index, aspect_ratio in items_data:
            if isinstance(aspect_ratio, tuple):
                continue

            aspect_ratio = self._sanitize_aspect_ratio(aspect_ratio)
            item_width = col_w
            item_height = int(item_width / aspect_ratio)

            # Reverse of shortest-column downward layout: place into the column
            # whose current top boundary is lowest on screen.
            chosen_col = max(range(num_cols), key=lambda i: column_tops[i])
            x = chosen_col * (col_w + spacing)
            y = column_tops[chosen_col] - item_height - spacing

            items.append({
                'index': index,
                'x': x,
                'y': y,
                'width': item_width,
                'height': item_height,
                'aspect_ratio': aspect_ratio,
            })

            column_tops[chosen_col] = y

        items.reverse()
        return items

    def assemble_items(self):
        """Assemble _masonry_items from all cached pages + prefix spacer."""
        if not self._page_cache:
            return []

        cached_pages = sorted(self._page_cache.keys())
        items = []

        # Prefix spacer
        first_page = cached_pages[0]
        if first_page > 0 and self._prefix_height > 0:
            col_w, spacing, num_cols = self._cache_config
            full_width = (col_w + spacing) * num_cols - spacing
            items.append({
                'index': -2,
                'x': 0,
                'y': 0,
                'width': int(full_width),
                'height': int(self._prefix_height),
                'aspect_ratio': 1.0,
            })

        # Cached page items
        for page_num in cached_pages:
            items.extend(self._page_cache[page_num]['items'])

        return items

    def reflow_cached_pages_from(self, page_num, items_data_loader):
        """Recompute a cached contiguous block from page_num downward.

        Returns the list of pages that were recomputed. Later pages ripple from
        the changed page using the previous cached page's end heights as the
        fixed upstream boundary.
        """
        if not self.is_active:
            return []
        if page_num not in self._page_cache:
            return []

        col_w, spacing, num_cols = self._cache_config
        cached_pages = sorted(self._page_cache.keys())
        if not cached_pages:
            return []

        pages_to_reflow = []
        cur = int(page_num)
        while cur in self._page_cache:
            pages_to_reflow.append(cur)
            cur += 1
        if not pages_to_reflow:
            return []

        first_cached_page = cached_pages[0]
        if (page_num - 1) in self._page_cache:
            column_heights = list(self._page_cache[page_num - 1]['end_heights'])
        else:
            start_y = int(self._prefix_height if page_num == first_cached_page else 0)
            column_heights = [start_y] * num_cols

        recomputed = []
        for p in pages_to_reflow:
            items_data = []
            if callable(items_data_loader):
                items_data = list(items_data_loader(p) or [])
            items = self._layout_items(items_data, column_heights, col_w, spacing, num_cols)
            self._page_cache[p] = {
                'items': items,
                'end_heights': list(column_heights),
            }
            recomputed.append(p)

        return recomputed

    def reflow_cached_pages_upward_from(self, page_num, items_data_loader):
        """Recompute a cached contiguous block from page_num upward.

        The downstream cached band stays authoritative. Each recomputed page is
        aligned to the already-cached page below it so the anchored band does
        not move when upper pages get corrected.
        """
        if not self.is_active:
            return []
        if page_num not in self._page_cache:
            return []

        cached_pages = sorted(self._page_cache.keys())
        if not cached_pages:
            return []

        pages_to_reflow = []
        cur = int(page_num)
        while cur in self._page_cache:
            pages_to_reflow.append(cur)
            cur -= 1
        if not pages_to_reflow:
            return []

        recomputed = []
        total_items = 0
        if self._cached_page_size > 0 and cached_pages:
            total_items = (max(cached_pages) + 1) * self._cached_page_size

        for p in pages_to_reflow:
            items_data = []
            if callable(items_data_loader):
                items_data = list(items_data_loader(p) or [])
            items = self.compute_page_up(int(p), items_data, total_items)
            if items is None:
                break
            recomputed.append(int(p))

        return recomputed

    def reflow_cached_pages_from_anchor_page(self, page_num, anchor_global, items_data_loader):
        """Recompute a cached block around a fixed anchor item.

        The anchor item's x/y stays fixed. Items before it are laid out upward
        from the anchor, items after it are laid out downward from the anchor,
        and later pages then continue downward from the anchor page's end
        heights.
        """
        if not self.is_active:
            return []
        if page_num not in self._page_cache:
            return []
        if not isinstance(anchor_global, int) or anchor_global < 0:
            return []

        col_w, spacing, num_cols = self._cache_config
        cached_pages = sorted(self._page_cache.keys())
        if not cached_pages:
            return []

        old_page_cache = self._page_cache.get(int(page_num)) or {}
        old_items = list(old_page_cache.get('items') or [])
        old_anchor_item = next(
            (dict(item) for item in old_items if int(item.get('index', -1)) == int(anchor_global)),
            None,
        )
        if old_anchor_item is None:
            return []

        items_data = []
        if callable(items_data_loader):
            items_data = list(items_data_loader(int(page_num)) or [])
        prefix_data = [
            entry for entry in items_data
            if isinstance(entry, tuple) and len(entry) >= 2 and int(entry[0]) < int(anchor_global)
        ]
        anchor_entry = next(
            (
                entry for entry in items_data
                if isinstance(entry, tuple) and len(entry) >= 2 and int(entry[0]) == int(anchor_global)
            ),
            None,
        )
        suffix_data = [
            entry for entry in items_data
            if isinstance(entry, tuple) and len(entry) >= 2 and int(entry[0]) > int(anchor_global)
        ]
        if anchor_entry is None:
            return []

        anchor_x = int(old_anchor_item.get('x', 0))
        anchor_y = int(old_anchor_item.get('y', 0))
        anchor_col = max(0, min(num_cols - 1, anchor_x // max(1, (col_w + spacing))))
        anchor_aspect_ratio = self._sanitize_aspect_ratio(anchor_entry[1])
        anchor_height = int(col_w / anchor_aspect_ratio)

        # Build the anchor item at the fixed location first.
        anchor_item = {
            'index': int(anchor_global),
            'x': anchor_col * (col_w + spacing),
            'y': anchor_y,
            'width': col_w,
            'height': anchor_height,
            'aspect_ratio': anchor_aspect_ratio,
        }

        # Layout items before the anchor upward from the anchor top.
        upward_tops = [int(anchor_y)] * num_cols
        prefix_items = self._layout_items_upward(
            list(reversed(prefix_data)),
            upward_tops,
            col_w,
            spacing,
            num_cols,
        )

        # Layout items after the anchor downward from the anchor row.
        column_heights = [int(anchor_y)] * num_cols
        column_heights[anchor_col] = int(anchor_y) + int(anchor_height) + int(spacing)
        suffix_items = self._layout_items(suffix_data, column_heights, col_w, spacing, num_cols)
        self._page_cache[int(page_num)] = {
            'items': prefix_items + [anchor_item] + suffix_items,
            'end_heights': list(column_heights),
        }

        recomputed = [int(page_num)]
        cur = int(page_num) + 1
        while cur in self._page_cache:
            downstream_data = []
            if callable(items_data_loader):
                downstream_data = list(items_data_loader(int(cur)) or [])
            downstream_items = self._layout_items(downstream_data, column_heights, col_w, spacing, num_cols)
            self._page_cache[int(cur)] = {
                'items': downstream_items,
                'end_heights': list(column_heights),
            }
            recomputed.append(int(cur))
            cur += 1

        return recomputed

    def purge_far_pages(self, current_page, max_pages=20):
        """Remove pages that are too far from the current page."""
        if len(self._page_cache) <= max_pages:
            return

        cached_pages = sorted(self._page_cache.keys())
        # Keep pages closest to current_page
        pages_by_distance = sorted(cached_pages, key=lambda p: abs(p - current_page))
        keep = set(pages_by_distance[:max_pages])
        purged = []
        for p in cached_pages:
            if p not in keep:
                del self._page_cache[p]
                purged.append(p)
        if purged:
            diagnostic_print(
                f"[MASONRY-INCR] Purged {len(purged)} far pages: {purged[0]}-{purged[-1]}",
                detail="verbose",
            )
