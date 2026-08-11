import os
from pathlib import Path
import sys


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "taggui"))

from PySide6.QtCore import QRect, QRectF
from PySide6.QtWidgets import QApplication, QGraphicsScene

from utils.rect import RectPosition
from widgets.image_viewer import ImageViewer
from widgets.marking import ResizeHintHUD


APP = QApplication.instance() or QApplication([])


class _ViewerStub:
    _live_hud_item = ImageViewer._live_hud_item
    _set_hud_crop_rect_if_alive = ImageViewer._set_hud_crop_rect_if_alive
    _set_hud_values_if_alive = ImageViewer._set_hud_values_if_alive

    def __init__(self, hud_item):
        self.hud_item = hud_item


def test_crop_hud_updates_ignore_scene_deleted_qt_item():
    scene = QGraphicsScene()
    hud_item = ResizeHintHUD(QRect(0, 0, 640, 480))
    scene.addItem(hud_item)
    viewer = _ViewerStub(hud_item)

    scene.clear()

    viewer._set_hud_crop_rect_if_alive(QRectF(10, 10, 100, 100))
    viewer._set_hud_values_if_alive(
        QRectF(10, 10, 100, 100),
        RectPosition.NONE,
    )

    assert viewer.hud_item is None


def test_crop_hud_updates_live_item():
    hud_item = ResizeHintHUD(QRect(0, 0, 640, 480))
    viewer = _ViewerStub(hud_item)
    rect = QRectF(10, 20, 100, 120)

    viewer._set_hud_crop_rect_if_alive(rect)
    viewer._set_hud_values_if_alive(rect, RectPosition.NONE)

    assert hud_item.has_crop is True
    assert hud_item.rect == rect
