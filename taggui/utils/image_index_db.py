"""Database caching for image dimensions and metadata to speed up directory loading."""

import sqlite3
import time
from pathlib import Path
from typing import Optional
from utils.settings import settings, DEFAULT_SETTINGS


DB_VERSION = 2  # Increment to force cache invalidation (v2: use relative paths instead of filenames)


class ImageIndexDB:
    """SQLite database for caching image dimensions and metadata."""

    def __init__(self, directory_path: Path):
        """Initialize database for given directory."""
        # Check if caching is enabled
        self.enabled = settings.value('enable_dimension_cache',
                                     defaultValue=DEFAULT_SETTINGS['enable_dimension_cache'],
                                     type=bool)

        self.db_path = directory_path / '.taggui_index.db'
        self.conn = None

        if self.enabled:
            self._init_db()

    def _init_db(self):
        """Create database and tables if they don't exist."""
        try:
            self.conn = sqlite3.connect(str(self.db_path), timeout=30.0)  # 30s timeout for large folders
            self.conn.row_factory = sqlite3.Row  # Access columns by name

            # Enable WAL mode for better concurrency (allows simultaneous reads/writes)
            self.conn.execute('PRAGMA journal_mode=WAL')
            self.conn.execute('PRAGMA synchronous=NORMAL')  # Faster writes, still safe with WAL
            self.conn.execute('PRAGMA cache_size=-64000')  # 64MB cache for large folders

            # Use immediate transactions to reduce lock contention
            self.conn.isolation_level = 'IMMEDIATE'

            cursor = self.conn.cursor()

            # Create schema
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS images (
                    file_name TEXT PRIMARY KEY,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    is_video INTEGER NOT NULL,
                    video_fps REAL,
                    video_duration REAL,
                    video_frame_count INTEGER,
                    mtime REAL NOT NULL
                )
            ''')

            # Check version
            cursor.execute('SELECT value FROM meta WHERE key = ?', ('version',))
            row = cursor.fetchone()

            if row is None:
                # New database, set version
                cursor.execute('INSERT INTO meta (key, value) VALUES (?, ?)',
                             ('version', str(DB_VERSION)))
                self.conn.commit()
            elif int(row['value']) != DB_VERSION:
                # Version mismatch, clear database
                cursor.execute('DELETE FROM images')
                cursor.execute('UPDATE meta SET value = ? WHERE key = ?',
                             (str(DB_VERSION), 'version'))
                self.conn.commit()

        except sqlite3.Error as e:
            print(f'Failed to initialize database: {e}')
            # If DB is corrupted, delete and retry
            if self.conn:
                self.conn.close()
            try:
                self.db_path.unlink()
                self._init_db()  # Retry
            except Exception:
                pass

    def get_cached_info(self, file_name: str, mtime: float) -> Optional[dict]:
        """
        Get cached image info if it exists and is up-to-date.

        Args:
            file_name: Name of the image file
            mtime: Current modification time of the file

        Returns:
            Dict with dimensions and metadata, or None if cache miss/stale
        """
        if not self.enabled or not self.conn:
            return None

        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT width, height, is_video, video_fps, video_duration,
                       video_frame_count, mtime
                FROM images
                WHERE file_name = ?
            ''', (file_name,))

            row = cursor.fetchone()
            if row is None:
                return None

            # Check if file was modified since cache
            if abs(row['mtime'] - mtime) > 0.1:  # Allow 0.1s tolerance
                return None

            result = {
                'dimensions': (row['width'], row['height']),
                'is_video': bool(row['is_video'])
            }

            if row['is_video']:
                result['video_metadata'] = {
                    'fps': row['video_fps'],
                    'duration': row['video_duration'],
                    'frame_count': row['video_frame_count']
                }

            return result

        except sqlite3.Error as e:
            print(f'Database read error: {e}')
            return None

    def save_info(self, file_name: str, width: int, height: int,
                  is_video: bool, mtime: float, video_metadata: Optional[dict] = None):
        """
        Save image info to cache.

        Args:
            file_name: Name of the image file
            width: Image width in pixels
            height: Image height in pixels
            is_video: Whether this is a video file
            mtime: File modification time
            video_metadata: Optional dict with fps, duration, frame_count
        """
        if not self.enabled or not self.conn:
            return

        video_fps = None
        video_duration = None
        video_frame_count = None

        if is_video and video_metadata:
            video_fps = video_metadata.get('fps')
            video_duration = video_metadata.get('duration')
            video_frame_count = video_metadata.get('frame_count')

        # Retry with exponential backoff for locked database
        max_retries = 3
        for attempt in range(max_retries):
            try:
                cursor = self.conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO images
                    (file_name, width, height, is_video, video_fps, video_duration,
                     video_frame_count, mtime)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (file_name, width, height, int(is_video), video_fps,
                      video_duration, video_frame_count, mtime))
                return  # Success

            except sqlite3.OperationalError as e:
                if 'locked' in str(e).lower() and attempt < max_retries - 1:
                    # Database locked, retry with backoff
                    time.sleep(0.1 * (2 ** attempt))  # 0.1s, 0.2s, 0.4s
                    continue
                print(f'Database write error: {e}')
                return

            except sqlite3.Error as e:
                print(f'Database write error: {e}')
                return

    def commit(self):
        """Commit pending transactions."""
        if not self.conn:
            return

        # Retry with exponential backoff for locked database
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self.conn.commit()
                return  # Success

            except sqlite3.OperationalError as e:
                if 'locked' in str(e).lower() and attempt < max_retries - 1:
                    # Database locked, retry with backoff
                    time.sleep(0.1 * (2 ** attempt))  # 0.1s, 0.2s, 0.4s
                    continue
                print(f'Database commit error: {e}')
                return

            except sqlite3.Error as e:
                print(f'Database commit error: {e}')
                return

    def close(self):
        """Close database connection."""
        if self.conn:
            try:
                self.conn.commit()
                self.conn.close()
            except sqlite3.Error:
                pass
            self.conn = None

    def __del__(self):
        """Ensure connection is closed on deletion."""
        self.close()
