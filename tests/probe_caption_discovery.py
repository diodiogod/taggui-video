"""Opt-in generated-workflow comparison; run through tests/run_isolated.py."""
import ast
import gc
import json
from pathlib import Path
import statistics
import subprocess
import time
import tracemalloc

from utils import caption_annotations, ideogram_caption, json_sidecar_reader


def checkpoint_function(module, name):
    source = subprocess.check_output([
        'git', 'show', f'b1aa6da:taggui/utils/{module.__name__.split(".")[-1]}.py'
    ], cwd=Path(__file__).resolve().parents[1], text=True, encoding='utf-8')
    function = next(node for node in ast.parse(source).body
                    if isinstance(node, ast.FunctionDef) and node.name == name)
    namespace = vars(module).copy()
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<checkpoint>', 'exec'), namespace)
    return namespace[name]


def test_generated_workflow_caption_discovery(tmp_path):
    media = tmp_path / 'generated.png'
    workflow = {'version': 1, 'state': {}, 'nodes': [
        {'id': i, 'inputs': {'nested': [{'name': 'test', 'value': [1, 2, 3]}]}}
        for i in range(40000)]}
    text = json.dumps(workflow)
    media.with_suffix('.json').write_text(text, encoding='utf-8')
    size = len(text.encode('utf-8'))
    del workflow, text
    baseline = [checkpoint_function(caption_annotations, 'load_caption_workspace'),
                checkpoint_function(ideogram_caption, 'discover_ideogram_caption')]
    current = [caption_annotations.load_caption_workspace,
               ideogram_caption.discover_ideogram_caption]
    results = {}
    for name, functions, fresh in [('checkpoint', baseline, True),
                                   ('current_first', current, True),
                                   ('current_repeat', current, False)]:
        durations = []
        for _ in range(5):
            if fresh:
                json_sidecar_reader._negative.clear()
            gc.collect()
            start = time.perf_counter()
            assert [function(media) for function in functions] == [None, None]
            durations.append((time.perf_counter() - start) * 1000)
        if fresh:
            json_sidecar_reader._negative.clear()
        gc.collect()
        tracemalloc.start()
        assert [function(media) for function in functions] == [None, None]
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        results[name] = {'median_ms': round(statistics.median(durations), 3),
                         'samples_ms': [round(value, 3) for value in durations],
                         'python_peak_mib': round(peak / 1024**2, 3)}
    print(json.dumps({'generated_bytes': size, 'results': results}, indent=2))
