"""Reaction feedback must survive a refresh of the same displayed media."""

import json
import os
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, QRect, Qt
from PySide6.QtGui import QCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from qt_test_helpers import assert_capture_contains_color, pump
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
    button = window.menu_manager.love_button
    QTest.mouseMove(button, button.rect().center())
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


@pytest.mark.parametrize('prompt_browser', ['memory', 'masonry', 'virtual'], indirect=True)
@pytest.mark.parametrize('kind,key', [('love', Qt.Key.Key_L), ('bomb', Qt.Key.Key_B)])
@pytest.mark.skipif(
    QApplication.platformName() in {'offscreen', 'minimal'},
    reason='Requires native cursor hit testing and desktop capture; use QT_QPA_PLATFORM=windows.',
)
def test_reaction_becomes_sticker_and_normal_feedback_stays_normal(prompt_browser, kind, key):
    window, directory, mode = prompt_browser
    viewer = window.image_viewer
    window.set_main_viewer_visible(True, save=False)
    window.set_reaction_controls_attached(False, save=False)
    window.set_reaction_controls_panel_visible(True, save=False)
    window.raise_()
    window.activateWindow()
    controls = viewer.sticker_controls
    viewport = viewer.view.viewport()
    overlay = viewer._reaction_feedback_overlay
    pump(lambda: viewer._image_decode_owner is None and controls.bounds() is not None)
    viewer.zoom_fit()
    QTest.qWait(100)
    image = viewer.current_media
    bounds = controls.bounds()
    point = viewer.view.mapFromScene(
        bounds.topLeft() + QPointF(bounds.width() * 0.28, bounds.height() * 0.38)
    )
    QCursor.setPos(viewport.mapToGlobal(point))
    QTest.mouseMove(viewport, point)
    viewer.view.setFocus()
    pump(lambda: QApplication.widgetAt(QCursor.pos()) is viewport)
    QTest.qWait(80)

    def capture(stage):
        origin = viewport.mapToGlobal(viewport.rect().topLeft())
        frame = viewport.screen().grabWindow(
            0, origin.x(), origin.y(), viewport.width(), viewport.height(),
        )
        destination = os.environ.get('TAGGUI_STICKER_CAPTURE_DIR')
        if destination:
            target = Path(destination)
            target.mkdir(parents=True, exist_ok=True)
            frame.save(str(target / f'{mode}-{kind}-{stage}.png'))
        return frame.toImage()

    assert_capture_contains_color(capture('before'), (255, 0, 0))
    expected_anchor = viewer.view.mapToScene(viewport.mapFromGlobal(QCursor.pos()))
    expected_x = (expected_anchor.x() - bounds.left()) / bounds.width()
    expected_y = (expected_anchor.y() - bounds.top()) / bounds.height()

    QTest.keyClick(viewer.view, key)
    pump(lambda: len(image.review_stickers) == 1 and len(controls.items) == 1
         and viewer._image_decode_owner is None)
    sticker = image.review_stickers[0]
    item = controls.items[0]
    assert sticker.badge_id == f'reaction_{kind}'
    assert abs(sticker.x - expected_x) < 0.0001 and abs(sticker.y - expected_y) < 0.0001
    assert getattr(image, kind)
    assert not overlay.isVisible() and not overlay._anchor_rect.isValid()
    assert item.placement_progress < 1
    assert not item.toolTip()
    assert item.pixmap().width() > round(item.logical_size * item.display_scale)
    assert (item.pos() - expected_anchor).manhattanLength() < 0.0001
    QTest.qWait(60)
    early_frame = capture('start')
    expected_color = (255, 110, 138) if kind == 'love' else (42, 44, 52)

    def assert_visible_artwork(frame):
        dpr = frame.devicePixelRatio()
        center = viewer.view.mapFromScene(controls.items[0].pos())
        region = QRect(round((center.x() - 6) * dpr), round((center.y() - 6) * dpr),
                       round(12 * dpr), round(12 * dpr))
        assert_capture_contains_color(frame.copy(region), expected_color, minimum_fraction=.3)

    assert_visible_artwork(early_frame)

    QTest.qWait(180)
    progress = controls.items[0].placement_progress
    assert 0 < progress < 1
    # Deliver the real model signal used after metadata saves. The new scene
    # must continue the same placement instead of showing a second animation.
    source = window.image_list_model
    index = source.index(source.get_loaded_row_for_path(image.path), 0)
    source.dataChanged.emit(index, index)
    pump(lambda: viewer._image_decode_owner is None and len(controls.items) == 1)
    assert controls.items[0].placement_progress >= progress
    assert not overlay.isVisible()
    capture('refresh')
    pump(lambda: not controls._placement_timer.isActive(), seconds=5)
    item = controls.items[0]
    assert item.placement_progress == 1
    assert not item.toolTip()
    assert item.pixmap().width() == round(item.logical_size * item.display_scale)
    assert (item.pos() - expected_anchor).manhattanLength() < 0.0001
    assert len([entry for entry in viewer.scene.items() if entry is item]) == 1
    assert not overlay.isVisible()
    QTest.qWait(40)
    assert_visible_artwork(capture('settled'))

    saved = taggui_sidecar_path(image.path)
    state = json.loads(saved.read_text(encoding='utf-8'))
    assert state[kind] and state['review_stickers'][0]['id'] == sticker.id

    # An already active reaction still places another sticker at a new cursor
    # position. Removing it during its animation must also cancel the timer.
    second_point = viewer.view.mapFromScene(
        bounds.topLeft() + QPointF(bounds.width() * 0.65, bounds.height() * 0.50)
    )
    QCursor.setPos(viewport.mapToGlobal(second_point))
    QTest.mouseMove(viewport, second_point)
    QTest.keyClick(viewer.view, key)
    pump(lambda: len(image.review_stickers) == 2 and len(controls.items) == 2
         and viewer._image_decode_owner is None)
    assert controls._placements

    # After placement, leave the image and use the same key. This must use
    # the original centered feedback and clear the matching reaction sticker.
    button = getattr(window.menu_manager, f'{kind}_button')
    QTest.mouseMove(button, button.rect().center())
    QCursor.setPos(button.mapToGlobal(button.rect().center()))
    assert QApplication.widgetAt(QCursor.pos()) is not viewport
    viewer.view.setFocus()
    QTest.keyClick(viewer.view, key)
    pump(lambda: not getattr(image, kind) and not image.review_stickers
         and viewer._image_decode_owner is None)
    QTest.qWait(120)
    assert overlay.isVisible() and overlay._kind == kind and not overlay._enabled
    assert not overlay._anchor_rect.isValid()
    assert abs(overlay.geometry().center().x() - viewport.rect().center().x()) <= 1
    assert abs(overlay.geometry().center().y() - viewport.rect().center().y()) <= 1
    assert not controls.items and not controls._placements

    source.undo()
    pump(lambda: getattr(image, kind) and len(controls.items) == 2)
    assert image.review_stickers[0].id == sticker.id
    assert all(item.placement_progress == 1 for item in controls.items)
    assert json.loads(saved.read_text(encoding='utf-8'))[kind]
    source.redo()
    pump(lambda: not getattr(image, kind) and not controls.items)
    assert not json.loads(saved.read_text(encoding='utf-8'))[kind]

    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    pump(lambda: getattr(image, kind) and viewer._image_decode_owner is None)
    assert not image.review_stickers and not controls.items
    assert overlay.isVisible() and overlay._enabled
    assert not overlay._anchor_rect.isValid()
