import os
from pathlib import Path
import sys


os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[1]
TAGGUI_ROOT = ROOT / 'taggui'
sys.path.insert(0, str(TAGGUI_ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from models.image_list_model import ImageListModel


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
