"""Compare live predicates with actual SQLite results and GUI-parsed input."""
import json
import random
import sqlite3

import pytest

from qt_test_helpers import APP, dispose_widget
from models.image_list_model import ImageListModel
from models.proxy_image_list_model import ProxyImageListModel
from utils.image import Image
from utils.image_index_db import ImageIndexDB
from utils.search_text import matches_like
from widgets.image_list_shared import FilterLineEdit


def test_like_matcher_matches_sqlite_oracle():
    connection = sqlite3.connect(':memory:')
    try:
        samples = ['', 'Blue', 'École', 'école', 'aXb', 'a_b', 'a%b', 'a?b', '[cb]at',
                   'line\nbreak', 'a\0rest', '猫🙂', '*', '?', '[', ']']
        patterns = ['', '%', '_', 'b%', 'É%', 'é%', '%a_b%', '%a%b%', '%*%', '%?%',
                    '[cb]at', '[%]', '[[_]]', '%\0ignored', 'a\0rest', '_%', '%_%']
        for text in samples:
            for pattern in patterns:
                assert matches_like(text, pattern) == bool(connection.execute(
                    'SELECT ? LIKE ?', (text, pattern)).fetchone()[0]), (text, pattern)
        rng = random.Random(42)
        alphabet = 'aABÉé_?*%[]\n猫🙂\0'
        for _ in range(1500):
            text = ''.join(rng.choices(alphabet, k=rng.randrange(20)))
            pattern = ''.join(rng.choices(alphabet, k=rng.randrange(12)))
            assert matches_like(text, pattern) == bool(connection.execute(
                'SELECT ? LIKE ?', (text, pattern)).fetchone()[0]), (text, pattern)
    finally:
        connection.close()


@pytest.fixture
def search_fixture(tmp_path):
    model = ImageListModel(128, ', ')
    model._directory_path = tmp_path
    proxy = ProxyImageListModel(model, tokenizer=None, tag_separator=', ')
    model.proxy_image_list_model = proxy
    parser = FilterLineEdit()
    database = ImageIndexDB(tmp_path)
    images = []
    for name, tags in [('aXb.png', ['Blue', 'red', 'car']), ('a_b.png', ['blue', '[cb]at']),
                       ('a%b.png', ['cat', 'a?b']), ('empty.png', ['__no_tags__']),
                       ('sub/École.png', ['École', '猫🙂']), ('sub/école.png', ['école'])]:
        image = Image(tmp_path / name, (100, 100), tags=tags)
        images.append(image)
        database.save_info(name.replace('/', '\\'), 100, 100, False, 1)
        database.set_tags_for_image(database.get_image_id(name.replace('/', '\\')), tags)
    # A palette-like word in prose must not be mistaken for a palette field.
    (tmp_path / 'aXb.ideogram.json').write_text(json.dumps({
        'high_level_description': 'A blue object marked #BADBAD.',
        'style_description': {'aesthetics': 'clean', 'lighting': 'even', 'medium': 'drawing',
                              'art_style': 'flat', 'color_palette': ['#CC0000', '#00AAFF']},
        'compositional_deconstruction': {'background': 'plain', 'elements': []},
    }), encoding='utf-8')
    (tmp_path / 'empty.json').write_text('{"unrelated":true}', encoding='utf-8')
    for image in images:
        database.set_ideogram_caption_text_for_file(
            str(image.path.relative_to(tmp_path)).replace('/', '\\'), image.path)
    database.conn.commit()
    try:
        yield model, proxy, parser, database, images
    finally:
        model.proxy_image_list_model = None
        proxy.setSourceModel(None)
        model.shutdown_background_workers()
        database.close()
        dispose_widget(parser)
        proxy.deleteLater()
        model.deleteLater()
        APP.processEvents()


@pytest.mark.parametrize('text', [
    'tag:b*', 'tag:Blue', 'tag:blue', 'tag:[cb]at', 'tag:*[cb]*', 'tag:a?b',
    'a_b', 'a%b', '"red, car"', 'caption:"red, car"', 'caption:RED', 'caption:""',
    'caption:*', 'caption:?', 'caption:"École"', 'caption:"école"', 'caption:"猫_"',
    'ideogram:BLUE', 'ideogram:""', 'ideogram:b*', 'ideogram:"#CC0000"',
    'ideogram_color:"#CC*"', 'ideogram_color:"cc0000"', 'ideogram_color:"#BADBAD"',
    'ideogram_color:""', 'ideogram_color:"#cc0000, #00aaff"',
    'NOT tag:b*', 'tag:b* OR caption:"猫_"', 'tag:b* AND NOT caption:green',
    'name:"École"', 'path:sub', 'tags:=0', 'chars:>3',
])
def test_parsed_text_search_and_membership_match_sql(search_fixture, text):
    model, proxy, parser, database, images = search_fixture
    parser.setText(text)
    node = parser.parse_filter_text()
    assert node is not None
    sql, bindings = model._build_filter_sql(node)
    expected = {row[0] for row in database.conn.execute(
        'SELECT file_name FROM images WHERE ' + sql, bindings)}
    actual = {str(image.path.relative_to(model._directory_path)).replace('/', '\\')
              for image in images if proxy.does_image_match_filter(image, node)}
    assert actual == expected
    # Membership is consulted in edit/undo paths even with pagination enabled.
    proxy.filter = node
    model._paginated_mode = True
    assert {str(image.path.relative_to(model._directory_path)).replace('/', '\\')
            for image in images if proxy.is_image_in_filtered_images(image)} == expected


def test_plain_term_does_not_match_only_the_root_directory(search_fixture):
    model, proxy, parser, database, images = search_fixture
    needle = model._directory_path.name
    node = needle
    sql, bindings = model._build_filter_sql(node)
    assert database.conn.execute('SELECT COUNT(*) FROM images WHERE ' + sql, bindings).fetchone()[0] == 0
    assert not any(proxy.does_image_match_filter(image, node) for image in images)


@pytest.mark.parametrize('text, names', [
    ('tag:b*', {'aXb.png', 'a_b.png'}),
    ('tag:Blue', {'aXb.png'}),
    ('tag:[cb]at', {'a_b.png'}),
    ('a_b', {'aXb.png', 'a_b.png', 'a%b.png'}),
    ('caption:"red, car"', set()),
    ('caption:*', set()),
    ('ideogram_color:"#BADBAD"', set()),
    ('ideogram_color:"#cc*"', {'aXb.png'}),
])
def test_existing_paginated_results_are_preserved(search_fixture, text, names):
    model, proxy, parser, database, images = search_fixture
    parser.setText(text)
    node = parser.parse_filter_text()
    sql, bindings = model._build_filter_sql(node)
    assert {row[0] for row in database.conn.execute(
        'SELECT file_name FROM images WHERE ' + sql, bindings)} == names
    assert {image.path.name for image in images if proxy.does_image_match_filter(image, node)} == names
