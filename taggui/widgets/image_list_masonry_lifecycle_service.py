import time
import traceback

from PySide6.QtCore import QTimer


class MasonryLifecycleService:
    """Owns masonry lifecycle orchestration for ImageListView."""

    def __init__(self, view):
        self._view = view

    def _source_model(self):
        model = self._view.model()
        if model and hasattr(model, "sourceModel"):
            return model.sourceModel()
        return model

    def do_recalculate_masonry(self):
        """Perform masonry recalculation after debounce, with safety gating."""
        # Keep legacy timestamp creation for debug parity.
        _timestamp = time.strftime("%H:%M:%S.") + f"{int(time.time() * 1000) % 1000:03d}"
        del _timestamp

        current_time = time.time()
        time_since_last_key = (current_time - self._view._last_filter_keystroke_time) * 1000
        if time_since_last_key < 50:
            self._view._masonry_recalc_timer.start(self._view._masonry_recalc_delay)
            return

        if self._view._masonry_calculating:
            self._view._masonry_recalc_timer.start(100)
            return

        if (
            hasattr(self._view, "_last_masonry_signal")
            and self._view._last_masonry_signal not in ["layoutChanged", "user_click"]
            and time_since_last_key < 3000
        ):
            self._view._masonry_recalc_timer.start(1000)
            return

        if self._view._rapid_input_detected:
            self._view._rapid_input_detected = False

        source_model = self._source_model()
        if source_model and hasattr(source_model, "_paginated_mode") and source_model._paginated_mode:
            loaded_pages = len(source_model._pages) if hasattr(source_model, "_pages") else 0
            self._view._log_flow(
                "MASONRY",
                f"Recalc requested; buffered pages loaded={loaded_pages}",
                throttle_key="masonry_recalc_req",
                every_s=0.5,
            )

        if self._view.use_masonry:
            self._view._calculate_masonry_layout()

    def check_masonry_completion(self):
        """Check whether async masonry calculation has completed."""
        source_model = self._source_model()
        if self._view._masonry_calc_future and self._view._masonry_calc_future.done():
            try:
                result = self._view._masonry_calc_future.result()
                self._view._on_masonry_calculation_complete(result)
            except Exception:
                traceback.print_exc()
                self._view._masonry_calculating = False
                if source_model and hasattr(source_model, "_enrichment_paused"):
                    source_model._enrichment_paused.clear()
                    print("[MASONRY] Resumed enrichment after error")
            return

        current_time = time.time()
        start_time = getattr(self._view, "_masonry_start_time", 0)
        if self._view._masonry_calculating and (current_time - start_time > 5.0):
            print(
                f"[MASONRY] ⚠️ Watchdog triggered: Calculation stuck for {current_time - start_time:.1f}s. Resetting state."
            )
            self._view._masonry_calculating = False
            self._view._masonry_calc_future = None
            if source_model and hasattr(source_model, "_enrichment_paused"):
                source_model._enrichment_paused.clear()
            return

        QTimer.singleShot(50, self._view._check_masonry_completion)

        if not hasattr(self._view, "_masonry_poll_counter"):
            self._view._masonry_poll_counter = 0
        self._view._masonry_poll_counter += 1

    def on_masonry_calculation_progress(self, current, total):
        """Update progress display while async calculation is running."""
        if hasattr(self._view, "_masonry_progress_bar"):
            self._view._masonry_progress_bar.setValue(current)
