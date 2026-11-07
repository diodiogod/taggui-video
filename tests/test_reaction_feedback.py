"""Reaction feedback must survive a refresh of the same displayed media."""

import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from qt_test_helpers import pump
from test_generation_prompt_navigation import prompt_browser
from utils.sidecar import taggui_sidecar_path


@pytest.mark.parametrize('prompt_browser', ['memory', 'masonry', 'virtual'], indirect=True)
def test_reaction_feedback_survives_image_refresh(prompt_browser):
    window, directory, _mode = prompt_browser
    viewer = window.image_viewer
    window.set_main_viewer_visible(True, save=False)
    window.set_reaction_controls_attached(False, save=False)
    window.set_reaction_controls_panel_visible(True, save=False)
    overlay = viewer._reaction_feedback_overlay
    image = viewer.current_media
    assert image.path == directory / 'a.png'

    # Use the actual shortcut and toolbar action: both refresh the current
    # image and can cause a second asynchronous decode after the feedback starts.
    viewer.view.setFocus()
    QTest.keyClick(viewer.view, Qt.Key.Key_L)
    pump(lambda: image.love and viewer._image_decode_owner is None)
    QTest.qWait(150)
    assert overlay.isVisible() and overlay._kind == 'love' and overlay._enabled
    assert overlay.get_progress() > 0 and overlay._opacity_effect.opacity() > 0

    bomb_button = window.menu_manager.bomb_button
    assert bomb_button.isVisible()
    QTest.mouseClick(bomb_button, Qt.MouseButton.LeftButton)
    pump(lambda: image.bomb and viewer._image_decode_owner is None)
    QTest.qWait(150)
    assert overlay.isVisible() and overlay._kind == 'bomb' and overlay._enabled
    assert overlay.get_progress() > 0 and overlay._opacity_effect.opacity() > 0
    sidecar = taggui_sidecar_path(image.path)
    pump(lambda: sidecar.exists()
         and json.loads(sidecar.read_text(encoding='utf-8')).get('love') is True
         and json.loads(sidecar.read_text(encoding='utf-8')).get('bomb') is True)

    love_button = window.menu_manager.love_button
    assert love_button.isVisible()
    QTest.mouseClick(love_button, Qt.MouseButton.LeftButton)
    pump(lambda: not image.love and viewer._image_decode_owner is None)
    QTest.qWait(150)
    assert overlay.isVisible() and overlay._kind == 'love' and not overlay._enabled

    viewer.view.setFocus()
    QTest.keyClick(viewer.view, Qt.Key.Key_B)
    pump(lambda: not image.bomb and viewer._image_decode_owner is None)
    QTest.qWait(150)
    assert overlay.isVisible() and overlay._kind == 'bomb' and not overlay._enabled

    # A real media change must still clear feedback belonging to the old file.
    source, proxy = window.image_list_model, window.proxy_image_list_model
    index = proxy.mapFromSource(source.index(source.get_loaded_row_for_path(directory / 'b.png'), 0))
    view = window.image_list.list_view
    view.scrollTo(index)
    QTest.qWait(200)
    index = proxy.mapFromSource(source.index(source.get_loaded_row_for_path(directory / 'b.png'), 0))
    pump(lambda: index.isValid() and view.visualRect(index).isValid()
         and view.viewport().rect().contains(view.visualRect(index).center())
         and not view._masonry_calculating)
    assert overlay.isVisible()
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.visualRect(index).center())
    pump(lambda: viewer.current_media is not None and viewer.current_media.path == directory / 'b.png')
    assert not overlay.isVisible()


@pytest.mark.parametrize('prompt_browser', ['masonry', 'virtual'], indirect=True)
def test_reaction_feedback_uses_list_when_main_viewer_is_hidden(prompt_browser):
    window, _directory, _mode = prompt_browser
    view = window.image_list.list_view
    window.set_main_viewer_visible(False, save=False)
    view.setFocus()
    QTest.keyClick(view, Qt.Key.Key_L)
    overlay = view._reaction_feedback_overlay
    pump(lambda: overlay.isVisible() and overlay.get_progress() > 0)
    QTest.qWait(150)
    assert overlay.isVisible() and overlay._kind == 'love' and overlay._enabled
    assert overlay._opacity_effect.opacity() > 0


@pytest.mark.parametrize('main_love,floating_love', [(True, False), (False, True)])
def test_floating_reaction_feedback_keeps_its_media_owner(prompt_browser, main_love, floating_love):
    window, directory, _mode = prompt_browser
    source, proxy = window.image_list_model, window.proxy_image_list_model
    main = window.image_viewer
    main_image = main.current_media
    index = proxy.mapFromSource(source.index(source.get_loaded_row_for_path(directory / 'b.png'), 0))
    floating_image = index.data(Qt.ItemDataRole.UserRole)
    main_image.love = main_love
    floating_image.love = floating_love
    source.persist_reaction_state(main_image)
    source.persist_reaction_state(floating_image)
    floating = window.spawn_floating_viewer_at(index)
    viewer = floating.viewer
    pump(lambda: viewer.current_media is floating_image and viewer._image_decode_owner is None)
    QTest.mouseClick(viewer.view.viewport(), Qt.MouseButton.LeftButton,
                     pos=viewer.view.viewport().rect().center())
    pump(lambda: window._get_explicit_action_target_viewer() is viewer)
    viewer.view.setFocus()
    QTest.keyClick(viewer.view, Qt.Key.Key_L)
    pump(lambda: floating_image.love is (not floating_love)
         and viewer._image_decode_owner is None)
    QTest.qWait(150)
    feedback = viewer._reaction_feedback_overlay
    assert feedback.isVisible() and feedback._kind == 'love'
    assert feedback._enabled is (not floating_love)
    assert main_image.love is main_love and main.current_media.path == directory / 'a.png'
    assert not main._reaction_feedback_overlay.isVisible()
    saved = taggui_sidecar_path(floating_image.path)
    pump(lambda: json.loads(saved.read_text(encoding='utf-8'))['love'] is (not floating_love))
    assert window.menu_manager.love_button.isChecked() is (not floating_love)

    source.undo()
    pump(lambda: floating_image.love is floating_love)
    assert main_image.love is main_love
    assert json.loads(saved.read_text(encoding='utf-8'))['love'] is floating_love
    source.redo()
    pump(lambda: floating_image.love is (not floating_love))
    assert main_image.love is main_love
    assert json.loads(saved.read_text(encoding='utf-8'))['love'] is (not floating_love)
