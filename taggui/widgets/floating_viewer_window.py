"""Frameless floating host window for spawned image viewers."""

from PySide6.QtCore import QPoint, QRect, QEvent, Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QMenu, QPushButton, QSizeGrip, QVBoxLayout, QWidget


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
        self._window_drag_offset = QPoint()
        self._active_drag_handle = None
        self._active = False
        self._close_hover_zone_px = 56
        self._drag_hover_padding_px = 10
        self._drag_handle_widgets: dict[str, QWidget] = {}
        self._drag_line_widgets: dict[str, QWidget] = {}
        self._drag_widget_to_handle: dict[QWidget, str] = {}
        self._video_controls_widget = None

        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(title)
        self.setMinimumSize(24, 24)
        self.setMouseTracking(True)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self.viewer)

        self._close_button = QPushButton("x", self)
        self._close_button.setObjectName("floatingViewerClose")
        self._close_button.setFixedSize(20, 20)
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

    def _emit_activated(self):
        self.activated.emit(self.viewer)

    def set_active(self, active: bool):
        self._active = bool(active)
        self._apply_style()

    def _apply_style(self):
        border_alpha = "180" if self._active else "130"
        self.setStyleSheet(
            f"""
            #floatingViewerClose {{
                border: 1px solid rgba(255, 255, 255, 90);
                border-radius: 4px;
                background: rgba(8, 10, 14, {border_alpha});
                color: rgba(240, 246, 252, 230);
                font-size: 12px;
                font-weight: 700;
                padding: 0px;
            }}
            #floatingViewerClose:hover {{
                background: rgba(26, 32, 40, 220);
                border: 1px solid rgba(255, 255, 255, 160);
            }}
            #floatingViewerDragZone {{
                background: transparent;
            }}
            #floatingViewerDragLine {{
                border: 1px solid rgba(0, 0, 0, 140);
                border-radius: 2px;
                background: rgba(255, 255, 255, {border_alpha});
            }}
            """
        )

    def _reposition_overlay_controls(self):
        margin = 6
        close_x = max(0, self.width() - self._close_button.width() - margin)
        close_y = min(margin, max(0, self.height() - self._close_button.height()))
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

    def eventFilter(self, watched, event):
        drag_sources = [self, self.viewer]
        if hasattr(self.viewer, "view"):
            drag_sources.append(self.viewer.view)
            drag_sources.append(self.viewer.view.viewport())
        handle_name = self._drag_widget_to_handle.get(watched)

        if handle_name is not None:
            if event.type() == QEvent.Type.ContextMenu:
                self._emit_activated()
                global_pos = event.globalPos() if hasattr(event, 'globalPos') else QCursor.pos()
                self._show_window_menu(global_pos)
                return True
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                if self._is_handle_blocked_by_controls(handle_name):
                    return True
                self._window_drag_active = True
                self._active_drag_handle = handle_name
                self._window_drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                self._emit_activated()
                return True
            if (event.type() == QEvent.Type.MouseMove and self._window_drag_active
                    and (event.buttons() & Qt.MouseButton.LeftButton)):
                self.move(event.globalPosition().toPoint() - self._window_drag_offset)
                self._update_overlay_hover_from_global_pos(event.globalPosition().toPoint())
                return True
            if event.type() == QEvent.Type.MouseButtonRelease and self._window_drag_active:
                self._window_drag_active = False
                self._active_drag_handle = None
                self._update_overlay_hover_from_global_pos(event.globalPosition().toPoint())
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
        elif watched in drag_sources:
            if event.type() == QEvent.Type.Enter:
                self._update_overlay_hover_from_global_pos(QCursor.pos())
            elif event.type() == QEvent.Type.ContextMenu:
                self._emit_activated()
                global_pos = event.globalPos() if hasattr(event, 'globalPos') else QCursor.pos()
                self._show_window_menu(global_pos)
                return True
            elif event.type() == QEvent.Type.MouseButtonPress:
                self._emit_activated()
            elif event.type() == QEvent.Type.MouseMove:
                self._update_overlay_hover_from_global_pos(event.globalPosition().toPoint())
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
