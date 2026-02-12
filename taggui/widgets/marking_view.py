"""Graphics view for image marking with insertion mode and context menus."""

from PySide6.QtCore import QSize, Qt, QRect
from PySide6.QtGui import QAction, QActionGroup, QIcon, QMouseEvent, QPainter
from PySide6.QtWidgets import QFrame, QGraphicsView, QGraphicsLineItem, QMenu
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from utils.image import ImageMarking
from utils.rect import RectPosition, map_rect_position_to_cursor
from widgets.marking import MarkingItem, MarkingLabel, grid


class ImageGraphicsView(QGraphicsView):
    """Graphics view handling marking insertion mode, mouse events, and context menus."""

    def __init__(self, scene, image_viewer):
        super().__init__(scene)
        self.setViewport(QOpenGLWidget())
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.showContextMenu)
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setLineWidth(0)
        self.setMidLineWidth(0)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        # Don't steal focus when clicked - prevents image list selection changes
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.viewport().setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # Also set on viewport
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.image_viewer = image_viewer
        MarkingItem.image_view = self
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.last_pos = None
        self._space_pan_active = False
        self._manual_pan_active = False
        self._manual_pan_last_global_pos = None
        self.clear_scene()

    def _should_start_manual_pan(self, event: QMouseEvent) -> bool:
        """Check pan gestures that should move viewport instead of editing marks."""
        if self.insertion_mode or MarkingItem.handle_selected != RectPosition.NONE:
            return False
        if event.button() not in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            return False

        scene_pos = self.mapToScene(event.pos())
        item = self.scene().itemAt(scene_pos, self.transform())
        while item is not None:
            if isinstance(item, MarkingItem):
                return False
            item = item.parentItem()

        return True

    def _pan_viewport_by(self, delta):
        self.horizontalScrollBar().setValue(
            self.horizontalScrollBar().value() - int(delta.x()))
        self.verticalScrollBar().setValue(
            self.verticalScrollBar().value() - int(delta.y()))

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
        if self._should_start_manual_pan(event):
            self._manual_pan_active = True
            self._manual_pan_last_global_pos = event.globalPosition().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

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
        if self._manual_pan_active:
            current_global = event.globalPosition().toPoint()
            if self._manual_pan_last_global_pos is not None:
                delta = current_global - self._manual_pan_last_global_pos
                self._pan_viewport_by(delta)
            self._manual_pan_last_global_pos = current_global
            event.accept()
            return

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

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._manual_pan_active and event.button() in (
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.MiddleButton,
        ):
            self._manual_pan_active = False
            self._manual_pan_last_global_pos = None
            if self._space_pan_active:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self._space_pan_active = True
            if not self._manual_pan_active:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Delete:
            edited_item = self.scene().focusItem()
            if not (isinstance(edited_item, MarkingLabel) and
                edited_item.textInteractionFlags() == Qt.TextEditorInteraction):
                # Delete marking only when not editing the label
                # Get selected items from scene
                selected = self.scene().selectedItems()
                if selected:
                    self.image_viewer.delete_markings(selected)
                else:
                    self.image_viewer.delete_markings()
            return
        elif event.key() in [Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down]:
            # Shift + arrow key scrolling when zoomed (avoids conflict with Ctrl+hint binding)
            shift_pressed = (event.modifiers() & Qt.KeyboardModifier.ShiftModifier) == Qt.KeyboardModifier.ShiftModifier
            if MarkingItem.handle_selected == RectPosition.NONE and shift_pressed and not event.isAutoRepeat():
                scroll_amount = 30  # pixels per arrow key press
                if event.key() == Qt.Key.Key_Left:
                    self.horizontalScrollBar().setValue(
                        self.horizontalScrollBar().value() - scroll_amount)
                    event.accept()
                    return
                elif event.key() == Qt.Key.Key_Right:
                    self.horizontalScrollBar().setValue(
                        self.horizontalScrollBar().value() + scroll_amount)
                    event.accept()
                    return
                elif event.key() == Qt.Key.Key_Up:
                    self.verticalScrollBar().setValue(
                        self.verticalScrollBar().value() - scroll_amount)
                    event.accept()
                    return
                elif event.key() == Qt.Key.Key_Down:
                    self.verticalScrollBar().setValue(
                        self.verticalScrollBar().value() + scroll_amount)
                    event.accept()
                    return
            return
        elif event.key() == Qt.Key.Key_C:
            # C key for crop mode - don't check modifiers, just activate crop
            if MarkingItem.handle_selected == RectPosition.NONE:
                self.image_viewer.marking_to_add = ImageMarking.CROP
                self.set_insertion_mode(ImageMarking.CROP)
            event.accept()
            # Don't call super - we handled this completely
            return

        # Handle Ctrl modifier for hint/exclude/crop modes (only if not C key)
        if MarkingItem.handle_selected == RectPosition.NONE:
            if ((event.modifiers() & Qt.KeyboardModifier.ControlModifier) ==
                    Qt.KeyboardModifier.ControlModifier):
                if ((event.modifiers() & Qt.KeyboardModifier.AltModifier) ==
                        Qt.KeyboardModifier.AltModifier):
                    self.image_viewer.marking_to_add = ImageMarking.EXCLUDE
                    self.set_insertion_mode(ImageMarking.EXCLUDE)
                    return
                elif ((event.modifiers() & Qt.KeyboardModifier.ShiftModifier) ==
                        Qt.KeyboardModifier.ShiftModifier):
                    self.image_viewer.marking_to_add = ImageMarking.CROP
                    self.set_insertion_mode(ImageMarking.CROP)
                    return
                else:
                    self.image_viewer.marking_to_add = ImageMarking.HINT
                    self.set_insertion_mode(ImageMarking.HINT)
                    return

        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self._space_pan_active = False
            if not self._manual_pan_active:
                self.unsetCursor()
            event.accept()
            return
        if MarkingItem.handle_selected == RectPosition.NONE:
            # Reset mode when Ctrl is released or any marking key (C) is released
            if event.key() in [Qt.Key.Key_Control, Qt.Key.Key_C]:
                self.set_insertion_mode(ImageMarking.NONE)
        super().keyReleaseEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.image_viewer.is_zoom_to_fit:
           self.image_viewer.zoom_fit()
