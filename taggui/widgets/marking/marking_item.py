"""Interactive marking rectangle with drag/resize functionality."""

from math import ceil, floor, sqrt
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsRectItem

from utils.settings import settings
from utils.image import ImageMarking
import utils.target_dimension as target_dimension
from utils.grid import Grid
from utils.rect import (change_rect, change_rect_to_match_size,
                        flip_rect_position, get_rect_position, RectPosition)

# The (inverse) golden ratio for showing hints during cropping
golden_ratio = 2 / (1 + sqrt(5))

# Grid for alignment to latent space
grid = Grid(QRect(0, 0, 1, 1))

marking_colors = {
    ImageMarking.CROP: Qt.blue,
    ImageMarking.HINT: Qt.gray,
    ImageMarking.INCLUDE: Qt.green,
    ImageMarking.EXCLUDE: Qt.red,
}

def calculate_grid(content: QRect):
    global grid
    grid = Grid(content)


class MarkingItem(QGraphicsRectItem):
    """Interactive rectangle item for image/video marking (crop, hint, include, exclude)."""

    # the halved size of the pen in local coordinates to make sure it stays the
    # same during zooming
    pen_half_width: float = 1.0
    # the minimal size of the active area in scene coordinates
    handle_half_size: int = 5
    zoom_factor: float = 1.0
    # The size of the image this rect belongs to
    image_size: QRect = QRect(0, 0, 1, 1)
    # Static link to the single ImageGraphicsView in this application
    image_view: bool = None
    show_marking_latent: bool = True
    handle_selected: RectPosition = RectPosition.NONE
    show_crop_hint: bool = True

    def __init__(self, rect: QRect, rect_type: ImageMarking, interactive: bool,
                 parent = None):
        super().__init__(rect.toRectF(), parent)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.rect_type = rect_type
        self.label = None  # Will be set to MarkingLabel externally
        self.color = marking_colors[rect_type]
        self.setZValue(2)

        # Instance variable for sticky snapping feature
        self.last_snapped_bucket_size = None

        if rect_type in [ImageMarking.INCLUDE, ImageMarking.EXCLUDE]:
            self.area = QGraphicsRectItem(self)
            self.area.setVisible(self.show_marking_latent)
            self.area.setFlag(QGraphicsItem.ItemStacksBehindParent)
            self.area.setZValue(1)
            area_color = QColor(self.color)
            area_color.setAlpha(127)
            self.area.setBrush(area_color)
            self.area.setPen(Qt.NoPen)
            self.move()
        if interactive:
            MarkingItem.handle_selected = RectPosition.BR

    def move(self):
        if self.rect_type == ImageMarking.CROP:
            self.image_view.image_viewer.hud_item.setValues(self.rect(), MarkingItem.handle_selected)
        elif self.rect_type == ImageMarking.INCLUDE:
            self.area.setRect(QRectF(grid.snap(self.rect().toRect().topLeft(), ceil),
                                     grid.snap(self.rect().toRect().adjusted(0,0,1,1).bottomRight(), floor)))
        elif self.rect_type == ImageMarking.EXCLUDE:
            self.area.setRect(QRectF(grid.snap(self.rect().toRect().topLeft(), floor),
                                     grid.snap(self.rect().toRect().adjusted(0,0,1,1).bottomRight(), ceil)))

    def handleAt(self, point: QPointF) -> RectPosition:
        handle_space = -min(self.pen_half_width - self.handle_half_size,
                            0)/self.zoom_factor
        pos = get_rect_position(point.x() < self.rect().left() + handle_space,
                                 point.x() > self.rect().right() - handle_space,
                                 point.y() < self.rect().top() + handle_space,
                                 point.y() > self.rect().bottom() - handle_space)
        # If we're inside the rect (not on edges), return CENTER
        if pos == RectPosition.NONE and self.rect().contains(point):
            return RectPosition.CENTER
        return pos

    def mousePressEvent(self, event):
        self.show_crop_hint = ((event.modifiers() & Qt.KeyboardModifier.AltModifier) !=
                               Qt.KeyboardModifier.AltModifier)
        MarkingItem.handle_selected = self.handleAt(event.pos())
        if (event.button() == Qt.MouseButton.LeftButton and
            MarkingItem.handle_selected != RectPosition.NONE):
            self.image_view.image_viewer.proxy_image_index.model().sourceModel().add_to_undo_stack(
                action_name=f'Change marking geometry', should_ask_for_confirmation=False)
            self.setZValue(4)
            # Store initial position for CENTER drag
            if MarkingItem.handle_selected == RectPosition.CENTER:
                self.drag_start_pos = event.pos()
                self.drag_start_rect = self.rect()
            # Reset snapped bucket size for sticky snapping behavior
            self.last_snapped_bucket_size = None
            self.move()
        elif (event.button() == Qt.MouseButton.RightButton and
                MarkingItem.handle_selected != RectPosition.NONE):
            pass
        else:
            event.ignore()

    def mouseMoveEvent(self, event):
        if MarkingItem.handle_selected != RectPosition.NONE:
            self.show_crop_hint = ((event.modifiers() & Qt.KeyboardModifier.AltModifier) !=
                                   Qt.KeyboardModifier.AltModifier)

            # Handle CENTER drag (move entire rect)
            if MarkingItem.handle_selected == RectPosition.CENTER:
                delta = event.pos() - self.drag_start_pos
                rect = self.drag_start_rect.translated(delta)
                # Clamp to image boundaries
                if rect.left() < 0:
                    rect.moveLeft(0)
                if rect.top() < 0:
                    rect.moveTop(0)
                if rect.right() > self.image_size.width():
                    rect.moveRight(self.image_size.width())
                if rect.bottom() > self.image_size.height():
                    rect.moveBottom(self.image_size.height())
            elif ((event.modifiers() & Qt.KeyboardModifier.ShiftModifier) ==
                Qt.KeyboardModifier.ShiftModifier):
                if self.rect_type == ImageMarking.CROP:
                    bucket_res = settings.value('export_bucket_res_size', type=int)

                    # First, calculate what the rect would be if we just follow the mouse
                    rect_pre = change_rect(self.rect(),
                                           MarkingItem.handle_selected,
                                           event.pos())
                    # Clamp to image boundaries
                    rect_pre = rect_pre.intersected(self.image_size)

                    target_size = target_dimension.get(rect_pre.toRect().size())

                    # Sticky snapping: only recalculate if target bucket size changed
                    if target_size != self.last_snapped_bucket_size:
                        self.last_snapped_bucket_size = target_size
                        # target is the final size, so anticipate the scaling
                        scale = min(rect_pre.width() / target_size.width(),
                                    rect_pre.height() / target_size.height())
                        target = target_size.toSizeF() * scale
                        target = QSize(max(bucket_res, ceil(target.width())),
                                       max(bucket_res, ceil(target.height())))
                        rect_candidate = change_rect_to_match_size(rect_pre,
                                                         MarkingItem.handle_selected,
                                                         target)
                        # Only accept the snap if it fits within image boundaries
                        if self.image_size.contains(rect_candidate):
                            rect = rect_candidate
                        else:
                            # Reject snap - use the clamped rect without snapping
                            rect = rect_pre
                    else:
                        # Same bucket size - but allow rect to grow if mouse moved significantly
                        # Try to fit the current bucket to the new mouse position
                        scale = min(rect_pre.width() / target_size.width(),
                                    rect_pre.height() / target_size.height())
                        target = target_size.toSizeF() * scale
                        target = QSize(max(bucket_res, ceil(target.width())),
                                       max(bucket_res, ceil(target.height())))
                        rect_candidate = change_rect_to_match_size(rect_pre,
                                                         MarkingItem.handle_selected,
                                                         target)
                        # Only update if it still fits
                        if self.image_size.contains(rect_candidate):
                            rect = rect_candidate
                        else:
                            # Keep current rect - can't grow further with this bucket size
                            rect = self.rect()
                else:
                    rect = change_rect(self.rect(),
                                       MarkingItem.handle_selected,
                                       event.pos())

                    round_tl = round
                    round_br = round
                    if self.rect_type == ImageMarking.EXCLUDE:
                        round_tl = floor
                        round_br = ceil
                    elif self.rect_type == ImageMarking.INCLUDE:
                        round_tl = ceil
                        round_br = floor
                    rect = QRectF(grid.snap(rect.toRect().topLeft(), round_tl),
                                  grid.snap(rect.toRect().bottomRight(), round_br))
                    rect = QRect(QPoint(round_br(rect.topLeft().x()),
                                        round_br(rect.topLeft().y())),
                                 QPoint(round_tl(rect.bottomRight().x()),
                                        round_tl(rect.bottomRight().y())))
            else:
                pos_quantized = event.pos().toPoint()
                rect = change_rect(self.rect().toRect(),
                                   MarkingItem.handle_selected,
                                   pos_quantized)

            # Only flip position for resize operations, not for CENTER move
            if MarkingItem.handle_selected != RectPosition.CENTER:
                MarkingItem.handle_selected = flip_rect_position(self.handle_selected,
                                                                 rect.width() < 0,
                                                                 rect.height() < 0)

            if rect.width() == 0 or rect.height() == 0:
                self.setRect(rect)
            else:
                rect = rect.intersected(self.image_size)
                self.setRect(rect)
                if MarkingItem.handle_selected != RectPosition.CENTER:
                    self.size_changed()

            self.move()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        MarkingItem.handle_selected = RectPosition.NONE
        self.move()
        self.setZValue(2)
        if ((event.modifiers() & Qt.KeyboardModifier.ControlModifier) ==
                Qt.KeyboardModifier.ControlModifier):
            self.image_view.set_insertion_mode(self.rect_type)
        self.ungrabMouse()
        super().mouseReleaseEvent(event)
        self.image_view.image_viewer.marking_changed(self)

    def paint(self, painter, option, widget=None):
        if self.rect_type == ImageMarking.CROP:
            # Only show hints and overlay during resize operations, not during CENTER move
            if (self.show_crop_hint and
                MarkingItem.handle_selected != RectPosition.NONE and
                MarkingItem.handle_selected != RectPosition.CENTER and
                self==self.scene().mouseGrabberItem()):
                hint_line_crossings = [
                    self.rect().center(),
                    self.rect().topLeft() + QPointF(self.rect().width()*golden_ratio,
                                                    self.rect().height()*golden_ratio),
                    self.rect().bottomRight() - QPointF(self.rect().width()*golden_ratio,
                                                        self.rect().height()*golden_ratio),
                    self.rect().topLeft() + QPointF(self.rect().width()/3,
                                                    self.rect().height()/3),
                    self.rect().bottomRight() - QPointF(self.rect().width()/3,
                                                        self.rect().height()/3)]
                lint_line_style = [Qt.SolidLine, Qt.DotLine, Qt.DotLine, Qt.DashLine, Qt.DashLine]
                for crossing, style in zip(hint_line_crossings, lint_line_style):
                    path = QPainterPath()
                    path.moveTo(self.rect().x(), crossing.y())
                    path.lineTo(self.rect().right(), crossing.y())
                    path.moveTo(crossing.x(), self.rect().y())
                    path.lineTo(crossing.x(), self.rect().bottom())
                    painter.setPen(QPen(QColor(255, 255, 255, 127), 3 / self.zoom_factor))
                    painter.drawPath(path)
                    painter.setPen(QPen(QColor(0, 0, 0), 1 / self.zoom_factor, style))
                    painter.drawPath(path)
            # Show red overlay during active resize operations (not during move or when idle)
            if (MarkingItem.handle_selected != RectPosition.NONE and
                MarkingItem.handle_selected != RectPosition.CENTER and
                self==self.scene().mouseGrabberItem()):
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(255, 0, 0, 127))
                path = QPainterPath()
                # The red shows what will be cropped OUT
                # First add the full image area, then subtract the crop rect to create the mask
                path.setFillRule(Qt.OddEvenFill)
                path.addRect(MarkingItem.image_size)
                path.addRect(self.rect())
                painter.drawPath(path)

        pen_half_width = self.pen_half_width / self.zoom_factor
        pen = QPen(self.color, 2*pen_half_width, Qt.SolidLine, Qt.RoundCap,
                   Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(self.rect().adjusted(-pen_half_width, -pen_half_width,
                                              pen_half_width, pen_half_width))

        if self.isSelected():
            s_rect = self.rect().adjusted(-2*pen_half_width, -2*pen_half_width,
                                           2*pen_half_width,  2*pen_half_width)
            painter.setPen(QPen(Qt.white, 1.5 / self.zoom_factor, Qt.SolidLine))
            painter.drawRect(s_rect)
            painter.setPen(QPen(Qt.black, 1.5 / self.zoom_factor, Qt.DotLine))
            painter.drawRect(s_rect)

    def shape(self):
        path = super().shape()
        adjust = (self.pen_half_width + max(self.pen_half_width,
                                            self.handle_half_size))/self.zoom_factor
        path.addRect(self.rect().adjusted(-adjust, -adjust, adjust, adjust))
        return path

    def boundingRect(self):
        adjust = (self.pen_half_width + max(self.pen_half_width,
                                            self.handle_half_size))/self.zoom_factor
        bbox = self.rect().adjusted(-adjust, -adjust, adjust, adjust)
        return bbox

    def size_changed(self):
        if self.rect_type == ImageMarking.CROP:
            old_grid = grid
            calculate_grid(self.rect().toRect())
            if old_grid != grid:
                self.image_view.image_viewer.recalculate_markings(self)
        self.adjust_layout()

    def adjust_layout(self):
        if self.label is not None:
            self.label.changeZoom(self.zoom_factor)
            pen_half_width = self.pen_half_width / self.zoom_factor
            if self.rect().y() > self.label.boundingRect().height():
                self.label.setPos(self.rect().adjusted(
                    -2 * pen_half_width,
                    -1.8*pen_half_width
                        - self.label.boundingRect().height() / self.zoom_factor,
                    0, 0).topLeft())
                self.label.parentItem().setRect(self.label.sceneBoundingRect())
            else:
                self.label.setPos(self.rect().adjusted(
                    -pen_half_width, -pen_half_width, 0, 0).topLeft())
                self.label.parentItem().setRect(self.label.sceneBoundingRect())
