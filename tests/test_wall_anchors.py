"""Anchored packing and real viewer input boundaries."""
import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from qt_test_helpers import APP, pump
from test_floating_wall_reflow import opened_wall, finish_reflow
from widgets.floating_wall_packing import pack_wall, valid_layout


def test_obstacles_preserve_exact_positions_and_sizes():
    bounds = QRect(-800, 30, 800, 600)
    anchors = [QRect(-620, 150, 210, 150), None, QRect(-220, 40, 180, 120), None]
    result = pack_wall([1.4, 1, 1.5, 2], bounds, anchored_rects=anchors,
                       preferred_sizes=[(210,150),(250,250),(180,120),(300,150)])
    assert len(result.rects) == 4
    assert valid_layout(result.rects, bounds, 6)
    assert result.rects[0] == anchors[0] and result.rects[2] == anchors[2]
    assert abs(result.rects[1].width()-result.rects[1].height()) <= 1


def test_overlapping_anchors_fail_without_moving_them():
    result = pack_wall([1,1], QRect(0,0,500,500), anchored_rects=[QRect(0,0,200,200),QRect(150,0,200,200)])
    assert not result.rects


def press(window):
    target = window.viewer.view.viewport()
    point = target.rect().center()
    QTest.mousePress(target, Qt.LeftButton, Qt.ControlModifier, point)
    return target, point


def settle(anchor):
    pump(lambda: anchor.drag is not None and anchor.drag['result'] is not None, seconds=10)


def test_ctrl_drag_previews_then_commits_and_keeps_anchors(opened_wall):
    host, windows = opened_wall
    wall, anchor = host._wall_layout, host._wall_layout.anchors
    for w in windows:
        w.resize(max(w.minimumWidth(), 130), max(w.minimumHeight(), 130))
    before = [QRect(w.geometry()) for w in windows]
    target, point = press(windows[0])
    assert anchor.drag is not None
    QTest.mouseMove(target, point + QPoint(25,25))
    settle(anchor)
    assert [w.geometry() for w in windows[1:]] == before[1:]
    assert anchor.overlay.isVisible()
    assert anchor.drag['result'] is not False
    QTest.mouseRelease(target, Qt.LeftButton, Qt.ControlModifier, target.rect().center())
    pump(lambda: anchor.drag is None, seconds=10)
    assert windows[0]._wall_position_anchored
    assert not anchor.overlay.isVisible()
    fixed = QRect(windows[0].geometry())
    wall.request_reflow(windows[1], force=True)
    finish_reflow(wall)
    assert windows[0].geometry() == fixed
    assert valid_layout([w.geometry() for w in windows], anchor.overlay.geometry(), 6)
    anchor.set_anchor(windows[1], True)
    assert windows[0]._wall_position_anchored and windows[1]._wall_position_anchored
    anchor.clear()
    assert all(not w._wall_position_anchored for w in windows)


def test_escape_restores_and_alt_does_not_start_anchor_drag(opened_wall):
    host, windows = opened_wall
    anchor = host._wall_layout.anchors
    before = QRect(windows[0].geometry())
    target, point = press(windows[0])
    QTest.mouseMove(target, point+QPoint(30,20))
    QTest.keyClick(target, Qt.Key_Escape)
    assert anchor.drag is None and windows[0].geometry() == before
    QTest.mouseRelease(target, Qt.LeftButton, Qt.ControlModifier, point)
    QTest.mousePress(target, Qt.LeftButton, Qt.ControlModifier | Qt.AltModifier, point)
    assert anchor.drag is None
    QTest.mouseRelease(target, Qt.LeftButton, Qt.ControlModifier | Qt.AltModifier, point)


def test_invalid_drop_rolls_back_without_new_anchor(opened_wall):
    host, windows = opened_wall
    anchor = host._wall_layout.anchors
    anchor.set_anchor(windows[1], True)
    before = QRect(windows[0].geometry())
    target, point = press(windows[0])
    anchor.update(windows[1].pos()+anchor.drag['offset'], Qt.ShiftModifier)
    settle(anchor)
    assert anchor.drag['result'] is False
    anchor.finish()
    assert anchor.drag is None
    assert windows[0].geometry() == before
    assert not getattr(windows[0], '_wall_position_anchored', False)
    assert windows[1]._wall_position_anchored


def test_snap_hysteresis_shift_and_cancel_on_sibling_change(opened_wall):
    host, windows = opened_wall
    anchor = host._wall_layout.anchors
    anchor.set_anchor(windows[1], True)
    target, point = press(windows[0])
    d = anchor.drag
    left = d['bounds'].left()
    y = d['original'].y()
    def move(x, modifiers=Qt.NoModifier):
        anchor.update(QPoint(x,y)+d['offset'], modifiers)
    move(left+8)
    assert windows[0].x() == left
    move(left+15)
    assert windows[0].x() == left
    move(left+20)
    assert windows[0].x() == left+20
    move(left+5, Qt.ShiftModifier)
    assert windows[0].x() == left+5
    windows[1].move(windows[1].pos()+QPoint(1,0))
    assert anchor.drag is None
    assert windows[0].geometry() == d['original']
    QTest.mouseRelease(target, Qt.LeftButton, Qt.ControlModifier, point)


def test_second_ctrl_drag_keeps_first_anchor_and_preview_pixels(opened_wall):
    from qt_test_helpers import assert_capture_contains_color
    host, windows = opened_wall
    anchor = host._wall_layout.anchors
    for window in windows:
        window.resize(max(100,window.minimumWidth()), max(100,window.minimumHeight()))
    anchor.set_anchor(windows[0], True)
    fixed = QRect(windows[0].geometry())
    target, point = press(windows[1])
    settle(anchor)
    assert anchor.drag['result'] is not False
    APP.processEvents()
    border = fixed.translated(-anchor.overlay.geometry().topLeft())
    capture = anchor.overlay.grab().toImage()
    stripe = capture.copy(QRect(border.x()+10, border.y()+1, 50, 3))
    assert_capture_contains_color(stripe, (165,43,58))
    assert windows[0].geometry() == fixed
    QTest.mouseRelease(target, Qt.LeftButton, Qt.ControlModifier, point)
    pump(lambda: anchor.drag is None, seconds=10)
    assert windows[1]._wall_position_anchored
    assert windows[0].geometry() == fixed
    assert windows[0]._wall_anchor_indicator.isVisible()
    assert windows[1]._wall_anchor_indicator.isVisible()


def test_release_pending_then_escape_cannot_apply_late_result(opened_wall, monkeypatch):
    import threading
    from controllers import wall_anchor_controller as module
    host, windows = opened_wall
    anchors = host._wall_layout.anchors
    entered, release = threading.Event(), threading.Event()
    original = module.calculate
    def held(payload, cancelled):
        entered.set()
        assert release.wait(10)
        return original(payload, cancelled)
    monkeypatch.setattr(module, 'calculate', held)
    before = [QRect(w.geometry()) for w in windows]
    target, point = press(windows[0])
    try:
        QTest.mouseMove(target, point+QPoint(10,10))
        QTest.mouseRelease(target, Qt.LeftButton, Qt.ControlModifier, target.rect().center())
        pump(entered.is_set)
        assert anchors.drag is not None and anchors.drag['released']
        assert [w.geometry() for w in windows[1:]] == before[1:]
        QTest.keyClick(target, Qt.Key_Escape)
        assert anchors.drag is None
    finally:
        release.set()
        anchors.worker.drain()
    APP.processEvents()
    assert [w.geometry() for w in windows] == before
    assert not getattr(windows[0], '_wall_position_anchored', False)


def test_resize_packing_grows_free_windows_but_drag_preview_keeps_sizes():
    bounds = QRect(0, 0, 1000, 700)
    previous = [QRect(0,0,100,100), QRect(106,0,100,100), QRect(212,0,100,100)]
    options = dict(anchored_rects=[previous[0], None, None],
                   preferred_sizes=[(100,100)]*3, previous_rects=previous)
    preview = pack_wall([1]*3, bounds, anchor_preview=True, **options)
    reflow = pack_wall([1]*3, bounds, **options)
    assert [r.size() for r in preview.rects] == [r.size() for r in previous]
    assert reflow.rects[0] == previous[0]
    assert all(r.width() > 200 for r in reflow.rects[1:])
    assert valid_layout(reflow.rects, bounds, 6)
    fixed = pack_wall([1]*3, bounds, automatic_sizing=False, **options)
    assert [r.size() for r in fixed.rects] == [r.size() for r in previous]


def test_real_resize_after_ctrl_anchor_fills_space_and_preserves_constraints(opened_wall):
    from test_floating_wall_reflow import resize_gesture
    host, windows = opened_wall
    wall = host._wall_layout
    for window in windows:
        window.resize(max(130, window.minimumWidth()), max(130, window.minimumHeight()))
    target, point = press(windows[0])
    QTest.mouseRelease(target, Qt.LeftButton, Qt.ControlModifier, point)
    pump(lambda: wall.anchors.drag is None, seconds=10)
    assert windows[0]._wall_position_anchored
    before = [QRect(w.geometry()) for w in windows]
    resize_gesture(windows[0], QPoint(-20, -20))
    chosen = QRect(windows[0].geometry())
    finish_reflow(wall)
    assert windows[0].geometry() == chosen
    assert sum(w.width()*w.height() for w in windows[1:]) > sum(r.width()*r.height() for r in before[1:])
    previous_result = wall.last_result
    resize_gesture(windows[1], QPoint(-30,-30))
    second_size = windows[1].size()
    finish_reflow(wall)
    assert wall.last_result is not previous_result
    assert windows[0].geometry() == chosen
    assert windows[1].size() == second_size
    assert valid_layout([w.geometry() for w in windows], windows[0].screen().availableGeometry(), 6)



def test_resize_ghost_predicts_release_and_alt_hides_preview(opened_wall):
    host, windows = opened_wall
    wall = host._wall_layout
    target = windows[0].viewer.view.viewport()
    point = target.rect().bottomRight()-QPoint(2,2)
    siblings = [QRect(w.geometry()) for w in windows[1:]]
    QTest.mousePress(target, Qt.LeftButton, Qt.NoModifier, point)
    QTest.mouseMove(target, point-QPoint(35,25))
    pump(lambda: wall.resize_preview.overlay.isVisible(), seconds=10)
    preview = [QRect(r) for r in wall.resize_preview.overlay.rects]
    assert wall.resize_preview.overlay.focus_rect is not None
    assert [w.geometry() for w in windows[1:]] == siblings
    QTest.mouseRelease(target, Qt.LeftButton, Qt.NoModifier, target.rect().bottomRight()-QPoint(2,2))
    finish_reflow(wall)
    assert not wall.resize_preview.overlay.isVisible()
    def rect_set(rects):
        return {(r.x(),r.y(),r.width(),r.height()) for r in rects}
    assert rect_set([w.geometry() for w in windows]) == rect_set(preview)
    point = target.rect().bottomRight()-QPoint(2,2)
    QTest.mousePress(target, Qt.LeftButton, Qt.AltModifier, point)
    QTest.mouseMove(target, point-QPoint(20,20))
    QTest.qWait(150)
    assert not wall.resize_preview.overlay.isVisible()
    QTest.mouseRelease(target, Qt.LeftButton, Qt.AltModifier, point-QPoint(20,20))


def test_resize_border_wins_over_child_button_but_interior_still_clicks(opened_wall):
    from PySide6.QtWidgets import QPushButton
    host, windows = opened_wall
    window = windows[0]
    button = QPushButton('overlay', window)
    button.setGeometry(window.width()-70, window.height()-40, 70,40)
    button.show()
    button.raise_()
    clicks = []
    button.clicked.connect(lambda: clicks.append(True))
    QTest.mouseClick(button, Qt.LeftButton, Qt.NoModifier, QPoint(25,15))
    assert clicks == [True]
    QTest.mousePress(button, Qt.LeftButton, Qt.NoModifier, QPoint(67,37))
    assert window._resize_active
    QTest.mouseMove(button, QPoint(45,20))
    QTest.mouseRelease(button, Qt.LeftButton, Qt.NoModifier, QPoint(45,20))
    assert not window._resize_active
    assert clicks == [True]
    finish_reflow(host._wall_layout)


def test_constraint_icons_follow_effective_locks_and_can_be_hidden(opened_wall):
    from utils.settings import settings
    host, windows = opened_wall
    wall, window = host._wall_layout, windows[0]
    wall.anchors.set_anchor(window, True)
    wall.resize_finished(window, True)
    # Keep-size icon is hidden while pinned, so one mark represents the effective state.
    wall.anchors.set_anchor(window, False)
    wall.refresh_indicators(window)
    size = window._wall_size_indicator
    wall.anchors.set_anchor(window, True)
    pin = window._wall_anchor_indicator
    assert pin.isVisible() and not size.isVisible()
    assert pin.width() == size.width() == 18
    assert not pin.testAttribute(Qt.WA_TransparentForMouseEvents)
    assert not size.testAttribute(Qt.WA_TransparentForMouseEvents)
    settings.setValue('floating_wall_preserve_manual_sizes', False)
    assert pin.isVisible() and not size.isVisible()
    wall._keep_size(window, True)
    assert not size.isVisible()
    settings.setValue('floating_wall_constraint_icons', False)
    assert not pin.isVisible() and not size.isVisible()
    assert window._wall_position_anchored and wall._fixed_size(window) is not None
    settings.setValue('floating_wall_constraint_icons', True)
    assert pin.isVisible() and not size.isVisible()
    wall.anchors.set_anchor(window, False)
    assert not pin.isVisible() and size.isVisible() and size.x() == 14
    wall._keep_size(window, False)
    assert not size.isVisible()



@pytest.mark.parametrize('anchor', [QRect(-200,0,500,900), QRect(700,0,500,900),
                                   QRect(0,-200,1000,500), QRect(0,400,1000,500),
                                   QRect(-500,-500,200,200)])
@pytest.mark.parametrize('preview', [False, True])
def test_offscreen_anchor_only_blocks_its_visible_area(anchor, preview):
    bounds = QRect(0,0,1000,700)
    result = pack_wall([anchor.width()/anchor.height(), 1, 1], bounds,
                       anchored_rects=[anchor, None, None], anchor_preview=preview,
                       preferred_sizes=[(anchor.width(),anchor.height()),(120,120),(120,120)],
                       automatic_sizing=False)
    assert len(result.rects) == 3
    assert result.rects[0] == anchor
    assert valid_layout(result.rects[1:], bounds, 6)
    for rect in result.rects[1:]:
        assert not rect.adjusted(0,0,6,6).intersects(anchor.adjusted(0,0,6,6))


def test_anchor_covering_entire_screen_still_has_no_fit():
    result = pack_wall([1,1], QRect(0,0,500,500),
                       anchored_rects=[QRect(-50,-50,600,600),None],
                       preferred_sizes=[(600,600),(100,100)])
    assert not result.rects


def test_real_resize_past_screen_edge_reflows_around_anchor(opened_wall):
    from test_floating_wall_reflow import resize_gesture
    host, windows = opened_wall
    wall, anchor = host._wall_layout, windows[0]
    bounds = anchor.screen().availableGeometry().adjusted(6,6,-6,-6)
    anchor.setGeometry(bounds.center().x(), bounds.top(), 160,160)
    for i, window in enumerate(windows[1:]):
        window.setGeometry(bounds.left(), bounds.top()+i*170,160,160)
    wall.anchors.set_anchor(anchor, True)
    before = wall.last_result
    resize_gesture(anchor, QPoint(bounds.width(),bounds.height()))
    chosen = QRect(anchor.geometry())
    assert not bounds.contains(chosen)
    finish_reflow(wall)
    assert wall.last_result is not before
    assert anchor.geometry() == chosen
    assert valid_layout([w.geometry() for w in windows[1:]], bounds, 6)
    for window in windows[1:]:
        assert not window.geometry().adjusted(0,0,6,6).intersects(chosen.adjusted(0,0,6,6))



def test_constraint_clicks_release_only_their_owner_and_follow_bottom_corner(opened_wall):
    host, windows = opened_wall
    wall, first, sibling = host._wall_layout, windows[0], windows[1]
    for window in (first, sibling):
        wall.anchors.set_anchor(window, True)
        wall._keep_size(window, True)
    pin = first._wall_anchor_indicator
    first.resize(first.width()+10, first.height()+10)
    assert pin.y() == first.height()-32
    assert first._resize_zone_from_local_pos(pin.geometry().center()) is None
    first.raise_()
    first.activateWindow()
    QTest.mouseMove(pin, pin.rect().center())
    pump(lambda: pin._hovered, seconds=3)
    QTest.mouseClick(pin, Qt.LeftButton, Qt.NoModifier, pin.rect().center())
    assert not first._wall_position_anchored
    assert wall._fixed_size(first) is not None
    assert sibling._wall_position_anchored and wall._fixed_size(sibling) is not None
    size = first._wall_size_indicator
    assert not pin.isVisible() and size.isVisible() and size.x() == 14
    QTest.mouseClick(size, Qt.LeftButton, Qt.NoModifier, size.rect().center())
    assert wall._fixed_size(first) is None and not size.isVisible()
    assert sibling._wall_position_anchored and wall._fixed_size(sibling) is not None
    assert not first._resize_active



def test_floating_ctrl_does_not_create_hints_and_still_starts_anchor_drag(opened_wall):
    from utils.image import ImageMarking
    host, windows = opened_wall
    window = windows[0]
    viewer, view = window.viewer, window.viewer.view
    window.raise_()
    view.setFocus()
    before = list(viewer.current_media.markings)
    QTest.keyPress(view, Qt.Key_Control)
    assert not view.insertion_mode
    assert viewer.marking_to_add == ImageMarking.NONE
    assert view.horizontal_line is None
    target, point = press(window)
    assert host._wall_layout.anchors.drag is not None
    QTest.keyClick(target, Qt.Key_Escape)
    QTest.mouseRelease(target, Qt.LeftButton, Qt.ControlModifier, point)
    QTest.keyRelease(view, Qt.Key_Control)
    viewer.add_marking(ImageMarking.HINT)
    assert not view.insertion_mode
    viewer.add_rectangle(QRect(5,5,30,30), ImageMarking.HINT, interactive=True)
    assert viewer.current_media.markings == before
    assert not any(item.rect_type == ImageMarking.HINT for item in viewer.marking_items)
    # The main viewer still supports hint insertion; no media mutation needed.
    host.image_viewer.add_marking(ImageMarking.HINT)
    assert host.image_viewer.view.insertion_mode
    host.image_viewer.view.set_insertion_mode(ImageMarking.NONE)
