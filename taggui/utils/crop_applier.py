"""Apply crop operations to images and videos with backup support."""

import shutil
import subprocess
from pathlib import Path
from PIL import Image
from PySide6.QtCore import QRect


def create_backup(file_path: Path) -> bool:
    """Create backup of original file with .backup extension.

    Returns True if backup was created or already exists.
    """
    backup_path = file_path.with_suffix(file_path.suffix + '.backup')
    if not backup_path.exists():
        try:
            shutil.copy2(file_path, backup_path)
            return True
        except Exception:
            return False
    return True  # Backup already exists


def apply_crop_to_image(image_path: Path, crop_rect: QRect) -> tuple[bool, str]:
    """Apply crop to an image file in-place (creates backup).

    Args:
        image_path: Path to the image file
        crop_rect: QRect defining the crop area (x, y, width, height)

    Returns:
        (success, message) tuple
    """
    try:
        # Create backup first
        if not create_backup(image_path):
            return False, f"Failed to create backup for {image_path.name}"

        # Open image
        img = Image.open(image_path)

        # Convert QRect to PIL crop box (left, top, right, bottom)
        # QRect uses (x, y, width, height), PIL uses (left, top, right, bottom)
        crop_box = (
            crop_rect.x(),
            crop_rect.y(),
            crop_rect.x() + crop_rect.width(),
            crop_rect.y() + crop_rect.height()
        )

        # Crop the image
        cropped = img.crop(crop_box)

        # Save back to original path
        # Preserve format and quality
        save_kwargs = {}
        if image_path.suffix.lower() in ['.jpg', '.jpeg']:
            save_kwargs['quality'] = 95
            save_kwargs['optimize'] = True
        elif image_path.suffix.lower() == '.png':
            save_kwargs['optimize'] = True

        cropped.save(image_path, **save_kwargs)

        return True, f"Cropped {image_path.name} to {crop_rect.width()}x{crop_rect.height()}"

    except Exception as e:
        return False, f"Error cropping {image_path.name}: {str(e)}"


def apply_crop_to_video(video_path: Path, crop_rect: QRect) -> tuple[bool, str]:
    """Apply crop to a video file in-place (creates backup).

    Args:
        video_path: Path to the video file
        crop_rect: QRect defining the crop area (x, y, width, height)

    Returns:
        (success, message) tuple
    """
    try:
        # Create backup first
        if not create_backup(video_path):
            return False, f"Failed to create backup for {video_path.name}"

        # Create temp output path
        temp_output = video_path.with_suffix('.temp' + video_path.suffix)

        # Build ffmpeg crop filter
        # Format: crop=width:height:x:y
        crop_filter = f"crop={crop_rect.width()}:{crop_rect.height()}:{crop_rect.x()}:{crop_rect.y()}"

        # Run ffmpeg to crop video
        cmd = [
            'ffmpeg', '-y',
            '-i', str(video_path),
            '-vf', crop_filter,
            '-c:v', 'libx264',  # Re-encode video
            '-preset', 'medium',
            '-crf', '18',  # High quality
            '-c:a', 'copy',  # Copy audio stream
            str(temp_output)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            if temp_output.exists():
                temp_output.unlink()
            return False, f"FFmpeg error: {result.stderr[-200:]}"

        # Replace original with cropped version
        shutil.move(str(temp_output), str(video_path))

        return True, f"Cropped {video_path.name} to {crop_rect.width()}x{crop_rect.height()}"

    except Exception as e:
        if temp_output.exists():
            temp_output.unlink()
        return False, f"Error cropping {video_path.name}: {str(e)}"


def apply_crop(file_path: Path, crop_rect: QRect) -> tuple[bool, str]:
    """Apply crop to an image or video file.

    Automatically detects file type and applies appropriate crop method.

    Args:
        file_path: Path to the file
        crop_rect: QRect defining the crop area

    Returns:
        (success, message) tuple
    """
    video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.webm'}

    if file_path.suffix.lower() in video_extensions:
        return apply_crop_to_video(file_path, crop_rect)
    else:
        return apply_crop_to_image(file_path, crop_rect)
