import os
from pathlib import Path
import sys


os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'taggui'))

from PySide6.QtCore import QStringListModel
from PySide6.QtWidgets import QApplication

from utils.image import Image
from widgets.image_tags_editor import TagInputBox


class _NoSelectionView:
    def get_selected_image_batch(self):
        return []


class _ImageList:
    list_view = _NoSelectionView()


def test_tag_input_continues_editing_viewer_image_after_filter_removal(tmp_path):
    app = QApplication.instance() or QApplication([])
    image_path = tmp_path / 'image.png'
    image_path.write_bytes(b'not-needed-for-input-test')
    image = Image(image_path, (100, 100), ['first'])
    tag_model = QStringListModel(['first'])
    input_box = TagInputBox(tag_model, None, _ImageList(), ', ')
    input_box.current_image_reference_getter = lambda: image

    input_box.add_tag('second')
    input_box.add_tag('third')

    assert tag_model.stringList() == ['first', 'second', 'third']
    input_box.deleteLater()
    app.processEvents()
