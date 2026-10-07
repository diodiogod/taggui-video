"""Exercise actual wall badge clicks without starting a native decoder."""
from dataclasses import replace
import json
import sys
import traceback

import pytest
from PySide6.QtCore import Qt, QCoreApplication, QEvent
from PySide6.QtTest import QTest
from shiboken6 import isValid

from qt_test_helpers import APP, dispose_widget, pump
from utils.image import Image
from utils.image_index_db import ImageIndexDB
from utils.latest_task import LatestTask
from utils.review_marks import ReviewFlag, serialize_review_flags
from utils.sidecar import taggui_sidecar_path
from widgets.main_window import MainWindow
from widgets.video_player import VideoPlayerWidget


@pytest.fixture
def wall_factory(monkeypatch, tmp_path):
    monkeypatch.setenv('TAGGUI_FORCE_CLEAN_EXIT_ON_CLOSE', '0')
    monkeypatch.setattr(MainWindow, 'restore', lambda self: None)
    monkeypatch.setattr(VideoPlayerWidget, 'prewarm_gl_widget', lambda *args: None)
    errors = []
    monkeypatch.setattr(sys, 'excepthook', lambda *error: errors.append(error))
    host = MainWindow(APP)
    source, proxy = host.image_list_model, host.proxy_image_list_model
    source._directory_path = tmp_path
    source._db = ImageIndexDB(tmp_path)
    windows = []
    players = []

    def create(count, playing, paginated):
        images = [Image(tmp_path / f'clip-{i}.mp4', (320, 240), is_video=True)
                  for i in range(count)]
        for image in images:
            image.path.touch()
        source.beginResetModel()
        source._paginated_mode = paginated
        source.images = images
        source._pages = {0: images} if paginated else {}
        source._total_count = count
        source.endResetModel()
        for row, image in enumerate(images):
            payload = host._create_floating_viewer_payload(proxy.index(row, 0))
            window, viewer = payload['window'], payload['viewer']
            windows.append(window)
            # Media installation is the only boundary bypassed: no generated
            # file is decoded. Use the real viewer/player and all badge signals.
            viewer._selection_masonry_wall_viewer = True
            viewer.load_image(proxy.index(row, 0), False)
            viewer._ensure_video_components()
            viewer._is_video_loaded = True
            viewer.video_player.video_path = image.path
            viewer.video_player.is_playing = playing
            players.append(viewer.video_player)
            window.resize(480, 360)
            window.set_review_slots_enabled(True)
            window.show()
        APP.processEvents()
        # Opening a wall assigns its initial focused tile as the explicit
        # action target. Overlay clicks must be sufficient to change that.
        host._activate_floating_action_target(windows[0].viewer)
        return host, images, windows

    yield create
    # Complete pending browser reset/layout work while the view is alive.
    QTest.qWait(180)
    for window in windows:
        for task in window.viewer.findChildren(LatestTask):
            task.drain()
        window.viewer.close()
        dispose_widget(window)
    for player in players:
        player.cleanup(force_gc=False)
        for owner in (player.media_player, player.position_timer):
            owner.deleteLater()
            QCoreApplication.sendPostedEvents(owner, QEvent.DeferredDelete)
        dispose_widget(player._mpv_parking_widget)
        dispose_widget(player)
    for task in host.findChildren(LatestTask):
        task.drain()
    source.shutdown_background_workers()
    executor = host.image_list.list_view._masonry_executor
    if executor is not None:
        executor.shutdown(wait=True, cancel_futures=True)
    dispose_widget(host)
    APP.processEvents()
    assert not any(isValid(window) for window in windows)
    assert source is proxy.sourceModel()
    assert not errors, [''.join(traceback.format_exception(*error)) for error in errors]


def click_badge(window, badge_id):
    overlay = window._review_slots_overlay
    overlay.set_hover_active(True)
    spec_index = next(i for i, spec in enumerate(overlay._slot_items())
                      if spec.badge_id == badge_id)
    QTest.mouseClick(overlay, Qt.MouseButton.LeftButton,
                     pos=overlay._slot_rect(spec_index).center())
    APP.processEvents()


@pytest.mark.parametrize('count', [2, 3])
@pytest.mark.parametrize('playing', [False, True])
@pytest.mark.parametrize('paginated', [False, True])
@pytest.mark.parametrize('badge_id, rank, flag', [
    ('flag_warning', 0, ReviewFlag.WARNING),
    ('flag_reject', 0, ReviewFlag.REJECT),
    ('rank_2', 2, 0),
])
def test_badge_click_targets_its_tile_and_updates_live_state(
        wall_factory, count, playing, paginated, badge_id, rank, flag):
    host, images, windows = wall_factory(count, playing, paginated)
    # No video-surface click/hover is needed before clicking a different tile.
    target = windows[-1]
    click_badge(target, badge_id)
    assert [(image.review_rank, image.review_flags) for image in images] == (
        [(0, 0)] * (count - 1) + [(rank, int(flag))])
    assert all((image.review_rank, image.review_flags) == (0, 0)
               for image in images[:-1]), 'A sibling received the review change'
    assert target._review_slots_overlay._current_review_state() == (rank, int(flag))
    assert host._get_explicit_action_target_viewer() is target.viewer
    assert all(window.viewer.video_player.is_playing is playing for window in windows)
    saved = json.loads(taggui_sidecar_path(images[-1].path).read_text(encoding='utf-8'))
    assert saved['review_rank'] == rank
    assert saved['review_flags'] == serialize_review_flags(flag)
    db_state = host.image_list_model._db.get_review_states_for_paths([images[-1].path.name])
    assert db_state[images[-1].path.name]['review_rank'] == rank
    assert db_state[images[-1].path.name]['review_flags'] == int(flag)
    assert host.image_list_model.undo_stack[-1].image_snapshots[0]['image'] is images[-1]
    # Leaving hover must retain the clicked badge over the live tile.
    target._review_slots_overlay.set_hover_active(False)
    assert [spec.badge_id for _, spec in target._review_slots_overlay._display_items()] == [badge_id]

    # Returning to the first tile must transfer ownership again; toggling the
    # last tile off must then leave the first tile's state intact.
    click_badge(windows[0], badge_id)
    click_badge(target, badge_id)
    assert (images[-1].review_rank, images[-1].review_flags) == (0, 0)
    assert (images[0].review_rank, images[0].review_flags) == (rank, int(flag))
    assert target._review_slots_overlay._current_review_state() == (0, 0)
    saved = json.loads(taggui_sidecar_path(images[-1].path).read_text(encoding='utf-8'))
    assert saved['review_rank'] == 0 and saved['review_flags'] == []
    assert all(window.viewer.video_player.is_playing is playing for window in windows)


@pytest.mark.parametrize('playing', [False, True])
@pytest.mark.parametrize('kind', ['rank', 'flag'])
def test_review_toggle_reads_the_same_owner_that_it_writes(wall_factory, playing, kind):
    host, images, windows = wall_factory(2, playing, True)
    if kind == 'rank':
        images[0].review_rank = 2
    else:
        images[0].review_flags = int(ReviewFlag.WARNING)
    # Passive activation can differ from the remembered explicit target.
    # A shortcut toggle must read that target, not a sibling's empty state.
    host.set_active_viewer(windows[-1].viewer)
    assert host.get_active_viewer() is windows[-1].viewer
    assert host._get_explicit_action_target_viewer() is windows[0].viewer
    if kind == 'rank':
        assert host._toggle_current_review_rank(2)
    else:
        assert host._toggle_current_review_flag('warning')
    # Complete the queued sidecar write while the UI consumers are alive.
    APP.processEvents()
    assert [(image.review_rank, image.review_flags) for image in images] == [(0, 0), (0, 0)]
    assert all(window.viewer.video_player.is_playing is playing for window in windows)


@pytest.mark.parametrize('playing', [False, True])
def test_four_video_wall_keeps_badges_after_background_refresh(wall_factory, playing):
    host, images, windows = wall_factory(4, playing, True)
    images[0].review_flags = int(ReviewFlag.REJECT)
    source = host.image_list_model
    for image in images:
        source.save_review_state_to_db(image)
    existing = windows[0]._review_slots_overlay
    existing.set_hover_active(False)
    assert existing._current_review_state() == (0, int(ReviewFlag.REJECT))
    ready = []
    source.ordered_view_ready.connect(ready.append)
    source._start_paginated_enrichment = lambda **kwargs: None
    source._request_page_load = lambda page: None
    source.prepare_ordered_view(reason='refresh')
    pump(lambda: bool(ready))
    # The backend still owns the same playing clip; refresh must not detach
    # badge ownership just because Qt has invalidated the browser indices.
    assert all(window.viewer.video_player.is_playing is playing for window in windows)
    assert existing._current_review_state() == (0, int(ReviewFlag.REJECT))
    assert windows[0].viewer.current_media is not images[0]
    assert windows[0].viewer.current_media is source.data(
        source.index(source.get_loaded_row_for_path(images[0].path), 0), Qt.UserRole)
    target = windows[-1]
    click_badge(target, 'flag_warning')
    assert target._review_slots_overlay._current_review_state() == (0, int(ReviewFlag.WARNING))
    target._review_slots_overlay.set_hover_active(False)
    QTest.qWait(180)
    assert target._review_slots_overlay.isVisible()
    assert [spec.badge_id for _, spec in target._review_slots_overlay._display_items()] == ['flag_warning']
    assert all(window.viewer.video_player.is_playing is playing for window in windows)


@pytest.mark.parametrize('resident', [False, True])
def test_wall_reset_retains_path_owner_without_loading_evicted_pages(wall_factory, resident, monkeypatch):
    host, images, windows = wall_factory(4, True, True)
    source = host.image_list_model
    requests = []
    monkeypatch.setattr(source, '_request_page_load', lambda *args: requests.append(
        {frame.name for frame in traceback.extract_stack()}))
    windows[0].viewer.current_media.review_flags = int(ReviewFlag.REJECT)
    replacement = [replace(image) for image in reversed(images)] if resident else []
    source.beginResetModel()
    # Mutation callbacks must remain barred during Qt's reset window.
    assert host._current_viewer_image(windows[0].viewer) is None
    source._pages = {0: replacement} if resident else {}
    source.endResetModel()
    target = windows[-1]
    assert target.viewer.proxy_image_index.isValid() is resident
    if resident:
        assert target.viewer.current_media is replacement[0]
    click_badge(target, 'flag_warning')
    assert target._review_slots_overlay._current_review_state() == (0, int(ReviewFlag.WARNING))
    assert windows[0]._review_slots_overlay._current_review_state() == (0, int(ReviewFlag.REJECT))
    assert all(window.viewer.video_player.is_playing for window in windows)
    assert not any(stack & {'_on_proxy_model_reset', '_retained_wall_video_media',
                           '_current_review_state'} for stack in requests)


def test_wall_reset_cannot_keep_a_previous_folder_as_action_owner(wall_factory):
    host, images, windows = wall_factory(4, True, True)
    source = host.image_list_model
    source._directory_path = source._directory_path / 'another-folder'
    source.beginResetModel()
    source._pages = {}
    source.endResetModel()
    for window in windows:
        assert window.viewer.current_media is None
        assert host._current_viewer_image(window.viewer) is None
    click_badge(windows[-1], 'flag_warning')
    assert all(image.review_flags == 0 for image in images)
