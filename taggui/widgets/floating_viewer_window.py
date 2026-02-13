"""Frameless floating host window for spawned image viewers."""

from PySide6.QtCore import QPoint, QRect, QEvent, Qt, Signal
from PySide6.QtGui import QColor, QCursor
from PySide6.QtWidgets import (QFrame, QGraphicsColorizeEffect, QMenu, QPushButton,
                               QSizeGrip, QVBoxLayout, QWidget)


class FloatingViewerWindow(QWidget):
    """Minimal floating window that hosts one ImageViewer instance."""

    activated = Signal(object)  # Emits hosted viewer
    closing = Signal(object)    # Emits hosted viewer
    sync_video_requested = Signal()
    close_all_requested = Signal()

    def __init__(self, viewer: QWidget, title: str, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.Window
            | Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint,
        )
        self.viewer = viewer
        self._window_drag_active = False
        self._window_drag_button = Qt.MouseButton.NoButton
        self._window_drag_offset = QPoint()
        self._active_drag_handle = None
        self._close_button_margin_px = 8
        self._close_button_clearance_px = 4
        self._active = False
        self._close_hover_zone_px = 56
        self._drag_hover_padding_px = 10
        self._drag_handle_widgets: dict[str, QWidget] = {}
        self._drag_line_widgets: dict[str, QWidget] = {}
        self._drag_widget_to_handle: dict[QWidget, str] = {}
        self._corner_resize_widgets: dict[str, QWidget] = {}
        self._corner_widget_to_corner: dict[QWidget, str] = {}
        self._edge_resize_widgets: dict[str, QWidget] = {}
        self._edge_widget_to_edge: dict[QWidget, str] = {}
        self._resize_active = False
        self._resize_corner = None
        self._resize_start_geometry = QRect()
        self._resize_start_global_pos = QPoint()
        self._video_controls_widget = None
        self._frozen_passthrough_mode = False
        self._colorize_effect = QGraphicsColorizeEffect(self.viewer)
        self._colorize_effect.setColor(QColor(128, 128, 128))
        self._colorize_effect.setStrength(0.0)
        self.viewer.setGraphicsEffect(self._colorize_effect)
        self._frozen_outline = QWidget(self)
        self._frozen_outline.setObjectName("floatingViewerFrozenOutline")
        self._frozen_outline.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._frozen_outline.hide()
        self._frozen_outline.raise_()

        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setObjectName("floatingViewerWindow")
        self.setWindowTitle(title)
        self.setMinimumSize(24, 24)
        self.setMouseTracking(True)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self.viewer)

        if hasattr(self.viewer, "view"):
            self.viewer.view.setFrameShape(QFrame.Shape.NoFrame)
            self.viewer.view.setLineWidth(0)
            self.viewer.view.setMidLineWidth(0)

        self._close_button = QPushButton("X", self)
        self._close_button.setObjectName("floatingViewerClose")
        self._close_button.setFixedSize(24, 24)
        self._close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_button.setToolTip("Close floating viewer")
        self._close_button.clicked.connect(self.close)
        self._close_button.hide()
        self._close_button.raise_()

        self._size_grip = QSizeGrip(self)
        self._size_grip.setFixedSize(14, 14)
        self._size_grip.setStyleSheet("QSizeGrip { background: transparent; }")
        self._size_grip.raise_()

        self._create_drag_handles()
        self._create_corner_resize_handles()
        self._create_edge_resize_handles()

        self.viewer.installEventFilter(self)
        self.installEventFilter(self)
        if hasattr(self.viewer, "view"):
            self.viewer.view.installEventFilter(self)
            self.viewer.view.viewport().installEventFilter(self)
        self._video_controls_widget = getattr(self.viewer, "video_controls", None)
        if self._video_controls_widget is not None:
            self._video_controls_widget.installEventFilter(self)
        if hasattr(self.viewer, "activated"):
            self.viewer.activated.connect(self._emit_activated)

        self._apply_style()
        self._reposition_overlay_controls()

    def _event_global_pos(self, event) -> QPoint:
        try:
            if hasattr(event, "globalPosition"):
                return event.globalPosition().toPoint()
            if hasattr(event, "globalPos"):
                return event.globalPos()
        except Exception:
            pass
        return QCursor.pos()

    def refresh_video_controls_performance_profile(self):
        """Proxy performance-profile refresh request to main window."""
        parent = self.parentWidget()
        if parent is not None and hasattr(parent, 'refresh_video_controls_performance_profile'):
            try:
                parent.refresh_video_controls_performance_profile()
            except Exception:
                pass

    def _viewer_content_is_pannable(self) -> bool:
        checker = getattr(self.viewer, "is_content_pannable", None)
        if callable(checker):
            try:
                return bool(checker())
            except Exception:
                return False
        return False

    def _uses_handle_only_window_drag(self) -> bool:
        """When pannable, image drag is reserved for panning and handles move window."""
        return self._viewer_content_is_pannable()

    def _press_hits_marking(self, watched, event) -> bool:
        view = getattr(self.viewer, "view", None)
        if view is None or not hasattr(event, "position"):
            return False
        try:
            pos = event.position().toPoint()
            if watched is view.viewport():
                scene_pos = view.mapToScene(pos)
            elif watched is view:
                scene_pos = view.mapToScene(pos)
            elif watched is self.viewer:
                mapped = self.viewer.mapTo(view.viewport(), pos)
                scene_pos = view.mapToScene(mapped)
            else:
                return False

            item = view.scene().itemAt(scene_pos, view.transform())
            if item is None:
                return False

            from widgets.marking import MarkingItem, MarkingLabel
            current = item
            while current is not None:
                if isinstance(current, (MarkingItem, MarkingLabel)):
                    return True
                current = current.parentItem()
        except Exception:
            return False
        return False

    def _event_scene_pos(self, watched, event):
        """Map mouse event position to viewer scene coordinates."""
        view = getattr(self.viewer, "view", None)
        if view is None or not hasattr(event, "position"):
            return None
        try:
            pos = event.position().toPoint()
            if watched is view.viewport():
                return view.mapToScene(pos)
            if watched is view:
                return view.mapToScene(pos)
            if watched is self.viewer:
                mapped = self.viewer.mapTo(view.viewport(), pos)
                return view.mapToScene(mapped)
        except Exception:
            return None
        return None

    def _event_viewport_pos(self, watched, event):
        """Map mouse event position to viewer viewport coordinates."""
        view = getattr(self.viewer, "view", None)
        if view is None or not hasattr(event, "position"):
            return None
        try:
            pos = event.position().toPoint()
            if watched is view.viewport():
                return pos
            if watched is view:
                return view.viewport().mapFrom(view, pos)
            if watched is self.viewer:
                return self.viewer.mapTo(view.viewport(), pos)
        except Exception:
            return None
        return None

    def _should_start_surface_window_drag(self, watched, event) -> bool:
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        if self._uses_handle_only_window_drag():
            return False

        # Keep marking interactions functional when annotations are present.
        if self._press_hits_marking(watched, event):
            return False

        try:
            view = getattr(self.viewer, "view", None)
            if view is not None and bool(getattr(view, "insertion_mode", False)):
                return False
        except Exception:
            pass

        local_pos = self.mapFromGlobal(self._event_global_pos(event))
        if self._close_button.geometry().contains(local_pos):
            return False
        return True

    def _begin_window_drag(self, event, handle_name: str | None):
        global_pos = self._event_global_pos(event)
        drag_button = Qt.MouseButton.LeftButton
        try:
            if hasattr(event, "button"):
                drag_button = event.button()
        except Exception:
            pass
        self._window_drag_active = True
        self._window_drag_button = drag_button
        self._active_drag_handle = handle_name
        self._window_drag_offset = global_pos - self.frameGeometry().topLeft()
        self._emit_activated()
        self._update_overlay_hover_from_global_pos(global_pos)

    def _is_window_drag_button_down(self, event) -> bool:
        if not self._window_drag_active or self._window_drag_button == Qt.MouseButton.NoButton:
            return False
        try:
            return bool(event.buttons() & self._window_drag_button)
        except Exception:
            return False

    def _create_drag_handles(self):
        """Create draggable edge handles used to move the floating window."""
        for name in ("top", "right", "bottom", "left"):
            zone = QWidget(self)
            zone.setObjectName("floatingViewerDragZone")
            zone.setCursor(Qt.CursorShape.SizeAllCursor)
            zone.setToolTip("Drag floating viewer")
            zone.hide()
            zone.raise_()
            zone.installEventFilter(self)

            try:
                line = QWidget(zone)
            except Exception:
                # Some PySide builds can fail constructing a QWidget with parent in one call.
                line = QWidget()
                line.setParent(zone)
            line.setObjectName("floatingViewerDragLine")
            line.installEventFilter(self)

            self._drag_handle_widgets[name] = zone
            self._drag_line_widgets[name] = line
            self._drag_widget_to_handle[zone] = name
            self._drag_widget_to_handle[line] = name

    def _create_corner_resize_handles(self):
        """Create invisible corner handles used for resize from all corners."""
        cursor_by_corner = {
            "top_left": Qt.CursorShape.SizeFDiagCursor,
            "bottom_right": Qt.CursorShape.SizeFDiagCursor,
            "top_right": Qt.CursorShape.SizeBDiagCursor,
            "bottom_left": Qt.CursorShape.SizeBDiagCursor,
        }
        for corner, cursor in cursor_by_corner.items():
            zone = QWidget(self)
            zone.setObjectName("floatingViewerResizeCorner")
            zone.setCursor(cursor)
            zone.setToolTip("Resize floating viewer")
            zone.setMouseTracking(True)
            zone.raise_()
            zone.installEventFilter(self)
            self._corner_resize_widgets[corner] = zone
            self._corner_widget_to_corner[zone] = corner

    def _create_edge_resize_handles(self):
        """Create invisible border handles used for resize from all sides."""
        cursor_by_edge = {
            "top": Qt.CursorShape.SizeVerCursor,
            "right": Qt.CursorShape.SizeHorCursor,
            "bottom": Qt.CursorShape.SizeVerCursor,
            "left": Qt.CursorShape.SizeHorCursor,
        }
        for edge, cursor in cursor_by_edge.items():
            zone = QWidget(self)
            zone.setObjectName("floatingViewerResizeEdge")
            zone.setCursor(cursor)
            zone.setToolTip("Resize floating viewer")
            zone.setMouseTracking(True)
            zone.raise_()
            zone.installEventFilter(self)
            self._edge_resize_widgets[edge] = zone
            self._edge_widget_to_edge[zone] = edge

    def _emit_activated(self):
        self.activated.emit(self.viewer)

    def _force_activate_viewer_owner(self):
        """Force main-window active viewer switch for strict single-controls mode."""
        parent = self.parentWidget()
        if parent is not None and hasattr(parent, 'set_active_viewer'):
            try:
                parent.set_active_viewer(self.viewer)
                return
            except Exception:
                pass
        self._emit_activated()

    def set_frozen_passthrough_mode(self, enabled: bool):
        """Gray out and make this floating window input-transparent."""
        enabled = bool(enabled)
        if self._frozen_passthrough_mode == enabled:
            return
        self._frozen_passthrough_mode = enabled

        opacity = 0.46 if enabled else 1.0
        self.setWindowOpacity(opacity)
        if self._colorize_effect is not None:
            self._colorize_effect.setStrength(0.55 if enabled else 0.0)

        transparent_flag = getattr(Qt.WindowType, "WindowTransparentForInput", None)
        if transparent_flag is not None:
            self.setWindowFlag(transparent_flag, enabled)
            self.show()
        else:
            # Fallback for builds without WindowTransparentForInput.
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, enabled)

        if enabled:
            self._show_close_button(False)
            self._hide_all_drag_handles()
            self._frozen_outline.show()
            self._frozen_outline.raise_()
        else:
            self._frozen_outline.hide()
        self._apply_style()

    def set_active(self, active: bool):
        self._active = bool(active)
        self._apply_style()

    def _apply_style(self):
        border_alpha = "180" if self._active else "130"
        self.setStyleSheet(
            f"""
            #floatingViewerClose {{
                border: 1px solid rgba(255, 255, 255, 110);
                border-radius: 5px;
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 rgba(44, 51, 61, {border_alpha}),
                    stop: 1 rgba(22, 28, 36, {border_alpha})
                );
                color: rgba(248, 250, 252, 245);
                font-size: 13px;
                font-weight: 800;
                padding: 0px;
                text-align: center;
            }}
            #floatingViewerClose:hover {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 rgba(255, 110, 110, 245),
                    stop: 1 rgba(214, 42, 42, 245)
                );
                border: 1px solid rgba(255, 190, 190, 235);
                color: rgba(255, 255, 255, 255);
            }}
            #floatingViewerClose:pressed {{
                background: rgba(168, 24, 24, 245);
                border: 1px solid rgba(255, 170, 170, 220);
                color: rgba(255, 245, 245, 255);
            }}
            #floatingViewerDragZone {{
                background: transparent;
            }}
            #floatingViewerDragLine {{
                border: 1px solid rgba(0, 0, 0, 140);
                border-radius: 2px;
                background: rgba(255, 255, 255, {border_alpha});
            }}
            #floatingViewerFrozenOutline {{
                border: 3px solid rgba(28, 112, 255, 255);
                background: transparent;
            }}
            """
        )

    def _reposition_overlay_controls(self):
        margin = self._close_button_margin_px
        self._frozen_outline.setGeometry(0, 0, self.width(), self.height())
        corner_size = 18
        corner_gap = self._close_button_clearance_px
        # Keep close near top-right, but slightly inset from borders.
        close_x = max(
            0,
            self.width() - self._close_button.width() - margin - max(2, corner_size // 3),
        )
        close_y = max(0, min(self.height() - self._close_button.height(), margin + max(4, corner_size // 3)))
        # If still colliding with the top-right corner resizer, nudge down just enough.
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

        available_w = max(4, self.width() - (2 * margin))
        available_h = max(4, self.height() - (2 * margin))
        handle_len_h = min(max(24, int(self.width() * 0.15)), available_w)
        handle_len_v = min(max(24, int(self.height() * 0.15)), available_h)
        handle_thickness = min(18, max(6, min(self.width(), self.height()) - 2))
        line_thickness = 4

        top_x = (self.width() - handle_len_h) // 2
        top_y = margin - 1
        top_zone = self._drag_handle_widgets["top"]
        top_zone.setGeometry(top_x, top_y, handle_len_h, handle_thickness)
        self._drag_line_widgets["top"].setGeometry(
            0,
            (handle_thickness - line_thickness) // 2,
            handle_len_h,
            line_thickness,
        )

        bottom_x = top_x
        bottom_y = self.height() - margin - handle_thickness + 1
        bottom_zone = self._drag_handle_widgets["bottom"]
        bottom_zone.setGeometry(bottom_x, bottom_y, handle_len_h, handle_thickness)
        self._drag_line_widgets["bottom"].setGeometry(
            0,
            (handle_thickness - line_thickness) // 2,
            handle_len_h,
            line_thickness,
        )

        left_x = margin - 1
        left_y = (self.height() - handle_len_v) // 2
        left_zone = self._drag_handle_widgets["left"]
        left_zone.setGeometry(left_x, left_y, handle_thickness, handle_len_v)
        self._drag_line_widgets["left"].setGeometry(
            (handle_thickness - line_thickness) // 2,
            0,
            line_thickness,
            handle_len_v,
        )

        right_x = self.width() - margin - handle_thickness + 1
        right_y = left_y
        right_zone = self._drag_handle_widgets["right"]
        right_zone.setGeometry(right_x, right_y, handle_thickness, handle_len_v)
        self._drag_line_widgets["right"].setGeometry(
            (handle_thickness - line_thickness) // 2,
            0,
            line_thickness,
            handle_len_v,
        )

        self._size_grip.move(self.width() - self._size_grip.width(), self.height() - self._size_grip.height())

        corner_size = 18
        self._corner_resize_widgets["top_left"].setGeometry(0, 0, corner_size, corner_size)
        self._corner_resize_widgets["top_right"].setGeometry(
            max(0, self.width() - corner_size),
            0,
            corner_size,
            corner_size,
        )
        self._corner_resize_widgets["bottom_left"].setGeometry(
            0,
            max(0, self.height() - corner_size),
            corner_size,
            corner_size,
        )

        edge_thickness = 5
        top_w = max(0, self.width() - (2 * corner_size))
        bottom_w = top_w
        side_h = max(0, self.height() - (2 * corner_size))
        self._edge_resize_widgets["top"].setGeometry(corner_size, 0, top_w, edge_thickness)
        self._edge_resize_widgets["bottom"].setGeometry(
            corner_size,
            max(0, self.height() - edge_thickness),
            bottom_w,
            edge_thickness,
        )
        self._edge_resize_widgets["left"].setGeometry(0, corner_size, edge_thickness, side_h)
        self._edge_resize_widgets["right"].setGeometry(
            max(0, self.width() - edge_thickness),
            corner_size,
            edge_thickness,
            side_h,
        )
        self._corner_resize_widgets["bottom_right"].setGeometry(
            max(0, self.width() - corner_size),
            max(0, self.height() - corner_size),
            corner_size,
            corner_size,
        )
        self._close_button.raise_()

    def _show_close_button(self, visible: bool):
        if visible:
            self._close_button.show()
        else:
            self._close_button.hide()

    def _get_controls_rect_in_window(self) -> QRect | None:
        """Get current video-controls rect mapped to floating-window coordinates."""
        controls = getattr(self, "_video_controls_widget", None)
        if controls is None:
            return None
        try:
            if not controls.isVisible():
                return None
            top_left = controls.mapTo(self, QPoint(0, 0))
            return QRect(top_left, controls.size())
        except RuntimeError:
            return None

    def _is_handle_blocked_by_controls(self, handle_name: str) -> bool:
        """Handle must stay hidden when video controls overlap its area."""
        controls_rect = self._get_controls_rect_in_window()
        if controls_rect is None:
            return False
        zone = self._drag_handle_widgets.get(handle_name)
        if zone is None:
            return False
        return zone.geometry().intersects(controls_rect)

    def _show_drag_handle(self, handle_name: str, visible: bool):
        zone = self._drag_handle_widgets.get(handle_name)
        if zone is None:
            return
        if not self._uses_handle_only_window_drag():
            zone.hide()
            return
        if visible and not self._is_handle_blocked_by_controls(handle_name):
            zone.show()
        else:
            zone.hide()

    def _hide_all_drag_handles(self):
        for zone in self._drag_handle_widgets.values():
            zone.hide()

    def _is_in_close_hover_zone(self, local_pos: QPoint) -> bool:
        if local_pos.x() < 0 or local_pos.y() < 0:
            return False
        if local_pos.x() >= self.width() or local_pos.y() >= self.height():
            return False
        zone = self._close_hover_zone_px
        return local_pos.x() >= (self.width() - zone) and local_pos.y() <= zone

    def _hovered_drag_handles(self, local_pos: QPoint) -> set[str]:
        """Return edge handles hovered by cursor (excluding control-overlapped handles)."""
        hovered = set()
        if not self._uses_handle_only_window_drag():
            return hovered
        if local_pos.x() < 0 or local_pos.y() < 0:
            return hovered
        if local_pos.x() >= self.width() or local_pos.y() >= self.height():
            return hovered

        for name, zone in self._drag_handle_widgets.items():
            if self._is_handle_blocked_by_controls(name):
                continue
            hover_rect = zone.geometry().adjusted(
                -self._drag_hover_padding_px,
                -self._drag_hover_padding_px,
                self._drag_hover_padding_px,
                self._drag_hover_padding_px,
            )
            if hover_rect.contains(local_pos):
                hovered.add(name)
        return hovered

    def _update_overlay_hover_from_global_pos(self, global_pos: QPoint):
        local_pos = self.mapFromGlobal(global_pos)
        self._show_close_button(self._is_in_close_hover_zone(local_pos))
        if not self._uses_handle_only_window_drag():
            self._hide_all_drag_handles()
            return
        hovered_handles = self._hovered_drag_handles(local_pos)
        for name in self._drag_handle_widgets:
            should_show = (
                (self._window_drag_active and name == self._active_drag_handle)
                or (name in hovered_handles)
            )
            self._show_drag_handle(name, should_show)

    def _show_window_menu(self, global_pos: QPoint):
        menu = QMenu(self)
        sync_action = menu.addAction("Sync video")
        close_all_action = menu.addAction("Close all spawned viewers")
        selected = menu.exec(global_pos)
        if selected is sync_action:
            self.sync_video_requested.emit()
        elif selected is close_all_action:
            self.close_all_requested.emit()

    def _apply_corner_resize(self, global_pos: QPoint):
        if not self._resize_active or not self._resize_corner:
            return
        start = self._resize_start_geometry
        if not start.isValid():
            return

        dx = global_pos.x() - self._resize_start_global_pos.x()
        dy = global_pos.y() - self._resize_start_global_pos.y()

        x = start.x()
        y = start.y()
        w = start.width()
        h = start.height()

        min_w = max(10, self.minimumWidth())
        min_h = max(10, self.minimumHeight())

        if self._resize_corner in ("top_left", "bottom_left", "left"):
            new_w = max(min_w, w - dx)
            x = x + (w - new_w)
            w = new_w
        elif self._resize_corner in ("top_right", "bottom_right", "right"):
            w = max(min_w, w + dx)

        if self._resize_corner in ("top_left", "top_right", "top"):
            new_h = max(min_h, h - dy)
            y = y + (h - new_h)
            h = new_h
        elif self._resize_corner in ("bottom_left", "bottom_right", "bottom"):
            h = max(min_h, h + dy)

        self.setGeometry(x, y, w, h)

    def eventFilter(self, watched, event):
        drag_sources = [self, self.viewer]
        if hasattr(self.viewer, "view"):
            drag_sources.append(self.viewer.view)
            drag_sources.append(self.viewer.view.viewport())
        edge_name = self._edge_widget_to_edge.get(watched)
        corner_name = self._corner_widget_to_corner.get(watched)
        handle_name = self._drag_widget_to_handle.get(watched)

        if edge_name is not None:
            if event.type() == QEvent.Type.ContextMenu:
                self._emit_activated()
                global_pos = event.globalPos() if hasattr(event, 'globalPos') else QCursor.pos()
                self._show_window_menu(global_pos)
                return True
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._resize_active = True
                self._resize_corner = edge_name
                self._resize_start_geometry = self.geometry()
                self._resize_start_global_pos = self._event_global_pos(event)
                self._window_drag_active = False
                self._window_drag_button = Qt.MouseButton.NoButton
                self._active_drag_handle = None
                self._emit_activated()
                return True
            if event.type() == QEvent.Type.MouseMove and self._resize_active:
                self._apply_corner_resize(self._event_global_pos(event))
                return True
            if event.type() == QEvent.Type.MouseButtonRelease and self._resize_active:
                self._resize_active = False
                self._resize_corner = None
                self._update_overlay_hover_from_global_pos(self._event_global_pos(event))
                return True
            if event.type() == QEvent.Type.Enter:
                self._emit_activated()
            if event.type() == QEvent.Type.Leave:
                self._update_overlay_hover_from_global_pos(QCursor.pos())
        elif corner_name is not None:
            if event.type() == QEvent.Type.ContextMenu:
                self._emit_activated()
                global_pos = event.globalPos() if hasattr(event, 'globalPos') else QCursor.pos()
                self._show_window_menu(global_pos)
                return True
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._resize_active = True
                self._resize_corner = corner_name
                self._resize_start_geometry = self.geometry()
                self._resize_start_global_pos = self._event_global_pos(event)
                self._window_drag_active = False
                self._window_drag_button = Qt.MouseButton.NoButton
                self._active_drag_handle = None
                self._emit_activated()
                return True
            if event.type() == QEvent.Type.MouseMove and self._resize_active:
                self._apply_corner_resize(self._event_global_pos(event))
                return True
            if event.type() == QEvent.Type.MouseButtonRelease and self._resize_active:
                self._resize_active = False
                self._resize_corner = None
                self._update_overlay_hover_from_global_pos(self._event_global_pos(event))
                return True
            if event.type() == QEvent.Type.Enter:
                self._emit_activated()
            if event.type() == QEvent.Type.Leave:
                self._update_overlay_hover_from_global_pos(QCursor.pos())
        elif handle_name is not None:
            if event.type() == QEvent.Type.ContextMenu:
                self._emit_activated()
                global_pos = event.globalPos() if hasattr(event, 'globalPos') else QCursor.pos()
                self._show_window_menu(global_pos)
                return True
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                if not self._uses_handle_only_window_drag():
                    return True
                if self._is_handle_blocked_by_controls(handle_name):
                    return True
                self._begin_window_drag(event, handle_name)
                return True
            if (event.type() == QEvent.Type.MouseMove and self._is_window_drag_button_down(event)):
                global_pos = self._event_global_pos(event)
                self.move(global_pos - self._window_drag_offset)
                self._update_overlay_hover_from_global_pos(global_pos)
                return True
            if (
                event.type() == QEvent.Type.MouseButtonRelease
                and self._window_drag_active
                and event.button() == self._window_drag_button
            ):
                self._window_drag_active = False
                self._window_drag_button = Qt.MouseButton.NoButton
                self._active_drag_handle = None
                self._update_overlay_hover_from_global_pos(self._event_global_pos(event))
                return True
            if event.type() == QEvent.Type.Enter:
                self._show_drag_handle(handle_name, True)
            if event.type() == QEvent.Type.Leave:
                self._update_overlay_hover_from_global_pos(QCursor.pos())
        elif watched is getattr(self, "_video_controls_widget", None):
            if event.type() in (
                QEvent.Type.Move,
                QEvent.Type.Resize,
                QEvent.Type.Show,
                QEvent.Type.Hide,
            ):
                self._update_overlay_hover_from_global_pos(QCursor.pos())
            elif event.type() == QEvent.Type.MouseButtonPress:
                self._emit_activated()
            elif event.type() == QEvent.Type.MouseMove:
                # Keep ownership switching click-free when hovering controls.
                self._force_activate_viewer_owner()
        elif watched in drag_sources:
            if event.type() == QEvent.Type.Enter:
                self._update_overlay_hover_from_global_pos(QCursor.pos())
            elif event.type() == QEvent.Type.MouseButtonDblClick:
                self._emit_activated()
                if event.button() == Qt.MouseButton.LeftButton:
                    if self._press_hits_marking(watched, event):
                        return False
                    zoom_handler = getattr(self.viewer, "apply_floating_double_click_zoom", None)
                    if callable(zoom_handler):
                        handled = False
                        scene_anchor = self._event_scene_pos(watched, event)
                        view_anchor = self._event_viewport_pos(watched, event)
                        try:
                            handled = bool(
                                zoom_handler(
                                    scene_anchor_pos=scene_anchor,
                                    view_anchor_pos=view_anchor,
                                )
                            )
                        except Exception:
                            handled = False
                        if handled:
                            self._update_overlay_hover_from_global_pos(self._event_global_pos(event))
                            return True
            elif event.type() == QEvent.Type.ContextMenu:
                self._emit_activated()
                global_pos = event.globalPos() if hasattr(event, 'globalPos') else QCursor.pos()
                self._show_window_menu(global_pos)
                return True
            elif event.type() == QEvent.Type.MouseButtonPress:
                self._emit_activated()
                if event.button() == Qt.MouseButton.MiddleButton:
                    self._begin_window_drag(event, None)
                    return True
                if self._should_start_surface_window_drag(watched, event):
                    self._begin_window_drag(event, None)
                    return True
            elif event.type() == QEvent.Type.MouseMove:
                # Force handoff on hover even if child event propagation differs.
                if self._video_controls_widget is not None:
                    try:
                        if self._video_controls_widget.geometry().adjusted(-20, -20, 20, 20).contains(
                            self.viewer.mapFromGlobal(self._event_global_pos(event))
                        ):
                            self._force_activate_viewer_owner()
                    except Exception:
                        pass
                if self._is_window_drag_button_down(event):
                    global_pos = self._event_global_pos(event)
                    self.move(global_pos - self._window_drag_offset)
                    self._update_overlay_hover_from_global_pos(global_pos)
                    return True
                self._update_overlay_hover_from_global_pos(self._event_global_pos(event))
            elif event.type() == QEvent.Type.MouseButtonRelease:
                if self._window_drag_active and event.button() == self._window_drag_button:
                    self._window_drag_active = False
                    self._window_drag_button = Qt.MouseButton.NoButton
                    self._active_drag_handle = None
                    self._update_overlay_hover_from_global_pos(self._event_global_pos(event))
                    return True
            elif event.type() == QEvent.Type.FocusIn:
                self._emit_activated()
        elif watched is self and event.type() == QEvent.Type.WindowActivate:
            self._emit_activated()

        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        self._reposition_overlay_controls()
        self._update_overlay_hover_from_global_pos(QCursor.pos())
        super().resizeEvent(event)

    def enterEvent(self, event):
        self._update_overlay_hover_from_global_pos(QCursor.pos())
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._show_close_button(False)
        if not self._window_drag_active:
            self._hide_all_drag_handles()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        self._emit_activated()
        super().mousePressEvent(event)

    def focusInEvent(self, event):
        self._emit_activated()
        super().focusInEvent(event)

    def closeEvent(self, event):
        self.closing.emit(self.viewer)
        super().closeEvent(event)
