"""Discreet corner buttons for releasing individual wall constraints."""
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton


class WallConstraintIndicator(QAbstractButton):
    def __init__(self, parent, *, size_lock=False):
        super().__init__(parent)
        self.size_lock = size_lock
        self.setFixedSize(18, 18)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self._hovered = False
        parent.installEventFilter(self)
        self.setAttribute(Qt.WA_NoSystemBackground)
        action = 'Release kept size (allow resizing)' if size_lock else 'Unpin position (allow repositioning)'
        self.setAccessibleName(action)
        self.setToolTip(action)

    def eventFilter(self, watched, event):
        if watched is self.parentWidget() and event.type() == QEvent.Resize:
            self.move(self.x(), max(14, watched.height() - self.height() - 14))
        return False

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        bright = self._hovered or self.hasFocus() or self.isDown()
        ink = QColor(255, 255, 255, 255 if bright else 145)
        shadow = QColor(0, 0, 0, 130 if bright else 65)
        path = QPainterPath()
        if self.size_lock:
            path.addEllipse(QPointF(9, 3.5), 1.6, 1.6)
            path.moveTo(9, 5.2)
            path.lineTo(9, 15.5)
            path.moveTo(5.5, 7)
            path.lineTo(12.5, 7)
            path.moveTo(3, 10)
            path.cubicTo(3, 13.8, 6, 15.5, 9, 15.5)
            path.cubicTo(12, 15.5, 15, 13.8, 15, 10)
            path.moveTo(3, 10)
            path.lineTo(2, 12)
            path.moveTo(3, 10)
            path.lineTo(5, 11)
            path.moveTo(15, 10)
            path.lineTo(13, 11)
            path.moveTo(15, 10)
            path.lineTo(16, 12)
            points = [path.pointAtPercent(path.percentAtLength(i * 2.3))
                      for i in range(int(path.length() / 2.3) + 1)]
            for color, width in ((shadow, 2.7), (ink, 1.35)):
                painter.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap))
                painter.drawPoints(points)
        else:
            painter.translate(9, 9)
            painter.rotate(30)
            painter.translate(-9, -9)
            path.moveTo(6, 2.5)
            path.lineTo(12, 2.5)
            path.lineTo(11, 7.5)
            path.lineTo(13, 10)
            path.lineTo(5, 10)
            path.lineTo(7, 7.5)
            path.closeSubpath()
            path.moveTo(9, 10)
            path.lineTo(9, 16)
            for color, width in ((shadow, 2.7), (ink, 1.2)):
                painter.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                painter.drawPath(path)
        painter.end()
