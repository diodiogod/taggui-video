import re
from PySide6.QtCore import (QEvent, QModelIndex, QPersistentModelIndex, QPoint, QPointF,
                            QRect, QRectF, QSize, Qt, Signal, Slot, QTimer)
from PySide6.QtGui import QColor, QCursor, QImage, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import (QGraphicsItem, QGraphicsPixmapItem, QGraphicsRectItem,
                               QGraphicsScene, QGraphicsView,
                               QVBoxLayout, QWidget, QStyleOptionGraphicsItem)
from PIL import Image as pilimage
from utils.settings import settings, DEFAULT_SETTINGS
from models.proxy_image_list_model import ProxyImageListModel
from utils.image import Image, ImageMarking, Marking
from utils.rect import RectPosition
from widgets.video_player import VideoPlayerWidget
from widgets.video_controls import VideoControlsWidget
from widgets.marking import (MarkingItem, MarkingLabel, ResizeHintHUD,
                              marking_colors, calculate_grid)
from widgets.marking_view import ImageGraphicsView

COMPARE_FIT_MODE_PRESERVE = 'preserve'
COMPARE_FIT_MODE_FILL = 'fill'
COMPARE_FIT_MODE_STRETCH = 'stretch'
COMPARE_FIT_MODE_OPTIONS = (
    (COMPARE_FIT_MODE_PRESERVE, 'Preserve Aspect Ratio'),
    (COMPARE_FIT_MODE_FILL, 'Fill (Crop)'),
    (COMPARE_FIT_MODE_STRETCH, 'Stretch (Distorts)'),
)


def pil_to_qimage(pil_image):
    """Convert PIL image to QImage properly"""
    pil_image = pil_image.convert("RGBA")
    data = pil_image.tobytes("raw", "RGBA")
    qimage = QImage(data, pil_image.width, pil_image.height, QImage.Format_RGBA8888)
    return qimage




class ImageViewer(QWidget):
    """Main widget coordinating image/video display, marking, and zoom functionality."""

    zoom = Signal(float, name='zoomChanged')
    marking = Signal(ImageMarking, name='markingToAdd')
    accept_crop_addition = Signal(bool, name='allowAdditionOfCrop')
    crop_changed = Signal(object, name='cropChanged')  # Grid type
    rating_changed = Signal(float, name='ratingChanged')
    directory_reload_requested = Signal(name='directoryReloadRequested')
    activated = Signal(name='viewerActivated')

    def __init__(self, proxy_image_list_model: ProxyImageListModel, *, is_spawned_viewer: bool = False):
        super().__init__()
        self.is_spawned_viewer = bool(is_spawned_viewer)
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
        self._scene_padding_px = 0

        self.view = ImageGraphicsView(self.scene, self)
        self.view.setOptimizationFlags(QGraphicsView.DontSavePainterState)
        self.crop_marking: ImageMarking | None = None
        settings.change.connect(self.setting_change)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.setLayout(layout)

        self.proxy_image_index: QPersistentModelIndex = QPersistentModelIndex()
        self._viewer_model_resetting = False
        self.marking_items: list[MarkingItem] = []

        self.view.wheelEvent = self.wheelEvent

        # Video player and controls
        self.video_player = VideoPlayerWidget()
        # Pre-warm the MPV GL widget so its GL context is initialized during
        # startup (while the window is still loading) rather than on first play,
        # which would cause a ~1s full-window flash.
        QTimer.singleShot(0, lambda: self.video_player.prewarm_gl_widget(self.view))
        self.current_video_item = None
        self.current_image_item = None
        self._compare_mode_active = False
        self._compare_base_index = QPersistentModelIndex()
        self._compare_right_index = QPersistentModelIndex()
        self._compare_split_ratio = 0.5
        self._compare_reveal_progress = 1.0
        self._compare_overlay_item = None
        self._compare_clip_item = None
        self._compare_divider_item = None
        self._compare_last_viewer_x = None
        self._compare_overlay_offset = QPointF(0.0, 0.0)
        compare_fit_mode = str(
            settings.value(
                'compare_fit_mode',
                defaultValue=DEFAULT_SETTINGS.get('compare_fit_mode', COMPARE_FIT_MODE_PRESERVE),
                type=str,
            )
            or COMPARE_FIT_MODE_PRESERVE
        ).strip().lower()
        if compare_fit_mode not in {COMPARE_FIT_MODE_PRESERVE, COMPARE_FIT_MODE_FILL, COMPARE_FIT_MODE_STRETCH}:
            compare_fit_mode = COMPARE_FIT_MODE_PRESERVE
        self._compare_fit_mode = compare_fit_mode
        self._compare_divider_overlay = QWidget(self)
        self._compare_divider_overlay.setObjectName("imageViewerCompareDivider")
        self._compare_divider_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._compare_divider_overlay.setStyleSheet("background-color: rgba(255, 255, 255, 230);")
        self._compare_divider_overlay.hide()
        self._compare_divider_overlay.raise_()
        self._compare_reveal_timer = QTimer(self)
        self._compare_reveal_timer.setInterval(16)
        self._compare_reveal_timer.timeout.connect(self._tick_compare_reveal)
        self.video_controls = VideoControlsWidget(self)
        self.video_controls._is_spawned_owner = self.is_spawned_viewer
        self.video_controls.setVisible(False)
        # Spawned viewers always use auto-hide to keep multi-view playback responsive.
        if self.is_spawned_viewer:
            self.video_controls_auto_hide = True
        else:
            # Main viewer follows user setting (inverted from always_show setting).
            always_show = settings.value('video_always_show_controls', False, type=bool)
            self.video_controls_auto_hide = not always_show
        self._controls_visible = False
        self._controls_hover_inside = False
        self._is_video_loaded = False
        self._floating_double_click_return_scale = None
        self._floating_last_auto_double_click_zoom_scale = None
        self._pending_controls_stabilize = True

        # Timer for auto-hiding controls
        self._controls_hide_timer = QTimer(self)
        self._controls_hide_timer.setSingleShot(True)
        self._controls_hide_timer.timeout.connect(self._hide_controls)

        # Guard against stale index access during proxy/source model resets.
        self.proxy_image_list_model.modelAboutToBeReset.connect(self._on_proxy_model_about_to_reset)
        self.proxy_image_list_model.modelReset.connect(self._on_proxy_model_reset)

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
                min_w = self.video_controls.minimum_runtime_width()
                controls_width = max(min_w, min(controls_width, self.width()))  # Clamp
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
        self.video_controls.installEventFilter(self)
        self.view.installEventFilter(self)
        self.view.viewport().installEventFilter(self)
        self._refresh_video_surface_event_filters()

    def _iter_video_surface_widgets(self):
        """Yield live native video surface widgets used by backend renderers."""
        player = getattr(self, "video_player", None)
        if player is None:
            return
        for attr in ("vlc_widget", "mpv_widget"):
            widget = getattr(player, attr, None)
            if isinstance(widget, QWidget):
                yield widget

    def _refresh_video_surface_event_filters(self):
        """Attach viewer event filter to backend video surface widgets."""
        for widget in self._iter_video_surface_widgets():
            try:
                widget.installEventFilter(self)
                widget.setMouseTracking(True)
            except RuntimeError:
                continue

    def set_scene_padding(self, padding_px: int):
        """Set scene padding around media for this viewer."""
        self._scene_padding_px = max(0, int(padding_px))

        current_item = None
        if self.current_video_item is not None:
            current_item = self.current_video_item
        elif self.current_image_item is not None:
            current_item = self.current_image_item
        if current_item is not None:
            self._set_scene_rect_for_item(current_item)

    def _set_scene_rect_for_item(self, item):
        """Fit scene rect to one media item with optional padding."""
        if item is None:
            return
        padding = int(getattr(self, '_scene_padding_px', 0))
        rect = item.boundingRect().adjusted(-padding, -padding, padding, padding)
        self.scene.setSceneRect(rect)

    def is_compare_mode_active(self) -> bool:
        return bool(self._compare_mode_active)

    def get_compare_base_index(self) -> QModelIndex:
        if self._compare_mode_active and self._compare_base_index.isValid():
            return self._normalize_proxy_index(self._compare_base_index)
        return self._normalize_proxy_index(self.proxy_image_index)

    def _is_static_image_index(self, proxy_index: QModelIndex) -> bool:
        if not proxy_index.isValid():
            return False
        try:
            image = proxy_index.data(Qt.ItemDataRole.UserRole)
            return bool(image is not None and not bool(getattr(image, "is_video", False)))
        except Exception:
            return False

    def _load_static_pixmap_for_proxy_index(self, proxy_index: QModelIndex) -> QPixmap:
        proxy_index = self._normalize_proxy_index(proxy_index)
        if not proxy_index.isValid():
            return QPixmap()
        image = self._safe_get_image(proxy_index)
        if image is None or bool(getattr(image, "is_video", False)):
            return QPixmap()

        from PySide6.QtGui import QImageReader
        reader = QImageReader(str(image.path))
        reader.setAutoTransform(True)
        qimage = reader.read()
        if qimage.isNull():
            pil_image = pilimage.open(image.path)
            qimage = pil_to_qimage(pil_image)
        return QPixmap.fromImage(qimage)

    def _clear_compare_scene_items(self):
        for attr in ("_compare_overlay_item", "_compare_clip_item", "_compare_divider_item"):
            item = getattr(self, attr, None)
            if item is None:
                continue
            try:
                self.scene.removeItem(item)
            except Exception:
                pass
            setattr(self, attr, None)
        self._compare_overlay_offset = QPointF(0.0, 0.0)

    def get_compare_fit_mode(self) -> str:
        mode = str(getattr(self, "_compare_fit_mode", COMPARE_FIT_MODE_PRESERVE) or COMPARE_FIT_MODE_PRESERVE).strip().lower()
        if mode not in {COMPARE_FIT_MODE_PRESERVE, COMPARE_FIT_MODE_FILL, COMPARE_FIT_MODE_STRETCH}:
            return COMPARE_FIT_MODE_PRESERVE
        return mode

    def get_compare_fit_mode_options(self):
        return tuple(COMPARE_FIT_MODE_OPTIONS)

    def set_compare_fit_mode(self, mode: str, *, persist: bool = True) -> bool:
        mode = str(mode or COMPARE_FIT_MODE_PRESERVE).strip().lower()
        if mode not in {COMPARE_FIT_MODE_PRESERVE, COMPARE_FIT_MODE_FILL, COMPARE_FIT_MODE_STRETCH}:
            return False
        changed = mode != self.get_compare_fit_mode()
        self._compare_fit_mode = mode
        if persist:
            settings.setValue('compare_fit_mode', mode)
        if self._compare_mode_active:
            self._refresh_compare_overlay_pixmap(reset_reveal=False)
        return changed

    def _prepare_compare_overlay_pixmap(self, base_size: QSize, incoming_pixmap: QPixmap):
        if base_size.width() <= 0 or base_size.height() <= 0 or incoming_pixmap.isNull():
            return incoming_pixmap, QPointF(0.0, 0.0)

        mode = self.get_compare_fit_mode()
        if mode == COMPARE_FIT_MODE_STRETCH:
            scaled = incoming_pixmap.scaled(
                base_size,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            return scaled, QPointF(0.0, 0.0)

        if mode == COMPARE_FIT_MODE_PRESERVE:
            scaled = incoming_pixmap.scaled(
                base_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            offset_x = (float(base_size.width()) - float(scaled.width())) * 0.5
            offset_y = (float(base_size.height()) - float(scaled.height())) * 0.5

            # Compose onto an opaque matte so the background image does not
            # bleed through preserve-mode bars while scrubbing compare split.
            matte_color = self.view.palette().color(self.view.viewport().backgroundRole())
            matte_color.setAlpha(255)
            composed = QPixmap(base_size)
            composed.fill(matte_color)
            painter = QPainter(composed)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawPixmap(int(round(offset_x)), int(round(offset_y)), scaled)
            painter.end()
            return composed, QPointF(0.0, 0.0)

        aspect_mode = (
            Qt.AspectRatioMode.KeepAspectRatioByExpanding
            if mode == COMPARE_FIT_MODE_FILL
            else Qt.AspectRatioMode.KeepAspectRatio
        )
        scaled = incoming_pixmap.scaled(
            base_size,
            aspect_mode,
            Qt.TransformationMode.SmoothTransformation,
        )
        offset_x = (float(base_size.width()) - float(scaled.width())) * 0.5
        offset_y = (float(base_size.height()) - float(scaled.height())) * 0.5
        return scaled, QPointF(offset_x, offset_y)

    def _refresh_compare_overlay_pixmap(self, *, reset_reveal: bool):
        if not self._compare_mode_active:
            return
        overlay_item = self._compare_overlay_item
        base_item = self.current_image_item
        incoming_proxy = self._normalize_proxy_index(self._compare_right_index)
        if overlay_item is None or base_item is None or not incoming_proxy.isValid():
            return

        base_pixmap = base_item.pixmap()
        incoming_pixmap = self._load_static_pixmap_for_proxy_index(incoming_proxy)
        if base_pixmap.isNull() or incoming_pixmap.isNull():
            return

        prepared_pixmap, overlay_offset = self._prepare_compare_overlay_pixmap(base_pixmap.size(), incoming_pixmap)
        overlay_item.setPixmap(prepared_pixmap)
        self._compare_overlay_offset = overlay_offset
        if reset_reveal:
            self._compare_reveal_progress = 0.0
            self._compare_reveal_timer.start()
        self._update_compare_overlay_geometry()

    def _tick_compare_reveal(self):
        if not self._compare_mode_active:
            self._compare_reveal_timer.stop()
            return
        self._compare_reveal_progress = min(1.0, float(self._compare_reveal_progress) + 0.08)
        self._update_compare_overlay_geometry()
        if self._compare_reveal_progress >= 1.0:
            self._compare_reveal_timer.stop()

    def _update_compare_overlay_geometry(self):
        if not self._compare_mode_active:
            return
        base_item = self.current_image_item
        if base_item is None:
            return
        clip_item = self._compare_clip_item
        overlay_item = self._compare_overlay_item
        if clip_item is None or overlay_item is None:
            return

        base_rect = base_item.boundingRect()
        if base_rect.width() <= 0 or base_rect.height() <= 0:
            return
        base_pos = base_item.pos()
        clip_item.setPos(base_pos)
        overlay_item.setPos(self._compare_overlay_offset)

        progress = max(0.0, min(1.0, float(self._compare_reveal_progress)))
        split_ratio = max(0.0, min(1.0, float(self._compare_split_ratio)))
        split_ratio *= progress
        split_x = max(0.0, min(float(base_rect.width()), float(base_rect.width()) * split_ratio))
        clip_item.setRect(QRectF(0.0, 0.0, split_x, float(base_rect.height())))
        self._update_compare_divider_overlay(self._compare_last_viewer_x)

    def _update_compare_divider_overlay(self, viewer_x: int | None = None):
        overlay = getattr(self, "_compare_divider_overlay", None)
        if overlay is None:
            return
        if not self._compare_mode_active:
            overlay.hide()
            return

        line_x = None if viewer_x is None else int(viewer_x)
        if line_x is None:
            base_item = self.current_image_item
            if base_item is not None:
                try:
                    base_rect = base_item.boundingRect()
                    base_pos = base_item.pos()
                    split_ratio = max(0.0, min(1.0, float(self._compare_split_ratio)))
                    progress = max(0.0, min(1.0, float(self._compare_reveal_progress)))
                    split_scene_x = float(base_pos.x()) + (float(base_rect.width()) * split_ratio * progress)
                    split_scene_y = float(base_pos.y()) + (float(base_rect.height()) * 0.5)
                    split_view_pos = self.view.mapFromScene(split_scene_x, split_scene_y)
                    split_viewer_pos = self.mapFrom(self.view.viewport(), split_view_pos)
                    line_x = int(split_viewer_pos.x())
                except Exception:
                    line_x = None

        if line_x is None:
            line_x = int(self.width() * max(0.0, min(1.0, float(self._compare_split_ratio))))

        line_x = max(0, min(max(0, self.width() - 1), int(line_x)))
        split_ratio = max(0.0, min(1.0, float(self._compare_split_ratio)))
        if (
            self.width() <= 3
            or line_x <= 0
            or line_x >= (self.width() - 1)
            or split_ratio <= 1e-4
            or split_ratio >= (1.0 - 1e-4)
        ):
            overlay.hide()
            return
        divider_width = 3
        overlay.setGeometry(line_x - (divider_width // 2), 0, divider_width, max(1, self.height()))
        overlay.show()
        overlay.raise_()

    def _set_compare_split_ratio(self, split: float):
        split = max(0.0, min(1.0, float(split)))
        # Once user starts moving the mouse, stop reveal interpolation so
        # divider tracking stays locked to pointer position.
        reveal_completed_by_input = False
        if float(self._compare_reveal_progress) < 1.0:
            self._compare_reveal_progress = 1.0
            self._compare_reveal_timer.stop()
            reveal_completed_by_input = True

        if abs(split - float(self._compare_split_ratio)) < 1e-4 and not reveal_completed_by_input:
            return
        self._compare_split_ratio = split
        self._update_compare_overlay_geometry()

    def set_compare_split_from_viewer_pos(self, viewer_pos: QPoint):
        if not self._compare_mode_active or viewer_pos is None:
            return
        base_item = self.current_image_item
        if base_item is None:
            return
        global_pos = None
        try:
            cursor_global = QCursor.pos()
            cursor_viewer = self.mapFromGlobal(cursor_global)
            if self.rect().contains(cursor_viewer):
                global_pos = cursor_global
        except Exception:
            global_pos = None
        if global_pos is None:
            try:
                global_pos = self.mapToGlobal(viewer_pos)
            except Exception:
                global_pos = None
        if global_pos is None:
            return
        try:
            self._compare_last_viewer_x = int(self.mapFromGlobal(global_pos).x())
            self._update_compare_divider_overlay(self._compare_last_viewer_x)
        except Exception:
            pass

        try:
            viewport_pos = self.view.viewport().mapFromGlobal(global_pos)
            scene_pos = self.view.mapToScene(viewport_pos)
            base_scene_rect = base_item.sceneBoundingRect()
            width = float(base_scene_rect.width())
            if width <= 0.0:
                return
            split = (float(scene_pos.x()) - float(base_scene_rect.left())) / width
            self._set_compare_split_ratio(split)
            return
        except Exception:
            pass

        viewport_rect = self.view.viewport().rect()
        width = max(1, int(viewport_rect.width()))
        self._set_compare_split_ratio(float(viewer_pos.x()) / float(width))

    def set_compare_split_from_view_x(self, x_pos: int):
        self.set_compare_split_from_viewer_pos(QPoint(int(x_pos), int(self.height() * 0.5)))

    def _sync_compare_split_to_global_cursor(self):
        if not self._compare_mode_active:
            return
        try:
            cursor_viewer_pos = self.mapFromGlobal(QCursor.pos())
        except Exception:
            return
        self.set_compare_split_from_viewer_pos(cursor_viewer_pos)

    def exit_compare_mode(self, *, reset_split: bool = False) -> bool:
        had_compare = bool(self._compare_mode_active or self._compare_overlay_item is not None)
        self._compare_reveal_timer.stop()
        self._clear_compare_scene_items()
        self._compare_mode_active = False
        self._compare_base_index = QPersistentModelIndex()
        self._compare_right_index = QPersistentModelIndex()
        self._compare_last_viewer_x = None
        if self._compare_divider_overlay is not None:
            self._compare_divider_overlay.hide()
        self._compare_reveal_progress = 1.0
        if reset_split:
            self._compare_split_ratio = 0.5
        return had_compare

    def enter_compare_mode(
        self,
        base_index,
        incoming_index,
        *,
        keep_split_ratio: bool = True,
    ) -> bool:
        base_proxy = self._normalize_proxy_index(base_index)
        incoming_proxy = self._normalize_proxy_index(incoming_index)
        if not base_proxy.isValid() or not incoming_proxy.isValid():
            return False
        if not self._is_static_image_index(base_proxy) or not self._is_static_image_index(incoming_proxy):
            return False

        current_proxy = self._normalize_proxy_index(self.proxy_image_index)
        if (
            not current_proxy.isValid()
            or current_proxy.row() != base_proxy.row()
            or current_proxy.column() != base_proxy.column()
        ):
            self.load_image(base_proxy, True)

        current_proxy = self._normalize_proxy_index(self.proxy_image_index)
        if (
            not current_proxy.isValid()
            or current_proxy.row() != base_proxy.row()
            or current_proxy.column() != base_proxy.column()
        ):
            return False
        if self._is_video_loaded or self.current_image_item is None:
            return False

        base_pixmap = self.current_image_item.pixmap()
        incoming_pixmap = self._load_static_pixmap_for_proxy_index(incoming_proxy)
        if base_pixmap.isNull() or incoming_pixmap.isNull():
            return False

        incoming_pixmap, overlay_offset = self._prepare_compare_overlay_pixmap(
            base_pixmap.size(),
            incoming_pixmap,
        )

        self._compare_reveal_timer.stop()
        self._clear_compare_scene_items()
        self._compare_mode_active = True
        self._compare_base_index = QPersistentModelIndex(base_proxy)
        self._compare_right_index = QPersistentModelIndex(incoming_proxy)
        self._compare_last_viewer_x = None
        if not keep_split_ratio:
            self._compare_split_ratio = 0.5
        self._compare_reveal_progress = 0.0

        self._compare_clip_item = QGraphicsRectItem()
        self._compare_clip_item.setPen(Qt.PenStyle.NoPen)
        self._compare_clip_item.setBrush(Qt.BrushStyle.NoBrush)
        self._compare_clip_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._compare_clip_item.setFlag(
            QGraphicsItem.GraphicsItemFlag.ItemClipsChildrenToShape,
            True,
        )
        self._compare_clip_item.setZValue(2.0)
        self.scene.addItem(self._compare_clip_item)

        self._compare_overlay_item = QGraphicsPixmapItem(incoming_pixmap)
        self._compare_overlay_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self._compare_overlay_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._compare_overlay_item.setZValue(3.0)
        self._compare_overlay_item.setParentItem(self._compare_clip_item)
        self._compare_overlay_offset = overlay_offset
        self._compare_divider_item = None

        self._update_compare_overlay_geometry()
        self._compare_reveal_timer.start()
        return True

    def replace_compare_right(self, incoming_index) -> bool:
        incoming_proxy = self._normalize_proxy_index(incoming_index)
        if not incoming_proxy.isValid() or not self._is_static_image_index(incoming_proxy):
            return False
        if not self._compare_mode_active:
            base_proxy = self._normalize_proxy_index(self.proxy_image_index)
            return self.enter_compare_mode(base_proxy, incoming_proxy, keep_split_ratio=True)

        base_item = self.current_image_item
        overlay_item = self._compare_overlay_item
        if base_item is None or overlay_item is None:
            return False

        base_pixmap = base_item.pixmap()
        incoming_pixmap = self._load_static_pixmap_for_proxy_index(incoming_proxy)
        if base_pixmap.isNull() or incoming_pixmap.isNull():
            return False

        incoming_pixmap, overlay_offset = self._prepare_compare_overlay_pixmap(
            base_pixmap.size(),
            incoming_pixmap,
        )
        overlay_item.setPixmap(incoming_pixmap)
        self._compare_overlay_offset = overlay_offset
        self._compare_right_index = QPersistentModelIndex(incoming_proxy)
        self._compare_reveal_progress = 0.0
        self._update_compare_overlay_geometry()
        self._compare_reveal_timer.start()
        return True

    def get_content_aspect_ratio(self) -> float | None:
        """Return current loaded media ratio from actual rendered pixmap."""
        try:
            if self.current_video_item is not None:
                pixmap = self.current_video_item.pixmap()
                if pixmap and not pixmap.isNull() and pixmap.height() > 0:
                    return float(pixmap.width()) / float(pixmap.height())
            if self.current_image_item is not None:
                pixmap = self.current_image_item.pixmap()
                if pixmap and not pixmap.isNull() and pixmap.height() > 0:
                    return float(pixmap.width()) / float(pixmap.height())
        except Exception:
            pass
        return None

    def is_content_pannable(self) -> bool:
        """Return True when media is larger than viewport at current zoom."""
        try:
            # Ignore tiny fit overscan so adaptive floating-window drag mode
            # does not switch just because of seam-compensation scaling.
            if bool(getattr(self, 'is_zoom_to_fit', False)):
                return False

            scene_rect = self.scene.sceneRect()
            viewport_rect = self.view.viewport().rect()
            if scene_rect.width() <= 0 or scene_rect.height() <= 0:
                return False
            if viewport_rect.width() <= 0 or viewport_rect.height() <= 0:
                return False

            transform = self.view.transform()
            scale_x = abs(float(transform.m11()))
            scale_y = abs(float(transform.m22()))
            if scale_x <= 0 or scale_y <= 0:
                return False

            scaled_w = scene_rect.width() * scale_x
            scaled_h = scene_rect.height() * scale_y
            return (scaled_w > (viewport_rect.width() + 1.0)
                    or scaled_h > (viewport_rect.height() + 1.0))
        except Exception:
            return False

    def _apply_uniform_zoom_scale(
        self,
        scale: float,
        zoom_to_fit_state: bool,
        focus_scene_pos=None,
        anchor_view_pos=None,
    ):
        """Apply one uniform zoom scale around current scene center."""
        if scale <= 0:
            return
        scene_rect = self.scene.sceneRect()
        if scene_rect.width() <= 0 or scene_rect.height() <= 0:
            return
        self.view.resetTransform()
        self.view.scale(scale, scale)

        # Cursor-anchored zoom (wheel-like): keep clicked detail under same
        # viewport position after scale change.
        anchored = False
        try:
            if (
                focus_scene_pos is not None
                and anchor_view_pos is not None
                and hasattr(focus_scene_pos, "x")
                and hasattr(focus_scene_pos, "y")
                and hasattr(anchor_view_pos, "x")
                and hasattr(anchor_view_pos, "y")
            ):
                new_scene_at_anchor = self.view.mapToScene(anchor_view_pos)
                delta = new_scene_at_anchor - focus_scene_pos
                self.view.translate(delta.x(), delta.y())
                anchored = True
        except Exception:
            anchored = False

        if not anchored:
            focus_point = scene_rect.center()
            try:
                if focus_scene_pos is not None and hasattr(focus_scene_pos, 'x') and hasattr(focus_scene_pos, 'y'):
                    focus_point = focus_scene_pos
            except Exception:
                focus_point = scene_rect.center()
            self.view.centerOn(focus_point)

        MarkingItem.zoom_factor = scale
        self.is_zoom_to_fit = bool(zoom_to_fit_state)
        self.zoom_emit()

    def apply_floating_double_click_zoom(self, scene_anchor_pos=None, view_anchor_pos=None) -> bool:
        """Adaptive double-click zoom behavior for spawned floating viewers."""
        try:
            scene_rect = self.scene.sceneRect()
            viewport_rect = self.view.viewport().rect()
            if scene_rect.width() <= 0 or scene_rect.height() <= 0:
                return False
            if viewport_rect.width() <= 0 or viewport_rect.height() <= 0:
                return False

            fit_w = viewport_rect.width() / scene_rect.width()
            fit_h = viewport_rect.height() / scene_rect.height()
            if fit_w <= 0 or fit_h <= 0:
                return False

            current_scale = abs(float(self.view.transform().m11()))
            if current_scale <= 0:
                current_scale = abs(float(MarkingItem.zoom_factor or 0))
            if current_scale <= 0:
                current_scale = min(fit_w, fit_h)

            scaled_w = scene_rect.width() * current_scale
            scaled_h = scene_rect.height() * current_scale

            # Positive values mean visible empty bands ("black borders") on that axis.
            gap_x = viewport_rect.width() - scaled_w
            gap_y = viewport_rect.height() - scaled_h
            # Treat only meaningful gaps as bars; ignore tiny rounding/overscan seams.
            bar_threshold_x = max(4.0, viewport_rect.width() * 0.015)
            bar_threshold_y = max(4.0, viewport_rect.height() * 0.015)
            has_side_bars = gap_x > bar_threshold_x and gap_y <= bar_threshold_y
            has_top_bottom_bars = gap_y > bar_threshold_y and gap_x <= bar_threshold_x
            click_inside_media = True
            try:
                if (
                    scene_anchor_pos is not None
                    and hasattr(scene_anchor_pos, "x")
                    and hasattr(scene_anchor_pos, "y")
                ):
                    click_inside_media = scene_rect.contains(scene_anchor_pos)
            except Exception:
                click_inside_media = True

            # Priority toggle: if we previously stored a zoom scale for this
            # floating viewer, restore it first when current view is unpannable.
            # This keeps double-click acting as a zoom in/out toggle, even when
            # fit mode currently has bars due window aspect ratio.
            stored_scale = self._floating_double_click_return_scale
            if (
                click_inside_media
                and
                not self.is_content_pannable()
                and isinstance(stored_scale, (int, float))
                and float(stored_scale) > (current_scale + 1e-6)
            ):
                target_scale = min(16.0, float(stored_scale))
                self._apply_uniform_zoom_scale(
                    target_scale,
                    zoom_to_fit_state=False,
                    focus_scene_pos=scene_anchor_pos,
                    anchor_view_pos=view_anchor_pos,
                )
                self._floating_last_auto_double_click_zoom_scale = target_scale
                return True

            fill_overscan = 1.0004
            if has_side_bars:
                target_scale = fit_w * fill_overscan
                self._apply_uniform_zoom_scale(
                    target_scale,
                    zoom_to_fit_state=False,
                    focus_scene_pos=scene_anchor_pos,
                    anchor_view_pos=view_anchor_pos,
                )
                self._floating_last_auto_double_click_zoom_scale = target_scale
                return True
            if has_top_bottom_bars:
                target_scale = fit_h * fill_overscan
                self._apply_uniform_zoom_scale(
                    target_scale,
                    zoom_to_fit_state=False,
                    focus_scene_pos=scene_anchor_pos,
                    anchor_view_pos=view_anchor_pos,
                )
                self._floating_last_auto_double_click_zoom_scale = target_scale
                return True

            # If no visible bars and content is pannable (zoomed/cropped), restore fit.
            if self.is_content_pannable():
                # Save return scale only if user intentionally changed zoom away
                # from the last auto double-click zoom-in scale.
                auto_scale = self._floating_last_auto_double_click_zoom_scale
                should_store_return_scale = True
                if isinstance(auto_scale, (int, float)):
                    auto_scale = float(auto_scale)
                    scale_delta = abs(current_scale - auto_scale)
                    tolerance = max(1e-4, auto_scale * 1e-3)
                    should_store_return_scale = scale_delta > tolerance
                if should_store_return_scale:
                    self._floating_double_click_return_scale = current_scale
                self.zoom_fit()
                return True

            # If still unpannable/no-op, do a local configurable detail zoom at click anchor.
            if not self.is_content_pannable():
                zoom_percent = settings.value(
                    'floating_double_click_detail_zoom_percent',
                    defaultValue=DEFAULT_SETTINGS.get(
                        'floating_double_click_detail_zoom_percent', 400
                    ),
                    type=int,
                )
                zoom_percent = max(110, min(1600, int(zoom_percent)))
                zoom_step = zoom_percent / 100.0
                max_zoom = 16.0
                target_scale = min(max_zoom, current_scale * zoom_step)
                if target_scale > (current_scale + 1e-6):
                    self._apply_uniform_zoom_scale(
                        target_scale,
                        zoom_to_fit_state=False,
                        focus_scene_pos=scene_anchor_pos,
                        anchor_view_pos=view_anchor_pos,
                    )
                    self._floating_last_auto_double_click_zoom_scale = target_scale
                    return True
            return False
        except Exception:
            return False

    @Slot()
    def _on_proxy_model_about_to_reset(self):
        self._viewer_model_resetting = True
        self.proxy_image_index = QPersistentModelIndex()

    @Slot()
    def _on_proxy_model_reset(self):
        self._viewer_model_resetting = False
        self.proxy_image_index = QPersistentModelIndex()

    def _normalize_proxy_index(self, index_like) -> QModelIndex:
        """Build a fresh, bounds-checked proxy index from QModelIndex/Persistent index."""
        try:
            if index_like is None:
                return QModelIndex()
            if isinstance(index_like, QPersistentModelIndex):
                if not index_like.isValid():
                    return QModelIndex()
                model = index_like.model()
                row = index_like.row()
                col = index_like.column()
            else:
                if not hasattr(index_like, 'isValid') or not index_like.isValid():
                    return QModelIndex()
                model = index_like.model()
                row = index_like.row()
                col = index_like.column()

            if model is None or model is not self.proxy_image_list_model:
                return QModelIndex()
            if row < 0 or row >= model.rowCount() or col < 0:
                return QModelIndex()
            return model.index(row, col)
        except Exception:
            return QModelIndex()

    def _safe_get_image(self, proxy_index: QModelIndex):
        """Resolve current Image via source model mapping with reset/bounds guards."""
        if self._viewer_model_resetting or not proxy_index.isValid():
            return None
        try:
            source_model = self.proxy_image_list_model.sourceModel()
            source_index = self.proxy_image_list_model.mapToSource(proxy_index)
            if not source_model or not source_index.isValid():
                return None
            row = source_index.row()
            if row < 0 or row >= source_model.rowCount():
                return None
            return source_model.data(source_index, Qt.ItemDataRole.UserRole)
        except Exception:
            return None

    def closeEvent(self, event):
        """Stop all timers before the widget is destroyed to prevent use-after-free crashes."""
        try:
            self._controls_hide_timer.stop()
        except Exception:
            pass
        try:
            self._compare_reveal_timer.stop()
        except Exception:
            pass
        try:
            if hasattr(self, 'video_player') and self.video_player:
                self.video_player.stop()
        except Exception:
            pass
        super().closeEvent(event)

    def _position_video_controls(self, force_bottom=False):
        """Position video controls overlay at saved position."""
        if not self.video_controls:
            return
        try:
            # Guard against destroyed C++ object when window is closing
            _ = self.video_controls.isVisible()
        except RuntimeError:
            return

        controls_height = self.video_controls.sizeHint().height()
        target_geometry = None

        # Check if we have saved percentage positions and width
        saved_x_percent = settings.value('video_controls_x_percent', type=float)
        saved_y_percent = settings.value('video_controls_y_percent', type=float)
        saved_width_percent = settings.value('video_controls_width_percent', type=float)

        if force_bottom or saved_x_percent is None or saved_y_percent is None:
            # Position at bottom center with default width
            controls_width = self.video_controls.sizeHint().width()
            x_pos = (self.width() - controls_width) // 2
            y_pos = self.height() - controls_height
            target_geometry = (x_pos, y_pos, controls_width, controls_height)
        else:
            # Use saved percentages to calculate position and width
            if self.width() > 0 and self.height() > 0:
                # Calculate width
                if saved_width_percent is not None:
                    controls_width = int(saved_width_percent * self.width())
                    min_w = self.video_controls.minimum_runtime_width()
                    controls_width = max(min_w, min(controls_width, self.width()))
                else:
                    controls_width = self.video_controls.sizeHint().width()

                x_pos = int(saved_x_percent * self.width())
                y_pos = int(saved_y_percent * self.height())
                # Clamp to valid range
                x_pos = max(0, min(x_pos, self.width() - controls_width))
                y_pos = max(0, min(y_pos, self.height() - controls_height))
                target_geometry = (x_pos, y_pos, controls_width, controls_height)

        if target_geometry is not None:
            current = self.video_controls.geometry()
            changed = (
                current.x() != target_geometry[0]
                or current.y() != target_geometry[1]
                or current.width() != target_geometry[2]
                or current.height() != target_geometry[3]
            )
            if changed:
                self.video_controls.setGeometry(*target_geometry)
                self._pending_controls_stabilize = True

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
        try:
            self.video_player.sync_external_surface_geometry()
        except Exception:
            pass
        if self._compare_mode_active:
            self._update_compare_overlay_geometry()

    def mouseMoveEvent(self, event):
        """Show controls when hovering over their position."""
        if self._compare_mode_active:
            self.set_compare_split_from_viewer_pos(event.pos())
        if self._is_video_loaded:
            self._process_controls_hover(event.pos())
        super().mouseMoveEvent(event)

    def _event_pos_to_viewer(self, watched, event):
        """Map an event local position from watched object to viewer coordinates."""
        if not hasattr(event, 'position'):
            return None
        try:
            local_pos = event.position().toPoint()
        except Exception:
            try:
                local_pos = event.pos()
            except Exception:
                return None
        try:
            if watched is self:
                return local_pos
            if watched is self.view:
                return self.mapFrom(self.view, local_pos)
            if watched is self.view.viewport():
                return self.mapFrom(self.view.viewport(), local_pos)
            if watched is self.video_controls:
                return self.mapFrom(self.video_controls, local_pos)
            if isinstance(watched, QWidget):
                global_pos = watched.mapToGlobal(local_pos)
                return self.mapFromGlobal(global_pos)
        except Exception:
            return None
        return None

    def _resolve_main_window_host(self):
        """Resolve the main window host that owns active-viewer routing."""
        host = self.window()
        if host is not None and hasattr(host, 'set_active_viewer'):
            return host
        parent = host.parentWidget() if (host is not None and hasattr(host, 'parentWidget')) else None
        while parent is not None:
            if hasattr(parent, 'set_active_viewer'):
                return parent
            parent = parent.parentWidget() if hasattr(parent, 'parentWidget') else None
        return None

    def _process_controls_hover(self, viewer_pos):
        """Apply control ownership/show-hide behavior from one hover position."""
        if viewer_pos is None or not self._is_video_loaded:
            return
        controls_rect = self.video_controls.geometry()
        detection_rect = controls_rect.adjusted(-20, -20, 20, 20)
        in_controls_zone = detection_rect.contains(viewer_pos)

        if in_controls_zone:
            host = self._resolve_main_window_host()

            active_is_self = False
            try:
                if host is not None and hasattr(host, 'get_active_viewer'):
                    active_is_self = host.get_active_viewer() is self
            except Exception:
                active_is_self = False

            # Enforce ownership switch on zone enter OR when this viewer is not active.
            if (not self._controls_hover_inside) or (not active_is_self):
                # Direct switch guarantees immediate exclusive hide/show, even if
                # signal/event ordering differs across top-level floating windows.
                if host is not None and hasattr(host, 'set_active_viewer'):
                    host.set_active_viewer(self)
                else:
                    self.activated.emit()
                self._controls_hover_inside = True
            if self.video_controls_auto_hide:
                self._show_controls_temporarily()
            elif not self._controls_visible:
                # Main viewer may be force-hidden by exclusive visibility mode.
                self._show_controls_permanent()
        else:
            self._controls_hover_inside = False

    def eventFilter(self, watched, event):
        self._refresh_video_surface_event_filters()
        event_type = event.type()
        if event_type == QEvent.Type.KeyPress and self._compare_mode_active:
            try:
                if event.key() == Qt.Key.Key_Escape:
                    self.exit_compare_mode(reset_split=False)
                    event.accept()
                    return True
            except Exception:
                pass
        if event_type == QEvent.Type.Wheel:
            # Forward wheel to zoom handler when it comes from a video surface
            # widget directly, OR from the viewport (video surfaces use
            # WA_TransparentForMouseEvents so events fall through to viewport).
            is_video_surface = any(watched is s for s in self._iter_video_surface_widgets())
            is_viewport = watched is self.view.viewport()
            if is_video_surface or (is_viewport and self._is_video_loaded):
                self.wheelEvent(event)
                return True
        if event_type == QEvent.Type.MouseMove:
            viewer_pos = self._event_pos_to_viewer(watched, event)
            if viewer_pos is not None and self._compare_mode_active:
                self.set_compare_split_from_viewer_pos(viewer_pos)
            if viewer_pos is not None and self._is_video_loaded:
                self._process_controls_hover(viewer_pos)
        if event_type in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.FocusIn,
            QEvent.Type.WindowActivate,
        ):
            self.activated.emit()
        if event_type in (QEvent.Type.Leave, QEvent.Type.HoverLeave):
            if self._compare_mode_active:
                self._sync_compare_split_to_global_cursor()
            self._controls_hover_inside = False
        return super().eventFilter(watched, event)

    def leaveEvent(self, event):
        if self._compare_mode_active:
            self._sync_compare_split_to_global_cursor()
        super().leaveEvent(event)

    def _show_controls_temporarily(self):
        """Show controls and start hide timer."""
        try:
            _ = self.video_controls.isVisible()
        except RuntimeError:
            return  # widget already destroyed (window closing)
        if not self._controls_visible:
            self.video_controls.setVisible(True)
            self._controls_visible = True
            self._position_video_controls()
            if self._pending_controls_stabilize:
                self.video_controls._stabilize_after_geometry_change()
                self._pending_controls_stabilize = False

        # Reset hide timer (0.8 seconds)
        self._controls_hide_timer.stop()
        self._controls_hide_timer.start(800)

    def _hide_controls(self):
        """Hide controls after timeout, but only if mouse is not over them and not resizing."""
        if self.video_controls_auto_hide and self._is_video_loaded:
            # Don't hide if actively resizing or dragging
            if hasattr(self.video_controls, '_resizing') and self.video_controls._resizing:
                return
            if hasattr(self.video_controls, '_dragging') and self.video_controls._dragging:
                return

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
        if self._pending_controls_stabilize:
            self.video_controls._stabilize_after_geometry_change()
            self._pending_controls_stabilize = False

    @Slot(bool)
    def set_always_show_controls(self, always_show: bool):
        """Toggle always-show mode for video controls."""
        if self.is_spawned_viewer:
            # Spawned viewers intentionally remain auto-hide for performance.
            self.video_controls_auto_hide = True
            if self._is_video_loaded:
                self._show_controls_temporarily()
            return
        self.video_controls_auto_hide = not always_show
        if always_show and self._is_video_loaded:
            self._show_controls_permanent()
        elif self._is_video_loaded:
            # Re-enable auto-hide, show temporarily
            self._show_controls_temporarily()

    def _show_error_placeholder(self, message: str):
        """Display an error message on the scene."""
        self.scene.clear()
        
        # Create standard background size
        w, h = 800, 600
        bg = QGraphicsRectItem(0, 0, w, h)
        bg.setBrush(Qt.GlobalColor.black)
        self.scene.addItem(bg)
        
        # Add text
        from PySide6.QtWidgets import QGraphicsSimpleTextItem
        from PySide6.QtGui import QFont, QColor
        
        # Truncate overly long messages
        display_msg = str(message)
        if len(display_msg) > 100:
            display_msg = display_msg[:100] + "..."
            
        text = QGraphicsSimpleTextItem(f"⚠️ LOAD FAILED\n\n{display_msg}")
        text.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        text.setBrush(QColor("#ff5555"))
        
        # Center text
        text_rect = text.boundingRect()
        text.setPos((w - text_rect.width()) / 2, (h - text_rect.height()) / 2)
        
        self.scene.addItem(text)
        self.view.fitInView(bg, Qt.AspectRatioMode.KeepAspectRatio)

    @Slot()
    def load_image(self, proxy_image_index: QModelIndex, is_complete = True):
        try:
            self._load_image_impl(proxy_image_index, is_complete)
        except (pilimage.UnidentifiedImageError, OSError, ValueError) as e:
            # Expected error for corrupt/unsupported files - suppress traceback
            print(f"[IMAGE_VIEWER] Load failed (expected): {e}")
            self._show_error_placeholder(f"Read Error: {e}")
        except Exception as e:
            print(f"[IMAGE_VIEWER] ERROR in load_image: {e}")
            import traceback
            traceback.print_exc()
            self._show_error_placeholder(f"Read Error: {e}")

    def _load_image_impl(self, proxy_image_index: QModelIndex, is_complete = True):
        if self._viewer_model_resetting:
            return
        proxy_index = self._normalize_proxy_index(proxy_image_index)
        if self._compare_mode_active:
            self.exit_compare_mode(reset_split=False)

        # Check if we should skip this reload
        if not proxy_index.isValid():
            return

        if (
            self.inhibit_reload_image
            and self.proxy_image_index.isValid()
            and proxy_index.row() == self.proxy_image_index.row()
            and proxy_index.column() == self.proxy_image_index.column()
        ):
            return

        self.proxy_image_index = QPersistentModelIndex(proxy_index)
        self._floating_double_click_return_scale = None
        self._floating_last_auto_double_click_zoom_scale = None

        image: Image = self._safe_get_image(proxy_index)
        if image is None:
            # Page not loaded yet in pagination mode - wait
            return
        self.rating_changed.emit(image.rating)

        if is_complete:
            self.marking_items.clear()
            self.view.clear_scene()
            auto_play_after_layout = False
            was_video_loaded = bool(self._is_video_loaded)

            # Check if this is a video
            if image.is_video:
                try:
                    # Image -> video handoff needs a slightly stricter native-reveal policy
                    # to avoid showing an unready backend frame.
                    self.video_player.hint_next_video_starts_from_still(not was_video_loaded)
                except Exception:
                    pass
                # Create a pixmap item for video frames BEFORE cleanup
                image_item = QGraphicsPixmapItem()
                # Enable high-quality smooth transformation for video frame downscaling
                image_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
                image_item.setZValue(0)
                self.scene.addItem(image_item)
                self.current_video_item = image_item
                self.current_image_item = None

                # Now load video and display first frame
                if self.video_player.load_video(
                    image.path,
                    image_item,
                    video_metadata=getattr(image, 'video_metadata', None),
                    preview_qimage=getattr(image, 'thumbnail_qimage', None),
                    video_dimensions=getattr(image, 'dimensions', None),
                ):
                    # Update scene rect after video loads
                    if image_item.pixmap() and not image_item.pixmap().isNull():
                        self._set_scene_rect_for_item(image_item)
                        MarkingItem.image_size = image_item.boundingRect().toRect()

                        # Show video controls
                        self._is_video_loaded = True
                        effective_video_metadata = dict(image.video_metadata or {})
                        live_frame_count = int(self.video_player.get_total_frames() or 0)
                        live_fps = float(self.video_player.get_fps() or 0.0)
                        if live_frame_count > 0:
                            effective_video_metadata['frame_count'] = live_frame_count
                        if live_fps > 0:
                            effective_video_metadata['fps'] = live_fps
                        if live_frame_count > 0 and live_fps > 0:
                            effective_video_metadata['duration'] = live_frame_count / live_fps

                        if effective_video_metadata:
                            self.video_controls.set_video_info(
                                effective_video_metadata,
                                image=image,
                                proxy_model=self.proxy_image_list_model
                            )

                        # Only show controls if always-show is enabled
                        if not self.video_controls_auto_hide:
                            self._show_controls_permanent()

                        # Auto-play is deferred until after zoom/layout settles.
                        auto_play_after_layout = bool(self.video_controls.should_auto_play())
                    else:
                        print(f"Video loaded but no frame available: {image.path}")
                        self._show_error_placeholder("Video loaded (no frame)")
                        return
                    try:
                        top = self.window()
                        if top and hasattr(top, 'refresh_video_controls_performance_profile'):
                            top.refresh_video_controls_performance_profile()
                    except Exception:
                        pass
                else:
                    # Failed to load video, show error
                    print(f"Failed to load video: {image.path}")
                    self._show_error_placeholder("Failed to open video file")
                    return
            else:
                # Hide video controls for static images
                self._is_video_loaded = False
                self._controls_hide_timer.stop()
                self.video_controls.setVisible(False)
                self._controls_visible = False

                # Suspend video playback quickly when switching to still image.
                # This avoids expensive frame-reset work on backend transitions.
                self.video_player.suspend_for_media_switch()
                try:
                    top = self.window()
                    if top and hasattr(top, 'refresh_video_controls_performance_profile'):
                        top.refresh_video_controls_performance_profile()
                except Exception:
                    pass

                # Load static image using QImageReader (like thumbnails for best quality)
                from PySide6.QtGui import QImageReader
                image_reader = QImageReader(str(image.path))
                image_reader.setAutoTransform(True)
                qimage = image_reader.read()

                if qimage.isNull():
                    # Fallback to PIL if QImageReader fails
                    pil_image = pilimage.open(image.path)
                    qimage = pil_to_qimage(pil_image)

                pixmap = QPixmap.fromImage(qimage)

                # Use standard pixmap item with SmoothTransformation
                # OpenGL viewport + render hints should provide high-quality GPU scaling
                image_item = QGraphicsPixmapItem(pixmap)
                image_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
                image_item.setZValue(0)
                self._set_scene_rect_for_item(image_item)
                self.scene.addItem(image_item)
                self.current_image_item = image_item  # Keep reference to prevent garbage collection!
                self.current_video_item = None
                MarkingItem.image_size = image_item.boundingRect().toRect()

            self.zoom_fit()
            self.hud_item = ResizeHintHUD(MarkingItem.image_size, image_item)
            if auto_play_after_layout:
                QTimer.singleShot(0, self.video_player.play)
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
            # No crop - reset HUD state
            if hasattr(self, 'hud_item'):
                self.hud_item.has_crop = False
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
        try:
            current_scale = abs(float(self.view.transform().m11()))
        except Exception:
            current_scale = 0.0
        if current_scale <= 0:
            current_scale = float(MarkingItem.zoom_factor or 1.0)
        MarkingItem.zoom_factor = min(current_scale * 1.25, 16)
        self.is_zoom_to_fit = False
        self.zoom_emit()

    @Slot()
    def zoom_out(self, center_pos: QPoint = None):
        view = self.view.viewport().size()
        scene = self.scene.sceneRect()
        if scene.width() < 1 or scene.height() < 1:
            return
        limit = min(view.width()/scene.width(), view.height()/scene.height())
        try:
            current_scale = abs(float(self.view.transform().m11()))
        except Exception:
            current_scale = 0.0
        if current_scale <= 0:
            current_scale = float(MarkingItem.zoom_factor or limit)
        MarkingItem.zoom_factor = max(current_scale / 1.25, limit)
        self.is_zoom_to_fit = abs(MarkingItem.zoom_factor - limit) <= max(1e-6, limit * 1e-6)
        self.zoom_emit()

    @Slot()
    def zoom_original(self):
        MarkingItem.zoom_factor = 1.0
        self.is_zoom_to_fit = False
        self.zoom_emit()

    @Slot()
    def zoom_fit(self):
        scene_rect = self.scene.sceneRect()
        viewport_rect = self.view.viewport().rect()
        if scene_rect.width() <= 0 or scene_rect.height() <= 0:
            return
        if viewport_rect.width() <= 0 or viewport_rect.height() <= 0:
            return

        # Manual fit avoids the internal fitInView margin that can leave a
        # persistent 1-2px edge around media.
        scale_x = viewport_rect.width() / scene_rect.width()
        scale_y = viewport_rect.height() / scene_rect.height()
        scale = min(scale_x, scale_y)
        if scale <= 0:
            return

        # Tiny overscan hides occasional 1px sampling seams on edges.
        scale *= 1.0008

        self.view.resetTransform()
        self.view.scale(scale, scale)
        self.view.centerOn(scene_rect.center())
        MarkingItem.zoom_factor = scale
        self.is_zoom_to_fit = True
        self.zoom_emit()

    def zoom_emit(self):
        ResizeHintHUD.zoom_factor = MarkingItem.zoom_factor
        transform = self.view.transform()
        self.view.setTransform(QTransform(
            MarkingItem.zoom_factor, transform.m12(), transform.m13(),
            transform.m21(), MarkingItem.zoom_factor, transform.m23(),
            transform.m31(), transform.m32(), transform.m33()))
        try:
            self.video_player.sync_external_surface_geometry()
        except Exception:
            pass
        try:
            self.video_player.set_view_transformed(not self.is_zoom_to_fit)
        except Exception:
            pass
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
        delta_y = event.angleDelta().y()
        if delta_y == 0:
            return

        viewport = self.view.viewport()
        viewport_rect = viewport.rect()
        if viewport_rect.width() <= 0 or viewport_rect.height() <= 0:
            return

        anchor_view_pos = viewport.mapFromGlobal(QCursor.pos())
        if not viewport_rect.contains(anchor_view_pos):
            try:
                anchor_view_pos = viewport.mapFromGlobal(event.globalPosition().toPoint())
            except Exception:
                try:
                    anchor_view_pos = event.position().toPoint()
                except Exception:
                    anchor_view_pos = viewport_rect.center()
                if not viewport_rect.contains(anchor_view_pos):
                    try:
                        anchor_view_pos = viewport.mapFrom(self.view, anchor_view_pos)
                    except Exception:
                        pass

        if not viewport_rect.contains(anchor_view_pos):
            anchor_view_pos = QPoint(
                max(0, min(anchor_view_pos.x(), max(0, viewport_rect.width() - 1))),
                max(0, min(anchor_view_pos.y(), max(0, viewport_rect.height() - 1))),
            )

        focus_scene_pos = self.view.mapToScene(anchor_view_pos)
        scene_rect = self.scene.sceneRect()
        if scene_rect.width() <= 0 or scene_rect.height() <= 0:
            return

        try:
            current_scale = abs(float(self.view.transform().m11()))
        except Exception:
            current_scale = 0.0
        if current_scale <= 0:
            current_scale = float(MarkingItem.zoom_factor or 1.0)

        fit_limit = min(
            viewport_rect.width() / scene_rect.width(),
            viewport_rect.height() / scene_rect.height(),
        )
        fit_limit = max(1e-9, float(fit_limit))

        if delta_y > 0:
            target_scale = min(current_scale * 1.25, 16.0)
            zoom_to_fit_state = False
        else:
            target_scale = max(current_scale / 1.25, fit_limit)
            zoom_to_fit_state = abs(target_scale - fit_limit) <= max(1e-6, fit_limit * 1e-6)

        self._apply_uniform_zoom_scale(
            target_scale,
            zoom_to_fit_state=zoom_to_fit_state,
            focus_scene_pos=focus_scene_pos,
            anchor_view_pos=anchor_view_pos,
        )
        event.accept()

    def add_rectangle(self, rect: QRect, rect_type: ImageMarking,
                      interactive: bool, size: QSize = None, name: str = '',
                      confidence: float = 1.0):
        self.marking_to_add = ImageMarking.NONE
        marking_item = MarkingItem(rect, rect_type, interactive, size)
        marking_item.setVisible(self.show_marking_state)
        if rect_type == ImageMarking.CROP:
            self.crop_marking = marking_item
            marking_item.size_changed() # call after self.crop_marking was set!
            # Enable HUD text display when crop marking exists
            if hasattr(self, 'hud_item'):
                self.hud_item.has_crop = True
                self.hud_item.rect = marking_item.rect()
                self.hud_item.update()
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
            # Update HUD rect for crop display
            if hasattr(self, 'hud_item'):
                self.hud_item.has_crop = True
                self.hud_item.rect = marking.rect()
                self.hud_item.update()
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
                # Reset HUD when crop is deleted
                if hasattr(self, 'hud_item'):
                    self.hud_item.has_crop = False
                    self.hud_item.update()
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
