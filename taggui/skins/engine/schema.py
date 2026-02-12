"""Skin schema definition - what properties can be customized."""

from typing import Dict, Any, List
from dataclasses import dataclass, field


@dataclass
class TokensSchema:
    """Token definitions for reusable values."""

    colors: Dict[str, str] = field(default_factory=dict)
    spacing: Dict[str, int] = field(default_factory=dict)
    opacity: Dict[str, float] = field(default_factory=dict)
    shadows: Dict[str, str] = field(default_factory=dict)


@dataclass
class LayoutSchema:
    """Layout positioning and sizing."""

    control_bar_height: int = 60
    control_bar_position: str = "bottom"  # top, bottom, overlay
    button_alignment: str = "center"  # left, center, right
    timeline_position: str = "above"  # above, below, integrated
    button_spacing: int = 8
    section_spacing: int = 16


@dataclass
class StylingSchema:
    """Visual styling properties."""

    # Background colors
    background: str = "#0D0D0D"
    control_bar_color: str = "#242424"
    control_bar_opacity: float = 0.95

    # Buttons
    button_size: int = 32
    button_icon_color: str = "#FFFFFF"
    button_bg_color: str = "#1A1A1A"
    button_hover_color: str = "#2196F3"
    button_border: str = "1px solid #333333"
    button_border_radius: int = 6

    # Timeline/slider
    timeline_height: int = 8
    timeline_color: str = "#2196F3"
    timeline_bg_color: str = "#1A1A1A"
    slider_handle_size: int = 16
    slider_handle_color: str = "#FFFFFF"
    slider_handle_border: str = "2px solid #333333"

    # Loop markers
    loop_marker_start_color: str = "#FF0080"
    loop_marker_end_color: str = "#FF8C00"
    loop_marker_outline: str = "#FFFFFF"
    loop_marker_outline_width: int = 2

    # Speed slider gradient (3 colors)
    speed_gradient_start: str = "#2D5A2D"
    speed_gradient_mid: str = "#6B8E23"
    speed_gradient_end: str = "#32CD32"

    # Text
    text_color: str = "#FFFFFF"
    text_secondary_color: str = "#B0B0B0"
    label_font_size: int = 12

    # Shadows
    control_bar_shadow: str = "0 4px 8px rgba(0,0,0,0.3)"
    button_shadow: str = "0 2px 4px rgba(0,0,0,0.2)"


@dataclass
class BordersSchema:
    """Border styling."""

    radius: int = 6
    control_bar_border: str = "1px solid #333333"
    button_border: str = "1px solid #333333"


@dataclass
class ShadowsSchema:
    """Shadow definitions."""

    control_bar: str = "0 4px 8px rgba(0,0,0,0.3)"
    button: str = "0 2px 4px rgba(0,0,0,0.2)"
    overlay: str = "0 8px 16px rgba(0,0,0,0.4)"


@dataclass
class VideoPlayerSchema:
    """Complete video player skin schema."""

    layout: LayoutSchema = field(default_factory=LayoutSchema)
    styling: StylingSchema = field(default_factory=StylingSchema)
    borders: BordersSchema = field(default_factory=BordersSchema)
    shadows: ShadowsSchema = field(default_factory=ShadowsSchema)


@dataclass
class SkinSchema:
    """Complete skin definition schema."""

    name: str = "Untitled Skin"
    author: str = "Unknown"
    version: str = "1.0"

    tokens: TokensSchema = field(default_factory=TokensSchema)
    video_player: VideoPlayerSchema = field(default_factory=VideoPlayerSchema)

    @classmethod
    def get_required_fields(cls) -> List[str]:
        """Return list of required top-level fields."""
        return ['name', 'version']

    @classmethod
    def get_optional_fields(cls) -> List[str]:
        """Return list of optional top-level fields."""
        return ['author', 'tokens', 'video_player']

    @classmethod
    def validate_structure(cls, data: Dict[str, Any]) -> tuple[bool, str]:
        """Validate skin data structure.

        Returns:
            (valid, error_message) tuple
        """
        # Check required fields
        for field in cls.get_required_fields():
            if field not in data:
                return False, f"Missing required field: {field}"

        # Validate video_player section if present
        if 'video_player' in data:
            vp = data['video_player']

            if 'component_styles' in vp and not isinstance(vp['component_styles'], dict):
                return False, "video_player.component_styles must be a mapping"

            if 'designer_layout' in vp and not isinstance(vp['designer_layout'], dict):
                return False, "video_player.designer_layout must be a mapping"

            # Validate layout position values
            if 'layout' in vp:
                layout = vp['layout']

                if 'control_bar_position' in layout:
                    valid_positions = ['top', 'bottom', 'overlay']
                    if layout['control_bar_position'] not in valid_positions:
                        return False, f"control_bar_position must be one of {valid_positions}"

                if 'button_alignment' in layout:
                    valid_alignments = ['left', 'center', 'right']
                    if layout['button_alignment'] not in valid_alignments:
                        return False, f"button_alignment must be one of {valid_alignments}"

                if 'timeline_position' in layout:
                    valid_timeline_pos = ['above', 'below', 'integrated']
                    if layout['timeline_position'] not in valid_timeline_pos:
                        return False, f"timeline_position must be one of {valid_timeline_pos}"

        return True, ""
