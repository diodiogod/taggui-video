import os
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'taggui'))

from utils.auto_crop import calculate_crop_avoiding_boxes
from controllers.marking_effects_controller import MarkingEffectsController
from PySide6.QtCore import QRect
from utils.image import Image, ImageMarking, Marking


def test_crop_out_prefers_least_destructive_edge_for_corner_watermark():
    crop = calculate_crop_avoiding_boxes(
        (1000, 1000),
        [[800, 900, 990, 990]],
        padding_percent=1.0,
        minimum_retained_percent=75.0,
    )

    assert crop is not None
    assert crop.getRect() == (0, 0, 1000, 890)


def test_crop_out_rejects_interior_detection_when_too_much_would_be_lost():
    crop = calculate_crop_avoiding_boxes(
        (1000, 1000),
        [[450, 450, 550, 550]],
        padding_percent=1.0,
        minimum_retained_percent=75.0,
    )

    assert crop is None


def test_crop_out_avoids_multiple_detections_with_one_crop():
    crop = calculate_crop_avoiding_boxes(
        (1000, 800),
        [[20, 710, 180, 790], [800, 720, 980, 790]],
        padding_percent=1.0,
        minimum_retained_percent=75.0,
    )

    assert crop is not None
    assert crop.bottom() < 710


def test_marking_crop_filter_supports_type_and_case_insensitive_label(tmp_path):
    image = Image(tmp_path / 'image.png', (100, 100), markings=[
        Marking('Corner Watermark', ImageMarking.EXCLUDE, QRect(80, 80, 20, 20)),
        Marking('subject', ImageMarking.INCLUDE, QRect(10, 10, 50, 50)),
    ])
    options = {
        'marking_type': 'Exclude',
        'label_filter': 'watermark',
        'label_match': 'Contains',
    }

    assert MarkingEffectsController._matching_marking_boxes(image, options) == [
        [80, 80, 100, 100],
    ]


def test_marking_crop_filter_allows_all_types_with_exact_label(tmp_path):
    image = Image(tmp_path / 'image.png', (100, 100), markings=[
        Marking('logo', ImageMarking.HINT, QRect(0, 0, 10, 10)),
        Marking('logo extra', ImageMarking.EXCLUDE, QRect(80, 80, 20, 20)),
    ])
    options = {
        'marking_type': 'All marking types',
        'label_filter': 'LOGO',
        'label_match': 'Exact',
    }

    assert MarkingEffectsController._matching_marking_boxes(image, options) == [
        [0, 0, 10, 10],
    ]
