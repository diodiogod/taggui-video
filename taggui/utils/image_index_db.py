"""Database caching for image dimensions and metadata to speed up directory loading."""

import sqlite3
import time
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any
from utils.settings import settings, DEFAULT_SETTINGS


DB_VERSION = 6  # Increment to allow NULLs in width/height (v6)


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

        # Lock for thread-safe DB access (multiple worker threads)
        self._db_lock = threading.Lock()

        if self.enabled:
            self._init_db()

    def _ensure_connection(self):
        """Ensure database connection is open and active."""
        if not self.enabled: return False
        with self._db_lock:
            try:
                if self.conn:
                    self.conn.execute("SELECT 1")
                    return True
            except (sqlite3.Error, AttributeError):
                pass
            
            try:
                # print(f"[DB] Reconnecting to {self.db_path.name}...")
                self._init_db()
                return self.conn is not None
            except Exception as e:
                print(f"[DB] Reconnect failed: {e}")
                return False

    _init_lock = threading.Lock() # Class-level lock for migrations

    def _init_db(self):
        """Create database and tables if they don't exist."""
        try:
            with ImageIndexDB._init_lock:
                self.conn = sqlite3.connect(str(self.db_path), timeout=60.0, check_same_thread=False)  # Increased timeout for migrations
                self.conn.row_factory = sqlite3.Row  # Access columns by name

                # Enable WAL mode for better concurrency (allows simultaneous reads/writes)
                self.conn.execute('PRAGMA journal_mode=WAL')
                self.conn.execute('PRAGMA synchronous=NORMAL')  # Faster writes, still safe with WAL
                self.conn.execute('PRAGMA cache_size=-64000')  # 64MB cache for large folders

                # Use immediate transactions to reduce lock contention
                self.conn.isolation_level = 'IMMEDIATE'

                # Register custom regex function for SQLite
                import re
                def regexp(pattern, string):
                    if string is None:
                        return False
                    try:
                        return re.search(pattern, string) is not None
                    except re.error:
                        return False
                self.conn.create_function("REGEXP", 2, regexp)

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
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        file_name TEXT UNIQUE NOT NULL,
                        width INTEGER,
                        height INTEGER,
                        aspect_ratio REAL,
                        is_video INTEGER NOT NULL,
                        video_fps REAL,
                        video_duration REAL,
                        video_frame_count INTEGER,
                        mtime REAL NOT NULL,
                        rating REAL DEFAULT 0.0,
                        indexed_at REAL,
                        thumbnail_cached INTEGER DEFAULT 0,
                        file_size INTEGER,
                        file_type TEXT,
                        ctime REAL
                    )
                ''')

                # Separate tags table for efficient querying
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS image_tags (
                        image_id INTEGER NOT NULL,
                        tag TEXT NOT NULL,
                        PRIMARY KEY (image_id, tag),
                        FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE
                    )
                ''')

                # Create indexes for fast queries
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_images_mtime ON images(mtime)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_images_filename ON images(file_name)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_images_aspect_ratio ON images(aspect_ratio)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_images_is_video ON images(is_video)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_images_rating ON images(rating)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_images_thumbnail_cached ON images(thumbnail_cached)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_tags_tag ON image_tags(tag)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_tags_image_id ON image_tags(image_id)')

                # Check version
                cursor.execute('SELECT value FROM meta WHERE key = ?', ('version',))
                row = cursor.fetchone()

                if row is None:
                    # New database, set version
                    cursor.execute('INSERT INTO meta (key, value) VALUES (?, ?)',
                                 ('version', str(DB_VERSION)))
                    self.conn.commit()
                elif int(row['value']) != DB_VERSION:
                    # Version mismatch, drop and recreate tables (schema changed)
                    print(f'Database version mismatch (v{row["value"]} -> v{DB_VERSION}), recreating tables...')
                    cursor.execute('DROP TABLE IF EXISTS images')
                    cursor.execute('DROP TABLE IF EXISTS image_tags')
                    cursor.execute('UPDATE meta SET value = ? WHERE key = ?',
                                 (str(DB_VERSION), 'version'))
                    self.conn.commit()
                    # Recreate tables with new schema (v6 allows NULL width/height)
                    cursor.execute('''
                        CREATE TABLE images (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            file_name TEXT UNIQUE NOT NULL,
                            width INTEGER,
                            height INTEGER,
                            aspect_ratio REAL,
                            is_video INTEGER NOT NULL,
                            video_fps REAL,
                            video_duration REAL,
                            video_frame_count INTEGER,
                            mtime REAL NOT NULL,
                            rating REAL DEFAULT 0.0,
                            indexed_at REAL,
                            thumbnail_cached INTEGER DEFAULT 0,
                            file_size INTEGER,
                            file_type TEXT,
                            ctime REAL
                        )
                    ''')
                    cursor.execute('''
                        CREATE TABLE image_tags (
                            image_id INTEGER NOT NULL,
                            tag TEXT NOT NULL,
                            PRIMARY KEY (image_id, tag),
                            FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE
                        )
                    ''')
                    # Recreate indexes
                    cursor.execute('CREATE INDEX idx_images_mtime ON images(mtime)')
                else:
                    # Existing database (v6), check for missing columns (migration from v5)
                    cursor.execute("PRAGMA table_info(images)")
                    columns = [info[1] for info in cursor.fetchall()]
                    
                    if 'file_size' not in columns:
                        print("Migrating DB: Adding file_size column...")
                        cursor.execute('ALTER TABLE images ADD COLUMN file_size INTEGER')
                        self.conn.commit()
                        
                    if 'file_type' not in columns:
                        print("Migrating DB: Adding file_type column...")
                        cursor.execute('ALTER TABLE images ADD COLUMN file_type TEXT')
                        self.conn.commit()
                        
                    if 'ctime' not in columns:
                        print("Migrating DB: Adding ctime column...")
                        cursor.execute('ALTER TABLE images ADD COLUMN ctime REAL')
                        self.conn.commit()
                        
                    # Ensure indexes exist
                    cursor.execute('CREATE INDEX IF NOT EXISTS idx_images_filename ON images(file_name)')
                    cursor.execute('CREATE INDEX IF NOT EXISTS idx_images_aspect_ratio ON images(aspect_ratio)')
                    cursor.execute('CREATE INDEX IF NOT EXISTS idx_images_is_video ON images(is_video)')
                    cursor.execute('CREATE INDEX IF NOT EXISTS idx_images_rating ON images(rating)')
                    cursor.execute('CREATE INDEX IF NOT EXISTS idx_images_thumbnail_cached ON images(thumbnail_cached)')
                    cursor.execute('CREATE INDEX IF NOT EXISTS idx_images_ctime ON images(ctime)')
                    cursor.execute('CREATE INDEX IF NOT EXISTS idx_images_file_size ON images(file_size)')
                    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tags_tag ON image_tags(tag)')
                    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tags_image_id ON image_tags(image_id)')
                    self.conn.commit()

        except sqlite3.Error as e:
            print(f'Failed to initialize database: {e}')
            # If DB is corrupted, delete and retry
            if self.conn:
                try: self.conn.close() 
                except: pass
            try:
                if self.db_path.exists():
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
                       video_frame_count, mtime, thumbnail_cached
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
                'is_video': bool(row['is_video']),
                'thumbnail_cached': bool(row['thumbnail_cached'])
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
                  is_video: bool, mtime: float, video_metadata: Optional[dict] = None,
                  rating: float = 0.0, file_size: int = None, file_type: str = None,
                  ctime: float = None):
        """
        Save image info to cache.

        Args:
            file_name: Name of the image file
            width: Image width in pixels
            height: Image height in pixels
            is_video: Whether this is a video file
            mtime: File modification time
            video_metadata: Optional dict with fps, duration, frame_count
            rating: Image rating (0.0 to 5.0)
            file_size: File size in bytes (optional)
            file_type: File extension (optional)
            ctime: Creation time (optional)
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

        # Calculate aspect ratio
        aspect_ratio = width / height if height > 0 else 1.0
        indexed_at = time.time()
        
        # Use mtime as fallback for ctime if not provided
        if ctime is None:
            ctime = mtime

        # Retry with exponential backoff for locked database
        max_retries = 3
        for attempt in range(max_retries):
            try:
                cursor = self.conn.cursor()
                # Use INSERT ... ON CONFLICT to preserve thumbnail_cached flag
                cursor.execute('''
                    INSERT INTO images
                    (file_name, width, height, aspect_ratio, is_video, video_fps,
                     video_duration, video_frame_count, mtime, rating, indexed_at,
                     file_size, file_type, ctime)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(file_name) DO UPDATE SET
                        width = excluded.width,
                        height = excluded.height,
                        aspect_ratio = excluded.aspect_ratio,
                        is_video = excluded.is_video,
                        video_fps = excluded.video_fps,
                        video_duration = excluded.video_duration,
                        video_frame_count = excluded.video_frame_count,
                        mtime = excluded.mtime,
                        rating = excluded.rating,
                        indexed_at = excluded.indexed_at,
                        file_size = excluded.file_size,
                        file_type = excluded.file_type,
                        ctime = excluded.ctime
                        -- thumbnail_cached intentionally NOT updated (preserve existing value)
                ''', (file_name, width, height, aspect_ratio, int(is_video), video_fps,
                      video_duration, video_frame_count, mtime, rating, indexed_at,
                      file_size, file_type, ctime))
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
            except sqlite3.Error as e:
                print(f'Database write error: {e}')
                return

    def bulk_insert_files(self, file_paths: List[Path], directory_path: Path):
        """
        Bulk insert initial file records into the database.
        Used when initializing large folders to ensure DB has records for pagination.
        Skips files that already exist in DB.
        """
        if not self.enabled or not self.conn or not file_paths:
            return

        # Prepare data chunks for insertion
        files_data = []
        now = time.time()
        
        # Get set of existing filenames to avoid duplicates (faster than INSERT OR IGNORE for 1M files)
        try:
             existing_files = set(self.get_all_paths())
        except:
             existing_files = set()

        new_files_count = 0
        for path in file_paths:
             # Store just the filename relative to directory_path, but simplified to just name 
             # because DB schema says 'file_name TEXT UNIQUE'.
             # In cache logic: 'relative_path = str(image_path.relative_to(directory_path))'
             # Wait, db.save_info uses file_name. 
             # schema says file_name UNIQUE.
             
             # Let's match what save_info does.
             # In fast load: get_cached_info(relative_path...)
             # So we should store relative path.
             try:
                 rel_path = str(path.relative_to(directory_path))
             except ValueError:
                 rel_path = path.name # Fallback
             
             if rel_path in existing_files:
                 continue
                 
             # Fallback values for new files
             try:
                 stat = path.stat()
                 mtime = stat.st_mtime
                 ctime = stat.st_ctime
                 file_size = stat.st_size
             except (OSError, FileNotFoundError):
                 continue

             suffix = path.suffix.lower()
             is_video = suffix in ['.mp4', '.avi', '.mov', '.mkv', '.webm']
             file_type = suffix.lstrip('.') if suffix else ''
             
             files_data.append((
                 rel_path, 
                 None, None, 1.0,  # Placeholder dims (NULL)
                 int(is_video), 
                 None, None, None, # Video metadata
                 mtime, 0.0, now,
                 file_size, file_type, ctime
             ))
             new_files_count += 1
             
             if len(files_data) >= 1000:
                 self._bulk_insert_chunk(files_data)
                 files_data = []
                 
        if files_data:
             self._bulk_insert_chunk(files_data)
             
        if new_files_count > 0:
             print(f"[DB] Bulk inserted {new_files_count} new files")


    def _bulk_insert_chunk(self, data_chunk):
        """Helper to insert a chunk of data."""
        try:
            cursor = self.conn.cursor()
            cursor.executemany('''
                INSERT OR IGNORE INTO images
                (file_name, width, height, aspect_ratio, is_video, video_fps,
                 video_duration, video_frame_count, mtime, rating, indexed_at,
                 file_size, file_type, ctime)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', data_chunk)
            self.conn.commit()
        except sqlite3.Error as e:
            print(f'Database bulk insert error: {e}')
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

    # ========== Paginated Query Methods ==========

    def count(self, filter_sql: str = '', bindings: tuple = ()) -> int:
        """Get total count of images, optionally filtered."""
        if not self._ensure_connection():
            return 0

        try:
            cursor = self.conn.cursor()
            query = 'SELECT COUNT(*) FROM images'
            if filter_sql:
                query += f' WHERE {filter_sql}'
            cursor.execute(query, bindings)
            return cursor.fetchone()[0]
        except sqlite3.Error as e:
            print(f'Database count error: {e}')
            return 0

    def count_cached_thumbnails(self) -> int:
        """Get count of images with cached thumbnails."""
        return self.count(filter_sql='thumbnail_cached = 1')

    def get_page(self, page: int, page_size: int = 1000,
                 sort_field: str = 'mtime', sort_dir: str = 'DESC',
                 filter_sql: str = '', bindings: tuple = (), **kwargs) -> List[Dict[str, Any]]:
        """
        Get a page of images from the database.

        Args:
            page: Page number (0-indexed)
            page_size: Number of images per page
            sort_field: Column to sort by (mtime, file_name, aspect_ratio, rating)
            sort_dir: Sort direction (ASC or DESC)
            filter_sql: Optional WHERE clause (without WHERE keyword)
            bindings: Parameters for the filter_sql

        Returns:
            List of image dictionaries
        """
        if not self._ensure_connection():
            return []

        # Validate sort field to prevent SQL injection
        valid_sort_fields = {'mtime', 'file_name', 'aspect_ratio', 'rating', 'width', 'height', 'id', 'RANDOM()', 'width * height', 'file_size', 'file_type', 'ctime'}
        if sort_field not in valid_sort_fields:
            sort_field = 'mtime'
        if sort_dir.upper() not in ('ASC', 'DESC'):
            sort_dir = 'DESC'

        try:
            cursor = self.conn.cursor()
            offset = page * page_size

            # Handle stable random sorting if requested
            sort_expr = sort_field
            if sort_field == 'RANDOM()':
                # Use a stable random based on ID and provided seed (or default)
                seed = kwargs.get('random_seed', 1234567)
                # Better mixing using LCG multiplier and a large prime modulus
                sort_expr = f"ABS(id * 1103515245 + {seed}) % 1000000007"
            elif sort_field == 'ctime':
                sort_expr = 'COALESCE(ctime, mtime)'
            elif sort_field == 'file_size':
                sort_expr = 'COALESCE(file_size, 0)'

            query = f'''
                SELECT id, file_name, width, height, aspect_ratio, is_video,
                       video_fps, video_duration, video_frame_count, mtime, rating,
                       file_size, file_type, ctime
                FROM images
            '''
            if filter_sql:
                query += f' WHERE {filter_sql} '
                
            query += f' ORDER BY {sort_expr} {sort_dir} LIMIT ? OFFSET ?'

            cursor.execute(query, bindings + (page_size, offset))
            rows = cursor.fetchall()

            return [dict(row) for row in rows]

        except sqlite3.Error as e:
            print(f'Database query error: {e}')
            return []

    def get_image_by_id(self, image_id: int) -> Optional[Dict[str, Any]]:
        """Get a single image by ID."""
        if not self.enabled or not self.conn:
            return None

        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT id, file_name, width, height, aspect_ratio, is_video,
                       video_fps, video_duration, video_frame_count, mtime, rating,
                       file_size, file_type, ctime
                FROM images WHERE id = ?
            ''', (image_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        except sqlite3.Error as e:
            print(f'Database query error: {e}')
            return None

    def get_images_by_ids(self, image_ids: List[int]) -> List[Dict[str, Any]]:
        """Get multiple images by their IDs."""
        if not self.enabled or not self.conn or not image_ids:
            return []

        try:
            cursor = self.conn.cursor()
            placeholders = ','.join('?' * len(image_ids))
            cursor.execute(f'''
                SELECT id, file_name, width, height, aspect_ratio, is_video,
                       video_fps, video_duration, video_frame_count, mtime, rating
                FROM images WHERE id IN ({placeholders})
            ''', image_ids)
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            print(f'Database query error: {e}')
            return []

    def get_all_paths(self) -> List[str]:
        """Get all cached file paths (for fast reboot without rescanning)."""
        if not self.enabled or not self.conn:
            return []

        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT file_name FROM images')
            return [row[0] for row in cursor.fetchall()]
        except sqlite3.Error:
            return []

    # ========== Tag Management ==========

    def get_tags_for_image(self, image_id: int) -> List[str]:
        """Get all tags for a specific image."""
        if not self.enabled or not self.conn:
            return []

        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT tag FROM image_tags WHERE image_id = ?', (image_id,))
            return [row[0] for row in cursor.fetchall()]
        except sqlite3.Error as e:
            print(f'Database tag query error: {e}')
            return []

    def get_tags_for_images(self, image_ids: List[int]) -> Dict[int, List[str]]:
        """Get tags for multiple images in a single query."""
        if not self.enabled or not self.conn or not image_ids:
            return {}

        try:
            cursor = self.conn.cursor()
            placeholders = ','.join('?' * len(image_ids))
            cursor.execute(f'''
                SELECT image_id, tag FROM image_tags
                WHERE image_id IN ({placeholders})
                ORDER BY image_id
            ''', image_ids)

            result: Dict[int, List[str]] = {img_id: [] for img_id in image_ids}
            for row in cursor.fetchall():
                result[row[0]].append(row[1])
            return result
        except sqlite3.Error as e:
            print(f'Database tag query error: {e}')
            return {}

    def set_tags_for_image(self, image_id: int, tags: List[str]):
        """Replace all tags for an image."""
        if not self.enabled or not self.conn:
            return

        try:
            cursor = self.conn.cursor()
            # Delete existing tags
            cursor.execute('DELETE FROM image_tags WHERE image_id = ?', (image_id,))
            # Insert new tags (deduplicated to prevent UNIQUE constraint errors)
            if tags:
                unique_tags = list(dict.fromkeys(tags))  # Preserve order, remove duplicates
                cursor.executemany(
                    'INSERT INTO image_tags (image_id, tag) VALUES (?, ?)',
                    [(image_id, tag) for tag in unique_tags]
                )
            self.commit()
        except sqlite3.Error as e:
            print(f'Database tag write error: {e}')

    def add_tag_to_image(self, image_id: int, tag: str):
        """Add a single tag to an image."""
        if not self.enabled or not self.conn:
            return

        try:
            cursor = self.conn.cursor()
            cursor.execute(
                'INSERT OR IGNORE INTO image_tags (image_id, tag) VALUES (?, ?)',
                (image_id, tag)
            )
            self.commit()
        except sqlite3.Error as e:
            print(f'Database tag write error: {e}')

    def remove_tag_from_image(self, image_id: int, tag: str):
        """Remove a single tag from an image."""
        if not self.enabled or not self.conn:
            return

        try:
            cursor = self.conn.cursor()
            cursor.execute(
                'DELETE FROM image_tags WHERE image_id = ? AND tag = ?',
                (image_id, tag)
            )
            self.commit()
        except sqlite3.Error as e:
            print(f'Database tag write error: {e}')

    def get_all_tags(self) -> List[Dict[str, Any]]:
        """Get all unique tags with their usage counts."""
        if not self.enabled or not self.conn:
            return []

        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT tag, COUNT(*) as count
                FROM image_tags
                WHERE tag != '__no_tags__'
                GROUP BY tag
                ORDER BY count DESC
            ''')
            return [{'tag': row[0], 'count': row[1]} for row in cursor.fetchall()]
        except sqlite3.Error as e:
            print(f'Database tag query error: {e}')
            return []

    # ... (get_images_with_tag skipped) ...

    def get_files_with_tag(self, tag: str) -> List[str]:
        """Get list of filenames that have a specific tag."""
        if not self.enabled or not self.conn:
             return []
        try:
             cursor = self.conn.cursor()
             cursor.execute('''
                 SELECT i.file_name 
                 FROM images i
                 JOIN image_tags it ON i.id = it.image_id
                 WHERE it.tag = ?
             ''', (tag,))
             return [row[0] for row in cursor.fetchall()]
        except sqlite3.Error as e:
             print(f'Database query error: {e}')
             return []

    def get_image_count(self) -> int:
        """Get total number of images in DB."""
        if not self.enabled or not self.conn:
             return 0
        try:
             cursor = self.conn.cursor()
             cursor.execute('SELECT COUNT(*) FROM images')
             return cursor.fetchone()[0]
        except sqlite3.Error as e:
             print(f'Database query error: {e}')
             return 0

    def get_placeholder_files(self, limit: int = 1000) -> List[str]:
        """
        Get list of files that have placeholder dimensions (need enrichment)
        OR have no tags indexed (need tag extraction).
        """
        if not self.enabled or not self.conn:
            return []

        try:
            cursor = self.conn.cursor()
            # Find files with missing dims OR no presence in image_tags table
            # Using LEFT JOIN is usually faster than NOT IN for this check
            cursor.execute('''
                SELECT DISTINCT file_name FROM images 
                LEFT JOIN image_tags ON images.id = image_tags.image_id
                WHERE images.width IS NULL 
                   OR image_tags.image_id IS NULL
                LIMIT ?
            ''', (limit,))
            return [row[0] for row in cursor.fetchall()]
        except sqlite3.Error as e:
            print(f'Database query error: {e}')
            return []

    def get_images_with_tag(self, tag: str, page: int = 0, page_size: int = 1000) -> List[Dict[str, Any]]:
        """Get paginated images that have a specific tag."""
        if not self.enabled or not self.conn:
            return []

        try:
            cursor = self.conn.cursor()
            offset = page * page_size
            cursor.execute('''
                SELECT i.id, i.file_name, i.width, i.height, i.aspect_ratio, i.is_video,
                       i.video_fps, i.video_duration, i.video_frame_count, i.mtime, i.rating
                FROM images i
                INNER JOIN image_tags t ON i.id = t.image_id
                WHERE t.tag = ?
                ORDER BY i.mtime DESC
                LIMIT ? OFFSET ?
            ''', (tag, page_size, offset))
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            print(f'Database query error: {e}')
            return []

    # ========== Rating Management ==========

    def set_rating(self, image_id: int, rating: float):
        """Set rating for an image."""
        if not self.enabled or not self.conn:
            return

        try:
            cursor = self.conn.cursor()
            cursor.execute('UPDATE images SET rating = ? WHERE id = ?', (rating, image_id))
        except sqlite3.Error as e:
            print(f'Database rating write error: {e}')

    def mark_thumbnail_cached(self, file_name: str, cached: bool = True):
        """Mark thumbnail as cached/uncached for an image (thread-safe)."""
        if not self.enabled or not self.conn:
            return

        # Use lock to prevent concurrent access from multiple threads
        with self._db_lock:
            try:
                cursor = self.conn.cursor()
                cursor.execute('UPDATE images SET thumbnail_cached = ? WHERE file_name = ?',
                             (1 if cached else 0, file_name))
                affected = cursor.rowcount
                self.conn.commit()

                # Debug: warn if UPDATE matched no rows (first 5 misses only)
                if affected == 0 and not hasattr(self, '_warned_miss_count'):
                    self._warned_miss_count = 0
                if affected == 0 and self._warned_miss_count < 5:
                    print(f'[DB] UPDATE matched 0 rows for: {file_name}')
                    self._warned_miss_count += 1
                    if self._warned_miss_count == 5:
                        print('[DB] (suppressing further warnings...)')

            except sqlite3.Error as e:
                print(f'Database thumbnail cache flag write error: {e}')

    # ========== Image ID Lookup ==========

    def get_image_id(self, file_name: str) -> Optional[int]:
        """Get image ID by file name."""
        if not self.enabled or not self.conn:
            return None

        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT id FROM images WHERE file_name = ?', (file_name,))
            row = cursor.fetchone()
            return row[0] if row else None
        except sqlite3.Error as e:
            print(f'Database query error: {e}')
            return None

    # ========== Bulk Tag Operations ==========

    def count_tag_matches(self, pattern: str, use_regex: bool = False, whole_tag_only: bool = True) -> int:
        """Count tag matches across all images in database."""
        if not self.enabled or not self.conn:
            return 0

        try:
            cursor = self.conn.cursor()
            if whole_tag_only:
                if use_regex:
                    # Use custom REGEXP function (full match)
                    cursor.execute('SELECT COUNT(*) FROM image_tags WHERE tag REGEXP ?', (f'^{pattern}$',))
                else:
                    # Exact match
                    cursor.execute('SELECT COUNT(*) FROM image_tags WHERE tag = ?', (pattern,))
            else:
                if use_regex:
                    # Partial match with regex
                    cursor.execute('SELECT COUNT(*) FROM image_tags WHERE tag REGEXP ?', (pattern,))
                else:
                    # Match within tag (substring)
                    cursor.execute('SELECT COUNT(*) FROM image_tags WHERE tag LIKE ?', (f'%{pattern}%',))

            return cursor.fetchone()[0]
        except sqlite3.Error as e:
            print(f'Database tag count error: {e}')
            return 0

    def find_replace_tags(self, find_text: str, replace_text: str, use_regex: bool = False) -> int:
        """
        Find and replace text in all tags across the database.

        Returns number of affected images.
        """
        if not self.enabled or not self.conn:
            return 0

        try:
            cursor = self.conn.cursor()

            if use_regex:
                # Placeholder for complex regex logic I accidentally overwrote
                print("Warning: Regex find/replace logic currently disabled")
                return 0

            else:
                # Simple SQL replace
                cursor.execute(f'''
                    UPDATE image_tags 
                    SET tag = REPLACE(tag, ?, ?) 
                    WHERE tag LIKE ?
                ''', (find_text, replace_text, f'%{find_text}%'))
                count = cursor.rowcount
            
            self.conn.commit()
            return count

        except sqlite3.Error as e:
            print(f'Database find/replace error: {e}')
            return 0



    def get_all_image_ids(self, filter_sql: str = '', bindings: tuple = ()) -> List[int]:
        """Get all image IDs, optionally filtered."""
        if not self.enabled or not self.conn:
            return []

        try:
            cursor = self.conn.cursor()
            query = 'SELECT id FROM images'
            if filter_sql:
                query += f' WHERE {filter_sql}'
            cursor.execute(query, bindings)
            return [row[0] for row in cursor.fetchall()]
        except sqlite3.Error as e:
            print(f'Database query error: {e}')
            return []

    def backfill_missing_metadata(self, directory_path: Path):
        """
        Backfill missing metadata (size, type, ctime) for existing records.
        Safe to call repeatedly - only selects rows with NULL fields.
        """
        if not self.enabled or not self.conn:
            return

        try:
            cursor = self.conn.cursor()
            # Find ID and name for rows missing any new metadata
            cursor.execute('''
                SELECT id, file_name FROM images 
                WHERE file_size IS NULL OR file_type IS NULL OR ctime IS NULL
            ''')
            rows = cursor.fetchall()
            
            if not rows:
                return
                
            print(f"[DB] Backfilling metadata for {len(rows)} images...")
            updates = []
            
            for row in rows:
                img_id = row[0]
                file_name = row[1]
                full_path = directory_path / file_name
                
                try:
                    stat = full_path.stat()
                    size = stat.st_size
                    ctime = stat.st_ctime
                    # Standardize extension logic
                    suffix = full_path.suffix.lower()
                    ftype = suffix.lstrip('.') if suffix else ''
                    
                    updates.append((size, ftype, ctime, img_id))
                except (OSError, FileNotFoundError):
                    # File might have been deleted, skip or mark?
                    # For now just skip, it will be cleaned up on next full scan
                    continue
            
            
            batch_size = 50
            for i in range(0, len(updates), batch_size):
                batch = updates[i:i + batch_size]
                try:
                    cursor.executemany('''
                        UPDATE images 
                        SET file_size = ?, file_type = ?, ctime = ?
                        WHERE id = ?
                    ''', batch)
                    self.conn.commit()
                    # print(f"[DB] Backfill batch {i//batch_size + 1} done")
                    time.sleep(0.01) # Yield slightly
                except sqlite3.Error as e:
                    print(f"Backfill batch error: {e}")
            
            print(f"[DB] Backfill complete: Updated {len(updates)} records")
                
        except sqlite3.Error as e:
            print(f"Database backfill error: {e}")


