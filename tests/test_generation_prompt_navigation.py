"""Prompt navigation through real browser and viewer ownership boundaries."""

from pathlib import Path
import sys
import threading
import time

import pytest
from PIL import Image
from PySide6.QtCore import QPoint, QThreadPool, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolTip
from shiboken6 import isValid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'taggui'))
from models.image_list_model import ImageListModel
from qt_test_helpers import APP, dispose_widget, pump
from test_generation_prompt_ui import _write_image
from test_generation_prompt_video_ui import choose_context_action
from utils.latest_task import LatestTask
from utils.generation_prompt import PromptCandidate
from utils.settings import settings
from utils.settings_widgets import SettingsComboBox
from widgets import generation_prompt_dialog as prompt_ui
from widgets.generation_prompt_dialog import GenerationPromptDialog
from widgets.main_window import MainWindow


@pytest.fixture
def prompt_browser(request, tmp_path, monkeypatch):
    mode = getattr(request, 'param', 'memory')
    monkeypatch.setenv('TAGGUI_FORCE_CLEAN_EXIT_ON_CLOSE', '0')
    monkeypatch.setattr(ImageListModel, 'PAGE_SIZE', 2)
    monkeypatch.setattr(MainWindow, 'restore', lambda self: None)
    _write_image(tmp_path / 'a.png', 'prompt A')
    Image.new('RGB', (64, 48), 'green').save(tmp_path / 'b.png')
    _write_image(tmp_path / 'c.png', 'prompt C')
    settings.setValue('secondary_browser_restore_on_startup', False)
    settings.setValue('secondary_browser_visible', False)
    settings.setValue('pagination_threshold', 1000 if mode == 'memory' else 0)
    settings.setValue('image_list_image_width', 120)
    settings.setValue('image_list_thumbnail_size', 240 if mode == 'virtual' else 64)
    settings.setValue('image_list_view_mode', 'list' if mode == 'virtual' else 'icon')
    settings.setValue('image_list_sort_by', 'Default')
    settings.setValue('image_list_sort_dir', 'ASC')
    settings.setValue('image_list_double_click_action', 'generation prompt viewer')
    window = MainWindow(APP)
    source = window.image_list_model
    view = window.image_list.list_view
    executor = view._masonry_executor
    try:
        window.resize(1100, 800)
        window.show()
        window.load_directory(tmp_path, select_path=str(tmp_path / 'a.png'))
        pump(lambda: source._view_prepare_owner is None
             and not getattr(source, '_initial_page_load_pending', False)
             and (source._total_count if source._paginated_mode else len(source.images)) == 3
             and window.image_viewer.current_media is not None, seconds=20)
        QTest.qWait(500)
        assert source._paginated_mode is (mode != 'memory')
        assert view.use_virtual_list is (mode == 'virtual')
        yield window, tmp_path, mode
    finally:
        QThreadPool.globalInstance().waitForDone(20000)
        APP.processEvents()
        QToolTip.hideText()
        for dialog in window.findChildren(GenerationPromptDialog):
            if isValid(dialog):
                dialog._worker.drain()
                dispose_widget(dialog)
        for floating in list(getattr(window, '_floating_viewers', [])):
            if not isValid(floating):
                continue
            for dialog in floating.findChildren(GenerationPromptDialog):
                if isValid(dialog):
                    dialog._worker.drain()
                    dispose_widget(dialog)
            for task in floating.viewer.findChildren(LatestTask):
                task.drain()
            floating.viewer.close()
            dispose_widget(floating)
        for task in window.findChildren(LatestTask):
            task.drain()
        secondary = getattr(window, '_secondary_browser', None)
        secondary_executor = (getattr(secondary.dock.list_view, '_masonry_executor', None)
                              if secondary is not None else None)
        window.shutdown_background_workers()
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
        if secondary_executor is not None:
            secondary_executor.shutdown(wait=True, cancel_futures=True)
        dispose_widget(window)
        APP.processEvents()


@pytest.mark.parametrize('prompt_browser', ['memory', 'masonry', 'virtual'], indirect=True)
def test_double_click_prompt_and_arrows_follow_browser(prompt_browser):
    window, directory, mode = prompt_browser
    view, proxy, source = (window.image_list.list_view, window.proxy_image_list_model,
                           window.image_list_model)
    initial = proxy.mapFromSource(source.index(source.get_loaded_row_for_path(directory / 'a.png'), 0))
    view.setCurrentIndex(initial)
    window.commit_thumbnail_click_selection(initial)
    clicked = proxy.mapFromSource(source.index(source.get_loaded_row_for_path(directory / 'b.png'), 0))
    pump(lambda: clicked.isValid() and view.visualRect(clicked).isValid(), seconds=10)
    QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.visualRect(clicked).center())
    pump(lambda: bool(window.findChildren(GenerationPromptDialog)))
    dialog = window.findChildren(GenerationPromptDialog)[-1]
    pump(lambda: dialog.path == directory / 'b.png'
         and 'No positive prompt' in dialog.info.text(), seconds=10)
    assert not dialog.copy_button.isEnabled()
    assert dialog.previous_button.isEnabled() and dialog.next_button.isEnabled()
    assert dialog.previous_button.y() >= dialog.text.geometry().bottom()
    assert dialog.previous_button.x() < dialog.next_button.x() < dialog.copy_button.x()
    QTest.mouseClick(dialog.next_button, Qt.MouseButton.LeftButton)
    pump(lambda: dialog.path == directory / 'c.png'
         and window.image_viewer.current_media is not None
         and window.image_viewer.current_media.path == dialog.path
         and dialog.text.toPlainText() == 'prompt C', seconds=25)
    QTest.qWait(1200)  # Include proxy remapping, layout and enrichment callbacks.
    assert view.currentIndex().data(Qt.ItemDataRole.UserRole).path == directory / 'c.png'
    assert window.image_viewer.current_media.path == directory / 'c.png'
    assert not dialog.next_button.isEnabled()
    QTest.mouseClick(dialog.previous_button, Qt.MouseButton.LeftButton)
    pump(lambda: dialog.path == directory / 'b.png'
         and window.image_viewer.current_media is not None
         and window.image_viewer.current_media.path == dialog.path
         and 'No positive prompt' in dialog.info.text(), seconds=25)
    assert not dialog.copy_button.isEnabled()


@pytest.mark.parametrize('prompt_browser', ['masonry', 'virtual'], indirect=True)
def test_resident_prompt_navigation_keeps_list_layout_and_selection(prompt_browser, monkeypatch):
    window, directory, mode = prompt_browser
    view, source, proxy = window.image_list.list_view, window.image_list_model, window.proxy_image_list_model
    index = proxy.mapFromSource(source.index(source.get_loaded_row_for_path(directory / 'b.png'), 0))
    view.setCurrentIndex(index)
    window.commit_thumbnail_click_selection(index)
    view.view_generation_prompt_action.trigger()
    pump(lambda: any(item.isVisible() for item in window.findChildren(GenerationPromptDialog)))
    dialog = next(item for item in window.findChildren(GenerationPromptDialog) if item.isVisible())
    pump(lambda: dialog.previous_button.isEnabled() and not source._loading_pages
         and not source._enrichment_running and not view._masonry_calculating, seconds=15)
    QTest.qWait(350)
    target = proxy.mapFromSource(source.index(source.get_loaded_row_for_path(directory / 'a.png'), 0))
    before_rect = view.visualRect(target)
    before_scroll = view.verticalScrollBar().value()
    calls = []
    original_jump = view.go_to_global_index
    original_prepare = source.prepare_target_window
    original_load = window.image_viewer.load_image

    def record_jump(*args, **kwargs):
        calls.append('jump')
        return original_jump(*args, **kwargs)

    def record_prepare(*args, **kwargs):
        calls.append('prepare')
        return original_prepare(*args, **kwargs)

    def record_load(*args, **kwargs):
        calls.append('load')
        return original_load(*args, **kwargs)

    monkeypatch.setattr(view, 'go_to_global_index', record_jump)
    monkeypatch.setattr(source, 'prepare_target_window', record_prepare)
    monkeypatch.setattr(window.image_viewer, 'load_image', record_load)
    QTest.mouseClick(dialog.previous_button, Qt.MouseButton.LeftButton)
    pump(lambda: dialog.path == directory / 'a.png'
         and dialog.text.toPlainText() == 'prompt A'
         and window.image_viewer.current_media is not None
         and window.image_viewer.current_media.path == dialog.path, seconds=10)
    assert 'jump' not in calls and 'prepare' not in calls
    assert calls.count('load') == 1
    if view.viewport().rect().contains(before_rect):
        assert view.verticalScrollBar().value() == before_scroll
        assert view.visualRect(target) == before_rect

    QTest.mouseClick(dialog.next_button, Qt.MouseButton.LeftButton)
    pump(lambda: dialog.path == directory / 'b.png'
         and window.image_viewer.current_media.path == dialog.path
         and 'No positive prompt' in dialog.info.text())
    QTest.mouseClick(dialog.previous_button, Qt.MouseButton.LeftButton)
    pump(lambda: dialog.path == directory / 'a.png'
         and window.image_viewer.current_media.path == dialog.path
         and dialog.text.toPlainText() == 'prompt A')
    assert 'jump' not in calls and 'prepare' not in calls
    assert calls.count('load') == 3

    # Real deferred page/enrichment notifications must retain the new path
    # and rank without depending on the heavyweight jump's old anchors.
    source._emit_pages_updated()
    source._start_paginated_enrichment(window_pages={0}, scope='window')
    pump(lambda: not source._enrichment_running, seconds=10)
    QTest.qWait(700)
    assert view.currentIndex().data(Qt.ItemDataRole.UserRole).path == directory / 'a.png'
    assert view._selected_global_index == 0
    assert window.image_viewer.current_media.path == directory / 'a.png'
    assert dialog.path == directory / 'a.png'

    # Ordinary thumbnail clicks must take ownership back after prompt browsing.
    index = proxy.mapFromSource(source.index(source.get_loaded_row_for_path(directory / 'b.png'), 0))
    view.scrollTo(index)
    QTest.qWait(250)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.visualRect(index).center())
    pump(lambda: window.image_viewer.current_media is not None
         and window.image_viewer.current_media.path == directory / 'b.png', seconds=10)


@pytest.mark.parametrize('prompt_browser', ['memory', 'masonry', 'virtual'], indirect=True)
def test_floating_prompt_arrows_update_only_the_owning_viewer(prompt_browser):
    window, directory, _mode = prompt_browser
    source, proxy, main = window.image_list_model, window.proxy_image_list_model, window.image_viewer
    main_index = proxy.mapFromSource(source.index(source.get_loaded_row_for_path(directory / 'a.png'), 0))
    window.image_list.list_view.setCurrentIndex(main_index)
    window.commit_thumbnail_click_selection(main_index)
    other_index = proxy.mapFromSource(source.index(source.get_loaded_row_for_path(directory / 'b.png'), 0))
    floating = window.spawn_floating_viewer_at(other_index)
    pump(lambda: floating.viewer.current_media is not None
         and floating.viewer.current_media.path == directory / 'b.png', seconds=10)
    window.set_active_viewer(main)
    choose_context_action(window, floating.viewer.view.viewport(), 'View / Copy Generation Prompt...')
    pump(lambda: bool(floating.findChildren(GenerationPromptDialog)))
    dialog = floating.findChildren(GenerationPromptDialog)[-1]
    pump(lambda: 'No positive prompt' in dialog.info.text())
    QTest.mouseClick(dialog.next_button, Qt.MouseButton.LeftButton)
    pump(lambda: dialog.path == directory / 'c.png'
         and floating.viewer.current_media is not None
         and floating.viewer.current_media.path == dialog.path
         and dialog.text.toPlainText() == 'prompt C', seconds=15)
    QTest.qWait(700)
    assert main.current_media.path == directory / 'a.png'
    assert window.image_list.list_view.currentIndex().data(Qt.ItemDataRole.UserRole).path == directory / 'a.png'


def test_floating_prompt_arrow_over_viewer_border_is_not_a_resize(prompt_browser):
    window, directory, _mode = prompt_browser
    source, proxy = window.image_list_model, window.proxy_image_list_model
    index = proxy.mapFromSource(source.index(source.get_loaded_row_for_path(directory / 'b.png'), 0))
    floating = window.spawn_floating_viewer_at(index)
    pump(lambda: floating.viewer.current_media is not None
         and floating.viewer.current_media.path == directory / 'b.png')
    choose_context_action(window, floating.viewer.view.viewport(), 'View / Copy Generation Prompt...')
    pump(lambda: any(dialog.isVisible() for dialog in floating.findChildren(GenerationPromptDialog)))
    dialog = next(dialog for dialog in floating.findChildren(GenerationPromptDialog) if dialog.isVisible())
    pump(lambda: dialog.previous_button.isEnabled())

    # The dialog is a separate window even though it has the viewer as parent.
    # Place its arrow directly over a resize border of that parent.
    floating.resize(350, 350)
    floating.move(200, 340)
    point = floating.mapToGlobal(QPoint(1, floating.height() // 2))
    button = dialog.previous_button
    dialog.move(dialog.pos() + point - button.mapToGlobal(button.rect().center()))
    QTest.qWait(100)
    assert floating._resize_zone_from_local_pos(
        floating.mapFromGlobal(button.mapToGlobal(button.rect().center()))) is not None
    clicks = []
    button.clicked.connect(lambda: clicks.append(True))
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert clicks == [True]
    assert not floating._resize_active
    pump(lambda: dialog.path == directory / 'a.png'
         and floating.viewer.current_media.path == dialog.path
         and dialog.text.toPlainText() == 'prompt A')


def test_double_click_setting_is_saved_and_restored(prompt_browser):
    from dialogs.settings_dialog import SettingsDialog

    window, _directory, _mode = prompt_browser
    first = SettingsDialog(window)
    second = None
    try:
        combo = next(item for item in first.findChildren(SettingsComboBox)
                     if item.key == 'image_list_double_click_action')
        assert combo.findText('generation prompt viewer') >= 0
        combo.setCurrentText('system default app')
        combo.setCurrentText('generation prompt viewer')
        assert settings.value('image_list_double_click_action', type=str) == 'generation prompt viewer'
        second = SettingsDialog(window)
        restored = next(item for item in second.findChildren(SettingsComboBox)
                        if item.key == 'image_list_double_click_action')
        assert restored.currentText() == 'generation prompt viewer'
    finally:
        dispose_widget(first)
        if second is not None:
            dispose_widget(second)


def test_double_click_modifiers_keep_existing_alternatives(prompt_browser, monkeypatch):
    window, directory, _mode = prompt_browser
    view, source, proxy = window.image_list.list_view, window.image_list_model, window.proxy_image_list_model
    index = proxy.mapFromSource(source.index(source.get_loaded_row_for_path(directory / 'b.png'), 0))
    pump(lambda: view.visualRect(index).isValid())
    calls = []
    monkeypatch.setattr(view, '_spawn_viewer_for_double_click',
                        lambda item, event: calls.append(('floating', item.data(Qt.UserRole).path)) or True)
    monkeypatch.setattr(view, '_open_double_click_in_system_app',
                        lambda image: calls.append(('system', image.path)) or True)
    monkeypatch.setattr(view, 'open_generation_prompt_at_index',
                        lambda item: calls.append(('prompt', item.data(Qt.UserRole).path)) or True)
    monkeypatch.setattr(view, '_show_in_windows_explorer',
                        lambda path: calls.append(('explorer', path)))
    for action, normal, control in (
            ('spawn viewer', 'floating', 'system'),
            ('system default app', 'system', 'floating'),
            ('generation prompt viewer', 'prompt', 'floating')):
        settings.setValue('image_list_double_click_action', action)
        for modifier, expected in ((Qt.KeyboardModifier.NoModifier, normal),
                                   (Qt.KeyboardModifier.ControlModifier, control),
                                   (Qt.KeyboardModifier.AltModifier, 'explorer')):
            QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, modifier,
                              view.visualRect(index).center())
            assert calls.pop() == (expected, directory / 'b.png')


def test_navigation_discards_an_older_prompt_read(prompt_browser, monkeypatch):
    window, directory, _mode = prompt_browser
    view, source, proxy = window.image_list.list_view, window.image_list_model, window.proxy_image_list_model
    started, release = threading.Event(), threading.Event()

    def delayed_read(path, cancelled):
        if path.name == 'a.png':
            started.set()
            release.wait(8)
        return [PromptCandidate(path.stem, 'Saved')]

    monkeypatch.setattr(prompt_ui, 'read_generation_prompts', delayed_read)
    index = proxy.mapFromSource(source.index(source.get_loaded_row_for_path(directory / 'a.png'), 0))
    view.setCurrentIndex(index)
    window.commit_thumbnail_click_selection(index)
    try:
        view.view_generation_prompt_action.trigger()
        pump(lambda: bool(window.findChildren(GenerationPromptDialog)) and started.is_set())
        dialog = window.findChildren(GenerationPromptDialog)[-1]
        QTest.mouseClick(dialog.next_button, Qt.MouseButton.LeftButton)
        pump(lambda: dialog.path == directory / 'b.png'
             and window.image_viewer.current_media.path == dialog.path)
        assert dialog.text.toPlainText() == '' and not dialog.copy_button.isEnabled()
        release.set()
        pump(lambda: dialog.text.toPlainText() == 'b')
        assert dialog.filename.text() == 'b.png'
    finally:
        release.set()


def test_browsing_after_ambiguous_copy_does_not_copy_automatically(prompt_browser, monkeypatch):
    window, directory, _mode = prompt_browser
    view, source, proxy = window.image_list.list_view, window.image_list_model, window.proxy_image_list_model

    def read(path, cancelled):
        return ([PromptCandidate('one', 'First'), PromptCandidate('two', 'Second')]
                if path.name == 'a.png' else [PromptCandidate('next prompt', 'Saved')])

    monkeypatch.setattr(prompt_ui, 'read_generation_prompts', read)
    index = proxy.mapFromSource(source.index(source.get_loaded_row_for_path(directory / 'a.png'), 0))
    view.setCurrentIndex(index)
    window.commit_thumbnail_click_selection(index)
    QApplication.clipboard().setText('before')
    view.copy_generation_prompt_action.trigger()
    pump(lambda: any(item.isVisible() and item.source.count() == 2
                     for item in window.findChildren(GenerationPromptDialog)))
    dialog = next(item for item in window.findChildren(GenerationPromptDialog) if item.isVisible())
    QTest.mouseClick(dialog.next_button, Qt.MouseButton.LeftButton)
    pump(lambda: dialog.path == directory / 'b.png' and dialog.text.toPlainText() == 'next prompt')
    assert dialog.isVisible() and QApplication.clipboard().text() == 'before'


def test_main_viewer_menu_prompt_arrows_update_the_main_viewer(prompt_browser):
    window, directory, _mode = prompt_browser
    source, proxy, view = window.image_list_model, window.proxy_image_list_model, window.image_list.list_view
    index = proxy.mapFromSource(source.index(source.get_loaded_row_for_path(directory / 'b.png'), 0))
    view.setCurrentIndex(index)
    window.commit_thumbnail_click_selection(index)
    menu = window.menu_manager.toolbars_menu.parentWidget()
    action = next(item for item in menu.actions() if item.text() == 'Generation Prompt (Main Viewer)...')
    action.trigger()
    pump(lambda: any(item.isVisible() for item in window.findChildren(GenerationPromptDialog)))
    dialog = next(item for item in window.findChildren(GenerationPromptDialog) if item.isVisible())
    pump(lambda: dialog.next_button.isEnabled())
    QTest.mouseClick(dialog.next_button, Qt.MouseButton.LeftButton)
    pump(lambda: dialog.path == directory / 'c.png'
         and dialog.text.toPlainText() == 'prompt C'
         and window.image_viewer.current_media is not None
         and window.image_viewer.current_media.path == dialog.path)


@pytest.mark.parametrize('prompt_browser', ['memory', 'masonry', 'virtual'], indirect=True)
def test_prompt_arrows_follow_changed_sort_order(prompt_browser):
    window, directory, _mode = prompt_browser
    view, source, proxy = window.image_list.list_view, window.image_list_model, window.proxy_image_list_model
    index = proxy.mapFromSource(source.index(source.get_loaded_row_for_path(directory / 'b.png'), 0))
    view.setCurrentIndex(index)
    window.commit_thumbnail_click_selection(index)
    view.view_generation_prompt_action.trigger()
    pump(lambda: any(item.isVisible() for item in window.findChildren(GenerationPromptDialog)))
    dialog = next(item for item in window.findChildren(GenerationPromptDialog) if item.isVisible())
    window.image_list.set_sort_state('Name', 'DESC', reapply_sort=True, preserve_selection=True)
    pump(lambda: source._view_prepare_owner is None and dialog.next_button.isEnabled(), seconds=20)
    QTest.qWait(500)
    QTest.mouseClick(dialog.next_button, Qt.MouseButton.LeftButton)
    pump(lambda: dialog.path == directory / 'a.png'
         and window.image_viewer.current_media is not None
         and window.image_viewer.current_media.path == dialog.path
         and dialog.text.toPlainText() == 'prompt A', seconds=20)
    QTest.qWait(900)
    assert view.currentIndex().data(Qt.ItemDataRole.UserRole).path == directory / 'a.png'


def test_secondary_browser_prompt_keeps_its_source_context(prompt_browser):
    window, directory, _mode = prompt_browser
    other_dir = directory / 'secondary'
    other_dir.mkdir()
    _write_image(other_dir / 'x.png', 'secondary X')
    _write_image(other_dir / 'y.png', 'secondary Y')
    window._ensure_secondary_browser()
    secondary = window._secondary_browser
    secondary.dock.show()
    secondary.load_directory(other_dir)
    pump(lambda: len(secondary.image_list_model.images) == 2
         and secondary.image_list_model._view_prepare_owner is None, seconds=15)
    source, proxy, view = secondary.image_list_model, secondary.proxy_image_list_model, secondary.dock.list_view
    index = proxy.mapFromSource(source.index(source.get_loaded_row_for_path(other_dir / 'x.png'), 0))
    view.setCurrentIndex(index)
    secondary.commit_thumbnail_click_selection(index)
    pump(lambda: window.image_viewer.current_media is not None
         and window.image_viewer.current_media.path == other_dir / 'x.png')
    view.view_generation_prompt_action.trigger()
    pump(lambda: any(item.isVisible() and item.path == other_dir / 'x.png'
                     for item in window.findChildren(GenerationPromptDialog)))
    dialog = next(item for item in window.findChildren(GenerationPromptDialog)
                  if item.isVisible() and item.path == other_dir / 'x.png')

    primary = window.image_list.list_view
    primary_source, primary_proxy = window.image_list_model, window.proxy_image_list_model
    primary_index = primary_proxy.mapFromSource(
        primary_source.index(primary_source.get_loaded_row_for_path(directory / 'a.png'), 0))
    primary.setCurrentIndex(primary_index)
    window.commit_thumbnail_click_selection(primary_index)
    pump(lambda: window.image_viewer.current_media is not None
         and window.image_viewer.current_media.path == directory / 'a.png')
    QTest.mouseClick(dialog.next_button, Qt.MouseButton.LeftButton)
    pump(lambda: dialog.path == other_dir / 'y.png'
         and window.image_viewer.current_media is not None
         and window.image_viewer.current_media.path == dialog.path
         and dialog.text.toPlainText() == 'secondary Y', seconds=15)
    assert primary.currentIndex().data(Qt.ItemDataRole.UserRole).path == directory / 'a.png'


@pytest.mark.parametrize('prompt_browser', ['masonry', 'virtual'], indirect=True)
def test_closing_a_pending_prompt_keeps_a_sibling_window_usable(prompt_browser, monkeypatch):
    window, directory, _mode = prompt_browser
    view, source, proxy = window.image_list.list_view, window.image_list_model, window.proxy_image_list_model
    index = proxy.mapFromSource(source.index(source.get_loaded_row_for_path(directory / 'b.png'), 0))
    view.setCurrentIndex(index)
    window.commit_thumbnail_click_selection(index)
    view.view_generation_prompt_action.trigger()
    view.view_generation_prompt_action.trigger()
    pump(lambda: len(window.findChildren(GenerationPromptDialog)) == 2)
    first, sibling = window.findChildren(GenerationPromptDialog)
    pump(lambda: first.next_button.isEnabled() and sibling.previous_button.isEnabled())
    pump(lambda: not source._loading_pages and not source._pending_page_results, seconds=10)
    started, release = threading.Event(), threading.Event()
    original = source._load_images_from_db
    errors = []
    monkeypatch.setattr(sys, 'excepthook', lambda *args: errors.append(args))

    def delayed_page(page, *args, **kwargs):
        if page == 1:
            started.set()
            release.wait(8)
        return original(page, *args, **kwargs)

    monkeypatch.setattr(source, '_load_images_from_db', delayed_page)
    try:
        source._prune_loaded_pages_to_window(0, 0)
        QTest.mouseClick(first.next_button, Qt.MouseButton.LeftButton)
        pump(started.is_set)
        navigator = first._navigator
        first.close()
        assert navigator._closed and navigator._pending is None
        release.set()
        pump(lambda: 1 in source._pages, seconds=10)
        QTest.mouseClick(sibling.previous_button, Qt.MouseButton.LeftButton)
        pump(lambda: sibling.path == directory / 'a.png'
             and sibling.text.toPlainText() == 'prompt A'
             and window.image_viewer.current_media is not None
             and window.image_viewer.current_media.path == sibling.path, seconds=20)
        QTest.qWait(500)
        assert not errors
    finally:
        release.set()


@pytest.mark.parametrize('prompt_browser', ['masonry', 'virtual'], indirect=True)
def test_floating_prompt_recovers_an_evicted_anchor_page(prompt_browser):
    window, directory, _mode = prompt_browser
    source, proxy = window.image_list_model, window.proxy_image_list_model
    index = proxy.mapFromSource(source.index(source.get_loaded_row_for_path(directory / 'b.png'), 0))
    floating = window.spawn_floating_viewer_at(index)
    pump(lambda: floating.viewer.current_media is not None
         and floating.viewer.current_media.path == directory / 'b.png')
    choose_context_action(window, floating.viewer.view.viewport(), 'View / Copy Generation Prompt...')
    pump(lambda: bool(floating.findChildren(GenerationPromptDialog)))
    dialog = floating.findChildren(GenerationPromptDialog)[-1]
    pump(lambda: dialog.next_button.isEnabled())
    pump(lambda: not source._loading_pages and not source._pending_page_results)
    source._prune_loaded_pages_to_window(1, 1)
    assert 0 not in source._pages
    pump(lambda: source.get_loaded_row_for_path(directory / 'b.png') < 0
         and dialog.next_button.isEnabled())
    QTest.mouseClick(dialog.next_button, Qt.MouseButton.LeftButton)
    pump(lambda: dialog.path == directory / 'c.png'
         and floating.viewer.current_media is not None
         and floating.viewer.current_media.path == dialog.path
         and dialog.text.toPlainText() == 'prompt C', seconds=20)


@pytest.mark.parametrize('prompt_browser', ['masonry', 'virtual'], indirect=True)
def test_cold_next_page_loads_off_thread_and_keeps_selection(prompt_browser, monkeypatch):
    window, directory, _mode = prompt_browser
    view, source, proxy = window.image_list.list_view, window.image_list_model, window.proxy_image_list_model
    index = proxy.mapFromSource(source.index(source.get_loaded_row_for_path(directory / 'b.png'), 0))
    view.setCurrentIndex(index)
    window.commit_thumbnail_click_selection(index)
    view.view_generation_prompt_action.trigger()
    pump(lambda: any(item.isVisible() for item in window.findChildren(GenerationPromptDialog)))
    dialog = next(item for item in window.findChildren(GenerationPromptDialog) if item.isVisible())
    pump(lambda: dialog.path == directory / 'b.png' and dialog.next_button.isEnabled())
    pump(lambda: not source._loading_pages and not source._pending_page_results, seconds=10)
    started, release = threading.Event(), threading.Event()
    worker_threads = []
    original = source._load_images_from_db

    def delayed_page(page, *args, **kwargs):
        if page == 1:
            worker_threads.append(threading.get_ident())
            started.set()
            release.wait(8)
        return original(page, *args, **kwargs)

    monkeypatch.setattr(source, '_load_images_from_db', delayed_page)
    try:
        source._prune_loaded_pages_to_window(0, 0)
        assert 1 not in source._pages
        before = time.monotonic()
        QTest.mouseClick(dialog.next_button, Qt.MouseButton.LeftButton)
        assert time.monotonic() - before < 1.0
        pump(started.is_set, seconds=5)
        tick = []
        QTimer.singleShot(0, window, lambda: tick.append(True))
        pump(lambda: bool(tick))
        assert worker_threads[0] != threading.get_ident()
        assert dialog.path == directory / 'b.png'
        release.set()
        pump(lambda: dialog.path == directory / 'c.png'
             and window.image_viewer.current_media is not None
             and window.image_viewer.current_media.path == dialog.path, seconds=20)
        QTest.qWait(1000)
        assert view.currentIndex().data(Qt.ItemDataRole.UserRole).path == directory / 'c.png'
    finally:
        release.set()
