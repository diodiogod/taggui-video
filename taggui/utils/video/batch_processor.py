"""Batch processing for video operations."""

from pathlib import Path
from typing import List, Tuple

from .sar_fixer import SARFixer


class BatchProcessor:
    """Handles batch video processing operations."""

    @staticmethod
    def batch_fix_sar(video_paths: List[Path], progress_callback=None) -> Tuple[int, int, List[str]]:
        """
        Batch fix multiple videos with non-square SAR.
        Creates .backup for each video before fixing.

        Args:
            video_paths: List of video paths to fix
            progress_callback: Optional callback(current, total, video_name) for progress updates

        Returns:
            Tuple of (success_count, failure_count, error_messages)
        """
        success_count = 0
        failure_count = 0
        error_messages = []
        total = len(video_paths)

        for i, video_path in enumerate(video_paths):
            if progress_callback:
                # Check if cancelled
                cancelled = progress_callback(i + 1, total, video_path.name)
                if cancelled:
                    break

            success, message = SARFixer.fix_sar_to_square_pixels(video_path, video_path)

            if success:
                success_count += 1
            else:
                failure_count += 1
                error_messages.append(f"{video_path.name}: {message}")

        return success_count, failure_count, error_messages
