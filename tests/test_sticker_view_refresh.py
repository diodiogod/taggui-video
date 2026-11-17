"""Sticker edits refresh overlays without reopening the displayed media.

Run through tests/run_isolated.py with QT_QPA_PLATFORM=windows for native input
and captures. The browser fixture opens real images and drains/destroys viewers.
"""

import json

import pytest
from PySide6.QtCore import QPoint, QPointF, QTimer, Qt
from PySide6.QtGui import QCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu

from qt_test_helpers import assert_capture_contains_color, pump
from test_generation_prompt_navigation import prompt_browser
from utils.sidecar import taggui_sidecar_path


def _visible_frame(viewer):
    viewport = viewer.view.viewport()
    origin = viewport.mapToGlobal(QPoint()) - viewport.screen().geometry().topLeft()
    return viewport.screen().grabWindow(
        0, origin.x(), origin.y(), viewport.width(), viewport.height(),
    ).toImage()


def _view_state(viewer):
    return (viewer.current_image_item, viewer.view.transform(),
            viewer.view.horizontalScrollBar().value(), viewer.view.verticalScrollBar().value(),
            viewer.scene.sceneRect(), viewer.is_zoom_to_fit)


def _open_image(window, path):
    source, proxy = window.image_list_model, window.proxy_image_list_model
    view = window.image_list.list_view

    def index():
        return proxy.mapFromSource(source.index(source.get_loaded_row_for_path(path), 0))

    pump(lambda: index().isValid())
    view.scrollTo(index())
    QTest.qWait(180)
    pump(lambda: view.visualRect(index()).isValid()
         and view.viewport().rect().contains(view.visualRect(index()).center())
         and not view._masonry_calculating)
    QTest.mouseClick(view.viewport(), Qt.LeftButton, pos=view.visualRect(index()).center())
    pump(lambda: window.image_viewer.current_media is not None
         and window.image_viewer.current_media.path == path
         and window.image_viewer._image_decode_owner is None)


def _replace_sticker(window, viewer, pos, label):
    failures = []
    watchdog = QTimer(window)
    watchdog.setSingleShot(True)
    watchdog.timeout.connect(lambda: QApplication.activePopupWidget().close()
                              if isinstance(QApplication.activePopupWidget(), QMenu) else None)

    def choose():
        menu = QApplication.activePopupWidget()
        try:
            assert isinstance(menu, QMenu)
            action = next(action for action in menu.actions() if action.text().strip() == label)
            QTest.mouseClick(menu, Qt.LeftButton, pos=menu.actionGeometry(action).center())
        except Exception as error:
            failures.append(error)
            if isinstance(menu, QMenu):
                menu.close()

    QTimer.singleShot(0, window, choose)
    watchdog.start(3000)
    QTest.mouseClick(viewer.view.viewport(), Qt.RightButton, pos=pos)
    watchdog.stop()
    watchdog.deleteLater()
    assert not failures, failures


@pytest.mark.skipif(QApplication.platformName() in {'offscreen', 'minimal'},
                    reason='Requires native cursor hit testing and visible desktop capture.')
@pytest.mark.parametrize('prompt_browser', ['memory', 'masonry', 'virtual'], indirect=True)
@pytest.mark.parametrize('filtered', [False, True])
def test_move_replace_and_history_keep_loaded_image_and_zoom(prompt_browser, monkeypatch, filtered):
    window, directory, _mode = prompt_browser
    viewer = window.image_viewer
    source, proxy = window.image_list_model, window.proxy_image_list_model
    window.set_main_viewer_visible(True, save=False)
    viewer.set_main_controls_overlay_attached(False)
    window.set_reaction_controls_attached(False, save=False)
    window.move(window.screen().availableGeometry().topLeft() + QPoint(10, 20))
    window.raise_()
    window.activateWindow()
    pump(lambda: viewer._image_decode_owner is None and viewer.sticker_controls.bounds() is not None)

    if filtered:
        window.image_list.filter_line_edit.setText('review_rank:>=0')
        QTest.keyClick(window.image_list.filter_line_edit, Qt.Key_Return)
        pump(lambda: bool(proxy.filter) and source._view_prepare_owner is None)
        QTest.qWait(500)
        _open_image(window, directory / 'a.png')

    viewer.zoom_fit()
    viewport = viewer.view.viewport()
    QTest.qWait(120)
    point = viewport.rect().center()
    QCursor.setPos(viewport.mapToGlobal(point))
    QTest.mouseMove(viewport, point)
    viewer.view.setFocus()
    pump(lambda: QApplication.widgetAt(QCursor.pos()) is viewport)
    QTest.keyClick(viewer.view, Qt.Key_1)
    image = viewer.current_media
    controls = viewer.sticker_controls
    pump(lambda: len(image.review_stickers) == 1 and len(controls.items) == 1
         and viewer._image_decode_owner is None)
    QTest.qWait(300)
    original_sticker = image.review_stickers[0]

    siblings = []
    for number, path in enumerate((image.path, directory / 'b.png')):
        index = proxy.mapFromSource(source.index(source.get_loaded_row_for_path(path), 0))
        floating = window.spawn_floating_viewer_at(index)
        floating.resize(300, 220)
        available = window.screen().availableGeometry()
        floating.move(available.right() - 320, available.top() + 40 + number * 270)
        sibling = floating.viewer
        pump(lambda: sibling.current_media is not None and sibling._image_decode_owner is None)
        sibling.zoom_fit()
        sibling_fit = sibling._compute_fit_scale(sibling.scene.sceneRect(), sibling.view.viewport().rect())
        sibling._apply_uniform_zoom_scale(sibling_fit * (1.2 + number * .3), False)
        siblings.append(sibling)
    other_image = siblings[1].current_media
    other_image.review_rank = 4
    other_image.love = True
    source.write_meta_to_disk(other_image, notify=False)
    source.save_reactions_to_db(other_image)
    sibling_states = [_view_state(sibling) for sibling in siblings]
    QTest.qWait(120)
    assert_capture_contains_color(_visible_frame(siblings[0]), (255, 0, 0))
    assert_capture_contains_color(_visible_frame(siblings[1]), (0, 128, 0))
    window.raise_()
    window.activateWindow()

    # Use independent zoom/pan and retain the actual media item installed by
    # normal image opening; preserving a numeric zoom value alone is not enough.
    fit = viewer._compute_fit_scale(viewer.scene.sceneRect(), viewport.rect())
    viewer._apply_uniform_zoom_scale(fit * 1.8, False,
                                     focus_scene_pos=QPointF(37, 26))
    QTest.qWait(120)
    assert_capture_contains_color(_visible_frame(viewer), (255, 0, 0))
    before = _view_state(viewer)
    calls = []
    original_load = viewer.load_image
    original_submit = viewer._image_decode_task.submit
    original_prepare = source.prepare_ordered_view

    def load(*args, **kwargs):
        calls.append('load')
        return original_load(*args, **kwargs)

    def decode(*args, **kwargs):
        calls.append('decode')
        return original_submit(*args, **kwargs)

    def prepare(*args, **kwargs):
        calls.append('prepare')
        return original_prepare(*args, **kwargs)

    monkeypatch.setattr(viewer, 'load_image', load)
    monkeypatch.setattr(viewer._image_decode_task, 'submit', decode)
    monkeypatch.setattr(source, 'prepare_ordered_view', prepare)

    start = viewer.view.mapFromScene(controls.items[0].pos())
    end = start + QPoint(55, 28)
    QTest.mousePress(viewport, Qt.LeftButton, pos=start)
    QTest.mouseMove(viewport, end, 80)
    QTest.mouseRelease(viewport, Qt.LeftButton, pos=end)
    pump(lambda: image.review_stickers[0].x != original_sticker.x)
    QTest.qWait(350)
    assert calls == [], calls
    assert _view_state(viewer) == before
    assert [_view_state(sibling) for sibling in siblings] == sibling_states
    assert_capture_contains_color(_visible_frame(viewer), (255, 0, 0))
    moved_sticker = image.review_stickers[0]

    _replace_sticker(window, viewer, viewer.view.mapFromScene(controls.items[0].pos()), '2')
    pump(lambda: image.review_stickers[0].badge_id == 'rank_2')
    QTest.qWait(350)
    assert calls == [], calls
    assert _view_state(viewer) == before
    assert image.review_rank == 2
    assert image.review_stickers[0].x == moved_sticker.x
    assert image.review_stickers[0].y == moved_sticker.y
    assert siblings[0].sticker_controls.items[0].sticker == image.review_stickers[0]
    assert [_view_state(sibling) for sibling in siblings] == sibling_states
    assert other_image.review_rank == 4 and other_image.love and not other_image.review_stickers
    sidecar = taggui_sidecar_path(image.path)
    assert json.loads(sidecar.read_text(encoding='utf-8'))['review_stickers'] == [vars(image.review_stickers[0])]

    for key, expected in ((Qt.Key_Z, moved_sticker), (Qt.Key_Z, original_sticker),
                          (Qt.Key_Y, moved_sticker)):
        viewer.view.setFocus()
        QTest.keyClick(viewer.view, key, Qt.ControlModifier)
        pump(lambda: image.review_stickers == (expected,))
        QTest.qWait(150)
        assert calls == [], calls
        assert _view_state(viewer) == before
        assert [_view_state(sibling) for sibling in siblings] == sibling_states
        assert siblings[0].sticker_controls.items[0].sticker == expected
        assert json.loads(sidecar.read_text(encoding='utf-8'))['review_stickers'] == [vars(expected)]
    assert image.path == directory / 'a.png'
    assert not source._metadata_filter_refresh_pending

    # A genuine thumbnail selection must still open the new image normally.
    _open_image(window, directory / 'b.png')
    assert calls and 'load' in calls
    assert_capture_contains_color(_visible_frame(viewer), (0, 128, 0))


@pytest.mark.skipif(QApplication.platformName() in {'offscreen', 'minimal'},
                    reason='Requires native cursor hit testing and popup input.')
@pytest.mark.parametrize('prompt_browser', ['memory', 'masonry', 'virtual'], indirect=True)
def test_replacement_that_changes_filter_membership_still_requeries(prompt_browser):
    window, directory, _mode = prompt_browser
    source, proxy = window.image_list_model, window.proxy_image_list_model
    viewer = window.image_viewer
    window.set_main_viewer_visible(True, save=False)
    viewer.set_main_controls_overlay_attached(False)
    window.set_reaction_controls_attached(False, save=False)
    window.move(window.screen().availableGeometry().topLeft() + QPoint(10, 20))
    window.raise_()
    window.activateWindow()
    pump(lambda: viewer._image_decode_owner is None and viewer.sticker_controls.bounds() is not None)
    viewer.zoom_fit()
    viewport = viewer.view.viewport()
    QTest.qWait(100)
    QCursor.setPos(viewport.mapToGlobal(viewport.rect().center()))
    QTest.mouseMove(viewport, viewport.rect().center())
    viewer.view.setFocus()
    pump(lambda: QApplication.widgetAt(QCursor.pos()) is viewport)
    QTest.qWait(80)
    QTest.keyClick(viewer.view, Qt.Key_1)
    pump(lambda: len(viewer.sticker_controls.items) == 1)

    window.image_list.filter_line_edit.setText('review_rank:=1')
    QTest.keyClick(window.image_list.filter_line_edit, Qt.Key_Return)
    pump(lambda: bool(proxy.filter) and proxy.rowCount() == 1 and source._view_prepare_owner is None)
    _open_image(window, directory / 'a.png')
    controls = viewer.sticker_controls
    saved = taggui_sidecar_path(directory / 'a.png')
    _replace_sticker(window, viewer, viewer.view.mapFromScene(controls.items[0].pos()), '2')
    assert json.loads(saved.read_text(encoding='utf-8'))['review_rank'] == 2
    pump(lambda: proxy.rowCount() == 0 and source._view_prepare_owner is None)
    assert json.loads(saved.read_text(encoding='utf-8'))['review_rank'] == 2

    # Selection changes also participate in Ctrl+Z. Use the shared keyboard
    # workflow rather than bypassing it through the model's private history.
    def history_until(key, rank):
        for _ in range(4):
            viewer.view.setFocus()
            QTest.keyClick(viewer.view, key, Qt.ControlModifier)
            QTest.qWait(250)
            if json.loads(saved.read_text(encoding='utf-8'))['review_rank'] == rank:
                return
        pytest.fail(f'History did not restore rank {rank}')

    history_until(Qt.Key_Z, 1)
    pump(lambda: proxy.rowCount() == 1 and source._view_prepare_owner is None)
    image = proxy.index(0, 0).data(Qt.UserRole)
    assert image.path == directory / 'a.png' and image.review_rank == 1
    assert image.review_stickers[0].badge_id == 'rank_1'
    history_until(Qt.Key_Y, 2)
    pump(lambda: proxy.rowCount() == 0 and source._view_prepare_owner is None)
    assert json.loads(saved.read_text(encoding='utf-8'))['review_rank'] == 2
