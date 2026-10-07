from pathlib import Path
import sys
import threading
import time
import pytest

from PySide6.QtCore import QItemSelectionModel, QSortFilterProxyModel, Qt, QTimer
from PySide6.QtGui import QImage, QColor, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QApplication

sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'taggui'))
from utils.image import Image
from utils.image_index_db import ImageIndexDB
from models.image_list_model import ImageListModel
from models.proxy_image_list_model import ProxyImageListModel
from widgets import image_viewer
from utils.folder_snapshot import collect_folder_snapshot

from qt_test_helpers import APP, pump, dispose_widget, dispose_qobject


def test_viewer_replaces_slow_selection_and_installs_only_latest_pixels(tmp_path,monkeypatch):
    source = QStandardItemModel()
    source._directory_path = tmp_path
    for i,color in enumerate(('red','blue')):
        path = tmp_path / f'{i}.png'
        pixels = QImage(1024,768,QImage.Format_RGB32)
        pixels.fill(QColor(color))
        assert pixels.save(str(path))
        item = QStandardItem()
        item.setData(Image(path,(1024,768)),Qt.UserRole)
        source.appendRow(item)
    proxy = QSortFilterProxyModel()
    proxy.setSourceModel(source)
    viewer = image_viewer.ImageViewer(proxy)
    started,release = threading.Event(),threading.Event()
    actual_decode = image_viewer.decode_image
    def blocked(path,cancelled):
        if path.name == '0.png':
            started.set()
            assert release.wait(2)
        return actual_decode(path,cancelled)
    monkeypatch.setattr(image_viewer,'decode_image',blocked)
    try:
        viewer.load_image(proxy.index(0,0))
        assert started.wait(1)
        assert viewer.current_image_item is None
        viewer.load_image(proxy.index(1,0))
        assert viewer.current_media.path.name == '1.png'
        release.set()
        pump(lambda: viewer.current_image_item is not None)
        assert viewer._static_source_qimage.pixelColor(50,50) == QColor('blue')
        assert viewer._static_source_qimage.size().toTuple() == (1024,768)
        assert viewer.view.isEnabled()
        assert viewer.hud_item is not None
        assert viewer._image_decode_owner is None
    finally:
        release.set()
        viewer._image_decode_task.drain()
        dispose_widget(viewer)
        APP.processEvents()


@pytest.mark.parametrize('fail', [False, True])
def test_still_switch_retains_inert_pixels_until_latest_result(tmp_path, monkeypatch, fail):
    source = QStandardItemModel()
    source._directory_path = tmp_path
    for i, color in enumerate(('red', 'green', 'blue')):
        path = tmp_path / f'{i}.png'
        pixels = QImage(128, 96, QImage.Format_RGB32)
        pixels.fill(QColor(color))
        assert pixels.save(str(path))
        item = QStandardItem()
        item.setData(Image(path, (128, 96)), Qt.UserRole)
        source.appendRow(item)
    proxy = QSortFilterProxyModel()
    proxy.setSourceModel(source)
    viewer = image_viewer.ImageViewer(proxy)
    release, started = threading.Event(), threading.Event()
    decode = image_viewer.decode_image

    def blocked(path, cancelled):
        if path.name == '1.png':
            started.set()
            assert release.wait(5)
        if path.name == '2.png' and fail:
            raise OSError('Synthetic decode failure')
        return decode(path, cancelled)

    try:
        viewer.load_image(proxy.index(0, 0))
        pump(lambda: viewer._image_decode_owner is None)
        original_transform = viewer.current_image_item.sceneTransform()
        original_view = viewer.view.transform()
        monkeypatch.setattr(image_viewer, 'decode_image', blocked)
        viewer.load_image(proxy.index(1, 0))
        assert started.wait(1)
        for row in (1, 2):
            if row == 2:
                viewer.load_image(proxy.index(row, 0))
            APP.processEvents()
            frame = viewer._loading_image_item
            assert frame.pixmap().toImage().pixelColor(20, 20) == QColor('red')
            assert frame.sceneTransform() == original_transform
            assert viewer.view.transform() == original_view
            assert viewer.scene.items() == [frame]
            assert not viewer.view.isEnabled()
            assert viewer.get_live_image_context()[2] is None
            assert viewer.current_image_item is None
        release.set()
        pump(lambda: viewer._image_decode_owner is None)
        assert viewer._loading_image_item is None
        assert viewer.view.isEnabled()
        if fail:
            assert viewer.current_image_item is None
            assert any('Synthetic decode failure' in item.text()
                       for item in viewer.scene.items() if hasattr(item, 'text'))
        else:
            assert viewer._static_source_qimage.pixelColor(20, 20) == QColor('blue')
            assert viewer.hud_item is not None
    finally:
        release.set()
        viewer._image_decode_task.drain()
        dispose_widget(viewer)
        APP.processEvents()


def test_ordered_preparation_supersedes_filter_and_preserves_target_rank(tmp_path,monkeypatch):
    db = ImageIndexDB(tmp_path)
    images=[]
    for i in range(8):
        path=tmp_path/f'{i}.png'
        path.touch()
        db.conn.execute('INSERT INTO images(file_name,width,height,is_video,mtime) VALUES(?,32,32,0,10)',(path.name,))
        images.append(Image(path,(32,32)))
    db.conn.commit()
    model=ImageListModel(120,',')
    proxy=ProxyImageListModel(model,None,',')
    model.proxy_image_list_model=proxy
    model.image_list_selection_model=QItemSelectionModel(proxy)
    model._db,model._directory_path,model._paginated_mode=db,tmp_path,True
    model._pages={0:images}
    model._total_count=8
    model._start_paginated_enrichment=lambda **kwargs:None
    started,release=threading.Event(),threading.Event()
    original=model._prepare_ordered_view_worker
    def blocked(request,cancelled):
        if request['reason']=='first':
            started.set()
            assert release.wait(2)
        return original(request,cancelled)
    monkeypatch.setattr(model,'_prepare_ordered_view_worker',blocked)
    ready=[]
    model.ordered_view_ready.connect(ready.append)
    try:
        model._filter_sql='id <= 4'
        model.prepare_ordered_view(reason='first')
        assert started.wait(1)
        model._filter_sql='id > 4'
        model.prepare_ordered_view(reason='sort',selected_path=images[-1].path)
        release.set()
        pump(lambda:len(ready)==1)
        assert ready[0]['total']==4
        assert ready[0]['target']==0  # default descending mtime and id
        assert [image.path.name for image in model._pages[0]]==['7.png','6.png','5.png','4.png']
        assert model.rowCount()==4
        assert model._view_prepare_owner is None
        errors=[]
        model.ordered_view_failed.connect(errors.append)
        model._filter_sql='missing_sql_function(id)'
        model.prepare_ordered_view(reason='filter',previous_query=('id > 4',()))
        pump(lambda:bool(errors))
        assert model._filter_sql=='id > 4'
        assert model.rowCount()==4
    finally:
        release.set()
        model._view_prepare_task.drain()
        model.shutdown_background_workers()
        db.close()
        dispose_qobject(model.image_list_selection_model)
        dispose_qobject(proxy)
        dispose_qobject(model)


def test_folder_snapshot_preserves_recursive_counts_and_skips_internal_dirs(tmp_path):
    (tmp_path/'child').mkdir()
    (tmp_path/'child'/'photo.jpg').touch()
    (tmp_path/'photo.png').touch()
    (tmp_path/'caption.txt').touch()
    (tmp_path/'.taggui').mkdir()
    (tmp_path/'.taggui'/'ignored.png').touch()
    result=collect_folder_snapshot((tmp_path,{'.png','.jpg'},{'.taggui'}),threading.Event())
    assert len(result)==2
    assert result[0][2]==2
    assert result[1][2]==1
    assert result[1][1]==0


@pytest.fixture
def paginated_model(tmp_path):
    db = ImageIndexDB(tmp_path)
    for i in range(12):
        (tmp_path/f'{i:02}.png').touch()
        db.conn.execute('INSERT INTO images(file_name,width,height,is_video,mtime) VALUES(?,32,32,0,10)',
                        (f'{i:02}.png',))
    db.conn.commit()
    model = ImageListModel(120,',')
    proxy = ProxyImageListModel(model,None,',')
    model.proxy_image_list_model = proxy
    model.image_list_selection_model = QItemSelectionModel(proxy)
    model._db,model._directory_path,model._paginated_mode = db,tmp_path,True
    model.PAGE_SIZE = 2
    model._total_count = 12
    model._sort_field,model._sort_dir = 'file_name','ASC'
    model._start_paginated_enrichment = lambda **kwargs:None
    model._request_page_load = lambda page:None
    try:
        yield model,proxy,db
    finally:
        model._view_prepare_task.drain()
        model.shutdown_background_workers()
        db.close()
        dispose_qobject(model.image_list_selection_model)
        dispose_qobject(proxy)
        dispose_qobject(model)
        APP.processEvents()


def test_metadata_refresh_keeps_selection_across_resident_pages(paginated_model):
    model,proxy,db = paginated_model
    for page in (0,2,3):
        model._pages[page],_ = model._load_images_from_db(page)
    first = proxy.index(0,0)
    other = proxy.index(4,0)
    expected = {first.data(Qt.UserRole).path,other.data(Qt.UserRole).path}
    selection = model.image_list_selection_model
    selection.setCurrentIndex(first,QItemSelectionModel.ClearAndSelect)
    selection.select(other,QItemSelectionModel.Select)
    ready=[]
    model.ordered_view_ready.connect(ready.append)
    model.prepare_ordered_view(reason='metadata')
    pump(lambda:bool(ready))
    settled=[]
    QTimer.singleShot(120,lambda:settled.append(True))
    pump(lambda:bool(settled))
    assert set(model._pages) == {0,2,3}
    assert {index.data(Qt.UserRole).path for index in selection.selectedIndexes()} == expected


def test_unselected_refresh_retains_the_protected_distant_window(paginated_model):
    model, proxy, db = paginated_model
    model._pages[4], _ = model._load_images_from_db(4)
    model.set_page_protection_window(3, 5)
    ready = []
    model.ordered_view_ready.connect(ready.append)
    model.prepare_ordered_view(reason='refresh')
    pump(lambda: len(ready) == 1)
    assert ready[0]['page'] == 4 and ready[0]['target'] == 8
    assert model._pages[4][0].path.name == '08.png'


def test_stale_repair_repeats_until_target_page_is_complete(paginated_model):
    model,proxy,db = paginated_model
    # More than one missing target page previously survived the single retry.
    for i in range(5):
        (model._directory_path/f'{i:02}.png').unlink()
    ready=[]
    finished=[]
    model._initial_page_load_pending=True
    model.initial_page_load_finished.connect(lambda:finished.append(True))
    model.ordered_view_ready.connect(ready.append)
    model.prepare_ordered_view(reason='stale')
    pump(lambda:bool(ready))
    assert ready[0]['total'] == 7
    assert [image.path.name for image in model._pages[0]] == ['05.png','06.png']
    assert finished == [True]


def test_failed_superseding_filter_restores_last_accepted_query(paginated_model,monkeypatch):
    model,proxy,db = paginated_model
    model._pages[0],_ = model._load_images_from_db(0)
    started,release=threading.Event(),threading.Event()
    original=model._prepare_ordered_view_worker
    def blocked(request,cancelled):
        started.set()
        assert release.wait(2)
        return original(request,cancelled)
    monkeypatch.setattr(model,'_prepare_ordered_view_worker',blocked)
    errors=[]
    model.ordered_view_failed.connect(errors.append)
    try:
        model.apply_filter('first')
        assert started.wait(1)
        monkeypatch.setattr(model,'_build_filter_sql',lambda value:('unknown_function(id)',()))
        model.apply_filter('second')
        release.set()
        pump(lambda:bool(errors))
        assert model._filter_sql == ''
        assert model._text_filter_sql == ''
        assert model._total_count == 12
    finally:
        release.set()


def test_superseded_sql_is_interrupted_only_on_its_owned_connection(paginated_model,monkeypatch):
    model,proxy,db=paginated_model
    started=threading.Event()
    original=ImageIndexDB.count_or_raise
    def counted(connection,sql='',bindings=()):
        if 'WITH RECURSIVE' in sql:
            started.set()
        return original(connection,sql,bindings)
    monkeypatch.setattr(ImageIndexDB,'count_or_raise',counted)
    ready=[]
    model.ordered_view_ready.connect(ready.append)
    model._filter_sql='id < (WITH RECURSIVE r(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM r WHERE x<10000000) SELECT sum(x) FROM r)'
    model.prepare_ordered_view(reason='slow')
    assert started.wait(1)
    model._filter_sql=''
    model.prepare_ordered_view(reason='latest')
    pump(lambda:bool(ready))
    assert [result['request']['reason'] for result in ready]==['latest']
    assert ready[0]['total']==12
    assert db.count_or_raise()==12


@pytest.mark.parametrize('cancel_comparison',[False,True])
def test_comparison_waits_for_base_decode_and_respects_exit(tmp_path,monkeypatch,cancel_comparison):
    source=QStandardItemModel()
    source._directory_path=tmp_path
    for i,color in enumerate(('red','blue')):
        path=tmp_path/f'{i}.png'
        pixels=QImage(128,96,QImage.Format_RGB32)
        pixels.fill(QColor(color))
        assert pixels.save(str(path))
        item=QStandardItem()
        item.setData(Image(path,(128,96)),Qt.UserRole)
        source.appendRow(item)
    proxy=QSortFilterProxyModel()
    proxy.setSourceModel(source)
    viewer=image_viewer.ImageViewer(proxy)
    started,release=threading.Event(),threading.Event()
    original=image_viewer.decode_image
    def blocked(path,cancelled):
        started.set()
        assert release.wait(2)
        return original(path,cancelled)
    monkeypatch.setattr(image_viewer,'decode_image',blocked)
    try:
        assert viewer.enter_compare_mode(proxy.index(0,0),proxy.index(1,0))
        assert started.wait(1)
        assert viewer.is_compare_mode_active()
        if cancel_comparison:
            assert viewer.exit_compare_mode()
        release.set()
        pump(lambda:viewer.current_image_item is not None and viewer._image_decode_owner is None
             and viewer._compare_prepare_owner is None)
        assert viewer.is_compare_mode_active() is not cancel_comparison
        assert len(viewer._compare_layers)==(0 if cancel_comparison else 1)
    finally:
        release.set()
        viewer._image_decode_task.drain()
        viewer._compare_prepare_task.drain()
        dispose_widget(viewer)
        APP.processEvents()
