"""Opt-in generated 27,000-row count responsiveness; isolated runner only."""
import json
import statistics
import time

from PySide6.QtCore import QTimer

from qt_test_helpers import APP, pump
from utils.image_index_db import ImageIndexDB
from utils.latest_task import LatestTask
from utils.quick_sort_count import count_quick_sort_requests


def test_count_heartbeat(tmp_path):
    db = ImageIndexDB(tmp_path)
    db.conn.executemany('INSERT INTO images(file_name,width,height,is_video,mtime) VALUES(?,32,32,0,1)',
                        [(f'folder/image-{i:06d}.png',) for i in range(27000)])
    db.conn.commit()
    request = {'directory': tmp_path, 'db_path': db.db_path, 'sql': 'TAGGUI_NAME_MATCH(file_name, ?)',
               'bindings': ('image*2',), 'tokenizer': None, 'mode': 'all_except', 'selected': 0}
    task, timer = LatestTask(), QTimer()
    timer.setInterval(1)
    ticks, accepted = [], []
    timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
    task.completed.connect(lambda token, counts, error: accepted.append((counts, error)))
    result = {}
    try:
        for name in ('synchronous', 'worker'):
            handler, finished, heartbeat, tick_counts = [], [], [], []
            for _ in range(5):
                ticks.clear()
                accepted.clear()
                timer.start()
                start = time.perf_counter()
                if name == 'synchronous':
                    counts = [db.count_or_raise(request['sql'], request['bindings'])]
                    accepted.append((counts, None))
                else:
                    task.submit(count_quick_sort_requests, [request])
                handler.append((time.perf_counter()-start)*1000)
                pump(lambda: bool(accepted))
                finished.append((time.perf_counter()-start)*1000)
                tick_counts.append(len(ticks))
                APP.processEvents()
                heartbeat.append((ticks[0]-start)*1000)
                timer.stop()
                assert accepted[0] == ([sum('2' in f'{i:06d}' for i in range(27000))], None)
            result[name] = {'handler_median_ms': statistics.median(handler),
                            'result_median_ms': statistics.median(finished),
                            'first_timer_median_ms': statistics.median(heartbeat),
                            'ticks_before_result': tick_counts}
        print('ASYNC_COUNT', json.dumps(result))
    finally:
        timer.stop()
        task.drain()
        task.close()
        db.close()
        APP.processEvents()
