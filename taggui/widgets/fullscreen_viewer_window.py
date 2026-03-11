"""Temporary fullscreen host for one ImageViewer."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget


class FullscreenViewerWindow(QWidget):
    """Host an existing viewer widget in a dedicated black fullscreen window."""

    closing = Signal(object)

    def __init__(self, viewer: QWidget, parent=None):
        super().__init__(parent, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.viewer = viewer
        self.setObjectName("fullscreenViewerWindow")
        self.setStyleSheet("#fullscreenViewerWindow { background-color: black; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.viewer)
        self.viewer.show()
        self.viewer.raise_()

        if hasattr(self.viewer, "view"):
            self.viewer.view.setFrameShape(QFrame.Shape.NoFrame)
            self.viewer.view.setLineWidth(0)
            self.viewer.view.setMidLineWidth(0)

    def _sync_viewer_surfaces(self):
        """Refresh geometry/controls after fullscreen host layout changes."""
        try:
            self.viewer.show()
            self.viewer.raise_()
        except Exception:
            pass
        try:
            position_controls = getattr(self.viewer, "_position_video_controls", None)
            if callable(position_controls):
                position_controls()
        except Exception:
            pass
        try:
            player = getattr(self.viewer, "video_player", None)
            if player is not None:
                player.sync_external_surface_geometry()
        except Exception:
            pass

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_viewer_surfaces()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_viewer_surfaces()

    def closeEvent(self, event):
        self.closing.emit(self.viewer)
        super().closeEvent(event)
