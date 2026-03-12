"""Visual crop hints/guides HUD for marking operations."""

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Slot
from PySide6.QtGui import QColor, QFont, QPainterPath, QPen
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
        self.setCacheMode(QGraphicsItem.CacheMode.NoCache)
        self.setZValue(6)
        self.last_point: QPointF | float = QPointF(-1, -1)
        self.last_pos = RectPosition.NONE
        self.has_crop = False  # Track if there's an active crop marking

    def shape(self):
        """Return empty path so this item is never hit by mouse events.

        This makes the HUD completely transparent to mouse clicks - scene().itemAt()
        will never return this item, allowing clicks to pass through to items below.
        """
        return QPainterPath()  # Empty path = not hit-testable

    @Slot(QRectF, RectPosition)
    def setValues(self, rect: QRectF, pos: RectPosition):
        normalized_rect = QRectF(rect).normalized()
        if self.rect == normalized_rect and self.last_pos == pos and self.has_crop:
            return

        rect_change = self.rect != normalized_rect
        self.rect = normalized_rect
        self.has_crop = True  # A crop exists if setValues is called
        # Don't hide the HUD itself - just update visibility of guide lines via pos
        pos_change = self.last_pos != pos
        force_rebuild = bool(pos_change or rect_change)
        self.last_pos = pos

        self.path_ar = QPainterPath()
        self.path_size = QPainterPath()
        do_update = False

        if pos == RectPosition.TL:
            do_update = self.add_hyperbola_limit(self.rect.bottomRight(), -1, -1, force_rebuild)
        elif pos == RectPosition.TOP:
            do_update = self.add_line_limit_lr(self.rect.bottom(), -1, force_rebuild)
        elif pos == RectPosition.TR:
            do_update = self.add_hyperbola_limit(self.rect.bottomLeft(), 1, -1, force_rebuild)
        elif pos == RectPosition.RIGHT:
            do_update = self.add_line_limit_td(self.rect.x(), 1, force_rebuild)
        elif pos == RectPosition.BR:
            do_update = self.add_hyperbola_limit(self.rect.topLeft(), 1, 1, force_rebuild)
        elif pos == RectPosition.BOTTOM:
            do_update = self.add_line_limit_lr(self.rect.y(), 1, force_rebuild)
        elif pos == RectPosition.BL:
            do_update = self.add_hyperbola_limit(self.rect.topRight(), -1, 1, force_rebuild)
        elif pos == RectPosition.LEFT:
            do_update = self.add_line_limit_td(self.rect.right(), -1, force_rebuild)
        else:
            self.last_point = QPointF(-1, -1)

        if do_update or force_rebuild:
            self.update()

    def set_crop_rect(self, rect: QRectF):
        self.setValues(QRectF(rect), RectPosition.NONE)

    def clear_crop(self):
        self.rect = QRectF(0, 0, 1, 1)
        self.path_ar = QPainterPath()
        self.path_size = QPainterPath()
        self.last_point = QPointF(-1, -1)
        self.last_pos = RectPosition.NONE
        self.has_crop = False
        self.update()

    def add_line_limit_td(self, x: float, lr: int, force_rebuild: bool) -> bool:
        if self.last_point == x and not force_rebuild:
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
        self.last_point = x
        return True

    def add_line_limit_lr(self, y: float, td: int, force_rebuild: bool) -> bool:
        if self.last_point == y and not force_rebuild:
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
        self.last_point = y
        return True

    def add_hyperbola_limit(self, pos: QPointF, lr: int, td: int, force_rebuild: bool) -> bool:
        if self.last_point == pos and not force_rebuild:
            return False
        target_area = max(settings.value('export_resolution', type=int)**2, 1)
        res_size = max(settings.value('export_bucket_res_size', type=int), 1)
        if td < 0:
            divisor = pos.y() - self._boundingRect.y()
            if divisor == 0:
                return False
            distance_x = target_area / divisor
        else:
            divisor = self._boundingRect.bottom() - pos.y()
            if divisor == 0:
                return False
            distance_x = target_area / divisor
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
        self.last_point = pos
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
        painter.save()
        clip_path = QPainterPath()
        clip_path.addRect(self._boundingRect)
        painter.setClipPath(clip_path)

        painter.setBrush(Qt.NoBrush)
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

        # Display current crop resolution and aspect ratio (only when crop marking exists)
        if self.has_crop and self.rect.width() > 0 and self.rect.height() > 0:
            # Calculate actual aspect ratio
            rect_aspect = self.rect.width() / self.rect.height()

            # Format: (width, height, numeric_ratio, "display_name")
            aspect_ratios = [
                (1, 1, 1.0, "1:1"),
                (6, 5, 1.2, "6:5"),
                (4, 3, 1.333, "4:3"),
                (3, 2, 1.5, "3:2"),
                (16, 9, 1.778, "16:9"),
                (2, 1, 2.0, "2:1"),
                (3, 1, 3.0, "3:1"),
                (4, 1, 4.0, "4:1"),
                (5, 6, 0.833, "5:6"),
                (3, 4, 0.75, "3:4"),
                (2, 3, 0.667, "2:3"),
                (9, 16, 0.5625, "9:16"),
                (1, 2, 0.5, "1:2"),
                (1, 3, 0.333, "1:3"),
                (1, 4, 0.25, "1:4"),
            ]

            # Find nearest standard ratio
            nearest_ar = min(aspect_ratios,
                            key=lambda ar: abs(ar[2] - rect_aspect))

            # If very close to a standard ratio (within 1%), use the standard name
            # Otherwise show the actual calculated ratio
            if abs(nearest_ar[2] - rect_aspect) < 0.01:
                ar_name = nearest_ar[3]
            else:
                # Show actual ratio as decimal
                ar_name = f"{rect_aspect:.2f}:1" if rect_aspect >= 1 else f"1:{1/rect_aspect:.2f}"

            text = f"{int(self.rect.width())}x{int(self.rect.height())} ({ar_name})"

            # Set up font
            font = QFont("Arial", max(12, int(14 / self.zoom_factor)))
            font.setBold(True)
            painter.setFont(font)

            # Position text at top-left of crop rect with some padding
            text_pos = QPointF(self.rect.x() + 10 / self.zoom_factor,
                              self.rect.y() + 20 / self.zoom_factor)

            # Draw text with white outline for visibility
            painter.setPen(QPen(QColor(255, 255, 255), 3 / self.zoom_factor))
            painter.drawText(text_pos, text)
            painter.setPen(QPen(QColor(0, 0, 0), 1 / self.zoom_factor))
            painter.drawText(text_pos, text)
        painter.restore()
