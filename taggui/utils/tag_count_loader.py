"""Read complete tag counts on a request-owned SQLite connection."""
from utils.image_index_db import ImageIndexDB


def prepare_tag_counts(request, cancelled):
    if cancelled.is_set():
        return None
    db = ImageIndexDB(request['directory'])
    try:
        db.configure_filter_tokenizer(request['tokenizer'])
        db.conn.set_progress_handler(lambda: int(cancelled.is_set()), 1000)
        db.conn.execute('BEGIN')
        all_tags = db.get_all_tags(raise_errors=True)
        if cancelled.is_set():
            return None
        filtered = db.get_filtered_tags(request['sql'], request['bindings'], raise_errors=True) if request['filtered'] else None
        if cancelled.is_set():
            return None
        return request, all_tags, filtered
    finally:
        db.close()
