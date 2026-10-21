"""Packing invariants for real screen geometry and manual size constraints."""
import random

import pytest
from PySide6.QtCore import QRect

from widgets import floating_wall_packing as packing


def area(rects):
    return sum(r.width() * r.height() for r in rects)


@pytest.mark.parametrize('algorithm', packing.ALGORITHMS)
@pytest.mark.parametrize('ratios', [
    [16 / 9] * 4, [9 / 16] * 6,
    [16 / 9, 9 / 16, 1, 4 / 3, 9 / 16, 16 / 9, 1, 3 / 2, 2 / 3, 1],
    [8, .125, 1, 2],
    [8], [.125],
])
def test_opening_fits_all_media_without_rotation_overlap_or_offscreen(algorithm, ratios):
    bounds = QRect(-1914, 46, 1908, 1028)
    result = packing.pack_wall(ratios, bounds, algorithm=algorithm)
    assert len(result.rects) == len(ratios)
    assert packing.valid_layout(result.rects, bounds, 6)
    for rect, ratio in zip(result.rects, ratios):
        assert abs(rect.width() - ratio * rect.height()) <= max(1, ratio) + .001


@pytest.mark.parametrize('algorithm', packing.ALGORITHMS)
def test_three_manual_sizes_survive_every_later_repack(algorithm):
    bounds = QRect(6, 6, 1500, 900)
    sizes = [(300, 200), (220, 330), (200, 200), (320, 180), (240, 180)]
    ratios = [w / h for w, h in sizes]
    for locked in (1, 2, 3):
        result = packing.pack_wall(
            ratios, bounds, preferred_sizes=sizes,
            fixed_sizes=sizes[:locked] + [None] * (len(sizes) - locked), algorithm=algorithm)
        assert len(result.rects) == len(sizes)
        assert packing.valid_layout(result.rects, bounds, 6)
        assert [(r.width(), r.height()) for r in result.rects[:locked]] == sizes[:locked]


@pytest.mark.parametrize('algorithm', packing.ALGORITHMS)
def test_positions_only_never_changes_any_size(algorithm):
    sizes = [(320, 180), (200, 300), (250, 250), (190, 120)]
    result = packing.pack_wall(
        [w / h for w, h in sizes], QRect(0, 0, 1200, 800), algorithm=algorithm,
        preferred_sizes=sizes, automatic_sizing=False)
    assert [(r.width(), r.height()) for r in result.rects] == sizes


def test_impossible_fixed_sizes_return_no_partial_or_shrunken_layout():
    result = packing.pack_wall([1, 1], QRect(0, 0, 500, 500),
                               preferred_sizes=[(400, 400)] * 2, automatic_sizing=False)
    assert result.rects == []


def test_best_fit_never_discards_a_better_feasible_masonry_or_maxrects_candidate():
    rng = random.Random(104)
    for count in (2, 4, 7, 10, 15):
        ratios = rng.choices([.5, 9 / 16, .75, 1, 1.5, 16 / 9, 2], k=count)
        results = {a: packing.pack_wall(ratios, QRect(0, 0, 1600, 900), algorithm=a)
                   for a in packing.ALGORITHMS}
        assert area(results['Best fit'].rects) >= max(area(results[a].rects) for a in ('Masonry', 'MaxRects'))


def test_missing_optional_runtime_dependency_falls_back_to_masonry(monkeypatch):
    monkeypatch.setattr(packing, 'MaxRectsBssf', None)
    result = packing.pack_wall([1, 1.5, .75], QRect(0, 0, 1000, 700), algorithm='MaxRects')
    assert len(result.rects) == 3
    assert result.algorithm == 'Masonry'
    assert result.dependency_missing


@pytest.mark.parametrize('algorithm', packing.ALGORITHMS)
def test_preserve_order_and_individual_window_minimums(algorithm):
    sizes = [(400, 300), (150, 200), (300, 200), (180, 180)]
    result = packing.pack_wall(
        [w / h for w, h in sizes], QRect(0, 0, 1400, 900), algorithm=algorithm,
        preferred_sizes=sizes, minimum_sizes=[(400, 300), (24, 24), (24, 24), (24, 24)],
        preserve_order=True)
    assert len(result.rects) == 4
    assert result.rects[0].width() >= 400 and result.rects[0].height() >= 300
    assert sorted(range(4), key=lambda i: (result.rects[i].y(), result.rects[i].x())) == list(range(4))


def test_cancelled_packing_does_not_continue_searching():
    import threading
    cancelled = threading.Event()
    cancelled.set()
    result = packing.pack_wall([1, 1], QRect(0, 0, 500, 500),
                               preferred_sizes=[(100, 100)] * 2, cancelled=cancelled)
    assert result.rects == []
