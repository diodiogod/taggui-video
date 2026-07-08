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


def ffmpeg_base_args_software() -> list[str]:
    """Base ffmpeg args without hwaccel_output_format.

    Use this for editing operations that apply software filters (trim, setpts,
    scale, etc.). When hwaccel_output_format=cuda is set, decoded frames stay
    on the GPU and software filters cannot process them, causing:
      'Impossible to convert between the formats supported by the filter
       Parsed_setpts_N and the filter auto_scale_0'

    CUDA hwaccel for decode is still used when available (faster demux), but
    frames are downloaded to system RAM before the filter chain runs.
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
        # hwaccel without hwaccel_output_format: CUDA accelerates decode but
        # frames are automatically downloaded to system RAM for software filters.
        cmd.extend([
            '-hwaccel', 'cuda',
            '-hwaccel_device', str(max(0, device_idx)),
        ])

    return cmd
