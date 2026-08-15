from pathlib import Path
from types import SimpleNamespace
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'taggui'))

from models.image_batch import ImageBatchItem
from utils.image import Image
from widgets.auto_captioner import AutoCaptioner


class _EmptyImageList:
    def get_selected_image_batch(self):
        return []

    def get_selected_image_indices(self):
        return []


def test_current_viewer_image_is_captionable_after_leaving_filter(tmp_path):
    image_path = tmp_path / 'captionable.png'
    image_path.write_bytes(b'not-needed-for-selection-test')
    image = Image(image_path, (100, 100), ['generated'])

    captioner = AutoCaptioner.__new__(AutoCaptioner)
    captioner.image_list = _EmptyImageList()
    captioner.image_list_model = SimpleNamespace(_directory_path=tmp_path)
    captioner.image_viewer = SimpleNamespace(
        current_media=None,
        _last_displayed_media=image,
    )

    batch = captioner._selected_image_batch()

    assert len(batch) == 1
    assert isinstance(batch[0], ImageBatchItem)
    assert batch[0].image is image


def test_current_viewer_tags_follow_caption_result(tmp_path):
    image_path = tmp_path / 'captionable.png'
    image_path.write_bytes(b'not-needed-for-selection-test')
    image = Image(image_path, (100, 100), ['old'])
    source_image = Image(image_path, (100, 100), ['old'])

    captioner = AutoCaptioner.__new__(AutoCaptioner)
    captioner.image_viewer = SimpleNamespace(
        current_media=None,
        _last_displayed_media=image,
    )
    captioner.image_list_model = SimpleNamespace(
        resolve_image_reference=lambda _reference: source_image,
    )

    captioner._sync_viewer_caption_tags(
        ImageBatchItem(source_image),
        'caption',
        ['new', 'tags'],
    )

    assert image.tags == ['new', 'tags']
