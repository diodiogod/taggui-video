import os
from pathlib import Path
import sys

import pytest


os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'taggui'))

from PySide6.QtWidgets import QApplication
from widgets import video_player
from widgets.video_player import MpvGlWidget, VideoPlayerWidget
from utils.video.playback_backend import PLAYBACK_BACKEND_MPV


APP = QApplication.instance() or QApplication([])


@pytest.fixture
def paused_mpv(monkeypatch):
    player = VideoPlayerWidget()
    widget = MpvGlWidget()
    player.mpv_widget = widget
    player.mpv_player = object()
    player.runtime_playback_backend = PLAYBACK_BACKEND_MPV
    player._active_forward_backend = PLAYBACK_BACKEND_MPV
    player._mpv_ready_for_seeks = True
    player._mpv_vo_ready = True
    player._mpv_needs_reload = False
    player.total_frames = 200
    player.fps = 25.0
    player.current_frame = 50
    visible = {'cover': False, 'surface': True}
    commands = []
    timeouts = []

    def set_visible(value, *, keep_opencv_cover=False):
        visible['surface'] = value
        if value and not keep_opencv_cover:
            visible['cover'] = False

    def prepare_cover(**kwargs):
        visible['cover'] = True
        player._mpv_paused_seek_cover_active = True
        set_visible(not kwargs.get('hide_surface', True),
                    keep_opencv_cover=not kwargs.get('hide_surface', True))
        return True

    monkeypatch.setattr(player, '_set_mpv_visible', set_visible)
    monkeypatch.setattr(player, '_prepare_mpv_paused_seek_cover', prepare_cover)
    monkeypatch.setattr(player, '_hide_opencv_cover_overlay',
                        lambda: visible.update(cover=False))
    monkeypatch.setattr(player, 'sync_external_surface_geometry', lambda: None)
    monkeypatch.setattr(player, '_mpv_set_property', lambda *args: None)
    monkeypatch.setattr(player, '_mpv_string_command',
                        lambda *args: commands.append(args))
    monkeypatch.setattr(video_player.QTimer, 'singleShot',
                        lambda interval, callback: timeouts.append(callback))
    yield player, widget, visible, commands, timeouts
    player._mpv_seek_timer.stop()
    player._clear_mpv_paused_seek_reveal_handler()
    player.mpv_player = None
    player.mpv_widget = None
    widget.deleteLater()
    player._mpv_parking_widget.deleteLater()
    player.deleteLater()


@pytest.mark.parametrize('steps', [(1, 1, 1), (-1, -1, -1), (1, -1, 1)])
def test_rapid_wall_steps_keep_cover_until_final_seek(paused_mpv, steps):
    player, widget, visible, commands, _ = paused_mpv
    for step in steps:
        target = player.get_current_frame_number() + step
        player.pause()
        player.seek_to_frame(target)
        assert visible['cover'], 'The stale first-frame thumbnail was exposed'

    player._mpv_seek_timer.stop()
    player._flush_mpv_seek()
    assert player.current_frame == 50 + sum(steps)
    assert commands == [('seek', f'{player.current_frame / player.fps:.6f}',
                         'absolute+exact')]
    assert visible['cover']
    widget.frame_painted.emit()
    assert not visible['cover']
    assert visible['surface']


def test_new_step_invalidates_previous_reveal_and_timeout(paused_mpv):
    player, widget, visible, _, timeouts = paused_mpv
    player.seek_to_frame(51)
    player._mpv_seek_timer.stop()
    player._flush_mpv_seek()
    old_frame_callback = player._mpv_paused_seek_frame_painted_handler
    old_timeout = timeouts[-1]

    player.pause()
    player.seek_to_frame(52)
    old_frame_callback()
    old_timeout()
    assert visible['cover'], 'An older seek removed the newer seek cover'
    assert player._mpv_paused_seek_cover_active
    assert not widget._emit_frame_painted

    player._mpv_seek_timer.stop()
    player._flush_mpv_seek()
    old_timeout()
    assert visible['cover']
    widget.frame_painted.emit()
    assert not visible['cover']
