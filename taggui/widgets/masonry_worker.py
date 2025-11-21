"""Multiprocessing worker for masonry layout calculations.

This runs in a separate process to avoid Python GIL blocking the UI thread.
"""

import json
from pathlib import Path
from dataclasses import dataclass, asdict


@dataclass
class MasonryItem:
    """Represents a positioned item in the masonry layout."""
    index: int
    x: int
    y: int
    width: int
    height: int
    aspect_ratio: float


def calculate_masonry_layout(items_data, column_width, spacing, num_columns, cache_key=None):
    """
    Calculate masonry layout in a separate process (no GIL blocking).

    Args:
        items_data: List of (index, aspect_ratio) tuples
        column_width: Width of each column
        spacing: Spacing between items
        num_columns: Number of columns
        cache_key: Optional cache key

    Returns:
        dict with 'items' (list of positioned items) and 'total_height'
    """
    # Try to load from cache first
    if cache_key:
        cached = _load_from_cache(cache_key, items_data, column_width, spacing, num_columns)
        if cached:
            return cached

    # Calculate positions
    column_heights = [0] * num_columns
    positioned_items = []

    for index, aspect_ratio in items_data:
        # Calculate item dimensions
        item_width = column_width
        item_height = int(item_width / aspect_ratio) if aspect_ratio > 0 else item_width

        # Find shortest column
        shortest_col = min(range(num_columns), key=lambda i: column_heights[i])

        # Calculate position
        x = shortest_col * (column_width + spacing)
        y = column_heights[shortest_col]

        # Store positioned item
        positioned_items.append(MasonryItem(
            index=index,
            x=x,
            y=y,
            width=item_width,
            height=item_height,
            aspect_ratio=aspect_ratio
        ))

        # Update column height
        column_heights[shortest_col] += item_height + spacing

    total_height = max(column_heights) if column_heights else 0

    result = {
        'items': [asdict(item) for item in positioned_items],
        'total_height': total_height
    }

    # Save to cache
    if cache_key:
        _save_to_cache(cache_key, result, items_data, column_width, spacing, num_columns)

    return result


def _get_cache_path(cache_key):
    """Get cache file path."""
    cache_dir = Path.home() / '.taggui_cache' / 'masonry'
    cache_dir.mkdir(parents=True, exist_ok=True)
    import hashlib
    key_hash = hashlib.md5(cache_key.encode()).hexdigest()
    return cache_dir / f'{key_hash}.json'


def _save_to_cache(cache_key, result, items_data, column_width, spacing, num_columns):
    """Save result to cache."""
    try:
        cache_path = _get_cache_path(cache_key)
        cache_data = {
            'cache_version': 2,
            'column_width': column_width,
            'spacing': spacing,
            'num_columns': num_columns,
            'items_count': len(items_data),
            'items': result['items'],
            'total_height': result['total_height']
        }
        with open(cache_path, 'w') as f:
            json.dump(cache_data, f)
    except Exception as e:
        print(f"Failed to save masonry cache: {e}")


def _load_from_cache(cache_key, items_data, column_width, spacing, num_columns):
    """Load result from cache if valid."""
    try:
        cache_path = _get_cache_path(cache_key)
        if not cache_path.exists():
            return None

        with open(cache_path, 'r') as f:
            cache_data = json.load(f)

        # Validate cache
        if (cache_data.get('cache_version') != 2 or
            cache_data['column_width'] != column_width or
            cache_data['spacing'] != spacing or
            cache_data['num_columns'] != num_columns or
            cache_data['items_count'] != len(items_data)):
            return None

        # Validate aspect ratios match
        cached_items = cache_data['items']
        for i, (index, aspect_ratio) in enumerate(items_data):
            if i >= len(cached_items):
                return None
            cached_aspect = cached_items[i]['aspect_ratio']
            if abs(cached_aspect - aspect_ratio) > 0.001:
                return None

        return {
            'items': cache_data['items'],
            'total_height': cache_data['total_height']
        }
    except Exception:
        return None
