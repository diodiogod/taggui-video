"""Opt-in construction comparison; run only through tests/run_isolated.py."""
import ast
import json
import statistics
import subprocess
import time
from types import SimpleNamespace

from PySide6.QtCore import QSortFilterProxyModel
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import QMainWindow

from qt_test_helpers import APP, dispose_widget
from utils.settings import settings
from widgets import ideogram_caption_editor, pipeline_editor
from widgets.image_viewer import ImageViewer


def _checkpoint_constructor(module, name, path):
    source = subprocess.check_output(['git', 'show', f'1cbc935:{path}'],
                                     text=True, encoding='utf-8')
    cls = next(node for node in ast.parse(source).body
               if isinstance(node, ast.ClassDef) and node.name == name)
    constructor = next(node for node in cls.body
                       if isinstance(node, ast.FunctionDef) and node.name == '__init__')
    # Extract only the checkpoint constructor. An explicit super keeps the
    # same base initialization without a synthetic __class__ closure.
    for node in ast.walk(constructor):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == 'super' and not node.args):
            node.args = [ast.Name(id=name, ctx=ast.Load()), ast.Name(id='self', ctx=ast.Load())]
    namespace = dict(vars(module))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[constructor], type_ignores=[])),
                 f'<checkpoint {name} constructor>', 'exec'), namespace)
    return type('Checkpoint' + name, (getattr(module, name),), {'__init__': namespace['__init__']})


def test_panel_construction_and_final_render_parity():
    # Match run_gui's production style. All stores and paths were isolated by
    # the runner before these widget/service modules were imported.
    APP.setStyle('Fusion')
    model, proxy = QStandardItemModel(), QSortFilterProxyModel()
    proxy.setSourceModel(model)
    viewer = ImageViewer(proxy)
    host = QMainWindow()
    host.image_list_model = model
    host.auto_captioner = SimpleNamespace(caption_settings_form=None)
    results = {}
    try:
        for module, name, path, arguments, setting in (
            (ideogram_caption_editor, 'IdeogramCaptionEditor',
             'taggui/widgets/ideogram_caption_editor.py', (viewer,), 'ideogram_caption_ui_zoom'),
            (pipeline_editor, 'PipelineEditor',
             'taggui/widgets/pipeline_editor.py', (host,), 'pipeline_ui_zoom'),
        ):
            checkpoint = _checkpoint_constructor(module, name, path)
            classes = {'checkpoint': checkpoint, 'current': getattr(module, name)}
            for zoom in (60, 100, 160):
                settings.setValue(setting, zoom)
                samples = {label: [] for label in classes}
                final = {}
                # One warm-up pair; alternate order to limit cache-order bias.
                for trial in range(6):
                    order = list(classes) if trial % 2 == 0 else list(reversed(classes))
                    for label in order:
                        start = time.perf_counter()
                        panel = classes[label](*arguments)
                        elapsed = (time.perf_counter() - start) * 1000
                        try:
                            if trial:
                                samples[label].append(elapsed)
                            panel.resize(440, 640)
                            panel.ensurePolished()
                            final[label] = (panel.styleSheet(), panel.widget().styleSheet(),
                                            panel.grab().toImage())
                        finally:
                            dispose_widget(panel)
                            APP.processEvents()
                assert final['checkpoint'] == final['current'], (name, zoom)
                results[f'{name}_{zoom}'] = {
                    label + '_median_ms': round(statistics.median(values), 3)
                    for label, values in samples.items()}
                results[f'{name}_{zoom}']['exact_final_render_parity'] = True
        print('PANEL_STARTUP_COMPARISON', json.dumps(results))
    finally:
        dispose_widget(host)
        viewer._image_decode_task.drain()
        viewer._compare_prepare_task.drain()
        dispose_widget(viewer)
        APP.processEvents()
