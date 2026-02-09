"""Per-page masonry cache for incremental scroll updates.

Instead of recomputing the entire masonry layout every time a new page loads,
this service caches masonry results per page and allows appending new pages
without disturbing existing item positions.

Full recalc only happens on: drag jump, resize, enrichment, or config change.
"""

import math


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
            print(f"[MASONRY-INCR] Cache invalidated ({len(self._page_cache)} pages): {reason}")
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

        This is trickier: we compute the page's masonry starting from the
        estimated prefix position, and adjust existing items if needed.

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

        # Check if the next page's items need shifting
        next_cache = self._page_cache[page_num + 1]
        next_start_y = min(item['y'] for item in next_cache['items']) if next_cache['items'] else 0
        my_max_y = max(end_heights) if end_heights else 0

        # If there's a gap or overlap between this page and the next,
        # shift the next page (and all subsequent pages) to align.
        delta = my_max_y - next_start_y
        if abs(delta) > 2:
            self._shift_pages_from(page_num + 1, delta)

        self._page_cache[page_num] = {
            'items': items,
            'end_heights': end_heights,
        }
        self._prefix_height = new_prefix_h
        return items

    def _shift_pages_from(self, start_page, delta_y):
        """Shift all cached pages from start_page onward by delta_y pixels."""
        for page_num in sorted(self._page_cache.keys()):
            if page_num < start_page:
                continue
            cache = self._page_cache[page_num]
            for item in cache['items']:
                item['y'] += delta_y
            cache['end_heights'] = [h + delta_y for h in cache['end_heights']]

    def _layout_items(self, items_data, column_heights, col_w, spacing, num_cols):
        """Compute masonry positions for items, modifying column_heights in place."""
        items = []
        for index, aspect_ratio in items_data:
            if isinstance(aspect_ratio, tuple):
                continue  # skip spacers

            if not isinstance(aspect_ratio, (int, float)) or aspect_ratio <= 0:
                aspect_ratio = 1.0
            if aspect_ratio != aspect_ratio:  # NaN
                aspect_ratio = 1.0
            if aspect_ratio > 100:
                aspect_ratio = 100
            if aspect_ratio < 0.01:
                aspect_ratio = 0.01

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
            print(f"[MASONRY-INCR] Purged {len(purged)} far pages: {purged[0]}-{purged[-1]}")
