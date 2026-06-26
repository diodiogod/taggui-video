"""Interactive graphics item for Ideogram structured-caption regions."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QBrush, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsRectItem, QMenu

from utils.rect import RectPosition, change_rectF, map_rect_position_to_cursor
from utils.settings import DEFAULT_SETTINGS, settings


class IdeogramRegionItem(QGraphicsRectItem):
    """Movable region with resize handles on every edge and corner."""

    HANDLE_SIZE = 16.0
    PALETTE_STRIP_SIZE = 22.0
    MIN_SIZE = 2.0

    def __init__(
        self,
        rect: QRectF,
        *,
        element_index: int,
        color: QColor,
        on_selected,
        on_geometry_changed,
        on_type_change=None,
        on_palette_color_selected=None,
        palette_colors=None,
    ):
        super().__init__(rect)
        self.element_index = element_index
        self._on_selected = on_selected
        self._on_geometry_changed = on_geometry_changed
        self._on_type_change = on_type_change
        self._on_palette_color_selected = on_palette_color_selected
        self._drag_handle = RectPosition.NONE
        self._label_item = None
        self._base_color = QColor(color)
        self._palette_colors = [
            QColor(palette_color)
            for palette_color in (palette_colors or [])
            if QColor(palette_color).isValid()
        ]
        self._press_pos = QPointF()
        self._start_rect = QRectF(rect)
        self._start_item_pos = QPointF()
        self._drag_moved = False
        self._group_start_rects: dict["IdeogramRegionItem", QRectF] = {}
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

    def boundingRect(self) -> QRectF:
        # Keep this stable across zoom changes; Qt can crash if boundingRect()
        # changes dynamically without prepareGeometryChange().
        outset = self.HANDLE_SIZE
        return super().boundingRect().adjusted(-outset, -outset, outset, outset)

    def set_highlighted(self, highlighted: bool):
        pen = QPen(self._base_color, 4 if highlighted else 2)
        pen.setCosmetic(True)
        pen.setStyle(Qt.PenStyle.SolidLine if highlighted else Qt.PenStyle.DashLine)
        self.setPen(pen)
        fill = QColor(self._base_color)
        fill.setAlpha(58 if highlighted else 34)
        self.setBrush(QBrush(fill))

    def _scaled_handle_size(self) -> float:
        rect = self.rect()
        size = self.HANDLE_SIZE
        scene = self.scene()
        if scene is not None and scene.views():
            scale = abs(scene.views()[0].transform().m11())
            if scale > 0:
                size = self.HANDLE_SIZE / scale
        return max(1.0, min(size, rect.width(), rect.height()))

    def _grab_band_size(self) -> float:
        size = self.HANDLE_SIZE
        scene = self.scene()
        if scene is not None and scene.views():
            scale = abs(scene.views()[0].transform().m11())
            if scale > 0:
                size = self.HANDLE_SIZE / scale
        return max(3.0, size)

    def _handle_rects(self) -> dict[RectPosition, QRectF]:
        rect = self.rect()
        size = self._grab_band_size()
        half = size * 0.5
        handle_rects = {
            RectPosition.TL: QRectF(
                rect.left() - half,
                rect.top() - half,
                size,
                size,
            ),
            RectPosition.TR: QRectF(
                rect.right() - half,
                rect.top() - half,
                size,
                size,
            ),
            RectPosition.BR: QRectF(
                rect.right() - half,
                rect.bottom() - half,
                size,
                size,
            ),
            RectPosition.BL: QRectF(
                rect.left() - half,
                rect.bottom() - half,
                size,
                size,
            ),
            RectPosition.TOP: QRectF(
                rect.left() + half,
                rect.top() - half,
                max(0.0, rect.width() - size),
                size,
            ),
            RectPosition.RIGHT: QRectF(
                rect.right() - half,
                rect.top() + half,
                size,
                max(0.0, rect.height() - size),
            ),
            RectPosition.BOTTOM: QRectF(
                rect.left() + half,
                rect.bottom() - half,
                max(0.0, rect.width() - size),
                size,
            ),
            RectPosition.LEFT: QRectF(
                rect.left() - half,
                rect.top() + half,
                size,
                max(0.0, rect.height() - size),
            ),
            RectPosition.CENTER: QRectF(
                rect.left() + half,
                rect.top() + half,
                max(0.0, rect.width() - size),
                max(0.0, rect.height() - size),
            ),
        }
        return handle_rects

    def _palette_strip_height(self) -> float:
        if not self._palette_colors:
            return 0.0
        size = self.PALETTE_STRIP_SIZE
        scene = self.scene()
        if scene is not None and scene.views():
            scale = abs(scene.views()[0].transform().m11())
            if scale > 0:
                size = self.PALETTE_STRIP_SIZE / scale
        return min(max(3.0, size), max(1.0, self.rect().height()))

    def _palette_index_at(self, point: QPointF) -> int | None:
        if not self._palette_colors:
            return None
        rect = self.rect()
        if (
            point.y() < rect.top()
            or point.y() > rect.top() + self._palette_strip_height()
            or point.x() < rect.left()
            or point.x() > rect.right()
        ):
            return None
        strip_width = rect.width() / len(self._palette_colors)
        if strip_width <= 0:
            return None
        return max(
            0,
            min(
                len(self._palette_colors) - 1,
                int((point.x() - rect.left()) / strip_width),
            ),
        )

    def _palette_hex_at(self, index: int) -> str | None:
        if index < 0 or index >= len(self._palette_colors):
            return None
        color = self._palette_colors[index]
        return f"#{color.red():02X}{color.green():02X}{color.blue():02X}"

    @staticmethod
    def _configured_border_width() -> float:
        return max(
            0.75,
            float(
                settings.value(
                    'ideogram_overlay_border_px',
                    defaultValue=DEFAULT_SETTINGS['ideogram_overlay_border_px'],
                    type=int,
                )
            ),
        )

    @staticmethod
    def _configured_halo_width() -> float:
        return max(
            0.0,
            float(
                settings.value(
                    'ideogram_overlay_line_halo_px',
                    defaultValue=DEFAULT_SETTINGS['ideogram_overlay_line_halo_px'],
                    type=int,
                )
            ),
        )

    @staticmethod
    def _configured_halo_alpha() -> int:
        return max(
            0,
            min(
                255,
                int(
                    settings.value(
                        'ideogram_overlay_line_halo_alpha',
                        defaultValue=DEFAULT_SETTINGS['ideogram_overlay_line_halo_alpha'],
                        type=int,
                    )
                ),
            ),
        )

    @classmethod
    def _contrast_halo_color(cls, accent: QColor) -> QColor:
        base = QColor('#FFFFFF' if accent.lightness() < 128 else '#05070A')
        base.setAlpha(cls._configured_halo_alpha())
        return base

    @staticmethod
    def _configured_halo_color() -> QColor:
        color = QColor(
            str(
                settings.value(
                    'ideogram_overlay_line_halo_color',
                    defaultValue=DEFAULT_SETTINGS['ideogram_overlay_line_halo_color'],
                    type=str,
                )
                or DEFAULT_SETTINGS['ideogram_overlay_line_halo_color']
            )
        )
        color.setAlpha(IdeogramRegionItem._configured_halo_alpha())
        return color

    def _cursor_at(self, point: QPointF):
        handle = self._handle_at(point)
        if handle not in (RectPosition.NONE, RectPosition.CENTER):
            return map_rect_position_to_cursor(handle)
        if self._palette_index_at(point) is not None:
            return Qt.CursorShape.PointingHandCursor
        return map_rect_position_to_cursor(handle)

    def _handle_at(self, point: QPointF) -> RectPosition:
        for position, handle_rect in self._handle_rects().items():
            if position == RectPosition.CENTER:
                continue
            if handle_rect.contains(point):
                return position
        center_rect = self._handle_rects().get(RectPosition.CENTER)
        if center_rect is not None and center_rect.contains(point):
            return RectPosition.CENTER
        if self.rect().contains(point):
            return RectPosition.CENTER
        return RectPosition.NONE

    def scene_rect(self) -> QRectF:
        return self.mapRectToScene(self.rect()).normalized()

    def set_scene_rect(self, rect: QRectF):
        self.setPos(0, 0)
        self.setRect(QRectF(rect).normalized())
        self._relayout_label()

    def set_label_item(self, label_item):
        self._label_item = label_item
        self._relayout_label()

    def _relayout_label(self):
        if self._label_item is not None:
            self._label_item.set_anchor_rect(
                self.mapRectToScene(self.rect())
            )

    def hoverMoveEvent(self, event):
        cursor = self._cursor_at(event.pos())
        self.setCursor(cursor or Qt.CursorShape.SizeAllCursor)
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event):
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        scene = self.scene()
        if scene is not None and scene.views():
            scene.views()[0].setFocus(Qt.FocusReason.MouseFocusReason)
        additive = bool(
            event.modifiers()
            & (
                Qt.KeyboardModifier.ControlModifier
                | Qt.KeyboardModifier.ShiftModifier
                | Qt.KeyboardModifier.MetaModifier
            )
        )
        if not additive and self.scene() is not None:
            for item in self.scene().selectedItems():
                if isinstance(item, IdeogramRegionItem) and item is not self:
                    item.setSelected(False)
        self._on_selected(self.element_index)
        press_handle = self._handle_at(event.pos())
        palette_index = (
            self._palette_index_at(event.pos())
            if press_handle in (RectPosition.NONE, RectPosition.CENTER)
            else None
        )
        if (
            palette_index is not None
            and callable(self._on_palette_color_selected)
        ):
            color = self._palette_hex_at(palette_index)
            if color is not None:
                self._on_palette_color_selected(self.element_index, color)
                self.setSelected(True)
                event.accept()
                return
        if additive and self.isSelected():
            self.setSelected(False)
            self._group_start_rects = {}
            event.accept()
            return
        self.setSelected(True)
        self._press_pos = event.scenePos()
        self._start_rect = QRectF(self.rect())
        self._start_item_pos = QPointF(self.pos())
        self._drag_moved = False
        self._drag_handle = press_handle
        self._group_start_rects = self._selected_region_rects()
        cursor = self._cursor_at(event.pos())
        self.setCursor(cursor or Qt.CursorShape.ClosedHandCursor)
        event.accept()

    def mouseMoveEvent(self, event):
        delta = event.scenePos() - self._press_pos
        if abs(delta.x()) > 0.5 or abs(delta.y()) > 0.5:
            self._drag_moved = True
        if self._drag_handle == RectPosition.CENTER:
            if len(self._group_start_rects) > 1:
                for item, start_rect in self._group_start_rects.items():
                    item.set_scene_rect(start_rect.translated(delta))
            else:
                self.setPos(self._start_item_pos + delta)
        elif self._drag_handle != RectPosition.NONE:
            if len(self._group_start_rects) > 1:
                active_start = self._group_start_rects.get(
                    self,
                    self.mapRectToScene(self._start_rect).normalized(),
                )
                active_new = change_rectF(
                    QRectF(active_start),
                    self._drag_handle,
                    event.scenePos(),
                ).normalized()
                if active_new.width() < self.MIN_SIZE:
                    active_new.setWidth(self.MIN_SIZE)
                if active_new.height() < self.MIN_SIZE:
                    active_new.setHeight(self.MIN_SIZE)
                self._resize_group(active_start, active_new)
            else:
                new_rect = change_rectF(
                    QRectF(self._start_rect),
                    self._drag_handle,
                    event.pos(),
                ).normalized()
                if new_rect.width() < self.MIN_SIZE:
                    new_rect.setWidth(self.MIN_SIZE)
                if new_rect.height() < self.MIN_SIZE:
                    new_rect.setHeight(self.MIN_SIZE)
                self.setRect(new_rect)
        self._relayout_label()
        event.accept()

    def mouseReleaseEvent(self, event):
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        released_handle = self._drag_handle
        self._drag_handle = RectPosition.NONE
        self._relayout_label()
        self.setSelected(True)
        if self.scene() is not None and self.scene().views():
            self.scene().views()[0].setFocus(Qt.FocusReason.MouseFocusReason)
        self._on_selected(self.element_index)
        changed_items = self._group_start_rects or {self: self.scene_rect()}
        if released_handle != RectPosition.NONE and self._drag_moved:
            for item in changed_items:
                item.setSelected(True)
                item._relayout_label()
                self._on_geometry_changed(item.element_index, item.scene_rect())
        self._drag_moved = False
        self._group_start_rects = {}
        event.accept()

    def _selected_region_rects(self) -> dict["IdeogramRegionItem", QRectF]:
        if self.scene() is None:
            return {self: self.scene_rect()}
        selected = {}
        for item in self.scene().selectedItems():
            if isinstance(item, IdeogramRegionItem):
                selected[item] = item.scene_rect()
        selected.setdefault(self, self.scene_rect())
        return selected

    def _resize_group(self, active_start: QRectF, active_new: QRectF):
        scale_x = self._resize_scale(
            active_start.width(),
            active_new.width(),
            self._drag_handle
            in {
                RectPosition.TL,
                RectPosition.TR,
                RectPosition.RIGHT,
                RectPosition.BR,
                RectPosition.BL,
                RectPosition.LEFT,
            },
        )
        scale_y = self._resize_scale(
            active_start.height(),
            active_new.height(),
            self._drag_handle
            in {
                RectPosition.TL,
                RectPosition.TOP,
                RectPosition.TR,
                RectPosition.BR,
                RectPosition.BOTTOM,
                RectPosition.BL,
            },
        )
        anchor_x = (
            active_start.right()
            if self._drag_handle
            in {RectPosition.TL, RectPosition.LEFT, RectPosition.BL}
            else active_start.left()
        )
        anchor_y = (
            active_start.bottom()
            if self._drag_handle
            in {RectPosition.TL, RectPosition.TOP, RectPosition.TR}
            else active_start.top()
        )
        for item, start_rect in self._group_start_rects.items():
            x = anchor_x + (start_rect.x() - anchor_x) * scale_x
            y = anchor_y + (start_rect.y() - anchor_y) * scale_y
            width = max(self.MIN_SIZE, start_rect.width() * scale_x)
            height = max(self.MIN_SIZE, start_rect.height() * scale_y)
            item.set_scene_rect(QRectF(x, y, width, height))

    @staticmethod
    def _resize_scale(start_size: float, new_size: float, enabled: bool) -> float:
        if not enabled or start_size <= 0:
            return 1.0
        return max(0.01, new_size / start_size)

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
        rect = self.rect()

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.brush())
        painter.drawRect(rect)

        if self._palette_colors:
            strip_height = self._palette_strip_height()
            strip_width = rect.width() / len(self._palette_colors)
            painter.setPen(Qt.PenStyle.NoPen)
            for index, color in enumerate(self._palette_colors):
                painter.setBrush(color)
                painter.drawRect(
                    QRectF(
                        rect.left() + strip_width * index,
                        rect.top(),
                        strip_width,
                        strip_height,
                    )
                )

        selected = self.isSelected()
        border_width = self._configured_border_width()
        halo_width = self._configured_halo_width()
        selected_boost = 0.6 if selected else 0.0

        painter.setBrush(Qt.BrushStyle.NoBrush)
        if halo_width > 0.0:
            halo_pen = QPen(
                self._contrast_halo_color(self.pen().color()),
                border_width + halo_width + selected_boost,
            )
            halo_pen.setCosmetic(True)
            halo_pen.setStyle(Qt.PenStyle.SolidLine)
            painter.setPen(halo_pen)
            painter.drawRect(rect)

        inner_pen = QPen(self.pen().color(), border_width + selected_boost)
        inner_pen.setCosmetic(True)
        inner_pen.setStyle(Qt.PenStyle.SolidLine)
        painter.setPen(inner_pen)
        painter.drawRect(rect)

        if selected:
            accent = QColor("#FFFFFF")
            accent.setAlpha(190)
            accent_pen = QPen(accent, 1.0)
            accent_pen.setCosmetic(True)
            accent_pen.setStyle(Qt.PenStyle.DotLine)
            painter.setPen(accent_pen)
            painter.drawRect(rect.adjusted(-1.0, -1.0, 1.0, 1.0))
