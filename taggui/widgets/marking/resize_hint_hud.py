"""Visual crop hints/guides HUD for marking operations."""

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Slot
from PySide6.QtGui import QColor, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem

from utils.settings import settings
import utils.target_dimension as target_dimension
from utils.rect import RectPosition


class ResizeHintHUD(QGraphicsItem):
    """Heads-up display showing crop size hints and aspect ratio guides."""

    zoom_factor = 1.0

    def __init__(self, boundingRect: QRect, parent=None):
        super().__init__(parent)
        self._boundingRect = boundingRect
        self.rect = QRectF(0, 0, 1, 1)
        self.path_ar = QPainterPath()
        self.path_size = QPainterPath()
        self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)
        self.setZValue(3)
        self.last_point: QPointF | float = QPointF(-1, -1)
        self.last_pos = RectPosition.NONE

    def shape(self):
        """Return empty path so this item is never hit by mouse events.

        This makes the HUD completely transparent to mouse clicks - scene().itemAt()
        will never return this item, allowing clicks to pass through to items below.
        """
        return QPainterPath()  # Empty path = not hit-testable

    @Slot(QRectF, RectPosition)
    def setValues(self, rect: QRectF, pos: RectPosition):
        if self.rect == rect and self.isVisible() == (pos != RectPosition.NONE):
            return

        self.rect = rect
        self.setVisible(pos != RectPosition.NONE)
        pos_change = self.last_pos != pos
        self.last_pos = pos

        self.path_ar = QPainterPath()
        self.path_size = QPainterPath()
        do_update = False

        if pos == RectPosition.TL:
            do_update = self.add_hyperbola_limit(self.rect.bottomRight(), -1, -1, pos_change)
        elif pos == RectPosition.TOP:
            do_update = self.add_line_limit_lr(self.rect.bottom(), -1, pos_change)
        elif pos == RectPosition.TR:
            do_update = self.add_hyperbola_limit(self.rect.bottomLeft(), 1, -1, pos_change)
        elif pos == RectPosition.RIGHT:
            do_update = self.add_line_limit_td(self.rect.x(), 1, pos_change)
        elif pos == RectPosition.BR:
            do_update = self.add_hyperbola_limit(self.rect.topLeft(), 1, 1, pos_change)
        elif pos == RectPosition.BOTTOM:
            do_update = self.add_line_limit_lr(self.rect.y(), 1, pos_change)
        elif pos == RectPosition.BL:
            do_update = self.add_hyperbola_limit(self.rect.topRight(), -1, 1, pos_change)
        elif pos == RectPosition.LEFT:
            do_update = self.add_line_limit_td(self.rect.right(), -1, pos_change)

        if do_update:
            self.update()

    def add_line_limit_td(self, x: float, lr: int, pos_change: bool) -> bool:
        if self.last_point == x and not pos_change:
            return False
        width = settings.value('export_resolution', type=int)**2 / self.rect.height()
        res_size = max(settings.value('export_bucket_res_size', type=int), 1)
        self.path_size.moveTo(x + lr * width, self.rect.y()                     )
        self.path_size.lineTo(x + lr * width, self.rect.y() + self.rect.height())

        for ar in target_dimension.get_preferred_sizes():
            s = max(res_size / ar[0], res_size / ar[1])
            f = max(self._boundingRect.width() / ar[0],
                    self._boundingRect.height() / ar[1], 2)
            self.path_ar.moveTo(x + lr * ar[0] * s, self.rect.y()      + ar[1] * s)
            self.path_ar.lineTo(x + lr * ar[0] * f, self.rect.y()      + ar[1] * f)
            self.path_ar.moveTo(x + lr * ar[0] * s, self.rect.bottom() - ar[1] * s)
            self.path_ar.lineTo(x + lr * ar[0] * f, self.rect.bottom() - ar[1] * f)
        self.last_pos = x
        return True

    def add_line_limit_lr(self, y: float, td: int, pos_change: bool) -> bool:
        if self.last_point == y and not pos_change:
            return False
        height = settings.value('export_resolution', type=int)**2 / self.rect.width()
        res_size = max(settings.value('export_bucket_res_size', type=int), 1)
        self.path_size.moveTo(self.rect.x(),                     y + td * height)
        self.path_size.lineTo(self.rect.x() + self.rect.width(), y + td * height)

        for ar in target_dimension.get_preferred_sizes():
            s = max(res_size / ar[0], res_size / ar[1])
            f = max(self._boundingRect.width() / ar[0],
                    self._boundingRect.height() / ar[1], 2)
            self.path_ar.moveTo(self.rect.x()     + ar[0] * s, y + td * ar[1] * s)
            self.path_ar.lineTo(self.rect.x()     + ar[0] * f, y + td * ar[1] * f)
            self.path_ar.moveTo(self.rect.right() - ar[0] * s, y + td * ar[1] * s)
            self.path_ar.lineTo(self.rect.right() - ar[0] * f, y + td * ar[1] * f)
        self.last_pos = y
        return True

    def add_hyperbola_limit(self, pos: QPointF, lr: int, td: int, pos_change: bool) -> bool:
        if self.last_point == pos and not pos_change:
            return False
        target_area = max(settings.value('export_resolution', type=int)**2, 1)
        res_size = max(settings.value('export_bucket_res_size', type=int), 1)
        if td < 0:
            distance_x = target_area / (pos.y() - self._boundingRect.y())
        else:
            distance_x = target_area / (self._boundingRect.bottom() - pos.y())
        x = self._boundingRect.x() if lr < 0 else pos.x() + distance_x
        end_x = pos.x() - distance_x if lr < 0 else self._boundingRect.right()
        first = True
        while x < end_x + 50:
            p = QPointF(x, pos.y() + td * target_area / (lr * (x - pos.x())))
            self.path_size.moveTo(p) if first else self.path_size.lineTo(p)
            first = False
            x += 50

        for ar in target_dimension.get_preferred_sizes():
            s = max(res_size / ar[0], res_size / ar[1])
            f = max(self._boundingRect.width() / ar[0],
                    self._boundingRect.height() / ar[1], 2)
            self.path_ar.moveTo(pos.x() + lr * ar[0] * s, pos.y() + td * ar[1] * s)
            self.path_ar.lineTo(pos.x() + lr * ar[0] * f, pos.y() + td * ar[1] * f)
        self.last_pos = pos
        return True

    def boundingRect(self):
        return self._boundingRect

    def shape(self):
        """Return empty path so this item is never hit by mouse events.

        This makes the HUD completely transparent to mouse clicks - scene().itemAt()
        will never return this item, allowing clicks to pass through to items below.
        """
        return QPainterPath()  # Empty path = not hit-testable

    def paint(self, painter, option, widget=None):
        clip_path = QPainterPath()
        clip_path.addRect(self._boundingRect)
        painter.setClipPath(clip_path)
        pen = QPen(QColor(255, 255, 255, 127), 3 / self.zoom_factor)
        painter.setPen(pen)
        painter.drawPath(self.path_size)
        painter.drawPath(self.path_ar)
        pen = QPen(QColor(0, 255, 0), 1 / self.zoom_factor)
        painter.setPen(pen)
        painter.drawPath(self.path_size)
        pen = QPen(QColor(0, 0, 0), 1 / self.zoom_factor)
        painter.setPen(pen)
        painter.drawPath(self.path_ar)
