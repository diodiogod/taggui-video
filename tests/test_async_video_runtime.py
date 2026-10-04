from pathlib import Path
from threading import Event

import pytest
from PySide6.QtGui import QImage
from PySide6.QtCore import QTimer

from qt_test_helpers import APP, pump
from test_lazy_video_audio import player_scene
from utils.video import playback_backend
from utils.video.runtime_loader import RuntimeLoader
from widgets import video_player


@pytest.fixture
def pending_runtime(monkeypatch):
    release = Event()
    module = object()
    def importer(name):
        assert release.wait(5)
        return module
    loader = RuntimeLoader(importer)
    monkeypatch.setattr(playback_backend, '_RUNTIME_LOADER', loader)
    for name, value in [('MPV_PYTHON_MODULE', None), ('MPV_BACKEND_AVAILABLE', False),
                        ('MPV_BACKEND_ERROR', '')]:
        monkeypatch.setattr(playback_backend, name, value)
    monkeypatch.setattr(video_player, 'get_configured_playback_backend', lambda: playback_backend.PLAYBACK_BACKEND_MPV)
    monkeypatch.setenv('QT_OPENGL', 'desktop')
    yield release, loader
    release.set()
    loader.load('mpv')


def load_preview(player, item, name='first.avi'):
    preview = QImage(16, 16, QImage.Format_RGB32)
    preview.fill(0)
    assert player.load_video(Path(name), item, {'fps': 24, 'frame_count': 12, 'duration': .5}, preview, (16, 16))
    assert not item.pixmap().isNull()


@pytest.mark.parametrize('initial_play', [False, True])
@pytest.mark.parametrize('toggle', [False, True])
def test_preview_and_latest_play_intent_while_import_pending(player_scene, pending_runtime, monkeypatch, initial_play, toggle):
    player, _, item = player_scene
    release, loader = pending_runtime
    played, signals = [], []
    monkeypatch.setattr(player, '_play_ready', lambda **kw: played.append((player.video_path, kw)))
    monkeypatch.setattr(player, '_show_opencv_frame', lambda *args: pytest.fail('Pending pause decoded media'))
    player.playback_started.connect(lambda: signals.append('play'))
    player.playback_paused.connect(lambda: signals.append('pause'))
    load_preview(player, item)
    assert player._runtime_pending and player.audio_output is None
    assert not loader.snapshot('mpv').module
    if initial_play:
        player.play()
    if toggle:
        player.pause() if initial_play else player.play()
    expected_play = initial_play != toggle
    assert player.is_playing is expected_play
    ticks = []
    QTimer.singleShot(0, player, lambda: ticks.append(True))
    APP.processEvents()
    assert ticks == [True] and loader.snapshot('mpv').status == 'pending'
    assert not played
    assert player.cap is None, 'Pausing a pending preview must not decode a frame'
    release.set()
    pump(lambda: not player._runtime_pending)
    assert len(played) == int(expected_play)
    if played:
        assert played[0] == (Path('first.avi'), {'notify': False})
    assert signals.count('play') == int(initial_play or toggle)


@pytest.mark.parametrize('action', ['switch', 'still', 'cleanup'])
def test_pending_completion_cannot_play_abandoned_selection(player_scene, pending_runtime, monkeypatch, action):
    player, _, item = player_scene
    release, loader = pending_runtime
    played = []
    monkeypatch.setattr(player, '_play_ready', lambda **kw: played.append(player.video_path))
    load_preview(player, item)
    player.play()
    if action == 'switch':
        load_preview(player, item, 'second.avi')
    elif action == 'still':
        player.suspend_for_media_switch()
    else:
        player.cleanup(force_gc=False)
    release.set()
    loader.load('mpv')
    player._poll_runtime_ready()
    assert not played
    assert not player.is_playing


def test_pause_during_runtime_change_also_pauses_existing_native_player(player_scene, pending_runtime, monkeypatch):
    player, _, item = player_scene
    load_preview(player, item)
    player.mpv_player = object()
    paused = []
    monkeypatch.setattr(player, '_mpv_set_property', lambda *args: paused.append(args))
    monkeypatch.setattr(player, '_get_mpv_position_ms', lambda: None)
    player.play()
    player.pause()
    assert ('pause', True) in paused
    assert not player.is_playing and not player._runtime_play_requested


def test_completed_import_before_second_play_does_not_lose_request(player_scene, pending_runtime, monkeypatch):
    player, _, item = player_scene
    release, loader = pending_runtime
    played = []
    monkeypatch.setattr(player, '_play_ready', lambda **kw: played.append(kw))
    load_preview(player, item)
    player.play()
    release.set()
    loader.load('mpv')
    player.play()  # Completion occurred before the poll timer could run.
    assert played == [{'notify': False}]


def test_failed_import_resolves_to_qt_only_after_completion(player_scene, monkeypatch):
    player, _, item = player_scene
    release = Event()
    def importer(name):
        assert release.wait(5)
        raise OSError('test missing DLL')
    loader = RuntimeLoader(importer)
    monkeypatch.setattr(playback_backend, '_RUNTIME_LOADER', loader)
    monkeypatch.setattr(playback_backend, 'MPV_PYTHON_MODULE', None)
    monkeypatch.setattr(playback_backend, 'MPV_BACKEND_ERROR', '')
    monkeypatch.setattr(playback_backend, 'MPV_BACKEND_AVAILABLE', False)
    monkeypatch.setattr(video_player, 'get_configured_playback_backend', lambda: playback_backend.PLAYBACK_BACKEND_MPV)
    monkeypatch.setenv('QT_OPENGL', 'desktop')
    starts = []
    monkeypatch.setattr(player, '_play_ready', lambda **kw: starts.append(player.runtime_playback_backend))
    try:
        load_preview(player, item)
        player.play()
        assert player.audio_output is None
        assert player.runtime_playback_backend == playback_backend.PLAYBACK_BACKEND_MPV
        release.set()
        pump(lambda: bool(starts))
        assert starts == [playback_backend.PLAYBACK_BACKEND_QT_HYBRID]
        assert 'test missing DLL' in playback_backend.MPV_BACKEND_ERROR
    finally:
        release.set()
        loader.load('mpv')


def test_pending_sync_priming_resumes_without_starting_playback(player_scene, pending_runtime, monkeypatch):
    player, _, item = player_scene
    release, _ = pending_runtime
    load_preview(player, item)
    assert not player.prime_for_sync_startup()
    primed = []
    monkeypatch.setattr(player, '_setup_mpv_for_current_video', lambda: primed.append(True) or False)
    release.set()
    pump(lambda: not player._runtime_pending)
    assert primed == [True]
    assert not player.is_playing
