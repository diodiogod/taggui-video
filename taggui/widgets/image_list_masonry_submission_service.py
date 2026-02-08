import threading
import traceback
from concurrent.futures import ThreadPoolExecutor

try:
    from widgets.masonry_worker import calculate_masonry_layout
except ModuleNotFoundError:
    from taggui.widgets.masonry_worker import calculate_masonry_layout


class MasonrySubmissionService:
    """Owns masonry worker submission and executor lifecycle concerns."""

    def __init__(self, view):
        self._view = view

    def prepare_executor(self):
        """Periodically recreate executor to avoid long-lived thread pool issues."""
        if not hasattr(self._view, "_masonry_calc_count"):
            self._view._masonry_calc_count = 0

        self._view._masonry_calc_count += 1
        if self._view._masonry_calc_count % 20 != 0:
            return

        print(f"[MASONRY] Recreating executor after {self._view._masonry_calc_count} calculations")
        try:
            old_executor = self._view._masonry_executor
            self._view._masonry_executor = ThreadPoolExecutor(max_workers=1)
            threading.Thread(target=lambda: old_executor.shutdown(wait=True), daemon=True).start()
        except Exception as e:
            print(f"[MASONRY] Failed to recreate executor: {e}")

    def submit_layout_job(self, items_data, column_width: int, spacing: int, num_columns: int, cache_key: str) -> bool:
        """Validate and submit a masonry calculation job to the worker executor."""
        try:
            items_data_copy = list(items_data)

            if not all(isinstance(item, (tuple, list)) and len(item) >= 2 for item in items_data_copy[:10]):
                print("[MASONRY] WARNING: items_data contains invalid entries, skipping calculation")
                self._view._masonry_calculating = False
                return False

            self._view._masonry_calc_future = self._view._masonry_executor.submit(
                calculate_masonry_layout,
                items_data_copy,
                column_width,
                spacing,
                num_columns,
                cache_key,
            )
            return True
        except Exception as e:
            print(f"[MASONRY] CRITICAL ERROR starting calculation: {e}")
            traceback.print_exc()
            self._view._masonry_calculating = False
            return False
