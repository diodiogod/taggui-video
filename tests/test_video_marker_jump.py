"""Marker button middle clicks seek without editing the range or play intent."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from qt_test_helpers import APP, dispose_widget
from test_extract_playback import opened_video
from utils.sidecar import taggui_sidecar_path
from widgets.video_controls import VideoControlsWidget


@pytest.fixture
def sibling_controls():
    controls = [VideoControlsWidget(), VideoControlsWidget()]
    for widget in controls:
        widget.set_video_info({'fps': 24, 'frame_count': 300, 'duration': 12.5})
        widget.resize(1100, 200)
        widget.show()
    APP.processEvents()
    yield controls
    for widget in controls:
        dispose_widget(widget)


@pytest.mark.parametrize('button, expected', [('loop_start_btn', 0), ('loop_end_btn', 96)])
def test_middle_click_uses_clicked_controls_and_does_not_set_markers(sibling_controls, button, expected):
    first, sibling = sibling_controls
    first.fixed_marker_size = 73
    first.apply_loop_state(0, 96, False, save=False, emit_signals=False)
    sibling.apply_loop_state(150, 222, False, save=False, emit_signals=False)
    first.frame_spinbox.setValue(240)
    jumps, sibling_jumps, edits = [], [], []
    first.frame_changed.connect(jumps.append)
    sibling.frame_changed.connect(sibling_jumps.append)
    first.loop_start_set.connect(lambda: edits.append('start'))
    first.loop_end_set.connect(lambda: edits.append('end'))
    QTest.mouseClick(getattr(first, button), Qt.MiddleButton)
    assert jumps == [expected] and not sibling_jumps and not edits
    assert first.get_loop_range() == (0, 96)
    assert sibling.get_loop_range() == (150, 222)
    assert not first.can_undo_loop_marker_move()
    # Left-click still sets a marker and respects the fixed range size.
    QTest.mouseClick(getattr(first, button), Qt.LeftButton)
    assert first.get_loop_range() == ((240, 299) if button == 'loop_start_btn' else (168, 240))


@pytest.mark.parametrize('button', ['loop_start_btn', 'loop_end_btn'])
def test_middle_click_without_a_marker_does_nothing(sibling_controls, button):
    first, _ = sibling_controls
    jumps = []
    first.frame_changed.connect(jumps.append)
    QTest.mouseClick(getattr(first, button), Qt.MiddleButton)
    assert not jumps and first.get_loop_range() is None


@pytest.mark.parametrize('playing', [False, True])
def test_real_viewer_marker_click_wins_over_hold_shortcut(opened_video, monkeypatch, playing):
    host, path, errors = opened_video
    viewer = host.image_viewer
    controls, player = viewer.video_controls, viewer.video_player
    controls.apply_loop_state(24, 96, False, save=True, emit_signals=True)
    metadata_before = taggui_sidecar_path(path).read_bytes()
    hold_toggles = []
    monkeypatch.setattr(host, 'toggle_floating_hold_mode', lambda: hold_toggles.append(True))
    if playing:
        assert host.toggle_viewer_play_pause(viewer)
    for button, frame in ((controls.loop_start_btn, 24), (controls.loop_end_btn, 96)):
        QTest.mouseClick(button, Qt.MiddleButton)
        assert player.current_frame == frame
        assert player.is_playing is playing
        assert controls.get_loop_range() == (24, 96)
        assert taggui_sidecar_path(path).read_bytes() == metadata_before
        assert not hold_toggles and not errors
    # The existing shortcut elsewhere in the viewer still works.
    QTest.mouseClick(viewer.view.viewport(), Qt.MiddleButton)
    assert hold_toggles == [True]
