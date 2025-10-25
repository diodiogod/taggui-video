"""Video validation utilities for detecting corruption and issues."""

import subprocess
import json
from pathlib import Path
from typing import Tuple, Optional
import cv2


class VideoValidator:
    """Validates video files for corruption and basic integrity."""

    @staticmethod
    def validate_with_ffprobe(video_path: Path, check_decode: bool = True) -> Tuple[bool, str]:
        """
        Validate video using ffprobe to detect corruption.

        Args:
            video_path: Path to video file
            check_decode: If True, attempt to decode all frames to detect corruption

        Returns:
            Tuple of (is_valid: bool, message: str)
        """
        try:
            if check_decode:
                # More thorough check: try to decode all frames
                cmd = [
                    'ffmpeg',
                    '-v', 'error',
                    '-i', str(video_path),
                    '-f', 'null',
                    '-'
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

                # Check for corruption errors
                if result.stderr:
                    # Filter out warnings, only look for actual errors
                    errors = []
                    for line in result.stderr.split('\n'):
                        line_lower = line.lower()
                        if any(err in line_lower for err in ['error', 'corrupt', 'invalid', 'failed', 'missing']):
                            errors.append(line.strip())

                    if errors:
                        return False, f"Video corruption detected:\n" + "\n".join(errors[:5])

                if result.returncode != 0:
                    return False, f"Video decode failed (ffmpeg exit code {result.returncode})"

            # Basic structure check
            cmd = [
                'ffprobe',
                '-v', 'error',
                '-print_format', 'json',
                '-show_streams',
                '-show_format',
                str(video_path)
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

            # Check for errors in stderr
            if result.stderr:
                return False, f"Video corruption detected:\n{result.stderr}"

            if result.returncode != 0:
                return False, f"ffprobe failed with code {result.returncode}"

            # Parse and validate basic properties
            try:
                data = json.loads(result.stdout)

                # Check if we have video streams
                has_video = False
                for stream in data.get('streams', []):
                    if stream.get('codec_type') == 'video':
                        has_video = True
                        break

                if not has_video:
                    return False, "No video stream found"

            except json.JSONDecodeError:
                return False, "Failed to parse video information"

            return True, "Video appears valid"

        except subprocess.TimeoutExpired:
            return False, "Validation timeout - file may be corrupted or very large"
        except FileNotFoundError:
            return False, "ffprobe/ffmpeg not found"
        except Exception as e:
            return False, f"Validation error: {str(e)}"

    @staticmethod
    def validate_with_opencv(video_path: Path, sample_frames: int = 10) -> Tuple[bool, str]:
        """
        Validate video by attempting to read sample frames with OpenCV.

        Args:
            video_path: Path to video file
            sample_frames: Number of frames to sample throughout video

        Returns:
            Tuple of (is_valid: bool, message: str)
        """
        cap = None
        try:
            cap = cv2.VideoCapture(str(video_path))

            if not cap.isOpened():
                return False, "Failed to open video file"

            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            if total_frames <= 0:
                return False, "Video has no frames"

            # Sample frames throughout the video
            failed_frames = []
            sample_positions = [int(i * total_frames / sample_frames)
                              for i in range(sample_frames)]

            for frame_num in sample_positions:
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
                ret, frame = cap.read()

                if not ret or frame is None:
                    failed_frames.append(frame_num)

            if failed_frames:
                return False, f"Failed to read frames: {failed_frames}\nVideo may be corrupted"

            return True, f"Successfully validated {sample_frames} sample frames"

        except Exception as e:
            return False, f"OpenCV validation error: {str(e)}"
        finally:
            if cap is not None:
                cap.release()

    @staticmethod
    def validate(video_path: Path, deep: bool = False, check_decode: bool = False) -> Tuple[bool, str]:
        """
        Validate video file for corruption and integrity.

        Args:
            video_path: Path to video file
            deep: If True, perform deep validation with frame sampling (slower)
            check_decode: If True, attempt to decode entire video with ffmpeg (slowest, most thorough)

        Returns:
            Tuple of (is_valid: bool, message: str)
        """
        if not video_path.exists():
            return False, f"File not found: {video_path}"

        if video_path.stat().st_size == 0:
            return False, "File is empty"

        # First check with ffprobe (fast or thorough depending on check_decode)
        valid, message = VideoValidator.validate_with_ffprobe(video_path, check_decode=check_decode)

        if not valid:
            return False, f"Validation failed: {message}"

        # If deep validation requested, also sample frames with OpenCV
        if deep:
            valid, message = VideoValidator.validate_with_opencv(video_path, sample_frames=20)
            if not valid:
                return False, f"Frame validation failed: {message}"

        return True, "Video validated successfully"
