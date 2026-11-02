"""Geometry-only resize previews using the same constraints as release reflow."""
import weakref
from PySide6.QtCore import QObject, QTimer, QRect
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid
from utils.latest_task import LatestTask
from controllers.wall_anchor_controller import GhostOverlay, calculate


class WallResizePreview(QObject):
    def __init__(self, wall):
        super().__init__(wall)
        self.wall = wall
        self.source = None
        self.pending = None
        self.overlay = GhostOverlay(wall.host)
        self.worker = LatestTask(self, name='wall-resize-preview')
        self.worker.completed.connect(self.completed)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(70)
        self.timer.timeout.connect(self.submit)

    def cancel(self):
        self.source = self.pending = None
        self.timer.stop()
        self.worker.cancel()
        self.overlay.hide()

    def close(self):
        self.cancel()
        self.worker.close()
        self.overlay.close()

    def update(self, source):
        if (not getattr(source, '_resize_active', False)
                or not getattr(source, '_selection_masonry_wall_window', False)
                or getattr(source, '_wall_skip_reflow', False)
                or not self.wall.automatic_layout_enabled
                or not self.wall.setting('floating_wall_resize_preview')):
            self.cancel()
            return
        self.source = weakref.ref(source)
        self.pending = None
        self.worker.cancel()
        if not self.timer.isActive():
            self.timer.start()

    def submit(self):
        source = self.source() if self.source else None
        if source is None or not isValid(source) or not source._resize_active:
            self.cancel()
            return
        windows = self.wall.windows()
        if source not in windows:
            self.cancel()
            return
        preserve = self.wall.host._floating_viewer_rearrange_preserve_screen_order()
        if preserve:
            windows.sort(key=self.wall.host._window_screen_order_sort_key)
        screen = QApplication.screenAt(source.geometry().center()) or source.screen()
        if screen is None:
            return
        gap = self.wall.host._floating_viewer_wall_gap_px()
        screen_bounds = QRect(screen.availableGeometry())
        payload = self.wall._window_payload(windows, screen_bounds.adjusted(gap,gap,-gap,-gap), preserve_order=preserve)
        # Predict resize_finished without mutating the saved size during a gesture.
        if (getattr(source, '_wall_size_lock_kind', None) == 'explicit'
                or self.wall.setting('floating_wall_preserve_manual_sizes')):
            payload[2]['fixed_sizes'][windows.index(source)] = (source.width(), source.height())
        token = self.worker.submit(calculate, payload)
        self.pending = (token, [(weakref.ref(w), QRect(w.geometry())) for w in windows],
                        weakref.ref(screen), screen_bounds)

    def completed(self, token, result, error):
        pending = self.pending
        source = self.source() if self.source else None
        if pending is None or token != pending[0] or source is None or not isValid(source):
            return
        _, entries, screen_ref, bounds = pending
        screen = screen_ref()
        windows = [ref() for ref, _ in entries]
        if (not source._resize_active or getattr(source, '_wall_skip_reflow', False)
                or screen is None or not isValid(screen) or screen.availableGeometry() != bounds
                or any(w is None or not isValid(w) or not w.isVisible() or w.geometry() != r
                       for w, (_, r) in zip(windows, entries))
                or set(windows) != set(self.wall.windows())):
            self.cancel()
            return
        valid = error is None and result is not None and len(result.rects) == len(windows)
        self.overlay.setGeometry(bounds)
        self.overlay.rects = result.rects if valid else [r for _, r in entries]
        self.overlay.focus_rect = result.rects[windows.index(source)] if valid else QRect(source.geometry())
        self.overlay.anchors = [QRect(w.geometry()) for w in windows if getattr(w, '_wall_position_anchored', False)]
        self.overlay.invalid = not valid
        self.overlay.show()
        self.overlay.raise_()
        self.overlay.update()
