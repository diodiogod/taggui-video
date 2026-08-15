import os
import sqlite3
from pathlib import Path
import sys


os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'taggui'))

from PySide6.QtWidgets import QApplication

from models.image_list_model import ImageListModel
from models.proxy_image_list_model import ProxyImageListModel
from utils.image import Image


def _app():
    return QApplication.instance() or QApplication([])


def _filter_sql_rows(model, filter_struct):
    sql, bindings = model._build_filter_sql(filter_struct)
    connection = sqlite3.connect(':memory:')
    try:
        connection.executescript(
            '''
            CREATE TABLE images (id INTEGER PRIMARY KEY);
            CREATE TABLE image_tags (image_id INTEGER, tag TEXT);
            '''
        )
        connection.executemany(
            'INSERT INTO images (id) VALUES (?)',
            [(1,), (2,), (3,), (4,), (5,)],
        )
        connection.executemany(
            'INSERT INTO image_tags (image_id, tag) VALUES (?, ?)',
            [
                (2, '__no_tags__'),
                (3, 'landscape'),
                (4, ''),
                (5, 'ab'),
                (5, 'cd'),
            ],
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


def test_paginated_tag_filters_ignore_empty_image_sentinel():
    model = ImageListModel.__new__(ImageListModel)
    model.tag_separator = ', '
    assert _filter_sql_rows(model, ['tags', '=', '0']) == [1, 2, 4]
    assert _filter_sql_rows(model, ['tag', '*']) == [3, 5]
    assert _filter_sql_rows(model, ['NOT', ['tag', '*']]) == [1, 2, 4]


def test_paginated_character_filters_measure_the_joined_caption():
    model = ImageListModel.__new__(ImageListModel)
    model.tag_separator = ', '
    assert _filter_sql_rows(model, ['chars', '<', '5']) == [1, 2, 4]
    assert _filter_sql_rows(model, ['chars', '=', '6']) == [5]


def test_in_memory_tag_filters_use_the_same_real_tag_count():
    app = _app()
    model = ImageListModel(256, ', ')
    proxy = ProxyImageListModel(model, tokenizer=None, tag_separator=', ')
    empty_image = Image(Path('empty.png'), (100, 100), tags=['__no_tags__'])
    tagged_image = Image(Path('tagged.png'), (100, 100), tags=['landscape'])

    assert proxy.does_image_match_filter(empty_image, ['tags', '=', '0'])
    assert proxy.does_image_match_filter(empty_image, ['NOT', ['tag', '*']])
    assert not proxy.does_image_match_filter(empty_image, ['tag', '*'])
    assert not proxy.does_image_match_filter(tagged_image, ['tags', '=', '0'])
    assert proxy.does_image_match_filter(tagged_image, ['tag', '*'])

    model.deleteLater()
    app.processEvents()
