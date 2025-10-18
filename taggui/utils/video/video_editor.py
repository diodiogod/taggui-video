"""Video editing utilities - Backward compatibility wrapper."""

from pathlib import Path
from typing import Tuple, Optional, List

from .frame_editor import FrameEditor
from .sar_fixer import SARFixer
from .batch_processor import BatchProcessor
from .common import create_backup


class VideoEditor:
    """
    Unified video editor interface - delegates to specialized modules.
    Maintains backward compatibility with original VideoEditor class.
    """

    # Frame editing operations
    @staticmethod
    def extract_range_rough(input_path: Path, output_path: Path,
                            start_frame: int, end_frame: int, fps: float) -> Tuple[bool, str]:
        """Extract a rough frame range using keyframes (fast, no re-encoding)."""
        return FrameEditor.extract_range_rough(input_path, output_path, start_frame, end_frame, fps)

    @staticmethod
    def extract_range(input_path: Path, output_path: Path,
                      start_frame: int, end_frame: int, fps: float, reverse: bool = False) -> Tuple[bool, str]:
        """Extract a frame range from video (precise, re-encodes)."""
        return FrameEditor.extract_range(input_path, output_path, start_frame, end_frame, fps, reverse)

    @staticmethod
    def remove_range(input_path: Path, output_path: Path,
                     start_frame: int, end_frame: int, fps: float) -> Tuple[bool, str]:
        """Remove a frame range from video."""
        return FrameEditor.remove_range(input_path, output_path, start_frame, end_frame, fps)

    @staticmethod
    def remove_frame(input_path: Path, output_path: Path,
                     frame_num: int, fps: float) -> Tuple[bool, str]:
        """Remove a single frame from video."""
        return FrameEditor.remove_frame(input_path, output_path, frame_num, fps)

    @staticmethod
    def repeat_frame(input_path: Path, output_path: Path,
                     frame_num: int, repeat_count: int, fps: float) -> Tuple[bool, str]:
        """Repeat a single frame multiple times."""
        return FrameEditor.repeat_frame(input_path, output_path, frame_num, repeat_count, fps)

    @staticmethod
    def fix_frame_count_to_n4_plus_1(input_path: Path, output_path: Path,
                                    fps: float, repeat_last: bool = True,
                                    target_frames: Optional[int] = None) -> Tuple[bool, str]:
        """Adjust video frame count to follow N*4+1 rule."""
        return FrameEditor.fix_frame_count_to_n4_plus_1(
            input_path, output_path, fps, repeat_last, target_frames
        )

    @staticmethod
    def change_speed(input_path: Path, output_path: Path,
                    speed_multiplier: float, target_fps: Optional[float] = None) -> Tuple[bool, str]:
        """Change video speed by adjusting frame count (drops/duplicates frames)."""
        return FrameEditor.change_speed(input_path, output_path, speed_multiplier, target_fps)

    @staticmethod
    def change_fps(input_path: Path, output_path: Path,
                   target_fps: float) -> Tuple[bool, str]:
        """Change video FPS without changing duration (drops/duplicates frames as needed)."""
        return FrameEditor.change_fps(input_path, output_path, target_fps)

    # SAR fixing operations
    @staticmethod
    def check_sar(video_path: Path) -> Tuple[Optional[int], Optional[int], Optional[Tuple[int, int]]]:
        """Check video's Sample Aspect Ratio."""
        return SARFixer.check_sar(video_path)

    @staticmethod
    def fix_sar_to_square_pixels(input_path: Path, output_path: Path) -> Tuple[bool, str]:
        """Fix video with non-square pixels."""
        return SARFixer.fix_sar_to_square_pixels(input_path, output_path)

    @staticmethod
    def scan_directory_for_non_square_sar(directory: Path, video_extensions: set = None) -> List[Tuple[Path, int, int]]:
        """Scan directory for videos with non-square SAR."""
        return SARFixer.scan_directory_for_non_square_sar(directory, video_extensions)

    # Batch processing operations
    @staticmethod
    def batch_fix_sar(video_paths: List[Path], progress_callback=None) -> Tuple[int, int, List[str]]:
        """Batch fix multiple videos with non-square SAR."""
        return BatchProcessor.batch_fix_sar(video_paths, progress_callback)

    # Common utilities
    @staticmethod
    def _create_backup(input_path: Path) -> bool:
        """Create backup of original video."""
        return create_backup(input_path)
