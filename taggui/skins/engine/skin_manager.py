"""Skin manager - coordinates loading, switching, and applying skins."""

from pathlib import Path
from typing import Dict, Any, Optional, List
from .skin_loader import SkinLoader
from .skin_applier import SkinApplier


class SkinManager:
    """Manages skin loading, switching, and application."""

    def __init__(self, skin_dirs: Optional[List[Path]] = None):
        """Initialize skin manager.

        Args:
            skin_dirs: List of directories to search for skins.
                       Defaults to [defaults/, user/]
        """
        if skin_dirs is None:
            base_dir = Path(__file__).parent.parent
            skin_dirs = [
                base_dir / 'defaults',
                base_dir / 'user'
            ]

        self.skin_dirs = skin_dirs
        self.loader = SkinLoader()
        self.current_skin: Optional[Dict[str, Any]] = None
        self.current_applier: Optional[SkinApplier] = None
        self.available_skins: List[Dict[str, Any]] = []

        # Load available skins
        self.refresh_available_skins()

    def refresh_available_skins(self):
        """Refresh list of available skins."""
        self.available_skins = self.loader.list_available_skins(self.skin_dirs)

    def get_available_skins(self) -> List[Dict[str, Any]]:
        """Get list of available skins.

        Returns:
            List of dicts with 'name', 'author', 'version', 'path' keys
        """
        return self.available_skins

    def load_skin(self, skin_name: str) -> bool:
        """Load a skin by name.

        Args:
            skin_name: Name of skin to load (from available skins)

        Returns:
            True if loaded successfully, False otherwise
        """
        # Find skin by name
        skin_info = None
        for skin in self.available_skins:
            if skin['name'] == skin_name:
                skin_info = skin
                break

        if not skin_info:
            print(f"Skin not found: {skin_name}")
            return False

        # Load skin data (cached in loader)
        self.current_skin = skin_info['data']
        self.current_applier = SkinApplier(self.current_skin)
        return True

    def load_skin_from_path(self, skin_path: Path) -> bool:
        """Load a skin from file path.

        Args:
            skin_path: Path to YAML skin file

        Returns:
            True if loaded successfully, False otherwise
        """
        skin_data = self.loader.load_skin(skin_path)
        if skin_data:
            self.current_skin = skin_data
            self.current_applier = SkinApplier(skin_data)
            return True
        return False

    def get_current_applier(self) -> Optional[SkinApplier]:
        """Get current skin applier.

        Returns:
            SkinApplier instance or None if no skin loaded
        """
        return self.current_applier

    def get_current_skin_name(self) -> str:
        """Get name of currently loaded skin.

        Returns:
            Skin name or "No Skin" if none loaded
        """
        if self.current_skin:
            return self.current_skin.get('name', 'Unknown')
        return "No Skin"

    def get_default_skin_name(self) -> str:
        """Get name of default skin.

        Returns:
            Name of first available skin, or empty string
        """
        if self.available_skins:
            return self.available_skins[0]['name']
        return ""

    def load_default_skin(self) -> bool:
        """Load the default skin.

        Returns:
            True if loaded successfully, False otherwise
        """
        default_name = self.get_default_skin_name()
        if default_name:
            return self.load_skin(default_name)
        return False
