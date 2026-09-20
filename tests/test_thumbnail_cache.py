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


def test_paginated_thumbnail_job_survives_prepend_and_checks_crop():
    from types import SimpleNamespace
    from PySide6.QtCore import Qt
    from utils.image import Image

    calls = []
    def submit(*args):
        future = Future()
        calls.append((args, future))
        return future

    target = Image(Path("target.png"), (800, 1200))
    placeholder = object()
    model = SimpleNamespace(
        _paginated_mode=True, PAGE_SIZE=1000,
        _pages={14: [target]}, _page_load_lock=threading.Lock(),
        _touch_page=lambda page: None, _pause_thumbnail_loading=False,
        _thumbnail_lock=threading.Lock(), _thumbnail_futures={},
        _load_executor=SimpleNamespace(submit=submit),
        _load_thumbnail_async=lambda *args: None,
        _get_placeholder_icon=lambda: placeholder,
    )
    def request(row):
        index = SimpleNamespace(row=lambda: row, isValid=lambda: True)
        return ImageListModel.data(model, index, Qt.DecorationRole)

    assert request(0) is placeholder
    assert calls[0][0][-1] == 14000
    model._pages[13] = [Image(Path(f"previous-{i}.png"), (100, 100)) for i in range(1000)]
    assert request(1000) is placeholder
    assert len(calls) == 1

    # Even a completed old crop must be ignored after editing the image.
    calls[0][1].set_result((None, True))
    target.crop = QRect(0, 0, 400, 400)
    assert request(1000) is placeholder
    assert len(calls) == 2


def test_thumbnail_completion_resolves_global_identity_after_prepend():
    from types import SimpleNamespace
    from utils.image import Image

    target = Image(Path("target.png"), None)
    previous = Image(Path("previous.png"), (100, 100))
    model = SimpleNamespace(
        _paginated_mode=True, PAGE_SIZE=1000,
        get_loaded_row_for_global_index=lambda idx: 1000 if idx == 14000 else -1,
        get_image_at_row=lambda row: target if row == 1000 else previous,
        get_global_index_for_row=lambda row: 14000,
        _recent_dimension_update_pages=set(), _db=None, _save_executor=None,
        _schedule_dimensions_updated=lambda: None,
        _pending_thumbnail_updates=set(),
        _thumbnail_batch_timer=SimpleNamespace(isActive=lambda: False, start=lambda: None),
    )
    ImageListModel._notify_thumbnail_ready(model, 14000, 800, 1200, str(target.path))
    assert target.dimensions == (800, 1200)
    assert previous.dimensions == (100, 100)
    assert model._pending_thumbnail_updates == {1000}
    assert model._recent_dimension_update_pages == {14}
    # Evicted or reordered completion cannot modify the new occupant.
    ImageListModel._notify_thumbnail_ready(model, 13000, 1, 2, str(target.path))
    ImageListModel._notify_thumbnail_ready(model, 14000, 1, 2, "other.png")
    assert target.dimensions == (800, 1200)


def test_restart_thumbnail_preload_cancels_outside_callback_lock(monkeypatch):
    from types import SimpleNamespace
    from utils import thumbnail_cache

    # Stop at the cache accessor after cancellation; no Qt timers or disk I/O.
    class StopAfterCancellation(Exception):
        pass
    monkeypatch.setattr(thumbnail_cache, "get_thumbnail_cache",
                        lambda: (_ for _ in ()).throw(StopAfterCancellation()))
    tracker = SimpleNamespace(images=[None] * 5001,
                              _thumbnail_lock=threading.Lock(), _thumbnail_futures={})
    future = Future()
    lock_available = []
    def callback(completed):
        acquired = tracker._thumbnail_lock.acquire(blocking=False)
        lock_available.append(acquired)
        if acquired:
            tracker._thumbnail_lock.release()
    future.add_done_callback(callback)
    tracker._thumbnail_futures[0] = (future, Path("queued.png"))
    try:
        ImageListModel._preload_thumbnails_async(tracker)
    except StopAfterCancellation:
        pass
    assert future.cancelled()
    assert lock_available == [True]
    assert tracker._thumbnail_futures == {}
