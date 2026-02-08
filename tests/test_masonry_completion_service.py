from taggui.widgets.image_list_masonry_completion_service import MasonryCompletionService


class FakePauseFlag:
    def __init__(self):
        self.clear_calls = 0

    def clear(self):
        self.clear_calls += 1


class FakeSourceModel:
    def __init__(self):
        self._enrichment_paused = FakePauseFlag()


class FakeModel:
    def __init__(self, source_model):
        self._source_model = source_model

    def sourceModel(self):
        return self._source_model


class FakeScrollBar:
    def value(self):
        return 0

    def maximum(self):
        return 1


class FakeViewport:
    def height(self):
        return 100


class FakeViewForNullResult:
    def __init__(self):
        self._masonry_calculating = True
        self._last_masonry_done_time = 0
        self._masonry_items = []
        self._source_model = FakeSourceModel()
        self._model = FakeModel(self._source_model)
        self._scrollbar = FakeScrollBar()
        self._viewport = FakeViewport()

    def model(self):
        return self._model

    def verticalScrollBar(self):
        return self._scrollbar

    def viewport(self):
        return self._viewport


def test_completion_service_handles_null_result_and_resumes_enrichment():
    view = FakeViewForNullResult()
    service = MasonryCompletionService(view)

    service.on_masonry_calculation_complete(None)

    assert view._masonry_calculating is False
    assert view._last_masonry_done_time > 0
    assert view._source_model._enrichment_paused.clear_calls == 1
