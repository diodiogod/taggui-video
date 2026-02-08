from taggui.widgets import image_list_masonry_window_planner_service as planner_module
from taggui.widgets.image_list_masonry_window_planner_service import MasonryWindowPlannerService


class FakeScrollBar:
    def __init__(self, value=0, maximum=10000, slider_position=0):
        self._value = value
        self._maximum = maximum
        self._slider_position = slider_position

    def value(self):
        return self._value

    def maximum(self):
        return self._maximum

    def sliderPosition(self):
        return self._slider_position


class FakeViewport:
    def __init__(self, width=1000, height=600):
        self._width = width
        self._height = height

    def width(self):
        return self._width

    def height(self):
        return self._height


class FakeView:
    def __init__(self):
        self._scrollbar = FakeScrollBar()
        self._viewport = FakeViewport()
        self._scrollbar_dragging = False
        self._drag_preview_mode = False
        self._drag_target_page = None
        self._drag_release_anchor_active = False
        self._drag_release_anchor_idx = None
        self._drag_release_anchor_until = 0.0
        self._stick_to_edge = None
        self._masonry_items = []
        self._current_page = 0
        self._masonry_sticky_until = 0.0
        self._masonry_sticky_page = 0

    def verticalScrollBar(self):
        return self._scrollbar

    def viewport(self):
        return self._viewport

    def _strict_page_from_position(self, scroll_value, source_model):
        del source_model
        return max(0, scroll_value // 1000)

    def _get_masonry_visible_items(self, viewport_rect):
        del viewport_rect
        return []


def test_resolve_current_page_uses_drag_target_in_strict_mode():
    view = FakeView()
    view._scrollbar = FakeScrollBar(value=100, maximum=10000, slider_position=100)
    view._scrollbar_dragging = True
    view._drag_target_page = 3
    service = MasonryWindowPlannerService(view)

    page = service.resolve_current_page(
        source_model=object(),
        page_size=1000,
        total_items=5000,
        strict_mode=True,
        local_anchor_mode=False,
    )

    assert page == 3
    assert view._current_page == 3


def test_get_window_buffer_clamps_settings_value(monkeypatch):
    view = FakeView()
    service = MasonryWindowPlannerService(view)

    monkeypatch.setattr(planner_module.settings, "value", lambda *args, **kwargs: 99)
    assert service.get_window_buffer() == 6

    monkeypatch.setattr(planner_module.settings, "value", lambda *args, **kwargs: 0)
    assert service.get_window_buffer() == 1


def test_compute_window_bounds_switches_to_full_layout_at_high_coverage():
    service = MasonryWindowPlannerService(FakeView())
    result = service.compute_window_bounds(
        total_items=1000,
        page_size=100,
        current_page=5,
        strategy="full_compat",
        loaded_count=950,
        window_buffer=3,
    )

    assert result["full_layout_mode"] is True
    assert result["window_start_page"] == 0
    assert result["window_end_page"] == 9
    assert result["min_idx"] == 0
    assert result["max_idx"] == 1000


def test_build_items_with_spacers_inserts_prefix_gap_and_tail():
    service = MasonryWindowPlannerService(FakeView())
    items = service.build_items_with_spacers(
        filtered_items=[(1000, 1.0), (1002, 1.0)],
        min_idx=1000,
        max_idx=1005,
        total_items=1005,
        num_cols_est=1,
        avg_h=10.0,
        avail_width=1000,
        column_width=100,
        spacing=2,
    )

    indices = [item[0] for item in items]
    assert -3 in indices
    assert -1 in indices
    assert -2 in indices
    assert (1000, 1.0) in items
    assert (1002, 1.0) in items


def test_build_items_with_spacers_creates_block_spacer_when_window_empty():
    service = MasonryWindowPlannerService(FakeView())
    items = service.build_items_with_spacers(
        filtered_items=[],
        min_idx=200,
        max_idx=300,
        total_items=1000,
        num_cols_est=2,
        avg_h=12.0,
        avail_width=1000,
        column_width=100,
        spacing=2,
    )

    assert len(items) == 2
    assert items[0][0] == -3
    assert items[1][0] == 200
    assert items[1][1][0] == "SPACER"
