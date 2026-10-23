import os
from pathlib import Path
import sys


os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'taggui'))

from PySide6.QtWidgets import QApplication

from widgets.video_player import PLAYBACK_BACKEND_MPV, VideoPlayerWidget


APP = QApplication.instance() or QApplication([])


def test_application_deactivation_hides_and_suspends_mpv_surface():
    player = VideoPlayerWidget()
    widget = type('FakeGlWidget', (), {'_application_render_suspended': False})()
    player.mpv_widget = widget
    player._mpv_surface_active = True
    visibility = []
    player._set_mpv_visible = lambda visible, **kwargs: visibility.append(visible)

    player.set_application_render_active(False)

    assert widget._application_render_suspended is True
    assert player._mpv_surface_active_before_app_suspend is True
    assert visibility == [False]

    player.mpv_widget = None
    player.deleteLater()


def test_display_change_releases_mpv_before_adapter_migration(monkeypatch):
    player = VideoPlayerWidget()
    player.is_playing = True
    player.playback_speed = 1.0
    player.video_path = Path('example.mp4')
    player.mpv_player = object()
    player._active_forward_backend = PLAYBACK_BACKEND_MPV
    player._mpv_surface_active = True
    player.fps = 20.0
    player.total_frames = 1000
    calls = []
    monkeypatch.setattr(
        player,
        'set_application_render_active',
        lambda active: calls.append(('active', active)),
    )
    monkeypatch.setattr(
        player,
        '_teardown_mpv',
        lambda drop_player=False: calls.append(('teardown', drop_player)),
    )
    monkeypatch.setattr(player, 'play', lambda: calls.append(('play',)))
    monkeypatch.setattr(player, '_get_mpv_position_ms', lambda: 4321.0)

    assert player.prepare_for_display_change() is True
    assert player.prepare_for_display_change() is True
    player.finish_display_change()

    assert calls == [('active', False), ('teardown', True), ('play',)]
    assert player.current_frame == 86
    assert player._mpv_estimated_position_ms == 4321.0
    player.deleteLater()


def test_display_change_ignores_parked_mpv_while_showing_still_media(monkeypatch):
    player = VideoPlayerWidget()
    player.mpv_player = object()
    player.video_path = Path('previous-video.mp4')
    player._active_forward_backend = PLAYBACK_BACKEND_MPV
    player._mpv_surface_active = False
    calls = []
    monkeypatch.setattr(
        player,
        'set_application_render_active',
        lambda active: calls.append(('active', active)),
    )
    monkeypatch.setattr(
        player,
        '_teardown_mpv',
        lambda drop_player=False: calls.append(('teardown', drop_player)),
    )

    assert player.prepare_for_display_change() is False
    player.finish_display_change()

    assert calls == []
    assert player._display_change_pending is False
    player.mpv_player = None
    player.deleteLater()
