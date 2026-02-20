from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QResizeEvent
from PySide6.QtWidgets import QWidget

from widgets.image_viewer import ImageViewer
from widgets.video_sync_coordinator import VideoSyncCoordinator


class MediaComparisonWidget(QWidget):
    """Frameless A/B comparison window for image or video media."""

    closing = Signal()

    def __init__(self, model_a, model_b, proxy_image_list_model, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.Window | Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle("Media Comparison")
        self.setMinimumSize(400, 300)
        self.setMouseTracking(True)

        self.split_position = 0.5
        self._is_dragging = False
        self._closed = False

        self.viewer_a = ImageViewer(proxy_image_list_model, is_spawned_viewer=True)
        self.viewer_a.setParent(self)
        self.viewer_a.set_scene_padding(0)

        self.viewer_b = ImageViewer(proxy_image_list_model, is_spawned_viewer=True)
        self._viewer_b_clip = QWidget(self)
        self._viewer_b_clip.setObjectName("mediaComparisonClip")
        self._viewer_b_clip.setMouseTracking(True)
        self.viewer_b.setParent(self._viewer_b_clip)
        self.viewer_b.set_scene_padding(0)

        self._divider_widget = QWidget(self)
        self._divider_widget.setStyleSheet("background-color: rgba(255, 255, 255, 220);")
        self._divider_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._model_a = model_a
        self._model_b = model_b

        self.viewer_a.lower()
        self._viewer_b_clip.raise_()
        self._divider_widget.raise_()

        self._refresh_filter_timer = QTimer(self)
        self._refresh_filter_timer.setInterval(300)
        self._refresh_filter_timer.timeout.connect(self._refresh_event_filters)
        self._refresh_filter_timer.start()
        self._sync_bootstrap_timer = QTimer(self)
        self._sync_bootstrap_timer.setSingleShot(False)
        self._sync_bootstrap_timer.setInterval(180)
        self._sync_bootstrap_timer.timeout.connect(self._maybe_start_video_sync)
        self._sync_bootstrap_attempts = 0
        self._sync_coordinator: VideoSyncCoordinator | None = None

        self._refresh_event_filters()
        self._update_split_layout()
        QTimer.singleShot(0, self._deferred_load)

    def viewers(self) -> list[ImageViewer]:
        return [self.viewer_a, self.viewer_b]

    def _deferred_load(self):
        try:
            if self._model_a is not None:
                self.viewer_a.load_image(self._model_a)
            if self._model_b is not None:
                self.viewer_b.load_image(self._model_b)
            self._update_split_layout()
            self._schedule_auto_sync()
        except Exception:
            pass

    def _iter_video_surface_widgets(self, viewer: ImageViewer):
        player = getattr(viewer, "video_player", None)
        if player is None:
            return
        for attr in ("vlc_widget", "mpv_widget"):
            widget = getattr(player, attr, None)
            if isinstance(widget, QWidget):
                yield widget

    def _refresh_event_filters(self):
        widgets: list[QWidget] = [self, self.viewer_a, self._viewer_b_clip, self.viewer_b]
        for viewer in (self.viewer_a, self.viewer_b):
            view = getattr(viewer, "view", None)
            if view is not None:
                widgets.append(view)
                widgets.append(view.viewport())
            for surface in self._iter_video_surface_widgets(viewer):
                widgets.append(surface)

        for widget in widgets:
            try:
                widget.installEventFilter(self)
                widget.setMouseTracking(True)
            except Exception:
                continue

    def _set_split_position(self, split: float):
        split = max(0.0, min(1.0, float(split)))
        if abs(split - float(self.split_position)) < 1e-4:
            return
        self.split_position = split
        self._update_split_layout()

    def _update_split_from_global_cursor(self):
        if self.width() <= 0:
            return
        local_pos = self.mapFromGlobal(QCursor.pos())
        split = float(local_pos.x()) / float(max(1, self.width()))
        self._set_split_position(split)

    def _update_split_layout(self):
        width = max(1, self.width())
        height = max(1, self.height())
        split_x = max(0, min(width, int(round(float(width) * float(self.split_position)))))

        self.viewer_a.setGeometry(0, 0, width, height)
        clip_width = max(0, width - split_x)
        self._viewer_b_clip.setGeometry(split_x, 0, clip_width, height)
        self.viewer_b.setGeometry(-split_x, 0, width, height)

        if clip_width <= 0:
            self._viewer_b_clip.hide()
        else:
            self._viewer_b_clip.show()
            self._viewer_b_clip.raise_()

        if split_x <= 0 or split_x >= width:
            self._divider_widget.hide()
        else:
            self._divider_widget.setGeometry(max(0, split_x - 1), 0, 3, height)
            self._divider_widget.show()
            self._divider_widget.raise_()

    def _is_video_ready(self, viewer: ImageViewer) -> bool:
        try:
            if not bool(getattr(viewer, "_is_video_loaded", False)):
                return False
            player = getattr(viewer, "video_player", None)
            if player is None:
                return False
            return bool(getattr(player, "video_path", None))
        except Exception:
            return False

    def _both_videos_ready(self) -> bool:
        return self._is_video_ready(self.viewer_a) and self._is_video_ready(self.viewer_b)

    def _stop_video_sync(self):
        coordinator = self._sync_coordinator
        self._sync_coordinator = None
        if coordinator is not None:
            try:
                coordinator.stop()
            except Exception:
                pass

    def _schedule_auto_sync(self):
        if self._closed:
            return
        self._sync_bootstrap_attempts = 0
        if self._both_videos_ready():
            self._maybe_start_video_sync()
            return
        self._sync_bootstrap_timer.start()

    def _maybe_start_video_sync(self):
        if self._closed:
            self._sync_bootstrap_timer.stop()
            return
        if not self._both_videos_ready():
            self._sync_bootstrap_attempts += 1
            if self._sync_bootstrap_attempts >= 80:
                self._sync_bootstrap_timer.stop()
            return
        self._sync_bootstrap_timer.stop()
        self._stop_video_sync()
        try:
            self._sync_coordinator = VideoSyncCoordinator(
                [self.viewer_a, self.viewer_b],
                parent=self,
                show_sync_icon=False,
            )
            self._sync_coordinator.start()
        except Exception:
            self._sync_coordinator = None

    def eventFilter(self, watched, event):
        event_type = event.type()
        if event_type == QEvent.Type.MouseButtonPress:
            try:
                if event.button() == Qt.MouseButton.LeftButton:
                    self._is_dragging = True
                    self._update_split_from_global_cursor()
                    event.accept()
                    return True
            except Exception:
                pass
        elif event_type == QEvent.Type.MouseMove:
            self._update_split_from_global_cursor()
            if self._is_dragging:
                try:
                    event.accept()
                except Exception:
                    pass
                return True
        elif event_type == QEvent.Type.MouseButtonRelease:
            try:
                if event.button() == Qt.MouseButton.LeftButton:
                    self._is_dragging = False
                    self._update_split_from_global_cursor()
                    event.accept()
                    return True
            except Exception:
                pass
        elif event_type in (QEvent.Type.Leave, QEvent.Type.HoverLeave):
            self._update_split_from_global_cursor()

        return super().eventFilter(watched, event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = True
            self._update_split_from_global_cursor()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        self._update_split_from_global_cursor()
        if self._is_dragging:
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = False
            self._update_split_from_global_cursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        self._update_split_layout()
        self._refresh_event_filters()

    def leaveEvent(self, event):
        self._update_split_from_global_cursor()
        super().leaveEvent(event)

    def closeEvent(self, event):
        if self._closed:
            super().closeEvent(event)
            return
        self._closed = True
        self._refresh_filter_timer.stop()
        self._sync_bootstrap_timer.stop()
        self._stop_video_sync()
        for viewer in (self.viewer_a, self.viewer_b):
            try:
                player = getattr(viewer, "video_player", None)
                if player is not None:
                    player.cleanup()
            except Exception:
                pass
        self.closing.emit()
        try:
            self.viewer_a.deleteLater()
            self.viewer_b.deleteLater()
        except Exception:
            pass
        super().closeEvent(event)
