"""Exercise real SQLite query contracts, including separate reader connections."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'taggui'))
from utils.image_index_db import ImageIndexDB


@pytest.fixture
def indexed(tmp_path):
    db = ImageIndexDB(tmp_path)
    assert db.conn is not None
    rows = [(f'item-{i}.png', i % 3 if i % 4 else None,
             i % 5 / 5, i % 2, (i // 2) % 2, None if i % 3 else 7)
            for i in range(30)]
    db.conn.executemany('''INSERT INTO images(file_name,width,height,is_video,mtime,rating,love,bomb,ctime)
        VALUES(?,?,20,0,10,?,?,?,?)''', rows)
    db.conn.commit()
    yield db
    db.close()


@pytest.mark.parametrize('field', ['width', 'height', 'mtime', 'ctime', 'rating',
                                  'file_name', 'RANDOM()', 'love_rate_bomb'])
@pytest.mark.parametrize('direction', ['ASC', 'DESC'])
def test_every_rank_matches_actual_page(indexed, field, direction):
    kwargs = dict(random_seed=42, filter_sql='id % 2 = ?', bindings=(0,))
    rows = indexed.get_page(0, 50, field, direction, **kwargs)
    assert len(rows) == 15
    for rank, row in enumerate(rows):
        assert indexed.get_rank_of_image(row['file_name'], field, direction, **kwargs) == rank
    assert indexed.get_rank_of_image('missing.png', field, direction, **kwargs) == -1


def test_other_connection_sort_does_not_replace_first_view(indexed):
    other = ImageIndexDB(indexed._directory_path)
    try:
        first = indexed.get_page(0, 30, 'RANDOM()', 'ASC', random_seed=21)
        assert len(first) == 30
        other.get_page(0, 30, 'RANDOM()', 'ASC', random_seed=93)
        assert indexed.get_page(0, 30, 'RANDOM()', 'ASC', random_seed=21) == first
        assert indexed.conn.execute('SELECT count(*) FROM ordered_views').fetchone()[0] == 2
    finally:
        other.close()


def test_edit_from_other_connection_invalidates_cached_order(indexed):
    other = ImageIndexDB(indexed._directory_path)
    try:
        indexed._should_use_order_cache_for_page = lambda *_: True
        first = indexed.get_page(0, 30, 'rating', 'DESC')
        edited = first[-1]['id']
        other.set_rating(edited, 1)
        assert indexed.get_page(0, 30, 'rating', 'DESC')[0]['id'] == edited
        before = indexed._order_revision()
        other.conn.execute('UPDATE images SET thumbnail_cached=1')
        other.conn.commit()
        assert indexed._order_revision() == before
    finally:
        other.close()


def test_eviction_between_ensure_and_fetch_falls_back(indexed):
    original = indexed._ensure_order_cache
    other = ImageIndexDB(indexed._directory_path)
    try:
        def evict(**kwargs):
            result = original(**kwargs)
            other.conn.execute('DELETE FROM ordered_view_items')
            other.conn.execute('DELETE FROM ordered_views')
            other.conn.commit()
            return result
        indexed._ensure_order_cache = evict
        assert len(indexed.get_page(0, 30, 'RANDOM()', 'ASC', random_seed=42)) == 30
    finally:
        other.close()


def test_large_scope_has_one_binding_and_shared_membership(indexed):
    names = [f'item-{i}.png' for i in range(40000)]
    scope = indexed.register_path_scope(names)
    other = ImageIndexDB(indexed._directory_path)
    try:
        query = 'EXISTS(SELECT 1 FROM image_scopes s WHERE s.scope_id=? AND s.file_name=images.file_name)'
        assert other.count(query, (scope,)) == 30
        assert len(other.get_page(0, 100, filter_sql=query, bindings=(scope,))) == 30
        assert len(indexed._serialize_order_cache_key(
            indexed._order_cache_key('mtime', 'DESC', query, (scope,)))) == 64
    finally:
        other.close()


def test_cached_order_reuse_does_not_wait_for_unrelated_writer(indexed):
    other = ImageIndexDB(indexed._directory_path)
    try:
        query = dict(sort_field='RANDOM()',sort_dir='ASC',random_seed=123)
        assert indexed._ensure_order_cache(**query)
        indexed.conn.execute('PRAGMA busy_timeout=1')
        other.conn.execute('UPDATE images SET thumbnail_cached=1')
        assert indexed._ensure_order_cache(**query)
        assert len(indexed.get_page(0,30,**query)) == 30
    finally:
        other.conn.rollback()
        other.close()


def test_cached_random_rank_avoids_repeating_dataset_random_function(indexed):
    query=dict(sort_field='RANDOM()',sort_dir='ASC',random_seed=234)
    rows=indexed.get_page(0,30,**query)
    traced=[]
    indexed.conn.set_trace_callback(traced.append)
    try:
        assert indexed.get_rank_of_image(rows[17]['file_name'],**query)==17
    finally:
        indexed.conn.set_trace_callback(None)
    assert not any('COUNT(*) FROM images' in statement for statement in traced)
