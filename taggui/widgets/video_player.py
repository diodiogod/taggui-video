import os
import sys
import time
# Set environment variables BEFORE importing cv2
os.environ['OPENCV_FFMPEG_LOGLEVEL'] = '-8'
os.environ['OPENCV_LOG_LEVEL'] = 'SILENT'

import cv2
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, Signal, Slot, QUrl, QRect
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QGraphicsPixmapItem, QWidget, QMessageBox
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem

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


class VideoPlayerWidget(QWidget):
    """Hybrid video player using QMediaPlayer for playback and OpenCV for frame extraction."""
    _mpv_orphan_players = []
    _vlc_orphan_players = []

    # Signals
    frame_changed = Signal(int, float)  # frame_number, time_ms
    playback_finished = Signal()
    playback_started = Signal()  # Emitted when playback starts
    playback_paused = Signal()   # Emitted when playback pauses

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
        self.vlc_instance = None
        self.vlc_player = None
        self.vlc_widget = None
        self.vlc_host_view = None
        self.vlc_geometry_timer = QTimer(self)
        self.vlc_geometry_timer.setInterval(100)
        self.vlc_geometry_timer.timeout.connect(self._update_vlc_geometry_from_pixmap)
        self._vlc_estimated_position_ms = 0.0
        self._vlc_play_started_monotonic = 0.0
        self._vlc_play_base_position_ms = 0.0
        self._vlc_needs_reload = True
        self._vlc_last_widget_rect = QRect(0, 0, 1, 1)
        self._vlc_end_reached_flag = False
        self._vlc_event_manager = None
        self._vlc_end_event_handler = None
        self._vlc_last_progress_ms = None
        self._vlc_stall_ticks = 0
        self._vlc_last_loop_restart_monotonic = 0.0
        self._vlc_soft_restart_deadline_monotonic = 0.0
        self._vlc_soft_restart_pending = False
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
        """Rate-limited loop debug logging for backend diagnostics."""
        now = time.monotonic()
        if (not force) and ((now - self._loop_debug_last_log_monotonic) < 0.25):
            return
        self._loop_debug_last_log_monotonic = now
        print(f"[VIDEO][LOOP] {message}")

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

    def set_view_transformed(self, transformed: bool):
        """Hint from viewer zoom/pan state to choose compatible render path."""
        _ = bool(transformed)
        # Keep native backend active; only refresh geometry against the new transform.
        self.sync_external_surface_geometry()

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
        # Use exclusive end to keep the selected end frame perceptually included.
        end_ms = float(frame_bounds[1] + 1) * frame_ms
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
        """Show/hide mpv surface if it exists.

        Avoid frequent QWidget visible-state toggles; on Windows this has been
        unstable with embedded mpv. Instead, keep the widget shown and hide by
        collapsing geometry.
        """
        try:
            if self.mpv_widget:
                try:
                    import shiboken6
                    if not shiboken6.isValid(self.mpv_widget):
                        self.mpv_widget = None
                        return
                except Exception:
                    pass
                if visible:
                    self._update_mpv_geometry_from_pixmap()
                    if not self.mpv_geometry_timer.isActive():
                        self.mpv_geometry_timer.start()
                else:
                    self.mpv_geometry_timer.stop()
                    self.mpv_widget.setGeometry(QRect(0, 0, 1, 1))
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
        if not self.vlc_widget or not self.pixmap_item:
            return
        try:
            pixmap = self.pixmap_item.pixmap()
            if not pixmap or pixmap.isNull():
                return

            view = self._resolve_mpv_target_view()
            if view is None:
                return
            self.vlc_host_view = view

            scene_rect = self.pixmap_item.sceneBoundingRect()
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

    def _teardown_vlc(self, drop_player: bool = False):
        """Release vlc runtime resources if initialized."""
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
        """Attach VLC end-of-media event for reliable loop handling."""
        if self.vlc_player is None or vlc is None:
            return
        self._unbind_vlc_events()
        try:
            event_manager = self.vlc_player.event_manager()
        except Exception:
            self._vlc_event_manager = None
            self._vlc_end_event_handler = None
            return

        def _on_end_reached(_event):
            self._vlc_end_reached_flag = True

        try:
            event_manager.event_attach(vlc.EventType.MediaPlayerEndReached, _on_end_reached)
            self._vlc_event_manager = event_manager
            self._vlc_end_event_handler = _on_end_reached
        except Exception as e:
            print(f"[VIDEO] Failed to bind VLC end event: {e}")
            self._vlc_event_manager = None
            self._vlc_end_event_handler = None

    def _unbind_vlc_events(self):
        """Detach VLC events on teardown/recreate."""
        if self._vlc_event_manager is not None and self._vlc_end_event_handler is not None and vlc is not None:
            try:
                self._vlc_event_manager.event_detach(
                    vlc.EventType.MediaPlayerEndReached,
                    self._vlc_end_event_handler,
                )
            except Exception:
                pass
        self._vlc_event_manager = None
        self._vlc_end_event_handler = None

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
        if not self.pixmap_item or not self.pixmap_item.scene() or not self.video_path:
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

    def _restart_vlc_from_position_ms(self, position_ms: float, hard: bool = False):
        """Restart VLC from a target position; soft first, hard fallback if needed."""
        if self.vlc_player is None:
            return
        now = time.monotonic()
        # Guard against repeated loop restarts while VLC reports stale terminal state.
        if (now - float(self._vlc_last_loop_restart_monotonic or 0.0)) < 0.20:
            return
        self._vlc_last_loop_restart_monotonic = now
        safe_ms = max(0.0, float(position_ms))
        self._vlc_end_reached_flag = False
        self._vlc_estimated_position_ms = safe_ms
        self._vlc_play_base_position_ms = safe_ms
        self._vlc_play_started_monotonic = time.monotonic()
        self._vlc_last_progress_ms = safe_ms
        self._vlc_stall_ticks = 0
        if hard:
            self._vlc_soft_restart_pending = False
            self._vlc_soft_restart_deadline_monotonic = 0.0
            try:
                self.vlc_player.stop()
            except Exception:
                pass
            try:
                self.vlc_player.play()
            except Exception:
                return
            self._seek_vlc_position_ms(safe_ms)
            QTimer.singleShot(16, lambda ms=safe_ms: self._seek_vlc_position_ms(ms))
            QTimer.singleShot(35, lambda ms=safe_ms: self._seek_vlc_position_ms(ms))
            return

        # Soft restart path: avoid stop() to prevent black flash.
        self._vlc_soft_restart_pending = True
        self._vlc_soft_restart_deadline_monotonic = now + 0.24
        try:
            self.vlc_player.play()
        except Exception:
            return
        # libVLC can ignore the first seek right after Ended->play transition.
        self._seek_vlc_position_ms(safe_ms)
        QTimer.singleShot(0, lambda ms=safe_ms: self._seek_vlc_position_ms(ms))
        QTimer.singleShot(16, lambda ms=safe_ms: self._seek_vlc_position_ms(ms))
        QTimer.singleShot(30, lambda ms=safe_ms: self._seek_vlc_position_ms(ms))

    def _resolve_mpv_target_view(self):
        """Pick the most suitable QGraphicsView for the current pixmap scene."""
        if not self.pixmap_item:
            return None
        scene = self.pixmap_item.scene()
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

    def _begin_mpv_reveal(self, delay_ms: int = 120):
        """Reveal mpv surface immediately to avoid timer-related native crashes."""
        self._mpv_pending_reveal = False
        self._mpv_reveal_deadline_monotonic = 0.0
        self._mpv_reveal_timer.stop()
        try:
            if self.pixmap_item:
                self.pixmap_item.hide()
        except RuntimeError:
            pass
        self._set_mpv_visible(True)

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
            try:
                if self.pixmap_item:
                    self.pixmap_item.hide()
            except RuntimeError:
                pass
            self._set_mpv_visible(True)
            self._cancel_mpv_reveal()

    def _update_mpv_geometry_from_pixmap(self):
        """Keep mpv proxy geometry aligned with current pixmap frame size."""
        if not self.mpv_widget or not self.pixmap_item:
            return
        try:
            pixmap = self.pixmap_item.pixmap()
            if not pixmap or pixmap.isNull():
                return

            view = self._resolve_mpv_target_view()
            if view is None:
                return
            self.mpv_host_view = view

            scene_rect = self.pixmap_item.sceneBoundingRect()
            mapped_poly = view.mapFromScene(scene_rect)
            widget_rect = mapped_poly.boundingRect().intersected(view.viewport().rect())
            if widget_rect.width() > 1 and widget_rect.height() > 1:
                self.mpv_widget.setGeometry(widget_rect)
            else:
                self.mpv_widget.setGeometry(QRect(0, 0, 1, 1))
        except RuntimeError:
            self.mpv_widget = None

    def _teardown_mpv(self, drop_player: bool = False):
        """Release mpv runtime resources if initialized."""
        self._cancel_mpv_reveal()
        self.mpv_geometry_timer.stop()
        self._mpv_estimated_position_ms = 0.0
        self._mpv_play_started_monotonic = 0.0
        self._mpv_play_base_position_ms = 0.0
        self._active_forward_backend = PLAYBACK_BACKEND_QT_HYBRID
        self._mpv_needs_reload = True
        player = self.mpv_player
        if player is not None:
            try:
                player.command('set', 'pause', 'yes')
            except Exception:
                pass
        if drop_player:
            # Intentionally avoid explicit terminate() due repeated Windows native crashes.
            if player is not None:
                VideoPlayerWidget._mpv_orphan_players.append(player)
            self.mpv_player = None

        if self.mpv_widget is not None:
            try:
                self.mpv_widget.hide()
                self.mpv_widget.deleteLater()
            except Exception:
                pass
            self.mpv_widget = None

        self.mpv_host_view = None

    def _setup_mpv_for_current_video(self) -> bool:
        """Initialize mpv renderer bound to a scene widget surface."""
        if mpv is None or not self._is_using_mpv_backend():
            return False
        if not self.pixmap_item or not self.pixmap_item.scene() or not self.video_path:
            return False

        try:
            target_view = self._resolve_mpv_target_view()
            if target_view is None:
                return False

            if self.mpv_widget is None:
                self.mpv_host_view = target_view
                self.mpv_widget = QWidget(self.mpv_host_view.viewport())
                self.mpv_widget.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
                self.mpv_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                self.mpv_widget.setStyleSheet('background: black;')
                self.mpv_widget.setGeometry(0, 0, 1, 1)
                self.mpv_widget.show()
            else:
                self.mpv_host_view = target_view

            self._update_mpv_geometry_from_pixmap()
            self._set_mpv_visible(False)

            if self.mpv_player is None:
                wid = int(self.mpv_widget.winId())
                self.mpv_player = mpv.MPV(
                    wid=str(wid),
                    vo='gpu',
                    hwdec='no',
                    keep_open='yes',
                    pause=True,
                    osc='no',
                    input_default_bindings=False,
                    input_vo_keyboard=False,
                    start_event_thread=False,
                )
            self._mpv_string_command('loadfile', str(self.video_path), 'replace')
            self._mpv_set_property('pause', True)
            self._mpv_set_property('speed', max(0.1, float(self.playback_speed)))
            self._mpv_set_property('mute', bool(self.audio_output.isMuted()) if self.audio_output else True)
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
        seek_s = float(position_ms) / 1000.0
        try:
            self._mpv_string_command('seek', f'{seek_s:.6f}', 'absolute', 'exact')
        except Exception:
            pass

    def _mpv_string_command(self, name: str, *args):
        if self.mpv_player is None:
            return
        call_args = [str(arg) for arg in args if arg is not None]
        # Avoid python-mpv string_command on Windows; it has been a native crash hotspot.
        self.mpv_player.command(str(name), *call_args)

    def _mpv_set_property(self, prop_name: str, value):
        if self.mpv_player is None:
            return
        if isinstance(value, bool):
            encoded = 'yes' if value else 'no'
        else:
            encoded = str(value)
        self._mpv_string_command('set', str(prop_name), encoded)

    def _load_qt_media_source_for_current_video(self):
        if not self.video_path or self.video_item is None:
            return
        current_path = str(self.video_path)
        if self._qt_video_source_path == current_path:
            return

        import sys
        stdout_fd = sys.stdout.fileno()
        stderr_fd = sys.stderr.fileno()
        with open(os.devnull, 'w') as devnull:
            old_stdout = os.dup(stdout_fd)
            old_stderr = os.dup(stderr_fd)
            os.dup2(devnull.fileno(), stdout_fd)
            os.dup2(devnull.fileno(), stderr_fd)
            try:
                self.media_player.setSource(QUrl.fromLocalFile(current_path))
                self.media_player.setVideoOutput(self.video_item)
            finally:
                os.dup2(old_stdout, stdout_fd)
                os.dup2(old_stderr, stderr_fd)
                os.close(old_stdout)
                os.close(old_stderr)
        self._qt_video_source_path = current_path

    def sync_external_surface_geometry(self):
        """Force one immediate sync for external native video surfaces."""
        self._update_mpv_geometry_from_pixmap()
        self._update_vlc_geometry_from_pixmap()

    def load_video(self, video_path: Path, pixmap_item: QGraphicsPixmapItem):
        """Load a video file."""
        self._refresh_backend_selection()

        # Stop any previous playback
        self.pause()

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
        self._vlc_needs_reload = True
        self._qt_video_source_path = None
        self._cancel_mpv_reveal()
        self._set_mpv_visible(False)
        self._set_vlc_visible(False)
        if self.mpv_player is not None:
            try:
                self._mpv_set_property('pause', True)
            except Exception:
                pass
        if self.vlc_player is not None or self.vlc_widget is not None:
            try:
                self._teardown_vlc(drop_player=True)
            except Exception:
                pass

        # Load with OpenCV to get metadata and for frame extraction
        # Suppress ffmpeg output by temporarily redirecting stdout and stderr at OS level
        import sys
        stdout_fd = sys.stdout.fileno()
        stderr_fd = sys.stderr.fileno()
        with open(os.devnull, 'w') as devnull:
            old_stdout = os.dup(stdout_fd)
            old_stderr = os.dup(stderr_fd)
            os.dup2(devnull.fileno(), stdout_fd)
            os.dup2(devnull.fileno(), stderr_fd)
            try:
                self.cap = cv2.VideoCapture(str(video_path))
            finally:
                os.dup2(old_stdout, stdout_fd)
                os.dup2(old_stderr, stderr_fd)
                os.close(old_stdout)
                os.close(old_stderr)

        if not self.cap.isOpened():
            print(f"Failed to open video: {video_path}")
            return False

        # Get video properties from OpenCV (more reliable for frame count)
        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.duration_ms = (self.total_frames / self.fps * 1000) if self.fps > 0 else 0
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
        if pixmap_item.scene():
            pixmap_item.scene().addItem(self.video_item)

        # For external backends, avoid touching QMediaPlayer during list-click load path.
        # Lazily load Qt source only if/when Qt playback path is used.
        if (not self._is_using_mpv_backend()) and (not self._is_using_vlc_backend()):
            self._load_qt_media_source_for_current_video()

        # Show first frame using OpenCV (for frame-accurate display)
        self._show_opencv_frame(0)

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
            # Use OpenCV frame-by-frame for backward playback
            self._active_forward_backend = PLAYBACK_BACKEND_QT_HYBRID
            self._cancel_mpv_reveal()
            try:
                if self.video_item:
                    self.video_item.hide()
            except RuntimeError:
                pass  # C++ object deleted
            try:
                if self.pixmap_item:
                    self.pixmap_item.show()
            except RuntimeError:
                pass  # C++ object deleted
            self._set_mpv_visible(False)
            self._set_vlc_visible(False)
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
                    if self._is_segment_loop_active():
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
                    self._active_forward_backend = PLAYBACK_BACKEND_MPV_EXPERIMENTAL
                    self._mpv_set_property('speed', max(0.1, float(self.playback_speed)))
                    self._mpv_set_property('pause', False)
                    self._mpv_play_base_position_ms = float(self._mpv_estimated_position_ms)
                    self._mpv_play_started_monotonic = time.monotonic()
                    # Keep current frame visible until mpv output is ready.
                    try:
                        if self.pixmap_item:
                            self.pixmap_item.show()
                    except RuntimeError:
                        pass
                    self._begin_mpv_reveal(delay_ms=120)
                except Exception as e:
                    print(f"[VIDEO] mpv play fallback to Qt backend: {e}")
                    self.runtime_playback_backend = PLAYBACK_BACKEND_QT_HYBRID
                    self._active_forward_backend = PLAYBACK_BACKEND_QT_HYBRID
                    self._cancel_mpv_reveal()
                    self._set_mpv_visible(False)
                    self._set_vlc_visible(False)
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
                    self._active_forward_backend = PLAYBACK_BACKEND_VLC_EXPERIMENTAL
                    self._set_vlc_rate(self.playback_speed)
                    self._set_vlc_muted(bool(self.audio_output.isMuted()) if self.audio_output else True)
                    self._vlc_end_reached_flag = False
                    self._vlc_stall_ticks = 0
                    self.vlc_player.play()
                    self._seek_vlc_position_ms(self._vlc_estimated_position_ms)
                    self._vlc_play_base_position_ms = float(self._vlc_estimated_position_ms)
                    self._vlc_play_started_monotonic = time.monotonic()
                    try:
                        if self.pixmap_item:
                            self.pixmap_item.hide()
                    except RuntimeError:
                        pass
                    self._cancel_mpv_reveal()
                    self._set_mpv_visible(False)
                    self._set_vlc_visible(True)
                    # Geometry can still be stale right after first show/load.
                    # Re-sync in the next event-loop ticks to avoid partial/offset render.
                    QTimer.singleShot(0, self.sync_external_surface_geometry)
                    QTimer.singleShot(60, self.sync_external_surface_geometry)
                except Exception as e:
                    print(f"[VIDEO] vlc play fallback to Qt backend: {e}")
                    self.runtime_playback_backend = PLAYBACK_BACKEND_QT_HYBRID
                    self._active_forward_backend = PLAYBACK_BACKEND_QT_HYBRID
                    self._set_mpv_visible(False)
                    self._set_vlc_visible(False)
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
                self._load_qt_media_source_for_current_video()
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
            try:
                if self.video_item:
                    self.video_item.hide()
            except RuntimeError:
                pass  # C++ object deleted
            try:
                if self.pixmap_item:
                    self.pixmap_item.hide()
            except RuntimeError:
                pass  # C++ object deleted
            self._set_mpv_visible(True)
            self._set_vlc_visible(False)
            return

        # Switch to OpenCV frame for frame-accurate display
        try:
            if self.video_item:
                self.video_item.hide()
        except RuntimeError:
            pass  # C++ object deleted
        self._set_mpv_visible(False)
        self._set_vlc_visible(False)

        try:
            if self.pixmap_item:
                self.pixmap_item.show()
        except RuntimeError:
            pass  # C++ object deleted

        # Show exact current frame
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

    def toggle_play_pause(self):
        """Toggle between play and pause."""
        if self.is_playing:
            self.pause()
        else:
            self.play()

    def seek_to_frame(self, frame_number: int):
        """Seek to a specific frame (frame-accurate using OpenCV)."""
        if not self.cap:
            return

        frame_number = max(0, min(frame_number, self.total_frames - 1))
        self.current_frame = frame_number

        # Calculate position in milliseconds
        position_ms = (frame_number / self.fps * 1000) if self.fps > 0 else 0
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

        # If paused, show exact frame with OpenCV
        if not self.is_playing:
            if self._is_mpv_forward_active():
                try:
                    if self.video_item:
                        self.video_item.hide()
                except RuntimeError:
                    pass
                if self.mpv_widget is not None and self.mpv_widget.isVisible():
                    self._cancel_mpv_reveal()
                    try:
                        if self.pixmap_item:
                            self.pixmap_item.hide()
                    except RuntimeError:
                        pass
                    self._set_mpv_visible(True)
                else:
                    try:
                        if self.pixmap_item:
                            self.pixmap_item.show()
                    except RuntimeError:
                        pass
                    self._begin_mpv_reveal(delay_ms=80)
            else:
                self._show_opencv_frame(frame_number)

        # Emit frame changed signal
        self.frame_changed.emit(frame_number, position_ms)

    def _show_opencv_frame(self, frame_number: int):
        """Extract and display exact frame using OpenCV."""
        if not self.cap or not self.pixmap_item:
            return

        frame_number = max(0, min(frame_number, self.total_frames - 1))

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

        # Convert to QPixmap
        h, w, ch = frame_rgb.shape
        bytes_per_line = ch * w
        qt_image = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qt_image.copy())

        # Update pixmap item
        try:
            self.pixmap_item.setPixmap(pixmap)

            # Update video item size to match
            if self.video_item:
                self.video_item.setSize(pixmap.size())
            self._update_mpv_geometry_from_pixmap()
            self._update_vlc_geometry_from_pixmap()
        except RuntimeError:
            self.pixmap_item = None

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

            if self.current_frame <= start_frame:
                if self.loop_enabled and self.loop_end is not None:
                    # Loop back to end
                    self.current_frame = self.loop_end
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
            vlc_playing_state = getattr(vlc.State, "Playing", None) if vlc is not None else None
            seamless_pre_end_restart = bool(
                is_vlc_active
                and self.loop_enabled
                and is_full_video_loop
                and not self._vlc_soft_restart_pending
                and vlc_is_playing is True
                and (vlc_state is None or vlc_state == vlc_playing_state)
                and (
                    near_video_end
                    or (vlc_position_ratio is not None and vlc_position_ratio >= 0.95)
                )
            )

            if seamless_pre_end_restart and (
                (now_monotonic - float(self._vlc_last_loop_restart_monotonic or 0.0)) >= 0.18
            ):
                self._vlc_last_loop_restart_monotonic = now_monotonic
                self._vlc_end_reached_flag = False
                self._vlc_soft_restart_pending = False
                self._vlc_soft_restart_deadline_monotonic = 0.0
                self._log_loop_debug(
                    "full-loop seamless pre-end seek restart "
                    f"pos_ms={position_ms:.1f} frame={frame_number} "
                    f"ratio={vlc_position_ratio if vlc_position_ratio is not None else 'n/a'} "
                    f"state={vlc_state}",
                    force=True,
                )
                self._seek_vlc_position_ms(0.0)
                try:
                    self.vlc_player.play()
                except Exception:
                    pass
                return

            if is_vlc_active and self._vlc_soft_restart_pending:
                vlc_not_ended = True
                if vlc is not None:
                    vlc_not_ended = vlc_state != getattr(vlc.State, "Ended", None)
                resumed = bool(
                    vlc_is_playing is True
                    and vlc_not_ended
                    and position_ms >= max(5.0, frame_ms * 0.8)
                )
                if resumed:
                    self._vlc_soft_restart_pending = False
                    self._vlc_soft_restart_deadline_monotonic = 0.0
                elif now_monotonic >= float(self._vlc_soft_restart_deadline_monotonic or 0.0):
                    self._log_loop_debug(
                        "soft restart did not resume; escalating hard "
                        f"pos_ms={position_ms:.1f} frame={frame_number} "
                        f"state={vlc_state} vlc_playing={vlc_is_playing}",
                        force=True,
                    )
                    self._restart_vlc_from_position_ms(0.0, hard=True)
                    return
                else:
                    # Wait for soft restart to settle before evaluating loop triggers again.
                    return

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
                        loop_end_ms = float(end_frame + 1) * frame_ms
                        reached_loop_end = position_ms >= (loop_end_ms - max(12.0, frame_ms * 0.75))

                if reached_loop_end:
                    if self._is_mpv_forward_active() and self._is_segment_loop_active():
                        # mpv A/B loop handles the segment wrap directly.
                        pass
                    else:
                        # Loop back to start
                        start_position_ms = (float(start_frame) * frame_ms) if frame_ms > 0 else 0.0
                        if is_vlc_active and vlc_reached_ended:
                            self._restart_vlc_from_position_ms(start_position_ms)
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
        if not self.cap:
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
        if not enabled:
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
                # Need to switch playback modes
                self.pause()
                self.play()
            elif is_negative:
                # Update OpenCV timer interval
                interval_ms = round(1000 / (self.fps * abs(self.playback_speed)))
                self.position_timer.setInterval(interval_ms)
            else:
                # Update active forward backend rate
                if self._is_mpv_forward_active():
                    try:
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
            self.media_player.stop()
            self.media_player.setVideoOutput(None)  # Disconnect video output
            self.media_player.setSource(QUrl())  # Clear source

        # Release OpenCV capture
        if self.cap:
            self.cap.release()
            self.cap = None

        # Remove video item from scene
        if self.video_item and self.video_item.scene():
            self.video_item.scene().removeItem(self.video_item)
            self.video_item = None
        self._teardown_mpv(drop_player=True)
        self._teardown_vlc(drop_player=True)

        # Reset video path to indicate no video is loaded
        self.video_path = None

        # Force Python garbage collection to release file handles immediately
        import gc
        gc.collect()
