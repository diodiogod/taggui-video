"""Profiles and ordered pending-tag state for Quick Tag Review."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any
from uuid import uuid4


QUICK_TAG_SCHEMA_VERSION = 1
QUICK_TAG_SESSION_SCHEMA_VERSION = 1
QUICK_TAG_RESERVED_KEYS = {
    "tab",
    "shift+tab",
    "backspace",
    "space",
    "enter",
    "esc",
    "escape",
    "f11",
    "left",
    "right",
    "up",
    "down",
    "pgup",
    "pgdown",
    "home",
    "end",
    "ctrl+z",
    "ctrl+y",
    "ctrl+shift+z",
}


class QuickTagValidationError(ValueError):
    """Raised when a Quick Tag profile is malformed."""


def new_quick_tag_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def normalize_quick_tag_key(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parts = [part.strip() for part in raw.split("+") if part.strip()]
    if not parts:
        return ""
    names = {
        "control": "Ctrl",
        "ctrl": "Ctrl",
        "alt": "Alt",
        "shift": "Shift",
        "meta": "Meta",
        "cmd": "Meta",
        "command": "Meta",
        "escape": "Esc",
    }
    modifiers = []
    for part in parts[:-1]:
        normalized = names.get(part.casefold(), part)
        if normalized not in modifiers:
            modifiers.append(normalized)
    key = names.get(parts[-1].casefold(), parts[-1])
    if len(key) == 1 and key.isalpha():
        key = key.upper()
    order = ("Ctrl", "Alt", "Shift", "Meta")
    return "+".join([*(item for item in order if item in modifiers),
                     *(item for item in modifiers if item not in order), key])


def _validate_tag(value: str, field_name: str) -> str:
    tag = " ".join(str(value or "").strip().split())
    if not tag:
        raise QuickTagValidationError(f"{field_name} cannot be empty.")
    if any(character in tag for character in "\r\n\0"):
        raise QuickTagValidationError(f"{field_name} contains an invalid character.")
    return tag


def merge_ordered_tags(existing: list[str], additions: list[str]) -> list[str]:
    """Append new tags once while preserving the exact existing order."""
    merged = [str(tag).strip() for tag in existing if str(tag).strip()]
    for tag in additions:
        normalized = " ".join(str(tag or "").strip().split())
        if normalized and normalized not in merged:
            merged.append(normalized)
    return merged


def edit_ordered_tag(
    tags: list[str],
    index: int,
    value: str,
    *,
    insert: bool = False,
) -> list[str]:
    """Return an ordered tag list after an inline replace or insertion."""
    normalized = _validate_tag(value, "Tag")
    updated = list(tags)
    if insert:
        updated.insert(max(0, min(int(index), len(updated))), normalized)
    elif 0 <= int(index) < len(updated):
        updated[int(index)] = normalized
    else:
        raise QuickTagValidationError("Tag edit index is out of range.")
    return updated


@dataclass
class QuickTagMapping:
    tag: str
    key: str
    color: str = "#62E7D8"
    enabled: bool = True
    id: str = field(default_factory=lambda: new_quick_tag_id("tag"))

    def validate(self) -> None:
        self.tag = _validate_tag(self.tag, "Tag")
        self.key = normalize_quick_tag_key(self.key)
        if not self.key:
            raise QuickTagValidationError(f"{self.tag!r} needs a keyboard key.")
        if not self.id:
            raise QuickTagValidationError("Every Quick Tag mapping needs an ID.")
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(self.color or "")):
            raise QuickTagValidationError(f"{self.tag!r} has an invalid color.")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "id": self.id,
            "tag": self.tag,
            "key": self.key,
            "color": self.color,
            "enabled": bool(self.enabled),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "QuickTagMapping":
        if not isinstance(payload, dict):
            raise QuickTagValidationError("Quick Tag mappings must be objects.")
        mapping = cls(
            id=str(payload.get("id") or new_quick_tag_id("tag")),
            tag=str(payload.get("tag") or ""),
            key=str(payload.get("key") or ""),
            color=str(payload.get("color") or "#62E7D8"),
            enabled=bool(payload.get("enabled", True)),
        )
        mapping.validate()
        return mapping


@dataclass
class QuickTagProfile:
    name: str
    mappings: list[QuickTagMapping] = field(default_factory=list)
    source_scope: str = "current_folder"
    include_subfolders: bool = False
    include_videos: bool = False
    start_fullscreen: bool = True
    refine_key: str = "Tab"
    insert_key: str = "Shift+Tab"
    remove_key: str = "Backspace"
    advance_key: str = "Space"
    template_key: str = ""
    id: str = field(default_factory=lambda: new_quick_tag_id("profile"))
    schema_version: int = QUICK_TAG_SCHEMA_VERSION

    def enabled_mappings(self) -> list[QuickTagMapping]:
        return [mapping for mapping in self.mappings if mapping.enabled]

    def validate(self) -> None:
        self.name = str(self.name or "").strip()
        if not self.name:
            raise QuickTagValidationError("Profile name cannot be empty.")
        if not self.id:
            raise QuickTagValidationError("Quick Tag profiles need an ID.")
        self.template_key = str(self.template_key or "").strip()
        if self.schema_version != QUICK_TAG_SCHEMA_VERSION:
            raise QuickTagValidationError(
                f"Unsupported Quick Tag schema version: {self.schema_version}"
            )
        if self.source_scope not in {"current_folder", "selected", "filtered", "all_loaded"}:
            raise QuickTagValidationError(f"Unsupported source scope: {self.source_scope!r}")
        control_keys = {
            "refine_key": normalize_quick_tag_key(self.refine_key),
            "insert_key": normalize_quick_tag_key(self.insert_key),
            "remove_key": normalize_quick_tag_key(self.remove_key),
            "advance_key": normalize_quick_tag_key(self.advance_key),
        }
        if len(set(control_keys.values())) != len(control_keys):
            raise QuickTagValidationError("Quick Tag control keys must be different.")
        for field_name, key in control_keys.items():
            if key.casefold() not in QUICK_TAG_RESERVED_KEYS:
                raise QuickTagValidationError(
                    f"{field_name.replace('_', ' ').title()} must use a reserved control key."
                )
            setattr(self, field_name, key)
        seen_ids: set[str] = set()
        seen_keys: set[str] = set()
        for mapping in self.mappings:
            mapping.validate()
            if mapping.id in seen_ids:
                raise QuickTagValidationError(f"Duplicate Quick Tag mapping ID: {mapping.id}")
            seen_ids.add(mapping.id)
            if not mapping.enabled:
                continue
            normalized_key = mapping.key.casefold()
            if normalized_key in QUICK_TAG_RESERVED_KEYS:
                raise QuickTagValidationError(f"Key {mapping.key!r} is reserved for Quick Tag controls.")
            if normalized_key in seen_keys:
                raise QuickTagValidationError(f"Key {mapping.key!r} is assigned more than once.")
            seen_keys.add(normalized_key)

    def mapping_for_key(self, key: str) -> QuickTagMapping | None:
        normalized = normalize_quick_tag_key(key).casefold()
        return next(
            (mapping for mapping in self.enabled_mappings() if mapping.key.casefold() == normalized),
            None,
        )

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "name": self.name,
            "mappings": [mapping.to_dict() for mapping in self.mappings],
            "source_scope": self.source_scope,
            "include_subfolders": bool(self.include_subfolders),
            "include_videos": bool(self.include_videos),
            "start_fullscreen": bool(self.start_fullscreen),
            "refine_key": self.refine_key,
            "insert_key": self.insert_key,
            "remove_key": self.remove_key,
            "advance_key": self.advance_key,
            "template_key": self.template_key,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "QuickTagProfile":
        if not isinstance(payload, dict):
            raise QuickTagValidationError("Quick Tag profiles must be objects.")
        profile = cls(
            schema_version=int(payload.get("schema_version", QUICK_TAG_SCHEMA_VERSION)),
            id=str(payload.get("id") or new_quick_tag_id("profile")),
            name=str(payload.get("name") or ""),
            mappings=[QuickTagMapping.from_dict(item) for item in payload.get("mappings", [])],
            source_scope=str(payload.get("source_scope") or "current_folder"),
            include_subfolders=bool(payload.get("include_subfolders", False)),
            include_videos=bool(payload.get("include_videos", False)),
            start_fullscreen=bool(payload.get("start_fullscreen", True)),
            refine_key=str(payload.get("refine_key") or "Tab"),
            insert_key=str(payload.get("insert_key") or "Shift+Tab"),
            remove_key=str(payload.get("remove_key") or "Backspace"),
            advance_key=str(payload.get("advance_key") or "Space"),
            template_key=str(payload.get("template_key") or ""),
        )
        profile.validate()
        return profile


def default_quick_tag_profile(name: str = "My Quick Tags") -> QuickTagProfile:
    profile = QuickTagProfile(name=name)
    profile.validate()
    return profile


def builtin_quick_tag_profiles() -> tuple[QuickTagProfile, ...]:
    """Return fresh templates shipped with Quick Tag Review.

    Callers should clone a template before adding it to the user's profile
    store so template IDs never collide with saved profiles.
    """
    general = QuickTagProfile(
        name="General image labeling",
        template_key="general_image_labeling",
        mappings=[
            QuickTagMapping(tag="person", key="P", color="#62E7D8"),
            QuickTagMapping(tag="animal", key="A", color="#F2C96D"),
            QuickTagMapping(tag="object", key="O", color="#7AA2FF"),
            QuickTagMapping(tag="landscape", key="L", color="#72D49A"),
            QuickTagMapping(tag="indoor", key="I", color="#B98CFF"),
            QuickTagMapping(tag="outdoor", key="E", color="#62B6CB"),
            QuickTagMapping(tag="close-up", key="C", color="#E87979"),
            QuickTagMapping(tag="full body", key="F", color="#C5D86D"),
        ],
    )
    portrait = QuickTagProfile(
        name="Portrait / Character",
        template_key="portrait_character",
        mappings=[
            QuickTagMapping(tag="face", key="F", color="#62E7D8"),
            QuickTagMapping(tag="hair", key="H", color="#B98CFF"),
            QuickTagMapping(tag="eyes", key="E", color="#7AA2FF"),
            QuickTagMapping(tag="pose", key="P", color="#F2C96D"),
            QuickTagMapping(tag="clothing", key="C", color="#72D49A"),
            QuickTagMapping(tag="accessory", key="A", color="#D49AEE"),
            QuickTagMapping(tag="background", key="B", color="#62B6CB"),
        ],
    )
    clothing = QuickTagProfile(
        name="Clothing / Body parts",
        template_key="clothing_body_parts",
        mappings=[
            QuickTagMapping(tag="hat", key="H", color="#F2C96D"),
            QuickTagMapping(tag="shirt", key="T", color="#62E7D8"),
            QuickTagMapping(tag="jacket", key="J", color="#7AA2FF"),
            QuickTagMapping(tag="dress", key="D", color="#E87979"),
            QuickTagMapping(tag="pants", key="P", color="#B98CFF"),
            QuickTagMapping(tag="skirt", key="K", color="#D49AEE"),
            QuickTagMapping(tag="shoes", key="S", color="#72D49A"),
            QuickTagMapping(tag="left arm", key="L", color="#62B6CB"),
            QuickTagMapping(tag="right arm", key="R", color="#C5D86D"),
        ],
    )
    quality = QuickTagProfile(
        name="Quality review",
        template_key="quality_review",
        mappings=[
            QuickTagMapping(tag="high-quality", key="H", color="#72D49A"),
            QuickTagMapping(tag="medium-quality", key="M", color="#F2C96D"),
            QuickTagMapping(tag="low-quality", key="L", color="#E87979"),
            QuickTagMapping(tag="blurry", key="B", color="#B98CFF"),
            QuickTagMapping(tag="cropped", key="C", color="#7AA2FF"),
            QuickTagMapping(tag="duplicate", key="D", color="#62B6CB"),
            QuickTagMapping(tag="needs-review", key="N", color="#D49AEE"),
        ],
    )
    composition = QuickTagProfile(
        name="Composition / Shot sizes",
        template_key="composition_shot_sizes",
        mappings=[
            QuickTagMapping(tag="extreme close-up", key="E", color="#E87979"),
            QuickTagMapping(tag="close-up", key="C", color="#F2C96D"),
            QuickTagMapping(tag="bust shot", key="B", color="#62E7D8"),
            QuickTagMapping(tag="medium shot", key="M", color="#7AA2FF"),
            QuickTagMapping(tag="cowboy shot", key="K", color="#B98CFF"),
            QuickTagMapping(tag="full body", key="F", color="#72D49A"),
            QuickTagMapping(tag="wide shot", key="W", color="#62B6CB"),
            QuickTagMapping(tag="extreme wide shot", key="X", color="#C5D86D"),
            QuickTagMapping(tag="over-the-shoulder", key="O", color="#D49AEE"),
        ],
    )
    profiles = (general, portrait, clothing, quality, composition)
    for profile in profiles:
        profile.validate()
    return profiles


def clone_quick_tag_profile(profile: QuickTagProfile, *, name: str | None = None) -> QuickTagProfile:
    """Clone a profile with fresh IDs, suitable for a new saved profile."""
    clone = QuickTagProfile(
        name=name or profile.name,
        mappings=[
            QuickTagMapping(
                tag=mapping.tag,
                key=mapping.key,
                color=mapping.color,
                enabled=mapping.enabled,
            )
            for mapping in profile.mappings
        ],
        source_scope=profile.source_scope,
        include_subfolders=profile.include_subfolders,
        include_videos=profile.include_videos,
        start_fullscreen=profile.start_fullscreen,
        refine_key=profile.refine_key,
        insert_key=profile.insert_key,
        remove_key=profile.remove_key,
        advance_key=profile.advance_key,
        template_key=profile.template_key,
    )
    clone.validate()
    return clone


def reconcile_quick_tag_profiles(
    profiles: list[QuickTagProfile],
    templates: tuple[QuickTagProfile, ...],
) -> tuple[list[QuickTagProfile], bool]:
    """Migrate old preset copies without touching genuinely edited profiles."""
    template_signatures = {
        _quick_tag_profile_signature(template): template for template in templates
    }
    available_template_keys = {
        template.template_key
        for profile in profiles
        for template in [template_signatures.get(_quick_tag_profile_signature(profile))]
        if template is not None
    }
    claimed_templates: set[str] = set()
    reconciled: list[QuickTagProfile] = []
    changed = False
    for profile in profiles:
        signature_template = template_signatures.get(_quick_tag_profile_signature(profile))
        stale_builtin_name = profile.name.endswith(" (built-in)")
        stale_builtin_template = next(
            (template for template in templates if profile.name[:-10].rstrip() == template.name),
            None,
        )
        stale_custom_template = next(
            (template for template in templates if profile.name == f"{template.name} (custom)"),
            None,
        )
        if (
            stale_builtin_name
            and signature_template is None
            and stale_builtin_template is not None
            and stale_builtin_template.template_key in available_template_keys
        ):
            # Old builds could save a partially edited copy under the
            # built-in label. If the real template copy is also present, it
            # is only stale UI state and should not remain as a duplicate.
            changed = True
            continue
        if (
            stale_custom_template is not None
            and signature_template is None
            and not profile.template_key
            and stale_custom_template.template_key in available_template_keys
        ):
            changed = True
            continue
        if signature_template is not None:
            template_key = signature_template.template_key
            if template_key in claimed_templates:
                # Exact duplicate created by the old preset selector.
                changed = True
                continue
            if profile.template_key != template_key or profile.name != f"{signature_template.name} (custom)":
                profile.template_key = template_key
                profile.name = f"{signature_template.name} (custom)"
                changed = True
            claimed_templates.add(template_key)
        elif profile.template_key:
            # Editing a template copy turns it into a normal user profile.
            profile.template_key = ""
            changed = True
        if profile.name.endswith(" (built-in)"):
            profile.name = profile.name[:-10].rstrip() + " (custom)"
            changed = True
        reconciled.append(profile)
    return reconciled, changed


def _quick_tag_profile_signature(profile: QuickTagProfile) -> tuple:
    return tuple(
        (
            mapping.tag.casefold(),
            mapping.key.casefold(),
            mapping.color.casefold(),
            bool(mapping.enabled),
        )
        for mapping in profile.mappings
    )


class QuickTagProfileStore:
    """Atomic persistence for named Quick Tag profiles."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else self.default_path()

    @staticmethod
    def default_path() -> Path:
        app_data = os.getenv("APPDATA")
        base = Path(app_data) / "taggui" if app_data else Path.home() / ".config" / "taggui"
        return base / "quick_tag_profiles.json"

    def load(self) -> list[QuickTagProfile]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("schema_version") != QUICK_TAG_SCHEMA_VERSION:
                raise ValueError("unsupported schema")
            profiles = [QuickTagProfile.from_dict(item) for item in payload.get("profiles", [])]
            seen = set()
            for profile in profiles:
                if profile.id in seen:
                    raise QuickTagValidationError(f"Duplicate profile ID: {profile.id}")
                seen.add(profile.id)
            return profiles
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise QuickTagValidationError(f"Cannot read Quick Tag profiles from {self.path}: {exc}") from exc

    def save(self, profiles: list[QuickTagProfile]) -> None:
        seen = set()
        for profile in profiles:
            profile.validate()
            if profile.id in seen:
                raise QuickTagValidationError(f"Duplicate profile ID: {profile.id}")
            seen.add(profile.id)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent,
                prefix=f".{self.path.name}.", suffix=".tmp", delete=False,
            ) as temporary_file:
                json.dump({"schema_version": QUICK_TAG_SCHEMA_VERSION,
                           "profiles": [profile.to_dict() for profile in profiles]},
                          temporary_file, ensure_ascii=False, indent=2)
                temporary_file.write("\n")
                temporary_path = Path(temporary_file.name)
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                try:
                    temporary_path.unlink()
                except OSError:
                    pass


class QuickTagSessionStore:
    """Atomic persistence for completed Quick Tag image decisions."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else QuickTagProfileStore.default_path().with_name("quick_tag_sessions.json")

    def load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict) or payload.get("schema_version") != QUICK_TAG_SESSION_SCHEMA_VERSION:
            return {}
        return {str(key): value for key, value in payload.get("sessions", {}).items() if isinstance(value, dict)}

    def get(self, key: str) -> dict[str, Any] | None:
        value = self.load().get(str(key))
        return dict(value) if value is not None else None

    def put(self, key: str, state: dict[str, Any]) -> None:
        sessions = self.load()
        sessions[str(key)] = dict(state)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=f".{self.path.name}.", suffix=".tmp", delete=False) as temporary_file:
                json.dump({"schema_version": QUICK_TAG_SESSION_SCHEMA_VERSION, "sessions": sessions},
                          temporary_file, ensure_ascii=False, indent=2)
                temporary_file.write("\n")
                temporary_path = Path(temporary_file.name)
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                try:
                    temporary_path.unlink()
                except OSError:
                    pass

    def remove(self, key: str) -> None:
        sessions = self.load()
        if str(key) not in sessions:
            return
        sessions.pop(str(key), None)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=f".{self.path.name}.", suffix=".tmp", delete=False) as temporary_file:
                json.dump({"schema_version": QUICK_TAG_SESSION_SCHEMA_VERSION, "sessions": sessions},
                          temporary_file, ensure_ascii=False, indent=2)
                temporary_file.write("\n")
                temporary_path = Path(temporary_file.name)
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                try:
                    temporary_path.unlink()
                except OSError:
                    pass
