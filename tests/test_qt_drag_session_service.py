from taggui.widgets.image_list_qt_drag_session_service import QtDragSessionService
from PySide6.QtCore import QCoreApplication, QObject
from shiboken6 import isValid


APP = QCoreApplication.instance() or QCoreApplication([])


class FakeTimer:
    def __init__(self, *, active=False, interval_ms=100):
        self.active = active
        self.interval_ms = interval_ms
        self.stop_calls = 0
        self.started = []

    def isActive(self):
        return self.active

    def interval(self):
        return self.interval_ms

    def stop(self):
        self.active = False
        self.stop_calls += 1

    def start(self, delay):
        self.active = True
        self.started.append(delay)


class FakeSourceModel:
    def __init__(self, timer):
        self._pause_thumbnail_loading = False
        self._enrichment_timer = timer
        self._native_qt_drag_active = False


class FakeView:
    def __init__(self, source_model, *, pointer_drag=True, window=None):
        self._source_model = source_model
        self._qt_drag_active = False
        self._suppress_selection_commit_until_release = pointer_drag
        self._window = window

    def model(self):
        return self._source_model

    def window(self):
        return self._window


class FakeVideoPlayer:
    def __init__(self):
        self.render_states = []

    def set_application_render_active(self, active):
        self.render_states.append(bool(active))


class FakeWindow:
    def __init__(self, players):
        self._viewers = [type("Viewer", (), {"video_player": player})() for player in players]

    def _iter_all_viewers(self):
        return list(self._viewers)


def test_drag_session_pauses_churn_and_restores_pointer_interaction():
    timer = FakeTimer()
    source_model = FakeSourceModel(timer)
    view = FakeView(source_model)
    service = QtDragSessionService(view)

    state = service.begin()

    assert state is not None
    assert view._qt_drag_active is True
    assert source_model._native_qt_drag_active is True
    assert source_model._pause_thumbnail_loading is True
    assert timer.stop_calls == 1
    assert service.begin() is None

    service.finish(state)

    assert view._qt_drag_active is False
    assert source_model._native_qt_drag_active is False
    assert source_model._pause_thumbnail_loading is False
    assert timer.started == [500]


def test_drag_session_preserves_preexisting_timer_state():
    timer = FakeTimer(active=True, interval_ms=100)
    source_model = FakeSourceModel(timer)
    source_model._pause_thumbnail_loading = True
    view = FakeView(source_model, pointer_drag=False)
    service = QtDragSessionService(view)

    state = service.begin()
    service.finish(state)

    assert source_model._pause_thumbnail_loading is True
    assert source_model._native_qt_drag_active is False
    assert timer.started == [100]
    assert view._qt_drag_active is False


def test_completed_drag_is_destroyed_before_the_next_native_loop():
    drag = QObject()

    QtDragSessionService.retire_drag(drag)

    assert isValid(drag) is False


def test_drag_session_suspends_and_restores_video_rendering():
    timer = FakeTimer()
    source_model = FakeSourceModel(timer)
    players = [FakeVideoPlayer(), FakeVideoPlayer()]
    view = FakeView(source_model, window=FakeWindow(players))
    service = QtDragSessionService(view)

    state = service.begin()
    assert [player.render_states for player in players] == [[False], [False]]

    service.finish(state)
    assert [player.render_states for player in players] == [[False, True], [False, True]]
