import time

from PySide6.QtCore import QItemSelectionModel, QTimer
from PySide6.QtWidgets import QAbstractItemView


class MasonryCompletionService:
    """Owns masonry completion handling and UI/apply lifecycle."""

    def __init__(self, view):
        self._view = view

    def on_masonry_calculation_complete(self, result):
        """Called when multiprocessing calculation completes."""
        v = self._view
        try:
            timestamp = time.strftime("%H:%M:%S.") + f"{int(time.time() * 1000) % 1000:03d}"

            v._masonry_calculating = False
            v._last_masonry_done_time = time.time()

            if result is None:
                source_model = v.model().sourceModel() if v.model() and hasattr(v.model(), 'sourceModel') else v.model()
                if source_model and hasattr(source_model, '_enrichment_paused'):
                    source_model._enrichment_paused.clear()
                    print("[MASONRY] Resumed enrichment (null result)")
                return

            # If view mode changed while this job was running, ignore stale results.
            current_gen = int(getattr(v, "_masonry_mode_generation", 0))
            calc_gen = int(getattr(v, "_masonry_calc_mode_generation", current_gen))
            if (not v.use_masonry) or (calc_gen != current_gen):
                source_model = v.model().sourceModel() if v.model() and hasattr(v.model(), 'sourceModel') else v.model()
                if source_model and hasattr(source_model, '_enrichment_paused'):
                    source_model._enrichment_paused.clear()
                return

            # result is the dict returned by worker
            result_dict = result
        
            # 1. ANCHORING: Capture current view position before updating data
            anchor_index = -1
            anchor_offset = 0
            scroll_val = v.verticalScrollBar().value()
            old_scroll_max = v.verticalScrollBar().maximum()
            viewport_height = v.viewport().height()

            if v._masonry_items:
                initial_viewport = v.viewport().rect().translated(0, scroll_val)
                visible_before = v._get_masonry_visible_items(initial_viewport)
                if visible_before:
                    visible_before.sort(key=lambda x: x['rect'].y())
                    anchor_index = visible_before[0]['index']
                    anchor_offset = visible_before[0]['rect'].y() - scroll_val

            # 2. Update model data
            v._masonry_items = result_dict.get('items', [])
            v._masonry_index_map = None
            total_height_chunk = result_dict.get('total_height', 0)

            # 3. Determine if buffered mode
            source_model = v.proxy_image_list_model.sourceModel()
            is_buffered = source_model and hasattr(source_model, '_paginated_mode') and source_model._paginated_mode
            strategy = v._get_masonry_strategy(source_model) if source_model else "full_compat"
            strict_mode = strategy == "windowed_strict"
            total_items = source_model._total_count if is_buffered else (v.model().rowCount() if v.model() else 0)

            # 4. CALIBRATION & ESTIMATION
            avg_height = getattr(v, '_stable_avg_item_height', 100.0)
            import math
        
            if v._masonry_items:
                # Real data refined average (row-based, not item-based).
                # Dividing by item count severely underestimates virtual height in multi-column grids.
                chunk_items = len([it for it in v._masonry_items if it.get('index', -1) >= 0])
                if chunk_items > 0 and total_height_chunk > 0:
                    column_width_for_avg = v.current_thumbnail_size
                    spacing_for_avg = 2
                    viewport_width_for_avg = v.viewport().width()
                    horizontal_padding = int(getattr(v, "_masonry_horizontal_padding", 0) or 0)
                    avail_w_for_avg = viewport_width_for_avg - horizontal_padding
                    num_columns_for_avg = max(1, avail_w_for_avg // (column_width_for_avg + spacing_for_avg))
                    chunk_rows = max(1, math.ceil(chunk_items / num_columns_for_avg))
                    if strict_mode:
                        # In strict/windowed mode, total_height_chunk includes the
                        # prefix spacer which inflates the average and creates a
                        # runaway growth loop (bigger avg → bigger spacer → bigger
                        # total_height → bigger avg → ...).  Compute real_avg from
                        # only the real items' vertical extent.
                        real_items_for_avg = [it for it in v._masonry_items if it.get('index', -1) >= 0]
                        if len(real_items_for_avg) >= 2:
                            min_real_y = min(it['y'] for it in real_items_for_avg)
                            max_real_y = max(it['y'] + it['height'] for it in real_items_for_avg)
                            content_h = max_real_y - min_real_y
                            real_avg = content_h / chunk_rows
                        else:
                            real_avg = total_height_chunk / chunk_rows
                    else:
                        real_avg = total_height_chunk / chunk_rows
                    if 10.0 < real_avg < 5000.0:
                        if strict_mode:
                            current_strict_avg = float(getattr(v, "_strict_virtual_avg_height", 0.0) or 0.0)
                            if current_strict_avg <= 1.0:
                                v._strict_virtual_avg_height = float(real_avg)
                            elif real_avg > current_strict_avg:
                                # Strict: only grow, never shrink. Keeps canonical domain stable.
                                blended = (current_strict_avg * 0.9) + (float(real_avg) * 0.1)
                                v._strict_virtual_avg_height = max(current_strict_avg, blended)
                        else:
                            if not hasattr(v, '_stable_avg_item_height'):
                                v._stable_avg_item_height = real_avg
                            else:
                                # Use a slower moving average to prevent oscillation loops
                                v._stable_avg_item_height = (v._stable_avg_item_height * 0.9) + (real_avg * 0.1)
                    
            # Use the most up-to-date stable average
            if strict_mode:
                avg_height = v._get_strict_virtual_avg_height()
            else:
                avg_height = getattr(v, '_stable_avg_item_height', 100.0)

            # Final total height estimation
            if math.isnan(avg_height):
                avg_height = v._get_strict_virtual_avg_height() if strict_mode else 100.0

            # Calculate actual columns to fix estimation error
            # (Previously assumed 1 column, causing massive overestimation with many columns)
            column_width = v.current_thumbnail_size
            spacing = 2
            viewport_width = v.viewport().width()
            horizontal_padding = int(getattr(v, "_masonry_horizontal_padding", 0) or 0)
            avail_w2 = viewport_width - horizontal_padding
            num_columns = max(1, avail_w2 // (column_width + spacing))
        
            estimated_rows = math.ceil(total_items / num_columns)
            v._masonry_total_height = int(estimated_rows * avg_height)
            v._masonry_total_height = max(v._masonry_total_height, estimated_rows * 10)

            # 5. BUFFER MODE SHIFTING & RESCUE
            # Buffer mode logic
            if is_buffered and v._masonry_items:
                first_item_idx = v._masonry_items[0]['index']
            
                # DEFAULT OFFSET: 0 (Cumulative Layout)
                # Since min_idx=0 and we use spacers, the item['y'] is already absolute.
                y_offset = 0
            
                # VISUAL ANCHORING (Blind Spot Fix):
                # If we don't have a visual anchor (jumped into void), 
                # align the content to where the user is LOOKING, not where theory says it should be.
                if anchor_index == -1 and first_item_idx > 0:
                    # User is at 'scroll_val'.
                    # Based on our PREVIOUS estimate (which led the user to drag here),
                    # they expect to see 'target_idx'.
                    # target_idx = scroll_val / old_avg (We don't have old_avg easily, but we know scroll_val)
                
                    # We can reverse it: Find the item in our new batch that SHOULD be at scroll_val
                    # matching the 'percentage' of the scrollbar? 
                    # Simpler: Just align the first visible loaded item to the top?
                    # No, that might shift Page 20 to top even if we scrolled to Page 21.

                    # Better: Calculate offset delta to minimize jump.
                    # The user is at `scroll_val`.
                    # We want the items to cover `scroll_val`.
                    # Currently they start at `result.y` (relative 0).
                    # If we use `y_offset = scroll_val`, then `item[0]` starts at `scroll_val`.
                    # This works if `item[0]` is roughly what corresponds to `scroll_val`.
                
                    # Let's try to match the 'expected index' to the scroll position
                    # This matches the paintEvent logic that requested these pages
                    expected_idx_at_top = int(scroll_val / avg_height) # Use CURRENT avg as best guess
                
                    # Find item in masonry list closest to this index
                    closest_item = min(v._masonry_items, key=lambda x: abs(x['index'] - expected_idx_at_top))
                
                    if abs(closest_item['index'] - expected_idx_at_top) < 2000: # Safety: only if reasonably close
                        # Align this item to the scroll top
                        # current_absolute_y = closest_item.y + y_offset
                        # target_absolute_y = scroll_val
                        # So: closest_item.y + new_offset = scroll_val
                        # new_offset = scroll_val - closest_item.y
                    
                        proposed_offset = scroll_val - closest_item['y']
                    
                        # Only apply if it doesn't deviate INSANELY from theory (e.g. +/- 50%)
                        # This prevents breaking the scrollbar physics completely
                        if 0.5 * y_offset < proposed_offset < 1.5 * y_offset:
                            y_offset = proposed_offset
                            # print(f"[ANCHOR] Blind Jump: Aligned item {closest_item['index']} to scroll {scroll_val}")

                if strict_mode:
                    # Strict mode keeps virtual ownership from scrollbar fraction; avoid
                    # blind re-anchoring offsets that can shift the viewport unexpectedly.
                    y_offset = 0
                elif first_item_idx == 0:
                     y_offset = 0

                # Shift all items to absolute y
                max_actual_y = 0
                has_first_item = False
                has_last_item = False
                for item in v._masonry_items:
                    item['y'] += y_offset
                    max_actual_y = max(max_actual_y, item['y'] + item['height'])
                    if item.get('index', -1) == 0:
                        has_first_item = True
                    if total_items > 0 and item.get('index', -1) == (total_items - 1):
                        has_last_item = True

                # Reconcile virtual height only in compatibility mode.
                # In strict mode, keeping a stable virtual height prevents thumb jitter.
                if not strict_mode:
                    if has_last_item:
                        v._masonry_total_height = max(max_actual_y, viewport_height + 1)
                    elif max_actual_y > v._masonry_total_height:
                        v._masonry_total_height = max_actual_y
                elif has_last_item and max_actual_y > v._masonry_total_height:
                    # Strict mode: never shrink virtual height, but do grow it when tail content
                    # proves the current estimate is too small (prevents bottom clipping).
                    previous_height = v._masonry_total_height
                    v._masonry_total_height = max(max_actual_y, viewport_height + 1)
                    strict_rows = max(1, math.ceil(total_items / max(1, num_columns)))
                    implied_avg = v._masonry_total_height / strict_rows
                    if 10.0 < implied_avg < 5000.0 and implied_avg > v._get_strict_virtual_avg_height():
                        v._strict_virtual_avg_height = implied_avg
                        # Also grow masonry_avg_h so canonical domain covers
                        # the actual tail content (otherwise the scrollbar max
                        # is too small to reach the true bottom by scrolling).
                        if implied_avg > float(getattr(v, '_strict_masonry_avg_h', 0.0) or 0.0):
                            v._strict_masonry_avg_h = implied_avg
                    v._log_flow(
                        "MASONRY",
                        f"Strict tail extend: total_height {previous_height}->{v._masonry_total_height}",
                        throttle_key="strict_tail_extend",
                        every_s=1.0,
                    )
            
                # RE-ALIGN VIEW (ANCHOR OR RESCUE)
                anchor_suppressed = v._scrollbar_dragging or (time.time() < getattr(v, '_suppress_anchor_until', 0.0))
                release_anchor_active = (
                    getattr(v, '_drag_release_anchor_active', False)
                    and v._drag_release_anchor_idx is not None
                    and time.time() < getattr(v, '_drag_release_anchor_until', 0.0)
                )
                if strict_mode:
                    sb = v.verticalScrollBar()
                    stable_max = v._strict_canonical_domain_max(source_model)
                    old_val = sb.value()
                    old_max_raw = int(sb.maximum())
                    old_max = max(1, old_max_raw)
                    was_at_top = int(old_val) <= 2
                    was_at_bottom = old_max_raw > 0 and int(old_val) >= old_max_raw - 2
                    def _strict_tail_scroll_target():
                        try:
                            total_items_i = int(getattr(source_model, '_total_count', 0) or 0)
                            if total_items_i <= 0 or not v._masonry_items:
                                return None
                            tail_idx = total_items_i - 1
                            tail_item = None
                            for _it in v._masonry_items:
                                if int(_it.get('index', -1)) == tail_idx:
                                    tail_item = _it
                                    break
                            if tail_item is None:
                                return None
                            tail_bottom = int(tail_item.get('y', 0)) + int(tail_item.get('height', 0))
                            return max(0, min(tail_bottom - max(1, viewport_height), stable_max))
                        except Exception:
                            return None
                    bottom_intent = False
                    top_intent = False
                    try:
                        page_size = int(getattr(source_model, 'PAGE_SIZE', 1000) or 1000)
                        last_page = max(0, (int(total_items) - 1) // max(1, page_size))
                        cur_page = getattr(v, '_current_page', None)
                        release_lock_page = getattr(v, '_release_page_lock_page', None)
                        bottom_intent = (
                            was_at_bottom
                            or getattr(v, '_stick_to_edge', None) == "bottom"
                            or (
                                isinstance(release_lock_page, int)
                                and release_lock_page >= last_page
                            )
                            or (
                                isinstance(cur_page, int)
                                and cur_page >= last_page
                                and old_max_raw > 0
                                and int(old_val) >= int(old_max * 0.80)
                            )
                        )
                        top_intent = (
                            was_at_top
                            or getattr(v, '_stick_to_edge', None) == "top"
                        )
                    except Exception:
                        bottom_intent = was_at_bottom
                        top_intent = was_at_top
                    _click_scroll_freeze = (
                        time.time()
                        < float(getattr(v, '_user_click_selection_frozen_until', 0.0) or 0.0)
                    )
                    if v._scrollbar_dragging or v._drag_preview_mode:
                        v._restore_strict_drag_domain(sb=sb, source_model=source_model)
                    elif _click_scroll_freeze:
                        # User recently clicked — update range but keep scroll
                        # value unchanged so the viewport doesn't jump.
                        prev_block = sb.blockSignals(True)
                        sb.setRange(0, stable_max)
                        if bottom_intent:
                            _tail_target = _strict_tail_scroll_target()
                            if _tail_target is not None:
                                sb.setValue(_tail_target)
                            else:
                                sb.setValue(max(0, min(old_val, stable_max)))
                        elif top_intent:
                            sb.setValue(0)
                        else:
                            sb.setValue(max(0, min(old_val, stable_max)))
                        sb.blockSignals(prev_block)
                    else:
                        # Block signals so the range change doesn't corrupt
                        # _last_stable_scroll_value via _on_scroll_value_changed.
                        prev_block = sb.blockSignals(True)
                        sb.setRange(0, stable_max)
                        # If release-lock is active, re-anchor the value to the
                        # locked page so the thumb stays put even if canonical
                        # domain grew (from avg_height adaptation).
                        release_lock_page = getattr(v, '_release_page_lock_page', None)
                        release_lock_live = (
                            release_lock_page is not None
                            and time.time() < float(getattr(v, '_release_page_lock_until', 0.0) or 0.0)
                        )
                        if v._pending_edge_snap == "bottom":
                            _tail_target = _strict_tail_scroll_target()
                            if _tail_target is not None:
                                sb.setValue(_tail_target)
                            else:
                                sb.setValue(max(0, min(old_val, stable_max)))
                            v._current_page = max(0, (total_items - 1) // source_model.PAGE_SIZE) if source_model else v._current_page
                        elif v._pending_edge_snap == "top":
                            sb.setValue(0)
                            v._current_page = 0
                        elif release_lock_live:
                            page_size = int(getattr(source_model, 'PAGE_SIZE', 1000) or 1000)
                            last_page = max(0, (int(total_items) - 1) // max(1, page_size))
                            release_page_i = max(0, int(release_lock_page))
                            # Bottom-intent drag release: keep true tail reachable.
                            # Locking to first item of last page creates a fake end
                            # above the real last item and causes pull-back behavior.
                            if release_page_i >= last_page:
                                _tail_target = _strict_tail_scroll_target()
                                if _tail_target is not None:
                                    target_val = int(_tail_target)
                                else:
                                    target_val = max(0, min(int(old_val), stable_max))
                            else:
                                # Prefer actual masonry y-coordinate of the locked page's
                                # first item so the viewport aligns with real content
                                # (formula-based fraction drifts when real heights != avg_h).
                                _lock_start_idx = release_page_i * page_size
                                _lock_item = None
                                for _it in v._masonry_items:
                                    if _it.get('index', -1) >= _lock_start_idx:
                                        _lock_item = _it
                                        break
                                if _lock_item is not None:
                                    target_val = max(0, min(int(_lock_item['y']), stable_max))
                                else:
                                    # Fallback: item-based fraction.
                                    page_frac = max(0.0, min(1.0, (_lock_start_idx) / max(1, total_items)))
                                    target_val = int(round(page_frac * stable_max))
                            sb.setValue(max(0, min(target_val, stable_max)))
                            v._last_stable_scroll_value = sb.value()
                        else:
                            restore_target = (
                                v._get_restore_anchor_scroll_value(source_model, stable_max)
                                if hasattr(v, '_get_restore_anchor_scroll_value')
                                else None
                            )
                            if restore_target is not None:
                                sb.setValue(max(0, min(int(restore_target), stable_max)))
                            elif bottom_intent:
                                _tail_target = _strict_tail_scroll_target()
                                if _tail_target is not None:
                                    sb.setValue(_tail_target)
                                else:
                                    sb.setValue(max(0, min(old_val, stable_max)))
                            elif top_intent:
                                sb.setValue(0)
                            else:
                                # Preserve absolute scroll value (clamped to new range).
                                # Ratio-preserving caused runaway drift: after zoom the
                                # domain changes dramatically so ratio * new_max maps
                                # to 0 or a distant position, corrupting the viewport.
                                sb.setValue(max(0, min(old_val, stable_max)))
                        sb.blockSignals(prev_block)
                elif release_anchor_active:
                    release_anchor_found = False
                    target_idx = int(v._drag_release_anchor_idx)
                    for item in v._masonry_items:
                        if item['index'] == target_idx:
                            sb = v.verticalScrollBar()
                            sb.setRange(0, max(0, v._masonry_total_height - viewport_height))
                            target_y = max(0, min(item['y'], sb.maximum()))
                            sb.setValue(target_y)
                            v._last_stable_scroll_value = target_y
                            release_anchor_found = True
                            break
                    if release_anchor_found:
                        if getattr(v, '_stick_to_edge', None) in {"top", "bottom"}:
                            v._drag_release_anchor_until = time.time() + 4.0
                        else:
                            v._drag_release_anchor_active = False
                            v._drag_release_anchor_until = 0.0
                            v._pending_edge_snap = None
                            v._pending_edge_snap_until = 0.0
                if (not strict_mode) and v._pending_edge_snap == "bottom":
                    sb = v.verticalScrollBar()
                    sb.setRange(0, max(0, v._masonry_total_height - viewport_height))
                    sb.setValue(sb.maximum())
                    v._current_page = max(0, (total_items - 1) // source_model.PAGE_SIZE) if source_model else v._current_page
                elif (not strict_mode) and v._pending_edge_snap == "top":
                    sb = v.verticalScrollBar()
                    sb.setRange(0, max(0, v._masonry_total_height - viewport_height))
                    sb.setValue(0)
                    v._current_page = 0
                if (not strict_mode) and anchor_index != -1 and not anchor_suppressed and not release_anchor_active:
                    found_anchor = False
                    for item in v._masonry_items:
                        if item['index'] == anchor_index:
                            new_scroll_y = item['y'] - anchor_offset
                            new_scroll_y = max(0, min(new_scroll_y, v._masonry_total_height - viewport_height))
                        
                            v.verticalScrollBar().setRange(0, v._masonry_total_height - viewport_height)
                            v.verticalScrollBar().setValue(new_scroll_y)
                            found_anchor = True
                            break
                
                    # If anchor not found, might be a drag into void - Rescue will handle it if above
                    if not found_anchor:
                        pass
            
                # RESCUE ONE-WAY (Avoid violent snap-back when scrolling down)
                if not strict_mode:
                    min_y = v._masonry_items[0]['y']
                    if (not release_anchor_active) and scroll_val + viewport_height < min_y:
                        # Viewport is stuck ABOVE the current loaded block. Snap down to start.
                        print(f"[RESCUE] Viewport {scroll_val} above block {min_y}. Snapping down.")
                        from PySide6.QtCore import QTimer
                        QTimer.singleShot(0, lambda: v.verticalScrollBar().setValue(min_y))
        
            elif not is_buffered:
                v._masonry_total_height = total_height_chunk

            # 5b. CACHE per-page masonry for incremental scroll updates
            if is_buffered and v._masonry_items and hasattr(v, '_get_masonry_incremental_service'):
                try:
                    page_size = source_model.PAGE_SIZE if hasattr(source_model, 'PAGE_SIZE') else 1000
                    v._get_masonry_incremental_service().cache_from_full_result(
                        v._masonry_items, page_size, column_width, spacing, num_columns, avg_height,
                    )
                except Exception as e:
                    print(f"[MASONRY-INCR] Cache store failed: {e}")

            # 6. ASYNC UI UPDATE
            from PySide6.QtCore import QTimer
            def apply_and_signal():
                try:
                    # If a recent user click is protecting the selection, block
                    # selection-model signals during the apply phase.  This
                    # prevents updateGeometries / Qt layout churn from firing
                    # spurious currentChanged that overwrite the clicked image.
                    _click_freeze = (
                        time.time()
                        < float(getattr(v, '_user_click_selection_frozen_until', 0.0) or 0.0)
                    )
                    _sel_model = v.selectionModel() if _click_freeze else None
                    if _sel_model:
                        _sel_model.blockSignals(True)
                    try:
                        v._apply_layout_to_ui(timestamp)
                    finally:
                        if _sel_model:
                            _sel_model.blockSignals(False)
                    v.layout_ready.emit()

                    def _ensure_selected_anchor_if_needed():
                        """Keep selected image anchored during resize/zoom relayout bursts.

                        Only scrolls when the target item would be OFF-SCREEN.
                        Never touches scroll when a user click freeze is active.
                        """
                        try:
                            now = time.time()

                            # User recently clicked — viewport must NOT move.
                            if now < float(getattr(v, '_user_click_selection_frozen_until', 0.0) or 0.0):
                                return

                            resize_anchor_live = (
                                getattr(v, '_resize_anchor_page', None) is not None
                                and now <= float(getattr(v, '_resize_anchor_until', 0.0) or 0.0)
                            )
                            restore_anchor_live = now <= float(getattr(v, '_restore_anchor_until', 0.0) or 0.0)
                            if not (resize_anchor_live or restore_anchor_live):
                                return

                            # If user is intentionally at an edge, never pull the viewport
                            # toward the selected item during resize-anchor hold.
                            sb_local = v.verticalScrollBar()
                            cur_scroll = int(sb_local.value())
                            max_scroll = int(sb_local.maximum())
                            at_top_edge = cur_scroll <= 2
                            at_bottom_edge = max_scroll > 0 and cur_scroll >= max_scroll - 2
                            if resize_anchor_live and (at_top_edge or at_bottom_edge):
                                return

                            target_global = getattr(v, '_selected_global_index', None)
                            if not (isinstance(target_global, int) and target_global >= 0):
                                target_global = getattr(v, '_restore_target_global_index', None)
                            if not (isinstance(target_global, int) and target_global >= 0):
                                return

                            source_model_local = (
                                v.model().sourceModel()
                                if v.model() and hasattr(v.model(), 'sourceModel')
                                else v.model()
                            )
                            if not source_model_local:
                                return

                            # IMPORTANT: avoid selection rebinding during resize/zoom anchoring.
                            # It can remap through transient buffered rows and cause jumpy
                            # "wrong image selected" behavior. Keep rebind only for restore.
                            if restore_anchor_live and (not resize_anchor_live):
                                if hasattr(source_model_local, 'get_loaded_row_for_global_index'):
                                    loaded_row = source_model_local.get_loaded_row_for_global_index(target_global)
                                    if loaded_row >= 0:
                                        src_idx = source_model_local.index(loaded_row, 0)
                                        proxy_model_local = v.model()
                                        proxy_idx = (
                                            proxy_model_local.mapFromSource(src_idx)
                                            if proxy_model_local and hasattr(proxy_model_local, 'mapFromSource')
                                            else src_idx
                                        )
                                        if proxy_idx.isValid() and v.currentIndex() != proxy_idx:
                                            sel_model = v.selectionModel()
                                            if sel_model is not None:
                                                sel_model.setCurrentIndex(
                                                    proxy_idx,
                                                    QItemSelectionModel.SelectionFlag.ClearAndSelect,
                                                )
                                            else:
                                                v.setCurrentIndex(proxy_idx)

                            # Anchor viewport to actual masonry item position.
                            target_item = None
                            for it in (v._masonry_items or []):
                                if int(it.get('index', -1)) == int(target_global):
                                    target_item = it
                                    break
                            if target_item is None:
                                return

                            cur_scroll = sb_local.value()
                            vh = v.viewport().height()
                            item_top = int(target_item.get('y', 0))
                            item_bot = item_top + int(target_item.get('height', 0))

                            # Only scroll if target item is NOT already visible.
                            # Unconditional centering caused viewport jumps when
                            # the user was viewing items away from the selection.
                            if item_top >= cur_scroll and item_bot <= (cur_scroll + vh):
                                return  # Already visible — don't move viewport

                            target_y = item_top + (item_bot - item_top) // 2 - (vh // 2)
                            target_y = max(0, min(target_y, int(sb_local.maximum())))
                            prev_block = sb_local.blockSignals(True)
                            try:
                                if sb_local.value() != target_y:
                                    sb_local.setValue(target_y)
                            finally:
                                sb_local.blockSignals(prev_block)
                            v._last_stable_scroll_value = target_y
                        except Exception:
                            pass

                    _ensure_selected_anchor_if_needed()
                
                    if v._recenter_after_layout:
                        v._recenter_after_layout = False
                        idx = v.currentIndex()
                        if idx.isValid():
                            # Manual scrollTo for masonry to ensure robust centering
                            # (Standard scrollTo fails with custom layout/buffered data)
                            try:
                                # Get global index
                                global_idx = idx.row()
                                if hasattr(v.model(), 'mapToSource'):
                                    src_idx = v.model().mapToSource(idx)
                                    if hasattr(source_model, 'get_global_index_for_row'):
                                        global_idx = source_model.get_global_index_for_row(src_idx.row())
                                    else:
                                        global_idx = src_idx.row()

                                # Find item rect in masonry map
                                item_rect = v._get_masonry_item_rect(global_idx)
                            
                                if not item_rect.isNull():
                                    # Scroll to center
                                    target_y = item_rect.center().y() - (v.viewport().height() // 2)
                                    target_y = max(0, min(target_y, v.verticalScrollBar().maximum()))
                                    v.verticalScrollBar().setValue(target_y)
                                else:
                                    # Fallback if item not found (e.g. not loaded yet)
                                    v.scrollTo(idx, QAbstractItemView.ScrollHint.PositionAtCenter)
                            except Exception as e:
                                print(f"[MASONRY] Manual scrollTo failed: {e}")
                                v.scrollTo(idx, QAbstractItemView.ScrollHint.PositionAtCenter)

                    # Resume enrichment
                    def resume_enrichment_delayed():
                        model_for_resume = v.model().sourceModel() if v.model() and hasattr(v.model(), 'sourceModel') else v.model()
                        if model_for_resume and hasattr(model_for_resume, '_enrichment_paused'):
                            model_for_resume._enrichment_paused.clear()
                    QTimer.singleShot(200, resume_enrichment_delayed)

                except Exception as e:
                    print(f"[MASONRY] UI update crashed: {e}")
                    model_for_error = v.model().sourceModel() if v.model() and hasattr(v.model(), 'sourceModel') else v.model()
                    if model_for_error and hasattr(model_for_error, '_enrichment_paused'):
                        model_for_error._enrichment_paused.clear()

            QTimer.singleShot(0, apply_and_signal)
        
            if not v._preload_complete:
                v._idle_preload_timer.start(100)

            # Finalize pending Home/End navigation now that masonry items exist.
            if getattr(v, '_pending_home_end_nav', None) is not None:
                v._finish_home_end_nav()

            # CRITICAL FIX: Check if a new calculation was requested while we were busy
            # This handles the case where pages loaded WHILE we were calculating spacers
            if getattr(v, '_masonry_recalc_pending', False):
                v._masonry_recalc_pending = False
                # print("[MASONRY] Triggering PENDING recalculation (pages loaded during calc)")
                QTimer.singleShot(50, v._calculate_masonry_layout)


        except Exception as e:
            print(f"[MASONRY] CRASH in completion handler: {e}")
            import traceback
            traceback.print_exc()
            v._masonry_calculating = False
            source_model = v.model().sourceModel() if v.model() and hasattr(v.model(), 'sourceModel') else v.model()
            if source_model and hasattr(source_model, '_enrichment_paused'):
                source_model._enrichment_paused.clear()
