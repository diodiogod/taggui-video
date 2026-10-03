"""Opt-in Qt jump probe. Default synthetic; explicit source index enables
read-only sidecar hydration against a database backup. Run through run_isolated.
TAGGUI_PROBE_BASELINE=1 extracts only the checkpoint's metadata-cache method.
TAGGUI_PROBE_PARALLEL_PAGES=1 restores the previous window-dispatch method.
"""
import os
assert os.environ.get('TAGGUI_SETTINGS_PATH'), 'Use tests/run_isolated.py'

import ast
import subprocess
import time
import sqlite3
import gc
import threading
from collections import Counter
from concurrent.futures import CancelledError, ThreadPoolExecutor
from pathlib import Path

from qt_test_helpers import APP
from PySide6.QtCore import QCoreApplication, QEvent, QTimer, QPoint, QPointF, Qt
from PySide6.QtGui import QPixmap, QColor, QIcon, QWheelEvent
from PySide6.QtWidgets import QStyleFactory
from models.image_list_model import ImageListModel
from models.proxy_image_list_model import ProxyImageListModel
from utils.image import Image
from utils.settings import settings
from widgets.image_list_view import ImageListView
from widgets import image_list_view


def test_repeated_drag_probe(tmp_path, monkeypatch):
    assert Path(settings.fileName()).resolve() == Path(os.environ['TAGGUI_SETTINGS_PATH']).resolve()
    settings.setValue('diagnostic_log_mode', 'off')
    settings.setValue('image_list_thumbnail_size', 120)
    model = ImageListModel(120, ',')
    if os.environ.get('TAGGUI_PROBE_ONE_PAGE_WORKER') == '1':
        model._page_executor.shutdown(wait=True, cancel_futures=True)
        model._page_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='page_probe')
    if os.environ.get('TAGGUI_PROBE_PARALLEL_PAGES') == '1':
        assert os.environ.get('TAGGUI_PROBE_BASELINE') != '1', 'Compare one mechanism at a time'
        source_text = subprocess.check_output(['git', 'show',
            '180c520:taggui/models/image_list_model.py'], encoding='utf-8')
        tree = ast.parse(source_text)
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                   and node.name == 'ImageListModel')
        method = next(node for node in cls.body if isinstance(node, ast.FunctionDef)
                      and node.name == 'prepare_target_window')
        namespace = dict(ImageListModel.prepare_target_window.__globals__)
        exec(compile(ast.Module(body=[method], type_ignores=[]), '<checkpoint>', 'exec'), namespace)
        prepare = namespace['prepare_target_window'].__get__(model)
        def prepare_parallel(*args, **kwargs):
            kwargs.pop('target_first', None)
            return prepare(*args, **kwargs)
        monkeypatch.setattr(model, 'prepare_target_window', prepare_parallel)
    if os.environ.get('TAGGUI_PROBE_BASELINE') == '1':
        model._sidecar_meta_cache = {}
        model._sidecar_meta_cache_limit = 2048
        source_text = subprocess.check_output(['git', 'show',
            '94c11bb:taggui/models/image_list_model.py'], encoding='utf-8')
        tree = ast.parse(source_text)
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                   and node.name == 'ImageListModel')
        method = next(node for node in cls.body if isinstance(node, ast.FunctionDef)
                      and node.name == '_read_cached_sidecar_meta')
        namespace = dict(ImageListModel._read_cached_sidecar_meta.__globals__)
        exec(compile(ast.Module(body=[method], type_ignores=[]), '<checkpoint>', 'exec'), namespace)
        monkeypatch.setattr(model, '_read_cached_sidecar_meta',
            namespace['_read_cached_sidecar_meta'].__get__(model))
    proxy = ProxyImageListModel(model, None, ',')
    model.proxy_image_list_model = proxy
    model._paginated_mode = True
    model._total_count = 27009
    model._directory_path = tmp_path
    model._db = object()
    model._bootstrap_complete = True
    thumb = QPixmap(120, 90)
    thumb.fill(QColor('steelblue'))
    shared_icon = QIcon(thumb)
    pages = {}
    for page in range(28):
        pages[page] = []
        for i in range(page * 1000, min((page+1)*1000, model._total_count)):
            image = Image(tmp_path / f'{i}.png', (800, 600))
            image.thumbnail = QIcon(thumb)
            pages[page].append(image)
    model._pages = {page: pages[page] for page in range(7)}
    model._page_load_order = list(model._pages)
    monkeypatch.setattr(model, '_start_paginated_enrichment', lambda **kwargs: None)
    def load(page, **kwargs):
        event = kwargs.get('cancel_event')
        if event is not None and event.wait(.35):
            raise CancelledError()
        return pages[page], []
    monkeypatch.setattr(model, '_load_images_from_db', load)
    copied_db = None
    source_index = os.environ.get('TAGGUI_AUDIT_SOURCE_INDEX')
    if source_index:
        # Only the backup is opened by an application database service.
        # Hydration reads original file existence and sidecars; it never decodes,
        # repairs, writes sidecars, or constructs services for the source folder.
        source_index = Path(source_index).resolve(strict=True)
        destination = tmp_path / '.taggui' / 'index.db'
        destination.parent.mkdir()
        source = sqlite3.connect(source_index.as_uri()+'?mode=ro', uri=True)
        try:
            source.execute('PRAGMA query_only=ON')
            with sqlite3.connect(destination) as target:
                source.backup(target)
        finally:
            source.close()
        from utils.image_index_db import ImageIndexDB
        copied_db = ImageIndexDB(tmp_path)
        assert copied_db.db_path.resolve() == destination.resolve()
        model._db = copied_db
        real_root = source_index.parent.parent
        model._total_count = copied_db.count_or_raise()
        def hydrate(page, **kwargs):
            started = time.perf_counter()
            rows = copied_db.get_page(page, 1000, 'ctime', 'DESC')
            sql_ms = (time.perf_counter()-started)*1000
            images, missing = model._images_from_db_rows(rows, copied_db, real_root,
                cancel_event=kwargs.get('cancel_event'))
            for image in images:
                image.thumbnail = shared_icon
            print('HYDRATE', page, 'sql_ms', round(sql_ms, 2), 'total_ms',
                  round((time.perf_counter()-started)*1000, 2))
            return images, missing
        monkeypatch.setattr(model, '_load_images_from_db', hydrate)
        sidecar_times = []
        sidecar_versions = Counter()
        original_read = model._read_cached_sidecar_meta
        def read_sidecar(path):
            start = time.perf_counter()
            result = original_read(path)
            if path is not None:
                sidecar_times.append(((time.perf_counter()-start)*1000, path.stat().st_size))
                sidecar_versions[str(result.get('version')) if isinstance(result, dict) else 'none'] += 1
            return result
        monkeypatch.setattr(model, '_read_cached_sidecar_meta', read_sidecar)
    # QProxyStyle owns its base. The standalone fixture shares a QApplication
    # with pytest, so give this view an equivalent private base for teardown.
    track_style = image_list_view.ImageListScrollBarTrackStyle
    monkeypatch.setattr(image_list_view, 'ImageListScrollBarTrackStyle',
        lambda base: track_style(QStyleFactory.create(base.objectName())))
    view = ImageListView(None, proxy, ',', 120)
    view.use_masonry = True
    model.image_list_selection_model = view.selectionModel()
    view.resize(700, 800)
    view.show()
    event_times = []
    heartbeat_gaps = []
    last_beat = [time.perf_counter()]
    heartbeat = QTimer()
    heartbeat.setInterval(5)
    def tick():
        now = time.perf_counter()
        heartbeat_gaps.append((now-last_beat[0])*1000)
        last_beat[0] = now
    heartbeat.timeout.connect(tick)
    heartbeat.start()
    gc_starts, gc_times = {}, []
    def gc_timing(phase, info):
        key = (threading.get_ident(), info['generation'])
        if phase == 'start':
            gc_starts[key] = time.perf_counter()
        elif key in gc_starts:
            gc_times.append(((time.perf_counter()-gc_starts.pop(key))*1000, info['generation']))
    gc.callbacks.append(gc_timing)
    def events(seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            start = time.perf_counter()
            APP.processEvents()
            event_times.append((time.perf_counter()-start)*1000)
            time.sleep(.002)
    try:
        events(.5)
        view._calculate_masonry_layout()
        events(1)
        print('INITIAL', len(view._masonry_items), view._masonry_calculating, view.layoutMode())
        assert view._masonry_items
        for fraction in (.64, .3, 1., .5):
            sb = view.verticalScrollBar()
            started = time.perf_counter()
            sb.setSliderDown(True)
            press_ms = (time.perf_counter()-started)*1000
            events(.05)
            print('PRESS', sb.value(), sb.maximum(), view._drag_scroll_max_baseline, view.use_masonry)
            sb.setSliderPosition(round(sb.maximum()*fraction))
            print('MOVE', sb.value(), sb.sliderPosition(), sb.maximum(), view._strict_drag_live_fraction)
            started = time.perf_counter()
            sb.setSliderDown(False)
            print('DRAG', fraction, 'press_ms', round(press_ms, 2),
                  'release_ms', round((time.perf_counter()-started)*1000, 2))
            events(.08)
        events(25 if source_index else 2)
        assert view._one_shot_jump_target_global is None
        assert view._get_masonry_item_rect(13000).translated(0, -sb.value()).intersects(view.viewport().rect())
        def wheel(delta):
            position = QPointF(100, 100)
            event = QWheelEvent(position, position, QPoint(), QPoint(0, delta),
                                Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False)
            QCoreApplication.sendEvent(view.viewport(), event)
            events(.02)
        landed_scroll = sb.value()
        for _ in range(16):
            wheel(120)
        assert sb.value() < landed_scroll
        upper_scroll = sb.value()
        for _ in range(32):
            wheel(-120)
        assert sb.value() > upper_scroll
        visible = view._get_masonry_visible_items(
            view.viewport().rect().translated(0, sb.value()))
        assert visible and any(item['index'] >= 13000 for item in visible)
        print('BIDIRECTIONAL_SCROLL', landed_scroll, upper_scroll, sb.value())
        print('MAX_EVENT_MS', max(event_times), 'SCROLL', sb.value(), sb.maximum())
        print('MAX_HEARTBEAT_MS', max(heartbeat_gaps))
        if source_index:
            print('SLOWEST_SIDECARS_MS_BYTES', sorted(sidecar_times, reverse=True)[:10])
            print('SIDECAR_VERSIONS', sidecar_versions, 'GC_PAUSES_MS', sorted(gc_times, reverse=True)[:10])
    finally:
        heartbeat.stop()
        view.close()
        model._db = None
        page_executor = model._page_executor
        model.shutdown_background_workers()
        page_executor.shutdown(wait=True, cancel_futures=True)
        view._masonry_executor.shutdown(wait=True, cancel_futures=True)
        if copied_db is not None:
            copied_db.close()
        APP.processEvents()
        gc.callbacks.remove(gc_timing)
        view.deleteLater()
        proxy.deleteLater()
        model.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
