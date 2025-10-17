from PySide6.QtCore import Qt, Signal, Slot, QPointF, QRectF
from PySide6.QtGui import QIcon, QPainter, QPolygonF, QColor, QPen
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton,
                               QSlider, QSpinBox, QVBoxLayout, QWidget, QCheckBox, QStyle, QStyleOptionSlider)


class LoopSlider(QSlider):
    """Custom slider with visual loop markers."""

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.loop_start = None
        self.loop_end = None

    def set_loop_markers(self, start, end):
        """Set loop marker positions."""
        self.loop_start = start
        self.loop_end = end
        self.update()

    def clear_loop_markers(self):
        """Clear loop markers."""
        self.loop_start = None
        self.loop_end = None
        self.update()

    def paintEvent(self, event):
        """Paint slider with loop markers."""
        super().paintEvent(event)

        if self.loop_start is None and self.loop_end is None:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Calculate positions
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        groove = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderGroove, self)

        # Draw loop markers as triangles
        marker_size = 10

        if self.loop_start is not None:
            # Start marker (pink/magenta triangle pointing down)
            pos = self._value_to_position(self.loop_start, groove)
            triangle = QPolygonF([
                QPointF(pos, groove.top() - 2),
                QPointF(pos - marker_size // 2, groove.top() - marker_size - 2),
                QPointF(pos + marker_size // 2, groove.top() - marker_size - 2)
            ])
            painter.setBrush(QColor(255, 0, 128))  # Pink/Magenta
            painter.setPen(QPen(QColor(200, 0, 100), 2))
            painter.drawPolygon(triangle)

        if self.loop_end is not None:
            # End marker (orange triangle pointing down)
            pos = self._value_to_position(self.loop_end, groove)
            triangle = QPolygonF([
                QPointF(pos, groove.top() - 2),
                QPointF(pos - marker_size // 2, groove.top() - marker_size - 2),
                QPointF(pos + marker_size // 2, groove.top() - marker_size - 2)
            ])
            painter.setBrush(QColor(255, 140, 0))  # Orange
            painter.setPen(QPen(QColor(200, 100, 0), 2))
            painter.drawPolygon(triangle)

    def _value_to_position(self, value, groove_rect):
        """Convert slider value to pixel position."""
        if self.maximum() == self.minimum():
            return groove_rect.left()

        ratio = (value - self.minimum()) / (self.maximum() - self.minimum())
        return int(groove_rect.left() + ratio * groove_rect.width())


class VideoControlsWidget(QWidget):
    """Video playback controls with frame-accurate navigation - overlay widget."""

    # Signals
    play_pause_requested = Signal()
    stop_requested = Signal()
    frame_changed = Signal(int)  # Frame number
    loop_start_set = Signal()
    loop_end_set = Signal()
    loop_reset = Signal()
    loop_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)

        # Make it semi-transparent overlay
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(self.backgroundRole(), Qt.GlobalColor.black)
        self.setPalette(palette)
        self.setWindowOpacity(0.8)

        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 4, 8, 4)
        main_layout.setSpacing(8)

        # Top row: Playback controls + Frame navigation
        controls_layout = QHBoxLayout()

        # Playback buttons with icons
        self.play_pause_btn = QPushButton()
        self.play_pause_btn.setIcon(QIcon.fromTheme('media-playback-start'))
        self.play_pause_btn.setToolTip('Play/Pause (Space)')
        self.play_pause_btn.setMaximumWidth(40)
        self.play_pause_btn.clicked.connect(self.play_pause_requested.emit)

        self.stop_btn = QPushButton()
        self.stop_btn.setIcon(QIcon.fromTheme('media-playback-stop'))
        self.stop_btn.setToolTip('Stop')
        self.stop_btn.setMaximumWidth(40)
        self.stop_btn.clicked.connect(self.stop_requested.emit)

        # Frame navigation with icons
        self.prev_frame_btn = QPushButton()
        self.prev_frame_btn.setIcon(QIcon.fromTheme('media-skip-backward'))
        self.prev_frame_btn.setToolTip('Previous Frame (Left Arrow)')
        self.prev_frame_btn.setMaximumWidth(40)
        self.prev_frame_btn.clicked.connect(self._prev_frame)

        self.next_frame_btn = QPushButton()
        self.next_frame_btn.setIcon(QIcon.fromTheme('media-skip-forward'))
        self.next_frame_btn.setToolTip('Next Frame (Right Arrow)')
        self.next_frame_btn.setMaximumWidth(40)
        self.next_frame_btn.clicked.connect(self._next_frame)

        # Frame number input
        self.frame_label = QLabel('Frame:')
        self.frame_spinbox = QSpinBox()
        self.frame_spinbox.setMinimum(0)
        self.frame_spinbox.setMaximum(0)
        self.frame_spinbox.setMaximumWidth(80)
        self.frame_spinbox.valueChanged.connect(self.frame_changed.emit)

        self.frame_total_label = QLabel('/ 0')

        controls_layout.addWidget(self.play_pause_btn)
        controls_layout.addWidget(self.stop_btn)
        controls_layout.addSpacing(20)
        controls_layout.addWidget(self.prev_frame_btn)
        controls_layout.addWidget(self.next_frame_btn)
        controls_layout.addSpacing(20)
        controls_layout.addWidget(self.frame_label)
        controls_layout.addWidget(self.frame_spinbox)
        controls_layout.addWidget(self.frame_total_label)
        controls_layout.addStretch()

        # Timeline slider with loop markers
        slider_layout = QHBoxLayout()
        self.timeline_slider = LoopSlider(Qt.Orientation.Horizontal)
        self.timeline_slider.setMinimum(0)
        self.timeline_slider.setMaximum(0)
        self.timeline_slider.valueChanged.connect(self._slider_changed)
        slider_layout.addWidget(self.timeline_slider)

        # Bottom row: Info display + Loop controls
        info_layout = QHBoxLayout()

        # Time display
        self.time_label = QLabel('00:00.000 / 00:00.000')
        self.time_label.setMinimumWidth(150)

        # FPS display
        self.fps_label = QLabel('0.00 fps')
        self.fps_label.setMinimumWidth(80)

        # Frame count display
        self.frame_count_label = QLabel('0 frames')
        self.frame_count_label.setMinimumWidth(80)

        # Loop controls - smaller buttons with text labels
        self.loop_start_btn = QPushButton('◀')  # Triangle pointing left/down
        self.loop_start_btn.setToolTip('Set Loop Start at current frame (Pink marker)')
        self.loop_start_btn.setMaximumWidth(30)
        self.loop_start_btn.setStyleSheet("QPushButton { font-size: 18px; padding: 2px; }")
        self.loop_start_btn.clicked.connect(self._set_loop_start)

        self.loop_end_btn = QPushButton('▶')  # Triangle pointing right/down
        self.loop_end_btn.setToolTip('Set Loop End at current frame (Orange marker)')
        self.loop_end_btn.setMaximumWidth(30)
        self.loop_end_btn.setStyleSheet("QPushButton { font-size: 18px; padding: 2px; }")
        self.loop_end_btn.clicked.connect(self._set_loop_end)

        self.loop_checkbox = QCheckBox('Loop')
        self.loop_checkbox.setToolTip('Enable/Disable Loop Playback')
        self.loop_checkbox.toggled.connect(self._toggle_loop)

        self.loop_reset_btn = QPushButton('✕')
        self.loop_reset_btn.setToolTip('Clear Loop Markers')
        self.loop_reset_btn.setMaximumWidth(30)
        self.loop_reset_btn.setStyleSheet("QPushButton { font-size: 16px; padding: 2px; }")
        self.loop_reset_btn.clicked.connect(self._reset_loop)

        info_layout.addWidget(self.time_label)
        info_layout.addWidget(self.fps_label)
        info_layout.addWidget(self.frame_count_label)
        info_layout.addStretch()
        info_layout.addWidget(self.loop_start_btn)
        info_layout.addWidget(self.loop_end_btn)
        info_layout.addWidget(self.loop_checkbox)
        info_layout.addWidget(self.loop_reset_btn)

        # Add all layouts to main
        main_layout.addLayout(controls_layout)
        main_layout.addLayout(slider_layout)
        main_layout.addLayout(info_layout)

        # Track current state
        self.is_playing = False
        self._updating_slider = False

        # Loop state
        self.loop_start_frame = None
        self.loop_end_frame = None
        self.is_looping = False

        # Hide by default
        self.hide()

    @Slot()
    def _prev_frame(self):
        """Go to previous frame."""
        current = self.frame_spinbox.value()
        if current > 0:
            self.frame_spinbox.setValue(current - 1)

    @Slot()
    def _next_frame(self):
        """Go to next frame."""
        current = self.frame_spinbox.value()
        if current < self.frame_spinbox.maximum():
            self.frame_spinbox.setValue(current + 1)

    @Slot(int)
    def _slider_changed(self, value):
        """Sync spinbox when slider moves."""
        if not self._updating_slider:
            self.frame_spinbox.setValue(value)

    @Slot(dict)
    def set_video_info(self, metadata: dict):
        """Update controls with video metadata."""
        if not metadata:
            return

        fps = metadata.get('fps', 0)
        frame_count = metadata.get('frame_count', 0)
        duration = metadata.get('duration', 0)

        # Update frame controls
        self.frame_spinbox.setMaximum(frame_count - 1 if frame_count > 0 else 0)
        self.timeline_slider.setMaximum(frame_count - 1 if frame_count > 0 else 0)
        self.frame_total_label.setText(f'/ {frame_count}')

        # Update info labels
        self.fps_label.setText(f'{fps:.2f} fps')
        self.frame_count_label.setText(f'{frame_count} frames')

        # Format duration as mm:ss.mmm
        minutes = int(duration // 60)
        seconds = int(duration % 60)
        milliseconds = int((duration % 1) * 1000)
        self.time_label.setText(f'00:00.000 / {minutes:02d}:{seconds:02d}.{milliseconds:03d}')

    @Slot(int, float)
    def update_position(self, frame: int, time_ms: float):
        """Update display when playback position changes."""
        # Update frame display
        self._updating_slider = True
        self.frame_spinbox.setValue(frame)
        self.timeline_slider.setValue(frame)
        self._updating_slider = False

        # Update time display
        time_seconds = time_ms / 1000.0
        minutes = int(time_seconds // 60)
        seconds = int(time_seconds % 60)
        milliseconds = int((time_seconds % 1) * 1000)

        current_text = self.time_label.text()
        total_time = current_text.split('/ ')[-1] if '/' in current_text else '00:00.000'
        self.time_label.setText(f'{minutes:02d}:{seconds:02d}.{milliseconds:03d} / {total_time}')

    @Slot(bool)
    def set_playing(self, playing: bool):
        """Update play/pause button state."""
        self.is_playing = playing
        if playing:
            self.play_pause_btn.setIcon(QIcon.fromTheme('media-playback-pause'))
            self.play_pause_btn.setToolTip('Pause (Space)')
        else:
            self.play_pause_btn.setIcon(QIcon.fromTheme('media-playback-start'))
            self.play_pause_btn.setToolTip('Play (Space)')

    @Slot()
    def _set_loop_start(self):
        """Set loop start at current frame."""
        self.loop_start_frame = self.frame_spinbox.value()
        self.loop_start_set.emit()
        # Update button color to match pink marker
        self.loop_start_btn.setStyleSheet("QPushButton { background-color: #FF0080; color: white; font-size: 18px; padding: 2px; }")
        # Update timeline markers
        self.timeline_slider.set_loop_markers(self.loop_start_frame, self.loop_end_frame)

    @Slot()
    def _set_loop_end(self):
        """Set loop end at current frame."""
        self.loop_end_frame = self.frame_spinbox.value()
        self.loop_end_set.emit()
        # Update button color to match orange marker
        self.loop_end_btn.setStyleSheet("QPushButton { background-color: #FF8C00; color: white; font-size: 18px; padding: 2px; }")
        # Update timeline markers
        self.timeline_slider.set_loop_markers(self.loop_start_frame, self.loop_end_frame)

    @Slot(bool)
    def _toggle_loop(self, enabled: bool):
        """Toggle loop playback."""
        self.is_looping = enabled
        self.loop_toggled.emit(enabled)

    @Slot()
    def _reset_loop(self):
        """Reset loop markers."""
        self.loop_start_frame = None
        self.loop_end_frame = None
        self.is_looping = False
        self.loop_checkbox.setChecked(False)
        self.loop_reset.emit()
        # Clear button styling
        self.loop_start_btn.setStyleSheet("QPushButton { font-size: 18px; padding: 2px; }")
        self.loop_end_btn.setStyleSheet("QPushButton { font-size: 18px; padding: 2px; }")
        # Clear timeline markers
        self.timeline_slider.clear_loop_markers()

    def get_loop_range(self):
        """Get current loop range (start, end) or None if not set."""
        if self.loop_start_frame is not None and self.loop_end_frame is not None:
            return (self.loop_start_frame, self.loop_end_frame)
        return None

    @Slot()
    def reset(self):
        """Reset controls to default state."""
        self.frame_spinbox.setValue(0)
        self.timeline_slider.setValue(0)
        self.time_label.setText('00:00.000 / 00:00.000')
        self.fps_label.setText('0.00 fps')
        self.frame_count_label.setText('0 frames')
        self.frame_total_label.setText('/ 0')
        self.set_playing(False)
        self._reset_loop()
