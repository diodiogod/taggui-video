from widgets.image_list_shared import *  # noqa: F401,F403

class ImageListViewRecalcMixin:
    def _do_recalculate_masonry(self):
        """Actually perform the masonry recalculation (called after debounce)."""
        import time
        timestamp = time.strftime("%H:%M:%S.") + f"{int(time.time() * 1000) % 1000:03d}"

        # Check if more keystrokes came in while timer was running (race condition)
        current_time = time.time()
        time_since_last_key = (current_time - self._last_filter_keystroke_time) * 1000
        if time_since_last_key < 50:  # Keystroke came in very recently (< 50ms ago)
            # print(f"[{timestamp}] ⚠️ SKIP: Keystroke {time_since_last_key:.0f}ms ago, user still typing")
            # Restart timer to wait for user to finish
            self._masonry_recalc_timer.start(self._masonry_recalc_delay)
            return

        # CRITICAL: Skip calculation entirely if already calculating
        # Even spawning threads can block the UI due to Qt/GIL overhead
        if self._masonry_calculating:
            # print(f"[{timestamp}] ⚠️ SKIP: Already calculating, will retry in 100ms")
            self._masonry_recalc_timer.start(100)
            return

        # CRITICAL: Skip ALL masonry calculations until user stops typing completely
        # Python's GIL means ANY computation in ANY thread blocks keyboard input
        # Even with time.sleep(0) every 10 items, 385-1147 items still blocks for 900ms
        # Solution: Keep showing old layout, only recalculate after typing stops for 3+ seconds
        # EXCEPTION: layoutChanged and user_click signals bypass this check (not related to typing)
        if hasattr(self, '_last_masonry_signal') and self._last_masonry_signal not in ['layoutChanged', 'user_click']:
            if time_since_last_key < 3000:
                # print(f"[{timestamp}] ⚠️ SKIP: Only {time_since_last_key:.0f}ms since last key, waiting for typing to fully stop")
                # Check again in 1 second
                self._masonry_recalc_timer.start(1000)
                return

        # Clear rapid input flag since user has stopped typing
        if self._rapid_input_detected:
            # print(f"[{timestamp}] ✓ User stopped typing for 3+ seconds, clearing rapid input flag")
            self._rapid_input_detected = False

        # Pagination mode with buffered masonry - only calculates for loaded pages
        source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else None
        if source_model and hasattr(source_model, '_paginated_mode') and source_model._paginated_mode:
            # Buffered mode - will only calculate for loaded pages
            loaded_pages = len(source_model._pages) if hasattr(source_model, '_pages') else 0
            self._log_flow("MASONRY", f"Recalc requested; buffered pages loaded={loaded_pages}",
                           throttle_key="masonry_recalc_req", every_s=0.5)

        # print(f"[{timestamp}] ⚡ EXECUTE: Timer expired, starting masonry calculation")
        if self.use_masonry:
            self._calculate_masonry_layout()
            # Don't call scheduleDelayedItemsLayout() or update() here!
            # They block the UI thread and should only be called when calculation completes
        # print(f"[{timestamp}] ⚡ Masonry thread spawned (async)")
