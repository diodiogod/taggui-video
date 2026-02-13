"""FFmpeg GPU acceleration helpers driven by app settings."""

from __future__ import annotations

from utils.settings import settings, DEFAULT_SETTINGS


def ffmpeg_base_args() -> list[str]:
    """Build base ffmpeg invocation with optional decode acceleration args.

    Notes:
    - This only injects decode-side hwaccel flags.
    - Encoding codec selection remains unchanged to preserve behavior.
    """
    cmd = ['ffmpeg']
    accel_mode = str(
        settings.value(
            'video_ffmpeg_accel_mode',
            defaultValue=DEFAULT_SETTINGS.get('video_ffmpeg_accel_mode', 'none'),
            type=str,
        )
    ).strip().lower()

    if accel_mode == 'cuda':
        device_idx = int(
            settings.value(
                'video_ffmpeg_cuda_device',
                defaultValue=DEFAULT_SETTINGS.get('video_ffmpeg_cuda_device', 0),
                type=int,
            )
        )
        cmd.extend([
            '-hwaccel', 'cuda',
            '-hwaccel_output_format', 'cuda',
            '-hwaccel_device', str(max(0, device_idx)),
        ])

    return cmd
