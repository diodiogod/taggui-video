"""Run through tests/run_isolated.py to keep settings and cache roots private."""
import json
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QListView

from qt_test_helpers import APP, dispose_widget, pump


@pytest.fixture
def isolated_settings():
    assert os.environ.get('TAGGUI_SETTINGS_PATH'), 'Run with tests/run_isolated.py'
    from utils.settings import settings
    root = Path(os.environ['TAGGUI_SETTINGS_PATH']).parent.resolve()
    assert Path(settings.fileName()).resolve().is_relative_to(root)
    assert Path(settings.value('thumbnail_cache_location')).resolve().is_relative_to(root)
    return settings


def make_pair(folder):
    path = folder / 'image.png'
    path.write_bytes(b'image')
    path.with_suffix('.json').write_text(json.dumps({
        'version': 1, 'state': {}, 'nodes': [{'id': 1, 'type': 'CLIPTextEncode'}]}))
    return path


def test_dialog_archive_restore_and_heartbeat(isolated_settings, tmp_path):
    from dialogs.workflow_archive_dialog import WorkflowArchiveDialog
    path = make_pair(tmp_path)
    dialog = WorkflowArchiveDialog()
    dialog.folder.setText(str(tmp_path))
    assert dialog.remove.isChecked()
    dialog.remove.setChecked(True)
    beats = []
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: beats.append(time.monotonic()))
    timer.start()
    dialog.show()
    try:
        QTest.mouseClick(dialog.pack, Qt.LeftButton)
        assert dialog.task is not None and not dialog.restore.isEnabled()
        pump(lambda: dialog.task is None, seconds=20)
        assert 'Removed originals: 1' in dialog.status.text()
        assert not path.with_suffix('.json').exists()
        assert len(beats) > 5
        QTest.mouseClick(dialog.restore, Qt.LeftButton)
        pump(lambda: dialog.task is None, seconds=20)
        assert 'Restored: 1' in dialog.status.text()
        assert path.with_suffix('.json').exists()
    finally:
        timer.stop()
        if dialog.task is not None:
            dialog.task.shutdown()
            pump(lambda: dialog.task is None)
        dispose_widget(dialog)


def test_close_cancels_and_waits_for_worker(isolated_settings, tmp_path):
    from dialogs.workflow_archive_dialog import WorkflowArchiveDialog
    from utils.workflow_archive import check_cancel
    dialog = WorkflowArchiveDialog()
    dialog.folder.setText(str(tmp_path))
    entered = threading.Event()
    def operation(*, cancel, progress):
        entered.set()
        cancel.wait(5)
        check_cancel(cancel)
    dialog.show()
    dialog.start(operation)
    pump(entered.is_set)
    dialog.close()
    assert dialog.isVisible()
    pump(lambda: dialog.task is None)
    assert 'Cancelled' in dialog.status.text()
    dispose_widget(dialog)


def test_live_progress_reaches_dialog_before_json_processing_finishes(isolated_settings, tmp_path, monkeypatch):
    from dialogs.workflow_archive_dialog import WorkflowArchiveDialog
    from utils import workflow_archive as wa
    from types import SimpleNamespace
    for number in range(20):
        folder = tmp_path / str(number)
        folder.mkdir()
        path = make_pair(folder)
        path.rename(tmp_path / f'image-{number}.png')
        path.with_suffix('.json').rename(tmp_path / f'image-{number}.json')
    gate = threading.Event()
    entered = threading.Event()
    reads = [0]
    read = wa._workflow_bytes
    def hold_midway(path):
        reads[0] += 1
        if reads[0] == 6:
            entered.set()
            gate.wait(10)
        return read(path)
    monkeypatch.setattr(wa, '_workflow_bytes', hold_midway)
    monkeypatch.setattr(wa, 'time', SimpleNamespace(monotonic=lambda: reads[0]))
    dialog = WorkflowArchiveDialog()
    dialog.folder.setText(str(tmp_path))
    dialog.show()
    try:
        QTest.mouseClick(dialog.pack, Qt.LeftButton)
        pump(lambda: entered.is_set() and dialog.progress.value() == 5)
        assert dialog.task is not None
        assert dialog.progress.maximum() == 20 and dialog.progress.isTextVisible()
        assert '5 / 20' in dialog.status.text()
        assert '5 workflows found' in dialog.status.text()
        assert 'Current: image-' in dialog.status.text()
        before = dialog.status.text()
        pump(lambda: dialog.status.text() != before, seconds=3)
        assert 'Elapsed:' in dialog.status.text()
        dialog.reject()
        gate.set()
        pump(lambda: dialog.task is None)
        assert 'Cancelled' in dialog.status.text()
        assert len(list(tmp_path.glob('*.json'))) == 20
    finally:
        gate.set()
        if dialog.task is not None:
            dialog.task.shutdown()
            pump(lambda: dialog.task is None)
        dispose_widget(dialog)


def test_drag_prepares_in_background_and_survives_owner_deletion(isolated_settings, tmp_path, monkeypatch):
    from utils import workflow_archive as wa
    from widgets import workflow_archive_drag as module
    path = make_pair(tmp_path)
    wa.create_archive(tmp_path, {'.png'}, remove_originals=True)
    cache = wa.WorkflowDragCache()
    monkeypatch.setattr(module, 'drag_cache', cache)
    model = QStandardItemModel()
    item = QStandardItem('image')
    item.setData(SimpleNamespace(path=path), Qt.UserRole)
    model.appendRow(item)
    class View(QListView):
        def _workflow_sidecar_drag_path_for_image_path(self, path):
            return None
    view = View()
    sibling = View()
    view.setModel(model)
    sibling.setModel(model)
    coordinator = module.WorkflowArchiveDrag(view)
    monkeypatch.setattr(coordinator, 'notify', lambda message: None)
    index = model.index(0, 0)
    assert not coordinator.prepare([index], index, Qt.CopyAction)
    task = coordinator.task
    # Delete the requester before the extraction completion callback. The app
    # owns the worker; sibling model consumers must stay valid.
    dispose_widget(view)
    task.wait(10000)
    pump(lambda: not APP._workflow_archive_tasks)
    assert cache.lookup(path)[1].is_file()
    assert sibling.model().index(0, 0).data() == 'image'
    dispose_widget(sibling)


def test_released_cold_drag_prompts_retry_and_cached_drag_is_ready(isolated_settings, tmp_path, monkeypatch):
    from utils import workflow_archive as wa
    from widgets import workflow_archive_drag as module
    path = make_pair(tmp_path)
    wa.create_archive(tmp_path, {'.png'}, remove_originals=True)
    monkeypatch.setattr(module, 'drag_cache', wa.WorkflowDragCache())
    model = QStandardItemModel()
    item = QStandardItem('image')
    item.setData(SimpleNamespace(path=path), Qt.UserRole)
    model.appendRow(item)
    view = QListView()
    view.setModel(model)
    view._workflow_sidecar_drag_path_for_image_path = lambda path: None
    coordinator = module.WorkflowArchiveDrag(view)
    messages = []
    monkeypatch.setattr(coordinator, 'notify', messages.append)
    index = model.index(0, 0)
    assert not coordinator.prepare([index], index, Qt.CopyAction)
    pump(lambda: coordinator.task is None, seconds=20)
    assert 'ready' in messages[-1]
    assert coordinator.prepare([index], index, Qt.CopyAction)
    dispose_widget(view)
