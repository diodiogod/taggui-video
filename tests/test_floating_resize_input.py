"""Cursor ownership around floating-window resize borders."""
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QWidget

from controllers.floating_resize_input import FloatingResizeInput
from qt_test_helpers import dispose_widget


class ResizeWindow(QWidget):
    def __init__(self, wall):
        super().__init__()
        self.wall = wall
        self.resize(200, 100)

    def _wall_controller(self):
        return self.wall

    def _apply_corner_resize(self, _position):
        pass

    def _resize_zone_from_local_pos(self, position):
        return 'right' if position.x() >= self.width() - 12 else None

    def _cursor_for_resize_zone(self, _zone):
        return Qt.SizeHorCursor


class MouseTarget(QWidget):
    def mouseMoveEvent(self, event):
        event.accept()


def test_resize_cursor_is_stable_and_restores_the_original(monkeypatch):
    wall = QObject()
    window = ResizeWindow(wall)
    target = MouseTarget(window)
    target.setGeometry(window.rect())
    target.setMouseTracking(True)
    target.setCursor(Qt.CrossCursor)
    dialog = QWidget(window, Qt.Dialog)
    unrelated = QWidget()
    resize_input = FloatingResizeInput(wall)
    changes = []
    original_set = target.setCursor
    original_unset = target.unsetCursor
    monkeypatch.setattr(target, 'setCursor', lambda cursor: (changes.append('set'), original_set(cursor)))
    monkeypatch.setattr(target, 'unsetCursor', lambda: (changes.append('unset'), original_unset()))

    def move(widget, position):
        point = QPointF(position)
        global_point = QPointF(widget.mapToGlobal(position))
        event = QMouseEvent(QEvent.MouseMove, point, global_point,
                            Qt.NoButton, Qt.NoButton, Qt.NoModifier)
        QApplication.sendEvent(widget, event)

    try:
        move(target, QPoint(195, 50))
        for x in (196, 197, 198):
            move(target, QPoint(x, 50))
        assert target.cursor().shape() == Qt.SizeHorCursor
        assert changes == ['set']

        # An unrelated widget leaving does not own the saved cursor.
        QApplication.sendEvent(unrelated, QEvent(QEvent.Leave))
        assert target.cursor().shape() == Qt.SizeHorCursor
        assert changes == ['set']

        move(target, QPoint(100, 50))
        assert target.cursor().shape() == Qt.CrossCursor
        assert changes == ['set', 'set']

        move(target, QPoint(195, 50))
        move(dialog, QPoint(195, 50))
        assert target.cursor().shape() == Qt.CrossCursor
        assert dialog.cursor().shape() != Qt.SizeHorCursor
    finally:
        resize_input.close()
        dispose_widget(dialog)
        dispose_widget(window)
        dispose_widget(unrelated)
