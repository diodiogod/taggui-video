"""Top-level visual feedback for compare drag hover/hold states."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class CompareDropFeedbackOverlay(QWidget):
    """Transparent top-level overlay that paints target-border feedback."""

    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._target_rect_local = QRect()
        self._state = "none"
        self._progress = 0.0
        self._margin_px = 8
        self.hide()

    def hide_feedback(self):
        self._state = "none"
        self._progress = 0.0
        self._target_rect_local = QRect()
        self.hide()

    def show_feedback(self, target_global_rect: QRect, *, state: str, progress: float):
        if target_global_rect is None or not target_global_rect.isValid():
            self.hide_feedback()
            return

        margin = int(self._margin_px)
        framed = QRect(target_global_rect)
        framed.adjust(-margin, -margin, margin, margin)
        self.setGeometry(framed)
        self._target_rect_local = QRect(margin, margin, target_global_rect.width(), target_global_rect.height())
        self._state = str(state or "none")
        self._progress = max(0.0, min(1.0, float(progress)))
        self.show()
        self.raise_()
        self.update()

    def _state_color(self) -> QColor:
        if self._state == "blocked":
            return QColor(255, 78, 78, 255)
        if self._state == "ready":
            return QColor(88, 255, 170, 255)
        return QColor(64, 220, 255, 255)

    def _draw_progress_border(self, painter: QPainter, rect: QRect, ratio: float, color: QColor):
        ratio = max(0.0, min(1.0, ratio))
        if ratio <= 0.0:
            return

        x1 = float(rect.left())
        y1 = float(rect.top())
        x2 = float(rect.right())
        y2 = float(rect.bottom())
        width = max(0.0, x2 - x1)
        height = max(0.0, y2 - y1)
        perimeter = max(1.0, (2.0 * width) + (2.0 * height))
        remain = perimeter * ratio

        def draw_segment(start: QPointF, end: QPointF):
            nonlocal remain
            if remain <= 0.0:
                return
            length = abs(end.x() - start.x()) + abs(end.y() - start.y())
            if length <= 0.0:
                return
            if remain >= length:
                painter.drawLine(start, end)
                remain -= length
                return
            t = remain / length
            mid = QPointF(
                start.x() + ((end.x() - start.x()) * t),
                start.y() + ((end.y() - start.y()) * t),
            )
            painter.drawLine(start, mid)
            remain = 0.0

        glow_pen = QPen(QColor(color.red(), color.green(), color.blue(), 205), 12.0)
        glow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        glow_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(glow_pen)

        p1 = QPointF(x1, y1)
        p2 = QPointF(x2, y1)
        p3 = QPointF(x2, y2)
        p4 = QPointF(x1, y2)
        draw_segment(p1, p2)
        draw_segment(p2, p3)
        draw_segment(p3, p4)
        draw_segment(p4, p1)

        remain = perimeter * ratio
        neon_pen = QPen(QColor(color.red(), color.green(), color.blue(), 255), 5.4)
        neon_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        neon_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(neon_pen)

        draw_segment(p1, p2)
        draw_segment(p2, p3)
        draw_segment(p3, p4)
        draw_segment(p4, p1)

        remain = perimeter * ratio
        core_pen = QPen(QColor(255, 255, 255, 250), 1.8)
        core_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        core_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(core_pen)

        draw_segment(p1, p2)
        draw_segment(p2, p3)
        draw_segment(p3, p4)
        draw_segment(p4, p1)

    def paintEvent(self, event):
        if self._state == "none" or not self._target_rect_local.isValid():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self._target_rect_local.adjusted(1, 1, -1, -1)
        base = self._state_color()

        # Soft pulse background.
        fill_alpha = 54 if self._state != "blocked" else 64
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(base.red(), base.green(), base.blue(), fill_alpha))
        painter.drawRoundedRect(rect, 10, 10)

        # Outer halo + base border.
        halo_pen = QPen(QColor(base.red(), base.green(), base.blue(), 92), 7.5)
        painter.setPen(halo_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 10, 10)

        base_pen = QPen(QColor(base.red(), base.green(), base.blue(), 188), 2.8)
        painter.setPen(base_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 10, 10)

        # Progress border "takes over" as hold progresses.
        self._draw_progress_border(
            painter,
            rect,
            self._progress,
            QColor(base.red(), base.green(), base.blue(), 255),
        )

        if self._state == "ready":
            ready_pen = QPen(QColor(255, 255, 255, 240), 1.7)
            painter.setPen(ready_pen)
            painter.drawRoundedRect(rect.adjusted(3, 3, -3, -3), 8, 8)
