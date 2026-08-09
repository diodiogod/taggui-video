import os
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'taggui'))

from utils.auto_crop import calculate_crop_avoiding_boxes


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
