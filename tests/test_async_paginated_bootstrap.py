import os
from pathlib import Path
import sys
import threading


os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[1]
TAGGUI_ROOT = ROOT / 'taggui'
sys.path.insert(0, str(TAGGUI_ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from models.image_list_model import ImageListModel
from utils.load_options import LimitedLoadOptions


def test_initial_paginated_page_is_queued_without_sync_loading(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    model = ImageListModel(256, ', ')
    requested_pages = []
    synchronous_pages = []
    activity_started = []

    monkeypatch.setattr(model, '_request_page_load', requested_pages.append)
    monkeypatch.setattr(model, '_load_page_sync', synchronous_pages.append)
    monkeypatch.setattr(model, '_emit_paginated_layout_refresh', lambda: None)
    model.initial_page_load_started.connect(lambda: activity_started.append(True))

    try:
        model._load_directory_paginated(
            Path(tmp_path),
            image_paths=None,
            file_paths=None,
            db_synced=True,
            preindexed_count=1000,
        )

        assert requested_pages == [0]
        assert synchronous_pages == []
        assert activity_started == [True]
        assert model._initial_page_load_pending is True
    finally:
        if model._db is not None:
            model._db.close()
        model.shutdown_background_workers()
        model.deleteLater()
        app.processEvents()


def test_adjacent_bootstrap_pages_wait_for_page_zero(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    model = ImageListModel(256, ', ')
    requested_pages = []

    monkeypatch.setattr(model, '_request_page_load', requested_pages.append)
    monkeypatch.setattr(model, '_emit_paginated_layout_refresh', lambda: None)

    try:
        model._load_directory_paginated(
            Path(tmp_path),
            image_paths=None,
            file_paths=None,
            db_synced=True,
            preindexed_count=3000,
        )

        assert requested_pages == [0]
        assert model._initial_warm_pages == (1, 2)
    finally:
        if model._db is not None:
            model._db.close()
        model.shutdown_background_workers()
        model.deleteLater()
        app.processEvents()


def test_initial_page_completion_reuses_existing_debounce_timer(monkeypatch):
    app = QApplication.instance() or QApplication([])
    model = ImageListModel(256, ', ')
    enrichment_requests = []
    model._paginated_mode = True
    model._pages = {0: []}
    model._bootstrap_complete = True
    model._initial_page_load_pending = True
    model._initial_warm_pages = ()
    model._post_bootstrap_debounce_timer = QTimer()
    model._post_bootstrap_debounce_timer.setSingleShot(True)
    model._post_bootstrap_debounce_timer.timeout.connect(model._emit_pages_updated)
    monkeypatch.setattr(
        model,
        '_start_paginated_enrichment',
        lambda **kwargs: enrichment_requests.append(kwargs),
    )

    try:
        model._on_page_loaded_signal(0)

        assert model._initial_page_load_pending is False
        assert enrichment_requests == [{'window_pages': {0}, 'scope': 'window'}]
    finally:
        model.shutdown_background_workers()
        model.deleteLater()
        app.processEvents()


def test_stale_page_worker_cannot_mutate_reloaded_model(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    model = ImageListModel(256, ', ')
    load_started = threading.Event()
    release_load = threading.Event()
    emitted_pages = []

    def blocking_load(_page_num, **_kwargs):
        load_started.set()
        assert release_load.wait(timeout=5)
        return [object()], []

    monkeypatch.setattr(model, '_load_images_from_db', blocking_load)
    model.page_loaded.connect(lambda page, generation: emitted_pages.append((page, generation)))
    model._loading_pages.add(0)
    old_generation = model._page_load_generation
    snapshot = {
        'db': object(),
        'directory_path': Path(tmp_path),
        'sort_field': 'mtime',
        'sort_dir': 'DESC',
        'filter_sql': '',
        'filter_bindings': (),
        'random_seed': 0,
    }
    worker = threading.Thread(
        target=model._load_page_async,
        args=(0, old_generation, snapshot),
    )

    try:
        worker.start()
        assert load_started.wait(timeout=5)
        model._advance_page_load_generation()
        model._loading_pages.add(0)  # A new-generation request for the same page.
        release_load.set()
        worker.join(timeout=5)
        app.processEvents()

        assert worker.is_alive() is False
        assert model._pages == {}
        assert model._loading_pages == {0}
        assert emitted_pages == []
    finally:
        release_load.set()
        worker.join(timeout=5)
        model.shutdown_background_workers()
        model.deleteLater()
        app.processEvents()


def test_limited_validation_refreshes_current_model_without_folder_reload(
    tmp_path,
    monkeypatch,
):
    app = QApplication.instance() or QApplication([])
    model = ImageListModel(256, ', ')
    directory_path = Path(tmp_path)
    limited_paths = ['new.png', 'existing.png']
    reload_calls = []

    class FakeDB:
        def get_limited_paths(self, _load_options):
            return list(limited_paths)

        def count(self, **_kwargs):
            return len(limited_paths)

    model._paginated_mode = True
    model._directory_path = directory_path
    model._db = FakeDB()
    model._active_load_options = LimitedLoadOptions(limit=1000)
    model._path_validation_generation = 7
    model._pending_path_validation_result = {
        'generation': 7,
        'directory_path': directory_path,
        'changes_detected': True,
        'added_count': 1,
        'removed_count': 0,
        'added_db_paths': ['new.png'],
        'tag_updates_count': 0,
        'ideogram_updates_count': 0,
        'db_synced': True,
    }
    monkeypatch.setattr(
        model,
        '_reload_paginated_model_after_db_update',
        lambda **kwargs: reload_calls.append(kwargs) or [0],
    )
    monkeypatch.setattr(
        model,
        'load_directory',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError('limited validation must not reload the folder')
        ),
    )

    try:
        model._apply_pending_path_validation()

        assert model._scope_rel_paths == tuple(limited_paths)
        assert reload_calls == [{
            'new_total': len(limited_paths),
            'touched_paths': [directory_path / 'new.png'],
            'preloaded_pages': None,
        }]
        assert model._path_validation_satisfied_generation == 7
    finally:
        model._db = None
        model.shutdown_background_workers()
        model.deleteLater()
        app.processEvents()
