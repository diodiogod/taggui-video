"""Masonry layout calculator for image grid display."""

import json
from pathlib import Path
from dataclasses import dataclass, asdict
from PySide6.QtCore import QRect, QSize, Qt


@dataclass
class MasonryItem:
    """Represents a positioned item in the masonry layout."""
    index: int
    rect: QRect
    aspect_ratio: float


class MasonryLayout:
    """Calculates masonry (Pinterest-style) layout positions for items."""

    CACHE_VERSION = 2  # Increment to invalidate all old caches

    def __init__(self, column_width: int = 200, spacing: int = 2, num_columns: int = 4):
        """
        Initialize masonry layout calculator.

        Args:
            column_width: Width of each column in pixels
            spacing: Spacing between items in pixels
            num_columns: Number of columns (auto-calculated if viewport width provided)
        """
        self.column_width = column_width
        self.spacing = spacing
        self.num_columns = num_columns
        self._column_heights = [0] * num_columns
        self._item_positions = []  # List of MasonryItem
        self._total_height = 0

    def set_viewport_width(self, width: int):
        """Calculate number of columns based on viewport width."""
        if width <= 0:
            return
        # Calculate how many columns fit
        self.num_columns = max(1, (width + self.spacing) // (self.column_width + self.spacing))
        self._reset_columns()

    def _reset_columns(self):
        """Reset column heights for recalculation."""
        self._column_heights = [0] * self.num_columns
        self._item_positions = []
        self._total_height = 0

    def add_item(self, index: int, aspect_ratio: float) -> QRect:
        """
        Add an item to the layout and return its calculated position.

        Args:
            index: Item index
            aspect_ratio: width / height ratio of the item

        Returns:
            QRect representing the item's position and size
        """
        # Calculate item height based on column width and aspect ratio
        item_width = self.column_width
        item_height = int(item_width / aspect_ratio) if aspect_ratio > 0 else item_width

        # Find the shortest column
        shortest_col = min(range(self.num_columns), key=lambda i: self._column_heights[i])

        # Calculate position
        x = shortest_col * (self.column_width + self.spacing)
        y = self._column_heights[shortest_col]

        # Create rect for this item
        rect = QRect(x, y, item_width, item_height)

        # Update column height
        self._column_heights[shortest_col] += item_height + self.spacing

        # Store item position
        item = MasonryItem(index=index, rect=rect, aspect_ratio=aspect_ratio)
        self._item_positions.append(item)

        # Update total height
        self._total_height = max(self._column_heights)

        return rect

    def calculate_all(self, items_data: list[tuple[int, float]], cache_key: str = None, progress_callback=None):
        """
        Calculate positions for all items at once.

        Args:
            items_data: List of (index, aspect_ratio) tuples
            cache_key: Optional cache key for saving/loading positions
            progress_callback: Optional callback(current, total) for progress updates
        """
        # Try to load from cache first
        if cache_key and self._load_from_cache(cache_key, items_data):
            print(f"    ✓ CACHE HIT: Loaded {len(items_data)} items from cache")
            if progress_callback:
                progress_callback(len(items_data), len(items_data))  # Report 100% immediately
            return  # Successfully loaded from cache

        if cache_key:
            print(f"    ✗ CACHE MISS: Calculating {len(items_data)} items...")

        # Calculate positions with progress updates
        self._reset_columns()
        total = len(items_data)
        for i, (index, aspect_ratio) in enumerate(items_data):
            self.add_item(index, aspect_ratio)
            # Release GIL every 10 items to let UI thread process keyboard events
            # Python's GIL can block UI even in background threads
            if i % 10 == 0:
                import time
                time.sleep(0)  # Releases GIL, allows UI thread to run
            # Report progress every 50 items to avoid too many signals
            if progress_callback and (i % 50 == 0 or i == total - 1):
                progress_callback(i + 1, total)

        # Save to cache
        if cache_key:
            self._save_to_cache(cache_key, items_data)

    def _get_cache_path(self, cache_key: str) -> Path:
        """Get the cache file path for a given key."""
        # Store cache in system temp directory
        cache_dir = Path.home() / '.taggui_cache' / 'masonry'
        cache_dir.mkdir(parents=True, exist_ok=True)
        # Use hash of cache_key as filename
        import hashlib
        key_hash = hashlib.md5(cache_key.encode()).hexdigest()
        return cache_dir / f'{key_hash}.json'

    def _save_to_cache(self, cache_key: str, items_data: list[tuple[int, float]]):
        """Save calculated positions to disk cache."""
        try:
            cache_path = self._get_cache_path(cache_key)
            cache_data = {
                'cache_version': self.CACHE_VERSION,
                'column_width': self.column_width,
                'spacing': self.spacing,
                'num_columns': self.num_columns,
                'items_count': len(items_data),
                'items': [
                    {
                        'index': item.index,
                        'x': item.rect.x(),
                        'y': item.rect.y(),
                        'width': item.rect.width(),
                        'height': item.rect.height(),
                        'aspect_ratio': item.aspect_ratio
                    }
                    for item in self._item_positions
                ],
                'total_height': self._total_height
            }
            with open(cache_path, 'w') as f:
                json.dump(cache_data, f)
        except Exception as e:
            print(f"Failed to save masonry cache: {e}")

    def _load_from_cache(self, cache_key: str, items_data: list[tuple[int, float]]) -> bool:
        """
        Load positions from disk cache if valid.

        Returns:
            True if loaded successfully, False otherwise
        """
        try:
            cache_path = self._get_cache_path(cache_key)
            if not cache_path.exists():
                return False

            with open(cache_path, 'r') as f:
                cache_data = json.load(f)

            # Validate cache version - reject old cache formats
            if cache_data.get('cache_version') != self.CACHE_VERSION:
                return False

            # Validate cache matches current configuration
            if (cache_data['column_width'] != self.column_width or
                cache_data['spacing'] != self.spacing or
                cache_data['num_columns'] != self.num_columns or
                cache_data['items_count'] != len(items_data)):
                return False

            # Validate aspect ratios match (same images in same order)
            # This prevents using cached layouts when sort order changes the image sequence
            cached_items = cache_data['items']
            import time
            for i, (index, aspect_ratio) in enumerate(items_data):
                if i >= len(cached_items):
                    return False
                cached_aspect = cached_items[i]['aspect_ratio']
                # Allow small floating point differences
                if abs(cached_aspect - aspect_ratio) > 0.001:
                    return False
                # Release GIL every 10 items
                if i % 10 == 0:
                    time.sleep(0)

            # Restore item positions
            self._reset_columns()
            self._item_positions = []
            for i, item in enumerate(cache_data['items']):
                self._item_positions.append(
                    MasonryItem(
                        index=item['index'],
                        rect=QRect(item['x'], item['y'], item['width'], item['height']),
                        aspect_ratio=item['aspect_ratio']
                    )
                )
                # Release GIL every 10 items
                if i % 10 == 0:
                    time.sleep(0)

            self._total_height = cache_data['total_height']

            # Restore column heights (reconstruct from items)
            self._column_heights = [0] * self.num_columns
            for i, item in enumerate(self._item_positions):
                col = item.rect.x() // (self.column_width + self.spacing)
                if 0 <= col < self.num_columns:
                    self._column_heights[col] = max(
                        self._column_heights[col],
                        item.rect.bottom() + self.spacing
                    )
                # Release GIL every 10 items
                if i % 10 == 0:
                    time.sleep(0)

            return True
        except Exception as e:
            print(f"Failed to load masonry cache: {e}")
            return False

    def get_item_rect(self, index: int) -> QRect:
        """Get the rectangle for a specific item index."""
        if index < len(self._item_positions):
            return self._item_positions[index].rect
        return QRect()

    def get_visible_items(self, viewport_rect: QRect) -> list[MasonryItem]:
        """
        Get items that are visible in the given viewport rectangle.

        Args:
            viewport_rect: The visible area

        Returns:
            List of MasonryItem objects that intersect with viewport
        """
        visible = []
        for item in self._item_positions:
            if item.rect.intersects(viewport_rect):
                visible.append(item)
        return visible

    def get_total_height(self) -> int:
        """Get the total height needed for all items."""
        return self._total_height

    def get_total_size(self) -> QSize:
        """Get the total size needed for the layout."""
        width = self.num_columns * (self.column_width + self.spacing) - self.spacing
        return QSize(width, self._total_height)

    # ========== Pagination Support ==========

    def calculate_page(self, page_num: int, items_data: list[tuple[int, float]],
                       append: bool = False) -> int:
        """
        Calculate layout for a single page of items.

        Args:
            page_num: Page number (for tracking)
            items_data: List of (index, aspect_ratio) tuples for this page
            append: If True, append to existing layout. If False, reset first.

        Returns:
            The starting Y position for this page
        """
        if not append:
            self._reset_columns()

        page_start_y = max(self._column_heights) if self._column_heights else 0

        for index, aspect_ratio in items_data:
            self.add_item(index, aspect_ratio)

        return page_start_y

    def estimate_total_height(self, total_items: int, loaded_items: int) -> int:
        """
        Estimate total height based on loaded items.

        Args:
            total_items: Total number of items in dataset
            loaded_items: Number of items already laid out

        Returns:
            Estimated total height for scrollbar
        """
        if loaded_items == 0 or self._total_height == 0:
            # No data yet, use rough estimate
            avg_height = self.column_width  # Assume square items
            items_per_row = self.num_columns
            estimated_rows = (total_items + items_per_row - 1) // items_per_row
            return estimated_rows * (avg_height + self.spacing)

        # Calculate average height per item from loaded data
        avg_height_per_item = self._total_height / loaded_items

        # Extrapolate to total items
        return int(avg_height_per_item * total_items)

    def get_page_at_position(self, y_position: int, page_size: int) -> int:
        """
        Estimate which page contains a given Y position.

        Args:
            y_position: Y scroll position
            page_size: Number of items per page

        Returns:
            Estimated page number
        """
        if not self._item_positions:
            return 0

        # Binary search for item at this Y position
        # Find first item whose rect.y() > y_position
        low, high = 0, len(self._item_positions) - 1
        result_idx = 0

        while low <= high:
            mid = (low + high) // 2
            if self._item_positions[mid].rect.y() <= y_position:
                result_idx = mid
                low = mid + 1
            else:
                high = mid - 1

        # Convert item index to page number
        return result_idx // page_size

    def get_items_in_range(self, start_y: int, end_y: int) -> list[MasonryItem]:
        """
        Get items within a Y range (for efficient rendering).

        Args:
            start_y: Start of range
            end_y: End of range

        Returns:
            List of items intersecting the range
        """
        items = []
        for item in self._item_positions:
            item_top = item.rect.y()
            item_bottom = item.rect.bottom()

            # Skip items completely above the range
            if item_bottom < start_y:
                continue

            # Stop if we've passed the range
            if item_top > end_y:
                break

            items.append(item)

        return items
