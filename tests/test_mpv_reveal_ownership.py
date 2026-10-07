"""Reveal callbacks must belong to the current attempt and native player."""
import pytest
from PySide6.QtCore import QObject, Signal

from qt_test_helpers import dispose_qobject
from test_lazy_video_audio import player_scene
from widgets import video_player


class RevealSurface(QObject):
    frame_painted = Signal()
    _emit_frame_painted = False


@pytest.mark.parametrize('playing', [False, True])
def test_cancel_and_new_reveal_reject_old_fallbacks(player_scene, monkeypatch, playing):
    player, _, _ = player_scene
    surface = RevealSurface()
    player.mpv_widget = surface
    player.is_playing = playing
    scheduled, visible = [], []
    monkeypatch.setattr(video_player, 'MpvGlWidget', RevealSurface)
    monkeypatch.setattr(video_player.QTimer, 'singleShot', lambda *args: scheduled.append(args))
    monkeypatch.setattr(player, '_set_mpv_visible', lambda *args, **kwargs: visible.append(args))
    try:
        player._begin_mpv_reveal()
        initial_timeout = scheduled.pop()
        assert initial_timeout[1] is player
        initial_timeout[-1]()
        hard_fallback = scheduled.pop()
        assert hard_fallback[1] is player
        visible.clear()
        player._cancel_mpv_reveal()
        assert not player._mpv_pending_reveal
        assert not surface._emit_frame_painted
        hard_fallback[-1]()
        assert not visible
        player._begin_mpv_reveal()
        current_timeout = scheduled.pop()
        initial_timeout[-1]()
        hard_fallback[-1]()
        assert not visible and player._mpv_pending_reveal
        current_timeout[-1]()
        assert visible == [(True,)]
        surface.frame_painted.emit()
        assert not player._mpv_pending_reveal
        assert player.is_playing is playing
    finally:
        player.mpv_widget = None
        dispose_qobject(surface)
