from pathlib import Path
from types import SimpleNamespace
import sys
import threading

from PySide6.QtCore import QRect

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "taggui"))

from models.image_list_model import ImageListModel
from utils.image import Image
from widgets.image_list_view_strategy_mixin import ImageListViewStrategyMixin
from widgets.image_list_masonry_incremental_service import MasonryIncrementalService
from widgets.image_list_view_interaction_mixin import ImageListViewInteractionMixin


def test_full_and_incremental_layout_agree_on_tall_and_cropped_images():
    images = [
        Image(Path("tall.png"), (100, 1000)),
        Image(Path("cropped.png"), (1000, 1000), crop=QRect(100, 100, 400, 200)),
    ]
    source = SimpleNamespace(
        _paginated_mode=True, _pages={2: images}, _page_load_lock=threading.Lock(),
        PAGE_SIZE=1000, _total_count=2002, _log_flow=lambda *args, **kwargs: None,
    )
    full, _, _ = ImageListModel.get_buffered_aspect_ratios(source)
    incremental = ImageListViewStrategyMixin._build_masonry_page_items_data(None, source, 2)

    assert full == incremental == [(2000, 1 / 3), (2001, 2.0)]
    service = MasonryIncrementalService(None)
    tiles = service._layout_items(incremental, [0, 0], 120, 2, 2)
    assert [tile["height"] for tile in tiles] == [360, 60]
    assert images[0].aspect_ratio == 0.1  # Raw image metadata is unchanged.
    assert images[1].crop == QRect(100, 100, 400, 200)


def test_pending_boundary_survives_resize_but_not_dataset_change():
    source = SimpleNamespace(_paginated_mode=True, _page_load_generation=1)
    view = SimpleNamespace(
        model=lambda: source, use_masonry=True, viewport=lambda: SimpleNamespace(width=lambda: 800),
        current_thumbnail_size=120, _jump_layout_boundary=(3000, 73200, 122),
        _jump_layout_boundary_identity=(id(source), 1, 650, 120),
        _one_shot_jump_target_global=3000,
    )
    resolve = ImageListViewStrategyMixin._get_jump_layout_boundary
    assert resolve(view) == (3000, 73200, 122)
    assert view._jump_layout_boundary_identity == (id(source), 1, 800, 120)
    source._page_load_generation += 1
    assert resolve(view) is None


def test_scoped_enrichment_uses_worker_updates_and_async_layout():
    calls = []
    source = SimpleNamespace(
        _enrichment_scope="window", _enrichment_exhausted=True,
        _enrichment_target_pages={12}, _enrichment_actual_count=2,
        _total_count=27000, PAGE_SIZE=1000,
        _apply_pending_paginated_dimension_updates=lambda: calls.append("apply"),
        _start_paginated_enrichment=lambda **kwargs: calls.append(kwargs["scope"]),
    )
    view = SimpleNamespace(
        proxy_image_list_model=SimpleNamespace(sourceModel=lambda: source),
        _current_page=12, _mouse_scrolling=False, _scrollbar_dragging=False,
        _masonry_calculating=False,
        _get_transient_owner_anchor_page=lambda **kwargs: None,
        _try_incremental_reflow_changed_pages=lambda *args, **kwargs: False,
        _recalculate_masonry_if_needed=lambda reason: calls.append(reason),
    )
    # The fake model intentionally has no synchronous DB/page loader.
    ImageListViewStrategyMixin._on_paginated_enrichment_complete(view)
    assert calls == ["apply", "enrichment_complete", "preload"]


def test_keyboard_reanchor_queues_one_jump_for_an_evicted_page():
    calls = []
    source = SimpleNamespace(_total_count=27000, PAGE_SIZE=1000, _paginated_mode=True, _pages={})
    view = SimpleNamespace(use_masonry=True, _one_shot_jump_target_global=None)
    def start(target, **kwargs):
        calls.append(target)
        view._one_shot_jump_target_global = target
    view._start_one_shot_targeted_jump = start
    reanchor = ImageListViewInteractionMixin._reanchor_keyboard_to_selected_global
    assert reanchor(view, source, 12005) is False
    assert reanchor(view, source, 12005) is False
    assert calls == [12005]
