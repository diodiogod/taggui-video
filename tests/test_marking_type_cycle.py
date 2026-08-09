import os
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'taggui'))

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QGraphicsRectItem

from utils.image import ImageMarking
from widgets.image_viewer import ImageViewer
from widgets.marking.marking_item import MarkingItem
from widgets.marking.marking_label import MarkingLabel


def _app():
    return QApplication.instance() or QApplication([])


def test_type_change_updates_latent_area_color_and_visibility():
    _app()
    item = MarkingItem(QRect(1, 2, 20, 30), ImageMarking.HINT, False)

    item.set_rect_type(ImageMarking.EXCLUDE)
    assert item.area.isVisible()
    assert item.area.brush().color() == QColor(255, 0, 0, 127)

    item.set_rect_type(ImageMarking.INCLUDE)
    assert item.area.isVisible()
    assert item.area.brush().color() == QColor(0, 255, 0, 127)

    item.set_rect_type(ImageMarking.HINT)
    assert not item.area.isVisible()


def test_type_change_renames_only_generated_labels():
    _app()
    generated = MarkingItem(QRect(0, 0, 10, 10), ImageMarking.HINT, False)
    generated_background = QGraphicsRectItem(generated)
    generated.label = MarkingLabel('exclusion', 1.0, generated_background)
    generated.setData(0, 'exclusion')

    ImageViewer._rename_default_marking_label(generated, ImageMarking.INCLUDE)
    assert generated.label.toPlainText() == 'include'
    assert generated.data(0) == 'include'

    custom = MarkingItem(QRect(0, 0, 10, 10), ImageMarking.HINT, False)
    custom_background = QGraphicsRectItem(custom)
    custom.label = MarkingLabel('watermark', 1.0, custom_background)
    custom.setData(0, 'watermark')

    ImageViewer._rename_default_marking_label(custom, ImageMarking.EXCLUDE)
    assert custom.label.toPlainText() == 'watermark'
    assert custom.data(0) == 'watermark'
