"""Interactive graphics item for Ideogram structured-caption regions."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QBrush, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsRectItem


class IdeogramRegionItem(QGraphicsRectItem):
    """Movable region with a bottom-right resize handle."""

    HANDLE_SIZE = 12.0

    def __init__(
        self,
        rect: QRectF,
        *,
        element_index: int,
        color: QColor,
        on_selected,
        on_geometry_changed,
    ):
        super().__init__(rect)
        self.element_index = element_index
        self._on_selected = on_selected
        self._on_geometry_changed = on_geometry_changed
        self._resizing = False
        self._press_pos = QPointF()
        self._start_rect = QRectF(rect)
        self._start_item_pos = QPointF()
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges,
            True,
        )
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        pen = QPen(color, 2)
        pen.setCosmetic(True)
        pen.setStyle(Qt.PenStyle.DashLine)
        self.setPen(pen)
        fill = QColor(color)
        fill.setAlpha(34)
        self.setBrush(QBrush(fill))
        self.setZValue(30)

    def _handle_rect(self) -> QRectF:
        rect = self.rect()
        size = self.HANDLE_SIZE
        return QRectF(
            rect.right() - size,
            rect.bottom() - size,
            size,
            size,
        )

    def mousePressEvent(self, event):
        self._on_selected(self.element_index)
        self._press_pos = event.scenePos()
        self._start_rect = QRectF(self.rect())
        self._start_item_pos = QPointF(self.pos())
        self._resizing = self._handle_rect().contains(event.pos())
        self.setCursor(
            Qt.CursorShape.SizeFDiagCursor
            if self._resizing
            else Qt.CursorShape.ClosedHandCursor
        )
        event.accept()

    def mouseMoveEvent(self, event):
        delta = event.scenePos() - self._press_pos
        if self._resizing:
            width = max(2.0, self._start_rect.width() + delta.x())
            height = max(2.0, self._start_rect.height() + delta.y())
            self.setRect(
                QRectF(
                    self._start_rect.topLeft(),
                    self._start_rect.topLeft() + QPointF(width, height),
                )
            )
        else:
            self.setPos(self._start_item_pos + delta)
        event.accept()

    def mouseReleaseEvent(self, event):
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        scene_rect = self.mapRectToScene(self.rect()).normalized()
        self._on_geometry_changed(self.element_index, scene_rect)
        event.accept()

    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.pen().color())
        painter.drawRect(self._handle_rect())
