"""Precise extraction must apply a drawn crop in a single encode.

Run through tests/run_isolated.py to isolate settings and cache roots.
"""
import json
import subprocess
from threading import Event
from types import SimpleNamespace

import cv2
import pytest
from PySide6.QtCore import QEvent, QPointF, QRect, QTimer, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QCheckBox, QMessageBox

from qt_test_helpers import APP, pump
from test_extract_playback import NATIVE, opened_video
from test_video_marking_overlay import assert_crop_pixels, wait_for_visible_frame
from controllers import video_editing_controller as editing
from utils.image import ImageMarking, Marking
from utils.sidecar import taggui_sidecar_path
from utils.video.frame_editor import FrameEditor
from utils.video.video_editor import VideoEditor


@pytest.fixture
def patterned_video(tmp_path):
    path = tmp_path / 'pattern.mp4'
    subprocess.run([
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
        'color=c=red:s=320x240:r=24:d=3,'
        'drawbox=x=160:y=0:w=160:h=240:color=blue:t=fill,'
        "drawbox=x=160:y=0:w=160:h=240:color=lime:t=fill:enable='gte(t,1.5)'",
        '-f', 'lavfi', '-i', 'sine=frequency=440:duration=3',
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
        '-y', str(path),
    ], capture_output=True, check=True, timeout=20)
    return path


def decoded_frames(path):
    capture = cv2.VideoCapture(str(path))
    frames = []
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            frames.append(frame)
    finally:
        capture.release()
    return frames


@pytest.mark.parametrize('adjust_timing', [False, True])
def test_crop_encodes_once_with_audio_and_timing(patterned_video, monkeypatch, adjust_timing):
    output = patterned_video.with_name('cropped.mp4')
    calls = []
    run = subprocess.run

    def record(command, *args, **kwargs):
        if command[0] == 'ffmpeg':
            calls.append(command)
        return run(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, 'run', record)
    success, message = VideoEditor.extract_range(
        patterned_video, output, 24, 71, 24, crop_rect=(161, 21, 100, 80),
        reverse=adjust_timing, speed_factor=2.0 if adjust_timing else 1.0,
        target_fps=12 if adjust_timing else None,
    )
    assert success, message
    assert len(calls) == 1
    assert '-c:v' in calls[0] and calls[0][calls[0].index('-c:v') + 1] == 'libx264'
    frames = decoded_frames(output)
    assert len(frames) == (12 if adjust_timing else 48)
    assert frames[0].shape[:2] == (80, 100)
    first_channel, last_channel = (1, 0) if adjust_timing else (0, 1)
    assert frames[0].mean(axis=(0, 1))[first_channel] > 200
    assert frames[-1].mean(axis=(0, 1))[last_channel] > 200
    assert all(frame[:, :, 2].mean() < 20 for frame in frames), 'Crop included the red left half'
    audio, _, video_stream, error = FrameEditor._probe_streams(output)
    assert audio and not error
    assert video_stream['avg_frame_rate'] == ('12/1' if adjust_timing else '24/1')
    assert patterned_video.exists() and not patterned_video.with_suffix('.mp4.backup').exists()


@pytest.mark.parametrize('crop', [(300, 0, 100, 80), (-1, 0, 100, 80), (0, 0, 101, 80)])
def test_invalid_crop_preserves_in_place_source(patterned_video, crop):
    original = patterned_video.read_bytes()
    success, message = FrameEditor.extract_range(
        patterned_video, patterned_video, 24, 71, 24, crop_rect=crop,
    )
    assert not success and 'Crop must' in message
    assert patterned_video.read_bytes() == original
    assert not patterned_video.with_suffix('.mp4.backup').exists()


def test_crop_copy_preserves_foreign_sidecars_and_source_metadata(tmp_path):
    source, output = tmp_path / 'source.mp4', tmp_path / 'output.mp4'
    metadata = {
        'version': 1, 'crop': [21, 31, 160, 100], 'loop_start_frame': 24,
        'loop_end_frame': 71, 'rating': 3, 'caption_workspace': {'version': 1, 'entries': []},
        'markings': [
            {'label': 'partial', 'type': 'HINT', 'rect': [11, 41, 30, 20], 'confidence': 0.8},
            {'label': 'outside', 'type': 'EXCLUDE', 'rect': [240, 150, 10, 10]},
        ],
    }
    taggui_sidecar_path(source).write_text(json.dumps(metadata), encoding='UTF-8')
    foreign = '{"version":1,"nodes":[],"state":{"lastNodeId":0}}'
    source.with_suffix('.json').write_text(foreign, encoding='UTF-8')
    source.with_suffix('.txt').write_text('source caption', encoding='UTF-8')
    controller = editing.VideoEditingController(SimpleNamespace())
    controller._copy_extract_sidecars(source, output, crop_rect=(21, 31, 160, 100))
    saved = json.loads(taggui_sidecar_path(output).read_text())
    assert 'crop' not in saved
    assert saved['markings'] == [{**metadata['markings'][0], 'rect': [0, 10, 20, 20]}]
    assert saved['caption_workspace'] == metadata['caption_workspace'] and saved['rating'] == 3
    assert saved['loop_start_frame'] is None and saved['loop_end_frame'] is None
    assert output.with_suffix('.txt').read_text() == 'source caption'
    assert output.with_suffix('.json').read_text() == foreign
    assert json.loads(taggui_sidecar_path(source).read_text()) == metadata


@pytest.mark.parametrize('apply_crop', [False, True])
def test_extraction_dialog_snapshots_crop_and_keeps_source(opened_video, monkeypatch, apply_crop):
    host, path, errors = opened_video
    viewer, controller = host.image_viewer, host.video_editing_controller
    image, controls = viewer.current_media, viewer.video_controls
    controls.apply_loop_state(24, 71, False, save=True, emit_signals=True)
    image.crop = QRect(21, 31, 161, 101)
    host.image_list_model.write_meta_to_disk(image)
    host.toggle_viewer_play_pause(viewer)
    original = path.read_bytes()
    started, release = Event(), Event()
    editor = editing._video_editor_class()
    extract = editor.extract_range
    calls, messages, ready = [], [], []

    def delayed(*args, **kwargs):
        calls.append(kwargs)
        started.set()
        assert release.wait(10)
        return extract(*args, **kwargs)

    def accept_dialog():
        dialog = APP.activeModalWidget()
        checkbox = next(box for box in dialog.findChildren(QCheckBox)
                        if box.text().startswith('Apply current crop'))
        assert checkbox.isEnabled() and checkbox.isChecked()
        assert '160 × 100' in checkbox.text()
        checkbox.setChecked(apply_crop)
        dialog.accept()

    monkeypatch.setattr(editor, 'extract_range', delayed)
    for name in ('information', 'warning', 'critical'):
        monkeypatch.setattr(QMessageBox, name, lambda *args: messages.append(args[1:]))
    host.image_list_model.ordered_view_ready.connect(ready.append)
    QTimer.singleShot(0, host, accept_dialog)
    try:
        controller.extract_video_range()
        assert started.wait(3)
        # While extracting, the user draws the crop and markers for the next clip.
        image.crop = QRect(40, 50, 120, 80)
        controls.apply_loop_state(150, 222, False, save=True, emit_signals=True)
        host.image_list_model.write_meta_to_disk(image)
        release.set()
        pump(lambda: not controller._video_operation_active and bool(ready), seconds=25)
        QTest.qWait(500)
        output = path.with_name('source_extract_24-71.mp4')
        frames = decoded_frames(output)
        assert len(frames) == 48
        assert frames[0].shape[:2] == ((100, 160) if apply_crop else (240, 320))
        assert calls[0]['crop_rect'] == ((21, 31, 160, 100) if apply_crop else None)
        metadata = json.loads(taggui_sidecar_path(output).read_text())
        assert ('crop' not in metadata) if apply_crop else metadata['crop'] == [40, 50, 120, 80]
        assert path.read_bytes() == original
        assert viewer.current_media.path == path and viewer.video_player.video_path == path
        assert viewer.current_media.crop == QRect(40, 50, 120, 80)
        assert viewer.video_player.is_playing and controls.get_loop_range() == (150, 222)
        assert not messages and not errors
    finally:
        release.set()


@pytest.mark.parametrize('delete_during_extraction', [False, True])
def test_deleted_crop_stays_deleted_after_extraction(opened_video, monkeypatch, delete_during_extraction):
    host, path, errors = opened_video
    viewer, model = host.image_viewer, host.image_list_model
    controls, controller = viewer.video_controls, host.video_editing_controller
    controls.apply_loop_state(24, 71, False, save=True, emit_signals=True)
    host.toggle_viewer_play_pause(viewer)
    view, viewport = viewer.view, viewer.view.viewport()
    if NATIVE:
        host.move(host.screen().availableGeometry().topLeft())
        pump(lambda: viewer.video_player._mpv_surface_active, seconds=15)
        wait_for_visible_frame(viewer)

    viewer.add_marking(ImageMarking.CROP)
    start, end = view.mapFromScene(40, 40), view.mapFromScene(240, 180)
    QTest.mousePress(viewport, Qt.LeftButton, pos=start)
    APP.sendEvent(viewport, QMouseEvent(
        QEvent.MouseMove, QPointF(end), QPointF(viewport.mapToGlobal(end)),
        Qt.NoButton, Qt.LeftButton, Qt.NoModifier,
    ))
    QTest.mouseRelease(viewport, Qt.LeftButton, pos=end)
    pump(lambda: viewer.current_media.crop is not None)
    QTest.qWait(250)  # Deliver scene.changed and present the native foreground.
    crop = QRect(viewer.current_media.crop)
    sidecar = taggui_sidecar_path(path)
    saved = json.loads(sidecar.read_text())
    saved['caption_workspace'] = {'version': 1, 'entries': []}
    saved['custom_metadata'] = {'keep': True}
    sidecar.write_text(json.dumps(saved), encoding='UTF-8')
    foreign = '{"version":1,"nodes":[],"state":{"lastNodeId":0}}'
    path.with_suffix('.json').write_text(foreign, encoding='UTF-8')
    if NATIVE:
        assert_crop_pixels(viewer, path.parent / 'crop-before-delete.png')

    def assert_deleted():
        assert viewer.current_media.crop is None and viewer.crop_marking is None
        assert not any(getattr(item, 'rect_type', None) == ImageMarking.CROP
                       for item in viewer.scene.items())
        metadata = json.loads(sidecar.read_text())
        assert 'crop' not in metadata, 'Deleted crop remained in the saved sidecar'
        assert metadata['caption_workspace'] == saved['caption_workspace']
        assert metadata['custom_metadata'] == saved['custom_metadata']
        assert path.with_suffix('.json').read_text() == foreign
        if NATIVE:
            pixels = wait_for_visible_frame(viewer)
            bounds = view.mapFromScene(crop).boundingRect().adjusted(-5, -5, 5, 5)
            bounds = bounds.intersected(pixels.rect())
            assert not any(pixels.pixelColor(x, y).blue() > 200
                           and pixels.pixelColor(x, y).red() < 60
                           and pixels.pixelColor(x, y).green() < 60
                           for y in range(bounds.top(), bounds.bottom() + 1)
                           for x in range(bounds.left(), bounds.right() + 1))

    def delete_crop():
        viewer.scene.clearSelection()
        viewer.crop_marking.setSelected(True)
        QTest.keyClick(view, Qt.Key_Delete)
        QTest.qWait(50)
        assert_deleted()

    if not delete_during_extraction:
        delete_crop()
        model.undo()
        APP.processEvents()
        assert viewer.current_media.crop == crop
        assert json.loads(sidecar.read_text())['crop'] == list(crop.getRect())
        model.redo()
        APP.processEvents()
        assert_deleted()

    started, release = Event(), Event()
    editor = editing._video_editor_class()
    extract = editor.extract_range
    calls, ready, messages = [], [], []

    def delayed(*args, **kwargs):
        calls.append(kwargs)
        started.set()
        assert release.wait(10)
        return extract(*args, **kwargs)

    def accept_dialog():
        dialog = APP.activeModalWidget()
        checkbox = next(box for box in dialog.findChildren(QCheckBox)
                        if box.text().startswith('Apply current crop'))
        assert checkbox.isEnabled() is delete_during_extraction
        assert checkbox.isChecked() is delete_during_extraction
        dialog.accept()

    monkeypatch.setattr(editor, 'extract_range', delayed)
    for name in ('information', 'warning', 'critical'):
        monkeypatch.setattr(QMessageBox, name, lambda *args: messages.append(args[1:]))
    model.ordered_view_ready.connect(ready.append)
    QTimer.singleShot(0, host, accept_dialog)
    try:
        controller.extract_video_range()
        assert started.wait(3)
        if delete_during_extraction:
            delete_crop()
        release.set()
        pump(lambda: not controller._video_operation_active and bool(ready), seconds=25)
        QTest.qWait(500)
        assert_deleted()
        output = path.with_name('source_extract_24-71.mp4')
        assert 'crop' not in json.loads(taggui_sidecar_path(output).read_text())
        frames = decoded_frames(output)
        assert len(frames) == 48
        assert frames[0].shape[:2] == (
            (crop.height() // 2 * 2, crop.width() // 2 * 2)
            if delete_during_extraction else (240, 320))
        assert (calls[0]['crop_rect'] is not None) is delete_during_extraction
        assert viewer.video_player.video_path == path and viewer.video_player.is_playing
        def select(media_path):
            index = model.index(model.get_index_for_path(media_path), 0)
            host.image_list.list_view.setCurrentIndex(host.proxy_image_list_model.mapFromSource(index))
            pump(lambda: viewer.current_media is not None and viewer.current_media.path == media_path
                 and viewer.video_player.video_path == media_path, seconds=15)
            QTest.qWait(400)

        select(output)
        assert viewer.current_media.crop is None and viewer.crop_marking is None
        select(path)
        assert_deleted()
        assert not messages and not errors
    finally:
        release.set()


def test_in_place_extraction_consumes_crop_and_preserves_backup(opened_video, monkeypatch):
    host, path, errors = opened_video
    controller, viewer = host.video_editing_controller, host.image_viewer
    image = viewer.current_media
    viewer.video_controls.apply_loop_state(24, 71, False, save=True, emit_signals=True)
    image.crop = QRect(21, 31, 160, 100)
    image.markings = [Marking('inside', ImageMarking.HINT, QRect(31, 41, 20, 20))]
    host.image_list_model.write_meta_to_disk(image)
    original = path.read_bytes()
    original_meta = taggui_sidecar_path(path).read_bytes()
    messages = []
    for name in ('information', 'warning', 'critical'):
        monkeypatch.setattr(QMessageBox, name, lambda *args: messages.append(args[1:]))

    def accept_dialog():
        dialog = APP.activeModalWidget()
        next(box for box in dialog.findChildren(QCheckBox)
             if box.text().startswith('Extract as copy')).setChecked(False)
        dialog.accept()

    QTimer.singleShot(0, host, accept_dialog)
    controller.extract_video_range()
    pump(lambda: not controller._video_operation_active and viewer._is_video_loaded
         and viewer.current_media is not None and viewer.current_media.dimensions == (160, 100),
         seconds=25)
    QTest.qWait(500)
    metadata = json.loads(taggui_sidecar_path(path).read_text())
    assert 'crop' not in metadata and viewer.current_media.crop is None
    assert metadata['markings'][0]['rect'] == [10, 10, 20, 20]
    assert metadata['loop_start_frame'] is None and metadata['loop_end_frame'] is None
    assert path.with_suffix('.mp4.backup').read_bytes() == original
    assert taggui_sidecar_path(path).with_suffix('.json.backup').read_bytes() == original_meta
    frames = decoded_frames(path)
    assert len(frames) == 48 and frames[0].shape[:2] == (100, 160)
    assert messages and all(message[0] == 'Success' for message in messages)
    assert not errors
