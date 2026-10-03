from types import SimpleNamespace
import sqlite3
import threading
from collections import OrderedDict

import pytest

from utils.image_index_db import ImageIndexDB


def test_filtered_counts_reuse_tokens_but_not_across_queries(tmp_path):
    db = ImageIndexDB(tmp_path)
    calls = []

    def tokenizer(text):
        calls.append(text)
        return SimpleNamespace(input_ids=[0] * (len(text) + 2))

    try:
        for i in range(4):
            db.save_info(f'{i}.png', 10, 10, False, 1.0)
            db.set_tags_for_image(db.get_image_id(f'{i}.png'), [f'{i}a', f'{i}b', f'{i}c'])
        db.configure_filter_tokenizer(tokenizer)
        clause = 'TAGGUI_TOKEN_COUNT(images.file_name) > ?'
        actual = db.get_filtered_tags(clause, (0,), raise_errors=True)
        assert len(actual) == 12
        assert len(calls) == 4
        assert db._filter_query_state.token_counts is None
        assert db._filter_query_state.token_bytes == 0
        calls.clear()
        assert db.get_filtered_tags(clause, (0,), raise_errors=True) == actual
        assert len(calls) == 4
        db.configure_filter_tokenizer(lambda text: SimpleNamespace(input_ids=[0, 0]))
        assert db.get_filtered_tags(clause, (0,), raise_errors=True) == []
        with pytest.raises(sqlite3.Error):
            db.get_filtered_tags('missing_function(images.id)', raise_errors=True)
        assert db._filter_query_state.token_counts is None
        assert db._filter_query_state.token_bytes == 0
    finally:
        db.close()


def test_memo_bounds_errors_and_thread_isolation(tmp_path):
    db = ImageIndexDB(tmp_path)
    calls = []

    def tokenizer(text):
        calls.append(text)
        if text == 'fail':
            raise ValueError('temporary failure')
        return SimpleNamespace(input_ids=[0, 1, 2])

    try:
        db.configure_filter_tokenizer(tokenizer)
        state = db._filter_query_state
        state.token_counts, state.token_bytes = OrderedDict(), 0
        for text in ('short', 'short'):
            assert db._sql_token_count(text) == 1
        assert calls == ['short']
        worker = threading.Thread(target=lambda: db._sql_token_count('short'))
        worker.start()
        worker.join()
        assert calls == ['short', 'short']
        for _ in range(2):
            assert db._sql_token_count('fail') == 0
        assert calls.count('fail') == 2
        for _ in range(2):
            assert db._sql_token_count('x' * 4097) == 1
        assert calls.count('x' * 4097) == 2
        assert len(state.token_counts) == 1
        for index in range(5000):
            db._sql_token_count(f'{index:04d}' + 'x' * 1024)
        assert len(state.token_counts) <= 4096
        assert state.token_bytes <= 2 * 1024 * 1024
        assert 'short' not in state.token_counts
    finally:
        db.close()
