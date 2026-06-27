"""Graphics view for image marking with insertion mode and context menus."""

from PySide6.QtCore import QSize, Qt, QRect
from PySide6.QtGui import QAction, QActionGroup, QCursor, QIcon, QMouseEvent, QPainter
from PySide6.QtWidgets import QFrame, QGraphicsView, QGraphicsLineItem, QMenu, QWidget
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from utils.image import ImageMarking
from utils.settings import settings, DEFAULT_SETTINGS
from utils.rect import RectPosition, map_rect_position_to_cursor
from widgets.ideogram_region_item import IdeogramRegionItem
from widgets.marking import MarkingItem, MarkingLabel, grid


class ImageGraphicsView(QGraphicsView):
    """Graphics view handling marking insertion mode, mouse events, and context menus."""

    def __init__(self, scene, image_viewer):
        super().__init__(scene)
        backend_name = str(
            settings.value(
                'video_playback_backend',
                defaultValue=DEFAULT_SETTINGS.get('video_playback_backend', 'qt_hybrid'),
                type=str,
            ) or ''
        ).strip().lower()
        use_native_video_backend = backend_name == 'vlc_experimental'
        if use_native_video_backend:
            # VLC still embeds a native child surface and is unreliable when
            # the view itself uses an OpenGL viewport.
            self.setViewport(QWidget())
        else:
            self.setViewport(QOpenGLWidget())
            # QOpenGLWidget-backed views are safer with full viewport updates,
            # especially during large pans/zooms on high-resolution displays.
            self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
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
        self._temporarily_raised_ideogram_item = None
        self._temporarily_disabled_ideogram_items = []
        self._forced_ideogram_resize_item = None
        self._temporarily_raised_marking_item = None
        self._temporarily_disabled_marking_items = []
        self.clear_scene()

    def _interactive_region_at(self, scene_pos):
        for item in self.scene().items(scene_pos):
            current = item
            while current is not None:
                if isinstance(current, (MarkingItem, IdeogramRegionItem)):
                    return current
                current = current.parentItem()
        return None

    def _ideogram_region_at(self, scene_pos):
        for item in self.scene().items(scene_pos):
            current = item
            while current is not None:
                if isinstance(current, IdeogramRegionItem):
                    return current
                current = current.parentItem()
        return None

    def _selected_ideogram_resize_region_at(self, scene_pos):
        for item in self._selected_ideogram_region_candidates():
            if item.resize_handle_at_scene_pos(scene_pos) != RectPosition.NONE:
                return item
        return None

    def _marking_regions_at(self, scene_pos):
        regions = []
        seen = set()
        for scene_item in self.scene().items(scene_pos):
            current = scene_item
            while current is not None:
                if isinstance(current, MarkingItem):
                    if id(current) not in seen:
                        regions.append(current)
                        seen.add(id(current))
                    break
                current = current.parentItem()
        return regions

    @staticmethod
    def _marking_area(item):
        rect = item.rect().normalized()
        return max(0.0, rect.width()) * max(0.0, rect.height())

    def _selected_marking_resize_region_at(self, scene_pos):
        candidates = [
            item for item in self.scene().selectedItems()
            if isinstance(item, MarkingItem)
        ]
        candidates.sort(key=self._marking_area)
        for item in candidates:
            handle = item.handleAt(item.mapFromScene(scene_pos))
            if handle not in (RectPosition.NONE, RectPosition.CENTER):
                return item
        return None

    def _preferred_marking_region_at(self, scene_pos):
        candidates = self._marking_regions_at(scene_pos)
        if not candidates:
            return None
        return min(candidates, key=self._marking_area)

    def _prepare_marking_region_for_press(self, target, scene_pos):
        self._restore_transient_marking_regions()
        if target is None:
            return
        self._temporarily_raised_marking_item = (target, target.zValue())
        target.setZValue(max(target.zValue(), 3000.0))
        disabled = []
        for item in self._marking_regions_at(scene_pos):
            if item is target:
                continue
            disabled.append((item, item.acceptedMouseButtons()))
            item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._temporarily_disabled_marking_items = disabled

    def _restore_transient_marking_regions(self):
        disabled = self._temporarily_disabled_marking_items
        self._temporarily_disabled_marking_items = []
        for item, buttons in disabled:
            try:
                item.setAcceptedMouseButtons(buttons)
            except RuntimeError:
                pass
        raised = self._temporarily_raised_marking_item
        self._temporarily_raised_marking_item = None
        if raised is not None:
            item, z_value = raised
            try:
                item.setZValue(z_value)
            except RuntimeError:
                pass

    def _selected_ideogram_region_candidates(self):
        candidates = []
        seen = set()

        def add_candidate(item):
            if (
                isinstance(item, IdeogramRegionItem)
                and id(item) not in seen
            ):
                candidates.append(item)
                seen.add(id(item))

        selected_index = getattr(
            self.image_viewer,
            "_last_selected_ideogram_index",
            None,
        )
        overlay_items = getattr(self.image_viewer, "ideogram_overlay_items", [])
        if selected_index is not None:
            for item in overlay_items:
                if int(getattr(item, "element_index", -1)) == int(selected_index):
                    add_candidate(item)
        for item in overlay_items:
            if bool(getattr(item, "_highlighted", False)):
                add_candidate(item)
        for item in self.scene().selectedItems():
            add_candidate(item)
        return candidates

    def _raise_ideogram_region_for_press(self, item):
        self._restore_temporarily_raised_ideogram_region()
        if item is None:
            return
        self._temporarily_raised_ideogram_item = item
        item.setZValue(max(item.zValue(), 2000.0))

    def _disable_overlapping_ideogram_regions_for_press(self, target, scene_pos):
        self._restore_temporarily_disabled_ideogram_regions()
        if target is None:
            return
        disabled = []
        seen = set()
        for item in self.scene().items(scene_pos):
            current = item
            while current is not None:
                if isinstance(current, IdeogramRegionItem):
                    if current is not target and id(current) not in seen:
                        seen.add(id(current))
                        disabled.append((current, current.acceptedMouseButtons()))
                        current.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                    break
                current = current.parentItem()
        self._temporarily_disabled_ideogram_items = disabled

    def _restore_temporarily_disabled_ideogram_regions(self):
        disabled = self._temporarily_disabled_ideogram_items
        self._temporarily_disabled_ideogram_items = []
        for item, buttons in disabled:
            try:
                item.setAcceptedMouseButtons(buttons)
            except RuntimeError:
                pass

    def _restore_temporarily_raised_ideogram_region(self):
        item = self._temporarily_raised_ideogram_item
        self._temporarily_raised_ideogram_item = None
        if item is None:
            return
        try:
            base_z = item.data(1)
            if base_z is not None:
                item.setZValue(float(base_z))
        except RuntimeError:
            pass

    def _should_start_manual_pan(self, event: QMouseEvent) -> bool:
        """Check pan gestures that should move viewport instead of editing marks."""
        if self.insertion_mode or MarkingItem.handle_selected != RectPosition.NONE:
            return False
        if event.button() not in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            return False

        scene_pos = self.mapToScene(event.pos())
        if self._interactive_region_at(scene_pos) is not None:
            return False

        return True

    def restore_transient_ideogram_interaction_state(self):
        if self._forced_ideogram_resize_item is not None:
            try:
                self._forced_ideogram_resize_item.finish_forced_resize()
            except RuntimeError:
                pass
            self._forced_ideogram_resize_item = None
        self._restore_temporarily_disabled_ideogram_regions()
        self._restore_temporarily_raised_ideogram_region()
        self._restore_transient_marking_regions()

    def _set_view_cursor(self, cursor):
        if cursor is None:
            self.unsetCursor()
            self.viewport().unsetCursor()
            return
        self.setCursor(cursor)
        self.viewport().setCursor(cursor)

    def _pan_viewport_by(self, delta):
        self.horizontalScrollBar().setValue(
            self.horizontalScrollBar().value() - int(delta.x()))
        self.verticalScrollBar().setValue(
            self.verticalScrollBar().value() - int(delta.y()))

    def showContextMenu(self, pos):
        scene_pos = self.mapToScene(pos)
        item = (
            self._selected_marking_resize_region_at(scene_pos)
            or self._preferred_marking_region_at(scene_pos)
            or self.scene().itemAt(scene_pos, self.transform())
        )
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
        self.restore_transient_ideogram_interaction_state()
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
        color_pick_handler = getattr(
            self.image_viewer,
            "handle_ideogram_color_pick_press",
            None,
        )
        if callable(color_pick_handler):
            try:
                if bool(color_pick_handler(event.pos(), event.button())):
                    event.accept()
                    return
            except Exception:
                pass
        if event.button() == Qt.MouseButton.LeftButton and not self.insertion_mode:
            zone_press_handler = getattr(self.image_viewer, "handle_video_surface_zone_press", None)
            if callable(zone_press_handler):
                try:
                    if bool(zone_press_handler(event.pos())):
                        event.accept()
                        return
                except Exception:
                    pass

        scene_pos = self.mapToScene(event.pos())
        selected_marking_resize_item = self._selected_marking_resize_region_at(
            scene_pos
        )
        selected_resize_item = self._selected_ideogram_resize_region_at(scene_pos)
        if (
            selected_resize_item is not None
            and event.button() == Qt.MouseButton.LeftButton
            and selected_resize_item.begin_forced_resize(
                scene_pos,
                event.modifiers(),
            )
        ):
            self._forced_ideogram_resize_item = selected_resize_item
            cursor = map_rect_position_to_cursor(
                selected_resize_item.resize_handle_at_scene_pos(scene_pos)
            )
            self._set_view_cursor(cursor)
            event.accept()
            return

        if self._should_start_manual_pan(event):
            if event.button() == Qt.MouseButton.LeftButton:
                clear_selection = getattr(
                    self.image_viewer,
                    "clear_ideogram_selection",
                    None,
                )
                if callable(clear_selection):
                    clear_selection()
            self._manual_pan_active = True
            self._manual_pan_last_global_pos = event.globalPosition().toPoint()
            fast_pan_mode_setter = getattr(self.image_viewer, "_set_fast_pan_visual_mode", None)
            if callable(fast_pan_mode_setter):
                fast_pan_mode_setter(True)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        # Check if clicking on an existing marking item first
        preferred_marking_item = (
            selected_marking_resize_item
            or self._preferred_marking_region_at(scene_pos)
        )
        self._prepare_marking_region_for_press(
            preferred_marking_item,
            scene_pos,
        )
        self._raise_ideogram_region_for_press(selected_resize_item)
        self._disable_overlapping_ideogram_regions_for_press(
            selected_resize_item,
            scene_pos,
        )
        interactive_item = self._interactive_region_at(scene_pos)
        if interactive_item is not None:
            if isinstance(interactive_item, IdeogramRegionItem) and self.insertion_mode:
                self.set_insertion_mode(ImageMarking.NONE)
            if (
                isinstance(interactive_item, MarkingItem)
                and not (
                    event.modifiers()
                    & (
                        Qt.KeyboardModifier.ControlModifier
                        | Qt.KeyboardModifier.ShiftModifier
                        | Qt.KeyboardModifier.MetaModifier
                    )
                )
            ):
                clear_selection = getattr(
                    self.image_viewer,
                    "clear_ideogram_selection",
                    None,
                )
                if callable(clear_selection):
                    clear_selection()
            super().mousePressEvent(event)
            return

        if self.insertion_mode and event.button() == Qt.MouseButton.LeftButton:
            rect_type = self.image_viewer.marking_to_add
            if rect_type == ImageMarking.NONE:
                if ((event.modifiers() & Qt.KeyboardModifier.AltModifier) ==
                    Qt.KeyboardModifier.AltModifier):
                    rect_type = ImageMarking.EXCLUDE
                else:
                    rect_type = ImageMarking.HINT

            proxy_index = self.image_viewer.proxy_image_index
            source_model = proxy_index.model().sourceModel() if proxy_index.isValid() else None
            image = proxy_index.data(Qt.ItemDataRole.UserRole) if proxy_index.isValid() else None
            if source_model is not None:
                source_model.add_image_to_undo_stack(
                    image,
                    action_name=f'Add {rect_type.value}',
                    should_ask_for_confirmation=False,
                )

            self.image_viewer.add_rectangle(QRect(self.last_pos, QSize(0, 0)),
                                            rect_type, interactive=True)
            self.set_insertion_mode(ImageMarking.NONE)
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._forced_ideogram_resize_item is not None:
            self._forced_ideogram_resize_item.forced_drag_to_scene_pos(
                self.mapToScene(event.pos())
            )
            event.accept()
            return
        color_pick_move_handler = getattr(
            self.image_viewer,
            "handle_ideogram_color_pick_move",
            None,
        )
        if callable(color_pick_move_handler):
            try:
                if bool(color_pick_move_handler(event.pos())):
                    event.accept()
                    return
            except Exception:
                pass
        zone_move_handler = getattr(self.image_viewer, "handle_video_surface_zone_move", None)
        if callable(zone_move_handler):
            try:
                if bool(zone_move_handler(event.pos())):
                    event.accept()
                    return
            except Exception:
                pass
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
            selected_marking_resize_item = self._selected_marking_resize_region_at(
                scene_pos
            )
            if selected_marking_resize_item is not None:
                handle = selected_marking_resize_item.handleAt(
                    selected_marking_resize_item.mapFromScene(scene_pos)
                )
                cursor = map_rect_position_to_cursor(handle)
            selected_resize_item = self._selected_ideogram_resize_region_at(scene_pos)
            if cursor is None and selected_resize_item is not None:
                cursor = map_rect_position_to_cursor(
                    selected_resize_item.resize_handle_at_scene_pos(scene_pos)
                )
                self.setDragMode(QGraphicsView.DragMode.NoDrag)
                self._set_view_cursor(cursor)
                if ((event.modifiers() & Qt.KeyboardModifier.ShiftModifier) ==
                    Qt.KeyboardModifier.ShiftModifier):
                    self.last_pos = grid.snap(scene_pos.toPoint()).toPoint()
                else:
                    self.last_pos = scene_pos.toPoint()
                event.accept()
                return
            preferred_marking_item = self._preferred_marking_region_at(scene_pos)
            if cursor is None and preferred_marking_item is not None:
                handle = preferred_marking_item.handleAt(
                    preferred_marking_item.mapFromScene(scene_pos)
                )
                if handle != RectPosition.NONE:
                    cursor = map_rect_position_to_cursor(handle)
            for item in items:
                if cursor is not None:
                    break
                if isinstance(item, IdeogramRegionItem):
                    cursor = item.cursor().shape()
                    break
                if isinstance(item, MarkingItem):
                    handle = item.handleAt(scene_pos)
                    if handle == RectPosition.NONE:
                        continue
                    cursor = map_rect_position_to_cursor(handle)
                    break
        if cursor is None:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self._set_view_cursor(None)
        else:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self._set_view_cursor(cursor)

        if ((event.modifiers() & Qt.KeyboardModifier.ShiftModifier) ==
            Qt.KeyboardModifier.ShiftModifier):
            self.last_pos = grid.snap(scene_pos.toPoint()).toPoint()
        else:
            self.last_pos = scene_pos.toPoint()

        if self.insertion_mode:
            self.update_lines_pos()
        else:
            super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        item = self.scene().itemAt(self.mapToScene(event.pos()), self.transform())
        if isinstance(item, MarkingLabel):
            super().mouseDoubleClickEvent(event)
            return
        if event.button() == Qt.MouseButton.LeftButton and not self.insertion_mode:
            zoom_handler = getattr(self.image_viewer, "apply_floating_double_click_zoom", None)
            if callable(zoom_handler):
                scene_pos = self.mapToScene(event.pos())
                view_pos = event.pos()
                try:
                    handled = bool(zoom_handler(scene_anchor_pos=scene_pos, view_anchor_pos=view_pos))
                except Exception:
                    handled = False
                if handled:
                    event.accept()
                    return
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._forced_ideogram_resize_item is not None:
            self._forced_ideogram_resize_item.finish_forced_resize()
            self._forced_ideogram_resize_item = None
            self._restore_temporarily_disabled_ideogram_regions()
            self._restore_temporarily_raised_ideogram_region()
            self._set_view_cursor(None)
            event.accept()
            return
        zone_release_handler = getattr(self.image_viewer, "handle_video_surface_zone_release", None)
        if callable(zone_release_handler):
            try:
                if bool(zone_release_handler(event.pos())):
                    event.accept()
                    return
            except Exception:
                pass
        if self._manual_pan_active and event.button() in (
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.MiddleButton,
        ):
            self._manual_pan_active = False
            self._manual_pan_last_global_pos = None
            fast_pan_mode_setter = getattr(self.image_viewer, "_set_fast_pan_visual_mode", None)
            if callable(fast_pan_mode_setter):
                fast_pan_mode_setter(False)
            if self._space_pan_active:
                self._set_view_cursor(Qt.CursorShape.OpenHandCursor)
            else:
                self._set_view_cursor(None)
            self._restore_temporarily_disabled_ideogram_regions()
            self._restore_temporarily_raised_ideogram_region()
            self._restore_transient_marking_regions()
            event.accept()
            return
        try:
            super().mouseReleaseEvent(event)
        finally:
            self._restore_temporarily_disabled_ideogram_regions()
            self._restore_temporarily_raised_ideogram_region()
            self._restore_transient_marking_regions()

    def keyPressEvent(self, event):
        edited_item = self.scene().focusItem()
        is_editing_label = (
            isinstance(edited_item, MarkingLabel)
            and bool(
                edited_item.textInteractionFlags()
                & Qt.TextInteractionFlag.TextEditorInteraction
            )
        )
        if is_editing_label:
            super().keyPressEvent(event)
            return

        if event.key() == Qt.Key.Key_Space:
            self._space_pan_active = True
            if not self._manual_pan_active:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        selected = self.scene().selectedItems()
        ideogram_indices = [
            int(item.element_index)
            for item in selected
            if isinstance(item, IdeogramRegionItem)
        ]
        ctrl_pressed = bool(
            event.modifiers()
            & (
                Qt.KeyboardModifier.ControlModifier
                | Qt.KeyboardModifier.MetaModifier
            )
        )
        if ctrl_pressed and not is_editing_label:
            if event.key() == Qt.Key.Key_C and ideogram_indices:
                self.image_viewer.ideogram_elements_copy_requested.emit(
                    sorted(set(ideogram_indices))
                )
                event.accept()
                return
            if event.key() == Qt.Key.Key_V:
                self.image_viewer.ideogram_elements_paste_requested.emit()
                event.accept()
                return
            if event.key() == Qt.Key.Key_D and ideogram_indices:
                self.image_viewer.ideogram_elements_duplicate_requested.emit(
                    sorted(set(ideogram_indices))
                )
                event.accept()
                return
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if not is_editing_label:
                # Delete marking only when not editing the label
                # Get selected items from scene
                selected_markings = [
                    item for item in selected
                    if isinstance(item, MarkingItem)
                ]
                if selected_markings:
                    self.image_viewer.delete_markings(selected_markings)
                elif ideogram_indices:
                    self.image_viewer.delete_selected_ideogram_regions()
                elif selected:
                    self.image_viewer.delete_markings(selected)
                else:
                    self.image_viewer.delete_markings()
            event.accept()
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
                cursor_pos = self.viewport().mapFromGlobal(QCursor.pos())
                if self.viewport().rect().contains(cursor_pos):
                    scene_pos = self.mapToScene(cursor_pos)
                    if self._ideogram_region_at(scene_pos) is not None:
                        event.accept()
                        return
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
