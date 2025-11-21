from enum import Enum
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QIcon


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
    is_video: bool = False
    video_metadata: dict | None = None  # fps, duration, frame_count, current_frame
    loop_start_frame: int | None = None
    loop_end_frame: int | None = None

    @property
    def aspect_ratio(self) -> float:
        """Get aspect ratio (width/height), cached to avoid recalculation."""
        if self.dimensions:
            width, height = self.dimensions
            return width / height if height > 0 else 1.0
        return 1.0  # Default square for images without dimensions
