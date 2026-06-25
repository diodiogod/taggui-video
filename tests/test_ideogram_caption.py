import json

import pytest

from taggui.utils.ideogram_caption import (
    IdeogramCaption,
    IdeogramElement,
    IdeogramCaptionError,
    append_unique_elements,
    bbox_to_pixel_rect,
    build_ideogram_caption_prompt,
    discover_ideogram_caption,
    export_ideogram_jsonl,
    ideogram_caption_path,
    load_ideogram_caption,
    parse_ideogram_caption_text,
    pixel_rect_to_bbox,
    preserve_seed_bboxes,
    save_ideogram_caption,
)


def _caption_payload():
    return {
        "high_level_description": "A poster with a red bicycle.",
        "style_description": {
            "aesthetics": "clean",
            "lighting": "even",
            "medium": "graphic_design",
            "art_style": "flat vector",
            "color_palette": ["#FFFFFF", "#CC0000"],
        },
        "compositional_deconstruction": {
            "background": "An off-white poster background.",
            "elements": [
                {
                    "type": "obj",
                    "bbox": [100, 200, 800, 900],
                    "desc": "A red bicycle shown from the side.",
                },
                {
                    "type": "text",
                    "bbox": [40, 100, 140, 900],
                    "text": "RIDE",
                    "desc": "Large black headline.",
                },
            ],
        },
    }


def test_discovers_preferred_ideogram_sidecar(tmp_path):
    media_path = tmp_path / "sample.png"
    media_path.write_bytes(b"")
    caption_path = ideogram_caption_path(media_path)
    caption_path.write_text(json.dumps(_caption_payload()), encoding="utf-8")

    caption = discover_ideogram_caption(media_path)

    assert caption is not None
    assert caption.source_path == caption_path
    assert caption.elements[1].text == "RIDE"
    assert caption.to_json().startswith('{"high_level_description":')


def test_legacy_json_is_loaded_only_when_it_matches_schema(tmp_path):
    media_path = tmp_path / "sample.png"
    workflow_path = tmp_path / "sample.json"
    workflow_path.write_text('{"nodes":[]}', encoding="utf-8")

    assert discover_ideogram_caption(media_path) is None

    workflow_path.write_text(json.dumps(_caption_payload()), encoding="utf-8")
    assert discover_ideogram_caption(media_path) is not None


def test_rejects_invalid_ideogram_bbox(tmp_path):
    payload = _caption_payload()
    payload["compositional_deconstruction"]["elements"][0]["bbox"] = [
        100,
        200,
        1100,
        900,
    ]
    caption_path = tmp_path / "sample.ideogram.json"
    caption_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(IdeogramCaptionError, match="between 0 and 1000"):
        load_ideogram_caption(caption_path)


def test_converts_yx_bbox_to_pixel_rect():
    assert bbox_to_pixel_rect((100, 200, 600, 700), 2000, 1000) == (
        400.0,
        100.0,
        1000.0,
        500.0,
    )


def test_save_uses_preferred_name_and_normalizes_palette(tmp_path):
    media_path = tmp_path / "sample.png"
    payload = _caption_payload()
    payload["style_description"]["color_palette"] = ["#ffffff", "#cc0000"]
    caption_path = tmp_path / "input.json"
    caption_path.write_text(json.dumps(payload), encoding="utf-8")
    caption = load_ideogram_caption(caption_path)

    saved_path = save_ideogram_caption(media_path, caption)

    assert saved_path == tmp_path / "sample.ideogram.json"
    assert '"color_palette":["#FFFFFF","#CC0000"]' in saved_path.read_text(
        encoding="utf-8"
    )


def test_converts_pixel_rect_to_yx_bbox():
    assert pixel_rect_to_bbox(400, 100, 1000, 500, 2000, 1000) == (
        100,
        200,
        600,
        700,
    )


def test_unique_element_merge_skips_same_label_and_coordinates():
    existing = [
        IdeogramElement(type="obj", desc="watermark", bbox=(900, 840, 980, 990))
    ]
    candidates = [
        IdeogramElement(type="obj", desc="Watermark", bbox=(901, 839, 979, 991)),
        IdeogramElement(type="obj", desc="face", bbox=(100, 100, 400, 400)),
    ]

    merged, added_count = append_unique_elements(existing, candidates)

    assert added_count == 1
    assert [element.desc for element in merged] == ["watermark", "face"]


def test_unique_element_merge_preserves_overlapping_regions():
    existing = [
        IdeogramElement(type="obj", desc="face", bbox=(100, 100, 500, 500))
    ]
    candidates = [
        IdeogramElement(type="obj", desc="face", bbox=(120, 120, 480, 480)),
        IdeogramElement(type="obj", desc="person", bbox=(80, 80, 700, 700)),
    ]

    merged, added_count = append_unique_elements(existing, candidates)

    assert added_count == 2
    assert len(merged) == 3


def test_parses_fenced_model_json_with_trailing_comma():
    text = """```json
    {"compositional_deconstruction":{"background":"","elements":[
      {"type":"obj","bbox":[1,2,3,4],"desc":"face"},
    ]}}
    ```"""

    caption = parse_ideogram_caption_text(text)

    assert caption.elements[0].desc == "face"


def test_preserves_and_appends_locked_regions():
    seeds = [
        IdeogramElement(type="obj", desc="watermark", bbox=(900, 800, 990, 990)),
        IdeogramElement(type="obj", desc="face", bbox=(100, 200, 500, 600)),
    ]
    caption = IdeogramCaption(
        compositional_background="",
        elements=[
            IdeogramElement(type="obj", desc="logo", bbox=(1, 2, 3, 4))
        ],
    )

    result = preserve_seed_bboxes(caption, seeds)

    assert result.elements[0].bbox == seeds[0].bbox
    assert result.elements[1] == seeds[1]


def test_locked_regions_match_by_label_when_model_reorders_elements():
    seeds = [
        IdeogramElement(type="obj", desc="watermark", bbox=(900, 800, 990, 990)),
        IdeogramElement(type="obj", desc="face", bbox=(100, 200, 500, 600)),
    ]
    caption = IdeogramCaption(
        compositional_background="",
        elements=[
            IdeogramElement(
                type="obj",
                desc="A clearly visible human face.",
                bbox=(10, 20, 30, 40),
            ),
            IdeogramElement(
                type="obj",
                desc="watermark",
                bbox=(1, 2, 3, 4),
            ),
            IdeogramElement(
                type="obj",
                desc="A red bicycle.",
                bbox=(200, 200, 700, 800),
            ),
        ],
    )

    result = preserve_seed_bboxes(caption, seeds)

    assert result.elements[0].desc == "watermark"
    assert result.elements[0].bbox == seeds[0].bbox
    assert result.elements[1].desc == "A clearly visible human face."
    assert result.elements[1].bbox == seeds[1].bbox
    assert result.elements[2].desc == "A red bicycle."


def test_locked_region_merge_removes_only_exact_duplicate_regions():
    seed = IdeogramElement(
        type="obj",
        desc="watermark",
        bbox=(900, 800, 990, 990),
    )
    caption = IdeogramCaption(
        compositional_background="",
        elements=[
            IdeogramElement(
                type="obj",
                desc="watermark",
                bbox=(900, 800, 990, 990),
            ),
            IdeogramElement(
                type="obj",
                desc="watermark",
                bbox=(901, 799, 989, 991),
            ),
            IdeogramElement(
                type="obj",
                desc="watermark",
                bbox=(100, 100, 300, 300),
            ),
        ],
    )

    result = preserve_seed_bboxes(caption, [seed])

    assert len(result.elements) == 2
    assert result.elements[0].bbox == seed.bbox
    assert result.elements[1].bbox == (100, 100, 300, 300)


def test_exports_only_valid_ideogram_captions_to_jsonl(tmp_path):
    valid_media = tmp_path / "valid.png"
    invalid_media = tmp_path / "invalid.png"
    missing_media = tmp_path / "missing.png"
    for path in (valid_media, invalid_media, missing_media):
        path.write_bytes(b"")
    ideogram_caption_path(valid_media).write_text(
        json.dumps(_caption_payload()),
        encoding="utf-8",
    )
    ideogram_caption_path(invalid_media).write_text("{bad", encoding="utf-8")
    destination = tmp_path / "captions.jsonl"

    count = export_ideogram_jsonl(
        [valid_media, invalid_media, missing_media],
        destination,
        base_directory=tmp_path,
    )

    assert count == 1
    row = json.loads(destination.read_text(encoding="utf-8"))
    assert row["file_name"] == "valid.png"
    exported_caption = json.loads(row["caption"])
    assert exported_caption["compositional_deconstruction"]["elements"]


class _FakeRect:
    def __init__(self, x, y, width, height):
        self._values = x, y, width, height

    def normalized(self):
        return self

    def x(self):
        return self._values[0]

    def y(self):
        return self._values[1]

    def width(self):
        return self._values[2]

    def height(self):
        return self._values[3]


class _FakeMarkingType:
    value = "hint"


class _FakeMarking:
    label = "face"
    type = _FakeMarkingType()
    rect = _FakeRect(100, 200, 300, 400)


class _FakeImage:
    def __init__(self, path):
        self.path = path
        self.markings = [_FakeMarking()]

    def valid_dimensions(self):
        return 1000, 1000


def test_build_prompt_seeds_taggui_markings(tmp_path):
    image = _FakeImage(tmp_path / "sample.png")

    prompt, seeds = build_ideogram_caption_prompt(image)

    assert seeds[0].desc == "face"
    assert seeds[0].bbox == (200, 100, 600, 400)
    assert "Preserve these locked regions" in prompt
