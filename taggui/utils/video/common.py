"""Common utilities for video editing."""

import shutil
from pathlib import Path
from utils.sidecar import existing_json_sidecar_paths_for_media, sidecar_backup_path


def _backup_sidecar_json(input_path: Path) -> bool:
    """Backup JSON sidecars when present."""
    try:
        for json_path in existing_json_sidecar_paths_for_media(input_path):
            json_backup_path = sidecar_backup_path(json_path)
            if json_backup_path.exists():
                continue
            shutil.copy2(json_path, json_backup_path)
        return True
    except Exception:
        return False


def create_backup(input_path: Path) -> bool:
    """Create backup of original video and sidecar JSON when present."""
    backup_path = input_path.with_suffix(input_path.suffix + '.backup')
    if not backup_path.exists():
        try:
            shutil.copy2(input_path, backup_path)
        except Exception:
            return False

    return _backup_sidecar_json(input_path)
