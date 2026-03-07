"""Common utilities for video editing."""

import shutil
from pathlib import Path


def _backup_sidecar_json(input_path: Path) -> bool:
    """Backup sidecar JSON when present."""
    json_path = input_path.with_suffix('.json')
    if not json_path.exists():
        return True

    json_backup_path = json_path.with_suffix(json_path.suffix + '.backup')
    if json_backup_path.exists():
        return True

    try:
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
