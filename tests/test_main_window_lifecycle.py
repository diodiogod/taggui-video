"""Exercise actual empty-window ownership with the Windows failsafe disabled."""
import sys
import traceback

import pytest
from shiboken6 import isValid
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt

from utils.latest_task import LatestTask
from widgets.main_window import MainWindow
from qt_test_helpers import APP, dispose_widget
from utils.settings import settings


@pytest.mark.parametrize('deliver_startup', [False, True])
def test_window_can_be_destroyed_before_or_after_startup_delivery(monkeypatch, tmp_path, deliver_startup):
    monkeypatch.setenv('TAGGUI_FORCE_CLEAN_EXIT_ON_CLOSE', '0')
    errors = []
    monkeypatch.setattr(sys, 'excepthook', lambda *error: errors.append(error))
    shared = APP.style()
    restored = []
    original_restore = MainWindow.restore
    def restore_session(self):
        original_restore(self)
        restored.append('session')
    monkeypatch.setattr(MainWindow, 'restore', restore_session)
    monkeypatch.setenv('TAGGUI_PRIMARY_RESTORE_DELAY_MS', '0')
    settings.setValue('directory_path', str(tmp_path))
    settings.setValue('secondary_browser_restore_on_startup', False)
    settings.setValue('secondary_browser_visible', False)
    loaded = []
    monkeypatch.setattr(MainWindow, 'load_directory',
                        lambda self, path, **kwargs: loaded.append(path))
    monkeypatch.setattr(MainWindow, '_apply_saved_workspace_preset',
                        lambda self: restored.append('workspace'))
    original_parent, original_proxy = shared.parent(), shared.proxy()
    window = MainWindow(APP)
    window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, window.image_list)
    window._session_settings_set_value('window_state', window.saveState())
    window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, window.image_list)
    tasks = window.findChildren(LatestTask)
    executor = window.image_list.list_view._masonry_executor
    # Keep model owners alive until explicit native destruction completes.
    model, proxy = window.image_list_model, window.proxy_image_list_model
    try:
        assert shared.parent() is original_parent
        assert shared.proxy() is original_proxy
        if deliver_startup:
            window.show()
            QTest.qWait(50)
            APP.processEvents()
            assert restored == ['session', 'workspace']
            assert loaded == [tmp_path]
            assert window.dockWidgetArea(window.image_list) == Qt.DockWidgetArea.RightDockWidgetArea
            assert window._main_window_closing is False
        window.pipeline_editor.step_list.schedule_link_connector_refresh()
    finally:
        window.close()
        for task in tasks:
            task.drain()
        executor.shutdown(wait=True, cancel_futures=True)
        dispose_widget(window)
        for _ in range(3):
            APP.processEvents()
        QTest.qWait(100)
    assert not isValid(window)
    assert restored == (['session', 'workspace'] if deliver_startup else [])
    assert isValid(shared) and APP.style() is shared
    assert model is proxy.sourceModel()
    assert not errors, [''.join(traceback.format_exception(*error)) for error in errors]
