import json

import pytest

from taggui.utils.ideogram_caption import (
    IdeogramElement,
    IdeogramCaptionError,
    append_unique_elements,
    bbox_to_pixel_rect,
    discover_ideogram_caption,
    ideogram_caption_path,
    load_ideogram_caption,
    pixel_rect_to_bbox,
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
