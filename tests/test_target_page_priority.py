from concurrent.futures import CancelledError
import threading

from qt_test_helpers import APP, pump
from models.image_list_model import ImageListModel
from utils.image import Image


def make_model(tmp_path, monkeypatch, loader):
    model = ImageListModel(120, ',')
    model._paginated_mode = True
    model._total_count = 13000
    model._directory_path = tmp_path
    model._db = object()
    model._bootstrap_complete = True
    monkeypatch.setattr(model, '_load_images_from_db', loader)
    monkeypatch.setattr(model, '_start_paginated_enrichment', lambda **kwargs: None)
    return model


def close_model(model):
    executor = model._page_executor
    model._db = None
    model.shutdown_background_workers()
    executor.shutdown(wait=True, cancel_futures=True)
    model.deleteLater()
    APP.processEvents()


def prepare(model, target, **kwargs):
    return model.prepare_target_window(target * 1000, sync_target_page=False,
        adjacent_only=True, target_first=True, restart_enrichment=False, **kwargs)


def test_target_runs_alone_then_both_neighbors_are_available(tmp_path, monkeypatch):
    calls = []
    started, release = threading.Event(), threading.Event()
    def load(page, **kwargs):
        calls.append(page)
        if page == 9:
            started.set()
            assert release.wait(3)
        return [Image(tmp_path / f'{page}.png', (800, 600))], []
    model = make_model(tmp_path, monkeypatch, load)
    try:
        prepare(model, 9)
        assert started.wait(3)
        model._request_page_load(8)  # Direct geometry/boundary request must also wait.
        model._request_page_load(10)
        assert calls == [9]
        release.set()
        pump(lambda: bool(model._pages.get(9)))
        assert model._target_page_first is None
        model.prepare_target_window(9000, sync_target_page=False, adjacent_only=True,
            restart_enrichment=False)
        pump(lambda: {8, 9, 10}.issubset(model._pages))
        assert set(calls) == {8, 9, 10}
    finally:
        release.set()
        close_model(model)


def test_replacement_cancels_running_neighbor_before_target(tmp_path, monkeypatch):
    old_started, canceled = threading.Event(), threading.Event()
    calls = []
    def load(page, **kwargs):
        calls.append(page)
        if page == 8:
            old_started.set()
            assert kwargs['cancel_event'].wait(3)
            canceled.set()
            raise CancelledError()
        return [Image(tmp_path / f'{page}.png', (800, 600))], []
    model = make_model(tmp_path, monkeypatch, load)
    try:
        model._request_page_load(8)
        assert old_started.wait(3)
        prepare(model, 9)
        pump(lambda: bool(model._pages.get(9)))
        assert canceled.wait(3)
        assert 8 not in model._pages
        assert calls == [8, 9]
        assert not model._page_load_cancellations
    finally:
        close_model(model)


def test_failed_target_does_not_leave_neighbor_requests_blocked(tmp_path, monkeypatch):
    calls = []
    def load(page, **kwargs):
        calls.append(page)
        if page == 9:
            raise OSError('Synthetic failed page read')
        return [Image(tmp_path / f'{page}.png', (800, 600))], []
    model = make_model(tmp_path, monkeypatch, load)
    try:
        prepare(model, 9)
        pump(lambda: 9 not in model._loading_pages)
        model._request_page_load(8)
        pump(lambda: bool(model._pages.get(8)))
        assert calls == [9, 8]
        model._advance_page_load_generation()
        assert model._target_page_first is None
    finally:
        close_model(model)


def test_new_jump_owns_gate_when_an_old_delivery_is_already_queued(tmp_path, monkeypatch):
    finished, new_started, release = threading.Event(), threading.Event(), threading.Event()
    def load(page, **kwargs):
        if page == 3:
            new_started.set()
            assert release.wait(3)
        if page == 9:
            finished.set()
        return [Image(tmp_path / f'{page}.png', (800, 600))], []
    model = make_model(tmp_path, monkeypatch, load)
    try:
        prepare(model, 9)
        assert finished.wait(3)
        # Wait on the worker future only in the harness, without delivering Qt
        # events, to exercise an already-queued old result during replacement.
        model._page_load_futures[(model._page_load_generation, 9)].result(timeout=3)
        prepare(model, 3)
        assert new_started.wait(3)
        APP.processEvents()
        assert model._target_page_first == (model._page_load_generation, 3)
        model._request_page_load(2)
        assert 2 not in model._loading_pages
        release.set()
        pump(lambda: bool(model._pages.get(3)))
        assert model._target_page_first is None
    finally:
        release.set()
        close_model(model)
