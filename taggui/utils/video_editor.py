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
                    '-frames:v', str(start_frame),  # Exact frame count
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
    def fix_frame_count_to_n4_plus_1(input_path: Path, output_path: Path,
                                    fps: float, repeat_last: bool = True,
                                    target_frames: Optional[int] = None) -> Tuple[bool, str]:
        """
        Adjust video frame count to follow N*4+1 rule by adding or removing frames.
        If target_frames is specified, adjusts to that exact count (must be N*4+1).
        Otherwise, finds the nearest valid N*4+1 count.

        Args:
            input_path: Input video file path
            output_path: Output video file path
            fps: Video frames per second
            repeat_last: Whether to repeat/remove the last frame (True) or first frame (False)
            target_frames: Optional exact target frame count (must be N*4+1)

        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            # Get current frame count
            import subprocess
            probe_cmd = [
                'ffprobe',
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_streams',
                str(input_path)
            ]
            probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
            if probe_result.returncode != 0:
                return False, f"Failed to probe video: {probe_result.stderr}"

            import json
            probe_data = json.loads(probe_result.stdout)
            current_frames = None
            for stream in probe_data.get('streams', []):
                if stream.get('codec_type') == 'video':
                    current_frames = stream.get('nb_frames')
                    break

            if current_frames is None:
                return False, "Could not determine frame count"

            current_frames = int(current_frames)

            # Determine target frame count
            if target_frames is not None:
                # Validate target
                if (target_frames - 1) % 4 != 0:
                    return False, f"Target frame count {target_frames} does not follow N*4+1 rule"
                final_target = target_frames
            else:
                # Find nearest valid N*4+1 with minimal changes
                if (current_frames - 1) % 4 == 0:
                    return True, f"Video already has {current_frames} frames (valid N*4+1)"
                current_n = (current_frames - 1) // 4
                lower_target = current_n * 4 + 1
                upper_target = (current_n + 1) * 4 + 1

                # Calculate frames needed for each option
                frames_to_remove_for_lower = max(0, current_frames - lower_target)
                frames_to_add_for_upper = upper_target - current_frames

                # Choose the option requiring fewer frame changes
                if frames_to_remove_for_lower <= frames_to_add_for_upper:
                    final_target = lower_target
                else:
                    final_target = upper_target

            # Check if already at target
            if current_frames == final_target:
                return True, f"Video already has {current_frames} frames"

            if current_frames < final_target:
                # Need to add frames
                frames_to_add = final_target - current_frames
                if repeat_last:
                    frame_to_repeat = current_frames - 1
                else:
                    frame_to_repeat = 0
                return VideoEditor.repeat_frame(input_path, output_path, frame_to_repeat, frames_to_add, fps)
            else:
                # Need to remove frames
                frames_to_remove = current_frames - final_target
                if repeat_last:
                    # Remove from end
                    start_frame = current_frames - frames_to_remove
                    end_frame = current_frames - 1
                else:
                    # Remove from beginning
                    start_frame = 0
                    end_frame = frames_to_remove - 1
                return VideoEditor.remove_range(input_path, output_path, start_frame, end_frame, fps)

        except Exception as e:
            return False, f"Error: {str(e)}"

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
            # Get current frame count first
            probe_cmd = [
                'ffprobe',
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_streams',
                str(input_path)
            ]
            probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
            if probe_result.returncode != 0:
                return False, f"Failed to probe video: {probe_result.stderr}"

            import json
            probe_data = json.loads(probe_result.stdout)
            current_frames = None
            for stream in probe_data.get('streams', []):
                if stream.get('codec_type') == 'video':
                    current_frames = stream.get('nb_frames')
                    break

            if current_frames is None:
                return False, "Could not determine frame count"

            current_frames = int(current_frames)

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

            # Extract segment before frame (frames 0 to frame_num-1)
            if frame_num > 0:
                # Use frame count instead of time for precision
                cmd1 = [
                    'ffmpeg',
                    '-i', str(input_path),
                    '-frames:v', str(frame_num),  # Exact frame count (0 to frame_num-1)
                    '-c', 'copy',
                    '-y',
                    str(segment1)
                ]
                subprocess.run(cmd1, capture_output=True, check=True)

            # Extract the frame as image
            cmd2 = [
                'ffmpeg',
                '-i', str(input_path),
                '-vf', f'select=eq(n\\,{frame_num})',  # Select exact frame by number
                '-vframes', '1',
                '-y',
                str(frame_img)
            ]
            subprocess.run(cmd2, capture_output=True, check=True)

            # Create video from repeated frame with high quality - use duration
            repeat_duration = repeat_count / fps
            cmd3 = [
                'ffmpeg',
                '-f', 'image2',
                '-loop', '1',  # Loop the image
                '-i', str(frame_img),
                '-c:v', 'libx264',
                '-crf', '18',  # High quality (18 = visually lossless)
                '-preset', 'slow',  # Better compression
                '-t', str(repeat_duration),  # Exact duration
                '-pix_fmt', 'yuv420p',
                '-r', str(fps),
                '-y',
                str(repeated)
            ]
            subprocess.run(cmd3, capture_output=True, check=True)

            # Extract segment after frame (if any frames remain)
            next_frame_time = (frame_num + 1) / fps
            # Check if there are frames after the repeated frame
            if frame_num + 1 < current_frames:
                cmd4 = [
                    'ffmpeg',
                    '-i', str(input_path),
                    '-ss', str(next_frame_time),
                    '-c', 'copy',
                    '-y',
                    str(segment2)
                ]
                subprocess.run(cmd4, capture_output=True, check=True)
            # If no frames after, segment2 remains empty (which is fine)

            # Create concat list - only include segments that exist and have content
            with open(concat_list, 'w') as f:
                if frame_num > 0 and segment1.exists() and segment1.stat().st_size > 0:
                    f.write(f"file '{segment1}'\n")
                if repeated.exists() and repeated.stat().st_size > 0:
                    f.write(f"file '{repeated}'\n")
                if segment2.exists() and segment2.stat().st_size > 0:
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
