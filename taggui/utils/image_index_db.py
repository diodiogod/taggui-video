"""Database caching for image dimensions and metadata to speed up directory loading."""

import json
import sqlite3
import shutil
import time
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any
from utils.settings import settings, DEFAULT_SETTINGS


DB_VERSION = 7  # v7 adds searchable image_markings index


class ImageIndexDB:
    """SQLite database for caching image dimensions and metadata."""

    DB_DIR_NAME = '.taggui'
    DB_FILE_NAME = 'index.db'
    LEGACY_DB_NAME = '.taggui_index.db'
    BUNDLE_SUFFIXES = ('', '-wal', '-shm')
    INTERNAL_DIR_NAMES = {DB_DIR_NAME, '.taggui_profiles'}
    RATING_MIGRATION_DONE_KEY = 'rating_migration_v1_done'
    RATING_MIGRATION_LAST_ID_KEY = 'rating_migration_v1_last_id'
    MARKING_MIGRATION_DONE_KEY = 'marking_migration_v1_done'
    MARKING_MIGRATION_LAST_ID_KEY = 'marking_migration_v1_last_id'

    @classmethod
    def db_dir_path(cls, directory_path: Path) -> Path:
        return Path(directory_path) / cls.DB_DIR_NAME

    @classmethod
    def db_base_path(cls, directory_path: Path) -> Path:
        return cls.db_dir_path(directory_path) / cls.DB_FILE_NAME

    @classmethod
    def legacy_db_base_path(cls, directory_path: Path) -> Path:
        return Path(directory_path) / cls.LEGACY_DB_NAME

    @classmethod
    def bundle_paths_for_base(cls, base_path: Path) -> list[Path]:
        base_str = str(base_path)
        return [Path(base_str + suffix) for suffix in cls.BUNDLE_SUFFIXES]

    @classmethod
    def active_bundle_paths(cls, directory_path: Path) -> list[Path]:
        return cls.bundle_paths_for_base(cls.db_base_path(directory_path))

    @classmethod
    def legacy_bundle_paths(cls, directory_path: Path) -> list[Path]:
        return cls.bundle_paths_for_base(cls.legacy_db_base_path(directory_path))

    @classmethod
    def all_bundle_paths(cls, directory_path: Path, include_legacy: bool = True) -> list[Path]:
        paths = cls.active_bundle_paths(directory_path)
        if include_legacy:
            paths.extend(cls.legacy_bundle_paths(directory_path))
        return paths

    @classmethod
    def delete_database_bundle(cls, directory_path: Path, include_legacy: bool = True) -> list[Path]:
        """Delete current DB bundle files (and optional legacy bundle files)."""
        removed: list[Path] = []
        for path in cls.all_bundle_paths(directory_path, include_legacy=include_legacy):
            if not path.exists():
                continue
            try:
                path.unlink()
                removed.append(path)
            except Exception:
                continue

        db_dir = cls.db_dir_path(directory_path)
        try:
            if db_dir.exists() and db_dir.is_dir() and not any(db_dir.iterdir()):
                db_dir.rmdir()
        except Exception:
            pass

        return removed

    @classmethod
    def total_database_bundle_size(cls, directory_path: Path, include_legacy: bool = True) -> int:
        """Return total bytes used by the DB bundle for one dataset directory."""
        total_size = 0
        for path in cls.all_bundle_paths(directory_path, include_legacy=include_legacy):
            if not path.exists():
                continue
            try:
                total_size += path.stat().st_size
            except Exception:
                continue
        return total_size

    def __init__(self, directory_path: Path):
        """Initialize database for given directory."""
        # Check if caching is enabled
        self.enabled = settings.value('enable_dimension_cache',
                                     defaultValue=DEFAULT_SETTINGS['enable_dimension_cache'],
                                     type=bool)

        self._directory_path = Path(directory_path)
        self.db_dir = self.db_dir_path(self._directory_path)
        self.db_path = self.db_base_path(self._directory_path)
        self.legacy_db_path = self.legacy_db_base_path(self._directory_path)
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

    @staticmethod
    def _normalize_bindings(bindings) -> tuple:
        """Normalize SQL bindings into a tuple."""
        if bindings is None:
            return ()
        if isinstance(bindings, tuple):
            return bindings
        if isinstance(bindings, list):
            return tuple(bindings)
        return (bindings,)

    _init_lock = threading.Lock() # Class-level lock for migrations

    @staticmethod
    def _create_image_markings_schema(cursor):
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS image_markings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_id INTEGER NOT NULL,
                label TEXT NOT NULL,
                type TEXT NOT NULL,
                confidence REAL DEFAULT 1.0,
                x INTEGER,
                y INTEGER,
                width INTEGER,
                height INTEGER,
                FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_markings_image_id ON image_markings(image_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_markings_label ON image_markings(label)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_markings_type ON image_markings(type)')

    def _init_db(self):
        """Create database and tables if they don't exist."""
        try:
            with ImageIndexDB._init_lock:
                self._prepare_db_location()
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

                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS directories (
                        dir_path TEXT PRIMARY KEY,
                        mtime REAL NOT NULL,
                        scanned_at REAL NOT NULL
                    )
                ''')
                self._create_image_markings_schema(cursor)

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
                    old_version = int(row['value'])
                    if old_version == 6 and DB_VERSION == 7:
                        print(f'Database version mismatch (v{old_version} -> v{DB_VERSION}), migrating markings index...')
                        self._create_image_markings_schema(cursor)
                        cursor.execute('UPDATE meta SET value = ? WHERE key = ?',
                                     (str(DB_VERSION), 'version'))
                        self.conn.commit()
                    else:
                        # Version mismatch, drop and recreate tables (schema changed)
                        print(f'Database version mismatch (v{row["value"]} -> v{DB_VERSION}), recreating tables...')
                        cursor.execute('DROP TABLE IF EXISTS image_markings')
                        cursor.execute('DROP TABLE IF EXISTS images')
                        cursor.execute('DROP TABLE IF EXISTS image_tags')
                        cursor.execute('UPDATE meta SET value = ? WHERE key = ?',
                                     (str(DB_VERSION), 'version'))
                        self.conn.commit()
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
                        self._create_image_markings_schema(cursor)
                        cursor.execute('CREATE INDEX IF NOT EXISTS idx_images_mtime ON images(mtime)')
                        cursor.execute('CREATE INDEX IF NOT EXISTS idx_images_filename ON images(file_name)')
                        cursor.execute('CREATE INDEX IF NOT EXISTS idx_images_aspect_ratio ON images(aspect_ratio)')
                        cursor.execute('CREATE INDEX IF NOT EXISTS idx_images_is_video ON images(is_video)')
                        cursor.execute('CREATE INDEX IF NOT EXISTS idx_images_rating ON images(rating)')
                        cursor.execute('CREATE INDEX IF NOT EXISTS idx_images_thumbnail_cached ON images(thumbnail_cached)')
                        cursor.execute('CREATE INDEX IF NOT EXISTS idx_tags_tag ON image_tags(tag)')
                        cursor.execute('CREATE INDEX IF NOT EXISTS idx_tags_image_id ON image_tags(image_id)')
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
                    self._create_image_markings_schema(cursor)
                    self.conn.commit()

        except sqlite3.Error as e:
            print(f'Failed to initialize database: {e}')
            # If DB is corrupted, delete and retry
            if self.conn:
                try: self.conn.close() 
                except: pass
            try:
                self.delete_database_bundle(self._directory_path, include_legacy=False)
                self._init_db()  # Retry
            except Exception:
                pass

    def _prepare_db_location(self):
        """Ensure the DB folder exists and migrate a legacy root-level DB if needed."""
        self.db_dir.mkdir(parents=True, exist_ok=True)

        if self.db_path.exists():
            return

        legacy_bundle = [path for path in self.bundle_paths_for_base(self.legacy_db_path) if path.exists()]
        if not legacy_bundle:
            return

        moved_any = False
        legacy_base_name = self.legacy_db_path.name
        new_base_name = self.db_path.name

        for src in legacy_bundle:
            suffix = src.name[len(legacy_base_name):]
            dst = self.db_path.with_name(new_base_name + suffix)
            if dst.exists():
                continue
            try:
                src.rename(dst)
            except OSError:
                shutil.move(str(src), str(dst))
            moved_any = True

        if moved_any:
            print(f"[DB] Migrated legacy index to {self.DB_DIR_NAME}/{self.DB_FILE_NAME}")

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

    def bulk_insert_files(self, file_paths: List[Path], directory_path: Path,
                          progress_callback=None):
        """
        Bulk insert initial file records into the database.
        Used when initializing large folders to ensure DB has records for pagination.
        Skips files that already exist in DB.

        Args:
            progress_callback: Optional callable(current, total) for UI progress.
        """
        if not self.enabled or not self.conn or not file_paths:
            return

        # Prepare data chunks for insertion
        files_data = []
        now = time.time()

        # Get set of existing filenames to avoid duplicates (faster than INSERT OR IGNORE for 1M files)
        try:
             existing_files = set(self.get_all_paths())
        except Exception:
             existing_files = set()

        new_files_count = 0
        total_files = len(file_paths)
        for i, path in enumerate(file_paths):
             try:
                 rel_path = str(path.relative_to(directory_path))
             except ValueError:
                 rel_path = path.name

             if rel_path in existing_files:
                 continue

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
                 None, None, 1.0,  # Placeholder dims
                 int(is_video),
                 None, None, None, # Video metadata
                 mtime, 0.0, now,
                 file_size, file_type, ctime
             ))
             new_files_count += 1

             if len(files_data) >= 5000:
                 self._bulk_insert_chunk(files_data)
                 files_data = []

             # Progress every 10k files (covers both new and skipped)
             if (i + 1) % 10000 == 0:
                 if progress_callback:
                     progress_callback(i + 1, total_files)
                 if new_files_count % 50000 == 0 and new_files_count > 0:
                     print(f"[DB] Indexed {new_files_count:,}/{total_files:,} new files...")

        if files_data:
             self._bulk_insert_chunk(files_data)

        if new_files_count > 0:
             print(f"[DB] Bulk inserted {new_files_count:,} new files")

    def bulk_insert_relative_paths(self, rel_paths: List[str], directory_path: Path,
                                   progress_callback=None):
        """
        Bulk insert file records from relative paths.
        Intended for incremental refreshes where the caller already knows which
        paths are new, avoiding a full DB path-set load.
        """
        if not self.enabled or not self.conn or not rel_paths:
            return

        files_data = []
        now = time.time()
        total_files = len(rel_paths)
        new_files_count = 0

        for i, rel_path in enumerate(rel_paths):
            try:
                full_path = directory_path / rel_path
                stat = full_path.stat()
                mtime = stat.st_mtime
                ctime = stat.st_ctime
                file_size = stat.st_size
            except (OSError, FileNotFoundError, ValueError):
                continue

            suffix = full_path.suffix.lower()
            is_video = suffix in ['.mp4', '.avi', '.mov', '.mkv', '.webm']
            file_type = suffix.lstrip('.') if suffix else ''

            files_data.append((
                rel_path,
                None, None, 1.0,  # Placeholder dims
                int(is_video),
                None, None, None,  # Video metadata
                mtime, 0.0, now,
                file_size, file_type, ctime
            ))
            new_files_count += 1

            if len(files_data) >= 5000:
                self._bulk_insert_chunk(files_data)
                files_data = []

            if (i + 1) % 10000 == 0 and progress_callback:
                progress_callback(i + 1, total_files)

        if files_data:
            self._bulk_insert_chunk(files_data)

        if new_files_count > 0:
            print(f"[DB] Bulk inserted {new_files_count:,} new files")


    def run_maintenance(self, directory_path: Path):
        """Run maintenance: backfill metadata and reset suspicious dimensions."""
        try:
            cursor = self.conn.cursor()
            
            # 1. Reset suspicious dimensions (Super Tall/Fat OR Huge) to force re-scan with Smart Logic
            # Thresholds match Smart Verification (0.2, 5.0, 12000px)
            cursor.execute("""
                UPDATE images 
                SET width=NULL, height=NULL, aspect_ratio=1.0 
                WHERE width > 0 AND height > 0 
                AND (
                    (CAST(width AS FLOAT)/height < 0.2 OR CAST(width AS FLOAT)/height > 5.0)
                    OR
                    (width > 12000 OR height > 12000)
                )
            """)
            if cursor.rowcount > 0:
                print(f"[DB] Maintenance: Reset dimensions for {cursor.rowcount} suspicious items (will be re-scanned).")
                self.conn.commit()

            # 2. Backfill missing metadata
            # Find entries with missing metadata (size OR type OR ctime)
            cursor.execute("SELECT id, file_name FROM images WHERE file_size IS NULL OR file_type IS NULL OR ctime IS NULL")
            rows = cursor.fetchall()
            
            updates = []
            if rows:
                print(f"[DB] Backfilling metadata for {len(rows)} legacy items...")
                
                batch_size = 1000
                for i, (row_id, rel_path) in enumerate(rows):
                    try:
                        full_path = directory_path / rel_path
                        if not full_path.exists():
                            continue
                            
                        stat = full_path.stat()
                        suffix = full_path.suffix.lower().lstrip('.')
                        
                        updates.append((stat.st_size, suffix, stat.st_ctime, row_id))
                    except (OSError, ValueError):
                        continue
                    
                    if len(updates) >= batch_size:
                        cursor.executemany("UPDATE images SET file_size=?, file_type=?, ctime=? WHERE id=?", updates)
                        self.conn.commit()
                        updates = []
                
            if updates:
                cursor.executemany("UPDATE images SET file_size=?, file_type=?, ctime=? WHERE id=?", updates)
                self.conn.commit()

            if rows:
                print(f"[DB] Backfill complete.")

            # 3. One-time/Incremental rating migration: JSON sidecars -> DB rating.
            migrated, scanned, done = self.migrate_ratings_from_sidecars(directory_path)
            if migrated > 0:
                print(f"[DB] Rating migration: imported {migrated} rating(s) from {scanned} candidate sidecar(s).")
            elif not done and scanned > 0:
                print(f"[DB] Rating migration: scanned {scanned} candidate sidecar(s) (no new ratings yet).")

            # 4. One-time/Incremental markings migration: JSON sidecars -> DB markings index.
            migrated_markings, scanned_marking_sidecars, marking_done = self.migrate_markings_from_sidecars(directory_path)
            if migrated_markings > 0:
                print(f"[DB] Marking migration: imported {migrated_markings} marking(s) from {scanned_marking_sidecars} candidate sidecar(s).")
            elif not marking_done and scanned_marking_sidecars > 0:
                print(f"[DB] Marking migration: scanned {scanned_marking_sidecars} candidate sidecar(s) (no indexed markings yet).")
            
        except sqlite3.Error as e:
            print(f"[DB] Maintenance error: {e}")

    def migrate_ratings_from_sidecars(
        self,
        directory_path: Path,
        *,
        batch_size: int = 2000,
        max_seconds: float = 2.5,
    ) -> tuple[int, int, bool]:
        """
        Incrementally migrate legacy rating values from JSON sidecars into DB.

        Returns:
            (migrated_count, scanned_sidecars_count, done)
        """
        if not self.enabled or not self.conn:
            return 0, 0, True

        if batch_size <= 0:
            batch_size = 2000
        if max_seconds <= 0:
            max_seconds = 2.5

        start_ts = time.monotonic()
        migrated_total = 0
        scanned_sidecars = 0

        done = False
        last_id = 0
        try:
            with self._db_lock:
                cursor = self.conn.cursor()
                cursor.execute(
                    'SELECT value FROM meta WHERE key = ?',
                    (self.RATING_MIGRATION_DONE_KEY,),
                )
                row = cursor.fetchone()
                if row is not None and str(row[0]) == '1':
                    return 0, 0, True

                cursor.execute(
                    'SELECT value FROM meta WHERE key = ?',
                    (self.RATING_MIGRATION_LAST_ID_KEY,),
                )
                last_row = cursor.fetchone()
                if last_row is not None:
                    try:
                        last_id = int(last_row[0])
                    except Exception:
                        last_id = 0
        except sqlite3.Error:
            return 0, 0, True

        while (time.monotonic() - start_ts) < max_seconds:
            try:
                with self._db_lock:
                    cursor = self.conn.cursor()
                    cursor.execute(
                        '''
                        SELECT id, file_name
                        FROM images
                        WHERE id > ? AND COALESCE(rating, 0) <= 0.0
                        ORDER BY id
                        LIMIT ?
                        ''',
                        (int(last_id), int(batch_size)),
                    )
                    rows = cursor.fetchall()
            except sqlite3.Error:
                break

            if not rows:
                done = True
                break

            updates: list[tuple[float, int]] = []
            for row in rows:
                try:
                    row_id = int(row['id'] if isinstance(row, sqlite3.Row) else row[0])
                    rel_path = str(row['file_name'] if isinstance(row, sqlite3.Row) else row[1])
                except Exception:
                    continue

                if row_id > last_id:
                    last_id = row_id

                json_path = (directory_path / rel_path).with_suffix('.json')
                if not json_path.exists():
                    continue
                try:
                    if json_path.stat().st_size <= 0:
                        continue
                except OSError:
                    continue

                scanned_sidecars += 1
                try:
                    with json_path.open(encoding='UTF-8') as fp:
                        meta = json.load(fp)
                except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                    continue

                raw_rating = meta.get('rating') if isinstance(meta, dict) else None
                if not isinstance(raw_rating, (int, float)):
                    continue

                rating_value = float(raw_rating)
                # Legacy-safe normalization: accept old 0..5 values too.
                if rating_value > 1.0 and rating_value <= 5.0:
                    rating_value = rating_value / 5.0
                rating_value = max(0.0, min(1.0, rating_value))

                # Skip explicit zeros; DB default already represents "no rating".
                if rating_value <= 0.0:
                    continue

                updates.append((rating_value, row_id))

            try:
                with self._db_lock:
                    cursor = self.conn.cursor()
                    if updates:
                        cursor.executemany(
                            'UPDATE images SET rating = ? WHERE id = ?',
                            updates,
                        )
                        migrated_total += len(updates)

                    cursor.execute(
                        '''
                        INSERT INTO meta (key, value)
                        VALUES (?, ?)
                        ON CONFLICT(key) DO UPDATE SET value = excluded.value
                        ''',
                        (self.RATING_MIGRATION_LAST_ID_KEY, str(int(last_id))),
                    )

                    self.conn.commit()
            except sqlite3.Error:
                break

            if len(rows) < batch_size:
                done = True
                break

        if done:
            try:
                with self._db_lock:
                    cursor = self.conn.cursor()
                    cursor.execute(
                        '''
                        INSERT INTO meta (key, value)
                        VALUES (?, ?)
                        ON CONFLICT(key) DO UPDATE SET value = excluded.value
                        ''',
                        (self.RATING_MIGRATION_DONE_KEY, '1'),
                    )
                    self.conn.commit()
            except sqlite3.Error:
                pass

        return migrated_total, scanned_sidecars, done

    def migrate_markings_from_sidecars(
        self,
        directory_path: Path,
        *,
        batch_size: int = 1000,
        max_seconds: float = 2.5,
    ) -> tuple[int, int, bool]:
        """
        Incrementally migrate existing sidecar markings into the DB search index.

        Returns:
            (migrated_markings_count, scanned_sidecars_count, done)
        """
        if not self.enabled or not self.conn:
            return 0, 0, True

        if batch_size <= 0:
            batch_size = 1000
        if max_seconds <= 0:
            max_seconds = 2.5

        start_ts = time.monotonic()
        migrated_total = 0
        scanned_sidecars = 0
        done = False
        last_id = 0

        try:
            with self._db_lock:
                cursor = self.conn.cursor()
                cursor.execute(
                    'SELECT value FROM meta WHERE key = ?',
                    (self.MARKING_MIGRATION_DONE_KEY,),
                )
                row = cursor.fetchone()
                if row is not None and str(row[0]) == '1':
                    return 0, 0, True

                cursor.execute(
                    'SELECT value FROM meta WHERE key = ?',
                    (self.MARKING_MIGRATION_LAST_ID_KEY,),
                )
                last_row = cursor.fetchone()
                if last_row is not None:
                    try:
                        last_id = int(last_row[0])
                    except Exception:
                        last_id = 0
        except sqlite3.Error:
            return 0, 0, True

        while (time.monotonic() - start_ts) < max_seconds:
            try:
                with self._db_lock:
                    cursor = self.conn.cursor()
                    cursor.execute(
                        '''
                        SELECT id, file_name
                        FROM images
                        WHERE id > ?
                        ORDER BY id
                        LIMIT ?
                        ''',
                        (int(last_id), int(batch_size)),
                    )
                    rows = cursor.fetchall()
            except sqlite3.Error:
                break

            if not rows:
                done = True
                break

            pending_rows: list[tuple[int, str, str, float, int | None, int | None, int | None, int | None]] = []
            processed_ids: list[int] = []
            for row in rows:
                try:
                    row_id = int(row['id'] if isinstance(row, sqlite3.Row) else row[0])
                    rel_path = str(row['file_name'] if isinstance(row, sqlite3.Row) else row[1])
                except Exception:
                    continue

                if row_id > last_id:
                    last_id = row_id
                processed_ids.append(row_id)

                json_path = (directory_path / rel_path).with_suffix('.json')
                if not json_path.exists():
                    continue
                try:
                    if json_path.stat().st_size <= 0:
                        continue
                except OSError:
                    continue

                scanned_sidecars += 1
                try:
                    with json_path.open(encoding='UTF-8') as fp:
                        meta = json.load(fp)
                except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                    continue

                raw_markings = meta.get('markings') if isinstance(meta, dict) else None
                if not isinstance(raw_markings, list):
                    continue

                for marking in raw_markings:
                    if not isinstance(marking, dict):
                        continue
                    rect = marking.get('rect')
                    if not isinstance(rect, (list, tuple)) or len(rect) < 4:
                        continue
                    try:
                        x, y, width, height = [int(round(float(v))) for v in rect[:4]]
                    except Exception:
                        continue
                    label = str(marking.get('label') or '').strip()
                    marking_type = str(marking.get('type') or '').strip().lower()
                    if not label or not marking_type:
                        continue
                    try:
                        confidence = float(marking.get('confidence', 1.0) or 1.0)
                    except Exception:
                        confidence = 1.0
                    pending_rows.append(
                        (row_id, label, marking_type, confidence, x, y, width, height)
                    )

            try:
                with self._db_lock:
                    cursor = self.conn.cursor()
                    if processed_ids:
                        placeholders = ','.join('?' for _ in processed_ids)
                        cursor.execute(
                            f'DELETE FROM image_markings WHERE image_id IN ({placeholders})',
                            processed_ids,
                        )
                    if pending_rows:
                        cursor.executemany(
                            '''
                            INSERT INTO image_markings
                            (image_id, label, type, confidence, x, y, width, height)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            ''',
                            pending_rows,
                        )
                        migrated_total += len(pending_rows)
                    cursor.execute(
                        '''
                        INSERT INTO meta (key, value)
                        VALUES (?, ?)
                        ON CONFLICT(key) DO UPDATE SET value = excluded.value
                        ''',
                        (self.MARKING_MIGRATION_LAST_ID_KEY, str(int(last_id))),
                    )
                    self.conn.commit()
            except sqlite3.Error:
                break

            if len(rows) < batch_size:
                done = True
                break

        if done:
            try:
                with self._db_lock:
                    cursor = self.conn.cursor()
                    cursor.execute(
                        '''
                        INSERT INTO meta (key, value)
                        VALUES (?, ?)
                        ON CONFLICT(key) DO UPDATE SET value = excluded.value
                        ''',
                        (self.MARKING_MIGRATION_DONE_KEY, '1'),
                    )
                    self.conn.commit()
            except sqlite3.Error:
                pass

        return migrated_total, scanned_sidecars, done


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

    def set_markings_for_image(self, image_id: int, markings: List[Dict[str, Any]]):
        """Replace searchable markings for one image."""
        if not self.enabled or not self.conn:
            return

        normalized_rows: list[tuple[int, str, str, float, int | None, int | None, int | None, int | None]] = []
        for marking in markings or []:
            if not isinstance(marking, dict):
                continue

            rect = marking.get('rect')
            if isinstance(rect, (list, tuple)) and len(rect) >= 4:
                try:
                    x, y, width, height = [int(round(float(v))) for v in rect[:4]]
                except Exception:
                    x = y = width = height = None
            else:
                x = y = width = height = None

            label = str(marking.get('label') or '').strip()
            marking_type = str(marking.get('type') or '').strip().lower()
            if not label or not marking_type:
                continue

            try:
                confidence = float(marking.get('confidence', 1.0) or 1.0)
            except Exception:
                confidence = 1.0

            normalized_rows.append(
                (image_id, label, marking_type, confidence, x, y, width, height)
            )

        try:
            cursor = self.conn.cursor()
            cursor.execute('DELETE FROM image_markings WHERE image_id = ?', (image_id,))
            if normalized_rows:
                cursor.executemany(
                    '''
                    INSERT INTO image_markings
                    (image_id, label, type, confidence, x, y, width, height)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    normalized_rows,
                )
            self.commit()
        except sqlite3.Error as e:
            print(f'Database marking write error: {e}')
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

    def get_rank_of_image(self, rel_path: str, sort_field: str = 'file_name', sort_dir: str = 'ASC', 
                          filter_sql: str = '', bindings: tuple = (), **kwargs) -> int:
        """
        Calculate the 0-indexed rank of an image in the current sort order.
        Returns -1 if not found. used for restoring selection in paginated mode.
        """
        if not self._ensure_connection():
            return -1

        try:
            cursor = self.conn.cursor()
            safe_bindings = self._normalize_bindings(bindings)
            
            # 1. Resolve sort expression (must match get_page logic)
            sort_expr = sort_field
            if sort_field == 'RANDOM()':
                seed = kwargs.get('random_seed', 1234567)
                sort_expr = f"ABS(id * 1103515245 + {seed}) % 1000000007"
            elif sort_field == 'ctime':
                sort_expr = 'COALESCE(ctime, mtime)'
            elif sort_field == 'file_size':
                sort_expr = 'COALESCE(file_size, 0)'
                
            # 2. Resolve target row (id + sort value), trying exact and slash-variant paths.
            target_candidates = [rel_path]
            alt_path = rel_path.replace('\\', '/')
            if alt_path != rel_path:
                target_candidates.append(alt_path)
            alt_path2 = rel_path.replace('/', '\\')
            if alt_path2 != rel_path and alt_path2 not in target_candidates:
                target_candidates.append(alt_path2)

            target_row = None
            for candidate in target_candidates:
                if filter_sql:
                    q = f"SELECT id, {sort_expr} FROM images WHERE file_name = ? AND ({filter_sql}) LIMIT 1"
                    cursor.execute(q, (candidate,) + safe_bindings)
                else:
                    q = f"SELECT id, {sort_expr} FROM images WHERE file_name = ? LIMIT 1"
                    cursor.execute(q, (candidate,))
                target_row = cursor.fetchone()
                if target_row:
                    break

            if not target_row:
                # Case-insensitive fallback for Windows path casing mismatches.
                if filter_sql:
                    q = (
                        f"SELECT id, {sort_expr} FROM images "
                        f"WHERE lower(file_name) = lower(?) AND ({filter_sql}) LIMIT 1"
                    )
                    cursor.execute(q, (rel_path,) + safe_bindings)
                else:
                    q = f"SELECT id, {sort_expr} FROM images WHERE lower(file_name) = lower(?) LIMIT 1"
                    cursor.execute(q, (rel_path,))
                target_row = cursor.fetchone()

            if not target_row:
                print(f"[DB] get_rank: Target file not found in DB: {rel_path}")
                return -1

            target_id = int(target_row[0])
            target_val = target_row[1]

            # 3. Deterministic rank count mirroring get_page tie-break: ORDER BY sort_expr, id ASC.
            if sort_dir.upper() == 'ASC':
                before_clause = f"(({sort_expr} < ?) OR ({sort_expr} = ? AND id < ?))"
            else:
                before_clause = f"(({sort_expr} > ?) OR ({sort_expr} = ? AND id < ?))"

            if filter_sql:
                where_clause = f"({filter_sql}) AND {before_clause}"
                query_bindings = safe_bindings + (target_val, target_val, target_id)
            else:
                where_clause = before_clause
                query_bindings = (target_val, target_val, target_id)

            cursor.execute(f"SELECT COUNT(*) FROM images WHERE {where_clause}", query_bindings)
            return int(cursor.fetchone()[0])
            
        except Exception as e:
            print(f"[DB] get_rank error: {e}")
            return -1

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
            with self._db_lock:
                cursor = self.conn.cursor()
                offset = page * page_size

                # Handle stable random sorting if requested
                sort_expr = sort_field
                if sort_field == 'RANDOM()':
                    seed = kwargs.get('random_seed', 1234567)
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
                    
                query += f' ORDER BY {sort_expr} {sort_dir}, id ASC LIMIT ? OFFSET ?'

                safe_bindings = self._normalize_bindings(bindings)
                cursor.execute(query, safe_bindings + (page_size, offset))
                rows = cursor.fetchall()
                if not rows:
                    return []

                # sqlite3.Row normally supports dict(row), but under some reconnect/concurrency
                # conditions rows may be plain tuples. Handle both robustly.
                first = rows[0]
                if isinstance(first, sqlite3.Row):
                    return [dict(row) for row in rows]

                col_names = [desc[0] for desc in cursor.description] if cursor.description else []
                if col_names:
                    return [dict(zip(col_names, row)) for row in rows]
                return []

        except sqlite3.Error as e:
            print(f'Database query error: {e}')
            return []

    def get_ordered_aspect_ratios(self, sort_field: str = 'mtime', sort_dir: str = 'DESC',
                                 filter_sql: str = '', bindings: tuple = (), **kwargs) -> List[float]:
        """
        Get ALL aspect ratios sorted and filtered.
        Used for global masonry layout calculation.
        """
        if not self._ensure_connection():
            return []

        # Validate sort (reuse logic from get_page)
        valid_sort_fields = {'mtime', 'file_name', 'aspect_ratio', 'rating', 'width', 'height', 'id', 'RANDOM()', 'width * height', 'file_size', 'file_type', 'ctime'}
        if sort_field not in valid_sort_fields:
            sort_field = 'mtime'
        if sort_dir.upper() not in ('ASC', 'DESC'):
            sort_dir = 'DESC'

        try:
            with self._db_lock:
                cursor = self.conn.cursor()

                # Handle stable random sorting
                sort_expr = sort_field
                if sort_field == 'RANDOM()':
                    seed = kwargs.get('random_seed', 1234567)
                    sort_expr = f"ABS(id * 1103515245 + {seed}) % 1000000007"
                elif sort_field == 'ctime':
                    sort_expr = 'COALESCE(ctime, mtime)'
                elif sort_field == 'file_size':
                    sort_expr = 'COALESCE(file_size, 0)'

                query = f'SELECT aspect_ratio FROM images'
                if filter_sql:
                    query += f' WHERE {filter_sql} '
                
                query += f' ORDER BY {sort_expr} {sort_dir}'

                safe_bindings = self._normalize_bindings(bindings)
                cursor.execute(query, safe_bindings)
                return [row[0] if row[0] is not None else 1.0 for row in cursor.fetchall()]

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
            result = []
            
            # Batch queries to avoid SQLite limit (usually 999)
            batch_size = 50
            for i in range(0, len(image_ids), batch_size):
                batch = image_ids[i:i + batch_size]
                placeholders = ','.join('?' * len(batch))
                cursor.execute(f'''
                    SELECT id, file_name, width, height, aspect_ratio, is_video,
                           video_fps, video_duration, video_frame_count, mtime, rating
                    FROM images WHERE id IN ({placeholders})
                ''', batch)
                result.extend([dict(row) for row in cursor.fetchall()])
            
            return result
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

    def get_meta_value(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get a value from DB meta table."""
        if not self._ensure_connection():
            return default
        try:
            with self._db_lock:
                cursor = self.conn.cursor()
                cursor.execute('SELECT value FROM meta WHERE key = ?', (key,))
                row = cursor.fetchone()
                if row is None:
                    return default
                if isinstance(row, sqlite3.Row):
                    return row['value']
                return row[0] if row else default
        except sqlite3.Error:
            return default

    def set_meta_value(self, key: str, value: str):
        """Persist one value in DB meta table."""
        if not self._ensure_connection():
            return
        try:
            with self._db_lock:
                cursor = self.conn.cursor()
                cursor.execute(
                    '''
                    INSERT INTO meta (key, value)
                    VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    ''',
                    (str(key), str(value)),
                )
                self.conn.commit()
        except sqlite3.Error:
            return

    def get_directory_signatures(self) -> Dict[str, float]:
        """Return stored directory mtimes keyed by relative directory path."""
        if not self._ensure_connection():
            return {}

        try:
            with self._db_lock:
                cursor = self.conn.cursor()
                cursor.execute('SELECT dir_path, mtime FROM directories')
                rows = cursor.fetchall()
                return {
                    str(row['dir_path'] if isinstance(row, sqlite3.Row) else row[0]).replace('\\', '/'): (
                        float(row['mtime']) if isinstance(row, sqlite3.Row) else float(row[1])
                    )
                    for row in rows
                }
        except sqlite3.Error:
            return {}

    def replace_directory_signatures(self, dir_mtimes: Dict[str, float]):
        """Replace the persisted directory signature snapshot."""
        if not self._ensure_connection():
            return

        try:
            with self._db_lock:
                cursor = self.conn.cursor()
                cursor.execute('DELETE FROM directories')

                if dir_mtimes:
                    now = time.time()
                    rows = [
                        (str(dir_path).replace('\\', '/'), float(mtime), now)
                        for dir_path, mtime in sorted(dir_mtimes.items())
                    ]
                    cursor.executemany(
                        '''
                        INSERT INTO directories (dir_path, mtime, scanned_at)
                        VALUES (?, ?, ?)
                        ''',
                        rows,
                    )

                self.conn.commit()
        except sqlite3.Error as e:
            print(f'Database directory signature write error: {e}')

    # ========== Tag Management ==========

    def get_tags_for_image(self, image_id: int) -> List[str]:
        """Get all tags for a specific image."""
        if not self.enabled or not self._ensure_connection():
            return []

        try:
            with self._db_lock:
                cursor = self.conn.cursor()
                # Keep the original caption/tag sequence as inserted in DB.
                # Without explicit ordering SQLite may return rows via index order
                # (e.g. lexicographic tag order), which scrambles descriptive text.
                cursor.execute(
                    'SELECT tag FROM image_tags WHERE image_id = ? ORDER BY rowid ASC',
                    (image_id,),
                )
                return [row[0] for row in cursor.fetchall()]
        except sqlite3.Error as e:
            print(f'Database tag query error: {e}')
            return []

    def get_tags_for_images(self, image_ids: List[int]) -> Dict[int, List[str]]:
        """Get tags for multiple images in a single query."""
        if not self.enabled or not self._ensure_connection() or not image_ids:
            return {}

        try:
            with self._db_lock:
                cursor = self.conn.cursor()
                result: Dict[int, List[str]] = {img_id: [] for img_id in image_ids}
                
                # Batch queries to avoid SQLite limit (usually 999)
                batch_size = 50
                for i in range(0, len(image_ids), batch_size):
                    batch = image_ids[i:i + batch_size]
                    placeholders = ','.join('?' * len(batch))
                    cursor.execute(f'''
                        SELECT image_id, tag FROM image_tags
                        WHERE image_id IN ({placeholders})
                        ORDER BY image_id, rowid
                    ''', tuple(batch))

                    for row in cursor.fetchall():
                        if not row or len(row) < 2:
                            continue
                        if row[0] in result:
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

    def remove_images_by_paths(self, rel_paths: list):
        """Remove images (and their tags) from the DB by relative path."""
        if not self.enabled or not self.conn or not rel_paths:
            return 0
        try:
            cursor = self.conn.cursor()
            placeholders = ','.join('?' for _ in rel_paths)
            # Get IDs first for tag cleanup
            cursor.execute(
                f'SELECT id FROM images WHERE file_name IN ({placeholders})',
                rel_paths
            )
            ids = [row[0] for row in cursor.fetchall()]
            if ids:
                id_ph = ','.join('?' for _ in ids)
                cursor.execute(f'DELETE FROM image_tags WHERE image_id IN ({id_ph})', ids)
                cursor.execute(f'DELETE FROM image_markings WHERE image_id IN ({id_ph})', ids)
            cursor.execute(
                f'DELETE FROM images WHERE file_name IN ({placeholders})',
                rel_paths
            )
            self.commit()
            if ids:
                print(f'[DB] Removed {len(ids)} deleted images from index.')
            return len(ids)
        except Exception as e:
            print(f'[DB] Error removing deleted images: {e}')
            return 0

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

    def get_placeholder_files_in_range(self, start_rank: int, end_rank: int,
                                       sort_field: str = 'file_name',
                                       sort_dir: str = 'ASC',
                                       filter_sql: str = '',
                                       bindings: tuple = (),
                                       **kwargs) -> List[str]:
        """Get unenriched file names within a rank range (page).

        Uses the same sort order as get_page so ranks correspond to pages.
        Returns file_name values where width IS NULL (need enrichment).
        """
        if not self.enabled or not self.conn:
            return []

        valid_sort_fields = {'mtime', 'file_name', 'aspect_ratio', 'rating',
                             'width', 'height', 'id', 'RANDOM()',
                             'width * height', 'file_size', 'file_type', 'ctime'}
        if sort_field not in valid_sort_fields:
            sort_field = 'file_name'
        if sort_dir.upper() not in ('ASC', 'DESC'):
            sort_dir = 'ASC'

        try:
            with self._db_lock:
                cursor = self.conn.cursor()
                page_size = end_rank - start_rank

                sort_expr = sort_field
                if sort_field == 'RANDOM()':
                    seed = kwargs.get('random_seed', 1234567)
                    sort_expr = f"ABS(id * 1103515245 + {seed}) % 1000000007"
                elif sort_field == 'ctime':
                    sort_expr = 'COALESCE(ctime, mtime)'
                elif sort_field == 'file_size':
                    sort_expr = 'COALESCE(file_size, 0)'

                inner_query = 'SELECT file_name, width FROM images'
                if filter_sql:
                    inner_query += f' WHERE {filter_sql}'
                inner_query += f' ORDER BY {sort_expr} {sort_dir} LIMIT ? OFFSET ?'

                safe_bindings = self._normalize_bindings(bindings)
                query = f'SELECT file_name FROM ({inner_query}) sub WHERE sub.width IS NULL'
                cursor.execute(query, safe_bindings + (page_size, start_rank))
                return [row[0] for row in cursor.fetchall()]
        except sqlite3.Error as e:
            print(f'Database placeholder range query error: {e}')
            return []

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

        with self._db_lock:
            try:
                cursor = self.conn.cursor()
                cursor.execute('UPDATE images SET rating = ? WHERE id = ?', (rating, image_id))
                self.conn.commit()
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
            
            for i_row, row in enumerate(rows):
                img_id = row[0]
                file_name = row[1]
                full_path = directory_path / file_name

                # Yield GIL every 10 files so the main thread's event loop stays
                # responsive. Without this, 1000+ stat() calls hold the GIL for
                # 1-2 seconds, freezing scroll input.
                if i_row > 0 and i_row % 10 == 0:
                    time.sleep(0.002)

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
