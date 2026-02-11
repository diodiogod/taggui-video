"""Skin loader - reads and validates skin files."""

import re
import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from .schema import SkinSchema


class SkinLoader:
    """Loads and validates skin files."""

    def __init__(self):
        self.loaded_skins: Dict[str, Dict[str, Any]] = {}

    def load_skin(self, skin_path: Path) -> Optional[Dict[str, Any]]:
        """Load and validate a skin file.

        Args:
            skin_path: Path to YAML skin file

        Returns:
            Validated skin dict or None if invalid
        """
        try:
            with open(skin_path, 'r', encoding='utf-8') as f:
                skin_data = yaml.safe_load(f)

            if not skin_data:
                print(f"Empty skin file: {skin_path}")
                return None

            # Validate structure
            valid, error = SkinSchema.validate_structure(skin_data)
            if not valid:
                print(f"Invalid skin {skin_path.name}: {error}")
                return None

            # Resolve token references
            resolved_skin = self._resolve_tokens(skin_data)

            # Cache loaded skin
            self.loaded_skins[skin_path.stem] = resolved_skin

            return resolved_skin

        except yaml.YAMLError as e:
            print(f"YAML parse error in {skin_path.name}: {e}")
            return None
        except FileNotFoundError:
            print(f"Skin file not found: {skin_path}")
            return None
        except Exception as e:
            print(f"Error loading skin {skin_path.name}: {e}")
            return None

    def _resolve_tokens(self, skin_data: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve token references like {tokens.colors.primary}.

        Args:
            skin_data: Raw skin dictionary

        Returns:
            Skin data with resolved token references
        """
        tokens = skin_data.get('tokens', {})

        def resolve_value(value: Any) -> Any:
            """Recursively resolve token references in values."""
            if isinstance(value, str):
                # Find all {tokens.path.to.value} references
                pattern = r'\{tokens\.([^}]+)\}'
                matches = re.findall(pattern, value)

                # If no token references, return as-is
                if not matches:
                    return value

                # Resolve each token reference
                for match in matches:
                    # Navigate token path (e.g., "colors.primary")
                    parts = match.split('.')
                    token_value = tokens

                    for part in parts:
                        if isinstance(token_value, dict) and part in token_value:
                            token_value = token_value[part]
                        else:
                            # Token not found, leave unresolved
                            print(f"Warning: Token reference not found: {match}")
                            token_value = None
                            break

                    if token_value is not None:
                        # Successfully resolved token
                        placeholder = f"{{tokens.{match}}}"

                        # If the entire value is just the token reference, return the actual type
                        if value == placeholder:
                            return token_value

                        # Otherwise, replace within the string
                        value = value.replace(placeholder, str(token_value))

                return value

            elif isinstance(value, dict):
                return {k: resolve_value(v) for k, v in value.items()}

            elif isinstance(value, list):
                return [resolve_value(item) for item in value]

            else:
                return value

        # Create a copy and resolve all values EXCEPT the tokens section itself
        resolved = {}
        for key, value in skin_data.items():
            if key == 'tokens':
                # Keep tokens as-is, don't resolve them against themselves
                resolved[key] = value
            else:
                # Resolve token references in other sections
                resolved[key] = resolve_value(value)

        return resolved

    def get_skin_value(
        self,
        skin_data: Dict[str, Any],
        path: str,
        default: Any = None
    ) -> Any:
        """Get a value from skin data using dot-notation path.

        Args:
            skin_data: Loaded skin dictionary
            path: Dot-notation path (e.g., "video_player.styling.button_size")
            default: Default value if path not found

        Returns:
            Value at path or default
        """
        parts = path.split('.')
        value = skin_data

        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return default

        return value

    def list_available_skins(self, skin_dirs: list[Path]) -> list[Dict[str, Any]]:
        """List all available skins from directories.

        Args:
            skin_dirs: List of directories to search

        Returns:
            List of skin metadata dicts (name, author, version, path)
        """
        skins = []

        for skin_dir in skin_dirs:
            if not skin_dir.exists():
                continue

            for skin_file in skin_dir.glob('*.yaml'):
                skin_data = self.load_skin(skin_file)
                if skin_data:
                    skins.append({
                        'name': skin_data.get('name', skin_file.stem),
                        'author': skin_data.get('author', 'Unknown'),
                        'version': skin_data.get('version', '1.0'),
                        'path': skin_file,
                        'data': skin_data
                    })

        return skins
