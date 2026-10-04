"""Opt-in matched panel construction/render probe; isolated runner required."""
import ast
import json
import statistics
import subprocess
import time

from qt_test_helpers import APP, dispose_widget
from widgets import auto_captioner


def test_caption_construction_and_render_against_checkpoint():
    APP.setStyle('Fusion')
    source = subprocess.check_output(
        ['git', 'show', '746a3ce:taggui/widgets/auto_captioner.py'], text=True, encoding='utf-8')
    cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == 'AutoCaptioner')
    methods = [n for n in cls.body if isinstance(n, ast.FunctionDef)
               and n.name in ('set_layout_mode', '_apply_layout_style')]
    namespace = dict(vars(auto_captioner))
    exec(compile(ast.Module(body=methods, type_ignores=[]), '<baseline>', 'exec'), namespace)
    baseline = type('BaselineCaptioner', (auto_captioner.AutoCaptioner,),
                    {'set_layout_mode': namespace['set_layout_mode'],
                     '_apply_layout_style': namespace['_apply_layout_style'],
                     '_apply_container_style': lambda *args: None})
    times = {'baseline': [], 'current': []}
    renders = {}
    for trial in range(6):
        variants = [('baseline', baseline), ('current', auto_captioner.AutoCaptioner)]
        for label, factory in variants if trial % 2 == 0 else reversed(variants):
            begin = time.perf_counter()
            panel = factory(None, None)
            elapsed = (time.perf_counter() - begin) * 1000
            if trial:
                times[label].append(elapsed)
            try:
                for mode in ('compact', 'classic', 'compact'):
                    panel.set_layout_mode(mode, persist=False)
                    panel.resize(440, 850)
                    panel.show()
                    APP.processEvents()
                    renders[label, mode] = panel.grab().toImage()
            finally:
                dispose_widget(panel)
                APP.processEvents()
        for mode in ('compact', 'classic'):
            assert renders['baseline', mode] == renders['current', mode], mode
    print('CAPTION_STARTUP', json.dumps({key: statistics.median(values) for key, values in times.items()}))
