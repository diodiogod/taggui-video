import os
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'taggui'))

from models.image_list_model import ImageListModel
from utils.image import Image, ImageMarking


class _ImageReference:
    def __init__(self, image, *, valid=True):
        self._image = image
        self._valid = valid

    def data(self, role):
        if role == Qt.ItemDataRole.UserRole:
            return self._image
        return None

    def isValid(self):
        return self._valid


def test_generated_markings_update_loaded_image_instead_of_detached_batch_item(
        tmp_path):
    detached_image = Image(tmp_path / 'image.png', (100, 100), [])
    loaded_image = Image(tmp_path / 'image.png', (100, 100), [])
    batch_reference = _ImageReference(detached_image)
    loaded_index = _ImageReference(loaded_image)

    class _Model:
        resolve_image_reference = ImageListModel.resolve_image_reference
        add_image_markings = ImageListModel.add_image_markings

        def get_loaded_index_for_reference(self, _reference):
            return loaded_index

        def write_meta_to_disk(self, image):
            self.written_image = image

        def _save_markings_to_db(self, image):
            self.indexed_image = image

        class dataChanged:
            @staticmethod
            def emit(*_args):
                pass

    model = _Model()
    result = model.add_image_markings(batch_reference, [{
        'box': [10.2, 20.4, 30.6, 40.8],
        'label': 'watermark',
        'type': 'hint',
        'confidence': 0.9,
    }])

    assert result is loaded_image
    assert model.written_image is loaded_image
    assert model.indexed_image is loaded_image
    assert detached_image.markings == []
    assert len(loaded_image.markings) == 1
    assert loaded_image.markings[0].label == 'watermark'
    assert loaded_image.markings[0].type == ImageMarking.HINT


def test_crop_out_creates_crop_on_loaded_image_without_regular_marking(tmp_path):
    detached_image = Image(tmp_path / 'image.png', (1000, 1000), [])
    loaded_image = Image(tmp_path / 'image.png', (1000, 1000), [])
    batch_reference = _ImageReference(detached_image)
    loaded_index = _ImageReference(loaded_image)

    class _Model:
        resolve_image_reference = ImageListModel.resolve_image_reference
        add_image_markings = ImageListModel.add_image_markings

        def get_loaded_index_for_reference(self, _reference):
            return loaded_index

        def write_meta_to_disk(self, image):
            self.written_image = image

        def _save_markings_to_db(self, image):
            self.indexed_image = image

        class dataChanged:
            @staticmethod
            def emit(*_args):
                pass

    model = _Model()
    result = model.add_image_markings(batch_reference, [{
        'box': [800, 900, 990, 990],
        'label': 'watermark',
        'type': 'crop out',
        'confidence': 0.9,
        'crop_padding_percent': 1.0,
        'crop_minimum_retained_percent': 75.0,
    }])

    assert result is loaded_image
    assert loaded_image.crop.getRect() == (0, 0, 1000, 890)
    assert loaded_image.markings == []
    assert model.written_image is loaded_image
