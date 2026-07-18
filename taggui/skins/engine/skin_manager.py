"""Skin manager - coordinates loading, switching, and applying skins."""

from pathlib import Path
from typing import Dict, Any, Optional, List
from .skin_loader import SkinLoader
from .skin_applier import SkinApplier


class SkinManager:
    """Manages skin loading, switching, and application."""

    def __init__(
        self,
        skin_dirs: Optional[List[Path]] = None,
        *,
        discover_on_init: bool = True,
    ):
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
        self.current_skin_path: Optional[Path] = None  # Track current skin file path
        self.available_skins: List[Dict[str, Any]] = []
        self._catalog_signature = None

        if discover_on_init:
            self.refresh_available_skins()

    def _iter_skin_files(self):
        for skin_dir in self.skin_dirs:
            if not skin_dir.exists():
                continue
            yield from skin_dir.glob('*.yaml')

    def _skin_catalog_signature(self):
        signature = []
        for skin_path in self._iter_skin_files():
            try:
                stat = skin_path.stat()
                signature.append(
                    (str(skin_path), int(stat.st_mtime_ns), int(stat.st_size))
                )
            except OSError:
                continue
        return tuple(sorted(signature))

    @staticmethod
    def _skin_info(skin_path: Path, skin_data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            'name': skin_data.get('name', skin_path.stem),
            'author': skin_data.get('author', 'Unknown'),
            'version': skin_data.get('version', '1.0'),
            'path': skin_path,
            'data': skin_data,
        }

    def refresh_available_skins(self):
        """Refresh list of available skins."""
        signature = self._skin_catalog_signature()
        if self.available_skins and signature == self._catalog_signature:
            return
        self.available_skins = self.loader.list_available_skins(self.skin_dirs)
        self._catalog_signature = signature

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

        # Startup only needs the selected skin. In lazy-discovery mode, parse
        # files in normal precedence order until it is found; menus explicitly
        # refresh the complete catalog when they are opened.
        if not skin_info and not self.available_skins:
            for skin_path in self._iter_skin_files():
                skin_data = self.loader.load_skin(skin_path)
                if not skin_data:
                    continue
                candidate = self._skin_info(skin_path, skin_data)
                self.available_skins.append(candidate)
                if candidate['name'] == skin_name:
                    skin_info = candidate
                    break

        if not skin_info:
            print(f"Skin not found: {skin_name}")
            return False

        # Load skin data (cached in loader)
        self.current_skin = skin_info['data']
        self.current_applier = SkinApplier(self.current_skin)
        self.current_skin_path = Path(skin_info['path'])  # Store path for editing
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
