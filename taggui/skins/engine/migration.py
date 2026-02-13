"""Skin migration helpers for backward-compatible schema evolution."""

from copy import deepcopy
from typing import Any, Dict

from .player_components import COMPONENTS


def migrate_skin_to_v2(skin_data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize legacy skin structures into v2-compatible shape.

    This keeps legacy keys intact while projecting known values into:
    - video_player.component_styles
    - normalized designer position keys
    """
    migrated = deepcopy(skin_data)
    vp = migrated.setdefault('video_player', {})
    styling = vp.setdefault('styling', {})
    component_styles = vp.setdefault('component_styles', {})

    # Legacy per-component color keys -> component_styles.<id>.default.button_bg_color
    for component_id in COMPONENTS:
        legacy_color_key = f'{component_id}_color'
        if legacy_color_key in styling:
            component_block = component_styles.setdefault(component_id, {})
            default_block = component_block.setdefault('default', {})
            default_block.setdefault('button_bg_color', styling[legacy_color_key])

    # Normalize legacy designer position aliases.
    designer_positions = migrated.get('designer_positions', {})
    if isinstance(designer_positions, dict):
        if 'timeline' in designer_positions and 'timeline_slider' not in designer_positions:
            designer_positions['timeline_slider'] = designer_positions['timeline']

        # Legacy per-element align -> row alignment hint.
        vp = migrated.setdefault('video_player', {})
        designer_layout = vp.setdefault('designer_layout', {})
        controls_row = designer_layout.setdefault('controls_row', {})
        if 'button_alignment' not in controls_row:
            alignment_votes = {'left': 0, 'center': 0, 'right': 0}
            for values in designer_positions.values():
                if isinstance(values, dict):
                    align = values.get('align')
                    if align == 'h_center':
                        alignment_votes['center'] += 1
                    elif align in alignment_votes:
                        alignment_votes[align] += 1
            if sum(alignment_votes.values()) > 0:
                controls_row['button_alignment'] = max(alignment_votes, key=alignment_votes.get)

    migrated.setdefault('skin_schema_version', 2)
    return migrated
