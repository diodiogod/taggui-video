import cv2
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QGraphicsPixmapItem, QWidget


class VideoPlayerWidget(QWidget):
    """Video player with frame-accurate playback using OpenCV."""

    # Signals
    frame_changed = Signal(int, float)  # frame_number, time_ms
    playback_finished = Signal()

    def __init__(self):
        super().__init__()
        self.video_path = None
        self.cap = None
        self.is_playing = False
        self.current_frame = 0
        self.total_frames = 0
        self.fps = 0
        self.pixmap_item = None  # Will be set by ImageViewer

        # Loop state
        self.loop_enabled = False
        self.loop_start = None
        self.loop_end = None

        # Playback timer
        self.timer = QTimer()
        self.timer.timeout.connect(self._play_next_frame)

    def load_video(self, video_path: Path, pixmap_item: QGraphicsPixmapItem):
        """Load a video file."""
        # Stop any previous playback and cleanup
        self.pause()

        # Release old capture if exists
        if self.cap:
            self.cap.release()
            self.cap = None

        self.video_path = video_path
        self.pixmap_item = pixmap_item

        self.cap = cv2.VideoCapture(str(video_path))
        if not self.cap.isOpened():
            print(f"Failed to open video: {video_path}")
            return False

        # Get video properties
        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.current_frame = 0

        # Show first frame
        self.seek_to_frame(0)
        return True

    def play(self):
        """Start playback."""
        if not self.cap or self.is_playing:
            return

        self.is_playing = True
        # Calculate frame interval in milliseconds
        if self.fps > 0:
            interval_ms = int(1000 / self.fps)
            self.timer.start(interval_ms)

    def pause(self):
        """Pause playback."""
        self.is_playing = False
        self.timer.stop()

    def stop(self):
        """Stop playback and reset to first frame."""
        self.pause()
        self.seek_to_frame(0)

    def toggle_play_pause(self):
        """Toggle between play and pause."""
        if self.is_playing:
            self.pause()
        else:
            self.play()

    @Slot()
    def _play_next_frame(self):
        """Play next frame during playback."""
        # Check if we're at the end of loop or video
        end_frame = self.loop_end if (self.loop_enabled and self.loop_end is not None) else self.total_frames - 1

        if self.current_frame >= end_frame:
            if self.loop_enabled and self.loop_start is not None:
                # Loop back to start
                self.seek_to_frame(self.loop_start)
            else:
                # Reached end of video
                self.pause()
                self.playback_finished.emit()
            return

        self.seek_to_frame(self.current_frame + 1)

    def seek_to_frame(self, frame_number: int):
        """Seek to a specific frame."""
        if not self.cap or not self.pixmap_item:
            return

        frame_number = max(0, min(frame_number, self.total_frames - 1))
        self.current_frame = frame_number

        # Set frame position
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)

        # Read frame
        ret, frame = self.cap.read()
        if not ret:
            print(f"Failed to read frame {frame_number}")
            return

        # Convert BGR to RGB
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = frame_rgb.shape
        bytes_per_line = ch * w
        qt_image = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qt_image.copy())  # Copy to avoid data lifetime issues

        # Update the pixmap item - check if it's still valid
        try:
            self.pixmap_item.setPixmap(pixmap)
        except RuntimeError:
            # Pixmap item was deleted
            self.pixmap_item = None
            return

        # Emit position update
        time_ms = (frame_number / self.fps * 1000) if self.fps > 0 else 0
        self.frame_changed.emit(frame_number, time_ms)

    def get_current_frame_number(self):
        """Get current frame number."""
        return self.current_frame

    def get_total_frames(self):
        """Get total number of frames."""
        return self.total_frames

    def get_fps(self):
        """Get frames per second."""
        return self.fps

    def set_loop(self, enabled: bool, start_frame: int = None, end_frame: int = None):
        """Set loop playback parameters."""
        self.loop_enabled = enabled
        self.loop_start = start_frame
        self.loop_end = end_frame

    def cleanup(self):
        """Release video resources."""
        self.stop()
        if self.cap:
            self.cap.release()
            self.cap = None
