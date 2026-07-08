"""Canonical video-player component registry for skinning/designer parity."""

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class PlayerComponent:
    """Metadata for a skinnable video-player component."""

    component_id: str
    kind: str
    role: str
    supports_positioning: bool = True
    supports_size: bool = True
    supports_text_style: bool = False


COMPONENTS: Dict[str, PlayerComponent] = {
    "play_button": PlayerComponent("play_button", "button", "primary"),
    "stop_button": PlayerComponent("stop_button", "button", "primary"),
    "mute_button": PlayerComponent("mute_button", "button", "primary"),
    "prev_frame_button": PlayerComponent("prev_frame_button", "button", "navigation"),
    "next_frame_button": PlayerComponent("next_frame_button", "button", "navigation"),
    "skip_back_button": PlayerComponent("skip_back_button", "button", "navigation"),
    "skip_forward_button": PlayerComponent("skip_forward_button", "button", "navigation"),
    "loop_start_button": PlayerComponent("loop_start_button", "button", "loop"),
    "loop_end_button": PlayerComponent("loop_end_button", "button", "loop"),
    "loop_reset_button": PlayerComponent("loop_reset_button", "button", "loop"),
    "loop_checkbox": PlayerComponent("loop_checkbox", "button", "loop"),
    "frame_label": PlayerComponent("frame_label", "label", "meta", supports_text_style=True),
    "frame_total_label": PlayerComponent("frame_total_label", "label", "meta", supports_text_style=True),
    "time_label": PlayerComponent("time_label", "label", "meta", supports_text_style=True),
    "fps_label": PlayerComponent("fps_label", "label", "meta", supports_text_style=True),
    "frame_count_label": PlayerComponent("frame_count_label", "label", "meta", supports_text_style=True),
    "speed_label": PlayerComponent("speed_label", "label", "meta", supports_text_style=True),
    "speed_value_label": PlayerComponent("speed_value_label", "label", "accent", supports_text_style=True),
    "timeline_slider": PlayerComponent("timeline_slider", "slider", "timeline"),
    "speed_slider": PlayerComponent("speed_slider", "slider", "speed"),
    "control_bar": PlayerComponent("control_bar", "container", "root"),
}


def get_component(component_id: str) -> Optional[PlayerComponent]:
    """Return a registered component by id."""
    return COMPONENTS.get(component_id)

