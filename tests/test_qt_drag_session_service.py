import pytest

from taggui.widgets.image_list_qt_drag_session_service import QtDragSessionService
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QGuiApplication


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


@pytest.mark.parametrize("app_active", [True, False])
def test_drag_session_resumes_rendering_only_if_app_is_active(monkeypatch, app_active):
    timer = FakeTimer()
    source_model = FakeSourceModel(timer)
    players = [FakeVideoPlayer(), FakeVideoPlayer()]
    players[1]._display_change_pending = True
    view = FakeView(source_model, window=FakeWindow(players))
    service = QtDragSessionService(view)

    state = service.begin()
    assert [player.render_states for player in players] == [[False], [False]]

    app_state = Qt.ApplicationState.ApplicationActive if app_active else Qt.ApplicationState.ApplicationInactive
    monkeypatch.setattr(QGuiApplication, "applicationState", lambda: app_state)
    service.finish(state)
    assert players[0].render_states == ([False, True] if app_active else [False])
    assert players[1].render_states == [False]
    assert not view._qt_drag_active
