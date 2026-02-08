from taggui.widgets.image_list_strict_domain_service import StrictScrollDomainService


class FakeScrollBar:
    def __init__(self, maximum=0, width=15, visible=True):
        self._maximum = maximum
        self._width = width
        self._visible = visible

    def maximum(self):
        return self._maximum

    def width(self):
        return self._width

    def isVisible(self):
        return self._visible


class FakeViewport:
    def __init__(self, width=1000, height=500):
        self._width = width
        self._height = height

    def width(self):
        return self._width

    def height(self):
        return self._height


class FakeSourceModel:
    def __init__(self, total_count, page_size=1000, paginated=True):
        self._total_count = total_count
        self.PAGE_SIZE = page_size
        self._paginated_mode = paginated


class FakeProxyModel:
    def __init__(self, source):
        self._source = source

    def sourceModel(self):
        return self._source


class FakeView:
    def __init__(self, *, source_model, scrollbar_max=0, viewport_w=1000, viewport_h=500):
        self.current_thumbnail_size = 100
        self._strict_virtual_avg_height = 0.0
        self._strict_masonry_avg_h = 0.0
        self._strict_scroll_max_floor = 0
        self._strict_drag_frozen_max = 0
        self._drag_scroll_max_baseline = 0
        self._source_model = source_model
        self._scrollbar = FakeScrollBar(maximum=scrollbar_max, width=15, visible=True)
        self._viewport = FakeViewport(width=viewport_w, height=viewport_h)

    def model(self):
        return self._source_model

    def verticalScrollBar(self):
        return self._scrollbar

    def viewport(self):
        return self._viewport


def test_virtual_avg_height_fallback_and_cached_value():
    view = FakeView(source_model=FakeSourceModel(total_count=900))
    service = StrictScrollDomainService(view)

    assert service.get_strict_virtual_avg_height() == 102.0
    assert view._strict_virtual_avg_height == 102.0

    view._strict_virtual_avg_height = 333.0
    assert service.get_strict_virtual_avg_height() == 333.0


def test_estimate_strict_virtual_scroll_max_uses_paginated_formula():
    view = FakeView(source_model=FakeSourceModel(total_count=900), viewport_w=1000, viewport_h=500)
    service = StrictScrollDomainService(view)

    # cols=(1000+2)//(100+2)=9, rows=ceil(900/9)=100, avg_h=102
    # total_h=10200, max=10200-500=9700
    assert service.estimate_strict_virtual_scroll_max() == 9700


def test_get_strict_min_domain_applies_headroom_and_floor():
    view = FakeView(source_model=FakeSourceModel(total_count=900), viewport_w=1000, viewport_h=500)
    service = StrictScrollDomainService(view)

    # estimate=9700 => int(9700 * 1.10) = 10670
    assert service.get_strict_min_domain() == 10670

    tiny = FakeView(source_model=FakeSourceModel(total_count=1), viewport_w=300, viewport_h=2000)
    tiny_service = StrictScrollDomainService(tiny)
    assert tiny_service.get_strict_min_domain() == 10000


def test_get_strict_scroll_domain_max_respects_floors_and_drag_baseline():
    view = FakeView(source_model=FakeSourceModel(total_count=900), viewport_w=1000, viewport_h=500)
    view._strict_scroll_max_floor = 20000
    view._strict_drag_frozen_max = 15000
    view._drag_scroll_max_baseline = 25000
    service = StrictScrollDomainService(view)

    assert service.get_strict_scroll_domain_max() == 20000
    assert service.get_strict_scroll_domain_max(include_drag_baseline=True) == 25000


def test_strict_canonical_domain_max_uses_masonry_avg_height():
    view = FakeView(source_model=FakeSourceModel(total_count=900), viewport_w=1000, viewport_h=500)
    view._strict_masonry_avg_h = 120.0
    service = StrictScrollDomainService(view)

    # avail_w=1000-15-24=961 => cols=961//102=9, rows=100
    # total_h=100*120=12000 => 12000-500=11500
    assert service.strict_canonical_domain_max() == 11500


def test_strict_page_from_position_uses_scrollbar_domain_and_clamps():
    view = FakeView(source_model=FakeSourceModel(total_count=5000, page_size=1000), scrollbar_max=10000)
    service = StrictScrollDomainService(view)

    assert service.strict_page_from_position(0) == 0
    assert service.strict_page_from_position(5000) == 2
    assert service.strict_page_from_position(20000) == 4


def test_strict_page_from_position_falls_back_to_canonical_when_scrollbar_max_is_zero():
    view = FakeView(source_model=FakeSourceModel(total_count=5000, page_size=1000), scrollbar_max=0)
    service = StrictScrollDomainService(view)

    canonical_domain = service.strict_canonical_domain_max()
    assert canonical_domain > 0
    assert service.strict_page_from_position(canonical_domain // 2) == 2


def test_service_resolves_source_model_from_proxy():
    source = FakeSourceModel(total_count=900)
    proxy = FakeProxyModel(source)
    view = FakeView(source_model=proxy, scrollbar_max=77, viewport_w=1000, viewport_h=500)
    service = StrictScrollDomainService(view)

    # If sourceModel() resolution fails, this would return scrollbar max (77).
    assert service.estimate_strict_virtual_scroll_max() == 9700
