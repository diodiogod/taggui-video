from pathlib import Path
from concurrent.futures import Future
import sys
import threading
from types import MethodType

from PySide6.QtCore import QRect

ROOT = Path(__file__).resolve().parents[1]
TAGGUI_ROOT = ROOT / "taggui"
sys.path.insert(0, str(TAGGUI_ROOT))

from utils.thumbnail_cache import ThumbnailCache
from models.image_list_model import ImageListModel


def test_cache_probe_does_not_create_bucket_or_decode(tmp_path):
    cache = ThumbnailCache.__new__(ThumbnailCache)
    cache.enabled = True
    cache.cache_dir = tmp_path

    image_path = tmp_path / "source.jpg"
    cache_key = cache._get_cache_key(image_path, 123.0, 512)
    cache_path = cache._get_cache_path(cache_key)

    assert not cache.has_thumbnail(image_path, 123.0, 512)
    assert not cache_path.parent.exists()

    cache_path.parent.mkdir()
    cache_path.touch()
    assert cache.has_thumbnail(image_path, 123.0, 512)


def test_cropped_thumbnail_uses_a_distinct_cache_key(tmp_path):
    cache = ThumbnailCache.__new__(ThumbnailCache)
    image_path = tmp_path / "source.jpg"

    full_key = cache._get_cache_key(image_path, 123.0, 512)
    crop_key = cache._get_cache_key(
        image_path,
        123.0,
        512,
        QRect(10, 20, 300, 200),
    )

    assert full_key != crop_key


def test_thumbnail_future_cleanup_handles_fast_and_replaced_tasks(tmp_path):
    tracker = type("Tracker", (), {})()
    tracker._thumbnail_lock = threading.Lock()
    tracker._thumbnail_futures = {}
    tracker._forget_thumbnail_future = MethodType(
        ImageListModel._forget_thumbnail_future, tracker
    )

    already_done = Future()
    already_done.set_result(None)
    ImageListModel._track_thumbnail_future(
        tracker, 3, tmp_path / "fast.webp", already_done
    )
    assert 3 not in tracker._thumbnail_futures

    old_future = Future()
    new_future = Future()
    ImageListModel._track_thumbnail_future(
        tracker, 7, tmp_path / "old.webp", old_future
    )
    ImageListModel._track_thumbnail_future(
        tracker, 7, tmp_path / "new.webp", new_future
    )
    old_future.set_result(None)
    assert tracker._thumbnail_futures[7][0] is new_future
    new_future.set_result(None)
    assert 7 not in tracker._thumbnail_futures


def test_tall_thumbnail_preserves_crop_and_centers_inside_its_offset(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from PySide6.QtGui import QImage, QColor
    from models.image_list_model import load_thumbnail_data
    from utils import thumbnail_cache

    # No singleton initialization or access to the user's cache/settings.
    monkeypatch.setattr(thumbnail_cache, "get_thumbnail_cache", lambda: SimpleNamespace(enabled=False))
    image = QImage(100, 800, QImage.Format_RGB32)
    image.fill(QColor("red"))
    for y in range(250, 550):
        for x in range(20, 70):
            image.setPixelColor(x, y, QColor("blue"))
    path = tmp_path / "tall.png"
    assert image.save(str(path))
    crop = QRect(20, 200, 50, 400)

    thumbnail, _, _, _ = load_thumbnail_data(path, crop, 50, False)

    assert crop == QRect(20, 200, 50, 400)
    assert thumbnail.size().toTuple() == (50, 150)
    assert thumbnail.pixelColor(25, 0) == QColor("blue")
    assert thumbnail.pixelColor(25, 149) == QColor("blue")


def test_jxl_thumbnail_applies_crop_without_mutating_it(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from PIL import Image as PILImage
    from PySide6.QtGui import QColor
    from models import image_list_model
    from utils import thumbnail_cache

    monkeypatch.setattr(thumbnail_cache, "get_thumbnail_cache", lambda: SimpleNamespace(enabled=False))
    decoded = PILImage.new("RGB", (100, 100), "red")
    decoded.paste("blue", (50, 0, 100, 100))
    monkeypatch.setattr(image_list_model.pilimage, "open", lambda path: decoded)
    crop = QRect(50, 0, 50, 100)

    thumbnail, _, _, _ = image_list_model.load_thumbnail_data(tmp_path / "source.jxl", crop, 50, False)

    assert crop == QRect(50, 0, 50, 100)
    assert thumbnail.size().toTuple() == (50, 100)
    assert thumbnail.pixelColor(0, 50) == QColor("blue")
