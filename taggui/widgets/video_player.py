import os
# Set environment variables BEFORE importing cv2
os.environ['OPENCV_FFMPEG_LOGLEVEL'] = '-8'
os.environ['OPENCV_LOG_LEVEL'] = 'SILENT'

import cv2
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, Signal, Slot, QUrl
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QGraphicsPixmapItem, QWidget, QMessageBox
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem

from utils.video import VideoValidator

# Suppress OpenCV logs
cv2.setLogLevel(0)


class VideoPlayerWidget(QWidget):
    """Hybrid video player using QMediaPlayer for playback and OpenCV for frame extraction."""

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

    def load_video(self, video_path: Path, pixmap_item: QGraphicsPixmapItem):
        """Load a video file."""
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

        # Load video into QMediaPlayer (suppress ffmpeg output)
        import sys
        stdout_fd = sys.stdout.fileno()
        stderr_fd = sys.stderr.fileno()
        with open(os.devnull, 'w') as devnull:
            old_stdout = os.dup(stdout_fd)
            old_stderr = os.dup(stderr_fd)
            os.dup2(devnull.fileno(), stdout_fd)
            os.dup2(devnull.fileno(), stderr_fd)
            try:
                self.media_player.setSource(QUrl.fromLocalFile(str(video_path)))
                self.media_player.setVideoOutput(self.video_item)
            finally:
                os.dup2(old_stdout, stdout_fd)
                os.dup2(old_stderr, stderr_fd)
                os.close(old_stdout)
                os.close(old_stderr)

        # Show first frame using OpenCV (for frame-accurate display)
        self._show_opencv_frame(0)

        # Set video item size to match first frame
        if self.pixmap_item and self.pixmap_item.pixmap():
            video_size = self.pixmap_item.pixmap().size()
            self.video_item.setSize(video_size)

        # Hide video item initially (show pixmap with first frame)
        self.video_item.hide()
        self.pixmap_item.show()

        return True

    def play(self):
        """Start playback using QMediaPlayer (or OpenCV for negative speeds)."""
        if not self.video_path or self.is_playing:
            return

        self.is_playing = True
        self.playback_started.emit()  # Notify that playback started

        if self.playback_speed < 0:
            # Use OpenCV frame-by-frame for backward playback
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
            # Use QMediaPlayer for smooth forward playback
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

            # Set playback rate
            self.media_player.setPlaybackRate(self.playback_speed)

            # Start playback
            self.media_player.play()

            # Start position tracking timer
            self.position_timer.setInterval(16)  # ~60 FPS
            try:
                self.position_timer.timeout.disconnect()
            except:
                pass  # No connections yet
            self.position_timer.timeout.connect(self._update_frame_from_position)
            self.position_timer.start()

    def pause(self):
        """Pause playback and show exact frame with OpenCV."""
        was_playing = self.is_playing
        self.is_playing = False
        self.position_timer.stop()
        self.media_player.pause()

        if was_playing:
            self.playback_paused.emit()  # Notify that playback paused

        # Switch to OpenCV frame for frame-accurate display
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

        # Show exact current frame
        self._show_opencv_frame(self.current_frame)

    def stop(self):
        """Stop playback and reset to first frame."""
        self.pause()
        self.media_player.stop()
        self.seek_to_frame(0)

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

        # Seek QMediaPlayer
        self.media_player.setPosition(int(position_ms))

        # If paused, show exact frame with OpenCV
        if not self.is_playing:
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

        position_ms = self.media_player.position()
        playback_rate = self.media_player.playbackRate()

        # Calculate current frame from position
        if self.fps > 0:
            frame_number = int((position_ms / 1000.0) * self.fps)
            frame_number = max(0, min(frame_number, self.total_frames - 1))

            # Only update if frame changed
            if frame_number != self.current_frame:
                self.current_frame = frame_number
                self.frame_changed.emit(frame_number, float(position_ms))

            # Check loop boundaries
            if self.loop_enabled:
                end_frame = self.loop_end if self.loop_end is not None else self.total_frames - 1
                start_frame = self.loop_start if self.loop_start is not None else 0

                if frame_number >= end_frame:
                    # Loop back to start
                    self.seek_to_frame(start_frame)
                    if self.is_playing:
                        self.media_player.play()

    @Slot(QMediaPlayer.PlaybackState)
    def _on_playback_state_changed(self, state: QMediaPlayer.PlaybackState):
        """Handle playback state changes from QMediaPlayer."""
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

        # Enable/disable QMediaPlayer loops (for simple full-video loop)
        if enabled and start_frame is None and end_frame is None:
            self.media_player.setLoops(QMediaPlayer.Loops.Infinite)
        else:
            self.media_player.setLoops(QMediaPlayer.Loops.Once)

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
                # Update QMediaPlayer rate
                self.media_player.setPlaybackRate(self.playback_speed)

    def set_muted(self, muted: bool):
        """Set audio mute state."""
        if self.audio_output:
            self.audio_output.setMuted(muted)

    def cleanup(self):
        """Release video resources."""
        self.stop()
        self.position_timer.stop()

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

        # Reset video path to indicate no video is loaded
        self.video_path = None

        # Force Python garbage collection to release file handles immediately
        import gc
        gc.collect()
