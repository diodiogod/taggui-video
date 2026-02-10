"""Disk caching for generated thumbnails to speed up reloads."""

import hashlib
import shutil
import threading
from pathlib import Path
from PySide6.QtGui import QIcon, QPixmap
from utils.settings import settings, DEFAULT_SETTINGS


class ThumbnailCache:
    """Disk cache for thumbnail QIcons."""

    def __init__(self):
        """Initialize thumbnail cache directory."""
        # Check if caching is enabled
        self.enabled = settings.value('enable_thumbnail_cache',
                                     defaultValue=DEFAULT_SETTINGS['enable_thumbnail_cache'],
                                     type=bool)
        # Get cache location from settings (or use default)
        cache_location = settings.value('thumbnail_cache_location',
                                       defaultValue=DEFAULT_SETTINGS['thumbnail_cache_location'],
                                       type=str)

        if cache_location:
            new_cache_dir = Path(cache_location)
        else:
            new_cache_dir = Path.home() / '.taggui_cache' / 'thumbnails'

        # Check if cache location changed and migrate if needed
        old_cache_location = settings.value('_last_thumbnail_cache_location', type=str)
        if old_cache_location and old_cache_location != str(new_cache_dir):
            self._migrate_cache(Path(old_cache_location), new_cache_dir)

        # Save current location for next time
        settings.setValue('_last_thumbnail_cache_location', str(new_cache_dir))

        self.cache_dir = new_cache_dir

        if self.enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            print(f"[CACHE INIT] Thumbnail cache enabled: {self.cache_dir}")
            print(f"[CACHE INIT] Cache directory exists: {self.cache_dir.exists()}")
            # Clean up old PNG cache files (we use WebP now)
            self._cleanup_old_png_cache()
            # One-time purge of potentially corrupted cache entries from
            # the row-shift thumbnail bug (fixed in 330eadc).
            self._purge_corrupted_cache_v1()
        else:
            print("[CACHE INIT] Thumbnail cache DISABLED")

    def _purge_corrupted_cache_v1(self):
        """One-time purge of all cached thumbnails that may have been corrupted
        by the row-shift bug in paginated mode (fixed in commit 330eadc).

        Uses a settings flag so this only runs once per installation.
        """
        PURGE_KEY = '_thumbnail_cache_purge_v1'
        if settings.value(PURGE_KEY, False, type=bool):
            return  # Already purged

        if not self.cache_dir.exists():
            settings.setValue(PURGE_KEY, True)
            return

        try:
            webp_files = list(self.cache_dir.rglob('*.webp'))
            if webp_files:
                print(f'[CACHE] Purging {len(webp_files)} potentially corrupted cache entries (one-time fix)...')
                removed = 0
                for f in webp_files:
                    try:
                        f.unlink()
                        removed += 1
                    except Exception:
                        pass
                print(f'[CACHE] Purged {removed} entries. Cache will rebuild on demand.')
        except Exception as e:
            print(f'[CACHE] Purge failed: {e}')

        settings.setValue(PURGE_KEY, True)

    def _cleanup_old_png_cache(self):
        """Remove old PNG cache files (we use WebP now for better compression)."""
        CLEANUP_KEY = '_thumbnail_cache_png_cleanup_v1'
        if settings.value(CLEANUP_KEY, False, type=bool):
            return

        if not self.cache_dir.exists():
            settings.setValue(CLEANUP_KEY, True)
            return

        try:
            png_files = list(self.cache_dir.rglob('*.png'))
            if not png_files:
                settings.setValue(CLEANUP_KEY, True)
                return

            print(f'Cleaning up {len(png_files)} old PNG cache files...')
            removed = 0
            for png_file in png_files:
                try:
                    png_file.unlink()
                    removed += 1
                except Exception:
                    pass

            if removed > 0:
                print(f'Removed {removed} PNG files, cache will be rebuilt in WebP format')

        except Exception as e:
            print(f'Failed to cleanup PNG cache: {e}')
        finally:
            # Never retry on every startup; expensive cache walks can stall/crash workers.
            settings.setValue(CLEANUP_KEY, True)

    def _migrate_cache(self, old_dir: Path, new_dir: Path):
        """
        Migrate cache from old location to new location.

        Args:
            old_dir: Old cache directory
            new_dir: New cache directory
        """
        if not old_dir.exists():
            return  # Nothing to migrate

        try:
            print(f'Migrating thumbnail cache from {old_dir} to {new_dir}...')

            # Create new directory
            new_dir.mkdir(parents=True, exist_ok=True)

            # Count total files for progress (support both PNG and WebP)
            cache_files = list(old_dir.rglob('*.png')) + list(old_dir.rglob('*.webp'))
            total_files = len(cache_files)

            if total_files == 0:
                print('No cache files to migrate')
                return

            print(f'Moving {total_files} cached thumbnails...')

            moved = 0
            for old_file in cache_files:
                # Preserve subdirectory structure
                relative_path = old_file.relative_to(old_dir)
                new_file = new_dir / relative_path

                # Create subdirectory if needed
                new_file.parent.mkdir(parents=True, exist_ok=True)

                # Move file (faster than copy+delete)
                try:
                    shutil.move(str(old_file), str(new_file))
                    moved += 1

                    # Print progress every 100 files
                    if moved % 100 == 0:
                        print(f'Moved {moved}/{total_files} thumbnails...')
                except Exception as e:
                    print(f'Failed to move {old_file}: {e}')

            print(f'Cache migration complete: {moved}/{total_files} thumbnails moved')

            # Try to remove old directory if empty
            try:
                # Remove empty subdirectories
                for subdir in old_dir.iterdir():
                    if subdir.is_dir() and not any(subdir.iterdir()):
                        subdir.rmdir()

                # Remove main directory if empty
                if not any(old_dir.iterdir()):
                    old_dir.rmdir()
                    print(f'Removed old cache directory: {old_dir}')
            except Exception:
                pass  # Leave old directory if it's not empty

        except Exception as e:
            print(f'Cache migration failed: {e}')
            print('Cache will be rebuilt at new location')

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
        return cache_subdir / f"{cache_key}.webp"

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
        if not self.enabled:
            return None

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
        """Save thumbnail to cache from QIcon (DEPRECATED — prefer save_thumbnail_qimage)."""
        if not self.enabled or icon.isNull():
            return
        try:
            pixmap = icon.pixmap(size, size)
            if not pixmap.isNull():
                pixmap.save(str(self._get_cache_path(self._get_cache_key(file_path, mtime, size))), 'WEBP', quality=85)
        except Exception as e:
            print(f'[CACHE ERROR] Exception saving {file_path.name}: {type(e).__name__}: {e}')

    def save_thumbnail_qimage(self, file_path: Path, mtime: float, size: int, qimage):
        """Save thumbnail to cache from QImage (thread-safe, no QPixmap needed).

        Unlike save_thumbnail(), this method uses only QImage which is safe
        to call from any thread.  QPixmap operations are main-thread-only and
        cause GIL contention when used in worker threads.
        """
        if not self.enabled:
            return
        if qimage is None or qimage.isNull():
            return

        cache_key = self._get_cache_key(file_path, mtime, size)
        cache_path = self._get_cache_path(cache_key)

        try:
            result = qimage.save(str(cache_path), 'WEBP', quality=85)
            if not result:
                print(f"[CACHE ERROR] qimage.save() failed for: {file_path.name} -> {cache_path}")
        except Exception as e:
            print(f'[CACHE ERROR] Exception saving {file_path.name}: {type(e).__name__}: {e}')

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
                    if cache_file.suffix not in ['.png', '.webp']:
                        continue
                    age = current_time - cache_file.stat().st_mtime
                    if age > max_age_seconds:
                        cache_file.unlink()
        except Exception as e:
            print(f'Failed to clear old cache: {e}')


# Global singleton instance
_thumbnail_cache = None
_cache_lock = threading.Lock()


def get_thumbnail_cache() -> ThumbnailCache:
    """Get global thumbnail cache instance (thread-safe)."""
    global _thumbnail_cache
    if _thumbnail_cache is None:
        with _cache_lock:
            if _thumbnail_cache is None:
                _thumbnail_cache = ThumbnailCache()
    return _thumbnail_cache
