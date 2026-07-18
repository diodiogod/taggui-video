"""Playback backend selection helpers.

This module defines stable backend identifiers and runtime resolution rules.
"""

from __future__ import annotations

from utils.settings import DEFAULT_SETTINGS, settings
from .mpv_runtime import bootstrap_mpv_runtime_search_paths
from .vlc_runtime import bootstrap_vlc_runtime_search_paths

PLAYBACK_BACKEND_QT_HYBRID = 'qt_hybrid'
PLAYBACK_BACKEND_MPV_EXPERIMENTAL = 'mpv_experimental'
PLAYBACK_BACKEND_VLC_EXPERIMENTAL = 'vlc_experimental'

PLAYBACK_BACKEND_CHOICES = [
    PLAYBACK_BACKEND_QT_HYBRID,
    PLAYBACK_BACKEND_MPV_EXPERIMENTAL,
    PLAYBACK_BACKEND_VLC_EXPERIMENTAL,
]

RUNTIME_SUPPORTED_PLAYBACK_BACKENDS = {
    PLAYBACK_BACKEND_QT_HYBRID,
}

MPV_RUNTIME_BOOTSTRAP_INFO = bootstrap_mpv_runtime_search_paths()
MPV_RUNTIME_SEARCHED_DIRS = MPV_RUNTIME_BOOTSTRAP_INFO.get('searched_dirs', [])
MPV_RUNTIME_ADDED_DIRS = MPV_RUNTIME_BOOTSTRAP_INFO.get('added_dirs', [])

VLC_RUNTIME_BOOTSTRAP_INFO = bootstrap_vlc_runtime_search_paths()
VLC_RUNTIME_SEARCHED_DIRS = VLC_RUNTIME_BOOTSTRAP_INFO.get('searched_dirs', [])
VLC_RUNTIME_ADDED_DIRS = VLC_RUNTIME_BOOTSTRAP_INFO.get('added_dirs', [])
VLC_RUNTIME_PLUGIN_DIRS = VLC_RUNTIME_BOOTSTRAP_INFO.get('plugin_dirs', [])

MPV_PYTHON_MODULE = None
MPV_BACKEND_AVAILABLE = False
MPV_BACKEND_ERROR = ''
VLC_PYTHON_MODULE = None
VLC_BACKEND_AVAILABLE = False
VLC_BACKEND_ERROR = ''
_BACKEND_LOAD_ATTEMPTED: set[str] = set()


def load_playback_backend(backend_name: str):
    """Load an optional playback runtime only when it is requested."""
    global MPV_PYTHON_MODULE, MPV_BACKEND_AVAILABLE, MPV_BACKEND_ERROR
    global VLC_PYTHON_MODULE, VLC_BACKEND_AVAILABLE, VLC_BACKEND_ERROR

    selected = normalize_playback_backend_name(backend_name)
    if selected in _BACKEND_LOAD_ATTEMPTED:
        if selected == PLAYBACK_BACKEND_MPV_EXPERIMENTAL:
            return MPV_PYTHON_MODULE
        if selected == PLAYBACK_BACKEND_VLC_EXPERIMENTAL:
            return VLC_PYTHON_MODULE
        return None

    _BACKEND_LOAD_ATTEMPTED.add(selected)
    if selected == PLAYBACK_BACKEND_MPV_EXPERIMENTAL:
        try:
            import mpv as _mpv  # type: ignore
            MPV_PYTHON_MODULE = _mpv
            MPV_BACKEND_AVAILABLE = True
            MPV_BACKEND_ERROR = ''
        except Exception as e:
            MPV_BACKEND_AVAILABLE = False
            MPV_BACKEND_ERROR = f'{type(e).__name__}: {e}'
        return MPV_PYTHON_MODULE

    if selected == PLAYBACK_BACKEND_VLC_EXPERIMENTAL:
        try:
            import vlc as _vlc  # type: ignore
            VLC_PYTHON_MODULE = _vlc
            VLC_BACKEND_AVAILABLE = True
            VLC_BACKEND_ERROR = ''
        except Exception as e:
            VLC_BACKEND_AVAILABLE = False
            VLC_BACKEND_ERROR = f'{type(e).__name__}: {e}'
        return VLC_PYTHON_MODULE

    return None


def get_playback_backend_status(backend_name: str) -> tuple[bool, str]:
    """Return availability and load error, probing the requested backend once."""
    selected = normalize_playback_backend_name(backend_name)
    load_playback_backend(selected)
    if selected == PLAYBACK_BACKEND_MPV_EXPERIMENTAL:
        return MPV_BACKEND_AVAILABLE, MPV_BACKEND_ERROR
    if selected == PLAYBACK_BACKEND_VLC_EXPERIMENTAL:
        return VLC_BACKEND_AVAILABLE, VLC_BACKEND_ERROR
    return True, ''


def normalize_playback_backend_name(name: str | None) -> str:
    """Normalize backend identifier text."""
    value = (name or '').strip().lower()
    if value in PLAYBACK_BACKEND_CHOICES:
        return value
    return PLAYBACK_BACKEND_QT_HYBRID


def get_configured_playback_backend() -> str:
    """Return configured backend name from settings."""
    configured = settings.value(
        'video_playback_backend',
        defaultValue=DEFAULT_SETTINGS.get('video_playback_backend', PLAYBACK_BACKEND_QT_HYBRID),
        type=str,
    )
    return normalize_playback_backend_name(configured)


def resolve_runtime_playback_backend(configured_backend: str | None = None) -> str:
    """Resolve configured backend to a currently supported runtime backend."""
    selected = normalize_playback_backend_name(
        configured_backend if configured_backend is not None else get_configured_playback_backend()
    )
    if (
        selected == PLAYBACK_BACKEND_MPV_EXPERIMENTAL
        and load_playback_backend(selected) is not None
    ):
        return PLAYBACK_BACKEND_MPV_EXPERIMENTAL
    if (
        selected == PLAYBACK_BACKEND_VLC_EXPERIMENTAL
        and load_playback_backend(selected) is not None
    ):
        return PLAYBACK_BACKEND_VLC_EXPERIMENTAL
    if selected in RUNTIME_SUPPORTED_PLAYBACK_BACKENDS:
        return selected
    return PLAYBACK_BACKEND_QT_HYBRID
