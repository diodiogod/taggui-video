"""Bulk insert parity: row order, conflicts, transactions and variable limits."""
import sqlite3
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'taggui'))
from utils.sqlite_batches import execute_insert_batches
from utils.image_index_db import ImageIndexDB


def test_batching_preserves_conflicts_input_order_and_rollback():
    with sqlite3.connect(':memory:') as db:
        db.execute('CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT UNIQUE, value INTEGER)')
        db.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER,17)
        rows=[(f'name-{i}',i) for i in range(23)]
        cursor=db.cursor()
        assert execute_insert_batches(cursor,'INSERT OR IGNORE INTO items(name,value) VALUES(?,?)',iter(rows))==23
        assert execute_insert_batches(cursor,'INSERT OR IGNORE INTO items(name,value) VALUES(?,?)',rows)==0
        assert list(db.execute('SELECT name,value FROM items ORDER BY id'))==rows
        upsert='INSERT INTO items(name,value) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value'
        execute_insert_batches(cursor,upsert,[(name,value+1) for name,value in rows])
        assert list(db.execute('SELECT name,value FROM items ORDER BY id'))==[(name,value+1) for name,value in rows]
        db.rollback()
        assert db.execute('SELECT count(*) FROM items').fetchone()[0]==0


def test_real_bulk_insert_tracks_membership_without_losing_curator_data(tmp_path):
    db=ImageIndexDB(tmp_path)
    try:
        files=[tmp_path/f'{i}.png' for i in range(1200)]
        for path in files:
            path.touch()
        db.bulk_insert_files(files,tmp_path)
        assert db.count_or_raise()==1200
        first=db.get_image_id('0.png')
        db.set_rating(first,0.8)
        db.set_tags_for_image(first,['one','two','three'])
        before=db._order_revision()
        db.bulk_insert_files(files,tmp_path)
        assert db.count_or_raise()==1200
        assert db._order_revision()==before
        assert db.conn.execute('SELECT rating FROM images WHERE id=?',(first,)).fetchone()[0]==0.8
        assert db.get_tags_for_images([first])[first]==['one','two','three']
    finally:
        db.close()
