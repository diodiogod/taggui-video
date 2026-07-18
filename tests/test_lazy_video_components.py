import os
from pathlib import Path
import sys


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
TAGGUI_ROOT = ROOT / "taggui"
sys.path.insert(0, str(TAGGUI_ROOT))

from PySide6.QtCore import QSortFilterProxyModel
from PySide6.QtWidgets import QApplication

from widgets.image_viewer import ImageViewer


APP = QApplication.instance() or QApplication([])


def test_main_viewer_defers_video_widgets_and_emits_ready_on_creation():
    viewer = ImageViewer(QSortFilterProxyModel(), is_spawned_viewer=False)
    ready = []
    viewer.video_components_ready.connect(ready.append)

    assert viewer.video_player is None
    assert viewer.video_controls is None

    viewer._ensure_video_components()

    assert viewer.video_player is not None
    assert viewer.video_controls is not None
    assert ready == [viewer]
    player = viewer.video_player
    player.cleanup(force_gc=False)
    # Prevent the queued GL prewarm callback from touching a cleaned player
    # if this test shares a QApplication with later Qt tests.
    viewer.video_player = None
    viewer.deleteLater()
    APP.processEvents()
