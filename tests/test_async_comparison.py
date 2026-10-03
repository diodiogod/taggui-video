import threading

import pytest
from PySide6.QtCore import QSortFilterProxyModel, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPixmap, QStandardItem, QStandardItemModel

from qt_test_helpers import APP, pump, dispose_widget
from utils.image import Image
from widgets import image_viewer


@pytest.fixture
def comparison(tmp_path):
    source = QStandardItemModel()
    source._directory_path = tmp_path
    for i, color in enumerate(('red', 'green', 'blue', 'yellow')):
        path = tmp_path / f'{i}.png'
        pixels = QImage(96, 48, QImage.Format_ARGB32)
        pixels.fill(QColor(color))
        assert pixels.save(str(path))
        item = QStandardItem()
        item.setData(Image(path, (96, 48)), Qt.UserRole)
        source.appendRow(item)
    proxy = QSortFilterProxyModel()
    proxy.setSourceModel(source)
    viewer = image_viewer.ImageViewer(proxy)
    viewer.load_image(proxy.index(0, 0))
    pump(lambda: viewer.current_image_item is not None)
    try:
        yield viewer, proxy, source
    finally:
        viewer._compare_prepare_task.drain()
        viewer._image_decode_task.drain()
        dispose_widget(viewer)
        APP.processEvents()


def test_comparison_replaces_pending_pixels_and_yields_to_gui(comparison, monkeypatch):
    viewer, proxy, source = comparison
    started, release = threading.Event(), threading.Event()
    original = image_viewer.prepare_compare_images
    def blocked(request, cancelled):
        started.set()
        assert release.wait(3)
        return original(request, cancelled)
    monkeypatch.setattr(image_viewer, 'prepare_compare_images', blocked)
    try:
        assert viewer.enter_compare_mode(proxy.index(0, 0), proxy.index(1, 0))
        assert started.wait(1)
        ticks = []
        QTimer.singleShot(0, lambda: ticks.append(True))
        APP.processEvents()
        assert ticks and viewer._compare_overlay_count() == 0
        assert viewer.replace_compare_right(proxy.index(2, 0))
        assert viewer.add_compare_layer(proxy.index(3, 0))
        assert viewer.get_compare_image_count() == 3
        release.set()
        pump(lambda: viewer._compare_prepare_owner is None and viewer._compare_overlay_count() == 2)
        assert [index.row() for index in viewer._compare_overlay_indices] == [2, 3]
        assert viewer._compare_layers[0]['overlay_item'].pixmap().toImage().pixelColor(20, 20) == QColor('blue')
        assert viewer._compare_layers[1]['overlay_item'].pixmap().toImage().pixelColor(20, 20) == QColor('yellow')
        assert viewer.current_media is source.item(0).data(Qt.UserRole)
    finally:
        release.set()


@pytest.mark.parametrize('action', ['exit', 'selection', 'reset'])
def test_obsolete_comparison_never_installs_after_exit_or_model_change(comparison, monkeypatch, action):
    viewer, proxy, source = comparison
    started, release = threading.Event(), threading.Event()
    original = image_viewer.prepare_compare_images
    def blocked(request, cancelled):
        started.set()
        assert release.wait(3)
        return original(request, cancelled)
    monkeypatch.setattr(image_viewer, 'prepare_compare_images', blocked)
    try:
        assert viewer.enter_compare_mode(proxy.index(0, 0), proxy.index(1, 0))
        assert started.wait(1)
        if action == 'exit':
            viewer.exit_compare_mode()
        elif action == 'selection':
            viewer.load_image(proxy.index(2, 0))
        else:
            source.clear()
        release.set()
        pump(lambda: viewer._compare_prepare_task._active is None)
        assert not viewer._compare_layers
        if action == 'selection':
            pump(lambda: viewer.current_image_item is not None and viewer._image_decode_owner is None)
            assert viewer.current_media.path.name == '2.png'
    finally:
        release.set()


@pytest.mark.parametrize('mode', ['preserve', 'fill', 'stretch'])
def test_worker_comparison_fit_preserves_existing_rendering_contract(comparison, mode):
    from utils.image_decode import prepare_compare_images
    viewer, proxy, source = comparison
    pixels = QImage(9, 17, QImage.Format_ARGB32)
    pixels.fill(QColor(20, 100, 170, 130))
    path = source.item(1).data(Qt.UserRole).path
    assert pixels.save(str(path))
    viewer.set_compare_fit_mode(mode, persist=False)
    size = viewer.current_image_item.pixmap().size()
    expected, offset = viewer._prepare_compare_overlay_pixmap(size, QPixmap.fromImage(pixels))
    matte = viewer.view.palette().color(viewer.view.viewport().backgroundRole())
    matte.setAlpha(255)
    request = {'paths': (path,), 'cache': {}, 'size': size.toTuple(), 'mode': mode, 'matte': matte.rgba()}
    layers, cache = prepare_compare_images(request, threading.Event())
    actual, actual_offset = layers[0]
    assert actual.size() == expected.size()
    assert actual_offset == (offset.x(), offset.y())
    expected_pixels = expected.toImage()
    for x, y in ((0, 0), (10, 10), (actual.width()//2, actual.height()//2)):
        a, b = actual.pixelColor(x, y), expected_pixels.pixelColor(x, y)
        assert all(abs(left-right) <= 1 for left, right in zip(a.getRgb(), b.getRgb()))


def test_failed_comparison_replacement_preserves_accepted_overlay(comparison):
    viewer, proxy, source = comparison
    assert viewer.enter_compare_mode(proxy.index(0, 0), proxy.index(1, 0))
    pump(lambda: viewer._compare_prepare_owner is None)
    before = viewer._compare_layers[0]['overlay_item']
    source.item(2).data(Qt.UserRole).path.unlink()
    assert viewer.replace_compare_right(proxy.index(2, 0))
    pump(lambda: viewer._compare_prepare_owner is None)
    assert viewer._compare_overlay_indices[0].row() == 1
    assert viewer._compare_layers[0]['overlay_item'] is before
    assert viewer.get_compare_image_count() == 2


def test_comparison_rejects_source_changed_while_other_layer_decodes(comparison, monkeypatch):
    from utils import image_decode
    _, _, source = comparison
    paths = tuple(source.item(i).data(Qt.UserRole).path for i in (1, 2))
    original = image_decode.decode_image

    def decode_and_modify_earlier_layer(path, cancelled):
        decoded = original(path, cancelled)
        if path == paths[1]:
            # Change size as well as mtime, independent of filesystem clock resolution.
            with paths[0].open('ab') as stream:
                stream.write(b'changed')
        return decoded

    monkeypatch.setattr(image_decode, 'decode_image', decode_and_modify_earlier_layer)
    request = {'paths': paths, 'cache': {}, 'size': (96, 48),
               'mode': 'stretch', 'matte': QColor('black').rgba()}
    with pytest.raises(OSError, match='source changed'):
        image_decode.prepare_compare_images(request, threading.Event())
