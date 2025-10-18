import re
from math import ceil, floor, sqrt
from PySide6.QtCore import (QModelIndex, QPersistentModelIndex, QPoint, QPointF,
                            QRect, QRectF, QSize, Qt, Signal, Slot, QTimer)
from PySide6.QtGui import (QAction, QActionGroup, QColor, QIcon, QImage,
                           QPainter, QPainterPath, QPen, QPixmap, QTransform,
                           QMouseEvent)
from PySide6.QtWidgets import (QGraphicsItem, QGraphicsLineItem,
                               QGraphicsPixmapItem, QGraphicsRectItem,
                               QGraphicsTextItem, QGraphicsScene, QGraphicsView,
                               QMenu, QVBoxLayout, QWidget)
from PIL import Image as pilimage
from utils.settings import settings
from models.proxy_image_list_model import ProxyImageListModel
from utils.image import Image, ImageMarking, Marking
import utils.target_dimension as target_dimension
from utils.grid import Grid
from utils.rect import (change_rect, change_rect_to_match_size,
                        flip_rect_position, get_rect_position,
                        map_rect_position_to_cursor, RectPosition)
from widgets.video_player import VideoPlayerWidget
from widgets.video_controls import VideoControlsWidget

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

# Organization of Z value:
# 0: the image
# 1: the semi transparent include/exclude areas
# 2: the borders of the markings
# 3: the HUD
# 4: the currently manipulated marking
# 5: the cross hair lines

class MarkingItem(QGraphicsRectItem):
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
        self.label: MarkingLabel | None = None
        self.color = marking_colors[rect_type]
        self.setZValue(2)
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
        return get_rect_position(point.x() < self.rect().left() + handle_space,
                                 point.x() > self.rect().right() - handle_space,
                                 point.y() < self.rect().top() + handle_space,
                                 point.y() > self.rect().bottom() - handle_space)

    def mousePressEvent(self, event):
        self.show_crop_hint = ((event.modifiers() & Qt.KeyboardModifier.AltModifier) !=
                               Qt.KeyboardModifier.AltModifier)
        MarkingItem.handle_selected = self.handleAt(event.pos())
        if (event.button() == Qt.MouseButton.LeftButton and
            MarkingItem.handle_selected != RectPosition.NONE):
            self.image_view.image_viewer.proxy_image_index.model().sourceModel().add_to_undo_stack(
                action_name=f'Change marking geometry', should_ask_for_confirmation=False)
            self.setZValue(4)
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
            if ((event.modifiers() & Qt.KeyboardModifier.ShiftModifier) ==
                Qt.KeyboardModifier.ShiftModifier):
                if self.rect_type == ImageMarking.CROP:
                    bucket_res = settings.value('export_bucket_res_size', type=int)
                    rect_pre = change_rect(self.rect(),
                                           MarkingItem.handle_selected,
                                           event.pos())
                    target_size = target_dimension.get(rect_pre.toRect().size())
                    # target is the final size, so anticipate the scaling
                    scale = min(rect_pre.width() / target_size.width(),
                                rect_pre.height() / target_size.height())
                    target = target_size.toSizeF() * scale
                    target = QSize(max(bucket_res, ceil(target.width())),
                                   max(bucket_res, ceil(target.height())))
                    rect = change_rect_to_match_size(self.rect(),
                                                     MarkingItem.handle_selected,
                                                     target)
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

            MarkingItem.handle_selected = flip_rect_position(self.handle_selected,
                                                             rect.width() < 0,
                                                             rect.height() < 0)

            if rect.width() == 0 or rect.height() == 0:
                self.setRect(rect)
            else:
                rect = rect.intersected(self.image_size)
                self.setRect(rect)
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
            if (self.show_crop_hint and
                MarkingItem.handle_selected != RectPosition.NONE and
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
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 0, 0, 127))
            path = QPainterPath()
            path.addRect(self.rect())
            path.addRect(grid.visible)
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


class MarkingLabel(QGraphicsTextItem):
    editingFinished = Signal()

    def __init__(self, text, confidence, parent):
        if 0 <= confidence < 1:
            super().__init__(f'{text}: {confidence:.3f}', parent)
        else:
            super().__init__(text, parent)
        self.setDefaultTextColor(Qt.black)
        self.setTextInteractionFlags(Qt.TextEditorInteraction)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.editingFinished.emit()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Enter, Qt.Key_Return):
            self.clearFocus()
            self.editingFinished.emit()
        else:
            super().keyPressEvent(event)
            self.parentItem().setRect(self.sceneBoundingRect())

    def insertFromMimeData(self, source):
        if source.hasText():
            # Insert only the plain text
            cursor = self.textCursor()
            cursor.insertText(source.text())
        else:
            super().insertFromMimeData(source)
        self.parentItem().setRect(self.sceneBoundingRect())

    def changeZoom(self, zoom_factor):
        self.setScale(1/zoom_factor)
        self.parentItem().setRect(self.sceneBoundingRect())


class ResizeHintHUD(QGraphicsItem):
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

class ImageGraphicsView(QGraphicsView):
    def __init__(self, scene, image_viewer):
        super().__init__(scene)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.showContextMenu)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.image_viewer = image_viewer
        MarkingItem.image_view = self
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.last_pos = None
        self.clear_scene()

    def showContextMenu(self, pos):
        scene_pos = self.mapToScene(pos)
        item = self.scene().itemAt(scene_pos, self.transform())
        if isinstance(item, MarkingLabel):
            item = item.parentItem().parentItem()
        if isinstance(item, MarkingItem) and MarkingItem.handle_selected != RectPosition.NONE:
            menu = QMenu()
            if item.rect_type != ImageMarking.NONE:
                if item.rect_type == ImageMarking.CROP:
                    # Add "Apply Crop" option for crop markings
                    apply_crop_action = QAction('Apply Crop (Destructive)', self)
                    apply_crop_action.triggered.connect(
                        lambda: self.image_viewer.apply_crop_to_file())
                    menu.addAction(apply_crop_action)
                    menu.addSeparator()
                else:
                    marking_group = QActionGroup(menu)
                    change_to_hint_action = QAction('Hint', marking_group)
                    change_to_hint_action.setCheckable(True)
                    change_to_hint_action.setChecked(item.rect_type == ImageMarking.HINT)
                    change_to_hint_action.triggered.connect(
                        lambda: self.image_viewer.change_marking([item], ImageMarking.HINT))
                    menu.addAction(change_to_hint_action)
                    change_to_exclude_action = QAction('Exclude', marking_group)
                    change_to_exclude_action.setCheckable(True)
                    change_to_exclude_action.setChecked(item.rect_type == ImageMarking.EXCLUDE)
                    change_to_exclude_action.triggered.connect(
                        lambda: self.image_viewer.change_marking([item], ImageMarking.EXCLUDE))
                    menu.addAction(change_to_exclude_action)
                    change_to_include_action = QAction('Include', marking_group)
                    change_to_include_action.setCheckable(True)
                    change_to_include_action.setChecked(item.rect_type == ImageMarking.INCLUDE)
                    change_to_include_action.triggered.connect(
                        lambda: self.image_viewer.change_marking([item], ImageMarking.INCLUDE))
                    menu.addAction(change_to_include_action)
                    menu.addSeparator()
                delete_marking_action = QAction(
                    QIcon.fromTheme('edit-delete'), 'Delete', self)
                delete_marking_action.triggered.connect(
                    lambda: self.image_viewer.delete_markings([item]))
                menu.addAction(delete_marking_action)
            menu.exec(self.mapToGlobal(pos))

    def clear_scene(self):
        """Use this and not scene().clear() due to resource management."""
        self.insertion_mode = False
        self.horizontal_line = None
        self.vertical_line = None
        self.scene().clear()

    def set_insertion_mode(self, marking: ImageMarking):
        old_insertion_mode = self.insertion_mode
        self.insertion_mode = marking != ImageMarking.NONE
        if self.insertion_mode:
            if not old_insertion_mode:
                self.setDragMode(QGraphicsView.DragMode.NoDrag)
                self.horizontal_line = QGraphicsLineItem()
                self.horizontal_line.setZValue(5)
                self.vertical_line = QGraphicsLineItem()
                self.vertical_line.setZValue(5)
                self.scene().addItem(self.horizontal_line)
                self.scene().addItem(self.vertical_line)
                self.update_lines_pos()
            self.image_viewer.marking.emit(marking)
        else:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            if self.horizontal_line:
                self.scene().removeItem(self.horizontal_line)
                self.horizontal_line = None
                self.scene().removeItem(self.vertical_line)
                self.vertical_line = None
            self.image_viewer.marking.emit(ImageMarking.NONE)

    def update_lines_pos(self):
        """Show the hint lines at the position self.last_pos.

        Note: do not use a position parameter as then the key event couldn't
        immediately show them as the mouse position would be missing then.
        """
        if self.last_pos:
            view_rect = self.mapToScene(self.viewport().rect()).boundingRect()
            self.horizontal_line.setLine(view_rect.left(), self.last_pos.y(),
                                         view_rect.right(), self.last_pos.y())
            self.vertical_line.setLine(self.last_pos.x(), view_rect.top(),
                                       self.last_pos.x(), view_rect.bottom())

    def mousePressEvent(self, event: QMouseEvent):
        if self.insertion_mode and event.button() == Qt.MouseButton.LeftButton:
            rect_type = self.image_viewer.marking_to_add
            if rect_type == ImageMarking.NONE:
                if ((event.modifiers() & Qt.KeyboardModifier.AltModifier) ==
                    Qt.KeyboardModifier.AltModifier):
                    rect_type = ImageMarking.EXCLUDE
                else:
                    rect_type = ImageMarking.HINT

            self.image_viewer.proxy_image_index.model().sourceModel().add_to_undo_stack(
                action_name=f'Add {rect_type.value}', should_ask_for_confirmation=False)

            self.image_viewer.add_rectangle(QRect(self.last_pos, QSize(0, 0)),
                                            rect_type, interactive=True)
            self.set_insertion_mode(ImageMarking.NONE)
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        # Notify parent to show video controls if hovering near them
        if self.image_viewer._is_video_loaded and self.image_viewer.video_controls_auto_hide:
            # Map event position to parent widget coordinates
            parent_pos = self.mapTo(self.image_viewer, event.pos())
            controls_rect = self.image_viewer.video_controls.geometry()
            detection_rect = controls_rect.adjusted(-20, -20, 20, 20)
            if detection_rect.contains(parent_pos):
                self.image_viewer._show_controls_temporarily()

        scene_pos = self.mapToScene(event.position().toPoint())
        items = self.scene().items(scene_pos)
        cursor = None

        if self.insertion_mode:
            cursor = Qt.CursorShape.CrossCursor
        elif MarkingItem.handle_selected != RectPosition.NONE:
            cursor = map_rect_position_to_cursor(MarkingItem.handle_selected)
        else:
            for item in items:
                if isinstance(item, MarkingItem):
                    handle = item.handleAt(scene_pos)
                    if handle == RectPosition.NONE:
                        continue
                    cursor = map_rect_position_to_cursor(handle)
                    break
        if cursor is None:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        else:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(cursor)

        if ((event.modifiers() & Qt.KeyboardModifier.ShiftModifier) ==
            Qt.KeyboardModifier.ShiftModifier):
            self.last_pos = grid.snap(scene_pos.toPoint()).toPoint()
        else:
            self.last_pos = scene_pos.toPoint()

        if self.insertion_mode:
            self.update_lines_pos()
        else:
            super().mouseMoveEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete:
            edited_item = self.scene().focusItem()
            if not (isinstance(edited_item, MarkingLabel) and
                edited_item.textInteractionFlags() == Qt.TextEditorInteraction):
                # Delete marking only when not editing the label
                self.image_viewer.delete_markings()
        else:
            if MarkingItem.handle_selected == RectPosition.NONE:
                if ((event.modifiers() & Qt.KeyboardModifier.ControlModifier) ==
                        Qt.KeyboardModifier.ControlModifier):
                    if ((event.modifiers() & Qt.KeyboardModifier.AltModifier) ==
                            Qt.KeyboardModifier.AltModifier):
                        self.set_insertion_mode(ImageMarking.EXCLUDE)
                    else:
                        self.set_insertion_mode(ImageMarking.HINT)
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if MarkingItem.handle_selected == RectPosition.NONE:
            if ((event.modifiers() & Qt.KeyboardModifier.ControlModifier) ==
                Qt.KeyboardModifier.ControlModifier):
                if ((event.modifiers() & Qt.KeyboardModifier.AltModifier) ==
                        Qt.KeyboardModifier.AltModifier):
                    self.set_insertion_mode(ImageMarking.EXCLUDE)
                else:
                    self.set_insertion_mode(ImageMarking.HINT)
            else:
                self.set_insertion_mode(ImageMarking.NONE)
        super().keyReleaseEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.image_viewer.is_zoom_to_fit:
           self.image_viewer.zoom_fit()


class ImageViewer(QWidget):
    zoom = Signal(float, name='zoomChanged')
    marking = Signal(ImageMarking, name='markingToAdd')
    accept_crop_addition = Signal(bool, name='allowAdditionOfCrop')
    crop_changed = Signal(Grid, name='cropChanged')
    rating_changed = Signal(float, name='ratingChanged')

    def __init__(self, proxy_image_list_model: ProxyImageListModel):
        super().__init__()
        self.inhibit_reload_image = False
        self.proxy_image_list_model = proxy_image_list_model
        MarkingItem.pen_half_width = round(self.devicePixelRatio())
        MarkingItem.zoom_factor = 1.0
        self.is_zoom_to_fit = True
        self.show_marking_state = True
        self.show_label_state = True
        self.show_marking_latent_state = True
        self.marking_to_add = ImageMarking.NONE
        self.scene = QGraphicsScene()
        self.view = ImageGraphicsView(self.scene, self)
        self.view.setOptimizationFlags(QGraphicsView.DontSavePainterState)
        self.crop_marking: ImageMarking | None = None
        settings.change.connect(self.setting_change)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.setLayout(layout)

        self.proxy_image_index: QPersistentModelIndex = None
        self.marking_items: list[MarkingItem] = []

        self.view.wheelEvent = self.wheelEvent

        # Video player and controls
        self.video_player = VideoPlayerWidget()
        self.current_video_item = None
        self.video_controls = VideoControlsWidget(self)
        self.video_controls.setVisible(False)
        # Load auto-hide setting (inverted from always_show setting)
        always_show = settings.value('video_always_show_controls', False, type=bool)
        self.video_controls_auto_hide = not always_show
        self._controls_visible = False
        self._is_video_loaded = False

        # Timer for auto-hiding controls
        self._controls_hide_timer = QTimer(self)
        self._controls_hide_timer.setSingleShot(True)
        self._controls_hide_timer.timeout.connect(self._hide_controls)

        # Position controls (will restore saved position if exists)
        self._position_video_controls()

        # Restore saved X,Y position and width percentages if exists
        saved_x_percent = settings.value('video_controls_x_percent', type=float)
        saved_y_percent = settings.value('video_controls_y_percent', type=float)
        saved_width_percent = settings.value('video_controls_width_percent', type=float)
        if saved_x_percent is not None and saved_y_percent is not None and self.width() > 0 and self.height() > 0:
            controls_height = self.video_controls.sizeHint().height()
            # Use saved width if available, otherwise use sizeHint
            if saved_width_percent is not None:
                controls_width = int(saved_width_percent * self.width())
                controls_width = max(400, min(controls_width, self.width()))  # Clamp
            else:
                controls_width = self.video_controls.sizeHint().width()
            x_pos = int(saved_x_percent * self.width())
            y_pos = int(saved_y_percent * self.height())
            # Clamp to valid range
            x_pos = max(0, min(x_pos, self.width() - controls_width))
            y_pos = max(0, min(y_pos, self.height() - controls_height))
            self.video_controls.setGeometry(x_pos, y_pos, controls_width, controls_height)

        # Enable mouse tracking for auto-hide
        self.setMouseTracking(True)
        self.view.setMouseTracking(True)
        self.view.viewport().setMouseTracking(True)

    def _position_video_controls(self, force_bottom=False):
        """Position video controls overlay at saved position."""
        if not self.video_controls:
            return

        controls_height = self.video_controls.sizeHint().height()

        # Check if we have saved percentage positions and width
        saved_x_percent = settings.value('video_controls_x_percent', type=float)
        saved_y_percent = settings.value('video_controls_y_percent', type=float)
        saved_width_percent = settings.value('video_controls_width_percent', type=float)

        if force_bottom or saved_x_percent is None or saved_y_percent is None:
            # Position at bottom center with default width
            controls_width = self.video_controls.sizeHint().width()
            x_pos = (self.width() - controls_width) // 2
            y_pos = self.height() - controls_height
            self.video_controls.setGeometry(x_pos, y_pos, controls_width, controls_height)
        else:
            # Use saved percentages to calculate position and width
            if self.width() > 0 and self.height() > 0:
                # Calculate width
                if saved_width_percent is not None:
                    controls_width = int(saved_width_percent * self.width())
                    controls_width = max(400, min(controls_width, self.width()))
                else:
                    controls_width = self.video_controls.sizeHint().width()

                x_pos = int(saved_x_percent * self.width())
                y_pos = int(saved_y_percent * self.height())
                # Clamp to valid range
                x_pos = max(0, min(x_pos, self.width() - controls_width))
                y_pos = max(0, min(y_pos, self.height() - controls_height))
                self.video_controls.setGeometry(x_pos, y_pos, controls_width, controls_height)

        # Raise to ensure it's on top
        self.video_controls.raise_()

    def resizeEvent(self, event):
        """Reposition controls when viewer is resized."""
        super().resizeEvent(event)
        # Store visibility state
        was_visible = self.video_controls.isVisible()
        self._position_video_controls()
        # Restore visibility after resize (force controls to update)
        if was_visible:
            self.video_controls.setVisible(True)
            self.video_controls.raise_()

    def mouseMoveEvent(self, event):
        """Show controls when hovering over their position."""
        if self._is_video_loaded and self.video_controls_auto_hide:
            # Check if mouse is near the controls position
            controls_rect = self.video_controls.geometry()
            # Expand detection area slightly
            detection_rect = controls_rect.adjusted(-20, -20, 20, 20)
            if detection_rect.contains(event.pos()):
                self._show_controls_temporarily()
        super().mouseMoveEvent(event)

    def _show_controls_temporarily(self):
        """Show controls and start hide timer."""
        if not self._controls_visible:
            self.video_controls.setVisible(True)
            self._controls_visible = True
            self._position_video_controls()

        # Reset hide timer (0.8 seconds)
        self._controls_hide_timer.stop()
        self._controls_hide_timer.start(800)

    def _hide_controls(self):
        """Hide controls after timeout, but only if mouse is not over them."""
        if self.video_controls_auto_hide and self._is_video_loaded:
            # Check if mouse is still over controls
            mouse_pos = self.mapFromGlobal(self.cursor().pos())
            controls_rect = self.video_controls.geometry()
            if not controls_rect.contains(mouse_pos):
                self.video_controls.setVisible(False)
                self._controls_visible = False

    def _show_controls_permanent(self):
        """Show controls permanently (not auto-hide)."""
        self._controls_hide_timer.stop()
        self.video_controls.setVisible(True)
        self._controls_visible = True
        self._position_video_controls()

    @Slot(bool)
    def set_always_show_controls(self, always_show: bool):
        """Toggle always-show mode for video controls."""
        self.video_controls_auto_hide = not always_show
        if always_show and self._is_video_loaded:
            self._show_controls_permanent()
        elif self._is_video_loaded:
            # Re-enable auto-hide, show temporarily
            self._show_controls_temporarily()

    @Slot()
    def load_image(self, proxy_image_index: QModelIndex, is_complete = True):
        persistent_image_index = QPersistentModelIndex(proxy_image_index)
        if ((not persistent_image_index.isValid()) or
            (self.inhibit_reload_image and
             persistent_image_index == self.proxy_image_index)):
            return
        self.proxy_image_index = persistent_image_index

        image: Image = self.proxy_image_index.data(Qt.ItemDataRole.UserRole)
        self.rating_changed.emit(image.rating)

        if is_complete:
            self.marking_items.clear()
            self.view.clear_scene()

            # Check if this is a video
            if image.is_video:
                # Create a pixmap item for video frames BEFORE cleanup
                image_item = QGraphicsPixmapItem()
                image_item.setZValue(0)
                self.scene.addItem(image_item)
                self.current_video_item = image_item

                # Now load video and display first frame
                if self.video_player.load_video(image.path, image_item):
                    # Update scene rect after video loads
                    if image_item.pixmap() and not image_item.pixmap().isNull():
                        self.scene.setSceneRect(image_item.boundingRect()
                                              .adjusted(-1, -1, 1, 1))
                        MarkingItem.image_size = image_item.boundingRect().toRect()

                        # Show video controls
                        self._is_video_loaded = True
                        if image.video_metadata:
                            self.video_controls.set_video_info(image.video_metadata)

                        # Only show controls if always-show is enabled
                        if not self.video_controls_auto_hide:
                            self._show_controls_permanent()

                        # Auto-play if enabled (do this AFTER setting up controls to avoid signal conflicts)
                        if self.video_controls.should_auto_play():
                            self.video_player.play()
                    else:
                        print(f"Video loaded but no frame available: {image.path}")
                        return
                else:
                    # Failed to load video, show error
                    print(f"Failed to load video: {image.path}")
                    return
            else:
                # Hide video controls for static images
                self._is_video_loaded = False
                self._controls_hide_timer.stop()
                self.video_controls.setVisible(False)
                self._controls_visible = False
                # Load static image
                if image.path.suffix.lower() == ".jxl":
                     pil_image = pilimage.open(image.path)  # Decode JXL using Pillow
                     pil_image = pil_image.convert("RGBA")  # Ensure RGBA format

                     pixmap = QPixmap(QImage(
                         pil_image.tobytes("raw", "RGBA"),
                         pil_image.width,
                         pil_image.height,
                         QImage.Format_RGBA8888
                     ))
                else:
                    pixmap = QPixmap(str(image.path))
                image_item = QGraphicsPixmapItem(pixmap)
                image_item.setZValue(0)
                self.scene.setSceneRect(image_item.boundingRect()
                                        .adjusted(-1, -1, 1, 1)) # space for rect border
                self.scene.addItem(image_item)
                MarkingItem.image_size = image_item.boundingRect().toRect()

            self.zoom_fit()
            self.hud_item = ResizeHintHUD(MarkingItem.image_size, image_item)
        else:
            for item in self.marking_items:
                self.scene.removeItem(item)
            self.marking_items.clear()

        self.marking_to_add = ImageMarking.NONE
        self.marking.emit(ImageMarking.NONE)
        self.accept_crop_addition.emit(image.crop is None)
        if image.crop is not None:
            self.add_rectangle(image.crop, ImageMarking.CROP, interactive=False)
        else:
            calculate_grid(MarkingItem.image_size)
        for marking in image.markings:
            self.add_rectangle(marking.rect, marking.type, interactive=False,
                               name=marking.label, confidence=marking.confidence)

    def rating_change(self, rating: float):
        if self.proxy_image_index.isValid():
            image: Image = self.proxy_image_index.data(Qt.ItemDataRole.UserRole)
            if image.rating != rating:
                image.rating = rating
                self.proxy_image_list_model.sourceModel().write_meta_to_disk(image)

    @Slot()
    def setting_change(self, key, value):
        if key in ['export_resolution', 'export_bucket_res_size',
                   'export_latent_size', 'export_upscaling',
                   'export_bucket_strategy']:
            self.recalculate_markings()

    def recalculate_markings(self, ignore: MarkingItem | None = None):
        if self.crop_marking:
            calculate_grid(self.crop_marking.rect().toRect())
            if MarkingItem.handle_selected != RectPosition.NONE:
                # currently editing the crop marking -> update display
                self.crop_changed.emit(grid)
        else:
            calculate_grid(MarkingItem.image_size)
        for marking in self.marking_items:
            if marking != ignore:
                marking.size_changed()
        self.scene.invalidate()

    @Slot()
    def zoom_in(self, center_pos: QPoint = None):
        MarkingItem.zoom_factor = min(MarkingItem.zoom_factor * 1.25, 16)
        self.is_zoom_to_fit = False
        self.zoom_emit()

    @Slot()
    def zoom_out(self, center_pos: QPoint = None):
        view = self.view.viewport().size()
        scene = self.scene.sceneRect()
        if scene.width() < 1 or scene.height() < 1:
            return
        limit = min(view.width()/scene.width(), view.height()/scene.height())
        MarkingItem.zoom_factor = max(MarkingItem.zoom_factor / 1.25, limit)
        self.is_zoom_to_fit = MarkingItem.zoom_factor == limit
        self.zoom_emit()

    @Slot()
    def zoom_original(self):
        MarkingItem.zoom_factor = 1.0
        self.is_zoom_to_fit = False
        self.zoom_emit()

    @Slot()
    def zoom_fit(self):
        self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        MarkingItem.zoom_factor = self.view.transform().m11()
        self.is_zoom_to_fit = True
        self.zoom_emit()

    def zoom_emit(self):
        ResizeHintHUD.zoom_factor = MarkingItem.zoom_factor
        transform = self.view.transform()
        self.view.setTransform(QTransform(
            MarkingItem.zoom_factor, transform.m12(), transform.m13(),
            transform.m21(), MarkingItem.zoom_factor, transform.m23(),
            transform.m31(), transform.m32(), transform.m33()))
        for marking in self.marking_items:
            marking.adjust_layout()
        if self.is_zoom_to_fit:
            self.zoom.emit(-1)
        else:
            self.zoom.emit(MarkingItem.zoom_factor)

    @Slot(ImageMarking)
    def add_marking(self, marking: ImageMarking):
        self.marking_to_add = marking
        self.view.set_insertion_mode(marking)

    @Slot()
    def change_marking(self, items: list[MarkingItem] | None = None,
                       new_marking: ImageMarking = ImageMarking.NONE):
        self.proxy_image_index.model().sourceModel().add_to_undo_stack(
            action_name=f'Change marking', should_ask_for_confirmation=False)
        if items is None:
            items = self.scene.selectedItems()
        for item in items:
            if new_marking == ImageMarking.NONE:
                # default: toggle between all types
                item.rect_type = {ImageMarking.HINT: ImageMarking.EXCLUDE,
                                  ImageMarking.INCLUDE: ImageMarking.HINT,
                                  ImageMarking.EXCLUDE: ImageMarking.INCLUDE
                                 }[item.rect_type]
            else:
                item.rect_type = new_marking
            item.color = marking_colors[item.rect_type]
            item.label.parentItem().setBrush(item.color)
            self.marking_changed(item)
            item.update()

    @Slot(bool)
    def show_marking(self, checked: bool):
        self.show_marking_state = checked
        for marking in self.marking_items:
            marking.setVisible(checked)

    @Slot(bool)
    def show_label(self, checked: bool):
        self.show_label_state = checked
        for marking in self.marking_items:
            if marking.label:
                marking.label.setVisible(checked)
                marking.label.parentItem().setVisible(checked)

    @Slot(bool)
    def show_marking_latent(self, checked: bool):
        MarkingItem.show_marking_latent = checked
        for marking in self.marking_items:
            if marking.rect_type in [ImageMarking.INCLUDE, ImageMarking.EXCLUDE]:
                marking.area.setVisible(checked)

    def wheelEvent(self, event):
        old_pos = self.view.mapToScene(event.position().toPoint())

        if event.angleDelta().y() > 0:
            self.zoom_in()
        elif event.angleDelta().y() < 0:
            self.zoom_out()
        else:
            return

        new_pos = self.view.mapToScene(event.position().toPoint())
        delta = new_pos - old_pos
        self.view.translate(delta.x(), delta.y())

    def add_rectangle(self, rect: QRect, rect_type: ImageMarking,
                      interactive: bool, size: QSize = None, name: str = '',
                      confidence: float = 1.0):
        self.marking_to_add = ImageMarking.NONE
        marking_item = MarkingItem(rect, rect_type, interactive, size)
        marking_item.setVisible(self.show_marking_state)
        if rect_type == ImageMarking.CROP:
            self.crop_marking = marking_item
            marking_item.size_changed() # call after self.crop_marking was set!
        elif name == '' and rect_type != ImageMarking.NONE:
            image: Image = self.proxy_image_index.data(Qt.ItemDataRole.UserRole)
            name = {ImageMarking.HINT: 'hint',
                    ImageMarking.INCLUDE: 'include',
                    ImageMarking.EXCLUDE: 'exclude'}[rect_type]
            image.markings.append(Marking(name, rect_type, rect, confidence))
        marking_item.setData(0, name)
        marking_item.setData(1, confidence)
        if rect_type != ImageMarking.CROP and rect_type != ImageMarking.NONE:
            label_background = QGraphicsRectItem(marking_item)
            label_background.setZValue(2)
            label_background.setBrush(marking_item.color)
            label_background.setPen(Qt.NoPen)
            label_background.setVisible(self.show_label_state)
            marking_item.label = MarkingLabel(name, confidence, label_background)
            marking_item.label.setZValue(2)
            marking_item.label.setVisible(self.show_label_state)
            marking_item.label.editingFinished.connect(self.label_changed)
            marking_item.adjust_layout()
        self.scene.addItem(marking_item)
        self.marking_items.append(marking_item)
        if interactive:
            self.scene.clearSelection()
            marking_item.grabMouse()
        if rect_type == ImageMarking.CROP:
            self.accept_crop_addition.emit(False)

    @Slot()
    def label_changed(self):
        """Slot to call when a marking label was changed to sync the information
        in the image."""
        self.proxy_image_index.model().sourceModel().add_to_undo_stack(
            action_name=f'Change label', should_ask_for_confirmation=False)
        image: Image = self.proxy_image_index.data(Qt.ItemDataRole.UserRole)
        image.markings.clear()
        for marking in self.marking_items:
            if marking.rect_type != ImageMarking.CROP:
                label = marking.label.toPlainText()
                match = re.match(r'^(.*):\s*(\d*\.\d+)$', label)
                if match:
                    label = match.group(1)
                    confidence = float(match.group(2))
                else:
                    confidence = 1.0
                marking.label.parentItem().parentItem().setData(0, label)
                marking.label.parentItem().parentItem().setData(1, confidence)
                image.markings.append(Marking(label=label,
                                              type=marking.rect_type,
                                              rect=marking.rect().toRect(),
                                              confidence=confidence))
        self.proxy_image_list_model.sourceModel().write_meta_to_disk(image)

    @Slot(QGraphicsRectItem)
    def marking_changed(self, marking: QGraphicsRectItem):
        """Slot to call when a marking was changed to sync the information
        in the image."""
        assert self.proxy_image_index != None
        assert self.proxy_image_index.isValid()
        image: Image = self.proxy_image_index.data(Qt.ItemDataRole.UserRole)

        if marking.rect_type == ImageMarking.CROP:
            self.inhibit_reload_image = True
            self.proxy_image_list_model.sourceModel().layoutAboutToBeChanged.emit()
            image.thumbnail = None
            image.crop = marking.rect().toRect() # ensure int!
            image.target_dimension = grid.target
            if not self.proxy_image_list_model.does_image_match_filter(
                    image, self.proxy_image_list_model.filter):
                # don't call .invalidate() as the displayed list shouldn't
                # update
                self.proxy_image_list_model.filter = [['path', str(image.path)],
                                                      'OR',
                                                      self.proxy_image_list_model.filter]
            self.crop_changed.emit(None)
            self.proxy_image_list_model.sourceModel().changePersistentIndex(
                self.proxy_image_index, self.proxy_image_index)

            self.proxy_image_list_model.sourceModel().dataChanged.emit(
                self.proxy_image_index, self.proxy_image_index,
                [Qt.ItemDataRole.DecorationRole, Qt.ItemDataRole.SizeHintRole,
                 Qt.ToolTipRole, Qt.ItemDataRole.UserRole])
            self.proxy_image_list_model.sourceModel().layoutChanged.emit()
            self.inhibit_reload_image = False
        else:
            image.markings = [Marking(m.data(0),
                                      m.rect_type,
                                      m.rect().toRect(),
                                      m.data(1))
                for m in self.marking_items if m.rect_type != ImageMarking.CROP]
        self.proxy_image_list_model.sourceModel().write_meta_to_disk(image)

    def get_selected_type(self) -> ImageMarking:
        if len(self.scene.selectedItems()) > 0:
            return self.scene.selectedItems()[0].rect_type
        return ImageMarking.NONE

    @Slot()
    def delete_markings(self, items: list[MarkingItem] | None = None):
        """Slot to delete the list of items or when items = None all currently
        selected marking items."""
        self.proxy_image_index.model().sourceModel().add_to_undo_stack(
            action_name=f'Delete marking', should_ask_for_confirmation=False)
        image: Image = self.proxy_image_index.data(Qt.ItemDataRole.UserRole)
        if items is None:
            items = self.scene.selectedItems()
        for item in items:
            if item.rect_type == ImageMarking.CROP:
                self.crop_marking = None
                image.thumbnail = None
                image.crop = None
                image.target_dimension = None
                self.accept_crop_addition.emit(True)
                calculate_grid(MarkingItem.image_size)
                self.proxy_image_list_model.sourceModel().dataChanged.emit(
                    self.proxy_image_index, self.proxy_image_index,
                    [Qt.ItemDataRole.DecorationRole, Qt.ItemDataRole.SizeHintRole,
                     Qt.ToolTipRole, Qt.ItemDataRole.UserRole])
            else:
                self.marking_items.remove(item)
                self.label_changed()
                self.proxy_image_list_model.sourceModel().write_meta_to_disk(image)
            self.scene.removeItem(item)

    @Slot()
    def apply_crop_to_file(self):
        """Apply the crop directly to the file (destructive operation with backup)."""
        from PySide6.QtWidgets import QMessageBox
        from pathlib import Path
        from utils.crop_applier import apply_crop

        # Check if we have a crop defined
        if not self.crop_marking:
            QMessageBox.warning(self, "No Crop", "No crop marking defined for this image/video.")
            return

        # Get current image
        image: Image = self.proxy_image_index.data(Qt.ItemDataRole.UserRole)
        crop_rect = self.crop_marking.rect().toRect()

        # Warning dialog
        file_type = "video" if image.is_video else "image"
        reply = QMessageBox.question(
            self, "Apply Crop - Destructive Operation",
            f"This will PERMANENTLY crop the {file_type} file to {crop_rect.width()}x{crop_rect.height()}.\n\n"
            f"The original will be saved as:\n{image.path.name}.backup\n\n"
            f"⚠️  This modifies your working directory, not an export.\n"
            f"💡 Tip: Use File → Export for non-destructive workflows.\n\n"
            f"Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        # Apply the crop
        success, message = apply_crop(Path(image.path), crop_rect)

        if success:
            QMessageBox.information(self, "Success", message + "\n\nReloading directory...")
            # Clear the crop marking from metadata (since it's now applied)
            image.crop = None
            image.target_dimension = None
            image.thumbnail = None
            self.proxy_image_list_model.sourceModel().write_meta_to_disk(image)
            # Reload directory to show updated file
            # Need to access main_window through the model chain
            self.proxy_image_list_model.sourceModel().parent().reload_directory()
        else:
            QMessageBox.critical(self, "Error", message)
