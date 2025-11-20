import re
from PySide6.QtCore import (QModelIndex, QPersistentModelIndex, QPoint,
                            QRect, QSize, Qt, Signal, Slot, QTimer)
from PySide6.QtGui import QImage, QPixmap, QTransform
from PySide6.QtWidgets import (QGraphicsPixmapItem, QGraphicsRectItem,
                               QGraphicsScene, QGraphicsView,
                               QVBoxLayout, QWidget)
from PIL import Image as pilimage
from utils.settings import settings
from models.proxy_image_list_model import ProxyImageListModel
from utils.image import Image, ImageMarking, Marking
from utils.rect import RectPosition
from widgets.video_player import VideoPlayerWidget
from widgets.video_controls import VideoControlsWidget
from widgets.marking import (MarkingItem, MarkingLabel, ResizeHintHUD,
                              marking_colors, calculate_grid)
from widgets.marking_view import ImageGraphicsView


class ImageViewer(QWidget):
    """Main widget coordinating image/video display, marking, and zoom functionality."""

    zoom = Signal(float, name='zoomChanged')
    marking = Signal(ImageMarking, name='markingToAdd')
    accept_crop_addition = Signal(bool, name='allowAdditionOfCrop')
    crop_changed = Signal(object, name='cropChanged')  # Grid type
    rating_changed = Signal(float, name='ratingChanged')
    directory_reload_requested = Signal(name='directoryReloadRequested')

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

        # Check if we should skip this reload
        if not persistent_image_index.isValid():
            return

        if self.inhibit_reload_image and self.proxy_image_index and persistent_image_index == self.proxy_image_index:
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
                            self.video_controls.set_video_info(
                                image.video_metadata,
                                image=image,
                                proxy_model=self.proxy_image_list_model
                            )

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
                self.current_image_item = image_item  # Keep reference to prevent garbage collection!
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
        from widgets.marking import grid

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
        shift_pressed = (event.modifiers() & Qt.KeyboardModifier.ShiftModifier) == Qt.KeyboardModifier.ShiftModifier
        alt_pressed = (event.modifiers() & Qt.KeyboardModifier.AltModifier) == Qt.KeyboardModifier.AltModifier

        # Shift + scroll: horizontal pan; Alt + scroll: vertical pan
        if shift_pressed or alt_pressed:
            scroll_amount = 50  # pixels per scroll step
            if shift_pressed and not alt_pressed:
                # Shift + scroll: horizontal pan
                if event.angleDelta().y() > 0:
                    self.view.horizontalScrollBar().setValue(
                        self.view.horizontalScrollBar().value() - scroll_amount)
                else:
                    self.view.horizontalScrollBar().setValue(
                        self.view.horizontalScrollBar().value() + scroll_amount)
            elif alt_pressed:
                # Alt + scroll: vertical pan
                # Check both x and y deltas in case Alt transforms the scroll
                delta_y = event.angleDelta().y()
                delta_x = event.angleDelta().x()
                delta = delta_y if delta_y != 0 else delta_x

                current = self.view.verticalScrollBar().value()
                if delta > 0:
                    self.view.verticalScrollBar().setValue(current - scroll_amount)
                else:
                    self.view.verticalScrollBar().setValue(current + scroll_amount)
                event.accept()
                return
            event.accept()
            return

        # Standard zoom behavior
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
            if interactive:
                image: Image = self.proxy_image_index.data(Qt.ItemDataRole.UserRole)
                image.crop = rect
                self.proxy_image_list_model.sourceModel().write_meta_to_disk(image)
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
        from widgets.marking import grid

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
                self.proxy_image_list_model.sourceModel().write_meta_to_disk(image)
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

        # Save undo snapshot before editing (for both images and videos)
        undo_saved = False
        try:
            parent = self.parent()
            while parent:
                if hasattr(parent, 'video_editing_controller'):
                    parent.video_editing_controller._save_undo_snapshot(
                        Path(image.path),
                        f"Crop to {crop_rect.width()}x{crop_rect.height()}"
                    )
                    undo_saved = True
                    break
                parent = parent.parent()
        except Exception as e:
            print(f"Warning: Failed to save undo snapshot for crop: {e}")

        # Apply the crop
        success, message = apply_crop(Path(image.path), crop_rect)

        if success:
            QMessageBox.information(self, "Success", message + "\n\nReloading directory...")
            # Clear the crop marking from metadata (since it's now applied)
            image.crop = None
            image.target_dimension = None
            image.thumbnail = None
            self.proxy_image_list_model.sourceModel().write_meta_to_disk(image)
            # Request directory reload via signal
            self.directory_reload_requested.emit()
        else:
            QMessageBox.critical(self, "Error", message)
