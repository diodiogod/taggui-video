import os
from pathlib import Path
import sys
import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
TAGGUI_ROOT = ROOT / "taggui"
sys.path.insert(0, str(TAGGUI_ROOT))

from PySide6.QtCore import QSortFilterProxyModel, QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from widgets.image_viewer import ImageViewer
from widgets.video_player import VideoPlayerWidget
from utils.latest_task import LatestTask
from qt_test_helpers import dispose_widget


APP = QApplication.instance() or QApplication([])


@pytest.mark.parametrize('deliver_prewarm', [False, True])
def test_main_viewer_defers_video_widgets_and_emits_ready_on_creation(monkeypatch, deliver_prewarm):
    proxy = QSortFilterProxyModel()
    viewer = ImageViewer(proxy, is_spawned_viewer=False)
    prewarmed = []
    monkeypatch.setattr(VideoPlayerWidget, 'prewarm_gl_widget', lambda *args: prewarmed.append(True))
    ready = []
    viewer.video_components_ready.connect(ready.append)

    assert viewer.video_player is None
    assert viewer.video_controls is None

    viewer._ensure_video_components()

    assert viewer.video_player is not None
    assert viewer.video_controls is not None
    assert ready == [viewer]
    if deliver_prewarm:
        APP.processEvents()
        assert prewarmed == [True]
    player = viewer.video_player
    player.cleanup(force_gc=False)
    for task in viewer.findChildren(LatestTask):
        task.drain()
    dispose_widget(viewer)
    APP.processEvents()
    for owner in (player.media_player, player.position_timer):
        owner.deleteLater()
        QCoreApplication.sendPostedEvents(owner, QEvent.DeferredDelete)
    dispose_widget(player._mpv_parking_widget)
    dispose_widget(player)
    assert prewarmed == ([True] if deliver_prewarm else [])
