import threading
import sqlite3
import pytest
from types import SimpleNamespace

from qt_test_helpers import APP, pump, dispose_widget
from test_quick_sort_panel import _make_panel, _profile, _Controller
from widgets import quick_sort_panel
from controllers.quick_sort_controller import QuickSortController
from models.image_list_model import ImageListModel
from utils.image_index_db import ImageIndexDB
from utils.quick_sort import QuickSortProfile
from utils.quick_sort_count import count_quick_sort_requests


def test_snapshot_does_not_count_on_gui_and_worker_matches_scopes(tmp_path, monkeypatch):
    db = ImageIndexDB(tmp_path)
    model = ImageListModel(128, ',')
    try:
        for name, video in [('a.png', False), ('b.mp4', True), ('sub/c.png', False)]:
            db.save_info(name, 32, 32, video, 1)
        db.conn.commit()
        # A pending writer must not make a setup count initialize/migrate or wait.
        db.conn.execute("UPDATE images SET width = 33")
        model._db, model._directory_path, model._paginated_mode = db, tmp_path, True
        model._total_count = 3
        model._scope_sql, model._scope_bindings = '', ()
        model._filter_sql, model._filter_bindings = '', ()
        context = {'model': model, 'proxy': SimpleNamespace(tokenizer=None),
                   'image_list': SimpleNamespace()}
        controller = SimpleNamespace(
            _append_sql=QuickSortController._append_sql)
        controller._paginated_batch_for_profile = lambda profile, **kwargs: (
            QuickSortController._paginated_batch_for_profile(controller, profile, **kwargs))
        monkeypatch.setattr(db, 'count', lambda **kwargs: (_ for _ in ()).throw(
            AssertionError('GUI count')))
        for scope, videos, expected in [('current_folder', False, 1),
                                        ('all_loaded', False, 2), ('all_loaded', True, 3)]:
            profile = QuickSortProfile(name='test', source_scope=scope, include_subfolders=False,
                                       include_videos=videos)
            request = QuickSortController.prepare_count_request(controller, profile, context)
            assert 'model' not in request
            assert count_quick_sort_requests([request], threading.Event()) == [expected]
        model._filter_sql, model._filter_bindings = 'TAGGUI_NAME_MATCH(file_name, ?)', ('a',)
        profile = QuickSortProfile(name='filtered', source_scope='filtered', include_videos=True)
        request = QuickSortController.prepare_count_request(controller, profile, context)
        assert count_quick_sort_requests([request], threading.Event()) == [1]
        model._filter_sql, model._filter_bindings = '', ()
        for mode, expected in [('only', 1), ('all_except', 2)]:
            context['image_list'].get_selected_image_batch = lambda: model.create_paginated_image_batch(
                selection_mode=mode, selection_paths=('a.png',))
            profile = QuickSortProfile(name='selected', source_scope='selected', include_videos=True)
            request = QuickSortController.prepare_count_request(controller, profile, context)
            assert count_quick_sort_requests([request], threading.Event()) == [expected]
        reader = ImageIndexDB(tmp_path, read_only_path=db.db_path)
        try:
            assert reader.count_or_raise("file_name REGEXP ?", ('^a',)) == 1
            with pytest.raises(sqlite3.OperationalError, match='readonly'):
                reader.conn.execute('DELETE FROM images')
        finally:
            reader.close()
        # A closed reader must never reconnect through database initialization.
        with pytest.raises(sqlite3.OperationalError, match='unavailable'):
            reader.count_or_raise()
    finally:
        model.shutdown_background_workers()
        db.close()
        model.deleteLater()
        APP.processEvents()


def test_cancelled_count_does_not_open_database(monkeypatch):
    from utils import quick_sort_count
    monkeypatch.setattr(quick_sort_count, 'ImageIndexDB', lambda *a, **kw: pytest.fail('opened DB'))
    cancelled = threading.Event()
    cancelled.set()
    assert count_quick_sort_requests([{'directory': 'unused'}], cancelled) is None


def test_panel_accepts_only_latest_count_and_stays_responsive(tmp_path, monkeypatch):
    window, panel, _ = _make_panel(monkeypatch, tmp_path, [_profile('test', 'A', 'folder')])
    controller = _Controller(window)
    controller.prepare_count_request = lambda profile, context: {'count': controller.count}
    panel.bind_controller(controller)
    window.image_list_model._paginated_mode = True
    release, started = threading.Event(), threading.Event()

    def blocked(requests, cancelled):
        if requests[0]['count'] == 6:
            started.set()
            assert release.wait(4)
        return [request['count'] for request in requests]

    monkeypatch.setattr(quick_sort_panel, 'count_quick_sort_requests', blocked)
    try:
        window.show()
        panel.show()
        panel._count_refresh_timer.stop()
        panel._refresh_eligible_count()
        assert started.wait(1)
        APP.processEvents()
        assert panel._eligible_count_value is None
        controller.count = 12
        panel._invalidate_eligible_count()
        panel._count_refresh_timer.stop()
        panel._refresh_eligible_count()
        release.set()
        pump(lambda: panel._eligible_count_value == 12)
        assert controller.estimate_calls == 0
        assert panel._count_task in window.image_list_model._auxiliary_count_readers
        panel.hide()
        assert panel._count_owner is None
    finally:
        release.set()
        panel._count_task.drain()
        dispose_widget(window)
        APP.processEvents()


@pytest.mark.parametrize('action', ['hide', 'error'])
def test_hidden_or_failed_count_cannot_enable_start(tmp_path, monkeypatch, action):
    window, panel, _ = _make_panel(monkeypatch, tmp_path, [_profile('test', 'A', 'folder')])
    controller = _Controller(window)
    controller.prepare_count_request = lambda profile, context: {'count': 6}
    panel.bind_controller(controller)
    window.image_list_model._paginated_mode = True
    release, started = threading.Event(), threading.Event()

    def blocked(requests, cancelled):
        started.set()
        assert release.wait(4)
        if action == 'error':
            raise sqlite3.OperationalError('synthetic failure')
        return [6] * len(requests)

    monkeypatch.setattr(quick_sort_panel, 'count_quick_sort_requests', blocked)
    try:
        window.show()
        panel.show()
        panel._count_refresh_timer.stop()
        panel._refresh_eligible_count()
        pump(started.is_set)
        if action == 'hide':
            panel.hide()
        release.set()
        pump(lambda: panel._count_task._active is None)
        assert panel._eligible_count_value is None
        assert not panel.is_ready
        if action == 'error':
            assert panel.validation_chip.text() == 'COUNT ERROR'
    finally:
        release.set()
        panel._count_task.drain()
        dispose_widget(window)
        APP.processEvents()
