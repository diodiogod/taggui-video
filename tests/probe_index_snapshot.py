"""Explicit opt-in database-only benchmark of a read-only source backup.

Run through tests/run_isolated.py with TAGGUI_AUDIT_SOURCE_INDEX set. Never
construct TagGUI services for the source folder or hydrate its media/sidecars.
"""
import json
import os
from pathlib import Path
import sqlite3
import time

import pytest


def test_index_snapshot_queries(tmp_path):
    configured = os.environ.get('TAGGUI_AUDIT_SOURCE_INDEX')
    if not configured:
        pytest.skip('Explicit source index required')
    source_path = Path(configured).resolve(strict=True)
    isolated_settings = Path(os.environ['TAGGUI_SETTINGS_PATH']).resolve(strict=True)
    assert isolated_settings.parent.name.startswith('taggui-tests-')
    destination = tmp_path/'.taggui'/'index.db'
    destination.parent.mkdir()
    assert destination.resolve() != source_path
    started = time.perf_counter()
    source = sqlite3.connect(source_path.as_uri()+'?mode=ro',uri=True)
    try:
        source.execute('PRAGMA query_only=ON')
        with sqlite3.connect(destination) as target:
            def progress(*args):
                if time.perf_counter()-started > 45:
                    raise TimeoutError('Read-only snapshot exceeded its measurement limit')
            source.backup(target,pages=256,progress=progress)
    finally:
        source.close()
    snapshot_ms=(time.perf_counter()-started)*1000
    from utils.image_index_db import ImageIndexDB
    db=ImageIndexDB(tmp_path)
    assert db.db_path.resolve()==destination.resolve()
    observations=[]
    try:
        total=db.count_or_raise()
        for field,direction in (('mtime','DESC'),('file_name','ASC'),('RANDOM()','ASC')):
            for page in (0,max(0,(total-1)//1000)):
                start=time.perf_counter()
                rows=db.get_page(page,1000,field,direction,random_seed=123)
                elapsed=(time.perf_counter()-start)*1000
                expected=min(1000,max(0,total-page*1000))
                assert len(rows)==expected
                rank_ms=None
                if rows:
                    start=time.perf_counter()
                    rank=db.get_rank_of_image(rows[-1]['file_name'],field,direction,random_seed=123)
                    rank_ms=(time.perf_counter()-start)*1000
                    assert rank==page*1000+len(rows)-1
                observations.append(dict(sort=field,direction=direction,page=page,
                    query_ms=round(elapsed,3),last_item_rank_ms=round(rank_ms,3) if rank_ms is not None else None))
        start=time.perf_counter()
        tags=db.get_all_tags(raise_errors=True)
        all_tags_ms=(time.perf_counter()-start)*1000
        start=time.perf_counter()
        filtered=db.get_filtered_tags('rating > ?', (0,),raise_errors=True)
        filtered_ms=(time.perf_counter()-start)*1000
        print('\nREAL_INDEX_SNAPSHOT '+json.dumps(dict(
            rows=total,snapshot_ms=round(snapshot_ms,3),queries=observations,
            unique_tags=len(tags),all_tag_counts_ms=round(all_tags_ms,3),
            rated_unique_tags=len(filtered),rated_tag_counts_ms=round(filtered_ms,3),
            sqlite=sqlite3.sqlite_version,media_hydration=False)))
    finally:
        db.close()
