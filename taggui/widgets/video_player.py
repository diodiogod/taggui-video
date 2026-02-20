import os
import sys
import time
import weakref
# Set environment variables BEFORE importing cv2
os.environ['OPENCV_FFMPEG_LOGLEVEL'] = '-8'
os.environ['OPENCV_LOG_LEVEL'] = 'SILENT'

import cv2
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, Signal, Slot, QUrl, QRect, QMetaObject, Q_ARG
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QGraphicsPixmapItem, QWidget, QMessageBox, QLabel
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtGui import QOpenGLContext

from utils.video import VideoValidator
from utils.video.playback_backend import (
    MPV_PYTHON_MODULE,
    MPV_BACKEND_ERROR,
    MPV_RUNTIME_SEARCHED_DIRS,
    VLC_PYTHON_MODULE,
    VLC_BACKEND_ERROR,
    VLC_RUNTIME_SEARCHED_DIRS,
    PLAYBACK_BACKEND_MPV_EXPERIMENTAL,
    PLAYBACK_BACKEND_QT_HYBRID,
    PLAYBACK_BACKEND_VLC_EXPERIMENTAL,
    get_configured_playback_backend,
    resolve_runtime_playback_backend,
)

# Suppress OpenCV logs
cv2.setLogLevel(0)

mpv = MPV_PYTHON_MODULE
vlc = VLC_PYTHON_MODULE


class MpvGlWidget(QOpenGLWidget):
    """QOpenGLWidget that renders MPV frames via the libmpv render API.

    This avoids the native HWND / D3D11 swap chain entirely — MPV renders into
    Qt's FBO via OpenGL, so loadfile replace and window resizes are always safe.
    No more 0xe24c4a02 GPU driver crashes.
    """

    # Emitted on the Qt thread after the first frame is painted (used to
    # synchronise the reveal: hide the pixmap cover only once MPV has actually
    # drawn the first frame of the new file).
    frame_painted = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mpv_render_ctx = None
        self._update_pending = False
        self._render_ready = False  # True only when MPV has signalled a new frame
        self._emit_frame_painted = False  # set True by _begin_mpv_reveal to arm one-shot signal
        # Keep proc address resolver alive — ctypes GCs CFUNCTYPE objects otherwise
        self._proc_address_fn = None
        # Prevent Qt from auto-clearing the FBO before paintGL — without this,
        # every resize/restore clears to black even when paintGL returns early,
        # compositing a black rectangle over the pixmap behind us.
        self.setAutoFillBackground(False)
        self.setUpdateBehavior(QOpenGLWidget.UpdateBehavior.PartialUpdate)

    def set_render_context(self, ctx):
        """Called after MPV and its render context are created."""
        self._mpv_render_ctx = ctx
        # update_cb is called from MPV's internal thread — must marshal to Qt thread
        ctx.update_cb = self._on_mpv_update

    def _on_mpv_update(self):
        """Called from MPV thread when a new frame is ready. Posts to Qt thread."""
        if not self._update_pending:
            self._update_pending = True
            try:
                QMetaObject.invokeMethod(self, '_schedule_update', Qt.ConnectionType.QueuedConnection)
            except RuntimeError:
                # Widget was destroyed — stop trying to update
                self._update_pending = False

    @Slot()
    def _schedule_update(self):
        self._update_pending = False
        self._render_ready = True
        self.update()  # triggers paintGL on the Qt thread

    def initializeGL(self):
        pass  # Render context is created externally via set_render_context()

    def paintGL(self):
        if self._mpv_render_ctx is None or not self._render_ready:
            return
        self._render_ready = False
        try:
            ratio = self.devicePixelRatio()
            w = int(self.width() * ratio)
            h = int(self.height() * ratio)
            fbo = int(self.defaultFramebufferObject())
            self._mpv_render_ctx.render(
                flip_y=True,
                opengl_fbo={'w': w, 'h': h, 'fbo': fbo},
            )
            self._mpv_render_ctx.report_swap()
        except Exception:
            pass
        # One-shot: notify reveal machinery that a real frame has been painted.
        if self._emit_frame_painted:
            self._emit_frame_painted = False
            self.frame_painted.emit()

    def resizeGL(self, w, h):
        self.update()

    def cleanup(self):
        """Release the render context before the GL context is destroyed."""
        ctx = self._mpv_render_ctx
        if ctx is None:
            return
        # Clear first so paintGL and _on_mpv_update see None immediately.
        self._mpv_render_ctx = None
        self._render_ready = False
        self._update_pending = False
        try:
            # Disconnect the update callback before freeing — prevents MPV's
            # internal thread from firing update_cb on an already-freed handle.
            ctx.update_cb = None
        except Exception:
            pass
        try:
            ctx.free()
        except Exception:
            pass


class VideoPlayerWidget(QWidget):
    """Hybrid video player using QMediaPlayer for playback and OpenCV for frame extraction."""
    _mpv_orphan_players = []
    _mpv_init_lock = None  # threading.Lock — created lazily to avoid import-time issues
    _vlc_orphan_players = []

    # Signals
    frame_changed = Signal(int, float)  # frame_number, time_ms
    playback_finished = Signal()
    playback_started = Signal()  # Emitted when playback starts
    playback_paused = Signal()   # Emitted when playback pauses
    _vlc_loop_end_crossed = Signal()  # Emitted from VLC thread when segment loop end is reached

    def __init__(self):
        super().__init__()
        self.video_path = None
        self.cap = None  # OpenCV capture for frame extraction
        self.pixmap_item = None  # For displaying OpenCV frames when paused
        self.video_item = None  # QGraphicsVideoItem for QMediaPlayer

        # Video properties
        self.total_frames = 0
        self.fps = 0
        self.duration_ms = 0

        # Playback state
        self.is_playing = False
        self.current_frame = 0
        self.playback_speed = 1.0

        # Loop state
        self.loop_enabled = False
        self.loop_start = None
        self.loop_end = None

        # Corruption detection
        self.consecutive_frame_failures = 0
        self.corruption_warning_shown = False
        self._backend_fallback_warned = False
        self.configured_playback_backend = PLAYBACK_BACKEND_QT_HYBRID
        self.runtime_playback_backend = PLAYBACK_BACKEND_QT_HYBRID
        self.mpv_player = None
        self.mpv_widget = None
        self.mpv_host_view = None
        self._mpv_surface_active = False  # True only when MPV should be covering the viewport
        # Parking widget: mpv_widget is reparented here while not playing.
        # It stays hidden the entire time it is parked, so no native window
        # flash occurs — the GL context is preserved, just detached from the
        # viewport's paint tree so its FBO can't corrupt the pixmap display.
        self._mpv_parking_widget = QWidget()
        self._mpv_parking_widget.setFixedSize(1, 1)
        self._mpv_parking_widget.hide()
        self.mpv_geometry_timer = QTimer(self)
        self.mpv_geometry_timer.setInterval(100)
        self.mpv_geometry_timer.timeout.connect(self._update_mpv_geometry_from_pixmap)
        self._mpv_pending_reveal = False
        self._mpv_reveal_deadline_monotonic = 0.0
        self._mpv_reveal_timer = QTimer(self)
        self._mpv_reveal_timer.setInterval(16)
        self._mpv_reveal_timer.timeout.connect(self._try_reveal_mpv_surface)
        self._mpv_estimated_position_ms = 0.0
        self._mpv_play_started_monotonic = 0.0
        self._mpv_play_base_position_ms = 0.0
        self._active_forward_backend = PLAYBACK_BACKEND_QT_HYBRID
        self._mpv_loop_fallback_warned = False
        self._mpv_needs_reload = True
        self._mpv_ready_for_seeks = False  # True after file-loaded event
        self._mpv_vo_ready = False         # True after 30ms settle post file-loaded; gates command() calls
        self.vlc_instance = None
        self.vlc_player = None
        self.vlc_widget = None
        self.vlc_host_view = None
        self.vlc_geometry_timer = QTimer(self)
        self.vlc_geometry_timer.setInterval(100)
        self.vlc_geometry_timer.timeout.connect(self._update_vlc_geometry_from_pixmap)
        self._vlc_pending_reveal = False
        self._vlc_reveal_deadline_monotonic = 0.0
        self._vlc_reveal_force_deadline_monotonic = 0.0
        self._vlc_reveal_start_position_ms = 0.0
        self._vlc_reveal_loop_start_ms = None  # When set, reveal gates on exact loop_start position
        self._vlc_reveal_require_stable = False
        self._vlc_reveal_ready_hits = 0
        self._vlc_reveal_hold_play = False
        self._vlc_next_start_from_still = False
        self._vlc_reveal_timer = QTimer(self)
        self._vlc_reveal_timer.setInterval(16)
        self._vlc_reveal_timer.timeout.connect(self._try_reveal_vlc_surface)
        self._vlc_estimated_position_ms = 0.0
        self._vlc_play_started_monotonic = 0.0
        self._vlc_play_base_position_ms = 0.0
        self._vlc_needs_reload = True
        self._vlc_last_widget_rect = QRect(0, 0, 1, 1)
        self._vlc_end_reached_flag = False
        self._vlc_loop_end_flag = False   # Set by VLC thread, consumed by position timer
        self._vlc_loop_end_guard = False  # Prevents double-firing within one loop cycle
        self._vlc_event_manager = None
        self._vlc_end_event_handler = None
        self._vlc_position_event_handler = None
        self._vlc_last_progress_ms = None
        self._vlc_stall_ticks = 0
        self._vlc_last_loop_restart_monotonic = 0.0
        self._vlc_soft_restart_deadline_monotonic = 0.0
        self._vlc_soft_restart_pending = False
        self._vlc_cover_label = None
        self._vlc_cover_active = False
        self._opencv_cover_label = None  # QLabel overlay for reverse/OpenCV frames above MPV widget
        self._loop_debug_last_log_monotonic = 0.0
        self._qt_video_source_path = None
        self._refresh_backend_selection()

        # QMediaPlayer for smooth playback
        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.audio_output.setMuted(True)  # Mute audio by default
        self.media_player.setAudioOutput(self.audio_output)

        # Connect media player signals
        self.media_player.positionChanged.connect(self._on_position_changed)
        self.media_player.playbackStateChanged.connect(self._on_playback_state_changed)

        # Timer for position updates (syncs frame numbers)
        self.position_timer = QTimer()
        self.position_timer.setInterval(16)  # ~60 FPS update rate
        self.position_timer.timeout.connect(self._update_frame_from_position)

        # Cross-thread signal: VLC position event fires on VLC thread, delivered on Qt main thread
        self._vlc_loop_end_crossed.connect(self._on_vlc_loop_end_crossed)

        self._mpv_instance_generation = 0  # incremented on each new MPV instance
        self._mpv_load_generation = 0      # incremented on each loadfile call; filters stale events
        self._mpv_event_gen_box = None     # mutable list shared with event callback; [0] = current gen

        # MPV seek throttle — coalesces rapid scrub seeks, fires the last one after 50ms idle
        self._mpv_seek_pending_ms = None
        self._mpv_seek_was_playing = False
        self._mpv_pending_play_speed = None  # set when play() fires before file-loaded event
        self._mpv_seek_timer = QTimer(self)
        self._mpv_seek_timer.setSingleShot(True)
        self._mpv_seek_timer.setInterval(50)
        self._mpv_seek_timer.timeout.connect(self._flush_mpv_seek)

        # Polling timer for VLC loop-end detection — samples get_time() at 50ms intervals
        # which is ~5x faster than VLC's own PositionChanged event, and works regardless
        # of VLC decode speed (4K etc. where wall-clock != media-clock).
        self._vlc_loop_end_wall_timer = QTimer(self)
        self._vlc_loop_end_wall_timer.setInterval(50)
        self._vlc_loop_end_wall_timer.timeout.connect(self._on_vlc_loop_end_wall_timer)

    def _refresh_backend_selection(self):
        """Resolve playback backend setting to runtime backend.

        Unsupported selections are safely downgraded.
        """
        self.configured_playback_backend = get_configured_playback_backend()
        self.runtime_playback_backend = resolve_runtime_playback_backend(self.configured_playback_backend)

        if self.runtime_playback_backend != self.configured_playback_backend:
            if not self._backend_fallback_warned:
                reason = ''
                if self.configured_playback_backend == 'mpv_experimental' and mpv is None and MPV_BACKEND_ERROR:
                    reason = f" Reason: {MPV_BACKEND_ERROR}"
                    if not MPV_RUNTIME_SEARCHED_DIRS and os.name == 'nt':
                        reason += (
                            " Hint: place mpv-1.dll in "
                            "'third_party/mpv/windows-x86_64/' or in 'venv/Scripts/'."
                        )
                if self.configured_playback_backend == 'vlc_experimental' and vlc is None and VLC_BACKEND_ERROR:
                    reason = f" Reason: {VLC_BACKEND_ERROR}"
                    if not VLC_RUNTIME_SEARCHED_DIRS and os.name == 'nt':
                        reason += (
                            " Hint: place libvlc.dll/libvlccore.dll in "
                            "'third_party/vlc/windows-x86_64/'."
                        )
                print(
                    f"[VIDEO] Backend '{self.configured_playback_backend}' not active; "
                    f"using '{self.runtime_playback_backend}'.{reason}"
                )
                self._backend_fallback_warned = True
        else:
            self._backend_fallback_warned = False

    def _log_loop_debug(self, message: str, force: bool = False):
        """Loop debug logging intentionally disabled for normal runtime."""
        _ = (message, force)
        return

    def _is_using_mpv_backend(self) -> bool:
        return self.runtime_playback_backend == PLAYBACK_BACKEND_MPV_EXPERIMENTAL

    def _is_using_vlc_backend(self) -> bool:
        return self.runtime_playback_backend == PLAYBACK_BACKEND_VLC_EXPERIMENTAL

    def _is_mpv_forward_active(self) -> bool:
        return (
            self._active_forward_backend == PLAYBACK_BACKEND_MPV_EXPERIMENTAL
            and self.mpv_player is not None
            and self.playback_speed >= 0
        )

    def _is_vlc_forward_active(self) -> bool:
        return (
            self._active_forward_backend == PLAYBACK_BACKEND_VLC_EXPERIMENTAL
            and self.vlc_player is not None
            and self.playback_speed >= 0
        )

    def _get_live_pixmap_item(self):
        """Return pixmap item only when its underlying Qt object is still alive."""
        item = self.pixmap_item
        if item is None:
            return None
        try:
            item.scene()
            return item
        except RuntimeError:
            self.pixmap_item = None
            return None

    def _get_live_pixmap_scene(self):
        """Return (item, scene) when pixmap item and scene are valid."""
        item = self._get_live_pixmap_item()
        if item is None:
            return None, None
        try:
            return item, item.scene()
        except RuntimeError:
            self.pixmap_item = None
            return None, None

    def _get_live_video_item(self):
        """Return video item only when its underlying Qt object is still alive."""
        item = self.video_item
        if item is None:
            return None
        try:
            item.zValue()
            return item
        except RuntimeError:
            self.video_item = None
            return None

    def set_view_transformed(self, transformed: bool):
        """Hint from viewer zoom/pan state to choose compatible render path."""
        _ = bool(transformed)
        # Keep native backend active; only refresh geometry against the new transform.
        self.sync_external_surface_geometry()

    def prewarm_gl_widget(self, view):
        """Create and warm up the MpvGlWidget GL context before first play.

        QOpenGLWidget initializes its native GL context on first show(), which
        forces a full repaint of the parent window and causes a visible ~1s
        flash. Calling this at startup (while the UI is still loading) hides
        the flash because the window isn't fully visible yet.
        """
        if mpv is None or not self._is_using_mpv_backend():
            return
        if self.mpv_widget is not None:
            return
        try:
            self.mpv_host_view = view
            self.mpv_widget = MpvGlWidget(view.viewport())
            self.mpv_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self.mpv_widget.setStyleSheet('background: transparent;')
            self.mpv_widget.setAutoFillBackground(False)
            self.mpv_widget.setGeometry(0, 0, 1, 1)
            self.mpv_widget.lower()
            self.mpv_widget.show()
        except Exception:
            self.mpv_widget = None

    def _is_segment_loop_active(self) -> bool:
        return bool(self.loop_enabled and self.loop_start is not None and self.loop_end is not None)

    def _get_segment_loop_bounds_frames(self) -> tuple[int, int] | None:
        if not self._is_segment_loop_active() or self.total_frames <= 0:
            return None

        start_frame = max(0, min(int(self.loop_start), self.total_frames - 1))
        end_frame = max(0, min(int(self.loop_end), self.total_frames - 1))
        if start_frame > end_frame:
            start_frame, end_frame = end_frame, start_frame
        return start_frame, end_frame

    def _get_segment_loop_bounds_ms(self) -> tuple[float, float] | None:
        frame_bounds = self._get_segment_loop_bounds_frames()
        if frame_bounds is None or self.fps <= 0:
            return None

        frame_ms = 1000.0 / float(self.fps)
        start_ms = float(frame_bounds[0]) * frame_ms
        # Set ab-loop-b to the start of end_frame — MPV loops back when it
        # reaches this timestamp, so end_frame is the last frame displayed.
        end_ms = float(frame_bounds[1]) * frame_ms
        if end_ms <= start_ms:
            end_ms = start_ms + frame_ms
        return start_ms, end_ms

    def _apply_mpv_loop_settings(self, clear_when_inactive: bool = False) -> bool:
        if self.mpv_player is None:
            return True

        try:
            bounds_ms = self._get_segment_loop_bounds_ms()
            if bounds_ms is None:
                if not clear_when_inactive:
                    return True
                self._mpv_set_property('ab-loop-a', 'no')
                self._mpv_set_property('ab-loop-b', 'no')
                return True

            loop_start_ms, loop_end_ms = bounds_ms
            self._mpv_set_property('ab-loop-a', f'{(loop_start_ms / 1000.0):.6f}')
            self._mpv_set_property('ab-loop-b', f'{(loop_end_ms / 1000.0):.6f}')
            return True
        except Exception as e:
            print(f"[VIDEO] Failed to configure mpv A/B loop: {e}")
            return False

    def _set_mpv_visible(self, visible: bool):
        """Show/hide MPV output (QOpenGLWidget) and the pixmap_item cover.

        With vo=libmpv (render API) the mpv_widget is a QOpenGLWidget child of the
        viewport — resizing and hiding it are always safe (no D3D11 swap chain).

          - MPV visible  → show mpv_widget, hide pixmap_item cover
          - MPV hidden   → hide mpv_widget, show pixmap_item cover

        The geometry timer keeps the widget sized to the viewport during active
        playback (e.g. window resize while playing).
        """
        if not visible:
            self._mpv_surface_active = False
            self.mpv_geometry_timer.stop()
            try:
                if self.mpv_widget:
                    self.mpv_widget.setGeometry(-8, -8, 4, 4)
            except RuntimeError:
                pass
            try:
                if self.pixmap_item:
                    self.pixmap_item.show()
            except RuntimeError:
                pass
        else:
            self._mpv_surface_active = True
            self._hide_opencv_cover_overlay()
            self._sync_mpv_widget_to_viewport()
            try:
                if self.mpv_widget:
                    self.mpv_widget.raise_()
            except RuntimeError:
                pass
            try:
                if self.pixmap_item:
                    self.pixmap_item.hide()
            except RuntimeError:
                pass
            if not self.mpv_geometry_timer.isActive():
                self.mpv_geometry_timer.start()

    def _sync_mpv_widget_to_viewport(self):
        """Resize mpv_widget to match the pixmap item's on-screen rect.

        When zoom-to-fit, this equals the full viewport. When zoomed/panned,
        this follows the transformed pixmap bounds — same approach as VLC.
        With vo=libmpv (QOpenGLWidget) resizing is always safe — no D3D11 swap chain.
        """
        try:
            if not self.mpv_widget:
                return
            # Only resize when MPV is supposed to be covering the viewport.
            # Without this guard, zoom triggers sync and resizes the widget
            # back to full size even when it's been moved off-screen (paused).
            if not self._mpv_surface_active:
                return
            try:
                import shiboken6
                if not shiboken6.isValid(self.mpv_widget):
                    self.mpv_widget = None
                    return
            except Exception:
                pass
            view = self._resolve_mpv_target_view()
            if view is None:
                return
            self.mpv_host_view = view
            vp = view.viewport()
            vp_rect = vp.rect()

            # Try to match the pixmap item's screen rect (respects zoom/pan).
            item = self._get_live_pixmap_item()
            if item is not None:
                try:
                    scene_rect = item.sceneBoundingRect()
                    mapped = view.mapFromScene(scene_rect).boundingRect().normalized()
                    if mapped.width() > 1 and mapped.height() > 1:
                        self.mpv_widget.setGeometry(mapped)
                        return
                except Exception:
                    pass

            # Fallback: cover full viewport (zoom-to-fit or no pixmap item yet).
            if vp_rect.width() > 0 and vp_rect.height() > 0:
                self.mpv_widget.setGeometry(vp_rect)
        except RuntimeError:
            self.mpv_widget = None

    def _set_vlc_visible(self, visible: bool):
        """Show/hide vlc surface if it exists."""
        try:
            if self.vlc_widget:
                try:
                    import shiboken6
                    if not shiboken6.isValid(self.vlc_widget):
                        self.vlc_widget = None
                        return
                except Exception:
                    pass
                if visible:
                    self.vlc_widget.show()
                    self._update_vlc_geometry_from_pixmap()
                    self._rebind_vlc_output_target()
                    if self._vlc_cover_active and self._vlc_cover_label is not None:
                        try:
                            self._vlc_cover_label.raise_()
                        except Exception:
                            pass
                    if not self.vlc_geometry_timer.isActive():
                        self.vlc_geometry_timer.start()
                else:
                    self.vlc_geometry_timer.stop()
                    old_rect = QRect(self._vlc_last_widget_rect)
                    self.vlc_widget.hide()
                    self.vlc_widget.setGeometry(QRect(0, 0, 1, 1))
                    self._vlc_last_widget_rect = QRect(0, 0, 1, 1)
                    try:
                        parent = self.vlc_widget.parentWidget()
                        if parent is not None and old_rect.isValid() and not old_rect.isEmpty():
                            parent.update(old_rect.adjusted(-2, -2, 2, 2))
                    except Exception:
                        pass
        except RuntimeError:
            self.vlc_widget = None

    def _update_vlc_geometry_from_pixmap(self):
        """Keep vlc proxy geometry aligned with current pixmap frame size."""
        item = self._get_live_pixmap_item()
        if not self.vlc_widget or item is None:
            return
        try:
            pixmap = item.pixmap()
            if not pixmap or pixmap.isNull():
                return

            view = self._resolve_mpv_target_view()
            if view is None:
                return
            self.vlc_host_view = view

            scene_rect = item.sceneBoundingRect()
            mapped_poly = view.mapFromScene(scene_rect)
            widget_rect = mapped_poly.boundingRect()
            widget_rect = widget_rect.normalized()
            old_rect = QRect(self._vlc_last_widget_rect)
            if widget_rect.width() > 1 and widget_rect.height() > 1:
                self.vlc_widget.setGeometry(widget_rect)
                self._vlc_last_widget_rect = QRect(widget_rect)
                self._rebind_vlc_output_target()
            else:
                self.vlc_widget.setGeometry(QRect(0, 0, 1, 1))
                self._vlc_last_widget_rect = QRect(0, 0, 1, 1)
            self._update_vlc_cover_geometry_from_pixmap()
            try:
                parent = self.vlc_widget.parentWidget()
                if parent is not None:
                    repaint_rect = old_rect.united(self._vlc_last_widget_rect).adjusted(-2, -2, 2, 2)
                    if repaint_rect.isValid() and not repaint_rect.isEmpty():
                        parent.update(repaint_rect)
            except Exception:
                pass
        except RuntimeError:
            self.vlc_widget = None

    def _hide_vlc_cover_overlay(self):
        """Hide temporary cover overlay used for seamless image->video handoff."""
        self._vlc_cover_active = False
        label = self._vlc_cover_label
        if label is None:
            return
        try:
            label.hide()
            label.setPixmap(QPixmap())
        except RuntimeError:
            self._vlc_cover_label = None

    def _show_vlc_cover_overlay(self):
        """Show a still preview above VLC while first frame stabilizes."""
        item = self._get_live_pixmap_item()
        if item is None:
            self._hide_vlc_cover_overlay()
            return
        try:
            pixmap = item.pixmap()
        except RuntimeError:
            self.pixmap_item = None
            self._hide_vlc_cover_overlay()
            return
        if pixmap is None or pixmap.isNull():
            self._hide_vlc_cover_overlay()
            return
        target_view = self._resolve_mpv_target_view()
        if target_view is None:
            self._hide_vlc_cover_overlay()
            return
        target_parent = target_view.viewport()
        label = self._vlc_cover_label
        try:
            if label is None or label.parentWidget() is not target_parent:
                if label is not None:
                    try:
                        label.hide()
                        label.deleteLater()
                    except Exception:
                        pass
                label = QLabel(target_parent)
                label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                label.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
                label.setScaledContents(True)
                label.hide()
                self._vlc_cover_label = label
            label.setPixmap(pixmap)
            self._vlc_cover_active = True
            self._update_vlc_cover_geometry_from_pixmap()
            label.show()
            label.raise_()
        except RuntimeError:
            self._vlc_cover_label = None
            self._vlc_cover_active = False

    def _update_vlc_cover_geometry_from_pixmap(self):
        """Align temporary VLC cover overlay with current media rect."""
        if not self._vlc_cover_active:
            return
        label = self._vlc_cover_label
        item = self._get_live_pixmap_item()
        if label is None or item is None:
            return
        try:
            target_view = self._resolve_mpv_target_view()
            if target_view is None:
                return
            target_parent = target_view.viewport()
            if label.parentWidget() is not target_parent:
                return
            scene_rect = item.sceneBoundingRect()
            mapped_poly = target_view.mapFromScene(scene_rect)
            widget_rect = mapped_poly.boundingRect().normalized()
            if widget_rect.width() > 1 and widget_rect.height() > 1:
                label.setGeometry(widget_rect)
                label.raise_()
            else:
                label.hide()
        except RuntimeError:
            self._vlc_cover_label = None
            self._vlc_cover_active = False

    def _update_opencv_cover_geometry(self):
        """Align OpenCV reverse-playback overlay with current media rect (e.g. on zoom)."""
        label = self._opencv_cover_label
        if label is None:
            return
        try:
            if not label.isVisible():
                return
            view = self._resolve_mpv_target_view()
            if view is None:
                return
            target_parent = view.viewport()
            if label.parentWidget() is not target_parent:
                return
            item = self._get_live_pixmap_item()
            if item is None:
                return
            scene_rect = item.sceneBoundingRect()
            widget_rect = view.mapFromScene(scene_rect).boundingRect().normalized()
            if widget_rect.width() > 1 and widget_rect.height() > 1:
                label.setGeometry(widget_rect)
                label.raise_()
            else:
                label.hide()
        except RuntimeError:
            self._opencv_cover_label = None

    def _hide_opencv_cover_overlay(self):
        """Hide the OpenCV reverse-playback cover overlay."""
        label = self._opencv_cover_label
        if label is None:
            return
        try:
            label.hide()
            label.setPixmap(QPixmap())
        except RuntimeError:
            self._opencv_cover_label = None

    def _show_opencv_frame_as_overlay(self, pixmap: 'QPixmap'):
        """Display an OpenCV frame as a native QLabel overlay above MPV widget.

        Since QOpenGLWidget always composites on top of QGraphicsScene items,
        we use a native QLabel sibling raised above mpv_widget instead of
        writing to pixmap_item (which lives in the scene and gets covered).
        """
        view = self._resolve_mpv_target_view()
        if view is None:
            return
        target_parent = view.viewport()
        label = self._opencv_cover_label
        try:
            if label is None or label.parentWidget() is not target_parent:
                if label is not None:
                    try:
                        label.hide()
                        label.deleteLater()
                    except Exception:
                        pass
                label = QLabel(target_parent)
                label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                label.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
                label.setScaledContents(True)
                label.hide()
                self._opencv_cover_label = label
            label.setPixmap(pixmap)
            # Size to match the media rect in viewport coordinates.
            item = self._get_live_pixmap_item()
            if item is not None:
                try:
                    scene_rect = item.sceneBoundingRect()
                    widget_rect = view.mapFromScene(scene_rect).boundingRect().normalized()
                    if widget_rect.width() > 1 and widget_rect.height() > 1:
                        label.setGeometry(widget_rect)
                except Exception:
                    pass
            else:
                label.setGeometry(view.viewport().rect())
            label.show()
            label.raise_()
        except RuntimeError:
            self._opencv_cover_label = None

    def _teardown_vlc(self, drop_player: bool = False):
        """Release vlc runtime resources if initialized."""
        self._cancel_vlc_reveal()
        self._hide_vlc_cover_overlay()
        self.vlc_geometry_timer.stop()
        self._vlc_estimated_position_ms = 0.0
        self._vlc_play_started_monotonic = 0.0
        self._vlc_play_base_position_ms = 0.0
        self._vlc_needs_reload = True
        self._vlc_end_reached_flag = False
        self._vlc_last_progress_ms = None
        self._vlc_stall_ticks = 0
        self._vlc_soft_restart_deadline_monotonic = 0.0
        self._vlc_soft_restart_pending = False
        self._unbind_vlc_events()
        if self._active_forward_backend == PLAYBACK_BACKEND_VLC_EXPERIMENTAL:
            self._active_forward_backend = PLAYBACK_BACKEND_QT_HYBRID
        player = self.vlc_player
        instance = self.vlc_instance
        if player is not None:
            try:
                player.stop()
            except Exception:
                pass
        if drop_player:
            if player is not None:
                try:
                    player.release()
                except Exception:
                    VideoPlayerWidget._vlc_orphan_players.append(player)
            if instance is not None:
                try:
                    instance.release()
                except Exception:
                    VideoPlayerWidget._vlc_orphan_players.append(instance)
            self.vlc_player = None
            self.vlc_instance = None

        if self.vlc_widget is not None:
            try:
                self.vlc_widget.hide()
                self.vlc_widget.deleteLater()
            except Exception:
                pass
            self.vlc_widget = None
        self._vlc_last_widget_rect = QRect(0, 0, 1, 1)
        self.vlc_host_view = None

    def _set_vlc_muted(self, muted: bool):
        if self.vlc_player is None:
            return
        try:
            self.vlc_player.audio_set_mute(bool(muted))
        except Exception:
            pass

    def _bind_vlc_events(self):
        """Attach VLC events for end-of-media and segment loop boundary detection."""
        if self.vlc_player is None or vlc is None:
            return
        self._unbind_vlc_events()
        try:
            event_manager = self.vlc_player.event_manager()
        except Exception:
            self._vlc_event_manager = None
            self._vlc_end_event_handler = None
            self._vlc_position_event_handler = None
            return

        def _on_end_reached(_event):
            print(f"[LOOP_DBG] MediaPlayerEndReached fired")
            self._vlc_end_reached_flag = True

        def _on_position_changed(_event):
            # Runs on VLC internal thread — safe to set Python flags and call vlc_player methods.
            # Do NOT call any Qt UI methods here.
            if not self._is_segment_loop_active() or self._vlc_loop_end_guard:
                return
            if self.fps <= 0 or self.duration_ms <= 0:
                return
            try:
                pos_ratio = float(self.vlc_player.get_position())
                if pos_ratio < 0:
                    return
                pos_ms = pos_ratio * float(self.duration_ms)
                frame_ms = 1000.0 / float(self.fps)
                end_frame = max(0, min(int(self.loop_end), self.total_frames - 1))
                loop_end_ms = float(end_frame) * frame_ms
                current_frame_at_event = int(pos_ms / frame_ms)
                print(f"[LOOP_DBG] pos_ms={pos_ms:.1f} loop_end_ms={loop_end_ms:.1f} "
                      f"frame={current_frame_at_event} end_frame={end_frame}")
                if pos_ms >= (loop_end_ms - frame_ms):
                    self._vlc_loop_end_guard = True
                    # Pause VLC immediately from this thread to stop overshoot.
                    # The main thread will handle the seek-back and cover display.
                    try:
                        self.vlc_player.pause()
                    except Exception:
                        pass
                    # Set flag — main thread timer picks it up within 16ms.
                    self._vlc_loop_end_flag = True
                    print(f"[LOOP_DBG] SET FLAG + paused at pos_ms={pos_ms:.1f}")
            except Exception:
                pass

        try:
            event_manager.event_attach(vlc.EventType.MediaPlayerEndReached, _on_end_reached)
            event_manager.event_attach(vlc.EventType.MediaPlayerPositionChanged, _on_position_changed)
            self._vlc_event_manager = event_manager
            self._vlc_end_event_handler = _on_end_reached
            self._vlc_position_event_handler = _on_position_changed
        except Exception as e:
            print(f"[VIDEO] Failed to bind VLC events: {e}")
            self._vlc_event_manager = None
            self._vlc_end_event_handler = None
            self._vlc_position_event_handler = None

    def _unbind_vlc_events(self):
        """Detach VLC events on teardown/recreate."""
        if self._vlc_event_manager is not None and vlc is not None:
            try:
                if self._vlc_end_event_handler is not None:
                    self._vlc_event_manager.event_detach(
                        vlc.EventType.MediaPlayerEndReached,
                        self._vlc_end_event_handler,
                    )
            except Exception:
                pass
            try:
                if self._vlc_position_event_handler is not None:
                    self._vlc_event_manager.event_detach(
                        vlc.EventType.MediaPlayerPositionChanged,
                        self._vlc_position_event_handler,
                    )
            except Exception:
                pass
        self._vlc_event_manager = None
        self._vlc_end_event_handler = None
        self._vlc_position_event_handler = None

    @Slot(int)
    def _on_mpv_file_loaded(self, load_generation: int):
        """Called on Qt main thread when MPV has finished loading the new file.

        With vo=libmpv (render API) there is no D3D11 VO to initialize — commands
        are safe as soon as file-loaded fires.  We keep a tiny 30ms deferral so
        MPV's internal demuxer/decoder state has settled before we issue seeks.
        """
        if self.mpv_player is None:
            return
        if load_generation != self._mpv_load_generation:
            return  # stale
        self._mpv_ready_for_seeks = True
        QTimer.singleShot(30, lambda gen=load_generation: self._on_mpv_ready_for_commands(gen))

    def _on_mpv_ready_for_commands(self, load_generation: int):
        """Execute deferred post-file-loaded commands once MPV state has settled."""
        if self.mpv_player is None:
            return
        if load_generation != self._mpv_load_generation:
            return  # stale — user switched video again during the 80ms window
        # VO is now stable — allow command() calls.
        self._mpv_vo_ready = True
        # Apply loop settings.
        self._apply_mpv_loop_settings()
        # Flush any pending seek.
        if self._mpv_seek_pending_ms is not None:
            self._flush_mpv_seek()
        # Execute deferred play if play() was called before file was ready.
        if self._mpv_pending_play_speed is not None:
            speed = self._mpv_pending_play_speed
            self._mpv_pending_play_speed = None
            self._mpv_string_command('set', 'speed', str(speed))
            self._mpv_string_command('set', 'pause', 'no')
            self._begin_mpv_reveal()

    @Slot()
    def _on_vlc_loop_end_crossed(self):
        """Called on Qt main thread when VLC position event signals loop_end was reached."""
        if not self._is_segment_loop_active() or not self.is_playing:
            self._vlc_loop_end_guard = False
            return
        if not self._is_vlc_forward_active():
            self._vlc_loop_end_guard = False
            return
        if self.fps <= 0:
            self._vlc_loop_end_guard = False
            return

        frame_ms = 1000.0 / float(self.fps)
        end_frame = max(0, min(int(self.loop_end), self.total_frames - 1))
        start_frame = max(0, int(self.loop_start if self.loop_start is not None else 0))
        start_position_ms = float(start_frame) * frame_ms

        # Load start_frame into pixmap_item so the cover shows the correct first frame.
        try:
            self._show_opencv_frame(start_frame)
        except Exception:
            pass

        # Raise cover over VLC WITHOUT hiding VLC — avoids blank-frame repaint gap.
        # VLC keeps rendering underneath; the cover sits on top hiding any overshoot.
        self._cancel_vlc_reveal()
        try:
            if self.pixmap_item:
                self.pixmap_item.show()
        except RuntimeError:
            pass
        self._show_vlc_cover_overlay()

        # Seek VLC back to loop start, resume, reveal once VLC reaches start.
        self._seek_vlc_position_ms(start_position_ms)
        try:
            self.vlc_player.play()
        except Exception:
            pass
        self._begin_vlc_reveal(
            delay_ms=16, force_ms=800, require_stable=False,
            loop_start_ms=start_position_ms,
        )
        # Start poll timer for next loop end.
        self._schedule_vlc_loop_end_wall_timer(start_position_ms)

    def _schedule_vlc_loop_end_wall_timer(self, known_start_ms: float = -1.0):
        """Start the VLC loop-end polling timer.

        The timer polls get_time() every 50ms and triggers loop-end cover the
        moment VLC reaches (loop_end - 1 frame). This works regardless of
        decode speed (4K etc.) because it reads actual media time, not wall time.
        """
        self._vlc_loop_end_wall_timer.stop()
        if not self._is_segment_loop_active() or self.fps <= 0:
            return
        print(f"[LOOP_DBG] Starting loop-end poll timer (known_start_ms={known_start_ms:.1f})")
        self._vlc_loop_end_wall_timer.start()

    @Slot()
    def _on_vlc_loop_end_wall_timer(self):
        """Poll VLC get_time() every 50ms; trigger loop-end cover when close enough."""
        if not self._is_segment_loop_active() or not self.is_playing:
            self._vlc_loop_end_wall_timer.stop()
            return
        if not self._is_vlc_forward_active():
            self._vlc_loop_end_wall_timer.stop()
            return
        if self._vlc_loop_end_guard:
            return
        try:
            pos_ms = float(self.vlc_player.get_time()) if self.vlc_player else -1.0
        except Exception:
            pos_ms = -1.0
        if pos_ms <= 0:
            return
        if self.fps <= 0:
            return
        frame_ms = 1000.0 / float(self.fps)
        end_frame = max(0, min(int(self.loop_end), self.total_frames - 1))
        loop_end_ms = float(end_frame) * frame_ms
        # Trigger when within 1 frame of loop_end.
        if pos_ms >= (loop_end_ms - frame_ms):
            print(f"[LOOP_DBG] POLL TIMER triggered: pos_ms={pos_ms:.1f} loop_end_ms={loop_end_ms:.1f}")
            self._vlc_loop_end_wall_timer.stop()
            self._vlc_loop_end_guard = True
            self._on_vlc_loop_end_crossed()

    def _set_vlc_rate(self, rate: float):
        if self.vlc_player is None:
            return
        safe_rate = max(0.1, float(rate))
        try:
            self.vlc_player.set_rate(safe_rate)
        except Exception:
            pass

    def _rebind_vlc_output_target(self):
        """Re-apply native output target and autoscale after geometry changes."""
        if self.vlc_player is None or self.vlc_widget is None:
            return
        try:
            wid = int(self.vlc_widget.winId())
            if sys.platform.startswith('win'):
                self.vlc_player.set_hwnd(wid)
            elif sys.platform == 'darwin':
                self.vlc_player.set_nsobject(wid)
            else:
                self.vlc_player.set_xwindow(wid)
        except Exception:
            pass
        try:
            self.vlc_player.video_set_scale(0.0)
        except Exception:
            pass
        try:
            self.vlc_player.video_set_aspect_ratio(None)
        except Exception:
            pass

    def _set_vlc_paused(self, paused: bool):
        if self.vlc_player is None:
            return
        try:
            self.vlc_player.set_pause(1 if paused else 0)
        except Exception:
            if paused:
                try:
                    self.vlc_player.pause()
                except Exception:
                    pass
            else:
                try:
                    self.vlc_player.play()
                except Exception:
                    pass

    def _setup_vlc_for_current_video(self) -> bool:
        """Initialize libVLC renderer bound to a scene widget surface."""
        if vlc is None or not self._is_using_vlc_backend():
            return False
        _, scene = self._get_live_pixmap_scene()
        if scene is None or not self.video_path:
            return False

        try:
            target_view = self._resolve_mpv_target_view()
            if target_view is None:
                return False

            target_parent = target_view.viewport()
            if self.vlc_widget is not None and self.vlc_widget.parentWidget() is not target_parent:
                try:
                    self.vlc_widget.hide()
                    self.vlc_widget.deleteLater()
                except Exception:
                    pass
                self.vlc_widget = None

            if self.vlc_widget is None:
                self.vlc_host_view = target_view
                self.vlc_widget = QWidget(target_parent)
                self.vlc_widget.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
                self.vlc_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                self.vlc_widget.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
                self.vlc_widget.setStyleSheet('background: transparent;')
                self.vlc_widget.setGeometry(0, 0, 1, 1)
                self.vlc_widget.show()
            else:
                self.vlc_host_view = target_view

            self._set_vlc_visible(False)
            self._update_vlc_geometry_from_pixmap()

            if self.vlc_instance is None:
                vlc_args = [
                    '--no-video-title-show',
                    '--quiet',
                    '--no-osd',
                    '--no-stats',
                ]
                if sys.platform.startswith('win'):
                    vlc_args.extend(['--directx-device=any'])
                self.vlc_instance = vlc.Instance(vlc_args)
            if self.vlc_player is None:
                self.vlc_player = self.vlc_instance.media_player_new()
            self._bind_vlc_events()
            self._rebind_vlc_output_target()

            media = self.vlc_instance.media_new(str(self.video_path))
            self.vlc_player.set_media(media)
            try:
                media.release()
            except Exception:
                pass

            # Ensure libVLC does not consume interaction events; Qt viewport must
            # keep receiving mouse/key input for drag/zoom/context behavior.
            try:
                self.vlc_player.video_set_mouse_input(False)
            except Exception as e:
                print(f"[VIDEO] VLC mouse-input handoff setup failed: {e}")
            try:
                self.vlc_player.video_set_key_input(False)
            except Exception as e:
                print(f"[VIDEO] VLC key-input handoff setup failed: {e}")

            self._set_vlc_muted(bool(self.audio_output.isMuted()) if self.audio_output else True)
            self._set_vlc_rate(self.playback_speed)
            self._rebind_vlc_output_target()
            self._vlc_needs_reload = False
            self._vlc_end_reached_flag = False
            self._vlc_last_progress_ms = None
            self._vlc_stall_ticks = 0
            self._vlc_soft_restart_deadline_monotonic = 0.0
            self._vlc_soft_restart_pending = False
            return True
        except Exception as e:
            print(f"[VIDEO] Failed to initialize vlc backend: {e}")
            self._teardown_vlc(drop_player=True)
            self.runtime_playback_backend = PLAYBACK_BACKEND_QT_HYBRID
            return False

    def _get_vlc_position_ms(self) -> float | None:
        if self.vlc_player is None:
            return None
        try:
            position_ms = int(self.vlc_player.get_time())
            if position_ms >= 0:
                self._vlc_estimated_position_ms = float(position_ms)
                return float(position_ms)
        except Exception:
            pass

        if not self._is_vlc_forward_active() or not self.is_playing:
            return float(self._vlc_estimated_position_ms)

        speed = max(0.1, float(self.playback_speed))
        elapsed = max(0.0, time.monotonic() - self._vlc_play_started_monotonic)
        estimated = self._vlc_play_base_position_ms + (elapsed * 1000.0 * speed)

        if self.duration_ms > 0:
            estimated = max(0.0, min(float(self.duration_ms), estimated))
        self._vlc_estimated_position_ms = float(estimated)
        return float(self._vlc_estimated_position_ms)

    def _seek_vlc_position_ms(self, position_ms: float):
        self._vlc_estimated_position_ms = float(position_ms)
        self._vlc_last_progress_ms = float(position_ms)
        self._vlc_stall_ticks = 0
        if self.is_playing and self._is_vlc_forward_active():
            self._vlc_play_base_position_ms = float(position_ms)
            self._vlc_play_started_monotonic = time.monotonic()
        if self.vlc_player is None:
            return
        try:
            self.vlc_player.set_time(int(max(0.0, position_ms)))
        except Exception:
            try:
                if self.duration_ms > 0:
                    ratio = max(0.0, min(1.0, float(position_ms) / float(self.duration_ms)))
                    self.vlc_player.set_position(float(ratio))
            except Exception:
                pass
        if position_ms <= 1.0:
            try:
                self.vlc_player.set_position(0.0)
            except Exception:
                pass

    def _restart_vlc_from_position_ms(self, position_ms: float, hard: bool = False, cover_frame: int | None = None, loop_start_ms: float | None = None):
        """Restart VLC from a target position using a cover-overlay loop restart.

        Shows an OpenCV frame as a cover overlay, hides VLC surface, does
        a hard VLC restart, then lets the reveal system swap back to VLC once it
        has a real frame — eliminating the black flash without cutting playback short.

        cover_frame: specific frame to show as cover (e.g. exact loop_end frame).
                     Defaults to last frame of the video if None.
        """
        if self.vlc_player is None:
            return
        now = time.monotonic()
        # Guard against repeated loop restarts while VLC reports stale terminal state.
        if (now - float(self._vlc_last_loop_restart_monotonic or 0.0)) < 0.20:
            print(f"[LOOP_DBG] _restart_vlc_from_position_ms SKIPPED (too soon)")
            return
        self._vlc_last_loop_restart_monotonic = now
        safe_ms = max(0.0, float(position_ms))
        print(f"[LOOP_DBG] _restart_vlc_from_position_ms called: position_ms={position_ms:.1f} cover_frame={cover_frame} loop_start_ms={loop_start_ms}")
        self._vlc_end_reached_flag = False
        self._vlc_soft_restart_pending = False
        self._vlc_soft_restart_deadline_monotonic = 0.0
        self._vlc_estimated_position_ms = safe_ms
        self._vlc_play_base_position_ms = safe_ms
        self._vlc_play_started_monotonic = time.monotonic()
        self._vlc_last_progress_ms = safe_ms
        self._vlc_stall_ticks = 0

        # Capture exact cover frame into pixmap_item.
        # Use the provided cover_frame (e.g. exact loop_end) if given,
        # otherwise fall back to the last frame of the video.
        if self.fps > 0 and self.total_frames > 0:
            if cover_frame is not None:
                frame_to_show = max(0, min(int(cover_frame), self.total_frames - 1))
            else:
                frame_to_show = max(0, self.total_frames - 1)
            try:
                self._show_opencv_frame(frame_to_show)
            except Exception:
                pass

        # Hide VLC surface and show the cover overlay (last frame pixmap).
        # The reveal system will swap back to VLC once it has a real frame.
        self._cancel_vlc_reveal()
        self._set_vlc_visible(False)
        try:
            if self.pixmap_item:
                self.pixmap_item.show()
        except RuntimeError:
            pass
        self._show_vlc_cover_overlay()

        # Hard restart VLC — reliable from any terminal state (Ended/Stopped).
        try:
            self.vlc_player.stop()
        except Exception:
            pass

        # If segment loop is active, set --start-time and --stop-time on the media
        # so VLC enforces the loop boundaries internally — no polling needed.
        if self._is_segment_loop_active() and self.fps > 0 and self.video_path is not None:
            try:
                frame_ms = 1000.0 / float(self.fps)
                end_frame = max(0, min(int(self.loop_end), self.total_frames - 1))
                stop_time_s = float(end_frame + 1) * frame_ms / 1000.0
                start_time_s = safe_ms / 1000.0
                media = self.vlc_instance.media_new(str(self.video_path))
                media.add_option(f':start-time={start_time_s:.6f}')
                media.add_option(f':stop-time={stop_time_s:.6f}')
                self.vlc_player.set_media(media)
                media.release()
                print(f"[LOOP_DBG] set media start={start_time_s:.3f}s stop={stop_time_s:.3f}s")
            except Exception as e:
                print(f"[LOOP_DBG] Failed to set stop-time: {e}")

        try:
            self.vlc_player.play()
        except Exception:
            self._hide_vlc_cover_overlay()
            return
        # No need to seek — start-time option handles it.
        if not self._is_segment_loop_active():
            self._seek_vlc_position_ms(safe_ms)
            QTimer.singleShot(16, lambda ms=safe_ms: self._seek_vlc_position_ms(ms))
        # Start poll timer for loop end cover.
        self._schedule_vlc_loop_end_wall_timer(safe_ms)

        # Tighter reveal: fire as soon as VLC reports position past loop_start.
        self._begin_vlc_reveal(delay_ms=16, force_ms=1200, require_stable=False, loop_start_ms=loop_start_ms)

    def _resolve_mpv_target_view(self):
        """Pick the most suitable QGraphicsView for the current pixmap scene."""
        _, scene = self._get_live_pixmap_scene()
        if scene is None:
            return None
        views = [v for v in scene.views() if v is not None]
        if not views:
            return None

        current = self.mpv_host_view if self.mpv_host_view in views else self.vlc_host_view
        if current is not None and current in views:
            return current

        def _score(v):
            try:
                if not v.isVisible():
                    return -1
                vp = v.viewport()
                if vp is None:
                    return -1
                return int(vp.width()) * int(vp.height())
            except Exception:
                return -1

        return max(views, key=_score)

    def _cancel_mpv_reveal(self):
        self._mpv_pending_reveal = False
        self._mpv_reveal_deadline_monotonic = 0.0
        self._mpv_reveal_timer.stop()
        gl_widget = getattr(self, 'mpv_widget', None)
        if isinstance(gl_widget, MpvGlWidget):
            gl_widget._emit_frame_painted = False

    def _cancel_vlc_reveal(self):
        self._vlc_pending_reveal = False
        self._vlc_reveal_deadline_monotonic = 0.0
        self._vlc_reveal_force_deadline_monotonic = 0.0
        self._vlc_reveal_start_position_ms = 0.0
        self._vlc_reveal_loop_start_ms = None
        self._vlc_reveal_require_stable = False
        self._vlc_reveal_ready_hits = 0
        self._vlc_reveal_hold_play = False
        self._vlc_reveal_timer.stop()

    def hint_next_video_starts_from_still(self, from_still: bool):
        """Hint one-shot reveal behavior for the next VLC start."""
        self._vlc_next_start_from_still = bool(from_still)

    def _begin_vlc_reveal(
        self,
        delay_ms: int = 140,
        force_ms: int = 1400,
        require_stable: bool = False,
        hold_play: bool = False,
        loop_start_ms: float | None = None,
    ):
        """Keep first-frame pixmap visible until VLC starts producing frames.

        hold_play=True: VLC is kept paused at frame 0 during the reveal wait.
        When the reveal fires, VLC is unpaused — guaranteeing no frames are skipped.

        loop_start_ms: when set, reveal fires as soon as VLC reports position >=
                       this value, bypassing the normal threshold arithmetic.
                       Use for segment loop restarts for frame-accurate start.
        """
        if self.vlc_player is None:
            self._cancel_vlc_reveal()
            return
        self._vlc_pending_reveal = True
        self._vlc_reveal_start_position_ms = float(self._vlc_estimated_position_ms or 0.0)
        self._vlc_reveal_loop_start_ms = float(loop_start_ms) if loop_start_ms is not None else None
        self._vlc_reveal_require_stable = bool(require_stable)
        self._vlc_reveal_hold_play = bool(hold_play)
        self._vlc_reveal_ready_hits = 0
        now = time.monotonic()
        self._vlc_reveal_deadline_monotonic = now + max(0.05, (delay_ms / 1000.0))
        self._vlc_reveal_force_deadline_monotonic = now + max(0.45, (force_ms / 1000.0))
        self._vlc_reveal_timer.start()

    def _try_reveal_vlc_surface(self):
        if not self._vlc_pending_reveal:
            self._vlc_reveal_timer.stop()
            return
        if self.vlc_player is None:
            self._hide_vlc_cover_overlay()
            self._cancel_vlc_reveal()
            return
        if not self.is_playing or not self._is_vlc_forward_active():
            self._hide_vlc_cover_overlay()
            self._cancel_vlc_reveal()
            return

        now = time.monotonic()
        reached_min_delay = now >= self._vlc_reveal_deadline_monotonic
        force_ready = now >= self._vlc_reveal_force_deadline_monotonic

        # hold_play mode: VLC is paused at frame 0 — unpause once the min delay
        # has passed, then fall through to the normal position-check reveal so we
        # only show the VLC surface after it has actually rendered a frame.
        if self._vlc_reveal_hold_play:
            if reached_min_delay or force_ready:
                self._vlc_reveal_hold_play = False
                try:
                    self._set_vlc_paused(False)
                except Exception:
                    pass
                self._vlc_play_started_monotonic = time.monotonic()
                # Reset the reveal start position now that VLC is actually playing.
                self._vlc_reveal_start_position_ms = 0.0
                # Give VLC a moment to start producing frames before the position check runs.
                self._vlc_reveal_deadline_monotonic = time.monotonic() + 0.04
            return

        position_ready = False
        strict_mode = bool(self._vlc_reveal_require_stable)
        try:
            backend_pos_ms = float(self.vlc_player.get_time())
        except Exception:
            backend_pos_ms = -1.0
        state_ready = True
        if strict_mode and vlc is not None:
            try:
                state_ready = self.vlc_player.get_state() == getattr(vlc.State, "Playing", None)
            except Exception:
                state_ready = False
        if backend_pos_ms >= 0.0:
            loop_start_gate = self._vlc_reveal_loop_start_ms
            if loop_start_gate is not None:
                # Frame-accurate loop start: reveal exactly when VLC reaches loop_start.
                position_ready = backend_pos_ms >= float(loop_start_gate)
            else:
                reveal_threshold_ms = 35.0
                if self.fps > 0:
                    frame_ms = 1000.0 / float(self.fps)
                    if strict_mode:
                        reveal_threshold_ms = max(55.0, min(130.0, frame_ms * 1.5))
                    else:
                        reveal_threshold_ms = max(35.0, min(120.0, frame_ms * 1.25))
                if backend_pos_ms >= (self._vlc_reveal_start_position_ms + reveal_threshold_ms):
                    position_ready = True

        signal_ready = bool(reached_min_delay and state_ready and position_ready)
        if signal_ready:
            self._vlc_reveal_ready_hits += 1
        else:
            self._vlc_reveal_ready_hits = 0

        stable_hits_needed = 1
        ready = (signal_ready and self._vlc_reveal_ready_hits >= stable_hits_needed) or force_ready

        if ready:
            # Keep the preview pixmap visible under the native VLC surface.
            # Hiding it right at handoff can expose a single white-frame blink
            # while VLC's first composed frame lands.
            self._set_vlc_visible(True)
            self.sync_external_surface_geometry()
            QTimer.singleShot(60, self.sync_external_surface_geometry)
            if self._vlc_cover_active:
                QTimer.singleShot(40, self._hide_vlc_cover_overlay)
            self._cancel_vlc_reveal()
            # VLC is now past loop_start — allow next loop cycle to fire.
            self._vlc_loop_end_guard = False

    def _begin_mpv_reveal(self, delay_ms: int = 120):
        """Reveal mpv surface once MPV has painted the first frame of the new file.

        Connects a one-shot slot to MpvGlWidget.frame_painted so the pixmap
        cover is only removed after the GL buffer actually contains the new
        video's first frame — eliminating the flash of the previous video's
        last frame that occurred when revealing immediately.
        """
        self._mpv_pending_reveal = False
        self._mpv_reveal_deadline_monotonic = 0.0
        self._mpv_reveal_timer.stop()

        gl_widget = getattr(self, 'mpv_widget', None)
        if gl_widget is None or not isinstance(gl_widget, MpvGlWidget):
            # No GL widget — reveal immediately (fallback).
            self._set_mpv_visible(True)
            return

        # Arm the one-shot signal and connect a lambda that reveals once fired.
        gl_widget._emit_frame_painted = True

        def _on_first_frame():
            try:
                gl_widget.frame_painted.disconnect(_on_first_frame)
            except Exception:
                pass
            self._set_mpv_visible(True)

        gl_widget.frame_painted.connect(_on_first_frame)

        # Safety net: if the frame never arrives (e.g. video stays paused),
        # reveal after a short timeout so the UI doesn't stay blank forever.
        def _reveal_timeout():
            if not gl_widget._emit_frame_painted:
                return  # already revealed via frame_painted
            gl_widget._emit_frame_painted = False
            try:
                gl_widget.frame_painted.disconnect(_on_first_frame)
            except Exception:
                pass
            self._set_mpv_visible(True)

        QTimer.singleShot(300, _reveal_timeout)

    def _try_reveal_mpv_surface(self):
        if not self._mpv_pending_reveal:
            self._mpv_reveal_timer.stop()
            return
        if self.mpv_player is None:
            self._cancel_mpv_reveal()
            return

        # Avoid mpv property polling from GUI timer callbacks; it can crash on Windows.
        ready = time.monotonic() >= self._mpv_reveal_deadline_monotonic

        if ready:
            self._set_mpv_visible(True)
            self._cancel_mpv_reveal()

    def _update_mpv_geometry_from_pixmap(self):
        """Keep mpv_widget covering the full host viewport (called by geometry timer)."""
        self._sync_mpv_widget_to_viewport()

    def _teardown_mpv(self, drop_player: bool = False):
        """Release mpv runtime resources if initialized."""
        self._cancel_mpv_reveal()
        self.mpv_geometry_timer.stop()
        self._mpv_estimated_position_ms = 0.0
        self._mpv_play_started_monotonic = 0.0
        self._mpv_play_base_position_ms = 0.0
        self._active_forward_backend = PLAYBACK_BACKEND_QT_HYBRID
        self._mpv_needs_reload = True
        self._mpv_ready_for_seeks = False
        self._mpv_vo_ready = False
        self._mpv_pending_play_speed = None
        player = self.mpv_player
        if drop_player:
            if player is not None:
                # With vo=libmpv (render API) there is no D3D11 swap chain or render
                # thread to quiesce — cleanup the GL render context first, then
                # terminate() is safe to call synchronously from Qt main thread.
                gl_widget = self.mpv_widget
                if gl_widget is not None and isinstance(gl_widget, MpvGlWidget):
                    try:
                        gl_widget.makeCurrent()
                        gl_widget.cleanup()
                        gl_widget.doneCurrent()
                    except Exception:
                        try:
                            gl_widget.cleanup()
                        except Exception:
                            pass
                try:
                    player.terminate()
                except Exception:
                    pass
            self.mpv_player = None

        if self.mpv_widget is not None:
            widget = self.mpv_widget
            self.mpv_widget = None
            try:
                import shiboken6
                if shiboken6.isValid(widget):
                    widget.hide()
                    widget.deleteLater()
            except Exception:
                pass

        self.mpv_host_view = None

    def _setup_mpv_for_current_video(self) -> bool:
        """Initialize mpv renderer bound to a scene widget surface."""
        if mpv is None or not self._is_using_mpv_backend():
            return False
        _, scene = self._get_live_pixmap_scene()
        if scene is None or not self.video_path:
            return False

        try:
            target_view = self._resolve_mpv_target_view()
            if target_view is None:
                return False

            if self.mpv_widget is None:
                self.mpv_host_view = target_view
                # Create in parking widget — _set_mpv_visible(False) called
                # below will keep it hidden there until first frame is ready.
                self.mpv_widget = MpvGlWidget(self.mpv_host_view.viewport())
                self.mpv_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                self.mpv_widget.setStyleSheet('background: transparent;')
                self.mpv_widget.setAutoFillBackground(False)
                self.mpv_widget.setGeometry(0, 0, 1, 1)
                self.mpv_widget.lower()
                self.mpv_widget.show()
            else:
                self.mpv_host_view = target_view

            self._set_mpv_visible(False)

            import threading
            if VideoPlayerWidget._mpv_init_lock is None:
                VideoPlayerWidget._mpv_init_lock = threading.Lock()

            speed = max(0.1, float(self.playback_speed))
            muted = bool(self.audio_output.isMuted()) if self.audio_output else True

            if self.mpv_player is not None:
                # Reuse existing MPV instance via loadfile replace.
                # With vo=libmpv (render API) there is no D3D11 swap chain,
                # so loadfile replace is completely safe — no crash risk.
                try:
                    self.mpv_player.command('set', 'pause', 'yes')
                except Exception:
                    pass
                try:
                    self.mpv_player.command('set', 'speed', str(speed))
                except Exception:
                    pass
                try:
                    self.mpv_player.command('set', 'mute', 'yes' if muted else 'no')
                except Exception:
                    pass
                self._mpv_ready_for_seeks = False
                self._mpv_vo_ready = False
                self._mpv_load_generation += 1
                if self._mpv_event_gen_box is not None:
                    self._mpv_event_gen_box[0] = self._mpv_load_generation
                self._mpv_string_command('loadfile', str(self.video_path), 'replace')
                self._mpv_needs_reload = False
                return True

            # First video — create MPV instance with render API (vo=libmpv).
            self._mpv_instance_generation += 1
            self._mpv_load_generation += 1
            with VideoPlayerWidget._mpv_init_lock:
                self.mpv_player = mpv.MPV(
                    vo='libmpv',
                    hwdec='auto-copy',  # copy decoded frames to OpenGL — no zero-copy D3D11
                    keep_open='yes',
                    pause=True,
                    speed=str(speed),
                    mute='yes' if muted else 'no',
                    input_default_bindings=False,
                    input_vo_keyboard=False,
                    # Disable all built-in scripts. The custom mpv build already has
                    # Lua/JavaScript compiled out (-Dlua=disabled), but load_scripts=False
                    # ensures no external scripts are loaded either.
                    load_scripts=False,
                )

            # Create the OpenGL render context — must be done with GL context current.
            # makeCurrent() activates the QOpenGLWidget's GL context on this thread.
            gl_widget = self.mpv_widget  # type: MpvGlWidget
            gl_widget.makeCurrent()
            try:
                def _get_proc_addr(_, name):
                    ctx = QOpenGLContext.currentContext()
                    if ctx is None:
                        return 0
                    return int(ctx.getProcAddress(name) or 0)

                proc_fn = mpv.MpvGlGetProcAddressFn(_get_proc_addr)
                gl_widget._proc_address_fn = proc_fn  # keep alive

                render_ctx = mpv.MpvRenderContext(
                    self.mpv_player,
                    'opengl',
                    opengl_init_params={'get_proc_address': proc_fn},
                )
                gl_widget.set_render_context(render_ctx)
            finally:
                gl_widget.doneCurrent()

            # Wire file-loaded event — use invokeMethod (never Signal.emit from MPV thread)
            _self_ref = weakref.ref(self)
            _gen_box = [self._mpv_load_generation]
            self._mpv_event_gen_box = _gen_box
            @self.mpv_player.event_callback('file-loaded')
            def _on_file_loaded_event(event, _ref=_self_ref, _b=_gen_box):
                try:
                    obj = _ref()
                    if obj is not None:
                        QMetaObject.invokeMethod(
                            obj,
                            '_on_mpv_file_loaded',
                            Qt.ConnectionType.QueuedConnection,
                            Q_ARG(int, _b[0]),
                        )
                except Exception:
                    pass

            self._mpv_ready_for_seeks = False
            self._mpv_vo_ready = False
            self._mpv_string_command('loadfile', str(self.video_path), 'replace')
            self._mpv_needs_reload = False
            return True
        except Exception as e:
            print(f"[VIDEO] Failed to initialize mpv backend: {e}")
            self._teardown_mpv(drop_player=True)
            self.runtime_playback_backend = PLAYBACK_BACKEND_QT_HYBRID
            return False

    def _get_mpv_position_ms(self) -> float | None:
        if not self._is_mpv_forward_active() or not self.is_playing:
            return float(self._mpv_estimated_position_ms)

        speed = max(0.1, float(self.playback_speed))
        elapsed = max(0.0, time.monotonic() - self._mpv_play_started_monotonic)
        estimated = self._mpv_play_base_position_ms + (elapsed * 1000.0 * speed)

        loop_bounds_ms = self._get_segment_loop_bounds_ms()
        if loop_bounds_ms is not None:
            loop_start_ms, loop_end_ms = loop_bounds_ms
            loop_span_ms = max(1.0, loop_end_ms - loop_start_ms)
            estimated = ((estimated - loop_start_ms) % loop_span_ms) + loop_start_ms
        elif self.duration_ms > 0:
            estimated = max(0.0, min(float(self.duration_ms), estimated))
        self._mpv_estimated_position_ms = float(estimated)
        return float(self._mpv_estimated_position_ms)

    def _seek_mpv_position_ms(self, position_ms: float):
        self._mpv_estimated_position_ms = float(position_ms)
        if self.is_playing and self._is_mpv_forward_active():
            self._mpv_play_base_position_ms = float(position_ms)
            self._mpv_play_started_monotonic = time.monotonic()
        if self.mpv_player is None:
            return
        # Pause MPV immediately on first seek of a scrub gesture to prevent
        # audio/video drift during rapid scrubbing.
        if not self._mpv_seek_timer.isActive() and self.is_playing and self._is_mpv_forward_active():
            self._mpv_seek_was_playing = True
            self._mpv_string_command('set', 'pause', 'yes')
        # Coalesce rapid scrub seeks — send only the last position after 50ms idle.
        self._mpv_seek_pending_ms = float(position_ms)
        self._mpv_seek_timer.start()

    def _flush_mpv_seek(self):
        """Send the coalesced seek to MPV and resume if it was playing."""
        if self.mpv_player is None or self._mpv_seek_pending_ms is None:
            return
        if not self._mpv_ready_for_seeks or not self._mpv_vo_ready:
            self._mpv_seek_timer.start()
            return
        seek_s = self._mpv_seek_pending_ms / 1000.0
        self._mpv_seek_pending_ms = None
        self._mpv_string_command('seek', f'{seek_s:.6f}', 'absolute+exact')
        if self._mpv_seek_was_playing and self.is_playing:
            self._mpv_string_command('set', 'pause', 'no')
        self._mpv_seek_was_playing = False

    def _mpv_string_command(self, name: str, *args):
        if self.mpv_player is None:
            return
        call_args = [str(arg) for arg in args if arg is not None]
        try:
            self.mpv_player.command(str(name), *call_args)
        except Exception:
            pass

    def _mpv_set_property(self, prop_name: str, value):
        if self.mpv_player is None:
            return
        if isinstance(value, bool):
            encoded = 'yes' if value else 'no'
        else:
            encoded = str(value)
        self._mpv_string_command('set', str(prop_name), encoded)

    def _load_qt_media_source_for_current_video(self) -> bool:
        video_item = self._get_live_video_item()
        if not self.video_path or video_item is None:
            return False
        current_path = str(self.video_path)
        if self._qt_video_source_path == current_path:
            return True

        import sys
        stdout_fd = sys.stdout.fileno()
        stderr_fd = sys.stderr.fileno()
        with open(os.devnull, 'w') as devnull:
            old_stdout = os.dup(stdout_fd)
            old_stderr = os.dup(stderr_fd)
            os.dup2(devnull.fileno(), stdout_fd)
            os.dup2(devnull.fileno(), stderr_fd)
            try:
                try:
                    self.media_player.setSource(QUrl.fromLocalFile(current_path))
                    self.media_player.setVideoOutput(video_item)
                except RuntimeError:
                    self.video_item = None
                    self._qt_video_source_path = None
                    return False
            finally:
                os.dup2(old_stdout, stdout_fd)
                os.dup2(old_stderr, stderr_fd)
                os.close(old_stdout)
                os.close(old_stderr)
        self._qt_video_source_path = current_path
        return True

    def sync_external_surface_geometry(self):
        """Force one immediate sync for external native video surfaces."""
        self._update_mpv_geometry_from_pixmap()
        self._update_vlc_geometry_from_pixmap()
        self._update_vlc_cover_geometry_from_pixmap()
        self._update_opencv_cover_geometry()

    def _open_capture_silently(self, video_path: Path):
        """Open OpenCV capture while suppressing ffmpeg chatter."""
        import sys
        stdout_fd = sys.stdout.fileno()
        stderr_fd = sys.stderr.fileno()
        with open(os.devnull, 'w') as devnull:
            old_stdout = os.dup(stdout_fd)
            old_stderr = os.dup(stderr_fd)
            os.dup2(devnull.fileno(), stdout_fd)
            os.dup2(devnull.fileno(), stderr_fd)
            try:
                cap = cv2.VideoCapture(str(video_path), cv2.CAP_FFMPEG)
                cap.set(cv2.CAP_PROP_HW_ACCELERATION, cv2.VIDEO_ACCELERATION_NONE)
            finally:
                os.dup2(old_stdout, stdout_fd)
                os.dup2(old_stderr, stderr_fd)
                os.close(old_stdout)
                os.close(old_stderr)
        return cap

    def _apply_metadata_hints(self, video_metadata: dict | None) -> bool:
        """Populate runtime metadata from cached model values when available."""
        fps = 0.0
        frame_count = 0
        duration_ms = 0.0
        if isinstance(video_metadata, dict):
            try:
                fps = float(video_metadata.get('fps') or 0.0)
            except Exception:
                fps = 0.0
            try:
                frame_count = int(video_metadata.get('frame_count') or 0)
            except Exception:
                frame_count = 0
            try:
                duration_s = float(video_metadata.get('duration') or 0.0)
                if duration_s > 0:
                    duration_ms = duration_s * 1000.0
            except Exception:
                duration_ms = 0.0
        if fps > 0:
            self.fps = float(fps)
        if frame_count > 0:
            self.total_frames = int(frame_count)
        if duration_ms > 0:
            self.duration_ms = float(duration_ms)
        elif self.total_frames > 0 and self.fps > 0:
            self.duration_ms = (self.total_frames / self.fps) * 1000.0
        return bool(self.total_frames > 0 and self.fps > 0)

    def _set_initial_preview_pixmap(
        self,
        preview_qimage: QImage | None,
        video_dimensions: tuple[int, int] | None = None,
    ) -> bool:
        """Show a fast preview frame without opening OpenCV synchronously."""
        if self.pixmap_item is None:
            return False
        if preview_qimage is None or preview_qimage.isNull():
            return False
        try:
            pixmap = QPixmap.fromImage(preview_qimage.copy())
            if pixmap.isNull():
                return False
            if (
                isinstance(video_dimensions, tuple)
                and len(video_dimensions) == 2
                and int(video_dimensions[0]) > 0
                and int(video_dimensions[1]) > 0
            ):
                target_w = int(video_dimensions[0])
                target_h = int(video_dimensions[1])
                scaled = pixmap.scaled(
                    target_w,
                    target_h,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                if not scaled.isNull():
                    pixmap = scaled
            self.pixmap_item.setPixmap(pixmap)
            if self.video_item:
                self.video_item.setSize(pixmap.size())
            self._update_mpv_geometry_from_pixmap()
            self._update_vlc_geometry_from_pixmap()
            return True
        except Exception:
            return False

    def _ensure_cap_ready(self) -> bool:
        """Lazy-open OpenCV capture only when frame-accurate operations need it."""
        if self.cap is not None:
            try:
                if self.cap.isOpened():
                    return True
            except Exception:
                pass
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        if not self.video_path:
            return False
        cap = self._open_capture_silently(self.video_path)
        if cap is None or not cap.isOpened():
            try:
                if cap is not None:
                    cap.release()
            except Exception:
                pass
            return False
        self.cap = cap
        try:
            fps = float(self.cap.get(cv2.CAP_PROP_FPS) or 0.0)
        except Exception:
            fps = 0.0
        try:
            frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        except Exception:
            frame_count = 0
        if self.fps <= 0 and fps > 0:
            self.fps = fps
        if self.total_frames <= 0 and frame_count > 0:
            self.total_frames = frame_count
        if self.duration_ms <= 0 and self.total_frames > 0 and self.fps > 0:
            self.duration_ms = (self.total_frames / self.fps) * 1000.0
        return True

    def load_video(
        self,
        video_path: Path,
        pixmap_item: QGraphicsPixmapItem,
        video_metadata: dict | None = None,
        preview_qimage: QImage | None = None,
        video_dimensions: tuple[int, int] | None = None,
    ):
        """Load a video file."""
        self._refresh_backend_selection()

        # Stop any previous playback quickly (avoid expensive frame extraction).
        self.suspend_for_media_switch()

        # Reset corruption detection state
        self.consecutive_frame_failures = 0
        self.corruption_warning_shown = False

        # Release old OpenCV capture
        if self.cap:
            self.cap.release()
            self.cap = None

        self.video_path = video_path
        self.pixmap_item = pixmap_item
        self._active_forward_backend = PLAYBACK_BACKEND_QT_HYBRID
        self._mpv_needs_reload = True
        self._mpv_pending_play_speed = None  # cancel any deferred play from previous clip
        self._vlc_needs_reload = True
        self._qt_video_source_path = None
        # Pause MPV before switching to a new clip.
        if self.mpv_player is not None:
            try:
                self._mpv_set_property('pause', True)
            except Exception:
                pass
        self._cancel_mpv_reveal()
        self._cancel_vlc_reveal()
        self._set_mpv_visible(False)
        self._set_vlc_visible(False)
        if self.vlc_player is not None or self.vlc_widget is not None:
            try:
                if self._is_using_vlc_backend():
                    # Reuse VLC runtime between clips to reduce startup latency.
                    if self.vlc_player is not None:
                        try:
                            self.vlc_player.stop()
                        except Exception:
                            pass
                    self._vlc_end_reached_flag = False
                    self._vlc_last_progress_ms = None
                    self._vlc_stall_ticks = 0
                    self._vlc_soft_restart_pending = False
                    self._vlc_soft_restart_deadline_monotonic = 0.0
                else:
                    self._teardown_vlc(drop_player=True)
            except Exception:
                pass

        # Prefer cached metadata for instant clip-switch startup.
        self.fps = 0.0
        self.total_frames = 0
        self.duration_ms = 0.0
        metadata_ready = self._apply_metadata_hints(video_metadata)

        # If metadata is missing, fall back to immediate OpenCV probe.
        if not metadata_ready:
            if not self._ensure_cap_ready():
                print(f"Failed to open video: {video_path}")
                return False
            self._apply_metadata_hints(
                {
                    'fps': self.fps,
                    'frame_count': self.total_frames,
                    'duration': (self.duration_ms / 1000.0) if self.duration_ms > 0 else 0.0,
                }
            )

        self.current_frame = 0
        self._mpv_estimated_position_ms = 0.0
        self._mpv_play_started_monotonic = 0.0
        self._mpv_play_base_position_ms = 0.0
        self._vlc_estimated_position_ms = 0.0
        self._vlc_play_started_monotonic = 0.0
        self._vlc_play_base_position_ms = 0.0

        # Create QGraphicsVideoItem for QMediaPlayer output
        # Properly cleanup old video item
        if self.video_item:
            try:
                scene = self.video_item.scene()
                if scene:
                    scene.removeItem(self.video_item)
            except RuntimeError:
                pass  # C++ object already deleted
            self.video_item = None

        self.video_item = QGraphicsVideoItem()
        self.video_item.setZValue(0)

        # Add to same scene as pixmap_item
        try:
            scene = pixmap_item.scene()
        except RuntimeError:
            scene = None
        if scene is not None:
            scene.addItem(self.video_item)

        # For external backends, avoid touching QMediaPlayer during list-click load path.
        # Lazily load Qt source only if/when Qt playback path is used.
        if (not self._is_using_mpv_backend()) and (not self._is_using_vlc_backend()):
            if not self._load_qt_media_source_for_current_video():
                return False

        # Show initial preview without blocking on OpenCV unless necessary.
        preview_ready = self._set_initial_preview_pixmap(
            preview_qimage=preview_qimage,
            video_dimensions=video_dimensions,
        )
        if not preview_ready:
            if self._ensure_cap_ready():
                self._show_opencv_frame(0)
            else:
                print(f"Failed to initialize preview frame: {video_path}")
                return False

        # Do not initialize mpv on load; initialize lazily on first play().
        # This avoids startup/list-click crashes while browsing videos.
        self._cancel_mpv_reveal()
        self._set_mpv_visible(False)

        # Set video item size to match first frame
        if self.pixmap_item and self.pixmap_item.pixmap():
            video_size = self.pixmap_item.pixmap().size()
            self.video_item.setSize(video_size)
            self._update_mpv_geometry_from_pixmap()
            self._update_vlc_geometry_from_pixmap()

        # Hide video item initially (show pixmap with first frame)
        self.video_item.hide()
        self._set_mpv_visible(False)
        self._set_vlc_visible(False)
        self.pixmap_item.show()

        return True

    def play(self):
        """Start playback using QMediaPlayer (or OpenCV for negative speeds)."""
        self._refresh_backend_selection()
        reveal_from_still = bool(self._vlc_next_start_from_still)
        self._vlc_next_start_from_still = False
        self._hide_vlc_cover_overlay()

        if not self.video_path or self.is_playing:
            return

        # When loop markers are active, entering playback from outside the loop
        # should jump to loop-in (or loop-out for reverse playback).
        if self.loop_enabled and self.loop_start is not None and self.loop_end is not None:
            start_frame = max(0, min(int(self.loop_start), self.total_frames - 1))
            end_frame = max(0, min(int(self.loop_end), self.total_frames - 1))
            if start_frame > end_frame:
                start_frame, end_frame = end_frame, start_frame

            if self.current_frame < start_frame or self.current_frame > end_frame:
                target_frame = end_frame if self.playback_speed < 0 else start_frame
                self.seek_to_frame(target_frame)

        self.is_playing = True
        self.playback_started.emit()  # Notify that playback started

        if self.playback_speed < 0:
            if not self._ensure_cap_ready():
                self.is_playing = False
                self.playback_paused.emit()
                return
            # Use OpenCV frame-by-frame for backward playback
            self._active_forward_backend = PLAYBACK_BACKEND_QT_HYBRID
            self._cancel_mpv_reveal()
            self._cancel_vlc_reveal()
            try:
                if self.video_item:
                    self.video_item.hide()
            except RuntimeError:
                pass  # C++ object deleted
            self._set_vlc_visible(False)
            # Activate the OpenCV cover overlay — a native QLabel raised above
            # mpv_widget. QOpenGLWidget always composites on top of QGraphicsScene
            # items so we can't use pixmap_item during reverse; the overlay is a
            # native sibling widget that can be raised above mpv_widget.
            # Show a placeholder frame immediately so there's no blank flash.
            self._show_opencv_frame(self.current_frame)
            # Start OpenCV playback timer
            interval_ms = round(1000 / (self.fps * abs(self.playback_speed)))
            self.position_timer.setInterval(interval_ms)
            try:
                self.position_timer.timeout.disconnect()
            except:
                pass  # No connections yet
            self.position_timer.timeout.connect(self._play_next_frame_opencv)
            self.position_timer.start()
        else:
            # Use selected forward backend (mpv/vlc experimental, otherwise QMediaPlayer).
            use_mpv_forward = self._is_using_mpv_backend()
            use_vlc_forward = self._is_using_vlc_backend()

            if use_mpv_forward:
                if self.mpv_player is None or self._mpv_needs_reload:
                    if not self._setup_mpv_for_current_video():
                        self.runtime_playback_backend = PLAYBACK_BACKEND_QT_HYBRID
                        use_mpv_forward = False
                    else:
                        # Sync freshly initialized mpv decoder to current frame.
                        start_ms = (self.current_frame / self.fps * 1000.0) if self.fps > 0 else 0.0
                        self._seek_mpv_position_ms(start_ms)
                        self._mpv_estimated_position_ms = float(start_ms)
                        self._mpv_play_base_position_ms = float(start_ms)
                        self._mpv_play_started_monotonic = time.monotonic()
                if use_mpv_forward and self.mpv_player is not None:
                    if self._is_segment_loop_active() and self._mpv_vo_ready:
                        self._apply_mpv_loop_settings()
            elif use_vlc_forward:
                if self.vlc_player is None or self._vlc_needs_reload:
                    if not self._setup_vlc_for_current_video():
                        self.runtime_playback_backend = PLAYBACK_BACKEND_QT_HYBRID
                        use_vlc_forward = False
                    else:
                        start_ms = (self.current_frame / self.fps * 1000.0) if self.fps > 0 else 0.0
                        self._seek_vlc_position_ms(start_ms)
                        self._vlc_estimated_position_ms = float(start_ms)
                        self._vlc_play_base_position_ms = float(start_ms)
                        self._vlc_play_started_monotonic = time.monotonic()
                        self._vlc_end_reached_flag = False
                        self._vlc_last_progress_ms = float(start_ms)
                        self._vlc_stall_ticks = 0

            if use_mpv_forward and self.mpv_player is not None:
                try:
                    if self.video_item:
                        self.video_item.hide()
                except RuntimeError:
                    pass  # C++ object deleted
                try:
                    self._cancel_vlc_reveal()
                    self._active_forward_backend = PLAYBACK_BACKEND_MPV_EXPERIMENTAL
                    speed = max(0.1, float(self.playback_speed))
                    if self._mpv_ready_for_seeks and self._mpv_vo_ready:
                        # File is already loaded and VO is stable — safe to play immediately.
                        # Seek to estimated position first so MPV resumes from the right spot
                        # (e.g. after OpenCV reverse playback moved current_frame).
                        seek_sec = self._mpv_estimated_position_ms / 1000.0
                        self._mpv_string_command('seek', str(seek_sec), 'absolute+exact')
                        self._mpv_string_command('set', 'speed', str(speed))
                        self._mpv_string_command('set', 'pause', 'no')
                        self._mpv_play_base_position_ms = float(self._mpv_estimated_position_ms)
                        self._mpv_play_started_monotonic = time.monotonic()
                        # Hide opencv cover overlay — MPV is taking over display.
                        self._hide_opencv_cover_overlay()
                        self._begin_mpv_reveal(delay_ms=120)
                    else:
                        # loadfile was just issued; wait for file-loaded event before unpausing.
                        # _on_mpv_file_loaded will call _begin_mpv_reveal when ready.
                        self._mpv_pending_play_speed = speed
                        self._mpv_play_base_position_ms = float(self._mpv_estimated_position_ms)
                        self._mpv_play_started_monotonic = time.monotonic()
                except Exception as e:
                    print(f"[VIDEO] mpv play fallback to Qt backend: {e}")
                    self.runtime_playback_backend = PLAYBACK_BACKEND_QT_HYBRID
                    self._active_forward_backend = PLAYBACK_BACKEND_QT_HYBRID
                    self._cancel_mpv_reveal()
                    self._set_mpv_visible(False)
                    self._set_vlc_visible(False)
                    if not self._load_qt_media_source_for_current_video():
                        self.is_playing = False
                        self.playback_paused.emit()
                        return
                    try:
                        if self.video_item:
                            self.video_item.show()
                    except RuntimeError:
                        pass
                    try:
                        if self.pixmap_item:
                            self.pixmap_item.hide()
                    except RuntimeError:
                        pass
                    self.media_player.setPlaybackRate(self.playback_speed)
                    self.media_player.play()
            elif use_vlc_forward and self.vlc_player is not None:
                try:
                    if self.video_item:
                        self.video_item.hide()
                except RuntimeError:
                    pass  # C++ object deleted
                try:
                    self._cancel_vlc_reveal()
                    self._active_forward_backend = PLAYBACK_BACKEND_VLC_EXPERIMENTAL
                    self._set_vlc_rate(self.playback_speed)
                    self._set_vlc_muted(bool(self.audio_output.isMuted()) if self.audio_output else True)
                    self._vlc_end_reached_flag = False
                    self._vlc_stall_ticks = 0
                    # hide VLC surface first so pausing VLC can't flash black
                    self._set_vlc_visible(False)
                    try:
                        if self.pixmap_item:
                            self.pixmap_item.show()
                    except RuntimeError:
                        pass
                    self.vlc_player.play()
                    self._seek_vlc_position_ms(self._vlc_estimated_position_ms)
                    self._vlc_play_base_position_ms = float(self._vlc_estimated_position_ms)
                    self._vlc_play_started_monotonic = time.monotonic()
                    # hold_play: keep VLC paused at frame 0 during the reveal delay so
                    # no frames are skipped before the surface becomes visible.
                    if reveal_from_still:
                        self._set_vlc_paused(True)
                    self._cancel_mpv_reveal()
                    self._set_mpv_visible(False)
                    if reveal_from_still:
                        self._show_vlc_cover_overlay()
                    self._begin_vlc_reveal(
                        delay_ms=85 if reveal_from_still else 120,
                        force_ms=1200 if reveal_from_still else 1400,
                        require_stable=False,
                        hold_play=reveal_from_still,
                    )
                    self._schedule_vlc_loop_end_wall_timer(float(self._vlc_estimated_position_ms))
                except Exception as e:
                    print(f"[VIDEO] vlc play fallback to Qt backend: {e}")
                    self.runtime_playback_backend = PLAYBACK_BACKEND_QT_HYBRID
                    self._active_forward_backend = PLAYBACK_BACKEND_QT_HYBRID
                    self._cancel_vlc_reveal()
                    self._set_mpv_visible(False)
                    self._set_vlc_visible(False)
                    self._hide_vlc_cover_overlay()
                    if not self._load_qt_media_source_for_current_video():
                        self.is_playing = False
                        self.playback_paused.emit()
                        return
                    try:
                        if self.video_item:
                            self.video_item.show()
                    except RuntimeError:
                        pass
                    try:
                        if self.pixmap_item:
                            self.pixmap_item.hide()
                    except RuntimeError:
                        pass
                    self.media_player.setPlaybackRate(self.playback_speed)
                    self.media_player.play()
            else:
                self._active_forward_backend = PLAYBACK_BACKEND_QT_HYBRID
                self._cancel_mpv_reveal()
                self._cancel_vlc_reveal()
                self._hide_vlc_cover_overlay()
                if not self._load_qt_media_source_for_current_video():
                    self.is_playing = False
                    self.playback_paused.emit()
                    return
                try:
                    if self.pixmap_item:
                        self.pixmap_item.hide()
                except RuntimeError:
                    pass  # C++ object deleted
                try:
                    if self.video_item:
                        self.video_item.show()
                except RuntimeError:
                    pass  # C++ object deleted
                self._set_mpv_visible(False)
                self._set_vlc_visible(False)

                # Set playback rate
                self.media_player.setPlaybackRate(self.playback_speed)

                # Start playback
                self.media_player.play()

            # Start position tracking timer
            self.position_timer.setInterval(16)  # ~60 FPS
            try:
                self.position_timer.timeout.disconnect()
            except Exception:
                pass  # No connections yet
            self.position_timer.timeout.connect(self._update_frame_from_position)
            self.position_timer.start()

    def pause(self):
        """Pause playback and show exact frame with OpenCV."""
        was_playing = self.is_playing
        self.is_playing = False
        self._cancel_mpv_reveal()
        self._cancel_vlc_reveal()
        self._hide_vlc_cover_overlay()
        self.position_timer.stop()
        self.media_player.pause()
        if self.mpv_player is not None:
            current_estimated_ms = self._get_mpv_position_ms()
            if current_estimated_ms is not None:
                self._mpv_estimated_position_ms = float(current_estimated_ms)
            try:
                self._mpv_set_property('pause', True)
            except Exception:
                pass
        if self.vlc_player is not None:
            current_estimated_ms = self._get_vlc_position_ms()
            if current_estimated_ms is not None:
                self._vlc_estimated_position_ms = float(current_estimated_ms)
                self._vlc_last_progress_ms = float(current_estimated_ms)
            self._vlc_stall_ticks = 0
            self._vlc_soft_restart_pending = False
            self._vlc_soft_restart_deadline_monotonic = 0.0
            try:
                self._set_vlc_paused(True)
            except Exception:
                pass

        if was_playing:
            self.playback_paused.emit()  # Notify that playback paused

        if self._is_mpv_forward_active():
            # MPV was playing forward — just keep widget visible, already paused.
            try:
                if self.video_item:
                    self.video_item.hide()
            except RuntimeError:
                pass
            try:
                if self.pixmap_item:
                    self.pixmap_item.hide()
            except RuntimeError:
                pass
            self._set_mpv_visible(True)
            self._set_vlc_visible(False)
            return

        # If MPV backend is selected and initialized, use it for frame-accurate
        # pause display via exact seek — no OpenCV needed, better format support.
        # Skip if the opencv cover overlay is active — means we just came from
        # reverse playback; keep the overlay showing the last OpenCV frame.
        _opencv_active = False
        try:
            _opencv_active = bool(self._opencv_cover_label and self._opencv_cover_label.isVisible())
        except RuntimeError:
            pass
        if self._is_using_mpv_backend() and self.mpv_player is not None \
                and self._mpv_ready_for_seeks and not _opencv_active:
            seek_ms = (self.current_frame / self.fps * 1000.0) if self.fps > 0 else self._mpv_estimated_position_ms
            try:
                self._mpv_string_command('seek', f'{seek_ms / 1000.0:.6f}', 'absolute+exact')
            except Exception:
                pass
            try:
                if self.video_item:
                    self.video_item.hide()
            except RuntimeError:
                pass
            try:
                if self.pixmap_item:
                    self.pixmap_item.hide()
            except RuntimeError:
                pass
            self._set_mpv_visible(True)
            self._set_vlc_visible(False)
            return

        # Fallback: OpenCV frame display (reverse playback, or MPV not ready).
        try:
            if self.video_item:
                self.video_item.hide()
        except RuntimeError:
            pass
        self._set_mpv_visible(False)
        self._set_vlc_visible(False)

        try:
            if self.pixmap_item:
                self.pixmap_item.show()
        except RuntimeError:
            pass

        self._show_opencv_frame(self.current_frame)

    def stop(self):
        """Stop playback and reset to first frame."""
        self.pause()
        self.media_player.stop()
        if self.mpv_player is not None:
            try:
                self._mpv_set_property('pause', True)
                self._seek_mpv_position_ms(0.0)
            except Exception:
                pass
        if self.vlc_player is not None:
            try:
                self._set_vlc_paused(True)
                self._seek_vlc_position_ms(0.0)
                self.vlc_player.stop()
                self._vlc_end_reached_flag = False
                self._vlc_last_progress_ms = 0.0
                self._vlc_stall_ticks = 0
                self._vlc_soft_restart_pending = False
                self._vlc_soft_restart_deadline_monotonic = 0.0
            except Exception:
                pass
        self.seek_to_frame(0)
        self._active_forward_backend = PLAYBACK_BACKEND_QT_HYBRID

    def suspend_for_media_switch(self):
        """Low-latency suspend when switching from video to still image.

        This intentionally avoids OpenCV frame rendering/reset work so UI can
        show the target image immediately.
        """
        was_playing = self.is_playing
        self.is_playing = False

        self._cancel_mpv_reveal()
        self._cancel_vlc_reveal()
        self._hide_vlc_cover_overlay()
        self._hide_opencv_cover_overlay()
        self.position_timer.stop()

        # Pause forward backends quickly (no reset/seek work here).
        try:
            self.media_player.pause()
        except Exception:
            pass
        if self.mpv_player is not None:
            try:
                self._mpv_set_property('pause', True)
            except Exception:
                pass
        if self.vlc_player is not None:
            try:
                self._set_vlc_paused(True)
            except Exception:
                pass
            self._vlc_stall_ticks = 0
            self._vlc_soft_restart_pending = False
            self._vlc_soft_restart_deadline_monotonic = 0.0

        # Hide all video surfaces immediately.
        try:
            if self.video_item:
                self.video_item.hide()
        except RuntimeError:
            pass
        self._set_mpv_visible(False)
        self._set_vlc_visible(False)

        # Keep the internal state in a neutral backend mode.
        self._active_forward_backend = PLAYBACK_BACKEND_QT_HYBRID

        if was_playing:
            self.playback_paused.emit()

    def toggle_play_pause(self):
        """Toggle between play and pause."""
        if self.is_playing:
            self.pause()
        else:
            self.play()

    def seek_to_frame(self, frame_number: int):
        """Seek to a specific frame (frame-accurate using OpenCV)."""
        if self.total_frames <= 0 or self.fps <= 0:
            self._ensure_cap_ready()
        if self.total_frames <= 0:
            return

        frame_number = max(0, min(frame_number, self.total_frames - 1))
        self.current_frame = frame_number

        # Calculate position in milliseconds
        if self.fps > 0:
            position_ms = (frame_number / self.fps * 1000)
        elif self.total_frames > 1 and self.duration_ms > 0:
            position_ms = (frame_number / (self.total_frames - 1)) * self.duration_ms
        else:
            position_ms = 0.0
        self._mpv_estimated_position_ms = float(position_ms)
        if self.is_playing and self._is_mpv_forward_active():
            self._mpv_play_base_position_ms = float(position_ms)
            self._mpv_play_started_monotonic = time.monotonic()

        # Seek QMediaPlayer
        if self._qt_video_source_path is not None:
            self.media_player.setPosition(int(position_ms))
        if self.mpv_player is not None and self._active_forward_backend == PLAYBACK_BACKEND_MPV_EXPERIMENTAL:
            self._seek_mpv_position_ms(position_ms)
        if self.vlc_player is not None and self._active_forward_backend == PLAYBACK_BACKEND_VLC_EXPERIMENTAL:
            self._seek_vlc_position_ms(position_ms)

        # If paused, show exact frame via MPV seek (or OpenCV fallback).
        if not self.is_playing:
            if self._is_using_mpv_backend() and self.mpv_player is not None and self._mpv_ready_for_seeks:
                # Route through the coalescing seek timer — rapid scrub events
                # are collapsed to one seek per 50ms, always absolute+exact.
                self._seek_mpv_position_ms(position_ms)
                try:
                    if self.video_item:
                        self.video_item.hide()
                except RuntimeError:
                    pass
                try:
                    if self.pixmap_item:
                        self.pixmap_item.hide()
                except RuntimeError:
                    pass
                self._set_mpv_visible(True)
            else:
                self._show_opencv_frame(frame_number)

        # Emit frame changed signal
        self.frame_changed.emit(frame_number, position_ms)

    def _show_opencv_frame(self, frame_number: int):
        """Extract and display exact frame using OpenCV."""
        item = self._get_live_pixmap_item()
        if item is None:
            return
        if not self._ensure_cap_ready() or not self.cap:
            return

        if self.total_frames > 0:
            frame_number = max(0, min(frame_number, self.total_frames - 1))
        else:
            frame_number = max(0, int(frame_number))

        # Seek to frame
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)

        # Read frame
        ret, frame = self.cap.read()
        if not ret:
            print(f"Failed to read frame {frame_number}")
            self.consecutive_frame_failures += 1

            # Show warning if multiple consecutive failures detected
            if self.consecutive_frame_failures >= 3 and not self.corruption_warning_shown:
                self.corruption_warning_shown = True
                self.pause()  # Stop playback

                backup_path = Path(str(self.video_path) + '.backup')
                backup_msg = f"\n\nA backup file exists at:\n{backup_path}" if backup_path.exists() else ""

                QMessageBox.warning(
                    None,
                    "Video Corruption Detected",
                    f"Failed to read multiple frames from:\n{self.video_path.name}\n\n"
                    f"The video file appears to be corrupted or damaged. "
                    f"Playback has been paused.{backup_msg}"
                )
            return

        # Reset failure counter on successful read
        self.consecutive_frame_failures = 0

        # Convert BGR to RGB
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Apply SAR correction if needed
        sar_num = self.cap.get(cv2.CAP_PROP_SAR_NUM)
        sar_den = self.cap.get(cv2.CAP_PROP_SAR_DEN)

        if sar_num > 0 and sar_den > 0 and sar_num != sar_den:
            h, w = frame_rgb.shape[:2]
            display_width = int(w * sar_num / sar_den)
            frame_rgb = cv2.resize(frame_rgb, (display_width, h), interpolation=cv2.INTER_LINEAR)

        # Convert to QPixmap — use tobytes() so QImage owns the buffer and
        # the numpy array can be freed without corrupting the image data.
        h, w, ch = frame_rgb.shape
        bytes_per_line = ch * w
        qt_image = QImage(frame_rgb.tobytes(), w, h, bytes_per_line, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qt_image)

        # If MPV widget is actively covering the viewport, it composites on top of
        # QGraphicsScene items (pixmap_item) regardless of Z-order. In that case
        # use a native QLabel overlay raised above mpv_widget instead.
        # Only route to overlay when MPV surface is active — otherwise (paused,
        # stopped, initial load) write to pixmap_item as normal.
        if self.mpv_widget is not None and self._mpv_surface_active:
            self._show_opencv_frame_as_overlay(pixmap)
            return

        # Update pixmap item (no MPV widget present)
        try:
            item.setPixmap(pixmap)

            # Update video item size to match
            if self.video_item:
                self.video_item.setSize(pixmap.size())
            self._update_mpv_geometry_from_pixmap()
            self._update_vlc_geometry_from_pixmap()
        except RuntimeError:
            self.pixmap_item = None
            return

    @Slot(int)
    def _on_position_changed(self, position_ms: int):
        """Handle QMediaPlayer position changes."""
        # This is called during playback
        pass

    @Slot()
    def _play_next_frame_opencv(self):
        """Play next frame using OpenCV (for backward playback or very slow speeds)."""
        if not self.is_playing:
            return

        if self.playback_speed < 0:
            # Backward playback
            start_frame = self.loop_start if (self.loop_enabled and self.loop_start is not None) else 0
            # Wrap destination: loop_end marker, or last frame of video
            wrap_to_frame = self.loop_end if (self.loop_enabled and self.loop_end is not None) else (self.total_frames - 1)

            if self.current_frame <= start_frame:
                if self.loop_enabled:
                    # Loop back to end (marker or last frame)
                    self.current_frame = wrap_to_frame
                    self._show_opencv_frame(self.current_frame)
                else:
                    # Reached start, stop
                    self.pause()
                    return
            else:
                self.current_frame -= 1
                self._show_opencv_frame(self.current_frame)

            # Emit position update
            time_ms = (self.current_frame / self.fps * 1000) if self.fps > 0 else 0
            self.frame_changed.emit(self.current_frame, time_ms)
        else:
            # Forward playback (slow speeds)
            end_frame = self.loop_end if (self.loop_enabled and self.loop_end is not None) else self.total_frames - 1

            if self.current_frame >= end_frame:
                if self.loop_enabled and self.loop_start is not None:
                    # Loop back to start
                    self.current_frame = self.loop_start
                    self._show_opencv_frame(self.current_frame)
                else:
                    # Reached end
                    self.pause()
                    self.playback_finished.emit()
                    return
            else:
                self.current_frame += 1
                self._show_opencv_frame(self.current_frame)

            # Emit position update
            time_ms = (self.current_frame / self.fps * 1000) if self.fps > 0 else 0
            self.frame_changed.emit(self.current_frame, time_ms)

    @Slot()
    def _update_frame_from_position(self):
        """Update current frame number from QMediaPlayer position."""
        if not self.is_playing:
            return

        # Check flag set by VLC position event thread — faster than queued signal.
        if self._vlc_loop_end_flag and self._is_vlc_forward_active():
            self._vlc_loop_end_flag = False
            try:
                pos_now = float(self.vlc_player.get_time()) if self.vlc_player else -1
            except Exception:
                pos_now = -1
            print(f"[LOOP_DBG] FLAG consumed by timer: vlc_time_now={pos_now:.1f}")
            self._on_vlc_loop_end_crossed()
            return

        if self._is_mpv_forward_active():
            position_ms = self._get_mpv_position_ms()
            if position_ms is None:
                return
        elif self._is_vlc_forward_active():
            position_ms = self._get_vlc_position_ms()
            if position_ms is None:
                return
        else:
            position_ms = float(self.media_player.position())

        is_external_backend = self._is_mpv_forward_active() or self._is_vlc_forward_active()
        is_vlc_active = self._is_vlc_forward_active()
        is_full_video_loop = bool(self.loop_enabled and self.loop_start is None and self.loop_end is None)
        effective_duration_ms = float(self.duration_ms or 0.0)
        vlc_state = None
        vlc_position_ratio = None
        vlc_is_playing = None
        if is_vlc_active and self.vlc_player is not None:
            try:
                backend_len_ms = int(self.vlc_player.get_length())
                if backend_len_ms > 0:
                    effective_duration_ms = float(backend_len_ms)
            except Exception:
                pass
            try:
                vlc_state = self.vlc_player.get_state()
            except Exception:
                vlc_state = None
            try:
                ratio_value = float(self.vlc_player.get_position())
                if ratio_value >= 0.0:
                    vlc_position_ratio = max(0.0, min(1.0, ratio_value))
            except Exception:
                vlc_position_ratio = None
            try:
                vlc_is_playing = bool(self.vlc_player.is_playing())
            except Exception:
                vlc_is_playing = None

        now_monotonic = time.monotonic()

        # Calculate current frame from position
        if self.fps > 0:
            frame_number = int((position_ms / 1000.0) * self.fps)
            frame_number = max(0, min(frame_number, self.total_frames - 1))
            frame_ms = 1000.0 / float(self.fps)

            # Only update if frame changed
            if frame_number != self.current_frame:
                self.current_frame = frame_number
                self.frame_changed.emit(frame_number, float(position_ms))

            near_video_end = (
                effective_duration_ms > 0
                and position_ms >= (effective_duration_ms - max(20.0, frame_ms * 1.5))
            )
            vlc_near_ratio_end = bool(vlc_position_ratio is not None and vlc_position_ratio >= 0.992)
            vlc_reached_ended = bool(
                is_vlc_active
                and vlc is not None
                and (
                    vlc_state == getattr(vlc.State, "Ended", None)
                    or self._vlc_end_reached_flag
                )
            )
            vlc_reached_stopped = bool(
                is_vlc_active
                and vlc is not None
                and vlc_state == getattr(vlc.State, "Stopped", None)
                and position_ms >= 80.0
            )
            vlc_reached_terminal = bool(vlc_reached_ended or vlc_reached_stopped)

            if is_vlc_active:
                # Track whether playback is progressing to detect silent stalls.
                if self._vlc_last_progress_ms is None:
                    self._vlc_last_progress_ms = float(position_ms)
                    self._vlc_stall_ticks = 0
                else:
                    progress_delta = abs(float(position_ms) - float(self._vlc_last_progress_ms))
                    # Count as stall only when there is effectively no forward movement.
                    if progress_delta <= 0.5:
                        self._vlc_stall_ticks += 1
                    else:
                        self._vlc_stall_ticks = 0
                        self._vlc_last_progress_ms = float(position_ms)

            near_tail_hint = bool(
                near_video_end
                or (vlc_position_ratio is not None and vlc_position_ratio >= 0.965)
                or frame_number >= max(0, self.total_frames - 3)
            )
            elapsed_play_s = max(0.0, time.monotonic() - float(self._vlc_play_started_monotonic or 0.0))
            vlc_stalled_near_tail = bool(
                is_vlc_active
                and near_tail_hint
                and self._vlc_stall_ticks >= 45
            )
            vlc_backend_not_playing_tail = bool(
                is_vlc_active
                and vlc_is_playing is False
                and near_tail_hint
                and elapsed_play_s >= 0.35
            )
            if is_vlc_active and self.loop_enabled and is_full_video_loop and (
                vlc_reached_terminal
                or vlc_backend_not_playing_tail
                or vlc_stalled_near_tail
            ):
                self._log_loop_debug(
                    "full-loop restart "
                    f"pos_ms={position_ms:.1f} frame={frame_number} "
                    f"ratio={vlc_position_ratio if vlc_position_ratio is not None else 'n/a'} "
                    f"state={vlc_state} vlc_playing={vlc_is_playing} "
                    f"stalls={self._vlc_stall_ticks} elapsed={elapsed_play_s:.3f}s"
                )
                self._restart_vlc_from_position_ms(0.0)
                return

            # External backend path: handle natural end-of-file when loop is disabled.
            if (
                is_external_backend
                and not self.loop_enabled
                and self.total_frames > 0
                and (
                    frame_number >= (self.total_frames - 1)
                    or near_video_end
                    or vlc_near_ratio_end
                    or vlc_reached_terminal
                    or (
                        is_vlc_active
                        and vlc_is_playing is False
                        and near_tail_hint
                        and self._vlc_stall_ticks >= 30
                    )
                )
            ):
                self._vlc_end_reached_flag = False
                self.pause()
                self.playback_finished.emit()
                return

            # Check loop boundaries
            if self.loop_enabled:
                end_frame = self.loop_end if self.loop_end is not None else self.total_frames - 1
                start_frame = self.loop_start if self.loop_start is not None else 0
                if start_frame > end_frame:
                    start_frame, end_frame = end_frame, start_frame

                reached_loop_end = frame_number >= end_frame
                if not reached_loop_end and self.total_frames > 0:
                    if self.loop_start is None and self.loop_end is None:
                        reached_loop_end = near_video_end or vlc_near_ratio_end or vlc_reached_terminal
                    else:
                        # Fire when position reaches the start of end_frame (not end_frame+1).
                        # Scale lead time with speed so fast playback doesn't overshoot.
                        loop_end_ms = float(end_frame) * frame_ms
                        speed_factor = max(1.5, abs(float(self.playback_speed)) * 1.5)
                        early_trigger_ms = max(frame_ms, frame_ms * speed_factor)
                        reached_loop_end = position_ms >= (loop_end_ms - early_trigger_ms)

                if reached_loop_end:
                    if self._is_mpv_forward_active() and self._is_segment_loop_active():
                        # mpv A/B loop handles the segment wrap directly.
                        pass
                    else:
                        # Loop back to start
                        start_position_ms = (float(start_frame) * frame_ms) if frame_ms > 0 else 0.0
                        is_segment_loop = self.loop_start is not None or self.loop_end is not None
                        if is_vlc_active and vlc_reached_ended:
                            self._restart_vlc_from_position_ms(
                                start_position_ms,
                                cover_frame=start_frame if is_segment_loop else None,
                                loop_start_ms=start_position_ms if is_segment_loop else None,
                            )
                        elif is_vlc_active and is_segment_loop and not self._vlc_loop_end_guard:
                            # Fallback: event-based path didn't fire (VLC build difference).
                            # Cover with exact end_frame and restart.
                            try:
                                self._show_opencv_frame(end_frame)
                            except Exception:
                                pass
                            self._cancel_vlc_reveal()
                            self._set_vlc_visible(False)
                            try:
                                if self.pixmap_item:
                                    self.pixmap_item.show()
                            except RuntimeError:
                                pass
                            self._show_vlc_cover_overlay()
                            self._seek_vlc_position_ms(start_position_ms)
                            self._begin_vlc_reveal(
                                delay_ms=16, force_ms=800, require_stable=False,
                                loop_start_ms=start_position_ms,
                            )
                        else:
                            self.seek_to_frame(start_frame)
                            if is_vlc_active and is_full_video_loop and vlc_near_ratio_end:
                                # Some VLC builds stall near EOF without entering Ended;
                                # force a clean restart in that case.
                                self._restart_vlc_from_position_ms(start_position_ms)
                        if self.is_playing:
                            if self._is_mpv_forward_active():
                                try:
                                    self._mpv_set_property('pause', False)
                                except Exception:
                                    pass
                            elif self._is_vlc_forward_active():
                                try:
                                    self.vlc_player.play()
                                except Exception:
                                    pass
                            else:
                                self.media_player.play()
                        if is_vlc_active:
                            self._vlc_end_reached_flag = False

    @Slot(QMediaPlayer.PlaybackState)
    def _on_playback_state_changed(self, state: QMediaPlayer.PlaybackState):
        """Handle playback state changes from QMediaPlayer."""
        if self._is_mpv_forward_active() or self._is_vlc_forward_active():
            return
        if state == QMediaPlayer.PlaybackState.StoppedState and self.is_playing:
            # Reached end of video
            if self.loop_enabled and self.loop_start is not None:
                self.seek_to_frame(self.loop_start)
                self.media_player.play()
            else:
                self.pause()
                self.playback_finished.emit()

    def get_current_frame_number(self):
        """Get current frame number."""
        return self.current_frame

    def resolve_exact_frame_for_marker(self, fallback_frame: int | None = None) -> int:
        """Resolve the best exact frame candidate for marker commit."""
        if self.total_frames <= 0 or self.fps <= 0:
            self._ensure_cap_ready()

        if fallback_frame is None:
            fallback = int(self.current_frame or 0)
        else:
            try:
                fallback = int(fallback_frame)
            except Exception:
                fallback = int(self.current_frame or 0)

        if self.total_frames > 0:
            fallback = max(0, min(fallback, self.total_frames - 1))
        else:
            fallback = max(0, fallback)

        position_ms = None
        try:
            if self._is_vlc_forward_active():
                position_ms = self._get_vlc_position_ms()
            elif self._is_mpv_forward_active():
                position_ms = self._get_mpv_position_ms()
            elif self.is_playing:
                position_ms = float(self.media_player.position())
        except Exception:
            position_ms = None

        resolved = fallback
        if position_ms is not None and self.fps > 0:
            resolved = int(round((float(position_ms) / 1000.0) * float(self.fps)))

        if self.total_frames > 0:
            resolved = max(0, min(resolved, self.total_frames - 1))
        else:
            resolved = max(0, resolved)
        return int(resolved)

    def get_total_frames(self):
        """Get total number of frames."""
        return self.total_frames

    def get_fps(self):
        """Get frames per second."""
        return self.fps

    def get_current_frame_as_numpy(self):
        """Extract current frame as RGB numpy array for processing.

        Returns:
            numpy.ndarray: RGB frame data, or None if extraction fails
        """
        if not self._ensure_cap_ready() or not self.cap:
            return None

        try:
            # Seek to current frame
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame)

            # Read frame
            ret, frame = self.cap.read()
            if not ret:
                return None

            # Convert BGR to RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            return frame_rgb
        except Exception as e:
            print(f"Error extracting frame {self.current_frame}: {e}")
            return None

    def set_loop(self, enabled: bool, start_frame: int = None, end_frame: int = None):
        """Set loop playback parameters."""
        self.loop_enabled = enabled
        self.loop_start = start_frame
        self.loop_end = end_frame
        # Reset loop-end guard/flag whenever markers change so next cycle fires cleanly.
        self._vlc_loop_end_guard = False
        self._vlc_loop_end_flag = False
        if not enabled:
            self._vlc_loop_end_wall_timer.stop()
            self._vlc_end_reached_flag = False
            self._vlc_stall_ticks = 0
            self._vlc_soft_restart_pending = False
            self._vlc_soft_restart_deadline_monotonic = 0.0
        self._log_loop_debug(
            f"set_loop enabled={bool(enabled)} start={start_frame} end={end_frame} "
            f"backend={self._active_forward_backend} fps={self.fps:.3f} total_frames={self.total_frames}"
            ,
            force=True,
        )

        # Enable/disable QMediaPlayer loops (for simple full-video loop)
        if enabled and start_frame is None and end_frame is None:
            self.media_player.setLoops(QMediaPlayer.Loops.Infinite)
        else:
            self.media_player.setLoops(QMediaPlayer.Loops.Once)

        if self.mpv_player is not None:
            if self._apply_mpv_loop_settings(clear_when_inactive=True):
                self._mpv_loop_fallback_warned = False

    def set_playback_speed(self, speed: float):
        """Set playback speed multiplier (-8.0 to 8.0)."""
        old_speed = self.playback_speed
        self.playback_speed = max(-8.0, min(8.0, speed))

        # If playing, switch modes if needed
        if self.is_playing:
            was_negative = old_speed < 0
            is_negative = self.playback_speed < 0

            if was_negative != is_negative:
                # Need to switch playback modes.
                self.pause()
                # Sync estimated position from current_frame so MPV/VLC resume
                # from where OpenCV left off, not from their pre-reverse position.
                # Must happen after pause() since pause() overwrites _mpv_estimated_position_ms.
                if was_negative and self.fps > 0:
                    sync_ms = self.current_frame / self.fps * 1000.0
                    self._mpv_estimated_position_ms = sync_ms
                    self._mpv_play_base_position_ms = sync_ms
                    self._vlc_estimated_position_ms = sync_ms
                self.play()
            elif is_negative:
                # Update OpenCV timer interval
                interval_ms = round(1000 / (self.fps * abs(self.playback_speed)))
                self.position_timer.setInterval(interval_ms)
            else:
                # Update active forward backend rate
                if self._is_mpv_forward_active():
                    try:
                        # Re-anchor dead-reckoning clock at current estimated
                        # position before changing speed, otherwise the new
                        # speed multiplied by the old elapsed time produces a
                        # wrong (jumped-back) position estimate.
                        current_ms = self._get_mpv_position_ms()
                        if current_ms is not None:
                            self._mpv_play_base_position_ms = float(current_ms)
                            self._mpv_play_started_monotonic = time.monotonic()
                        self._mpv_set_property('speed', max(0.1, float(self.playback_speed)))
                    except Exception:
                        pass
                elif self._is_vlc_forward_active():
                    self._set_vlc_rate(self.playback_speed)
                else:
                    self.media_player.setPlaybackRate(self.playback_speed)

    def set_muted(self, muted: bool):
        """Set audio mute state."""
        if self.audio_output:
            self.audio_output.setMuted(muted)
        if self.mpv_player is not None:
            try:
                self._mpv_set_property('mute', bool(muted))
            except Exception:
                pass
        if self.vlc_player is not None:
            self._set_vlc_muted(bool(muted))

    def cleanup(self):
        """Release video resources."""
        self._cancel_mpv_reveal()
        self._cancel_vlc_reveal()
        self.position_timer.stop()
        self.is_playing = False
        try:
            self.media_player.pause()
        except Exception:
            pass
        if self.mpv_player is not None:
            try:
                self._mpv_set_property('pause', True)
            except Exception:
                pass
        if self.vlc_player is not None:
            try:
                self._set_vlc_paused(True)
                self.vlc_player.stop()
            except Exception:
                pass
        self._qt_video_source_path = None

        # Release QMediaPlayer first (more sticky on Windows)
        if self.media_player:
            try:
                self.media_player.stop()
            except Exception:
                pass
            try:
                self.media_player.setVideoOutput(None)  # Disconnect video output
            except Exception:
                pass
            try:
                self.media_player.setSource(QUrl())  # Clear source
            except Exception:
                pass

        # Release OpenCV capture
        if self.cap:
            self.cap.release()
            self.cap = None

        # Remove video item from scene
        video_item = self.video_item
        self.video_item = None
        if video_item is not None:
            scene = None
            try:
                scene = video_item.scene()
            except Exception:
                scene = None
            if scene is not None:
                try:
                    scene.removeItem(video_item)
                except Exception:
                    pass
        self._teardown_mpv(drop_player=True)
        self._teardown_vlc(drop_player=True)

        # Reset video path to indicate no video is loaded
        self.video_path = None

        # Force Python garbage collection to release file handles immediately
        import gc
        gc.collect()
