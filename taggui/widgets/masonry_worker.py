"""Multiprocessing worker for masonry layout calculations.

This runs in a separate process to avoid Python GIL blocking the UI thread.
"""

import pickle
from pathlib import Path
from dataclasses import dataclass
import threading


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
    # Top-level safety wrapper to catch ANY crash before process dies
    try:
        return _calculate_masonry_layout_impl(items_data, column_width, spacing, num_columns, cache_key)
    except Exception as e:
        print(f"[MASONRY] FATAL: Top-level catch prevented process crash: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        # Return minimal valid result to prevent app crash
        return {
            'items': [],
            'total_height': 0
        }


def _calculate_masonry_layout_impl(items_data, column_width, spacing, num_columns, cache_key=None):
    """Internal implementation of masonry layout calculation."""
    try:
        # Try to load from cache first
        if cache_key:
            try:
                cached = _load_from_cache(cache_key, items_data, column_width, spacing, num_columns)
                if cached:
                    return cached
            except Exception as e:
                # Cache load failed, proceed with calculation
                print(f"[MASONRY] Cache load failed: {e}")

        # Calculate positions
        column_heights = [0] * num_columns
        positioned_items = []

        for index, aspect_ratio in items_data:
            # CHECK FOR SPACER
            # Spacer format: aspect_ratio is ('SPACER', height_pixels)
            if isinstance(aspect_ratio, tuple) and len(aspect_ratio) == 2 and aspect_ratio[0] == 'SPACER':
                spacer_height = int(aspect_ratio[1])
                
                # Push ALL columns down to the max height + spacer
                # This ensures the gap is preserved across the whole layout width
                max_h = max(column_heights)
                new_h = max_h + spacer_height
                for i in range(num_columns):
                    column_heights[i] = new_h
                
                # We don't create a visual item for the spacer
                continue

            # Calculate item dimensions
            item_width = column_width

            # Validate aspect ratio to prevent crashes
            if not isinstance(aspect_ratio, (int, float)):
                 aspect_ratio = 1.0 # Fallback for bad data

            if not aspect_ratio or aspect_ratio <= 0 or aspect_ratio != aspect_ratio:  # NaN check
                aspect_ratio = 1.0  # Fallback to square
            if aspect_ratio > 100:  # Extremely wide
                aspect_ratio = 100
            if aspect_ratio < 0.01:  # Extremely tall
                aspect_ratio = 0.01

            item_height = int(item_width / aspect_ratio)

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

        # Convert items to dicts manually (asdict() can crash on large datasets)
        items_list = []
        for item in positioned_items:
            items_list.append({
                'index': item.index,
                'x': item.x,
                'y': item.y,
                'width': item.width,
                'height': item.height,
                'aspect_ratio': item.aspect_ratio
            })

        result = {
            'items': items_list,
            'total_height': total_height
        }

        # Save to cache
        if cache_key:
            try:
                _save_to_cache(cache_key, result, items_data, column_width, spacing, num_columns)
            except Exception as e:
                # Cache save failed, but return result anyway
                print(f"[MASONRY] Cache save failed: {e}")

        return result

    except Exception as e:
        # Catch any crash and return minimal valid result to prevent app crash
        print(f"[MASONRY] CRITICAL ERROR in calculation: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        # Return empty but valid result
        return {
            'items': [],
            'total_height': 0
        }


def _get_cache_path(cache_key):
    """Get cache file path."""
    cache_dir = Path.home() / '.taggui_cache' / 'masonry'
    cache_dir.mkdir(parents=True, exist_ok=True)
    import hashlib
    key_hash = hashlib.md5(cache_key.encode()).hexdigest()
    return cache_dir / f'{key_hash}.pkl'  # Changed from .json to .pkl


def _save_to_cache_worker(cache_path, cache_data):
    """Background worker to save cache without blocking."""
    try:
        with open(cache_path, 'wb') as f:
            pickle.dump(cache_data, f, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as e:
        print(f"[MASONRY] Background cache save failed: {e}")


def _save_to_cache(cache_key, result, items_data, column_width, spacing, num_columns):
    """Save result to cache asynchronously in background thread."""
    try:
        cache_path = _get_cache_path(cache_key)
        cache_data = {
            'cache_version': 3,  # Bumped version for pickle format
            'column_width': column_width,
            'spacing': spacing,
            'num_columns': num_columns,
            'items_count': len(items_data),
            'items': result['items'],
            'total_height': result['total_height']
        }

        # Save in background thread so it never blocks
        thread = threading.Thread(
            target=_save_to_cache_worker,
            args=(cache_path, cache_data),
            daemon=True  # Don't prevent app exit
        )
        thread.start()

    except Exception as e:
        print(f"[MASONRY] Failed to start cache save thread: {e}")


def _load_from_cache(cache_key, items_data, column_width, spacing, num_columns):
    """Load result from cache if valid."""
    try:
        cache_path = _get_cache_path(cache_key)
        if not cache_path.exists():
            # Try old .json cache for migration
            old_cache_path = cache_path.with_suffix('.json')
            if old_cache_path.exists():
                print(f"[MASONRY] Deleting old JSON cache, will regenerate with pickle")
                old_cache_path.unlink()
            return None

        with open(cache_path, 'rb') as f:
            cache_data = pickle.load(f)

        # Validate cache
        if (cache_data.get('cache_version') != 3 or
            cache_data['column_width'] != column_width or
            cache_data['spacing'] != spacing or
            cache_data['num_columns'] != num_columns or
            cache_data['items_count'] != len(items_data)):
            return None

        # Validate aspect ratios match (sample check for performance)
        cached_items = cache_data['items']
        # Only validate first 100 items for speed (full validation too slow for 32K items)
        sample_size = min(100, len(items_data))
        for i in range(sample_size):
            index, aspect_ratio = items_data[i]
            if i >= len(cached_items):
                return None
            cached_aspect = cached_items[i]['aspect_ratio']
            if abs(cached_aspect - aspect_ratio) > 0.001:
                return None

        return {
            'items': cache_data['items'],
            'total_height': cache_data['total_height']
        }
    except Exception as e:
        print(f"[MASONRY] Cache load failed: {e}")
        return None
