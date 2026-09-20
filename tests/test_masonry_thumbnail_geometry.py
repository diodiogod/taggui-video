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


def test_resident_upper_page_is_visible_even_with_unknown_dimensions():
    target_tile = {"index": 14000, "y": 1000}
    upper_tile = {"index": 13999, "y": 880}
    source = SimpleNamespace(
        _paginated_mode=True, _page_load_generation=1,
        _pages={13: [Image(Path("unknown.png"), None)], 14: [Image(Path("target.png"), (800, 1200))]},
    )
    extensions = []
    incremental = SimpleNamespace(
        is_active=True, get_cached_pages=lambda: {14},
        can_extend_down=lambda page: page == 15,
        can_extend_up=lambda page: page == 13,
        purge_far_pages=lambda page: None,
        assemble_items=lambda: [upper_tile, target_tile],
    )
    view = SimpleNamespace(
        proxy_image_list_model=SimpleNamespace(sourceModel=lambda: source), use_masonry=True,
        _get_masonry_strategy=lambda source: "windowed_strict",
        _idle_preload_timer=SimpleNamespace(isActive=lambda: False, start=lambda delay: None),
        _enforce_locked_selected_global=lambda source: None,
        _schedule_rebind_current_index_to_selected_global=lambda: None,
        _get_masonry_incremental_service=lambda: incremental,
        _has_pending_explicit_jump_hold=lambda: False,
        _masonry_cached_dataset_identity=(id(source), 1),
        _masonry_has_visible_content=lambda: True,
        _get_non_restore_reflow_anchor_global=lambda **kwargs: 14000,
        _masonry_items=[target_tile], _masonry_index_map={14000: target_tile},
        _current_page=14,
        _page_needs_enrichment=lambda images: True,
        _try_incremental_extend=lambda page, source, **kwargs: extensions.append((page, kwargs["direction"])) or True,
        viewport=lambda: SimpleNamespace(update=lambda: None),
        _check_and_enrich_loaded_pages=lambda: None,
    )
    ImageListViewStrategyMixin._on_pages_updated(view, [13, 14])
    assert extensions == [(13, "up")]
    assert view._masonry_items == [upper_tile, target_tile]


def test_thumbnail_preload_alternates_across_landing_line():
    from widgets.image_list_view_geometry_mixin import ImageListViewGeometryMixin

    source = SimpleNamespace(_paginated_mode=True, PAGE_SIZE=1000, _total_count=27000,
                             set_visible_indices=lambda indices: None)
    view = SimpleNamespace(
        model=lambda: SimpleNamespace(sourceModel=lambda: source),
        verticalScrollBar=lambda: SimpleNamespace(value=lambda: 1000),
        viewport=lambda: SimpleNamespace(height=lambda: 800, width=lambda: 600),
        _get_masonry_visible_items=lambda rect: [{"index": i} for i in range(14000, 14010)],
        _scroll_direction=None,
        _idle_preload_timer=SimpleNamespace(stop=lambda: None, start=lambda delay: None),
    )
    ImageListViewGeometryMixin._build_queues_async(view)
    assert view._high_queue[:6] == [13999, 14010, 13998, 14011, 13997, 14012]
    assert set(view._urgent_queue) == set(range(14000, 14010))
    # Wheel direction keeps predictive buffer sizes without starving the other edge.
    view._scroll_direction = "down"
    ImageListViewGeometryMixin._build_queues_async(view)
    assert view._high_queue[:4] == [14010, 13999, 14011, 13998]


def test_cold_jump_requests_target_then_both_immediate_neighbors():
    calls = []
    model = SimpleNamespace(
        _paginated_mode=True, PAGE_SIZE=1000, _total_count=26871,
        _page_debouncer=SimpleNamespace(stop=lambda: None),
        set_page_protection_window=lambda start, end: None,
        cancel_pending_loads_except=lambda pages: None,
        _cancel_queued_thumbnails_outside_window=lambda start, end: None,
        _request_page_load=calls.append,
        _order_window_pages=ImageListModel._order_window_pages,
    )
    # Supply a normal three-page buffer without consulting user settings.
    model._get_target_window_pages = lambda target, **kwargs: (
        target // 1000, max(0, target // 1000 - 3), min(26, target // 1000 + 3), 26
    )
    for target, expected in ((14000, [14, 13, 15]), (0, [0, 1]), (26870, [26, 25])):
        calls.clear()
        ImageListModel.prepare_target_window(
            model, target, sync_target_page=False, adjacent_only=True,
            restart_enrichment=False, emit_update=False,
        )
        assert calls == expected


def test_tall_upper_page_requests_full_layout_without_negative_tiles():
    service = MasonryIncrementalService(None)
    target = {"index": 2, "x": 0, "y": 100, "width": 120, "height": 120, "aspect_ratio": 1.0}
    service.cache_from_full_result([target], 2, 120, 2, 1, 100)
    before = service.assemble_items()
    assert service.compute_page_up(0, [(0, 1 / 3), (1, 1 / 3)], 4) is None
    assert service.get_cached_pages() == {1}
    assert service.assemble_items() == before
    assert target["y"] == 100

    # Ordinary upper extension remains incremental and preserves the boundary.
    target["y"] = 1000
    service.cache_from_full_result([target], 2, 120, 2, 1, 100)
    upper = service.compute_page_up(0, [(0, 1 / 3), (1, 1 / 3)], 4)
    assert upper is not None and all(item["y"] >= 0 for item in upper)
    assert target["y"] == 1000
