"""Ideogram 4 structured caption parsing and sidecar discovery."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any


IDEOGRAM_CAPTION_SUFFIX = ".ideogram.json"
IDEOGRAM_BBOX_SCALE = 1000
_HEX_COLOR_PATTERN = re.compile(r"^#[0-9A-F]{6}$", re.IGNORECASE)


class IdeogramCaptionError(ValueError):
    """Raised when an Ideogram caption cannot be parsed or validated."""


@dataclass
class IdeogramElement:
    type: str
    desc: str
    bbox: tuple[int, int, int, int] | None = None
    text: str | None = None
    color_palette: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any], index: int) -> "IdeogramElement":
        element_type = payload.get("type")
        if element_type not in {"obj", "text"}:
            raise IdeogramCaptionError(
                f"Element {index} has unsupported type {element_type!r}."
            )

        desc = payload.get("desc")
        if not isinstance(desc, str):
            raise IdeogramCaptionError(f"Element {index} must contain a string desc.")

        text = payload.get("text")
        if element_type == "text" and not isinstance(text, str):
            raise IdeogramCaptionError(
                f"Text element {index} must contain a string text value."
            )
        if element_type == "obj":
            text = None

        bbox = _parse_bbox(payload.get("bbox"), f"Element {index}")
        palette = _parse_palette(
            payload.get("color_palette"),
            maximum=5,
            context=f"Element {index}",
        )
        return cls(
            type=element_type,
            desc=desc,
            bbox=bbox,
            text=text,
            color_palette=palette,
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": self.type}
        if self.bbox is not None:
            payload["bbox"] = list(self.bbox)
        if self.type == "text":
            payload["text"] = self.text or ""
        payload["desc"] = self.desc
        if self.color_palette:
            payload["color_palette"] = list(self.color_palette)
        return payload


@dataclass
class IdeogramCaption:
    compositional_background: str
    elements: list[IdeogramElement]
    high_level_description: str | None = None
    style_description: dict[str, Any] | None = None
    aspect_ratio: str | None = None
    source_path: Path | None = field(default=None, compare=False)

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
        *,
        source_path: Path | None = None,
    ) -> "IdeogramCaption":
        if not is_ideogram_caption_dict(payload):
            raise IdeogramCaptionError(
                "JSON does not match the Ideogram 4 structured caption schema."
            )

        high_level_description = payload.get("high_level_description")
        if high_level_description is not None and not isinstance(
            high_level_description, str
        ):
            raise IdeogramCaptionError("high_level_description must be a string.")

        aspect_ratio = payload.get("aspect_ratio")
        if aspect_ratio is not None:
            if not isinstance(aspect_ratio, str) or not re.fullmatch(
                r"[1-9]\d*:[1-9]\d*", aspect_ratio
            ):
                raise IdeogramCaptionError(
                    "aspect_ratio must use positive integer W:H notation."
                )

        style_description = payload.get("style_description")
        if style_description is not None:
            style_description = _parse_style_description(style_description)

        deconstruction = payload["compositional_deconstruction"]
        background = deconstruction.get("background")
        if not isinstance(background, str):
            raise IdeogramCaptionError(
                "compositional_deconstruction.background must be a string."
            )

        raw_elements = deconstruction.get("elements")
        if not isinstance(raw_elements, list):
            raise IdeogramCaptionError(
                "compositional_deconstruction.elements must be a list."
            )
        elements = []
        for index, element in enumerate(raw_elements):
            if not isinstance(element, dict):
                raise IdeogramCaptionError(f"Element {index} must be an object.")
            elements.append(IdeogramElement.from_dict(element, index))

        return cls(
            aspect_ratio=aspect_ratio,
            high_level_description=high_level_description,
            style_description=style_description,
            compositional_background=background,
            elements=elements,
            source_path=source_path,
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.aspect_ratio is not None:
            payload["aspect_ratio"] = self.aspect_ratio
        if self.high_level_description is not None:
            payload["high_level_description"] = self.high_level_description
        if self.style_description is not None:
            payload["style_description"] = _ordered_style_description(
                self.style_description
            )
        payload["compositional_deconstruction"] = {
            "background": self.compositional_background,
            "elements": [element.to_dict() for element in self.elements],
        }
        return payload

    def to_json(self, *, pretty: bool = False) -> str:
        if pretty:
            return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
        )


def ideogram_caption_path(media_path: Path) -> Path:
    """Return the preferred structured-caption path for a media file."""
    return Path(media_path).with_suffix(IDEOGRAM_CAPTION_SUFFIX)


def legacy_ideogram_caption_path(media_path: Path) -> Path:
    """Return the ambiguous legacy JSON caption path for a media file."""
    return Path(media_path).with_suffix(".json")


def is_ideogram_caption_dict(payload: Any) -> bool:
    """Return whether a decoded object has the required Ideogram structure."""
    if not isinstance(payload, dict):
        return False
    deconstruction = payload.get("compositional_deconstruction")
    return (
        isinstance(deconstruction, dict)
        and isinstance(deconstruction.get("background"), str)
        and isinstance(deconstruction.get("elements"), list)
    )


def load_ideogram_caption(path: Path) -> IdeogramCaption:
    """Load and validate one Ideogram structured-caption JSON file."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IdeogramCaptionError(f"Failed to read {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise IdeogramCaptionError("Ideogram caption root must be a JSON object.")
    return IdeogramCaption.from_dict(payload, source_path=Path(path))


def discover_ideogram_caption(media_path: Path) -> IdeogramCaption | None:
    """Load the preferred valid caption beside media, if one exists."""
    preferred_path = ideogram_caption_path(media_path)
    if preferred_path.exists():
        return load_ideogram_caption(preferred_path)

    legacy_path = legacy_ideogram_caption_path(media_path)
    if not legacy_path.exists():
        return None
    try:
        payload = json.loads(legacy_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not is_ideogram_caption_dict(payload):
        return None
    return IdeogramCaption.from_dict(payload, source_path=legacy_path)


def save_ideogram_caption(
    media_path: Path,
    caption: IdeogramCaption,
    *,
    path: Path | None = None,
    pretty: bool = False,
) -> Path:
    """Save a structured caption, defaulting to the unambiguous sidecar name."""
    destination = Path(path) if path is not None else ideogram_caption_path(media_path)
    destination.write_text(caption.to_json(pretty=pretty), encoding="utf-8")
    caption.source_path = destination
    return destination


def bbox_to_pixel_rect(
    bbox: tuple[int, int, int, int],
    width: int,
    height: int,
) -> tuple[float, float, float, float]:
    """Convert Ideogram [y1,x1,y2,x2] coordinates into pixel x/y/w/h."""
    y1, x1, y2, x2 = bbox
    x = x1 * width / IDEOGRAM_BBOX_SCALE
    y = y1 * height / IDEOGRAM_BBOX_SCALE
    return (
        x,
        y,
        max(0.0, (x2 - x1) * width / IDEOGRAM_BBOX_SCALE),
        max(0.0, (y2 - y1) * height / IDEOGRAM_BBOX_SCALE),
    )


def _parse_bbox(value: Any, context: str) -> tuple[int, int, int, int] | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 4:
        raise IdeogramCaptionError(f"{context} bbox must contain four integers.")
    if any(isinstance(coord, bool) or not isinstance(coord, int) for coord in value):
        raise IdeogramCaptionError(f"{context} bbox must contain four integers.")
    y1, x1, y2, x2 = value
    if not all(0 <= coord <= IDEOGRAM_BBOX_SCALE for coord in value):
        raise IdeogramCaptionError(
            f"{context} bbox coordinates must be between 0 and 1000."
        )
    if y2 < y1 or x2 < x1:
        raise IdeogramCaptionError(f"{context} bbox coordinates are inverted.")
    return y1, x1, y2, x2


def _parse_palette(value: Any, *, maximum: int, context: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > maximum:
        raise IdeogramCaptionError(
            f"{context} color_palette must contain at most {maximum} colors."
        )
    if any(not isinstance(color, str) or not _HEX_COLOR_PATTERN.fullmatch(color) for color in value):
        raise IdeogramCaptionError(
            f"{context} color_palette entries must use uppercase #RRGGBB notation."
        )
    return [color.upper() for color in value]


def _parse_style_description(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise IdeogramCaptionError("style_description must be an object.")
    has_photo = "photo" in value
    has_art_style = "art_style" in value
    if has_photo == has_art_style:
        raise IdeogramCaptionError(
            "style_description must contain exactly one of photo or art_style."
        )
    for key in ("aesthetics", "lighting", "medium"):
        if not isinstance(value.get(key), str):
            raise IdeogramCaptionError(
                f"style_description.{key} must be a string."
            )
    mode_key = "photo" if has_photo else "art_style"
    if not isinstance(value.get(mode_key), str):
        raise IdeogramCaptionError(
            f"style_description.{mode_key} must be a string."
        )
    palette = _parse_palette(
        value.get("color_palette"),
        maximum=16,
        context="style_description",
    )
    parsed = {
        "aesthetics": value["aesthetics"],
        "lighting": value["lighting"],
        mode_key: value[mode_key],
        "medium": value["medium"],
    }
    if mode_key == "art_style":
        parsed = {
            "aesthetics": value["aesthetics"],
            "lighting": value["lighting"],
            "medium": value["medium"],
            "art_style": value["art_style"],
        }
    if palette:
        parsed["color_palette"] = palette
    return parsed


def _ordered_style_description(value: dict[str, Any]) -> dict[str, Any]:
    mode_key = "photo" if "photo" in value else "art_style"
    if mode_key == "photo":
        ordered = {
            "aesthetics": value.get("aesthetics", ""),
            "lighting": value.get("lighting", ""),
            "photo": value.get("photo", ""),
            "medium": value.get("medium", ""),
        }
    else:
        ordered = {
            "aesthetics": value.get("aesthetics", ""),
            "lighting": value.get("lighting", ""),
            "medium": value.get("medium", ""),
            "art_style": value.get("art_style", ""),
        }
    palette = value.get("color_palette")
    if palette:
        ordered["color_palette"] = list(palette)
    return ordered
