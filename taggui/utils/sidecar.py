"""Helpers for TagGUI-owned metadata sidecars and related file operations."""

from __future__ import annotations

import shutil
import json
from pathlib import Path

TAGGUI_SIDECAR_SUFFIX = ".taggui.json"
LEGACY_JSON_SIDECAR_SUFFIX = ".json"

_JSON_OBJECT = object()
_TAGGUI_METADATA_FIELDS = frozenset({
    'crop', 'markings', 'rating', 'love', 'bomb', 'reaction_updated_at',
    'review_rank', 'review_flags', 'review_updated_at', 'caption_workspace',
    'loop_start_frame', 'loop_end_frame', 'viewer_loop_markers',
    'floating_last_loop_start_frame', 'floating_last_loop_end_frame',
})


def taggui_sidecar_path(media_path: Path) -> Path:
    """Return TagGUI's owned metadata sidecar path for a media file."""
    return Path(media_path).with_suffix(TAGGUI_SIDECAR_SUFFIX)


def legacy_json_sidecar_path(media_path: Path) -> Path:
    """Return the legacy sibling JSON path used before TagGUI had its own suffix."""
    return Path(media_path).with_suffix(LEGACY_JSON_SIDECAR_SUFFIX)


def sidecar_backup_path(sidecar_path: Path) -> Path:
    """Return the backup path for a sidecar file."""
    return Path(sidecar_path).with_suffix(Path(sidecar_path).suffix + ".backup")


def json_sidecar_paths_for_media(media_path: Path) -> tuple[Path, ...]:
    """Return the JSON sidecar paths associated with a media file."""
    candidates = (
        taggui_sidecar_path(media_path),
        legacy_json_sidecar_path(media_path),
    )
    unique_paths: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique_paths.append(candidate)
    return tuple(unique_paths)


def existing_json_sidecar_paths_for_media(media_path: Path) -> tuple[Path, ...]:
    """Return existing JSON sidecars for a media file in preferred order."""
    return tuple(path for path in json_sidecar_paths_for_media(media_path) if path.exists())


def preferred_taggui_sidecar_read_path(media_path: Path) -> Path | None:
    """Return TagGUI's preferred metadata read path for a media file."""
    for path in json_sidecar_paths_for_media(media_path):
        try:
            if path.exists():
                return path
        except OSError:
            continue
    return None


def is_taggui_metadata_dict(payload) -> bool:
    """Return whether a decoded JSON object matches TagGUI's metadata schema."""
    return (isinstance(payload, dict) and payload.get("version") == 1
            and not _is_foreign_workflow_structure(payload))


def _is_foreign_workflow_structure(payload: dict) -> bool:
    # ComfyUI's v1 workflow schema shares our version number but has root
    # nodes/state. Preserve legacy mixed documents with actual TagGUI fields.
    state = payload.get('state')
    return (isinstance(payload.get('nodes'), list)
            and (isinstance(state, dict) or state is _JSON_OBJECT)
            and not _TAGGUI_METADATA_FIELDS.intersection(payload))


def read_taggui_metadata(path: Path) -> dict | None:
    """Read metadata without retaining foreign workflow object graphs.

    Legacy siblings share .json with generators. A first standard-JSON pass
    replaces decoded objects with one placeholder, discarding their children.
    The last reduced object is the root when the parse returns the placeholder.
    Only compatible metadata needs a second decode; dedicated sidecars take
    the direct path. Key ordering, duplicate keys and escaping remain JSON's.
    """
    text = path.read_text(encoding='UTF-8')
    if not path.name.endswith(TAGGUI_SIDECAR_SUFFIX):
        last_object = None
        def reduce_object(obj):
            nonlocal last_object
            last_object = obj
            return _JSON_OBJECT
        root = json.loads(text, object_hook=reduce_object)
        if root is not _JSON_OBJECT or not is_taggui_metadata_dict(last_object):
            return None
    payload = json.loads(text)
    return payload if is_taggui_metadata_dict(payload) else None


def copy_existing_json_sidecars(source_media_path: Path, target_media_path: Path):
    """Copy all existing JSON sidecars from one media path to another."""
    for source_sidecar in existing_json_sidecar_paths_for_media(source_media_path):
        target_sidecar = (
            taggui_sidecar_path(target_media_path)
            if source_sidecar == taggui_sidecar_path(source_media_path)
            else legacy_json_sidecar_path(target_media_path)
        )
        shutil.copy2(str(source_sidecar), str(target_sidecar))


def restore_json_sidecars(source_media_path: Path, target_media_path: Path):
    """Restore JSON sidecars from one media path to another, deleting missing targets."""
    for source_sidecar, target_sidecar in zip(
        json_sidecar_paths_for_media(source_media_path),
        json_sidecar_paths_for_media(target_media_path),
    ):
        if source_sidecar.exists():
            shutil.copy2(str(source_sidecar), str(target_sidecar))
        elif target_sidecar.exists():
            target_sidecar.unlink()
