from widgets.image_list_shared import *  # noqa: F401,F403

class ImageListViewInteractionMixin:
    def _event_global_point(self, event) -> QPoint:
        """Get reliable global mouse point from event."""
        try:
            if hasattr(event, "globalPosition"):
                return event.globalPosition().toPoint()
            if hasattr(event, "globalPos"):
                return event.globalPos()
        except Exception:
            pass
        return QCursor.pos()

    def _clear_spawn_drag_tracking(self):
        """Reset pending spawn-drag gesture tracking."""
        self._spawn_drag_start_pos = None
        self._spawn_drag_index = QPersistentModelIndex()
        self._spawn_drag_origin_global_pos = QPoint()

    def _begin_spawn_drag_active(self, index: QPersistentModelIndex, global_pos: QPoint | None = None):
        """Arm internal spawn-drag mode until left button release."""
        self._spawn_drag_active = True
        self._spawn_drag_active_index = QPersistentModelIndex(index)
        self._spawn_drag_last_global_pos = QPoint(global_pos) if global_pos is not None else QCursor.pos()
        try:
            live_index = self.model().index(index.row(), index.column())
        except Exception:
            live_index = QModelIndex()
        show_ghost = getattr(self, "_show_spawn_drag_ghost", None)
        if callable(show_ghost) and live_index.isValid():
            show_ghost(live_index)
        update_ghost = getattr(self, "_update_spawn_drag_ghost_pos", None)
        if callable(update_ghost):
            update_ghost(self._spawn_drag_last_global_pos)
        host = self.window()
        if host is not None and hasattr(host, "begin_compare_drag_from_thumbnail"):
            try:
                host.begin_compare_drag_from_thumbnail(index)
            except Exception:
                pass
        if hasattr(self, "_spawn_drag_poll_timer"):
            self._spawn_drag_poll_timer.start()

    def _finish_spawn_drag_active(self, *, should_spawn: bool):
        """Disarm internal spawn-drag mode and optionally spawn one viewer."""
        if hasattr(self, "_spawn_drag_poll_timer"):
            self._spawn_drag_poll_timer.stop()
        hide_ghost = getattr(self, "_hide_spawn_drag_ghost", None)
        if callable(hide_ghost):
            hide_ghost()
        host = self.window()
        active_index = QPersistentModelIndex(getattr(self, "_spawn_drag_active_index", QPersistentModelIndex()))
        self._spawn_drag_active = False
        self._spawn_drag_active_index = QPersistentModelIndex()
        compare_handled = False
        if should_spawn and host is not None and hasattr(host, "release_compare_drag"):
            try:
                compare_handled = bool(host.release_compare_drag(self._spawn_drag_last_global_pos))
            except Exception:
                compare_handled = False
        if compare_handled:
            return
        if should_spawn and active_index.isValid():
            try:
                live_index = self.model().index(active_index.row(), active_index.column())
            except Exception:
                live_index = QModelIndex()
            if live_index.isValid():
                spawn_direct = getattr(self, "_spawn_floating_for_index_at_cursor", None)
                if callable(spawn_direct):
                    spawn_direct(live_index, spawn_global_pos=self._spawn_drag_last_global_pos)
        if host is not None and hasattr(host, "cancel_compare_drag"):
            try:
                host.cancel_compare_drag()
            except Exception:
                pass

    def _poll_spawn_drag_release(self):
        """Release detector for ultra-fast drags that miss widget release events."""
        if not bool(getattr(self, "_spawn_drag_active", False)):
            if hasattr(self, "_spawn_drag_poll_timer"):
                self._spawn_drag_poll_timer.stop()
            return
        self._spawn_drag_last_global_pos = QCursor.pos()
        update_ghost = getattr(self, "_update_spawn_drag_ghost_pos", None)
        if callable(update_ghost):
            update_ghost(self._spawn_drag_last_global_pos)
        host = self.window()
        if host is not None and hasattr(host, "update_compare_drag_cursor"):
            try:
                host.update_compare_drag_cursor(self._spawn_drag_last_global_pos)
            except Exception:
                pass
        if not (QApplication.mouseButtons() & Qt.MouseButton.LeftButton):
            self._finish_spawn_drag_active(should_spawn=True)

    def _cancel_pending_zoom_anchor_on_user_click(self):
        """User click should take ownership from pending zoom/resize anchoring."""
        import time
        # Stop delayed zoom-finished recalc if user already made a deliberate click.
        if hasattr(self, '_resize_timer'):
            self._resize_timer.stop()
        # If a stale zoom/resize recalc was already queued, skip it once.
        self._skip_next_resize_recalc = True
        # Clear recenter intent from prior mode/zoom transitions.
        self._recenter_after_layout = False
        # Drop resize anchor lock so completion handler won't snap to stale target.
        if time.time() < float(getattr(self, '_resize_anchor_until', 0.0) or 0.0):
            self._resize_anchor_page = None
            self._resize_anchor_until = 0.0
        # Drop restore anchor — user's deliberate click supersedes startup restore.
        self._restore_anchor_until = 0.0
        self._restore_target_page = None
        self._restore_target_global_index = None
        # Clear main_window's restore-in-progress so save_image_index isn't suppressed.
        mw = self.window()
        if mw and hasattr(mw, '_restore_in_progress'):
            mw._restore_in_progress = False
            mw._restore_target_global_rank = -1

    def mousePressEvent(self, event):
        """Override mouse press to fix selection in masonry mode."""
        source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else None

        if event.button() == Qt.MouseButton.LeftButton:
            start_index = self.indexAt(event.pos())
            if start_index.isValid():
                self._spawn_drag_start_pos = event.pos()
                self._spawn_drag_index = QPersistentModelIndex(start_index)
                self._spawn_drag_origin_global_pos = self._event_global_point(event)
            else:
                self._spawn_drag_start_pos = None
                self._spawn_drag_index = QPersistentModelIndex()
                self._spawn_drag_origin_global_pos = QPoint()
        else:
            self._spawn_drag_start_pos = None
            self._spawn_drag_index = QPersistentModelIndex()
            self._spawn_drag_origin_global_pos = QPoint()
    
        # Pause enrichment during interaction to prevent crashes
        if source_model and hasattr(source_model, '_enrichment_timer') and source_model._enrichment_timer:
            source_model._enrichment_timer.stop()
            # Will resume after 500ms idle (see mouseReleaseEvent)

        if self.use_masonry and self._masonry_items:
            # Explicit click means user is choosing a new selection identity.
            self._selected_global_lock_until = 0.0
            self._selected_global_lock_value = None
            # If zoom/resize relayout is in-flight, ignore click to avoid stale
            # indexAt mapping against transient geometry.
            if getattr(self, '_masonry_calculating', False):
                event.accept()
                return
            if hasattr(self, '_resize_timer') and self._resize_timer.isActive():
                event.accept()
                return

            # Clear previous click freeze so THIS click's signals propagate.
            self._user_click_selection_frozen_until = 0.0

            # Prioritize user's explicit click over any pending zoom/resize anchor work.
            self._cancel_pending_zoom_anchor_on_user_click()

            # Resolve click target using the PAINTED geometry snapshot.
            # This is the key fix for post-zoom click drift: the user clicks
            # what was rendered, not what an async recalc may have replaced.
            index = QModelIndex()
            click_pos = event.pos()
            try:
                import time as _t
                clicked_global = -1

                # Prefer painted snapshot (immune to async recalc swaps).
                # CRITICAL: use the scroll offset that was active WHEN the
                # snapshot was captured, not the current scrollbar value.
                # updateGeometries() can change the scroll value between
                # paints, and using the wrong offset causes the hit-test to
                # resolve to a wrong item.
                painted = getattr(self, '_painted_hit_regions', None)
                painted_age = _t.time() - float(getattr(self, '_painted_hit_regions_time', 0.0) or 0.0)
                if painted and painted_age < 2.0:
                    snap_scroll = int(getattr(self, '_painted_hit_regions_scroll_offset', 0) or 0)
                    adjusted_point = QPoint(click_pos.x(), click_pos.y() + snap_scroll)
                    for g_idx, rect in painted.items():
                        if rect.contains(adjusted_point):
                            clicked_global = int(g_idx)
                            break
                else:
                    # Fallback: live masonry items (no recent paint).
                    scroll_offset = int(self.verticalScrollBar().value())
                    adjusted_point = QPoint(click_pos.x(), click_pos.y() + scroll_offset)
                    for item in reversed(self._masonry_items):
                        g_idx = int(item.get('index', -1))
                        if g_idx < 0:
                            continue
                        item_rect = QRect(
                            int(item.get('x', 0)),
                            int(item.get('y', 0)),
                            int(item.get('width', 0)),
                            int(item.get('height', 0)),
                        )
                        if item_rect.contains(adjusted_point):
                            clicked_global = g_idx
                            break

                if clicked_global >= 0 and source_model is not None:
                    self._selected_global_index = int(clicked_global)
                    if hasattr(source_model, 'get_loaded_row_for_global_index'):
                        src_row = source_model.get_loaded_row_for_global_index(clicked_global)
                    else:
                        src_row = clicked_global

                    if isinstance(src_row, int) and src_row >= 0:
                        src_idx = source_model.index(src_row, 0)
                        proxy_model = self.model()
                        if proxy_model and hasattr(proxy_model, 'mapFromSource'):
                            index = proxy_model.mapFromSource(src_idx)
                        else:
                            index = src_idx
                        if index.isValid():
                            _cur_scroll = int(self.verticalScrollBar().value())
                            _snap_s = int(getattr(self, '_painted_hit_regions_scroll_offset', 0) or 0)
                            _used_snap = painted and painted_age < 2.0
                            _delta = _cur_scroll - _snap_s if _used_snap else 0
                            print(f"[CLICK-HIT] global={clicked_global} proxy_row={index.row()} scroll={_cur_scroll} snap_scroll={_snap_s} delta={_delta} used_snap={_used_snap}")
                    else:
                        # If target page is not loaded yet, request it and ignore this click.
                        if hasattr(source_model, 'ensure_pages_for_range'):
                            source_model.ensure_pages_for_range(clicked_global, clicked_global + 1)
                        event.accept()
                        return
            except Exception:
                index = QModelIndex()

            if not index.isValid():
                # Fallback path
                index = self.indexAt(click_pos)

            if index.isValid():
                # Normalize to a fresh model-owned index (guards stale indexAt results
                # during rapid proxy/page churn).
                model = self.model()
                if model is None:
                    event.accept()
                    return
                row = index.row()
                if row < 0 or row >= model.rowCount():
                    event.accept()
                    return
                index = model.index(row, 0)
                if not index.isValid():
                    event.accept()
                    return

                # Check modifiers
                modifiers = event.modifiers()

                if modifiers & Qt.ControlModifier:
                    # Ctrl+Click: toggle selection WITHOUT clearing others
                    was_selected = self.selectionModel().isSelected(index)

                    # First, set as current index
                    self.selectionModel().setCurrentIndex(index, QItemSelectionModel.NoUpdate)

                    # Then toggle its selection state
                    if was_selected:
                        # print(f"[DEBUG] Ctrl+Click: deselecting row={index.row()}")
                        self.selectionModel().select(index, QItemSelectionModel.Deselect)
                    else:
                        # print(f"[DEBUG] Ctrl+Click: selecting row={index.row()}")
                        self.selectionModel().select(index, QItemSelectionModel.Select)

                    # Debug: show all selected indices
                    # all_selected = [idx.row() for idx in self.selectionModel().selectedIndexes()]
                    # print(f"[DEBUG] After Ctrl+Click, all selected rows: {all_selected}")

                    # Force repaint to show selection changes
                    self.viewport().update()
                elif modifiers & Qt.ShiftModifier:
                    # Shift+Click: range selection
                    current = self.currentIndex()
                    if current.isValid():
                        # Select all items between current and clicked index
                        start_row = min(current.row(), index.row())
                        end_row = max(current.row(), index.row())

                        # print(f"[DEBUG] Shift+Click: selecting range from row {start_row} to {end_row}")

                        # Build selection range
                        selection = QItemSelection()
                        for row in range(start_row, end_row + 1):
                            item_index = self.model().index(row, 0)
                            selection.select(item_index, item_index)

                        # Apply selection (add to existing if Ctrl also held)
                        self.selectionModel().select(selection, QItemSelectionModel.Select)
                        self.selectionModel().setCurrentIndex(index, QItemSelectionModel.NoUpdate)

                        # Debug: show all selected indices
                        # all_selected = [idx.row() for idx in self.selectionModel().selectedIndexes()]
                        # print(f"[DEBUG] After Shift+Click, all selected rows: {all_selected}")
                    else:
                        # No current index, just select this one
                        self.selectionModel().select(index, QItemSelectionModel.Select)
                        self.selectionModel().setCurrentIndex(index, QItemSelectionModel.NoUpdate)

                    # Force repaint
                    self.viewport().update()
                else:
                    # Normal click: clear and select only this item
                    # Use a single Qt selection operation. This is safer than
                    # clearSelection()+select() during rapid layout updates.
                    sel_model = self.selectionModel()
                    if sel_model:
                        sel_model.setCurrentIndex(
                            index, QItemSelectionModel.SelectionFlag.ClearAndSelect
                        )
                        self.viewport().update()

                # Freeze selection against recalc-driven mutations.
                # The click's own setCurrentIndex already fired synchronously above,
                # so all handlers (save_image_index, load_image, etc.) already ran
                # with the CORRECT index.  Any subsequent currentChanged triggered
                # by updateGeometries / layout churn in the completion path must NOT
                # overwrite the user's deliberate click.
                import time as _time_mod
                self._user_click_selection_frozen_until = _time_mod.time() + 2.0

                # Accept the event to prevent further processing
                event.accept()
            else:
                # Transient layout/proxy churn can briefly make indexAt invalid.
                # Keep current selection instead of clearing to avoid accidental remap.
                event.accept()
        else:
            # Use default behavior in list mode
            super().mousePressEvent(event)


    def mouseMoveEvent(self, event):
        """Handle thumbnail drag gestures and prevent rubber-band in masonry mode."""
        if bool(getattr(self, "_spawn_drag_active", False)):
            # Internal spawn-drag is armed; wait for release (event or poll timer).
            self._spawn_drag_last_global_pos = self._event_global_point(event)
            update_ghost = getattr(self, "_update_spawn_drag_ghost_pos", None)
            if callable(update_ghost):
                update_ghost(self._spawn_drag_last_global_pos)
            event.accept()
            return

        if (
            self._spawn_drag_start_pos is not None
            and self._spawn_drag_index.isValid()
            and (event.buttons() & Qt.MouseButton.LeftButton)
        ):
            drag_distance = (event.pos() - self._spawn_drag_start_pos).manhattanLength()
            if drag_distance >= QApplication.startDragDistance():
                spawn_drag_index = QPersistentModelIndex(self._spawn_drag_index)
                self._spawn_drag_start_pos = None
                self._spawn_drag_index = QPersistentModelIndex()
                drag_index = self.model().index(
                    spawn_drag_index.row() if spawn_drag_index.isValid() else -1,
                    spawn_drag_index.column() if spawn_drag_index.isValid() else 0,
                )
                if drag_index.isValid():
                    self._begin_spawn_drag_active(
                        QPersistentModelIndex(drag_index),
                        global_pos=self._event_global_point(event),
                    )
                    event.accept()
                    return
        elif self._spawn_drag_start_pos is not None and not (event.buttons() & Qt.MouseButton.LeftButton):
            # Lost-release fallback: if left is no longer down but no release
            # event arrived to this widget, forcibly clear drag tracking.
            self._clear_spawn_drag_tracking()

        if self.use_masonry and self._masonry_items:
            # Don't call super() - it triggers rubber-band selection
            # Just accept the event to prevent default behavior
            event.accept()
        else:
            super().mouseMoveEvent(event)


    def mouseDoubleClickEvent(self, event):
        """Handle double-click events."""
        # Double-click opens image in default app
        index = self.indexAt(event.pos())
        if index.isValid():
            # Get the image at this index
            image = index.data(Qt.ItemDataRole.UserRole)
            if image:
                # Visual feedback: flash the thumbnail
                self._flash_thumbnail(index)
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(image.path)))
                event.accept()
                return

        # Default behavior for other double-clicks
        super().mouseDoubleClickEvent(event)


    def _flash_thumbnail(self, index):
        """Create a quick flash and scale effect on thumbnail before opening."""
        from PySide6.QtCore import QPropertyAnimation, QEasingCurve, QRect, QParallelAnimationGroup
        from PySide6.QtWidgets import QGraphicsOpacityEffect

        # Get the viewport rect for this index
        rect = self.visualRect(index)

        # Create a temporary white overlay widget
        overlay = QWidget(self.viewport())
        overlay.setGeometry(rect)
        overlay.setStyleSheet("background-color: rgba(255, 255, 255, 180); border-radius: 4px;")
        overlay.show()

        # Opacity effect for fade
        opacity_effect = QGraphicsOpacityEffect(overlay)
        overlay.setGraphicsEffect(opacity_effect)

        # Create animation group for parallel animations
        animation_group = QParallelAnimationGroup(self)

        # Fade out animation
        fade_animation = QPropertyAnimation(opacity_effect, b"opacity")
        fade_animation.setDuration(250)
        fade_animation.setStartValue(1.0)
        fade_animation.setEndValue(0.0)
        fade_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Scale animation (grow slightly then shrink back)
        scale_animation = QPropertyAnimation(overlay, b"geometry")
        scale_animation.setDuration(250)

        # Calculate scaled rect (10% larger)
        center = rect.center()
        scaled_width = int(rect.width() * 1.1)
        scaled_height = int(rect.height() * 1.1)
        scaled_rect = QRect(
            center.x() - scaled_width // 2,
            center.y() - scaled_height // 2,
            scaled_width,
            scaled_height
        )

        scale_animation.setStartValue(rect)
        scale_animation.setKeyValueAt(0.4, scaled_rect)  # Peak at 40%
        scale_animation.setEndValue(rect)  # Back to original
        scale_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Add both animations to group
        animation_group.addAnimation(fade_animation)
        animation_group.addAnimation(scale_animation)

        # Clean up overlay when done
        animation_group.finished.connect(overlay.deleteLater)
        animation_group.start()


    def mouseReleaseEvent(self, event):
        """Override mouse release to prevent Qt from changing selection."""
        self._clear_spawn_drag_tracking()
        if bool(getattr(self, "_spawn_drag_active", False)):
            self._finish_spawn_drag_active(should_spawn=(event.button() == Qt.MouseButton.LeftButton))
            event.accept()
            return

        # Resume enrichment after 500ms idle
        source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else None
        if source_model and hasattr(source_model, '_enrichment_timer') and source_model._enrichment_timer:
            source_model._enrichment_timer.start(500)

        if self.use_masonry and self._masonry_items:
            # Just accept the event, don't let Qt handle it
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        # If pointer exits during a fast drag/release, ensure no stale spawn
        # gesture remains armed.
        if not bool(getattr(self, "_spawn_drag_active", False)):
            self._clear_spawn_drag_tracking()
        super().leaveEvent(event)

    def focusOutEvent(self, event):
        # Losing focus while dragging can drop release events; keep armed state
        # and let poll timer detect button release globally.
        if not bool(getattr(self, "_spawn_drag_active", False)):
            self._clear_spawn_drag_tracking()
        super().focusOutEvent(event)


    def keyPressEvent(self, event):
        """Handle keyboard events in the image list."""
        # Clear click-selection freeze so keyboard nav propagates normally.
        self._user_click_selection_frozen_until = 0.0
        if event.key() == Qt.Key.Key_Delete:
            # Toggle deletion marking for selected images
            selected_indices = self.selectedIndexes()
            if selected_indices:
                # Walk up the parent chain to find ImageList
                parent = self.parent()
                if parent:
                    parent = parent.parent()
                try:
                    parent.toggle_deletion_marking()
                    event.accept()
                    return
                except Exception as e:
                    print(f"[ERROR] Failed to toggle deletion marking: {e}")

        # Ctrl+Shift+D: Dev diagnostic / repair for thumbnail-image mismatch
        if (event.key() == Qt.Key.Key_D
                and event.modifiers() == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)):
            self._dev_diagnose_selection()
            event.accept()
            return

        # Home/End: navigate to first/last item in masonry paginated mode
        if event.key() in (Qt.Key.Key_Home, Qt.Key.Key_End) and self.use_masonry:
            source_model = (self.model().sourceModel()
                            if self.model() and hasattr(self.model(), 'sourceModel')
                            else self.model())
            if source_model and getattr(source_model, '_paginated_mode', False):
                self._masonry_home_end(event.key() == Qt.Key.Key_End, source_model)
                event.accept()
                return

        # Arrow/Page navigation: if selected image is offscreen after a drag jump,
        # first re-anchor viewport to the selected global item before moving.
        nav_keys = {
            Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right,
            Qt.Key.Key_PageUp, Qt.Key.Key_PageDown,
        }
        if event.key() in nav_keys and self.use_masonry:
            source_model = (
                self.model().sourceModel()
                if self.model() and hasattr(self.model(), 'sourceModel')
                else self.model()
            )
            if source_model and getattr(source_model, '_paginated_mode', False):
                import time as _t
                lock_active = _t.time() < float(getattr(self, '_selected_global_lock_until', 0.0) or 0.0)
                target_global = (
                    getattr(self, '_selected_global_lock_value', None)
                    if lock_active else
                    getattr(self, '_selected_global_index', None)
                )
                if isinstance(target_global, int) and target_global >= 0:
                    should_reanchor = False
                    current_global = None
                    try:
                        cur_idx = self.currentIndex()
                        if cur_idx.isValid():
                            src_idx = (
                                self.model().mapToSource(cur_idx)
                                if self.model() and hasattr(self.model(), 'mapToSource')
                                else cur_idx
                            )
                            if src_idx.isValid() and hasattr(source_model, 'get_global_index_for_row'):
                                current_global = source_model.get_global_index_for_row(src_idx.row())
                    except Exception:
                        current_global = None

                    if current_global != target_global:
                        should_reanchor = True
                    else:
                        rect = self._get_masonry_item_rect(target_global)
                        if not rect.isValid():
                            should_reanchor = True
                        else:
                            sb_val = int(self.verticalScrollBar().value())
                            vp_h = int(self.viewport().height())
                            item_top = int(rect.y())
                            item_bottom = int(rect.y() + rect.height())
                            if item_bottom < sb_val or item_top > (sb_val + vp_h):
                                should_reanchor = True

                    if should_reanchor:
                        # While lock is active, never navigate from remapped local
                        # currentIndex. First resolve back to stable selected global.
                        resolved = self._resolve_keyboard_anchor(source_model, target_global)
                        if resolved:
                            self._selected_global_lock_until = 0.0
                            self._selected_global_lock_value = None
                        else:
                            # Keep key consumed until stable target is materialized.
                            event.accept()
                            return
                    elif lock_active:
                        # Already anchored on stable global; release lock and navigate.
                        self._selected_global_lock_until = 0.0
                        self._selected_global_lock_value = None

        # Default behavior for other keys
        super().keyPressEvent(event)

    def _resolve_keyboard_anchor(self, source_model, target_global: int) -> bool:
        """Best-effort selection rebind for first keypress after drag jumps."""
        try:
            target_global = int(target_global)
        except Exception:
            return False
        if target_global < 0:
            return False

        # Fast path: already anchored.
        cur_global = self._current_global_from_current_index(source_model)
        if isinstance(cur_global, int) and cur_global == target_global:
            return True

        # First try locked-global enforcement (used by pages_updated flow).
        try:
            if self._enforce_locked_selected_global(source_model):
                cur_global = self._current_global_from_current_index(source_model)
                if isinstance(cur_global, int) and cur_global == target_global:
                    return True
        except Exception:
            pass

        # Fallback: explicit re-anchor helper (can request/force target page).
        try:
            self._reanchor_keyboard_to_selected_global(source_model, target_global)
        except Exception:
            return False

        cur_global = self._current_global_from_current_index(source_model)
        return isinstance(cur_global, int) and cur_global == target_global

    def _current_global_from_current_index(self, source_model):
        """Map current proxy index to stable global index."""
        try:
            cur_idx = self.currentIndex()
            if not cur_idx.isValid():
                return None
            src_idx = (
                self.model().mapToSource(cur_idx)
                if self.model() and hasattr(self.model(), 'mapToSource')
                else cur_idx
            )
            if not src_idx.isValid() or not hasattr(source_model, 'get_global_index_for_row'):
                return None
            mapped = source_model.get_global_index_for_row(src_idx.row())
            return int(mapped) if isinstance(mapped, int) and mapped >= 0 else None
        except Exception:
            return None

    def _reanchor_keyboard_to_selected_global(self, source_model, target_global: int) -> bool:
        """Rebind + center current selection to stable global index for keyboard nav."""
        try:
            target_global = int(target_global)
        except Exception:
            return False
        if target_global < 0:
            return False

        total_items = int(getattr(source_model, '_total_count', 0) or 0)
        page_size = int(getattr(source_model, 'PAGE_SIZE', 1000) or 1000)
        target_page = (target_global // max(1, page_size)) if total_items > 0 else 0

        # Load target page immediately when selection is outside loaded window.
        try:
            loaded_pages = getattr(source_model, '_pages', {})
            if isinstance(loaded_pages, dict) and target_page not in loaded_pages:
                if hasattr(source_model, '_load_page_sync'):
                    source_model._load_page_sync(target_page)
                    if hasattr(source_model, '_emit_pages_updated'):
                        source_model._emit_pages_updated()
        except Exception:
            pass

        loaded_row = -1
        if hasattr(source_model, 'get_loaded_row_for_global_index'):
            loaded_row = source_model.get_loaded_row_for_global_index(target_global)

        # Fallback: request page load + steer masonry window to selected page.
        if loaded_row < 0:
            try:
                if hasattr(source_model, 'ensure_pages_for_range'):
                    source_model.ensure_pages_for_range(target_global, target_global + 1)
                self._current_page = max(0, int(target_page))
                self._restore_target_page = int(target_page)
                self._restore_target_global_index = int(target_global)
                import time as _t
                self._restore_anchor_until = _t.time() + 4.0
                if self._get_masonry_strategy(source_model) == 'windowed_strict':
                    sb = self.verticalScrollBar()
                    canonical = int(self._strict_canonical_domain_max(source_model))
                    frac = (target_global / max(1, total_items - 1)) if total_items > 1 else 0.0
                    target_scroll = max(0, min(int(round(frac * canonical)), canonical))
                    prev_block = sb.blockSignals(True)
                    try:
                        sb.setRange(0, canonical)
                        sb.setValue(target_scroll)
                    finally:
                        sb.blockSignals(prev_block)
                self._last_masonry_window_signature = None
                self._calculate_masonry_layout()
            except Exception:
                pass
            return False

        src_idx = source_model.index(loaded_row, 0)
        proxy_model = self.model()
        proxy_idx = (
            proxy_model.mapFromSource(src_idx)
            if proxy_model and hasattr(proxy_model, 'mapFromSource')
            else src_idx
        )
        if not proxy_idx.isValid():
            try:
                if hasattr(source_model, 'ensure_pages_for_range'):
                    source_model.ensure_pages_for_range(target_global, target_global + 1)
                self._current_page = max(0, int(target_page))
                self._restore_target_page = int(target_page)
                self._restore_target_global_index = int(target_global)
                import time as _t
                self._restore_anchor_until = _t.time() + 4.0
                self._last_masonry_window_signature = None
                self._calculate_masonry_layout()
            except Exception:
                pass
            return False

        sel_model = self.selectionModel()
        if sel_model:
            sel_model.setCurrentIndex(proxy_idx, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        else:
            self.setCurrentIndex(proxy_idx)
        self.scrollTo(proxy_idx, QAbstractItemView.ScrollHint.PositionAtCenter)
        self.viewport().update()
        return True


    def _dev_diagnose_selection(self):
        """Ctrl+Shift+D: Diagnose and repair thumbnail-image mismatch.

        Prints a full mapping trace for the current selection and forces
        a page reload + masonry rebuild if a mismatch is detected.
        """
        import os
        print("\n" + "=" * 70)
        print("[DEV-DIAG] Ctrl+Shift+D: Thumbnail/Image mapping diagnostic")
        print("=" * 70)
        source_model = (self.model().sourceModel()
                        if self.model() and hasattr(self.model(), 'sourceModel')
                        else self.model())
        proxy_model = self.model()
        current_proxy_idx = self.currentIndex()

        # ── 1. Current selection info ──
        if not current_proxy_idx.isValid():
            print("[DEV-DIAG] No item currently selected.")
            print("=" * 70 + "\n")
            return

        proxy_row = current_proxy_idx.row()
        src_idx = proxy_model.mapToSource(current_proxy_idx) if hasattr(proxy_model, 'mapToSource') else current_proxy_idx
        src_row = src_idx.row() if src_idx.isValid() else -1
        image_via_proxy = proxy_model.data(current_proxy_idx, Qt.ItemDataRole.UserRole)
        image_path_proxy = getattr(image_via_proxy, 'path', '??') if image_via_proxy else 'None'

        print(f"  Proxy row      : {proxy_row}")
        print(f"  Source row     : {src_row}")
        print(f"  Image (proxy)  : {os.path.basename(str(image_path_proxy))}")

        # ── 2. Reverse-map: what global index does this source row correspond to? ──
        global_from_row = -1
        if hasattr(source_model, 'get_global_index_for_row'):
            global_from_row = source_model.get_global_index_for_row(src_row)
        print(f"  Global idx (from source row): {global_from_row}")

        # ── 3. Find the masonry item the user likely clicked ──
        scroll_val = self.verticalScrollBar().value()
        viewport_rect = self.viewport().rect().translated(0, scroll_val)
        visible_items = self._get_masonry_visible_items(viewport_rect) if self._masonry_items else []
        real_vis = [it for it in visible_items if it.get('index', -1) >= 0]
        masonry_global = None
        masonry_path = None
        if real_vis:
            # Find the masonry item whose mapped row matches proxy_row
            for it in real_vis:
                g_idx = it.get('index', -1)
                if hasattr(source_model, 'get_loaded_row_for_global_index'):
                    mapped_row = source_model.get_loaded_row_for_global_index(g_idx)
                else:
                    mapped_row = g_idx
                if mapped_row == src_row:
                    masonry_global = g_idx
                    break
            if masonry_global is None and real_vis:
                # Fallback: check middle visible item
                mid = real_vis[len(real_vis) // 2]
                masonry_global = mid.get('index', -1)
        print(f"  Masonry global idx (matched): {masonry_global}")

        # ── 4. Forward-map the masonry global index and compare ──
        if masonry_global is not None and masonry_global >= 0 and hasattr(source_model, 'get_loaded_row_for_global_index'):
            fwd_src_row = source_model.get_loaded_row_for_global_index(masonry_global)
            if fwd_src_row >= 0:
                fwd_src_idx = source_model.index(fwd_src_row, 0)
                fwd_proxy_idx = proxy_model.mapFromSource(fwd_src_idx) if hasattr(proxy_model, 'mapFromSource') else fwd_src_idx
                fwd_image = proxy_model.data(fwd_proxy_idx, Qt.ItemDataRole.UserRole) if fwd_proxy_idx.isValid() else None
                fwd_path = getattr(fwd_image, 'path', '??') if fwd_image else 'None'
                print(f"  Forward-mapped source row: {fwd_src_row}")
                print(f"  Forward-mapped image     : {os.path.basename(str(fwd_path))}")
                mismatch = str(image_path_proxy) != str(fwd_path)
                if mismatch:
                    print(f"  *** MISMATCH DETECTED ***")
                    print(f"      Viewer shows  : {os.path.basename(str(image_path_proxy))}")
                    print(f"      Masonry expects: {os.path.basename(str(fwd_path))}")
                else:
                    print(f"  Mapping OK - no mismatch.")
            else:
                print(f"  Forward-mapped source row: -1 (page not loaded)")

        # ── 5. Loaded pages state ──
        if hasattr(source_model, '_pages'):
            loaded_pages = sorted(source_model._pages.keys())
            page_sizes = {p: len(source_model._pages[p]) for p in loaded_pages[:10]}
            print(f"  Loaded pages   : {loaded_pages}")
            print(f"  Page sizes (first 10): {page_sizes}")
            if hasattr(source_model, 'PAGE_SIZE'):
                total_loaded = sum(len(source_model._pages[p]) for p in loaded_pages)
                print(f"  Total loaded rows: {total_loaded}  (model rowCount: {source_model.rowCount()})")

        # ── 6. Repair: clear stale thumbnail (memory + disk cache) + force reload ──
        print("[DEV-DIAG] Clearing stale thumbnail on selected image...")
        if image_via_proxy is not None:
            # Wipe in-memory cached thumbnail
            image_via_proxy.thumbnail = None
            image_via_proxy.thumbnail_qimage = None
            print(f"  Cleared in-memory thumbnail on: {os.path.basename(str(image_path_proxy))}")

            # Delete corrupted disk cache entry so it gets regenerated from source file
            try:
                from utils.thumbnail_cache import get_thumbnail_cache
                cache = get_thumbnail_cache()
                if cache.enabled:
                    thumb_width = getattr(source_model, 'thumbnail_generation_width', 512)
                    mtime = image_via_proxy.path.stat().st_mtime
                    cache_key = cache._get_cache_key(image_via_proxy.path, mtime, thumb_width)
                    cache_path = cache._get_cache_path(cache_key)
                    if cache_path.exists():
                        cache_path.unlink()
                        print(f"  Deleted disk cache entry: {cache_path.name}")
                    else:
                        print(f"  No disk cache entry found for this file.")
            except Exception as e:
                print(f"  Failed to clear disk cache: {e}")

            # Also clear any pending future for this row
            if hasattr(source_model, '_thumbnail_futures') and hasattr(source_model, '_thumbnail_lock'):
                with source_model._thumbnail_lock:
                    source_model._thumbnail_futures.pop(src_row, None)
                    source_model._thumbnail_futures.pop(proxy_row, None)

        # ── 7. Re-enrich: re-read dimensions from disk + update DB ──
        if image_via_proxy is not None and hasattr(source_model, '_directory_path') and source_model._directory_path:
            print("[DEV-DIAG] Re-enriching dimensions from disk...")
            try:
                import imagesize
                from utils.image_index_db import ImageIndexDB

                img_path = image_via_proxy.path
                suffix = img_path.suffix.lower()
                video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.webm'}
                is_video = suffix in video_extensions

                dimensions = None
                if is_video:
                    from utils.video_utils import extract_video_info
                    dimensions, _, _ = extract_video_info(img_path)
                elif suffix == '.jxl':
                    from utils.jxlutil import get_jxl_size
                    dimensions = get_jxl_size(img_path)
                else:
                    dimensions = imagesize.get(str(img_path))
                    if dimensions == (-1, -1):
                        dimensions = None
                    if dimensions:
                        # Verify with PIL for suspicious aspect ratios or JPEG EXIF rotation
                        ar = dimensions[0] / dimensions[1] if dimensions[1] else 1
                        needs_pil = (ar < 0.2 or ar > 5.0 or dimensions[0] > 12000
                                     or dimensions[1] > 12000
                                     or suffix in ('.jpg', '.jpeg'))
                        if needs_pil:
                            try:
                                from PIL import Image as _PILImage
                                with _PILImage.open(img_path) as _img:
                                    dimensions = _img.size
                                    if suffix in ('.jpg', '.jpeg', '.tif', '.tiff'):
                                        _exif = _img.getexif()
                                        if _exif:
                                            orientation = _exif.get(274)
                                            if orientation in (5, 6, 7, 8):
                                                dimensions = (dimensions[1], dimensions[0])
                            except Exception:
                                pass  # Keep imagesize result

                if dimensions and dimensions != (-1, -1):
                    old_dims = getattr(image_via_proxy, 'dimensions', None)
                    image_via_proxy.dimensions = dimensions
                    print(f"  Dimensions: {old_dims} → {dimensions[0]}x{dimensions[1]}")

                    rel_path = str(img_path.relative_to(source_model._directory_path))
                    mtime = img_path.stat().st_mtime
                    db_fix = ImageIndexDB(source_model._directory_path)
                    db_fix.save_info(rel_path, dimensions[0], dimensions[1], int(is_video), mtime)
                    db_fix.commit()
                    db_fix.close()
                    print(f"  DB updated: {rel_path}")

                    # Clear masonry caches so the new aspect ratio is reflected
                    self._last_masonry_window_signature = None
                    if hasattr(self, '_masonry_incremental_svc') and self._masonry_incremental_svc:
                        self._masonry_incremental_svc.clear_all()
                    # Force a full masonry recalc directly — dimensions_updated is
                    # throttled and has early-return guards that can silently drop it.
                    if hasattr(self, '_recalculate_masonry_if_needed'):
                        self._recalculate_masonry_if_needed("layoutChanged")
                else:
                    print(f"  Could not read dimensions from file — skipping DB update.")
            except Exception as e:
                print(f"  Re-enrichment failed: {e}")

        print("[DEV-DIAG] Triggering repair: viewport repaint (thumbnail will reload from source file)...")
        self.viewport().update()
        print("=" * 70 + "\n")


    def _masonry_home_end(self, go_end: bool, source_model):
        """Navigate to first (Home) or last (End) item in paginated masonry.

        Loads the target page synchronously, sets _current_page so the masonry
        window is computed around the target.  The final scroll + select happens
        in _on_masonry_calculation_complete via _pending_home_end_nav.
        """
        total_items = int(getattr(source_model, '_total_count', 0) or 0)
        page_size = int(getattr(source_model, 'PAGE_SIZE', 1000) or 1000)
        if total_items <= 0:
            return

        if go_end:
            target_global_idx = total_items - 1
            target_page = target_global_idx // page_size
        else:
            target_global_idx = 0
            target_page = 0

        # Ensure the target page is loaded
        if hasattr(source_model, '_load_page_sync'):
            if target_page not in getattr(source_model, '_pages', {}):
                source_model._load_page_sync(target_page)
                source_model._emit_pages_updated()

        # Set _current_page BEFORE masonry rebuild so the window is centered
        # on the target page, not the old position.
        self._current_page = target_page

        # Set scroll position BEFORE masonry rebuild so the layout sees the
        # correct scroll_val for source_idx determination.
        sb = self.verticalScrollBar()
        strategy = getattr(self, '_masonry_strategy', '')
        sb.blockSignals(True)
        if strategy == 'windowed_strict':
            canonical_max = self._strict_canonical_domain_max(source_model)
            sb.setMaximum(canonical_max)
            sb.setValue(canonical_max if go_end else 0)
        else:
            sb.setValue(sb.maximum() if go_end else 0)
        sb.blockSignals(False)

        # Store pending nav — masonry calc is async, so the final scroll + select
        # is deferred to _on_masonry_calculation_complete.
        self._pending_home_end_nav = {
            'go_end': go_end,
            'target_global_idx': target_global_idx,
        }

        # Force masonry rebuild — will use _current_page + scroll position
        self._last_masonry_window_signature = None
        self._masonry_index_map = None
        self._last_masonry_signal = "home_end_nav"
        self._calculate_masonry_layout()


    def _finish_home_end_nav(self):
        """Called from _on_masonry_calculation_complete to finalize Home/End scroll."""
        nav = getattr(self, '_pending_home_end_nav', None)
        if nav is None:
            return
        self._pending_home_end_nav = None

        go_end = nav['go_end']
        target_global_idx = nav['target_global_idx']

        source_model = (self.model().sourceModel()
                        if self.model() and hasattr(self.model(), 'sourceModel')
                        else self.model())

        sb = self.verticalScrollBar()
        if go_end and self._masonry_items:
            real_items = [it for it in self._masonry_items if it.get('index', -1) >= 0]
            if real_items:
                last_item = max(real_items, key=lambda it: it['y'] + it['height'])
                bottom_y = last_item['y'] + last_item['height']
                viewport_h = max(1, self.viewport().height())
                target_scroll = max(0, bottom_y - viewport_h)
                sb.blockSignals(True)
                if sb.maximum() < target_scroll:
                    sb.setMaximum(target_scroll)
                sb.setValue(target_scroll)
                sb.blockSignals(False)
        elif not go_end:
            sb.blockSignals(True)
            sb.setValue(0)
            sb.blockSignals(False)

        # Select the target item
        if source_model:
            loaded_row = source_model.get_loaded_row_for_global_index(target_global_idx)
            if loaded_row >= 0:
                src_idx = source_model.index(loaded_row, 0)
                proxy = self.model()
                if hasattr(proxy, 'mapFromSource'):
                    proxy_idx = proxy.mapFromSource(src_idx)
                else:
                    proxy_idx = src_idx
                if proxy_idx.isValid():
                    self.setCurrentIndex(proxy_idx)

        self.viewport().update()

    def show_go_to_page_dialog(self):
        """Prompt user for page number and jump there."""
        if getattr(self, "_jump_dialog_open", False):
            return

        source_model = (
            self.model().sourceModel()
            if self.model() and hasattr(self.model(), "sourceModel")
            else self.model()
        )
        if source_model is None:
            return

        total_items = int(getattr(source_model, "_total_count", 0) or 0)
        if total_items <= 0:
            total_items = int(self.model().rowCount()) if self.model() else 0
        if total_items <= 0:
            return

        page_size = int(getattr(source_model, "PAGE_SIZE", 1000) or 1000)
        total_pages = max(1, (total_items + max(1, page_size) - 1) // max(1, page_size))
        current_page = max(1, min(total_pages, int(getattr(self, "_current_page", 0) or 0) + 1))

        from PySide6.QtWidgets import QInputDialog

        self._jump_dialog_open = True
        try:
            page, ok = QInputDialog.getInt(
                self,
                "Go To Page",
                f"Page (1-{total_pages}):",
                current_page,
                1,
                total_pages,
                1,
            )
        finally:
            self._jump_dialog_open = False

        if ok:
            self.go_to_page(page)

    def show_go_to_image_index_dialog(self):
        """Prompt user for image index and jump there."""
        if getattr(self, "_jump_dialog_open", False):
            return

        source_model = (
            self.model().sourceModel()
            if self.model() and hasattr(self.model(), "sourceModel")
            else self.model()
        )
        if source_model is None:
            return

        total_items = int(getattr(source_model, "_total_count", 0) or 0)
        if total_items <= 0:
            total_items = int(self.model().rowCount()) if self.model() else 0
        if total_items <= 0:
            return

        current_global = self._current_global_from_current_index(source_model)
        if not (isinstance(current_global, int) and current_global >= 0):
            current_global = int(getattr(self, "_selected_global_index", 0) or 0)
        current_value = max(1, min(total_items, int(current_global) + 1))

        from PySide6.QtWidgets import QInputDialog

        self._jump_dialog_open = True
        try:
            index_1_based, ok = QInputDialog.getInt(
                self,
                "Go To Image Index",
                f"Image index (1-{total_items}):",
                current_value,
                1,
                total_items,
                1,
            )
        finally:
            self._jump_dialog_open = False

        if ok:
            self.go_to_global_index(index_1_based - 1)

    def go_to_page(self, page_1_based: int) -> bool:
        """Jump to first image on a 1-based page number."""
        source_model = (
            self.model().sourceModel()
            if self.model() and hasattr(self.model(), "sourceModel")
            else self.model()
        )
        if source_model is None:
            return False

        total_items = int(getattr(source_model, "_total_count", 0) or 0)
        if total_items <= 0:
            total_items = int(self.model().rowCount()) if self.model() else 0
        if total_items <= 0:
            return False

        page_size = int(getattr(source_model, "PAGE_SIZE", 1000) or 1000)
        total_pages = max(1, (total_items + max(1, page_size) - 1) // max(1, page_size))
        target_page = max(0, min(total_pages - 1, int(page_1_based) - 1))
        target_global = max(0, min(total_items - 1, target_page * max(1, page_size)))
        return self.go_to_global_index(target_global)

    def go_to_global_index(self, target_global: int) -> bool:
        """Jump to stable global index and select it."""
        source_model = (
            self.model().sourceModel()
            if self.model() and hasattr(self.model(), "sourceModel")
            else self.model()
        )
        if source_model is None:
            return False

        total_items = int(getattr(source_model, "_total_count", 0) or 0)
        if total_items <= 0:
            total_items = int(self.model().rowCount()) if self.model() else 0
        if total_items <= 0:
            return False

        try:
            target_global = int(target_global)
        except Exception:
            return False
        target_global = max(0, min(total_items - 1, target_global))

        # New explicit jump overrides drag/release edge and lock state.
        self._selected_global_lock_until = 0.0
        self._selected_global_lock_value = None
        self._drag_release_anchor_active = False
        self._drag_release_anchor_idx = None
        self._drag_release_anchor_until = 0.0
        self._release_page_lock_page = None
        self._release_page_lock_until = 0.0
        self._pending_edge_snap = None
        self._pending_edge_snap_until = 0.0
        self._stick_to_edge = None

        page_size = int(getattr(source_model, "PAGE_SIZE", 1000) or 1000)
        target_page = target_global // max(1, page_size)

        # Load target page eagerly when possible.
        try:
            pages = getattr(source_model, "_pages", {})
            if isinstance(pages, dict) and target_page not in pages and hasattr(source_model, "_load_page_sync"):
                source_model._load_page_sync(target_page)
                if hasattr(source_model, "_emit_pages_updated"):
                    source_model._emit_pages_updated()
        except Exception:
            pass

        # Request window around target for buffered pagination.
        try:
            if hasattr(source_model, "ensure_pages_for_range"):
                window = max(1, page_size)
                start_idx = max(0, target_global - window)
                end_idx = min(total_items, target_global + window)
                source_model.ensure_pages_for_range(start_idx, end_idx)
        except Exception:
            pass

        self._current_page = max(0, int(target_page))
        self._restore_target_page = int(target_page)
        self._restore_target_global_index = int(target_global)
        import time as _t
        self._restore_anchor_until = _t.time() + 4.0

        loaded_row = -1
        if hasattr(source_model, "get_loaded_row_for_global_index"):
            loaded_row = source_model.get_loaded_row_for_global_index(target_global)
        else:
            loaded_row = target_global
        if loaded_row < 0:
            self._last_masonry_window_signature = None
            self._calculate_masonry_layout()
            return False

        src_idx = source_model.index(loaded_row, 0)
        proxy_model = self.model()
        proxy_idx = (
            proxy_model.mapFromSource(src_idx)
            if proxy_model and hasattr(proxy_model, "mapFromSource")
            else src_idx
        )
        if not proxy_idx.isValid():
            self._last_masonry_window_signature = None
            self._calculate_masonry_layout()
            return False

        sel_model = self.selectionModel()
        if sel_model is not None:
            sel_model.setCurrentIndex(proxy_idx, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        else:
            self.setCurrentIndex(proxy_idx)
        self._selected_global_index = int(target_global)
        self.scrollTo(proxy_idx, QAbstractItemView.ScrollHint.PositionAtCenter)
        self.viewport().update()
        return True


    def wheelEvent(self, event):
        """Handle Ctrl+scroll for zooming thumbnails."""
        if event.modifiers() == Qt.ControlModifier:
            import time
            # Ctrl+wheel can arrive without keyboard focus; keep arrows working after zoom.
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            source_model = (
                self.model().sourceModel()
                if self.model() and hasattr(self.model(), 'sourceModel')
                else self.model()
            )
            # A prior click may have set _skip_next_resize_recalc.  Clear it so
            # the zoom's own resize timer fires properly with scroll anchoring.
            self._skip_next_resize_recalc = False
            if (
                self.use_masonry
                and hasattr(self, '_activate_resize_anchor')
                and time.time() > float(getattr(self, '_restore_anchor_until', 0.0) or 0.0)
            ):
                self._activate_resize_anchor(source_model=source_model, hold_s=4.0)
            # Get scroll direction
            delta = event.angleDelta().y()

            # Adjust thumbnail size
            zoom_step = 20  # Pixels per scroll step
            if delta > 0:
                # Scroll up = zoom in (larger thumbnails)
                new_size = min(self.current_thumbnail_size + zoom_step, self.max_thumbnail_size)
            else:
                # Scroll down = zoom out (smaller thumbnails)
                new_size = max(self.current_thumbnail_size - zoom_step, self.min_thumbnail_size)

            if new_size != self.current_thumbnail_size:
                self.current_thumbnail_size = new_size
                self.setIconSize(QSize(self.current_thumbnail_size, self.current_thumbnail_size * 3))

                # Update view mode (single column vs multi-column)
                self._update_view_mode()

                # If masonry, recalculate layout and re-center after zoom stops
                if self.use_masonry:
                    # Debounce: recalculate and re-center after user stops zooming
                    self._resize_timer.stop()
                    self._resize_timer.start(420)

                # Save to settings
                settings.setValue('image_list_thumbnail_size', self.current_thumbnail_size)

            event.accept()
            return

        # Non-zoom wheel: if user wheels away from a sticky edge, release it.
        if self.use_masonry:
            delta_dir = event.angleDelta().y()
            if delta_dir > 0 and getattr(self, "_stick_to_edge", None) == "bottom":
                self._stick_to_edge = None
            elif delta_dir < 0 and getattr(self, "_stick_to_edge", None) == "top":
                self._stick_to_edge = None

        # Mark as mouse scrolling and restart timer (for pagination preloading)
        if not self._mouse_scrolling:
            self._mouse_scrolling = True
            # print("[SCROLL] Mouse scroll started - pausing background preloading")

        # Reset timer - will fire 150ms after last scroll event
        self._mouse_scroll_timer.stop()
        self._mouse_scroll_timer.start(150)  # Shorter delay for faster resume

        # Normal scroll behavior - but boost scroll speed in IconMode
        if self.viewMode() == QListView.ViewMode.IconMode:
            # In icon mode, manually scroll by a reasonable pixel amount
            delta = event.angleDelta().y()
            scroll_amount = delta * 2  # Multiply by 2 for faster scrolling
            current_value = self.verticalScrollBar().value()
            self.verticalScrollBar().setValue(current_value - scroll_amount)
            event.accept()
        else:
            # Default scroll behavior in ListMode
            super().wheelEvent(event)
