from enum import Enum
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QIcon, QImage


class ImageMarking(str, Enum):
    CROP = 'crop'
    HINT = 'hint'
    INCLUDE = 'include in mask'
    EXCLUDE = 'exclude from mask'
    NONE = 'no marking'


@dataclass
class Marking:
    label: str
    type: ImageMarking
    rect: QRect
    confidence: float = 1.0


@dataclass
class Image:
    path: Path
    dimensions: tuple[int, int] | None
    tags: list[str] = field(default_factory=list)
    target_dimension: QSize | None = None
    crop: QRect | None = None
    markings: list[Marking] = field(default_factory=list)
    rating: float = 0.0
    thumbnail: QIcon | None = None
    thumbnail_qimage: QImage | None = None  # Store QImage, convert to QPixmap/QIcon lazily
    is_video: bool = False
    video_metadata: dict | None = None  # fps, duration, frame_count, current_frame
    loop_start_frame: int | None = None
    loop_end_frame: int | None = None
    viewer_loop_markers: dict[str, dict[str, int | None]] = field(default_factory=dict)
    marked_for_deletion: bool = False
    file_size: int | None = None
    file_type: str | None = None
    ctime: float | None = None
    mtime: float | None = None

    @property
    def aspect_ratio(self) -> float:
        """Get aspect ratio (width/height), cached to avoid recalculation."""
        if self.dimensions:
            width, height = self.dimensions
            # Handle potential None values unpacked from dimensions
            if width is not None and height is not None and height > 0:
                return width / height
        return 1.0  # Default square for images without dimensions
