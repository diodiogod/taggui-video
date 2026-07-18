from pathlib import Path
from concurrent.futures import Future
import sys
import threading
from types import MethodType


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
