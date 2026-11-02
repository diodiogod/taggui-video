"""Reserve floating-viewer border input before overlay children consume it."""
import weakref
from PySide6.QtCore import QObject, QEvent, Qt
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid


class FloatingResizeInput(QObject):
    def __init__(self, wall):
        super().__init__(wall)
        self.wall = wall
        self.active = None
        self.hover = None
        QApplication.instance().installEventFilter(self)

    def restore_cursor(self):
        if self.hover:
            ref, cursor, explicit = self.hover
            widget = ref()
            if widget is not None and isValid(widget):
                widget.setCursor(cursor) if explicit else widget.unsetCursor()
            self.hover = None

    def close(self):
        self.finish(commit=False)
        self.restore_cursor()
        QApplication.instance().removeEventFilter(self)

    def finish(self, event=None, *, commit=True):
        ref, self.active = self.active, None
        window = ref() if ref else None
        if window is not None and isValid(window):
            window._end_window_resize(event, commit=commit)
            window.releaseMouse()

    def eventFilter(self, watched, event):
        kind = event.type()
        if self.active:
            window = self.active()
            if window is None or not isValid(window):
                self.active = None
            elif kind == QEvent.MouseMove:
                window._track_wall_geometry_gesture(event)
                window._apply_corner_resize(event.globalPosition().toPoint())
                return True
            elif kind == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                self.finish(event)
                return True
            elif kind == QEvent.ApplicationDeactivate or (watched is window and kind in (QEvent.Hide, QEvent.Close, QEvent.UngrabMouse)):
                self.finish(commit=False)
        if kind == QEvent.Leave:
            self.restore_cursor()
        if kind not in (QEvent.MouseMove, QEvent.MouseButtonPress) or not isinstance(watched, QWidget):
            return False
        self.restore_cursor()
        if event.modifiers() & Qt.ControlModifier:
            return False
        window = watched
        while window is not None and not hasattr(window, '_apply_corner_resize'):
            window = window.parentWidget()
        if window is None or window._wall_controller() is not self.wall:
            return False
        if watched is getattr(window, '_close_button', None):
            return False
        zone = window._resize_zone_from_local_pos(window.mapFromGlobal(event.globalPosition().toPoint()))
        if zone is None:
            return False
        if kind == QEvent.MouseMove:
            self.hover = (weakref.ref(watched), watched.cursor(), watched.testAttribute(Qt.WA_SetCursor))
            watched.setCursor(window._cursor_for_resize_zone(zone))
        elif event.button() == Qt.LeftButton:
            window._begin_window_resize(event, zone)
            self.active = weakref.ref(window)
            window.grabMouse()
            return True
        return False
