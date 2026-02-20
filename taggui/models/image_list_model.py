import random
import re
import sys
import time
from typing import List, Dict, Any, Optional
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
# Global lock for thumbnail cache writes (limits I/O contention during scroll).
_thumbnail_save_lock = threading.Lock()

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

def load_thumbnail_data(
    image_path: Path, crop: QRect, thumbnail_width: int, is_video: bool
) -> tuple[QImage | None, bool, tuple[int, int] | None]:
    """
    Load thumbnail data (can run in background thread - uses QImage which IS thread-safe).

    Args:
        image_path: Path to the image/video file
        crop: Crop rectangle (or None for full image)
        thumbnail_width: Width to scale thumbnail to
        is_video: Whether this is a video file

    Returns:
        (qimage, was_cached, original_size): QImage, cache-hit flag,
        and original dimensions when available.
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

            cached_qimage = None
            if cache_path.exists():
                # Load directly as QImage (thread-safe, no QIcon/QPixmap needed)
                cached_qimage = QImage(str(cache_path))
            if cached_qimage is not None and not cached_qimage.isNull():
                return (cached_qimage, True, None)  # Cache hit! (No original dims from cache)
    except Exception:
        pass  # Cache check failed, fall through to generation

    # Generate new thumbnail using QImage (thread-safe for creation)
    original_size = None
    try:
        if is_video:
            # For videos, extract first frame as thumbnail (returns QImage, thread-safe)
            dims, _, first_frame_image = extract_video_info(image_path)
            original_size = dims
            if first_frame_image and not first_frame_image.isNull():
                qimage = first_frame_image.scaledToWidth(
                    thumbnail_width,
                    Qt.TransformationMode.SmoothTransformation)
            else:
                # Fallback to a placeholder
                qimage = QImage(thumbnail_width, thumbnail_width, QImage.Format_RGB888)
                qimage.fill(Qt.gray)
        elif image_path.suffix.lower() == ".jxl":
            pil_image = pilimage.open(image_path)  # Uses pillow-jxl
            original_size = pil_image.size
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
            original_size = tuple(image_reader.size().toTuple())
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
        return qimage, False, original_size
    except Exception as e:
        print(f"Error loading image/video {image_path}: {e}")
        # Return a placeholder QImage
        qimage = QImage(thumbnail_width, thumbnail_width, QImage.Format_RGB888)
        qimage.fill(Qt.gray)
        return qimage, False, None


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

def get_file_paths(directory_path: Path, progress_callback=None) -> set[Path]:
    """
    Recursively get all file paths in a directory, including
    subdirectories. Includes symlinks.
    """
    file_paths = set()
    print(f"[SCAN] Scanning directory: {directory_path}")
    count = 0
    for path in directory_path.rglob("*"):  # Use rglob for recursive search
        # Accept regular files or symlinks (for organized workflows and test datasets)
        if path.is_file() or path.is_symlink():
            file_paths.add(path)
            count += 1
            if progress_callback and count % 20000 == 0:
                try:
                    progress_callback(count)
                except Exception:
                    pass
            # Progress feedback for large directories
            if count % 100000 == 0:
                print(f"[SCAN] Found {count:,} files...")
    if progress_callback:
        try:
            progress_callback(count)
        except Exception:
            pass
    print(f"[SCAN] Scan complete: {len(file_paths):,} total files found")
    return file_paths


def get_directory_tree_stats(directory_path: Path, progress_callback=None) -> tuple[int, float]:
    """
    Fast recursive filesystem stats for cache freshness checks.

    Returns:
        (file_count, max_mtime_seen) where max_mtime_seen is the latest mtime of
        any directory entry in the tree.
    """
    import os

    file_count = 0
    max_mtime = 0.0
    stack = [directory_path]

    try:
        root_stat = directory_path.stat()
        max_mtime = float(root_stat.st_mtime)
    except OSError:
        pass

    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        stat = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue

                    mtime = float(getattr(stat, "st_mtime", 0.0) or 0.0)
                    if mtime > max_mtime:
                        max_mtime = mtime

                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False) or entry.is_symlink():
                        file_count += 1
                        if progress_callback and file_count % 20000 == 0:
                            try:
                                progress_callback(file_count)
                            except Exception:
                                pass
        except OSError:
            continue

    if progress_callback:
        try:
            progress_callback(file_count)
        except Exception:
            pass

    return file_count, max_mtime


def extract_video_info(video_path: Path) -> tuple[tuple[int, int] | None, dict | None, QImage | None]:
    """
    Extract metadata and first frame from a video file.
    Returns: (dimensions, video_metadata, first_frame_image)

    Thread-safe: Uses global lock to prevent OpenCV/ffmpeg crashes.
    Returns QImage (thread-safe) instead of QPixmap (main-thread only).
    """
    with _video_lock:
        try:
            # Force software decoding (CAP_FFMPEG backend, no DXVA/D3D11 HW accel).
            # OpenCV is built with DXVA + NVD3D11 support — if hw accel is active while
            # MPV's D3D11 renderer is running, both fight over the D3D11 device and trigger
            # exception 0xe24c4a02 in the GPU driver. SW decode avoids the conflict entirely.
            cap = cv2.VideoCapture(str(video_path), cv2.CAP_FFMPEG)
            cap.set(cv2.CAP_PROP_HW_ACCELERATION, cv2.VIDEO_ACCELERATION_NONE)
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

            # Convert BGR to RGB — return QImage (thread-safe; caller converts to QPixmap if needed)
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = frame_rgb.shape
            bytes_per_line = ch * w
            qt_image = QImage(frame_rgb.data.tobytes(), w, h, bytes_per_line, QImage.Format_RGB888)

            video_metadata = {
                'fps': fps,
                'duration': duration,
                'frame_count': frame_count,
                'current_frame': 0,
                'sar_num': sar_num if sar_num > 0 else 1,
                'sar_den': sar_den if sar_den > 0 else 1
            }

            return (width, height), video_metadata, qt_image
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

    @staticmethod
    def _parse_viewer_loop_markers(raw_markers) -> dict[str, dict[str, int | None]]:
        """Normalize viewer-specific loop markers loaded from metadata."""
        markers: dict[str, dict[str, int | None]] = {}
        if not isinstance(raw_markers, dict):
            return markers

        for scope, values in raw_markers.items():
            if not isinstance(scope, str) or not isinstance(values, dict):
                continue
            loop_start = values.get('loop_start_frame')
            loop_end = values.get('loop_end_frame')
            start_value = loop_start if isinstance(loop_start, int) else None
            end_value = loop_end if isinstance(loop_end, int) else None
            if start_value is None and end_value is None:
                continue
            markers[scope] = {
                'loop_start_frame': start_value,
                'loop_end_frame': end_value,
            }
        return markers

    @staticmethod
    def _serialize_viewer_loop_markers(image: Image) -> dict[str, dict[str, int | None]]:
        """Prepare viewer-specific loop markers for JSON persistence."""
        raw_markers = getattr(image, 'viewer_loop_markers', None)
        if not isinstance(raw_markers, dict):
            return {}

        serialized: dict[str, dict[str, int | None]] = {}
        for scope, values in raw_markers.items():
            if not isinstance(scope, str) or not isinstance(values, dict):
                continue
            loop_start = values.get('loop_start_frame')
            loop_end = values.get('loop_end_frame')
            start_value = loop_start if isinstance(loop_start, int) else None
            end_value = loop_end if isinstance(loop_end, int) else None
            if start_value is None and end_value is None:
                continue
            serialized[scope] = {
                'loop_start_frame': start_value,
                'loop_end_frame': end_value,
            }
        return serialized

    def _apply_loop_metadata_from_meta(self, image: Image, meta: dict):
        """Apply loop-related metadata from parsed JSON meta dict."""
        loop_start = meta.get('loop_start_frame')
        image.loop_start_frame = loop_start if isinstance(loop_start, int) else None
        loop_end = meta.get('loop_end_frame')
        image.loop_end_frame = loop_end if isinstance(loop_end, int) else None
        image.viewer_loop_markers = self._parse_viewer_loop_markers(
            meta.get('viewer_loop_markers')
        )
        floating_last_start = meta.get('floating_last_loop_start_frame')
        floating_last_end = meta.get('floating_last_loop_end_frame')
        if isinstance(floating_last_start, int) and isinstance(floating_last_end, int):
            if not isinstance(image.viewer_loop_markers, dict):
                image.viewer_loop_markers = {}
            image.viewer_loop_markers.setdefault(
                'floating_last',
                {
                    'loop_start_frame': floating_last_start,
                    'loop_end_frame': floating_last_end,
                },
            )

    def get_index_for_path(self, path: Path) -> int:
        """Find the source row index for a given file path. Returns -1 if not found."""
        try:
             # Normal Mode: _image_files is a list of Image objects
             if not self._paginated_mode:
                 for i, img in enumerate(self._image_files):
                     if img.path == path:
                         return i
             else:
                 # Paginated Mode: Query DB for rank
                 if self._db is None: return -1
                 rel_candidates = []
                 dir_path = Path(self._directory_path)
                 for candidate_path in (path,):
                     try:
                         rel = str(candidate_path.relative_to(dir_path))
                         rel_candidates.append(rel)
                     except Exception:
                         pass
                 try:
                     rel = str(path.resolve().relative_to(dir_path.resolve()))
                     rel_candidates.append(rel)
                 except Exception:
                     pass
                 # Normalize separators and dedupe while preserving order.
                 normalized = []
                 seen = set()
                 for rel in rel_candidates:
                     for var in (rel, rel.replace('\\', '/'), rel.replace('/', '\\')):
                         if var not in seen:
                             seen.add(var)
                             normalized.append(var)
                 # Final fallback (least reliable): basename.
                 if not normalized:
                     normalized.append(path.name)

                 print(f"[RESTORE] Checking rank for rel_path candidates: {normalized[:3]}")
                     
                 sort_field = getattr(self, '_sort_field', 'file_name')
                 sort_dir = getattr(self, '_sort_dir', 'ASC')
                 random_seed = getattr(self, '_random_seed', 1234567)
                 filter_sql = getattr(self, '_filter_sql', '') or ''
                 filter_bindings = getattr(self, '_filter_bindings', ()) or ()
                 
                 rank = -1
                 for rel_path in normalized:
                     rank = self._db.get_rank_of_image(rel_path, sort_field, sort_dir,
                                                       filter_sql=filter_sql,
                                                       bindings=filter_bindings,
                                                       random_seed=random_seed)
                     if rank != -1:
                         break
                 print(f"[RESTORE] DB returned rank: {rank}")
                 
                 if rank == -1:
                     return -1
                     
                 # Map Global Rank to Local Row (and load page if needed)
                 page_size = getattr(self, 'PAGE_SIZE', 1000)
                 target_page_num = rank // page_size
                 offset = rank % page_size
                 
                 page_needed_loading = False
                 with self._page_load_lock:
                     if target_page_num not in self._pages:
                         print(f"[RESTORE] Loading target page {target_page_num} for restore")
                         self._load_page_sync(target_page_num)
                         page_needed_loading = True
                 
                 if page_needed_loading:
                     # Notify view to update rowCount
                     self._emit_pages_updated()
                 
                 # Calculate Local Row
                 # Iterate loaded pages in order to find where our target page sits.
                 # Important: loaded pages may be shorter than PAGE_SIZE because
                 # missing files are skipped when building Image objects.
                 with self._page_load_lock:
                     base_dir = Path(self._directory_path)

                     def _norm_rel(p: Path) -> str:
                         try:
                             rel = p.relative_to(base_dir)
                         except Exception:
                             rel = p
                         return str(rel).replace('\\', '/').casefold()

                     target_norm = _norm_rel(path)
                     target_name = path.name.casefold()
                     sorted_pages = sorted(self._pages.keys())
                     row_offset = 0
                     found_page = False
                     for p_num in sorted_pages:
                         if p_num == target_page_num:
                             found_page = True
                             break
                         # Add full length of preceding loaded pages
                         row_offset += len(self._pages[p_num])
                     
                     if found_page:
                         page_images = self._pages.get(target_page_num, [])

                         # Fast-path if offset still maps to the exact requested path.
                         if 0 <= offset < len(page_images):
                             try:
                                 candidate = page_images[offset]
                                 if candidate and (
                                     _norm_rel(candidate.path) == target_norm
                                     or candidate.path.name.casefold() == target_name
                                 ):
                                     local_row = row_offset + offset
                                     print(f"[RESTORE] Mapped Global Rank {rank} to Local Row {local_row}")
                                     return local_row
                             except Exception:
                                 pass

                         # Robust fallback: resolve by exact path inside the loaded page.
                         for i, img in enumerate(page_images):
                             try:
                                 if img and (
                                     _norm_rel(img.path) == target_norm
                                     or img.path.name.casefold() == target_name
                                 ):
                                     local_row = row_offset + i
                                     print(
                                         f"[RESTORE] Remapped path within page {target_page_num}: "
                                         f"rank {rank} -> Local Row {local_row}"
                                     )
                                     return local_row
                             except Exception:
                                 continue

                         # If the exact image isn't present in the loaded page
                         # (stale DB / file moved), fail safely instead of returning
                         # a potentially wrong row.
                         print(
                             f"[RESTORE] Target path not found in loaded page {target_page_num}; "
                             f"aborting row map for rank {rank}"
                         )
                         return -1
                 
                 return -1

        except Exception as e:
            print(f"[RESTORE] get_index_for_path error: {e}")
            pass
        return -1

    def get_image_at_row(self, row: int):
        """Get Image object at specific row, handling both normal and paginated modes."""
        try:
             # Normal Mode
             if not self._paginated_mode:
                 if 0 <= row < len(self._image_files):
                     return self._image_files[row]
                 return None
             
             # Paginated Mode
             if not hasattr(self, '_pages'):
                 return None

             # In buffered pagination, `row` is the position in the concatenated
             # loaded-pages list (sorted by page number), not a global rank.
             if row < 0:
                 return None

             with self._page_load_lock:
                 cumulative = 0
                 for page_num in sorted(self._pages.keys()):
                     page = self._pages.get(page_num) or []
                     page_size = len(page)
                     if row < cumulative + page_size:
                         idx_in_page = row - cumulative
                         if 0 <= idx_in_page < page_size:
                             return page[idx_in_page]
                         return None
                     cumulative += page_size
        except Exception:
            pass
        return None

    # Signals for pagination
    page_loaded = Signal(int)  # Emitted when a page finishes loading (page_num)
    total_count_changed = Signal(int)  # Emitted when total image count changes
    indexing_progress = Signal(int, int)  # (current, total) during initial indexing
    # DISABLED: Cache warming causes UI blocking
    # cache_warm_progress = Signal(int, int)  # (cached_count, total_count) for background cache warming
    enrichment_complete = Signal()  # Emitted when background enrichment finishes
    dimensions_updated = Signal()  # Emitted when aspect ratios change (no layout invalidation)
    # NEW: Signal for buffered mode page updates (avoids layoutChanged which crashes Qt)
    pages_updated = Signal(list)  # Emits list of currently loaded page numbers

    # Default threshold for enabling pagination mode (overridden by settings)
    PAGINATION_THRESHOLD = 0  # Will be loaded from settings
    PAGE_SIZE = 1000
    MAX_PAGES_IN_MEMORY = 20  # Increased from 5 to reduce evictions and crashes

    @staticmethod
    def _set_low_priority_thread():
        """Set low OS priority for worker threads to never interfere with UI."""
        import sys
        try:
            if sys.platform == 'win32':
                # Windows: Set thread priority to lowest
                import ctypes
                ctypes.windll.kernel32.SetThreadPriority(
                    ctypes.windll.kernel32.GetCurrentThread(),
                    -2  # THREAD_PRIORITY_LOWEST
                )
            else:
                # Unix/Linux: Set nice value to lowest priority
                import os
                os.nice(19)  # Lowest priority
        except Exception as e:
            # Silently ignore if setting priority fails
            pass

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
        self._page_load_lock = threading.RLock()
        self._db: ImageIndexDB = None
        self._directory_path: Path = None
        self._sort_field = 'mtime'
        self._sort_dir = 'DESC'
        self._filter_sql = ""       # Combined SQL passed to DB calls
        self._filter_bindings = ()  # Combined bindings
        self._text_filter_sql = ""  # Text filter portion only
        self._text_filter_bindings = ()
        self._media_type_sql = ""   # Media type portion only
        self._random_seed = 0
        self._pause_thumbnail_loading = False  # Pause during scrollbar drag for smooth dragging

        # Aspect ratio cache for masonry layout (avoids Qt model iteration on UI thread)
        self._aspect_ratio_cache: list[float] = []
        self._aspect_ratio_cache_lock = threading.Lock()  # Protect cache from race conditions

        # Separate ThreadPoolExecutors for loading vs saving (prioritize loads)
        # Load executor: 6 workers for fast thumbnail generation (UI blocking fixed with async queues + paint throttling)
        self._load_executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="thumb_load")
        # Save executor: single worker keeps disk pressure predictable during scroll.
        self._save_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="thumb_save",
            initializer=self._set_low_priority_thread
        )
        # Page loader executor for paginated mode
        self._page_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="page_load")
        
        # Debouncer for page requests during scrolling (avoids flooding executor)
        self._page_debouncer = QTimer(self)
        self._page_debouncer.setSingleShot(True)
        self._page_debouncer.setInterval(50)  # 50ms delay
        self._page_debouncer.timeout.connect(self._process_pending_page_requests)
        self._pending_page_range = None
        # DISABLED: Cache warming causes UI blocking
        # Cache warming executor: 2 workers for proactive cache building when idle (low priority)
        # Reduced to 1 worker to minimize resource usage during idle warming
        # self._cache_warm_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cache_warm")

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

        # DISABLED: Cache warming causes UI blocking
        # Track background cache warming (proactive cache building when idle)
        # self._cache_warm_cancelled = threading.Event()
        # self._cache_warm_futures = []  # List of futures for cache warming tasks
        # self._cache_warm_lock = threading.Lock()
        # self._cache_warm_progress = 0  # How many images have been cache-warmed
        # self._cache_warm_total = 0  # Total images to warm
        # self._cache_warm_running = False  # Is warming currently active?

        # Defer cache writes during scrolling to avoid I/O blocking
        self._is_scrolling = False  # Set by view during active scrolling
        self._pending_cache_saves = []  # Queue of (path, mtime, width, thumbnail) to save when idle
        self._pending_cache_saves_lock = threading.Lock()
        self._pending_db_cache_flags = []  # Batch DB updates for thumbnail_cached flag (file_name strings)
        self._pending_db_cache_flags_lock = threading.Lock()

        # Timer for deferred DB flush (only when truly idle)
        self._db_flush_timer = QTimer(self)
        self._db_flush_timer.setSingleShot(True)
        self._db_flush_timer.timeout.connect(self._flush_db_cache_flags)
        self._db_flush_timer.setInterval(5000)  # 5 seconds idle before DB flush
        self._shutdown_requested = False

        # Track background enrichment
        self._enrichment_cancelled = threading.Event()
        self._enrichment_paused = threading.Event()  # Pause enrichment during masonry recalc
        self._suppress_enrichment_signals = False  # Suppress dataChanged during filtering
        self._enrichment_completed_flag = False  # Flag to trigger masonry recalc after enrichment
        self._final_recalc_timer = None  # Timer for final masonry recalc (only one should be active)

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
        self._flow_log_last: dict[str, float] = {}
        self._dimensions_update_timer = QTimer(self)
        self._dimensions_update_timer.setSingleShot(True)
        self._dimensions_update_timer.setInterval(300)
        self._dimensions_update_timer.timeout.connect(self._emit_dimensions_updated_debounced)
        self._last_dimensions_emit_at = 0.0

    def _log_flow(self, component: str, message: str, *, level: str = "DEBUG",
                  throttle_key: str | None = None, every_s: float | None = None):
        """Timestamped, optionally throttled flow logging for pagination/masonry diagnostics."""
        # TRACE_RESTORE: temporary minimal diagnostics filter for strict drag debugging.
        # Set `minimal_trace_logs` to False in settings to restore full flow logs.
        try:
            minimal_trace = bool(settings.value("minimal_trace_logs", True, type=bool))
        except Exception:
            minimal_trace = True
        if minimal_trace:
            keep = False
            if component == "ASPECT_RATIOS" and message.startswith("Iterating loaded pages"):
                keep = True
            elif component == "PAGINATION" and message.startswith("Triggered loads"):
                keep = True
            if not keep:
                return

        now = time.time()
        if throttle_key and every_s is not None:
            last = self._flow_log_last.get(throttle_key, 0.0)
            if (now - last) < every_s:
                return
            self._flow_log_last[throttle_key] = now
        ts = time.strftime("%H:%M:%S", time.localtime(now)) + f".{int((now % 1) * 1000):03d}"
        print(f"[{ts}][TRACE][{component}][{level}] {message}")

    def _schedule_dimensions_updated(self):
        """Coalesce frequent dimension updates into one masonry refresh signal."""
        now = time.time()
        # In paginated mode, limit refresh pressure from continuous thumbnail/JIT updates.
        if self._paginated_mode and (now - self._last_dimensions_emit_at) < 1.0:
            return
        if self._dimensions_update_timer.isActive():
            return
        self._dimensions_update_timer.start()

    def _emit_dimensions_updated_debounced(self):
        self._last_dimensions_emit_at = time.time()
        self.dimensions_updated.emit()

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

    def get_buffered_aspect_ratios(self) -> tuple[list[tuple[int, float]], int, int]:
        """Get aspect ratios for ONLY loaded pages (buffered masonry).

        Returns:
            tuple of (items_data, first_index, last_index) where:
            - items_data: list of (global_index, aspect_ratio) for loaded pages only
            - first_index: global index of first loaded item
            - last_index: global index of last loaded item
        """
        if not self._paginated_mode:
            # Normal mode - return all
            return ([(i, ar) for i, ar in enumerate(self.get_aspect_ratios())], 0, len(self.images) - 1)
        
        if not self._pages:
            # Paginated mode but no pages loaded yet - return empty
            # DONT fallback to get_aspect_ratios() as it's expensive and breaks buffered logic
            return ([], 0, 0)

        # Get sorted page numbers (with lock to avoid race conditions)
        # CRITICAL: Hold lock while building data to prevent concurrent modifications
        with self._page_load_lock:
            if not self._pages:
                return ([], 0, 0)

            # Snapshot page numbers to avoid changes during iteration
            loaded_pages = sorted(self._pages.keys())
            if not loaded_pages:
                return ([], 0, 0)

            items_data = []
            first_index = loaded_pages[0] * self.PAGE_SIZE
            last_index = (loaded_pages[-1] + 1) * self.PAGE_SIZE - 1
            last_index = min(last_index, self._total_count - 1)

            # Build aspect ratio list from loaded pages
            # Create a deep snapshot to avoid concurrent modification
            if loaded_pages:
                summary = f"{loaded_pages[0]}-{loaded_pages[-1]} ({len(loaded_pages)} pages)"
            else:
                summary = "none"
            self._log_flow("ASPECT_RATIOS", f"Iterating loaded pages: {summary}",
                           throttle_key="aspect_iter", every_s=2.0)
            for page_num in loaded_pages:
                if page_num not in self._pages:
                    continue  # Page was evicted during iteration

                page = self._pages[page_num]
                page_start_idx = page_num * self.PAGE_SIZE

                # Snapshot the page to avoid modifications during iteration
                try:
                    for offset, image in enumerate(list(page)):
                        if image and hasattr(image, 'aspect_ratio'):
                            global_idx = page_start_idx + offset
                            ar = image.aspect_ratio
                            if ar < 1/3:
                                ar = 1/3  # Cap at 3:1 tall to match thumbnail crop
                            items_data.append((global_idx, ar))
                except Exception as e:
                    # Page was modified during iteration, skip it
                    print(f"[MASONRY] Page {page_num} modified during snapshot: {e}")
                    continue

        # DEBUG: Log index range
        if items_data:
            min_idx = min(item[0] for item in items_data)
            max_idx = max(item[0] for item in items_data)
            self._log_flow("ASPECT_RATIOS", f"Returning {len(items_data)} items, indices {min_idx}-{max_idx}",
                           throttle_key="aspect_return", every_s=2.0)

        return (items_data, first_index, last_index)

    def get_all_aspect_ratios(self) -> List[float]:
        """
        Get ALL aspect ratios from DB in current sort order.
        Used for Global Masonry Layout (stable alignment).
        """
        if self._db and self._paginated_mode:
            return self._db.get_ordered_aspect_ratios(
                sort_field=self._sort_field,
                sort_dir=self._sort_dir,
                filter_sql=self._filter_sql,
                bindings=self._filter_bindings,
                random_seed=self._random_seed
            )
        # Fallback for non-paginated mode (just use loaded images)
        return [img.aspect_ratio for img in self.images]

    def _rebuild_aspect_ratio_cache(self):
        """Rebuild aspect ratio cache when images change (thread-safe)."""
        # Both modes use self.images now
        try:
            import time
            start_time = time.time()
            images_snapshot = self.images[:]
            # Build cache with validation to prevent crashes from corrupted data
            new_cache = []
            corrupted_count = 0
            for img in images_snapshot:
                try:
                    ar = img.aspect_ratio
                    # Validate aspect ratio
                    if ar is None or ar != ar or ar <= 0:  # None or NaN or invalid
                        corrupted_count += 1
                        ar = 1.0
                    if ar > 100:
                        corrupted_count += 1
                        ar = 100
                    if ar < 1/3:
                        # Cap at 3:1 tall to match thumbnail crop limit
                        ar = 1/3
                    new_cache.append(ar)
                except Exception as e:
                    # Corrupted image object - use fallback
                    print(f"[CACHE] Corrupted aspect ratio for image, using 1.0: {e}")
                    corrupted_count += 1
                    new_cache.append(1.0)

            # Update cache atomically under lock
            with self._aspect_ratio_cache_lock:
                self._aspect_ratio_cache = new_cache

            elapsed = time.time() - start_time
            print(f"[CACHE] Rebuilt aspect ratio cache: {len(new_cache)} items in {elapsed:.2f}s ({corrupted_count} corrupted)")
        except Exception as e:
            print(f"[CACHE] Error rebuilding aspect ratio cache: {e}")
            import traceback
            traceback.print_exc()
            # Keep old cache if rebuild fails
            pass

    def get_masonry_data_for_range(self, start_idx: int, end_idx: int) -> list[tuple[int, float]]:
        """Get aspect ratios for a global index range in buffered mode.
        
        For loaded pages, returns actual aspect ratios. For unloaded pages, returns
        estimated aspect ratios (1.0) to enable virtual masonry calculation.
        
        Args:
            start_idx: Starting global index
            end_idx: Ending global index (inclusive)
            
        Returns:
            List of (global_index, aspect_ratio) tuples
        """
        if not self._paginated_mode:
            # Normal mode: just return from cache
            with self._aspect_ratio_cache_lock:
                return [(i, self._aspect_ratio_cache[i]) 
                        for i in range(start_idx, min(end_idx + 1, len(self._aspect_ratio_cache)))]
        
        items_data = []
        with self._page_load_lock:
            for idx in range(start_idx, min(end_idx + 1, self._total_count)):
                page_num = idx // self.PAGE_SIZE
                if page_num in self._pages:
                    page = self._pages[page_num]
                    offset = idx % self.PAGE_SIZE
                    if offset < len(page) and page[offset]:
                        items_data.append((idx, page[offset].aspect_ratio))
                    else:
                        items_data.append((idx, 1.0))  # Fallback for invalid offset
                else:
                    # Page not loaded - use estimated aspect ratio
                    items_data.append((idx, 1.0))
        
        return items_data


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
        
        # Determine strict loading during scrolling
        return None

    def get_loaded_row_for_global_index(self, global_index: int) -> int:
        """Get the row number (0..loaded_count-1) for a global index. Returns -1 if not loaded.
        
        This is crucial for mapping virtual masonry global indices to valid Qt model indices
        for painting.
        """
        if not self._paginated_mode:
            return global_index if global_index < len(self.images) else -1
        
        target_page = global_index // self.PAGE_SIZE
        target_offset = global_index % self.PAGE_SIZE
        
        with self._page_load_lock:
            if target_page not in self._pages:
                return -1
            
            # Calculate row by summing lengths of all loaded pages before target
            row_offset = 0
            # Note: We must iterate in the same order as data() and rowCount()
            for page_num in sorted(self._pages.keys()):
                if page_num == target_page:
                    page_images = self._pages.get(page_num, [])
                    if 0 <= target_offset < len(page_images):
                        return row_offset + target_offset
                    return -1
                row_offset += len(self._pages[page_num])
        
        return -1

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
        # print(f"[PAGE request] Requesting Page {page_num}")
        self._page_executor.submit(self._load_page_async, page_num)

    def _load_page_sync(self, page_num: int):
        """Load a page synchronously (for initial load)."""
        if not self._db:
            return

        images = self._load_images_from_db(page_num)
        self._store_page(page_num, images)

    def cancel_pending_loads_except(self, keep_pages: set[int]):
        """Cancel pending page loads that are not in the keep set."""
        with self._page_load_lock:
            # We can't stop running threads, but we can remove pages from the loading set.
            # The worker thread will check this set and abort if its page is missing.
            current_loading = list(self._loading_pages)
            for page_num in current_loading:
                if page_num not in keep_pages:
                    self._loading_pages.discard(page_num)
                    # print(f"[PAGE LOAD] Cancelled load for Page {page_num} (superseded)")

    def _load_page_async(self, page_num: int):
        """Load a page in background thread."""
        try:
            # Check for cancellation
            with self._page_load_lock:
                if page_num not in self._loading_pages:
                    # print(f"[ASYNC_LOAD] ABORT: Page {page_num} cancelled")
                    return

            # print(f"[ASYNC_LOAD] Starting load for Page {page_num} (Thread: {threading.current_thread().name})")
            if not self._db:
                # print(f"[ASYNC_LOAD] ABORT: No database connection for Page {page_num}")
                return

            images = self._load_images_from_db(page_num)
            # print(f"[ASYNC_LOAD] Loaded {len(images)} images from DB for Page {page_num}")
            self._store_page(page_num, images)
            # print(f"[ASYNC_LOAD] Stored Page {page_num}, now emitting signal...")

            # Emit signal (will be handled on main thread via signal/slot mechanism)
            self.page_loaded.emit(page_num)
            # print(f"[ASYNC_LOAD] Signal emitted for Page {page_num}")

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
            sort_dir=self._sort_dir,
            filter_sql=self._filter_sql,
            bindings=self._filter_bindings,
            random_seed=self._random_seed
        )

        images = []
        image_ids = [row['id'] for row in rows]
        tags_map = self._db.get_tags_for_images(image_ids)

        for row in rows:
            file_path = self._directory_path / row['file_name']
            img_id = row['id']
            
            # Get tags from DB map (much faster than file I/O)
            tags = tags_map.get(img_id, [])

            # Skip files that no longer exist on disk (deleted outside app
            # or between sessions).  Lightweight stat check avoids showing
            # gray placeholders for stale DB entries.
            if not file_path.exists():
                continue

            image = Image(
                path=file_path,
                dimensions=(row['width'], row['height']),
                tags=tags,
                is_video=bool(row['is_video']),
                rating=row.get('rating', 0.0)
            )

            # Populate metadata
            image.file_size = row.get('file_size')
            image.file_type = row.get('file_type')
            image.ctime = row.get('ctime')
            image.mtime = row.get('mtime')

            if row['is_video']:
                image.video_metadata = {
                    'fps': row.get('video_fps'),
                    'duration': row.get('video_duration'),
                    'frame_count': row.get('video_frame_count')
                }

            # In paginated mode we still need sidecar loop metadata for playback loop markers.
            json_file_path = file_path.with_suffix('.json')
            if json_file_path.exists() and json_file_path.stat().st_size > 0:
                with json_file_path.open(encoding='UTF-8') as source:
                    try:
                        meta = json.load(source)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        pass
                    else:
                        if meta.get('version') == 1:
                            self._apply_loop_metadata_from_meta(image, meta)

            images.append(image)

        return images

    def _rebuild_combined_filter(self):
        """Rebuild _filter_sql/_filter_bindings from text + media type parts."""
        parts = []
        bindings = ()
        if self._media_type_sql:
            parts.append(self._media_type_sql)
        if self._text_filter_sql:
            parts.append(f"({self._text_filter_sql})")
            bindings = self._text_filter_bindings
        self._filter_sql = " AND ".join(parts)
        self._filter_bindings = bindings

    def set_media_type_filter(self, media_type: str):
        """Set media type filter for paginated mode."""
        if media_type == 'Images':
            new_sql = "is_video = 0"
        elif media_type == 'Videos':
            new_sql = "is_video = 1"
        else:
            new_sql = ""

        if new_sql == self._media_type_sql:
            return
        self._media_type_sql = new_sql
        # Don't reload here — apply_filter will be called right after by the proxy

    def apply_filter(self, filter_struct: list | str | None):
        """Apply a filter to the paginated database view."""
        if not self._paginated_mode or not self._db:
            return

        try:
            text_sql, text_bindings = self._build_filter_sql(filter_struct)
        except Exception as e:
            print(f"Filter build error: {e}")
            text_sql, text_bindings = "", ()

        # Store text filter parts, then rebuild combined
        self._text_filter_sql = text_sql
        self._text_filter_bindings = text_bindings
        old_combined = (self._filter_sql, self._filter_bindings)
        self._rebuild_combined_filter()

        # Only reload if combined result changed
        if (self._filter_sql, self._filter_bindings) == old_combined:
            return

        # Update total count based on combined filter
        self._total_count = self._db.count(
            filter_sql=self._filter_sql, bindings=self._filter_bindings)

        # Clear cache and reset
        self._pages.clear()

        # Bootstrap load first pages
        print(f"[FILTER] Applied SQL filter (Count: {self._total_count})")
        for page_num in range(min(3, (self._total_count + self.PAGE_SIZE - 1) // self.PAGE_SIZE)):
            self._load_page_sync(page_num)

        # Emit reset AFTER pages are loaded so rowCount() returns valid data
        self.modelReset.emit()
        self.total_count_changed.emit(self._total_count)

    def _build_filter_sql(self, filter_node) -> tuple[str, tuple]:
        """Convert filter structure to SQL WHERE clause and bindings."""
        if filter_node is None:
            return "", ()
        
        if isinstance(filter_node, str):
            # Simple string search: tag OR filename
            pattern = f"%{filter_node}%"
            return (
                "(file_name LIKE ? OR EXISTS(SELECT 1 FROM image_tags WHERE image_id=images.id AND tag LIKE ?))",
                (pattern, pattern)
            )
            
        if isinstance(filter_node, list):
            if len(filter_node) == 0:
                return "", ()
                
            # Handle infix notation [A, 'AND', B] or prefix ['tag', 'val']
            # Determine type by inspection
            if len(filter_node) == 2:
                # Binary operator like ['tag', 'val']
                op = filter_node[0]
                val = filter_node[1]
                
                if op == 'tag':
                    if '*' in val or '?' in val:
                        val = val.replace('*', '%').replace('?', '_')
                        return "EXISTS(SELECT 1 FROM image_tags WHERE image_id=images.id AND tag LIKE ?)", (val,)
                    else:
                        return "EXISTS(SELECT 1 FROM image_tags WHERE image_id=images.id AND tag = ?)", (val,)
                
                if op == 'name':
                     # Contains match by default
                     return "file_name LIKE ?", (f"%{val}%",)
                
                # Default case for other prefixes? like 'path'
                
            # Handle Infix AND/OR/NOT if length >= 3 and middle is OP
            if len(filter_node) >= 3:
                # Check for [A, 'AND', B]
                op = filter_node[1]
                if op in ('AND', 'OR'):
                     s1, p1 = self._build_filter_sql(filter_node[0])
                     s2, p2 = self._build_filter_sql(filter_node[2:] if len(filter_node) > 3 else filter_node[2])
                     
                     clauses = []
                     if s1: clauses.append(f"({s1})")
                     if s2: clauses.append(f"({s2})")
                     return f" {op} ".join(clauses), p1 + p2
            
            # Fallback recursion for simple list?
            return "", ()

        return "", ()

    def _store_page(self, page_num: int, images: list[Image]):
        """Store a loaded page and evict old pages if needed."""
        with self._page_load_lock:
            self._pages[page_num] = images
            if page_num not in self._page_load_order:
                self._page_load_order.append(page_num)

            # Check if we need to evict pages (but don't do it here - background thread unsafe)
            if len(self._pages) > self.MAX_PAGES_IN_MEMORY:
                # Schedule eviction on model's thread (main/UI thread).
                # QTimer.singleShot from worker context can miss/dispatch inconsistently.
                QMetaObject.invokeMethod(
                    self,
                    "_evict_old_pages",
                    Qt.ConnectionType.QueuedConnection
                )

    @Slot()
    def _evict_old_pages(self):
        """Evict old pages (called on main thread via QTimer)."""
        evicted_any = False
        with self._page_load_lock:
            while len(self._pages) > self.MAX_PAGES_IN_MEMORY:
                oldest_page = self._page_load_order.pop(0)
                if oldest_page in self._pages:
                    # Cancel pending thumbnail loads for evicted page
                    self._cancel_page_thumbnails(oldest_page)
                    del self._pages[oldest_page]
                    # print(f"[PAGE] Evicted page {oldest_page}, {len(self._pages)} pages remain")
                    evicted_any = True

        # If pages were evicted, notify masonry that pages changed (avoid layoutChanged crash!)
        if evicted_any:
            self._emit_pages_updated()

    def _cancel_page_thumbnails(self, page_num: int):
        """Cancel pending thumbnail loading futures for an evicted page."""
        start_idx = page_num * self.PAGE_SIZE
        end_idx = start_idx + self.PAGE_SIZE

        with self._thumbnail_lock:
            cancelled_count = 0
            for idx in range(start_idx, end_idx):
                if idx in self._thumbnail_futures:
                    entry = self._thumbnail_futures[idx]
                    future = entry[0] if isinstance(entry, tuple) else entry
                    if not future.done():
                        future.cancel()
                        cancelled_count += 1
                    del self._thumbnail_futures[idx]

            if cancelled_count > 0:
                print(f"[PAGE] Cancelled {cancelled_count} pending thumbnails for evicted page {page_num}")

    def ensure_pages_for_range(self, start_idx: int, end_idx: int):
        """Ensure pages covering the given index range are loaded (throttled for smooth scrolling)."""
        if not self._paginated_mode:
            return

        # Update pending range and restart timer (debounce)
        self._pending_page_range = (start_idx, end_idx)
        self._page_debouncer.start()

    def _process_pending_page_requests(self):
        """Process the latest requested page range (called by debounce timer)."""
        if not self._pending_page_range or not self._paginated_mode:
            return

        start_idx, end_idx = self._pending_page_range
        start_page = self._get_page_for_index(start_idx)
        end_page = self._get_page_for_index(end_idx)
        
        # print(f"[PAGINATION] Processing range {start_idx}-{end_idx} (Pages {start_page}-{end_page})")

        # 1. Cleanup: Cancel pending loads that are far outside the current view
        # Keep current view +/- 2 pages
        keep_window = set(range(start_page - 2, end_page + 3))
        self.cancel_pending_loads_except(keep_window)

        # 2. Submit new requests
        requested_any = False
        for page_num in range(start_page, end_page + 1):
             should_load = False
             
             with self._page_load_lock:
                 if page_num not in self._pages:
                     if page_num not in self._loading_pages:
                         should_load = True
             
             if should_load:
                 self._request_page_load(page_num)
                 requested_any = True

        if requested_any:
            self._log_flow("PAGINATION", f"Triggered loads for page range {start_page}-{end_page}",
                           throttle_key="page_range", every_s=1.0)

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
        if not self._paginated_mode:
            return

        self._log_flow("PAGE", f"Loaded page {page_num}; in-memory pages={len(self._pages)}",
                       throttle_key="page_loaded", every_s=0.2)

        # Track if we're still in initial bootstrap (first 3 pages: 0, 1, 2)
        if not hasattr(self, '_bootstrap_complete'):
            self._bootstrap_complete = False

        # Mark bootstrap complete once we have pages 0, 1, 2 loaded
        if not self._bootstrap_complete and 0 in self._pages and 1 in self._pages and 2 in self._pages:
            self._bootstrap_complete = True
            self._log_flow("PAGE", "Initial bootstrap complete; switching to pages_updated flow", level="INFO")

        # CRITICAL: Only trigger masonry recalc during initial bootstrap
        # After that, pages load in background without triggering UI updates
        if not self._bootstrap_complete:
            # Bootstrap phase: trigger layout updates so user sees images appear
            # Use layoutChanged here (not pages_updated) because Qt needs to know about new items
            if not hasattr(self, '_page_load_debounce_timer'):
                from PySide6.QtCore import QTimer
                self._page_load_debounce_timer = QTimer()
                self._page_load_debounce_timer.setSingleShot(True)
                self._page_load_debounce_timer.timeout.connect(lambda: self.layoutChanged.emit())

            # Trigger layout change after 200ms of no new page loads
            self._page_load_debounce_timer.stop()
            self._page_load_debounce_timer.start(200)
        else:
            # After bootstrap: trigger masonry recalc for newly loaded pages
            # Use debounce to batch multiple page loads together
            if not hasattr(self, '_post_bootstrap_debounce_timer'):
                from PySide6.QtCore import QTimer
                self._post_bootstrap_debounce_timer = QTimer()
                self._post_bootstrap_debounce_timer.setSingleShot(True)
                self._post_bootstrap_debounce_timer.timeout.connect(self._emit_pages_updated)

            # Trigger layout change after 300ms of no new page loads
            # This batches rapid page loads during scrolling
            self._post_bootstrap_debounce_timer.stop()
            self._post_bootstrap_debounce_timer.start(300)

    def _emit_pages_updated(self):
        """Emit pages_updated signal with current loaded pages (safe alternative to layoutChanged)."""
        with self._page_load_lock:
            loaded_pages = list(self._pages.keys())
        self.pages_updated.emit(loaded_pages)
        self._log_flow("PAGE", f"Emitted pages_updated with {len(loaded_pages)} pages",
                       throttle_key="pages_updated", every_s=0.3)


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

            # Log processing (don't emit signals during enrichment to avoid crashes)
            if updated_indices and not self._suppress_enrichment_signals:
                batch_time = (time.time() - batch_start) * 1000
                # Disabled: Too spammy for large datasets (1M images)
                # if processed >= 50:  # Only log significant batches
                #     timestamp = time.strftime("%H:%M:%S")
                #     print(f"[ENRICH {timestamp}] Processed {processed} dimension updates in {batch_time:.1f}ms")

            # DISABLED: Incremental recalcs during enrichment cause crashes/freezes on large datasets
            # Only recalc once at the end when enrichment completes

            # Continue processing if queue has more items
            if not self._enrichment_queue.empty():
                # Schedule next batch immediately
                if self._enrichment_timer:
                    self._enrichment_timer.start(10)  # 10ms between batches
            else:
                # Queue empty - check if enrichment just completed
                if self._enrichment_completed_flag:
                    self._enrichment_completed_flag = False
                    timestamp = time.strftime("%H:%M:%S")
                    print(f"[ENRICH {timestamp}] Enrichment complete - scheduling final masonry recalc in 2 seconds")

                    # Cancel any existing final recalc timer to prevent overlapping recalcs
                    if self._final_recalc_timer is not None:
                        self._final_recalc_timer.stop()
                        self._final_recalc_timer.deleteLater()
                        print(f"[ENRICH {timestamp}] Cancelled previous final recalc timer")

                    # Wait 2 seconds to let everything settle before final recalc
                    def trigger_final_recalc():
                        timestamp = time.strftime("%H:%M:%S")

                        # Check if enrichment was cancelled/restarted while we were waiting
                        if self._enrichment_cancelled.is_set():
                            print(f"[ENRICH {timestamp}] Skipping final recalc - enrichment was restarted")
                            return

                        # Rebuild aspect ratio cache with final dimensions
                        self._rebuild_aspect_ratio_cache()

                        # Trigger final masonry recalc WITHOUT invalidating layout
                        # Using dimensions_updated instead of layoutChanged to avoid Qt crash
                        # (layoutChanged invalidates proxy indices mid-calculation with 32K items)
                        print(f"[ENRICH {timestamp}] Triggering final masonry recalc (dimensions only)")
                        self._schedule_dimensions_updated()

                        # Signal that enrichment is complete (for cache warming to start)
                        print(f"[ENRICH {timestamp}] Enrichment complete")
                        self.enrichment_complete.emit()

                        # Clear timer reference
                        self._final_recalc_timer = None

                    from PySide6.QtCore import QTimer
                    self._final_recalc_timer = QTimer()
                    self._final_recalc_timer.setSingleShot(True)
                    self._final_recalc_timer.timeout.connect(trigger_final_recalc)
                    self._final_recalc_timer.start(2000)  # 2 seconds delay

                # Check again in 100ms
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
            for entry in self._thumbnail_futures.values():
                f = entry[0] if isinstance(entry, tuple) else entry
                f.cancel()
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

    # DISABLED: Cache warming causes UI blocking
    # def start_cache_warming(self, start_idx: int, direction: str):
    #     """
    #     Start proactive cache warming in background (idle state only).
    #     Generates thumbnails ahead of scroll to build disk cache.
    #
    #     Args:
    #         start_idx: Index to start warming from
    #         direction: 'down' or 'up' - which direction to warm
    #     """
    #     # Only in pagination mode
    #     if not self._paginated_mode:
    #         return
    #
    #     # Don't restart if already running
    #     with self._cache_warm_lock:
    #         if self._cache_warm_running:
    #             return
    #         self._cache_warm_running = True
    #
    #     # Clear cancellation flag
    #     self._cache_warm_cancelled.clear()
    #
    #     # Cancel any existing cache warming tasks
    #     with self._cache_warm_lock:
    #         for future in self._cache_warm_futures:
    #             future.cancel()
    #         self._cache_warm_futures.clear()

    #         # Determine range to warm - ENTIRE folder with nearby prioritized first
    #         total_images = len(self.images)
    # 
    #         if direction == 'down':
    #             # Prioritize next 500, then rest after, then before start
    #             priority_end = min(start_idx + 500, total_images)
    #             indices_to_warm = list(range(start_idx, priority_end))
    #             # Then rest of folder after priority zone
    #             if priority_end < total_images:
    #                 indices_to_warm.extend(range(priority_end, total_images))
    #             # Finally images before start_idx
    #             if start_idx > 0:
    #                 indices_to_warm.extend(range(start_idx - 1, -1, -1))
    #         else:  # up
    #             # Prioritize previous 500, then rest before, then after start
    #             priority_start = max(start_idx - 500, 0)
    #             indices_to_warm = list(range(start_idx, priority_start, -1))
    #             # Then beginning of folder
    #             if priority_start > 0:
    #                 indices_to_warm.extend(range(priority_start - 1, -1, -1))
    #             # Finally images after start_idx
    #             if start_idx < total_images - 1:
    #                 indices_to_warm.extend(range(start_idx + 1, total_images))
    # 
    #         # Filter out already-cached images using DB (FAST - no disk scans!)
    #         uncached_indices = []
    # 
    #         for idx in indices_to_warm:
    #             if idx < 0 or idx >= len(self.images):
    #                 continue
    # 
    #             image = self.images[idx]
    # 
    #             # Skip if already loaded in memory
    #             if image.thumbnail or image.thumbnail_qimage:
    #                 continue
    # 
    #             # Query DB directly for current cached status (don't rely on stale _db_cached_info)
    #             if self._db and self._directory_path:
    #                 try:
    #                     relative_path = str(image.path.relative_to(self._directory_path))
    #                     cached_info = self._db.get_cached_info(relative_path, image.path.stat().st_mtime)
    #                     if cached_info and cached_info.get('thumbnail_cached', 0) == 1:
    #                         continue  # DB says it's cached, skip
    #                 except (ValueError, OSError):
    #                     pass  # Path error or file doesn't exist, assume uncached
    # 
    #             # Not cached, add to warm list
    #             uncached_indices.append(idx)
    # 
    #         if not uncached_indices:
    #             return
    # 
    #         # Store total for progress tracking
    #         self._cache_warm_total = len(uncached_indices)
    #         self._cache_warm_progress = 0
    # 
    #         # Emit initial progress to show label immediately
    #         self.cache_warm_progress.emit(0, len(uncached_indices))
    # 
    #         # Submit cache warming tasks (use separate executor with 1 worker for low resource usage)
    #         def cache_warm_worker(idx):
    #             """Worker that generates and caches a thumbnail (low priority, slow)."""
    #             # Add small delay to avoid resource spikes
    #             import time
    #             time.sleep(0.1)  # 100ms delay between each thumbnail
    # 
    #             # Check if cancelled
    #             if self._cache_warm_cancelled.is_set():
    #                 return False
    # 
    #             if idx >= len(self.images):
    #                 return False
    # 
    #             image = self.images[idx]
    #             success = False
    # 
    #             try:
    #                 # Load thumbnail (generates if needed)
    #                 qimage, was_cached = load_thumbnail_data(image.path, image.crop,
    #                                                          self.thumbnail_generation_width, image.is_video)
    # 
    #                 if qimage and not qimage.isNull():
    #                     # Store in memory
    #                     image.thumbnail_qimage = qimage
    #                     image._last_thumbnail_was_cached = was_cached
    #                     success = True
    # 
    #                     # If not from cache, save to disk cache
    #                     if not was_cached:
    #                         from PySide6.QtGui import QIcon, QPixmap
    #                         pixmap = QPixmap.fromImage(qimage)
    #                         icon = QIcon(pixmap)
    # 
    #                         # Save to disk cache
    #                         from utils.thumbnail_cache import get_thumbnail_cache
    #                         get_thumbnail_cache().save_thumbnail(image.path, image.path.stat().st_mtime,
    #                                                             self.thumbnail_generation_width, icon)
    # 
    #                     # Mark in DB as cached (whether it was already cached or just generated)
    #                     # Debug: log first check
    #                     if not hasattr(self, '_db_check_logged'):
    #                         print(f'[DB CHECK] _db={self._db is not None}, _directory_path={self._directory_path is not None}')
    #                         if self._db:
    #                             print(f'[DB CHECK] DB enabled={self._db.enabled}')
    #                         self._db_check_logged = True
    # 
    #                     if self._db and self._directory_path:
    #                         try:
    #                             relative_path = str(image.path.relative_to(self._directory_path))
    #                             # Debug: log first 3 DB updates
    #                             if not hasattr(self, '_db_update_log_count'):
    #                                 self._db_update_log_count = 0
    #                             if self._db_update_log_count < 3:
    #                                 print(f'[DB UPDATE] Marking cached: {relative_path}')
    #                                 self._db_update_log_count += 1
    #                             self._db.mark_thumbnail_cached(relative_path, cached=True)
    # 
    #                             # Update in-memory flag so next warming cycle knows it's cached
    #                             if not hasattr(image, '_db_cached_info') or image._db_cached_info is None:
    #                                 image._db_cached_info = {}
    #                             image._db_cached_info['thumbnail_cached'] = 1
    #                         except ValueError as e:
    #                             print(f'[DB UPDATE ERROR] ValueError: {e} for path {image.path}')
    #                             pass
    # 
    #                 # Check if cancelled after generation
    #                 if self._cache_warm_cancelled.is_set():
    #                     return False
    # 
    #             except Exception as e:
    #                 print(f"[CACHE WARM] Error warming cache for {image.path.name}: {e}")
    # 
    #             # ALWAYS increment progress and emit (even on failure, so progress bar advances)
    #             self._cache_warm_progress += 1
    #             if self._cache_warm_progress % 5 == 0 or self._cache_warm_progress >= self._cache_warm_total:
    #                 # Emit every 5 items or on completion (reduce signal spam)
    #                 self.cache_warm_progress.emit(self._cache_warm_progress, self._cache_warm_total)
    # 
    #             return success
    # 
    #         # Submit warming tasks slowly to minimize resource usage
    #         # Only warm 50 images at a time, with delays between batches
    #         max_batch_size = 50
    #         uncached_batch = uncached_indices[:max_batch_size]
    # 
    #         with self._cache_warm_lock:
    #             for idx in uncached_batch:
    #                 future = self._cache_warm_executor.submit(cache_warm_worker, idx)
    #                 self._cache_warm_futures.append(future)
    # 
    #         print(f"[CACHE WARM] Starting batch of {len(uncached_batch)} thumbnails (low priority)")
    # 
    #         # Add callback to mark warming complete when all futures finish
    #         def on_warming_complete():
    #             progress = self._cache_warm_progress
    #             total = self._cache_warm_total
    #             with self._cache_warm_lock:
    #                 self._cache_warm_running = False
    #             print(f"[CACHE WARM] Completed - {progress}/{total} cached")
    #             # Emit 0, 0 to signal completion and show real cache status
    #             self.cache_warm_progress.emit(0, 0)
    # 
    #         # Wait for all futures in background thread
    #         def wait_for_completion():
    #             for future in self._cache_warm_futures:
    #                 try:
    #                     future.result()  # Wait for completion
    #                 except Exception:
    #                     pass
    #             on_warming_complete()
    # 
    #         # Submit waiter to separate thread
    #         import threading
    #         threading.Thread(target=wait_for_completion, daemon=True).start()

    # DISABLED: Cache warming causes UI blocking
    # def stop_cache_warming(self):
    #     """Stop background cache warming immediately (called when user interacts)."""
    #     # Set cancellation flag
    #     self._cache_warm_cancelled.set()
    #
    #     # Cancel all pending futures
    #     with self._cache_warm_lock:
    #         for future in self._cache_warm_futures:
    #             future.cancel()
    #         self._cache_warm_futures.clear()
    #         self._cache_warm_running = False  # Allow restart
    #
    #     # Reset progress
    #     self._cache_warm_progress = 0
    #     self._cache_warm_total = 0
    #
    #     # Emit signal to hide label
    #     self.cache_warm_progress.emit(0, 0)

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
            # Start deferred DB flush timer (only flushes if still idle after 5 seconds)
            self._db_flush_timer.start()
        else:
            # Cancel DB flush if user starts scrolling again
            self._db_flush_timer.stop()

    def set_visible_indices(self, visible_indices: set):
        """
        Update which indices are currently visible in viewport.
        Used to prioritize enrichment for visible images.
        """
        self._visible_indices_hint = visible_indices

    def _flush_pending_cache_saves(self, force=False):
        """Submit pending cache saves to background executor (fully async, zero main thread work)."""
        if self._shutdown_requested or not self._save_executor:
            return
        # Don't flush if actively scrolling (unless forced on app close)
        if not force and self._is_scrolling:
            return  # Wait until truly idle

        # Do EVERYTHING including list access in background thread to avoid ANY main thread blocking
        def background_flush():
            # Access the list in background thread to avoid main thread lock contention
            with self._pending_cache_saves_lock:
                if not self._pending_cache_saves:
                    return

                count = len(self._pending_cache_saves)

                # Only flush if we have a substantial batch (50+ items) to make it worthwhile
                # Or force flush (e.g., on app close, or queue too large 300+)
                if not force and count < 50:
                    return  # Accumulate more before flushing

                # Swap with a new empty list
                saves_to_submit = self._pending_cache_saves
                self._pending_cache_saves = []

            # Print and submit all saves
            print(f"[CACHE] Flushing {len(saves_to_submit)} pending cache saves")

            for path, mtime, width, qimage in saves_to_submit:
                self._save_executor.submit(
                    self._save_thumbnail_worker,
                    path, mtime, width, qimage
                )

        # Run the ENTIRE flush (including lock acquisition) in executor
        self._save_executor.submit(background_flush)

    def _load_thumbnail_worker(self, idx: int, path: Path, crop: QRect, width: int, is_video: bool):
        """Worker function that runs in background thread to load thumbnail data (QImage)."""
        if self._shutdown_requested:
            return
        try:
            # Load QImage in background thread (thread-safe, I/O bound)
            qimage, was_cached, _ = load_thumbnail_data(path, crop, width, is_video)

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

    def _save_thumbnail_worker(self, path: Path, mtime: float, width: int, qimage):
        """Worker function that saves thumbnail QImage to disk cache.

        Accepts a QImage (thread-safe) instead of QIcon/QPixmap to avoid
        GIL contention that stalls the main thread.
        """
        if self._shutdown_requested:
            return
        import time

        # Small delay to prevent disk I/O saturation
        time.sleep(0.05)  # 50ms delay between saves

        try:
            from utils.thumbnail_cache import get_thumbnail_cache
            with _thumbnail_save_lock:
                get_thumbnail_cache().save_thumbnail_qimage(path, mtime, width, qimage)

            # Queue DB update for deferred batch write (when truly idle)
            if self._db and self._directory_path:
                try:
                    relative_path = str(path.relative_to(self._directory_path))
                    with self._pending_db_cache_flags_lock:
                        self._pending_db_cache_flags.append(relative_path)
                        # REMOVED: Immediate flush every 100 items (caused blocking)
                        # DB updates now deferred to idle time (5+ seconds after scrolling stops)
                except ValueError:
                    # Path not relative to directory, skip
                    pass

            with self._cache_saves_lock:
                self._cache_saves_count += 1

                # DISABLED: Cache warming causes UI blocking
                # Emit cache status update every 10 saves (not too spammy)
                # if self._cache_saves_count % 10 == 0:
                #     self.cache_warm_progress.emit(0, 0)  # Signal to refresh cache status
        except Exception as e:
            print(f"[CACHE] ERROR saving in background: {e}")
            import traceback
            traceback.print_exc()

    def _flush_db_cache_flags(self):
        """Batch update DB thumbnail_cached flags (async, non-blocking).

        Writes in small chunks (50 rows) with short yields between commits
        so the _db_lock is never held long enough to block page loads.
        """
        if self._shutdown_requested or not self._save_executor:
            return

        with self._pending_db_cache_flags_lock:
            if not self._pending_db_cache_flags:
                return

            batch = list(self._pending_db_cache_flags)
            self._pending_db_cache_flags.clear()

        # Submit DB flush to background thread (never blocks main thread)
        def db_flush_worker():
            """Worker function that performs DB commit in small chunks."""
            import time
            if not self._db:
                return
            CHUNK = 50
            total = len(batch)
            flushed = 0
            try:
                for i in range(0, total, CHUNK):
                    chunk = batch[i:i + CHUNK]
                    with self._db._db_lock:
                        cursor = self._db.conn.cursor()
                        cursor.executemany(
                            'UPDATE images SET thumbnail_cached = 1 WHERE file_name = ?',
                            [(fn,) for fn in chunk]
                        )
                        self._db.conn.commit()
                    flushed += len(chunk)
                    # Yield between chunks so page loads can acquire the lock
                    if i + CHUNK < total:
                        time.sleep(0.02)  # 20ms
                if flushed:
                    print(f"[DB] Flushed {flushed} thumbnail_cached flags in background")
            except Exception as e:
                print(f"[DB] ERROR batch updating thumbnail_cached flags: {e}")

        # Submit to save executor (dedicated thread pool for I/O operations)
        self._save_executor.submit(db_flush_worker)

    def shutdown_background_workers(self):
        """Cancel pending background work so app shutdown does not stall."""
        if self._shutdown_requested:
            return
        self._shutdown_requested = True

        # Stop timers that can enqueue additional work while shutting down.
        for timer_name in (
            '_page_debouncer',
            '_thumbnail_batch_timer',
            '_db_flush_timer',
            '_dimensions_update_timer',
            '_page_load_debounce_timer',
            '_post_bootstrap_debounce_timer',
            '_final_recalc_timer',
            '_cache_report_timer',
            '_enrichment_timer',
            '_qimage_timer',
        ):
            timer = getattr(self, timer_name, None)
            if timer is not None and hasattr(timer, 'stop'):
                try:
                    timer.stop()
                except Exception:
                    pass

        # Drop pending queues; these are cache/perf hints, safe to rebuild later.
        with self._pending_cache_saves_lock:
            self._pending_cache_saves.clear()
        with self._pending_db_cache_flags_lock:
            self._pending_db_cache_flags.clear()

        # Cancel queued jobs in all executors to prevent minute-long shutdown hangs.
        for executor_name in ('_page_executor', '_load_executor', '_save_executor'):
            executor = getattr(self, executor_name, None)
            if executor is None:
                continue
            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                # Python fallback if cancel_futures isn't supported
                executor.shutdown(wait=False)
            except Exception as e:
                print(f"[SHUTDOWN] Executor shutdown warning ({executor_name}): {e}")
            setattr(self, executor_name, None)

    @Slot(int, int, int)
    def _notify_thumbnail_ready(self, idx: int, width: int = -1, height: int = -1):
        """Called on main thread when thumbnail QImage is ready (batched to reduce repaints).
        
        Args:
            idx: Global index of image (OR Local Row in Buffered Mode)
            width, height: Original dimensions found during load (optional, -1 if unknown)
        """
        # JUST-IN-TIME ENRICHMENT:
        # If we found dimensions during loading and the model doesn't have them (or has None),
        # update them now to fix masonry layout instantly!
        
        # Use safe accessor for both Normal and Buffered modes
        image = self.get_image_at_row(idx)
        
        if image and width > 0 and height > 0:
            # Update dimensions if missing
            if not image.dimensions or image.dimensions[0] is None or image.dimensions[1] is None:
                # print(f"[JIT] Updating dimensions for {image.path.name}: {width}x{height}")
                image.dimensions = (width, height)
                
                # Update DB in background 
                if self._db and self._save_executor:
                    self._save_executor.submit(lambda: self._db.update_image_dimensions(str(image.path), width, height))

                # Trigger debounced dimension update signal so masonry refreshes smoothly.
                self._schedule_dimensions_updated()

        # Queue repaint (dataChanged)
        # In buffered mode, idx is local row, so standard len check fails
        valid_idx = False
        if self._paginated_mode:
            if idx >= 0: valid_idx = True
        elif idx < len(self.images):
            valid_idx = True

        if valid_idx:
            self._pending_thumbnail_updates.add(idx)
            # Restart timer to batch updates (coalesces rapid thumbnail loads)
            self._thumbnail_batch_timer.start()

    def _load_thumbnail_async(self, path: Path, crop, is_video: bool, row: int):
        """Load thumbnail in background thread, then notify UI."""
        try:
            qimage, was_cached, original_size = load_thumbnail_data(
                path, crop, self.thumbnail_generation_width, is_video
            )
            
            width = -1
            height = -1
            if original_size:
                 width, height = original_size
                 
            # Notify main thread that thumbnail is ready
            QMetaObject.invokeMethod(
                self,
                "_notify_thumbnail_ready",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(int, row),
                Q_ARG(int, width),
                Q_ARG(int, height)
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
            # Ensure valid size even if image_list_image_width is uninitialized or 0
            size = getattr(self, 'image_list_image_width', 200)
            if size <= 0: 
                size = 200
                
            pixmap = QPixmap(size, size)
            pixmap.fill(QColor(40, 40, 40))  # Dark grey for placeholder (better for dark theme)
            
            # Draw a simple border or content to make it visible
            from PySide6.QtGui import QPainter
            painter = QPainter(pixmap)
            painter.setPen(QColor(60, 60, 60))
            painter.drawRect(0, 0, size-1, size-1)
            painter.end()
            
            self._placeholder_icon = QIcon(pixmap)
        return self._placeholder_icon



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
        # Buffered pagination mode: return only loaded items (not total)
        # This prevents Qt from iterating 1M unloaded items
        if self._paginated_mode:
            # Return count of loaded items only
            with self._page_load_lock:
                loaded_count = sum(len(page) for page in self._pages.values())
            return loaded_count
        return len(self.images)

    def get_global_index_for_row(self, row: int) -> int:
        """Get the absolute global index for a visible row. Returns -1 if not found."""
        if not self._paginated_mode:
            return row if row < len(self.images) else -1
            
        with self._page_load_lock:
            cumulative = 0
            for page_num in sorted(self._pages.keys()):
                page_size = len(self._pages[page_num])
                if row < cumulative + page_size:
                    return (page_num * self.PAGE_SIZE) + (row - cumulative)
                cumulative += page_size
        return -1

    def data(self, index: QModelIndex, role=None) -> Image | str | QIcon | QSize:
        # Validate index bounds to prevent errors during model reset
        try:
            row = index.row()
            if not index.isValid():
                return None

            # Get image - different logic for paginated vs normal mode
            if self._paginated_mode:
                # Buffered pagination: row is index into loaded items only
                # Need to map row to actual page/offset
                try:
                    with self._page_load_lock:
                        sorted_pages = sorted(self._pages.keys())
                        cumulative = 0
                        for page_num in sorted_pages:
                            if page_num not in self._pages:
                                continue  # Page was evicted during iteration
                            page = self._pages[page_num]
                            page_size = len(page)
                            if row < cumulative + page_size:
                                # Row is in this page
                                page_offset = row - cumulative
                                if page_offset < len(page):
                                    self._touch_page(page_num)
                                    image = page[page_offset]
                                    break
                                else:
                                    return None
                            cumulative += page_size
                        else:
                            # Row not found in loaded pages
                            return None
                except Exception as e:
                    # Race condition during page load/eviction
                    return None
            else:
                # Normal mode: use self.images list
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
            # DEBUG: Trace why thumbnails are missing
            # if row == 0 or row == 1:
            #     print(f"[DATA DEBUG] DecorationRole for row {row}, image={image}, thumbnail={image.thumbnail}, qimage={image.thumbnail_qimage}")

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
                    # Pass QImage (thread-safe) instead of QIcon (needs QPixmap = GIL contention)
                    save_qimage = image.thumbnail_qimage
                    if save_qimage and not save_qimage.isNull():
                        if self._is_scrolling:
                            with self._pending_cache_saves_lock:
                                self._pending_cache_saves.append((image.path, image.path.stat().st_mtime,
                                                                  self.thumbnail_generation_width, save_qimage))
                        else:
                            self._save_executor.submit(
                                self._save_thumbnail_worker,
                                image.path,
                                image.path.stat().st_mtime,
                                self.thumbnail_generation_width,
                                save_qimage
                            )

                return thumbnail

            # Async loading for:
            # 1. Pagination mode (always async)
            # 2. Videos in ANY mode (cv2.VideoCapture can block for seconds)
            # In normal mode for images: preloading needs synchronous loads to work
            if not self._paginated_mode and not image.is_video:
                # Normal mode for images: Load synchronously (enables preloading to work)
                try:
                    qimage, was_cached, _ = load_thumbnail_data(
                        image.path, image.crop, self.thumbnail_generation_width, image.is_video
                    )

                    if qimage and not qimage.isNull():
                        pixmap = QPixmap.fromImage(qimage)
                        thumbnail = QIcon(pixmap)
                        image.thumbnail = thumbnail
                        image._last_thumbnail_was_cached = was_cached

                        # Save to disk cache in background thread if not from cache
                        if not was_cached:
                            mtime = image.path.stat().st_mtime
                            # Defer during scroll to avoid I/O blocking
                            if self._is_scrolling:
                                with self._pending_cache_saves_lock:
                                    self._pending_cache_saves.append((image.path, mtime,
                                                                      self.thumbnail_generation_width, qimage))
                            else:
                                self._save_executor.submit(
                                    self._save_thumbnail_worker,
                                    image.path,
                                    mtime,
                                    self.thumbnail_generation_width,
                                    qimage
                                )

                        return thumbnail
                except Exception as e:
                    print(f"[THUMBNAIL ERROR] Failed to load thumbnail for {image.path.name}: {e}")
                    import traceback
                    traceback.print_exc()

                # print(f"[DATA DEBUG] Returning None for row {row}")
                return None

            # Pagination mode: Async loading with placeholders for smooth scrolling
            # _thumbnail_futures stores (future, submitted_path) tuples so we can
            # verify the row still maps to the same image after page eviction.
            with self._thumbnail_lock:
                # Check if already loading
                if row in self._thumbnail_futures:
                    entry = self._thumbnail_futures[row]
                    future, submitted_path = (entry if isinstance(entry, tuple)
                                              else (entry, None))
                    if not future.done():
                        # Still loading - return placeholder
                        return self._get_placeholder_icon()
                    # Future done - check result
                    try:
                        # Path check: if pages were evicted/reloaded, this row
                        # may now map to a different image.  Discard stale result.
                        if submitted_path is not None and image.path != submitted_path:
                            del self._thumbnail_futures[row]
                            # Fall through to re-submit below
                        else:
                            qimage, was_cached = future.result()
                            thumbnail = None
                            if qimage and not qimage.isNull():
                                pixmap = QPixmap.fromImage(qimage)
                                thumbnail = QIcon(pixmap)
                                image.thumbnail = thumbnail
                                image._last_thumbnail_was_cached = was_cached

                                # Save to cache if needed
                                if not was_cached:
                                    mtime = image.path.stat().st_mtime
                                    # Defer during scroll to avoid I/O blocking
                                    if self._is_scrolling:
                                        with self._pending_cache_saves_lock:
                                            self._pending_cache_saves.append((image.path, mtime,
                                                                              self.thumbnail_generation_width, qimage))
                                    else:
                                        self._save_executor.submit(
                                            self._save_thumbnail_worker,
                                            image.path,
                                            mtime,
                                            self.thumbnail_generation_width,
                                            qimage
                                        )

                            del self._thumbnail_futures[row]
                            return thumbnail
                    except Exception as e:
                        print(f"[THUMBNAIL ERROR] Failed to load thumbnail for {image.path.name}: {e}")
                        del self._thumbnail_futures[row]
                        return None

                # Not loading yet (or stale entry was discarded) - submit to background thread
                if row not in self._thumbnail_futures:
                    future = self._load_executor.submit(
                        self._load_thumbnail_async,
                        image.path,
                        image.crop,
                        image.is_video,
                        row
                    )
                    self._thumbnail_futures[row] = (future, image.path)

                # Return placeholder immediately (smooth scrolling)
                # print(f"[DATA DEBUG] Returning PLACEHOLDER for row {row}")
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

    def _start_paginated_enrichment(self, *, window_pages=None, scope='window'):
        """Start background enrichment for paginated mode (using DB placeholders).

        Args:
            window_pages: Optional range/iterable of page numbers to enrich.
                          If provided, ONLY images from these pages are enriched.
                          If None, falls back to all loaded pages (legacy behavior).
            scope: 'window' for visible-area enrichment (triggers masonry refresh
                   on completion), 'preload' for ahead-of-scroll enrichment
                   (no masonry refresh, no retrigger).
        """
        # Cancel any running enrichment so it doesn't waste time on stale pages
        if hasattr(self, '_enrichment_cancelled'):
            self._enrichment_cancelled.set()
            # Non-blocking: worker checks cancel flag every 10 files (~20ms),
            # so it will notice quickly without blocking the UI thread here.
            self._enrichment_cancelled = threading.Event()

        # Snapshot the window pages for the worker closure
        _window_page_set = set(window_pages) if window_pages is not None else None

        self._enrichment_running = True
        self._enrichment_scope = scope
        self._enrichment_target_pages = frozenset(_window_page_set) if _window_page_set else None

        def enrich_worker():
             from utils.image_index_db import ImageIndexDB
             from utils.image import Image
             import time
             from pathlib import Path
             import imagesize

             if not self._directory_path:
                 self._enrichment_running = False
                 return

             db_bg = ImageIndexDB(self._directory_path)

             # Collect unenriched images — scoped to window pages if provided.
             prioritized_rel_paths = []
             seen = set()
             if _window_page_set is not None:
                 # Window-scoped: use DB to find unenriched files (avoids stale in-memory data).
                 # Query DB for placeholder files in the page range, ordered center-out.
                 pages_sorted = sorted(_window_page_set)
                 center = pages_sorted[len(pages_sorted) // 2]
                 page_size = self.PAGE_SIZE if hasattr(self, 'PAGE_SIZE') else 1000
                 _sort_field = getattr(self, '_sort_field', 'file_name')
                 _sort_dir = getattr(self, '_sort_dir', 'ASC')
                 _filter_sql = getattr(self, '_filter_sql', '')
                 _filter_bindings = getattr(self, '_filter_bindings', ())
                 _random_seed = getattr(self, '_random_seed', 1234567)
                 for page_num in sorted(pages_sorted, key=lambda p: abs(p - center)):
                     start_rank = page_num * page_size
                     end_rank = start_rank + page_size
                     page_placeholders = db_bg.get_placeholder_files_in_range(
                         start_rank, end_rank,
                         sort_field=_sort_field,
                         sort_dir=_sort_dir,
                         filter_sql=_filter_sql,
                         bindings=_filter_bindings,
                         random_seed=_random_seed,
                     )
                     for rel_path in page_placeholders:
                         if rel_path not in seen:
                             prioritized_rel_paths.append(rel_path)
                             seen.add(rel_path)
                 # DB query is the source of truth for what needs enrichment.
                 # No in-memory fallback — stale in-memory objects report dims=None
                 # even after DB has real values, causing infinite re-enrichment.
                 placeholders = prioritized_rel_paths[:]
             else:
                 # Legacy: scan in-memory pages + DB candidates
                 with self._page_load_lock:
                     pages_to_scan = list(reversed(self._page_load_order)) if self._page_load_order else sorted(self._pages.keys())
                     for page_num in pages_to_scan:
                         page = self._pages.get(page_num, [])
                         for image in page:
                             if not image:
                                 continue
                             try:
                                 rel_path = str(image.path.relative_to(self._directory_path))
                             except Exception:
                                 rel_path = image.path.name
                             dims = image.dimensions
                             if (not dims or dims[0] is None or dims[1] is None or dims == (512, 512)) and rel_path not in seen:
                                 prioritized_rel_paths.append(rel_path)
                                 seen.add(rel_path)
                 db_candidates = db_bg.get_placeholder_files(limit=5000)
                 placeholders = prioritized_rel_paths[:]
                 for rel_path in db_candidates:
                     if rel_path not in seen:
                         placeholders.append(rel_path)
                         seen.add(rel_path)

             # Keep small for fast first-cycle masonry fix (~3-4s).
             max_enrich_per_cycle = 1500
             placeholders = placeholders[:max_enrich_per_cycle]

             if not placeholders:
                 self._enrichment_exhausted = True
                 self._enrichment_actual_count = 0
                 self._enrichment_running = False
                 # 0 files to enrich = area already enriched in DB.
                 # Don't emit — no data changed, so masonry refresh would be
                 # pointless and can break restore scroll position at startup.
                 return

             scope = f"pages {sorted(_window_page_set)[:3]}..." if _window_page_set else "all loaded"
             print(f"[ENRICH] {len(placeholders)} to enrich ({scope})")
             
             enriched_count = 0
             commit_interval = 100
             video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.webm'}
             
             for i, rel_path in enumerate(placeholders):
                 if hasattr(self, '_enrichment_cancelled') and self._enrichment_cancelled.is_set():
                     db_bg.commit()
                     self._enrichment_running = False
                     print("[ENRICH] Cancelled")
                     return

                 # Yield disk time every 10 files to avoid blocking thumbnail I/O
                 if i > 0 and i % 10 == 0:
                     time.sleep(0.002)

                 full_path = self._directory_path / rel_path
                 
                 try:
                      is_video = Path(rel_path).suffix.lower() in video_extensions
                      dimensions = None
                      video_metadata = None
                      tags = []
                      
                      # Extract tags
                      txt_path = full_path.with_suffix('.txt')
                      if txt_path.exists():
                          try:
                              caption = txt_path.read_text(encoding='utf-8', errors='replace')
                              if caption:
                                  tags = [t.strip() for t in caption.split(self.tag_separator) if t.strip()]
                          except Exception:
                              pass
                      
                      # Extract dimensions
                      if is_video:
                         dimensions, video_metadata, _ = extract_video_info(full_path)
                      elif full_path.suffix.lower() == '.jxl':
                         from utils.jxlutil import get_jxl_size
                         dimensions = get_jxl_size(full_path)
                      else:
                          # Try fast imagesize first
                          dimensions = imagesize.get(str(full_path))
                          
                          # HEURISTIC CHECK:
                          # If dimensions seem "Impossible" or "Suspicious" (Super Tall/Fat),
                          # Double check with PIL. This catches corrupted headers where imagesize reads garbage.
                          is_suspicious = False
                          
                          if dimensions == (-1, -1):
                              is_suspicious = True
                          elif dimensions[0] > 0 and dimensions[1] > 0:
                              aspect_ratio = dimensions[0] / dimensions[1]
                              # Thresholds: Taller than 1:5 (0.2) or Wider than 5:1 (5.0)
                              # Normal panoramas might trigger this, but verifying them via PIL is safe/fast enough.
                              if aspect_ratio < 0.2 or aspect_ratio > 5.0:
                                  is_suspicious = True
                              # New check: Max Dimension (> 12,000px)
                              # Many corrupted files report huge dims (e.g. 60,000px)
                              elif dimensions[0] > 12000 or dimensions[1] > 12000:
                                  is_suspicious = True

                          # For Suspicious items OR JPEGs (that risk EXIF rotation issues), verify with PIL
                          # (We verify suspicious PNGs/WebP too)
                          if is_suspicious and full_path.suffix.lower() in ('.jpg', '.jpeg', '.webp', '.tiff', '.png'):
                               try:
                                   with pilimage.open(full_path) as img:
                                       # Trust PIL dimensions over imagesize (fixes corruption cases)
                                       dimensions = img.size

                                       # Orientation is relevant only for EXIF-backed formats.
                                       # Avoid getexif() for PNG/WebP to reduce decoder crash surface.
                                       if full_path.suffix.lower() in ('.jpg', '.jpeg', '.tif', '.tiff'):
                                           exif = img.getexif()
                                           if exif:
                                               orientation = exif.get(274)
                                               if orientation in (5, 6, 7, 8):
                                                   dimensions = (dimensions[1], dimensions[0])
                               except:
                                   # If PIL fails, fall back to whatever imagesize got (or try custom parser)
                                   if dimensions == (-1, -1) and full_path.suffix.lower() in ('.jpg', '.jpeg'):
                                        dimensions = self._read_jpeg_header_dimensions(full_path) or (-1, -1)
                       
                      if dimensions and dimensions != (-1, -1):
                           mtime = full_path.stat().st_mtime
                           # Save dimensions
                           db_bg.save_info(rel_path, dimensions[0], dimensions[1], int(is_video), mtime, video_metadata)
                           
                           # Save tags (requires image_id from newly inserted/updated record)
                           image_id = db_bg.get_image_id(rel_path)
                           if image_id:
                               if tags:
                                   db_bg.set_tags_for_image(image_id, tags)
                               else:
                                   # Mark as scanned with special tag to prevent reprocessing
                                   db_bg.add_tag_to_image(image_id, '__no_tags__')
                                   
                           enriched_count += 1

                           if enriched_count % commit_interval == 0:
                                db_bg.commit()

                 except Exception as e:
                      pass

             db_bg.commit()
             self._enrichment_exhausted = (enriched_count < max_enrich_per_cycle)
             self._enrichment_actual_count = enriched_count
             self._enrichment_running = False
             print(f"[ENRICH] Enriched {enriched_count}/{len(placeholders)} ({scope})"
                   f"{' [ALL DONE]' if self._enrichment_exhausted else ''}")

             # Signal completion from background thread
             self.enrichment_complete.emit()

        self._load_executor.submit(enrich_worker)

    def load_directory(self, directory_path: Path):
        from PySide6.QtWidgets import QProgressDialog, QApplication, QMessageBox
        from PySide6.QtCore import Qt
        from utils.settings import settings, DEFAULT_SETTINGS

        # DON'T call beginResetModel() here - it clears the view immediately
        # Load all metadata first, THEN reset the model (keeps old images visible during loading)
        error_messages: list[str] = []
        new_images = []  # Build new image list without clearing old one

        # Try to load file paths from DB cache first (much faster for large folders)
        from utils.image_index_db import ImageIndexDB
        db = ImageIndexDB(directory_path)
        cached_paths = db.get_all_paths()
        cache_stats = None
        scan_progress = None

        def _ensure_scan_progress():
            nonlocal scan_progress
            if scan_progress is not None:
                return scan_progress
            scan_progress = QProgressDialog("Scanning folder...", "", 0, 0)
            scan_progress.setWindowTitle("Scanning Folder")
            scan_progress.setWindowModality(Qt.WindowModal)
            scan_progress.setCancelButton(None)
            scan_progress.setMinimumDuration(0)
            scan_progress.setAutoClose(False)
            scan_progress.setAutoReset(False)
            scan_progress.show()
            QApplication.processEvents()
            return scan_progress

        def _update_scan_progress(label: str, count: int = None, maximum: int = None):
            dialog = _ensure_scan_progress()
            if maximum is None:
                dialog.setRange(0, 0)
            else:
                dialog.setRange(0, max(1, int(maximum)))
                if count is not None:
                    dialog.setValue(max(0, min(int(count), dialog.maximum())))
            if count is None:
                dialog.setLabelText(label)
            else:
                dialog.setLabelText(f"{label}\nFiles: {int(count):,}")
            QApplication.processEvents()

        try:
            if cached_paths and len(cached_paths) > 1000:
                # For very large folders, cached path lists are fast, but must be
                # validated or newly added files will be missed.
                cached_count = len(cached_paths)
                _update_scan_progress("Checking folder changes...")
                fs_count, fs_tree_mtime = get_directory_tree_stats(
                    directory_path,
                    progress_callback=lambda c: _update_scan_progress(
                        "Checking folder changes...",
                        count=c,
                    ),
                )
                cache_stats = (fs_count, fs_tree_mtime)

                saved_count_raw = db.get_meta_value('path_cache_file_count')
                saved_tree_mtime_raw = db.get_meta_value('path_cache_tree_mtime')

                try:
                    saved_count = int(saved_count_raw) if saved_count_raw is not None else None
                except (TypeError, ValueError):
                    saved_count = None
                try:
                    saved_tree_mtime = float(saved_tree_mtime_raw) if saved_tree_mtime_raw is not None else None
                except (TypeError, ValueError):
                    saved_tree_mtime = None

                stale_reasons = []
                if fs_count != cached_count:
                    stale_reasons.append(f"count {cached_count:,}->{fs_count:,}")
                if saved_count is None or saved_tree_mtime is None:
                    stale_reasons.append("missing signature")
                else:
                    if saved_count != cached_count:
                        stale_reasons.append(f"signature-count {saved_count:,}->{cached_count:,}")
                    if fs_tree_mtime > (saved_tree_mtime + 0.001):
                        stale_reasons.append("tree-mtime changed")

                if stale_reasons:
                    reason_text = ", ".join(stale_reasons)
                    print(f"[CACHE] Path cache stale ({reason_text}), rescanning filesystem")
                    _update_scan_progress(
                        "Rescanning folder files...",
                        count=0,
                        maximum=max(1, fs_count),
                    )
                    file_paths = get_file_paths(
                        directory_path,
                        progress_callback=lambda c: _update_scan_progress(
                            "Rescanning folder files...",
                            count=c,
                            maximum=max(1, fs_count),
                        ),
                    )
                else:
                    print(f"[CACHE] Using {cached_count:,} cached file paths (skipping scan)")
                    file_paths = {Path(directory_path) / p for p in cached_paths}
            else:
                # Full scan needed (first time or small folder)
                _update_scan_progress("Scanning folder files...")
                file_paths = get_file_paths(
                    directory_path,
                    progress_callback=lambda c: _update_scan_progress(
                        "Scanning folder files...",
                        count=c,
                    ),
                )

            # Persist signature used for path-cache freshness checks (large folders only).
            if len(file_paths) > 1000:
                try:
                    if cache_stats is None:
                        cache_stats = get_directory_tree_stats(directory_path)
                    db.set_meta_value('path_cache_file_count', str(int(cache_stats[0])))
                    db.set_meta_value('path_cache_tree_mtime', f"{float(cache_stats[1]):.6f}")
                    db.set_meta_value('path_cache_updated_at', f"{time.time():.6f}")
                except Exception:
                    pass
        finally:
            if scan_progress is not None:
                scan_progress.close()
                scan_progress.deleteLater()
                scan_progress = None

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

        # Check for pagination mode (based on user setting)
        total_images = len(image_paths)

        # Load pagination threshold from settings (already imported at top)
        pagination_threshold = settings.value(
            'pagination_threshold',
            defaultValue=DEFAULT_SETTINGS['pagination_threshold'],
            type=int
        )

        if total_images >= pagination_threshold:
            if pagination_threshold == 0:
                print(f"[PAGINATION] Using paginated mode (always paginate enabled)")
            else:
                print(f"[PAGINATION] Large folder detected ({total_images} images >= {pagination_threshold} threshold), switching to paginated mode")
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
        # Run maintenance to fix bad dimensions (Super Tall/Fat glitches) and backfill metadata
        db.run_maintenance(directory_path)

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
                        self._apply_loop_metadata_from_meta(image, meta)
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

            # Trigger background metadata backfill safely handled later
            self._trigger_metadata_backfill_later(directory_path)

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

                    except Exception:
                        pass  # Skip problematic images silently

                db_bg.commit()
                db_bg.close()

                print(f"[ENRICH] BG enrichment done: {enriched_count} updated, {self._enrichment_queue.qsize()} queued")

                # Timer will continue processing queue until empty, then stop itself

            # Submit background enrichment task
            self._load_executor.submit(enrich_dimensions)

    def _resolve_page_memory_limits(self) -> tuple[int, int, int]:
        """Resolve raw + effective paginated page-memory limits from settings."""
        raw_max = settings.value(
            'max_pages_in_memory',
            defaultValue=DEFAULT_SETTINGS.get('max_pages_in_memory', 20),
            type=int,
        )
        raw_max = max(3, min(int(raw_max), 60))

        eviction_pages = settings.value(
            'thumbnail_eviction_pages',
            defaultValue=DEFAULT_SETTINGS.get('thumbnail_eviction_pages', 3),
            type=int,
        )
        eviction_pages = max(1, min(int(eviction_pages), 5))

        # Must at least hold current page plus eviction window on both sides.
        required_min = (2 * eviction_pages) + 1
        effective_max = max(raw_max, required_min)
        return raw_max, eviction_pages, effective_max

    def _load_directory_paginated(self, directory_path: Path, image_paths: list[Path], file_paths: set[Path]):
        """Load a large directory using buffered virtual pagination (1M+ images).

        Strategy: Don't load ANY Image objects upfront. Pages (1000 images each) are loaded
        on-demand as user scrolls. Masonry calculates only for loaded pages (buffered range).

        Memory: ~6MB for buffered pages vs ~300MB for all Image objects.
        """
        import time

        total_images = len(image_paths)

        # Initialize database
        self._directory_path = directory_path
        
        # Load max pages from settings with safety guardrail:
        # keep at least the current +/- eviction window (+ current page).
        raw_max, eviction_pages, effective_max = self._resolve_page_memory_limits()
        self.MAX_PAGES_IN_MEMORY = effective_max
        if effective_max != raw_max:
            print(f"[PAGINATION] Max pages in memory: {effective_max} "
                  f"(raised from {raw_max} to satisfy eviction window {eviction_pages})")
        else:
            print(f"[PAGINATION] Max pages in memory: {self.MAX_PAGES_IN_MEMORY}")

        self._db = ImageIndexDB(directory_path)
        self._paginated_mode = True

        # CRITICAL: Ensure DB is populated with files for paginated access
        # This is fast (checks existing) and necessary for get_page() to work
        print(f"[PAGINATION] Ensuring DB is populated for {len(image_paths)} files...")
        self._db.bulk_insert_files(image_paths, directory_path)

        print(f"[PAGINATION] Buffered virtual mode: {total_images} images")
        start_time = time.time()

        self.beginResetModel()

        # Don't load Image objects - keep self.images empty for paginated mode
        self.images = []
        # Sync total count with DB (handling skipped files)
        self._total_count = self._db.get_image_count()
        self._pages = {}  # Will be populated on-demand

        self.endResetModel()

        # Emit signal
        self.total_count_changed.emit(self._total_count)

        # Bootstrap: Load first 3 pages immediately so UI has something to show
        print(f"[PAGINATION] Loading first 3 pages to bootstrap UI...")
        for page_num in range(min(3, (total_images + self.PAGE_SIZE - 1) // self.PAGE_SIZE)):
            self._load_page_sync(page_num)
        print(f"[PAGINATION] Loaded {len(self._pages)} pages initially")

        # Trigger masonry calculation now that we have initial pages
        # CRITICAL: Emit pages_updated BEFORE layoutChanged so proxy invalidates first
        # Otherwise proxy.rowCount() returns 0 during masonry calculation
        self._emit_pages_updated()
        self.layoutChanged.emit()

        elapsed = time.time() - start_time
        print(f"================================================================================")
        print(f"BUFFERED VIRTUAL PAGINATION: {self._total_count} images ready")
        print(f"Load time: {elapsed*1000:.0f}ms")
        print(f"Memory: Minimal (pages load on-demand)")
        print(f"Pages: 0/{(total_images + self.PAGE_SIZE - 1) // self.PAGE_SIZE} loaded initially")
        print(f"Masonry: Calculated only for loaded pages (buffered range)")
        print(f"================================================================================")

    def _read_jpeg_header_dimensions(self, file_path):
        """
        Read JPEG dimensions directly from file header.
        This works on some corrupted JPEG files where PIL fails.
        Returns (width, height) or None if header is too corrupted.
        """
        try:
            with open(file_path, 'rb') as f:
                # Check JPEG signature
                if f.read(2) != b'\xff\xd8':
                    return None

                # Scan for SOF (Start of Frame) marker
                while True:
                    marker = f.read(2)
                    if not marker:
                        return None
                    if marker[0] != 0xff:
                        return None

                    # SOF markers: 0xC0-0xCF (except 0xC4, 0xC8, 0xCC)
                    marker_type = marker[1]
                    if 0xC0 <= marker_type <= 0xCF and marker_type not in (0xC4, 0xC8, 0xCC):
                        # Found SOF - read dimensions
                        length = int.from_bytes(f.read(2), 'big')
                        f.read(1)  # precision
                        height = int.from_bytes(f.read(2), 'big')
                        width = int.from_bytes(f.read(2), 'big')
                        return (width, height)

                    # Skip to next marker
                    length = int.from_bytes(f.read(2), 'big')
                    if length < 2:
                        return None
                    f.seek(length - 2, 1)  # Relative seek
        except Exception:
            return None

    def _restart_enrichment(self):
        """Restart background enrichment after sorting/filtering (with new indices)."""
        # Pagination mode now uses enrichment too for uncached files

        # Cancel any pending final recalc timer from previous enrichment
        if self._final_recalc_timer is not None:
            self._final_recalc_timer.stop()
            self._final_recalc_timer.deleteLater()
            self._final_recalc_timer = None
            import time
            timestamp = time.strftime("%H:%M:%S")
            print(f"[ENRICH {timestamp}] Cancelled pending final recalc timer (sort restarted enrichment)")

        # Clear cancellation flag and completion flag
        self._enrichment_cancelled.clear()
        self._enrichment_completed_flag = False

        # Count how many images still need enrichment
        needs_enrichment = sum(1 for img in self.images if img.dimensions == (512, 512))

        if needs_enrichment == 0:
            return  # Nothing to enrich

        import time

        # Reset incremental recalc counter
        self._enrichment_recalc_counter = 0
        self._last_recalc_time = time.time()

        timestamp = time.strftime("%H:%M:%S")
        print(f"[ENRICH {timestamp}] Restarting background enrichment for {needs_enrichment} images after sort")

        # Start/restart timer if not already running
        if not self._enrichment_timer:
            from PySide6.QtCore import QTimer
            self._enrichment_timer = QTimer()
            self._enrichment_timer.timeout.connect(self._process_enrichment_queue)
        if not self._enrichment_timer.isActive():
            self._enrichment_timer.start(100)

        # Submit background enrichment task using paginated-aware worker
        self._start_paginated_enrichment()

    @property
    def is_paginated(self) -> bool:
        """Check if model is in paginated mode."""
        return getattr(self, '_paginated_mode', False)

    def get_all_tags_stats(self) -> list[dict]:
        """Get all tags with counts from DB (paginated mode)."""
        if self._db:
             return self._db.get_all_tags()
        return []

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

        # Get image ID using relative path (DB stores relative paths)
        try:
            rel_path = str(image.path.relative_to(self._directory_path))
        except ValueError:
            rel_path = image.path.name

        image_id = self._db.get_image_id(rel_path)
        if not image_id:
             # Attempt to self-heal by inserting/updating image info
             try:
                 print(f"[DB FIX] Inserting missing image to DB: {rel_path}")
                 stat = image.path.stat()
                 is_video = image.path.suffix.lower() in ('.mp4', '.avi', '.mov', '.mkv', '.webm')
                 self._db.save_info(
                     file_name=rel_path,
                     width=image.width or 512,
                     height=image.height or 512,
                     is_video=is_video,
                     mtime=stat.st_mtime,
                     rating=image.rating
                 )
                 # Retry get ID
                 image_id = self._db.get_image_id(rel_path)
             except Exception as e:
                 print(f"[DB ERROR] Failed to self-heal image {rel_path}: {e}")

        if image_id:
            if image.tags:
                 self._db.set_tags_for_image(image_id, image.tags)
            else:
                 # Ensure we don't trigger re-enrichment by having at least one tag
                 self._db.set_tags_for_image(image_id, [])
                 self._db.add_tag_to_image(image_id, '__no_tags__')

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
        viewer_loop_markers = self._serialize_viewer_loop_markers(image)
        if viewer_loop_markers:
            meta['viewer_loop_markers'] = viewer_loop_markers
            floating_last = viewer_loop_markers.get('floating_last')
            if isinstance(floating_last, dict):
                meta['floating_last_loop_start_frame'] = floating_last.get('loop_start_frame')
                meta['floating_last_loop_end_frame'] = floating_last.get('loop_end_frame')
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
        self.write_image_tags_to_disk(image)
        self.dataChanged.emit(image_index, image_index)

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
            # Add tags ensuring no duplicates in the image object
            new_tags_added = False
            for tag in tags:
                if tag not in image.tags:
                    image.tags.append(tag)
                    new_tags_added = True
            
            if new_tags_added:
                self.write_image_tags_to_disk(image)
        min_image_index = min(image_indices, key=lambda index: index.row())
        max_image_index = max(image_indices, key=lambda index: index.row())
        self.dataChanged.emit(min_image_index, max_image_index)

    def _rename_tags_paginated(self, old_tags: list[str], new_tag: str, scope, use_regex: bool):
        files_to_process = set()
        if use_regex:
             all_tags = [item['tag'] for item in self._db.get_all_tags()]
             pattern = old_tags[0]
             matched_tags = [t for t in all_tags if re.fullmatch(pattern, t)]
             for t in matched_tags:
                 files_to_process.update(self._db.get_files_with_tag(t))
        else:
             for tag in old_tags:
                 files_to_process.update(self._db.get_files_with_tag(tag))
        
        for rel_path in files_to_process:
             path = self._directory_path / rel_path
             if not path.exists(): continue
             
             txt_path = path.with_suffix('.txt')
             current_tags = []
             if txt_path.exists():
                 try:
                     content = txt_path.read_text(encoding='utf-8', errors='replace')
                     current_tags = [t.strip() for t in content.split(self.tag_separator) if t.strip()]
                 except: pass
            
             updated = False
             new_tags_list = []
             
             if use_regex:
                 pattern = old_tags[0]
                 for tag in current_tags:
                     if re.fullmatch(pattern, tag):
                         new_tags_list.append(new_tag)
                         updated = True
                     else:
                         new_tags_list.append(tag)
             else:
                 for tag in current_tags:
                     if tag in old_tags:
                         new_tags_list.append(new_tag)
                         updated = True
                     else:
                         new_tags_list.append(tag)
            
             if updated:
                 try:
                     txt_path.write_text(self.tag_separator.join(new_tags_list), encoding='utf-8')
                     image_id = self._db.get_image_id(rel_path)
                     if image_id:
                         self._db.set_tags_for_image(image_id, new_tags_list)
                 except Exception as e:
                     print(f"Error updating tags for {rel_path}: {e}")

    def _delete_tags_paginated(self, tags: list[str], scope, use_regex: bool):
        files_to_process = set()
        if use_regex:
             all_tags = [item['tag'] for item in self._db.get_all_tags()]
             pattern = tags[0]
             matched_tags = [t for t in all_tags if re.fullmatch(pattern, t)]
             for t in matched_tags:
                 files_to_process.update(self._db.get_files_with_tag(t))
        else:
             for tag in tags:
                 files_to_process.update(self._db.get_files_with_tag(tag))

        for rel_path in files_to_process:
             path = self._directory_path / rel_path
             if not path.exists(): continue
             
             txt_path = path.with_suffix('.txt')
             current_tags = []
             if txt_path.exists():
                 try:
                     content = txt_path.read_text(encoding='utf-8', errors='replace')
                     current_tags = [t.strip() for t in content.split(self.tag_separator) if t.strip()]
                 except: pass
             
             updated = False
             new_tags_list = []
             
             if use_regex:
                 pattern = tags[0]
                 for tag in current_tags:
                     if not re.fullmatch(pattern, tag):
                         new_tags_list.append(tag)
                     else:
                         updated = True
             else:
                 for tag in current_tags:
                     if tag not in tags:
                         new_tags_list.append(tag)
                     else:
                         updated = True

             if updated:
                 try:
                     txt_path.write_text(self.tag_separator.join(new_tags_list), encoding='utf-8')
                     image_id = self._db.get_image_id(rel_path)
                     if image_id:
                         if new_tags_list:
                             self._db.set_tags_for_image(image_id, new_tags_list)
                         else:
                             self._db.set_tags_for_image(image_id, [])
                             self._db.add_tag_to_image(image_id, '__no_tags__')
                 except Exception as e:
                     print(f"Error deleting tags for {rel_path}: {e}")

    @Slot(list, str)
    def rename_tags(self, old_tags: list[str], new_tag: str,
                    scope: Scope | str = Scope.ALL_IMAGES,
                    use_regex: bool = False):
        self.add_to_undo_stack(
            action_name=f'Rename {pluralize("Tag", len(old_tags))}',
            should_ask_for_confirmation=True)
            
        if self._paginated_mode and scope == Scope.ALL_IMAGES:
            self._rename_tags_paginated(old_tags, new_tag, scope, use_regex)
            # Reload currently loaded pages to reflect changes
            current_pages = list(self._pages.keys())
            self._pages.clear()
            for page in current_pages:
                self._load_page_sync(page)
            self.modelReset.emit()
            return
            
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
            
        if self._paginated_mode and scope == Scope.ALL_IMAGES:
            self._delete_tags_paginated(tags, scope, use_regex)
            # Reload currently loaded pages to reflect changes
            current_pages = list(self._pages.keys())
            self._pages.clear()
            for page in current_pages:
                self._load_page_sync(page)
            self.modelReset.emit()
            return

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
                        self._apply_loop_metadata_from_meta(image, meta)

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

    def _trigger_metadata_backfill_later(self, directory_path):
        """Run metadata backfill in a background thread to avoid blocking UI."""
        import threading
        def backfill_worker():
            try:
                from utils.image_index_db import ImageIndexDB
                db = ImageIndexDB(directory_path)
                if db.enabled:
                    # Small delay to let initial load finish completely
                    import time
                    time.sleep(2.0)
                    db.backfill_missing_metadata(directory_path)
                    db.close()
            except Exception as e:
                print(f"[BACKFILL] Error: {e}")
        
        threading.Thread(target=backfill_worker, daemon=True).start()
