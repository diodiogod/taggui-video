import time

from PySide6.QtCore import Qt, Signal, Slot, QPointF, QRectF
from PySide6.QtGui import QIcon, QPainter, QPolygonF, QColor, QPen
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton,
                               QSlider, QSpinBox, QVBoxLayout, QWidget, QCheckBox, QStyle, QStyleOptionSlider,
                               QSizePolicy)
from utils.settings import settings, DEFAULT_SETTINGS
from skins.engine import SkinManager

try:
    from shiboken6 import isValid as _shiboken_is_valid
except Exception:
    _shiboken_is_valid = None


class LoopSlider(QSlider):
    """Custom slider with visual loop markers."""

    loop_start_changed = Signal(int)
    loop_end_changed = Signal(int)
    marker_drag_started = Signal()  # Emitted when marker drag starts
    marker_drag_ended = Signal()  # Emitted when marker drag ends
    marker_preview_frame = Signal(int)  # Emitted during drag to preview frame

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.loop_start = None
        self.loop_end = None
        self._dragging_marker = None  # 'start', 'end', 'both', or None
        self._marker_size = 20  # Click detection radius
        self._marker_gap = 0  # Distance between markers when dragging both
        self._drag_anchor = None  # 'start' or 'end' - which marker was originally clicked for 'both' drag

        # Marker colors (can be set by skin system)
        self._marker_start_color = QColor(255, 0, 128)  # Default pink/magenta
        self._marker_end_color = QColor(255, 140, 0)   # Default orange
        self._marker_outline_color = QColor(255, 255, 255)  # Default white
        self._marker_outline_width = 2
        self._marker_width = 18
        self._marker_height = 14
        self._marker_offset_y = -2
        self._marker_shape = 'triangle'

        # Set minimum height to show markers above slider
        self.setMinimumHeight(30)

        # Tooltip to explain marker controls
        self.setToolTip(
            'Loop Markers:\n'
            '• Drag markers to adjust range\n'
            '• Shift+Drag marker to move both together'
        )

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

    def set_marker_colors(self, colors: dict):
        """Set loop marker colors from skin.

        Args:
            colors: Dict with marker color/style properties.
        """
        start_hex = colors.get('start_color', '#FF0080')
        end_hex = colors.get('end_color', '#FF8C00')
        outline_hex = colors.get('outline_color', '#FFFFFF')

        # Convert hex to QColor
        self._marker_start_color = QColor(start_hex)
        self._marker_end_color = QColor(end_hex)
        self._marker_outline_color = QColor(outline_hex)
        self._marker_outline_width = max(1, int(colors.get('outline_width', 2)))
        self._marker_width = max(8, int(colors.get('marker_width', 18)))
        self._marker_height = max(6, int(colors.get('marker_height', 14)))
        self._marker_offset_y = int(colors.get('marker_offset_y', -2))
        shape = str(colors.get('marker_shape', 'triangle')).lower()
        self._marker_shape = shape if shape in ('triangle', 'diamond') else 'triangle'
        self._marker_size = max(10, int(self._marker_width * 0.9))

        # Trigger repaint
        self.update()

    def paintEvent(self, event):
        """Paint slider with loop markers."""
        super().paintEvent(event)

        if self.loop_start is None and self.loop_end is None:
            return

        painter = QPainter(self)
        if not painter.isActive():
            return

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Calculate positions
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        groove = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderGroove, self)

        marker_width = self._marker_width
        marker_height = self._marker_height
        marker_offset_y = self._marker_offset_y

        def _build_marker_polygon(x_pos: int) -> QPolygonF:
            if self._marker_shape == 'diamond':
                return QPolygonF([
                    QPointF(x_pos, groove.top() + marker_offset_y),
                    QPointF(x_pos - marker_width / 2, groove.top() + marker_offset_y - marker_height / 2),
                    QPointF(x_pos, groove.top() + marker_offset_y - marker_height),
                    QPointF(x_pos + marker_width / 2, groove.top() + marker_offset_y - marker_height / 2),
                ])
            # Default: triangle pointing at groove
            return QPolygonF([
                QPointF(x_pos, groove.top() + marker_offset_y),
                QPointF(x_pos - marker_width / 2, groove.top() + marker_offset_y - marker_height),
                QPointF(x_pos + marker_width / 2, groove.top() + marker_offset_y - marker_height),
            ])

        if self.loop_start is not None:
            pos = self._value_to_position(self.loop_start, groove)
            marker_poly = _build_marker_polygon(pos)
            painter.setPen(QPen(self._marker_outline_color, self._marker_outline_width))
            painter.setBrush(self._marker_start_color)
            painter.drawPolygon(marker_poly)

        if self.loop_end is not None:
            pos = self._value_to_position(self.loop_end, groove)
            marker_poly = _build_marker_polygon(pos)
            painter.setPen(QPen(self._marker_outline_color, self._marker_outline_width))
            painter.setBrush(self._marker_end_color)
            painter.drawPolygon(marker_poly)

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
            # Remember which marker was clicked as the drag anchor
            self._drag_anchor = 'start' if near_start else 'end'
            self.marker_drag_started.emit()
            event.accept()
            return
        elif near_start:
            self._dragging_marker = 'start'
            self.marker_drag_started.emit()
            event.accept()
            return
        elif near_end:
            self._dragging_marker = 'end'
            self.marker_drag_started.emit()
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
                self.marker_preview_frame.emit(new_value)
            elif self._dragging_marker == 'end':
                self.loop_end = new_value
                self.loop_end_changed.emit(new_value)
                self.marker_preview_frame.emit(new_value)
            elif self._dragging_marker == 'both':
                # Move both markers maintaining the gap
                max_val = self.maximum()
                min_val = self.minimum()

                # Calculate new positions based on which marker is the drag anchor
                if self._drag_anchor == 'start':
                    # Mouse follows start marker
                    new_start = max(min_val, min(new_value, max_val - self._marker_gap))
                    new_end = new_start + self._marker_gap
                else:
                    # Mouse follows end marker
                    new_end = max(min_val + self._marker_gap, min(new_value, max_val))
                    new_start = new_end - self._marker_gap

                self.loop_start = new_start
                self.loop_end = new_end
                self.loop_start_changed.emit(new_start)
                self.loop_end_changed.emit(new_end)
                # Preview the marker that's being dragged
                preview_frame = new_start if self._drag_anchor == 'start' else new_end
                self.marker_preview_frame.emit(preview_frame)

            self.update()
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """Handle mouse release."""
        if self._dragging_marker:
            self._dragging_marker = None
            self.marker_drag_ended.emit()
            event.accept()
            return

        super().mouseReleaseEvent(event)


class SpeedSlider(QSlider):
    """Custom speed slider with colored zones and visual dividers."""

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        # Note: range and styling are set by parent VideoControlsWidget

    def paintEvent(self, event):
        """Paint slider with zone dividers."""
        super().paintEvent(event)

        # Draw zone dividers
        painter = QPainter(self)
        if not painter.isActive():
            return

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Get groove rectangle
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        groove = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderGroove, self)

        # Calculate divider positions (at fixed visual percentages to match color zones)
        # Divider 1: at 20% visual position
        divider1_x = groove.left() + groove.width() * 0.2

        # Divider 2: at 50% visual position
        divider2_x = groove.left() + groove.width() * 0.5

        # Draw dividers as thin vertical lines
        pen = QPen(QColor(255, 255, 255), 1)  # White lines, 1px width
        pen.setStyle(Qt.PenStyle.SolidLine)
        painter.setPen(pen)

        painter.drawLine(int(divider1_x), groove.top() + 1, int(divider1_x), groove.bottom())
        painter.drawLine(int(divider2_x), groove.top() + 1, int(divider2_x), groove.bottom())

        painter.end()


class VideoControlsWidget(QWidget):
    """Video playback controls with frame-accurate navigation - overlay widget."""

    # Signals
    play_pause_requested = Signal()
    stop_requested = Signal()
    frame_changed = Signal(int)  # Frame number
    marker_preview_requested = Signal(int)  # Preview frame during marker drag (doesn't move seekbar)
    skip_backward_requested = Signal()  # Skip 1 second backward
    skip_forward_requested = Signal()  # Skip 1 second forward
    loop_start_set = Signal()
    loop_end_set = Signal()
    loop_reset = Signal()
    loop_toggled = Signal(bool)
    speed_changed = Signal(float)  # Playback speed multiplier
    mute_toggled = Signal(bool)  # Mute state (True = muted)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._skin_bg_color = "#242424"
        self._skin_bg_opacity = 0.95
        self._skin_bg_border = "none"
        self._skin_bg_radius = 0

        # Background styling is handled by SkinApplier via stylesheet
        # (Don't use setWindowOpacity - it makes children transparent too)

        # Enable mouse tracking for cursor updates
        self.setMouseTracking(True)

        # Install event filter on parent to catch mouse release outside widget
        if parent:
            parent.installEventFilter(self)

        # For dragging the controls
        self._dragging = False
        self._drag_start_pos = None
        self._drag_has_moved = False

        # For resizing the controls
        self._resizing = False
        self._resize_start_pos = None
        self._resize_start_width = None
        self._resize_start_x = None
        self._resize_handle_width = 10  # Width of resize area on edges
        self._resize_corner_size = 20  # Size of corner resize areas (also resize width only)
        self._height_sync_in_progress = False
        self._stabilize_scheduled = False
        self._overlay_reposition_pending = False
        self._overlay_reposition_in_progress = False
        self._overlay_reposition_retry_count = 0

        # Double-click fit/restore state
        self._fit_mode_active = False
        self._pre_fit_geometry_percent = None
        self._last_position_ui_update_at = 0.0
        self._last_position_text_update_at = 0.0
        self._last_frame_total_display = None
        self._last_time_display = None
        self._perf_profile = 'single'
        self._last_playing_visual_state = None
        self._last_mute_visual_state = None
        self._timeline_scrubbing = False

        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 4, 8, 4)
        main_layout.setSpacing(8)
        self._outer_layout = main_layout

        # Background surface is intentionally separate from component entities, so
        # controls can be offset beyond the visual bar for floating designs.
        self.background_surface = QWidget(self)
        self.background_surface.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.background_surface.setAutoFillBackground(False)
        self.background_surface.lower()


        # Top row: Playback controls + Frame navigation
        self.controls_layout = QHBoxLayout()
        self.controls_layout.setContentsMargins(0, 0, 0, 0)

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

        self.mute_btn = QPushButton('🔇')
        self.mute_btn.setToolTip('Toggle Mute/Unmute')
        self.mute_btn.setMaximumWidth(40)
        self.mute_btn.setStyleSheet("""
            QPushButton {
                background-color: #2b2b2b;
                border: 2px solid #555;
                border-radius: 4px;
                font-size: 18px;
            }
            QPushButton:hover {
                background-color: #3a3a3a;
                border-color: #666;
            }
        """)
        self.mute_btn.clicked.connect(self._toggle_mute)

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
        self.speed_slider = SpeedSlider(Qt.Orientation.Horizontal)
        # Range for slider display (not used for mouse mapping anymore, using non-linear zones)
        self.speed_slider.setMinimum(-200)  # -2.0x
        self.speed_slider.setMaximum(600)   # 6.0x
        self.speed_slider.setValue(200)  # 1.0x at 50% position
        self.speed_slider.setTickInterval(100)  # 1.0x intervals
        self.speed_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.speed_slider.setSingleStep(0)  # Disable keyboard/click increment
        self.speed_slider.setPageStep(0)    # Disable page increment
        self.speed_slider.setMinimumWidth(100)  # Minimum width
        # No maximum width - let it expand to fill available space
        self.speed_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 8px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0.0 #2D5A2D,
                    stop:0.15 #2D5A2D,
                    stop:0.25 #6B8E23,
                    stop:0.45 #6B8E23,
                    stop:0.55 #32CD32,
                    stop:1.0 #32CD32);
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #FFFFFF;
                border: 2px solid #333;
                width: 16px;
                margin: -4px 0;
                border-radius: 8px;
            }
            QSlider::handle:horizontal:hover {
                background: #E0E0E0;
                border: 2px solid #000;
            }
        """)

        # Extended speed tracking for rubberband effect
        self._extended_speed = 1.0  # Actual speed (can be -12.0 to 12.0)
        self._is_dragging_speed = False
        self._last_mouse_pos = None
        self._drag_start_value = 100
        self._skip_next_slider_change = False  # Flag to skip processing next valueChanged signal

        # Gradient color schemes (from user's testcolor.html)
        self._gradient_themes = [
            # Current theme (Volcanic)
            ("#2D5A2D", "#6B8E23", "#32CD32"),
            # Cosmic Drift
            ("#4B0082", "#008080", "#39FF14"),
            # Organic Pulse
            ("#E97451", "#556B2F", "#00FF7F"),
            # Sunburst Rise
            ("#FF4500", "#FFD700", "#ADFF2F"),
            # Twilight Flow
            ("#2F4F4F", "#6A5ACD", "#00CED1"),
            # Ember Surge
            ("#8B0000", "#FF8C00", "#FFFF00"),
            # Aurora Stream
            ("#9400D3", "#00BFFF", "#7FFF00"),
            # Neon Wave
            ("#FF00FF", "#00FFFF", "#00FF00"),
            # Citrus Bloom
            ("#FFA500", "#FFFF66", "#CCFF99"),
            # Storm Fade
            ("#1C1C1C", "#5F9EA0", "#B0C4DE"),
            # Lava Drift
            ("#800000", "#FF6347", "#FFDAB9"),
            # Ice & Fire
            ("#00FFFF", "#FFFFFF", "#FF4500"),
            # Forest Light
            ("#013220", "#228B22", "#7CFC00"),
        ]
        # Load saved theme index from settings
        self._current_theme_index = settings.value('speed_slider_theme_index',
                                                    defaultValue=DEFAULT_SETTINGS['speed_slider_theme_index'],
                                                    type=int)

        # Apply the saved theme to the slider
        self._apply_speed_theme()

        # Install event filter for mouse tracking
        self.speed_slider.installEventFilter(self)

        # Connect slider signals
        self.speed_slider.valueChanged.connect(self._on_speed_slider_changed)
        self.speed_slider.sliderPressed.connect(self._on_speed_slider_pressed)
        self.speed_slider.sliderReleased.connect(self._on_speed_slider_released)

        self.speed_value_label = QLabel('1.00x')
        self.speed_value_label.setMinimumWidth(45)
        self.speed_value_label.setStyleSheet("QLabel { color: #4CAF50; font-weight: bold; }")
        self.speed_value_label.mousePressEvent = self._reset_speed
        self.speed_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.speed_value_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        # Speed label for theme cycling (clicking "Speed:" text)
        self.speed_label.mousePressEvent = self._cycle_speed_theme

        # Independent component slots (ground-up layout model)
        self._component_slots = {}
        self._component_widgets = {}
        self._slot_managed_components = {'speed_label', 'speed_slider', 'speed_value_label'}
        self._component_slot_rows = {}
        self._component_slot_stretch = {}
        self._component_slot_base_size = {}

        self.controls_content_layout = QHBoxLayout()
        self.controls_content_layout.setContentsMargins(0, 0, 0, 0)
        self.controls_content_layout.setSpacing(8)

        self._top_row_button_map = {
            'play_button': self._create_component_slot('play_button', self.play_pause_btn, 'controls_row'),
            'stop_button': self._create_component_slot('stop_button', self.stop_btn, 'controls_row'),
            'mute_button': self._create_component_slot('mute_button', self.mute_btn, 'controls_row'),
            'skip_back_button': self._create_component_slot('skip_back_button', self.skip_back_btn, 'controls_row'),
            'prev_frame_button': self._create_component_slot('prev_frame_button', self.prev_frame_btn, 'controls_row'),
            'next_frame_button': self._create_component_slot('next_frame_button', self.next_frame_btn, 'controls_row'),
            'skip_forward_button': self._create_component_slot('skip_forward_button', self.skip_forward_btn, 'controls_row'),
        }
        self._top_row_button_default_order = list(self._top_row_button_map.keys())

        self._controls_non_button_slots = {
            'frame_label': self._create_component_slot('frame_label', self.frame_label, 'controls_row'),
            'frame_spinbox': self._create_component_slot('frame_spinbox', self.frame_spinbox, 'controls_row'),
            'frame_total_label': self._create_component_slot('frame_total_label', self.frame_total_label, 'controls_row'),
            'speed_label': self._create_component_slot('speed_label', self.speed_label, 'controls_row'),
            'speed_slider': self._create_component_slot('speed_slider', self.speed_slider, 'controls_row', stretch=1),
            'speed_value_label': self._create_component_slot('speed_value_label', self.speed_value_label, 'controls_row'),
        }
        self._rebuild_top_controls_content()

        # Alignment spacers around controls content
        self.controls_layout.addStretch(1)
        self.controls_left_spacer_index = self.controls_layout.count() - 1
        self.controls_layout.addLayout(self.controls_content_layout)
        self.controls_layout.addStretch(1)
        self.controls_right_spacer_index = self.controls_layout.count() - 1

        # Timeline slider with loop markers
        self.slider_layout = QHBoxLayout()
        self.timeline_slider = LoopSlider(Qt.Orientation.Horizontal)
        self.timeline_slider.setMinimum(0)
        self.timeline_slider.setMaximum(0)
        self.timeline_slider.valueChanged.connect(self._slider_changed)
        self.timeline_slider.sliderPressed.connect(self._on_timeline_slider_pressed)
        self.timeline_slider.sliderReleased.connect(self._on_timeline_slider_released)
        # Connect marker dragging signals
        self.timeline_slider.loop_start_changed.connect(self._on_loop_start_dragged)
        self.timeline_slider.loop_end_changed.connect(self._on_loop_end_dragged)
        # Connect marker preview signals
        self.timeline_slider.marker_drag_started.connect(self._on_marker_drag_started)
        self.timeline_slider.marker_drag_ended.connect(self._on_marker_drag_ended)
        self.timeline_slider.marker_preview_frame.connect(self._on_marker_preview_frame)
        self.slider_layout.addWidget(
            self._create_component_slot('timeline_slider', self.timeline_slider, 'timeline_row', stretch=1),
            1,
        )

        # Bottom row: Info display + Loop controls
        self.info_layout = QHBoxLayout()

        # Time display
        self.time_label = QLabel('00:00.000 / 00:00.000')
        self.time_label.setMinimumWidth(150)

        # FPS display
        self.fps_label = QLabel('0.00 fps')
        self.fps_label.setMinimumWidth(80)

        # Frame count display
        self.frame_count_label = QLabel('0 frames')
        self.frame_count_label.setMinimumWidth(80)

        # Combined preview labels container
        self.preview_labels_layout = QVBoxLayout()
        self.preview_labels_layout.setSpacing(0)
        self.preview_labels_layout.setContentsMargins(0, 0, 0, 0)

        # Container widget to constrain the preview layout
        self.preview_container = QWidget()
        self.preview_container.setLayout(self.preview_labels_layout)
        self.preview_container.setMaximumWidth(300)  # Limit width to prevent over-expansion

        # Marker range frame count display
        self.marker_range_label = QLabel('')
        self.marker_range_label.setStyleSheet("QLabel { color: #4CAF50; font-weight: bold; font-size: 9px; }")


        # SAR warning indicator (only shown for non-square pixel videos)
        self.sar_warning_label = QLabel('')
        self.sar_warning_label.setStyleSheet("QLabel { color: #FF5722; font-weight: bold; }")
        self.sar_warning_label.setToolTip('Video has non-square pixels (SAR != 1:1)\nMay cause issues with training tools that ignore SAR')
        self.sar_warning_label.hide()  # Hide by default, only show when SAR != 1:1

        # Speed preview label (shows what would happen if speed is applied)
        self.speed_preview_label = QLabel('')
        self.speed_preview_label.setStyleSheet("QLabel { color: #2196F3; font-weight: bold; font-size: 9px; }")
        self.speed_preview_label.setToolTip('Preview of video if speed change is applied. Click to set custom FPS.')
        self.speed_preview_label.mousePressEvent = self._on_preview_label_clicked

        # Loop controls - smaller buttons with text labels
        self.loop_start_btn = QPushButton('◀')  # Triangle pointing left/down
        self.loop_start_btn.setToolTip('Set Loop Start at current frame (Pink marker)')
        self.loop_start_btn.setMaximumWidth(30)
        # Style will be applied by apply_current_skin() after skin_manager is initialized
        self.loop_start_btn.clicked.connect(self._set_loop_start)

        self.loop_end_btn = QPushButton('▶')  # Triangle pointing right/down
        self.loop_end_btn.setToolTip('Set Loop End at current frame (Orange marker)')
        self.loop_end_btn.setMaximumWidth(30)
        # Style will be applied by apply_current_skin() after skin_manager is initialized
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

        self.info_layout.addWidget(self._create_component_slot('time_label', self.time_label, 'info_row'))
        self.info_layout.addWidget(self._create_component_slot('fps_label', self.fps_label, 'info_row'))
        self.info_layout.addWidget(self._create_component_slot('frame_count_label', self.frame_count_label, 'info_row'))
        self.info_layout.addStretch(1)
        self.info_layout.addWidget(self._create_component_slot('preview_container', self.preview_container, 'info_row'))
        self.info_layout.addStretch(1)
        self.info_layout.addWidget(self._create_component_slot('sar_warning_label', self.sar_warning_label, 'info_row'))
        self.info_layout.addWidget(self._create_component_slot('loop_reset_button', self.loop_reset_btn, 'info_row'))
        self.info_layout.addWidget(self._create_component_slot('loop_start_button', self.loop_start_btn, 'info_row'))
        self.info_layout.addWidget(self._create_component_slot('loop_end_button', self.loop_end_btn, 'info_row'))
        self.info_layout.addWidget(self._create_component_slot('loop_checkbox', self.loop_checkbox, 'info_row'))

        # Add all layouts to main
        self.main_layout = main_layout
        self.main_layout.addLayout(self.controls_layout)
        self.main_layout.addLayout(self.slider_layout)
        self.main_layout.addLayout(self.info_layout)

        # Track current state
        self.is_playing = False
        self._updating_slider = False

        # Current image and model reference for persistence
        self.current_image = None
        self.proxy_image_list_model = None
        self._loop_persistence_scope = 'main'

        # Loop state
        self.loop_start_frame = None
        self.loop_end_frame = None
        self.is_looping = False

        # Fixed marker size (set from main window)
        self.fixed_marker_size = 31

        # Auto-play state (persists across video changes and reboots)
        self.auto_play_enabled = settings.value('video_auto_play', defaultValue=False, type=bool)

        # Mute state (persists across video changes and reboots)
        self.is_muted = settings.value('video_muted', defaultValue=True, type=bool)

        # Video metadata for speed preview calculations
        self._current_fps = 0
        self._current_frame_count = 0
        self._current_duration = 0
        self._custom_preview_fps = None  # User can override FPS for preview

        # Marker preview state
        self._in_marker_preview = False  # True when dragging a marker
        self._preview_restore_frame = None  # Frame to restore to after preview ends
        self._was_playing_before_preview = False  # Store play state to restore after preview
        self._was_playing_before_scrub = False

        # Load persistent settings
        self._load_persistent_settings()

        # Initialize mute button appearance
        self._update_mute_button()

        # Initialize skin system
        self.skin_manager = SkinManager()
        # Load saved skin or default
        saved_skin = settings.value('video_player_skin', defaultValue='Classic', type=str)
        if not self.skin_manager.load_skin(saved_skin):
            # Fallback to first available skin
            self.skin_manager.load_default_skin()
        # Apply skin to all widgets
        self.apply_current_skin()

        # Hide by default
        self.hide()

    def _floating_bleed(self) -> int:
        """Extra empty area around the visual bar used for floating controls."""
        if not hasattr(self, 'skin_manager') or not getattr(self.skin_manager, 'current_skin', None):
            return 80
        designer_layout = self.skin_manager.current_skin.get('video_player', {}).get('designer_layout', {})
        if not isinstance(designer_layout, dict):
            return 80
        bleed = designer_layout.get('floating_bleed', 0)
        try:
            bleed = int(bleed)
        except (TypeError, ValueError):
            bleed = 80
        return max(0, min(200, bleed))

    def _refresh_background_surface(self):
        """Apply current skin background to the dedicated visual surface widget."""
        if not hasattr(self, 'background_surface'):
            return
        qcolor = QColor(str(getattr(self, '_skin_bg_color', '#242424')))
        opacity = max(0.0, min(1.0, float(getattr(self, '_skin_bg_opacity', 0.95))))
        qcolor.setAlphaF(opacity)
        rgba = f"rgba({qcolor.red()}, {qcolor.green()}, {qcolor.blue()}, {qcolor.alpha()})"
        border = str(getattr(self, '_skin_bg_border', 'none'))
        radius = int(getattr(self, '_skin_bg_radius', 0))
        self.background_surface.setStyleSheet(
            f"QWidget {{ background-color: {rgba}; border: {border}; border-radius: {radius}px; }}"
        )
        self._update_background_surface_geometry()

    def _update_background_surface_geometry(self):
        """Keep background rectangle inset from floating area."""
        if not hasattr(self, 'background_surface'):
            return
        bleed = self._floating_bleed()
        rect = self.rect().adjusted(bleed, bleed, -bleed, -bleed)
        if rect.width() < 1 or rect.height() < 1:
            self.background_surface.hide()
            return
        self.background_surface.setGeometry(rect)
        self.background_surface.lower()
        self.background_surface.show()
        self._update_component_overlay_geometry()

    def _update_component_overlay_geometry(self):
        """Keep overlay synced with player bounds and above background."""
        # Overlay layer removed; components are parented directly to self.
        return

    def _qt_widget_alive(self, widget) -> bool:
        """Best-effort liveness check for wrapped Qt objects."""
        if widget is None:
            return False
        if _shiboken_is_valid is not None:
            try:
                if not _shiboken_is_valid(widget):
                    return False
            except Exception:
                return False
        try:
            widget.objectName()
        except RuntimeError:
            return False
        except Exception:
            pass
        return True

    def _schedule_overlay_reposition(self, delay_ms: int = 0):
        """Queue one overlay reposition pass (deduped) to avoid event-loop spin."""
        if not self._qt_widget_alive(self):
            return
        if self._overlay_reposition_pending:
            return
        self._overlay_reposition_pending = True

        from PySide6.QtCore import QTimer

        def _run():
            self._overlay_reposition_pending = False
            if not self._qt_widget_alive(self):
                return
            self._reposition_component_overlays()

        QTimer.singleShot(max(0, int(delay_ms)), _run)

    def _reposition_component_overlays(self):
        """Position real component widgets from anchor slot geometry."""
        if not self._qt_widget_alive(self):
            return
        if self._overlay_reposition_in_progress:
            return
        try:
            if not self.isVisible():
                self._overlay_reposition_retry_count = 0
                return
        except RuntimeError:
            return
        self._overlay_reposition_in_progress = True
        try:
            self._update_component_overlay_geometry()
        except RuntimeError:
            self._overlay_reposition_in_progress = False
            return
        invalid_anchor_found = False
        try:
            for component_id in list(self._component_slots.keys()):
                slot = self._component_slots.get(component_id)
                widget = self._component_widgets.get(component_id)
                if widget is None or slot is None:
                    continue
                if (not self._qt_widget_alive(slot)) or (not self._qt_widget_alive(widget)):
                    self._component_slots.pop(component_id, None)
                    self._component_widgets.pop(component_id, None)
                    continue
                if component_id in self._slot_managed_components:
                    continue

                try:
                    cfg = self._get_component_layout(component_id)
                except RuntimeError:
                    self._component_slots.pop(component_id, None)
                    self._component_widgets.pop(component_id, None)
                    continue
                align = str(cfg.get('align', 'center')).lower()
                requested_container_width = int(cfg.get('container_width', 0))
                offset_x = max(-240, min(240, int(cfg.get('offset_x', 0))))
                offset_y = max(-180, min(180, int(cfg.get('offset_y', 0))))
                try:
                    anchor = slot.geometry()
                except RuntimeError:
                    # Qt object was deleted; drop stale registry entries safely.
                    self._component_slots.pop(component_id, None)
                    self._component_widgets.pop(component_id, None)
                    continue
                if anchor.width() <= 0 or anchor.height() <= 0:
                    # Speed slider fallback anchor derived from Speed: and 1.00x labels.
                    if component_id == 'speed_slider':
                        try:
                            left_ref = self.speed_label.geometry()
                            right_ref = self.speed_value_label.geometry()
                        except RuntimeError:
                            invalid_anchor_found = True
                            continue
                        if left_ref.isValid() and right_ref.isValid() and right_ref.left() > left_ref.right():
                            anchor = left_ref
                            anchor.setLeft(left_ref.right() + 6)
                            anchor.setRight(right_ref.left() - 6)
                        else:
                            invalid_anchor_found = True
                            continue
                    else:
                        invalid_anchor_found = True
                        continue

                try:
                    hint = widget.sizeHint()
                except RuntimeError:
                    self._component_widgets.pop(component_id, None)
                    continue
                width = max(8, int(hint.width()))
                height = max(8, int(hint.height()))

                try:
                    max_w = int(widget.maximumWidth())
                    max_h = int(widget.maximumHeight())
                    min_w = int(widget.minimumWidth())
                    min_h = int(widget.minimumHeight())
                except RuntimeError:
                    self._component_widgets.pop(component_id, None)
                    continue

                if 0 < max_w < 16777215:
                    width = max_w
                if 0 < max_h < 16777215:
                    height = max_h
                width = max(width, max(0, min_w))
                height = max(height, max(0, min_h))

                if component_id == 'speed_slider':
                    if requested_container_width > 0:
                        width = max(20, requested_container_width)
                    else:
                        width = max(20, anchor.width())
                elif component_id == 'timeline_slider':
                    width = max(20, anchor.width())

                if component_id in ('speed_label', 'speed_value_label'):
                    # Speed text/value are anchored by dedicated slots.
                    x = anchor.left()
                    y = anchor.top()
                    width = anchor.width()
                    height = anchor.height()
                    offset_x = 0
                    offset_y = 0
                elif component_id == 'speed_slider':
                    # Slider is laid out in a dedicated lane between speed label and value.
                    x = anchor.left()
                    offset_x = 0
                elif component_id == 'timeline_slider':
                    x = anchor.left()
                elif align == 'left':
                    x = anchor.left()
                elif align == 'right':
                    x = anchor.right() - width + 1
                else:
                    x = anchor.left() + (anchor.width() - width) // 2
                y = anchor.top() + (anchor.height() - height) // 2

                # Prevent narrow-width overlap: keep text-like widgets inside their anchor lane.
                if component_id in (
                    'frame_label',
                    'frame_spinbox',
                    'frame_total_label',
                    'time_label',
                    'fps_label',
                    'frame_count_label',
                    'speed_label',
                    'speed_value_label',
                    'loop_checkbox',
                ):
                    width = min(width, max(8, anchor.width()))
                    height = min(height, max(8, anchor.height()))
                    if align == 'right':
                        x = anchor.right() - width + 1
                    elif align == 'left':
                        x = anchor.left()
                    else:
                        x = anchor.left() + (anchor.width() - width) // 2
                    y = anchor.top() + (anchor.height() - height) // 2

                try:
                    widget.setGeometry(int(x + offset_x), int(y + offset_y), int(width), int(height))
                except RuntimeError:
                    self._component_widgets.pop(component_id, None)
                    continue
                # Avoid forcing show/raise during rapid rebuilds; visibility is managed
                # by skin/layout logic and explicit compact/nano mode rules.
        finally:
            self._overlay_reposition_in_progress = False

        try:
            should_retry = bool(invalid_anchor_found and self._qt_widget_alive(self) and self.isVisible())
        except RuntimeError:
            should_retry = False
        if should_retry:
            if self._overlay_reposition_retry_count < 12:
                self._overlay_reposition_retry_count += 1
                self._schedule_overlay_reposition(16)
        else:
            self._overlay_reposition_retry_count = 0

    def _create_component_slot(self, component_id: str, widget: QWidget, row_key: str, stretch: int = 0) -> QWidget:
        """Create an anchor slot and attach real widget to overlay for free positioning."""
        slot = QWidget(self)
        slot.setAutoFillBackground(False)
        slot.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        if stretch > 0:
            slot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        else:
            slot.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        if component_id in self._slot_managed_components:
            slot_layout = QHBoxLayout(slot)
            slot_layout.setContentsMargins(0, 0, 0, 0)
            slot_layout.setSpacing(0)
            if component_id == 'speed_label':
                slot_layout.addStretch(1)
                slot_layout.addWidget(widget)
            elif component_id == 'speed_value_label':
                slot_layout.addWidget(widget)
                slot_layout.addStretch(1)
            else:
                slot_layout.addWidget(widget, 1)
            widget.setParent(slot)
        else:
            widget.setParent(self)
        widget.show()

        self._component_slots[component_id] = slot
        self._component_widgets[component_id] = widget
        self._component_slot_rows[component_id] = row_key
        self._component_slot_stretch[component_id] = int(stretch)
        self._component_slot_base_size[component_id] = {
            "min_w": int(widget.minimumWidth()),
            "max_w": int(widget.maximumWidth()),
            "min_h": int(widget.minimumHeight()),
            "max_h": int(widget.maximumHeight()),
        }
        return slot

    def _rebuild_top_controls_content(self):
        """Rebuild top-row order while preserving individual component slots."""
        while self.controls_content_layout.count():
            self.controls_content_layout.takeAt(0)

        for component_id in self._top_row_button_default_order:
            slot = self._top_row_button_map.get(component_id)
            if slot:
                self.controls_content_layout.addWidget(slot)

        self.controls_content_layout.addWidget(self._controls_non_button_slots['frame_label'])
        self.controls_content_layout.addWidget(self._controls_non_button_slots['frame_spinbox'])
        self.controls_content_layout.addWidget(self._controls_non_button_slots['frame_total_label'])
        self.controls_content_layout.addWidget(self._controls_non_button_slots['speed_label'])
        self.controls_content_layout.addWidget(
            self._controls_non_button_slots['speed_slider'],
            self._component_slot_stretch.get('speed_slider', 1),
        )
        self.controls_content_layout.addWidget(self._controls_non_button_slots['speed_value_label'])

    def _component_style_value(self, component_id: str, key: str, default):
        """Resolve style value using component override fallback to global styling."""
        skin = getattr(self.skin_manager, 'current_skin', {}) if hasattr(self, 'skin_manager') else {}
        vp = skin.get('video_player', {}) if isinstance(skin, dict) else {}
        component_styles = vp.get('component_styles', {})
        if isinstance(component_styles, dict):
            block = component_styles.get(component_id, {})
            if isinstance(block, dict):
                state_block = block.get('default', {})
                if isinstance(state_block, dict) and key in state_block:
                    return state_block[key]
        styling = vp.get('styling', {})
        if isinstance(styling, dict) and key in styling:
            return styling.get(key)
        return default

    def _get_component_layout(self, component_id: str) -> dict:
        defaults = {
            # Keep speed trio visually grouped by default.
            'speed_label': {'align': 'right', 'container_width': 64},
            'speed_slider': {'align': 'center', 'container_width': 0},
            'speed_value_label': {'align': 'left', 'container_width': 64},
            'frame_spinbox': {'align': 'center', 'container_width': 86},
            'frame_total_label': {'align': 'left', 'container_width': 64},
            'loop_reset_button': {'container_width': 44},
            'loop_start_button': {'container_width': 44},
            'loop_end_button': {'container_width': 44},
            'loop_checkbox': {'container_width': 72},
        }
        skin = getattr(self.skin_manager, 'current_skin', {}) if hasattr(self, 'skin_manager') else {}
        vp = skin.get('video_player', {}) if isinstance(skin, dict) else {}
        designer_layout = vp.get('designer_layout', {}) if isinstance(vp, dict) else {}
        if not isinstance(designer_layout, dict):
            return dict(defaults.get(component_id, {}))
        component_layouts = designer_layout.get('component_layouts', {})
        if not isinstance(component_layouts, dict):
            return dict(defaults.get(component_id, {}))
        layout = component_layouts.get(component_id, {})
        merged = dict(defaults.get(component_id, {}))
        if isinstance(layout, dict):
            merged.update(layout)
        try:
            scale_value = float(merged.get('scale', 1.0))
        except (TypeError, ValueError):
            scale_value = 1.0
        # Keep runtime responsive: avoid pathological per-component scaling
        # values that can explode layout costs during playback updates.
        scale_value = max(0.25, min(2.0, scale_value))
        if component_id == 'speed_slider':
            scale_value = min(1.45, scale_value)
        merged['scale'] = scale_value

        for key in ('container_width', 'container_height', 'offset_x', 'offset_y'):
            if key in merged:
                try:
                    merged[key] = int(merged.get(key, 0))
                except (TypeError, ValueError):
                    merged[key] = 0
        merged['container_width'] = max(0, min(900, merged.get('container_width', 0)))
        merged['container_height'] = max(0, min(300, merged.get('container_height', 0)))
        if component_id in ('speed_label', 'speed_value_label'):
            try:
                cw = int(merged.get('container_width', 0))
            except (TypeError, ValueError):
                cw = 0
            if cw <= 0:
                merged['container_width'] = 58
        return merged

    def _load_persistent_settings(self):
        """Load persistent settings from config."""
        # Load loop enabled state
        loop_enabled = settings.value('video_loop_enabled', False, type=bool)
        # Block signals temporarily to avoid emission during init
        self.loop_checkbox.blockSignals(True)
        self.loop_checkbox.setChecked(loop_enabled)
        self.loop_checkbox.blockSignals(False)
        # Set internal state (signal will be emitted when video loads)
        self.is_looping = loop_enabled

    def set_loop_persistence_scope(self, scope: str | None):
        """Set metadata scope key used for loop marker persistence."""
        normalized_scope = str(scope).strip() if scope else 'main'
        self._loop_persistence_scope = normalized_scope or 'main'

    def _resolve_loop_markers_for_scope(self, image, max_frame: int) -> tuple[int | None, int | None]:
        """Resolve loop markers for current scope with backward-compatible fallback."""
        if image is None:
            return (None, None)

        def _valid_pair(start, end):
            return (
                isinstance(start, int)
                and isinstance(end, int)
                and start >= 0
                and end >= 0
            )

        scope = getattr(self, '_loop_persistence_scope', 'main')
        viewer_markers = getattr(image, 'viewer_loop_markers', {})

        # Main viewer keeps legacy fields as authoritative for compatibility.
        legacy_start = getattr(image, 'loop_start_frame', None)
        legacy_end = getattr(image, 'loop_end_frame', None)
        if scope == 'main' and _valid_pair(legacy_start, legacy_end):
            return (legacy_start, legacy_end)

        if isinstance(viewer_markers, dict):
            scoped = viewer_markers.get(scope)
            if isinstance(scoped, dict):
                scoped_start = scoped.get('loop_start_frame')
                scoped_end = scoped.get('loop_end_frame')
                if _valid_pair(scoped_start, scoped_end):
                    return (scoped_start, scoped_end)

        # Floating viewers fallback to the last floating markers saved for this media.
        if scope != 'main' and isinstance(viewer_markers, dict):
            floating_last = viewer_markers.get('floating_last')
            if isinstance(floating_last, dict):
                last_start = floating_last.get('loop_start_frame')
                last_end = floating_last.get('loop_end_frame')
                if _valid_pair(last_start, last_end):
                    return (last_start, last_end)

        if _valid_pair(legacy_start, legacy_end):
            return (legacy_start, legacy_end)

        if scope != 'main' and isinstance(viewer_markers, dict):
            main_scoped = viewer_markers.get('main')
            if isinstance(main_scoped, dict):
                main_start = main_scoped.get('loop_start_frame')
                main_end = main_scoped.get('loop_end_frame')
                if _valid_pair(main_start, main_end):
                    return (main_start, main_end)

            # Last-resort: if only one floating scope exists, use it.
            floating_ranges = []
            for key, values in viewer_markers.items():
                if key in ('main', 'floating_last') or not isinstance(values, dict):
                    continue
                range_start = values.get('loop_start_frame')
                range_end = values.get('loop_end_frame')
                if _valid_pair(range_start, range_end):
                    floating_ranges.append((range_start, range_end))
            if len(floating_ranges) == 1:
                return floating_ranges[0]

        return (None, None)

    def apply_current_skin(self):
        """Apply current skin to all video control widgets.

        This method is called:
        - On initialization
        - When user switches skins (live update, no restart needed)
        """
        applier = self.skin_manager.get_current_applier()
        if not applier:
            return

        # Apply to control bar container (this widget)
        applier.apply_to_control_bar(self)
        self._apply_skin_layout_properties(applier)

        # Apply to all buttons (with canonical component ids)
        button_map = {
            'play_button': self.play_pause_btn,
            'stop_button': self.stop_btn,
            'mute_button': self.mute_btn,
            'prev_frame_button': self.prev_frame_btn,
            'next_frame_button': self.next_frame_btn,
            'skip_back_button': self.skip_back_btn,
            'skip_forward_button': self.skip_forward_btn,
            'loop_start_button': self.loop_start_btn,
            'loop_end_button': self.loop_end_btn,
            'loop_reset_button': self.loop_reset_btn,
            'loop_checkbox': self.loop_checkbox,
        }
        for component_id, button in button_map.items():
            applier.apply_to_button(button, component_id=component_id)

        # Apply to timeline slider
        applier.apply_to_timeline_slider(self.timeline_slider, component_id='timeline_slider')

        # Apply to speed slider
        applier.apply_to_speed_slider(self.speed_slider, component_id='speed_slider')

        # Apply to labels
        label_map = {
            'frame_label': self.frame_label,
            'frame_total_label': self.frame_total_label,
            'time_label': self.time_label,
            'fps_label': self.fps_label,
            'frame_count_label': self.frame_count_label,
            'speed_label': self.speed_label,
        }
        for component_id, label in label_map.items():
            applier.apply_to_label(label, component_id=component_id)

        # Apply special styling to speed value label
        applier.apply_to_label(
            self.speed_value_label,
            component_id='speed_value_label',
            is_secondary=False
        )

        # Update loop marker colors
        marker_colors = applier.get_loop_marker_colors()
        self.timeline_slider.set_marker_colors(marker_colors)

        # Apply designer position offsets (if any)
        self.apply_designer_positions()

        # Keep layout/entity scaling synced with newly applied skin values.
        self._apply_scaling()
        self._schedule_layout_settle_reflow()

        # Force repaint
        self.update()

    def _apply_skin_layout_properties(self, applier):
        """Apply layout-related skin values to runtime Qt layouts."""
        designer_layout = self.skin_manager.current_skin.get('video_player', {}).get('designer_layout', {})
        controls_row = designer_layout.get('controls_row', {}) if isinstance(designer_layout, dict) else {}
        timeline_row = designer_layout.get('timeline_row', {}) if isinstance(designer_layout, dict) else {}
        info_row = designer_layout.get('info_row', {}) if isinstance(designer_layout, dict) else {}

        button_spacing = max(0, int(applier.get_button_spacing()))
        section_spacing = max(0, int(applier.get_section_spacing()))
        button_alignment = applier.layout.get('button_alignment', 'center')
        timeline_position = applier.layout.get('timeline_position', 'above')
        control_bar_height = max(40, int(applier.get_control_bar_height()))

        if isinstance(controls_row, dict):
            if 'button_spacing' in controls_row:
                button_spacing = max(0, int(controls_row.get('button_spacing', button_spacing)))
            if 'section_spacing' in controls_row:
                section_spacing = max(0, int(controls_row.get('section_spacing', section_spacing)))
            if 'button_alignment' in controls_row:
                button_alignment = controls_row.get('button_alignment', button_alignment)
            if 'timeline_position' in controls_row:
                timeline_position = controls_row.get('timeline_position', timeline_position)
            self._apply_top_row_button_order(controls_row.get('button_order'))
        offset_x = 0
        offset_y = 0
        if isinstance(controls_row, dict):
            offset_x = int(controls_row.get('offset_x', 0))
            offset_y = int(controls_row.get('offset_y', 0))
        offset_x = max(-500, min(500, offset_x))
        offset_y = max(-200, min(200, offset_y))
        timeline_offset_x = int(timeline_row.get('offset_x', 0)) if isinstance(timeline_row, dict) else 0
        timeline_offset_y = int(timeline_row.get('offset_y', 0)) if isinstance(timeline_row, dict) else 0
        info_offset_x = int(info_row.get('offset_x', 0)) if isinstance(info_row, dict) else 0
        info_offset_y = int(info_row.get('offset_y', 0)) if isinstance(info_row, dict) else 0
        timeline_offset_x = max(-500, min(500, timeline_offset_x))
        timeline_offset_y = max(-200, min(200, timeline_offset_y))
        info_offset_x = max(-500, min(500, info_offset_x))
        info_offset_y = max(-200, min(200, info_offset_y))

        responsive_scale = float(getattr(self, '_responsive_scale_factor', 1.0))
        responsive_scale = max(0.45, min(1.0, responsive_scale))
        scaled_button_spacing = max(2, int(round(button_spacing * responsive_scale)))
        scaled_section_spacing = max(2, int(round(section_spacing * responsive_scale)))

        # Per-component spacing in top/info/timeline rows
        self.controls_content_layout.setSpacing(scaled_button_spacing)
        self.info_layout.setSpacing(scaled_button_spacing)
        self.slider_layout.setSpacing(scaled_button_spacing)

        # Inter-row spacing
        self.controls_layout.setSpacing(scaled_section_spacing)

        # Section alignment in controls row
        # left: [content...............]
        # center: [....content....]
        # right: [...............content]
        if button_alignment == 'left':
            self.controls_layout.setStretch(self.controls_left_spacer_index, 0)
            self.controls_layout.setStretch(self.controls_right_spacer_index, 100)
        elif button_alignment == 'right':
            self.controls_layout.setStretch(self.controls_left_spacer_index, 100)
            self.controls_layout.setStretch(self.controls_right_spacer_index, 0)
        else:
            self.controls_layout.setStretch(self.controls_left_spacer_index, 1)
            self.controls_layout.setStretch(self.controls_right_spacer_index, 1)

        # Explicit row offset from designer (positive -> move right, negative -> move left).
        self.controls_layout.setContentsMargins(
            max(0, offset_x),
            max(0, offset_y),
            max(0, -offset_x),
            max(0, -offset_y),
        )
        self.slider_layout.setContentsMargins(
            max(0, timeline_offset_x),
            max(0, timeline_offset_y),
            max(0, -timeline_offset_x),
            max(0, -timeline_offset_y),
        )
        self.info_layout.setContentsMargins(
            max(0, info_offset_x),
            max(0, info_offset_y),
            max(0, -info_offset_x),
            max(0, -info_offset_y),
        )

        self._apply_component_layout_properties()

        # Timeline position (supported: above/below, integrated falls back to above)
        if timeline_position == 'below':
            self._set_main_row_order('controls_info_timeline')
        else:
            self._set_main_row_order('controls_timeline_info')

        # Keep the bar comfortably sized without hard-fixing height.
        self.setMinimumHeight(control_bar_height + (self._floating_bleed() * 2))

    def _apply_component_layout_properties(self):
        """Apply per-component container alignment/offset/size in slots."""
        responsive_scale = float(getattr(self, '_responsive_scale_factor', 1.0))
        responsive_scale = max(0.45, min(1.0, responsive_scale))
        for component_id, slot in self._component_slots.items():
            cfg = self._get_component_layout(component_id)
            widget = self._component_widgets.get(component_id)
            container_width = int(cfg.get('container_width', 0))
            is_full_width_timeline = component_id == 'timeline_slider'
            is_speed_slider = component_id == 'speed_slider'
            container_height = int(cfg.get('container_height', 0))
            is_visible = bool(widget and widget.isVisible())
            hint_w = int(widget.sizeHint().width()) if (widget and is_visible) else 0
            hint_h = int(widget.sizeHint().height()) if (widget and is_visible) else 0
            min_lane_w = 12 if is_visible else 0
            min_lane_h = 12 if is_visible else 0

            # Fully collapse hidden component slots so compact modes can truly shrink.
            if not is_visible:
                slot.setFixedWidth(0)
                slot.setFixedHeight(0)
                continue

            if is_full_width_timeline or is_speed_slider:
                slot.setMinimumWidth(0)
                slot.setMaximumWidth(16777215)
                slot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            elif container_width > 0:
                scaled_w = int(round(container_width * responsive_scale))
                slot.setFixedWidth(max(12, min(900, scaled_w)))
            else:
                slot.setMinimumWidth(max(min_lane_w, hint_w))
                slot.setMaximumWidth(16777215)
            if container_height > 0:
                scaled_h = int(round(container_height * responsive_scale))
                slot.setFixedHeight(max(12, min(300, scaled_h)))
            else:
                slot.setMinimumHeight(max(min_lane_h, hint_h))
                slot.setMaximumHeight(16777215)

        self._reposition_component_overlays()

    def _clear_layout(self, layout):
        """Detach all widgets/items from a layout."""
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if child_layout is not None:
                self._clear_layout(child_layout)
            if widget is not None:
                widget.setParent(self)

    def _apply_top_row_button_order(self, requested_order):
        """Apply deterministic ordering for the top-row transport buttons."""
        default_order = list(self._top_row_button_map.keys())
        if not isinstance(requested_order, list):
            requested_order = list(default_order)
        normalized = [name for name in requested_order if name in self._top_row_button_map]
        for name in default_order:
            if name not in normalized:
                normalized.append(name)
        self._top_row_button_default_order = normalized
        self._rebuild_top_controls_content()

    def _set_main_row_order(self, mode: str):
        """Reorder main rows safely when timeline position changes."""
        if getattr(self, '_main_row_mode', None) == mode:
            return

        while self.main_layout.count():
            self.main_layout.takeAt(0)

        if mode == 'controls_info_timeline':
            self.main_layout.addLayout(self.controls_layout)
            self.main_layout.addLayout(self.info_layout)
            self.main_layout.addLayout(self.slider_layout)
        else:
            self.main_layout.addLayout(self.controls_layout)
            self.main_layout.addLayout(self.slider_layout)
            self.main_layout.addLayout(self.info_layout)

        self._main_row_mode = mode
        self._reposition_component_overlays()

    def _schedule_layout_settle_reflow(self):
        """Re-run positioning after Qt finishes the current layout pass."""
        from PySide6.QtCore import QTimer
        self._schedule_overlay_reposition(0)
        QTimer.singleShot(0, self._update_background_surface_geometry)
        QTimer.singleShot(0, self._sync_height_to_content)

    def _stabilize_after_geometry_change(self):
        """Schedule one deferred layout stabilization pass."""
        from PySide6.QtCore import QTimer
        if self._stabilize_scheduled:
            return
        self._stabilize_scheduled = True

        def _pass():
            self._stabilize_scheduled = False
            if not self.isVisible():
                return
            self._apply_scaling()
            self._sync_height_to_content()
            self._schedule_layout_settle_reflow()

        QTimer.singleShot(0, _pass)

    def _sync_height_to_content(self):
        """Keep widget height aligned to current content/layout while preserving width."""
        if self._height_sync_in_progress or self._resizing:
            return
        self._height_sync_in_progress = True
        try:
            current_width = max(self.minimum_runtime_width(), self.width())
            self.layout().invalidate()
            self.layout().activate()
            target_height = max(self.minimumHeight(), self.sizeHint().height())
            if abs(self.height() - target_height) > 1:
                self.resize(current_width, target_height)
            self._update_background_surface_geometry()
            self._reposition_component_overlays()
        finally:
            self._height_sync_in_progress = False

    def apply_designer_positions(self):
        """Apply designer position offsets to widgets from skin data.

        Legacy absolute positioning is now non-destructive:
        - Layout-owned widgets are not detached from Qt layouts.
        - Absolute positions are only applied to free widgets (if any).
        """
        if not hasattr(self, 'skin_manager') or not self.skin_manager.current_skin:
            return

        designer_positions = self.skin_manager.current_skin.get('designer_positions', {})
        if not designer_positions:
            return

        # Map property names to actual widgets
        widget_map = {
            'play_button': self.play_pause_btn,
            'stop_button': self.stop_btn,
            'mute_button': self.mute_btn,
            'prev_frame_button': self.prev_frame_btn,
            'next_frame_button': self.next_frame_btn,
            'skip_back_button': self.skip_back_btn,
            'skip_forward_button': self.skip_forward_btn,
            'loop_start_button': self.loop_start_btn,
            'loop_end_button': self.loop_end_btn,
            'loop_reset_button': self.loop_reset_btn,
            'loop_checkbox': self.loop_checkbox,
            'frame_label': self.frame_label,
            'time_label': self.time_label,
            'fps_label': self.fps_label,
            'frame_count_label': self.frame_count_label,
        }

        # Store custom positions to reapply on resize
        self._designer_positions = designer_positions
        self._positioned_widgets = widget_map

        # Apply after layout settles
        from PySide6.QtCore import QTimer
        QTimer.singleShot(50, self._apply_designer_positions_now)

    def _apply_designer_positions_now(self):
        """Internal method to apply legacy designer positions safely."""
        if not hasattr(self, '_designer_positions') or not self._designer_positions:
            return

        for prop_name, pos_data in self._designer_positions.items():
            if prop_name in self._positioned_widgets:
                widget = self._positioned_widgets[prop_name]
                # New anchor/entity layout owns all registered components.
                # Skip legacy absolute positioning for these components.
                if hasattr(self, '_component_slots') and prop_name in self._component_slots:
                    continue
                x = pos_data.get('x')
                y = pos_data.get('y')

                if x is not None and y is not None:
                    # If managed by a layout, skip absolute position (preserve fit/responsive behavior).
                    managed_by_layout = False
                    parent_widget = widget.parentWidget()
                    if parent_widget and parent_widget.layout():
                        managed_by_layout = parent_widget.layout().indexOf(widget) >= 0
                    if managed_by_layout:
                        continue

                    # Absolute positioning only for free widgets.
                    if widget.parent() == self:
                        current_size = widget.size()
                        widget.setGeometry(int(x), int(y), current_size.width(), current_size.height())
                        widget.show()

    def switch_skin(self, skin_name: str):
        """Switch to a different skin and apply it immediately.

        Args:
            skin_name: Name of skin to switch to

        Returns:
            True if skin loaded successfully, False otherwise
        """
        if self.skin_manager.load_skin(skin_name):
            # Save to settings
            settings.setValue('video_player_skin', skin_name)
            # Apply immediately (live update!)
            self.apply_current_skin()
            return True
        return False

    def apply_skin_data(self, skin_data: dict):
        """Apply a skin dictionary directly.

        Args:
            skin_data: The skin configuration dictionary.
        """
        if not hasattr(self, 'skin_manager'):
            return

        # Update manager state
        from skins.engine.skin_applier import SkinApplier
        self.skin_manager.current_skin = skin_data
        self.skin_manager.current_applier = SkinApplier(skin_data)
        
        # Apply
        self.apply_current_skin()

    def get_available_skins(self):
        """Get list of available skins.

        Returns:
            List of skin dicts with 'name', 'author', 'version' keys
        """
        # Refresh to pick up newly added preset files immediately.
        self.skin_manager.refresh_available_skins()
        return self.skin_manager.get_available_skins()

    def _set_loop_button_style(self, button, is_set=False):
        """Set loop button style based on state, using skin colors.

        Args:
            button: Loop button (start/end)
            is_set: Whether the loop point is set (True) or unset (False)
        """
        applier = self.skin_manager.get_current_applier()
        if not applier:
            return

        styling = applier.styling

        # Determine which color to use based on button
        if button == self.loop_start_btn:
            active_color = styling.get('loop_marker_start_color', '#FF0080')
        elif button == self.loop_end_btn:
            active_color = styling.get('loop_marker_end_color', '#FF8C00')
        else:
            active_color = styling.get('button_bg_color', '#2b2b2b')

        if is_set:
            # Active state - use marker color
            button.setStyleSheet(f"""
                QPushButton {{
                    background-color: {active_color};
                    color: white;
                    font-size: 18px;
                    padding: 2px;
                }}
            """)
        else:
            # Inactive state - use default button styling
            component_id = None
            if button == self.loop_start_btn:
                component_id = 'loop_start_button'
            elif button == self.loop_end_btn:
                component_id = 'loop_end_button'
            elif button == self.loop_reset_btn:
                component_id = 'loop_reset_button'
            elif button == self.loop_checkbox:
                component_id = 'loop_checkbox'
            applier.apply_to_button(button, component_id=component_id)

    def _apply_scaling(self):
        """Apply scaling to internal elements based on current width."""
        width = self.width()
        designer_layout = {}
        if hasattr(self, 'skin_manager') and self.skin_manager.current_skin:
            designer_layout = self.skin_manager.current_skin.get('video_player', {}).get('designer_layout', {})
        scaling_cfg = designer_layout.get('scaling', {}) if isinstance(designer_layout, dict) else {}

        # Ideal size is 800px - only scale DOWN when smaller, never scale up
        ideal_width = int(scaling_cfg.get('ideal_width', 800)) if isinstance(scaling_cfg, dict) else 800
        ideal_width = max(200, ideal_width)
        min_scale = float(scaling_cfg.get('min_scale', 0.5)) if isinstance(scaling_cfg, dict) else 0.5
        max_scale = float(scaling_cfg.get('max_scale', 1.0)) if isinstance(scaling_cfg, dict) else 1.0
        min_scale = max(0.1, min(2.0, min_scale))
        max_scale = max(min_scale, min(3.0, max_scale))
        raw_scale = min(max_scale, max(min_scale, width / ideal_width))
        # Ease scaling so tiny widths do not over-shrink controls.
        scale = raw_scale ** 0.78
        self._responsive_scale_factor = scale

        def component_scale(component_id: str) -> float:
            cfg = self._get_component_layout(component_id)
            return max(0.25, min(4.0, float(cfg.get('scale', 1.0))))

        # Keep transport buttons visually proportional in compact tiers.
        # Three tiers:
        # - middle (<520): near-full layout, gentle shrink
        # - compact (<420): hide low-priority items
        # - nano (<320): essentials-only layout
        # Floors are monotonic so nano never looks "bigger" than compact.
        if width < 320:
            button_scale_floor = 0.72
        elif width < 420:
            button_scale_floor = 0.76
        elif width < 520:
            button_scale_floor = 0.80
        else:
            button_scale_floor = 0.78
        button_scale = max(button_scale_floor, scale)

        # Scale button sizes per component.
        button_map = {
            'play_button': self.play_pause_btn,
            'stop_button': self.stop_btn,
            'mute_button': self.mute_btn,
            'prev_frame_button': self.prev_frame_btn,
            'next_frame_button': self.next_frame_btn,
            'skip_back_button': self.skip_back_btn,
            'skip_forward_button': self.skip_forward_btn,
            'loop_start_button': self.loop_start_btn,
            'loop_end_button': self.loop_end_btn,
            'loop_reset_button': self.loop_reset_btn,
            'loop_checkbox': self.loop_checkbox,
        }
        for component_id, btn in button_map.items():
            base_button_size = int(self._component_style_value(component_id, 'button_size', 40))
            scaled_size = int(max(12, base_button_size * button_scale * component_scale(component_id)))
            btn.setMinimumWidth(scaled_size)
            btn.setMaximumWidth(scaled_size)
            btn.setMinimumHeight(scaled_size)
            btn.setMaximumHeight(scaled_size)
            if component_id == 'loop_checkbox':
                loop_width = int(max(64, scaled_size * 1.9))
                btn.setMinimumWidth(loop_width)
                btn.setMaximumWidth(loop_width)

        # Scale frame spinbox
        spinbox_width = int(max(60, 80 * scale * component_scale('frame_spinbox')))
        self.frame_spinbox.setMaximumWidth(spinbox_width)
        spinbox_font = self.frame_spinbox.font()
        spinbox_font.setPointSize(max(8, int(11 * scale * component_scale('frame_spinbox'))))
        self.frame_spinbox.setFont(spinbox_font)

        # Scale label fonts per component.
        label_map = {
            'frame_label': self.frame_label,
            'frame_total_label': self.frame_total_label,
            'time_label': self.time_label,
            'fps_label': self.fps_label,
            'frame_count_label': self.frame_count_label,
            'sar_warning_label': self.sar_warning_label,
            'speed_label': self.speed_label,
            'speed_value_label': self.speed_value_label,
        }
        for component_id, label in label_map.items():
            base_font_size = int(self._component_style_value(component_id, 'label_font_size', 11))
            font = label.font()
            font.setPointSize(max(7, int(base_font_size * scale * component_scale(component_id))))
            label.setFont(font)

        preview_font_size = max(8, int(10 * scale * component_scale('preview_container')))
        for i in range(self.preview_labels_layout.count()):
            item = self.preview_labels_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if isinstance(widget, QLabel):
                    font = widget.font()
                    font.setPointSize(preview_font_size)
                    widget.setFont(font)

        speed_slider_min_width = int(max(80, 100 * scale * component_scale('speed_slider')))
        # Prevent speed slider from claiming disproportionate space and causing
        # repeated expensive relayout in dense multi-view scenarios.
        speed_slider_min_width = min(speed_slider_min_width, max(100, int(self.width() * 0.45)))
        self.speed_slider.setMinimumWidth(speed_slider_min_width)
        slider_height = int(max(20, 30 * scale * component_scale('timeline_slider')))
        self.timeline_slider.setMinimumHeight(slider_height)

        self._apply_compact_visibility(width)

        # Scale margins and spacing
        margin = max(12, int(8 * scale))
        spacing = int(8 * scale)
        self.layout().setContentsMargins(
            margin,
            int(4 * scale),
            margin,
            int(4 * scale),
        )
        self.layout().setSpacing(spacing)
        self._apply_component_layout_properties()
        self._update_background_surface_geometry()

    def _apply_compact_visibility(self, width: int):
        """Hide low-priority labels when width is very small to prevent overlap."""
        middle = width < 520
        compact = width < 420
        nano = width < 320

        # Middle tier: keep almost everything visible.
        self.fps_label.setVisible(not compact)
        self.frame_count_label.setVisible(not compact)

        if compact:
            self.frame_label.setText('')
            self.speed_label.setText('')
            self.frame_label.setVisible(False)
            self.speed_label.setVisible(False)
            self.frame_total_label.setVisible(False)
        else:
            self.frame_label.setVisible(True)
            self.speed_label.setVisible(True)
            self.frame_label.setText('Frame:')
            self.speed_label.setText('Speed:')
            self.frame_total_label.setVisible(True)

        # Hide preview label row only when space gets tight.
        self.preview_container.setVisible(not middle)
        # Keep timeline visible in every tier (including nano).
        self.timeline_slider.setVisible(True)

        # Compact tier: drop some non-essential controls but keep main interaction intact.
        self.frame_spinbox.setVisible(not compact)
        self.speed_slider.setVisible(not compact)
        self.speed_value_label.setVisible(not compact)
        self.skip_back_btn.setVisible(not compact)
        self.skip_forward_btn.setVisible(not compact)
        self.loop_start_btn.setVisible(not compact)
        self.loop_end_btn.setVisible(not compact)
        self.loop_reset_btn.setVisible(not compact)

        # Nano mode: only core playback + timeline.
        self.play_pause_btn.setVisible(True)
        if nano:
            self.mute_btn.setVisible(False)
            self.prev_frame_btn.setVisible(False)
            self.next_frame_btn.setVisible(False)
            self.frame_spinbox.setVisible(False)
            self.loop_checkbox.setVisible(False)
            self.time_label.setVisible(False)
            # Extreme nano: keep only play/pause to avoid transport overlap.
            self.stop_btn.setVisible(width >= 220)
        else:
            self.mute_btn.setVisible(True)
            self.prev_frame_btn.setVisible(True)
            self.next_frame_btn.setVisible(True)
            self.loop_checkbox.setVisible(True)
            self.time_label.setVisible(True)
            self.stop_btn.setVisible(True)

    def minimum_runtime_width(self) -> int:
        """Minimum practical runtime width for drag-resize and viewer restore."""
        return 80

    def _capture_geometry_percent(self):
        """Capture current geometry as parent-relative percentages."""
        parent = self.parentWidget()
        if not parent:
            return None
        pw = parent.width()
        ph = parent.height()
        if pw <= 0 or ph <= 0:
            return None
        return (
            self.x() / pw,
            self.y() / ph,
            self.width() / pw,
        )

    def _apply_geometry_percent(self, geometry_percent):
        """Apply parent-relative geometry percentages, clamped to parent bounds."""
        if not geometry_percent or len(geometry_percent) != 3:
            return
        parent = self.parentWidget()
        if not parent:
            return
        pw = parent.width()
        ph = parent.height()
        if pw <= 0 or ph <= 0:
            return
        x_pct, y_pct, w_pct = geometry_percent
        min_w = self.minimum_runtime_width()
        width = max(min_w, min(int(w_pct * pw), pw))
        height = self.height()
        x = max(0, min(int(x_pct * pw), pw - width))
        y = max(0, min(int(y_pct * ph), ph - height))
        self.setGeometry(x, y, width, height)
        self._apply_scaling()
        self._schedule_layout_settle_reflow()
        settings.setValue('video_controls_x_percent', self.x() / pw)
        settings.setValue('video_controls_y_percent', self.y() / ph)
        settings.setValue('video_controls_width_percent', self.width() / pw)

    def fit_to_parent_width(self):
        """Auto-fit controls width to parent while preserving current Y position."""
        parent = self.parentWidget()
        if not parent:
            return
        parent_rect = parent.rect()
        if parent_rect.width() <= 0 or parent_rect.height() <= 0:
            return
        min_w = self.minimum_runtime_width()
        target_w = max(min_w, int(parent_rect.width() * 0.96))
        target_w = min(target_w, parent_rect.width())
        x_pos = max(0, (parent_rect.width() - target_w) // 2)
        y_pos = max(0, min(self.y(), parent_rect.height() - self.height()))
        self.setGeometry(x_pos, y_pos, target_w, self.height())
        self._apply_scaling()
        self._schedule_layout_settle_reflow()
        self._sync_height_to_content()
        settings.setValue('video_controls_x_percent', self.x() / parent_rect.width())
        settings.setValue('video_controls_y_percent', self.y() / parent_rect.height())
        settings.setValue('video_controls_width_percent', self.width() / parent_rect.width())

    def toggle_fit_width(self):
        """Toggle between auto-fit width and previously used custom geometry."""
        if self._fit_mode_active:
            if self._pre_fit_geometry_percent:
                self._apply_geometry_percent(self._pre_fit_geometry_percent)
            self._fit_mode_active = False
            return

        current_percent = self._capture_geometry_percent()
        if current_percent:
            self._pre_fit_geometry_percent = current_percent
        self.fit_to_parent_width()
        self._fit_mode_active = True

    def resizeEvent(self, event):
        """Scale all controls based on available width."""
        super().resizeEvent(event)

        # Don't interfere with manual resizing
        if self._resizing:
            return

        self._apply_scaling()
        self._update_background_surface_geometry()
        self._schedule_layout_settle_reflow()

        # Reapply designer positions after scaling
        if hasattr(self, '_designer_positions') and self._designer_positions:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(10, self._apply_designer_positions_now)

    def showEvent(self, event):
        """Ensure overlay-positioned components snap to valid anchors when shown."""
        super().showEvent(event)
        self._schedule_layout_settle_reflow()

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

    @Slot()
    def _on_timeline_slider_pressed(self):
        # Pause while scrubbing so timeline drag does not fight active playback.
        self._was_playing_before_scrub = bool(self.is_playing)
        if self._was_playing_before_scrub:
            self.play_pause_requested.emit()
        self._timeline_scrubbing = True
        # Force immediate paint cadence while actively scrubbing.
        self._last_position_ui_update_at = 0.0
        self._last_position_text_update_at = 0.0

    @Slot()
    def _on_timeline_slider_released(self):
        self._timeline_scrubbing = False
        # Ensure first post-scrub update is not delayed by stale timestamps.
        self._last_position_ui_update_at = 0.0
        self._last_position_text_update_at = 0.0
        # Resume only if playback was active before the scrub began.
        if self._was_playing_before_scrub and not self.is_playing:
            self.play_pause_requested.emit()
        self._was_playing_before_scrub = False

    def is_timeline_scrubbing(self) -> bool:
        return bool(self._timeline_scrubbing or self.timeline_slider.isSliderDown())

    def eventFilter(self, obj, event):
        """Event filter for speed slider mouse tracking and global mouse release."""
        # Handle global mouse release to catch releases outside widget during resize/drag
        if obj == self.parent() and event.type() == event.Type.MouseButtonRelease:
            if (self._resizing or self._dragging) and event.button() == Qt.MouseButton.LeftButton:
                # Mouse released outside widget during resize/drag - clean up
                self._resizing = False
                self._dragging = False
                self._restart_parent_hide_timer()
                return False  # Let parent handle the event too

        if obj == self.speed_slider:
            from PySide6.QtCore import QEvent, QPoint
            from PySide6.QtGui import QCursor

            # Handle clicks to snap to position
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    # Snap to clicked position
                    slider_rect = self.speed_slider.geometry()
                    slider_width = slider_rect.width()
                    slider_left = self.speed_slider.mapToGlobal(QPoint(0, 0)).x()

                    mouse_x = event.globalPos().x()
                    # Clamp position_ratio to visual bounds (no rubberband on click)
                    position_ratio = max(0.0, min(1.0, (mouse_x - slider_left) / slider_width))

                    # Non-linear mapping for zones
                    if position_ratio < 0.2:
                        # Red zone: 0-20% maps to -2.0x to 0.0x
                        self._extended_speed = -2.0 + (position_ratio / 0.2) * 2.0
                    elif position_ratio < 0.5:
                        # Orange zone: 20-50% maps to 0.0x to 1.0x
                        self._extended_speed = (position_ratio - 0.2) / 0.3 * 1.0
                    else:
                        # Green zone: 50-100% maps to 1.0x to 6.0x
                        self._extended_speed = 1.0 + (position_ratio - 0.5) / 0.5 * 5.0

                    # Update slider handle position for visual feedback
                    slider_pos = int(self.speed_slider.minimum() + position_ratio * (self.speed_slider.maximum() - self.speed_slider.minimum()))
                    self._skip_next_slider_change = True  # Prevent valueChanged from re-calculating speed
                    self.speed_slider.setValue(slider_pos)

                    # Update labels and emit with the calculated speed
                    self.speed_value_label.setText(f'{self._extended_speed:.2f}x')
                    self.speed_changed.emit(self._extended_speed)
                    self._update_speed_preview()
                    self._update_marker_range_display()
                    event.accept()
                    return

            # Handle mouse wheel for fine adjustment
            if event.type() == QEvent.Type.Wheel:
                wheel_delta = event.angleDelta().y()
                # Positive delta = wheel up = increase speed
                # Negative delta = wheel down = decrease speed
                adjustment = 0.01 if wheel_delta > 0 else -0.01

                # Clamp new speed to visual range (-2.0 to 6.0)
                self._extended_speed = max(-2.0, min(6.0, self._extended_speed + adjustment))

                # Update slider position to match new speed
                position_ratio = self._speed_to_position_ratio(self._extended_speed)
                slider_pos = int(self.speed_slider.minimum() + position_ratio * (self.speed_slider.maximum() - self.speed_slider.minimum()))
                self._skip_next_slider_change = True
                self.speed_slider.setValue(slider_pos)

                # Update display
                self.speed_value_label.setText(f'{self._extended_speed:.2f}x')
                self.speed_changed.emit(self._extended_speed)
                self._update_speed_preview()
                self._update_marker_range_display()
                event.accept()
                return True  # Consume event - prevent zoom from happening

            if event.type() == QEvent.Type.MouseMove and self._is_dragging_speed:
                from PySide6.QtCore import QPoint
                from PySide6.QtGui import QCursor

                current_mouse = QCursor.pos()

                # Get slider geometry
                slider_rect = self.speed_slider.geometry()
                slider_width = slider_rect.width()
                slider_left = self.speed_slider.mapToGlobal(QPoint(0, 0)).x()
                slider_right = slider_left + slider_width

                if slider_width > 0:
                    # Calculate mouse position relative to slider (0.0 to 1.0)
                    mouse_x = current_mouse.x()
                    position_ratio = (mouse_x - slider_left) / slider_width

                    # Non-linear mapping for zones:
                    # 0-20% → -2.0x to 0.0x
                    # 20-50% → 0.0x to 1.0x (more space for accuracy)
                    # 50-100% → 1.0x to 6.0x
                    if position_ratio < 0.0:
                        # Beyond left edge - rubberband
                        overshoot_factor = abs(position_ratio)
                        self._extended_speed = -2.0 - (overshoot_factor * 10.0)
                    elif position_ratio < 0.2:
                        # Red zone: 0-20% maps to -2.0x to 0.0x
                        self._extended_speed = -2.0 + (position_ratio / 0.2) * 2.0
                    elif position_ratio < 0.5:
                        # Orange zone: 20-50% maps to 0.0x to 1.0x
                        self._extended_speed = (position_ratio - 0.2) / 0.3 * 1.0
                    elif position_ratio <= 1.0:
                        # Green zone: 50-100% maps to 1.0x to 6.0x
                        self._extended_speed = 1.0 + (position_ratio - 0.5) / 0.5 * 5.0
                    else:
                        # Beyond right edge - rubberband
                        overshoot_factor = position_ratio - 1.0
                        self._extended_speed = 6.0 + (overshoot_factor * 6.0)

                    # Clamp to absolute limits (-12.0 to 12.0)
                    self._extended_speed = max(-12.0, min(12.0, self._extended_speed))

                    # Update slider position: clamp position_ratio to visual bounds for display
                    clamped_ratio = max(0.0, min(1.0, position_ratio))
                    slider_pos = int(self.speed_slider.minimum() + clamped_ratio * (self.speed_slider.maximum() - self.speed_slider.minimum()))
                    self.speed_slider.blockSignals(True)
                    self.speed_slider.setValue(slider_pos)
                    self.speed_slider.blockSignals(False)

                    # Update display and emit signal
                    self.speed_value_label.setText(f'{self._extended_speed:.2f}x')
                    self.speed_changed.emit(self._extended_speed)
                    self._update_speed_preview()
                    self._update_marker_range_display()

                self._last_mouse_pos = current_mouse

        return super().eventFilter(obj, event)

    @Slot()
    def _on_speed_slider_pressed(self):
        """Handle speed slider press - start extended drag tracking."""
        self._is_dragging_speed = True
        # Don't recalculate speed here - keep the accurate speed from click/drag
        # (speed_slider.value() would use linear math which is wrong for our non-linear zones)
        self._drag_start_value = self.speed_slider.value()
        from PySide6.QtGui import QCursor
        self._last_mouse_pos = QCursor.pos()

    def _speed_to_position_ratio(self, speed):
        """Convert speed value to visual position ratio (0.0 to 1.0) using non-linear zones."""
        if speed < -2.0:
            return 0.0
        elif speed < 0.0:
            # Red zone: -2.0x to 0.0x maps to 0-20%
            return (speed + 2.0) / 2.0 * 0.2
        elif speed < 1.0:
            # Orange zone: 0.0x to 1.0x maps to 20-50%
            return 0.2 + (speed / 1.0) * 0.3
        elif speed <= 6.0:
            # Green zone: 1.0x to 6.0x maps to 50-100%
            return 0.5 + (speed - 1.0) / 5.0 * 0.5
        else:
            return 1.0

    @Slot()
    def _on_speed_slider_released(self):
        """Handle speed slider release - clamp to visual range."""
        self._is_dragging_speed = False
        self._last_mouse_pos = None

        # If extended speed is outside the visual range (-2.0-6.0), clamp to edges
        if self._extended_speed < -2.0:
            # Was below minimum, clamp to -2.0x
            self._extended_speed = -2.0
        elif self._extended_speed > 6.0:
            # Was above max, clamp to maximum (6.0x)
            self._extended_speed = 6.0
        # else: keep the accurate _extended_speed calculated during drag

        # Update slider display: convert speed to position_ratio, then to slider value
        position_ratio = self._speed_to_position_ratio(self._extended_speed)
        slider_pos = int(self.speed_slider.minimum() + position_ratio * (self.speed_slider.maximum() - self.speed_slider.minimum()))
        self.speed_slider.blockSignals(True)
        self.speed_slider.setValue(slider_pos)
        self.speed_slider.blockSignals(False)
        self.speed_value_label.setText(f'{self._extended_speed:.2f}x')
        self.speed_changed.emit(self._extended_speed)
        self._update_speed_preview()
        self._update_marker_range_display()

    @Slot(int)
    def _on_speed_slider_changed(self, value):
        """Handle playback speed slider change (normal mode only)."""
        # Skip if we just set this value ourselves during click handling
        if self._skip_next_slider_change:
            self._skip_next_slider_change = False
            return

        # Only process if not actively dragging with our custom handler
        if not self._is_dragging_speed:
            # Convert slider value to position ratio, then to speed using non-linear mapping
            position_ratio = (value - self.speed_slider.minimum()) / (self.speed_slider.maximum() - self.speed_slider.minimum())

            # Apply non-linear zone mapping
            if position_ratio < 0.2:
                self._extended_speed = -2.0 + (position_ratio / 0.2) * 2.0
            elif position_ratio < 0.5:
                self._extended_speed = (position_ratio - 0.2) / 0.3 * 1.0
            else:
                self._extended_speed = 1.0 + (position_ratio - 0.5) / 0.5 * 5.0

            self.speed_value_label.setText(f'{self._extended_speed:.2f}x')
            self.speed_changed.emit(self._extended_speed)
            self._update_speed_preview()
            self._update_marker_range_display()

    def get_speed_value(self) -> float:
        """Return current playback speed value from controls."""
        return float(self._extended_speed)

    def set_speed_value(self, speed: float, emit_signal: bool = True):
        """Set playback speed value and keep slider/labels synchronized."""
        try:
            parsed_speed = float(speed)
        except (TypeError, ValueError):
            parsed_speed = 1.0

        self._extended_speed = max(-12.0, min(12.0, parsed_speed))
        position_ratio = self._speed_to_position_ratio(self._extended_speed)
        slider_pos = int(
            self.speed_slider.minimum()
            + position_ratio * (self.speed_slider.maximum() - self.speed_slider.minimum())
        )
        self.speed_slider.blockSignals(True)
        self.speed_slider.setValue(slider_pos)
        self.speed_slider.blockSignals(False)
        self.speed_value_label.setText(f'{self._extended_speed:.2f}x')
        if emit_signal:
            self.speed_changed.emit(self._extended_speed)
        self._update_speed_preview()
        self._update_marker_range_display()

    def _reset_speed(self, event):
        """Reset playback speed to 1.0x when speed value label is clicked."""
        self.set_speed_value(1.0, emit_signal=True)

    def _apply_speed_theme(self):
        """Apply the current theme to the speed slider stylesheet."""
        theme = self._gradient_themes[self._current_theme_index]
        # Update gradient stylesheet with theme colors
        # Keep the same transition smoothness as before (0.15-0.25, 0.45-0.55)
        self.speed_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                height: 8px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0.0 {theme[0]},
                    stop:0.15 {theme[0]},
                    stop:0.25 {theme[1]},
                    stop:0.45 {theme[1]},
                    stop:0.55 {theme[2]},
                    stop:1.0 {theme[2]});
                border-radius: 4px;
            }}
            QSlider::handle:horizontal {{
                background: #FFFFFF;
                border: 2px solid #333;
                width: 16px;
                margin: -4px 0;
                border-radius: 8px;
            }}
            QSlider::handle:horizontal:hover {{
                background: #E0E0E0;
                border: 2px solid #000;
            }}
        """)

    def _cycle_speed_theme(self, event):
        """Cycle through gradient themes when 'Speed:' label is clicked."""
        # Move to next theme
        self._current_theme_index = (self._current_theme_index + 1) % len(self._gradient_themes)
        # Apply the new theme
        self._apply_speed_theme()
        # Save theme choice to settings
        settings.setValue('speed_slider_theme_index', self._current_theme_index)

    def _update_speed_preview(self):
        """Update speed preview label based on current speed and video metadata."""
        if self._current_frame_count == 0 or abs(self._extended_speed - 1.0) < 0.01 or abs(self._extended_speed) < 0.01:
            # No video loaded, speed is 1.0x, or speed is 0 (avoid division by zero), hide preview
            self.speed_preview_label.setText('')
            return

        # Use custom FPS if set, otherwise use current FPS
        preview_fps = self._custom_preview_fps if self._custom_preview_fps else self._current_fps

        # Calculate new duration based on speed multiplier
        original_duration = self._current_frame_count / self._current_fps if self._current_fps > 0 else 0
        new_duration = original_duration / self._extended_speed

        # Calculate new frame count based on target FPS and new duration
        # Use round() to match ffmpeg's fps filter behavior better
        new_frame_count = max(1, round(new_duration * preview_fps))

        # Format duration as seconds with 1 decimal
        duration_str = f'{new_duration:.1f}s'

        # Display format: [Speed: 2.0x → 40f @30fps | 1.3s]
        # Add asterisk if using custom FPS
        fps_indicator = f'*{preview_fps:.0f}' if self._custom_preview_fps else f'{preview_fps:.0f}'
        preview_text = f'[{self._extended_speed:.1f}x → {new_frame_count}f @{fps_indicator}fps | {duration_str}]'
        self.speed_preview_label.setText(preview_text)

    def _on_preview_label_clicked(self, event):
        """Handle click on speed preview label to set custom FPS."""
        if self._current_frame_count == 0:
            return

        from PySide6.QtWidgets import QInputDialog

        current_fps = self._custom_preview_fps if self._custom_preview_fps else self._current_fps

        fps, ok = QInputDialog.getDouble(
            self, "Set Preview FPS",
            f"Enter target FPS for preview calculation:\n(Original: {self._current_fps:.2f} fps)",
            value=current_fps,
            minValue=1.0,
            maxValue=120.0,
            decimals=2
        )

        if ok:
            # Set custom FPS (or reset to original if same)
            if abs(fps - self._current_fps) < 0.01:
                self._custom_preview_fps = None  # Reset to original
            else:
                self._custom_preview_fps = fps

            # Update preview with new FPS
            self._update_speed_preview()
            self._update_marker_range_display()

    @Slot()
    def _toggle_mute(self):
        """Toggle mute/unmute state."""
        self.is_muted = not self.is_muted
        # Save to settings for persistence across reboots
        settings.setValue('video_muted', self.is_muted)
        self.mute_toggled.emit(self.is_muted)
        self._update_mute_button()

    def _update_mute_button(self):
        """Update mute button appearance based on state."""
        if self._last_mute_visual_state is not None and self._last_mute_visual_state == self.is_muted:
            return
        if self.is_muted:
            self.mute_btn.setText('🔇')
            self.mute_btn.setToolTip('Unmute Audio')
            # Normal state when muted
            self.mute_btn.setStyleSheet("""
                QPushButton {
                    background-color: #2b2b2b;
                    border: 2px solid #555;
                    border-radius: 4px;
                    font-size: 18px;
                }
                QPushButton:hover {
                    background-color: #3a3a3a;
                    border-color: #666;
                }
            """)
        else:
            self.mute_btn.setText('🔊')
            self.mute_btn.setToolTip('Mute Audio')
            # Green glow when unmuted
            self.mute_btn.setStyleSheet("""
                QPushButton {
                    background-color: #1a3a1a;
                    border: 2px solid #4CAF50;
                    border-radius: 4px;
                    font-size: 18px;
                }
                QPushButton:hover {
                    background-color: #254a25;
                    border-color: #5FBF60;
                }
            """)
        self._last_mute_visual_state = self.is_muted

    @Slot(dict)
    def set_video_info(self, metadata: dict, image=None, proxy_model=None):
        """Update controls with video metadata and load loop markers from image."""
        if not metadata:
            return

        # Store references for persistence
        self.current_image = image
        self.proxy_image_list_model = proxy_model

        def _to_float(value, default):
            try:
                if value is None:
                    return default
                return float(value)
            except (TypeError, ValueError):
                return default

        def _to_int(value, default):
            try:
                if value is None:
                    return default
                return int(value)
            except (TypeError, ValueError):
                return default

        fps = _to_float(metadata.get('fps', 0), 0.0)
        frame_count = _to_int(metadata.get('frame_count', 0), 0)
        duration = _to_float(metadata.get('duration', 0), 0.0)
        sar_num = _to_int(metadata.get('sar_num', 1), 1)
        sar_den = _to_int(metadata.get('sar_den', 1), 1)

        # Store for speed preview calculations
        self._current_fps = fps
        self._current_frame_count = frame_count
        self._current_duration = duration

        # Update frame controls
        self.frame_spinbox.setMaximum(frame_count - 1 if frame_count > 0 else 0)
        self.timeline_slider.setMaximum(frame_count - 1 if frame_count > 0 else 0)
        self.frame_total_label.setText(f'/ {frame_count}')

        # Load loop markers for current viewer scope.
        max_frame = frame_count - 1 if frame_count > 0 else 0
        resolved_start, resolved_end = self._resolve_loop_markers_for_scope(image, max_frame)
        if resolved_start is not None and resolved_end is not None:
            normalized_start = max(0, min(int(resolved_start), max_frame))
            normalized_end = max(0, min(int(resolved_end), max_frame))
            if normalized_start > normalized_end:
                normalized_start, normalized_end = normalized_end, normalized_start
            self.loop_start_frame = normalized_start
            self.loop_end_frame = normalized_end
            self.timeline_slider.set_loop_markers(self.loop_start_frame, self.loop_end_frame)
            self._set_loop_button_style(self.loop_start_btn, is_set=True)
            self._set_loop_button_style(self.loop_end_btn, is_set=True)
        else:
            self._reset_loop(save=False)

        # Update info labels
        self.fps_label.setText(f'{fps:.2f} fps')
        self.frame_count_label.setText(f'{frame_count} frames')

        # Update frame total label initially
        if frame_count > 0:
            self.frame_total_label.setText(f'/ {frame_count}')
        else:
            self.frame_total_label.setText('/ 0')


        # Update SAR warning indicator (only show if SAR != 1:1)
        if sar_num > 0 and sar_den > 0 and sar_num != sar_den:
            sar_ratio = sar_num / sar_den
            self.sar_warning_label.setText(f'⚠SAR {sar_num}:{sar_den}')
            self.sar_warning_label.setToolTip(
                f'Video has non-square pixels (SAR {sar_num}:{sar_den} = {sar_ratio:.3f})\n'
                f'Training tools like musubi-tuner may ignore SAR and use wrong dimensions.\n'
                f'Consider re-encoding with square pixels (SAR 1:1) before training.'
            )
            self.sar_warning_label.show()
        else:
            self.sar_warning_label.setText('')
            self.sar_warning_label.setToolTip('')
            self.sar_warning_label.hide()

        # Format duration as mm:ss.mmm
        minutes = int(duration // 60)
        seconds = int(duration % 60)
        milliseconds = int((duration % 1) * 1000)
        self.time_label.setText(f'00:00.000 / {minutes:02d}:{seconds:02d}.{milliseconds:03d}')

        # Restore loop state after video loads
        if self.is_looping:
            self.loop_toggled.emit(True)
            # If loop markers are defined, start playback/view from loop-in frame.
            if self.loop_start_frame is not None and self.loop_end_frame is not None:
                start_frame = max(0, min(int(self.loop_start_frame), self.frame_spinbox.maximum()))
                self.frame_changed.emit(start_frame)

        # Restore mute state after video loads (emit to sync with video player)
        self.mute_toggled.emit(self.is_muted)

        # Update speed preview with new video metadata
        self._update_speed_preview()

    def _save_loop_markers(self):
        """Save current loop markers to image metadata."""
        if self.current_image and self.proxy_image_list_model:
            scope = getattr(self, '_loop_persistence_scope', 'main') or 'main'

            viewer_markers = getattr(self.current_image, 'viewer_loop_markers', None)
            if not isinstance(viewer_markers, dict):
                viewer_markers = {}

            if self.loop_start_frame is None and self.loop_end_frame is None:
                viewer_markers.pop(scope, None)
                if scope != 'main':
                    viewer_markers.pop('floating_last', None)
            else:
                viewer_markers[scope] = {
                    'loop_start_frame': self.loop_start_frame,
                    'loop_end_frame': self.loop_end_frame,
                }
                if scope != 'main':
                    viewer_markers['floating_last'] = {
                        'loop_start_frame': self.loop_start_frame,
                        'loop_end_frame': self.loop_end_frame,
                    }

            if scope == 'main':
                self.current_image.loop_start_frame = self.loop_start_frame
                self.current_image.loop_end_frame = self.loop_end_frame
                if self.loop_start_frame is None and self.loop_end_frame is None:
                    viewer_markers.pop('main', None)
                else:
                    viewer_markers['main'] = {
                        'loop_start_frame': self.loop_start_frame,
                        'loop_end_frame': self.loop_end_frame,
                    }

            self.current_image.viewer_loop_markers = viewer_markers
            # Write to disk through the source model
            self.proxy_image_list_model.sourceModel().write_meta_to_disk(self.current_image)

    def should_auto_play(self) -> bool:
        """Check if auto-play should trigger for the next video."""
        return self.auto_play_enabled

    @Slot(int, float)
    def update_position(self, frame: int, time_ms: float):
        """Update display when playback position changes."""
        # Hidden controls in background viewers don't need per-frame UI churn.
        # This significantly reduces UI-thread pressure when multiple videos play.
        if not self.isVisible():
            return

        # Skip updates if in marker preview mode (dragging marker)
        # This keeps seekbar frozen at original position during preview
        if self._in_marker_preview:
            return

        is_scrubbing = self.is_timeline_scrubbing()

        now = time.monotonic()
        host_window = self.window()
        is_active_window = bool(host_window and host_window.isActiveWindow())
        is_spawned_owner = bool(getattr(self, '_is_spawned_owner', False))
        max_frame = self.frame_spinbox.maximum()
        is_boundary_frame = frame <= 0 or frame >= max_frame
        frame_delta = abs(frame - self.frame_spinbox.value())

        # Dynamic profile keeps single-view UX responsive while scaling down
        # per-frame churn when many videos are active.
        profile = str(getattr(self, '_perf_profile', 'single') or 'single')
        if profile == 'dual':
            tuning = {
                'main_active': (1.0 / 28.0, 0.14, 2, 4),
                'main_inactive': (0.24, 0.38, 4, 6),
                'spawn_active': (0.12, 0.22, 3, 5),
                'spawn_inactive': (0.26, 0.44, 5, 7),
            }
        elif profile == 'multi':
            tuning = {
                'main_active': (1.0 / 22.0, 0.18, 3, 5),
                'main_inactive': (0.28, 0.45, 5, 8),
                'spawn_active': (0.16, 0.30, 4, 7),
                'spawn_inactive': (0.34, 0.58, 6, 10),
            }
        elif profile == 'heavy':
            tuning = {
                'main_active': (1.0 / 16.0, 0.24, 4, 7),
                'main_inactive': (0.36, 0.60, 7, 11),
                'spawn_active': (0.22, 0.40, 6, 9),
                'spawn_inactive': (0.46, 0.78, 9, 14),
            }
        else:
            tuning = {
                'main_active': (1.0 / 36.0, 0.10, 2, 3),
                'main_inactive': (0.20, 0.30, 3, 5),
                'spawn_active': (0.09, 0.16, 2, 4),
                'spawn_inactive': (0.18, 0.32, 4, 6),
            }

        if is_spawned_owner:
            key = 'spawn_active' if is_active_window else 'spawn_inactive'
        else:
            key = 'main_active' if is_active_window else 'main_inactive'
        position_interval, text_interval, active_delta, inactive_delta = tuning[key]
        min_frame_delta = active_delta if is_active_window else inactive_delta

        # While user is dragging timeline, disable update throttles for this widget.
        if is_scrubbing:
            position_interval = 0.0
            text_interval = 0.0
            min_frame_delta = 0

        # Keep seek/slider responsive, but don't push every decoded frame.
        should_update_position = (
            is_boundary_frame
            or frame_delta >= min_frame_delta
            or (now - self._last_position_ui_update_at) >= position_interval
        )
        if should_update_position:
            self._updating_slider = True
            if self.frame_spinbox.value() != frame:
                self.frame_spinbox.blockSignals(True)
                self.frame_spinbox.setValue(frame)
                self.frame_spinbox.blockSignals(False)
            if self.timeline_slider.value() != frame:
                self.timeline_slider.setValue(frame)
            self._updating_slider = False
            self._last_position_ui_update_at = now

        # Text labels are cheaper to update less frequently.
        should_update_text = (
            is_boundary_frame
            or (now - self._last_position_text_update_at) >= text_interval
        )
        if not should_update_text:
            return

        # Update frame total label with "last" indicator
        total_frames = self.frame_spinbox.maximum() + 1  # Convert from 0-based max to total count
        if total_frames > 0:
            is_last = frame == self.frame_spinbox.maximum()
            if is_last:
                frame_display = "last"
            else:
                frame_display = str(total_frames)
            frame_total_text = f'/ {frame_display}'
        else:
            frame_total_text = '/ 0'
        if frame_total_text != self._last_frame_total_display:
            self.frame_total_label.setText(frame_total_text)
            self._last_frame_total_display = frame_total_text

        # Update time display
        time_seconds = time_ms / 1000.0
        minutes = int(time_seconds // 60)
        seconds = int(time_seconds % 60)
        milliseconds = int((time_seconds % 1) * 1000)

        current_text = self.time_label.text()
        total_time = current_text.split('/ ')[-1] if '/' in current_text else '00:00.000'
        time_text = f'{minutes:02d}:{seconds:02d}.{milliseconds:03d} / {total_time}'
        if time_text != self._last_time_display:
            self.time_label.setText(time_text)
            self._last_time_display = time_text
        self._last_position_text_update_at = now

    @Slot(bool)
    def set_playing(self, playing: bool, update_auto_play: bool = False):
        """Update play/pause button state.

        Args:
            playing: Whether video is playing
            update_auto_play: If True, updates auto-play state (for manual user toggles)
        """
        playing = bool(playing)
        previous_playing = bool(self.is_playing)
        self.is_playing = playing

        # Only update auto-play state on manual user toggles
        if update_auto_play:
            self.auto_play_enabled = playing
            # Save to settings for persistence across reboots
            settings.setValue('video_auto_play', playing)

        # Avoid repeated icon/stylesheet churn during playback loops.
        if (
            self._last_playing_visual_state is not None
            and self._last_playing_visual_state == playing
            and previous_playing == playing
            and not update_auto_play
        ):
            return

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
        self._last_playing_visual_state = playing

    def set_performance_profile(self, profile: str, *, is_active_owner: bool = False):
        """Apply profile hints while preserving single-view UX quality."""
        self._perf_profile = str(profile or 'single')

        # Reduce secondary spawned-only non-critical labels in heavier multi-view loads.
        reduced_noncritical = (
            self._perf_profile in ('multi', 'heavy')
            and bool(getattr(self, '_is_spawned_owner', False))
            and not bool(is_active_owner)
        )
        target_preview_visible = not reduced_noncritical
        if self.preview_container.isVisible() != target_preview_visible:
            self.preview_container.setVisible(target_preview_visible)
        if reduced_noncritical and self.sar_warning_label.isVisible():
            self.sar_warning_label.hide()

    def _update_marker_range_display(self):
        """Update the marker range frame count display."""
        # Clear existing preview labels
        while self.preview_labels_layout.count():
            item = self.preview_labels_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().setParent(None)

        # Show marker range if markers are set (ALWAYS show when both markers exist)
        if self.loop_start_frame is not None and self.loop_end_frame is not None:
            frame_count = abs(self.loop_end_frame - self.loop_start_frame) + 1

            # Check if we should show speed/FPS prediction
            # Show full prediction if either speed changed OR custom FPS is set (but not if speed is 0)
            if (abs(self._extended_speed - 1.0) >= 0.01 or self._custom_preview_fps is not None) and self._current_fps > 0 and abs(self._extended_speed) >= 0.01:
                # Speed/FPS changed - show full prediction
                preview_fps = self._custom_preview_fps if self._custom_preview_fps else self._current_fps

                # Calculate for marker range
                original_duration = frame_count / self._current_fps
                new_duration = original_duration / self._extended_speed
                # Use round() to match ffmpeg's fps filter behavior better
                new_frame_count = max(1, round(new_duration * preview_fps))

                # Format marker range display: [81 frames → 23f @16fps 3.5x]
                fps_indicator = f'*{preview_fps:.0f}' if self._custom_preview_fps else f'{preview_fps:.0f}'
                marker_text = f'[{frame_count} frames → {new_frame_count}f @{fps_indicator}fps {self._extended_speed:.1f}x]'
            else:
                # Speed is 1.0x and no custom FPS - show basic frame count only
                marker_text = f'[{frame_count} frames]'

            # Create marker range label
            marker_label = QLabel(marker_text)
            marker_label.setStyleSheet("QLabel { color: #4CAF50; font-weight: bold; font-size: 10px; }")
            marker_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            marker_label.setToolTip('Frame count between markers. Click to set custom FPS for preview calculation.')
            marker_label.mousePressEvent = self._on_preview_label_clicked

            self.preview_labels_layout.addWidget(marker_label)

        # Show speed preview if speed is changed (regardless of markers)
        if abs(self._extended_speed - 1.0) >= 0.01 and abs(self._extended_speed) >= 0.01 and self._current_fps > 0 and self._current_frame_count > 0:
            # Use custom FPS if set, otherwise use current FPS
            preview_fps = self._custom_preview_fps if self._custom_preview_fps else self._current_fps

            # Calculate for full video speed preview
            full_original_duration = self._current_frame_count / self._current_fps
            full_new_duration = full_original_duration / self._extended_speed
            # Use round() to match ffmpeg's fps filter behavior better
            full_new_frame_count = max(1, round(full_new_duration * preview_fps))

            # Format duration as seconds with 1 decimal
            duration_str = f'{full_new_duration:.1f}s'

            # Display format for speed preview: [2.0x → 40f @30fps | 1.3s]
            fps_indicator = f'*{preview_fps:.0f}' if self._custom_preview_fps else f'{preview_fps:.0f}'
            full_preview_text = f'[{self._extended_speed:.1f}x → {full_new_frame_count}f @{fps_indicator}fps | {duration_str}]'

            # Create speed preview label with full prediction
            speed_preview_label = QLabel(full_preview_text)
            speed_preview_label.setStyleSheet("QLabel { color: #2196F3; font-weight: bold; font-size: 10px; }")
            speed_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            speed_preview_label.setToolTip('Preview of video if speed change is applied. Click to set custom FPS.')
            speed_preview_label.mousePressEvent = self._on_preview_label_clicked

            self.preview_labels_layout.addWidget(speed_preview_label)

    @Slot()
    def _set_loop_start(self):
        """Set loop start at current frame, and auto-set end if fixed marker size is enabled."""
        self.loop_start_frame = self.frame_spinbox.value()

        # Auto-set end marker based on fixed marker size (only if not Custom/0)
        if self.fixed_marker_size > 0:
            max_frame = self.frame_spinbox.maximum()
            self.loop_end_frame = min(self.loop_start_frame + self.fixed_marker_size - 1, max_frame)
            # Update end button color too
            self._set_loop_button_style(self.loop_end_btn, is_set=True)
            self.loop_end_set.emit()

        self.loop_start_set.emit()
        # Update button color to match pink marker
        self._set_loop_button_style(self.loop_start_btn, is_set=True)
        # Update timeline markers
        self.timeline_slider.set_loop_markers(self.loop_start_frame, self.loop_end_frame)
        # Update range display
        self._update_marker_range_display()
        # Save to JSON
        self._save_loop_markers()

    @Slot()
    def _set_loop_end(self):
        """Set loop end at current frame, and auto-set start if fixed marker size is enabled."""
        self.loop_end_frame = self.frame_spinbox.value()

        # Auto-set start marker based on fixed marker size (only if not Custom/0)
        if self.fixed_marker_size > 0:
            self.loop_start_frame = max(0, self.loop_end_frame - self.fixed_marker_size + 1)
            # Update start button color too
            self._set_loop_button_style(self.loop_start_btn, is_set=True)
            self.loop_start_set.emit()

        self.loop_end_set.emit()
        # Update button color to match orange marker
        self._set_loop_button_style(self.loop_end_btn, is_set=True)
        # Update timeline markers
        self.timeline_slider.set_loop_markers(self.loop_start_frame, self.loop_end_frame)
        # Update range display
        self._update_marker_range_display()
        # Save to JSON
        self._save_loop_markers()

    @Slot(bool)
    def _toggle_loop(self, enabled: bool):
        """Toggle loop playback."""
        self.is_looping = enabled
        self.loop_toggled.emit(enabled)
        # Save loop state to settings
        settings.setValue('video_loop_enabled', enabled)

    @Slot(bool)
    def _reset_loop(self, checked=False, save=True):
        """Reset loop markers only (keeps loop enabled/disabled state)."""
        self.loop_start_frame = None
        self.loop_end_frame = None
        # Don't change is_looping or loop_checkbox state
        self.loop_reset.emit()
        # Clear button styling
        self._set_loop_button_style(self.loop_start_btn, is_set=False)
        self._set_loop_button_style(self.loop_end_btn, is_set=False)
        # Clear timeline markers
        self.timeline_slider.clear_loop_markers()
        # Clear range display
        self._update_marker_range_display()
        # Save to JSON only if requested (don't save during video load validation)
        if save:
            self._save_loop_markers()

    def get_loop_range(self):
        """Get current loop range (start, end) or None if not set."""
        if self.loop_start_frame is not None and self.loop_end_frame is not None:
            return (self.loop_start_frame, self.loop_end_frame)
        return None

    def get_loop_state(self) -> dict[str, int | bool | None]:
        """Get loop markers and enabled state."""
        return {
            'start_frame': self.loop_start_frame,
            'end_frame': self.loop_end_frame,
            'enabled': bool(self.is_looping),
        }

    def apply_loop_state(
        self,
        start_frame: int | None,
        end_frame: int | None,
        enabled: bool,
        save: bool = False,
        emit_signals: bool = True,
    ):
        """Apply loop markers and loop-enabled state."""
        max_frame = self.frame_spinbox.maximum()

        has_markers = isinstance(start_frame, int) and isinstance(end_frame, int)
        if has_markers:
            normalized_start = max(0, min(int(start_frame), max_frame))
            normalized_end = max(0, min(int(end_frame), max_frame))
        else:
            normalized_start = None
            normalized_end = None

        self.loop_start_frame = normalized_start
        self.loop_end_frame = normalized_end

        if normalized_start is not None and normalized_end is not None:
            self.timeline_slider.set_loop_markers(normalized_start, normalized_end)
            self._set_loop_button_style(self.loop_start_btn, is_set=True)
            self._set_loop_button_style(self.loop_end_btn, is_set=True)
            if emit_signals:
                self.loop_start_set.emit()
                self.loop_end_set.emit()
        else:
            self.timeline_slider.clear_loop_markers()
            self._set_loop_button_style(self.loop_start_btn, is_set=False)
            self._set_loop_button_style(self.loop_end_btn, is_set=False)
            if emit_signals:
                self.loop_reset.emit()

        previous_block = self.loop_checkbox.blockSignals(True)
        self.loop_checkbox.setChecked(bool(enabled))
        self.loop_checkbox.blockSignals(previous_block)
        self.is_looping = bool(enabled)
        if emit_signals:
            self.loop_toggled.emit(self.is_looping)

        self._update_marker_range_display()
        if save:
            self._save_loop_markers()

    @Slot()
    def reset(self):
        """Reset controls to default state."""
        self.frame_spinbox.setValue(0)
        self.timeline_slider.setValue(0)
        self.time_label.setText('00:00.000 / 00:00.000')
        self.fps_label.setText('0.00 fps')
        self.frame_count_label.setText('0 frames')
        self.frame_total_label.setText('/ 0')
        # N*4+1 frame rule indicator removed - now shown as stamp on sidebar preview
        self.set_playing(False)
        self._reset_loop()

    @Slot(int)
    def _on_loop_start_dragged(self, frame):
        """Handle loop start marker being dragged."""
        self.loop_start_frame = frame
        self._set_loop_button_style(self.loop_start_btn, is_set=True)
        self.loop_start_set.emit()
        # Update range display
        self._update_marker_range_display()
        # Save to JSON
        self._save_loop_markers()

    @Slot(int)
    def _on_loop_end_dragged(self, frame):
        """Handle loop end marker being dragged."""
        self.loop_end_frame = frame
        self._set_loop_button_style(self.loop_end_btn, is_set=True)
        self.loop_end_set.emit()
        # Update range display
        self._update_marker_range_display()
        # Save to JSON
        self._save_loop_markers()

    @Slot()
    def _on_marker_drag_started(self):
        """Handle marker drag start - pause playback and store position."""
        # Store current frame position from the spinbox
        self._preview_restore_frame = self.frame_spinbox.value()

        # Store whether video is playing and pause if needed
        self._was_playing_before_preview = self.is_playing
        if self.is_playing:
            self.play_pause_requested.emit()  # Pause video

        # Enter preview mode (blocks seekbar updates)
        self._in_marker_preview = True

    @Slot(int)
    def _on_marker_preview_frame(self, frame):
        """Handle marker preview - show frame without moving seekbar."""
        if self._in_marker_preview:
            # Emit special preview signal that won't update the seekbar
            self.marker_preview_requested.emit(frame)

    @Slot()
    def _on_marker_drag_ended(self):
        """Handle marker drag end - restore position and resume playback."""
        # Exit preview mode first (allows seekbar updates again)
        self._in_marker_preview = False

        if self._preview_restore_frame is not None:
            # Force seek back to the stored frame (don't use setValue as it won't emit if value unchanged)
            self.frame_changed.emit(self._preview_restore_frame)
            self._preview_restore_frame = None

        # Resume playback if it was playing before
        if self._was_playing_before_preview:
            self.play_pause_requested.emit()  # Resume video
            self._was_playing_before_preview = False

    def _stop_parent_hide_timer(self):
        """Stop parent's auto-hide timer during drag/resize operations."""
        parent = self.parent()
        if parent and hasattr(parent, '_controls_hide_timer'):
            parent._controls_hide_timer.stop()

    def _restart_parent_hide_timer(self):
        """Restart parent's auto-hide timer after drag/resize ends."""
        parent = self.parent()
        if parent and hasattr(parent, '_show_controls_temporarily'):
            # Use parent's method to show controls and restart timer
            parent._show_controls_temporarily()

    def mousePressEvent(self, event):
        """Start dragging or resizing the controls widget."""
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.pos()

            # Check corners first (higher priority than edges)
            # Bottom-left corner
            if (pos.x() <= self._resize_corner_size and
                pos.y() >= self.height() - self._resize_corner_size):
                self._resizing = 'left'
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_start_width = self.width()
                self._resize_start_x = self.x()
                self._stop_parent_hide_timer()
                event.accept()
                return
            # Bottom-right corner
            elif (pos.x() >= self.width() - self._resize_corner_size and
                  pos.y() >= self.height() - self._resize_corner_size):
                self._resizing = 'right'
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_start_width = self.width()
                self._stop_parent_hide_timer()
                event.accept()
                return
            # Top-left corner
            elif (pos.x() <= self._resize_corner_size and
                  pos.y() <= self._resize_corner_size):
                self._resizing = 'left'
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_start_width = self.width()
                self._resize_start_x = self.x()
                self._stop_parent_hide_timer()
                event.accept()
                return
            # Top-right corner
            elif (pos.x() >= self.width() - self._resize_corner_size and
                  pos.y() <= self._resize_corner_size):
                self._resizing = 'right'
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_start_width = self.width()
                self._stop_parent_hide_timer()
                event.accept()
                return
            # Check edges
            elif pos.x() <= self._resize_handle_width:
                # Left edge resize
                self._resizing = 'left'
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_start_width = self.width()
                self._resize_start_x = self.x()
                self._stop_parent_hide_timer()
                event.accept()
                return
            elif pos.x() >= self.width() - self._resize_handle_width:
                # Right edge resize
                self._resizing = 'right'
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_start_width = self.width()
                self._stop_parent_hide_timer()
                event.accept()
                return

            # Otherwise, start dragging
            self._dragging = True
            self._drag_start_pos = event.globalPosition().toPoint() - self.pos()
            self._drag_has_moved = False
            self._stop_parent_hide_timer()
            event.accept()

    def mouseMoveEvent(self, event):
        """Drag or resize the controls widget, and update cursor."""
        pos = event.pos()

        # Update cursor based on position (also during resize to maintain visual feedback)
        # Check corners first
        if ((pos.x() <= self._resize_corner_size and pos.y() <= self._resize_corner_size) or
            (pos.x() >= self.width() - self._resize_corner_size and pos.y() >= self.height() - self._resize_corner_size) or
            (pos.x() <= self._resize_corner_size and pos.y() >= self.height() - self._resize_corner_size) or
            (pos.x() >= self.width() - self._resize_corner_size and pos.y() <= self._resize_corner_size)):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        # Check edges
        elif pos.x() <= self._resize_handle_width or pos.x() >= self.width() - self._resize_handle_width:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif not self._dragging and not self._resizing:
            self.setCursor(Qt.CursorShape.ArrowCursor)

        # Keep parent hide timer stopped during active resize/drag
        if self._resizing or self._dragging:
            self._stop_parent_hide_timer()

        if self._resizing:
            delta = event.globalPosition().toPoint() - self._resize_start_pos
            parent_rect = self.parent().rect()

            if self._resizing == 'left':
                # Resize from left edge
                new_width = self._resize_start_width - delta.x()
                new_x = self._resize_start_x + delta.x()
                # Clamp width (min runtime width, max parent width)
                min_w = self.minimum_runtime_width()
                new_width = max(min_w, min(new_width, parent_rect.width()))
                # Adjust x to maintain right edge position
                new_x = self._resize_start_x + (self._resize_start_width - new_width)
                # Clamp x position
                new_x = max(0, min(new_x, parent_rect.width() - new_width))
                self.setGeometry(new_x, self.y(), new_width, self.height())
            elif self._resizing == 'right':
                # Resize from right edge
                new_width = self._resize_start_width + delta.x()
                # Clamp width (min runtime width, max fits in parent)
                max_width = parent_rect.width() - self.x()
                min_w = self.minimum_runtime_width()
                new_width = max(min_w, min(new_width, max_width))
                self.setGeometry(self.x(), self.y(), new_width, self.height())
            event.accept()
        elif self._dragging:
            new_pos = event.globalPosition().toPoint() - self._drag_start_pos
            # Keep within parent bounds
            parent_rect = self.parent().rect()
            new_pos.setX(max(0, min(new_pos.x(), parent_rect.width() - self.width())))
            new_pos.setY(max(0, min(new_pos.y(), parent_rect.height() - self.height())))
            if new_pos != self.pos():
                self._drag_has_moved = True
            self.move(new_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        """Stop dragging or resizing the controls widget."""
        if event.button() == Qt.MouseButton.LeftButton:
            was_resizing = self._resizing
            was_dragging = self._dragging
            drag_moved = bool(self._drag_has_moved)
            current_width = self.width()  # Save width before changing flags

            # Always clear states first
            self._dragging = False
            self._resizing = False
            self._drag_has_moved = False

            # Restart parent hide timer after drag/resize ends
            if was_resizing or was_dragging:
                self._restart_parent_hide_timer()

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
            if was_resizing or drag_moved:
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
                        self._pre_fit_geometry_percent = (x_percent, y_percent, width_percent)
                        self._fit_mode_active = False
            event.accept()

    def mouseDoubleClickEvent(self, event):
        """Double-click empty bar background to fit width to viewer."""
        if event.button() == Qt.MouseButton.LeftButton:
            clicked_child = self.childAt(event.pos())
            non_interactive_fit_targets = {
                self.time_label,
                self.fps_label,
                self.frame_count_label,
                self.frame_label,
                self.frame_total_label,
            }
            if (
                clicked_child is None
                or clicked_child is self.background_surface
                or clicked_child in non_interactive_fit_targets
            ):
                self.toggle_fit_width()
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        """Show skin selection context menu on right-click."""
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QAction

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #2D2D2D;
                color: #FFFFFF;
                border: 1px solid #555;
            }
            QMenu::item:selected {
                background-color: #2196F3;
            }
        """)

        # Add skin submenu
        skin_menu = menu.addMenu("🎨 Change Skin")
        skin_menu.setStyleSheet(menu.styleSheet())

        # Get available skins
        available_skins = self.get_available_skins()
        current_skin = self.skin_manager.get_current_skin_name()

        # Add skin options
        for skin_info in available_skins:
            skin_name = skin_info['name']
            action = QAction(skin_name, self)

            # Mark current skin with checkmark
            if skin_name == current_skin:
                action.setText(f"✓ {skin_name}")
                action.setEnabled(False)  # Can't select current skin

            # Connect to switch function
            action.triggered.connect(
                lambda checked, name=skin_name: self.switch_skin(name)
            )
            skin_menu.addAction(action)

        # Add separator
        menu.addSeparator()

        # Add "Open Skins Folder" option
        open_skins_action = QAction("📁 Open Skins Folder", self)
        open_skins_action.triggered.connect(self._open_skins_folder)
        menu.addAction(open_skins_action)

        # Add separator
        menu.addSeparator()

        # Add "Design Skin" option
        designer_action = QAction("🎨 Design Custom Skin...", self)
        designer_action.triggered.connect(self._open_skin_designer)
        menu.addAction(designer_action)

        # Show menu at cursor position
        menu.exec(event.globalPos())

    def _open_skins_folder(self):
        """Open the skins user folder in file explorer."""
        from pathlib import Path
        import subprocess
        import sys

        skins_folder = Path(__file__).parent.parent / 'skins' / 'user'
        skins_folder.mkdir(parents=True, exist_ok=True)

        # Open folder in OS file explorer
        if sys.platform == 'win32':
            subprocess.run(['explorer', str(skins_folder)])
        elif sys.platform == 'darwin':
            subprocess.run(['open', str(skins_folder)])
        else:
            subprocess.run(['xdg-open', str(skins_folder)])

    def _open_skin_designer(self):
        """Open the interactive skin designer dialog."""
        from dialogs.skin_designer_live import SkinDesignerLive

        designer = SkinDesignerLive(self, video_controls=self)
        designer.exec()
