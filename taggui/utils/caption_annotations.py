"""Opt-in caption-entry classifications stored in TagGUI metadata sidecars."""

from __future__ import annotations

import json
from pathlib import Path

from utils.sidecar import (
    is_taggui_metadata_dict,
    preferred_taggui_sidecar_read_path,
    taggui_sidecar_path,
)

CAPTION_WORKSPACE_KEY = "caption_workspace"


def normalize_caption_entries(raw_entries) -> list[dict]:
    entries: list[dict] = []
    if not isinstance(raw_entries, list):
        return entries
    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "").strip()
        if not text:
            continue
        entries.append({
            "text": text,
            "needs_review": bool(raw.get("needs_review", False)),
            "excluded": bool(raw.get("excluded", False)),
        })
    return entries


def caption_attention_counts(entries: list[dict]) -> tuple[int, int]:
    normalized = normalize_caption_entries(entries)
    return (
        sum(bool(entry["needs_review"]) for entry in normalized),
        sum(bool(entry["excluded"]) for entry in normalized),
    )


def included_caption_tags(entries: list[dict]) -> list[str]:
    return [
        entry["text"]
        for entry in normalize_caption_entries(entries)
        if not entry["excluded"]
    ]


def load_caption_workspace(media_path: Path) -> list[dict] | None:
    sidecar_path = preferred_taggui_sidecar_read_path(Path(media_path))
    if sidecar_path is None:
        return None
    try:
        with sidecar_path.open(encoding="utf-8") as source:
            payload = json.load(source)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not is_taggui_metadata_dict(payload):
        return None
    workspace = payload.get(CAPTION_WORKSPACE_KEY)
    if not isinstance(workspace, dict) or workspace.get("version") != 1:
        return None
    entries = normalize_caption_entries(workspace.get("entries"))
    return entries or None


def save_caption_workspace(media_path: Path, entries: list[dict]) -> tuple[int, int]:
    """Persist classifications, removing the workspace when none remain."""
    media_path = Path(media_path)
    normalized = normalize_caption_entries(entries)
    counts = caption_attention_counts(normalized)
    read_path = preferred_taggui_sidecar_read_path(media_path)
    payload = {"version": 1}
    if read_path is not None:
        try:
            with read_path.open(encoding="utf-8") as source:
                loaded = json.load(source)
            if is_taggui_metadata_dict(loaded):
                payload = loaded
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass

    if any(counts):
        payload[CAPTION_WORKSPACE_KEY] = {
            "version": 1,
            "entries": normalized,
        }
    else:
        payload.pop(CAPTION_WORKSPACE_KEY, None)

    target = taggui_sidecar_path(media_path)
    if len(payload) == 1 and payload.get("version") == 1:
        if read_path is not None and read_path != target:
            target.write_text('{"version": 1}', encoding="utf-8")
        elif target.exists():
            target.unlink()
        return counts

    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return counts
