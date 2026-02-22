from __future__ import annotations

from PySide6.QtCore import QEvent, QModelIndex, QPersistentModelIndex, QPoint, QPointF, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QResizeEvent
from PySide6.QtWidgets import QMenu, QPushButton, QWidget

from utils.settings import DEFAULT_SETTINGS, settings
from widgets.image_viewer import (
    COMPARE_FIT_MODE_FILL,
    COMPARE_FIT_MODE_OPTIONS,
    COMPARE_FIT_MODE_PRESERVE,
    COMPARE_FIT_MODE_STRETCH,
    ImageViewer,
)
from widgets.video_controls import VideoControlsWidget
from widgets.video_sync_coordinator import VideoSyncCoordinator

try:
    from shiboken6 import isValid as _shiboken_is_valid
except Exception:
    _shiboken_is_valid = None


class MediaComparisonWidget(QWidget):
    """Frameless comparison window for video media (2-way with optional 3rd/4th layers)."""

    closing = Signal()

    def __init__(self, model_a, model_b, proxy_image_list_model, parent=None, model_c=None, model_d=None):
        super().__init__(
            parent,
            Qt.WindowType.Window | Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle("Media Comparison")
        self.setMinimumSize(400, 300)
        self.setMouseTracking(True)

        self.split_position = 0.5
        self.split_position_y = 0.5
        self._closed = False
        self._manual_seek_active = False
        self._audio_focus_side = None  # "a", "b", "c", or "d"
        self._window_drag_active = False
        self._window_drag_button = Qt.MouseButton.NoButton
        self._window_drag_offset = QPoint()
        self._resize_active = False
        self._resize_zone = None
        self._resize_start_global = QPoint()
        self._resize_start_geometry = QRect()
        self._resize_margin_px = 12
        self._pan_sync_active = False
        self._pan_sync_source: ImageViewer | None = None
        self._close_button_margin_px = 8
        self._close_hover_zone_px = 56
        self._video_fit_transform_stamp: dict[int, tuple] = {}
        self._proxy_image_list_model = proxy_image_list_model
        video_compare_fit_mode = str(
            settings.value(
                'video_compare_fit_mode',
                defaultValue=DEFAULT_SETTINGS.get('video_compare_fit_mode', COMPARE_FIT_MODE_PRESERVE),
                type=str,
            )
            or COMPARE_FIT_MODE_PRESERVE
        ).strip().lower()
        if video_compare_fit_mode not in {COMPARE_FIT_MODE_PRESERVE, COMPARE_FIT_MODE_FILL, COMPARE_FIT_MODE_STRETCH}:
            video_compare_fit_mode = COMPARE_FIT_MODE_PRESERVE
        self._video_compare_fit_mode = video_compare_fit_mode
        self._video_multi_compare_enabled = bool(
            settings.value(
                'video_multi_compare_experimental',
                defaultValue=DEFAULT_SETTINGS.get('video_multi_compare_experimental', True),
                type=bool,
            )
        )

        self._model_a = QPersistentModelIndex(model_a) if hasattr(model_a, "isValid") and model_a.isValid() else QPersistentModelIndex()
        self._model_b = QPersistentModelIndex(model_b) if hasattr(model_b, "isValid") and model_b.isValid() else QPersistentModelIndex()
        self._model_c = QPersistentModelIndex(model_c) if hasattr(model_c, "isValid") and model_c.isValid() else QPersistentModelIndex()
        self._model_d = QPersistentModelIndex(model_d) if hasattr(model_d, "isValid") and model_d.isValid() else QPersistentModelIndex()

        self.viewer_a = ImageViewer(proxy_image_list_model, is_spawned_viewer=True)
        self.viewer_a.setParent(self)
        self.viewer_a.set_scene_padding(0)
        self.viewer_a.view.setBackgroundBrush(Qt.GlobalColor.black)

        self.viewer_b = ImageViewer(proxy_image_list_model, is_spawned_viewer=True)
        self._viewer_b_clip = QWidget(self)
        self._viewer_b_clip.setObjectName("mediaComparisonClip")
        self._viewer_b_clip.setMouseTracking(True)
        self._viewer_b_clip.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self._viewer_b_clip.setStyleSheet("background-color: rgb(12, 12, 12);")
        self.viewer_b.setParent(self._viewer_b_clip)
        self.viewer_b.set_scene_padding(0)
        self.viewer_b.view.setBackgroundBrush(Qt.GlobalColor.black)

        self.viewer_c = ImageViewer(proxy_image_list_model, is_spawned_viewer=True)
        self._viewer_c_clip = QWidget(self)
        self._viewer_c_clip.setObjectName("mediaComparisonClipBottom")
        self._viewer_c_clip.setMouseTracking(True)
        self._viewer_c_clip.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self._viewer_c_clip.setStyleSheet("background-color: rgb(12, 12, 12);")
        self.viewer_c.setParent(self._viewer_c_clip)
        self.viewer_c.set_scene_padding(0)
        self.viewer_c.view.setBackgroundBrush(Qt.GlobalColor.black)
        self._viewer_c_clip.hide()

        self.viewer_d = ImageViewer(proxy_image_list_model, is_spawned_viewer=True)
        self._viewer_d_clip = QWidget(self)
        self._viewer_d_clip.setObjectName("mediaComparisonClipBottomRight")
        self._viewer_d_clip.setMouseTracking(True)
        self._viewer_d_clip.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self._viewer_d_clip.setStyleSheet("background-color: rgb(12, 12, 12);")
        self.viewer_d.setParent(self._viewer_d_clip)
        self.viewer_d.set_scene_padding(0)
        self.viewer_d.view.setBackgroundBrush(Qt.GlobalColor.black)
        self._viewer_d_clip.hide()

        self._divider_widget = QWidget(self)
        self._divider_widget.setStyleSheet("background-color: rgba(255, 255, 255, 220);")
        self._divider_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._divider_widget_h = QWidget(self)
        self._divider_widget_h.setStyleSheet("background-color: rgba(255, 255, 255, 220);")
        self._divider_widget_h.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._close_button = QPushButton("X", self)
        self._close_button.setObjectName("floatingViewerClose")
        self._close_button.setFixedSize(24, 24)
        self._close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_button.setToolTip("Close comparison window")
        self._close_button.clicked.connect(self.close)
        self._close_button.hide()
        self._close_button.raise_()

        self._shared_controls = VideoControlsWidget(self)
        self._shared_controls._is_spawned_owner = True
        self._shared_controls.set_loop_persistence_scope("compare_shared")
        self._shared_controls.hide()
        self._shared_controls_auto_geometry: QRect | None = None
        always_show_controls = bool(
            settings.value(
                'video_always_show_controls',
                defaultValue=DEFAULT_SETTINGS.get('video_always_show_controls', False),
                type=bool,
            )
        )
        self._shared_controls_auto_hide = not always_show_controls
        self._shared_controls_visible = False
        self._shared_controls_hover_inside = False
        self._shared_controls_hide_timer = QTimer(self)
        self._shared_controls_hide_timer.setSingleShot(True)
        self._shared_controls_hide_timer.timeout.connect(self._hide_shared_controls)
        self._configure_shared_controls_ui()
        self._connect_shared_controls()

        self._master_viewer: ImageViewer | None = None
        self._slave_viewer: ImageViewer | None = None
        self._master_signals_connected = False

        self._sync_bootstrap_timer = QTimer(self)
        self._sync_bootstrap_timer.setSingleShot(False)
        self._sync_bootstrap_timer.setInterval(180)
        self._sync_bootstrap_timer.timeout.connect(self._maybe_start_video_sync)
        self._sync_bootstrap_attempts = 0
        self._sync_coordinator: VideoSyncCoordinator | None = None

        self._refresh_filter_timer = QTimer(self)
        self._refresh_filter_timer.setInterval(300)
        self._refresh_filter_timer.timeout.connect(self._refresh_event_filters)
        self._refresh_filter_timer.start()
        self._split_cursor_sync_timer = QTimer(self)
        self._split_cursor_sync_timer.setInterval(16)
        self._split_cursor_sync_timer.timeout.connect(self._poll_split_cursor_sync)
        self._split_cursor_sync_timer.start()

        self.viewer_a.lower()
        self._viewer_b_clip.raise_()
        self._viewer_c_clip.raise_()
        self._viewer_d_clip.raise_()
        self._divider_widget.raise_()
        self._divider_widget_h.raise_()
        self._apply_overlay_style()
        self._reposition_overlay_controls()

        self._refresh_event_filters()
        self._update_split_layout()
        QTimer.singleShot(0, self._deferred_load)

    def viewers(self) -> list[ImageViewer]:
        return [self.viewer_a, self.viewer_b, self.viewer_c, self.viewer_d]

    def _active_viewers(self) -> list[ImageViewer]:
        viewers = [self.viewer_a, self.viewer_b]
        if self._has_third_layer():
            viewers.append(self.viewer_c)
        if self._has_fourth_layer():
            viewers.append(self.viewer_d)
        return viewers

    def _normalize_proxy_index(self, index_like) -> QModelIndex:
        try:
            if index_like is None:
                return QModelIndex()
            if isinstance(index_like, QPersistentModelIndex):
                if not index_like.isValid():
                    return QModelIndex()
                model = index_like.model()
                row = index_like.row()
                col = index_like.column()
            else:
                if not hasattr(index_like, "isValid") or not index_like.isValid():
                    return QModelIndex()
                model = index_like.model()
                row = index_like.row()
                col = index_like.column()
            if model is None or model is not self._proxy_image_list_model:
                return QModelIndex()
            if row < 0 or row >= model.rowCount() or col < 0:
                return QModelIndex()
            return model.index(row, col)
        except Exception:
            return QModelIndex()

    def _is_video_index(self, proxy_index: QModelIndex) -> bool:
        if not proxy_index.isValid():
            return False
        try:
            image = proxy_index.data(Qt.ItemDataRole.UserRole)
            return bool(image is not None and bool(getattr(image, "is_video", False)))
        except Exception:
            return False

    def _has_third_layer(self) -> bool:
        return self._normalize_proxy_index(self._model_c).isValid()

    def _has_fourth_layer(self) -> bool:
        return self._normalize_proxy_index(self._model_d).isValid()

    def get_primary_proxy_index(self) -> QModelIndex:
        return self._normalize_proxy_index(getattr(self.viewer_a, "proxy_image_index", QModelIndex()))

    def get_video_multi_compare_enabled(self) -> bool:
        return bool(getattr(self, "_video_multi_compare_enabled", False))

    def set_video_multi_compare_enabled(self, enabled: bool, *, persist: bool = True) -> bool:
        enabled = bool(enabled)
        changed = enabled != self.get_video_multi_compare_enabled()
        self._video_multi_compare_enabled = enabled
        if persist:
            settings.setValue("video_multi_compare_experimental", enabled)
        return changed

    def can_add_video_layer(self) -> bool:
        if self._closed:
            return False
        if not self.get_video_multi_compare_enabled():
            return False
        if self._has_fourth_layer():
            return False
        return True

    def add_video_layer(self, incoming_index) -> bool:
        if not self.can_add_video_layer():
            return False
        incoming_proxy = self._normalize_proxy_index(incoming_index)
        if not incoming_proxy.isValid() or not self._is_video_index(incoming_proxy):
            return False
        load_viewer = None
        if not self._has_third_layer():
            self._model_c = QPersistentModelIndex(incoming_proxy)
            load_viewer = self.viewer_c
        elif not self._has_fourth_layer():
            self._model_d = QPersistentModelIndex(incoming_proxy)
            load_viewer = self.viewer_d
        if load_viewer is None:
            return False
        try:
            load_viewer.load_image(incoming_proxy)
        except Exception:
            if load_viewer is self.viewer_c:
                self._model_c = QPersistentModelIndex()
            elif load_viewer is self.viewer_d:
                self._model_d = QPersistentModelIndex()
            return False

        self.split_position_y = max(0.0, min(1.0, float(self.split_position_y)))
        self._refresh_event_filters()
        self._apply_video_compare_fit_mode(force=True)
        self._update_split_layout()
        self._schedule_auto_sync()
        self._update_split_from_global_cursor()
        return True

    def get_video_compare_fit_mode(self) -> str:
        mode = str(getattr(self, "_video_compare_fit_mode", COMPARE_FIT_MODE_PRESERVE) or COMPARE_FIT_MODE_PRESERVE).strip().lower()
        if mode not in {COMPARE_FIT_MODE_PRESERVE, COMPARE_FIT_MODE_FILL, COMPARE_FIT_MODE_STRETCH}:
            return COMPARE_FIT_MODE_PRESERVE
        return mode

    def get_video_compare_fit_mode_options(self):
        return tuple(COMPARE_FIT_MODE_OPTIONS)

    def set_video_compare_fit_mode(self, mode: str, *, persist: bool = True) -> bool:
        mode = str(mode or COMPARE_FIT_MODE_PRESERVE).strip().lower()
        if mode not in {COMPARE_FIT_MODE_PRESERVE, COMPARE_FIT_MODE_FILL, COMPARE_FIT_MODE_STRETCH}:
            return False
        changed = mode != self.get_video_compare_fit_mode()
        self._video_compare_fit_mode = mode
        if persist:
            settings.setValue('video_compare_fit_mode', mode)
        self._apply_video_compare_fit_mode(force=True)
        return changed

    def _apply_video_compare_fit_mode_to_viewer(self, viewer: ImageViewer):
        try:
            player = getattr(viewer, "video_player", None)
            if player is None:
                return
            setter = getattr(player, "set_display_fit_mode", None)
            if callable(setter):
                setter(self.get_video_compare_fit_mode())
        except Exception:
            return

    def _apply_video_compare_fit_transform_to_viewer(self, viewer: ImageViewer, *, force: bool = False):
        try:
            if not bool(getattr(viewer, "_is_video_loaded", False)):
                self._video_fit_transform_stamp.pop(id(viewer), None)
                return
            view = getattr(viewer, "view", None)
            scene = getattr(viewer, "scene", None)
            if view is None or scene is None:
                return
            viewport_rect = view.viewport().rect()
            scene_rect = scene.sceneRect()
            if viewport_rect.width() <= 0 or viewport_rect.height() <= 0:
                return
            if scene_rect.width() <= 0 or scene_rect.height() <= 0:
                return

            mode = self.get_video_compare_fit_mode()
            stamp = (
                mode,
                int(viewport_rect.width()),
                int(viewport_rect.height()),
                int(round(float(scene_rect.width()))),
                int(round(float(scene_rect.height()))),
                bool(getattr(viewer, "is_zoom_to_fit", False)),
            )
            previous_stamp = self._video_fit_transform_stamp.get(id(viewer))
            if (not force) and previous_stamp == stamp:
                return
            if (not force) and not bool(getattr(viewer, "is_zoom_to_fit", False)):
                # User manually zoomed/panned; avoid snapping back while scrubbing split.
                self._video_fit_transform_stamp[id(viewer)] = stamp
                return

            if mode == COMPARE_FIT_MODE_PRESERVE:
                viewer.zoom_fit()
            elif mode == COMPARE_FIT_MODE_FILL:
                scale_x = float(viewport_rect.width()) / float(scene_rect.width())
                scale_y = float(viewport_rect.height()) / float(scene_rect.height())
                target_scale = max(scale_x, scale_y)
                if target_scale <= 0.0:
                    return
                viewer._apply_uniform_zoom_scale(
                    float(target_scale * 1.0004),
                    zoom_to_fit_state=True,
                    focus_scene_pos=scene_rect.center(),
                    anchor_view_pos=None,
                )
            else:
                # Stretch requires non-uniform scaling, so apply directly.
                scale_x = float(viewport_rect.width()) / float(scene_rect.width())
                scale_y = float(viewport_rect.height()) / float(scene_rect.height())
                if scale_x <= 0.0 or scale_y <= 0.0:
                    return
                view.resetTransform()
                view.scale(float(scale_x), float(scale_y))
                view.centerOn(scene_rect.center())
                viewer.is_zoom_to_fit = True
                player = getattr(viewer, "video_player", None)
                if player is not None:
                    try:
                        player.sync_external_surface_geometry()
                    except Exception:
                        pass
                    try:
                        player.set_view_transformed(False)
                    except Exception:
                        pass

            self._video_fit_transform_stamp[id(viewer)] = stamp
        except Exception:
            return

    def _apply_video_compare_fit_mode(self, *, force: bool = False):
        for viewer in self._active_viewers():
            self._apply_video_compare_fit_mode_to_viewer(viewer)
            self._apply_video_compare_fit_transform_to_viewer(viewer, force=force)

    def _shared_controls_widget(self) -> VideoControlsWidget | None:
        controls = getattr(self, "_shared_controls", None)
        if controls is None:
            return None
        if _shiboken_is_valid is not None:
            try:
                if not _shiboken_is_valid(controls):
                    self._shared_controls = None
                    return None
            except Exception:
                self._shared_controls = None
                return None
        return controls

    def _configure_shared_controls_ui(self):
        controls = self._shared_controls_widget()
        if controls is None:
            return
        # Keep compare control compact and focused on playback/seek.
        for attr in (
            "loop_start_btn",
            "loop_end_btn",
            "loop_checkbox",
            "loop_reset_btn",
            "marker_range_label",
            "sar_warning_label",
        ):
            widget = getattr(controls, attr, None)
            if widget is not None:
                widget.hide()
        controls.timeline_slider.setToolTip("Seek both compared videos")

    def _stabilize_shared_controls_layout(self):
        controls = self._shared_controls_widget()
        if controls is None:
            return
        # Re-apply compare-specific visibility after any internal layout/scaling pass.
        self._configure_shared_controls_ui()
        try:
            stabilize = getattr(controls, "_stabilize_after_geometry_change", None)
            if callable(stabilize):
                stabilize()
        except Exception:
            pass

    def _connect_shared_controls(self):
        c = self._shared_controls_widget()
        if c is None:
            return
        c.play_pause_requested.connect(self._on_shared_play_pause_requested)
        c.stop_requested.connect(self._on_shared_stop_requested)
        c.frame_changed.connect(self._on_shared_seek_frame)
        c.marker_preview_requested.connect(self._on_shared_seek_frame)
        c.skip_backward_requested.connect(lambda: self._on_shared_skip_requested(backward=True))
        c.skip_forward_requested.connect(lambda: self._on_shared_skip_requested(backward=False))
        c.speed_changed.connect(self._on_shared_speed_changed)
        c.mute_toggled.connect(self._on_shared_mute_toggled)

    def _deferred_load(self):
        try:
            if self._normalize_proxy_index(self._model_a).isValid():
                self.viewer_a.load_image(self._model_a)
            if self._normalize_proxy_index(self._model_b).isValid():
                self.viewer_b.load_image(self._model_b)
            if self._normalize_proxy_index(self._model_c).isValid():
                self.viewer_c.load_image(self._model_c)
            if self._normalize_proxy_index(self._model_d).isValid():
                self.viewer_d.load_image(self._model_d)
        except Exception:
            pass
        self._apply_video_compare_fit_mode(force=True)
        self._update_split_layout()
        self._schedule_auto_sync()

    def _iter_video_surface_widgets(self, viewer: ImageViewer):
        player = getattr(viewer, "video_player", None)
        if player is None:
            return
        for attr in ("vlc_widget", "mpv_widget"):
            widget = getattr(player, attr, None)
            if isinstance(widget, QWidget):
                yield widget

    def _refresh_event_filters(self):
        widgets: list[QWidget] = [
            self,
            self.viewer_a,
            self._viewer_b_clip,
            self.viewer_b,
            self._viewer_c_clip,
            self.viewer_c,
            self._viewer_d_clip,
            self.viewer_d,
            self._close_button,
        ]
        controls = self._shared_controls_widget()
        if controls is not None:
            widgets.append(controls)
        for viewer in self.viewers():
            view = getattr(viewer, "view", None)
            if view is not None:
                widgets.append(view)
                widgets.append(view.viewport())
            for surface in self._iter_video_surface_widgets(viewer):
                widgets.append(surface)

        for widget in widgets:
            try:
                widget.installEventFilter(self)
                widget.setMouseTracking(True)
            except Exception:
                continue

    def _set_split_position(self, split: float):
        split = max(0.0, min(1.0, float(split)))
        if abs(split - float(self.split_position)) < 1e-4:
            return
        self.split_position = split
        self._update_split_layout()

    def _set_split_position_y(self, split: float):
        split = max(0.0, min(1.0, float(split)))
        if abs(split - float(self.split_position_y)) < 1e-4:
            return
        self.split_position_y = split
        self._update_split_layout()

    def _update_split_from_global_cursor(self):
        if self._window_drag_active or self._resize_active or self._pan_sync_active:
            return
        if self.width() <= 0 or self.height() <= 0:
            return
        local_pos = self.mapFromGlobal(QCursor.pos())
        split_x = float(local_pos.x()) / float(max(1, self.width()))
        split_x = max(0.0, min(1.0, float(split_x)))
        changed = False
        if abs(split_x - float(self.split_position)) >= 1e-4:
            self.split_position = split_x
            changed = True
        if self._has_third_layer():
            split_y = float(local_pos.y()) / float(max(1, self.height()))
            split_y = max(0.0, min(1.0, float(split_y)))
            if abs(split_y - float(self.split_position_y)) >= 1e-4:
                self.split_position_y = split_y
                changed = True
        if changed:
            self._update_split_layout()

    def _poll_split_cursor_sync(self):
        if self._closed:
            try:
                self._split_cursor_sync_timer.stop()
            except Exception:
                pass
            return
        self._update_split_from_global_cursor()
        self._update_overlay_hover_from_global_pos(QCursor.pos())

    def _event_global_pos(self, event, watched: QWidget | None = None) -> QPoint:
        try:
            return event.globalPosition().toPoint()
        except Exception:
            pass
        try:
            if hasattr(event, "globalPos"):
                return event.globalPos()
        except Exception:
            pass
        if watched is not None and hasattr(event, "position"):
            try:
                return watched.mapToGlobal(event.position().toPoint())
            except Exception:
                pass
        try:
            return self.mapToGlobal(event.position().toPoint())
        except Exception:
            return QCursor.pos()

    def _event_local_pos(self, event, watched: QWidget | None = None) -> QPoint:
        try:
            return self.mapFromGlobal(self._event_global_pos(event, watched))
        except Exception:
            return QPoint()

    def _show_window_menu(self, global_pos: QPoint):
        menu = QMenu(self)
        fit_mode_map = {}
        close_action = menu.addAction("Close comparison")
        resync_action = None
        multi_compare_action = menu.addAction("Experimental: Allow 3/4-video compare")
        multi_compare_action.setCheckable(True)
        multi_compare_action.setChecked(self.get_video_multi_compare_enabled())
        if self._both_videos_ready():
            menu.addSeparator()
            fit_mode_menu = menu.addMenu("Compare Fit Mode")
            current_mode = self.get_video_compare_fit_mode()
            for mode, label in self.get_video_compare_fit_mode_options():
                action = fit_mode_menu.addAction(str(label))
                action.setCheckable(True)
                action.setChecked(str(mode) == str(current_mode))
                fit_mode_map[action] = str(mode)
            menu.addSeparator()
            resync_action = menu.addAction("Resync compared videos")

        close_all_action = None
        parent = self.parentWidget()
        close_all = getattr(parent, "close_all_floating_viewers", None) if parent is not None else None
        if callable(close_all):
            menu.addSeparator()
            close_all_action = menu.addAction("Close all spawned viewers")

        selected = menu.exec(global_pos)
        if selected is close_action:
            self.close()
        elif selected is multi_compare_action:
            self.set_video_multi_compare_enabled(not self.get_video_multi_compare_enabled(), persist=True)
        elif selected in fit_mode_map:
            self.set_video_compare_fit_mode(fit_mode_map[selected], persist=True)
        elif selected is resync_action:
            self._maybe_start_video_sync(force_restart=True)
        elif selected is close_all_action and callable(close_all):
            try:
                close_all()
            except Exception:
                pass

    def _apply_resize_cursor(self, watched, zone_name):
        cursor = self._cursor_for_resize_zone(zone_name)
        target_widget = watched if isinstance(watched, QWidget) else None
        try:
            if cursor is not None:
                if target_widget is not None:
                    target_widget.setCursor(cursor)
                self.setCursor(cursor)
            else:
                if target_widget is not None:
                    target_widget.unsetCursor()
                self.unsetCursor()
        except Exception:
            pass

    def _apply_overlay_style(self):
        self.setStyleSheet(
            """
            #floatingViewerClose {
                border: 1px solid rgba(255, 255, 255, 110);
                border-radius: 5px;
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 rgba(44, 51, 61, 190),
                    stop: 1 rgba(22, 28, 36, 190)
                );
                color: rgba(248, 250, 252, 245);
                font-size: 13px;
                font-weight: 800;
                padding: 0px;
                text-align: center;
            }
            #floatingViewerClose:hover {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 rgba(255, 110, 110, 245),
                    stop: 1 rgba(214, 42, 42, 245)
                );
                border: 1px solid rgba(255, 190, 190, 235);
                color: rgba(255, 255, 255, 255);
            }
            #floatingViewerClose:pressed {
                background: rgba(168, 24, 24, 245);
                border: 1px solid rgba(255, 170, 170, 220);
                color: rgba(255, 245, 245, 255);
            }
            """
        )

    def _reposition_overlay_controls(self):
        margin = max(0, int(self._close_button_margin_px))
        corner_size = max(18, int(self._resize_margin_px) + 6)
        corner_gap = 4
        close_x = max(
            0,
            self.width() - self._close_button.width() - margin - max(2, corner_size // 3),
        )
        close_y = max(
            0,
            min(self.height() - self._close_button.height(), margin + max(4, corner_size // 3)),
        )
        corner_block_rect = QRect(
            max(0, self.width() - corner_size - corner_gap),
            0,
            corner_size + corner_gap,
            corner_size + corner_gap,
        )
        close_rect = QRect(close_x, close_y, self._close_button.width(), self._close_button.height())
        if close_rect.intersects(corner_block_rect):
            close_y = min(
                max(0, self.height() - self._close_button.height()),
                corner_block_rect.bottom() + 1,
            )
        self._close_button.move(close_x, close_y)
        self._close_button.raise_()

    def _show_close_button(self, visible: bool):
        if bool(visible):
            self._close_button.show()
        else:
            self._close_button.hide()

    def _is_in_close_hover_zone(self, local_pos: QPoint) -> bool:
        if local_pos.x() < 0 or local_pos.y() < 0:
            return False
        if local_pos.x() >= self.width() or local_pos.y() >= self.height():
            return False
        zone = max(24, int(self._close_hover_zone_px))
        return local_pos.x() >= (self.width() - zone) and local_pos.y() <= zone

    def _event_targets_close_button(self, watched) -> bool:
        current = watched
        while isinstance(current, QWidget):
            if current is self._close_button:
                return True
            current = current.parentWidget()
        return False

    def _update_overlay_hover_from_global_pos(self, global_pos: QPoint):
        local_pos = self.mapFromGlobal(global_pos)
        self._show_close_button(self._is_in_close_hover_zone(local_pos))
        self._update_shared_controls_hover_from_global_pos(global_pos)

    def _resize_zone_from_local_pos(self, local_pos: QPoint):
        if not self.rect().contains(local_pos):
            return None
        margin = max(4, int(self._resize_margin_px))
        near_left = local_pos.x() <= margin
        near_right = local_pos.x() >= (self.width() - margin)
        near_top = local_pos.y() <= margin
        near_bottom = local_pos.y() >= (self.height() - margin)

        if near_top and near_left:
            return "top_left"
        if near_top and near_right:
            return "top_right"
        if near_bottom and near_left:
            return "bottom_left"
        if near_bottom and near_right:
            return "bottom_right"
        if near_top:
            return "top"
        if near_bottom:
            return "bottom"
        if near_left:
            return "left"
        if near_right:
            return "right"
        return None

    def _cursor_for_resize_zone(self, zone_name):
        if zone_name in ("top_left", "bottom_right"):
            return Qt.CursorShape.SizeFDiagCursor
        if zone_name in ("top_right", "bottom_left"):
            return Qt.CursorShape.SizeBDiagCursor
        if zone_name in ("top", "bottom"):
            return Qt.CursorShape.SizeVerCursor
        if zone_name in ("left", "right"):
            return Qt.CursorShape.SizeHorCursor
        return None

    def _begin_window_drag(self, event, watched: QWidget | None = None):
        global_pos = self._event_global_pos(event, watched)
        drag_button = Qt.MouseButton.LeftButton
        try:
            if hasattr(event, "button"):
                drag_button = event.button()
        except Exception:
            pass
        self._window_drag_active = True
        self._window_drag_button = drag_button
        self._window_drag_offset = global_pos - self.frameGeometry().topLeft()
        try:
            self.grabMouse()
        except Exception:
            pass

    def _is_window_drag_button_down(self, event) -> bool:
        if not self._window_drag_active or self._window_drag_button == Qt.MouseButton.NoButton:
            return False
        try:
            return bool(event.buttons() & self._window_drag_button)
        except Exception:
            return False

    def _end_window_drag(self):
        self._window_drag_active = False
        self._window_drag_button = Qt.MouseButton.NoButton
        try:
            self.releaseMouse()
        except Exception:
            pass

    def _begin_window_resize(self, event, zone_name, watched: QWidget | None = None):
        if not zone_name:
            return
        self._resize_active = True
        self._resize_zone = str(zone_name)
        self._resize_start_global = self._event_global_pos(event, watched)
        self._resize_start_geometry = QRect(self.geometry())
        try:
            self.grabMouse()
        except Exception:
            pass

    def _end_window_resize(self):
        self._resize_active = False
        self._resize_zone = None
        try:
            self.releaseMouse()
        except Exception:
            pass

    def _apply_window_resize(self, global_pos: QPoint):
        if not self._resize_active or not self._resize_zone:
            return

        start = QRect(self._resize_start_geometry)
        delta = global_pos - self._resize_start_global
        min_w = max(200, int(self.minimumWidth()))
        min_h = max(150, int(self.minimumHeight()))

        x = int(start.x())
        y = int(start.y())
        w = int(start.width())
        h = int(start.height())
        dx = int(delta.x())
        dy = int(delta.y())
        zone = str(self._resize_zone)

        if "left" in zone:
            x = x + dx
            w = w - dx
            if w < min_w:
                x = start.x() + (start.width() - min_w)
                w = min_w
        if "right" in zone:
            w = w + dx
            if w < min_w:
                w = min_w
        if "top" in zone:
            y = y + dy
            h = h - dy
            if h < min_h:
                y = start.y() + (start.height() - min_h)
                h = min_h
        if "bottom" in zone:
            h = h + dy
            if h < min_h:
                h = min_h

        self.setGeometry(x, y, w, h)

    def _position_shared_controls(self):
        controls = self._shared_controls_widget()
        if controls is None:
            return
        target_geometry = self._shared_controls_target_geometry()
        if not target_geometry.isValid():
            return
        current_geometry = QRect(controls.geometry())
        # If user dragged/resized shared controls, do not snap back to defaults.
        if (
            self._shared_controls_auto_geometry is not None
            and current_geometry != self._shared_controls_auto_geometry
        ):
            if controls.isVisible():
                controls.raise_()
            return
        geometry_changed = current_geometry != target_geometry
        if current_geometry != target_geometry:
            controls.setGeometry(target_geometry)
        self._shared_controls_auto_geometry = QRect(controls.geometry())
        if geometry_changed:
            self._stabilize_shared_controls_layout()
        if controls.isVisible():
            controls.raise_()

    def _shared_controls_target_geometry(self) -> QRect:
        controls = self._shared_controls_widget()
        if controls is None:
            return QRect()
        width = max(1, int(self.width()))
        height = max(1, int(self.height()))
        target_width = max(460, min(1100, int(width * 0.74)))
        try:
            target_width = max(target_width, int(controls.minimum_runtime_width()))
        except Exception:
            pass
        target_width = max(1, min(width, int(target_width)))
        target_height = max(100, int(controls.sizeHint().height()))
        target_height = max(1, min(height, int(target_height)))
        x_pos = max(0, (width - target_width) // 2)
        y_pos = min(10, max(0, height - target_height))
        return QRect(x_pos, y_pos, target_width, target_height)

    def _shared_controls_detection_rect(self) -> QRect:
        controls = self._shared_controls_widget()
        if controls is None:
            return QRect()
        rect = QRect(controls.geometry())
        if rect.width() <= 1 or rect.height() <= 1:
            if self._shared_controls_auto_geometry is not None:
                rect = QRect(self._shared_controls_auto_geometry)
        if rect.width() <= 1 or rect.height() <= 1:
            rect = self._shared_controls_target_geometry()
        if rect.width() <= 0 or rect.height() <= 0:
            return QRect()
        return rect.adjusted(-20, -20, 20, 20)

    def _show_shared_controls_temporarily(self):
        controls = self._shared_controls_widget()
        if controls is None:
            return
        self._position_shared_controls()
        try:
            controls.show()
            controls.raise_()
        except Exception:
            return
        self._stabilize_shared_controls_layout()
        self._shared_controls_visible = True
        self._shared_controls_hide_timer.stop()
        self._shared_controls_hide_timer.start(800)

    def _show_shared_controls_permanent(self):
        controls = self._shared_controls_widget()
        if controls is None:
            return
        self._shared_controls_hide_timer.stop()
        self._position_shared_controls()
        try:
            controls.show()
            controls.raise_()
        except Exception:
            return
        self._stabilize_shared_controls_layout()
        self._shared_controls_visible = True

    def _hide_shared_controls(self, force: bool = False):
        controls = self._shared_controls_widget()
        if controls is None:
            return
        if not force:
            if not self._shared_controls_auto_hide:
                return
            try:
                if bool(getattr(controls, "_resizing", False)) or bool(getattr(controls, "_dragging", False)):
                    self._shared_controls_hide_timer.stop()
                    self._shared_controls_hide_timer.start(250)
                    return
            except Exception:
                pass
            if self._pointer_over_shared_controls():
                self._shared_controls_hide_timer.stop()
                self._shared_controls_hide_timer.start(250)
                return
        self._shared_controls_hide_timer.stop()
        try:
            controls.hide()
        except Exception:
            return
        self._shared_controls_visible = False
        self._shared_controls_hover_inside = False

    def _update_shared_controls_hover_from_global_pos(self, global_pos: QPoint):
        controls = self._shared_controls_widget()
        if controls is None:
            return
        if not self._both_videos_ready():
            self._hide_shared_controls(force=True)
            return
        if not self._shared_controls_auto_hide:
            if self._shared_controls_visible:
                self._position_shared_controls()
            else:
                self._show_shared_controls_permanent()
            return
        try:
            local_pos = self.mapFromGlobal(global_pos)
        except Exception:
            local_pos = QPoint(-1, -1)
        in_zone = self._shared_controls_detection_rect().contains(local_pos)
        over_controls = self._pointer_over_shared_controls()
        if in_zone or over_controls:
            self._shared_controls_hover_inside = True
            self._show_shared_controls_temporarily()
        else:
            self._shared_controls_hover_inside = False

    def _suppress_viewer_controls(self, viewer: ImageViewer):
        try:
            viewer._controls_hide_timer.stop()
        except Exception:
            pass
        try:
            viewer._controls_visible = False
        except Exception:
            pass
        controls = getattr(viewer, "video_controls", None)
        if controls is None:
            return
        try:
            controls.setVisible(False)
            controls.setEnabled(False)
            controls.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            controls.setGeometry(-10000, -10000, 1, 1)
        except Exception:
            pass

    def _update_split_layout(self):
        width = max(1, self.width())
        height = max(1, self.height())
        split_x = max(0, min(width, int(round(float(width) * float(self.split_position)))))
        has_third = self._has_third_layer()
        has_fourth = self._has_fourth_layer()
        split_y = max(0, min(height, int(round(float(height) * float(self.split_position_y)))))

        self.viewer_a.setGeometry(0, 0, width, height)
        clip_width = max(0, width - split_x)
        top_height = split_y if has_third else height
        self._viewer_b_clip.setGeometry(split_x, 0, clip_width, top_height)
        self.viewer_b.setGeometry(-split_x, 0, width, height)
        if has_third:
            bottom_height = max(0, height - split_y)
            bottom_left_width = split_x if has_fourth else width
            self._viewer_c_clip.setGeometry(0, split_y, bottom_left_width, bottom_height)
            self.viewer_c.setGeometry(0, -split_y, width, height)
        else:
            self._viewer_c_clip.setGeometry(0, 0, 0, 0)
            self.viewer_c.setGeometry(0, 0, width, height)
        if has_fourth:
            bottom_height = max(0, height - split_y)
            right_width = max(0, width - split_x)
            self._viewer_d_clip.setGeometry(split_x, split_y, right_width, bottom_height)
            self.viewer_d.setGeometry(-split_x, -split_y, width, height)
        else:
            self._viewer_d_clip.setGeometry(0, 0, 0, 0)
            self.viewer_d.setGeometry(0, 0, width, height)

        if clip_width <= 0 or top_height <= 0:
            self._viewer_b_clip.hide()
        else:
            self._viewer_b_clip.show()
            self._viewer_b_clip.raise_()
        if has_third and (height - split_y) > 0:
            self._viewer_c_clip.show()
            self._viewer_c_clip.raise_()
        else:
            self._viewer_c_clip.hide()
        if has_fourth and (height - split_y) > 0 and (width - split_x) > 0:
            self._viewer_d_clip.show()
            self._viewer_d_clip.raise_()
        else:
            self._viewer_d_clip.hide()

        if split_x <= 0 or split_x >= width:
            self._divider_widget.hide()
        else:
            divider_h = height if has_fourth else (top_height if has_third else height)
            self._divider_widget.setGeometry(max(0, split_x - 1), 0, 3, max(1, divider_h))
            self._divider_widget.show()
            self._divider_widget.raise_()
        if not has_third or split_y <= 0 or split_y >= height:
            self._divider_widget_h.hide()
        else:
            self._divider_widget_h.setGeometry(0, max(0, split_y - 1), width, 3)
            self._divider_widget_h.show()
            self._divider_widget_h.raise_()

        for viewer in self.viewers():
            self._suppress_viewer_controls(viewer)
        self._apply_video_compare_fit_mode(force=False)
        self._position_shared_controls()
        self._reposition_overlay_controls()
        self._apply_audio_focus_from_split()

    def _is_video_ready(self, viewer: ImageViewer) -> bool:
        try:
            if not bool(getattr(viewer, "_is_video_loaded", False)):
                return False
            player = getattr(viewer, "video_player", None)
            if player is None:
                return False
            return bool(getattr(player, "video_path", None))
        except Exception:
            return False

    def _both_videos_ready(self) -> bool:
        viewers = self._active_viewers()
        if len(viewers) < 2:
            return False
        return all(self._is_video_ready(viewer) for viewer in viewers)

    def _viewer_duration_ms(self, viewer: ImageViewer) -> float:
        try:
            player = viewer.video_player
            duration = float(getattr(player, "duration_ms", 0.0) or 0.0)
            if duration > 0.0:
                return duration
            fps = float(player.get_fps() or 0.0)
            frames = float(player.get_total_frames() or 0.0)
            if fps > 0.0 and frames > 0.0:
                return (frames / fps) * 1000.0
        except Exception:
            pass
        return 0.0

    def _disconnect_master_signals(self):
        if not self._master_signals_connected or self._master_viewer is None:
            self._master_signals_connected = False
            return
        try:
            player = self._master_viewer.video_player
            try:
                player.frame_changed.disconnect(self._on_master_frame_changed)
            except Exception:
                pass
            try:
                player.playback_started.disconnect(self._on_master_playback_started)
            except Exception:
                pass
            try:
                player.playback_paused.disconnect(self._on_master_playback_stopped)
            except Exception:
                pass
            try:
                player.playback_finished.disconnect(self._on_master_playback_stopped)
            except Exception:
                pass
        except Exception:
            pass
        self._master_signals_connected = False

    def _connect_master_signals(self, viewer: ImageViewer):
        self._disconnect_master_signals()
        self._master_viewer = viewer
        self._slave_viewer = self.viewer_b if viewer is self.viewer_a else self.viewer_a
        try:
            player = viewer.video_player
            player.frame_changed.connect(self._on_master_frame_changed)
            player.playback_started.connect(self._on_master_playback_started)
            player.playback_paused.connect(self._on_master_playback_stopped)
            player.playback_finished.connect(self._on_master_playback_stopped)
            self._master_signals_connected = True
        except Exception:
            self._master_signals_connected = False

    def _configure_shared_controls_for_master(self):
        master = self._master_viewer
        if master is None:
            return
        controls = self._shared_controls_widget()
        if controls is None:
            return
        try:
            player = master.video_player
        except Exception:
            return

        fps = float(player.get_fps() or 0.0)
        frame_count = int(player.get_total_frames() or 0)
        duration_s = 0.0
        duration_ms = float(getattr(player, "duration_ms", 0.0) or 0.0)
        if duration_ms > 0.0:
            duration_s = duration_ms / 1000.0
        elif fps > 0.0 and frame_count > 0:
            duration_s = float(frame_count) / fps

        controls.set_video_info(
            {
                "fps": fps,
                "frame_count": frame_count,
                "duration": duration_s,
            },
            image=None,
            proxy_model=None,
        )
        resolver = getattr(player, "resolve_exact_frame_for_marker", None)
        if hasattr(controls, "set_exact_frame_resolver"):
            controls.set_exact_frame_resolver(resolver if callable(resolver) else None)

        controls.set_playing(bool(getattr(player, "is_playing", False)))
        self._position_shared_controls()
        if self._shared_controls_auto_hide:
            self._hide_shared_controls(force=True)
        else:
            self._show_shared_controls_permanent()
        self._apply_audio_focus_from_split()

    def _select_master_viewer(self):
        candidates = self._active_viewers()
        if not candidates:
            return
        selected = max(candidates, key=self._viewer_duration_ms)
        if self._master_viewer is selected:
            return
        self._connect_master_signals(selected)
        self._configure_shared_controls_for_master()

    def _master_max_frame(self) -> int:
        controls = self._shared_controls_widget()
        if controls is None:
            return 0
        try:
            return max(0, int(controls.frame_spinbox.maximum()))
        except Exception:
            return 0

    def _frame_for_ratio(self, viewer: ImageViewer, ratio: float) -> int:
        ratio = max(0.0, min(1.0, float(ratio)))
        try:
            max_frame = max(0, int(viewer.video_player.get_total_frames() or 0) - 1)
        except Exception:
            max_frame = 0
        if max_frame <= 0:
            return 0
        return int(round(float(max_frame) * ratio))

    def _ratio_from_master_frame(self, master_frame: int) -> float:
        max_frame = self._master_max_frame()
        if max_frame <= 0:
            return 0.0
        return max(0.0, min(1.0, float(master_frame) / float(max_frame)))

    def _any_video_playing(self) -> bool:
        for viewer in self._active_viewers():
            try:
                if bool(getattr(viewer.video_player, "is_playing", False)):
                    return True
            except Exception:
                continue
        return False

    def _pause_both_players(self):
        for viewer in self._active_viewers():
            try:
                viewer.video_player.pause()
            except Exception:
                continue

    def _play_both_players(self):
        for viewer in self._active_viewers():
            try:
                viewer.video_player.play()
            except Exception:
                continue

    def _stop_video_sync(self):
        coordinator = self._sync_coordinator
        self._sync_coordinator = None
        if coordinator is not None:
            try:
                coordinator.stop()
            except Exception:
                pass

    def _schedule_auto_sync(self):
        if self._closed:
            return
        self._sync_bootstrap_attempts = 0
        if self._both_videos_ready():
            self._maybe_start_video_sync(force_restart=True)
            return
        self._sync_bootstrap_timer.start()

    def _maybe_start_video_sync(self, force_restart: bool = False):
        if self._closed:
            self._sync_bootstrap_timer.stop()
            return False
        if not self._both_videos_ready():
            self._sync_bootstrap_attempts += 1
            if self._sync_bootstrap_attempts >= 80:
                self._sync_bootstrap_timer.stop()
            return False

        self._sync_bootstrap_timer.stop()
        self._select_master_viewer()

        if self._sync_coordinator is not None and not force_restart:
            return True
        self._stop_video_sync()

        try:
            self._sync_coordinator = VideoSyncCoordinator(
                self._active_viewers(),
                parent=self,
                show_sync_icon=False,
            )
            self._sync_coordinator.start()
            self._manual_seek_active = False
            return True
        except Exception:
            self._sync_coordinator = None
            return False

    def _on_master_frame_changed(self, frame: int, time_ms: float):
        controls = self._shared_controls_widget()
        if controls is None or not controls.isVisible():
            return
        try:
            controls.update_position(int(frame), float(time_ms))
        except Exception:
            pass

    def _on_master_playback_started(self):
        controls = self._shared_controls_widget()
        if controls is None:
            return
        try:
            controls.set_playing(True)
        except Exception:
            pass

    def _on_master_playback_stopped(self):
        controls = self._shared_controls_widget()
        if controls is None:
            return
        try:
            controls.set_playing(False)
        except Exception:
            pass

    def _on_shared_seek_frame(self, master_frame: int):
        if self._master_viewer is None:
            return
        self._stop_video_sync()
        self._pause_both_players()
        self._manual_seek_active = True

        ratio = self._ratio_from_master_frame(int(master_frame))
        for viewer in self._active_viewers():
            try:
                target = self._frame_for_ratio(viewer, ratio)
                viewer.video_player.seek_to_frame(target)
            except Exception:
                continue

        try:
            master_player = self._master_viewer.video_player
            fps = float(master_player.get_fps() or 0.0)
            if fps > 0.0:
                time_ms = (float(master_frame) / fps) * 1000.0
            else:
                time_ms = float(master_frame)
            controls = self._shared_controls_widget()
            if controls is not None:
                controls.update_position(int(master_frame), float(time_ms))
                controls.set_playing(False, update_auto_play=True)
        except Exception:
            pass

    def _on_shared_skip_requested(self, *, backward: bool):
        if self._master_viewer is None:
            return
        try:
            master_player = self._master_viewer.video_player
            current_frame = int(getattr(master_player, "current_frame", 0) or 0)
            fps = float(master_player.get_fps() or 25.0)
            delta = max(1, int(round(max(1.0, fps))))
            if backward:
                target_frame = current_frame - delta
            else:
                target_frame = current_frame + delta
            target_frame = max(0, min(self._master_max_frame(), int(target_frame)))
            self._on_shared_seek_frame(target_frame)
        except Exception:
            pass

    def _on_shared_play_pause_requested(self):
        if self._master_viewer is None:
            return
        controls = self._shared_controls_widget()
        if controls is None:
            return
        if self._any_video_playing():
            self._stop_video_sync()
            self._pause_both_players()
            controls.set_playing(False, update_auto_play=True)
            return

        if self._manual_seek_active:
            self._play_both_players()
            controls.set_playing(True, update_auto_play=True)
            return

        synced = self._maybe_start_video_sync(force_restart=True)
        if not synced:
            self._play_both_players()
            controls.set_playing(True, update_auto_play=True)

    def _on_shared_stop_requested(self):
        self._stop_video_sync()
        self._manual_seek_active = False
        for viewer in self._active_viewers():
            try:
                viewer.video_player.stop()
            except Exception:
                continue
        try:
            controls = self._shared_controls_widget()
            if controls is not None:
                controls.set_playing(False, update_auto_play=True)
        except Exception:
            pass

    def _on_shared_speed_changed(self, speed: float):
        for viewer in self._active_viewers():
            try:
                viewer.video_player.set_playback_speed(float(speed))
            except Exception:
                continue

    def _on_shared_mute_toggled(self, muted: bool):
        if bool(muted):
            for viewer in self._active_viewers():
                try:
                    viewer.video_player.set_muted(True)
                except Exception:
                    continue
            return
        self._apply_audio_focus_from_split()

    def _resolve_audio_focus_viewer(self) -> tuple[str, ImageViewer]:
        split_x = max(0.0, min(1.0, float(self.split_position)))
        if not self._has_third_layer():
            if split_x > 0.5:
                return ("a", self.viewer_a)
            if split_x < 0.5:
                return ("b", self.viewer_b)
            if self._audio_focus_side == "b":
                return ("b", self.viewer_b)
            return ("a", self.viewer_a)

        split_y = max(0.0, min(1.0, float(self.split_position_y)))
        if not self._has_fourth_layer():
            areas = {
                "a": split_x * split_y,
                "b": (1.0 - split_x) * split_y,
                "c": (1.0 - split_y),
            }
        else:
            areas = {
                "a": split_x * split_y,
                "b": (1.0 - split_x) * split_y,
                "c": split_x * (1.0 - split_y),
                "d": (1.0 - split_x) * (1.0 - split_y),
            }
        best_side = max(areas, key=areas.get)
        top_two = sorted(areas.values(), reverse=True)
        if len(top_two) >= 2 and abs(top_two[0] - top_two[1]) < 1e-6:
            if self._audio_focus_side in {"a", "b", "c", "d"}:
                best_side = str(self._audio_focus_side)
        if best_side == "b":
            return ("b", self.viewer_b)
        if best_side == "c":
            return ("c", self.viewer_c)
        if best_side == "d":
            return ("d", self.viewer_d)
        return ("a", self.viewer_a)

    def _apply_audio_side(self, side: str):
        side = str(side or "a").lower()
        for key, viewer in (("a", self.viewer_a), ("b", self.viewer_b), ("c", self.viewer_c), ("d", self.viewer_d)):
            if key == "c" and not self._has_third_layer():
                continue
            if key == "d" and not self._has_fourth_layer():
                continue
            try:
                viewer.video_player.set_muted(key != side)
            except Exception:
                continue

    def _apply_audio_focus_from_split(self):
        if not self._both_videos_ready():
            return
        controls = self._shared_controls_widget()
        if controls is None:
            return
        try:
            is_muted = bool(controls.is_muted)
        except Exception:
            is_muted = True
        if is_muted:
            for viewer in self._active_viewers():
                try:
                    viewer.video_player.set_muted(True)
                except Exception:
                    continue
            self._audio_focus_side = None
            return

        # Audio focus follows the dominant side of the split.
        # 2-way: A/B by dominant width. 3/4-way: dominant quadrant/region area.
        side, _viewer = self._resolve_audio_focus_viewer()
        self._apply_audio_side(side)
        self._audio_focus_side = side

    def _event_targets_shared_controls(self, watched) -> bool:
        controls = self._shared_controls_widget()
        if controls is None:
            return False
        current = watched
        while isinstance(current, QWidget):
            if current is controls:
                return True
            current = current.parentWidget()
        return False

    def _pointer_over_shared_controls(self) -> bool:
        controls = self._shared_controls_widget()
        if controls is None or not controls.isVisible():
            return False
        try:
            global_pos = QCursor.pos()
            local = controls.mapFromGlobal(global_pos)
            return controls.rect().contains(local)
        except Exception:
            return False

    def _event_source_viewer(self, watched) -> ImageViewer | None:
        current = watched
        while isinstance(current, QWidget):
            if current is self.viewer_a:
                return self.viewer_a
            if current is self._viewer_b_clip:
                return self.viewer_b
            if current is self.viewer_b:
                return self.viewer_b
            if current is self._viewer_c_clip:
                return self.viewer_c
            if current is self.viewer_c:
                return self.viewer_c
            if current is self._viewer_d_clip:
                return self.viewer_d
            if current is self.viewer_d:
                return self.viewer_d
            current = current.parentWidget()

        for viewer in self._active_viewers():
            try:
                for surface in self._iter_video_surface_widgets(viewer):
                    if watched is surface:
                        return viewer
            except Exception:
                continue
        return None

    def _event_scene_pos(self, viewer: ImageViewer, watched, event):
        view = getattr(viewer, "view", None)
        if view is None or not hasattr(event, "position"):
            return None
        try:
            pos = event.position().toPoint()
            if watched is view.viewport():
                return view.mapToScene(pos)
            if watched is view:
                return view.mapToScene(pos)
            if watched is viewer:
                mapped = viewer.mapTo(view.viewport(), pos)
                return view.mapToScene(mapped)
            if isinstance(watched, QWidget):
                mapped = watched.mapTo(view.viewport(), pos)
                return view.mapToScene(mapped)
        except Exception:
            return None
        return None

    def _event_viewport_pos(self, viewer: ImageViewer, watched, event):
        view = getattr(viewer, "view", None)
        if view is None or not hasattr(event, "position"):
            return None
        try:
            pos = event.position().toPoint()
            if watched is view.viewport():
                return pos
            if watched is view:
                return view.viewport().mapFrom(view, pos)
            if watched is viewer:
                return viewer.mapTo(view.viewport(), pos)
            if isinstance(watched, QWidget):
                return watched.mapTo(view.viewport(), pos)
        except Exception:
            return None
        return None

    def _pan_source_for_press(self, watched, event) -> ImageViewer | None:
        try:
            if event.button() != Qt.MouseButton.LeftButton:
                return None
        except Exception:
            return None
        source_viewer = self._event_source_viewer(watched)
        if source_viewer is None:
            return None
        try:
            if not bool(source_viewer.is_content_pannable()):
                return None
        except Exception:
            return None
        return source_viewer

    def _sync_pan_state_from_source(self, source_viewer: ImageViewer):
        try:
            source_scene = source_viewer.scene.sceneRect()
            if source_scene.width() <= 0 or source_scene.height() <= 0:
                return
            source_viewport = source_viewer.view.viewport()
            source_center_scene = source_viewer.view.mapToScene(source_viewport.rect().center())
            rel_x = (float(source_center_scene.x()) - float(source_scene.left())) / float(source_scene.width())
            rel_y = (float(source_center_scene.y()) - float(source_scene.top())) / float(source_scene.height())
            rel_x = max(0.0, min(1.0, rel_x))
            rel_y = max(0.0, min(1.0, rel_y))

            for target_viewer in self._active_viewers():
                if target_viewer is source_viewer:
                    continue
                try:
                    target_scene = target_viewer.scene.sceneRect()
                    if target_scene.width() <= 0 or target_scene.height() <= 0:
                        continue
                    target_center = QPointF(
                        float(target_scene.left()) + (float(target_scene.width()) * rel_x),
                        float(target_scene.top()) + (float(target_scene.height()) * rel_y),
                    )
                    target_viewer.view.centerOn(target_center)
                    try:
                        target_viewer.video_player.sync_external_surface_geometry()
                    except Exception:
                        pass
                except Exception:
                    continue
        except Exception:
            return

    def _sync_zoom_state_from_source(self, source_viewer: ImageViewer):
        try:
            source_scene = source_viewer.scene.sceneRect()
            if source_scene.width() <= 0 or source_scene.height() <= 0:
                return

            source_viewport = source_viewer.view.viewport()
            source_center_scene = source_viewer.view.mapToScene(source_viewport.rect().center())

            rel_x = (float(source_center_scene.x()) - float(source_scene.left())) / float(source_scene.width())
            rel_y = (float(source_center_scene.y()) - float(source_scene.top())) / float(source_scene.height())
            rel_x = max(0.0, min(1.0, rel_x))
            rel_y = max(0.0, min(1.0, rel_y))

            mode = self.get_video_compare_fit_mode()
            for target_viewer in self._active_viewers():
                if target_viewer is source_viewer:
                    continue
                target_scene = target_viewer.scene.sceneRect()
                if target_scene.width() <= 0 or target_scene.height() <= 0:
                    continue

                target_focus = QPointF(
                    float(target_scene.left()) + (float(target_scene.width()) * rel_x),
                    float(target_scene.top()) + (float(target_scene.height()) * rel_y),
                )
                target_focus = QPointF(
                    max(float(target_scene.left()), min(float(target_scene.right()), float(target_focus.x()))),
                    max(float(target_scene.top()), min(float(target_scene.bottom()), float(target_focus.y()))),
                )

                if mode == COMPARE_FIT_MODE_STRETCH:
                    source_transform = source_viewer.view.transform()
                    scale_x = abs(float(source_transform.m11()))
                    scale_y = abs(float(source_transform.m22()))
                    if scale_x <= 0.0 or scale_y <= 0.0:
                        return
                    target_viewer.view.resetTransform()
                    target_viewer.view.scale(float(scale_x), float(scale_y))
                    target_viewer.view.centerOn(target_focus)
                    target_viewer.is_zoom_to_fit = bool(getattr(source_viewer, "is_zoom_to_fit", False))
                    try:
                        target_viewer.video_player.sync_external_surface_geometry()
                    except Exception:
                        pass
                    continue

                target_scale = abs(float(source_viewer.view.transform().m11()))
                if target_scale <= 0.0:
                    return

                target_viewer._apply_uniform_zoom_scale(
                    float(target_scale),
                    zoom_to_fit_state=bool(getattr(source_viewer, "is_zoom_to_fit", False)),
                    focus_scene_pos=target_focus,
                    anchor_view_pos=None,
                )
        except Exception:
            return

    def eventFilter(self, watched, event):
        event_type = event.type()
        if event_type in (QEvent.Type.MouseMove, QEvent.Type.HoverMove, QEvent.Type.Enter, QEvent.Type.HoverEnter):
            self._update_overlay_hover_from_global_pos(
                self._event_global_pos(event, watched if isinstance(watched, QWidget) else None)
            )
        elif event_type in (QEvent.Type.Leave, QEvent.Type.HoverLeave):
            self._update_overlay_hover_from_global_pos(QCursor.pos())

        if event_type == QEvent.Type.ContextMenu:
            self._show_window_menu(self._event_global_pos(event, watched if isinstance(watched, QWidget) else None))
            try:
                event.accept()
            except Exception:
                pass
            return True

        if self._event_targets_close_button(watched):
            return super().eventFilter(watched, event)
        if self._event_targets_shared_controls(watched):
            return super().eventFilter(watched, event)

        if event_type == QEvent.Type.MouseButtonDblClick:
            source_viewer = self._event_source_viewer(watched)
            if source_viewer is not None:
                try:
                    if event.button() == Qt.MouseButton.LeftButton:
                        zoom_handler = getattr(source_viewer, "apply_floating_double_click_zoom", None)
                        if callable(zoom_handler):
                            handled = bool(
                                zoom_handler(
                                    scene_anchor_pos=self._event_scene_pos(source_viewer, watched, event),
                                    view_anchor_pos=self._event_viewport_pos(source_viewer, watched, event),
                                )
                            )
                            if handled:
                                self._sync_zoom_state_from_source(source_viewer)
                                event.accept()
                                return True
                except Exception:
                    pass

        if event_type == QEvent.Type.Wheel:
            source_viewer = self._event_source_viewer(watched)
            if source_viewer is not None:
                try:
                    source_viewer.wheelEvent(event)
                except Exception:
                    pass
                self._sync_zoom_state_from_source(source_viewer)
                try:
                    event.accept()
                except Exception:
                    pass
                return True

        if (
            self._pointer_over_shared_controls()
            and not self._window_drag_active
            and not self._resize_active
            and not self._pan_sync_active
        ):
            return super().eventFilter(watched, event)

        if event_type == QEvent.Type.MouseButtonPress:
            try:
                if event.button() == Qt.MouseButton.LeftButton:
                    local_pos = self._event_local_pos(event, watched if isinstance(watched, QWidget) else None)
                    if self._close_button.isVisible() and self._close_button.geometry().contains(local_pos):
                        return super().eventFilter(watched, event)
                    zone = self._resize_zone_from_local_pos(local_pos)
                    if zone is not None:
                        self._begin_window_resize(event, zone, watched if isinstance(watched, QWidget) else None)
                        event.accept()
                        return True
                    pan_source = self._pan_source_for_press(watched, event)
                    if pan_source is not None:
                        self._pan_sync_active = True
                        self._pan_sync_source = pan_source
                        return super().eventFilter(watched, event)
                    self._begin_window_drag(event, watched if isinstance(watched, QWidget) else None)
                    event.accept()
                    return True
                elif event.button() == Qt.MouseButton.MiddleButton:
                    self._begin_window_drag(event, watched if isinstance(watched, QWidget) else None)
                    event.accept()
                    return True
                elif event.button() == Qt.MouseButton.RightButton:
                    self._show_window_menu(self._event_global_pos(event, watched if isinstance(watched, QWidget) else None))
                    event.accept()
                    return True
            except Exception:
                pass
        elif event_type == QEvent.Type.MouseMove:
            if self._resize_active:
                self._apply_window_resize(self._event_global_pos(event, watched if isinstance(watched, QWidget) else None))
                try:
                    event.accept()
                except Exception:
                    pass
                return True
            if self._window_drag_active:
                if self._is_window_drag_button_down(event):
                    global_pos = self._event_global_pos(event, watched if isinstance(watched, QWidget) else None)
                    self.move(global_pos - self._window_drag_offset)
                    try:
                        event.accept()
                    except Exception:
                        pass
                    return True
                self._end_window_drag()
            if self._pan_sync_active:
                try:
                    if not bool(event.buttons() & Qt.MouseButton.LeftButton):
                        self._pan_sync_active = False
                        self._pan_sync_source = None
                except Exception:
                    self._pan_sync_active = False
                    self._pan_sync_source = None
                result = super().eventFilter(watched, event)
                source_viewer = self._pan_sync_source or self._event_source_viewer(watched)
                if source_viewer is not None:
                    QTimer.singleShot(0, lambda sv=source_viewer: self._sync_pan_state_from_source(sv))
                return result
            self._update_split_from_global_cursor()
            try:
                local_pos = self._event_local_pos(event, watched if isinstance(watched, QWidget) else None)
                if self._close_button.isVisible() and self._close_button.geometry().contains(local_pos):
                    self._apply_resize_cursor(watched, None)
                    return super().eventFilter(watched, event)
                zone = self._resize_zone_from_local_pos(local_pos)
                self._apply_resize_cursor(watched, zone)
            except Exception:
                pass
        elif event_type == QEvent.Type.MouseButtonRelease:
            try:
                if event.button() == Qt.MouseButton.LeftButton:
                    if self._resize_active:
                        self._end_window_resize()
                        self._update_split_from_global_cursor()
                        event.accept()
                        return True
                    if self._pan_sync_active:
                        source_viewer = self._pan_sync_source or self._event_source_viewer(watched)
                        self._pan_sync_active = False
                        self._pan_sync_source = None
                        result = super().eventFilter(watched, event)
                        if source_viewer is not None:
                            QTimer.singleShot(0, lambda sv=source_viewer: self._sync_pan_state_from_source(sv))
                        self._update_split_from_global_cursor()
                        return result
                    if self._window_drag_active and self._window_drag_button == Qt.MouseButton.LeftButton:
                        self._end_window_drag()
                        self._update_split_from_global_cursor()
                        event.accept()
                        return True
                    self._update_split_from_global_cursor()
                elif self._window_drag_active and event.button() == self._window_drag_button:
                    self._end_window_drag()
                    self._update_split_from_global_cursor()
                    event.accept()
                    return True
            except Exception:
                pass
        elif event_type in (QEvent.Type.Leave, QEvent.Type.HoverLeave):
            if not self._window_drag_active and not self._resize_active and not self._pan_sync_active:
                self._apply_resize_cursor(watched, None)
            self._update_split_from_global_cursor()

        return super().eventFilter(watched, event)

    def mousePressEvent(self, event):
        if (
            self._pointer_over_shared_controls()
            and not self._window_drag_active
            and not self._resize_active
            and not self._pan_sync_active
        ):
            super().mousePressEvent(event)
            return
        if event.button() == Qt.MouseButton.LeftButton:
            local_pos = self._event_local_pos(event, self)
            if self._close_button.isVisible() and self._close_button.geometry().contains(local_pos):
                super().mousePressEvent(event)
                return
            zone = self._resize_zone_from_local_pos(local_pos)
            if zone is not None:
                self._begin_window_resize(event, zone, self)
                event.accept()
                return
            self._begin_window_drag(event, self)
            event.accept()
            return
        if event.button() == Qt.MouseButton.MiddleButton:
            self._begin_window_drag(event, self)
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            self._show_window_menu(self._event_global_pos(event, self))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (
            self._pointer_over_shared_controls()
            and not self._window_drag_active
            and not self._resize_active
            and not self._pan_sync_active
        ):
            super().mouseMoveEvent(event)
            return
        if self._resize_active:
            self._apply_window_resize(self._event_global_pos(event, self))
            event.accept()
            return
        if self._window_drag_active:
            if self._is_window_drag_button_down(event):
                self.move(self._event_global_pos(event, self) - self._window_drag_offset)
                event.accept()
                return
            self._end_window_drag()
        self._update_split_from_global_cursor()
        try:
            local_pos = self._event_local_pos(event, self)
            if self._close_button.isVisible() and self._close_button.geometry().contains(local_pos):
                self._apply_resize_cursor(self, None)
                super().mouseMoveEvent(event)
                return
            zone = self._resize_zone_from_local_pos(local_pos)
            self._apply_resize_cursor(self, zone)
        except Exception:
            pass
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._resize_active:
                self._end_window_resize()
                self._update_split_from_global_cursor()
                event.accept()
                return
            if self._pan_sync_active:
                self._pan_sync_active = False
                self._pan_sync_source = None
                self._update_split_from_global_cursor()
                super().mouseReleaseEvent(event)
                return
            if self._window_drag_active and self._window_drag_button == Qt.MouseButton.LeftButton:
                self._end_window_drag()
                self._update_split_from_global_cursor()
                event.accept()
                return
            self._update_split_from_global_cursor()
        if self._window_drag_active and event.button() == self._window_drag_button:
            self._end_window_drag()
            self._update_split_from_global_cursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        self._update_split_layout()
        self._refresh_event_filters()
        self._update_overlay_hover_from_global_pos(QCursor.pos())

    def enterEvent(self, event):
        self._update_overlay_hover_from_global_pos(QCursor.pos())
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._show_close_button(False)
        self._update_split_from_global_cursor()
        super().leaveEvent(event)

    def closeEvent(self, event):
        if self._closed:
            super().closeEvent(event)
            return
        self._closed = True
        self._refresh_filter_timer.stop()
        self._sync_bootstrap_timer.stop()
        try:
            self._shared_controls_hide_timer.stop()
        except Exception:
            pass
        try:
            self._split_cursor_sync_timer.stop()
        except Exception:
            pass
        self._stop_video_sync()
        self._disconnect_master_signals()

        for viewer in self.viewers():
            try:
                player = getattr(viewer, "video_player", None)
                if player is not None:
                    player.cleanup()
            except Exception:
                pass

        self.closing.emit()
        try:
            self.viewer_a.deleteLater()
            self.viewer_b.deleteLater()
            self.viewer_c.deleteLater()
            self.viewer_d.deleteLater()
            controls = self._shared_controls_widget()
            self._shared_controls = None
            if controls is not None:
                controls.deleteLater()
        except Exception:
            pass
        super().closeEvent(event)
