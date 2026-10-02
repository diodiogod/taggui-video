from concurrent.futures import ThreadPoolExecutor
import gc
import threading
import time
import weakref

from taggui.utils.demand_executor import DemandExecutor
from taggui.utils.thumbnail_save_queue import ThumbnailSaveQueue


def test_visible_demand_bypasses_preload_and_pressure_preserves_required_work():
    executor = DemandExecutor(max_workers=1, max_pending=16)
    release, started = threading.Event(), threading.Event()
    def block():
        started.set()
        release.wait(5)
    order = []
    try:
        executor.submit(block)
        assert started.wait(2)
        required = executor.submit(lambda: order.append('required'))
        preload = [executor.submit_priority(10, lambda i=i: order.append(i)) for i in range(200)]
        urgent = executor.submit_priority(0, lambda: order.append('visible'))
        assert executor.pending_count <= 17  # 16 hints plus nondisposable work.
        assert sum(f.cancelled() for f in preload) >= 184
        release.set()
        urgent.result(2)
        required.result(2)
        assert order[0] == 'visible'
        assert not required.cancelled()
    finally:
        release.set()
        executor.shutdown(wait=True, cancel_futures=True)


def test_cancellation_releases_pending_arguments_before_active_decoder_finishes():
    class Payload:
        pass
    executor = DemandExecutor(max_workers=1)
    release, started = threading.Event(), threading.Event()
    def block():
        started.set()
        release.wait(5)
    try:
        executor.submit(block)
        assert started.wait(2)
        payload = Payload()
        owner = weakref.ref(payload)
        queued = executor.submit_priority(10, lambda value: None, payload)
        del payload
        assert owner() is not None
        assert queued.cancel()
        gc.collect()
        assert owner() is None
        assert executor.pending_count == 0
    finally:
        release.set()
        executor.shutdown(wait=True, cancel_futures=True)


def test_promote_and_shutdown_without_cancellation_drain_accepted_work():
    executor = DemandExecutor(max_workers=1)
    release, started = threading.Event(), threading.Event()
    def block():
        started.set()
        release.wait(5)
    order = []
    executor.submit(block)
    assert started.wait(2)
    first = executor.submit_priority(10, lambda: order.append(1))
    second = executor.submit_priority(10, lambda: order.append(2))
    executor.promote(second, 0)
    executor.shutdown(wait=False)
    release.set()
    second.result(2)
    first.result(2)
    executor.shutdown(wait=True)
    assert order == [2, 1]


def test_save_queue_bounds_bytes_deduplicates_and_releases_old_pixels():
    queue = ThumbnailSaveQueue(max_bytes=12, max_items=3)
    queue.put('same', 'old', 6)
    queue.put('same', 'new', 7)
    assert len(queue) == 1 and queue.retained_bytes == 7
    queue.put('next', 'next', 6)
    assert len(queue) == 1 and queue.retained_bytes == 6
    queue.put('oversized', 'oversized', 30)
    assert queue.pop() == 'next' and queue.pop() is None
    assert queue.retained_bytes == 0
    for i in range(100):
        queue.put(i, i, 1)
    assert len(queue) == 3 and queue.retained_bytes == 3
    queue.clear()
    assert queue.retained_bytes == 0


def test_controlled_backlog_records_priority_latency(capsys):
    """Synthetic 2 ms jobs measure scheduling only, not media or first paint."""
    timings = []
    for prioritized in (False, True):
        executor = DemandExecutor(max_workers=1) if prioritized else ThreadPoolExecutor(max_workers=1)
        release, started = threading.Event(), threading.Event()
        def block():
            started.set()
            release.wait(5)
        seen = []
        def work(value):
            time.sleep(.002)
            seen.append(value)
        try:
            executor.submit(block)
            assert started.wait(2)
            for i in range(100):
                if prioritized:
                    executor.submit_priority(10, work, i)
                else:
                    executor.submit(work, i)
            urgent = (executor.submit_priority(0, work, 'visible') if prioritized
                      else executor.submit(work, 'visible'))
            begin = time.perf_counter()
            release.set()
            urgent.result(3)
            timings.append((time.perf_counter() - begin) * 1000)
            assert seen.index('visible') == (0 if prioritized else 100)
        finally:
            release.set()
            executor.shutdown(wait=True, cancel_futures=True)
    print(f'Synthetic backlog urgent wait: FIFO={timings[0]:.2f}ms prioritized={timings[1]:.2f}ms')
    captured = capsys.readouterr()
    with capsys.disabled():
        print(captured.out.strip())


def test_model_cache_flush_retains_one_bounded_queue_and_saves_small_idle_batches(tmp_path):
    from types import MethodType, SimpleNamespace
    from PySide6.QtGui import QImage
    from models.image_list_model import ImageListModel
    callbacks, saved = [], []
    model = SimpleNamespace(_shutdown_requested=False, _is_scrolling=True,
        _save_executor=SimpleNamespace(submit=callbacks.append),
        _pending_cache_saves=ThumbnailSaveQueue(),
        _cache_flush_lock=threading.Lock(), _cache_flush_scheduled=False,
        _save_thumbnail_worker=lambda *args: saved.append(args[0]))
    model._flush_pending_cache_saves = MethodType(ImageListModel._flush_pending_cache_saves, model)
    for i in range(45):
        pixels = QImage(512, 512, QImage.Format_RGB32)
        ImageListModel._queue_thumbnail_save(model, tmp_path/f'{i}.png', None, 512, pixels, None)
    assert len(model._pending_cache_saves) == 32
    assert model._pending_cache_saves.retained_bytes == 32*1024*1024
    assert callbacks == []
    model._is_scrolling = False
    model._flush_pending_cache_saves()
    model._flush_pending_cache_saves()
    assert len(callbacks) == 1  # No decoded-image payload backlog in the executor.
    callbacks.pop()()
    assert len(saved) == 32 and len(model._pending_cache_saves) == 0
    ImageListModel._queue_thumbnail_save(model, tmp_path/'last.png', None, 512, pixels, None)
    assert len(callbacks) == 1  # Fewer than 50 pending images still reach disk.
    callbacks.pop()()
    assert saved[-1].name == 'last.png'
