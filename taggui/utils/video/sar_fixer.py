"""SAR (Sample Aspect Ratio) fixing operations."""

import subprocess
import json
import shutil
from pathlib import Path
from typing import Tuple, Optional

from .common import create_backup


class SARFixer:
    """Handles SAR (Sample Aspect Ratio) fixing operations."""

    @staticmethod
    def check_sar(video_path: Path) -> Tuple[Optional[int], Optional[int], Optional[Tuple[int, int]]]:
        """
        Check video's Sample Aspect Ratio (SAR) and dimensions.

        Args:
            video_path: Path to video file

        Returns:
            Tuple of (sar_num, sar_den, dimensions) or (None, None, None) on error
            dimensions is (width, height) storage dimensions
        """
        try:
            probe_cmd = [
                'ffprobe',
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_streams',
                str(video_path)
            ]
            result = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
            data = json.loads(result.stdout)

            for stream in data.get('streams', []):
                if stream.get('codec_type') == 'video':
                    sar_str = stream.get('sample_aspect_ratio', '1:1')
                    width = stream.get('width')
                    height = stream.get('height')

                    if ':' in sar_str:
                        sar_num, sar_den = map(int, sar_str.split(':'))
                    else:
                        sar_num, sar_den = 1, 1

                    return sar_num, sar_den, (width, height)

            return None, None, None
        except Exception:
            return None, None, None

    @staticmethod
    def fix_sar_to_square_pixels(input_path: Path, output_path: Path) -> Tuple[bool, str]:
        """
        Fix video with non-square pixels (SAR != 1:1) by re-encoding to square pixels.
        Creates .backup of original. Scales video to display dimensions with SAR 1:1.

        Args:
            input_path: Input video file path
            output_path: Output video file path

        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            # Check SAR
            sar_num, sar_den, dims = SARFixer.check_sar(input_path)

            if sar_num is None:
                return False, "Failed to read video metadata"

            if sar_num == sar_den:
                return True, f"Video already has square pixels (SAR {sar_num}:{sar_den})"

            # Create backup
            if not create_backup(input_path):
                return False, "Failed to create backup"

            # Calculate display dimensions to normalize SAR to 1:1
            # When SAR != 1:1, video is displayed stretched. Scale storage dimension
            # to match the display aspect ratio with square pixels.
            width, height = dims
            display_width = int(width * sar_num / sar_den)

            # Ensure dimensions are even (required by libx264)
            if display_width % 2 != 0:
                display_width += 1
            if height % 2 != 0:
                height += 1

            # Use temp output if input == output
            temp_output = output_path.parent / f'.temp_sar_fix_{output_path.name}'

            # Re-encode with correct dimensions and square pixels
            cmd = [
                'ffmpeg',
                '-i', str(input_path),
                '-vf', f'scale={display_width}:{height}:flags=lanczos,setsar=1:1',
                '-c:v', 'libx264',
                '-crf', '18',
                '-preset', 'slow',
                '-c:a', 'copy',  # Copy audio without re-encoding
                '-y',
                str(temp_output)
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)

            # If successful and input == output, replace input with temp
            if result.returncode == 0:
                if input_path == output_path:
                    shutil.move(str(temp_output), str(output_path))
                elif temp_output != output_path:
                    shutil.move(str(temp_output), str(output_path))
                return True, f"Fixed SAR {sar_num}:{sar_den} → 1:1, scaled {width}×{height} → {display_width}×{height}"
            else:
                # Cleanup temp file on error
                if temp_output.exists():
                    temp_output.unlink()
                return False, f"ffmpeg error: {result.stderr}"

        except FileNotFoundError:
            return False, "ffmpeg not found. Please install ffmpeg."
        except Exception as e:
            return False, f"Error: {str(e)}"

    @staticmethod
    def scan_directory_for_non_square_sar(directory: Path, video_extensions: set = None):
        """
        Scan directory for videos with non-square pixel aspect ratios.

        Args:
            directory: Directory to scan
            video_extensions: Set of video file extensions

        Returns:
            List of tuples: (video_path, sar_num, sar_den) for videos with SAR != 1:1
        """
        if video_extensions is None:
            video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.webm'}

        problem_videos = []

        for video_path in directory.rglob('*'):
            if video_path.suffix.lower() in video_extensions:
                # Skip backup files
                if video_path.suffix.endswith('.backup'):
                    continue

                sar_num, sar_den, _ = SARFixer.check_sar(video_path)
                if sar_num is not None and sar_den is not None and sar_num != sar_den:
                    problem_videos.append((video_path, sar_num, sar_den))

        return problem_videos
