import json
import os
import sqlite3
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT / 'taggui'))

from models.image_list_model import ImageListModel
from utils.image_index_db import ImageIndexDB


def _filter_model():
    model = ImageListModel.__new__(ImageListModel)
    model.tag_separator = ', '
    model._directory_path = Path('C:/dataset')
    return model


def _run_sql_filter(model, filter_struct):
    sql, bindings = model._build_filter_sql(filter_struct)
    connection = sqlite3.connect(':memory:')
    try:
        connection.executescript(
            '''
            CREATE TABLE images (
                id INTEGER PRIMARY KEY,
                file_name TEXT,
                width INTEGER,
                height INTEGER
            );
            CREATE TABLE image_tags (image_id INTEGER, tag TEXT);
            CREATE TABLE image_markings (
                image_id INTEGER,
                label TEXT,
                x INTEGER,
                y INTEGER,
                width INTEGER,
                height INTEGER
            );
            INSERT INTO images VALUES
                (1, 'sub/a.png', 512, 768),
                (2, 'other/b.png', 256, 256);
            INSERT INTO image_tags VALUES (1, 'short');
            INSERT INTO image_markings VALUES (1, 'watermark', 10, 10, 50, 50);
            '''
        )
        connection.create_function(
            'TAGGUI_TOKEN_COUNT',
            1,
            lambda value: len(str(value or '').split()),
        )
        connection.create_function(
            'TAGGUI_TARGET_MATCH',
            4,
            lambda _file_name, width, height, target: int(
                (int(width), int(height)) == (256, 256)
                and str(target) == '256x256'
            ),
        )
        connection.create_function(
            'TAGGUI_MARKING_VIEW_MATCH',
            10,
            lambda *_values: 1,
        )
        connection.create_function(
            'TAGGUI_PATH_MATCH',
            3,
            lambda file_name, directory, pattern: int(
                str(pattern) in str(file_name)
                or str(pattern) in f'{directory}/{file_name}'
            ),
        )
        connection.create_function(
            'TAGGUI_NAME_MATCH',
            2,
            lambda file_name, pattern: int(str(pattern) in str(file_name).rsplit('/', 1)[-1]),
        )
        connection.create_function(
            'TAGGUI_LABEL_MATCH',
            2,
            lambda label, pattern: int(str(pattern).strip('*') in str(label)),
        )
        return [
            row[0]
            for row in connection.execute(
                f'SELECT id FROM images WHERE {sql} ORDER BY id',
                bindings,
            )
        ]
    finally:
        connection.close()


def test_paginated_sql_covers_string_filters_missing_from_the_old_builder():
    model = _filter_model()
    assert _run_sql_filter(model, ['path', 'sub']) == [1]
    assert _run_sql_filter(model, ['size', '512:768']) == [1]
    assert _run_sql_filter(model, ['target', '256x256']) == [2]
    assert _run_sql_filter(model, ['visible', 'watermark']) == [1]
    assert _run_sql_filter(model, ['crops', 'watermark']) == [1]


def test_paginated_sql_uses_the_token_filter_predicate():
    model = _filter_model()
    assert _run_sql_filter(model, ['tokens', '>', '0']) == [1]


def test_every_parser_supported_filter_builds_a_paginated_predicate():
    model = _filter_model()
    filters = [
        ['tag', '*'],
        ['caption', 'cat'],
        ['ideogram', 'cat'],
        ['ideogram_color', 'blue'],
        ['marking', 'watermark'],
        ['marking_type', 'hint'],
        ['crops', 'watermark'],
        ['visible', 'watermark'],
        ['name', 'a'],
        ['path', 'sub'],
        ['size', '512x768'],
        ['target', '512x512'],
        ['love', 'true'],
        ['bomb', 'false'],
        ['review', 'ranked'],
        ['tags', '=', '0'],
        ['chars', '<', '100'],
        ['tokens', '<', '100'],
        ['stars', '>=', '4'],
        ['review_rank', '=', '3'],
        ['width', '=', '512'],
        ['height', '=', '768'],
        ['area', '=', '393216'],
    ]
    for filter_struct in filters:
        sql, bindings = model._build_filter_sql(filter_struct)
        assert sql, filter_struct
        assert isinstance(bindings, tuple), filter_struct


def test_database_filter_functions_match_token_and_crop_semantics(tmp_path):
    db = ImageIndexDB(tmp_path)
    try:
        db.save_info('image.png', 100, 100, False, 1.0)
        image_id = db.get_image_id('image.png')
        db.set_markings_for_image(
            image_id,
            [{
                'label': 'watermark',
                'type': 'hint',
                'confidence': 1.0,
                'rect': (10, 10, 30, 30),
            }],
        )
        (tmp_path / 'image.taggui.json').write_text(
            json.dumps({'version': 1, 'crop': [0, 0, 20, 20]}),
            encoding='utf-8',
        )
        db.configure_filter_tokenizer(
            lambda value: type(
                'Encoding',
                (),
                {'input_ids': [0] + str(value or '').split() + [1]},
            )(),
        )
        cursor = db.conn.cursor()
        cursor.execute("SELECT TAGGUI_TOKEN_COUNT('one two')")
        assert cursor.fetchone()[0] == 2
        cursor.execute(
            "SELECT TAGGUI_TARGET_MATCH('image.png', 100, 100, '20x20')"
        )
        assert cursor.fetchone()[0] == 1
        cursor.execute(
            "SELECT TAGGUI_MARKING_VIEW_MATCH(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)" ,
            ('image.png', 10, 10, 30, 30, 100, 100, 'watermark', 'water*', 'visible'),
        )
        assert cursor.fetchone()[0] == 1
        cursor.execute(
            "SELECT TAGGUI_MARKING_VIEW_MATCH(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)" ,
            ('image.png', 10, 10, 30, 30, 100, 100, 'watermark', 'water*', 'crops'),
        )
        assert cursor.fetchone()[0] == 1
    finally:
        db.close()
