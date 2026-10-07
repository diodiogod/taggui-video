from pathlib import Path

import pytest
from qt_test_helpers import APP
from test_lazy_video_audio import player_scene


@pytest.mark.parametrize('playing', [False, True])
@pytest.mark.parametrize('action', ['none', 'toggle', 'switch', 'play_again'])
def test_decoder_restart_respects_latest_playback_intent(player_scene, monkeypatch, playing, action):
    player, _, _ = player_scene
    player.mpv_player = object()
    player.video_path = Path('first.mp4')
    player.is_playing = playing
    starts = []
    monkeypatch.setattr(player, '_teardown_mpv', lambda **kw: setattr(player, 'mpv_player', None))
    monkeypatch.setattr(player, '_show_opencv_frame', lambda *args: None)
    monkeypatch.setattr(player, '_refresh_backend_selection', lambda: True)
    def start(**kw):
        starts.append(player.video_path)
        player.is_playing = True
    monkeypatch.setattr(player, '_play_ready', start)
    player.apply_mpv_hwdec_change()
    assert player.is_playing is playing, 'Temporary restart erased playback intent'
    if action == 'toggle':
        player.toggle_play_pause()
    elif action == 'switch':
        player.suspend_for_media_switch()
        player.video_path = Path('second.mp4')
    elif action == 'play_again':
        player.play()
    APP.processEvents()
    expected = (not playing) if action == 'toggle' else playing if action == 'none' else action == 'play_again'
    assert player.is_playing is expected
    assert starts == ([Path('first.mp4')] if expected else [])


def test_decoder_change_does_not_stop_reverse_playback(player_scene, monkeypatch):
    player, _, _ = player_scene
    player.mpv_player = object()
    player.is_playing = True
    player.playback_speed = -1
    player.position_timer.start(1000)
    monkeypatch.setattr(player, '_teardown_mpv', lambda **kw: setattr(player, 'mpv_player', None))
    player.apply_mpv_hwdec_change()
    assert player.is_playing
    assert player.position_timer.isActive()
