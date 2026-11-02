"""Ctrl-drag position anchors with cancellable, geometry-only ghost previews."""
import weakref
from PySide6.QtCore import QObject, QEvent, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget, QAbstractButton, QLineEdit
from shiboken6 import isValid
from utils.latest_task import LatestTask
from widgets.floating_wall_packing import pack_wall


def calculate(payload, cancelled):
    ratios, bounds, options = payload
    return pack_wall(ratios, bounds, cancelled=cancelled, **options)


class GhostOverlay(QWidget):
    def __init__(self, host):
        super().__init__(host, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                         Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.rects, self.anchors, self.invalid = [], [], False
        self.focus_rect = None

    def paintEvent(self, event):
        painter = QPainter(self)
        origin = self.geometry().topLeft()
        for rect in self.rects:
            painter.setPen(QPen(QColor('#e16969' if self.invalid else '#81b8de'), 2, Qt.DashLine))
            painter.setBrush(QColor(180, 50, 50, 35) if self.invalid else QColor(80, 160, 210, 35))
            painter.drawRect(rect.translated(-origin).adjusted(1, 1, -2, -2))
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor('#a52b3a'), 4))
        for rect in self.anchors:
            painter.drawRect(rect.translated(-origin).adjusted(2, 2, -3, -3))
        if self.focus_rect is not None:
            painter.setPen(QPen(QColor('#efbb58'), 3, Qt.DashLine))
            painter.drawRect(self.focus_rect.translated(-origin).adjusted(2, 2, -3, -3))
        painter.end()


class WallAnchorController(QObject):
    def __init__(self, wall):
        super().__init__(wall)
        self.wall = wall
        self.drag = None
        self.overlay = GhostOverlay(wall.host)
        self.worker = LatestTask(self, name='wall-anchor-preview')
        self.worker.completed.connect(self.completed)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(70)
        self.timer.timeout.connect(self.submit)
        QApplication.instance().installEventFilter(self)

    def set_anchor(self, window, enabled):
        self.wall.cancel()
        window._wall_position_anchored = enabled
        self.wall.refresh_indicators(window)
        self.wall._refresh_menus()

    def clear(self):
        for window in self.wall.windows():
            self.set_anchor(window, False)

    def close(self):
        self.abort()
        QApplication.instance().removeEventFilter(self)
        self.worker.close()
        self.overlay.close()

    def abort(self):
        drag, self.drag = self.drag, None
        self.timer.stop()
        self.worker.cancel()
        self.overlay.hide()
        if drag:
            window = drag['source']()
            if window is not None and isValid(window):
                window.move(drag['original'].topLeft())
                window.releaseMouse()

    def begin(self, window, position):
        self.wall.cancel()
        windows = self.wall.windows()
        screen = QApplication.screenAt(window.geometry().center()) or window.screen()
        if screen is None:
            return
        gap = self.wall.host._floating_viewer_wall_gap_px()
        bounds = screen.availableGeometry().adjusted(gap, gap, -gap, -gap)
        self.drag = dict(source=weakref.ref(window), windows=[weakref.ref(w) for w in windows],
                         original=QRect(window.geometry()), offset=position-window.pos(), bounds=bounds,
                         initial=[QRect(w.geometry()) for w in windows], token=None, result=None,
                         released=False, snap=[None, None], screen=screen,
                         screen_bounds=QRect(screen.availableGeometry()))
        self.overlay.setGeometry(screen.availableGeometry())
        window.grabMouse()
        self.update(position, Qt.NoModifier)

    def update(self, position, modifiers):
        d = self.drag
        window = d['source']()
        rect = QRect(position-d['offset'], window.size())
        bounds = d['bounds']
        others = [w() for w in d['windows'] if w() is not window and w() is not None and isValid(w())
                  and getattr(w(), '_wall_position_anchored', False)]
        gap = self.wall.host._floating_viewer_wall_gap_px()
        for axis in (0, 1):
            value = rect.x() if axis == 0 else rect.y()
            size = rect.width() if axis == 0 else rect.height()
            start = bounds.x() if axis == 0 else bounds.y()
            end = bounds.right()+1 if axis == 0 else bounds.bottom()+1
            targets = [start, end-size]
            for other in others:
                r = other.geometry()
                a, b = (r.x(), r.right()+1) if axis == 0 else (r.y(), r.bottom()+1)
                targets.extend([a, b-size, a-size-gap, b+gap])
            snap = d['snap'][axis]
            if modifiers & Qt.ShiftModifier or not self.wall.setting('floating_wall_anchor_snapping'):
                snap = None
            elif snap is None or abs(value-snap) > 18:
                closest = min(targets, key=lambda t: abs(value-t))
                snap = closest if abs(value-closest) <= 10 else None
            d['snap'][axis] = snap
            value = min(max(snap if snap is not None else value, start), max(start, end-size))
            rect.moveLeft(value) if axis == 0 else rect.moveTop(value)
        if window.geometry() != rect or d['token'] is None:
            window.move(rect.topLeft())
            d['result'] = None
            self.worker.cancel()
            d['token'] = None
            if not self.timer.isActive():
                self.timer.start()
        self.overlay.anchors = [QRect(w.geometry()) for w in others] + [QRect(window.geometry())]
        self.overlay.invalid = False
        self.overlay.show()
        self.overlay.raise_()
        self.overlay.update()

    def submit(self):
        d = self.drag
        if d is None:
            return
        windows = [ref() for ref in d['windows']]
        if any(w is None or not isValid(w) or not w.isVisible() for w in windows):
            self.abort()
            return
        payload = self.wall._window_payload(windows, d['bounds'], preserve_order=False)
        source = d['source']()
        payload[2]['anchor_preview'] = True
        payload[2]['anchored_rects'] = [QRect(w.geometry()) if w is source or
            getattr(w, '_wall_position_anchored', False) else None for w in windows]
        d['submitted'] = [QRect(w.geometry()) for w in windows]
        d['token'] = self.worker.submit(calculate, payload)

    def completed(self, token, result, error):
        d = self.drag
        if d is None or token != d['token']:
            return
        windows = [ref() for ref in d['windows']]
        if (not isValid(d['screen']) or d['screen'].availableGeometry() != d['screen_bounds'] or
                windows != self.wall.windows() or any(w is None or not isValid(w) or not w.isVisible()
                or w.geometry() != r for w, r in zip(windows, d['submitted']))):
            self.abort()
            return
        valid = error is None and result is not None and len(result.rects) == len(windows)
        d['result'] = result if valid else False
        self.overlay.rects = [r for w, r in zip(windows, result.rects) if
            w is not d['source']() and not getattr(w, '_wall_position_anchored', False)] if valid else d['submitted']
        self.overlay.invalid = not valid
        self.overlay.update()
        if d['released']:
            self.finish()

    def finish(self):
        d = self.drag
        d['released'] = True
        d['source']().releaseMouse()
        if self.timer.isActive() or d['token'] is None:
            self.timer.stop()
            self.submit()
        if d['result'] is None:
            return
        if d['result'] is False:
            self.abort()
            self.wall.show_message('No room around these anchors. Try another position, smaller sizes, or unpin a window.')
            return
        windows = [ref() for ref in d['windows']]
        source, result = d['source'](), d['result']
        self.drag = None
        self.overlay.hide()
        self.wall.apply_rects(windows, result.rects)
        self.wall.last_result = result
        self.set_anchor(source, True)

    def eventFilter(self, watched, event):
        kind = event.type()
        if self.drag:
            if kind == QEvent.ShortcutOverride and event.key() == Qt.Key_Escape:
                event.accept()
                return True
            if kind == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                self.abort()
                return True
            if kind == QEvent.ApplicationDeactivate:
                self.abort()
            elif kind in (QEvent.Close, QEvent.Hide) and any(ref() is watched for ref in self.drag['windows']):
                self.abort()
            elif (kind in (QEvent.Move, QEvent.Resize) and watched is not self.drag['source']()
                  and any(ref() is watched for ref in self.drag['windows'])):
                self.abort()
            elif kind == QEvent.UngrabMouse and watched is self.drag['source']() and not self.drag['released']:
                self.abort()
            elif kind == QEvent.MouseButtonPress and self.drag['released']:
                self.abort()
                return True
            elif kind == QEvent.MouseMove and not self.drag['released']:
                self.update(event.globalPosition().toPoint(), event.modifiers())
                return True
            elif kind == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                if not self.drag['released']:
                    self.update(event.globalPosition().toPoint(), event.modifiers())
                    self.finish()
                return True
        elif (kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton
              and event.modifiers() & Qt.ControlModifier and not event.modifiers() & Qt.AltModifier
              and isinstance(watched, QWidget) and not isinstance(watched, (QAbstractButton, QLineEdit))):
            window = watched.window()
            if self.wall.setting('floating_wall_anchor_drag') and window in self.wall.windows():
                self.begin(window, event.globalPosition().toPoint())
                return True
        return False
