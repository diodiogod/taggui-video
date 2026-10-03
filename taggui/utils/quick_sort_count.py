"""Owned database-only Quick Sort setup counts."""
from utils.image_index_db import ImageIndexDB


def count_quick_sort_requests(requests, cancelled):
    counts = []
    for request in requests:
        if cancelled.is_set():
            return None
        if request.get('empty'):
            counts.append(0)
            continue
        database = ImageIndexDB(request['directory'], read_only_path=request['db_path'])
        try:
            database.configure_filter_tokenizer(request['tokenizer'])
            database.conn.set_progress_handler(lambda: int(cancelled.is_set()), 1000)
            domain = database.count_or_raise(request['sql'], request['bindings'])
            counts.append(request['selected'] if request['mode'] == 'only'
                          else max(0, domain - request['selected']))
        finally:
            database.close()
    return None if cancelled.is_set() else counts
