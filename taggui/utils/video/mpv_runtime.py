"""Runtime helpers for discovering bundled libmpv/mpv DLLs."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_BOOTSTRAPPED = False
_LAST_SEARCH_DIRS: list[str] = []
_LAST_ADDED_DIRS: list[str] = []
_DLL_DIR_HANDLES: list[object] = []


def _unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    unique: list[Path] = []
    for p in paths:
        try:
            key = str(p.resolve())
        except Exception:
            key = str(p)
        key = key.lower() if os.name == 'nt' else key
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    return unique


def _platform_subdirs() -> list[str]:
    if sys.platform.startswith('win'):
        return ['windows-x86_64', 'windows-amd64', 'windows', 'win64', 'win']
    if sys.platform == 'darwin':
        return ['macos-arm64', 'macos-x86_64', 'macos', 'darwin']
    return ['linux-x86_64', 'linux-aarch64', 'linux']


def _repo_root_candidates() -> list[Path]:
    here = Path(__file__).resolve()
    candidates = [
        here.parents[3],  # repo root (taggui/utils/video/mpv_runtime.py)
        here.parents[2],  # taggui/
        Path(sys.executable).resolve().parent,
        Path(sys.executable).resolve().parent / '_taggui',
    ]
    if hasattr(sys, '_MEIPASS'):
        try:
            candidates.append(Path(getattr(sys, '_MEIPASS')))
        except Exception:
            pass
    env_override = os.getenv('TAGGUI_MPV_DIR', '').strip()
    if env_override:
        candidates.insert(0, Path(env_override))
    return _unique_paths(candidates)


def _mpv_filename_markers() -> tuple[str, ...]:
    if sys.platform.startswith('win'):
        return ('mpv-1.dll', 'mpv-2.dll', 'libmpv-2.dll')
    if sys.platform == 'darwin':
        return ('libmpv.dylib',)
    return ('libmpv.so', 'libmpv.so.2')


def _contains_mpv_runtime(directory: Path) -> bool:
    if not directory.exists() or not directory.is_dir():
        return False
    markers = _mpv_filename_markers()
    try:
        names = {p.name.lower() for p in directory.iterdir() if p.is_file()}
    except Exception:
        return False
    return any(marker.lower() in names for marker in markers)


def discover_mpv_runtime_dirs() -> list[str]:
    """Discover candidate directories that contain mpv runtime binaries."""
    search_roots: list[Path] = []
    for base in _repo_root_candidates():
        search_roots.append(base / 'third_party' / 'mpv')
        search_roots.append(base / 'mpv')

    candidates: list[Path] = []
    for root in _unique_paths(search_roots):
        candidates.append(root)
        for subdir in _platform_subdirs():
            candidates.append(root / subdir)

    candidates = _unique_paths(candidates)
    found = [str(path) for path in candidates if _contains_mpv_runtime(path)]
    return found


def _prepend_env_path_var(var_name: str, entries: list[str]) -> list[str]:
    current = os.environ.get(var_name, '')
    current_parts = [p for p in current.split(os.pathsep) if p]
    current_norm = {p.lower() if os.name == 'nt' else p for p in current_parts}
    added: list[str] = []
    for entry in reversed(entries):
        norm = entry.lower() if os.name == 'nt' else entry
        if norm not in current_norm:
            current_parts.insert(0, entry)
            current_norm.add(norm)
            added.append(entry)
    os.environ[var_name] = os.pathsep.join(current_parts)
    return added


def bootstrap_mpv_runtime_search_paths() -> dict[str, list[str]]:
    """Add discovered mpv runtime folders to process library search paths."""
    global _BOOTSTRAPPED, _LAST_SEARCH_DIRS, _LAST_ADDED_DIRS

    if _BOOTSTRAPPED:
        return {
            'searched_dirs': list(_LAST_SEARCH_DIRS),
            'added_dirs': list(_LAST_ADDED_DIRS),
        }

    discovered_dirs = discover_mpv_runtime_dirs()
    added_dirs = _prepend_env_path_var('PATH', discovered_dirs) if discovered_dirs else []

    if sys.platform.startswith('win') and hasattr(os, 'add_dll_directory'):
        for directory in discovered_dirs:
            try:
                handle = os.add_dll_directory(directory)
                _DLL_DIR_HANDLES.append(handle)
            except Exception:
                continue
    elif sys.platform == 'darwin':
        _prepend_env_path_var('DYLD_LIBRARY_PATH', discovered_dirs)
    else:
        _prepend_env_path_var('LD_LIBRARY_PATH', discovered_dirs)

    _LAST_SEARCH_DIRS = discovered_dirs
    _LAST_ADDED_DIRS = added_dirs
    _BOOTSTRAPPED = True
    return {
        'searched_dirs': list(_LAST_SEARCH_DIRS),
        'added_dirs': list(_LAST_ADDED_DIRS),
    }
