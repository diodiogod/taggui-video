"""Disk caching for generated thumbnails to speed up reloads."""

import hashlib
from pathlib import Path
from PySide6.QtGui import QIcon, QPixmap


class ThumbnailCache:
    """Disk cache for thumbnail QIcons."""

    def __init__(self):
        """Initialize thumbnail cache directory."""
        self.cache_dir = Path.home() / '.taggui_cache' / 'thumbnails'
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_key(self, file_path: Path, mtime: float, size: int) -> str:
        """
        Generate cache key from file path, modification time, and thumbnail size.

        Args:
            file_path: Path to the image file
            mtime: File modification time
            size: Thumbnail size in pixels

        Returns:
            Cache key as hex string
        """
        # Use path + mtime + size as key (so modified files get new thumbnails)
        key_string = f"{file_path}_{mtime}_{size}"
        return hashlib.md5(key_string.encode()).hexdigest()

    def _get_cache_path(self, cache_key: str) -> Path:
        """Get cache file path for a given key."""
        # Organize into subdirectories by first 2 chars to avoid too many files in one dir
        subdir = cache_key[:2]
        cache_subdir = self.cache_dir / subdir
        cache_subdir.mkdir(exist_ok=True)
        return cache_subdir / f"{cache_key}.png"

    def get_thumbnail(self, file_path: Path, mtime: float, size: int) -> QIcon | None:
        """
        Get cached thumbnail if it exists.

        Args:
            file_path: Path to the image file
            mtime: File modification time
            size: Thumbnail size in pixels

        Returns:
            Cached QIcon or None if cache miss
        """
        cache_key = self._get_cache_key(file_path, mtime, size)
        cache_path = self._get_cache_path(cache_key)

        if not cache_path.exists():
            return None

        try:
            pixmap = QPixmap(str(cache_path))
            if pixmap.isNull():
                # Corrupted cache file, delete it
                cache_path.unlink()
                return None
            return QIcon(pixmap)
        except Exception:
            # Failed to load, delete corrupted cache
            try:
                cache_path.unlink()
            except Exception:
                pass
            return None

    def save_thumbnail(self, file_path: Path, mtime: float, size: int, icon: QIcon):
        """
        Save thumbnail to cache.

        Args:
            file_path: Path to the image file
            mtime: File modification time
            size: Thumbnail size in pixels
            icon: QIcon to cache
        """
        if icon.isNull():
            return

        cache_key = self._get_cache_key(file_path, mtime, size)
        cache_path = self._get_cache_path(cache_key)

        try:
            # Get pixmap from icon and save as PNG
            pixmap = icon.pixmap(size, size)
            if not pixmap.isNull():
                pixmap.save(str(cache_path), 'PNG', quality=95)
        except Exception as e:
            print(f'Failed to save thumbnail cache: {e}')

    def clear_old_cache(self, max_age_days: int = 30):
        """
        Clear cache entries older than max_age_days.

        Args:
            max_age_days: Delete cached thumbnails older than this many days
        """
        import time
        max_age_seconds = max_age_days * 24 * 60 * 60
        current_time = time.time()

        try:
            for subdir in self.cache_dir.iterdir():
                if not subdir.is_dir():
                    continue
                for cache_file in subdir.iterdir():
                    if cache_file.suffix != '.png':
                        continue
                    age = current_time - cache_file.stat().st_mtime
                    if age > max_age_seconds:
                        cache_file.unlink()
        except Exception as e:
            print(f'Failed to clear old cache: {e}')


# Global singleton instance
_thumbnail_cache = None


def get_thumbnail_cache() -> ThumbnailCache:
    """Get global thumbnail cache instance."""
    global _thumbnail_cache
    if _thumbnail_cache is None:
        _thumbnail_cache = ThumbnailCache()
    return _thumbnail_cache
