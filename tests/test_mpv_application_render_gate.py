import os
from pathlib import Path
import sys


os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'taggui'))

from PySide6.QtWidgets import QApplication

from widgets.video_player import VideoPlayerWidget


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
