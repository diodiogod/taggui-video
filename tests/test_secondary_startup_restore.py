from pathlib import Path

import pytest
from PySide6.QtTest import QTest

from qt_test_helpers import APP, dispose_widget, pump
from utils.latest_task import LatestTask
from utils.settings import settings
from widgets.main_window import MainWindow
from widgets.secondary_browser import SecondaryBrowser


@pytest.mark.parametrize('action', ['normal', 'new_folder', 'replaced_browser', 'close'])
def test_secondary_delayed_restore_respects_newer_actions(monkeypatch, tmp_path, action):
    monkeypatch.setenv('TAGGUI_FORCE_CLEAN_EXIT_ON_CLOSE', '0')
    monkeypatch.setenv('TAGGUI_SECONDARY_RESTORE_DELAY_MS', '350')
    saved, chosen = tmp_path / 'saved', tmp_path / 'chosen'
    saved.mkdir()
    chosen.mkdir()
    settings.remove('directory_path')
    settings.setValue('secondary_browser_restore_on_startup', True)
    settings.setValue('secondary_browser_visible', True)
    settings.setValue('secondary_browser_directory_path', str(saved))
    monkeypatch.setattr(MainWindow, '_apply_saved_workspace_preset', lambda self: None)
    calls = []
    original = SecondaryBrowser.load_directory
    def load(self, path, **kwargs):
        calls.append(Path(path))
        return original(self, path, **kwargs)
    monkeypatch.setattr(SecondaryBrowser, 'load_directory', load)
    window = MainWindow(APP)
    secondary = None
    try:
        window.show()
        pump(lambda: window._secondary_browser is not None)
        secondary = window._secondary_browser
        assert calls == []
        if action == 'new_folder':
            secondary.load_directory(chosen)
        elif action == 'close':
            window.close()
        elif action == 'replaced_browser':
            # A delayed restore belongs to the original browser, not a later
            # replacement occupying the same main-window field.
            window._secondary_browser = None
        QTest.qWait(450)
        assert calls == {'normal': [saved], 'new_folder': [chosen],
                         'replaced_browser': [], 'close': []}[action]
    finally:
        if secondary is not None:
            window._secondary_browser = secondary
        window.close()
        for task in window.findChildren(LatestTask):
            task.drain()
        browsers = [window.image_list]
        models = [window.image_list_model]
        if secondary is not None:
            browsers.append(secondary.dock)
            models.append(secondary.image_list_model)
        for browser in browsers:
            executor = browser.list_view._masonry_executor
            if executor is not None:
                executor.shutdown(wait=True, cancel_futures=True)
        for model in models:
            model.shutdown_background_workers()
        dispose_widget(window)
        APP.processEvents()
