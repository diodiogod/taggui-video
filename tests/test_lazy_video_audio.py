"""Audio intent must survive selecting external backends and falling back to Qt."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QGraphicsScene
from shiboken6 import isValid

from qt_test_helpers import APP, dispose_widget
from widgets import video_player
from widgets.video_player import VideoPlayerWidget
from utils.video.playback_backend import (
    PLAYBACK_BACKEND_MPV, PLAYBACK_BACKEND_VLC_EXPERIMENTAL,
)


@pytest.fixture
def player_scene():
    player = VideoPlayerWidget()
    scene = QGraphicsScene()
    item = scene.addPixmap(QPixmap())
    yield player, scene, item
    player.mpv_player = None
    player.vlc_player = None
    player.cleanup(force_gc=False)
    # Audio output is owned by QMediaPlayer; destroy it through that parent.
    for owner in (player.media_player, player.position_timer):
        owner.deleteLater()
        QCoreApplication.sendPostedEvents(owner, QEvent.DeferredDelete)
    dispose_widget(player._mpv_parking_widget)
    dispose_widget(player)
    scene.clear()
    APP.processEvents()


@pytest.mark.parametrize('backend', [PLAYBACK_BACKEND_MPV, PLAYBACK_BACKEND_VLC_EXPERIMENTAL])
def test_external_preview_and_controls_do_not_open_qt_audio(player_scene, monkeypatch, backend):
    player, _, item = player_scene
    assert player.audio_output is None
    assert player.media_player.audioOutput() is None
    monkeypatch.setattr(video_player, 'resolve_runtime_playback_backend', lambda _: backend)
    def unexpected_audio(*args):
        pytest.fail('An external-backend preview opened a Qt audio device')
    monkeypatch.setattr(video_player, 'QAudioOutput', unexpected_audio)
    preview = QImage(16, 16, QImage.Format_RGB32)
    preview.fill(0)
    assert player.load_video(Path('preview-only.avi'), item,
                             {'fps': 24, 'frame_count': 12, 'duration': .5}, preview, (16, 16))
    calls = []
    player.mpv_player = object()
    player.vlc_player = SimpleNamespace(audio_set_volume=lambda value: calls.append(('vlc_volume', value)))
    monkeypatch.setattr(player, '_mpv_set_property', lambda *args: calls.append(args))
    monkeypatch.setattr(player, '_set_vlc_muted', lambda value: calls.append(('vlc_mute', value)))
    player.set_muted(False)
    player.set_volume(.35)
    assert not player._audio_muted
    assert player._audio_volume == .35
    assert ('mute', False) in calls and ('volume', 35.0) in calls
    assert ('vlc_mute', False) in calls and ('vlc_volume', 35) in calls
    assert player.audio_output is None
    assert not player.is_playing


@pytest.mark.parametrize('muted', [True, False])
@pytest.mark.parametrize('playing', [True, False])
def test_qt_fallback_restores_latest_audio_without_changing_play_intent(
        player_scene, monkeypatch, tmp_path, muted, playing):
    player, scene, _ = player_scene
    # No real media is required: native source assignment is asynchronous.
    player.video_path = tmp_path / 'missing-test-video.avi'
    player.video_item = video_player.QGraphicsVideoItem()
    scene.addItem(player.video_item)
    player.is_playing = playing
    player.set_muted(not muted)
    player.set_volume(.1)
    # Controls can change while the external backend has yet to initialize.
    player.set_muted(muted)
    player.set_volume(.37)
    events = []
    player.playback_started.connect(lambda: events.append('play'))
    player.playback_paused.connect(lambda: events.append('pause'))
    assert player._load_qt_media_source_for_current_video()
    output = player.audio_output
    assert output.parent() is player.media_player
    assert player.media_player.audioOutput() is output
    assert output.isMuted() is muted
    assert output.volume() == pytest.approx(.37)
    assert player.is_playing is playing
    assert not events
    # Idempotent setup, and a later global toggle remains authoritative.
    player.is_playing = not playing
    assert player._load_qt_media_source_for_current_video()
    assert player.audio_output is output
    assert player.is_playing is not playing
    player.set_muted(not muted)
    player.set_volume(.62)
    assert output.isMuted() is not muted
    assert output.volume() == pytest.approx(.62)
    player.media_player.deleteLater()
    QCoreApplication.sendPostedEvents(player.media_player, QEvent.DeferredDelete)
    assert not isValid(output)
    # Fixture cleanup still needs a live player wrapper.
    player.audio_output = None
    player.media_player = video_player.QMediaPlayer()
