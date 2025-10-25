"""Video editing utilities using ffmpeg."""
import subprocess
import shutil
import json
from pathlib import Path
from typing import Optional, Tuple, List


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
        Repeat a single frame multiple times using ffmpeg select filter.
        Creates .backup of original. Uses filter-based duplication for frame accuracy.

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

            # Use split filter to create multiple segments and concat them
            # This is more reliable than select for frame duplication
            # Strategy:
            # 1. Split into 3 parts: before, repeated frame, after
            # 2. Extract single frame as separate input
            # 3. Concat all parts together

            temp_dir = output_path.parent / '.temp_segments'
            temp_dir.mkdir(exist_ok=True)

            frame_png = temp_dir / f'frame_{frame_num}.png'

            # Extract the frame to repeat as a PNG
            extract_cmd = [
                'ffmpeg',
                '-i', str(input_path),
                '-vf', f'select=eq(n\\,{frame_num})',
                '-vframes', '1',
                '-y',
                str(frame_png)
            ]
            subprocess.run(extract_cmd, capture_output=True, check=True)

            # Build complex filter to split video and insert repeated frames
            # trimmed_before: frames 0 to frame_num-1
            # trimmed_at: frame frame_num (from original)
            # repeated: frame_num repeated repeat_count times (from PNG)
            # trimmed_after: frames frame_num+1 to end

            filter_parts = []

            # Split the input
            if frame_num > 0:
                # Frames before
                filter_parts.append(f'[0:v]trim=start_frame=0:end_frame={frame_num},setpts=PTS-STARTPTS[before];')

            # Original frame at position
            filter_parts.append(f'[0:v]trim=start_frame={frame_num}:end_frame={frame_num+1},setpts=PTS-STARTPTS[at];')

            # Repeated frames from PNG
            for i in range(repeat_count):
                filter_parts.append(f'[1:v]copy[repeat{i}];')

            # Frames after (if any)
            if frame_num < current_frames - 1:
                filter_parts.append(f'[0:v]trim=start_frame={frame_num+1},setpts=PTS-STARTPTS[after];')

            # Concatenate all parts
            concat_inputs = []
            if frame_num > 0:
                concat_inputs.append('[before]')
            concat_inputs.append('[at]')
            for i in range(repeat_count):
                concat_inputs.append(f'[repeat{i}]')
            if frame_num < current_frames - 1:
                concat_inputs.append('[after]')

            filter_parts.append(f'{"".join(concat_inputs)}concat=n={len(concat_inputs)}:v=1:a=0[outv]')

            filter_complex = ''.join(filter_parts)

            # Run ffmpeg with complex filter
            # Use temp output if input == output to avoid "same as Input" error
            temp_output = output_path.parent / f'.temp_output_{output_path.name}'

            cmd = [
                'ffmpeg',
                '-i', str(input_path),
                '-i', str(frame_png),
                '-filter_complex', filter_complex,
                '-map', '[outv]',
                '-map', '0:a?',  # Include audio if present
                '-c:v', 'libx264',
                '-crf', '18',
                '-preset', 'slow',
                '-c:a', 'aac',
                '-r', str(fps),
                '-y',
                str(temp_output)
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)

            # If successful and input == output, replace input with temp
            if result.returncode == 0 and input_path == output_path:
                import shutil
                shutil.move(str(temp_output), str(output_path))

            # Cleanup
            if frame_png.exists():
                frame_png.unlink()
            if temp_output.exists():
                temp_output.unlink()
            if temp_dir.exists():
                try:
                    temp_dir.rmdir()
                except:
                    pass

            if result.returncode == 0:
                return True, f"Successfully repeated frame {frame_num} {repeat_count} times"
            else:
                return False, f"ffmpeg error: {result.stderr}"

        except FileNotFoundError:
            return False, "ffmpeg not found. Please install ffmpeg."
        except Exception as e:
            return False, f"Error: {str(e)}"

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
            sar_num, sar_den, dims = VideoEditor.check_sar(input_path)

            if sar_num is None:
                return False, "Failed to read video metadata"

            if sar_num == sar_den:
                return True, f"Video already has square pixels (SAR {sar_num}:{sar_den})"

            # Create backup
            if not VideoEditor._create_backup(input_path):
                return False, "Failed to create backup"

            # Calculate display dimensions
            width, height = dims
            display_width = int(width * sar_num / sar_den)

            # Ensure dimensions are even (required by libx264)
            if display_width % 2 != 0:
                display_width += 1
            if height % 2 != 0:
                height += 1

            # Use temp output if input == output to avoid ffmpeg error
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
    def scan_directory_for_non_square_sar(directory: Path, video_extensions: set = None) -> List[Tuple[Path, int, int]]:
        """
        Scan directory for videos with non-square pixel aspect ratios.

        Args:
            directory: Directory to scan
            video_extensions: Set of video file extensions (default: {'.mp4', '.avi', '.mov', '.mkv', '.webm'})

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

                sar_num, sar_den, _ = VideoEditor.check_sar(video_path)
                if sar_num is not None and sar_den is not None and sar_num != sar_den:
                    problem_videos.append((video_path, sar_num, sar_den))

        return problem_videos

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
                progress_callback(i + 1, total, video_path.name)

            success, message = VideoEditor.fix_sar_to_square_pixels(video_path, video_path)

            if success:
                success_count += 1
            else:
                failure_count += 1
                error_messages.append(f"{video_path.name}: {message}")

        return success_count, failure_count, error_messages
