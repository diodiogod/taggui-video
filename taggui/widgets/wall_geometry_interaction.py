"""Shared manual geometry gestures for floating and comparison windows."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


class WallGeometryInteraction:
    def _wall_controller(self):
        return getattr(self.parentWidget(), '_wall_layout', None)

    def _begin_wall_geometry_gesture(self, event):
        self._wall_skip_reflow = False
        self._track_wall_geometry_gesture(event)
        controller = self._wall_controller()
        if controller is not None:
            controller.cancel()
            if (getattr(self, '_selection_masonry_wall_window', False)
                    and controller.manual_action.isChecked()):
                self._wall_skip_reflow = True

    def _track_wall_geometry_gesture(self, event=None):
        modifiers = (event.modifiers() if event is not None and hasattr(event, 'modifiers')
                     else QApplication.keyboardModifiers())
        if modifiers & Qt.KeyboardModifier.AltModifier:
            # Latch for the entire gesture, even if Alt is released first.
            self._wall_skip_reflow = True

    def _finish_wall_resize(self, previous, event=None, *, commit=True):
        self._track_wall_geometry_gesture(event)
        controller = self._wall_controller()
        if commit and controller is not None and self.geometry().size() != previous.size():
            controller.resize_finished(self, bool(getattr(self, '_wall_skip_reflow', False)))
