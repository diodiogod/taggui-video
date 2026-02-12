"""Frameless floating host window for spawned image viewers."""

from PySide6.QtCore import QPoint, QEvent, Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QMenu, QPushButton, QSizeGrip, QVBoxLayout, QWidget


class FloatingViewerWindow(QWidget):
    """Minimal floating window that hosts one ImageViewer instance."""

    activated = Signal(object)  # Emits hosted viewer
    closing = Signal(object)    # Emits hosted viewer
    sync_video_requested = Signal()

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
        self._active = False
        self._close_hover_zone_px = 56
        self._drag_hover_zone_height = 40

        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(title)
        self.setMinimumSize(320, 220)
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

        self._drag_handle_zone = QWidget(self)
        self._drag_handle_zone.setObjectName("floatingViewerDragZone")
        self._drag_handle_zone.setCursor(Qt.CursorShape.SizeAllCursor)
        self._drag_handle_zone.setToolTip("Drag floating viewer")
        self._drag_handle_zone.hide()
        self._drag_handle_zone.raise_()

        self._drag_handle_line = QWidget(self._drag_handle_zone)
        self._drag_handle_line.setObjectName("floatingViewerDragLine")

        self.viewer.installEventFilter(self)
        self.installEventFilter(self)
        if hasattr(self.viewer, "view"):
            self.viewer.view.installEventFilter(self)
            self.viewer.view.viewport().installEventFilter(self)
        self._drag_handle_zone.installEventFilter(self)
        self._drag_handle_line.installEventFilter(self)
        if hasattr(self.viewer, "activated"):
            self.viewer.activated.connect(self._emit_activated)

        self._apply_style()
        self._reposition_overlay_controls()

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
        self._close_button.move(self.width() - self._close_button.width() - margin, margin)
        handle_w = max(42, int(self.width() * 0.15))
        handle_h = 18
        handle_x = (self.width() - handle_w) // 2
        self._drag_handle_zone.setGeometry(handle_x, margin - 1, handle_w, handle_h)
        line_h = 4
        line_y = (handle_h - line_h) // 2
        self._drag_handle_line.setGeometry(0, line_y, handle_w, line_h)
        self._size_grip.move(self.width() - self._size_grip.width(), self.height() - self._size_grip.height())

    def _show_close_button(self, visible: bool):
        if visible:
            self._close_button.show()
        else:
            self._close_button.hide()

    def _show_drag_handle(self, visible: bool):
        if visible:
            self._drag_handle_zone.show()
        else:
            self._drag_handle_zone.hide()

    def _is_in_close_hover_zone(self, local_pos: QPoint) -> bool:
        if local_pos.x() < 0 or local_pos.y() < 0:
            return False
        if local_pos.x() >= self.width() or local_pos.y() >= self.height():
            return False
        zone = self._close_hover_zone_px
        return local_pos.x() >= (self.width() - zone) and local_pos.y() <= zone

    def _is_in_drag_hover_zone(self, local_pos: QPoint) -> bool:
        if local_pos.x() < 0 or local_pos.y() < 0:
            return False
        if local_pos.x() >= self.width() or local_pos.y() >= self.height():
            return False
        center_x = self.width() // 2
        half_width = max(1, self._drag_handle_zone.width() // 2)
        return (
            abs(local_pos.x() - center_x) <= half_width
            and local_pos.y() <= self._drag_hover_zone_height
        )

    def _update_overlay_hover_from_global_pos(self, global_pos: QPoint):
        local_pos = self.mapFromGlobal(global_pos)
        self._show_close_button(self._is_in_close_hover_zone(local_pos))
        self._show_drag_handle(
            self._window_drag_active or self._is_in_drag_hover_zone(local_pos)
        )

    def _show_window_menu(self, global_pos: QPoint):
        menu = QMenu(self)
        sync_action = menu.addAction("Sync video")
        selected = menu.exec(global_pos)
        if selected is sync_action:
            self.sync_video_requested.emit()

    def eventFilter(self, watched, event):
        drag_sources = [self, self.viewer]
        if hasattr(self.viewer, "view"):
            drag_sources.append(self.viewer.view)
            drag_sources.append(self.viewer.view.viewport())

        if watched in (self._drag_handle_zone, self._drag_handle_line):
            if event.type() == QEvent.Type.ContextMenu:
                self._emit_activated()
                global_pos = event.globalPos() if hasattr(event, 'globalPos') else QCursor.pos()
                self._show_window_menu(global_pos)
                return True
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._window_drag_active = True
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
                self._update_overlay_hover_from_global_pos(event.globalPosition().toPoint())
                return True
            if event.type() == QEvent.Type.Enter:
                self._show_drag_handle(True)
            if event.type() == QEvent.Type.Leave:
                self._update_overlay_hover_from_global_pos(QCursor.pos())
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
            self._show_drag_handle(False)
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
