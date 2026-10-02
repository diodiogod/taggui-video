from pathlib import Path
import sys
from types import SimpleNamespace
import threading

from PySide6.QtGui import QImage, QColor

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'taggui'))
from utils.thumbnail_cache import ThumbnailCache
from models.image_list_model import ImageListModel, load_thumbnail_data


def test_failed_encode_preserves_previous_complete_file(tmp_path):
    cache = ThumbnailCache.__new__(ThumbnailCache)
    cache.enabled, cache.cache_dir = True, tmp_path
    source = tmp_path / 'generated.png'
    image = QImage(16, 16, QImage.Format_RGB32)
    image.fill(QColor('red'))
    assert image.save(str(source))
    mtime = source.stat().st_mtime
    assert cache.save_thumbnail_qimage(source, mtime, 16, image)
    target = cache._get_cache_path(cache._get_cache_key(source, mtime, 16))
    previous = target.read_bytes()
    failed = SimpleNamespace(isNull=lambda: False, save=lambda *_a, **_k: False)
    assert not cache.save_thumbnail_qimage(source, mtime, 16, failed)
    assert target.read_bytes() == previous


def test_deferred_old_pixels_are_not_published_under_new_mtime(tmp_path, monkeypatch):
    from utils import thumbnail_cache
    source = tmp_path / 'generated.png'
    pixels = QImage(16, 16, QImage.Format_RGB32)
    pixels.fill(QColor('red'))
    assert pixels.save(str(source))
    calls = []
    monkeypatch.setattr(thumbnail_cache, 'get_thumbnail_cache', lambda: SimpleNamespace(
        enabled=False, save_thumbnail_qimage=lambda *a: calls.append(a)))
    decoded, _, _, _ = load_thumbnail_data(source, None, 16, False)
    assert decoded.text('taggui_source')
    source.write_bytes(b'replaced source contents')
    model = SimpleNamespace(_shutdown_requested=False, _db=None)
    ImageListModel._save_thumbnail_worker(model, source, None, 16, decoded)
    assert calls == []


def test_failed_save_does_not_increment_bookkeeping(tmp_path, monkeypatch):
    from utils import thumbnail_cache
    source = tmp_path / 'generated.png'
    pixels = QImage(16, 16, QImage.Format_RGB32)
    assert pixels.save(str(source))
    monkeypatch.setattr(thumbnail_cache, 'get_thumbnail_cache', lambda: SimpleNamespace(
        save_thumbnail_qimage=lambda *a: False))
    model = SimpleNamespace(_shutdown_requested=False, _db=None,
                            _cache_saves_lock=threading.Lock(), _cache_saves_count=0)
    ImageListModel._save_thumbnail_worker(model, source, source.stat().st_mtime, 16, pixels)
    assert model._cache_saves_count == 0


def test_source_replaced_during_publication_is_not_marked_cached(tmp_path, monkeypatch):
    from utils import thumbnail_cache
    source = tmp_path / 'generated.png'
    pixels = QImage(16,16,QImage.Format_RGB32)
    assert pixels.save(str(source))
    mtime = source.stat().st_mtime
    def replace_while_saving(*args):
        source.write_bytes(b'new source')
        return True
    monkeypatch.setattr(thumbnail_cache,'get_thumbnail_cache',lambda:SimpleNamespace(
        save_thumbnail_qimage=replace_while_saving))
    model = SimpleNamespace(_shutdown_requested=False,
        _db=SimpleNamespace(_directory_path=tmp_path),
        _pending_db_cache_flags_lock=threading.Lock(),_pending_db_cache_flags=[],
        _cache_saves_lock=threading.Lock(),_cache_saves_count=0)
    ImageListModel._save_thumbnail_worker(model,source,mtime,16,pixels)
    assert model._pending_db_cache_flags == []


def test_deferred_cache_flag_cannot_promote_reindexed_source(tmp_path):
    from utils.image_index_db import ImageIndexDB
    db = ImageIndexDB(tmp_path)
    db.conn.execute('INSERT INTO images(file_name,mtime,is_video) VALUES(?,?,0)',('generated.png',20))
    db.conn.commit()
    callbacks = []
    model = SimpleNamespace(_shutdown_requested=False,_db=db,
        _save_executor=SimpleNamespace(submit=callbacks.append),
        _pending_db_cache_flags_lock=threading.Lock(),
        _pending_db_cache_flags=[(db,'generated.png',10)])
    try:
        ImageListModel._flush_db_cache_flags(model)
        callbacks.pop()()
        assert db.conn.execute('SELECT thumbnail_cached FROM images').fetchone()[0] == 0
    finally:
        db.close()
