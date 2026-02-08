from taggui.widgets import image_list_masonry_lifecycle_service as lifecycle_module
from taggui.widgets.image_list_masonry_lifecycle_service import MasonryLifecycleService


class FakeTimer:
    def __init__(self):
        self.started = []

    def start(self, delay):
        self.started.append(delay)


class FakePauseFlag:
    def __init__(self):
        self.clear_calls = 0

    def clear(self):
        self.clear_calls += 1


class FakeSourceModel:
    def __init__(self, paginated=False, pages=None):
        self._paginated_mode = paginated
        self._pages = pages or {}
        self._enrichment_paused = FakePauseFlag()


class FakeFuture:
    def __init__(self, *, done, result=None, exc=None):
        self._done = done
        self._result = result
        self._exc = exc

    def done(self):
        return self._done

    def result(self):
        if self._exc is not None:
            raise self._exc
        return self._result


class FakeView:
    def __init__(self, source_model=None):
        self._source_model = source_model
        self._masonry_recalc_timer = FakeTimer()
        self._masonry_recalc_delay = 500
        self._masonry_calculating = False
        self._last_filter_keystroke_time = 0.0
        self._last_masonry_signal = "filter_changed"
        self._rapid_input_detected = False
        self.use_masonry = True
        self._masonry_calc_future = None
        self._masonry_start_time = 0.0
        self._masonry_poll_counter = 0
        self.calculate_calls = 0
        self.complete_calls = []
        self.log_messages = []

    def model(self):
        return self._source_model

    def _calculate_masonry_layout(self):
        self.calculate_calls += 1

    def _on_masonry_calculation_complete(self, result):
        self.complete_calls.append(result)

    def _check_masonry_completion(self):
        # Placeholder callback target for QTimer.singleShot scheduling assertions.
        return None

    def _log_flow(self, component, message, **kwargs):
        self.log_messages.append((component, message, kwargs))


def test_do_recalculate_masonry_restarts_timer_for_recent_keystroke(monkeypatch):
    view = FakeView(source_model=FakeSourceModel())
    service = MasonryLifecycleService(view)
    monkeypatch.setattr(lifecycle_module.time, "time", lambda: 10.0)
    view._last_filter_keystroke_time = 9.98  # 20ms ago

    service.do_recalculate_masonry()

    assert view._masonry_recalc_timer.started == [500]
    assert view.calculate_calls == 0


def test_do_recalculate_masonry_retries_while_calculating(monkeypatch):
    view = FakeView(source_model=FakeSourceModel())
    service = MasonryLifecycleService(view)
    monkeypatch.setattr(lifecycle_module.time, "time", lambda: 10.0)
    view._last_filter_keystroke_time = 0.0
    view._masonry_calculating = True

    service.do_recalculate_masonry()

    assert view._masonry_recalc_timer.started == [100]
    assert view.calculate_calls == 0


def test_do_recalculate_masonry_waits_for_typing_cooldown(monkeypatch):
    view = FakeView(source_model=FakeSourceModel())
    service = MasonryLifecycleService(view)
    monkeypatch.setattr(lifecycle_module.time, "time", lambda: 10.0)
    view._last_filter_keystroke_time = 9.0  # 1000ms ago
    view._last_masonry_signal = "filter_changed"

    service.do_recalculate_masonry()

    assert view._masonry_recalc_timer.started == [1000]
    assert view.calculate_calls == 0


def test_do_recalculate_masonry_executes_and_clears_rapid_flag(monkeypatch):
    source = FakeSourceModel(paginated=True, pages={1: [1], 2: [2]})
    view = FakeView(source_model=source)
    service = MasonryLifecycleService(view)
    monkeypatch.setattr(lifecycle_module.time, "time", lambda: 10.0)
    view._last_filter_keystroke_time = 0.0
    view._rapid_input_detected = True

    service.do_recalculate_masonry()

    assert view._rapid_input_detected is False
    assert view.calculate_calls == 1
    assert any("buffered pages loaded=2" in msg for _, msg, _ in view.log_messages)


def test_check_masonry_completion_done_path_calls_completion_handler():
    view = FakeView(source_model=FakeSourceModel())
    view._masonry_calc_future = FakeFuture(done=True, result={"ok": True})
    service = MasonryLifecycleService(view)

    service.check_masonry_completion()

    assert view.complete_calls == [{"ok": True}]


def test_check_masonry_completion_watchdog_resets_stuck_state(monkeypatch):
    source = FakeSourceModel()
    view = FakeView(source_model=source)
    view._masonry_calculating = True
    view._masonry_start_time = 1.0
    view._masonry_calc_future = FakeFuture(done=False)
    service = MasonryLifecycleService(view)
    monkeypatch.setattr(lifecycle_module.time, "time", lambda: 8.0)

    service.check_masonry_completion()

    assert view._masonry_calculating is False
    assert view._masonry_calc_future is None
    assert source._enrichment_paused.clear_calls == 1


def test_check_masonry_completion_schedules_poll_when_not_done(monkeypatch):
    class TimerSpy:
        calls = []

        @staticmethod
        def singleShot(delay, callback):
            TimerSpy.calls.append((delay, callback))

    monkeypatch.setattr(lifecycle_module, "QTimer", TimerSpy)
    monkeypatch.setattr(lifecycle_module.time, "time", lambda: 2.0)

    view = FakeView(source_model=FakeSourceModel())
    view._masonry_calculating = True
    view._masonry_start_time = 1.5
    view._masonry_calc_future = FakeFuture(done=False)
    service = MasonryLifecycleService(view)

    service.check_masonry_completion()

    assert TimerSpy.calls
    assert TimerSpy.calls[0][0] == 50
    assert TimerSpy.calls[0][1] == view._check_masonry_completion
    assert view._masonry_poll_counter == 1
