"""Skin applier - applies skin data to Qt widgets."""

from typing import Dict, Any, Optional
from PySide6.QtWidgets import QWidget, QSlider, QPushButton, QLabel
from PySide6.QtCore import Qt


class SkinApplier:
    """Applies skin styling to video player widgets."""

    def __init__(self, skin_data: Dict[str, Any]):
        """Initialize applier with skin data.

        Args:
            skin_data: Loaded and resolved skin dictionary
        """
        self.skin = skin_data
        self.vp = skin_data.get('video_player', {})
        self.layout = self.vp.get('layout', {})
        self.styling = self.vp.get('styling', {})
        self.borders = self.vp.get('borders', {})
        self.shadows = self.vp.get('shadows', {})

    def get_control_bar_height(self) -> int:
        """Get control bar height from skin."""
        return self.layout.get('control_bar_height', 60)

    def get_control_bar_position(self) -> str:
        """Get control bar position (top, bottom, overlay)."""
        return self.layout.get('control_bar_position', 'bottom')

    def get_button_spacing(self) -> int:
        """Get spacing between buttons."""
        return self.layout.get('button_spacing', 8)

    def get_section_spacing(self) -> int:
        """Get spacing between sections."""
        return self.layout.get('section_spacing', 16)

    def get_button_alignment(self) -> Qt.AlignmentFlag:
        """Get button alignment."""
        alignment = self.layout.get('button_alignment', 'center')
        alignment_map = {
            'left': Qt.AlignmentFlag.AlignLeft,
            'center': Qt.AlignmentFlag.AlignCenter,
            'right': Qt.AlignmentFlag.AlignRight
        }
        return alignment_map.get(alignment, Qt.AlignmentFlag.AlignCenter)

    def apply_to_control_bar(self, control_bar: QWidget):
        """Apply skin to control bar widget.

        Args:
            control_bar: QWidget control bar container
        """
        from PySide6.QtGui import QColor, QPalette
        from PySide6.QtCore import Qt

        bg_color = self.styling.get('control_bar_color', '#242424')
        opacity = self.styling.get('control_bar_opacity', 0.95)
        border = self.borders.get('control_bar_border', 'none')

        # Ensure opacity is a number (handle edge cases)
        if isinstance(opacity, str):
            try:
                opacity = float(opacity)
            except ValueError:
                opacity = 0.95

        # EXACT original method: use QPalette + setWindowOpacity, NOT stylesheet alpha
        control_bar.setAutoFillBackground(True)
        palette = control_bar.palette()
        palette.setColor(control_bar.backgroundRole(), QColor(bg_color))
        control_bar.setPalette(palette)
        control_bar.setWindowOpacity(opacity)

        # Only set border/radius if specified (Classic has none)
        if border != 'none':
            stylesheet = f"""
                QWidget {{
                    border: {border};
                    border-radius: {self.borders.get('radius', 0)}px;
                }}
            """
            control_bar.setStyleSheet(stylesheet)
        else:
            control_bar.setStyleSheet("")  # Clear any previous stylesheet

        # Don't use setFixedHeight - let the control bar size itself based on content
        # This matches original behavior where height was determined by layout

    def apply_to_button(self, button: QPushButton, is_primary: bool = False):
        """Apply skin to button.

        Args:
            button: QPushButton to style
            is_primary: Whether this is a primary action button
        """
        size = self.styling.get('button_size', 32)
        bg_color = self.styling.get('button_bg_color', '#1A1A1A')
        icon_color = self.styling.get('button_icon_color', '#FFFFFF')
        hover_color = self.styling.get('button_hover_color', '#2196F3')
        border = self.styling.get('button_border', '1px solid #333333')
        radius = self.styling.get('button_border_radius', 6)
        shadow = self.shadows.get('button', '0 2px 4px rgba(0,0,0,0.2)')

        # Note: Don't set any size constraints here - let _apply_scaling() handle all sizing
        # This way the scaling system (40 * scale) works correctly

        # Extract border color from border string (e.g. "2px solid #555" -> "#555")
        border_color = "#555"  # default
        if "solid" in border and "#" in border:
            parts = border.split("#")
            if len(parts) > 1:
                border_color = "#" + parts[1].strip()

        # EXACT original styling: hover changes background to hover_color and border to slightly lighter
        # Original was #3a3a3a bg with #666 border on hover
        hover_border_color = "#666" if bg_color == "#2b2b2b" else self._lighten_color(border_color, 1.2)

        stylesheet = f"""
            QPushButton {{
                background-color: {bg_color};
                color: {icon_color};
                border: {border};
                border-radius: {radius}px;
            }}
            QPushButton:hover {{
                background-color: {hover_color};
                border-color: {hover_border_color};
            }}
        """

        button.setStyleSheet(stylesheet)

    def apply_to_timeline_slider(self, slider: QSlider):
        """Apply skin to timeline slider.

        Args:
            slider: QSlider timeline widget
        """
        height = self.styling.get('timeline_height', 8)
        color = self.styling.get('timeline_color', '#2196F3')
        bg_color = self.styling.get('timeline_bg_color', '#1A1A1A')
        handle_size = self.styling.get('slider_handle_size', 16)
        handle_color = self.styling.get('slider_handle_color', '#FFFFFF')
        handle_border = self.styling.get('slider_handle_border', '2px solid #333333')

        stylesheet = f"""
            QSlider::groove:horizontal {{
                height: {height}px;
                background: {bg_color};
                border-radius: {height // 2}px;
            }}
            QSlider::sub-page:horizontal {{
                background: {color};
                border-radius: {height // 2}px;
            }}
            QSlider::handle:horizontal {{
                background: {handle_color};
                border: {handle_border};
                width: {handle_size}px;
                height: {handle_size + 4}px;
                margin: -{(handle_size - height) // 2}px 0;
                border-radius: {handle_size // 2}px;
            }}
            QSlider::handle:horizontal:hover {{
                background: #E0E0E0;
                border: 2px solid #000;
            }}
        """

        slider.setStyleSheet(stylesheet)

    def apply_to_speed_slider(self, slider: QSlider):
        """Apply skin to speed slider with gradient.

        Args:
            slider: QSlider speed control widget
        """
        start = self.styling.get('speed_gradient_start', '#2D5A2D')
        mid = self.styling.get('speed_gradient_mid', '#6B8E23')
        end = self.styling.get('speed_gradient_end', '#32CD32')
        handle_color = self.styling.get('slider_handle_color', '#FFFFFF')
        handle_border = self.styling.get('slider_handle_border', '2px solid #333333')
        handle_size = self.styling.get('slider_handle_size', 16)

        stylesheet = f"""
            QSlider::groove:horizontal {{
                height: 8px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0.0 {start},
                    stop:0.15 {start},
                    stop:0.25 {mid},
                    stop:0.45 {mid},
                    stop:0.55 {end},
                    stop:1.0 {end});
                border-radius: 4px;
            }}
            QSlider::handle:horizontal {{
                background: {handle_color};
                border: {handle_border};
                width: {handle_size}px;
                margin: -4px 0;
                border-radius: 8px;
            }}
            QSlider::handle:horizontal:hover {{
                background: #E0E0E0;
                border: 2px solid #000;
            }}
        """

        slider.setStyleSheet(stylesheet)

    def apply_to_label(self, label: QLabel, is_secondary: bool = False):
        """Apply skin to label.

        Args:
            label: QLabel to style
            is_secondary: Whether to use secondary text color
        """
        text_color = (self.styling.get('text_secondary_color', '#B0B0B0')
                      if is_secondary else
                      self.styling.get('text_color', '#FFFFFF'))
        font_size = self.styling.get('label_font_size', 12)

        stylesheet = f"""
            QLabel {{
                color: {text_color};
                font-size: {font_size}px;
            }}
        """

        label.setStyleSheet(stylesheet)

    def get_loop_marker_colors(self) -> Dict[str, Any]:
        """Get loop marker styling.

        Returns:
            Dict with start_color, end_color, outline_color, outline_width
        """
        return {
            'start_color': self.styling.get('loop_marker_start_color', '#FF0080'),
            'end_color': self.styling.get('loop_marker_end_color', '#FF8C00'),
            'outline_color': self.styling.get('loop_marker_outline', '#FFFFFF'),
            'outline_width': self.styling.get('loop_marker_outline_width', 2)
        }

    def _add_alpha_to_color(self, color: str, alpha: int) -> str:
        """Add alpha channel to hex color.

        Args:
            color: Hex color (e.g., '#242424')
            alpha: Alpha value (0-255)

        Returns:
            Hex color with alpha (e.g., '#242424F2')
        """
        if color.startswith('#'):
            return f"{color}{alpha:02X}"
        return color

    def _darken_color(self, color: str, factor: float = 0.8) -> str:
        """Darken a hex color.

        Args:
            color: Hex color (e.g., '#2196F3')
            factor: Darkening factor (0.0-1.0)

        Returns:
            Darkened hex color
        """
        if not color.startswith('#'):
            return color

        # Parse hex color
        hex_color = color.lstrip('#')
        if len(hex_color) == 6:
            r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        else:
            return color  # Invalid format

        # Darken
        r = int(r * factor)
        g = int(g * factor)
        b = int(b * factor)

        return f"#{r:02X}{g:02X}{b:02X}"

    def _lighten_color(self, color: str, factor: float = 1.2) -> str:
        """Lighten a hex color.

        Args:
            color: Hex color (e.g., '#555555')
            factor: Lightening factor (>1.0)

        Returns:
            Lightened hex color
        """
        if not color.startswith('#'):
            return color

        # Parse hex color
        hex_color = color.lstrip('#')
        if len(hex_color) == 6:
            r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        else:
            return color  # Invalid format

        # Lighten (cap at 255)
        r = min(255, int(r * factor))
        g = min(255, int(g * factor))
        b = min(255, int(b * factor))

        return f"#{r:02X}{g:02X}{b:02X}"
