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
    love: bool = False
    bomb: bool = False
    reaction_updated_at: float | None = None
    review_rank: int = 0
    review_flags: int = 0
    review_updated_at: float | None = None
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

    def valid_dimensions(self) -> tuple[int, int] | None:
        """Return normalized dimensions only when both sides are usable."""
        if not self.dimensions or len(self.dimensions) < 2:
            return None

        width, height = self.dimensions[0], self.dimensions[1]
        if width is None or height is None:
            return None

        try:
            width = int(width)
            height = int(height)
        except (TypeError, ValueError):
            return None

        if width <= 0 or height <= 0:
            return None

        return width, height

    def dimensions_qsize(self) -> QSize | None:
        """Return dimensions as QSize when both values are valid."""
        dimensions = self.valid_dimensions()
        if dimensions is None:
            return None
        return QSize(*dimensions)

    def dimensions_qrect(self) -> QRect:
        """Return dimensions as QRect, or an empty rect when unknown."""
        dimensions = self.valid_dimensions()
        if dimensions is None:
            return QRect()
        return QRect(0, 0, *dimensions)

    @property
    def aspect_ratio(self) -> float:
        """Get aspect ratio (width/height), cached to avoid recalculation."""
        dimensions = self.valid_dimensions()
        if dimensions:
            width, height = dimensions
            return width / height
        return 1.0  # Default square for images without dimensions
