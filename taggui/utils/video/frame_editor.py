"""Frame-level video editing operations."""

import subprocess
import json
from pathlib import Path
from typing import Tuple, Optional

from .common import create_backup


class FrameEditor:
    """Handles frame-level video editing operations using ffmpeg."""

    @staticmethod
    def extract_range_rough(input_path: Path, output_path: Path,
                            start_frame: int, end_frame: int, fps: float) -> Tuple[bool, str]:
        """
        Extract a rough frame range from video using keyframes (no re-encoding).
        FAST but NOT frame-accurate - cuts at nearest keyframes.
        Preserves 100% original quality. Creates .backup of original if input == output.

        Args:
            input_path: Input video file path
            output_path: Output video file path
            start_frame: Starting frame number (approximate)
            end_frame: Ending frame number (approximate)
            fps: Video frames per second

        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            # Create backup if replacing original
            if input_path == output_path:
                if not create_backup(input_path):
                    return False, "Failed to create backup"

            # Convert frames to time
            start_time = start_frame / fps
            end_time = (end_frame + 1) / fps
            duration = end_time - start_time

            # Use temp output if input == output
            import shutil
            temp_output = output_path.parent / f'.temp_extract_rough_{output_path.name}'
            actual_output = temp_output if input_path == output_path else output_path

            # ffmpeg command with stream copy (keyframe-accurate only, no re-encoding)
            cmd = [
                'ffmpeg',
                '-ss', str(start_time),  # Seek to start (keyframe)
                '-i', str(input_path),
                '-t', str(duration),     # Duration
                '-c', 'copy',            # Stream copy - no re-encoding!
                '-avoid_negative_ts', '1',
                '-y',
                str(actual_output)
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)

            # If successful and input == output, replace input with temp
            if result.returncode == 0 and input_path == output_path:
                shutil.move(str(temp_output), str(output_path))

            # Cleanup temp if it still exists
            if temp_output.exists():
                temp_output.unlink()

            if result.returncode == 0:
                return True, (f"Successfully extracted rough range (keyframe-based)\n"
                             f"Requested: frames {start_frame}-{end_frame}\n"
                             f"NOTE: Actual cut may be off by a few frames due to keyframe positioning")
            else:
                return False, f"ffmpeg error: {result.stderr}"

        except FileNotFoundError:
            return False, "ffmpeg not found. Please install ffmpeg."
        except Exception as e:
            return False, f"Error: {str(e)}"

    @staticmethod
    def extract_range(input_path: Path, output_path: Path,
                      start_frame: int, end_frame: int, fps: float, reverse: bool = False,
                      speed_factor: float = 1.0, target_fps: Optional[float] = None) -> Tuple[bool, str]:
        """
        Extract a frame range from video with FRAME ACCURACY (re-encodes).
        SLOW but PRECISE. Creates .backup of original if input == output.
        Optionally apply speed and/or FPS changes in the same encode pass.

        Args:
            input_path: Input video file path
            output_path: Output video file path
            start_frame: Starting frame number (inclusive)
            end_frame: Ending frame number (inclusive)
            fps: Video frames per second
            reverse: If True, reverse the extracted video
            speed_factor: Speed multiplier (2.0 = 2x faster, 0.5 = half speed). Default: 1.0
            target_fps: Target FPS for output. If None, keeps original FPS. Default: None

        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            # Create backup if replacing original
            if input_path == output_path:
                if not create_backup(input_path):
                    return False, "Failed to create backup"

            # Convert frames to time
            start_time = start_frame / fps
            duration = (end_frame - start_frame + 1) / fps

            # Use temp output if input == output
            import shutil
            temp_output = output_path.parent / f'.temp_extract_{output_path.name}'
            actual_output = temp_output if input_path == output_path else output_path

            # Build video filter chain
            vf_parts = [f'trim=start_frame={start_frame}:end_frame={end_frame+1}', 'setpts=PTS-STARTPTS']
            if reverse:
                vf_parts.append('reverse')

            # Add speed filter if needed
            if abs(speed_factor - 1.0) >= 0.01:
                vf_parts.append(f'setpts=PTS/{speed_factor}')

            # Add FPS filter if needed
            if target_fps is not None:
                vf_parts.append(f'fps={target_fps}')

            vf = ','.join(vf_parts)

            # Build audio filter chain
            af_parts = [f'atrim=start={start_time}:duration={duration}', 'asetpts=PTS-STARTPTS']
            if reverse:
                af_parts.append('areverse')

            # Add audio speed filter if needed (atempo has limitations: 0.5-2.0 range)
            if abs(speed_factor - 1.0) >= 0.01:
                # atempo only supports 0.5-2.0, so chain multiple filters if needed
                tempo = speed_factor
                while tempo > 2.0:
                    af_parts.append('atempo=2.0')
                    tempo /= 2.0
                while tempo < 0.5:
                    af_parts.append('atempo=0.5')
                    tempo /= 0.5
                if abs(tempo - 1.0) >= 0.01:
                    af_parts.append(f'atempo={tempo}')

            af = ','.join(af_parts)

            # ffmpeg command to extract range - frame-accurate extraction
            # Note: -c copy cannot do frame-accurate cuts, only keyframe cuts
            # Using trim filter for frame accuracy with re-encoding
            cmd = [
                'ffmpeg',
                '-i', str(input_path),
                '-vf', vf,
                '-af', af,
                '-c:v', 'libx264',
                '-crf', '18',  # High quality
                '-preset', 'medium',
                '-c:a', 'aac',  # Re-encode audio
                '-b:a', '192k',
                '-y',
                str(actual_output)
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)

            # If successful and input == output, replace input with temp
            if result.returncode == 0 and input_path == output_path:
                shutil.move(str(temp_output), str(output_path))

            # Cleanup temp if it still exists
            if temp_output.exists():
                temp_output.unlink()

            if result.returncode == 0:
                # Calculate expected output frames (considering speed/FPS changes)
                input_frames = end_frame - start_frame + 1

                # If speed or FPS changed, calculate expected output frames
                if abs(speed_factor - 1.0) >= 0.01 or target_fps is not None:
                    original_duration = input_frames / fps
                    new_duration = original_duration / speed_factor
                    output_fps = target_fps if target_fps is not None else fps
                    expected_output_frames = max(1, int(new_duration * output_fps))
                else:
                    expected_output_frames = input_frames

                # Verify output frame count
                probe_cmd = [
                    'ffprobe',
                    '-v', 'error',
                    '-select_streams', 'v:0',
                    '-count_frames',
                    '-show_entries', 'stream=nb_read_frames',
                    '-of', 'csv=p=0',
                    str(output_path)
                ]
                try:
                    probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=10)
                    if probe_result.returncode == 0:
                        actual_frames = int(probe_result.stdout.strip())
                        # Allow small tolerance for rounding differences
                        if abs(actual_frames - expected_output_frames) > 2:
                            return False, (f"Extraction incomplete: got {actual_frames} frames "
                                         f"but expected {expected_output_frames} frames. "
                                         f"This may indicate a corrupted source video.")
                except:
                    pass  # Skip verification if ffprobe fails

                reversed_msg = " (reversed)" if reverse else ""
                speed_msg = f" at {speed_factor}x speed" if abs(speed_factor - 1.0) >= 0.01 else ""
                fps_msg = f" @ {target_fps}fps" if target_fps is not None else ""

                # Get actual frame count for success message
                actual_output_frames = actual_frames if 'actual_frames' in locals() else expected_output_frames
                return True, f"Successfully extracted {input_frames} frames ({start_frame}-{end_frame}) → {actual_output_frames} output frames{reversed_msg}{speed_msg}{fps_msg}"
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
            if not create_backup(input_path):
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
        return FrameEditor.remove_range(input_path, output_path, frame_num, frame_num, fps)

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
            if not create_backup(input_path):
                return False, "Failed to create backup"

            # Use split filter to create multiple segments and concat them
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

            # Build complex filter
            filter_parts = []

            # Split the input
            if frame_num > 0:
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

            # Use temp output if input == output
            import shutil
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
                # Find nearest valid N*4+1
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
                return FrameEditor.repeat_frame(input_path, output_path, frame_to_repeat, frames_to_add, fps)
            else:
                # Need to remove frames
                frames_to_remove = current_frames - final_target
                if repeat_last:
                    start_frame = current_frames - frames_to_remove
                    end_frame = current_frames - 1
                else:
                    start_frame = 0
                    end_frame = frames_to_remove - 1
                return FrameEditor.remove_range(input_path, output_path, start_frame, end_frame, fps)

        except Exception as e:
            return False, f"Error: {str(e)}"

    @staticmethod
    def change_speed(input_path: Path, output_path: Path,
                    speed_multiplier: float, target_fps: Optional[float] = None) -> Tuple[bool, str]:
        """
        Change video speed by adjusting frame count (drops/duplicates frames).
        Creates .backup of original if input == output.

        Args:
            input_path: Input video file path
            output_path: Output video file path
            speed_multiplier: Speed multiplier (>1.0 = faster/fewer frames, <1.0 = slower/more frames)
            target_fps: Optional target FPS (if None, keeps original FPS)

        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            # Get original video info
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

            probe_data = json.loads(probe_result.stdout)
            original_fps = None
            for stream in probe_data.get('streams', []):
                if stream.get('codec_type') == 'video':
                    fps_str = stream.get('r_frame_rate', '0/1')
                    num, denom = map(float, fps_str.split('/'))
                    original_fps = num / denom if denom != 0 else 0
                    break

            if not original_fps:
                return False, "Could not determine original FPS"

            # Create backup if replacing original
            if input_path == output_path:
                if not create_backup(input_path):
                    return False, "Failed to create backup"

            # Use temp output if input == output
            import shutil
            temp_output = output_path.parent / f'.temp_speed_{output_path.name}'
            actual_output = temp_output if input_path == output_path else output_path

            # Build filter chain: setpts for speed, then fps for FPS change
            filters = []

            # Step 1: Change speed using setpts (affects duration)
            if abs(speed_multiplier - 1.0) > 0.01:
                # setpts=PTS/speed makes video faster (smaller PTS values)
                filters.append(f'setpts=PTS/{speed_multiplier}')

            # Step 2: Change FPS (affects frame count for the new duration)
            final_fps = target_fps if target_fps is not None else original_fps
            filters.append(f'fps={final_fps}')

            filter_string = ','.join(filters)

            # ffmpeg command to change speed and/or fps
            cmd = [
                'ffmpeg',
                '-i', str(input_path),
                '-filter:v', filter_string,
                '-c:a', 'copy',  # Keep audio unchanged
                '-y',
                str(actual_output)
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)

            # If successful and input == output, replace input with temp
            if result.returncode == 0 and input_path == output_path:
                shutil.move(str(temp_output), str(output_path))

            # Cleanup temp if it still exists
            if temp_output.exists():
                temp_output.unlink()

            if result.returncode == 0:
                return True, f"Successfully changed speed to {speed_multiplier:.2f}x (FPS: {final_fps:.2f})"
            else:
                return False, f"ffmpeg error: {result.stderr}"

        except FileNotFoundError:
            return False, "ffmpeg not found. Please install ffmpeg."
        except Exception as e:
            return False, f"Error: {str(e)}"

    @staticmethod
    def change_fps(input_path: Path, output_path: Path,
                   target_fps: float) -> Tuple[bool, str]:
        """
        Change video FPS without changing duration (drops/duplicates frames as needed).
        Preserves duration by adjusting frame count to match new FPS.
        Creates .backup of original if input == output.

        Args:
            input_path: Input video file path
            output_path: Output video file path
            target_fps: Target frames per second

        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            # Get original video info
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

            probe_data = json.loads(probe_result.stdout)
            original_fps = None
            current_frames = None
            for stream in probe_data.get('streams', []):
                if stream.get('codec_type') == 'video':
                    fps_str = stream.get('r_frame_rate', '0/1')
                    num, denom = map(float, fps_str.split('/'))
                    original_fps = num / denom if denom != 0 else 0
                    current_frames = int(stream.get('nb_frames', 0))
                    break

            if not original_fps:
                return False, "Could not determine original FPS"

            # Check if already at target FPS
            if abs(original_fps - target_fps) < 0.01:
                return True, f"Video already at {original_fps:.2f} fps"

            # Calculate duration and expected new frame count
            duration = current_frames / original_fps if original_fps > 0 else 0
            new_frame_count = int(duration * target_fps)

            # Create backup if replacing original
            if input_path == output_path:
                if not create_backup(input_path):
                    return False, "Failed to create backup"

            # Use temp output if input == output
            import shutil
            temp_output = output_path.parent / f'.temp_fps_{output_path.name}'
            actual_output = temp_output if input_path == output_path else output_path

            # Use fps filter to change framerate (automatically drops/duplicates frames)
            # This preserves duration by adjusting frame count
            cmd = [
                'ffmpeg',
                '-i', str(input_path),
                '-filter:v', f'fps={target_fps}',
                '-c:a', 'copy',  # Keep audio unchanged
                '-y',
                str(actual_output)
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)

            # If successful and input == output, replace input with temp
            if result.returncode == 0 and input_path == output_path:
                shutil.move(str(temp_output), str(output_path))

            # Cleanup temp if it still exists
            if temp_output.exists():
                temp_output.unlink()

            if result.returncode == 0:
                action = "dropped" if target_fps < original_fps else "duplicated"
                return True, (f"Successfully changed FPS: {original_fps:.2f} → {target_fps:.2f} fps\n"
                             f"Frames: {current_frames} → ~{new_frame_count} ({action} frames to preserve duration)")
            else:
                return False, f"ffmpeg error: {result.stderr}"

        except FileNotFoundError:
            return False, "ffmpeg not found. Please install ffmpeg."
        except Exception as e:
            return False, f"Error: {str(e)}"
