"""Versioned Quick Sort profile definitions and persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any
from uuid import uuid4


QUICK_SORT_SCHEMA_VERSION = 1
QUICK_SORT_SESSION_SCHEMA_VERSION = 1
QUICK_SORT_SOURCE_SCOPES = {
    "current_folder",
    "selected",
    "filtered",
    "all_loaded",
}
QUICK_SORT_OPERATION_MODES = {"move", "copy"}
QUICK_SORT_COLLISION_POLICIES = {"append", "skip", "ask"}
QUICK_SORT_HIERARCHY_ORDERS = {"destination_first", "qualifier_first"}
QUICK_SORT_MISSING_QUALIFIER_POLICIES = {"require", "unclassified"}
QUICK_SORT_RESERVED_KEYS = {
    "esc",
    "backspace",
    "f11",
    "space",
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


class QuickSortValidationError(ValueError):
    """Raised when a Quick Sort profile is malformed or unsafe."""


def new_quick_sort_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def normalize_key_sequence(value: str) -> str:
    """Return a stable, display-friendly shortcut string."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    plus_key = raw == "+" or raw.endswith("++")
    split_source = raw[:-1] if plus_key else raw
    parts = [part.strip() for part in split_source.split("+") if part.strip()]
    if plus_key:
        modifier_parts = parts
        key = "+"
    else:
        if not parts:
            return ""
        modifier_parts = parts[:-1]
        key = parts[-1]
    modifier_names = {
        "ctrl": "Ctrl",
        "control": "Ctrl",
        "alt": "Alt",
        "shift": "Shift",
        "meta": "Meta",
        "cmd": "Meta",
        "command": "Meta",
    }
    modifiers: list[str] = []
    for part in modifier_parts:
        modifier = modifier_names.get(part.casefold(), part)
        if modifier not in modifiers:
            modifiers.append(modifier)
    canonical_order = ("Ctrl", "Alt", "Shift", "Meta")
    normalized = [modifier for modifier in canonical_order if modifier in modifiers]
    normalized.extend(
        modifier for modifier in modifiers if modifier not in canonical_order
    )
    if len(key) == 1 and key.isalpha():
        key = key.upper()
    elif key.casefold().startswith("key_"):
        key = key[4:]
    normalized.append(key)
    return "+".join(normalized)


def _validate_relative_folder(value: str, *, field_name: str) -> None:
    text = str(value or "").strip()
    if not text:
        raise QuickSortValidationError(f"{field_name} cannot be empty.")
    folder = Path(text)
    if folder.is_absolute():
        raise QuickSortValidationError(
            f"{field_name} must be relative to the profile's base destination."
        )
    if any(part in {"", ".", ".."} for part in folder.parts):
        raise QuickSortValidationError(
            f"{field_name} cannot contain empty, current, or parent path segments."
        )
    reserved_names = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }
    for part in folder.parts:
        if any(character in part for character in '<>:"|?*\0'):
            raise QuickSortValidationError(
                f"{field_name} contains characters that are invalid in folder names."
            )
        if part.endswith((" ", ".")):
            raise QuickSortValidationError(
                f"{field_name} cannot contain a folder ending in a space or period."
            )
        base_name = part.split(".", 1)[0].upper()
        if base_name in reserved_names:
            raise QuickSortValidationError(
                f"{field_name} uses a reserved folder name: {part!r}."
            )


@dataclass
class QuickSortMapping:
    name: str
    key: str
    folder: str = ""
    color: str = "#62E7D8"
    enabled: bool = True
    id: str = field(default_factory=lambda: new_quick_sort_id("route"))

    def validate(self, *, kind: str = "mapping") -> None:
        self.name = str(self.name or "").strip()
        self.key = normalize_key_sequence(self.key)
        self.folder = str(self.folder or self.name).strip()
        self.color = str(self.color or "#62E7D8").strip()
        if not self.id:
            raise QuickSortValidationError(f"Every {kind} requires a stable ID.")
        if not self.name:
            raise QuickSortValidationError(f"{kind.title()} name cannot be empty.")
        if not self.key:
            raise QuickSortValidationError(f"{self.name!r} needs a keyboard key.")
        _validate_relative_folder(self.folder, field_name=f"Folder for {self.name!r}")
        color_pattern = r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3}(?:[0-9a-fA-F]{2})?)?"
        if re.fullmatch(color_pattern, self.color) is None:
            raise QuickSortValidationError(
                f"{self.name!r} has an invalid accent color."
            )

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "id": self.id,
            "name": self.name,
            "key": self.key,
            "folder": self.folder,
            "color": self.color,
            "enabled": bool(self.enabled),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "QuickSortMapping":
        if not isinstance(payload, dict):
            raise QuickSortValidationError("Quick Sort mappings must be JSON objects.")
        mapping = cls(
            id=str(payload.get("id") or new_quick_sort_id("route")),
            name=str(payload.get("name") or ""),
            key=str(payload.get("key") or ""),
            folder=str(payload.get("folder") or ""),
            color=str(payload.get("color") or "#62E7D8"),
            enabled=bool(payload.get("enabled", True)),
        )
        mapping.validate()
        return mapping


@dataclass
class QuickSortProfile:
    name: str
    destinations: list[QuickSortMapping] = field(default_factory=list)
    standard_key_destinations: bool = True
    qualifiers: list[QuickSortMapping] = field(default_factory=list)
    qualifier_enabled: bool = False
    qualifier_name: str = "Quality"
    hierarchy_order: str = "destination_first"
    missing_qualifier: str = "require"
    unclassified_folder: str = "Unclassified"
    base_destination: str = ""
    source_scope: str = "current_folder"
    include_subfolders: bool = False
    include_videos: bool = False
    operation_mode: str = "move"
    collision_policy: str = "append"
    include_sidecars: bool = True
    start_fullscreen: bool = True
    id: str = field(default_factory=lambda: new_quick_sort_id("profile"))
    schema_version: int = QUICK_SORT_SCHEMA_VERSION

    def enabled_destinations(self) -> list[QuickSortMapping]:
        return [mapping for mapping in self.destinations if mapping.enabled]

    def enabled_qualifiers(self) -> list[QuickSortMapping]:
        if not self.qualifier_enabled:
            return []
        return [mapping for mapping in self.qualifiers if mapping.enabled]

    @staticmethod
    def _validate_mapping_group(
        mappings: list[QuickSortMapping],
        *,
        label: str,
        require_enabled: bool,
    ) -> None:
        seen_ids: set[str] = set()
        seen_keys: dict[str, str] = {}
        enabled_count = 0
        for mapping in mappings:
            mapping.validate(kind=label)
            if mapping.id in seen_ids:
                raise QuickSortValidationError(
                    f"Duplicate {label} ID: {mapping.id}"
                )
            seen_ids.add(mapping.id)
            if not mapping.enabled:
                continue
            enabled_count += 1
            normalized_key = normalize_key_sequence(mapping.key).casefold()
            if normalized_key in QUICK_SORT_RESERVED_KEYS:
                raise QuickSortValidationError(
                    f"Key {mapping.key!r} is reserved for Quick Sort navigation "
                    "or session controls."
                )
            previous = seen_keys.get(normalized_key)
            if previous is not None:
                raise QuickSortValidationError(
                    f"Key {mapping.key!r} is assigned to both {previous!r} "
                    f"and {mapping.name!r} in the {label} stage."
                )
            seen_keys[normalized_key] = mapping.name
        if require_enabled and enabled_count == 0:
            raise QuickSortValidationError(
                f"At least one enabled {label} is required."
            )

    def validate(self) -> None:
        self.name = str(self.name or "").strip()
        self.qualifier_name = str(self.qualifier_name or "Quality").strip()
        self.base_destination = str(self.base_destination or "").strip()
        self.unclassified_folder = str(
            self.unclassified_folder or "Unclassified"
        ).strip()
        if self.schema_version != QUICK_SORT_SCHEMA_VERSION:
            raise QuickSortValidationError(
                f"Unsupported Quick Sort schema version: {self.schema_version}"
            )
        if not self.id:
            raise QuickSortValidationError("Quick Sort profiles require a stable ID.")
        if not self.name:
            raise QuickSortValidationError("Profile name cannot be empty.")
        if self.source_scope not in QUICK_SORT_SOURCE_SCOPES:
            raise QuickSortValidationError(
                f"Unsupported Quick Sort source scope: {self.source_scope!r}"
            )
        if self.operation_mode not in QUICK_SORT_OPERATION_MODES:
            raise QuickSortValidationError(
                f"Unsupported file operation: {self.operation_mode!r}"
            )
        if self.collision_policy not in QUICK_SORT_COLLISION_POLICIES:
            raise QuickSortValidationError(
                f"Unsupported collision policy: {self.collision_policy!r}"
            )
        if self.hierarchy_order not in QUICK_SORT_HIERARCHY_ORDERS:
            raise QuickSortValidationError(
                f"Unsupported folder hierarchy: {self.hierarchy_order!r}"
            )
        if self.missing_qualifier not in QUICK_SORT_MISSING_QUALIFIER_POLICIES:
            raise QuickSortValidationError(
                f"Unsupported missing-qualifier behavior: {self.missing_qualifier!r}"
            )
        if self.base_destination:
            base = Path(self.base_destination).expanduser()
            if not base.is_absolute():
                raise QuickSortValidationError(
                    "The base destination must be an absolute folder path."
                )
        self._validate_mapping_group(
            self.destinations,
            label="destination",
            require_enabled=not self.standard_key_destinations,
        )
        self._validate_mapping_group(
            self.qualifiers,
            label="qualifier",
            require_enabled=self.qualifier_enabled,
        )
        if self.qualifier_enabled and self.missing_qualifier == "unclassified":
            _validate_relative_folder(
                self.unclassified_folder,
                field_name="Unclassified folder",
            )
            qualifier_keys = {
                normalize_key_sequence(mapping.key).casefold(): mapping.name
                for mapping in self.enabled_qualifiers()
            }
            for destination in self.enabled_destinations():
                normalized_key = normalize_key_sequence(destination.key).casefold()
                qualifier_name = qualifier_keys.get(normalized_key)
                if qualifier_name is not None:
                    raise QuickSortValidationError(
                        f"Key {destination.key!r} is ambiguous between qualifier "
                        f"{qualifier_name!r} and destination {destination.name!r} while "
                        "Unclassified routing is enabled. Assign different keys or "
                        "require a qualifier."
                    )
            if self.standard_key_destinations:
                ambiguous = next(
                    (
                        mapping
                        for mapping in self.enabled_qualifiers()
                        if len(normalize_key_sequence(mapping.key)) == 1
                        and normalize_key_sequence(mapping.key).isalnum()
                    ),
                    None,
                )
                if ambiguous is not None:
                    raise QuickSortValidationError(
                        f"Qualifier key {ambiguous.key!r} overlaps the automatic "
                        "A-Z / 0-9 destinations while Unclassified routing is enabled. "
                        "Require a qualifier or use a non-alphanumeric qualifier key."
                    )

    def mapping_for_key(
        self,
        key: str,
        *,
        qualifier: bool,
    ) -> QuickSortMapping | None:
        target = normalize_key_sequence(key).casefold()
        mappings = self.qualifiers if qualifier else self.destinations
        explicit = next(
            (
                mapping
                for mapping in mappings
                if normalize_key_sequence(mapping.key).casefold() == target
            ),
            None,
        )
        if explicit is not None:
            return explicit if explicit.enabled else None
        if not qualifier and self.standard_key_destinations:
            normalized = normalize_key_sequence(key)
            if len(normalized) == 1 and normalized.isalnum():
                route = normalized.upper()
                return QuickSortMapping(
                    id=f"standard-{route}",
                    name=route,
                    key=route,
                    folder=route,
                    color="#3B82F6",
                )
        return None

    def route_directory(
        self,
        destination: QuickSortMapping,
        qualifier: QuickSortMapping | None = None,
        *,
        fallback_base: Path | None = None,
    ) -> Path:
        base_text = self.base_destination.strip()
        if base_text:
            base = Path(base_text).expanduser()
        elif fallback_base is not None:
            base = Path(fallback_base)
        else:
            raise QuickSortValidationError("Choose a base destination folder.")
        destination_folder = Path(destination.folder or destination.name)
        qualifier_folder: Path | None = None
        if self.qualifier_enabled:
            if qualifier is not None:
                qualifier_folder = Path(qualifier.folder or qualifier.name)
            elif self.missing_qualifier == "unclassified":
                qualifier_folder = Path(self.unclassified_folder)
            else:
                raise QuickSortValidationError(
                    f"Choose {self.qualifier_name.lower()} before a destination."
                )
        parts = [destination_folder]
        if qualifier_folder is not None:
            parts = (
                [qualifier_folder, destination_folder]
                if self.hierarchy_order == "qualifier_first"
                else [destination_folder, qualifier_folder]
            )
        target = base.joinpath(*parts)
        resolved_base = base.resolve(strict=False)
        resolved_target = target.resolve(strict=False)
        try:
            resolved_target.relative_to(resolved_base)
        except ValueError as exc:
            raise QuickSortValidationError(
                "A Quick Sort route escapes the selected base destination."
            ) from exc
        return resolved_target

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "name": self.name,
            "destinations": [mapping.to_dict() for mapping in self.destinations],
            "standard_key_destinations": bool(self.standard_key_destinations),
            "qualifiers": [mapping.to_dict() for mapping in self.qualifiers],
            "qualifier_enabled": bool(self.qualifier_enabled),
            "qualifier_name": self.qualifier_name,
            "hierarchy_order": self.hierarchy_order,
            "missing_qualifier": self.missing_qualifier,
            "unclassified_folder": self.unclassified_folder,
            "base_destination": self.base_destination,
            "source_scope": self.source_scope,
            "include_subfolders": bool(self.include_subfolders),
            "include_videos": bool(self.include_videos),
            "operation_mode": self.operation_mode,
            "collision_policy": self.collision_policy,
            "include_sidecars": bool(self.include_sidecars),
            "start_fullscreen": bool(self.start_fullscreen),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "QuickSortProfile":
        if not isinstance(payload, dict):
            raise QuickSortValidationError("Quick Sort profiles must be JSON objects.")
        try:
            schema_version = int(
                payload.get("schema_version", QUICK_SORT_SCHEMA_VERSION)
            )
        except (TypeError, ValueError) as exc:
            raise QuickSortValidationError(
                "Quick Sort schema version must be an integer."
            ) from exc
        raw_destinations = payload.get("destinations", [])
        raw_qualifiers = payload.get("qualifiers", [])
        if not isinstance(raw_destinations, list) or not isinstance(raw_qualifiers, list):
            raise QuickSortValidationError(
                "Quick Sort destinations and qualifiers must be lists."
            )
        profile = cls(
            schema_version=schema_version,
            id=str(payload.get("id") or new_quick_sort_id("profile")),
            name=str(payload.get("name") or ""),
            destinations=[
                QuickSortMapping.from_dict(item) for item in raw_destinations
            ],
            standard_key_destinations=bool(
                payload.get("standard_key_destinations", True)
            ),
            qualifiers=[QuickSortMapping.from_dict(item) for item in raw_qualifiers],
            qualifier_enabled=bool(payload.get("qualifier_enabled", False)),
            qualifier_name=str(payload.get("qualifier_name") or "Quality"),
            hierarchy_order=str(
                payload.get("hierarchy_order") or "destination_first"
            ),
            missing_qualifier=str(payload.get("missing_qualifier") or "require"),
            unclassified_folder=str(
                payload.get("unclassified_folder") or "Unclassified"
            ),
            base_destination=str(payload.get("base_destination") or ""),
            source_scope=str(payload.get("source_scope") or "current_folder"),
            include_subfolders=bool(payload.get("include_subfolders", False)),
            include_videos=bool(payload.get("include_videos", False)),
            operation_mode=str(payload.get("operation_mode") or "move"),
            collision_policy=str(payload.get("collision_policy") or "append"),
            include_sidecars=bool(payload.get("include_sidecars", True)),
            start_fullscreen=bool(payload.get("start_fullscreen", True)),
        )
        profile.validate()
        return profile


def default_quick_sort_profile(name: str = "My Quick Sort") -> QuickSortProfile:
    return QuickSortProfile(
        name=name,
        destinations=[],
        standard_key_destinations=True,
        qualifiers=[
            QuickSortMapping("High Quality", "1", "High Quality", "#70D6A4"),
            QuickSortMapping("Medium Quality", "2", "Medium Quality", "#F2C96D"),
            QuickSortMapping("Low Quality", "3", "Low Quality", "#E87979"),
        ],
    )


class QuickSortProfileStore:
    """Atomic JSON persistence for named Quick Sort profiles."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else self.default_path()

    @staticmethod
    def default_path() -> Path:
        app_data = os.getenv("APPDATA")
        if app_data:
            base = Path(app_data) / "taggui"
        else:
            config_home = os.getenv("XDG_CONFIG_HOME")
            base = (
                Path(config_home) / "taggui"
                if config_home
                else Path.home() / ".config" / "taggui"
            )
        return base / "quick_sort_profiles.json"

    def load(self) -> list[QuickSortProfile]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise QuickSortValidationError(
                f"Cannot read Quick Sort profiles from {self.path}: {exc}"
            ) from exc
        if not isinstance(payload, dict) or not isinstance(
            payload.get("profiles"), list
        ):
            raise QuickSortValidationError(
                "Quick Sort profile file has an invalid root structure."
            )
        try:
            schema_version = int(payload.get("schema_version"))
        except (TypeError, ValueError) as exc:
            raise QuickSortValidationError(
                "Quick Sort profile file has an invalid schema version."
            ) from exc
        if schema_version != QUICK_SORT_SCHEMA_VERSION:
            raise QuickSortValidationError(
                f"Unsupported Quick Sort profile file version: {schema_version}"
            )
        profiles = [
            QuickSortProfile.from_dict(item) for item in payload["profiles"]
        ]
        self._validate_profiles(profiles)
        return profiles

    @staticmethod
    def _validate_profiles(profiles: list[QuickSortProfile]) -> None:
        seen_ids: set[str] = set()
        for profile in profiles:
            profile.validate()
            if profile.id in seen_ids:
                raise QuickSortValidationError(
                    f"Duplicate Quick Sort profile ID: {profile.id}"
                )
            seen_ids.add(profile.id)

    def save(self, profiles: list[QuickSortProfile]) -> None:
        self._validate_profiles(profiles)
        payload = {
            "schema_version": QUICK_SORT_SCHEMA_VERSION,
            "profiles": [profile.to_dict() for profile in profiles],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                json.dump(payload, temporary_file, ensure_ascii=False, indent=2)
                temporary_file.write("\n")
                temporary_path = Path(temporary_file.name)
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                try:
                    temporary_path.unlink()
                except OSError:
                    pass


class QuickSortSessionStore:
    """Atomic persistence for resumable Quick Sort decisions."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else self.default_path()

    @staticmethod
    def default_path() -> Path:
        return QuickSortProfileStore.default_path().with_name(
            "quick_sort_sessions.json"
        )

    def load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        if payload.get("schema_version") != QUICK_SORT_SESSION_SCHEMA_VERSION:
            return {}
        sessions = payload.get("sessions")
        if not isinstance(sessions, dict):
            return {}
        return {
            str(key): value
            for key, value in sessions.items()
            if isinstance(value, dict)
        }

    def save(self, sessions: dict[str, dict[str, Any]]) -> None:
        payload = {
            "schema_version": QUICK_SORT_SESSION_SCHEMA_VERSION,
            "sessions": sessions,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                json.dump(payload, temporary_file, ensure_ascii=False, indent=2)
                temporary_file.write("\n")
                temporary_path = Path(temporary_file.name)
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                try:
                    temporary_path.unlink()
                except OSError:
                    pass

    def get(self, session_key: str) -> dict[str, Any] | None:
        value = self.load().get(str(session_key))
        return dict(value) if value is not None else None

    def put(self, session_key: str, state: dict[str, Any]) -> None:
        sessions = self.load()
        sessions[str(session_key)] = dict(state)
        self.save(sessions)

    def remove(self, session_key: str) -> None:
        sessions = self.load()
        if str(session_key) not in sessions:
            return
        sessions.pop(str(session_key), None)
        self.save(sessions)
