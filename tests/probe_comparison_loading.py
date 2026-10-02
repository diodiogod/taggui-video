"""Opt-in generated-media comparison probe; run only via run_isolated.py."""
import ast
import os
from pathlib import Path
import subprocess
import time
from types import MethodType

assert os.environ.get('TAGGUI_SETTINGS_PATH'), 'Run through tests/run_isolated.py'

from PySide6.QtCore import QSortFilterProxyModel, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QStandardItem, QStandardItemModel
from qt_test_helpers import APP, pump
from utils.image import Image
from utils.settings import settings
from widgets import image_viewer

assert Path(settings.fileName()).resolve() == Path(os.environ['TAGGUI_SETTINGS_PATH']).resolve()


def test_generated_comparison_handler_against_checkpoint(tmp_path):
    baseline_source = subprocess.check_output(
        ['git', 'show', 'd837a84:taggui/widgets/image_viewer.py'], text=True, encoding='utf-8')
    owner = next(node for node in ast.parse(baseline_source).body
                 if isinstance(node, ast.ClassDef) and node.name == 'ImageViewer')
    names = ('enter_compare_mode', '_build_compare_layer',
             '_load_static_pixmap_for_proxy_index', '_prepare_compare_overlay_pixmap')
    methods = [node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = dict(vars(image_viewer))
    exec(compile(ast.Module(body=methods, type_ignores=[]), '<checkpoint-comparison>', 'exec'), namespace)
    source = QStandardItemModel()
    source._directory_path = tmp_path
    for i, color in enumerate(('red', 'blue')):
        path = tmp_path/f'{i}.jpg'
        pixels = QImage(3000, 2000, QImage.Format_RGB32)
        pixels.fill(QColor(color))
        assert pixels.save(str(path), 'JPEG')
        item = QStandardItem()
        item.setData(Image(path, (3000,2000)), Qt.UserRole)
        source.appendRow(item)
    proxy = QSortFilterProxyModel()
    proxy.setSourceModel(source)
    for baseline in (True, False):
        viewer = image_viewer.ImageViewer(proxy)
        if baseline:
            for name in names:
                setattr(viewer, name, MethodType(namespace[name], viewer))
        handler, installed, gaps = [], [], []
        last = [time.perf_counter()]
        def heartbeat():
            now = time.perf_counter()
            gaps.append((now-last[0])*1000)
            last[0] = now
        timer = QTimer()
        timer.setInterval(2)
        timer.timeout.connect(heartbeat)
        try:
            viewer.load_image(proxy.index(0,0))
            pump(lambda: viewer.current_image_item is not None)
            timer.start()
            for sample in range(4):
                viewer.exit_compare_mode()
                last[0] = time.perf_counter()
                begin = last[0]
                assert viewer.enter_compare_mode(proxy.index(0,0), proxy.index(1,0))
                handler.append((time.perf_counter()-begin)*1000)
                pump(lambda: viewer._compare_overlay_count() == 1 and viewer._compare_prepare_owner is None)
                installed.append((time.perf_counter()-begin)*1000)
                APP.processEvents()
            print({'checkpoint' if baseline else 'current': {
                'handler_ms': [round(value,2) for value in handler],
                'accepted_install_ms': [round(value,2) for value in installed],
                'max_2ms_timer_gap': round(max(gaps, default=0),2),
                'first_paint_measured': False}})
        finally:
            timer.stop()
            viewer._compare_prepare_task.drain()
            viewer._image_decode_task.drain()
            viewer.close()
            viewer.deleteLater()
            APP.processEvents()
