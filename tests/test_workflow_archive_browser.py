"""Exercise the real thumbnail drag entry point across browser layouts."""
import json
from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QDrag, QKeySequence, QShortcut
from PySide6.QtTest import QTest

from qt_test_helpers import pump
from test_generation_prompt_navigation import prompt_browser
from utils.workflow_archive import create_archive, drag_cache


def test_workflow_archive_shortcut_opens_dialog(prompt_browser):
    from dialogs.workflow_archive_dialog import WorkflowArchiveDialog, WORKFLOW_ARCHIVE_SHORTCUT
    from qt_test_helpers import APP
    window, _, _ = prompt_browser
    sequence = QKeySequence(WORKFLOW_ARCHIVE_SHORTCUT)
    matching = [action for action in window.findChildren(QAction) if sequence in action.shortcuts()]
    matching += [shortcut for shortcut in window.findChildren(QShortcut) if shortcut.key() == sequence]
    assert len(matching) == 1
    window.activateWindow()
    window.image_list.list_view.setFocus()
    pump(lambda: window.isActiveWindow())
    opened = []
    timer = QTimer()
    timer.setInterval(20)
    def close_dialog():
        dialog = APP.activeModalWidget()
        if isinstance(dialog, WorkflowArchiveDialog):
            opened.append(dialog.windowTitle())
            dialog.reject()
    timer.timeout.connect(close_dialog)
    timer.start()
    try:
        QTest.keyClick(window.image_list.list_view, Qt.Key_F7,
                       Qt.ControlModifier | Qt.AltModifier | Qt.ShiftModifier)
        pump(lambda: bool(opened))
        assert opened == ['ComfyUI Workflow Archive']
    finally:
        timer.stop()


@pytest.mark.parametrize('prompt_browser', ['memory', 'masonry', 'virtual'], indirect=True)
def test_archived_workflow_drag_payload_and_loose_precedence(prompt_browser, monkeypatch):
    window, directory, mode = prompt_browser
    view = window.image_list.list_view
    path = directory / 'a.png'
    workflow = {'version': 1, 'state': {}, 'nodes': [{'id': 1, 'type': 'CLIPTextEncode'}]}
    sidecar = path.with_suffix('.json')
    sidecar.write_text(json.dumps(workflow))
    create_archive(directory, {'.png'}, remove_originals=True)
    index = view.currentIndex()
    assert index.data(Qt.UserRole).path == path
    exported = []
    # Keep the native drag loop out of automated tests, but exercise real Qt
    # modifier/mouse input, the production entry point and its actual MIME data.
    def capture(drag, *args):
        exported.append([Path(url.toLocalFile()) for url in drag.mimeData().urls()])
        return Qt.CopyAction
    monkeypatch.setattr(QDrag, 'exec', capture)
    modifiers = Qt.ControlModifier | Qt.AltModifier
    point = view.visualRect(index).center()
    QTest.mousePress(view.viewport(), Qt.LeftButton, modifiers, point)
    assert view._drag_export_mode() == 'workflow_smart'
    view._start_spawn_drag_for_index(index, Qt.CopyAction)
    QTest.mouseRelease(view.viewport(), Qt.LeftButton, modifiers, point)
    pump(lambda: view._workflow_archive_drag.task is None, seconds=15)
    assert drag_cache.lookup(path)[1].exists()
    exported.clear()
    QTest.mousePress(view.viewport(), Qt.LeftButton, modifiers, point)
    view._start_spawn_drag_for_index(index, Qt.CopyAction)
    QTest.mouseRelease(view.viewport(), Qt.LeftButton, modifiers, point)
    assert len(exported) == 1 and len(exported[0]) == 1
    assert json.loads(exported[0][0].read_bytes()) == workflow
    # Both ordinary Alt-drag and a newly restored loose workflow must keep
    # their established behavior after an archived drag.
    QTest.mousePress(view.viewport(), Qt.LeftButton, Qt.AltModifier, point)
    assert view._external_drag_path_for_image_path(path) == path
    QTest.mouseRelease(view.viewport(), Qt.LeftButton, Qt.AltModifier, point)
    sidecar.write_text(json.dumps({**workflow, 'extra': {'changed': True}}))
    QTest.mousePress(view.viewport(), Qt.LeftButton, modifiers, point)
    assert view._external_drag_path_for_image_path(path) == sidecar
    QTest.mouseRelease(view.viewport(), Qt.LeftButton, modifiers, point)
