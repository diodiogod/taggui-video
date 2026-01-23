import random
import re
import sys
from collections import Counter, deque
from dataclasses import dataclass
from enum import Enum
from math import floor, ceil
from pathlib import Path
import json

import cv2
import exifread
import imagesize
from PySide6.QtCore import (QAbstractListModel, QModelIndex, QMimeData, QPoint,
                            QRect, QSize, Qt, QUrl, Signal, Slot, QEvent, QMetaObject, Q_ARG, QTimer)
from PySide6.QtGui import QIcon, QImage, QImageReader, QPixmap
from PySide6.QtWidgets import QMessageBox, QApplication
import pillow_jxl
from PIL import Image as pilimage  # Import Pillow's Image class
from concurrent.futures import ThreadPoolExecutor
import threading


from utils.image import Image, ImageMarking, Marking
from utils.image_index_db import ImageIndexDB
from utils.jxlutil import get_jxl_size
from utils.settings import DEFAULT_SETTINGS, settings
from utils.thumbnail_cache import get_thumbnail_cache
from utils.utils import get_confirmation_dialog_reply, pluralize
import utils.target_dimension as target_dimension

UNDO_STACK_SIZE = 32

# Global lock for video operations (OpenCV/ffmpeg is not thread-safe)
_video_lock = threading.Lock()

# Custom event for background load completion
class BackgroundLoadCompleteEvent(QEvent):
    EVENT_TYPE = QEvent.Type(QEvent.registerEventType())

    def __init__(self, images):
        super().__init__(self.EVENT_TYPE)
        self.images = images

# Custom event for background dimension enrichment progress
class BackgroundEnrichmentProgressEvent(QEvent):
    EVENT_TYPE = QEvent.Type(QEvent.registerEventType())

    def __init__(self, count):
        super().__init__(self.EVENT_TYPE)
        self.count = count

# Custom event for page loaded in paginated mode
class PageLoadedEvent(QEvent):
    EVENT_TYPE = QEvent.Type(QEvent.registerEventType())

    def __init__(self, page_num):
        super().__init__(self.EVENT_TYPE)
        self.page_num = page_num

def pil_to_qimage(pil_image):
    """Convert PIL image to QImage properly"""
    pil_image = pil_image.convert("RGBA")
    data = pil_image.tobytes("raw", "RGBA")
    qimage = QImage(data, pil_image.width, pil_image.height, QImage.Format_RGBA8888)
    return qimage

def load_thumbnail_data(image_path: Path, crop: QRect, thumbnail_width: int, is_video: bool) -> tuple[QImage | None, bool]:
    """
    Load thumbnail data (can run in background thread - uses QImage which IS thread-safe).

    Args:
        image_path: Path to the image/video file
        crop: Crop rectangle (or None for full image)
        thumbnail_width: Width to scale thumbnail to
        is_video: Whether this is a video file

    Returns:
        (qimage, was_cached): QImage and whether it was loaded from cache
    """
    from utils.thumbnail_cache import get_thumbnail_cache

    # Check disk cache FIRST (thread-safe: we load as QImage, not QIcon)
    try:
        cache = get_thumbnail_cache()
        if cache.enabled:
            mtime = image_path.stat().st_mtime
            # Get cache path directly and load as QImage (thread-safe)
            cache_key = cache._get_cache_key(image_path, mtime, thumbnail_width)
            cache_path = cache._get_cache_path(cache_key)

            if cache_path.exists():
                # Load directly as QImage (thread-safe, no QIcon/QPixmap needed)
                cached_qimage = QImage(str(cache_path))
                if not cached_qimage.isNull():
                    return (cached_qimage, True)  # Cache hit!
    except Exception:
        pass  # Cache check failed, fall through to generation

    # Generate new thumbnail using QImage (thread-safe for creation)
    try:
        if is_video:
            # For videos, extract first frame as thumbnail
            _, _, first_frame_pixmap = extract_video_info(image_path)
            if first_frame_pixmap:
                # Convert QPixmap to QImage (thread-safe)
                qimage = first_frame_pixmap.toImage().scaledToWidth(
                    thumbnail_width,
                    Qt.TransformationMode.SmoothTransformation)
            else:
                # Fallback to a placeholder
                qimage = QImage(thumbnail_width, thumbnail_width, QImage.Format_RGB888)
                qimage.fill(Qt.gray)
        elif image_path.suffix.lower() == ".jxl":
            pil_image = pilimage.open(image_path)  # Uses pillow-jxl
            qimage = pil_to_qimage(pil_image)
            if not crop:
                crop = QRect(QPoint(0, 0), qimage.size())
            if crop.height() > crop.width()*3:
                # keep it reasonable, higher than 3x the width doesn't make sense
                crop.setTop((crop.height() - crop.width()*3)//2) # center crop
                crop.setHeight(crop.width()*3)

            qimage = qimage.scaledToWidth(
                thumbnail_width,
                Qt.TransformationMode.SmoothTransformation)
        else:
            image_reader = QImageReader(str(image_path))
            # Rotate the image based on the orientation tag.
            image_reader.setAutoTransform(True)
            if not crop:
                crop = QRect(QPoint(0, 0), image_reader.size())
            if crop.height() > crop.width()*3:
                # keep it reasonable, higher than 3x the width doesn't make sense
                crop.setTop((crop.height() - crop.width()*3)//2) # center crop
                crop.setHeight(crop.width()*3)
            image_reader.setClipRect(crop)
            # Read as QImage (thread-safe)
            qimage = image_reader.read()
            if qimage.isNull():
                raise Exception("Failed to read image")
            qimage = qimage.scaledToWidth(
                thumbnail_width,
                Qt.TransformationMode.SmoothTransformation)

        # Return QImage - caller will convert to QPixmap/QIcon on main thread
        return qimage, False
    except Exception as e:
        print(f"Error loading image/video {image_path}: {e}")
        # Return a placeholder QImage
        qimage = QImage(thumbnail_width, thumbnail_width, QImage.Format_RGB888)
        qimage.fill(Qt.gray)
        return qimage, False


def natural_sort_key(path: Path):
    """
    Generate a key for natural/alphanumeric sorting.
    Converts 'file1', 'file2', 'file11' to sort naturally instead of lexicographically.
    """
    import re
    parts = []
    for part in re.split(r'(\d+)', str(path)):
        if part.isdigit():
            parts.append(int(part))
        else:
            parts.append(part.lower())
    return parts

def get_file_paths(directory_path: Path) -> set[Path]:
    """
    Recursively get all file paths in a directory, including
    subdirectories.
    """
    file_paths = set()
    for path in directory_path.rglob("*"):  # Use rglob for recursive search
        if path.is_file():
            file_paths.add(path)
    return file_paths


def extract_video_info(video_path: Path) -> tuple[tuple[int, int] | None, dict | None, QPixmap | None]:
    """
    Extract metadata and first frame from a video file.
    Returns: (dimensions, video_metadata, first_frame_pixmap)

    Thread-safe: Uses global lock to prevent OpenCV/ffmpeg crashes.
    """
    with _video_lock:
        try:
            cap = cv2.VideoCapture(str(video_path))
            if not cap.isOpened():
                return None, None, None

            # Get video properties
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            duration = frame_count / fps if fps > 0 else 0

            # Get SAR (Sample Aspect Ratio)
            sar_num = cap.get(cv2.CAP_PROP_SAR_NUM)
            sar_den = cap.get(cv2.CAP_PROP_SAR_DEN)

            # Read first frame
            ret, frame = cap.read()
            cap.release()

            if not ret:
                return (width, height), None, None

            # Convert BGR to RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = frame_rgb.shape
            bytes_per_line = ch * w
            qt_image = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(qt_image)

            video_metadata = {
                'fps': fps,
                'duration': duration,
                'frame_count': frame_count,
                'current_frame': 0,
                'sar_num': sar_num if sar_num > 0 else 1,
                'sar_den': sar_den if sar_den > 0 else 1
            }

            return (width, height), video_metadata, pixmap
        except Exception as e:
            print(f"Error extracting video info from {video_path}: {e}")
            return None, None, None


@dataclass
class HistoryItem:
    action_name: str
    tags: list[dict[str, list[str] | QRect | None | list[Marking]]]
    should_ask_for_confirmation: bool


class Scope(str, Enum):
    ALL_IMAGES = 'All images'
    FILTERED_IMAGES = 'Filtered images'
    SELECTED_IMAGES = 'Selected images'


class ImageListModel(QAbstractListModel):
    update_undo_and_redo_actions_requested = Signal()

    # Signals for pagination
    page_loaded = Signal(int)  # Emitted when a page finishes loading (page_num)
    total_count_changed = Signal(int)  # Emitted when total image count changes
    indexing_progress = Signal(int, int)  # (current, total) during initial indexing
    cache_warm_progress = Signal(int, int)  # (cached_count, total_count) for background cache warming

    # Threshold for enabling pagination mode (number of images)
    PAGINATION_THRESHOLD = 5000
    PAGE_SIZE = 1000
    MAX_PAGES_IN_MEMORY = 20  # Increased from 5 to reduce evictions and crashes

    def __init__(self, image_list_image_width: int, tag_separator: str):
        super().__init__()
        # Always generate thumbnails at max size (512px) for best quality and performance
        # The view will scale them down/up as needed based on zoom level via setIconSize()
        # This decouples thumbnail generation size from display size
        self.thumbnail_generation_width = 512  # Max thumbnail size for generation
        self.image_list_image_width = image_list_image_width  # For layout sizing (SizeHintRole)
        self.tag_separator = tag_separator
        self.images: list[Image] = []
        self.undo_stack = deque(maxlen=UNDO_STACK_SIZE)
        self.redo_stack = []
        self.proxy_image_list_model = None
        self.image_list_selection_model = None

        # Pagination mode state
        self._paginated_mode = False
        self._total_count = 0  # Total images in paginated mode
        self._pages: dict = {}  # page_num -> list[Image]
        self._page_load_order: list = []  # LRU tracking
        self._loading_pages: set = set()  # Pages currently being loaded
        self._page_load_lock = threading.Lock()
        self._db: ImageIndexDB = None
        self._directory_path: Path = None
        self._sort_field = 'mtime'
        self._sort_dir = 'DESC'
        self._pause_thumbnail_loading = False  # Pause during scrollbar drag for smooth dragging

        # Aspect ratio cache for masonry layout (avoids Qt model iteration on UI thread)
        self._aspect_ratio_cache: list[float] = []
        self._aspect_ratio_cache_lock = threading.Lock()  # Protect cache from race conditions

        # Separate ThreadPoolExecutors for loading vs saving (prioritize loads)
        # Load executor: 6 workers for fast thumbnail generation (UI blocking fixed with async queues + paint throttling)
        self._load_executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="thumb_load")
        # Save executor: 2 workers for background cache writing (low priority, can be slow)
        self._save_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="thumb_save")
        # Page loader executor for paginated mode
        self._page_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="page_load")
        # Cache warming executor: 2 workers for proactive cache building when idle (low priority)
        self._cache_warm_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="cache_warm")

        self._thumbnail_futures = {}  # Maps image index to Future
        self._thumbnail_lock = threading.Lock()  # Protects futures dict
        self._images_lock = threading.RLock()  # Protects images list and image objects from race conditions

        # Batch thumbnail updates to reduce Qt repaint overhead
        self._pending_thumbnail_updates = set()  # Indices with loaded thumbnails pending UI update
        self._thumbnail_batch_timer = QTimer(self)
        self._thumbnail_batch_timer.setSingleShot(True)
        self._thumbnail_batch_timer.setInterval(50)  # Batch updates every 50ms
        self._thumbnail_batch_timer.timeout.connect(self._flush_thumbnail_updates)

        # Track cache saves for reporting
        self._cache_saves_count = 0
        self._cache_saves_lock = threading.Lock()
        self._last_reported_saves = 0

        # Track REAL cache status per image (scan once, update incrementally)
        self._cache_status = {}  # Maps image index -> True if cached on disk
        self._cache_status_lock = threading.Lock()
        self._initial_cache_scan_done = False

        # Track background cache warming (proactive cache building when idle)
        self._cache_warm_cancelled = threading.Event()
        self._cache_warm_futures = []  # List of futures for cache warming tasks
        self._cache_warm_lock = threading.Lock()
        self._cache_warm_progress = 0  # How many images have been cache-warmed
        self._cache_warm_total = 0  # Total images to warm
        self._cache_warm_running = False  # Is warming currently active?

        # Defer cache writes during scrolling to avoid I/O blocking
        self._is_scrolling = False  # Set by view during active scrolling
        self._pending_cache_saves = []  # Queue of (path, mtime, width, thumbnail) to save when idle
        self._pending_cache_saves_lock = threading.Lock()
        self._pending_db_cache_flags = []  # Batch DB updates for thumbnail_cached flag (file_name strings)
        self._pending_db_cache_flags_lock = threading.Lock()

        # Track background enrichment
        self._enrichment_cancelled = threading.Event()
        self._suppress_enrichment_signals = False  # Suppress dataChanged during filtering

        # Queue for thread-safe dimension updates from background enrichment
        from queue import Queue
        self._enrichment_queue = Queue()
        self._enrichment_timer = None  # Timer to process queue on main thread

        # Queue for QImages waiting to be converted to QPixmap on main thread
        self._qimage_queue = []  # List of (idx, qimage, was_cached) tuples
        self._qimage_queue_lock = threading.Lock()
        self._qimage_timer = None  # QTimer for processing queue gradually

        # Connect page_loaded signal to handler (for pagination mode)
        self.page_loaded.connect(self._on_page_loaded_signal)

    @property
    def is_paginated(self) -> bool:
        """Check if model is in paginated mode."""
        return self._paginated_mode

    def get_all_loaded_images(self) -> list[Image]:
        """Get all currently loaded images (handles both modes).

        Both modes use self.images now (pagination just lazy-loads thumbnails).
        """
        return self.images

    def iter_all_images(self):
        """Iterate through all images that are currently loaded.

        Both modes use self.images now (pagination just lazy-loads thumbnails).
        """
        yield from self.images

    def get_aspect_ratios(self) -> list[float]:
        """Get cached aspect ratios for all images (fast, no Qt calls)."""
        with self._aspect_ratio_cache_lock:
            return self._aspect_ratio_cache.copy()  # Return copy to prevent concurrent modification

    def _rebuild_aspect_ratio_cache(self):
        """Rebuild aspect ratio cache when images change (thread-safe)."""
        # Both modes use self.images now
        try:
            images_snapshot = self.images[:]
            new_cache = [img.aspect_ratio for img in images_snapshot]

            # Update cache atomically under lock
            with self._aspect_ratio_cache_lock:
                self._aspect_ratio_cache = new_cache
        except Exception as e:
            print(f"[CACHE] Error rebuilding aspect ratio cache: {e}")
            # Keep old cache if rebuild fails
            pass

    # ========== Pagination Methods ==========

    def _get_page_for_index(self, index: int) -> int:
        """Get page number containing a given image index."""
        return index // self.PAGE_SIZE

    def _get_image_at_index(self, index: int) -> Image | None:
        """Get image at index in paginated mode, loading page if necessary."""
        if not self._paginated_mode:
            return self.images[index] if index < len(self.images) else None

        page_num = self._get_page_for_index(index)
        index_in_page = index % self.PAGE_SIZE

        # Check if page is loaded
        if page_num in self._pages:
            page_images = self._pages[page_num]
            if index_in_page < len(page_images):
                self._touch_page(page_num)
                return page_images[index_in_page]
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
        with self._page_load_lock:
            if page_num in self._pages or page_num in self._loading_pages:
                return  # Already loaded or loading
            self._loading_pages.add(page_num)

        # Submit background load
        self._page_executor.submit(self._load_page_async, page_num)

    def _load_page_sync(self, page_num: int):
        """Load a page synchronously (for initial load)."""
        if not self._db:
            return

        images = self._load_images_from_db(page_num)
        self._store_page(page_num, images)

    def _load_page_async(self, page_num: int):
        """Load a page in background thread."""
        try:
            if not self._db:
                return

            images = self._load_images_from_db(page_num)
            self._store_page(page_num, images)

            # Emit signal (will be handled on main thread via signal/slot mechanism)
            self.page_loaded.emit(page_num)

        except Exception as e:
            print(f"[PAGE] Error loading page {page_num}: {e}")
            import traceback
            traceback.print_exc()
        finally:
            with self._page_load_lock:
                self._loading_pages.discard(page_num)

    def _load_images_from_db(self, page_num: int) -> list[Image]:
        """Load images from database for a specific page."""
        if not self._db or not self._directory_path:
            return []

        rows = self._db.get_page(
            page=page_num,
            page_size=self.PAGE_SIZE,
            sort_field=self._sort_field,
            sort_dir=self._sort_dir
        )

        images = []
        text_file_paths = set()
        # Gather text file paths for tag loading
        for path in self._directory_path.rglob("*.txt"):
            text_file_paths.add(str(path))

        for row in rows:
            file_path = self._directory_path / row['file_name']

            # Load tags from text file
            tags = []
            text_file_path = file_path.with_suffix('.txt')
            if str(text_file_path) in text_file_paths:
                try:
                    caption = text_file_path.read_text(encoding='utf-8', errors='replace')
                    if caption:
                        tags = [tag.strip() for tag in caption.split(self.tag_separator) if tag.strip()]
                except Exception:
                    pass

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

    def _store_page(self, page_num: int, images: list[Image]):
        """Store a loaded page and evict old pages if needed."""
        with self._page_load_lock:
            self._pages[page_num] = images
            self._touch_page(page_num)

            # Check if we need to evict pages (but don't do it here - background thread unsafe)
            if len(self._pages) > self.MAX_PAGES_IN_MEMORY:
                # Schedule eviction on main thread via QTimer
                from PySide6.QtCore import QTimer
                QTimer.singleShot(0, self._evict_old_pages)

    def _evict_old_pages(self):
        """Evict old pages (called on main thread via QTimer)."""
        # TEMPORARY: Disable eviction to test if that's causing crashes
        return

        with self._page_load_lock:
            while len(self._pages) > self.MAX_PAGES_IN_MEMORY:
                oldest_page = self._page_load_order.pop(0)
                if oldest_page in self._pages:
                    # Cancel pending thumbnail loads for evicted page
                    self._cancel_page_thumbnails(oldest_page)
                    del self._pages[oldest_page]
                    print(f"[PAGE] Evicted page {oldest_page}")

            # Rebuild aspect ratio cache after all evictions
            if len(self._pages) <= self.MAX_PAGES_IN_MEMORY:
                self._rebuild_aspect_ratio_cache()

    def _cancel_page_thumbnails(self, page_num: int):
        """Cancel pending thumbnail loading futures for an evicted page."""
        start_idx = page_num * self.PAGE_SIZE
        end_idx = start_idx + self.PAGE_SIZE

        with self._thumbnail_lock:
            cancelled_count = 0
            for idx in range(start_idx, end_idx):
                if idx in self._thumbnail_futures:
                    future = self._thumbnail_futures[idx]
                    if not future.done():
                        future.cancel()
                        cancelled_count += 1
                    del self._thumbnail_futures[idx]

            if cancelled_count > 0:
                print(f"[PAGE] Cancelled {cancelled_count} pending thumbnails for evicted page {page_num}")

    def ensure_pages_for_range(self, start_idx: int, end_idx: int):
        """Ensure pages covering the given index range are loaded (for scroll handler)."""
        if not self._paginated_mode:
            return

        start_page = self._get_page_for_index(start_idx)
        end_page = self._get_page_for_index(end_idx)

        for page_num in range(start_page, end_page + 1):
            if page_num not in self._pages and page_num not in self._loading_pages:
                self._request_page_load(page_num)

    def event(self, event):
        """Handle custom events for page loading."""
        if isinstance(event, PageLoadedEvent):
            import time
            timestamp = time.strftime("%H:%M:%S")
            print(f"[PAGE {timestamp}] Received PageLoadedEvent for page {event.page_num}")
            self._on_page_loaded(event.page_num)
            return True
        return super().event(event)

    def _on_page_loaded_signal(self, page_num: int):
        """Called on main thread when a page finishes loading (via signal)."""
        # Notify views that data changed for this page's range
        start_idx = page_num * self.PAGE_SIZE
        end_idx = min(start_idx + self.PAGE_SIZE - 1, self._total_count - 1)

        if end_idx >= start_idx:
            self.dataChanged.emit(
                self.index(start_idx),
                self.index(end_idx)
            )

        # Rebuild aspect ratio cache
        self._rebuild_aspect_ratio_cache()

        # Emit layoutChanged to trigger masonry recalculation
        self.layoutChanged.emit()

    def _process_enrichment_queue(self):
        """Process dimension updates from background thread (runs on main thread via timer)."""
        try:
            import time
            from queue import Empty

            processed = 0
            batch_start = time.time()
            updated_indices = []

            # Process up to 100 updates per timer tick (balance responsiveness vs throughput)
            while processed < 100:
                try:
                    idx, dimensions, video_metadata = self._enrichment_queue.get_nowait()

                    # Update image dimensions on main thread with lock
                    with self._images_lock:
                        if idx < len(self.images):
                            self.images[idx].dimensions = dimensions
                            if video_metadata:
                                self.images[idx].video_metadata = video_metadata
                            updated_indices.append(idx)

                    processed += 1
                except Empty:
                    break

            # Emit layout changes for updated images
            if updated_indices and not self._suppress_enrichment_signals:
                # Rebuild aspect ratio cache
                self._rebuild_aspect_ratio_cache()

                # Use dataChanged instead of layoutChanged for more granular updates
                # This only invalidates changed items, not entire layout
                if updated_indices:
                    min_idx = min(updated_indices)
                    max_idx = max(updated_indices)
                    self.dataChanged.emit(self.index(min_idx), self.index(max_idx))

                batch_time = (time.time() - batch_start) * 1000
                if processed >= 50:  # Only log significant batches
                    timestamp = time.strftime("%H:%M:%S")
                    print(f"[ENRICH {timestamp}] Processed {processed} dimension updates in {batch_time:.1f}ms")

            # Continue processing if queue has more items
            if not self._enrichment_queue.empty():
                # Schedule next batch immediately
                if self._enrichment_timer:
                    self._enrichment_timer.start(10)  # 10ms between batches
            else:
                # Queue empty, check again in 100ms
                if self._enrichment_timer:
                    self._enrichment_timer.start(100)

        except Exception as e:
            # Catch any crashes in queue processing to prevent app crash
            import traceback
            timestamp = time.strftime("%H:%M:%S")
            print(f"[ENRICH {timestamp}] ERROR in queue processing: {e}")
            traceback.print_exc()
            # Stop timer to prevent repeated crashes
            if self._enrichment_timer:
                self._enrichment_timer.stop()

    def _preload_thumbnails_async(self):
        """Preload thumbnails in background (only helps for uncached images)."""
        total_images = len(self.images)

        # Adaptive preloading strategy based on folder size
        if total_images > 5000:
            # Huge folders: only preload first 1000 to avoid flooding executor
            preload_limit = 1000
            print(f"[THUMBNAIL] Huge folder ({total_images} images), will check cache for first {preload_limit}")
        elif total_images > 2500:
            # Large folders: preload first 500
            preload_limit = 500
            print(f"[THUMBNAIL] Large folder ({total_images} images), will check cache for first {preload_limit}")
        else:
            # Normal folders: check cache and decide
            from utils.thumbnail_cache import get_thumbnail_cache
            cache = get_thumbnail_cache()

            uncached_count = 0
            for image in self.images:
                if image.thumbnail or image.thumbnail_qimage:
                    continue
                # Quick cache check (doesn't load, just checks if file exists)
                try:
                    mtime = image.path.stat().st_mtime
                    if not cache.get_thumbnail(image.path, mtime, self.thumbnail_generation_width):
                        uncached_count += 1
                except:
                    uncached_count += 1

            # Pagination mode always needs smart preload for smoothness
            # Normal mode can skip if mostly cached
            if not self._paginated_mode and uncached_count < 50:
                print(f"[THUMBNAIL] Only {uncached_count} uncached, using on-demand loading")
                return

            print(f"[THUMBNAIL] {uncached_count} uncached images, starting parallel loading")
            preload_limit = None  # Preload all

        # Cancel any existing thumbnail loading
        with self._thumbnail_lock:
            for future in self._thumbnail_futures.values():
                future.cancel()
            self._thumbnail_futures.clear()

        # Submit images up to preload_limit (or all if None)
        # But skip images that already have thumbnails loaded OR cached on disk
        from utils.thumbnail_cache import get_thumbnail_cache
        cache = get_thumbnail_cache()

        submitted = 0
        checked = 0
        skipped_memory = 0
        skipped_cache = 0

        for idx, image in enumerate(self.images):
            # Stop if we've checked enough images (preload_limit)
            if preload_limit is not None and checked >= preload_limit:
                break
            checked += 1

            # Skip if already loaded in memory
            if image.thumbnail or image.thumbnail_qimage:
                skipped_memory += 1
                continue

            # Skip if cached on disk (no need to submit to worker)
            if cache.enabled:
                try:
                    mtime = image.path.stat().st_mtime
                    cache_key = cache._get_cache_key(image.path, mtime, self.thumbnail_generation_width)
                    cache_path = cache._get_cache_path(cache_key)
                    if cache_path.exists():
                        skipped_cache += 1
                        continue  # Don't submit - will be loaded on-demand from cache
                except Exception:
                    pass  # Can't check cache, submit to worker

            future = self._load_executor.submit(
                self._load_thumbnail_worker, idx, image.path, image.crop,
                self.thumbnail_generation_width, image.is_video
            )
            with self._thumbnail_lock:
                self._thumbnail_futures[idx] = future
            submitted += 1

        if checked < total_images:
            print(f"[THUMBNAIL] Checked first {checked} images: {skipped_memory} in memory, {skipped_cache} cached, {submitted} submitted")
        else:
            print(f"[THUMBNAIL] Checked all {checked} images: {skipped_memory} in memory, {skipped_cache} cached, {submitted} submitted")

        # Start a timer to report cache save progress every 30 seconds
        from PySide6.QtCore import QTimer
        self._cache_report_timer = QTimer()
        self._cache_report_timer.timeout.connect(self._report_cache_progress)
        self._cache_report_timer.start(30000)  # 30 seconds

    def queue_thumbnail_load(self, idx: int):
        """Queue a single thumbnail for async loading (non-blocking)."""
        if idx < 0 or idx >= len(self.images):
            return

        image = self.images[idx]

        # Skip if already loaded or loading
        if image.thumbnail or image.thumbnail_qimage:
            return

        with self._thumbnail_lock:
            if idx in self._thumbnail_futures:
                return  # Already queued

        # Submit async load
        future = self._load_executor.submit(
            self._load_thumbnail_worker, idx, image.path, image.crop,
            self.thumbnail_generation_width, image.is_video
        )
        with self._thumbnail_lock:
            self._thumbnail_futures[idx] = future

    def _report_cache_progress(self):
        """Periodically report thumbnail cache save progress."""
        with self._cache_saves_lock:
            if self._cache_saves_count > self._last_reported_saves:
                new_saves = self._cache_saves_count - self._last_reported_saves
                print(f"[THUMBNAIL CACHE] {new_saves} thumbnails saved to cache (total: {self._cache_saves_count})")
                self._last_reported_saves = self._cache_saves_count

    def start_cache_warming(self, start_idx: int, direction: str):
        """
        Start proactive cache warming in background (idle state only).
        Generates thumbnails ahead of scroll to build disk cache.

        Args:
            start_idx: Index to start warming from
            direction: 'down' or 'up' - which direction to warm
        """
        # Only in pagination mode
        if not self._paginated_mode:
            return

        # Don't restart if already running
        with self._cache_warm_lock:
            if self._cache_warm_running:
                return
            self._cache_warm_running = True

        # Clear cancellation flag
        self._cache_warm_cancelled.clear()

        # Cancel any existing cache warming tasks
        with self._cache_warm_lock:
            for future in self._cache_warm_futures:
                future.cancel()
            self._cache_warm_futures.clear()

        # Determine range to warm - ENTIRE folder with nearby prioritized first
        total_images = len(self.images)

        if direction == 'down':
            # Prioritize next 500, then rest after, then before start
            priority_end = min(start_idx + 500, total_images)
            indices_to_warm = list(range(start_idx, priority_end))
            # Then rest of folder after priority zone
            if priority_end < total_images:
                indices_to_warm.extend(range(priority_end, total_images))
            # Finally images before start_idx
            if start_idx > 0:
                indices_to_warm.extend(range(start_idx - 1, -1, -1))
        else:  # up
            # Prioritize previous 500, then rest before, then after start
            priority_start = max(start_idx - 500, 0)
            indices_to_warm = list(range(start_idx, priority_start, -1))
            # Then beginning of folder
            if priority_start > 0:
                indices_to_warm.extend(range(priority_start - 1, -1, -1))
            # Finally images after start_idx
            if start_idx < total_images - 1:
                indices_to_warm.extend(range(start_idx + 1, total_images))

        # Filter out already-cached images using DB (FAST - no disk scans!)
        uncached_indices = []

        for idx in indices_to_warm:
            if idx < 0 or idx >= len(self.images):
                continue

            image = self.images[idx]

            # Skip if already loaded in memory
            if image.thumbnail or image.thumbnail_qimage:
                continue

            # Query DB directly for current cached status (don't rely on stale _db_cached_info)
            if self._db and self._directory_path:
                try:
                    relative_path = str(image.path.relative_to(self._directory_path))
                    cached_info = self._db.get_cached_info(relative_path, image.path.stat().st_mtime)
                    if cached_info and cached_info.get('thumbnail_cached', 0) == 1:
                        continue  # DB says it's cached, skip
                except (ValueError, OSError):
                    pass  # Path error or file doesn't exist, assume uncached

            # Not cached, add to warm list
            uncached_indices.append(idx)

        if not uncached_indices:
            return

        # Store total for progress tracking
        self._cache_warm_total = len(uncached_indices)
        self._cache_warm_progress = 0

        # Emit initial progress to show label immediately
        self.cache_warm_progress.emit(0, len(uncached_indices))

        # Submit cache warming tasks (use separate executor with 2 workers)
        def cache_warm_worker(idx):
            """Worker that generates and caches a thumbnail."""
            # Check if cancelled
            if self._cache_warm_cancelled.is_set():
                return False

            if idx >= len(self.images):
                return False

            image = self.images[idx]
            success = False

            try:
                # Load thumbnail (generates if needed)
                qimage, was_cached = load_thumbnail_data(image.path, image.crop,
                                                         self.thumbnail_generation_width, image.is_video)

                if qimage and not qimage.isNull():
                    # Store in memory
                    image.thumbnail_qimage = qimage
                    image._last_thumbnail_was_cached = was_cached
                    success = True

                    # If not from cache, save to disk cache
                    if not was_cached:
                        from PySide6.QtGui import QIcon, QPixmap
                        pixmap = QPixmap.fromImage(qimage)
                        icon = QIcon(pixmap)

                        # Save to disk cache
                        from utils.thumbnail_cache import get_thumbnail_cache
                        get_thumbnail_cache().save_thumbnail(image.path, image.path.stat().st_mtime,
                                                            self.thumbnail_generation_width, icon)

                    # Mark in DB as cached (whether it was already cached or just generated)
                    # Debug: log first check
                    if not hasattr(self, '_db_check_logged'):
                        print(f'[DB CHECK] _db={self._db is not None}, _directory_path={self._directory_path is not None}')
                        if self._db:
                            print(f'[DB CHECK] DB enabled={self._db.enabled}')
                        self._db_check_logged = True

                    if self._db and self._directory_path:
                        try:
                            relative_path = str(image.path.relative_to(self._directory_path))
                            # Debug: log first 3 DB updates
                            if not hasattr(self, '_db_update_log_count'):
                                self._db_update_log_count = 0
                            if self._db_update_log_count < 3:
                                print(f'[DB UPDATE] Marking cached: {relative_path}')
                                self._db_update_log_count += 1
                            self._db.mark_thumbnail_cached(relative_path, cached=True)

                            # Update in-memory flag so next warming cycle knows it's cached
                            if not hasattr(image, '_db_cached_info') or image._db_cached_info is None:
                                image._db_cached_info = {}
                            image._db_cached_info['thumbnail_cached'] = 1
                        except ValueError as e:
                            print(f'[DB UPDATE ERROR] ValueError: {e} for path {image.path}')
                            pass

                # Check if cancelled after generation
                if self._cache_warm_cancelled.is_set():
                    return False

            except Exception as e:
                print(f"[CACHE WARM] Error warming cache for {image.path.name}: {e}")

            # ALWAYS increment progress and emit (even on failure, so progress bar advances)
            self._cache_warm_progress += 1
            if self._cache_warm_progress % 5 == 0 or self._cache_warm_progress >= self._cache_warm_total:
                # Emit every 5 items or on completion (reduce signal spam)
                self.cache_warm_progress.emit(self._cache_warm_progress, self._cache_warm_total)

            return success

        # Submit all warming tasks to separate executor
        with self._cache_warm_lock:
            for idx in uncached_indices:
                future = self._cache_warm_executor.submit(cache_warm_worker, idx)
                self._cache_warm_futures.append(future)

        # Add callback to mark warming complete when all futures finish
        def on_warming_complete():
            progress = self._cache_warm_progress
            total = self._cache_warm_total
            with self._cache_warm_lock:
                self._cache_warm_running = False
            print(f"[CACHE WARM] Completed - {progress}/{total} cached")
            # Emit 0, 0 to signal completion and show real cache status
            self.cache_warm_progress.emit(0, 0)

        # Wait for all futures in background thread
        def wait_for_completion():
            for future in self._cache_warm_futures:
                try:
                    future.result()  # Wait for completion
                except Exception:
                    pass
            on_warming_complete()

        # Submit waiter to separate thread
        import threading
        threading.Thread(target=wait_for_completion, daemon=True).start()

    def stop_cache_warming(self):
        """Stop background cache warming immediately (called when user interacts)."""
        # Set cancellation flag
        self._cache_warm_cancelled.set()

        # Cancel all pending futures
        with self._cache_warm_lock:
            for future in self._cache_warm_futures:
                future.cancel()
            self._cache_warm_futures.clear()
            self._cache_warm_running = False  # Allow restart

        # Reset progress
        self._cache_warm_progress = 0
        self._cache_warm_total = 0

        # Emit signal to hide label
        self.cache_warm_progress.emit(0, 0)

    def get_cache_stats(self) -> tuple[int, int]:
        """
        Get real cache statistics from DB.
        Returns: (cached_count, total_count)
        """
        if not self._db or not self._paginated_mode:
            return (0, 0)

        try:
            cached = self._db.count_cached_thumbnails()
            total = len(self.images)
            return (cached, total)
        except Exception as e:
            print(f"[CACHE] Error getting cache stats: {e}")
            return (0, 0)

    def set_scrolling_state(self, is_scrolling: bool):
        """
        Update scrolling state to defer cache writes during scroll.
        Called by view when scrolling starts/stops.
        """
        self._is_scrolling = is_scrolling

        # When scrolling stops, flush all pending cache saves
        if not is_scrolling:
            self._flush_pending_cache_saves()

    def _flush_pending_cache_saves(self, force=False):
        """Submit pending cache saves to background executor (batched to avoid blocking)."""
        with self._pending_cache_saves_lock:
            if not self._pending_cache_saves:
                return

            count = len(self._pending_cache_saves)

            # Only flush if we have a substantial batch (50+ items) to make it worthwhile
            # Or force flush (e.g., on app close, or queue too large 300+)
            if not force and count < 50:
                return  # Accumulate more before flushing

            # Show first few filenames for debugging
            sample_names = [p.name for p, _, _, _ in self._pending_cache_saves[:3]]
            print(f"[CACHE] Flushing {count} pending cache saves (batch write) - e.g., {sample_names}")

            # Move list instead of copying to avoid QIcon copy overhead
            saves_to_submit = self._pending_cache_saves
            self._pending_cache_saves = []

        # Submit in background to avoid blocking (don't hold lock during submission loop)
        from PySide6.QtCore import QTimer

        # Track chunk index in closure
        chunk_state = {'index': 0}
        CHUNK_SIZE = 25  # Smaller chunks for smoother UI

        def submit_next_chunk():
            """Submit one chunk at a time, yielding between chunks."""
            i = chunk_state['index']
            if i >= len(saves_to_submit):
                return  # Done

            # Submit one chunk
            chunk_end = min(i + CHUNK_SIZE, len(saves_to_submit))
            for path, mtime, width, thumbnail in saves_to_submit[i:chunk_end]:
                self._save_executor.submit(
                    self._save_thumbnail_worker,
                    path, mtime, width, thumbnail
                )

            # Move to next chunk
            chunk_state['index'] = chunk_end

            # Schedule next chunk (yields to event loop)
            if chunk_state['index'] < len(saves_to_submit):
                QTimer.singleShot(0, submit_next_chunk)

        # Start submission in next event loop iteration
        QTimer.singleShot(0, submit_next_chunk)

    def _load_thumbnail_worker(self, idx: int, path: Path, crop: QRect, width: int, is_video: bool):
        """Worker function that runs in background thread to load thumbnail data (QImage)."""
        try:
            # Load QImage in background thread (thread-safe, I/O bound)
            qimage, was_cached = load_thumbnail_data(path, crop, width, is_video)

            if qimage and not qimage.isNull():
                # Find image by PATH, not by idx (array may have been sorted!)
                for img in self.images:
                    if img.path == path:
                        img.thumbnail_qimage = qimage
                        img._last_thumbnail_was_cached = was_cached
                        break

                # DON'T emit dataChanged - let Qt request thumbnails on-demand
                # Emitting 1147 dataChanged signals floods the event queue
                # Qt will call data() when it needs to paint visible items
        except Exception as e:
            print(f"Error in thumbnail worker for {path}: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # Remove from futures dict
            with self._thumbnail_lock:
                self._thumbnail_futures.pop(idx, None)

    def _save_thumbnail_worker(self, path: Path, mtime: float, width: int, thumbnail: QIcon):
        """Worker function that saves thumbnail to disk cache in background thread."""
        import threading
        # Removed noisy log: print(f"[CACHE SAVE] Background thread {threading.current_thread().name} saving: {path.name}")
        try:
            from utils.thumbnail_cache import get_thumbnail_cache
            get_thumbnail_cache().save_thumbnail(path, mtime, width, thumbnail)

            # Queue DB update instead of doing it immediately (batch for performance)
            if self._db and self._directory_path:
                try:
                    relative_path = str(path.relative_to(self._directory_path))
                    with self._pending_db_cache_flags_lock:
                        self._pending_db_cache_flags.append(relative_path)
                        # Flush DB updates every 100 items to avoid huge batches
                        if len(self._pending_db_cache_flags) >= 100:
                            self._flush_db_cache_flags()
                except ValueError:
                    # Path not relative to directory, skip
                    pass

            with self._cache_saves_lock:
                self._cache_saves_count += 1

                # Emit cache status update every 10 saves (not too spammy)
                if self._cache_saves_count % 10 == 0:
                    self.cache_warm_progress.emit(0, 0)  # Signal to refresh cache status
        except Exception as e:
            print(f"[CACHE] ERROR saving in background: {e}")
            import traceback
            traceback.print_exc()

    def _flush_db_cache_flags(self):
        """Batch update DB thumbnail_cached flags (called from worker thread)."""
        with self._pending_db_cache_flags_lock:
            if not self._pending_db_cache_flags:
                return

            batch = list(self._pending_db_cache_flags)
            self._pending_db_cache_flags.clear()

        # Batch DB update (single transaction for all flags)
        if self._db:
            try:
                with self._db._db_lock:
                    cursor = self._db.conn.cursor()
                    cursor.executemany(
                        'UPDATE images SET thumbnail_cached = 1 WHERE file_name = ?',
                        [(file_name,) for file_name in batch]
                    )
                    self._db.conn.commit()
            except Exception as e:
                print(f"[DB] ERROR batch updating thumbnail_cached flags: {e}")

    def _load_thumbnail_async(self, path: Path, crop, is_video: bool, row: int):
        """Load thumbnail in background thread, then notify UI."""
        try:
            qimage, was_cached = load_thumbnail_data(
                path, crop, self.thumbnail_generation_width, is_video
            )
            # Notify main thread that thumbnail is ready
            QMetaObject.invokeMethod(
                self,
                "_notify_thumbnail_ready",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(int, row)
            )
            return qimage, was_cached
        except Exception as e:
            print(f"[THUMBNAIL ASYNC] Error loading {path.name}: {e}")
            return None, False

    def _get_placeholder_icon(self):
        """Return a placeholder icon for thumbnails being loaded."""
        # Cache the placeholder to avoid recreating it
        if not hasattr(self, '_placeholder_icon'):
            # Create a simple grey square as placeholder
            from PySide6.QtGui import QPixmap, QColor
            size = self.image_list_image_width
            pixmap = QPixmap(size, size)
            pixmap.fill(QColor(200, 200, 200))  # Light grey
            self._placeholder_icon = QIcon(pixmap)
        return self._placeholder_icon

    @Slot(int)
    def _notify_thumbnail_ready(self, idx: int):
        """Called on main thread when thumbnail QImage is ready (batched to reduce repaints)."""
        if idx < len(self.images):
            self._pending_thumbnail_updates.add(idx)
            # Restart timer to batch updates (coalesces rapid thumbnail loads)
            self._thumbnail_batch_timer.start()

    def _flush_thumbnail_updates(self):
        """Emit batched dataChanged for all pending thumbnail updates."""
        if not self._pending_thumbnail_updates:
            return

        # Emit single dataChanged for contiguous ranges (more efficient than individual)
        indices = sorted(self._pending_thumbnail_updates)
        self._pending_thumbnail_updates.clear()

        # Group into contiguous ranges
        if not indices:
            return

        range_start = indices[0]
        range_end = indices[0]

        for idx in indices[1:]:
            if idx == range_end + 1:
                # Extend current range
                range_end = idx
            else:
                # Emit current range and start new one
                self.dataChanged.emit(
                    self.index(range_start), self.index(range_end),
                    [Qt.ItemDataRole.DecorationRole]
                )
                range_start = idx
                range_end = idx

        # Emit final range
        self.dataChanged.emit(
            self.index(range_start), self.index(range_end),
            [Qt.ItemDataRole.DecorationRole]
        )

    def event(self, event):
        """Handle custom events (background load completion and enrichment)."""
        if event.type() == BackgroundLoadCompleteEvent.EVENT_TYPE:
            # Append background-loaded images to the model
            start_idx = len(self.images)
            self.beginInsertRows(QModelIndex(), start_idx, start_idx + len(event.images) - 1)
            self.images.extend(event.images)
            self.endInsertRows()

            # Rebuild aspect ratio cache with new images
            self._rebuild_aspect_ratio_cache()

            print(f"[PROGRESSIVE] Model updated: {len(self.images)} total images")
            return True
        # BackgroundEnrichmentProgressEvent removed - now using queue + timer approach
        return super().event(event)

    def flags(self, index):
        default_flags = super().flags(index)
        if index.isValid():
            return Qt.ItemFlags.ItemIsDragEnabled | default_flags
        return default_flags

    def mimeTypes(self):
        return ('text/uri-list', 'text/plain')

    def mimeData(self, indexes):
        mimeData = QMimeData()
        mimeData.setUrls([QUrl('file://' + str(self.data(
            image_index, Qt.ItemDataRole.UserRole
            ).path)) for image_index in indexes])
        mimeData.setText('\r\n'.join(['file://' + str(self.data(
            image_index, Qt.ItemDataRole.UserRole
            ).path) for image_index in indexes]))
        return mimeData

    def rowCount(self, parent=None) -> int:
        # Both modes use self.images (pagination just lazy-loads thumbnails)
        return len(self.images)

    def data(self, index: QModelIndex, role=None) -> Image | str | QIcon | QSize:
        # Validate index bounds to prevent errors during model reset
        try:
            row = index.row()
            if not index.isValid():
                return None

            # Get image - same logic for both modes (all images in self.images now)
            # No lock needed - Python GIL protects simple reads, and lock was blocking thumbnail loads
            if row >= len(self.images) or row < 0:
                return None
            image = self.images[row]

            if role == Qt.ItemDataRole.UserRole:
                return image

            if image is None:
                return None
        except Exception as e:
            print(f"[MODEL] ERROR in data() for row {row if 'row' in locals() else '?'}: {e}")
            return None

        if role == Qt.ItemDataRole.DisplayRole:
            # The text shown next to the thumbnail in the image list.
            text = image.path.name
            if image.tags:
                caption = self.tag_separator.join(image.tags)
                text += f'\n{caption}'
            return text
        if role == Qt.ItemDataRole.DecorationRole:
            # During scrollbar drag ONLY: return placeholders to keep drag smooth
            # Mouse wheel scroll: allow loading (async is fast enough)
            if self._pause_thumbnail_loading:
                if image.thumbnail:
                    return image.thumbnail  # Show already loaded
                else:
                    return self._get_placeholder_icon()  # Don't load new ones during drag

            # Check if we already have a QIcon (from cache or previous lazy conversion)
            if image.thumbnail:
                return image.thumbnail

            # Check if background thread loaded a QImage for us
            if image.thumbnail_qimage and not image.thumbnail_qimage.isNull():
                # Lazy conversion: QImage → QPixmap → QIcon (on main thread, but only for visible items)
                pixmap = QPixmap.fromImage(image.thumbnail_qimage)
                thumbnail = QIcon(pixmap)
                image.thumbnail = thumbnail

                # Save to disk cache in background thread if not from cache
                # Only save if flag is explicitly set AND false (not from cache)
                # If flag doesn't exist or is True, don't save (either from cache or uncertain)
                has_flag = hasattr(image, '_last_thumbnail_was_cached')
                flag_value = getattr(image, '_last_thumbnail_was_cached', None) if has_flag else None
                should_save = has_flag and not flag_value

                if should_save:
                    # Defer cache writes during scrolling to avoid I/O blocking
                    if self._is_scrolling:
                        with self._pending_cache_saves_lock:
                            self._pending_cache_saves.append((image.path, image.path.stat().st_mtime,
                                                              self.thumbnail_generation_width, thumbnail))
                            queue_size = len(self._pending_cache_saves)

                            # Auto-flush if queue gets too large (300+) to prevent memory buildup
                            if queue_size >= 300:
                                print(f"[CACHE] Queue full ({queue_size} items), force flushing...")
                                self._flush_pending_cache_saves(force=True)
                    else:
                        # Submit to save executor (low priority, won't compete with loads)
                        self._save_executor.submit(
                            self._save_thumbnail_worker,
                            image.path,
                            image.path.stat().st_mtime,
                            self.thumbnail_generation_width,
                            thumbnail
                        )

                return thumbnail

            # Async loading ONLY in pagination mode (keeps normal mode smooth with preloading)
            # In normal mode, preloading needs synchronous loads to work
            if not self._paginated_mode:
                # Normal mode: Load synchronously (enables preloading to work)
                try:
                    qimage, was_cached = load_thumbnail_data(
                        image.path, image.crop, self.thumbnail_generation_width, image.is_video
                    )

                    if qimage and not qimage.isNull():
                        pixmap = QPixmap.fromImage(qimage)
                        thumbnail = QIcon(pixmap)
                        image.thumbnail = thumbnail
                        image._last_thumbnail_was_cached = was_cached

                        # Save to disk cache in background thread if not from cache
                        if not was_cached:
                            # Debug: why are we saving this?
                            mtime = image.path.stat().st_mtime
                            # Defer during scroll to avoid I/O blocking
                            if self._is_scrolling:
                                with self._pending_cache_saves_lock:
                                    self._pending_cache_saves.append((image.path, mtime,
                                                                      self.thumbnail_generation_width, thumbnail))
                            else:
                                self._save_executor.submit(
                                    self._save_thumbnail_worker,
                                    image.path,
                                    mtime,
                                    self.thumbnail_generation_width,
                                    thumbnail
                                )

                        return thumbnail
                except Exception as e:
                    print(f"[THUMBNAIL ERROR] Failed to load thumbnail for {image.path.name}: {e}")
                    import traceback
                    traceback.print_exc()

                return None

            # Pagination mode: Async loading with placeholders for smooth scrolling
            with self._thumbnail_lock:
                # Check if already loading
                if row in self._thumbnail_futures:
                    future = self._thumbnail_futures[row]
                    if not future.done():
                        # Still loading - return placeholder
                        return self._get_placeholder_icon()
                    # Future done - check result
                    try:
                        qimage, was_cached = future.result()
                        if qimage and not qimage.isNull():
                            pixmap = QPixmap.fromImage(qimage)
                            thumbnail = QIcon(pixmap)
                            image.thumbnail = thumbnail
                            image._last_thumbnail_was_cached = was_cached

                            # Save to cache if needed
                            if not was_cached:
                                # Debug: why are we saving this?
                                if not hasattr(self, '_cache_debug_count3'):
                                    self._cache_debug_count3 = 0
                                if self._cache_debug_count3 < 5:
                                    print(f"[CACHE DEBUG PATH3] Saving {image.path.name}: was_cached={was_cached}")
                                    self._cache_debug_count3 += 1

                                mtime = image.path.stat().st_mtime
                                # Defer during scroll to avoid I/O blocking
                                if self._is_scrolling:
                                    with self._pending_cache_saves_lock:
                                        self._pending_cache_saves.append((image.path, mtime,
                                                                          self.thumbnail_generation_width, thumbnail))
                                else:
                                    self._save_executor.submit(
                                        self._save_thumbnail_worker,
                                        image.path,
                                        mtime,
                                        self.thumbnail_generation_width,
                                        thumbnail
                                    )

                            del self._thumbnail_futures[row]
                            return thumbnail
                    except Exception as e:
                        print(f"[THUMBNAIL ERROR] Failed to load thumbnail for {image.path.name}: {e}")
                        del self._thumbnail_futures[row]
                        return None

                # Not loading yet - submit to background thread
                future = self._load_executor.submit(
                    self._load_thumbnail_async,
                    image.path,
                    image.crop,
                    image.is_video,
                    row
                )
                self._thumbnail_futures[row] = future

                # Return placeholder immediately (smooth scrolling)
                return self._get_placeholder_icon()
        if role == Qt.ItemDataRole.SizeHintRole:
            # Don't use thumbnail.availableSizes() - that returns the 512px generation size
            # Instead, calculate based on the actual image dimensions
            dimensions = image.crop.size().toTuple() if image.crop else image.dimensions
            if not dimensions:
                return QSize(self.image_list_image_width,
                             self.image_list_image_width)
            width, height = dimensions
            # Scale the dimensions to the image width.
            return QSize(self.image_list_image_width,
                         int(self.image_list_image_width * min(height / width, 3)))
        if role == Qt.ItemDataRole.ToolTipRole:
            path = image.path.relative_to(settings.value('directory_path', type=str))
            dimensions = f'{image.dimensions[0]}:{image.dimensions[1]}'
            if not image.target_dimension:
                if image.crop:
                    image.target_dimension = target_dimension.get(image.crop.size())
                else:
                    image.target_dimension = target_dimension.get(QSize(*image.dimensions))
            target = f'{image.target_dimension.width()}:{image.target_dimension.height()}'
            return f'{path}\n{dimensions} 🠮 {target}'

    def load_directory(self, directory_path: Path):
        from PySide6.QtWidgets import QProgressDialog, QApplication, QMessageBox
        from PySide6.QtCore import Qt

        # DON'T call beginResetModel() here - it clears the view immediately
        # Load all metadata first, THEN reset the model (keeps old images visible during loading)
        error_messages: list[str] = []
        new_images = []  # Build new image list without clearing old one
        file_paths = get_file_paths(directory_path)
        image_suffixes_string = settings.value(
            'image_list_file_formats',
            defaultValue=DEFAULT_SETTINGS['image_list_file_formats'], type=str)
        image_suffixes = []
        for suffix in image_suffixes_string.split(','):
            suffix = suffix.strip().lower()
            if not suffix.startswith('.'):
                suffix = '.' + suffix
            image_suffixes.append(suffix)
        image_paths = list(path for path in file_paths
                           if path.suffix.lower() in image_suffixes)

        # Debug: check what extensions are being filtered out
        print(f"[FILTER] Total files found: {len(file_paths)}")
        print(f"[FILTER] Image files after filter: {len(image_paths)}")
        if len(file_paths) != len(image_paths):
            excluded = len(file_paths) - len(image_paths)
            excluded_exts = {}
            for path in file_paths:
                if path.suffix.lower() not in image_suffixes:
                    ext = path.suffix.lower() or '(no extension)'
                    excluded_exts[ext] = excluded_exts.get(ext, 0) + 1
            print(f"[FILTER] Excluded {excluded} files by extension:")
            for ext, count in sorted(excluded_exts.items(), key=lambda x: -x[1])[:10]:
                print(f"  - {count:5d} files with extension '{ext}'")
            print(f"[FILTER] Accepted extensions: {', '.join(sorted(image_suffixes))}")

        # Check for pagination mode (large folders)
        total_images = len(image_paths)
        if total_images >= self.PAGINATION_THRESHOLD:
            print(f"[PAGINATION] Large folder detected ({total_images} images), switching to paginated mode")
            self._load_directory_paginated(directory_path, image_paths, file_paths)
            return

        # Normal folder - reset pagination flag
        self._paginated_mode = False

        # Sort paths early for consistent ordering
        image_paths.sort(key=natural_sort_key)

        # Comparing paths is slow on some systems, so convert the paths to
        # strings.
        text_file_path_strings = {str(path) for path in file_paths
                                  if path.suffix == '.txt'}
        json_file_path_strings = {str(path) for path in file_paths
                                  if path.suffix == '.json'}
        # Define video extensions
        video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.webm'}

        # Initialize database cache
        db = ImageIndexDB(directory_path)

        # Fast metadata-only loading for large folders
        if total_images > 5000:
            use_fast_load = True
            progress = QProgressDialog(f"Loading {total_images} images...", "Cancel", 0, total_images)
        else:
            use_fast_load = False
            progress = QProgressDialog("Loading images...", "Cancel", 0, total_images)

        progress.setWindowTitle("Loading Directory")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(500)  # Show after 500ms if still loading
        progress.setAutoClose(True)
        progress.setAutoReset(False)

        loaded_count = 0
        cache_hits = 0
        cache_misses = 0
        corrupted_files = 0
        failed_video_extractions = 0
        skip_reasons = {}  # Track why images were skipped

        # Scale processEvents frequency for large folders
        # Huge folders: update every 500 images, Large: every 100, Normal: every 10
        if total_images > 20000:
            update_interval = 500
        elif total_images > 5000:
            update_interval = 100
        else:
            update_interval = max(10, total_images // 100)

        for image_path in image_paths:
            # Update progress at scaled intervals to reduce UI overhead
            if loaded_count % update_interval == 0:
                progress.setValue(loaded_count)
                QApplication.processEvents()
                if progress.wasCanceled():
                    break

            loaded_count += 1
            is_video = image_path.suffix.lower() in video_extensions
            video_metadata = None
            first_frame_pixmap = None
            dimensions = None
            cached = None

            if use_fast_load:
                # Fast load: only check cache, skip expensive operations
                try:
                    mtime = image_path.stat().st_mtime
                    relative_path = str(image_path.relative_to(directory_path))
                    cached = db.get_cached_info(relative_path, mtime)

                    if cached:
                        dimensions = cached['dimensions']
                        is_video = cached['is_video']
                        video_metadata = cached.get('video_metadata')
                        cache_hits += 1
                    else:
                        # No cache - use placeholder dimensions, will enrich in background
                        cache_misses += 1
                        dimensions = (512, 512)  # Placeholder for uncached images
                except (ValueError, OSError) as e:
                    corrupted_files += 1
                    reason = f"stat error: {type(e).__name__}"
                    skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                    continue
            else:
                # Normal load: read dimensions from files as before
                try:
                    mtime = image_path.stat().st_mtime
                    relative_path = str(image_path.relative_to(directory_path))
                    cached = db.get_cached_info(relative_path, mtime)

                    if cached:
                        dimensions = cached['dimensions']
                        is_video = cached['is_video']
                        video_metadata = cached.get('video_metadata')
                        cache_hits += 1
                    else:
                        cache_misses += 1

                        if is_video:
                            dimensions, video_metadata, first_frame_pixmap = extract_video_info(image_path)
                            if dimensions is None:
                                failed_video_extractions += 1
                                reason = "video extraction failed"
                                skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                                error_messages.append(f'Failed to extract video info from '
                                                    f'{image_path}')
                                continue
                        elif str(image_path).endswith('jxl'):
                            dimensions = get_jxl_size(image_path)
                        else:
                            dimensions = imagesize.get(str(image_path))
                            if dimensions == (-1, -1):
                                dimensions = pilimage.open(image_path).size

                        if dimensions:
                            db.save_info(relative_path, dimensions[0], dimensions[1],
                                        is_video, mtime, video_metadata)

                            if cache_misses % 100 == 0:
                                db.commit()

                except (ValueError, OSError) as exception:
                    corrupted_files += 1
                    reason = f"corrupted: {type(exception).__name__}"
                    skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                    print(f'Skipping corrupted/unreadable image: {image_path.name}', file=sys.stderr)
                    continue

                # Only check EXIF orientation if not from cache (cache already has corrected dimensions)
                if not cached and not is_video:
                    try:
                        with open(image_path, 'rb') as image_file:
                            exif_tags = exifread.process_file(
                                image_file, details=False, extract_thumbnail=False,
                                stop_tag='Image Orientation')
                            if 'Image Orientation' in exif_tags:
                                orientations = (exif_tags['Image Orientation']
                                                .values)
                                if any(value in orientations
                                       for value in (5, 6, 7, 8)):
                                    dimensions = (dimensions[1], dimensions[0])
                                    db.save_info(relative_path, dimensions[0], dimensions[1],
                                               is_video, mtime, video_metadata)
                    except Exception as exception:
                        error_messages.append(f'Failed to get Exif tags for '
                                              f'{image_path}: {exception}')

            tags = []
            text_file_path = image_path.with_suffix('.txt')
            if str(text_file_path) in text_file_path_strings:
                # `errors='replace'` inserts a replacement marker such as '?'
                # when there is malformed data.
                caption = text_file_path.read_text(encoding='utf-8',
                                                   errors='replace')
                if caption:
                    tags = caption.split(self.tag_separator)
                    tags = [tag.strip() for tag in tags]
                    tags = [tag for tag in tags if tag]
            image = Image(image_path, dimensions, tags, is_video=is_video,
                         video_metadata=video_metadata)
            # Store DB cached info (including thumbnail_cached flag) for fast cache checks
            image._db_cached_info = cached if cached else {}
            json_file_path = image_path.with_suffix('.json')
            if (str(json_file_path) in json_file_path_strings and
                json_file_path.stat().st_size > 0):
                with json_file_path.open(encoding='UTF-8') as source:
                    try:
                        meta = json.load(source)
                    except json.JSONDecodeError as e:
                        # Silently skip invalid JSON files
                        pass
                    except UnicodeDecodeError as e:
                        # Silently skip files with invalid unicode
                        pass

                    if meta.get('version') == 1:
                        crop = meta.get('crop')
                        if crop and type(crop) is list and len(crop) == 4:
                            image.crop = QRect(*crop)
                        rating = meta.get('rating')
                        if rating:
                            image.rating = rating
                        markings = meta.get('markings')
                        if markings and type(markings) is list:
                            for marking in markings:
                                marking = Marking(label=marking.get('label'),
                                                  type=ImageMarking[marking.get('type')],
                                                  rect=QRect(*marking.get('rect')),
                                                  confidence=marking.get('confidence', 1.0))
                                image.markings.append(marking)
                        loop_start = meta.get('loop_start_frame')
                        image.loop_start_frame = loop_start if isinstance(loop_start, int) else None
                        loop_end = meta.get('loop_end_frame')
                        image.loop_end_frame = loop_end if isinstance(loop_end, int) else None
                    # Silently ignore unsupported JSON versions (like ComfyUI workflow files)
            new_images.append(image)

        progress.setValue(total_images)  # Complete load

        # Close database (will reopen for background enrichment if needed)
        db.commit()
        db.close()

        # Print loading summary
        print("\n" + "="*80)
        print(f"LOAD SUMMARY: {len(new_images)} images loaded from {total_images} image files")
        if total_images != len(new_images):
            skipped = total_images - len(new_images)
            print(f"  ⚠ WARNING: {skipped} images were SKIPPED")
            if skip_reasons:
                print(f"  Skip reasons:")
                for reason, count in sorted(skip_reasons.items(), key=lambda x: -x[1]):
                    print(f"    - {count:5d} {reason}")
            else:
                print(f"    - No skip reasons tracked (unknown cause)")

        if cache_hits > 0 or cache_misses > 0:
            cache_rate = (cache_hits / (cache_hits + cache_misses)) * 100 if (cache_hits + cache_misses) > 0 else 0
            print(f"Database cache: {cache_hits} hits, {cache_misses} misses ({cache_rate:.1f}% hit rate)")
        print("="*80 + "\n")

        # new_images already sorted by image_paths ordering (no need to re-sort)

        # NOW reset the model (fast swap of data, minimal UI blocking)
        self.beginResetModel()
        self.images.clear()
        self.images = new_images
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.update_undo_and_redo_actions_requested.emit()
        self._rebuild_aspect_ratio_cache()  # Build cache after loading
        self.endResetModel()

        # Start background thumbnail loading (parallel I/O)
        self._preload_thumbnails_async()

        # If using fast load with uncached images, enrich dimensions in background
        if use_fast_load and cache_misses > 0:
            import time
            timestamp = time.strftime("%H:%M:%S")
            print(f"[ENRICH {timestamp}] Starting background enrichment for {cache_misses} images...")

            # Start timer to process enrichment queue on main thread
            from PySide6.QtCore import QTimer
            self._enrichment_timer = QTimer()
            self._enrichment_timer.timeout.connect(self._process_enrichment_queue)
            self._enrichment_timer.start(100)  # Check queue every 100ms

            # Enrich dimensions in background thread
            def enrich_dimensions():
                db_bg = ImageIndexDB(directory_path)
                enriched_count = 0
                enriched_indices = []  # Track which indices changed

                # Adaptive batching based on total image count
                commit_interval = 500 if total_images > 20000 else 100
                layout_update_interval = 1000 if total_images > 20000 else 100

                for idx, image in enumerate(self.images):
                    # Check if cancelled (e.g., due to sort/filter)
                    if self._enrichment_cancelled.is_set():
                        print(f"[FAST_LOAD] Background enrichment cancelled after {enriched_count} images")
                        db_bg.commit()
                        db_bg.close()
                        return

                    # Skip if already has real dimensions (from cache)
                    if image.dimensions != (512, 512):
                        continue

                    try:
                        is_video = image.path.suffix.lower() in video_extensions
                        relative_path = str(image.path.relative_to(directory_path))
                        mtime = image.path.stat().st_mtime

                        # Read actual dimensions
                        if is_video:
                            dimensions, video_metadata, _ = extract_video_info(image.path)
                            if dimensions is None:
                                continue
                            image.video_metadata = video_metadata
                        elif str(image.path).endswith('jxl'):
                            dimensions = get_jxl_size(image.path)
                        else:
                            dimensions = imagesize.get(str(image.path))
                            if dimensions == (-1, -1):
                                dimensions = pilimage.open(image.path).size

                        if not dimensions:
                            continue

                        # Check EXIF orientation
                        if not is_video:
                            try:
                                with open(image.path, 'rb') as image_file:
                                    exif_tags = exifread.process_file(
                                        image_file, details=False, extract_thumbnail=False,
                                        stop_tag='Image Orientation')
                                    if 'Image Orientation' in exif_tags:
                                        orientations = exif_tags['Image Orientation'].values
                                        if any(value in orientations for value in (5, 6, 7, 8)):
                                            dimensions = (dimensions[1], dimensions[0])
                            except Exception:
                                pass

                        # Send update to queue (THREAD-SAFE - no direct image modification)
                        self._enrichment_queue.put((idx, dimensions, video_metadata if is_video else None))
                        enriched_indices.append(idx)

                        # Save to cache
                        db_bg.save_info(relative_path, dimensions[0], dimensions[1],
                                      is_video, mtime, video_metadata if is_video else None)

                        enriched_count += 1

                        # Commit to database at intervals
                        if enriched_count % commit_interval == 0:
                            db_bg.commit()
                            # Log progress every commit
                            import time
                            timestamp = time.strftime("%H:%M:%S")
                            print(f"[ENRICH {timestamp}] Progress: {enriched_count}/{total_images} images enriched, queue size: {self._enrichment_queue.qsize()}")

                    except Exception:
                        pass  # Skip problematic images silently

                db_bg.commit()
                db_bg.close()

                import time
                timestamp = time.strftime("%H:%M:%S")
                print(f"[ENRICH {timestamp}] Background enrichment complete: {enriched_count} images updated")
                print(f"[ENRICH {timestamp}] Queue has {self._enrichment_queue.qsize()} pending updates for main thread")

                # Timer will continue processing queue until empty, then stop itself

            # Submit background enrichment task
            self._load_executor.submit(enrich_dimensions)

    def _load_directory_paginated(self, directory_path: Path, image_paths: list[Path], file_paths: set[Path]):
        """Load a large directory using pagination mode (10K+ images).

        Strategy: Load all Image objects upfront (cheap metadata ~16MB for 32K images),
        but lazy-load thumbnails on-demand (expensive ~40MB VRAM for visible items only).

        This prevents Qt crashes from rendering 32K items where data() returns None.
        """
        from PySide6.QtWidgets import QProgressDialog, QApplication
        from PySide6.QtCore import Qt

        total_images = len(image_paths)
        video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.webm'}

        # Initialize database
        self._directory_path = directory_path
        self._db = ImageIndexDB(directory_path)
        self._paginated_mode = True

        # Check if we need indexing or can use fast load
        db_count = self._db.count()
        needs_full_index = abs(db_count - total_images) >= 100

        if needs_full_index:
            # Only index if significantly out of sync (new directory or many new files)
            # For small differences, use fast load with background enrichment
            print(f"[PAGINATION] Database has {db_count} entries, folder has {total_images} files")
            print(f"[PAGINATION] Using fast load - will index missing files in background")

        # No blocking indexing - just load with placeholders and enrich in background

        # Load ALL Image objects with fast load (use placeholders for uncached)
        print(f"[PAGINATION] Fast loading {total_images} images...")
        progress = QProgressDialog(f"Loading {total_images} images...", None, 0, total_images)
        progress.setWindowTitle("Loading Images")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(500)
        progress.setAutoClose(True)
        progress.setAutoReset(False)

        self.beginResetModel()
        self.images = []

        # Load cached info from DB into dict (fast bulk load)
        cached_files = {}
        try:
            cursor = self._db.conn.cursor()
            cursor.execute('SELECT file_name, width, height, is_video, mtime, video_fps, video_duration, video_frame_count, rating FROM images')
            for row in cursor:
                cached_files[row[0]] = {
                    'dimensions': (row[1], row[2]),
                    'is_video': bool(row[3]),
                    'mtime': row[4],
                    'video_metadata': {
                        'fps': row[5],
                        'duration': row[6],
                        'frame_count': row[7]
                    } if row[3] else None,
                    'rating': row[8] if row[8] is not None else 0.0
                }
            print(f"[PAGINATION] Loaded {len(cached_files)} cached entries from DB")
        except Exception as e:
            print(f"[PAGINATION] Warning: Could not load cache: {e}")

        # Gather text file paths for tag loading
        text_file_paths = set()
        for path in directory_path.rglob("*.txt"):
            text_file_paths.add(str(path))

        # Load all images (from cache or with placeholders)
        update_interval = max(100, total_images // 100)
        cache_hits = 0
        cache_misses = 0

        for i, image_path in enumerate(image_paths):
            # Update progress
            if i % update_interval == 0:
                progress.setValue(i)
                QApplication.processEvents()

            try:
                relative_path = str(image_path.relative_to(directory_path))
                mtime = image_path.stat().st_mtime

                # Check cache
                cached = cached_files.get(relative_path)
                if cached and cached['mtime'] == mtime:
                    # Use cached dimensions
                    dimensions = cached['dimensions']
                    is_video = cached['is_video']
                    video_metadata = cached['video_metadata']
                    rating = cached['rating']
                    cache_hits += 1
                else:
                    # Use placeholder - will enrich in background
                    dimensions = (512, 512)
                    is_video = image_path.suffix.lower() in video_extensions
                    video_metadata = None
                    rating = 0.0
                    cache_misses += 1

                # Load tags from text file
                tags = []
                text_file_path = image_path.with_suffix('.txt')
                if str(text_file_path) in text_file_paths:
                    try:
                        caption = text_file_path.read_text(encoding='utf-8', errors='replace')
                        if caption:
                            tags = [tag.strip() for tag in caption.split(self.tag_separator) if tag.strip()]
                    except Exception:
                        pass

                image = Image(
                    path=image_path,
                    dimensions=dimensions,
                    tags=tags,
                    is_video=is_video,
                    rating=rating
                )

                if is_video and video_metadata:
                    image.video_metadata = video_metadata

                self.images.append(image)

            except Exception as e:
                print(f"[PAGINATION] Error loading {image_path.name}: {e}")

        progress.close()
        print(f"[PAGINATION] Loaded {len(self.images)} images ({cache_hits} cached, {cache_misses} need enrichment)")

        self._total_count = len(self.images)
        print(f"[PAGINATION] Loaded {self._total_count} Image objects (~{self._total_count * 300 / 1024 / 1024:.1f} MB)")

        self.endResetModel()

        # Build aspect ratio cache
        self._rebuild_aspect_ratio_cache()

        # Emit signal
        self.total_count_changed.emit(self._total_count)

        print(f"================================================================================")
        print(f"PAGINATION MODE: {self._total_count} images loaded (thumbnails lazy-load)")
        print(f"Memory: ~{self._total_count * 300 / 1024 / 1024:.1f} MB for Image objects")
        print(f"VRAM: ~40 MB max (only visible thumbnails loaded)")
        print(f"================================================================================")

        # Start background enrichment if needed
        if cache_misses > 0:
            print(f"[PAGINATION] Starting background enrichment for {cache_misses} uncached images...")
            self._restart_enrichment()

    def _restart_enrichment(self):
        """Restart background enrichment after sorting/filtering (with new indices)."""
        # Pagination mode now uses enrichment too for uncached files

        # Clear cancellation flag
        self._enrichment_cancelled.clear()

        # Count how many images still need enrichment
        needs_enrichment = sum(1 for img in self.images if img.dimensions == (512, 512))

        if needs_enrichment == 0:
            return  # Nothing to enrich

        import time
        timestamp = time.strftime("%H:%M:%S")
        print(f"[ENRICH {timestamp}] Restarting background enrichment for {needs_enrichment} images after sort")

        # Start/restart timer if not already running
        if not self._enrichment_timer:
            from PySide6.QtCore import QTimer
            self._enrichment_timer = QTimer()
            self._enrichment_timer.timeout.connect(self._process_enrichment_queue)
        if not self._enrichment_timer.isActive():
            self._enrichment_timer.start(100)

        # Reuse the same enrichment logic
        def enrich_dimensions():
            from utils.image_index_db import ImageIndexDB
            from utils.settings import settings
            import sys

            directory_path = self.images[0].path.parent if self.images else None
            if not directory_path:
                return

            db_bg = ImageIndexDB(directory_path)
            enriched_count = 0
            enriched_indices = []
            video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.webm'}

            # Adaptive batching based on total image count
            total_images = len(self.images)
            commit_interval = 500 if total_images > 20000 else 100
            layout_update_interval = 1000 if total_images > 20000 else 100

            for idx, image in enumerate(self.images):
                # Check if cancelled
                if self._enrichment_cancelled.is_set():
                    print(f"[SORT] Background enrichment cancelled after {enriched_count} images")
                    db_bg.commit()
                    db_bg.close()
                    return

                # Skip if already has real dimensions
                if image.dimensions != (512, 512):
                    continue

                try:
                    is_video = image.path.suffix.lower() in video_extensions
                    relative_path = str(image.path.relative_to(directory_path))
                    mtime = image.path.stat().st_mtime

                    # Read actual dimensions
                    if is_video:
                        from models.image_list_model import extract_video_info
                        dimensions, video_metadata, _ = extract_video_info(image.path)
                        if dimensions is None:
                            continue
                        image.video_metadata = video_metadata
                    elif str(image.path).endswith('jxl'):
                        from utils.jxlutil import get_jxl_size
                        dimensions = get_jxl_size(image.path)
                    else:
                        import imagesize
                        dimensions = imagesize.get(str(image.path))
                        if dimensions == (-1, -1):
                            from PIL import Image as pilimage
                            dimensions = pilimage.open(image.path).size

                    if not dimensions:
                        continue

                    # Check EXIF orientation
                    if not is_video:
                        try:
                            import exifread
                            with open(image.path, 'rb') as image_file:
                                exif_tags = exifread.process_file(
                                    image_file, details=False, extract_thumbnail=False,
                                    stop_tag='Image Orientation')
                                if 'Image Orientation' in exif_tags:
                                    orientations = exif_tags['Image Orientation'].values
                                    if any(value in orientations for value in (5, 6, 7, 8)):
                                        dimensions = (dimensions[1], dimensions[0])
                        except Exception:
                            pass

                    # Send update to queue (THREAD-SAFE)
                    self._enrichment_queue.put((idx, dimensions, video_metadata if is_video else None))
                    enriched_indices.append(idx)

                    # Save to cache
                    db_bg.save_info(relative_path, dimensions[0], dimensions[1],
                                  is_video, mtime, video_metadata if is_video else None)

                    enriched_count += 1

                    # Commit to database and log at intervals
                    if enriched_count % commit_interval == 0:
                        db_bg.commit()
                        import time
                        timestamp = time.strftime("%H:%M:%S")
                        print(f"[ENRICH {timestamp}] Progress: {enriched_count}/{total_images} images enriched")

                except Exception:
                    pass

            db_bg.commit()
            db_bg.close()

            print(f"[SORT] Background enrichment complete: {enriched_count} images updated")

            import time
            timestamp = time.strftime("%H:%M:%S")
            print(f"[ENRICH {timestamp}] Sort enrichment complete: {enriched_count} images updated")
            print(f"[ENRICH {timestamp}] Queue has {self._enrichment_queue.qsize()} pending updates")

        # Submit enrichment task
        self._load_executor.submit(enrich_dimensions)

    def add_to_undo_stack(self, action_name: str,
                          should_ask_for_confirmation: bool):
        """Add the current state of the image tags to the undo stack."""
        tags = [{'tags': image.tags.copy(),
                 'rating': image.rating,
                 'crop': QRect(image.crop) if image.crop is not None else None,
                 'markings': image.markings.copy(),
                 'loop_start_frame': image.loop_start_frame,
                 'loop_end_frame': image.loop_end_frame} for image in self.images]
        self.undo_stack.append(HistoryItem(action_name, tags,
                                           should_ask_for_confirmation))
        self.redo_stack.clear()
        self.update_undo_and_redo_actions_requested.emit()

    def write_image_tags_to_disk(self, image: Image):
        try:
            image.path.with_suffix('.txt').write_text(
                self.tag_separator.join(image.tags), encoding='utf-8',
                errors='replace')

            # Also update database if in paginated mode
            if self._paginated_mode:
                self._save_tags_to_db(image)

        except OSError:
            error_message_box = QMessageBox()
            error_message_box.setWindowTitle('Error')
            error_message_box.setIcon(QMessageBox.Icon.Critical)
            error_message_box.setText(f'Failed to save tags for {image.path}.')
            error_message_box.exec()

    def _save_tags_to_db(self, image: Image):
        """Save tags to database (for paginated mode)."""
        if not self._paginated_mode or not self._db:
            return

        # Get image ID from filename
        image_id = self._db.get_image_id(image.path.name)
        if image_id:
            self._db.set_tags_for_image(image_id, image.tags)

    def write_meta_to_disk(self, image: Image):
        does_exist = image.path.with_suffix('.json').exists()
        meta: dict[str, any] = {'version': 1, 'rating': image.rating}
        if image.crop is not None:
            meta['crop'] = image.crop.getRect()
        meta['markings'] = [{'label': marking.label,
                             'type': marking.type.name,
                             'confidence': marking.confidence,
                             'rect': marking.rect.getRect()} for marking in image.markings]
        meta['loop_start_frame'] = image.loop_start_frame
        meta['loop_end_frame'] = image.loop_end_frame
        if does_exist or len(meta.keys()) > 1:
            try:
                with image.path.with_suffix('.json').open('w', encoding='UTF-8') as meta_file:
                    json.dump(meta, meta_file)
            except OSError:
                error_message_box = QMessageBox()
                error_message_box.setWindowTitle('Error')
                error_message_box.setIcon(QMessageBox.Icon.Critical)
                error_message_box.setText(f'Failed to save JSON for {image.path}.')
                error_message_box.exec()

    def restore_history_tags(self, is_undo: bool):
        if is_undo:
            source_stack = self.undo_stack
            destination_stack = self.redo_stack
        else:
            # Redo.
            source_stack = self.redo_stack
            destination_stack = self.undo_stack
        if not source_stack:
            return
        history_item = source_stack[-1]
        if history_item.should_ask_for_confirmation:
            undo_or_redo_string = 'Undo' if is_undo else 'Redo'
            reply = get_confirmation_dialog_reply(
                title=undo_or_redo_string,
                question=f'{undo_or_redo_string} '
                         f'"{history_item.action_name}"?')
            if reply != QMessageBox.StandardButton.Yes:
                return
        source_stack.pop()
        tags = [{'tags': image.tags.copy(),
                 'rating': image.rating,
                 'crop': QRect(image.crop) if image.crop is not None else None,
                 'markings': image.markings.copy(),
                 'loop_start_frame': image.loop_start_frame,
                 'loop_end_frame': image.loop_end_frame} for image in self.images]
        destination_stack.append(HistoryItem(
            history_item.action_name, tags,
            history_item.should_ask_for_confirmation))
        changed_image_indices = []
        for image_index, (image, history_image_tags) in enumerate(
                zip(self.images, history_item.tags)):
            if (image.tags == history_image_tags['tags'] and
                image.rating == history_image_tags['rating'] and
                image.crop == history_image_tags['crop'] and
                image.markings == history_image_tags['markings'] and
                image.loop_start_frame == history_image_tags.get('loop_start_frame') and
                image.loop_end_frame == history_image_tags.get('loop_end_frame')):
                continue
            changed_image_indices.append(image_index)
            image.tags = history_image_tags['tags']
            image.rating = history_image_tags['rating']
            image.crop = history_image_tags['crop']
            image.markings = history_image_tags['markings']
            image.loop_start_frame = history_image_tags.get('loop_start_frame')
            image.loop_end_frame = history_image_tags.get('loop_end_frame')
            self.write_image_tags_to_disk(image)
            self.write_meta_to_disk(image)
        if changed_image_indices:
            self.dataChanged.emit(self.index(changed_image_indices[0]),
                                  self.index(changed_image_indices[-1]))
        self.update_undo_and_redo_actions_requested.emit()

    @Slot()
    def undo(self):
        """Undo the last action."""
        self.restore_history_tags(is_undo=True)

    @Slot()
    def redo(self):
        """Redo the last undone action."""
        self.restore_history_tags(is_undo=False)

    def is_image_in_scope(self, scope: Scope | str, image_index: int,
                          image: Image) -> bool:
        if scope == Scope.ALL_IMAGES:
            return True
        if scope == Scope.FILTERED_IMAGES:
            return self.proxy_image_list_model.is_image_in_filtered_images(
                image)
        if scope == Scope.SELECTED_IMAGES:
            proxy_index = self.proxy_image_list_model.mapFromSource(
                self.index(image_index))
            return self.image_list_selection_model.isSelected(proxy_index)

    def get_text_match_count(self, text: str, scope: Scope | str,
                             whole_tags_only: bool, use_regex: bool) -> int:
        """Get the number of instances of a text in all captions."""
        # In paginated mode with ALL_IMAGES scope, use database
        if self._paginated_mode and scope == Scope.ALL_IMAGES:
            return self._db.count_tag_matches(text, use_regex, whole_tags_only)

        # For other scopes or regular mode, iterate through loaded images
        match_count = 0
        for image_index, image in enumerate(self.iter_all_images()):
            if not self.is_image_in_scope(scope, image_index, image):
                continue
            if whole_tags_only:
                if use_regex:
                    match_count += len([
                        tag for tag in image.tags
                        if re.fullmatch(pattern=text, string=tag)
                    ])
                else:
                    match_count += image.tags.count(text)
            else:
                caption = self.tag_separator.join(image.tags)
                if use_regex:
                    match_count += len(re.findall(pattern=text,
                                                  string=caption))
                else:
                    match_count += caption.count(text)
        return match_count

    def find_and_replace(self, find_text: str, replace_text: str,
                         scope: Scope | str, use_regex: bool):
        """
        Find and replace arbitrary text in captions, within and across tag
        boundaries.
        """
        if not find_text:
            return
        self.add_to_undo_stack(action_name='Find and Replace',
                               should_ask_for_confirmation=True)

        # In paginated mode with ALL_IMAGES scope, use database
        if self._paginated_mode and scope == Scope.ALL_IMAGES:
            affected_count = self._db.find_replace_tags(find_text, replace_text, use_regex)
            print(f"[FIND/REPLACE] Updated {affected_count} images in database")

            # Invalidate all loaded pages to force reload with updated tags
            self._pages.clear()
            self._page_load_order.clear()

            # Reload first page
            self._load_page_sync(0)

            # Emit full model reset
            self.beginResetModel()
            self.endResetModel()
            return

        # For other scopes or regular mode, iterate through loaded images
        changed_image_indices = []
        for image_index, image in enumerate(self.iter_all_images()):
            if not self.is_image_in_scope(scope, image_index, image):
                continue
            caption = self.tag_separator.join(image.tags)
            if use_regex:
                if not re.search(pattern=find_text, string=caption):
                    continue
                caption = re.sub(pattern=find_text, repl=replace_text,
                                 string=caption)
            else:
                if find_text not in caption:
                    continue
                caption = caption.replace(find_text, replace_text)
            changed_image_indices.append(image_index)
            image.tags = caption.split(self.tag_separator)
            self.write_image_tags_to_disk(image)

            # In paginated mode, also update database
            if self._paginated_mode:
                self._save_tags_to_db(image)

        if changed_image_indices:
            self.dataChanged.emit(self.index(changed_image_indices[0]),
                                  self.index(changed_image_indices[-1]))

    def sort_tags_alphabetically(self, do_not_reorder_first_tag: bool):
        """Sort the tags for each image in alphabetical order."""
        self.add_to_undo_stack(action_name='Sort Tags',
                               should_ask_for_confirmation=True)
        changed_image_indices = []
        for image_index, image in enumerate(self.iter_all_images()):
            if len(image.tags) < 2:
                continue
            old_caption = self.tag_separator.join(image.tags)
            if do_not_reorder_first_tag:
                first_tag = image.tags[0]
                image.tags = [first_tag] + sorted(image.tags[1:])
            else:
                image.tags.sort()
            new_caption = self.tag_separator.join(image.tags)
            if new_caption != old_caption:
                changed_image_indices.append(image_index)
                self.write_image_tags_to_disk(image)
        if changed_image_indices:
            self.dataChanged.emit(self.index(changed_image_indices[0]),
                                  self.index(changed_image_indices[-1]))

    def sort_tags_by_frequency(self, tag_counter: Counter,
                               do_not_reorder_first_tag: bool):
        """
        Sort the tags for each image by the total number of times a tag appears
        across all images.
        """
        self.add_to_undo_stack(action_name='Sort Tags',
                               should_ask_for_confirmation=True)
        changed_image_indices = []
        for image_index, image in enumerate(self.iter_all_images()):
            if len(image.tags) < 2:
                continue
            old_caption = self.tag_separator.join(image.tags)
            if do_not_reorder_first_tag:
                first_tag = image.tags[0]
                image.tags = [first_tag] + sorted(
                    image.tags[1:], key=lambda tag: tag_counter[tag],
                    reverse=True)
            else:
                image.tags.sort(key=lambda tag: tag_counter[tag], reverse=True)
            new_caption = self.tag_separator.join(image.tags)
            if new_caption != old_caption:
                changed_image_indices.append(image_index)
                self.write_image_tags_to_disk(image)
        if changed_image_indices:
            self.dataChanged.emit(self.index(changed_image_indices[0]),
                                  self.index(changed_image_indices[-1]))

    def reverse_tags_order(self, do_not_reorder_first_tag: bool):
        """Reverse the order of the tags for each image."""
        self.add_to_undo_stack(action_name='Reverse Order of Tags',
                               should_ask_for_confirmation=True)
        changed_image_indices = []
        for image_index, image in enumerate(self.iter_all_images()):
            if len(image.tags) < 2:
                continue
            changed_image_indices.append(image_index)
            if do_not_reorder_first_tag:
                image.tags = [image.tags[0]] + list(reversed(image.tags[1:]))
            else:
                image.tags = list(reversed(image.tags))
            self.write_image_tags_to_disk(image)
        if changed_image_indices:
            self.dataChanged.emit(self.index(changed_image_indices[0]),
                                  self.index(changed_image_indices[-1]))

    def shuffle_tags(self, do_not_reorder_first_tag: bool):
        """Shuffle the tags for each image randomly."""
        self.add_to_undo_stack(action_name='Shuffle Tags',
                               should_ask_for_confirmation=True)
        changed_image_indices = []
        for image_index, image in enumerate(self.iter_all_images()):
            if len(image.tags) < 2:
                continue
            changed_image_indices.append(image_index)
            if do_not_reorder_first_tag:
                first_tag, *remaining_tags = image.tags
                random.shuffle(remaining_tags)
                image.tags = [first_tag] + remaining_tags
            else:
                random.shuffle(image.tags)
            self.write_image_tags_to_disk(image)
        if changed_image_indices:
            self.dataChanged.emit(self.index(changed_image_indices[0]),
                                  self.index(changed_image_indices[-1]))

    def sort_sentences_down(self, separate_newline: bool):
        """Sort the tags so that the sentences are on the bottom."""
        self.add_to_undo_stack(action_name='Sort Sentence Tags',
                               should_ask_for_confirmation=True)
        changed_image_indices = []
        for image_index, image in enumerate(self.iter_all_images()):
            changed_image_indices.append(image_index)
            sentence_tags = []
            non_sentence_tags = []
            for tag in image.tags:
                if separate_newline and tag == '#newline':
                    continue
                if tag.endswith('.'):
                    sentence_tags.append(tag)
                else:
                    non_sentence_tags.append(tag)
            if separate_newline:
                if len(sentence_tags) > 0:
                    non_sentence_tags.append(sentence_tags.pop())
                for tag in sentence_tags:
                    non_sentence_tags.append('#newline')
                    non_sentence_tags.append(tag)
            else:
                non_sentence_tags.extend(sentence_tags)
            image.tags = non_sentence_tags
            self.write_image_tags_to_disk(image)
        if changed_image_indices:
            self.dataChanged.emit(self.index(changed_image_indices[0]),
                                  self.index(changed_image_indices[-1]))

    def move_tags_to_front(self, tags_to_move: list[str]):
        """
        Move one or more tags to the front of the tags list for each image.
        """
        self.add_to_undo_stack(action_name='Move Tags to Front',
                               should_ask_for_confirmation=True)
        changed_image_indices = []
        for image_index, image in enumerate(self.iter_all_images()):
            if not any(tag in image.tags for tag in tags_to_move):
                continue
            old_caption = self.tag_separator.join(image.tags)
            moved_tags = []
            for tag in tags_to_move:
                tag_count = image.tags.count(tag)
                moved_tags.extend([tag] * tag_count)
            unmoved_tags = [tag for tag in image.tags if tag not in moved_tags]
            image.tags = moved_tags + unmoved_tags
            new_caption = self.tag_separator.join(image.tags)
            if new_caption != old_caption:
                changed_image_indices.append(image_index)
                self.write_image_tags_to_disk(image)
        if changed_image_indices:
            self.dataChanged.emit(self.index(changed_image_indices[0]),
                                  self.index(changed_image_indices[-1]))

    def remove_duplicate_tags(self) -> int:
        """
        Remove duplicate tags for each image. Return the number of removed
        tags.
        """
        self.add_to_undo_stack(action_name='Remove Duplicate Tags',
                               should_ask_for_confirmation=True)
        changed_image_indices = []
        removed_tag_count = 0
        for image_index, image in enumerate(self.iter_all_images()):
            tag_count = len(image.tags)
            unique_tag_count = len(set(image.tags))
            if tag_count == unique_tag_count:
                continue
            changed_image_indices.append(image_index)
            removed_tag_count += tag_count - unique_tag_count
            # Use a dictionary instead of a set to preserve the order.
            image.tags = list(dict.fromkeys(image.tags))
            self.write_image_tags_to_disk(image)
        if changed_image_indices:
            self.dataChanged.emit(self.index(changed_image_indices[0]),
                                  self.index(changed_image_indices[-1]))
        return removed_tag_count

    def remove_empty_tags(self) -> int:
        """
        Remove empty tags (tags that are empty strings or only contain
        whitespace) for each image. Return the number of removed tags.
        """
        self.add_to_undo_stack(action_name='Remove Empty Tags',
                               should_ask_for_confirmation=True)
        changed_image_indices = []
        removed_tag_count = 0
        for image_index, image in enumerate(self.iter_all_images()):
            old_tag_count = len(image.tags)
            image.tags = [tag for tag in image.tags if tag.strip()]
            new_tag_count = len(image.tags)
            if old_tag_count == new_tag_count:
                continue
            changed_image_indices.append(image_index)
            removed_tag_count += old_tag_count - new_tag_count
            self.write_image_tags_to_disk(image)
        if changed_image_indices:
            self.dataChanged.emit(self.index(changed_image_indices[0]),
                                  self.index(changed_image_indices[-1]))
        return removed_tag_count

    def update_image_tags(self, image_index: QModelIndex, tags: list[str]):
        image: Image = self.data(image_index, Qt.ItemDataRole.UserRole)
        if image.tags == tags:
            return
        image.tags = tags
        self.dataChanged.emit(image_index, image_index)
        self.write_image_tags_to_disk(image)

    @Slot(list, list)
    def add_tags(self, tags: list[str], image_indices: list[QModelIndex]):
        """Add one or more tags to one or more images."""
        if not image_indices:
            return
        action_name = f'Add {pluralize("Tag", len(tags))}'
        should_ask_for_confirmation = len(image_indices) > 1
        self.add_to_undo_stack(action_name, should_ask_for_confirmation)
        for image_index in image_indices:
            image: Image = self.data(image_index, Qt.ItemDataRole.UserRole)
            image.tags.extend(tags)
            self.write_image_tags_to_disk(image)
        min_image_index = min(image_indices, key=lambda index: index.row())
        max_image_index = max(image_indices, key=lambda index: index.row())
        self.dataChanged.emit(min_image_index, max_image_index)

    @Slot(list, str)
    def rename_tags(self, old_tags: list[str], new_tag: str,
                    scope: Scope | str = Scope.ALL_IMAGES,
                    use_regex: bool = False):
        self.add_to_undo_stack(
            action_name=f'Rename {pluralize("Tag", len(old_tags))}',
            should_ask_for_confirmation=True)
        changed_image_indices = []
        for image_index, image in enumerate(self.iter_all_images()):
            if not self.is_image_in_scope(scope, image_index, image):
                continue
            if use_regex:
                pattern = old_tags[0]
                if not any(re.fullmatch(pattern=pattern, string=image_tag)
                           for image_tag in image.tags):
                    continue
                image.tags = [new_tag if re.fullmatch(pattern=pattern,
                                                      string=image_tag)
                              else image_tag for image_tag in image.tags]
            else:
                if not any(old_tag in image.tags for old_tag in old_tags):
                    continue
                image.tags = [new_tag if image_tag in old_tags else image_tag
                              for image_tag in image.tags]
            changed_image_indices.append(image_index)
            self.write_image_tags_to_disk(image)
        if changed_image_indices:
            self.dataChanged.emit(self.index(changed_image_indices[0]),
                                  self.index(changed_image_indices[-1]))

    @Slot(list)
    def delete_tags(self, tags: list[str],
                    scope: Scope | str = Scope.ALL_IMAGES,
                    use_regex: bool = False):
        self.add_to_undo_stack(
            action_name=f'Delete {pluralize("Tag", len(tags))}',
            should_ask_for_confirmation=True)
        changed_image_indices = []
        for image_index, image in enumerate(self.iter_all_images()):
            if not self.is_image_in_scope(scope, image_index, image):
                continue
            if use_regex:
                pattern = tags[0]
                if not any(re.fullmatch(pattern=pattern, string=image_tag)
                           for image_tag in image.tags):
                    continue
                image.tags = [image_tag for image_tag in image.tags
                              if not re.fullmatch(pattern=pattern,
                                                  string=image_tag)]
            else:
                if not any(tag in image.tags for tag in tags):
                    continue
                image.tags = [image_tag for image_tag in image.tags
                              if image_tag not in tags]
            changed_image_indices.append(image_index)
            self.write_image_tags_to_disk(image)
        if changed_image_indices:
            self.dataChanged.emit(self.index(changed_image_indices[0]),
                                  self.index(changed_image_indices[-1]))

    def add_image_markings(self, image_index: QModelIndex, markings: list[dict]):
        image: Image = self.data(image_index, Qt.ItemDataRole.UserRole)
        for marking in markings:
            marking_type = {
                'hint': ImageMarking.HINT,
                'include': ImageMarking.INCLUDE,
                'exclude': ImageMarking.EXCLUDE}[marking['type']]
            box = marking['box']
            top_left = QPoint(floor(box[0]), floor(box[1]))
            bottom_right = QPoint(ceil(box[2]), ceil(box[3]))
            image.markings.append(Marking(label=marking['label'],
                                          type=marking_type,
                                          rect=QRect(top_left, bottom_right),
                                          confidence=marking['confidence']))
        if len(markings) > 0:
            self.dataChanged.emit(image_index, image_index)
            self.write_meta_to_disk(image)

    def add_image(self, image_path: Path):
        """
        Add a single image to the model. This is used for duplicating images
        without reloading the entire directory.
        """
        # Check if image is already in the list
        if any(img.path == image_path for img in self.images):
            return

        # Determine if it's a video
        video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.webm'}
        is_video = image_path.suffix.lower() in video_extensions
        video_metadata = None
        first_frame_pixmap = None

        try:
            if is_video:
                # Handle video files
                dimensions, video_metadata, first_frame_pixmap = extract_video_info(image_path)
                if dimensions is None:
                    return  # Skip if video info extraction fails
            elif str(image_path).endswith('jxl'):
                dimensions = get_jxl_size(image_path)
            else:
                dimensions = pilimage.open(image_path).size

            if not is_video:
                # Only get EXIF for images, not videos
                try:
                    with open(image_path, 'rb') as image_file:
                        exif_tags = exifread.process_file(
                            image_file, details=False, extract_thumbnail=False,
                            stop_tag='Image Orientation')
                        if 'Image Orientation' in exif_tags:
                            orientations = (exif_tags['Image Orientation']
                                            .values)
                            if any(value in orientations
                                   for value in (5, 6, 7, 8)):
                                dimensions = (dimensions[1], dimensions[0])
                except Exception:
                    pass  # Ignore EXIF errors for duplicates
        except (ValueError, OSError):
            return  # Skip if dimensions cannot be obtained

        tags = []
        text_file_path = image_path.with_suffix('.txt')
        if text_file_path.exists():
            # `errors='replace'` inserts a replacement marker such as '?'
            # when there is malformed data.
            caption = text_file_path.read_text(encoding='utf-8',
                                               errors='replace')
            if caption:
                tags = caption.split(self.tag_separator)
                tags = [tag.strip() for tag in tags]
                tags = [tag for tag in tags if tag]

        image = Image(image_path, dimensions, tags, is_video=is_video,
                     video_metadata=video_metadata)

        json_file_path = image_path.with_suffix('.json')
        if json_file_path.exists() and json_file_path.stat().st_size > 0:
            with json_file_path.open(encoding='UTF-8') as source:
                try:
                    meta = json.load(source)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass  # Ignore JSON errors for duplicates
                else:
                    if meta.get('version') == 1:
                        crop = meta.get('crop')
                        if crop and type(crop) is list and len(crop) == 4:
                            image.crop = QRect(*crop)
                        rating = meta.get('rating')
                        if rating:
                            image.rating = rating
                        markings = meta.get('markings')
                        if markings and type(markings) is list:
                            for marking in markings:
                                marking = Marking(label=marking.get('label'),
                                                  type=ImageMarking[marking.get('type')],
                                                  rect=QRect(*marking.get('rect')),
                                                  confidence=marking.get('confidence', 1.0))
                                image.markings.append(marking)
                        loop_start = meta.get('loop_start_frame')
                        if loop_start is not None and isinstance(loop_start, int):
                            image.loop_start_frame = loop_start
                        loop_end = meta.get('loop_end_frame')
                        if loop_end is not None and isinstance(loop_end, int):
                            image.loop_end_frame = loop_end

        # Insert the image in the correct sorted position
        # Use natural sort key for insertion
        insert_pos = 0
        image_key = natural_sort_key(image_path)
        for i, existing_image in enumerate(self.images):
            if natural_sort_key(existing_image.path) > image_key:
                insert_pos = i
                break
        else:
            insert_pos = len(self.images)

        self.beginInsertRows(QModelIndex(), insert_pos, insert_pos)
        self.images.insert(insert_pos, image)
        self.endInsertRows()
