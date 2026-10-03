"""Opt-in synthetic UI resize timing: run through tests/run_isolated.py."""
import ast
import json
import statistics
import subprocess
import time
from types import MethodType

from PySide6.QtCore import Qt, QSortFilterProxyModel, QTimer
from PySide6.QtGui import QImage, QPixmap, QStandardItemModel

from qt_test_helpers import APP, dispose_widget, pump
from widgets.image_viewer import ImageViewer
from utils.latest_task import LatestTask


class PrototypeViewer(ImageViewer):
    """Measurement-only prototype: intentionally not shipped in the viewer."""
    def __init__(self, proxy):
        super().__init__(proxy)
        self._mipmap_task = LatestTask(self)
        self._mipmap_task.completed.connect(self._accept_scale)

    def _get_static_mipmap_pixmap(self, divisor):
        if divisor in self._static_mipmap_pixmaps:
            return self._static_mipmap_pixmaps[divisor]
        self._requested_divisor = divisor
        def scale(payload, cancelled):
            source, factor = payload
            return source.scaled(round(source.width()/factor), round(source.height()/factor),
                                 Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        self._mipmap_task.submit(scale, (self._static_source_qimage, divisor))
        return QPixmap()

    def _accept_scale(self, token, pixels, error):
        assert error is None
        self._static_mipmap_pixmaps[self._requested_divisor] = QPixmap.fromImage(pixels)
        self._apply_static_image_quality_for_scale(.1)


def test_async_mipmap_handler_and_heartbeat():
    baseline = subprocess.check_output(
        ['git', 'show', '0d0a53f:taggui/widgets/image_viewer.py'], text=True, encoding='utf-8')
    method = next(node for node in ast.walk(ast.parse(baseline))
                  if isinstance(node, ast.FunctionDef) and node.name == '_get_static_mipmap_pixmap')
    namespace = {'QPixmap': QPixmap, 'Qt': Qt}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])),
                 '<checkpoint mipmap method>', 'exec'), namespace)
    model, proxy = QStandardItemModel(), QSortFilterProxyModel()
    proxy.setSourceModel(model)
    viewer = PrototypeViewer(proxy)
    pixels = QImage(6000, 4000, QImage.Format_ARGB32)
    pixels.fill(0x80904020)
    viewer._static_source_qimage = pixels
    viewer._static_source_size = pixels.size()
    full = QPixmap.fromImage(pixels)
    viewer.current_image_item = viewer.scene.addPixmap(full)
    viewer.view.scale(.1, .1)
    current = viewer._get_static_mipmap_pixmap
    timer = QTimer()
    timer.setInterval(1)
    ticks = []
    timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
    result = {}
    try:
        for name, getter in [('checkpoint', MethodType(namespace['_get_static_mipmap_pixmap'], viewer)),
                             ('worker', current),
                             ('display_source', MethodType(ImageViewer._get_static_mipmap_pixmap, viewer))]:
            viewer._static_source_qimage = pixels
            durations, complete, first_tick, during = [], [], [], []
            viewer._get_static_mipmap_pixmap = getter
            for _ in range(7):
                viewer._static_mipmap_pixmaps = {1: full}
                viewer._static_current_mip_divisor = 1
                viewer.current_image_item.setPixmap(full)
                viewer.current_image_item.setScale(1)
                ticks.clear()
                timer.start()
                start = time.perf_counter()
                viewer._apply_static_image_quality_for_scale(.1)
                durations.append((time.perf_counter() - start) * 1000)
                pump(lambda: viewer._static_current_mip_divisor == 4)
                installed = time.perf_counter()
                complete.append((installed - start) * 1000)
                during.append(len(ticks))
                APP.processEvents()
                first_tick.append((ticks[0] - start) * 1000 if ticks else None)
                timer.stop()
            result[name] = {'handler_median_ms': statistics.median(durations),
                            'installed_median_ms': statistics.median(complete),
                            'first_timer_median_ms': statistics.median(t for t in first_tick if t is not None),
                            'timer_ticks_before_install': during}
        print('ASYNC_MIPMAP', json.dumps(result))
    finally:
        timer.stop()
        viewer._mipmap_task.drain()
        dispose_widget(viewer)
        APP.processEvents()
