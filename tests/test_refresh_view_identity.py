from pathlib import Path
from types import SimpleNamespace
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'taggui'))
from models.image_list_model import ImageListModel


def test_refresh_rebuilds_current_filter_instead_of_installing_old_pages(tmp_path):
    applied, queries, requests = [], [], []
    def count(**kwargs):
        queries.append(kwargs)
        return 7
    model = SimpleNamespace(
        _new_media_refresh_generation=1, _page_load_generation=8,
        _directory_path=tmp_path, _db=SimpleNamespace(count=count),
        _active_load_options=None, _filter_sql='is_video = 1', _filter_bindings=(),
        prepare_ordered_view=lambda **kwargs: requests.append(kwargs),
        _reload_paginated_model_after_db_update=lambda **kwargs: applied.append(kwargs) or [0],
    )
    result = dict(supported=True, generation=1, page_generation=7,
                  directory_path=str(tmp_path), new_total=20,
                  pages_to_reload=[0], preloaded_pages={0: ['old-sort-image']})
    ImageListModel.apply_refresh_new_media_only_result(model, result)
    assert applied == [] and queries == []
    assert requests == [dict(reason='refresh', refresh_scope=False)]
    assert result['model_refresh_pending']
    assert result['view_changed_during_refresh']
    applied.clear()
    queries.clear()
    result.pop('view_changed_during_refresh')
    result['page_generation'] = 8
    ImageListModel.apply_refresh_new_media_only_result(model, result)
    assert applied == [dict(new_total=20, preloaded_pages={0: ['old-sort-image']})]
    assert queries == []  # An unchanged view keeps the prepared worker result.
    applied.clear()
    result['directory_path'] = str(tmp_path / 'previous')
    ImageListModel.apply_refresh_new_media_only_result(model, result)
    assert result['stale'] and applied == []


def test_refresh_does_not_reinstall_pages_evicted_since_scan_started():
    installed, loaded = [], []
    model = SimpleNamespace(
        _paginated_mode=True, PAGE_SIZE=1000, _pages={14: ['visible']},
        _page_load_order=[14], _page_load_lock=threading.Lock(),
        _advance_page_load_generation=lambda: None,
        _load_images_from_db=lambda page: (loaded.append(page) or ['fresh'], []),
        beginResetModel=lambda: None, endResetModel=lambda: None,
        _store_page=lambda page, images: installed.append((page, images)),
        total_count_changed=SimpleNamespace(emit=lambda count: None),
        _emit_paginated_layout_refresh=lambda: None,
        _start_paginated_enrichment=lambda **kwargs: None,
    )
    pages = ImageListModel._reload_paginated_model_after_db_update(
        model, new_total=27000,
        preloaded_pages={0: ['old-window'], 1: ['old-window'], 14: ['prepared']},
    )
    assert pages == [14]
    assert installed == [(14, ['prepared'])]
    assert loaded == []


def test_limited_scope_refresh_is_worker_owned_and_survives_filter_replacement(tmp_path, monkeypatch):
    from PySide6.QtCore import QItemSelectionModel
    from PySide6.QtGui import QImage
    from qt_test_helpers import APP, pump
    from models.proxy_image_list_model import ProxyImageListModel
    from utils.image import Image
    from utils.image_index_db import ImageIndexDB
    from utils.load_options import LimitedLoadOptions
    db = ImageIndexDB(tmp_path)
    records = []
    for i in range(605):
        path = tmp_path / f'{i:04}.png'
        path.touch()
        records.append(Image(path, (32,32)))
    db.conn.executemany('INSERT INTO images(file_name,width,height,is_video,mtime,rating) VALUES(?,32,32,0,1,1)',
                        [(item.path.name,) for item in records])
    db.conn.commit()
    model = ImageListModel(120, ',')
    proxy = ProxyImageListModel(model, None, ',')
    model.proxy_image_list_model = proxy
    model.image_list_selection_model = QItemSelectionModel(proxy)
    model._db, model._directory_path, model._paginated_mode = db, tmp_path, True
    model._active_load_options = LimitedLoadOptions(600, 'name', 'ASC')
    model._new_media_refresh_generation = 1
    model._set_scope_from_rel_paths([image.path.name for image in records[:600]])
    model._pages, model._total_count = {0: records[:600]}, 600
    model._start_paginated_enrichment = lambda **kwargs: None
    model._sort_field, model._sort_dir = 'file_name', 'ASC'
    added = tmp_path / '000-before.png'
    added.touch()
    db.conn.execute('INSERT INTO images(file_name,width,height,is_video,mtime,rating) VALUES(?,32,32,0,1,2)', (added.name,))
    db.conn.commit()
    started, release = threading.Event(), threading.Event()
    original = ImageIndexDB.get_limited_paths
    gui_thread = threading.get_ident()
    calls = []
    def blocked(owner, options):
        calls.append(threading.get_ident())
        assert threading.get_ident() != gui_thread
        started.set()
        assert release.wait(4)
        return original(owner, options)
    monkeypatch.setattr(ImageIndexDB, 'get_limited_paths', blocked)
    monkeypatch.setattr(db, 'count', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('GUI count')))
    try:
        result = dict(supported=True, generation=model._new_media_refresh_generation,
            page_generation=model._page_load_generation, directory_path=str(tmp_path), new_total=606,
            pages_to_reload=[0], preloaded_pages={})
        model.apply_refresh_new_media_only_result(result)
        assert result['model_refresh_pending'] and started.wait(1)
        ticks = []
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: ticks.append(True))
        APP.processEvents()
        assert ticks
        model._text_filter_sql, model._text_filter_bindings = 'rating = ?', (2,)
        model._rebuild_combined_filter()
        model.prepare_ordered_view(reason='filter')
        release.set()
        pump(lambda: model._view_prepare_owner is None)
        assert calls and all(value != gui_thread for value in calls)
        assert model._total_count == 1
        assert model._pages[0][0].path == added
        assert added.name in model._scope_rel_paths and records[599].path.name not in model._scope_rel_paths
        assert len(model._scope_rel_paths) == 600 and len(model._scope_bindings) == 1
        assert model._filter_bindings == model._scope_bindings + (2,)
    finally:
        release.set()
        model._view_prepare_task.drain()
        model.shutdown_background_workers()
        db.close()


def test_reusing_large_scope_does_not_wait_for_an_unrelated_writer(tmp_path):
    from utils.image_index_db import ImageIndexDB
    db = ImageIndexDB(tmp_path)
    other = ImageIndexDB(tmp_path)
    paths = [f'generated-{i}.png' for i in range(1000)]
    try:
        identity = db.register_path_scope(paths)
        other.conn.execute('BEGIN IMMEDIATE')
        db.conn.execute('PRAGMA busy_timeout=5')
        assert db.register_path_scope(reversed(paths)) == identity
        assert not db.conn.in_transaction
    finally:
        other.conn.rollback()
        other.close()
        db.close()
