from widgets.image_list_shared import *  # noqa: F401,F403

class ImageListViewPaintSelectionMixin:
    def paintEvent(self, event):
        """Override paint to handle masonry layout rendering."""
        if self.use_masonry and self._drag_preview_mode:
            super().paintEvent(event)
            return
        # THROTTLE painting during active scrolling to prevent UI blocking
        # Skip paint if we painted too recently (< 16ms ago = faster than 60fps)
        if self.use_masonry:
            import time
            current_time = time.time()
            if not hasattr(self, '_last_paint_time'):
                self._last_paint_time = 0

            # During scrollbar-thumb dragging, throttle to max 30fps (33ms).
            # Do NOT throttle wheel/trackpad scrolling here; skipping those
            # paints can cause visible blank "curtain" artifacts while moving.
            if self._scrollbar_dragging:
                time_since_paint = (current_time - self._last_paint_time) * 1000
                if time_since_paint < 33:  # 33ms = 30fps
                    event.accept()
                    return  # Skip this paint, too soon

            self._last_paint_time = current_time

        if self.use_masonry and self._masonry_items and self.model():
            # Set flag to prevent layout changes during paint (prevents re-entrancy crash)
            self._painting = True
            try:
                import time
                paint_start = time.time()

                # Safety check: ensure model is valid
                if not self.model() or self.model().rowCount() == 0:
                    super().paintEvent(event)
                    return

                # Paint background
                painter = QPainter(self.viewport())
                painter.fillRect(self.viewport().rect(), self.palette().base())

                # Get visible viewport rect in absolute coordinates
                scroll_offset = self.verticalScrollBar().value()
                viewport_height = self.viewport().height()
                viewport_rect = QRect(0, scroll_offset, self.viewport().width(), viewport_height)

                # Add buffer zone for smooth scrolling (render items slightly outside viewport)
                buffer = 200  # pixels
                expanded_viewport = viewport_rect.adjusted(0, -buffer, 0, buffer)

                # Use masonry layout to get only visible items (OPTIMIZATION!)
                visible_items = self._get_masonry_visible_items(expanded_viewport)

                # Keep page loading aligned with what is actually visible.
                # Paint-time fallback exists only for blind-spot recovery during drag jumps.
                source_model = self.model().sourceModel() if hasattr(self.model(), 'sourceModel') else self.model()
                if source_model and hasattr(source_model, '_paginated_mode') and source_model._paginated_mode:

                    total_items = source_model._total_count if hasattr(source_model, '_total_count') else 0
                    page_size = source_model.PAGE_SIZE if hasattr(source_model, 'PAGE_SIZE') else 1000
                    local_anchor_mode = self._use_local_anchor_masonry(source_model)

                    real_visible = [it for it in visible_items if it.get('index', -1) >= 0]
                    req_start = None
                    req_end = None

                    if local_anchor_mode and total_items > 0 and page_size > 0:
                        # Prevent load-range thrash: drive range from scrollbar fraction.
                        total_pages = (total_items + page_size - 1) // page_size
                        last_page = max(0, total_pages - 1)
                        if self._scrollbar_dragging and self._drag_target_page is not None:
                            cur_page = max(0, min(last_page, int(self._drag_target_page)))
                        elif hasattr(self, '_current_page'):
                            cur_page = max(0, min(last_page, int(getattr(self, '_current_page', 0))))
                        else:
                            scroll_max = self.verticalScrollBar().maximum()
                            frac = max(0.0, min(1.0, (scroll_offset / scroll_max) if scroll_max > 0 else 0.0))
                            cur_page = max(0, min(last_page, int(round(frac * last_page))))
                        try:
                            buffer_pages = int(settings.value('thumbnail_eviction_pages', 3, type=int))
                        except Exception:
                            buffer_pages = 3
                        buffer_pages = max(1, min(buffer_pages, 5))
                        req_start = max(0, (cur_page - buffer_pages) * page_size)
                        req_end = min(total_items - 1, ((cur_page + buffer_pages + 1) * page_size) - 1)
                    else:
                        if real_visible:
                            real_visible.sort(key=lambda x: x['index'])
                            req_start = max(0, int(real_visible[0]['index']))
                            req_end = min(total_items - 1, int(real_visible[-1]['index']))
                        elif total_items > 0 and self._scrollbar_dragging:
                            # Blind spot while dragging: estimate by scrollbar fraction to recover quickly.
                            scroll_max = self.verticalScrollBar().maximum()
                            if scroll_max > 0:
                                scroll_fraction = max(0.0, min(1.0, scroll_offset / scroll_max))
                                est_idx = int(scroll_fraction * (total_items - 1))
                            else:
                                est_idx = 0
                            est_span = max(page_size, viewport_height // 32)
                            req_start = max(0, est_idx - (est_span // 2))
                            req_end = min(total_items - 1, est_idx + (est_span // 2))

                    strict_drag_active = local_anchor_mode and self._scrollbar_dragging
                    if req_start is not None and req_end is not None:
                        if self._scrollbar_dragging and page_size > 0:
                            self._current_page = max(0, min((total_items - 1) // page_size, req_start // page_size))
                        if (not strict_drag_active) and hasattr(source_model, 'ensure_pages_for_range'):
                            source_model.ensure_pages_for_range(req_start, req_end)

                    # If nothing is visible after a jump, force-load around current page immediately.
                    if (not strict_drag_active) and not visible_items and total_items > 0 and page_size > 0:
                        last_page = max(0, (total_items - 1) // page_size)
                        if self._scrollbar_dragging and self._drag_target_page is not None:
                            cur_page = max(0, min(last_page, int(self._drag_target_page)))
                        else:
                            cur_page = max(0, min(last_page, int(getattr(self, '_current_page', 0))))
                        force_start = max(0, (cur_page - 1) * page_size)
                        force_end = min(total_items - 1, (cur_page + 2) * page_size - 1)
                        if hasattr(source_model, 'ensure_pages_for_range'):
                            source_model.ensure_pages_for_range(force_start, force_end)

                # Auto-correct scroll bounds if needed.
                # IMPORTANT: strict mode must never hard-shrink max while dragging/relayout,
                # otherwise ownership snaps to a wrong page and viewport can go empty.
                max_allowed = self._get_masonry_total_height() - viewport_height
                if max_allowed > 0:
                    strategy = self._get_masonry_strategy(source_model)
                    strict_mode = strategy == "windowed_strict"
                    if strict_mode:
                        sb = self.verticalScrollBar()
                        keep_max = self._strict_canonical_domain_max(source_model)
                        if self._scrollbar_dragging or self._drag_preview_mode:
                            self._restore_strict_drag_domain(sb=sb, source_model=source_model)
                        else:
                            prev_block = sb.blockSignals(True)
                            _old_max = max(1, sb.maximum())
                            _old_val = sb.value()
                            if sb.maximum() != keep_max:
                                sb.setRange(0, keep_max)
                            # Re-anchor to locked page when domain changed.
                            _rl_page = getattr(self, '_release_page_lock_page', None)
                            _rl_live = (
                                _rl_page is not None
                                and time.time() < float(getattr(self, '_release_page_lock_until', 0.0) or 0.0)
                            )
                            if _rl_live and keep_max > 0:
                                _ps = int(getattr(source_model, 'PAGE_SIZE', 1000) or 1000)
                                _lock_idx = int(_rl_page) * _ps
                                _lock_it = None
                                for _it in self._masonry_items:
                                    if _it.get('index', -1) >= _lock_idx:
                                        _lock_it = _it
                                        break
                                if _lock_it is not None:
                                    sb.setValue(max(0, min(int(_lock_it['y']), keep_max)))
                                else:
                                    _ti = int(getattr(source_model, '_total_count', 0) or 0)
                                    _pf = max(0.0, min(1.0, _lock_idx / max(1, _ti)))
                                    sb.setValue(max(0, min(int(round(_pf * keep_max)), keep_max)))
                            elif _old_max != keep_max and keep_max > 0:
                                # Ratio-preserving correction when domain changed.
                                _ratio = _old_val / _old_max
                                sb.setValue(max(0, min(int(round(_ratio * keep_max)), keep_max)))
                            elif sb.value() > keep_max:
                                sb.setValue(keep_max)
                            sb.blockSignals(prev_block)
                    elif scroll_offset > max_allowed:
                        self.verticalScrollBar().setMaximum(max_allowed)
                        self.verticalScrollBar().setValue(max_allowed)

                items_painted = 0
                # Paint only visible items
                # Paint only visible items
                source_model = self.model().sourceModel() if hasattr(self.model(), 'sourceModel') else self.model()
                is_buffered = source_model and hasattr(source_model, '_paginated_mode') and source_model._paginated_mode

                # DEBUG: Track items that fail mapping
                skipped_count = 0
                first_skipped = []
                painted_count = 0
            
                # Snapshot cached selection state (updated via selection signals).
                # Avoid querying selectionModel() from paint; it has triggered
                # sporadic native crashes during rapid async page updates.
                selected_rows = set(getattr(self, "_selected_rows_cache", set()))
                current_row = int(getattr(self, "_current_proxy_row_cache", -1))

                real_visible_items = [it for it in visible_items if it.get('index', -1) >= 0]
                if (not visible_items or not real_visible_items) and is_buffered:
                    painter.setPen(Qt.GlobalColor.lightGray)
                    painter.drawText(self.viewport().rect(), Qt.AlignmentFlag.AlignCenter, "Loading target window...")
                    # Strict-mode recovery: if viewport landed in spacer void after a jump,
                    # move to nearest real masonry item so painting can resume immediately.
                    strategy = self._get_masonry_strategy(source_model) if source_model else "full_compat"
                    strict_mode = strategy == "windowed_strict"
                    if strict_mode and not (self._scrollbar_dragging or self._drag_preview_mode):
                        # During release-lock, the masonry recalc is in flight and will
                        # resolve the void; snapping here would corrupt the canonical
                        # scroll value (pixel y-coords vs. canonical domain).
                        _release_lock_live = (
                            getattr(self, '_release_page_lock_page', None) is not None
                            and time.time() < float(getattr(self, '_release_page_lock_until', 0.0) or 0.0)
                        )
                        if not _release_lock_live:
                            real_items_all = [it for it in self._masonry_items if it.get('index', -1) >= 0]
                            if real_items_all:
                                target_item = None
                                try:
                                    total_items_i = int(getattr(source_model, '_total_count', 0) or 0)
                                    page_size_i = int(getattr(source_model, 'PAGE_SIZE', 1000) or 1000)
                                    if total_items_i > 0 and page_size_i > 0:
                                        cur_page = max(0, min((total_items_i - 1) // page_size_i, int(getattr(self, '_current_page', 0) or 0)))
                                        p_start = cur_page * page_size_i
                                        p_end = min(total_items_i - 1, ((cur_page + 1) * page_size_i) - 1)
                                        page_candidates = [it for it in real_items_all if p_start <= int(it.get('index', -1)) <= p_end]
                                        if page_candidates:
                                            target_item = min(page_candidates, key=lambda it: int(it.get('y', 0)))
                                except Exception:
                                    target_item = None
                                if target_item is None:
                                    target_item = min(real_items_all, key=lambda it: abs(int(it.get('y', 0)) - int(scroll_offset)))
                                try:
                                    sb = self.verticalScrollBar()
                                    snap_y = max(0, min(int(target_item.get('y', 0)), int(sb.maximum())))
                                    now = time.time()
                                    if now - float(getattr(self, '_last_strict_void_snap_ts', 0.0) or 0.0) > 0.4:
                                        self._last_strict_void_snap_ts = now
                                        sb.setValue(snap_y)
                                except Exception:
                                    pass
                for item in visible_items:
                    # Draw spacers (negative index)
                    if item['index'] < 0:
                        # Spacer tokens keep Y continuity for windowed masonry.
                        # Avoid painting a full opaque block; it can appear as a giant gray square.
                        continue

                    # Construct valid index for painting
                    # ALWAYS map global index to loaded row in masonry mode
                    if hasattr(source_model, 'get_loaded_row_for_global_index'):
                        src_row = source_model.get_loaded_row_for_global_index(item['index'])
                    else:
                        src_row = item['index']
                    
                    if src_row == -1:
                        # Not loaded or belongs to a different view state
                        skipped_count += 1
                        continue
                    
                    
                    src_index = source_model.index(src_row, 0)
                    index = self.model().mapFromSource(src_index)

                    if not index.isValid():
                        continue

                    # Adjust rect to viewport coordinates
                    visual_rect = QRect(
                        item['rect'].x(),
                        item['rect'].y() - scroll_offset,
                        item['rect'].width(),
                        item['rect'].height()
                    )

                    # Skip if completely outside viewport (after buffer)
                    if visual_rect.bottom() < -buffer or visual_rect.top() > viewport_height + buffer:
                        continue
                    
                    # Create option for delegate using QStyleOptionViewItem
                    option = QStyleOptionViewItem()
                    option.rect = visual_rect
                    option.decorationSize = QSize(item['rect'].width(), item['rect'].height())
                    option.decorationAlignment = Qt.AlignCenter
                    option.palette = self.palette()  # Set palette for stamp drawing

                    # Set state flags
                    is_selected = index.row() in selected_rows
                    is_current = (current_row >= 0) and (index.row() == current_row)

                    # DEBUG: Report skipped items (only at deep scroll to avoid spam)
                    # if skipped_count > 0 and scroll_offset > 50000:
                    #    pass
                    # print(f"[PAINT_DEBUG] scroll={scroll_offset}, visible={len(visible_items)}, painted={items_painted}, skipped={skipped_count}, first_skipped={first_skipped}")

                    # Debug: log selection state for visible items
                    # if is_selected or is_current:
                    #     print(f"[DEBUG] Painting row={item.index}, is_selected={is_selected}, is_current={is_current}")

                    if is_selected:
                        option.state |= QStyle.StateFlag.State_Selected
                    if is_current:
                        option.state |= QStyle.StateFlag.State_HasFocus



                    # ALWAYS paint using delegate (it handles placeholders now)
                    # Fast scroll optimization removed because it prevented placeholders from showing
                    self.itemDelegate().paint(painter, option, index)

                    # Draw selection border on top
                    if is_selected or is_current:
                        painter.save()
                        pen = QPen(QColor(0, 120, 215), 4 if is_current else 2)
                        painter.setPen(pen)
                        painter.setBrush(Qt.BrushStyle.NoBrush)
                        painter.drawRect(visual_rect.adjusted(2, 2, -2, -2))
                        painter.restore()
                
                    # (Fast scroll optimization block removed)
                        # Debug: show rect for selected items
                        # print(f"[DEBUG] Painted selected item row={item.index}, visual_rect={visual_rect}, original_rect={item.rect}")

                    items_painted += 1

                painter.end()
            except Exception as e:
                # Catch any crashes during masonry painting to prevent segfaults
                print(f"[PAINT ERROR] Masonry paint crashed: {e}")
                import traceback
                traceback.print_exc()
                # Fall back to default painting
                super().paintEvent(event)
            finally:
                # Clear painting flag to allow layout changes again
                self._painting = False
        else:
            # Use default painting
            super().paintEvent(event)


    @Slot(Grid)
    def show_crop_size(self, grid):
        index = self.currentIndex()
        if index.isValid():
            image = index.data(Qt.ItemDataRole.UserRole)
            if grid is None:
                self.delegate.remove_label(index)
            else:
                crop_delta = grid.screen.size() - grid.visible.size()
                crop_fit = max(crop_delta.width(), crop_delta.height())
                crop_fit_text = f' (-{crop_fit})' if crop_fit > 0 else ''
                label = f'image: {image.dimensions[0]}x{image.dimensions[1]}\n'\
                        f'crop: {grid.screen.width()}x{grid.screen.height()}{crop_fit_text}\n'\
                        f'target: {grid.target.width()}x{grid.target.height()}'
                if grid.aspect_ratio is not None:
                    label += '✅' if grid.aspect_ratio[2] else ''
                    label += f'  {grid.aspect_ratio[0]}:{grid.aspect_ratio[1]}'
                self.delegate.update_label(index, label)


    def _disable_updates(self):
        """Disable widget updates during model reset."""
        self.setUpdatesEnabled(False)
        self.viewport().setUpdatesEnabled(False)


    def _enable_updates(self):
        """Re-enable widget updates after model reset."""
        # Defer re-enabling updates to next event loop iteration
        # This ensures the view's internal state is fully updated before repainting
        QTimer.singleShot(0, self._do_enable_updates)


    def _do_enable_updates(self):
        """Actually re-enable updates (called after event loop processes)."""
        self.setUpdatesEnabled(True)
        self.viewport().setUpdatesEnabled(True)

        # CRITICAL: Clear stale masonry data so new folder doesn't show old images
        self._masonry_items = []
        self._masonry_total_height = 0
        self._current_page = 0
        self._last_stable_scroll_value = 0
        self._strict_virtual_avg_height = 0.0
        self._strict_masonry_avg_h = 0.0
        self._strict_drag_frozen_max = 0
        self._strict_drag_frozen_until = 0.0
        self._strict_scroll_max_floor = 0

        # Reset preload state and start thumbnail loading immediately
        self._preload_index = 0
        self._preload_complete = False
        self._thumbnails_loaded.clear()
        self._thumbnail_cache_hits.clear()
        self._thumbnail_cache_misses.clear()
        # Start preloading immediately so users see progress bar right away
        QTimer.singleShot(100, self._preload_all_thumbnails)


    @Slot()
    def invert_selection(self):
        selected_proxy_rows = {index.row() for index in self.selectedIndexes()}
        all_proxy_rows = set(range(self.proxy_image_list_model.rowCount()))
        unselected_proxy_rows = all_proxy_rows - selected_proxy_rows
        first_unselected_proxy_row = min(unselected_proxy_rows, default=0)
        item_selection = QItemSelection()
        for row in unselected_proxy_rows:
            item_selection.append(
                QItemSelectionRange(self.proxy_image_list_model.index(row, 0)))
        self.setCurrentIndex(self.model().index(first_unselected_proxy_row, 0))
        self.selectionModel().select(
            item_selection, QItemSelectionModel.SelectionFlag.ClearAndSelect)


    def get_selected_images(self) -> list[Image]:
        selected_image_proxy_indices = self.selectedIndexes()
        selected_images = [index.data(Qt.ItemDataRole.UserRole)
                           for index in selected_image_proxy_indices]
        return selected_images


    @Slot()
    def copy_selected_image_tags(self):
        selected_images = self.get_selected_images()
        selected_image_captions = [self.tag_separator.join(image.tags)
                                   for image in selected_images]
        QApplication.clipboard().setText('\n'.join(selected_image_captions))


    def get_selected_image_indices(self) -> list[QModelIndex]:
        selected_image_proxy_indices = self.selectedIndexes()
        # print(f"[DEBUG] get_selected_image_indices: proxy indices = {[idx.row() for idx in selected_image_proxy_indices]}")
        selected_image_indices = [
            self.proxy_image_list_model.mapToSource(proxy_index)
            for proxy_index in selected_image_proxy_indices]
        # print(f"[DEBUG] get_selected_image_indices: source indices = {[idx.row() for idx in selected_image_indices]}")
        return selected_image_indices


    @Slot()
    def paste_tags(self):
        selected_image_count = len(self.selectedIndexes())
        if selected_image_count > 1:
            reply = get_confirmation_dialog_reply(
                title='Paste Tags',
                question=f'Paste tags to {selected_image_count} selected '
                         f'images?')
            if reply != QMessageBox.StandardButton.Yes:
                return
        tags = QApplication.clipboard().text().split(self.tag_separator)
        selected_image_indices = self.get_selected_image_indices()
        self.tags_paste_requested.emit(tags, selected_image_indices)


    @Slot()
    def copy_selected_image_file_names(self):
        selected_images = self.get_selected_images()
        selected_image_file_names = [image.path.name
                                     for image in selected_images]
        QApplication.clipboard().setText('\n'.join(selected_image_file_names))


    @Slot()
    def copy_selected_image_paths(self):
        selected_images = self.get_selected_images()
        selected_image_paths = [str(image.path) for image in selected_images]
        QApplication.clipboard().setText('\n'.join(selected_image_paths))


    @Slot()
    def move_selected_images(self):
        selected_images = self.get_selected_images()
        selected_image_count = len(selected_images)
        caption = (f'Select directory to move {selected_image_count} selected '
                   f'{pluralize("Image", selected_image_count)} and '
                   f'{pluralize("caption", selected_image_count)} to')
        move_directory_path = QFileDialog.getExistingDirectory(
            parent=self, caption=caption,
            dir=settings.value('directory_path', type=str))
        if not move_directory_path:
            return
        move_directory_path = Path(move_directory_path)

        # Check if any selected videos are currently loaded and unload them
        # Hierarchy: ImageListView -> container -> ImageList (QDockWidget) -> MainWindow
        main_window = self.parent().parent().parent()  # Get main window reference
        video_was_cleaned = False
        if hasattr(main_window, 'image_viewer') and hasattr(main_window.image_viewer, 'video_player'):
            video_player = main_window.image_viewer.video_player
            if video_player.video_path:
                currently_loaded_path = Path(video_player.video_path)
                # Check if we're moving the currently loaded video
                for image in selected_images:
                    if image.path == currently_loaded_path:
                        # Unload the video first (stop playback and release resources)
                        video_player.cleanup()
                        video_was_cleaned = True
                        break

        # Clear thumbnails for all selected videos to release graphics resources
        for image in selected_images:
            if hasattr(image, 'is_video') and image.is_video and image.thumbnail:
                image.thumbnail = None

        # If we cleaned up a video, give Qt/Windows a moment to release file handles
        if video_was_cleaned:
            from PySide6.QtCore import QThread
            QThread.msleep(100)  # 100ms delay
            QApplication.processEvents()  # Process pending events to ensure cleanup completes

        # Force garbage collection to release any remaining file handles
        import gc
        gc.collect()

        for image in selected_images:
            try:
                image.path.replace(move_directory_path / image.path.name)
                caption_file_path = image.path.with_suffix('.txt')
                if caption_file_path.exists():
                    caption_file_path.replace(
                        move_directory_path / caption_file_path.name)
                # Also move JSON metadata if it exists
                json_file_path = image.path.with_suffix('.json')
                if json_file_path.exists():
                    json_file_path.replace(
                        move_directory_path / json_file_path.name)
            except OSError as e:
                QMessageBox.critical(self, 'Error',
                                     f'Failed to move {image.path} to '
                                     f'{move_directory_path}.\n{str(e)}')
        self.directory_reload_requested.emit()
