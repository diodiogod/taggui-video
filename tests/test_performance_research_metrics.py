"""Generated-media measurements; reports mechanisms, never real-folder gains."""
import ast
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import MethodType

from PySide6.QtCore import QSortFilterProxyModel, QTimer, Qt
from PySide6.QtGui import QImage, QColor, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QApplication

sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'taggui'))
from widgets import image_viewer
from utils.image import Image
from utils.image_index_db import ImageIndexDB
from utils.sqlite_batches import execute_insert_batches

APP=QApplication.instance() or QApplication([])


def test_generated_viewer_input_return_and_decode_delivery(tmp_path):
    path=tmp_path/'generated-4096.jpg'
    pixels=QImage(4096,3072,QImage.Format_RGB32)
    pixels.fill(QColor('#659e35'))
    assert pixels.save(str(path),'JPEG',quality=92)
    source=QStandardItemModel()
    source._directory_path=tmp_path
    item=QStandardItem()
    item.setData(Image(path,(4096,3072)),Qt.UserRole)
    source.appendRow(item)
    proxy=QSortFilterProxyModel()
    proxy.setSourceModel(source)
    # Execute only the committed handler, using the same current viewer shell
    # and unchanged rendering helpers. No baseline application/settings import.
    text=subprocess.check_output(['git','show','45f749d35dd67b06dadd0571c6486a080208b324:taggui/widgets/image_viewer.py'],encoding='utf-8')
    parsed=ast.parse(text)
    cls=next(node for node in parsed.body if isinstance(node,ast.ClassDef) and node.name=='ImageViewer')
    handler=next(node for node in cls.body if isinstance(node,ast.FunctionDef) and node.name=='_load_image_impl')
    namespace=dict(image_viewer.__dict__)
    exec(compile(ast.Module(body=[handler],type_ignores=[]),'<committed-viewer-handler>','exec'),namespace)
    observations=[]
    for mode in ('committed synchronous handler','owned asynchronous handler'):
        viewer=image_viewer.ImageViewer(proxy)
        if mode.startswith('committed'):
            viewer._load_image_impl=MethodType(namespace['_load_image_impl'],viewer)
        gaps=[]
        clock=[time.perf_counter()]
        timer=QTimer()
        def tick():
            now=time.perf_counter();gaps.append((now-clock[0])*1000);clock[0]=now
        timer.timeout.connect(tick)
        timer.start(2)
        try:
            samples=[]
            for _ in range(4):
                APP.processEvents()
                clock[0]=time.perf_counter()
                start=clock[0]
                viewer.load_image(proxy.index(0,0))
                returned=(time.perf_counter()-start)*1000
                deadline=time.perf_counter()+5
                while viewer._image_decode_owner is not None and time.perf_counter()<deadline:
                    APP.processEvents();time.sleep(.001)
                APP.processEvents()
                assert viewer._image_decode_owner is None
                assert viewer.current_image_item is not None
                assert viewer._static_source_qimage.size().toTuple()==(4096,3072)
                samples.append({'input_handler_return_ms':round(returned,3),
                                'accepted_install_ms':round((time.perf_counter()-start)*1000,3)})
            observations.append({'mode':mode,'samples':samples,
                                 'max_2ms_timer_gap_ms':round(max(gaps),3)})
        finally:
            timer.stop()
            viewer._image_decode_task.drain()
            viewer.close()
    print('\nVIEWER_METRICS '+json.dumps(observations))


def test_compact_order_real_schema_generated_26848_rows(tmp_path):
    db=ImageIndexDB(tmp_path)
    try:
        start=time.perf_counter()
        execute_insert_batches(db.conn.cursor(),
            'INSERT INTO images(file_name,width,height,is_video,mtime) VALUES(?,?,?,?,?)',
            ((f'{i}.png',32,32,0,i%100) for i in range(26848)))
        db.conn.commit()
        insert_ms=(time.perf_counter()-start)*1000
        observations=[]
        for direction in ('ASC','DESC','ASC'):
            start=time.perf_counter()
            assert db._ensure_order_cache(sort_field='mtime',sort_dir=direction,
                                          filter_sql='file_name != ?',bindings=('x'*960,))
            elapsed=(time.perf_counter()-start)*1000
            observations.append(round(elapsed,3))
        keys=db.conn.execute('SELECT max(length(cache_key)),max(length(canonical_key)),count(*) FROM ordered_views').fetchone()
        assert keys[0]==64
        assert db.conn.execute('SELECT count(*) FROM ordered_view_items').fetchone()[0]==53696
        print('\nORDER_METRICS '+json.dumps({'rows':26848,'insert_with_revision_triggers_ms':round(insert_ms,3),
            'build_asc_desc_reuse_asc_ms':observations,'max_digest_chars':keys[0],
            'max_canonical_chars':keys[1],'retained_views':keys[2]}))
    finally:
        db.close()


def test_revision_trigger_write_cost_on_generated_schema(tmp_path):
    observations=[]
    count=26848
    # Alternate order to reduce simple warm-up/order bias. Both conditions use
    # the same current schema; the control removes only revision triggers.
    for sample,enabled in enumerate((False,True,True,False)):
        root=tmp_path/f'sample-{sample}'
        root.mkdir()
        db=ImageIndexDB(root)
        try:
            if not enabled:
                names=[row[0] for row in db.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'order_revision_%'")]
                for name in names:
                    db.conn.execute(f'DROP TRIGGER "{name}"')
                db.conn.commit()
            start=time.perf_counter()
            execute_insert_batches(db.conn.cursor(),
                'INSERT INTO images(file_name,width,height,is_video,mtime) VALUES(?,?,?,?,?)',
                ((f'{i}.png',32,32,0,i%100) for i in range(count)))
            db.conn.commit()
            images_ms=(time.perf_counter()-start)*1000
            start=time.perf_counter()
            execute_insert_batches(db.conn.cursor(),'INSERT INTO image_tags(image_id,tag) VALUES(?,?)',
                ((i+1,f'tag-{tag}') for i in range(count) for tag in range(10)))
            db.conn.commit()
            tags_ms=(time.perf_counter()-start)*1000
            revision=db._order_revision()
            start=time.perf_counter()
            db.conn.execute('UPDATE images SET thumbnail_cached=1')
            db.conn.commit()
            cache_flags_ms=(time.perf_counter()-start)*1000
            assert db._order_revision()==revision
            assert db.count_or_raise()==count
            assert len(db.get_all_tags())==10
            observations.append(dict(revision_triggers=enabled,images_ms=round(images_ms,3),
                tags_ms=round(tags_ms,3),cache_flags_ms=round(cache_flags_ms,3)))
            print('\nTRIGGER_SAMPLE '+json.dumps(observations[-1]),flush=True)
        finally:
            db.close()
    print('\nTRIGGER_METRICS '+json.dumps(dict(image_rows=count,tag_rows=count*10,samples=observations)))
