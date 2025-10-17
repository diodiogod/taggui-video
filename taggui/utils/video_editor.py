"""Video editing utilities using ffmpeg."""
import subprocess
import shutil
from pathlib import Path
from typing import Optional, Tuple


class VideoEditor:
    """Handles video editing operations using ffmpeg."""

    @staticmethod
    def _create_backup(input_path: Path) -> bool:
        """Create backup of original video with .backup extension."""
        backup_path = input_path.with_suffix(input_path.suffix + '.backup')
        if not backup_path.exists():
            try:
                shutil.copy2(input_path, backup_path)
                return True
            except Exception:
                return False
        return True  # Backup already exists

    @staticmethod
    def extract_range(input_path: Path, output_path: Path,
                      start_frame: int, end_frame: int, fps: float) -> Tuple[bool, str]:
        """
        Extract a frame range from video to new file.

        Args:
            input_path: Input video file path
            output_path: Output video file path
            start_frame: Starting frame number (inclusive)
            end_frame: Ending frame number (inclusive)
            fps: Video frames per second

        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            # Convert frames to time
            start_time = start_frame / fps
            duration = (end_frame - start_frame + 1) / fps

            # ffmpeg command to extract range - no re-encoding
            cmd = [
                'ffmpeg',
                '-i', str(input_path),
                '-ss', str(start_time),
                '-t', str(duration),
                '-c', 'copy',  # Copy streams without re-encoding
                '-avoid_negative_ts', 'make_zero',  # Fix timestamp issues
                '-y',
                str(output_path)
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0:
                return True, f"Successfully extracted frames {start_frame}-{end_frame}"
            else:
                return False, f"ffmpeg error: {result.stderr}"

        except FileNotFoundError:
            return False, "ffmpeg not found. Please install ffmpeg."
        except Exception as e:
            return False, f"Error: {str(e)}"

    @staticmethod
    def remove_range(input_path: Path, output_path: Path,
                     start_frame: int, end_frame: int, fps: float) -> Tuple[bool, str]:
        """
        Remove a frame range from video.
        Creates .backup of original. Uses stream copy (no re-encoding).

        Args:
            input_path: Input video file path
            output_path: Output video file path
            start_frame: Starting frame to remove (inclusive)
            end_frame: Ending frame to remove (inclusive)
            fps: Video frames per second

        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            # Create backup of original
            if not VideoEditor._create_backup(input_path):
                return False, "Failed to create backup"
            # Create two segments and concatenate
            start_time = start_frame / fps
            end_time = (end_frame + 1) / fps

            # Create temp directory for segments
            temp_dir = output_path.parent / '.temp_segments'
            temp_dir.mkdir(exist_ok=True)

            segment1 = temp_dir / 'segment1.mp4'
            segment2 = temp_dir / 'segment2.mp4'
            concat_list = temp_dir / 'concat.txt'

            # Extract first segment (before removal)
            if start_frame > 0:
                cmd1 = [
                    'ffmpeg',
                    '-i', str(input_path),
                    '-t', str(start_time),
                    '-c', 'copy',
                    '-y',
                    str(segment1)
                ]
                subprocess.run(cmd1, capture_output=True, check=True)

            # Extract second segment (after removal)
            cmd2 = [
                'ffmpeg',
                '-i', str(input_path),
                '-ss', str(end_time),
                '-c', 'copy',
                '-y',
                str(segment2)
            ]
            subprocess.run(cmd2, capture_output=True, check=True)

            # Create concat list
            with open(concat_list, 'w') as f:
                if start_frame > 0 and segment1.exists():
                    f.write(f"file '{segment1}'\n")
                if segment2.exists():
                    f.write(f"file '{segment2}'\n")

            # Concatenate segments
            cmd3 = [
                'ffmpeg',
                '-f', 'concat',
                '-safe', '0',
                '-i', str(concat_list),
                '-c', 'copy',
                '-y',
                str(output_path)
            ]
            result = subprocess.run(cmd3, capture_output=True, text=True)

            # Cleanup temp files
            for f in [segment1, segment2, concat_list]:
                if f.exists():
                    f.unlink()
            temp_dir.rmdir()

            if result.returncode == 0:
                return True, f"Successfully removed frames {start_frame}-{end_frame}"
            else:
                return False, f"ffmpeg error: {result.stderr}"

        except FileNotFoundError:
            return False, "ffmpeg not found. Please install ffmpeg."
        except Exception as e:
            return False, f"Error: {str(e)}"

    @staticmethod
    def remove_frame(input_path: Path, output_path: Path,
                     frame_num: int, fps: float) -> Tuple[bool, str]:
        """
        Remove a single frame from video.

        Args:
            input_path: Input video file path
            output_path: Output video file path
            frame_num: Frame number to remove
            fps: Video frames per second

        Returns:
            Tuple of (success: bool, message: str)
        """
        return VideoEditor.remove_range(input_path, output_path, frame_num, frame_num, fps)

    @staticmethod
    def repeat_frame(input_path: Path, output_path: Path,
                     frame_num: int, repeat_count: int, fps: float) -> Tuple[bool, str]:
        """
        Repeat a single frame multiple times.
        Creates .backup of original. Re-encoding required for repeated segment,
        using high quality settings (CRF 18).

        Args:
            input_path: Input video file path
            output_path: Output video file path
            frame_num: Frame number to repeat
            repeat_count: Number of times to repeat the frame
            fps: Video frames per second

        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            # Create backup of original
            if not VideoEditor._create_backup(input_path):
                return False, "Failed to create backup"
            frame_time = frame_num / fps
            repeat_duration = repeat_count / fps

            # Create temp directory
            temp_dir = output_path.parent / '.temp_segments'
            temp_dir.mkdir(exist_ok=True)

            segment1 = temp_dir / 'before.mp4'
            frame_img = temp_dir / 'frame.png'
            repeated = temp_dir / 'repeated.mp4'
            segment2 = temp_dir / 'after.mp4'
            concat_list = temp_dir / 'concat.txt'

            # Extract segment before frame
            if frame_num > 0:
                cmd1 = [
                    'ffmpeg',
                    '-i', str(input_path),
                    '-t', str(frame_time),
                    '-c', 'copy',
                    '-y',
                    str(segment1)
                ]
                subprocess.run(cmd1, capture_output=True, check=True)

            # Extract the frame as image
            cmd2 = [
                'ffmpeg',
                '-i', str(input_path),
                '-ss', str(frame_time),
                '-vframes', '1',
                '-y',
                str(frame_img)
            ]
            subprocess.run(cmd2, capture_output=True, check=True)

            # Create video from repeated frame with high quality
            cmd3 = [
                'ffmpeg',
                '-loop', '1',
                '-i', str(frame_img),
                '-c:v', 'libx264',
                '-crf', '18',  # High quality (18 = visually lossless)
                '-preset', 'slow',  # Better compression
                '-t', str(repeat_duration),
                '-pix_fmt', 'yuv420p',
                '-r', str(fps),
                '-y',
                str(repeated)
            ]
            subprocess.run(cmd3, capture_output=True, check=True)

            # Extract segment after frame
            next_frame_time = (frame_num + 1) / fps
            cmd4 = [
                'ffmpeg',
                '-i', str(input_path),
                '-ss', str(next_frame_time),
                '-c', 'copy',
                '-y',
                str(segment2)
            ]
            subprocess.run(cmd4, capture_output=True, check=True)

            # Create concat list
            with open(concat_list, 'w') as f:
                if frame_num > 0 and segment1.exists():
                    f.write(f"file '{segment1}'\n")
                if repeated.exists():
                    f.write(f"file '{repeated}'\n")
                if segment2.exists():
                    f.write(f"file '{segment2}'\n")

            # Concatenate all segments with re-encoding to fix timing issues
            cmd5 = [
                'ffmpeg',
                '-f', 'concat',
                '-safe', '0',
                '-i', str(concat_list),
                '-c:v', 'libx264',
                '-crf', '18',
                '-preset', 'slow',
                '-c:a', 'aac',
                '-r', str(fps),  # Force consistent frame rate
                '-y',
                str(output_path)
            ]
            result = subprocess.run(cmd5, capture_output=True, text=True)

            # Cleanup
            for f in [segment1, frame_img, repeated, segment2, concat_list]:
                if f.exists():
                    f.unlink()
            temp_dir.rmdir()

            if result.returncode == 0:
                return True, f"Successfully repeated frame {frame_num} {repeat_count} times"
            else:
                return False, f"ffmpeg error: {result.stderr}"

        except FileNotFoundError:
            return False, "ffmpeg not found. Please install ffmpeg."
        except Exception as e:
            return False, f"Error: {str(e)}"
