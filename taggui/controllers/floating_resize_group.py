"""One border gesture applies the same window dimensions to all floating viewers."""
import weakref

from PySide6.QtCore import QSize
from shiboken6 import isValid


class FloatingResizeGroup:
    def __init__(self, wall):
        self.wall = wall
        self.source = None
        self.entries = []

    def begin(self, source):
        windows = [w for w in self.wall.host._iter_rearrangeable_floating_media_windows()
                   if w.isVisible() and hasattr(w, '_capture_window_resize_state')]
        if source not in windows:
            return
        self.source = weakref.ref(source)
        for window in windows:
            if window is not source:
                window._capture_window_resize_state()
                window._set_view_resize_anchor_for_window_resize(True)
            self.entries.append((weakref.ref(window), window.geometry()))
        source._resize_group_active = True
        source._resize_group_minimum_size = QSize(
            max(10, *(w.minimumWidth() for w in windows)),
            max(10, *(w.minimumHeight() for w in windows)),
        )

    def update(self):
        source = self.source() if self.source else None
        if source is None or not isValid(source):
            return
        size = source.size()
        preserve_aspect = source._aspect_preserve_resize_active()
        for reference, original in self.entries:
            window = reference()
            if window is None or not isValid(window) or window is source or not window.isVisible():
                continue
            # Keep each sibling's position; only the dragged window follows the pointer.
            window.setGeometry(original.x(), original.y(), size.width(), size.height())
            if preserve_aspect:
                window._sync_viewer_scale_for_shift_resize(size.width(), size.height())

    def finish(self, *, commit):
        source = self.source() if self.source else None
        entries, self.entries = self.entries, []
        self.source = None
        windows = []
        changed = False
        for reference, original in entries:
            window = reference()
            if window is None or not isValid(window):
                continue
            if not commit:
                window.setGeometry(original)
                window._sync_viewer_scale_for_shift_resize(original.width(), original.height())
            elif window.isVisible():
                windows.append(window)
                changed |= window.size() != original.size()
            if window is not source:
                window._set_view_resize_anchor_for_window_resize(False)
        if source is not None and isValid(source):
            source._resize_group_active = False
            source._resize_group_minimum_size = QSize()
            if commit and changed:
                self.wall.resize_finished(source, bool(getattr(source, '_wall_skip_reflow', False)),
                                          windows=windows)
