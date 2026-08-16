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


def merge_caption_entries_with_disk_tags(
    entries: list[dict],
    disk_tags: list[str],
) -> list[dict]:
    """Merge the current ``.txt`` tags into a classified workspace.

    Excluded entries are intentionally absent from the ``.txt`` projection.
    When all previous entries are excluded, newly generated tags therefore
    have no existing included anchor. Put those new tags first so an
    ``exclude after first`` captioning run keeps the new caption instead of
    accidentally promoting an older excluded entry.
    """
    normalized_entries = normalize_caption_entries(entries)
    normalized_tags = [
        str(tag).strip()
        for tag in (disk_tags or [])
        if str(tag).strip()
    ]
    if (
        normalized_tags
        and normalized_entries
        and all(entry["excluded"] for entry in normalized_entries)
    ):
        return normalize_caption_entries([
            *[
                {"text": tag, "needs_review": False, "excluded": False}
                for tag in normalized_tags
            ],
            *normalized_entries,
        ])

    pools: dict[str, list[dict]] = {}
    for entry in normalized_entries:
        if not entry["excluded"]:
            pools.setdefault(entry["text"], []).append(entry)
    merged_entries: list[dict] = []
    for tag in normalized_tags:
        candidates = pools.get(tag) or []
        merged_entries.append(candidates.pop(0) if candidates else {
            "text": tag,
            "needs_review": False,
            "excluded": False,
        })

    # Reinsert excluded entries around their original included neighbours.
    # This keeps a newly inserted tag from displacing an older excluded entry
    # ahead of the included tag it originally followed.
    def index_by_identity(target) -> int:
        for index, candidate in enumerate(merged_entries):
            if candidate is target:
                return index
        return -1

    segments: list[tuple[dict | None, dict | None, list[dict]]] = []
    previous_included = None
    pending_excluded: list[dict] = []
    for entry in normalized_entries:
        if entry["excluded"]:
            pending_excluded.append(entry)
            continue
        if pending_excluded:
            segments.append((previous_included, entry, pending_excluded))
            pending_excluded = []
        previous_included = entry
    if pending_excluded:
        segments.append((previous_included, None, pending_excluded))

    for previous_included, next_included, excluded_segment in segments:
        next_index = index_by_identity(next_included) if next_included else -1
        previous_index = (
            index_by_identity(previous_included)
            if previous_included else -1
        )
        if next_index >= 0:
            insert_at = next_index
        elif previous_index >= 0:
            insert_at = previous_index + 1
        else:
            insert_at = len(merged_entries)
        merged_entries[insert_at:insert_at] = excluded_segment
    return normalize_caption_entries(merged_entries)


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
