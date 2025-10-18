"""Graphics view for image marking with insertion mode and context menus."""

from PySide6.QtCore import QSize, Qt, QRect
from PySide6.QtGui import QAction, QActionGroup, QIcon, QMouseEvent, QPainter
from PySide6.QtWidgets import QGraphicsView, QGraphicsLineItem, QMenu

from utils.image import ImageMarking
from utils.rect import RectPosition, map_rect_position_to_cursor
from widgets.marking import MarkingItem, MarkingLabel, grid


class ImageGraphicsView(QGraphicsView):
    """Graphics view handling marking insertion mode, mouse events, and context menus."""

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
        # Check if clicking on an existing marking item first
        scene_pos = self.mapToScene(event.pos())
        item_at_pos = self.scene().itemAt(scene_pos, self.transform())

        # Walk up the parent chain to find if we're clicking on a MarkingItem
        current_item = item_at_pos
        while current_item:
            if isinstance(current_item, MarkingItem):
                # Let the MarkingItem handle this event
                super().mousePressEvent(event)
                return
            current_item = current_item.parentItem()

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
