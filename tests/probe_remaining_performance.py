"""Opt-in remaining-candidate measurements; use tests/run_isolated.py."""
import json
import statistics
import time
from pathlib import Path
import ast
import subprocess

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap

from qt_test_helpers import APP
from utils.image_index_db import ImageIndexDB
from utils.lazy_tokenizer import LazyTokenizer
from utils.image_decode import decode_image
import threading


def timed(function, repeats=5):
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        function()
        samples.append((time.perf_counter() - start) * 1000)
    return round(statistics.median(samples), 3)


def test_native_scale_and_conversion_costs():
    results = []
    for width, height in ((2048, 1536), (6000, 4000)):
        for format in (QImage.Format_RGB32, QImage.Format_RGBA8888):
            source = QImage(width, height, format)
            source.fill(Qt.GlobalColor.red)
            retained = []

            def scale():
                retained[:] = [source.scaled(width // 4, height // 4,
                    Qt.IgnoreAspectRatio, Qt.SmoothTransformation)]

            scale_ms = timed(scale)
            scaled = retained[0]

            def convert():
                retained[:] = [QPixmap.fromImage(scaled)]

            convert_ms = timed(convert)
            results.append({'size': [width, height], 'format': format.name,
                            'scale_ms': scale_ms, 'convert_ms': convert_ms})
    print('NATIVE_COSTS', json.dumps(results))


def test_actual_decoder_scale_formats(tmp_path):
    results = []
    for suffix, alpha in (('jpg', False), ('png', False), ('png', True), ('webp', True)):
        source = QImage(6000, 4000, QImage.Format_ARGB32)
        source.fill(0x80904020 if alpha else 0xff904020)
        path = tmp_path / f'fixture-{alpha}.{suffix}'
        assert source.save(str(path))
        decoded = decode_image(path, threading.Event()).image
        results.append({'suffix': suffix, 'alpha': alpha, 'format': decoded.format().name,
                        'quarter_scale_ms': timed(lambda: decoded.scaled(
                            1500, 1000, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))})
    print('DECODED_SCALE', json.dumps(results))


def test_filtered_tag_candidate(tmp_path):
    db = ImageIndexDB(tmp_path)
    try:
        db.conn.executemany(
            'INSERT INTO images(file_name,width,height,is_video,mtime) VALUES(?,32,32,0,10)',
            [(f'{i}.png',) for i in range(5000)])
        ids = [row[0] for row in db.conn.execute('SELECT id FROM images')]
        db.conn.executemany('INSERT INTO image_tags(image_id,tag) VALUES(?,?)',
            [(identity, f'tag{tag}') for identity in ids for tag in range(20)])
        db.conn.commit()
        calls = 0

        def predicate(identity):
            nonlocal calls
            calls += 1
            return identity % 2

        db.conn.create_function('PROBE_MATCH', 1, predicate)
        results = []
        for clause in ('images.id % 2 = 1', 'PROBE_MATCH(images.id) = 1'):
            old = lambda: db.get_filtered_tags(clause, raise_errors=True)
            sql = f'''WITH matched AS MATERIALIZED
                (SELECT images.id FROM images WHERE {clause})
                SELECT image_tags.tag, COUNT(*) AS count
                FROM image_tags JOIN matched ON matched.id = image_tags.image_id
                WHERE image_tags.tag != '__no_tags__'
                GROUP BY image_tags.tag ORDER BY count DESC'''
            new = lambda: [{'tag': row[0], 'count': row[1]}
                           for row in db.conn.execute(sql).fetchall()]
            assert {r['tag']: r['count'] for r in old()} == {r['tag']: r['count'] for r in new()}
            calls = 0
            old_ms = timed(old)
            old_calls = calls // 5
            calls = 0
            new_ms = timed(new)
            results.append({'clause': clause, 'old_ms': old_ms, 'candidate_ms': new_ms,
                            'old_calls': old_calls, 'candidate_calls': calls // 5})
        print('TAG_COUNTS', json.dumps(results))
    finally:
        db.close()


def test_real_tokenizer_count_reuse(tmp_path):
    db = ImageIndexDB(tmp_path)
    root = Path(__file__).resolve().parents[1]
    tokenizer = LazyTokenizer(root / 'clip-vit-base-patch32')
    tokenizer('warm up')
    calls = 0

    def count_tokens(text):
        nonlocal calls
        calls += 1
        return tokenizer(text)

    try:
        db.conn.executemany(
            'INSERT INTO images(file_name,width,height,is_video,mtime) VALUES(?,32,32,0,10)',
            [(f'{i}.png',) for i in range(1000)])
        ids = [row[0] for row in db.conn.execute('SELECT id FROM images')]
        db.conn.executemany('INSERT INTO image_tags(image_id,tag) VALUES(?,?)',
            [(identity, f'caption word {tag} for image {identity}')
             for identity in ids for tag in range(10)])
        db.conn.commit()
        db.configure_filter_tokenizer(count_tokens)
        clause = '''TAGGUI_TOKEN_COUNT(COALESCE((SELECT GROUP_CONCAT(tag, ',')
            FROM image_tags WHERE image_id=images.id AND tag != '__no_tags__'), '')) > 0'''
        source = subprocess.check_output(['git', 'show', '86d1bfd:taggui/utils/image_index_db.py'],
                                        cwd=root, text=True, encoding='utf-8')
        cls = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef)
                   and node.name == 'ImageIndexDB')
        method = next(node for node in cls.body if isinstance(node, ast.FunctionDef)
                      and node.name == '_sql_token_count')
        namespace = {}
        exec(compile(ast.Module(body=[method], type_ignores=[]), '<checkpoint>', 'exec'), namespace)
        original = namespace['_sql_token_count'].__get__(db)
        results = {}
        expected = None
        for name, callback in [('checkpoint', original), ('current', db._sql_token_count)]:
            db.conn.create_function('TAGGUI_TOKEN_COUNT', 1, callback)
            result = db.get_filtered_tags(clause, raise_errors=True)
            mapping = {row['tag']: row['count'] for row in result}
            if expected is None:
                expected = mapping
            assert mapping == expected
            calls = 0
            elapsed = timed(lambda: db.get_filtered_tags(clause, raise_errors=True), repeats=3)
            results[name] = {'median_ms': elapsed, 'tokenizations': calls // 3}
        print('REAL_TOKENIZER', json.dumps(results))
    finally:
        db.close()
