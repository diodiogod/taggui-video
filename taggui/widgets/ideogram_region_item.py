"""Interactive graphics item for Ideogram structured-caption regions."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QBrush, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsRectItem, QMenu


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
        on_type_change=None,
    ):
        super().__init__(rect)
        self.element_index = element_index
        self._on_selected = on_selected
        self._on_geometry_changed = on_geometry_changed
        self._on_type_change = on_type_change
        self._resizing = False
        self._label_item = None
        self._base_color = QColor(color)
        self._press_pos = QPointF()
        self._start_rect = QRectF(rect)
        self._start_item_pos = QPointF()
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges,
            True,
        )
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        pen = QPen(color, 2)
        pen.setCosmetic(True)
        pen.setStyle(Qt.PenStyle.DashLine)
        self.setPen(pen)
        fill = QColor(color)
        fill.setAlpha(34)
        self.setBrush(QBrush(fill))
        self.setZValue(30)

    def set_highlighted(self, highlighted: bool):
        pen = QPen(self._base_color, 4 if highlighted else 2)
        pen.setCosmetic(True)
        pen.setStyle(Qt.PenStyle.SolidLine if highlighted else Qt.PenStyle.DashLine)
        self.setPen(pen)
        fill = QColor(self._base_color)
        fill.setAlpha(58 if highlighted else 34)
        self.setBrush(QBrush(fill))

    def _handle_rect(self) -> QRectF:
        rect = self.rect()
        size = self.HANDLE_SIZE
        scene = self.scene()
        if scene is not None and scene.views():
            scale = abs(scene.views()[0].transform().m11())
            if scale > 0:
                size = self.HANDLE_SIZE / scale
        size = min(size, rect.width(), rect.height())
        return QRectF(
            rect.right() - size,
            rect.bottom() - size,
            size,
            size,
        )

    def set_label_item(self, label_item):
        self._label_item = label_item
        self._relayout_label()

    def _relayout_label(self):
        if self._label_item is not None:
            self._label_item.set_anchor_rect(
                self.mapRectToScene(self.rect())
            )

    def hoverMoveEvent(self, event):
        self.setCursor(
            Qt.CursorShape.SizeFDiagCursor
            if self._handle_rect().contains(event.pos())
            else Qt.CursorShape.SizeAllCursor
        )
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event):
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        super().hoverLeaveEvent(event)

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
        self._relayout_label()
        event.accept()

    def mouseReleaseEvent(self, event):
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self._relayout_label()
        scene_rect = self.mapRectToScene(self.rect()).normalized()
        self._on_geometry_changed(self.element_index, scene_rect)
        event.accept()

    def contextMenuEvent(self, event):
        if self._on_type_change is None:
            event.ignore()
            return
        self._on_selected(self.element_index)
        self.setSelected(True)
        menu = QMenu()
        object_action = menu.addAction('Convert to Object region')
        text_action = menu.addAction('Convert to Text region')
        chosen = menu.exec(event.screenPos())
        if chosen is object_action:
            self._on_type_change(self.element_index, 'obj')
        elif chosen is text_action:
            self._on_type_change(self.element_index, 'text')
        event.accept()

    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.pen().color())
        painter.drawRect(self._handle_rect())
