"""Skin engine for TagGUI video player.

Provides declarative skin system allowing users to customize:
- Colors, spacing, opacity
- Button positions, sizes
- Layout variations
- Transparency effects
"""

from .skin_manager import SkinManager
from .skin_loader import SkinLoader
from .skin_applier import SkinApplier
from .schema import SkinSchema
from .player_components import COMPONENTS, PlayerComponent, get_component

__all__ = [
    'SkinManager',
    'SkinLoader',
    'SkinApplier',
    'SkinSchema',
    'COMPONENTS',
    'PlayerComponent',
    'get_component',
]
