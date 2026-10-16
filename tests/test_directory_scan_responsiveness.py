"""Cold Explorer-style startup must keep delivering native Qt input while scanning."""
import sys
import threading
import time
import traceback
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QThreadPool, QTimer, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDockWidget, QProgressDialog, QPushButton, QToolBar

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'taggui'))
from models import image_list_model as model_module
from qt_test_helpers import APP, assert_capture_contains_color, dispose_widget, pump
from utils.latest_task import LatestTask
from utils.settings import settings
from widgets.main_window import MainWindow


@pytest.fixture(autouse=True)
def configure(monkeypatch):
    assert __import__('os').environ.get('TAGGUI_SETTINGS_PATH'), 'Use tests/run_isolated.py'
    monkeypatch.setenv('TAGGUI_FORCE_CLEAN_EXIT_ON_CLOSE', '0')
    monkeypatch.setenv('TAGGUI_PRIMARY_RESTORE_DELAY_MS', '0')
    settings.remove('directory_path')
    settings.remove('last_selected_path')
    settings.setValue('secondary_browser_restore_on_startup', False)
    settings.setValue('secondary_browser_visible', False)
    settings.setValue('repair_extensionless_images', True)
    settings.setValue('pagination_threshold', 0)
    settings.setValue('main_viewer_visible', True)
    errors = []
    monkeypatch.setattr(sys, 'excepthook', lambda *error: errors.append(error))
    yield
    assert not errors, '\n'.join(''.join(traceback.format_exception(*error)) for error in errors)


def make_image(path):
    image = QImage(120, 90, QImage.Format_RGB32)
    image.fill(QColor(38, 170, 92))
    assert image.save(str(path), 'PNG')


def dispose_window(window):
    view = window.image_list.list_view
    executors = [view._masonry_executor]
    model = window.image_list_model
    executors.extend(getattr(model, name, None) for name in (
        '_page_executor', '_load_executor', '_enrichment_executor',
        '_refresh_executor', '_save_executor', '_scan_process_executor',
    ))
    window.close()
    for task in window.findChildren(LatestTask):
        task.drain()
    window.shutdown_background_workers()
    for executor in executors:
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
    QThreadPool.globalInstance().waitForDone(5000)
    dispose_widget(window)
    APP.processEvents()


def block_header(monkeypatch, blocked_path):
    started, release, finished = (threading.Event() for _ in range(3))
    worker_threads = []
    original_header = model_module._detect_image_suffix_from_header
    original_prepare = model_module._prepare_directory_files

    def header(path):
        if path == blocked_path:
            worker_threads.append(threading.get_ident())
            started.set()
            assert release.wait(8), 'GUI did not release the blocked file read'
        return original_header(path)

    def prepare(*args):
        try:
            return original_prepare(*args)
        finally:
            finished.set()

    monkeypatch.setattr(model_module, '_detect_image_suffix_from_header', header)
    monkeypatch.setattr(model_module, '_prepare_directory_files', prepare)
    return started, release, finished, worker_threads


@pytest.mark.parametrize('mode,pagination_threshold', [
    ('icon', 0), ('list', 0), ('icon', 1000), ('list', 1000),
])
def test_cold_startup_repairs_and_selects_while_gui_ticks(tmp_path, monkeypatch, mode, pagination_threshold):
    folder = tmp_path / 'startup'
    folder.mkdir()
    path = folder / 'repaired'
    make_image(path)
    settings.setValue('image_list_view_mode', mode)
    settings.setValue('image_list_thumbnail_size', 64 if mode == 'icon' else 240)
    settings.setValue('pagination_threshold', pagination_threshold)
    started, release, finished, worker_threads = block_header(monkeypatch, path)
    main_thread = threading.get_ident()
    index_threads = []
    original_insert = model_module.ImageIndexDB.bulk_insert_files

    def insert(self, *args, **kwargs):
        index_threads.append(threading.get_ident())
        return original_insert(self, *args, **kwargs)

    monkeypatch.setattr(model_module.ImageIndexDB, 'bulk_insert_files', insert)
    window = MainWindow(APP, startup_directory=folder)
    ticks = []
    timer = QTimer()

    def tick():
        if started.is_set() and not release.is_set():
            ticks.append(time.perf_counter())
            if len(ticks) >= 25:
                release.set()

    timer.timeout.connect(tick)
    timer.start(10)
    try:
        window.resize(1100, 750)
        window.show()
        viewer = window.image_viewer
        model = window.image_list_model
        view = window.image_list.list_view
        expected = path.with_suffix('.png')
        pump(lambda: model._paginated_mode == (pagination_threshold == 0)
             and not getattr(model, '_initial_page_load_pending', False)
             and window.proxy_image_list_model.rowCount() == 1, seconds=15)
        for dock in window.findChildren(QDockWidget):
            if dock is not window.image_list:
                dock.hide()
        for toolbar in window.findChildren(QToolBar):
            toolbar.hide()
        window.resize(1100, 750)
        window.resizeDocks([window.image_list], [300], Qt.Horizontal)
        QTest.qWait(300)
        index = window.proxy_image_list_model.index(0, 0)
        pump(lambda: view.visualRect(index).isValid(), seconds=8)
        rect = view.visualRect(index)
        assert rect.isValid()
        QTest.mouseClick(view.viewport(), Qt.LeftButton, pos=rect.center())
        pump(lambda: viewer.current_media is not None
             and viewer.current_media.path == expected
             and viewer._image_decode_owner is None, seconds=15)
        QTest.qWait(600)  # Include enrichment, layout and activation callbacks.
        viewer.zoom_fit()
        QTest.qWait(100)
        model = window.image_list_model
        view = window.image_list.list_view
        assert model._directory_path == folder
        assert view.currentIndex().data(Qt.UserRole).path == expected
        assert [index.data(Qt.UserRole).path for index in view.selectedIndexes()] == [expected]
        assert view.use_masonry == (mode == 'icon')
        assert not getattr(model, '_initial_page_load_pending', False)
        assert worker_threads and all(value != main_thread for value in worker_threads)
        if pagination_threshold == 0:
            assert index_threads and all(value != main_thread for value in index_threads)
        else:
            assert not index_threads
        assert len(ticks) >= 25
        maximum_gap = max(b - a for a, b in zip(ticks, ticks[1:]))
        assert maximum_gap < .35
        viewport = viewer.view.viewport()
        if APP.platformName() == 'windows':
            window.raise_()
            window.activateWindow()
            QTest.qWait(100)
            origin = viewport.mapToGlobal(QPoint(0, 0))
            pixels = viewport.screen().grabWindow(
                0, origin.x(), origin.y(), viewport.width(), viewport.height()).toImage()
        else:
            pixels = viewport.grab().toImage()
        if APP.platformName() == 'windows':
            assert_capture_contains_color(pixels, (38, 170, 92))
        print(f'COLD_STARTUP mode={mode} ticks={len(ticks)} maximum_gap_ms={maximum_gap*1000:.1f}')
    finally:
        timer.stop()
        release.set()
        try:
            if started.is_set():
                assert finished.wait(5)
        finally:
            dispose_window(window)


@pytest.mark.parametrize('action', ['cancel', 'close'])
def test_scan_cancel_does_not_wait_for_file_read_or_install_stale_result(tmp_path, monkeypatch, action):
    monkeypatch.setattr(MainWindow, 'restore', lambda self: None)
    old, target = tmp_path / 'old', tmp_path / 'target'
    old.mkdir()
    target.mkdir()
    make_image(old / 'old.png')
    blocked = target / 'blocked'
    make_image(blocked)
    window = MainWindow(APP)
    window.show()
    window.load_directory(old, save_path_to_settings=True)
    started, release, finished, _ = block_header(monkeypatch, blocked)
    input_times = []
    timer = QTimer()

    def cancel():
        if not started.is_set() or input_times:
            return
        # Relay/restore callbacks can run inside a modal loop. A second open
        # must not change this operation's media owner.
        window.load_directory(tmp_path)
        assert window.directory_path == old
        input_times.append(time.perf_counter())
        if action == 'close':
            window.close()
        else:
            dialog = next(widget for widget in APP.topLevelWidgets()
                          if isinstance(widget, QProgressDialog) and widget.isVisible())
            button = dialog.findChild(QPushButton)
            assert button is not None
            QTest.mouseClick(button, Qt.LeftButton)

    timer.timeout.connect(cancel)
    timer.start(10)
    try:
        window.load_directory(target, save_path_to_settings=True)
        returned_at = time.perf_counter()
        assert input_times
        assert returned_at - input_times[0] < .35
        assert not release.is_set() and not finished.is_set()
        assert window.directory_path == old
        assert window.image_list_model._directory_path == old
        assert window._session_settings_value('directory_path', '', value_type=str) == str(old)
        release.set()
        assert finished.wait(5)
        QTest.qWait(100)
        assert blocked.exists() and not blocked.with_suffix('.png').exists()
        assert window.directory_path == old
        assert window.image_list_model._directory_path == old
        print(f'SCAN_{action.upper()} input_to_return_ms={(returned_at-input_times[0])*1000:.1f}')
    finally:
        timer.stop()
        release.set()
        assert finished.wait(5)
        dispose_window(window)
