from widgets.image_list_shared import *  # noqa: F401,F403
from utils.diagnostic_logging import diagnostic_print, diagnostic_time_prefix
from utils.settings import DEFAULT_SETTINGS, settings

class ImageListViewInteractionMixin:
    def _mark_selection_log_source(self, source: str, *, hold_s: float = 2.0):
        """Tag upcoming selection persistence with a short-lived origin label."""
        import time as _t

        try:
            source_text = str(source or "").strip()
        except Exception:
            source_text = ""
        if not source_text:
            source_text = "program"
        self._selection_log_source = source_text
        self._selection_log_source_until = _t.time() + max(0.25, float(hold_s or 0.0))

    def _arm_pending_targeted_relocation(
        self,
        target_global: int,
        *,
        reason: str = "sort_restore",
        source_model=None,
        hold_s: float = 30.0,
    ) -> bool:
        """Preserve a targeted relocation goal across a model reset."""
        import time as _t

        if source_model is None:
            source_model = (
                self.model().sourceModel()
                if self.model() and hasattr(self.model(), "sourceModel")
                else self.model()
            )
        if source_model is None:
            return False

        try:
            target_global = int(target_global)
        except Exception:
            return False
        if target_global < 0:
            return False

        try:
            page_size = int(getattr(source_model, "PAGE_SIZE", 1000) or 1000)
        except Exception:
            page_size = 1000
        target_page = max(0, int(target_global) // max(1, page_size))
        hold_until = _t.time() + max(2.0, float(hold_s or 0.0))

        self._pending_targeted_relocation_target_global = int(target_global)
        self._pending_targeted_relocation_target_page = int(target_page)
        self._pending_targeted_relocation_reason = str(reason or "sort_restore")
        self._pending_targeted_relocation_until = hold_until
        self._selected_global_index = int(target_global)
        self._current_page = int(target_page)
        self._restore_target_page = int(target_page)
        self._restore_target_global_index = int(target_global)
        self._restore_anchor_until = max(
            float(getattr(self, "_restore_anchor_until", 0.0) or 0.0),
            hold_until,
        )
        self._selected_global_lock_value = int(target_global)
        self._selected_global_lock_until = max(
            float(getattr(self, "_selected_global_lock_until", 0.0) or 0.0),
            hold_until,
        )

        mw = self.window()
        if (
            mw is not None
            and hasattr(mw, "_restore_in_progress")
            and hasattr(mw, "_restore_target_global_rank")
        ):
            mw._restore_in_progress = True
            mw._restore_target_global_rank = int(target_global)

        self._mark_selection_log_source(str(reason or "sort_restore"), hold_s=max(2.0, float(hold_s or 0.0)))
        return True

    def _clear_pending_targeted_relocation(self):
        self._pending_targeted_relocation_target_global = None
        self._pending_targeted_relocation_target_page = None
        self._pending_targeted_relocation_reason = None
        self._pending_targeted_relocation_until = 0.0

    def _get_image_list_double_click_action(self) -> str:
        """Return normalized configured double-click action."""
        try:
            action = str(
                settings.value(
                    'image_list_double_click_action',
                    defaultValue=DEFAULT_SETTINGS.get('image_list_double_click_action', 'spawn viewer'),
                    type=str,
                )
                or ''
            ).strip().lower()
        except Exception:
            action = ''
        if action == 'system default app':
            return 'system_default_app'
        return 'spawn_viewer'

    def _spawn_viewer_for_double_click(self, index: QModelIndex, event) -> bool:
        """Open the clicked item in a spawned floating viewer."""
        if not index.isValid():
            return False
        host = self.window()
        spawn = getattr(host, 'spawn_floating_viewer_at', None)
        if not callable(spawn):
            return False
        try:
            spawn(
                index,
                spawn_global_pos=self._event_global_point(event),
                clamp_to_screen=True,
            )
            return True
        except Exception:
            return False

    def _open_double_click_in_system_app(self, image) -> bool:
        """Open the clicked item with the OS default application."""
        open_in_system_app = getattr(self, "_open_in_system_default_app", None)
        if callable(open_in_system_app):
            try:
                return bool(open_in_system_app(image.path))
            except Exception:
                pass
        try:
            return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(str(image.path))))
        except Exception:
            return False

    def _drag_to_external_only_mode(self) -> bool:
        """Alt+drag exports files to other apps instead of spawning a viewer."""
        try:
            return bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.AltModifier)
        except Exception:
            return False

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
        self._spawn_drag_external_only = False

    def _clear_explicit_jump_tracking(self):
        self._pending_explicit_jump_kind = None
        self._last_explicit_jump_kind = None
        self._last_explicit_jump_target_global = None
        self._last_explicit_jump_until = 0.0
        cancel_one_shot = getattr(self, "_cancel_one_shot_targeted_jump", None)
        if callable(cancel_one_shot):
            cancel_one_shot()
        self._cancel_exact_jump_settle()
        clear_stabilization = getattr(self, "_clear_post_jump_stabilization", None)
        if callable(clear_stabilization):
            clear_stabilization()
        clear_reflow_guide = getattr(self, "_clear_pending_target_reflow_guide", None)
        if callable(clear_reflow_guide):
            clear_reflow_guide()

    def _cancel_exact_jump_settle(self):
        target_global = getattr(self, "_exact_jump_settle_target_global", None)
        self._exact_jump_settle_target_global = None
        self._exact_jump_settle_until = 0.0
        self._exact_jump_settle_stable_hits = 0
        self._exact_jump_settle_token = int(getattr(self, "_exact_jump_settle_token", 0) or 0) + 1
        restore_target = getattr(self, "_restore_target_global_index", None)
        if target_global is None or restore_target == target_global:
            self._restore_target_global_index = None
            self._restore_target_page = None
            self._restore_anchor_until = 0.0
        if bool(getattr(self, "_exact_jump_settle_connected", False)):
            try:
                self.layout_ready.disconnect(self._on_exact_jump_layout_ready)
            except Exception:
                pass
            self._exact_jump_settle_connected = False
        mw = self.window()
        if (
            mw is not None
            and hasattr(mw, "_restore_in_progress")
            and hasattr(mw, "_restore_target_global_rank")
        ):
            try:
                active_target = int(getattr(mw, "_restore_target_global_rank", -1) or -1)
            except Exception:
                active_target = -1
            if target_global is None or active_target == int(target_global):
                mw._restore_in_progress = False
                mw._restore_target_global_rank = -1

    def _on_exact_jump_layout_ready(self):
        token = int(getattr(self, "_exact_jump_settle_token", 0) or 0)
        QTimer.singleShot(0, lambda token=token: self._run_exact_jump_settle(token))

    def _cancel_one_shot_targeted_jump(self):
        self._one_shot_jump_target_global = None
        self._one_shot_jump_reason = None
        self._one_shot_jump_token = int(getattr(self, "_one_shot_jump_token", 0) or 0) + 1
        self._one_shot_jump_attempts = 0
        self._strict_waiting_target_page = None
        self._strict_waiting_window_pages = None

    def _run_one_shot_targeted_jump_finalize(self, token: int | None = None):
        import time as _t

        active_token = int(getattr(self, "_one_shot_jump_token", 0) or 0)
        if token is not None and int(token) != active_token:
            return

        target_global = getattr(self, "_one_shot_jump_target_global", None)
        reason = str(getattr(self, "_one_shot_jump_reason", "") or "")
        if not (isinstance(target_global, int) and target_global >= 0):
            self._cancel_one_shot_targeted_jump()
            return

        source_model = (
            self.model().sourceModel()
            if self.model() and hasattr(self.model(), "sourceModel")
            else self.model()
        )
        if source_model is None:
            self._cancel_one_shot_targeted_jump()
            return

        target_item = self._get_masonry_item_for_global_index(int(target_global))
        if target_item is None:
            attempts = int(getattr(self, "_one_shot_jump_attempts", 0) or 0) + 1
            self._one_shot_jump_attempts = attempts
            try:
                if hasattr(source_model, "_request_page_load"):
                    page_size = int(getattr(source_model, "PAGE_SIZE", 1000) or 1000)
                    source_model._request_page_load(max(0, int(target_global) // max(1, page_size)))
            except Exception:
                pass
            if attempts <= 300:
                QTimer.singleShot(100, lambda token=active_token: self._run_one_shot_targeted_jump_finalize(token))
            else:
                self._cancel_one_shot_targeted_jump()
            return

        try:
            sb = self.verticalScrollBar()
            viewport_h = max(1, int(self.viewport().height()))
            item_top = int(target_item.get("y", 0))
            item_center_y = item_top + int(target_item.get("height", 0)) // 2
            if reason == "page_input":
                page_size = int(getattr(source_model, "PAGE_SIZE", 1000) or 1000)
                target_page = max(0, int(target_global) // max(1, page_size))
                page_start = int(target_page) * max(1, page_size)
                page_end = page_start + max(1, page_size)
                page_top = item_top
                try:
                    for it in (self._masonry_items or []):
                        idx = int(it.get("index", -1))
                        if page_start <= idx < page_end:
                            page_top = min(page_top, int(it.get("y", 0)))
                except Exception:
                    page_top = item_top
                top_margin = max(12, min(48, viewport_h // 12))
                target_scroll = max(0, min(page_top - top_margin, int(sb.maximum())))
            else:
                target_scroll = max(
                    0,
                    min(
                        item_center_y - (viewport_h // 2),
                        int(sb.maximum()),
                    ),
                )
            prev_block = sb.blockSignals(True)
            try:
                sb.setValue(target_scroll)
            finally:
                sb.blockSignals(prev_block)
            self._last_stable_scroll_value = int(target_scroll)
        except Exception:
            pass

        try_show_reflow_guide = getattr(self, "_try_show_pending_target_reflow_guide", None)
        if callable(try_show_reflow_guide):
            try:
                try_show_reflow_guide(int(target_global))
            except Exception:
                pass

        if reason in {"startup_restore", "page_drag", "index_input"}:
            try:
                loaded_row = -1
                if hasattr(source_model, "get_loaded_row_for_global_index"):
                    loaded_row = int(source_model.get_loaded_row_for_global_index(int(target_global)))
                if loaded_row >= 0:
                    src_idx = source_model.index(loaded_row, 0)
                    proxy_model = self.model()
                    proxy_idx = (
                        proxy_model.mapFromSource(src_idx)
                        if proxy_model and hasattr(proxy_model, "mapFromSource")
                        else src_idx
                    )
                    if proxy_idx.isValid():
                        sel_model = self.selectionModel()
                        if sel_model is not None:
                            sel_model.setCurrentIndex(
                                proxy_idx,
                                QItemSelectionModel.SelectionFlag.ClearAndSelect,
                            )
                        else:
                            self.setCurrentIndex(proxy_idx)
                        host = self.window()
                        if host is not None and hasattr(host, "commit_thumbnail_click_selection"):
                            host.commit_thumbnail_click_selection(proxy_idx)
            except Exception:
                pass

        page_size = int(getattr(source_model, "PAGE_SIZE", 1000) or 1000)
        target_page = max(0, int(target_global) // max(1, page_size))
        arm_stabilization = getattr(self, "_arm_post_jump_stabilization", None)
        if callable(arm_stabilization):
            try:
                arm_stabilization(
                    int(target_global),
                    target_page=int(target_page),
                    reason=reason or "sort_restore",
                    hold_s=180.0,
                )
            except Exception:
                pass

        self._restore_anchor_until = 0.0
        self._restore_target_page = None
        self._restore_target_global_index = None
        mw = self.window()
        if (
            mw is not None
            and hasattr(mw, "_restore_in_progress")
            and hasattr(mw, "_restore_target_global_rank")
        ):
            mw._restore_in_progress = False
            mw._restore_target_global_rank = -1

        if hasattr(source_model, "prepare_target_window"):
            try:
                prefer_forward = reason in {"sort_restore", "startup_restore"}
                source_model.prepare_target_window(
                    int(target_global),
                    sync_target_page=False,
                    include_buffer=True,
                    prefer_forward=prefer_forward,
                    emit_update=False,
                    request_async_window=True,
                    restart_enrichment=True,
                    prune_to_window=False,
                )
            except Exception:
                pass

        self.viewport().update()
        self._cancel_one_shot_targeted_jump()

    def _start_one_shot_targeted_jump(
        self,
        target_global: int,
        *,
        reason: str,
        source_model,
    ) -> bool:
        import time as _t

        try:
            target_global = int(target_global)
        except Exception:
            return False
        if target_global < 0 or source_model is None:
            return False

        self._cancel_one_shot_targeted_jump()
        self._cancel_exact_jump_settle()
        clear_stabilization = getattr(self, "_clear_post_jump_stabilization", None)
        if callable(clear_stabilization):
            clear_stabilization()
        self._strict_waiting_target_page = None
        self._strict_waiting_window_pages = None
        self._release_page_lock_page = None
        self._release_page_lock_until = 0.0
        if hasattr(source_model, "_enrichment_cancelled"):
            try:
                source_model._enrichment_cancelled.set()
            except Exception:
                pass

        page_size = int(getattr(source_model, "PAGE_SIZE", 1000) or 1000)
        target_page = max(0, int(target_global) // max(1, page_size))
        prefer_forward = str(reason or "") in {"sort_restore", "startup_restore"}
        publish_target_page_now = str(reason or "") in {"index_input", "page_drag"}
        total_items = int(getattr(source_model, "_total_count", 0) or 0)
        loaded_pages = sorted(getattr(source_model, "_pages", {}).keys()) if hasattr(source_model, "_pages") else []
        nearest_loaded_gap = 0
        if loaded_pages:
            nearest_loaded_gap = min(abs(int(page) - int(target_page)) for page in loaded_pages)
        target_page_loaded = int(target_page) in set(loaded_pages)
        deep_unloaded_jump = bool(
            (not target_page_loaded)
            and loaded_pages
            and nearest_loaded_gap > 2
        )
        sync_target_page = not deep_unloaded_jump
        self._mark_selection_log_source(str(reason), hold_s=20.0)
        self._selected_global_index = int(target_global)
        self._selected_global_lock_value = int(target_global)
        hold_s = 90.0 if deep_unloaded_jump else 20.0
        self._selected_global_lock_until = _t.time() + hold_s
        self._current_page = int(target_page)
        self._strict_jump_target_global = int(target_global)
        self._strict_jump_until = _t.time() + hold_s
        self._last_explicit_jump_kind = str(reason)
        self._last_explicit_jump_target_global = int(target_global)
        self._last_explicit_jump_until = _t.time() + hold_s
        self._release_page_lock_page = int(target_page)
        self._release_page_lock_until = _t.time() + hold_s
        self._restore_target_page = int(target_page)
        self._restore_target_global_index = int(target_global)
        self._restore_anchor_until = _t.time() + hold_s

        prepared_state = None
        if hasattr(source_model, "prepare_target_window"):
            try:
                prepared_state = source_model.prepare_target_window(
                    int(target_global),
                    sync_target_page=sync_target_page,
                    include_buffer=not deep_unloaded_jump,
                    prefer_forward=prefer_forward,
                    emit_update=(publish_target_page_now and sync_target_page),
                    request_async_window=True,
                    restart_enrichment=not deep_unloaded_jump,
                    prune_to_window=deep_unloaded_jump,
                )
            except Exception:
                prepared_state = None

        loaded_row = -1
        if isinstance(prepared_state, dict):
            try:
                loaded_row = int(prepared_state.get("loaded_row", -1))
            except Exception:
                loaded_row = -1
        if loaded_row < 0 and hasattr(source_model, "get_loaded_row_for_global_index"):
            try:
                loaded_row = int(source_model.get_loaded_row_for_global_index(int(target_global)))
            except Exception:
                loaded_row = -1
        if loaded_row < 0 and not deep_unloaded_jump:
            return False

        try:
            src_idx = source_model.index(loaded_row, 0)
            proxy_model = self.model()
            proxy_idx = (
                proxy_model.mapFromSource(src_idx)
                if proxy_model and hasattr(proxy_model, "mapFromSource")
                else src_idx
            )
        except Exception:
            proxy_idx = QModelIndex()

        if proxy_idx.isValid():
            sel_model = self.selectionModel()
            if sel_model is not None:
                sel_model.setCurrentIndex(proxy_idx, QItemSelectionModel.SelectionFlag.ClearAndSelect)
            else:
                self.setCurrentIndex(proxy_idx)

        mw = self.window()
        if (
            mw is not None
            and hasattr(mw, "_restore_in_progress")
            and hasattr(mw, "_restore_target_global_rank")
        ):
            mw._restore_in_progress = True
            mw._restore_target_global_rank = int(target_global)

        queue_reflow_guide = getattr(self, "_queue_target_reflow_guide", None)
        if self.use_masonry and callable(queue_reflow_guide):
            try:
                queue_reflow_guide(int(target_global), source_model=source_model, duration_ms=2200)
            except Exception:
                pass

        try:
            jump_domain = int(self._get_strict_scroll_domain_max(source_model, include_drag_baseline=True))
        except Exception:
            jump_domain = int(self._strict_canonical_domain_max(source_model))
        try:
            sb = self.verticalScrollBar()
            target_scroll = self._get_strict_canonical_scroll_for_global(
                int(target_global),
                source_model=source_model,
                domain_max=int(jump_domain),
            )
            if target_scroll is None:
                target_scroll = 0
            prev_block = sb.blockSignals(True)
            try:
                sb.setRange(0, int(jump_domain))
                sb.setValue(max(0, min(int(target_scroll), int(jump_domain))))
            finally:
                sb.blockSignals(prev_block)
            self._last_stable_scroll_value = int(sb.value())
        except Exception:
            pass

        self._one_shot_jump_target_global = int(target_global)
        self._one_shot_jump_reason = str(reason)
        token = int(getattr(self, "_one_shot_jump_token", 0) or 0) + 1
        self._one_shot_jump_token = token
        self._one_shot_jump_attempts = 0
        self._last_masonry_window_signature = None
        self._calculate_masonry_layout()
        QTimer.singleShot(80, lambda token=token: self._run_one_shot_targeted_jump_finalize(token))
        return True

    def _start_exact_jump_settle(self, target_global: int):
        import time as _t

        self._cancel_exact_jump_settle()
        try:
            target_global = int(target_global)
        except Exception:
            return
        if target_global < 0:
            return

        token = int(getattr(self, "_exact_jump_settle_token", 0) or 0) + 1
        self._exact_jump_settle_token = token
        self._exact_jump_settle_target_global = target_global
        self._exact_jump_settle_until = _t.time() + 30.0
        self._exact_jump_settle_stable_hits = 0
        if not bool(getattr(self, "_exact_jump_settle_connected", False)):
            try:
                self.layout_ready.connect(self._on_exact_jump_layout_ready)
                self._exact_jump_settle_connected = True
            except Exception:
                self._exact_jump_settle_connected = False

        mw = self.window()
        if (
            mw is not None
            and hasattr(mw, "_restore_in_progress")
            and hasattr(mw, "_restore_target_global_rank")
        ):
            mw._restore_in_progress = True
            mw._restore_target_global_rank = target_global

        QTimer.singleShot(0, lambda token=token: self._run_exact_jump_settle(token))

    def _extend_exact_target_hold(self, target_global: int, *, seconds: float = 8.0):
        import time as _t

        try:
            target_global = int(target_global)
        except Exception:
            return
        if target_global < 0:
            return

        now = _t.time()
        hold_until = now + max(0.5, float(seconds or 0.0))
        source_model = (
            self.model().sourceModel()
            if self.model() and hasattr(self.model(), "sourceModel")
            else self.model()
        )
        try:
            page_size = int(getattr(source_model, "PAGE_SIZE", 1000) or 1000)
        except Exception:
            page_size = 1000

        self._selected_global_index = int(target_global)
        self._current_page = max(0, int(target_global) // max(1, page_size))
        self._selected_global_lock_value = int(target_global)
        self._selected_global_lock_until = max(
            float(getattr(self, "_selected_global_lock_until", 0.0) or 0.0),
            hold_until,
        )
        preserve_restore_contract = False
        current_restore_target = getattr(self, "_restore_target_global_index", None)
        current_restore_until = float(getattr(self, "_restore_anchor_until", 0.0) or 0.0)
        if (
            isinstance(current_restore_target, int)
            and int(current_restore_target) == int(target_global)
            and current_restore_until > now
        ):
            preserve_restore_contract = True
        try:
            jump_kind = getattr(self, "_last_explicit_jump_kind", None)
            jump_target = getattr(self, "_last_explicit_jump_target_global", None)
            if (
                jump_kind == "index_input"
                and isinstance(jump_target, int)
                and int(jump_target) == int(target_global)
            ):
                preserve_restore_contract = True
                self._last_explicit_jump_until = max(
                    float(getattr(self, "_last_explicit_jump_until", 0.0) or 0.0),
                    hold_until,
                )
        except Exception:
            pass
        if (
            isinstance(getattr(self, "_exact_jump_settle_target_global", None), int)
            and int(getattr(self, "_exact_jump_settle_target_global", None)) == int(target_global)
        ):
            preserve_restore_contract = True
            self._exact_jump_settle_until = max(
                float(getattr(self, "_exact_jump_settle_until", 0.0) or 0.0),
                hold_until,
            )
        mw = self.window()
        if (
            mw is not None
            and hasattr(mw, "_restore_in_progress")
            and hasattr(mw, "_restore_target_global_rank")
        ):
            try:
                if (
                    getattr(mw, "_restore_in_progress", False)
                    and int(getattr(mw, "_restore_target_global_rank", -1) or -1) == int(target_global)
                ):
                    preserve_restore_contract = True
            except Exception:
                pass

        if preserve_restore_contract:
            self._restore_target_global_index = int(target_global)
            self._restore_target_page = max(0, int(target_global) // max(1, page_size))
            self._restore_anchor_until = max(
                float(getattr(self, "_restore_anchor_until", 0.0) or 0.0),
                hold_until,
            )
            if (
                mw is not None
                and hasattr(mw, "_restore_in_progress")
                and hasattr(mw, "_restore_target_global_rank")
            ):
                mw._restore_in_progress = True
                mw._restore_target_global_rank = int(target_global)

    def _run_exact_jump_settle(self, token: int | None = None):
        import time as _t

        active_token = int(getattr(self, "_exact_jump_settle_token", 0) or 0)
        if token is not None and int(token) != active_token:
            return

        now = _t.time()
        until = float(getattr(self, "_exact_jump_settle_until", 0.0) or 0.0)
        target_global = getattr(self, "_exact_jump_settle_target_global", None)
        if not (isinstance(target_global, int) and target_global >= 0) or now > until:
            self._cancel_exact_jump_settle()
            return

        proxy_model = self.model()
        source_model = (
            proxy_model.sourceModel()
            if proxy_model and hasattr(proxy_model, "sourceModel")
            else proxy_model
        )
        if source_model is None:
            return

        try:
            page_size = int(getattr(source_model, "PAGE_SIZE", 1000) or 1000)
        except Exception:
            page_size = 1000
        target_page = max(0, int(target_global) // max(1, page_size))

        self._selected_global_index = int(target_global)
        self._current_page = int(target_page)
        self._restore_target_global_index = int(target_global)
        self._restore_target_page = int(target_page)
        self._restore_anchor_until = max(
            float(getattr(self, "_restore_anchor_until", 0.0) or 0.0),
            now + 30.0,
        )

        mw = self.window()
        if (
            mw is not None
            and hasattr(mw, "_restore_in_progress")
            and hasattr(mw, "_restore_target_global_rank")
        ):
            mw._restore_in_progress = True
            mw._restore_target_global_rank = int(target_global)

        try:
            if hasattr(source_model, "ensure_pages_for_range"):
                window = max(1, page_size)
                start_idx = max(0, int(target_global) - window)
                end_idx = max(start_idx + 1, int(target_global) + window)
                source_model.ensure_pages_for_range(start_idx, end_idx)
        except Exception:
            pass

        loaded_row = -1
        try:
            if hasattr(source_model, "get_loaded_row_for_global_index"):
                loaded_row = int(source_model.get_loaded_row_for_global_index(int(target_global)))
            else:
                loaded_row = int(target_global)
        except Exception:
            loaded_row = -1

        proxy_idx = QModelIndex()
        if loaded_row >= 0:
            try:
                src_idx = source_model.index(loaded_row, 0)
                proxy_idx = (
                    proxy_model.mapFromSource(src_idx)
                    if proxy_model and hasattr(proxy_model, "mapFromSource")
                    else src_idx
                )
            except Exception:
                proxy_idx = QModelIndex()

        if proxy_idx.isValid():
            try:
                sel_model = self.selectionModel()
                if sel_model is not None and sel_model.currentIndex() != proxy_idx:
                    sel_model.setCurrentIndex(
                        proxy_idx,
                        QItemSelectionModel.SelectionFlag.ClearAndSelect,
                    )
                elif sel_model is None and self.currentIndex() != proxy_idx:
                    self.setCurrentIndex(proxy_idx)
            except Exception:
                pass

        target_item = None
        try:
            for item in (self._masonry_items or []):
                if int(item.get("index", -1)) == int(target_global):
                    target_item = item
                    break
        except Exception:
            target_item = None

        if target_item is not None:
            try:
                sb = self.verticalScrollBar()
                viewport_h = int(self.viewport().height())
                item_center_y = int(target_item.get("y", 0)) + int(target_item.get("height", 0)) // 2
                target_y = max(0, min(item_center_y - viewport_h // 2, int(sb.maximum())))
                prev_block = sb.blockSignals(True)
                try:
                    if sb.value() != target_y:
                        sb.setValue(target_y)
                finally:
                    sb.blockSignals(prev_block)
                self._last_stable_scroll_value = int(target_y)
            except Exception:
                pass

        current_global = self._current_global_from_current_index(source_model)
        target_page_loading = False
        try:
            loading_pages = getattr(source_model, "_loading_pages", set())
            if isinstance(loading_pages, set):
                target_page_loading = int(target_page) in loading_pages
            else:
                target_page_loading = int(target_page) in set(loading_pages or ())
        except Exception:
            target_page_loading = False
        target_visible = False
        if target_item is not None:
            try:
                sb_value = int(self.verticalScrollBar().value())
                viewport_h = int(self.viewport().height())
                item_top = int(target_item.get("y", 0))
                item_bottom = item_top + int(target_item.get("height", 0))
                target_visible = item_bottom >= sb_value and item_top <= (sb_value + viewport_h)
            except Exception:
                target_visible = False

        stable_now = (
            isinstance(current_global, int)
            and int(current_global) == int(target_global)
            and target_item is not None
            and target_visible
            and not target_page_loading
        )
        if stable_now:
            try_show_reflow_guide = getattr(self, "_try_show_pending_target_reflow_guide", None)
            if callable(try_show_reflow_guide):
                try:
                    try_show_reflow_guide(int(target_global))
                except Exception:
                    pass
        stable_hits = (
            int(getattr(self, "_exact_jump_settle_stable_hits", 0) or 0) + 1
            if stable_now else 0
        )
        self._exact_jump_settle_stable_hits = stable_hits
        jump_kind = str(getattr(self, "_last_explicit_jump_kind", "") or "")
        stable_hits_needed = 1 if jump_kind in {"sort_restore", "startup_restore"} else 2
        if stable_now and stable_hits >= stable_hits_needed:
            if jump_kind in {"sort_restore", "startup_restore"}:
                arm_stabilization = getattr(self, "_arm_post_jump_stabilization", None)
                if callable(arm_stabilization):
                    try:
                        arm_stabilization(
                            int(target_global),
                            target_page=int(target_page),
                            reason=jump_kind,
                            hold_s=180.0,
                        )
                    except Exception:
                        pass
            self._cancel_exact_jump_settle()
            return
        delay_ms = 350 if stable_now else 150
        QTimer.singleShot(delay_ms, lambda token=active_token: self._run_exact_jump_settle(token))

    def _begin_spawn_drag_active(self, index: QPersistentModelIndex, global_pos: QPoint | None = None):
        """Arm internal spawn-drag mode until left button release."""
        self._spawn_drag_active = True
        self._spawn_drag_external_only = bool(self._drag_to_external_only_mode())
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
        host = self.window()
        active_index = QPersistentModelIndex(getattr(self, "_spawn_drag_active_index", QPersistentModelIndex()))
        self._spawn_drag_active = False
        self._suppress_selection_commit_until_release = False
        self._spawn_drag_active_index = QPersistentModelIndex()
        compare_handled = False
        external_only = bool(getattr(self, "_spawn_drag_external_only", False))
        self._spawn_drag_external_only = False
        if should_spawn and (not external_only) and host is not None and hasattr(host, "release_compare_drag"):
            try:
                compare_handled = bool(host.release_compare_drag(self._spawn_drag_last_global_pos))
            except Exception:
                compare_handled = False
        if compare_handled:
            if callable(hide_ghost):
                hide_ghost()
            return
        spawn_started = False
        if should_spawn and (not external_only) and active_index.isValid():
            try:
                live_index = self.model().index(active_index.row(), active_index.column())
            except Exception:
                live_index = QModelIndex()
            if live_index.isValid():
                spawn_direct = getattr(self, "_spawn_floating_for_index_at_cursor", None)
                if callable(spawn_direct):
                    try:
                        spawn_started = bool(
                            spawn_direct(live_index, spawn_global_pos=self._spawn_drag_last_global_pos)
                        )
                    except Exception:
                        spawn_started = False
        if not spawn_started and callable(hide_ghost):
            hide_ghost()
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
            self._resize_anchor_target_global = None
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

    def _resolve_pressed_index(self, click_pos: QPoint, source_model=None) -> QModelIndex:
        """Resolve the model index under the cursor without mutating selection."""
        model = self.model()
        if model is None:
            return QModelIndex()

        index = QModelIndex()
        if self.use_masonry and self._masonry_items:
            try:
                import time as _t
                clicked_global = -1

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
                    if hasattr(source_model, 'get_loaded_row_for_global_index'):
                        src_row = source_model.get_loaded_row_for_global_index(clicked_global)
                    else:
                        src_row = clicked_global
                    if isinstance(src_row, int) and src_row >= 0:
                        src_idx = source_model.index(src_row, 0)
                        if hasattr(model, 'mapFromSource'):
                            index = model.mapFromSource(src_idx)
                        else:
                            index = src_idx
            except Exception:
                index = QModelIndex()

        if not index.isValid():
            index = self.indexAt(click_pos)

        if not index.isValid():
            return QModelIndex()

        row = int(index.row())
        if row < 0 or row >= int(model.rowCount()):
            return QModelIndex()

        fresh_index = model.index(row, 0)
        return fresh_index if fresh_index.isValid() else QModelIndex()

    def _should_preserve_selection_on_context_click(self, event, source_model=None) -> bool:
        """Keep the current selection when right-clicking within it or on empty space."""
        if event.button() != Qt.MouseButton.RightButton:
            return False

        selection_model = self.selectionModel()
        if selection_model is None:
            return False

        clicked_index = self._resolve_pressed_index(event.pos(), source_model)
        if clicked_index.isValid():
            return bool(selection_model.isSelected(clicked_index))

        return bool(self.selectedIndexes())

    def mousePressEvent(self, event):
        """Override mouse press to fix selection in masonry mode."""
        source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else None

        if event.button() == Qt.MouseButton.LeftButton:
            start_index = self.indexAt(event.pos())
            if start_index.isValid():
                self._spawn_drag_start_pos = event.pos()
                self._spawn_drag_index = QPersistentModelIndex(start_index)
                self._spawn_drag_origin_global_pos = self._event_global_point(event)
                self._suppress_selection_commit_until_release = True
                self._pending_click_commit_index = QPersistentModelIndex()
                self._pending_click_commit_global = None
            else:
                self._spawn_drag_start_pos = None
                self._spawn_drag_index = QPersistentModelIndex()
                self._spawn_drag_origin_global_pos = QPoint()
                self._suppress_selection_commit_until_release = False
                self._pending_click_commit_index = QPersistentModelIndex()
                self._pending_click_commit_global = None
        else:
            self._spawn_drag_start_pos = None
            self._spawn_drag_index = QPersistentModelIndex()
            self._spawn_drag_origin_global_pos = QPoint()
            self._suppress_selection_commit_until_release = False
            self._pending_click_commit_index = QPersistentModelIndex()
            self._pending_click_commit_global = None
    
        # Pause enrichment during interaction to prevent crashes
        if source_model and hasattr(source_model, '_enrichment_timer') and source_model._enrichment_timer:
            source_model._enrichment_timer.stop()
            # Will resume after 500ms idle (see mouseReleaseEvent)

        if self._should_preserve_selection_on_context_click(event, source_model):
            event.accept()
            return

        virtual_list_active = bool(
            hasattr(self, '_virtual_list_is_active') and self._virtual_list_is_active(source_model)
        )
        if virtual_list_active:
            if event.button() == Qt.MouseButton.LeftButton:
                index = self.indexAt(event.pos())
                if index.isValid():
                    model = self.model()
                    if model is None:
                        event.accept()
                        return
                    row = int(index.row())
                    if 0 <= row < int(model.rowCount()):
                        index = model.index(row, 0)
                    else:
                        event.accept()
                        return
                    if not index.isValid():
                        event.accept()
                        return

                    self._mark_selection_log_source("user_click", hold_s=2.5)
                    self._pending_click_commit_index = QPersistentModelIndex(index)
                    self._pending_click_commit_global = int(clicked_global) if clicked_global >= 0 else None
                    self._user_click_selection_frozen_until = 0.0
                    clicked_global = -1
                    try:
                        row_height = max(1, int(self._virtual_list_row_height()))
                        scroll_offset = int(self.verticalScrollBar().value())
                        total_items = int(getattr(source_model, "_total_count", 0) or 0)
                        guessed = (int(event.pos().y()) + scroll_offset) // row_height
                        if 0 <= guessed < total_items:
                            clicked_global = int(guessed)
                    except Exception:
                        clicked_global = -1
                    if clicked_global < 0:
                        try:
                            clicked_global = int(self._proxy_index_to_global_index(index))
                        except Exception:
                            clicked_global = -1

                    modifiers = event.modifiers()
                    active_exact_target = None
                    try:
                        active_exact_target = self._get_active_exact_target_global(source_model=source_model)
                    except Exception:
                        active_exact_target = None
                preserve_exact_target_hold = bool(
                    not (modifiers & (Qt.ControlModifier | Qt.ShiftModifier))
                    and isinstance(active_exact_target, int)
                    and active_exact_target >= 0
                    and int(clicked_global) == int(active_exact_target)
                )
                stabilize_state = None
                consume_stabilization = getattr(self, "_consume_post_jump_stabilization", None)
                if callable(consume_stabilization):
                    try:
                        stabilize_state = consume_stabilization(source_model=source_model)
                    except Exception:
                        stabilize_state = None
                if not preserve_exact_target_hold:
                    self._selected_global_lock_until = 0.0
                    self._selected_global_lock_value = None
                    self._clear_explicit_jump_tracking()
                    if (
                        not (modifiers & (Qt.ControlModifier | Qt.ShiftModifier))
                        and isinstance(clicked_global, int)
                        and clicked_global >= 0
                        and isinstance(stabilize_state, dict)
                    ):
                        arm_stabilization = getattr(self, "_arm_post_jump_stabilization", None)
                        if callable(arm_stabilization):
                            try:
                                page_size = int(getattr(source_model, "PAGE_SIZE", 1000) or 1000)
                            except Exception:
                                page_size = 1000
                            try:
                                arm_stabilization(
                                    int(clicked_global),
                                    target_page=max(0, int(clicked_global) // max(1, page_size)),
                                    reason=str(stabilize_state.get("reason", "browse_click") or "browse_click"),
                                    hold_s=90.0,
                                )
                            except Exception:
                                pass
                self._strict_jump_target_global = None
                self._strict_jump_until = 0.0

                sel_model = self.selectionModel()
                if sel_model is not None:
                    # Prevent Qt's native auto-scroll-to-current in virtual-list mode.
                    self._suppress_virtual_auto_scroll_once = True
                    self._suppress_masonry_auto_scroll_once = True
                    if modifiers & Qt.ControlModifier:
                        was_selected = sel_model.isSelected(index)
                        sel_model.setCurrentIndex(index, QItemSelectionModel.NoUpdate)
                        sel_model.select(
                            index,
                            QItemSelectionModel.Deselect if was_selected else QItemSelectionModel.Select,
                        )
                    elif modifiers & Qt.ShiftModifier:
                        current = self.currentIndex()
                        if current.isValid():
                            start_row = min(current.row(), index.row())
                            end_row = max(current.row(), index.row())
                            selection = QItemSelection()
                            for item_row in range(start_row, end_row + 1):
                                item_index = model.index(item_row, 0)
                                selection.select(item_index, item_index)
                            sel_model.select(selection, QItemSelectionModel.Select)
                            sel_model.setCurrentIndex(index, QItemSelectionModel.NoUpdate)
                        else:
                            sel_model.setCurrentIndex(
                                index,
                                QItemSelectionModel.SelectionFlag.ClearAndSelect,
                            )
                    else:
                        sel_model.setCurrentIndex(
                                index,
                                QItemSelectionModel.SelectionFlag.ClearAndSelect,
                            )
                    # If Qt skipped scrollTo for this selection mutation, clear the guard.
                    QTimer.singleShot(
                        0,
                        lambda: setattr(self, "_suppress_virtual_auto_scroll_once", False),
                    )
                    QTimer.singleShot(
                        0,
                        lambda: setattr(self, "_suppress_masonry_auto_scroll_once", False),
                    )
                else:
                    self._suppress_virtual_auto_scroll_once = True
                    self._suppress_masonry_auto_scroll_once = True
                    self.setCurrentIndex(index)
                    QTimer.singleShot(
                        0,
                        lambda: setattr(self, "_suppress_virtual_auto_scroll_once", False),
                    )
                    QTimer.singleShot(
                        0,
                        lambda: setattr(self, "_suppress_masonry_auto_scroll_once", False),
                    )

                    try:
                        current_global = self._current_global_from_current_index(source_model)
                        if isinstance(current_global, int) and current_global >= 0:
                            self._selected_global_index = int(current_global)
                            self._current_global_row_cache = int(current_global)
                            if not (modifiers & (Qt.ControlModifier | Qt.ShiftModifier)):
                                self._selected_global_rows_cache = {int(current_global)}
                        elif clicked_global >= 0:
                            self._selected_global_index = int(clicked_global)
                            self._current_global_row_cache = int(clicked_global)
                            if not (modifiers & (Qt.ControlModifier | Qt.ShiftModifier)):
                                self._selected_global_rows_cache = {int(clicked_global)}
                    except Exception:
                        if clicked_global >= 0:
                            self._selected_global_index = int(clicked_global)
                            self._current_global_row_cache = int(clicked_global)
                            if not (modifiers & (Qt.ControlModifier | Qt.ShiftModifier)):
                                self._selected_global_rows_cache = {int(clicked_global)}
                    self._current_proxy_row_cache = int(index.row())
                    if not (modifiers & (Qt.ControlModifier | Qt.ShiftModifier)):
                        self._selected_rows_cache = {int(index.row())}
                    self._last_stable_scroll_value = int(self.verticalScrollBar().value())
                    if (
                        not (modifiers & (Qt.ControlModifier | Qt.ShiftModifier))
                        and clicked_global >= 0
                    ):
                        try:
                            self._extend_exact_target_hold(
                                int(clicked_global),
                                seconds=20.0,
                            )
                        except Exception:
                            pass
                    import time as _time_mod
                    self._user_click_selection_frozen_until = _time_mod.time() + 1.5
                event.accept()
                return
            return super().mousePressEvent(event)

        if self.use_masonry and self._masonry_items:
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
                            pass
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

                if clicked_global < 0:
                    try:
                        clicked_global = int(self._proxy_index_to_global_index(index))
                    except Exception:
                        clicked_global = -1

                # A deliberate thumbnail click should override stale scroll-edge
                # ownership from earlier top/bottom navigation. Otherwise the
                # next resize can snap back to page 1 or the tail instead of
                # recentering the clicked item.
                self._stick_to_edge = None
                self._pending_edge_snap = None
                self._pending_edge_snap_until = 0.0
                self._release_page_lock_page = None
                self._release_page_lock_until = 0.0
                self._drag_release_anchor_active = False
                self._drag_release_anchor_idx = None
                self._drag_release_anchor_until = 0.0

                # Check modifiers
                modifiers = event.modifiers()
                active_exact_target = None
                try:
                    active_exact_target = self._get_active_exact_target_global(source_model=source_model)
                except Exception:
                    active_exact_target = None
                preserve_exact_target_hold = bool(
                    not (modifiers & (Qt.ControlModifier | Qt.ShiftModifier))
                    and isinstance(active_exact_target, int)
                    and active_exact_target >= 0
                    and int(clicked_global) == int(active_exact_target)
                )
                stabilize_state = None
                consume_stabilization = getattr(self, "_consume_post_jump_stabilization", None)
                if callable(consume_stabilization):
                    try:
                        stabilize_state = consume_stabilization(source_model=source_model)
                    except Exception:
                        stabilize_state = None
                if not preserve_exact_target_hold:
                    # Explicit click means user is choosing a new selection identity.
                    self._selected_global_lock_until = 0.0
                    self._selected_global_lock_value = None
                    self._clear_explicit_jump_tracking()
                    if (
                        not (modifiers & (Qt.ControlModifier | Qt.ShiftModifier))
                        and isinstance(clicked_global, int)
                        and clicked_global >= 0
                        and isinstance(stabilize_state, dict)
                    ):
                        arm_stabilization = getattr(self, "_arm_post_jump_stabilization", None)
                        if callable(arm_stabilization):
                            try:
                                page_size = int(getattr(source_model, "PAGE_SIZE", 1000) or 1000)
                            except Exception:
                                page_size = 1000
                            try:
                                arm_stabilization(
                                    int(clicked_global),
                                    target_page=max(0, int(clicked_global) // max(1, page_size)),
                                    reason=str(stabilize_state.get("reason", "browse_click") or "browse_click"),
                                    hold_s=90.0,
                                )
                            except Exception:
                                pass
                self._strict_jump_target_global = None
                self._strict_jump_until = 0.0
                self._mark_selection_log_source("user_click", hold_s=2.5)
                self._pending_click_commit_index = QPersistentModelIndex(index)
                self._pending_click_commit_global = int(clicked_global) if clicked_global >= 0 else None

                if modifiers & Qt.ControlModifier:
                    # Ctrl+Click: toggle selection WITHOUT clearing others
                    was_selected = self.selectionModel().isSelected(index)

                    # First, set as current index
                    self._suppress_masonry_auto_scroll_once = True
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
                        self._suppress_masonry_auto_scroll_once = True
                        self.selectionModel().setCurrentIndex(index, QItemSelectionModel.NoUpdate)

                        # Debug: show all selected indices
                        # all_selected = [idx.row() for idx in self.selectionModel().selectedIndexes()]
                        # print(f"[DEBUG] After Shift+Click, all selected rows: {all_selected}")
                    else:
                        # No current index, just select this one
                        self.selectionModel().select(index, QItemSelectionModel.Select)
                        self._suppress_masonry_auto_scroll_once = True
                        self.selectionModel().setCurrentIndex(index, QItemSelectionModel.NoUpdate)

                    # Force repaint
                    self.viewport().update()
                else:
                    # Normal click: clear and select only this item
                    # Use a single Qt selection operation. This is safer than
                    # clearSelection()+select() during rapid layout updates.
                    sel_model = self.selectionModel()
                    if sel_model:
                        self._suppress_masonry_auto_scroll_once = True
                        sel_model.setCurrentIndex(
                            index, QItemSelectionModel.SelectionFlag.ClearAndSelect
                        )
                        self.viewport().update()

                QTimer.singleShot(
                    0,
                    lambda: setattr(self, "_suppress_masonry_auto_scroll_once", False),
                )

                # Freeze selection against recalc-driven mutations.
                # The click's own setCurrentIndex already fired synchronously above,
                # so all handlers (save_image_index, load_image, etc.) already ran
                # with the CORRECT index.  Any subsequent currentChanged triggered
                # by updateGeometries / layout churn in the completion path must NOT
                # overwrite the user's deliberate click.
                import time as _time_mod
                if (
                    not (modifiers & (Qt.ControlModifier | Qt.ShiftModifier))
                    and clicked_global >= 0
                ):
                    try:
                        self._extend_exact_target_hold(
                            int(clicked_global),
                            seconds=20.0,
                        )
                    except Exception:
                        pass
                self._user_click_selection_frozen_until = _time_mod.time() + 2.0
                if hasattr(self, '_activate_selected_idle_anchor'):
                    try:
                        self._activate_selected_idle_anchor(source_model=source_model, hold_s=2.5)
                    except Exception:
                        pass

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
                    if self._drag_to_external_only_mode():
                        start_drag = getattr(self, "_start_spawn_drag_for_index", None)
                        if callable(start_drag):
                            start_drag(drag_index, Qt.DropAction.CopyAction)
                    else:
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

        source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else None
        virtual_list_active = bool(
            hasattr(self, '_virtual_list_is_active') and self._virtual_list_is_active(source_model)
        )
        list_like_active = bool(
            virtual_list_active
            or (
                not bool(getattr(self, "use_masonry", False))
                and self.viewMode() == QListView.ViewMode.ListMode
            )
        )

        if list_like_active and (event.buttons() & Qt.MouseButton.LeftButton):
            # Prevent Qt's native drag-selection/range-selection path for list
            # modes. Click selection is already decided on press, and larger
            # drags are handled above by the explicit spawn-drag gesture.
            event.accept()
        elif self.use_masonry and self._masonry_items:
            # Don't call super() - it triggers rubber-band selection
            # Just accept the event to prevent default behavior
            event.accept()
        else:
            super().mouseMoveEvent(event)


    def mouseDoubleClickEvent(self, event):
        """Handle double-click events."""
        # Only a left-button double-click should trigger media actions.
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseDoubleClickEvent(event)
            return

        source_model = (
            self.model().sourceModel()
            if self.model() and hasattr(self.model(), 'sourceModel')
            else self.model()
        )
        index = self._resolve_pressed_index(event.pos(), source_model)
        if index.isValid():
            # Get the image at this index
            image = index.data(Qt.ItemDataRole.UserRole)
            if image:
                # Visual feedback: flash the thumbnail
                self._flash_thumbnail(index)
                if event.modifiers() & Qt.KeyboardModifier.AltModifier:
                    show_in_explorer = getattr(self, "_show_in_windows_explorer", None)
                    if callable(show_in_explorer):
                        show_in_explorer(image.path)
                        event.accept()
                        return

                action = self._get_image_list_double_click_action()
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    action = (
                        'system_default_app'
                        if action == 'spawn_viewer'
                        else 'spawn_viewer'
                    )

                handled = False
                if action == 'spawn_viewer':
                    handled = self._spawn_viewer_for_double_click(index, event)
                    if not handled:
                        handled = self._open_double_click_in_system_app(image)
                else:
                    handled = self._open_double_click_in_system_app(image)
                    if not handled:
                        handled = self._spawn_viewer_for_double_click(index, event)

                if handled:
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
        should_commit_click_selection = (
            event.button() == Qt.MouseButton.LeftButton
            and bool(getattr(self, "_suppress_selection_commit_until_release", False))
            and not bool(getattr(self, "_spawn_drag_active", False))
        )
        self._clear_spawn_drag_tracking()
        if bool(getattr(self, "_spawn_drag_active", False)):
            self._finish_spawn_drag_active(should_spawn=(event.button() == Qt.MouseButton.LeftButton))
            event.accept()
            return

        # Resume enrichment after 500ms idle
        source_model = self.model().sourceModel() if self.model() and hasattr(self.model(), 'sourceModel') else None
        if source_model and hasattr(source_model, '_enrichment_timer') and source_model._enrichment_timer:
            source_model._enrichment_timer.start(500)

        virtual_list_active = bool(
            hasattr(self, '_virtual_list_is_active') and self._virtual_list_is_active(source_model)
        )

        if virtual_list_active:
            # Virtual-list selection is already fully handled on press. Letting
            # Qt process release can reuse a stale currentIndex() as a range
            # anchor and intermittently select everything between clicks.
            event.accept()
        elif self.use_masonry and self._masonry_items:
            # Just accept the event, don't let Qt handle it
            event.accept()
        else:
            super().mouseReleaseEvent(event)

        if should_commit_click_selection:
            host = self.window()
            if host is not None and hasattr(host, "commit_thumbnail_click_selection"):
                commit_index = QModelIndex()
                pending_global = getattr(self, "_pending_click_commit_global", None)
                if isinstance(pending_global, int) and pending_global >= 0:
                    try:
                        source_model = (
                            self.model().sourceModel()
                            if self.model() and hasattr(self.model(), "sourceModel")
                            else self.model()
                        )
                        loaded_row = -1
                        if source_model is not None and hasattr(source_model, "get_loaded_row_for_global_index"):
                            loaded_row = int(source_model.get_loaded_row_for_global_index(int(pending_global)))
                        if loaded_row >= 0 and source_model is not None:
                            src_idx = source_model.index(loaded_row, 0)
                            proxy_model = self.model()
                            if proxy_model is not None and hasattr(proxy_model, "mapFromSource"):
                                mapped_idx = proxy_model.mapFromSource(src_idx)
                            else:
                                mapped_idx = src_idx
                            if mapped_idx.isValid():
                                commit_index = mapped_idx
                    except Exception:
                        commit_index = QModelIndex()
                pending_commit = QPersistentModelIndex(
                    getattr(self, "_pending_click_commit_index", QPersistentModelIndex())
                )
                if (not commit_index.isValid()) and pending_commit.isValid():
                    try:
                        live_model = self.model()
                        if live_model is not None:
                            if isinstance(pending_commit, QPersistentModelIndex) and pending_commit.isValid():
                                live_index = QModelIndex(pending_commit)
                            else:
                                live_index = live_model.index(pending_commit.row(), pending_commit.column())
                            if live_index.isValid():
                                commit_index = live_index
                    except Exception:
                        commit_index = QModelIndex()
                try:
                    host.commit_thumbnail_click_selection(commit_index)
                except Exception:
                    pass
        self._pending_click_commit_index = QPersistentModelIndex()
        self._pending_click_commit_global = None
        self._suppress_selection_commit_until_release = False

    def leaveEvent(self, event):
        # If pointer exits during a fast drag/release, ensure no stale spawn
        # gesture remains armed.
        if not bool(getattr(self, "_spawn_drag_active", False)):
            self._clear_spawn_drag_tracking()
            if not (QApplication.mouseButtons() & Qt.MouseButton.LeftButton):
                self._suppress_selection_commit_until_release = False
        super().leaveEvent(event)

    def focusOutEvent(self, event):
        # Losing focus while dragging can drop release events; keep armed state
        # and let poll timer detect button release globally.
        if not bool(getattr(self, "_spawn_drag_active", False)):
            self._clear_spawn_drag_tracking()
            if not (QApplication.mouseButtons() & Qt.MouseButton.LeftButton):
                self._suppress_selection_commit_until_release = False
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
                            self._clear_explicit_jump_tracking()
                        else:
                            # Keep key consumed until stable target is materialized.
                            event.accept()
                            return
                    elif lock_active:
                        # Already anchored on stable global; release lock and navigate.
                        self._selected_global_lock_until = 0.0
                        self._selected_global_lock_value = None
                        self._clear_explicit_jump_tracking()

        plain_arrow_actions = {
            Qt.Key.Key_Left: QAbstractItemView.CursorAction.MoveLeft,
            Qt.Key.Key_Right: QAbstractItemView.CursorAction.MoveRight,
            Qt.Key.Key_Up: QAbstractItemView.CursorAction.MoveUp,
            Qt.Key.Key_Down: QAbstractItemView.CursorAction.MoveDown,
        }
        if (
            event.key() in plain_arrow_actions
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
        ):
            try:
                next_index = self.moveCursor(plain_arrow_actions[event.key()], event.modifiers())
            except Exception:
                next_index = QModelIndex()
            if next_index.isValid():
                sel_model = self.selectionModel()
                if sel_model is not None:
                    sel_model.setCurrentIndex(
                        next_index,
                        QItemSelectionModel.SelectionFlag.ClearAndSelect,
                    )
                else:
                    self.setCurrentIndex(next_index)
                self.scrollTo(next_index, QAbstractItemView.ScrollHint.EnsureVisible)
                event.accept()
                return

        # Default behavior for other keys
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        """Delay masonry snap until Ctrl is released after Ctrl+wheel zoom."""
        if event.key() == Qt.Key.Key_Control and bool(getattr(self, "_zoom_resize_wait_for_ctrl_release", False)):
            self._zoom_resize_snap_defer_until = 0.0
            if hasattr(self, "_zoom_resize_idle_timer"):
                self._zoom_resize_idle_timer.stop()
                self._zoom_resize_idle_timer.start(250)
        super().keyReleaseEvent(event)

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
        self._current_page = max(0, int(target_page))
        self._restore_target_page = int(target_page)
        try:
            enrich_buffer_pages = int(settings.value('thumbnail_eviction_pages', 3, type=int))
        except Exception:
            enrich_buffer_pages = 3
        enrich_buffer_pages = max(1, min(enrich_buffer_pages, 6))
        enrich_start_page = max(0, int(target_page) - enrich_buffer_pages)
        enrich_end_page = min(
            max(0, (total_items - 1) // max(1, page_size)),
            int(target_page) + enrich_buffer_pages,
        ) if total_items > 0 else 0

        # Load target page immediately when selection is outside loaded window.
        try:
            loaded_pages = getattr(source_model, '_pages', {})
            if isinstance(loaded_pages, dict) and target_page not in loaded_pages:
                if hasattr(source_model, '_load_page_sync'):
                    source_model._load_page_sync(target_page)
                    if hasattr(source_model, '_emit_pages_updated'):
                        source_model._emit_pages_updated()
                    if hasattr(source_model, '_start_paginated_enrichment'):
                        source_model._start_paginated_enrichment(
                            window_pages={int(target_page)},
                            scope='window',
                        )
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

        paginated_masonry_active = bool(
            self.use_masonry
            and getattr(source_model, '_paginated_mode', False)
        )
        if paginated_masonry_active:
            import time as _t

            self._selected_global_index = int(target_global)
            self._restore_target_page = int(target_page)
            self._restore_target_global_index = int(target_global)
            self._restore_anchor_until = max(
                float(getattr(self, '_restore_anchor_until', 0.0) or 0.0),
                _t.time() + 4.0,
            )

            item_rect = QRect()
            if getattr(self, '_masonry_items', None):
                try:
                    item_rect = self._get_masonry_item_rect(int(target_global))
                except Exception:
                    item_rect = QRect()

            if not item_rect.isValid():
                self._last_masonry_window_signature = None
                self._calculate_masonry_layout()
                self.viewport().update()
                return True

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
                    from models.image_list_model import extract_video_info
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

        Route Home/End through the exact-target jump path. The older dedicated
        masonry flow had separate page/window math and could drift to nearby
        viewports; exact jumps are now the more stable path.
        """
        total_items = int(getattr(source_model, '_total_count', 0) or 0)
        if total_items <= 0:
            return

        target_global_idx = (total_items - 1) if go_end else 0
        self._pending_home_end_nav = None
        self._pending_explicit_jump_kind = "index_input"
        self.go_to_global_index(int(target_global_idx))


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
            self._pending_explicit_jump_kind = "index_input"
            diagnostic_print(
                f"{diagnostic_time_prefix()} [jump index requested] index {int(index_1_based)}",
                detail="essential",
            )
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
        self._pending_explicit_jump_kind = "index_input"
        diagnostic_print(
            f"{diagnostic_time_prefix()} [jump page requested] page {target_page + 1} via=input",
            detail="essential",
        )
        return self.go_to_global_index(target_global)

    def start_targeted_relocation(
        self,
        target_global: int,
        *,
        reason: str = "global_jump",
        source_model=None,
    ) -> bool:
        """Relocate the viewport/selection to a stable global target."""
        import time as _t

        if source_model is None:
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

        jump_kind = str(reason or "").strip() or "global_jump"
        strict_paginated_masonry = bool(
            self.use_masonry
            and hasattr(source_model, "_paginated_mode")
            and source_model._paginated_mode
            and hasattr(self, "_use_local_anchor_masonry")
            and self._use_local_anchor_masonry(source_model)
        )
        prefer_forward_window = jump_kind in {"sort_restore", "startup_restore"}

        if strict_paginated_masonry and jump_kind in {
            "sort_restore",
            "startup_restore",
            "page_drag",
            "index_input",
        }:
            return self._start_one_shot_targeted_jump(
                int(target_global),
                reason=str(jump_kind),
                source_model=source_model,
            )

        start_ts = _t.monotonic()
        self._clear_pending_targeted_relocation()
        clear_stabilization = getattr(self, "_clear_post_jump_stabilization", None)
        if callable(clear_stabilization):
            clear_stabilization()
        self._mark_selection_log_source(str(jump_kind), hold_s=30.0 if strict_paginated_masonry else 8.0)
        queue_reflow_guide = getattr(self, "_queue_target_reflow_guide", None)
        if self.use_masonry and callable(queue_reflow_guide):
            try:
                queue_reflow_guide(int(target_global), source_model=source_model, duration_ms=3200)
            except Exception:
                pass

        if strict_paginated_masonry:
            lock_until = _t.time() + 30.0
            self._selected_global_lock_value = int(target_global)
            self._selected_global_lock_until = lock_until
            self._suppress_masonry_auto_scroll_until = _t.time() + 8.0
            self._strict_jump_target_global = int(target_global)
            self._strict_jump_until = lock_until
            self._last_explicit_jump_kind = str(jump_kind)
            self._last_explicit_jump_target_global = int(target_global)
            self._last_explicit_jump_until = lock_until
        else:
            self._selected_global_lock_until = 0.0
            self._selected_global_lock_value = None
            self._strict_jump_target_global = None
            self._strict_jump_until = 0.0
            self._last_explicit_jump_kind = str(jump_kind)
            self._last_explicit_jump_target_global = int(target_global)
            self._last_explicit_jump_until = _t.time() + 8.0

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
        if strict_paginated_masonry:
            self._release_page_lock_page = int(target_page)
            self._release_page_lock_until = _t.time() + 30.0
            self._idle_anchor_target_global = None
            self._idle_anchor_until = 0.0
            self._resize_anchor_page = None
            self._resize_anchor_target_global = None
            self._resize_anchor_until = 0.0

        prepared_state = None
        if getattr(source_model, "_paginated_mode", False) and hasattr(source_model, "prepare_target_window"):
            try:
                prepared_state = source_model.prepare_target_window(
                    int(target_global),
                    sync_target_page=True,
                    include_buffer=True,
                    prefer_forward=prefer_forward_window,
                    emit_update=True,
                    request_async_window=True,
                    restart_enrichment=bool(strict_paginated_masonry),
                )
            except Exception:
                prepared_state = None

        if prepared_state is None and not strict_paginated_masonry:
            try:
                pages = getattr(source_model, "_pages", {})
                if isinstance(pages, dict) and target_page not in pages and hasattr(source_model, "_load_page_sync"):
                    source_model._load_page_sync(target_page)
                    if hasattr(source_model, "_emit_pages_updated"):
                        source_model._emit_pages_updated()
            except Exception:
                pass

        if prepared_state is None:
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
        self._restore_anchor_until = _t.time() + 30.0
        self._selected_global_index = int(target_global)

        mw = self.window()
        if (
            mw is not None
            and hasattr(mw, "_restore_in_progress")
            and hasattr(mw, "_restore_target_global_rank")
        ):
            mw._restore_in_progress = True
            mw._restore_target_global_rank = int(target_global)

        if strict_paginated_masonry:
            try:
                jump_domain = int(self._get_strict_scroll_domain_max(source_model, include_drag_baseline=True))
            except Exception:
                jump_domain = int(self._strict_canonical_domain_max(source_model))
            self._strict_scroll_max_floor = max(
                int(getattr(self, "_strict_scroll_max_floor", 0) or 0),
                int(jump_domain),
            )
            self._strict_drag_frozen_max = max(
                int(getattr(self, "_strict_drag_frozen_max", 0) or 0),
                int(jump_domain),
            )
            self._strict_drag_frozen_until = _t.time() + 8.0

            try:
                sb = self.verticalScrollBar()
                keep_max = max(int(jump_domain), int(self._strict_canonical_domain_max(source_model)))
                target_scroll = self._get_strict_canonical_scroll_for_global(
                    int(target_global),
                    source_model=source_model,
                    domain_max=keep_max,
                )
                if target_scroll is None:
                    last_page = max(0, (total_items - 1) // max(1, page_size))
                    page_frac = max(0.0, min(1.0, int(target_page) / max(1, last_page)))
                    target_scroll = int(round(page_frac * keep_max))
                target_scroll = max(0, min(int(target_scroll), keep_max))
                prev_block = sb.blockSignals(True)
                try:
                    sb.setRange(0, keep_max)
                    sb.setValue(target_scroll)
                finally:
                    sb.blockSignals(prev_block)
                self._last_stable_scroll_value = int(target_scroll)
            except Exception:
                pass

            self._last_masonry_window_signature = None
            self._calculate_masonry_layout()

        loaded_row = -1
        if isinstance(prepared_state, dict):
            try:
                loaded_row = int(prepared_state.get("loaded_row", -1))
            except Exception:
                loaded_row = -1
        if loaded_row < 0:
            if hasattr(source_model, "get_loaded_row_for_global_index"):
                try:
                    loaded_row = int(source_model.get_loaded_row_for_global_index(target_global))
                except Exception:
                    loaded_row = -1
            else:
                loaded_row = target_global

        proxy_idx = QModelIndex()
        if loaded_row >= 0:
            try:
                src_idx = source_model.index(loaded_row, 0)
                proxy_model = self.model()
                proxy_idx = (
                    proxy_model.mapFromSource(src_idx)
                    if proxy_model and hasattr(proxy_model, "mapFromSource")
                    else src_idx
                )
            except Exception:
                proxy_idx = QModelIndex()

        if proxy_idx.isValid():
            sel_model = self.selectionModel()
            if sel_model is not None:
                sel_model.setCurrentIndex(proxy_idx, QItemSelectionModel.SelectionFlag.ClearAndSelect)
            else:
                self.setCurrentIndex(proxy_idx)

        if strict_paginated_masonry:
            print(
                f"[RELOCATE] {jump_kind}: target={int(target_global)} page={int(target_page)} "
                f"window={'forward' if prefer_forward_window else 'centered'} "
                f"prepared_ms={int((_t.monotonic() - start_ts) * 1000)}"
            )
            self._start_exact_jump_settle(int(target_global))
            self.viewport().update()
            return True

        if proxy_idx.isValid():
            self.scrollTo(proxy_idx, QAbstractItemView.ScrollHint.PositionAtCenter)
            self.viewport().update()
            return True
        return False

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
        jump_kind = getattr(self, "_pending_explicit_jump_kind", None)
        if not isinstance(jump_kind, str) or not jump_kind:
            jump_kind = "global_jump"
        self._pending_explicit_jump_kind = None
        return self.start_targeted_relocation(
            int(target_global),
            reason=str(jump_kind),
            source_model=source_model,
        )


    def wheelEvent(self, event):
        """Handle Ctrl+scroll for zooming thumbnails."""
        if event.modifiers() & Qt.ControlModifier:
            import time
            # Ctrl+wheel can arrive without keyboard focus; keep arrows working after zoom.
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            source_model = (
                self.model().sourceModel()
                if self.model() and hasattr(self.model(), 'sourceModel')
                else self.model()
            )
            anchor_global = None
            if (
                hasattr(self, "_virtual_list_is_active")
                and self._virtual_list_is_active(source_model)
            ):
                candidate = getattr(self, "_selected_global_index", None)
                if isinstance(candidate, int) and candidate >= 0:
                    anchor_global = int(candidate)
                else:
                    try:
                        mapped = self._current_global_from_current_index(source_model)
                        if isinstance(mapped, int) and mapped >= 0:
                            anchor_global = int(mapped)
                    except Exception:
                        anchor_global = None
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
            self._last_ctrl_wheel_zoom_direction = 1 if delta > 0 else -1 if delta < 0 else 0

            full_width_masonry = bool(
                self.use_masonry
                and hasattr(self, "_is_full_width_masonry_mode")
                and self._is_full_width_masonry_mode()
            )
            target_size, new_size = self._step_thumbnail_size_request(
                self._last_ctrl_wheel_zoom_direction,
            )
            self._target_thumbnail_size = int(target_size)

            if new_size != self.current_thumbnail_size or full_width_masonry:
                self.current_thumbnail_size = new_size
                self.setIconSize(QSize(self.current_thumbnail_size, self.current_thumbnail_size * 3))

                # Update view mode (single column vs multi-column)
                self._update_view_mode()

                # If masonry, recalculate layout and re-center after zoom stops
                if self.use_masonry:
                    if full_width_masonry:
                        # In full-width masonry, preview the already-correct
                        # fitted size during Ctrl+wheel instead of waiting for
                        # Ctrl release and then changing size again.
                        self._zoom_resize_wait_for_ctrl_release = False
                        self._zoom_resize_snap_defer_until = 0.0
                        if hasattr(self, "_zoom_resize_idle_timer"):
                            self._zoom_resize_idle_timer.stop()
                        resize_delay_ms = 120
                    else:
                        # Treat Ctrl+wheel as a zoom session and keep the splitter
                        # fixed until Ctrl is released.
                        self._zoom_resize_wait_for_ctrl_release = True
                        self._zoom_resize_snap_defer_until = time.time() + 1.0
                        if hasattr(self, "_zoom_resize_idle_timer"):
                            self._zoom_resize_idle_timer.stop()
                        resize_delay_ms = 420
                    # Debounce: recalculate and re-center after user stops zooming
                    self._resize_timer.stop()
                    self._resize_timer.start(resize_delay_ms)
                else:
                    updated_source_model = (
                        self.model().sourceModel()
                        if self.model() and hasattr(self.model(), 'sourceModel')
                        else self.model()
                    )
                    if (
                        hasattr(self, "_virtual_list_is_active")
                        and self._virtual_list_is_active(updated_source_model)
                        and hasattr(self, "_scroll_selected_global_to_center_safe")
                    ):
                        if isinstance(anchor_global, int) and anchor_global >= 0:
                            self._selected_global_index = int(anchor_global)
                        self._scroll_selected_global_to_center_safe()

                # Save to settings
                settings.setValue('image_list_thumbnail_size', self.current_thumbnail_size)
                refresh_thumbnail_controls = getattr(self, "_refresh_thumbnail_size_controls", None)
                if callable(refresh_thumbnail_controls):
                    refresh_thumbnail_controls()

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

        source_model = (
            self.model().sourceModel()
            if self.model() and hasattr(self.model(), "sourceModel")
            else self.model()
        )
        virtual_list_active = bool(
            hasattr(self, "_virtual_list_is_active")
            and self._virtual_list_is_active(source_model)
        )
        if virtual_list_active:
            delta = event.angleDelta().y()
            if delta == 0 and hasattr(event, "pixelDelta"):
                try:
                    delta = int(event.pixelDelta().y())
                except Exception:
                    delta = 0
            if delta != 0:
                sb = self.verticalScrollBar()
                row_height = max(1, int(self._virtual_list_row_height()))
                scroll_step = max(24, row_height // 2)
                steps = float(delta) / 120.0 if abs(delta) >= 120 else float(delta) / float(scroll_step)
                scroll_amount = int(round(steps * scroll_step))
                target_value = max(0, min(int(sb.maximum()), int(sb.value()) - scroll_amount))
                if target_value != int(sb.value()):
                    sb.setValue(target_value)
                self._last_stable_scroll_value = int(sb.value())
            event.accept()
            return

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
