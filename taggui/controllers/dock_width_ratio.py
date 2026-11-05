from PySide6.QtCore import QEvent, QObject, QTimer, Qt


class DockWidthRatioController(QObject):
    """Retain the preferred dock fraction when Qt clamps a smaller window.

    Independent dock changes (splitter drags, workspace restores, zoom snaps)
    establish a new preference. Window-driven changes never do.
    """

    def __init__(self, window, dock):
        super().__init__(window)
        self.window = window
        self.dock = dock
        self._window_width = window.width()
        self._ratio = None
        self._resizing_window = False
        self.preserve_ratio = False
        self._apply_timer = QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.timeout.connect(self._apply)
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.timeout.connect(self._settled)
        window.installEventFilter(self)
        dock.installEventFilter(self)

    def _eligible(self):
        return self.dock.isVisible() and not self.dock.isFloating()

    def _remember(self):
        if self._eligible() and self.window.width() > 0:
            self._ratio = self.dock.width() / self.window.width()

    def _settled(self):
        self._resizing_window = False

    def _apply(self):
        if self._ratio is not None and self._eligible():
            self.window.resizeDocks(
                [self.dock], [round(self._ratio * self.window.width())],
                Qt.Orientation.Horizontal,
            )

    def eventFilter(self, obj, event):
        event_type = event.type()
        if obj is self.window and event_type == QEvent.Type.Resize:
            width = event.size().width()
            if width != self._window_width:
                self._window_width = width
                self._resizing_window = True
                self.preserve_ratio = self._ratio is not None
                self._apply_timer.start(0)
                self._settle_timer.start(400)
        elif obj is self.dock:
            if event_type == QEvent.Type.Show:
                self._remember()
            elif event_type == QEvent.Type.Resize:
                # Child resize events can precede the parent's resizeEvent.
                if (self.window.width() == self._window_width
                        and not self._resizing_window
                        and event.size().width() != event.oldSize().width()):
                    self.preserve_ratio = False
                    self._remember()
        return False
