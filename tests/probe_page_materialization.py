"""Opt-in read-only source hydration profile; run through run_isolated.py.

TAGGUI_AUDIT_SOURCE_INDEX selects the original index. Application services
only open its temporary SQLite backup. Source media and sidecars are read only.
"""
import os
assert os.environ.get('TAGGUI_SETTINGS_PATH'), 'Use tests/run_isolated.py'

import cProfile
import json
import ast
import subprocess
from pathlib import Path
import pstats
import sqlite3
import time

from qt_test_helpers import APP
from models.image_list_model import ImageListModel
from models import image_list_model
from utils.image_index_db import ImageIndexDB
from utils.settings import settings


def test_page_materialization_profile(tmp_path, monkeypatch):
    assert Path(settings.fileName()).resolve() == Path(os.environ['TAGGUI_SETTINGS_PATH']).resolve()
    source_path = Path(os.environ['TAGGUI_AUDIT_SOURCE_INDEX']).resolve(strict=True)
    target_path = tmp_path / '.taggui' / 'index.db'
    target_path.parent.mkdir()
    source = sqlite3.connect(source_path.as_uri() + '?mode=ro', uri=True)
    try:
        source.execute('PRAGMA query_only=ON')
        with sqlite3.connect(target_path) as destination:
            source.backup(destination)
    finally:
        source.close()
    db = ImageIndexDB(tmp_path)
    assert db.db_path.resolve() == target_path.resolve()
    model = ImageListModel(120, ',')
    cache_namespace = None
    if os.environ.get('TAGGUI_PROBE_SMALL_CACHE') == '1':
        source_text = subprocess.check_output(['git', 'show',
            '180c520:taggui/models/image_list_model.py'], encoding='utf-8')
        cls = next(node for node in ast.parse(source_text).body
                   if isinstance(node, ast.ClassDef) and node.name == 'ImageListModel')
        method = next(node for node in cls.body if isinstance(node, ast.FunctionDef)
                      and node.name == '_read_cached_sidecar_meta')
        namespace = dict(ImageListModel._read_cached_sidecar_meta.__globals__)
        cache_namespace = namespace
        exec(compile(ast.Module(body=[method], type_ignores=[]), '<checkpoint>', 'exec'), namespace)
        monkeypatch.setattr(model, '_read_cached_sidecar_meta',
                            namespace['_read_cached_sidecar_meta'].__get__(model))
        model._sidecar_meta_cache = {}
        model._sidecar_meta_cache_limit = 2048
    if os.environ.get('TAGGUI_PROBE_READER') == 'full':
        def read_full(path):
            payload = json.loads(path.read_text(encoding='UTF-8'))
            return payload if isinstance(payload, dict) and payload.get('version') == 1 else None
        monkeypatch.setattr(image_list_model, 'read_taggui_metadata', read_full)
    parse_calls = [0]
    reader = image_list_model.read_taggui_metadata
    def counted_reader(path):
        parse_calls[0] += 1
        return reader(path)
    monkeypatch.setattr(image_list_model, 'read_taggui_metadata', counted_reader)
    if cache_namespace is not None:
        cache_namespace['read_taggui_metadata'] = counted_reader
    try:
        if os.environ.get('TAGGUI_PROBE_CHURN') == '1':
            for page in (13, 6, 7, 8, 9, 10, 11, 13):
                rows = db.get_page(page, 1000, 'ctime', 'DESC')
                previous_parse_calls = parse_calls[0]
                started = time.perf_counter()
                images, missing = model._images_from_db_rows(rows, db, source_path.parent.parent)
                assert len(images) + len(missing) == len(rows)
                print('CHURN_PAGE_MS', page, round((time.perf_counter() - started) * 1000, 2),
                      'cache_entries', len(model._sidecar_meta_cache),
                      'file_parses', parse_calls[0] - previous_parse_calls)
            if os.environ.get('TAGGUI_PROBE_SMALL_CACHE') != '1':
                assert parse_calls[0] == previous_parse_calls, 'Unchanged first page was reparsed'
            return
        rows = db.get_page(13, 1000, 'ctime', 'DESC')
        profile = cProfile.Profile()
        profile.enable()
        images, missing = model._images_from_db_rows(rows, db, source_path.parent.parent)
        profile.disable()
        assert len(images) + len(missing) == len(rows)
        print('PROFILED_PAGE', len(images), 'missing', len(missing))
        pstats.Stats(profile).strip_dirs().sort_stats('cumulative').print_stats(22)
        for sample in range(3):
            model._sidecar_meta_cache.clear()
            started = time.perf_counter()
            images, missing = model._images_from_db_rows(rows, db, source_path.parent.parent)
            print('FRESH_METADATA_WARM_FILES_PAGE_MS', sample, round((time.perf_counter() - started) * 1000, 2))
            assert len(images) + len(missing) == len(rows)
        started = time.perf_counter()
        model._images_from_db_rows(rows, db, source_path.parent.parent)
        print('CACHED_PAGE_MS', round((time.perf_counter() - started) * 1000, 2))
    finally:
        executor = model._page_executor
        model.shutdown_background_workers()
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
        db.close()
        model.deleteLater()
        APP.processEvents()
