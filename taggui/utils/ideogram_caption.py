"""Ideogram 4 structured caption parsing and sidecar discovery."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any


IDEOGRAM_CAPTION_SUFFIX = ".ideogram.json"
IDEOGRAM_BBOX_SCALE = 1000
IDEOGRAM_DUPLICATE_BBOX_TOLERANCE = 2
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


def parse_ideogram_caption_text(text: str) -> IdeogramCaption:
    """Parse model output, tolerating fences and trailing commas."""
    source = str(text or "").strip()
    start = source.find("{")
    end = source.rfind("}")
    if start < 0 or end <= start:
        raise IdeogramCaptionError("Model output did not contain a JSON object.")
    source = source[start:end + 1]
    source = re.sub(r",(\s*[}\]])", r"\1", source)
    try:
        payload = json.loads(source)
    except json.JSONDecodeError as exc:
        raise IdeogramCaptionError(f"Invalid model JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise IdeogramCaptionError("Ideogram caption root must be an object.")
    return IdeogramCaption.from_dict(payload)


def build_ideogram_caption_prompt(
    image: Any,
    *,
    user_prompt: str = "",
) -> tuple[str, list[IdeogramElement]]:
    """Build a strict image-analysis prompt with optional locked regions."""
    try:
        existing = discover_ideogram_caption(Path(image.path))
    except IdeogramCaptionError:
        existing = None
    seed_elements = list(existing.elements) if existing is not None else []
    dimensions = image.valid_dimensions()
    aspect_ratio = None
    if dimensions:
        width, height = dimensions
        divisor = _gcd(width, height)
        aspect_ratio = f"{width // divisor}:{height // divisor}"
        if not seed_elements:
            for marking in getattr(image, "markings", []):
                marking_type = getattr(
                    getattr(marking, "type", None),
                    "value",
                    str(getattr(marking, "type", "")),
                )
                if marking_type in {"crop", "no marking"}:
                    continue
                rect = marking.rect.normalized()
                seed_elements.append(
                    IdeogramElement(
                        type="obj",
                        desc=str(getattr(marking, "label", "") or "region"),
                        bbox=pixel_rect_to_bbox(
                            rect.x(),
                            rect.y(),
                            rect.width(),
                            rect.height(),
                            width,
                            height,
                        ),
                    )
                )
    locked = [
        {
            "order": index + 1,
            "type": element.type,
            "bbox": list(element.bbox) if element.bbox else None,
            "label": element.text or element.desc,
        }
        for index, element in enumerate(seed_elements)
    ]
    extra = user_prompt.strip()
    prompt = (
        "Analyze the supplied image and return only one compact JSON object for "
        "Ideogram 4 training. Use bbox coordinates on a 0-1000 grid ordered "
        "[y1,x1,y2,x2]. Keep keys in schema order. The top-level keys may be "
        "aspect_ratio, high_level_description, style_description, and "
        "compositional_deconstruction, in that order. high_level_description "
        "should be a one- or two-sentence summary. "
        "compositional_deconstruction must contain "
        "background and elements. Every element must be type obj or text, may "
        "contain bbox, must contain desc, and text elements must contain exact "
        "visible text in text. An element color_palette may contain at most five "
        "uppercase #RRGGBB values. Include all prominent readable text. "
        "style_description must be omitted or contain exactly one of photo or "
        "art_style plus string fields aesthetics, lighting, and medium; its "
        "optional color_palette may contain at most sixteen uppercase #RRGGBB "
        "values. Describe visible content, not annotation workflow metadata. "
        "Do not use markdown or commentary."
    )
    if aspect_ratio:
        prompt += f" Use aspect_ratio {aspect_ratio}."
    if locked:
        prompt += (
            " Preserve these locked regions in this exact order and preserve "
            "their bbox coordinates exactly; expand their labels into visual "
            f"descriptions when possible: {json.dumps(locked, ensure_ascii=False)}."
        )
    if extra:
        prompt += f" Additional user guidance: {extra}"
    return prompt, seed_elements


def preserve_seed_bboxes(
    caption: IdeogramCaption,
    seed_elements: list[IdeogramElement],
) -> IdeogramCaption:
    """Keep locked regions first while retaining model-expanded descriptions."""
    generated = list(caption.elements)
    used_indices: set[int] = set()
    locked_elements = []

    for seed_index, seed in enumerate(seed_elements):
        match_index = _find_seed_match(
            seed,
            seed_index,
            generated,
            used_indices,
        )
        if match_index is None:
            locked_elements.append(seed)
            continue

        matched = generated[match_index]
        used_indices.add(match_index)
        matched.bbox = seed.bbox
        if seed.type == "text" and seed.text:
            matched.text = seed.text
        locked_elements.append(matched)

    merged_elements = locked_elements + [
        element
        for index, element in enumerate(generated)
        if index not in used_indices
    ]
    caption.elements, _ = append_unique_elements([], merged_elements)
    return caption


def _find_seed_match(
    seed: IdeogramElement,
    seed_index: int,
    generated: list[IdeogramElement],
    used_indices: set[int],
) -> int | None:
    available = [
        index
        for index, element in enumerate(generated)
        if index not in used_indices and element.type == seed.type
    ]
    if seed.bbox is not None:
        for index in available:
            if generated[index].bbox == seed.bbox:
                return index

    seed_label = _normalized_element_label(seed)
    if seed_label:
        for index in available:
            if _normalized_element_label(generated[index]) == seed_label:
                return index

    if (
        seed_index < len(generated)
        and seed_index not in used_indices
        and generated[seed_index].type == seed.type
    ):
        return seed_index
    return available[0] if available else None


def export_ideogram_jsonl(
    media_paths: list[Path],
    destination: Path,
    *,
    base_directory: Path | None = None,
) -> int:
    """Write validated sibling captions as one JSONL training manifest."""
    rows = []
    base = Path(base_directory) if base_directory is not None else None
    for media_path in sorted(
        (Path(path) for path in media_paths),
        key=lambda path: str(path).casefold(),
    ):
        try:
            caption = discover_ideogram_caption(media_path)
        except IdeogramCaptionError:
            continue
        if caption is None:
            continue
        try:
            file_name = (
                str(media_path.relative_to(base))
                if base is not None
                else media_path.name
            )
        except ValueError:
            file_name = media_path.name
        rows.append(
            json.dumps(
                {
                    "file_name": file_name.replace("\\", "/"),
                    "caption": caption.to_json(),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        "\n".join(rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )
    return len(rows)


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
    destination.parent.mkdir(parents=True, exist_ok=True)
    serialized = caption.to_json(pretty=pretty)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_file.write(serialized)
            temporary_path = Path(temporary_file.name)
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
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


def pixel_rect_to_bbox(
    x: float,
    y: float,
    width: float,
    height: float,
    image_width: int,
    image_height: int,
) -> tuple[int, int, int, int]:
    """Convert pixel x/y/w/h into normalized Ideogram y/x coordinates."""
    if image_width <= 0 or image_height <= 0:
        raise IdeogramCaptionError("Image dimensions must be positive.")
    x1 = _normalized_coordinate(x, image_width)
    y1 = _normalized_coordinate(y, image_height)
    x2 = _normalized_coordinate(x + max(0.0, width), image_width)
    y2 = _normalized_coordinate(y + max(0.0, height), image_height)
    return y1, x1, y2, x2


def elements_are_same_region(
    first: IdeogramElement,
    second: IdeogramElement,
    *,
    coordinate_tolerance: int = IDEOGRAM_DUPLICATE_BBOX_TOLERANCE,
) -> bool:
    """Return whether two elements identify the same labeled region."""
    if first.type != second.type:
        return False
    if _normalized_element_label(first) != _normalized_element_label(second):
        return False
    if first.bbox is None or second.bbox is None:
        return first.bbox is None and second.bbox is None
    tolerance = max(0, int(coordinate_tolerance))
    return all(
        abs(first_coord - second_coord) <= tolerance
        for first_coord, second_coord in zip(first.bbox, second.bbox)
    )


def append_unique_elements(
    existing: list[IdeogramElement],
    candidates: list[IdeogramElement],
    *,
    coordinate_tolerance: int = IDEOGRAM_DUPLICATE_BBOX_TOLERANCE,
) -> tuple[list[IdeogramElement], int]:
    """Append candidates that are not coordinate-equivalent labeled regions."""
    merged = list(existing)
    added_count = 0
    for candidate in candidates:
        if any(
            elements_are_same_region(
                current,
                candidate,
                coordinate_tolerance=coordinate_tolerance,
            )
            for current in merged
        ):
            continue
        merged.append(candidate)
        added_count += 1
    return merged, added_count


def _normalized_element_label(element: IdeogramElement) -> str:
    if element.type == "text":
        label = element.text or element.desc
    else:
        label = element.desc
    return " ".join(str(label or "").casefold().split())


def _normalized_coordinate(value: float, extent: int) -> int:
    return max(
        0,
        min(
            IDEOGRAM_BBOX_SCALE,
            round(float(value) * IDEOGRAM_BBOX_SCALE / extent),
        ),
    )


def _gcd(a: int, b: int) -> int:
    while b:
        a, b = b, a % b
    return max(1, abs(a))


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
