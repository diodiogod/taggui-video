"""Common utilities for video editing."""

import shutil
from pathlib import Path


def create_backup(input_path: Path) -> bool:
    """Create backup of original video with .backup extension."""
    backup_path = input_path.with_suffix(input_path.suffix + '.backup')
    if not backup_path.exists():
        try:
            shutil.copy2(input_path, backup_path)
            return True
        except Exception:
            return False
    return True  # Backup already exists
