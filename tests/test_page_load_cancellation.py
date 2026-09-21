from concurrent.futures import CancelledError, Future
from pathlib import Path
from types import MethodType, SimpleNamespace
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "taggui"))
from models.image_list_model import ImageListModel


def test_secondary_browser_counts_paginated_tags_without_thumbnail_recounts():
    from PySide6.QtCore import Qt
    from widgets.secondary_browser import SecondaryBrowser
    calls = []
    stats = [{"tag": "example", "count": 1200}]
    browser = SimpleNamespace(
        image_list_model=SimpleNamespace(is_paginated=True, get_all_tags_stats=lambda: stats),
        tag_counter_model=SimpleNamespace(set_tags_from_db=lambda value: calls.append(value)),
    )
    browser._count_tags = lambda: SecondaryBrowser._count_tags(browser)
    SecondaryBrowser._count_tags_after_data_change(browser, None, None, [Qt.DecorationRole])
    assert calls == []
    SecondaryBrowser._count_tags_after_data_change(browser, None, None, [Qt.DisplayRole])
    assert calls == [stats]


def test_queued_repair_completion_rejects_newer_navigation_or_folder(tmp_path):
    calls = []
    model = SimpleNamespace(
        _enrichment_generation=4, _page_load_generation=2, _directory_path=tmp_path,
        _shutdown_requested=False,
        _notify_enrichment_complete=lambda **kwargs: calls.append(kwargs),
        enrichment_tags_updated=SimpleNamespace(emit=lambda: calls.append("tags")),
    )
    deliver = ImageListModel._on_paginated_enrichment_finished
    deliver(model, (3, (2, tmp_path), False))
    deliver(model, (4, (1, tmp_path), False))
    deliver(model, (4, (2, tmp_path / "old"), False))
    assert not calls
    deliver(model, (4, (2, tmp_path), False))
    assert calls == [{"tags_changed": False}]
    deliver(model, (3, (2, tmp_path), True))
    assert calls == [{"tags_changed": False}, "tags"]


def test_sort_generation_invalidates_completed_and_running_repairs():
    event = threading.Event()
    model = SimpleNamespace(
        _enrichment_cancelled=event, _enrichment_generation=4,
        _enrichment_running=True, _enrichment_zero_scope="window",
        _enrichment_zero_target_pages={9},
        _page_load_lock=threading.RLock(), _page_load_cancellations={},
        _page_load_futures={}, _page_load_generation=2,
        _loading_pages=set(), _pending_page_results={},
    )
    assert ImageListModel._advance_page_load_generation(model) == 3
    assert event.is_set() and model._enrichment_generation == 5
    assert not model._enrichment_running
    assert model._enrichment_zero_target_pages is None


def test_cache_flag_flush_cannot_write_into_replacement_folder():
    callbacks, writes = [], []
    def make_db():
        return SimpleNamespace(
            _db_lock=threading.Lock(), conn=SimpleNamespace(
                cursor=lambda: SimpleNamespace(executemany=lambda sql, rows: writes.extend(rows)),
                commit=lambda: None,
            ),
        )
    old_db, new_db = make_db(), make_db()
    model = SimpleNamespace(
        _shutdown_requested=False, _db=old_db,
        _save_executor=SimpleNamespace(submit=callbacks.append),
        _pending_db_cache_flags_lock=threading.Lock(),
        _pending_db_cache_flags=[(old_db, "same.png")],
    )
    ImageListModel._flush_db_cache_flags(model)
    model._db = new_db
    callbacks.pop()()
    assert writes == []
    model._pending_db_cache_flags = [(old_db, "wrong.png"), (new_db, "right.png"), (new_db, "right.png")]
    ImageListModel._flush_db_cache_flags(model)
    callbacks.pop()()
    assert writes == [("right.png",)]


def test_loaded_path_lookup_does_not_select_same_basename_in_other_folder(tmp_path):
    first = SimpleNamespace(path=tmp_path / "first" / "same.png")
    second = SimpleNamespace(path=tmp_path / "second" / "same.png")
    model = SimpleNamespace(
        _paginated_mode=True, _directory_path=tmp_path,
        _page_load_lock=threading.RLock(), _pages={2: [first], 9: [second]},
    )
    assert ImageListModel.get_loaded_row_for_path(model, second.path) == 1
    assert ImageListModel.get_loaded_row_for_path(model, Path("second/same.png")) == 1
    assert ImageListModel.get_loaded_row_for_path(model, tmp_path / "missing/same.png") == -1


def test_cancel_running_old_page_preserves_new_job_for_same_page():
    old_event = threading.Event()
    old_future = Future()
    old_future.set_running_or_notify_cancel()
    replacement_event = threading.Event()
    model = SimpleNamespace(
        _page_load_lock=threading.RLock(), _page_load_generation=1,
        _page_load_futures={(1, 2): old_future},
        _page_load_cancellations={(1, 2): old_event},
        _loading_pages={2}, _pending_page_results={},
        page_loaded=SimpleNamespace(emit=lambda *args: None),
    )
    ImageListModel.cancel_pending_loads_except(model, {10})
    assert old_event.is_set() and 2 not in model._loading_pages
    model._loading_pages.add(2)
    model._page_load_cancellations[(1, 2)] = replacement_event
    # Old worker unwinds after the same page was requested again.
    ImageListModel._load_page_async(model, 2, 1, {"cancel_event": old_event})
    assert 2 in model._loading_pages
    assert model._page_load_cancellations[(1, 2)] is replacement_event
    assert not model._pending_page_results


def test_target_priority_keeps_running_immediate_neighbor():
    future = Future()
    future.set_running_or_notify_cancel()
    event = threading.Event()
    model = SimpleNamespace(
        _page_load_lock=threading.RLock(), _page_load_generation=1,
        _page_load_futures={(1, 9): future}, _page_load_cancellations={(1, 9): event},
        _loading_pages={9},
    )
    ImageListModel.cancel_pending_loads_except(model, {10}, running_keep_pages={9, 10, 11})
    assert not event.is_set() and model._loading_pages == {9}


def test_page_materialization_stops_before_more_sidecars_or_partial_delivery(tmp_path):
    event = threading.Event()
    reads = []
    for name in ("first.png", "second.png"):
        (tmp_path / name).touch()
    rows = [{"id": i, "file_name": name, "width": 800, "height": 1200, "is_video": False}
            for i, name in enumerate(("first.png", "second.png"))]
    def read(path):
        reads.append(path)
        event.set()
        return None
    model = SimpleNamespace(
        _filter_internal_db_tags=lambda tags: tags,
        _preferred_sidecar_meta_path=lambda path: path,
        _read_cached_sidecar_meta=read,
    )
    db = SimpleNamespace(get_tags_for_images=lambda ids: {})
    try:
        ImageListModel._images_from_db_rows(model, rows, db, tmp_path, cancel_event=event)
    except CancelledError:
        pass
    else:
        raise AssertionError("Cancelled page must not return partial images")
    assert reads == [tmp_path / "first.png"]


def test_dimension_delivery_rejects_previous_folder_with_same_filename(tmp_path):
    from utils.image import Image
    old_root, new_root = tmp_path / "old", tmp_path / "new"
    image = Image(new_root / "same.png", (100, 200))
    source = SimpleNamespace(
        _paginated_mode=True, _directory_path=new_root, _page_load_generation=2,
        _paginated_dimension_updates_lock=threading.Lock(),
        _pending_paginated_dimension_updates=[((1, old_root), [("same.png", (999, 888), None)])],
        _page_load_lock=threading.RLock(), _pages={0: [image]},
        _recent_dimension_update_pages=set(), _schedule_dimensions_updated=lambda: None,
    )
    ImageListModel._apply_pending_paginated_dimension_updates(source)
    assert image.dimensions == (100, 200)
    source._pending_paginated_dimension_updates = [((2, new_root), [("same.png", (800, 1200), None)])]
    ImageListModel._apply_pending_paginated_dimension_updates(source)
    assert image.dimensions == (800, 1200)
    assert source._recent_dimension_update_pages == {0}


def test_scoped_dimension_repair_does_not_recount_folder_tags():
    calls = []
    source = SimpleNamespace(
        enrichment_tags_updated=SimpleNamespace(emit=lambda: calls.append("recount")),
        enrichment_complete=SimpleNamespace(emit=lambda: calls.append("layout")),
    )
    ImageListModel._notify_enrichment_complete(source, tags_changed=False)
    assert calls == ["layout"]
    ImageListModel._notify_enrichment_complete(source)
    assert calls == ["layout", "recount", "layout"]


def test_dimension_path_cache_follows_rename(tmp_path):
    from utils.image import Image
    image = Image(tmp_path / "old.png", (100, 200))
    image._dimension_update_relative_path = ((tmp_path, image.path), "old.png")
    image.path = tmp_path / "new.png"
    source = SimpleNamespace(
        _paginated_mode=True, _directory_path=tmp_path, _page_load_generation=2,
        _paginated_dimension_updates_lock=threading.Lock(),
        _pending_paginated_dimension_updates=[((2, tmp_path), [("new.png", (800, 1200), None)])],
        _page_load_lock=threading.RLock(), _pages={0: [image]},
        _recent_dimension_update_pages=set(), _schedule_dimensions_updated=lambda: None,
    )
    ImageListModel._apply_pending_paginated_dimension_updates(source)
    assert image.dimensions == (800, 1200)
    assert image._dimension_update_relative_path == ((tmp_path, image.path), "new.png")


def test_obsolete_pages_release_both_workers_before_reading_remaining_files(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    started = threading.Barrier(3)
    release = threading.Event()
    delivered = threading.Event()
    reads = []
    old_rows = [{"id": i, "file_name": f"{i}.png", "width": 800, "height": 1200, "is_video": False}
                for i in range(30)]
    for row in old_rows:
        (tmp_path / row["file_name"]).touch()
    events = {page: threading.Event() for page in (1, 2)}
    def read(path):
        reads.append(path)
        if path.name == "0.png":
            started.wait(timeout=3)
            assert release.wait(3)
        return None
    model = SimpleNamespace(
        _page_load_lock=threading.RLock(), _page_load_generation=1,
        _page_load_futures={}, _page_load_cancellations={(1,p):event for p,event in events.items()},
        _loading_pages={1,2}, _pending_page_results={},
        page_loaded=SimpleNamespace(emit=lambda page, generation: delivered.set()),
        _filter_internal_db_tags=lambda tags: tags,
        _preferred_sidecar_meta_path=lambda path: path, _read_cached_sidecar_meta=read,
    )
    db = SimpleNamespace(get_tags_for_images=lambda ids: {})
    def load(page, **kwargs):
        return ImageListModel._images_from_db_rows(model, old_rows if page < 10 else [], db,
                                                  tmp_path, cancel_event=kwargs['cancel_event'])
    model._load_images_from_db = load
    with ThreadPoolExecutor(max_workers=2) as executor:
        try:
            for page, event in events.items():
                model._page_load_futures[(1,page)] = executor.submit(
                    ImageListModel._load_page_async, model, page, 1, {'db':db,'cancel_event':event})
            started.wait(timeout=3)
            ImageListModel.cancel_pending_loads_except(model, {10})
            current_event = threading.Event()
            model._page_load_cancellations[(1,10)] = current_event
            model._loading_pages.add(10)
            target = executor.submit(ImageListModel._load_page_async, model, 10, 1,
                                     {'db':db,'cancel_event':current_event})
            release.set()
            assert delivered.wait(3)
            target.result(timeout=3)
        finally:
            release.set()
    assert len(reads) == 2  # No remaining sidecars from either obsolete page.
    assert set(model._pending_page_results) == {(1,10)}
