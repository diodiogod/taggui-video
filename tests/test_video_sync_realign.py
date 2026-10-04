import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'taggui'))

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication
from widgets import video_sync_coordinator as sync


APP = QApplication.instance() or QApplication([])


class FakePlayer(QObject):
    playback_finished = Signal()

    def __init__(self, *, fps=25.0, frame=100, frames=500, speed=1.0):
        super().__init__()
        self.video_path = Path('video.mp4')
        self.fps = fps
        self.current_frame = frame
        self.total_frames = frames
        self.duration_ms = frames / fps * 1000.0
        self.playback_speed = speed
        self.is_playing = True
        self.mpv_player = None
        self.vlc_player = None
        self._mpv_seek_pending_ms = None
        self._mpv_ready_for_seeks = True
        self._mpv_vo_ready = True
        self.seeks = []
        self.play_frames = []
        self.prime_calls = 0
        self.media_player = SimpleNamespace(position=lambda: self.current_frame / self.fps * 1000)

    def get_current_frame_number(self):
        return self.current_frame

    def get_total_frames(self):
        return self.total_frames

    def set_loop(self, *args):
        pass

    def pause(self):
        self.is_playing = False

    def seek_to_frame(self, frame):
        self.current_frame = frame
        self.seeks.append(frame)

    def play(self):
        self.is_playing = True
        self.play_frames.append(self.current_frame)

    def prime_for_sync_startup(self):
        self.prime_calls += 1


def make_viewer(*, loop=None, **kwargs):
    return SimpleNamespace(
        video_player=FakePlayer(**kwargs),
        video_controls=SimpleNamespace(is_looping=loop is not None, get_loop_range=lambda: loop),
    )


@pytest.fixture
def coordinator_factory(monkeypatch):
    coordinators = []
    monkeypatch.setattr(sync.QTimer, 'singleShot', lambda *args: None)

    def create(viewers):
        coordinator = sync.VideoSyncCoordinator(viewers, show_sync_icon=False)
        coordinators.append(coordinator)
        return coordinator

    yield create
    for coordinator in coordinators:
        if coordinator._state != coordinator._STATE_IDLE:
            coordinator.stop()
        coordinator.deleteLater()


@pytest.mark.parametrize('paused', [True, False])
def test_runtime_pending_does_not_timeout_barrier_or_override_global_toggle(coordinator_factory, paused):
    clicked = make_viewer(frame=100)
    clicked.video_player._runtime_pending = True
    coordinator = coordinator_factory([clicked])
    coordinator.start(reference_viewer=clicked, paused=paused)
    coordinator._barrier_start_monotonic = 0
    coordinator._poll_barrier()
    assert coordinator._state == coordinator._STATE_BARRIER
    assert not clicked.video_player.play_frames
    coordinator.set_paused(not paused)
    clicked.video_player._runtime_pending = False
    coordinator._pause_issued_monotonic = 0
    coordinator._poll_barrier()
    assert clicked.video_player.is_playing is paused


def test_realign_uses_clicked_video_then_next_cycle_restarts_normally(coordinator_factory):
    other = make_viewer(frame=20)
    clicked = make_viewer(frame=100)
    coordinator = coordinator_factory([other, clicked])
    coordinator.start(reference_viewer=clicked)
    coordinator._reseek_all()
    for viewer in (other, clicked):
        assert viewer.video_player.seeks == [100, 100]
        assert not viewer.video_player.is_playing
        assert viewer.video_player.prime_calls == 0

    coordinator._fire_play_all()
    for viewer in (other, clicked):
        assert viewer.video_player.play_frames == [100]
    assert coordinator._watchdog_timer.interval() == 17500  # 20s - 4s + 1.5s
    coordinator._begin_barrier()
    for viewer in (other, clicked):
        assert viewer.video_player.seeks[-1] == 0


def test_realign_maps_fps_and_loop_offsets_and_clamps_short_clips(coordinator_factory):
    clicked = make_viewer(fps=25, frame=150, loop=(50, 400))
    other = make_viewer(fps=30, frame=10, loop=(90, 450))
    short = make_viewer(fps=10, frames=20)
    coordinator = coordinator_factory([clicked, other, short])
    coordinator.start(reference_viewer=clicked)
    assert clicked.video_player.seeks == [150]
    assert other.video_player.seeks == [210]  # 3s loop start + 4s cycle progress
    assert short.video_player.seeks == [19]
    coordinator._fire_play_all()
    coordinator._begin_barrier()
    assert clicked.video_player.seeks[-1] == 50
    assert other.video_player.seeks[-1] == 90


def test_realign_paused_reference_uses_requested_frame_not_stale_native_time(coordinator_factory):
    clicked = make_viewer(frame=101)
    clicked.video_player.is_playing = False
    clicked.video_player.mpv_player = SimpleNamespace(time_pos=0.0)
    coordinator = coordinator_factory([clicked, make_viewer()])
    coordinator.start(reference_viewer=clicked)
    assert clicked.video_player.seeks == [101]


def test_realign_playing_reference_prefers_native_mpv_position(coordinator_factory):
    clicked = make_viewer(frame=150)
    clicked.video_player.mpv_player = SimpleNamespace(time_pos=4.0)
    other = make_viewer(fps=30)
    coordinator = coordinator_factory([other, clicked])
    coordinator.start(reference_viewer=clicked)
    assert clicked.video_player.seeks == [100]
    assert other.video_player.seeks == [120]


def test_realign_accounts_for_playback_speed(coordinator_factory):
    clicked = make_viewer(frame=100, speed=2.0)
    other = make_viewer(frame=10, speed=1.0)
    coordinator = coordinator_factory([clicked, other])
    coordinator.start(reference_viewer=clicked)
    assert other.video_player.seeks == [50]


def test_barrier_waits_for_pending_mpv_seek_and_target_position(coordinator_factory, monkeypatch):
    clicked = make_viewer(frame=100)
    player = clicked.video_player
    player.mpv_player = SimpleNamespace(time_pos=4.0, seeking=False)
    coordinator = coordinator_factory([clicked])
    coordinator.start(reference_viewer=clicked)
    entry = coordinator._entries[0]
    assert entry.is_ready(100)
    player._mpv_seek_pending_ms = 4000.0
    assert not entry.is_ready(100)
    player._mpv_seek_pending_ms = None
    player.mpv_player.seeking = True
    assert not entry.is_ready(100)
    player.mpv_player.seeking = False
    player.mpv_player.time_pos = 0.0
    assert not entry.is_ready(100)
    player.mpv_player.time_pos = 4.0
    assert entry.is_ready(100)

    monkeypatch.setattr(sync.time, 'monotonic', lambda: coordinator._pause_issued_monotonic + 0.2)
    coordinator._poll_barrier()
    assert player.play_frames == [100]


def test_original_sync_still_warms_up_and_restarts_from_beginning(coordinator_factory):
    viewer = make_viewer(frame=100)
    coordinator = coordinator_factory([viewer])
    coordinator.start()
    assert viewer.video_player.prime_calls == 1
    coordinator._on_warming_done()
    coordinator._reseek_all()
    assert viewer.video_player.seeks == [0, 0]
    coordinator._fire_play_all()
    assert viewer.video_player.play_frames == [0]


@pytest.mark.parametrize('backend', ['vlc', 'qt'])
def test_realign_waits_for_other_backend_target_positions(coordinator_factory, backend):
    viewer = make_viewer()
    player = viewer.video_player
    player.is_playing = False
    position = [0]
    if backend == 'vlc':
        player.vlc_player = SimpleNamespace(get_time=lambda: position[0])
    else:
        player._qt_video_source_path = player.video_path
        player.media_player = SimpleNamespace(position=lambda: position[0])
    entry = coordinator_factory([viewer])._entries[0]
    assert not entry.is_ready(100)
    position[0] = 4000
    assert entry.is_ready(100)


@pytest.mark.parametrize('is_video', [True, False])
def test_wall_menu_realign_action_uses_separate_signal(monkeypatch, is_video):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QMenu
    from widgets import floating_viewer_window as floating

    menu = QMenu()
    emitted = []
    window = SimpleNamespace(
        viewer=SimpleNamespace(_is_video_loaded=is_video),
        _selection_masonry_wall_window=True,
        parentWidget=lambda: None,
        realign_video_requested=SimpleNamespace(emit=lambda: emitted.append('realign')),
        sync_video_requested=SimpleNamespace(emit=lambda: emitted.append('restart')),
    )
    monkeypatch.setattr(floating, 'QMenu', lambda parent: menu)

    def select_realign(position):
        action = next(a for a in menu.actions() if a.text() == 'Realign wall from current frame')
        assert action.isEnabled() is is_video
        return action if is_video else None

    monkeypatch.setattr(menu, 'exec', select_realign)
    floating.FloatingViewerWindow._show_window_menu(window, QPoint())
    assert emitted == (['realign'] if is_video else [])
    menu.deleteLater()


@pytest.mark.parametrize('playing', [True, False])
def test_realign_request_routes_only_wall_viewers_and_clicked_reference(playing):
    from widgets.main_window import MainWindow

    clicked = SimpleNamespace(viewer=make_viewer(), _selection_masonry_wall_window=True)
    wall_peer = SimpleNamespace(viewer=make_viewer(), _selection_masonry_wall_window=True)
    unrelated = SimpleNamespace(viewer=make_viewer(), _selection_masonry_wall_window=False)
    for window in (clicked, wall_peer, unrelated):
        window.viewer._is_video_loaded = True
    calls = []
    main = SimpleNamespace(
        _floating_viewers=[clicked, wall_peer, unrelated],
        _pause_viewers_outside_sync_group=lambda viewers: calls.append(('pause_others', viewers)),
        _start_video_sync_for_viewers=lambda viewers, **kwargs: calls.append(('start', viewers, kwargs)),
        _refresh_selection_wall_speed_overlay=lambda: None,
        _selection_wall_any_playing=lambda: playing,
    )
    main._iter_window_scoped_sync_viewers = lambda window: MainWindow._iter_window_scoped_sync_viewers(main, window)
    MainWindow.realign_video_playback_from_window(main, clicked)
    assert calls[0] == ('pause_others', [clicked.viewer, wall_peer.viewer])
    assert calls[1][1] == [clicked.viewer, wall_peer.viewer]
    assert calls[1][2]['scope'] == 'selection_wall'
    assert calls[1][2]['reference_viewer'] is clicked.viewer
    assert calls[1][2]['paused'] is not playing


@pytest.mark.parametrize('paused', [True, False])
def test_realign_preserves_global_playback_state_and_resumes_at_aligned_frame(coordinator_factory, paused):
    clicked = make_viewer(frame=100)
    peer = make_viewer(frame=20)
    coordinator = coordinator_factory([clicked, peer])
    coordinator.start(reference_viewer=clicked, paused=paused)
    coordinator._fire_play_all()
    assert coordinator.is_paused() is paused
    assert coordinator._running_timer.isActive() is not paused
    assert coordinator._watchdog_timer.isActive() is not paused
    for viewer in (clicked, peer):
        assert viewer.video_player.current_frame == 100
        assert viewer.video_player.is_playing is not paused
        assert viewer.video_player.play_frames == ([] if paused else [100])
    if paused:
        coordinator.set_paused(False)
        for viewer in (clicked, peer):
            assert viewer.video_player.play_frames == [100]
        assert coordinator._running_timer.isActive()
        assert coordinator._watchdog_timer.isActive()


def test_global_pause_during_realign_is_honored_when_barrier_finishes(coordinator_factory):
    clicked = make_viewer()
    coordinator = coordinator_factory([clicked])
    coordinator.start(reference_viewer=clicked)
    coordinator.set_paused(True)
    coordinator._fire_play_all()
    assert not clicked.video_player.is_playing
    assert clicked.video_player.play_frames == []


@pytest.mark.parametrize('paused', [True, False])
def test_global_wall_button_uses_intended_state_while_realign_is_settling(coordinator_factory, paused):
    from widgets.main_window import MainWindow

    clicked = make_viewer()
    coordinator = coordinator_factory([clicked])
    coordinator.start(reference_viewer=clicked, paused=paused)
    # All players are temporarily paused by the seek barrier, even if the
    # global playback state is playing. The global button must still toggle.
    main = SimpleNamespace(
        _sync_coordinator=coordinator, _sync_scope='selection_wall',
        _selection_wall_video_viewers=lambda: [clicked],
        _refresh_selection_wall_speed_overlay=lambda: None,
    )
    main._selection_wall_any_playing = lambda: MainWindow._selection_wall_any_playing(main)
    assert main._selection_wall_any_playing() is not paused
    MainWindow._toggle_selection_wall_play_pause(main)
    coordinator._fire_play_all()
    assert clicked.video_player.is_playing is paused
