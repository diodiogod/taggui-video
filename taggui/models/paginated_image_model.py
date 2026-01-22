"""
Paginated image list model for handling 1M+ images efficiently.

This model loads images in pages from the database, keeping only a few pages
in memory at a time. It provides the same interface as ImageListModel but
scales to millions of images.
"""

from pathlib import Path
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import threading
import time

from PySide6.QtCore import (QAbstractListModel, QModelIndex, Qt, Signal, QSize,
                            QRect, QTimer)
from PySide6.QtGui import QIcon, QImage
from PySide6.QtWidgets import QApplication

from utils.image import Image
from utils.image_index_db import ImageIndexDB


# Page configuration
DEFAULT_PAGE_SIZE = 1000
MAX_PAGES_IN_MEMORY = 5


@dataclass
class PageInfo:
    """Metadata about a loaded page."""
    page_num: int
    images: List[Image]
    load_time: float
    aspect_ratios: List[float]


class PaginatedImageModel(QAbstractListModel):
    """
    A paginated image model that loads images from database in chunks.

    Only keeps a limited number of pages in memory (MAX_PAGES_IN_MEMORY).
    Pages are loaded on-demand as the user scrolls.
    """

    # Signals
    page_loaded = Signal(int)  # Emitted when a page finishes loading (page_num)
    total_count_changed = Signal(int)  # Emitted when total image count changes
    indexing_progress = Signal(int, int)  # (current, total) during initial indexing

    def __init__(self, page_size: int = DEFAULT_PAGE_SIZE):
        super().__init__()
        self.page_size = page_size
        self.db: Optional[ImageIndexDB] = None
        self.directory_path: Optional[Path] = None

        # Page storage
        self._pages: Dict[int, PageInfo] = {}
        self._page_load_order: List[int] = []  # LRU tracking

        # Total count (cached from database)
        self._total_count = 0

        # Current sort/filter settings
        self._sort_field = 'mtime'
        self._sort_dir = 'DESC'
        self._filter_sql = ''
        self._filter_bindings = ()

        # Background loading
        self._load_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="page_load")
        self._loading_pages: set = set()  # Pages currently being loaded
        self._load_lock = threading.Lock()

        # Aspect ratio cache (for visible pages only)
        self._aspect_ratio_cache: List[float] = []

        # Thumbnail settings (compatible with ImageListModel interface)
        self.thumbnail_generation_width = 512
        self.image_list_image_width = 200  # For SizeHintRole

    # ========== Qt Model Interface ==========

    def rowCount(self, parent=QModelIndex()) -> int:
        """Return total number of images (not just loaded ones)."""
        return self._total_count

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        """Get data for an item. Triggers page loading if needed."""
        if not index.isValid():
            return None

        row = index.row()
        if row < 0 or row >= self._total_count:
            return None

        # Get the image, loading page if necessary
        image = self._get_image_at_index(row)

        if image is None:
            # Page not loaded yet - return placeholder data
            if role == Qt.ItemDataRole.DisplayRole:
                return "Loading..."
            elif role == Qt.ItemDataRole.SizeHintRole:
                return QSize(self.image_list_image_width, self.image_list_image_width)
            return None

        # Return actual data (compatible with ImageListModel)
        if role == Qt.ItemDataRole.DisplayRole:
            return ', '.join(image.tags)
        elif role == Qt.ItemDataRole.DecorationRole:
            return image.thumbnail
        elif role == Qt.ItemDataRole.SizeHintRole:
            if image.dimensions:
                width, height = image.dimensions
                aspect_ratio = width / height if height > 0 else 1.0
                scaled_height = int(self.image_list_image_width / aspect_ratio)
                return QSize(self.image_list_image_width, scaled_height)
            return QSize(self.image_list_image_width, self.image_list_image_width)

        return None

    # ========== Directory Loading ==========

    def load_directory(self, directory_path: Path, progress_callback: Callable = None):
        """
        Load a directory into the paginated model.

        This indexes files into the database (if needed) and loads the first page.
        """
        self.beginResetModel()

        self.directory_path = directory_path
        self._pages.clear()
        self._page_load_order.clear()
        self._total_count = 0

        # Initialize database
        self.db = ImageIndexDB(directory_path)

        # Index files if database is empty or needs refresh
        self._index_directory(progress_callback)

        # Get total count
        self._total_count = self.db.count(self._filter_sql, self._filter_bindings)
        self.total_count_changed.emit(self._total_count)

        # Load first page
        self._load_page_sync(0)

        self.endResetModel()

        # Rebuild aspect ratio cache
        self._rebuild_aspect_ratio_cache()

    def _index_directory(self, progress_callback: Callable = None):
        """Index all files in directory into database."""
        if not self.db or not self.directory_path:
            return

        # Check if we need to index (compare file count with db count)
        from models.image_list_model import get_file_paths

        # Get supported extensions
        image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.tif', '.tiff', '.jxl'}
        video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.webm'}
        all_extensions = image_extensions | video_extensions

        # Gather all image/video files
        all_files = []
        for path in self.directory_path.rglob("*"):
            if path.is_file() and path.suffix.lower() in all_extensions:
                all_files.append(path)

        db_count = self.db.count()
        file_count = len(all_files)

        # If counts match (roughly), skip re-indexing
        if abs(db_count - file_count) < 10:
            print(f"[INDEX] Database has {db_count} images, found {file_count} files - skipping reindex")
            return

        print(f"[INDEX] Indexing {file_count} files into database...")

        # Index each file
        for i, file_path in enumerate(all_files):
            try:
                relative_path = file_path.relative_to(self.directory_path)
                mtime = file_path.stat().st_mtime

                # Check if already cached and up-to-date
                cached = self.db.get_cached_info(str(relative_path), mtime)
                if cached:
                    continue  # Already indexed

                # Get dimensions
                is_video = file_path.suffix.lower() in video_extensions
                if is_video:
                    from models.image_list_model import extract_video_info
                    dimensions, video_metadata, _ = extract_video_info(file_path)
                else:
                    import imagesize
                    try:
                        width, height = imagesize.get(str(file_path))
                        dimensions = (width, height) if width > 0 and height > 0 else None
                        video_metadata = None
                    except Exception:
                        dimensions = None
                        video_metadata = None

                if dimensions:
                    self.db.save_info(
                        str(relative_path),
                        dimensions[0],
                        dimensions[1],
                        is_video,
                        mtime,
                        video_metadata
                    )

                # Progress update
                if progress_callback and i % 100 == 0:
                    progress_callback(i, file_count)
                    self.indexing_progress.emit(i, file_count)

            except Exception as e:
                print(f"[INDEX] Error indexing {file_path}: {e}")

        self.db.commit()
        print(f"[INDEX] Indexing complete: {file_count} files processed")

    # ========== Page Management ==========

    def _get_page_for_index(self, index: int) -> int:
        """Get page number containing a given image index."""
        return index // self.page_size

    def _get_image_at_index(self, index: int) -> Optional[Image]:
        """Get image at index, loading page if necessary."""
        page_num = self._get_page_for_index(index)
        index_in_page = index % self.page_size

        # Check if page is loaded
        if page_num in self._pages:
            page = self._pages[page_num]
            if index_in_page < len(page.images):
                # Update LRU
                self._touch_page(page_num)
                return page.images[index_in_page]
            return None

        # Page not loaded - trigger async load
        self._request_page_load(page_num)
        return None

    def _touch_page(self, page_num: int):
        """Update LRU order for a page."""
        if page_num in self._page_load_order:
            self._page_load_order.remove(page_num)
        self._page_load_order.append(page_num)

    def _request_page_load(self, page_num: int):
        """Request a page to be loaded in background."""
        with self._load_lock:
            if page_num in self._pages or page_num in self._loading_pages:
                return  # Already loaded or loading

            self._loading_pages.add(page_num)

        # Submit background load
        self._load_executor.submit(self._load_page_async, page_num)

    def _load_page_sync(self, page_num: int):
        """Load a page synchronously (for initial load)."""
        if not self.db:
            return

        images = self._load_images_from_db(page_num)
        self._store_page(page_num, images)

    def _load_page_async(self, page_num: int):
        """Load a page in background thread."""
        try:
            if not self.db:
                return

            images = self._load_images_from_db(page_num)

            # Store page (thread-safe)
            self._store_page(page_num, images)

            # Emit signal on main thread
            QTimer.singleShot(0, lambda: self._on_page_loaded(page_num))

        except Exception as e:
            print(f"[PAGE] Error loading page {page_num}: {e}")
        finally:
            with self._load_lock:
                self._loading_pages.discard(page_num)

    def _load_images_from_db(self, page_num: int) -> List[Image]:
        """Load images from database for a specific page."""
        if not self.db or not self.directory_path:
            return []

        rows = self.db.get_page(
            page=page_num,
            page_size=self.page_size,
            sort_field=self._sort_field,
            sort_dir=self._sort_dir,
            filter_sql=self._filter_sql,
            bindings=self._filter_bindings
        )

        images = []
        for row in rows:
            file_path = self.directory_path / row['file_name']

            # Get tags for this image
            tags = self.db.get_tags_for_image(row['id'])

            image = Image(
                path=file_path,
                dimensions=(row['width'], row['height']),
                tags=tags,
                is_video=bool(row['is_video']),
                rating=row.get('rating', 0.0)
            )

            if row['is_video']:
                image.video_metadata = {
                    'fps': row.get('video_fps'),
                    'duration': row.get('video_duration'),
                    'frame_count': row.get('video_frame_count')
                }

            images.append(image)

        return images

    def _store_page(self, page_num: int, images: List[Image]):
        """Store a loaded page and evict old pages if needed."""
        aspect_ratios = [img.aspect_ratio for img in images]

        page_info = PageInfo(
            page_num=page_num,
            images=images,
            load_time=time.time(),
            aspect_ratios=aspect_ratios
        )

        with self._load_lock:
            self._pages[page_num] = page_info
            self._touch_page(page_num)

            # Evict old pages if over limit
            while len(self._pages) > MAX_PAGES_IN_MEMORY:
                oldest_page = self._page_load_order.pop(0)
                if oldest_page in self._pages:
                    del self._pages[oldest_page]
                    print(f"[PAGE] Evicted page {oldest_page}")

    def _on_page_loaded(self, page_num: int):
        """Called on main thread when a page finishes loading."""
        # Notify views that data changed for this page's range
        start_idx = page_num * self.page_size
        end_idx = min(start_idx + self.page_size - 1, self._total_count - 1)

        if end_idx >= start_idx:
            self.dataChanged.emit(
                self.index(start_idx),
                self.index(end_idx)
            )

        # Rebuild aspect ratio cache
        self._rebuild_aspect_ratio_cache()

        # Emit signal
        self.page_loaded.emit(page_num)

    # ========== Aspect Ratio Cache ==========

    def get_aspect_ratios(self) -> List[float]:
        """Get aspect ratios for all images (estimated for unloaded pages)."""
        return self._aspect_ratio_cache

    def _rebuild_aspect_ratio_cache(self):
        """Rebuild aspect ratio cache from loaded pages."""
        if self._total_count == 0:
            self._aspect_ratio_cache = []
            return

        # Initialize with default aspect ratios
        self._aspect_ratio_cache = [1.0] * self._total_count

        # Fill in actual ratios from loaded pages
        for page_num, page_info in self._pages.items():
            start_idx = page_num * self.page_size
            for i, ratio in enumerate(page_info.aspect_ratios):
                idx = start_idx + i
                if idx < self._total_count:
                    self._aspect_ratio_cache[idx] = ratio

    # ========== Sorting & Filtering ==========

    def set_sort(self, field: str, direction: str = 'DESC'):
        """Change sort order and reload from page 1."""
        valid_fields = {'mtime', 'file_name', 'aspect_ratio', 'rating'}
        if field not in valid_fields:
            field = 'mtime'

        self._sort_field = field
        self._sort_dir = direction.upper()

        # Clear pages and reload
        self._reload_from_database()

    def set_filter(self, filter_sql: str = '', bindings: tuple = ()):
        """Apply filter and reload from page 1."""
        self._filter_sql = filter_sql
        self._filter_bindings = bindings

        # Clear pages and reload
        self._reload_from_database()

    def _reload_from_database(self):
        """Reload data after sort/filter change."""
        self.beginResetModel()

        self._pages.clear()
        self._page_load_order.clear()

        if self.db:
            self._total_count = self.db.count(self._filter_sql, self._filter_bindings)
            self.total_count_changed.emit(self._total_count)

            # Load first page
            self._load_page_sync(0)

        self.endResetModel()
        self._rebuild_aspect_ratio_cache()

    # ========== Scroll-based Page Loading ==========

    def ensure_pages_for_range(self, start_idx: int, end_idx: int):
        """Ensure pages covering the given index range are loaded."""
        start_page = self._get_page_for_index(start_idx)
        end_page = self._get_page_for_index(end_idx)

        for page_num in range(start_page, end_page + 1):
            if page_num not in self._pages and page_num not in self._loading_pages:
                self._request_page_load(page_num)

    def preload_nearby_pages(self, current_page: int, buffer: int = 1):
        """Preload pages around the current visible page."""
        for offset in range(-buffer, buffer + 1):
            page_num = current_page + offset
            if 0 <= page_num < (self._total_count + self.page_size - 1) // self.page_size:
                if page_num not in self._pages and page_num not in self._loading_pages:
                    self._request_page_load(page_num)

    # ========== Compatibility with ImageListModel ==========

    @property
    def images(self) -> List[Image]:
        """
        Get all loaded images (for compatibility).
        WARNING: This only returns images from loaded pages!
        """
        all_images = []
        for page_num in sorted(self._pages.keys()):
            all_images.extend(self._pages[page_num].images)
        return all_images

    def get_image(self, index: int) -> Optional[Image]:
        """Get image at index."""
        return self._get_image_at_index(index)

    def cleanup(self):
        """Clean up resources."""
        self._load_executor.shutdown(wait=False)
        if self.db:
            self.db.close()
