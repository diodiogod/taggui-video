"""Video editing utilities - Compatibility shim for imports."""

# This module maintains backward compatibility for existing imports
# from utils.video_editor import VideoEditor

from utils.video.video_editor import VideoEditor

__all__ = ['VideoEditor']
