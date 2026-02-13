"""Skin applier - applies skin data to Qt widgets."""

from typing import Dict, Any, Optional
from PySide6.QtWidgets import QWidget, QSlider, QPushButton, QLabel
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QPolygon, QRegion


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
        self.component_styles = self.vp.get('component_styles', {})
        self.borders = self.vp.get('borders', {})
        self.shadows = self.vp.get('shadows', {})

    def _resolve_component_style(
        self,
        component_id: Optional[str],
        key: str,
        default: Any = None,
        state: str = 'default'
    ) -> Any:
        """Resolve style with fallback: component state -> component default -> legacy -> global."""
        if not component_id:
            return self.styling.get(key, default)

        # v2: component_styles.<component_id>.<state>.<key>
        component_block = self.component_styles.get(component_id, {})
        if isinstance(component_block, dict):
            state_block = component_block.get(state, {})
            if isinstance(state_block, dict) and key in state_block:
                return state_block[key]
            default_block = component_block.get('default', {})
            if isinstance(default_block, dict) and key in default_block:
                return default_block[key]

        # Legacy per-element keys from early designer implementation.
        # Example: play_button_color -> button_bg_color
        legacy_key_map = {
            'button_bg_color': f'{component_id}_color',
            'button_icon_color': f'{component_id}_icon_color',
            'button_hover_color': f'{component_id}_hover_color',
            'button_border': f'{component_id}_border',
            'button_border_radius': f'{component_id}_border_radius',
            'text_color': f'{component_id}_text_color',
            'label_font_size': f'{component_id}_font_size',
        }
        legacy_key = legacy_key_map.get(key)
        if legacy_key and legacy_key in self.styling:
            return self.styling.get(legacy_key, default)

        return self.styling.get(key, default)

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
        from PySide6.QtGui import QColor

        bg_color = self.styling.get('control_bar_color', '#242424')
        opacity = self.styling.get('control_bar_opacity', 0.95)
        border = self.borders.get('control_bar_border', 'none')
        radius = self.borders.get('radius', 0)

        # Ensure opacity is a number (handle edge cases)
        if isinstance(opacity, str):
            try:
                opacity = float(opacity)
            except ValueError:
                opacity = 0.95

        # Store background style on control bar and let widget paint/apply to its background surface.
        # This decouples child component movement from the background rectangle.
        setattr(control_bar, '_skin_bg_color', QColor(bg_color).name())
        setattr(control_bar, '_skin_bg_opacity', max(0.0, min(1.0, float(opacity))))
        setattr(control_bar, '_skin_bg_border', str(border))
        setattr(control_bar, '_skin_bg_radius', int(radius) if str(radius).isdigit() else 0)
        if hasattr(control_bar, '_refresh_background_surface'):
            control_bar._refresh_background_surface()

        # Don't use setFixedHeight - let the control bar size itself based on content
        # This matches original behavior where height was determined by layout

    def apply_to_button(
        self,
        button: QPushButton,
        component_id: Optional[str] = None,
        is_primary: bool = False
    ):
        """Apply skin to button.

        Args:
            button: QPushButton to style
            is_primary: Whether this is a primary action button
        """
        size = self._resolve_component_style(component_id, 'button_size', 32)
        bg_color = self._resolve_component_style(component_id, 'button_bg_color', '#1A1A1A')
        icon_color = self._resolve_component_style(component_id, 'button_icon_color', '#FFFFFF')
        hover_color = self._resolve_component_style(component_id, 'button_hover_color', '#2196F3')
        border = self._resolve_component_style(component_id, 'button_border', '1px solid #333333')
        radius = self._resolve_component_style(component_id, 'button_border_radius', 6)
        shape = str(self._resolve_component_style(component_id, 'button_shape', 'rounded')).lower()
        button_font_family = self._resolve_component_style(component_id, 'button_font_family', '')
        button_font_style = str(self._resolve_component_style(component_id, 'button_font_style', 'normal')).lower()
        opacity = float(self._resolve_component_style(component_id, 'opacity', 1.0))
        shadow = self.shadows.get('button', '0 2px 4px rgba(0,0,0,0.2)')
        opacity = max(0.0, min(1.0, opacity))
        bg_color = self._with_alpha(bg_color, opacity)
        hover_color = self._with_alpha(hover_color, opacity)
        default_checked = self.styling.get('loop_marker_start_color', hover_color) if component_id == 'loop_checkbox' else hover_color
        checked_bg = self._resolve_component_style(component_id, 'button_checked_bg_color', default_checked)
        checked_bg = self._with_alpha(checked_bg, opacity)

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
        btn_weight = '700' if 'bold' in button_font_style else '400'
        btn_italic = 'italic' if 'italic' in button_font_style else 'normal'
        btn_family_css = f"font-family: '{button_font_family}';" if button_font_family else ""
        if shape == 'square':
            effective_radius = 0
        elif shape == 'circle':
            effective_radius = max(8, int(size // 2))
        elif shape == 'star':
            effective_radius = 2
            border = f"2px dashed {border_color}"
        else:
            effective_radius = radius

        stylesheet = f"""
            QPushButton {{
                background-color: {bg_color};
                color: {icon_color};
                border: {border};
                border-radius: {effective_radius}px;
                {btn_family_css}
                font-weight: {btn_weight};
                font-style: {btn_italic};
            }}
            QPushButton:hover {{
                background-color: {hover_color};
                border-color: {hover_border_color};
            }}
            QPushButton:checked {{
                background-color: {checked_bg};
                border-color: {hover_border_color};
                color: {icon_color};
            }}
        """
        if component_id == 'loop_checkbox':
            loop_font = max(9, int(size * 0.28))
            stylesheet += f"\nQPushButton {{ font-size: {loop_font}px; font-weight: 700; padding: 2px 6px; }}\n"

        button.setStyleSheet(stylesheet)
        self._apply_button_shape_mask(button, shape, size)

    def _apply_button_shape_mask(self, button: QPushButton, shape: str, size_hint: int):
        """Apply non-rectangular masks for advanced shapes where possible."""
        if shape != 'star':
            button.clearMask()
            return
        max_w = int(button.maximumWidth())
        max_h = int(button.maximumHeight())
        if 0 < max_w < 16777215 and 0 < max_h < 16777215:
            side = max(16, min(max_w, max_h))
        else:
            side = max(16, int(size_hint))
        cx = side // 2
        cy = side // 2
        r_outer = side // 2 - 2
        r_inner = max(4, int(r_outer * 0.45))
        points = []
        import math
        for i in range(10):
            angle = -math.pi / 2 + (i * math.pi / 5)
            r = r_outer if i % 2 == 0 else r_inner
            x = int(cx + r * math.cos(angle))
            y = int(cy + r * math.sin(angle))
            points.append(QPoint(x, y))
        poly = QPolygon(points)
        try:
            button.setMask(QRegion(poly))
        except Exception:
            button.clearMask()

    def apply_to_timeline_slider(self, slider: QSlider, component_id: Optional[str] = None):
        """Apply skin to timeline slider.

        Args:
            slider: QSlider timeline widget
        """
        height = self._resolve_component_style(component_id, 'timeline_height', 8)
        color = self._resolve_component_style(component_id, 'timeline_color', '#2196F3')
        bg_color = self._resolve_component_style(component_id, 'timeline_bg_color', '#1A1A1A')
        handle_size = self._resolve_component_style(component_id, 'slider_handle_size', 16)
        handle_color = self._resolve_component_style(component_id, 'slider_handle_color', '#FFFFFF')
        handle_border = self._resolve_component_style(component_id, 'slider_handle_border', '2px solid #333333')
        opacity = float(self._resolve_component_style(component_id, 'opacity', 1.0))
        opacity = max(0.0, min(1.0, opacity))
        color = self._with_alpha(color, opacity)
        bg_color = self._with_alpha(bg_color, opacity)

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

    def apply_to_speed_slider(self, slider: QSlider, component_id: Optional[str] = None):
        """Apply skin to speed slider with gradient.

        Args:
            slider: QSlider speed control widget
        """
        start = self._resolve_component_style(component_id, 'speed_gradient_start', '#2D5A2D')
        mid = self._resolve_component_style(component_id, 'speed_gradient_mid', '#6B8E23')
        end = self._resolve_component_style(component_id, 'speed_gradient_end', '#32CD32')
        handle_color = self._resolve_component_style(component_id, 'slider_handle_color', '#FFFFFF')
        handle_border = self._resolve_component_style(component_id, 'slider_handle_border', '2px solid #333333')
        handle_size = self._resolve_component_style(component_id, 'slider_handle_size', 16)
        opacity = float(self._resolve_component_style(component_id, 'opacity', 1.0))
        opacity = max(0.0, min(1.0, opacity))
        start = self._with_alpha(start, opacity)
        mid = self._with_alpha(mid, opacity)
        end = self._with_alpha(end, opacity)

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

    def apply_to_label(
        self,
        label: QLabel,
        component_id: Optional[str] = None,
        is_secondary: bool = False
    ):
        """Apply skin to label.

        Args:
            label: QLabel to style
            is_secondary: Whether to use secondary text color
        """
        text_color = (self._resolve_component_style(component_id, 'text_secondary_color', '#B0B0B0')
                      if is_secondary else
                      self._resolve_component_style(component_id, 'text_color', '#FFFFFF'))
        font_size = self._resolve_component_style(component_id, 'label_font_size', 12)
        font_family = self._resolve_component_style(component_id, 'label_font_family', '')
        font_style = str(self._resolve_component_style(component_id, 'label_font_style', 'normal')).lower()
        opacity = float(self._resolve_component_style(component_id, 'opacity', 1.0))
        opacity = max(0.0, min(1.0, opacity))
        text_color = self._with_alpha(text_color, opacity)
        font_weight = '700' if 'bold' in font_style else '400'
        italic = 'italic' if 'italic' in font_style else 'normal'
        family_css = f"font-family: '{font_family}';" if font_family else ""

        stylesheet = f"""
            QLabel {{
                color: {text_color};
                font-size: {font_size}px;
                {family_css}
                font-weight: {font_weight};
                font-style: {italic};
            }}
        """

        label.setStyleSheet(stylesheet)

    def get_loop_marker_colors(self) -> Dict[str, Any]:
        """Get loop marker styling.

        Returns:
            Dict with marker color/style values.
        """
        return {
            'start_color': self.styling.get('loop_marker_start_color', '#FF0080'),
            'end_color': self.styling.get('loop_marker_end_color', '#FF8C00'),
            'outline_color': self.styling.get('loop_marker_outline', '#FFFFFF'),
            'outline_width': self.styling.get('loop_marker_outline_width', 2),
            'marker_width': self.styling.get('loop_marker_width', 18),
            'marker_height': self.styling.get('loop_marker_height', 14),
            'marker_offset_y': self.styling.get('loop_marker_offset_y', -2),
            'marker_shape': self.styling.get('loop_marker_shape', 'triangle'),
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

    def _with_alpha(self, color: str, opacity: float) -> str:
        """Convert hex color to rgba string with opacity."""
        if not isinstance(color, str) or not color.startswith('#'):
            return color
        hex_color = color.lstrip('#')
        if len(hex_color) != 6:
            return color
        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        a = int(max(0.0, min(1.0, opacity)) * 255)
        return f"rgba({r}, {g}, {b}, {a})"
