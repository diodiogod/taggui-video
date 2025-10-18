from PySide6.QtCore import Qt, Signal, Slot, QPointF, QRectF
from PySide6.QtGui import QIcon, QPainter, QPolygonF, QColor, QPen
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton,
                               QSlider, QSpinBox, QVBoxLayout, QWidget, QCheckBox, QStyle, QStyleOptionSlider)


class LoopSlider(QSlider):
    """Custom slider with visual loop markers."""

    loop_start_changed = Signal(int)
    loop_end_changed = Signal(int)

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.loop_start = None
        self.loop_end = None
        self._dragging_marker = None  # 'start', 'end', 'both', or None
        self._marker_size = 20  # Click detection radius
        self._marker_gap = 0  # Distance between markers when dragging both

        # Set minimum height to show markers above slider
        self.setMinimumHeight(30)

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
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Calculate positions
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        groove = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderGroove, self)

        # Draw loop markers as triangles ABOVE the groove (pointing UP at it)
        marker_width = 18  # Width of triangle base
        marker_height = 14  # Height of triangle

        if self.loop_start is not None:
            # Start marker (pink/magenta triangle pointing UP to groove)
            pos = self._value_to_position(self.loop_start, groove)
            triangle = QPolygonF([
                QPointF(pos, groove.top() - 2),  # Point at bottom (touching groove top)
                QPointF(pos - marker_width / 2, groove.top() - marker_height - 2),  # Left corner
                QPointF(pos + marker_width / 2, groove.top() - marker_height - 2)   # Right corner
            ])
            painter.setPen(QPen(QColor(255, 255, 255), 2))  # White outline
            painter.setBrush(QColor(255, 0, 128))  # Pink/Magenta
            painter.drawPolygon(triangle)

        if self.loop_end is not None:
            # End marker (orange triangle pointing UP to groove)
            pos = self._value_to_position(self.loop_end, groove)
            triangle = QPolygonF([
                QPointF(pos, groove.top() - 2),  # Point at bottom (touching groove top)
                QPointF(pos - marker_width / 2, groove.top() - marker_height - 2),  # Left corner
                QPointF(pos + marker_width / 2, groove.top() - marker_height - 2)   # Right corner
            ])
            painter.setPen(QPen(QColor(255, 255, 255), 2))  # White outline
            painter.setBrush(QColor(255, 140, 0))  # Orange
            painter.drawPolygon(triangle)

    def _value_to_position(self, value, groove_rect):
        """Convert slider value to pixel position."""
        if self.maximum() == self.minimum():
            return groove_rect.left()

        ratio = (value - self.minimum()) / (self.maximum() - self.minimum())
        return int(groove_rect.left() + ratio * groove_rect.width())

    def _position_to_value(self, x_pos, groove_rect):
        """Convert pixel position to slider value."""
        if groove_rect.width() == 0:
            return self.minimum()

        ratio = (x_pos - groove_rect.left()) / groove_rect.width()
        ratio = max(0, min(1, ratio))
        return int(self.minimum() + ratio * (self.maximum() - self.minimum()))

    def _is_near_marker(self, pos, marker_value, groove_rect):
        """Check if position is near a marker (upper area only for grabbing)."""
        if marker_value is None:
            return False
        marker_x = self._value_to_position(marker_value, groove_rect)
        # Only detect marker in the UPPER area (above groove) - y must be less than groove top
        # This allows seekbar clicks to work on the groove itself
        is_in_upper_area = pos.y() < groove_rect.top()
        return is_in_upper_area and abs(pos.x() - marker_x) < self._marker_size

    def mousePressEvent(self, event):
        """Handle mouse press for marker dragging and position jumping."""
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        groove = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderGroove, self)

        # Check if clicking near a marker
        near_start = self._is_near_marker(event.pos(), self.loop_start, groove)
        near_end = self._is_near_marker(event.pos(), self.loop_end, groove)

        # Check if Shift is pressed and both markers exist
        shift_pressed = (event.modifiers() & Qt.KeyboardModifier.ShiftModifier) == Qt.KeyboardModifier.ShiftModifier

        if shift_pressed and self.loop_start is not None and self.loop_end is not None and (near_start or near_end):
            # Drag both markers together
            self._dragging_marker = 'both'
            self._marker_gap = self.loop_end - self.loop_start
            event.accept()
            return
        elif near_start:
            self._dragging_marker = 'start'
            event.accept()
            return
        elif near_end:
            self._dragging_marker = 'end'
            event.accept()
            return

        # Jump to clicked position on slider, then allow dragging
        if event.button() == Qt.MouseButton.LeftButton:
            # Use the same calculation as _position_to_value for consistency
            new_value = self._position_to_value(event.pos().x(), groove)

            # Calculate where the handle will be for this value
            handle_pos = self._value_to_position(new_value, groove)

            # Create a modified event at the handle position so super() doesn't recalculate
            from PySide6.QtGui import QMouseEvent
            from PySide6.QtCore import QPointF
            modified_event = QMouseEvent(
                event.type(),
                QPointF(handle_pos, event.pos().y()),
                event.globalPosition(),
                event.button(),
                event.buttons(),
                event.modifiers()
            )

            self.setValue(new_value)
            # Pass modified event to super so it thinks we clicked on the handle
            super().mousePressEvent(modified_event)
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Handle mouse move for marker dragging."""
        if self._dragging_marker:
            opt = QStyleOptionSlider()
            self.initStyleOption(opt)
            groove = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderGroove, self)

            new_value = self._position_to_value(event.pos().x(), groove)

            if self._dragging_marker == 'start':
                self.loop_start = new_value
                self.loop_start_changed.emit(new_value)
            elif self._dragging_marker == 'end':
                self.loop_end = new_value
                self.loop_end_changed.emit(new_value)
            elif self._dragging_marker == 'both':
                # Move both markers maintaining the gap
                max_val = self.maximum()
                # Clamp the start position
                new_start = max(self.minimum(), min(new_value, max_val - self._marker_gap))
                new_end = new_start + self._marker_gap

                self.loop_start = new_start
                self.loop_end = new_end
                self.loop_start_changed.emit(new_start)
                self.loop_end_changed.emit(new_end)

            self.update()
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """Handle mouse release."""
        if self._dragging_marker:
            self._dragging_marker = None
            event.accept()
            return

        super().mouseReleaseEvent(event)


class VideoControlsWidget(QWidget):
    """Video playback controls with frame-accurate navigation - overlay widget."""

    # Signals
    play_pause_requested = Signal()
    stop_requested = Signal()
    frame_changed = Signal(int)  # Frame number
    skip_backward_requested = Signal()  # Skip 1 second backward
    skip_forward_requested = Signal()  # Skip 1 second forward
    loop_start_set = Signal()
    loop_end_set = Signal()
    loop_reset = Signal()
    loop_toggled = Signal(bool)
    speed_changed = Signal(float)  # Playback speed multiplier

    def __init__(self, parent=None):
        super().__init__(parent)

        # Make it semi-transparent overlay
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(self.backgroundRole(), Qt.GlobalColor.black)
        self.setPalette(palette)
        self.setWindowOpacity(0.8)

        # Enable mouse tracking for cursor updates
        self.setMouseTracking(True)

        # For dragging the controls
        self._dragging = False
        self._drag_start_pos = None

        # For resizing the controls
        self._resizing = False
        self._resize_start_pos = None
        self._resize_start_width = None
        self._resize_start_x = None
        self._resize_handle_width = 10  # Width of resize area on edges

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
        self.play_pause_btn.setStyleSheet("""
            QPushButton {
                background-color: #2b2b2b;
                border: 2px solid #555;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #3a3a3a;
                border-color: #666;
            }
        """)
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

        # 1-second skip buttons
        self.skip_back_btn = QPushButton('<<')
        self.skip_back_btn.setToolTip('Skip 1 Second Backward')
        self.skip_back_btn.setMaximumWidth(40)
        self.skip_back_btn.clicked.connect(self.skip_backward_requested.emit)

        self.skip_forward_btn = QPushButton('>>')
        self.skip_forward_btn.setToolTip('Skip 1 Second Forward')
        self.skip_forward_btn.setMaximumWidth(40)
        self.skip_forward_btn.clicked.connect(self.skip_forward_requested.emit)

        # Frame number input
        self.frame_label = QLabel('Frame:')
        self.frame_spinbox = QSpinBox()
        self.frame_spinbox.setMinimum(0)
        self.frame_spinbox.setMaximum(0)
        self.frame_spinbox.setMaximumWidth(80)
        self.frame_spinbox.valueChanged.connect(self.frame_changed.emit)

        self.frame_total_label = QLabel('/ 0')
        self.frame_total_label.setMinimumWidth(60)  # Make room for "last" text

        # Playback speed slider with extended range support (rubberband effect)
        self.speed_label = QLabel('Speed:')
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setMinimum(0)  # 0.0x (visual range)
        self.speed_slider.setMaximum(200)  # 2.0x (visual range)
        self.speed_slider.setValue(100)  # 1.0x
        self.speed_slider.setTickInterval(25)
        self.speed_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.speed_slider.setMinimumWidth(100)  # Minimum width
        # No maximum width - let it expand to fill available space
        self.speed_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 4px;
                background: #555;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #4CAF50;
                border: 1px solid #45a049;
                width: 14px;
                margin: -5px 0;
                border-radius: 7px;
            }
            QSlider::handle:horizontal:hover {
                background: #5FBF60;
            }
        """)

        # Extended speed tracking for rubberband effect
        self._extended_speed = 1.0  # Actual speed (can be -8.0 to 8.0)
        self._is_dragging_speed = False
        self._last_mouse_pos = None
        self._drag_start_value = 100

        # Install event filter for mouse tracking
        self.speed_slider.installEventFilter(self)

        # Connect slider signals
        self.speed_slider.valueChanged.connect(self._on_speed_slider_changed)
        self.speed_slider.sliderPressed.connect(self._on_speed_slider_pressed)
        self.speed_slider.sliderReleased.connect(self._on_speed_slider_released)

        self.speed_value_label = QLabel('1.00x')
        self.speed_value_label.setMinimumWidth(45)
        self.speed_value_label.setStyleSheet("QLabel { color: #4CAF50; font-weight: bold; cursor: pointer; }")
        self.speed_value_label.mousePressEvent = self._reset_speed

        controls_layout.addWidget(self.play_pause_btn)
        controls_layout.addWidget(self.stop_btn)
        controls_layout.addSpacing(20)
        controls_layout.addWidget(self.skip_back_btn)
        controls_layout.addWidget(self.prev_frame_btn)
        controls_layout.addWidget(self.next_frame_btn)
        controls_layout.addWidget(self.skip_forward_btn)
        controls_layout.addSpacing(20)
        controls_layout.addWidget(self.frame_label)
        controls_layout.addWidget(self.frame_spinbox)
        controls_layout.addWidget(self.frame_total_label)
        controls_layout.addSpacing(20)
        controls_layout.addWidget(self.speed_label)
        controls_layout.addWidget(self.speed_slider, 1)  # Stretch factor 1 - expands to fill space
        controls_layout.addWidget(self.speed_value_label)

        # Timeline slider with loop markers
        slider_layout = QHBoxLayout()
        self.timeline_slider = LoopSlider(Qt.Orientation.Horizontal)
        self.timeline_slider.setMinimum(0)
        self.timeline_slider.setMaximum(0)
        self.timeline_slider.valueChanged.connect(self._slider_changed)
        # Connect marker dragging signals
        self.timeline_slider.loop_start_changed.connect(self._on_loop_start_dragged)
        self.timeline_slider.loop_end_changed.connect(self._on_loop_end_dragged)
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

        # Marker range frame count display
        self.marker_range_label = QLabel('')
        self.marker_range_label.setMinimumWidth(90)
        self.marker_range_label.setStyleSheet("QLabel { color: #4CAF50; font-weight: bold; }")

        # N*4+1 frame rule indicator
        self.frame_rule_label = QLabel('')
        self.frame_rule_label.setMinimumWidth(60)
        self.frame_rule_label.setStyleSheet("QLabel { color: #FF9800; font-weight: bold; }")

        # SAR warning indicator (only shown for non-square pixel videos)
        self.sar_warning_label = QLabel('')
        self.sar_warning_label.setMinimumWidth(80)
        self.sar_warning_label.setStyleSheet("QLabel { color: #FF5722; font-weight: bold; }")
        self.sar_warning_label.setToolTip('Video has non-square pixels (SAR != 1:1)\nMay cause issues with training tools that ignore SAR')

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

        self.loop_checkbox = QPushButton('LOOP')
        self.loop_checkbox.setCheckable(True)
        self.loop_checkbox.setToolTip('Enable/Disable Loop Playback')
        self.loop_checkbox.setMaximumWidth(50)
        self.loop_checkbox.setStyleSheet("""
            QPushButton {
                font-weight: bold;
                font-size: 10px;
                padding: 2px 4px;
                border: 2px solid #666;
                background-color: #333;
                color: #999;
            }
            QPushButton:checked {
                background-color: #4CAF50;
                color: white;
                border: 2px solid #45a049;
            }
        """)
        self.loop_checkbox.toggled.connect(self._toggle_loop)

        self.loop_reset_btn = QPushButton('✕')
        self.loop_reset_btn.setToolTip('Clear Loop Markers')
        self.loop_reset_btn.setMaximumWidth(30)
        self.loop_reset_btn.setStyleSheet("QPushButton { font-size: 16px; padding: 2px; }")
        self.loop_reset_btn.clicked.connect(self._reset_loop)

        info_layout.addWidget(self.time_label)
        info_layout.addWidget(self.fps_label)
        info_layout.addWidget(self.frame_count_label)
        info_layout.addWidget(self.marker_range_label)
        info_layout.addWidget(self.frame_rule_label)
        info_layout.addWidget(self.sar_warning_label)
        info_layout.addStretch()
        info_layout.addWidget(self.loop_reset_btn)
        info_layout.addWidget(self.loop_start_btn)
        info_layout.addWidget(self.loop_end_btn)
        info_layout.addWidget(self.loop_checkbox)

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

        # Fixed marker size (set from main window)
        self.fixed_marker_size = 31

        # Auto-play state (persists across video changes)
        self.auto_play_enabled = False

        # Load persistent settings
        self._load_persistent_settings()

        # Hide by default
        self.hide()

    def _load_persistent_settings(self):
        """Load persistent settings from config."""
        from utils.settings import settings

        # Load loop enabled state
        loop_enabled = settings.value('video_loop_enabled', False, type=bool)
        # Block signals temporarily to avoid emission during init
        self.loop_checkbox.blockSignals(True)
        self.loop_checkbox.setChecked(loop_enabled)
        self.loop_checkbox.blockSignals(False)
        # Set internal state (signal will be emitted when video loads)
        self.is_looping = loop_enabled

    def _apply_scaling(self):
        """Apply scaling to internal elements based on current width."""
        width = self.width()

        # Ideal size is 800px - only scale DOWN when smaller, never scale up
        ideal_width = 800
        scale = min(1.0, max(0.5, width / ideal_width))

        # Scale button sizes
        button_size = int(40 * scale)
        for btn in [self.play_pause_btn, self.stop_btn, self.prev_frame_btn,
                    self.next_frame_btn, self.skip_back_btn, self.skip_forward_btn]:
            btn.setMaximumWidth(button_size)
            btn.setMaximumHeight(button_size)

        # Scale loop control buttons
        loop_btn_size = int(30 * scale)
        for btn in [self.loop_start_btn, self.loop_end_btn, self.loop_reset_btn]:
            btn.setMaximumWidth(loop_btn_size)
            btn.setMaximumHeight(loop_btn_size)
            font_size = int(18 * scale)
            btn.setStyleSheet(f"QPushButton {{ font-size: {font_size}px; padding: 2px; }}")

        # Scale loop checkbox
        loop_checkbox_width = int(50 * scale)
        font_size_loop = int(10 * scale)
        self.loop_checkbox.setMaximumWidth(loop_checkbox_width)
        self.loop_checkbox.setStyleSheet(f"""
            QPushButton {{
                font-weight: bold;
                font-size: {font_size_loop}px;
                padding: 2px 4px;
                border: 2px solid #666;
                background-color: #333;
                color: #999;
            }}
            QPushButton:checked {{
                background-color: #4CAF50;
                color: white;
                border: 2px solid #45a049;
            }}
        """)

        # Scale frame spinbox
        spinbox_width = int(80 * scale)
        self.frame_spinbox.setMaximumWidth(spinbox_width)
        # Scale spinbox font (bigger base size: 12pt)
        spinbox_font = self.frame_spinbox.font()
        spinbox_font.setPointSize(max(9, int(12 * scale)))
        self.frame_spinbox.setFont(spinbox_font)

        # Scale label fonts (bigger base size: 11pt)
        label_font = self.frame_label.font()
        label_font.setPointSize(max(8, int(11 * scale)))
        for label in [self.frame_label, self.time_label, self.fps_label,
                      self.frame_count_label, self.marker_range_label, self.frame_total_label,
                      self.frame_rule_label, self.sar_warning_label, self.speed_label, self.speed_value_label]:
            label.setFont(label_font)

        # Scale speed slider - only set minimum width, let it expand
        speed_slider_min_width = int(100 * scale)
        self.speed_slider.setMinimumWidth(speed_slider_min_width)
        # Don't set maximum width - let it fill available space

        # Scale slider minimum height
        slider_height = int(30 * scale)
        self.timeline_slider.setMinimumHeight(slider_height)

        # Scale margins and spacing
        margin = int(8 * scale)
        spacing = int(8 * scale)
        self.layout().setContentsMargins(margin, int(4 * scale), margin, int(4 * scale))
        self.layout().setSpacing(spacing)

    def resizeEvent(self, event):
        """Scale all controls based on available width."""
        super().resizeEvent(event)

        # Don't interfere with manual resizing
        if self._resizing:
            return

        self._apply_scaling()

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

    def eventFilter(self, obj, event):
        """Event filter for speed slider mouse tracking."""
        if obj == self.speed_slider:
            from PySide6.QtCore import QEvent
            from PySide6.QtGui import QCursor

            if event.type() == QEvent.Type.MouseMove and self._is_dragging_speed:
                current_mouse = QCursor.pos()

                if self._last_mouse_pos is not None:
                    # Calculate delta movement
                    delta_x = current_mouse.x() - self._last_mouse_pos.x()

                    # Calculate base sensitivity based on slider width
                    slider_width = self.speed_slider.width()
                    if slider_width > 0:
                        base_sensitivity = 2.0 / slider_width  # 2.0 is normal range

                        # Calculate acceleration based on how far we are from normal bounds
                        acceleration = 1.0
                        if self._extended_speed < 0.0:
                            # Left side acceleration: more negative = faster
                            out_of_bounds = abs(self._extended_speed)
                            acceleration = 1.0 + (out_of_bounds * 3.0)
                        elif self._extended_speed > 2.0:
                            # Right side acceleration: higher above 2.0 = faster
                            out_of_bounds = self._extended_speed - 2.0
                            acceleration = 1.0 + (out_of_bounds * 2.5)

                        # Apply accelerated sensitivity
                        sensitivity = base_sensitivity * acceleration
                        self._extended_speed += delta_x * sensitivity

                        # Clamp to absolute limits (-8.0 to 8.0)
                        self._extended_speed = max(-8.0, min(8.0, self._extended_speed))

                        # Update slider position (clamped to visual range 0.0-2.0)
                        clamped_value = max(0.0, min(2.0, self._extended_speed))
                        self.speed_slider.blockSignals(True)
                        self.speed_slider.setValue(int(clamped_value * 100.0))
                        self.speed_slider.blockSignals(False)

                        # If we're back in normal range, sync extended speed with slider
                        if 0.0 <= self._extended_speed <= 2.0:
                            self._extended_speed = clamped_value

                        # Update display and emit signal
                        self.speed_value_label.setText(f'{self._extended_speed:.2f}x')
                        self.speed_changed.emit(self._extended_speed)

                self._last_mouse_pos = current_mouse

        return super().eventFilter(obj, event)

    @Slot()
    def _on_speed_slider_pressed(self):
        """Handle speed slider press - start extended drag tracking."""
        self._is_dragging_speed = True
        self._extended_speed = self.speed_slider.value() / 100.0
        self._drag_start_value = self.speed_slider.value()
        from PySide6.QtGui import QCursor
        self._last_mouse_pos = QCursor.pos()

    @Slot()
    def _on_speed_slider_released(self):
        """Handle speed slider release - clamp to visual range."""
        self._is_dragging_speed = False
        self._last_mouse_pos = None

        # If extended speed is outside the visual range (0.0-2.0), clamp to edges
        # But for negative speeds, clamp to -2.0 (minimum backward speed) instead of 0.0
        if self._extended_speed < 0.0:
            # Was in negative range, clamp to minimum backward speed (-2.0x)
            # This corresponds to slider position 0 showing as minimum speed
            self._extended_speed = max(-2.0, self._extended_speed)
            # Map -2.0 to slider position 0
            slider_pos = 0
        elif self._extended_speed > 2.0:
            # Was above max, clamp to maximum (2.0x)
            self._extended_speed = 2.0
            slider_pos = 200
        else:
            # Within range, sync with slider value
            self._extended_speed = self.speed_slider.value() / 100.0
            slider_pos = int(self._extended_speed * 100.0)

        # Update slider and display
        self.speed_slider.blockSignals(True)
        self.speed_slider.setValue(slider_pos)
        self.speed_slider.blockSignals(False)
        self.speed_value_label.setText(f'{self._extended_speed:.2f}x')
        self.speed_changed.emit(self._extended_speed)

    @Slot(int)
    def _on_speed_slider_changed(self, value):
        """Handle playback speed slider change (normal mode only)."""
        if not self._is_dragging_speed:
            # Normal slider input (not during extended drag)
            self._extended_speed = value / 100.0
            self.speed_value_label.setText(f'{self._extended_speed:.2f}x')
            self.speed_changed.emit(self._extended_speed)

    def _reset_speed(self, event):
        """Reset playback speed to 1.0x when label is clicked."""
        self._extended_speed = 1.0
        self.speed_slider.blockSignals(True)
        self.speed_slider.setValue(100)
        self.speed_slider.blockSignals(False)
        self.speed_value_label.setText('1.00x')
        self.speed_changed.emit(1.0)

    @Slot(dict)
    def set_video_info(self, metadata: dict):
        """Update controls with video metadata."""
        if not metadata:
            return

        fps = metadata.get('fps', 0)
        frame_count = metadata.get('frame_count', 0)
        duration = metadata.get('duration', 0)
        sar_num = metadata.get('sar_num', 1)
        sar_den = metadata.get('sar_den', 1)

        # Update frame controls
        self.frame_spinbox.setMaximum(frame_count - 1 if frame_count > 0 else 0)
        self.timeline_slider.setMaximum(frame_count - 1 if frame_count > 0 else 0)
        self.frame_total_label.setText(f'/ {frame_count}')

        # Update info labels
        self.fps_label.setText(f'{fps:.2f} fps')
        self.frame_count_label.setText(f'{frame_count} frames')

        # Update frame total label initially
        if frame_count > 0:
            self.frame_total_label.setText(f'/ {frame_count}')
        else:
            self.frame_total_label.setText('/ 0')

        # Update N*4+1 frame rule indicator
        if frame_count > 0:
            # Check if frame count follows N*4+1 rule
            is_valid = (frame_count - 1) % 4 == 0
            if is_valid:
                self.frame_rule_label.setText('✓N*4+1')
                self.frame_rule_label.setStyleSheet("QLabel { color: #4CAF50; font-weight: bold; }")
            else:
                self.frame_rule_label.setText('✗N*4+1')
                self.frame_rule_label.setStyleSheet("QLabel { color: #F44336; font-weight: bold; }")
        else:
            self.frame_rule_label.setText('')

        # Update SAR warning indicator (only show if SAR != 1:1)
        if sar_num > 0 and sar_den > 0 and sar_num != sar_den:
            sar_ratio = sar_num / sar_den
            self.sar_warning_label.setText(f'⚠SAR {sar_num}:{sar_den}')
            self.sar_warning_label.setToolTip(
                f'Video has non-square pixels (SAR {sar_num}:{sar_den} = {sar_ratio:.3f})\n'
                f'Training tools like musubi-tuner may ignore SAR and use wrong dimensions.\n'
                f'Consider re-encoding with square pixels (SAR 1:1) before training.'
            )
        else:
            self.sar_warning_label.setText('')
            self.sar_warning_label.setToolTip('')

        # Format duration as mm:ss.mmm
        minutes = int(duration // 60)
        seconds = int(duration % 60)
        milliseconds = int((duration % 1) * 1000)
        self.time_label.setText(f'00:00.000 / {minutes:02d}:{seconds:02d}.{milliseconds:03d}')

        # Restore loop state after video loads
        if self.is_looping:
            self.loop_toggled.emit(True)

    def should_auto_play(self) -> bool:
        """Check if auto-play should trigger for the next video."""
        return self.auto_play_enabled

    @Slot(int, float)
    def update_position(self, frame: int, time_ms: float):
        """Update display when playback position changes."""
        # Update frame display - block signals to prevent feedback loop
        self._updating_slider = True
        self.frame_spinbox.blockSignals(True)
        self.frame_spinbox.setValue(frame)
        self.frame_spinbox.blockSignals(False)
        self.timeline_slider.setValue(frame)
        self._updating_slider = False

        # Update frame total label with "last" indicator
        total_frames = self.frame_spinbox.maximum() + 1  # Convert from 0-based max to total count
        if total_frames > 0:
            is_last = frame == self.frame_spinbox.maximum()
            if is_last:
                frame_display = "last"
            else:
                frame_display = str(total_frames)
            self.frame_total_label.setText(f'/ {frame_display}')
        else:
            self.frame_total_label.setText('/ 0')

        # Update time display
        time_seconds = time_ms / 1000.0
        minutes = int(time_seconds // 60)
        seconds = int(time_seconds % 60)
        milliseconds = int((time_seconds % 1) * 1000)

        current_text = self.time_label.text()
        total_time = current_text.split('/ ')[-1] if '/' in current_text else '00:00.000'
        self.time_label.setText(f'{minutes:02d}:{seconds:02d}.{milliseconds:03d} / {total_time}')

    @Slot(bool)
    def set_playing(self, playing: bool, update_auto_play: bool = False):
        """Update play/pause button state.

        Args:
            playing: Whether video is playing
            update_auto_play: If True, updates auto-play state (for manual user toggles)
        """
        self.is_playing = playing

        # Only update auto-play state on manual user toggles
        if update_auto_play:
            self.auto_play_enabled = playing

        if playing:
            self.play_pause_btn.setIcon(QIcon.fromTheme('media-playback-pause'))
            tooltip = 'Pause (Space) - Auto-play ON' if self.auto_play_enabled else 'Pause (Space) - Auto-play OFF'
            self.play_pause_btn.setToolTip(tooltip)
            # Green glow when playing
            self.play_pause_btn.setStyleSheet("""
                QPushButton {
                    background-color: #1a3a1a;
                    border: 2px solid #4CAF50;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: #254a25;
                    border-color: #5FBF60;
                }
            """)
        else:
            self.play_pause_btn.setIcon(QIcon.fromTheme('media-playback-start'))
            tooltip = 'Play (Space) - Auto-play ON' if self.auto_play_enabled else 'Play (Space) - Auto-play OFF'
            self.play_pause_btn.setToolTip(tooltip)
            # Normal state when paused
            self.play_pause_btn.setStyleSheet("""
                QPushButton {
                    background-color: #2b2b2b;
                    border: 2px solid #555;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: #3a3a3a;
                    border-color: #666;
                }
            """)

    def _update_marker_range_display(self):
        """Update the marker range frame count display."""
        if self.loop_start_frame is not None and self.loop_end_frame is not None:
            frame_count = abs(self.loop_end_frame - self.loop_start_frame) + 1
            self.marker_range_label.setText(f'[{frame_count} frames]')
        else:
            self.marker_range_label.setText('')

    @Slot()
    def _set_loop_start(self):
        """Set loop start at current frame, and auto-set end if fixed marker size is enabled."""
        self.loop_start_frame = self.frame_spinbox.value()

        # Auto-set end marker based on fixed marker size (only if not Custom/0)
        if self.fixed_marker_size > 0:
            max_frame = self.frame_spinbox.maximum()
            self.loop_end_frame = min(self.loop_start_frame + self.fixed_marker_size - 1, max_frame)
            # Update end button color too
            self.loop_end_btn.setStyleSheet("QPushButton { background-color: #FF8C00; color: white; font-size: 18px; padding: 2px; }")
            self.loop_end_set.emit()

        self.loop_start_set.emit()
        # Update button color to match pink marker
        self.loop_start_btn.setStyleSheet("QPushButton { background-color: #FF0080; color: white; font-size: 18px; padding: 2px; }")
        # Update timeline markers
        self.timeline_slider.set_loop_markers(self.loop_start_frame, self.loop_end_frame)
        # Update range display
        self._update_marker_range_display()

    @Slot()
    def _set_loop_end(self):
        """Set loop end at current frame."""
        self.loop_end_frame = self.frame_spinbox.value()
        self.loop_end_set.emit()
        # Update button color to match orange marker
        self.loop_end_btn.setStyleSheet("QPushButton { background-color: #FF8C00; color: white; font-size: 18px; padding: 2px; }")
        # Update timeline markers
        self.timeline_slider.set_loop_markers(self.loop_start_frame, self.loop_end_frame)
        # Update range display
        self._update_marker_range_display()

    @Slot(bool)
    def _toggle_loop(self, enabled: bool):
        """Toggle loop playback."""
        self.is_looping = enabled
        self.loop_toggled.emit(enabled)
        # Save loop state to settings
        from utils.settings import settings
        settings.setValue('video_loop_enabled', enabled)

    @Slot()
    def _reset_loop(self):
        """Reset loop markers only (keeps loop enabled/disabled state)."""
        self.loop_start_frame = None
        self.loop_end_frame = None
        # Don't change is_looping or loop_checkbox state
        self.loop_reset.emit()
        # Clear button styling
        self.loop_start_btn.setStyleSheet("QPushButton { font-size: 18px; padding: 2px; }")
        self.loop_end_btn.setStyleSheet("QPushButton { font-size: 18px; padding: 2px; }")
        # Clear timeline markers
        self.timeline_slider.clear_loop_markers()
        # Clear range display
        self._update_marker_range_display()

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
        self.frame_rule_label.setText('')
        self.set_playing(False)
        self._reset_loop()

    @Slot(int)
    def _on_loop_start_dragged(self, frame):
        """Handle loop start marker being dragged."""
        self.loop_start_frame = frame
        self.loop_start_btn.setStyleSheet("QPushButton { background-color: #FF0080; color: white; font-size: 18px; padding: 2px; }")
        self.loop_start_set.emit()
        # Update range display
        self._update_marker_range_display()

    @Slot(int)
    def _on_loop_end_dragged(self, frame):
        """Handle loop end marker being dragged."""
        self.loop_end_frame = frame
        self.loop_end_btn.setStyleSheet("QPushButton { background-color: #FF8C00; color: white; font-size: 18px; padding: 2px; }")
        self.loop_end_set.emit()
        # Update range display
        self._update_marker_range_display()

    def mousePressEvent(self, event):
        """Start dragging or resizing the controls widget."""
        if event.button() == Qt.MouseButton.LeftButton:
            # Check if near left or right edge for resize
            if event.pos().x() <= self._resize_handle_width:
                # Left edge resize
                self._resizing = 'left'
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_start_width = self.width()
                self._resize_start_x = self.x()
                event.accept()
                return
            elif event.pos().x() >= self.width() - self._resize_handle_width:
                # Right edge resize
                self._resizing = 'right'
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_start_width = self.width()
                event.accept()
                return

            # Otherwise, start dragging
            self._dragging = True
            self._drag_start_pos = event.globalPosition().toPoint() - self.pos()
            event.accept()

    def mouseMoveEvent(self, event):
        """Drag or resize the controls widget, and update cursor."""
        # Update cursor based on position
        if not self._dragging and not self._resizing:
            if event.pos().x() <= self._resize_handle_width or event.pos().x() >= self.width() - self._resize_handle_width:
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)

        if self._resizing:
            delta = event.globalPosition().toPoint() - self._resize_start_pos
            parent_rect = self.parent().rect()

            if self._resizing == 'left':
                # Resize from left edge
                new_width = self._resize_start_width - delta.x()
                new_x = self._resize_start_x + delta.x()
                # Clamp width (min 400px, max parent width)
                new_width = max(400, min(new_width, parent_rect.width()))
                # Adjust x to maintain right edge position
                new_x = self._resize_start_x + (self._resize_start_width - new_width)
                # Clamp x position
                new_x = max(0, min(new_x, parent_rect.width() - new_width))
                self.setGeometry(new_x, self.y(), new_width, self.height())
            elif self._resizing == 'right':
                # Resize from right edge
                new_width = self._resize_start_width + delta.x()
                # Clamp width (min 400px, max fits in parent)
                max_width = parent_rect.width() - self.x()
                new_width = max(400, min(new_width, max_width))
                self.setGeometry(self.x(), self.y(), new_width, self.height())
            event.accept()
        elif self._dragging:
            new_pos = event.globalPosition().toPoint() - self._drag_start_pos
            # Keep within parent bounds
            parent_rect = self.parent().rect()
            new_pos.setX(max(0, min(new_pos.x(), parent_rect.width() - self.width())))
            new_pos.setY(max(0, min(new_pos.y(), parent_rect.height() - self.height())))
            self.move(new_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        """Stop dragging or resizing the controls widget."""
        if event.button() == Qt.MouseButton.LeftButton:
            was_resizing = self._resizing
            current_width = self.width()  # Save width before changing _resizing flag
            self._dragging = False
            self._resizing = False

            # Trigger scaling update after resize is done
            if was_resizing:
                # Apply scaling to internal elements without changing widget width
                self._apply_scaling()
                # Adjust height to fit content, keeping width the same
                self.adjustSize()
                self.resize(current_width, self.sizeHint().height())
                # Force complete layout recalculation
                self.layout().invalidate()
                self.layout().activate()
                # Force slider to recalculate its internal geometry
                self.timeline_slider.update()
                # Repaint everything
                self.update()

            # Save position and width as percentage of parent dimensions
            from utils.settings import settings
            if self.parent():
                parent_width = self.parent().width()
                parent_height = self.parent().height()
                if parent_width > 0 and parent_height > 0:
                    x_percent = self.x() / parent_width
                    y_percent = self.y() / parent_height
                    width_percent = self.width() / parent_width
                    settings.setValue('video_controls_x_percent', x_percent)
                    settings.setValue('video_controls_y_percent', y_percent)
                    settings.setValue('video_controls_width_percent', width_percent)
            event.accept()
