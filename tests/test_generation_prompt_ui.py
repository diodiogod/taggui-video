import json
from pathlib import Path
import sys
import threading

from PIL import Image, PngImagePlugin
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'taggui'))
from qt_test_helpers import APP, dispose_widget, pump
from utils.generation_prompt import PromptCandidate
from utils.latest_task import LatestTask
from utils.settings import settings
from widgets import generation_prompt_dialog as prompt_ui


def test_copy_button_follows_multiline_selection_and_restores_full_copy(tmp_path, monkeypatch):
    prompt = '😀 alpha\nbeta omega'
    monkeypatch.setattr(prompt_ui, 'read_generation_prompts',
                        lambda path, cancelled: [PromptCandidate(prompt, 'Saved')])
    dialog = prompt_ui.GenerationPromptDialog(tmp_path / 'image.png')
    try:
        dialog.show()
        pump(lambda: dialog.copy_button.isEnabled())
        assert dialog.copy_button.text() == 'Copy Prompt'
        cursor = dialog.text.textCursor()
        cursor.setPosition(3)  # After the emoji (two UTF-16 units) and space.
        start = dialog.text.cursorRect(cursor).center()
        cursor.setPosition(13)
        end = dialog.text.cursorRect(cursor).center()
        viewport = dialog.text.viewport()
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(viewport, end, 100)
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=end)
        assert dialog.copy_button.text() == 'Copy Selected'
        QTest.mouseClick(dialog.copy_button, Qt.MouseButton.LeftButton)
        assert QApplication.clipboard().text() == 'alpha\nbeta'
        assert dialog.copy_button.text() == 'Copied!'
        QTest.qWait(1850)
        assert dialog.copy_button.text() == 'Copy Selected'

        QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=end)
        assert dialog.copy_button.text() == 'Copy Prompt'
        dialog.text.setFocus()
        QTest.keyClick(dialog.text, Qt.Key.Key_Home, Qt.KeyboardModifier.ControlModifier)
        for _ in range(2):
            QTest.keyClick(dialog.text, Qt.Key.Key_Right)
        for _ in range(len('alpha')):
            QTest.keyClick(dialog.text, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
        assert dialog.copy_button.text() == 'Copy Selected'
        QTest.mouseClick(dialog.copy_button, Qt.MouseButton.LeftButton)
        assert QApplication.clipboard().text() == 'alpha'
        dialog.text.setFocus()
        QTest.keyClick(dialog.text, Qt.Key.Key_Right)
        assert dialog.copy_button.text() == 'Copy Prompt'
        QTest.mouseClick(dialog.copy_button, Qt.MouseButton.LeftButton)
        assert QApplication.clipboard().text() == prompt
    finally:
        dialog._worker.drain()
        dispose_widget(dialog)


def test_copy_waits_for_unambiguous_result_and_does_not_overwrite_on_multiple(tmp_path, monkeypatch):
    clipboard = QApplication.clipboard()
    clipboard.setText('original clipboard')
    candidates = [PromptCandidate('first', 'First'), PromptCandidate('second', 'Second')]
    monkeypatch.setattr(prompt_ui, 'read_generation_prompts', lambda path, cancelled: candidates)
    dialog = prompt_ui.GenerationPromptDialog(tmp_path / 'image.png', copy_on_load=True)
    try:
        pump(lambda: dialog.copy_button.isEnabled())
        assert dialog.isVisible()
        assert dialog.source.count() == 2
        assert clipboard.text() == 'original clipboard'
        dialog.source.setCurrentIndex(1)
        dialog.copy_button.click()
        assert clipboard.text() == 'second'
    finally:
        dialog._worker.drain()
        dispose_widget(dialog)


def test_copy_mode_rejects_unverified_fallback(tmp_path, monkeypatch):
    clipboard = QApplication.clipboard()
    clipboard.setText('original clipboard')
    candidates = [PromptCandidate('maybe', 'Unverified', 'Connection could not be verified.', False)]
    monkeypatch.setattr(prompt_ui, 'read_generation_prompts', lambda path, cancelled: candidates)
    dialog = prompt_ui.GenerationPromptDialog(tmp_path / 'image.png', copy_on_load=True)
    try:
        pump(lambda: dialog.copy_button.isEnabled())
        assert dialog.isVisible()
        assert clipboard.text() == 'original clipboard'
        dialog.copy_button.click()
        assert clipboard.text() == 'maybe'
    finally:
        dialog._worker.drain()
        dispose_widget(dialog)


def test_unambiguous_copy_finishes_without_opening_a_dialog(tmp_path, monkeypatch):
    monkeypatch.setattr(prompt_ui, 'read_generation_prompts',
                        lambda path, cancelled: [PromptCandidate('quick copy', 'Saved')])
    clipboard = QApplication.clipboard()
    clipboard.setText('before')
    dialog = prompt_ui.GenerationPromptDialog(tmp_path / 'image.png', copy_on_load=True)
    try:
        pump(lambda: clipboard.text() == 'quick copy')
        assert not dialog.isVisible()
        assert dialog._worker._closed
    finally:
        dialog._worker.drain()
        dispose_widget(dialog)


def test_closing_during_read_does_not_change_clipboard(tmp_path, monkeypatch):
    started, release = threading.Event(), threading.Event()
    def read_slowly(path, cancelled):
        started.set()
        release.wait(5)
        return [PromptCandidate('too late', 'Saved')]
    monkeypatch.setattr(prompt_ui, 'read_generation_prompts', read_slowly)
    clipboard = QApplication.clipboard()
    clipboard.setText('original clipboard')
    dialog = prompt_ui.GenerationPromptDialog(tmp_path / 'image.png', copy_on_load=True)
    try:
        dialog.show()
        assert started.wait(2)
        dialog.close()
        release.set()
        dialog._worker.drain()
        APP.processEvents()
        assert clipboard.text() == 'original clipboard'
    finally:
        release.set()
        dialog._worker.drain()
        dispose_widget(dialog)


def test_older_pending_copy_cannot_overwrite_a_newer_copy(tmp_path, monkeypatch):
    first_started, release_first = threading.Event(), threading.Event()
    def read_in_order(path, cancelled):
        if path.name == 'first.png':
            first_started.set()
            release_first.wait(5)
        return [PromptCandidate(path.stem, 'Saved')]
    monkeypatch.setattr(prompt_ui, 'read_generation_prompts', read_in_order)
    clipboard = QApplication.clipboard()
    clipboard.setText('before')
    first = prompt_ui.GenerationPromptDialog(tmp_path / 'first.png', copy_on_load=True)
    second = None
    try:
        first.show()
        assert first_started.wait(2)
        second = prompt_ui.GenerationPromptDialog(tmp_path / 'second.png', copy_on_load=True)
        second.show()
        pump(lambda: clipboard.text() == 'second')
        assert clipboard.text() == 'second'
        release_first.set()
        pump(lambda: not first.isVisible())
        assert clipboard.text() == 'second'
    finally:
        release_first.set()
        first._worker.drain()
        dispose_widget(first)
        if second is not None:
            second._worker.drain()
            dispose_widget(second)


def _write_image(path, prompt, *, saved_positive=None):
    graph = {
        '1': {'class_type': 'CLIPTextEncode', 'inputs': {'text': prompt}},
        '2': {'class_type': 'KSampler', 'inputs': {'positive': ['1', 0]}},
    }
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text('prompt', json.dumps(graph))
    if saved_positive is not None:
        metadata.add_text('positive_prompt', saved_positive)
    Image.new('RGB', (64, 48), 'red').save(path, pnginfo=metadata)


def test_browser_and_floating_menu_read_their_own_images(tmp_path, monkeypatch):
    from models.image_list_model import ImageListModel
    from widgets import floating_viewer_window
    from widgets.main_window import MainWindow

    monkeypatch.setenv('TAGGUI_FORCE_CLEAN_EXIT_ON_CLOSE', '0')
    _write_image(tmp_path / 'a.png', 'workflow prompt A', saved_positive='prompt A')
    _write_image(tmp_path / 'b.png', 'prompt B')
    settings.setValue('directory_path', str(tmp_path))
    settings.setValue('secondary_browser_restore_on_startup', False)
    settings.setValue('secondary_browser_visible', False)
    settings.setValue('pagination_threshold', 1000)
    window = MainWindow(APP)
    model, proxy = window.image_list_model, window.proxy_image_list_model
    view = window.image_list.list_view
    executor = view._masonry_executor
    dialogs = []
    try:
        window.resize(1000, 700)
        window.show()
        pump(lambda: len(model.images) == 2 and model._view_prepare_owner is None, seconds=15)
        indices = {proxy.index(row, 0).data(Qt.UserRole).path.name: proxy.index(row, 0)
                   for row in range(proxy.rowCount())}
        view.setCurrentIndex(indices['a.png'])
        window.commit_thumbnail_click_selection(indices['a.png'])
        pump(lambda: window.image_viewer.current_media is not None
             and window.image_viewer.current_media.path.name == 'a.png')
        assert view.copy_generation_prompt_action.isEnabled()
        QApplication.clipboard().setText('before')
        view.copy_generation_prompt_action.trigger()
        pump(lambda: QApplication.clipboard().text() == 'prompt A')
        QApplication.clipboard().setText('keep this')
        view.view_generation_prompt_action.trigger()
        pump(lambda: any(dialog.isVisible() for dialog in
                         window.findChildren(prompt_ui.GenerationPromptDialog)))
        preview = next(dialog for dialog in window.findChildren(prompt_ui.GenerationPromptDialog)
                       if dialog.isVisible())
        dialogs.append(preview)
        pump(lambda: preview.copy_button.isEnabled())
        assert preview.text.toPlainText() == 'prompt A'
        assert QApplication.clipboard().text() == 'keep this'

        floating = window.spawn_floating_viewer_at(indices['b.png'])
        pump(lambda: floating.viewer.current_media is not None
             and floating.viewer.current_media.path.name == 'b.png', seconds=10)
        window.set_active_viewer(window.image_viewer)

        class PickPromptMenu(QMenu):
            def exec(self, *_):
                return next(action for action in self.actions()
                            if action.text() == 'View / Copy Generation Prompt...')
        monkeypatch.setattr(floating_viewer_window, 'QMenu', PickPromptMenu)
        floating._show_window_menu(QPoint())
        pump(lambda: bool(floating.findChildren(prompt_ui.GenerationPromptDialog)))
        float_dialog = floating.findChildren(prompt_ui.GenerationPromptDialog)[-1]
        dialogs.append(float_dialog)
        pump(lambda: float_dialog.copy_button.isEnabled())
        assert float_dialog.path.name == 'b.png'
        assert float_dialog.text.toPlainText() == 'prompt B'
        float_dialog.copy_button.click()
        assert QApplication.clipboard().text() == 'prompt B'
    finally:
        for dialog in dialogs:
            dialog._worker.drain()
            dispose_widget(dialog)
        tasks = window.findChildren(LatestTask)
        window.close()
        for task in tasks:
            task.drain()
        executor.shutdown(wait=True, cancel_futures=True)
        APP.processEvents()
        dispose_widget(window)
        APP.processEvents()
