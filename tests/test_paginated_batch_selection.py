import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QItemSelectionModel, QRect, QStringListModel, Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QApplication, QListView

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'taggui'))

from models.image_batch import ImageBatchItem, ImageBatchView, PaginatedImageBatch
from models.image_list_model import ImageListModel
from utils.image import Image, ImageMarking, Marking
from utils.image_index_db import ImageIndexDB
from widgets.image_list_view_paint_selection_mixin import (
    ImageListViewPaintSelectionMixin,
)
from widgets.image_list_view_interaction_mixin import ImageListViewInteractionMixin


class _FakeSourceModel:
    _paginated_mode = True
    _total_count = 400_000


class _FakeProxyModel:
    def sourceModel(self):
        return _FakeSourceModel()


class _FakeView:
    proxy_image_list_model = _FakeProxyModel()
    _virtual_select_all_active = True

    def selectedIndexes(self):
        return [object()] * 4_000


class _FakeIndex:
    def __init__(self, image):
        self.image = image

    def data(self, role):
        return self.image if role == Qt.ItemDataRole.UserRole else None

    def isValid(self):
        return True


def test_current_global_uses_stable_cache_during_enrichment():
    class View:
        _current_global_row_cache = 321
        _model_resetting = False

        def currentIndex(self):
            raise AssertionError('volatile Qt index must not be queried')

    source_model = type('SourceModel', (), {'_enrichment_running': True})()

    assert ImageListViewInteractionMixin._current_global_from_current_index(
        View(), source_model
    ) == 321


class _FakeSignal:
    def __init__(self):
        self.emissions = 0

    def emit(self):
        self.emissions += 1


class _FakeInvertView:
    proxy_image_list_model = _FakeProxyModel()
    _virtual_select_all_active = False
    _virtual_selection_mode = None
    _virtual_selection_paths = {}
    _virtual_selection_path_key = staticmethod(
        ImageListViewPaintSelectionMixin._virtual_selection_path_key
    )

    def __init__(self, images):
        self._indexes = [_FakeIndex(image) for image in images]
        self.restores = 0

    def selectedIndexes(self):
        return list(self._indexes)

    def _restore_virtual_selection_for_loaded_rows(self):
        self.restores += 1


def test_virtual_selection_count_uses_filtered_dataset_total():
    count = ImageListViewPaintSelectionMixin.get_selected_image_count(
        _FakeView()
    )

    assert count == 400_000


def test_virtual_selection_cannot_be_silently_materialized_as_qmodelindices():
    view = _FakeView()
    view.has_virtual_dataset_selection = lambda: True

    with pytest.raises(RuntimeError, match='get_selected_image_batch'):
        ImageListViewPaintSelectionMixin.get_selected_image_indices(view)


def test_invert_selection_tracks_excluded_paths_for_paginated_dataset(tmp_path):
    images = [
        Image(tmp_path / 'one.png', (1, 1), []),
        Image(tmp_path / 'two.png', (1, 1), []),
    ]
    view = _FakeInvertView(images)

    ImageListViewPaintSelectionMixin.invert_selection(view)

    assert view._virtual_select_all_active is True
    assert view._virtual_selection_mode == 'all_except'
    assert set(view._virtual_selection_paths.values()) == {
        str(image.path) for image in images
    }
    assert ImageListViewPaintSelectionMixin.get_selected_image_count(view) == (
        399_998
    )

    ImageListViewPaintSelectionMixin.invert_selection(view)

    assert view._virtual_selection_mode == 'only'
    assert ImageListViewPaintSelectionMixin.get_selected_image_count(view) == 2
    assert view.restores == 2


def test_virtual_ctrl_toggle_records_exclusions_and_inclusions(tmp_path):
    image = Image(tmp_path / 'one.png', (1, 1), [])
    view = _FakeInvertView([image])
    view._virtual_select_all_active = True
    view._virtual_selection_mode = 'all_except'
    view.selection_summary_changed = _FakeSignal()
    view.has_virtual_dataset_selection = lambda: True
    index = _FakeIndex(image)

    assert ImageListViewPaintSelectionMixin.update_virtual_selection_for_toggle(
        view,
        index,
        was_selected=True,
    )
    assert view._virtual_selection_paths == {
        str(image.path).replace('\\', '/').casefold(): str(image.path)
    }
    assert ImageListViewPaintSelectionMixin.get_selected_image_count(view) == 399_999

    assert ImageListViewPaintSelectionMixin.update_virtual_selection_for_toggle(
        view,
        index,
        was_selected=False,
    )
    assert view._virtual_selection_paths == {}
    assert ImageListViewPaintSelectionMixin.get_selected_image_count(view) == 400_000
    assert view.selection_summary_changed.emissions == 2


def test_ctrl_toggle_deselects_an_existing_thumbnail_without_clearing_others():
    app = QApplication.instance() or QApplication([])
    model = QStringListModel(['one', 'two', 'three'])
    selection_model = QItemSelectionModel(model)

    class _View:
        def selectionModel(self):
            return selection_model

        def update_virtual_selection_for_toggle(self, index, *, was_selected):
            self.last_toggle = (index.row(), was_selected)

    view = _View()
    first = model.index(0, 0)
    second = model.index(1, 0)
    selection_model.select(first, QItemSelectionModel.Select)
    selection_model.select(second, QItemSelectionModel.Select)

    assert ImageListViewInteractionMixin._toggle_thumbnail_selection(view, second)
    assert [index.row() for index in selection_model.selectedIndexes()] == [0]
    assert view.last_toggle == (1, True)

    assert not ImageListViewInteractionMixin._toggle_thumbnail_selection(view, second)
    assert [index.row() for index in selection_model.selectedIndexes()] == [0, 1]
    assert view.last_toggle == (1, False)


def test_selection_undo_restores_previous_thumbnail_selection(tmp_path):
    app = QApplication.instance() or QApplication([])
    model = QStandardItemModel()
    for name in ('one.png', 'two.png', 'three.png'):
        item = QStandardItem()
        item.setData(
            Image(tmp_path / name, (1, 1), []),
            Qt.ItemDataRole.UserRole,
        )
        model.appendRow(item)

    class _SelectionView(ImageListViewPaintSelectionMixin, QListView):
        selection_summary_changed = Signal()
        selection_history_changed = Signal()

    view = _SelectionView()
    view.setModel(model)
    view.setSelectionMode(QListView.SelectionMode.ExtendedSelection)
    view._virtual_select_all_active = False
    view._virtual_selection_mode = None
    view._virtual_selection_paths = {}
    view._applying_virtual_select_all = False
    view._model_resetting = False
    view._selection_history = []
    view._selection_redo_history = []
    view._selection_history_current = view._capture_selection_snapshot()
    view._selection_history_pending_before = None
    view._selection_history_pending_after = None
    view._selection_history_flush_scheduled = False
    view._selection_history_suspended = False
    view.selectionModel().selectionChanged.connect(
        view._on_selection_history_changed
    )

    for row in (0, 1):
        view.selectionModel().select(
            model.index(row, 0),
            QItemSelectionModel.Select,
        )
    app.processEvents()

    view.selectionModel().setCurrentIndex(
        model.index(2, 0),
        QItemSelectionModel.ClearAndSelect,
    )
    app.processEvents()
    assert [index.row() for index in view.selectedIndexes()] == [2]

    assert view.undo_selection()
    assert [index.row() for index in view.selectedIndexes()] == [0, 1]

    assert view.redo_selection()
    assert [index.row() for index in view.selectedIndexes()] == [2]


def test_explicit_paginated_selection_uses_stable_path_batch(tmp_path):
    image = Image(tmp_path / 'one.png', (1, 1), [])

    class _Source:
        _paginated_mode = True

        def create_paginated_image_batch(self, **kwargs):
            self.kwargs = kwargs
            return 'batch'

    source = _Source()

    class _Proxy:
        def sourceModel(self):
            return source

    class _View:
        proxy_image_list_model = _Proxy()
        _virtual_select_all_active = False

        def selectedIndexes(self):
            return [_FakeIndex(image)]

        def get_selected_image_indices(self):
            raise AssertionError('QModelIndex fallback should not be used')

    result = ImageListViewPaintSelectionMixin.get_selected_image_batch(_View())

    assert result == 'batch'
    assert source.kwargs == {
        'selection_mode': 'only',
        'selection_paths': (str(image.path),),
    }


def test_paginated_batch_snapshots_ids_and_loads_in_chunks(monkeypatch, tmp_path):
    opened_databases = []

    class _FakeDatabase:
        def __init__(self, directory_path):
            self.directory_path = directory_path
            self.closed = False
            opened_databases.append(self)

        def get_ordered_image_ids(self, **kwargs):
            self.query = kwargs
            return [5, 2, 9]

        def get_image_ids_for_paths(self, paths):
            return {'two.png': 2} if tuple(paths) == ('two.png',) else {}

        def close(self):
            self.closed = True

    class _FakeModel:
        def __init__(self):
            self.chunks = []

        def _load_images_from_db_ids(
            self,
            image_ids,
            *,
            db,
            directory_path,
        ):
            self.chunks.append(list(image_ids))
            return (
                [Image(Path(directory_path) / f'{image_id}.png', (1, 1), [])
                 for image_id in image_ids],
                [],
            )

    monkeypatch.setattr('models.image_batch.ImageIndexDB', _FakeDatabase)
    model = _FakeModel()
    batch = PaginatedImageBatch(
        model=model,
        directory_path=tmp_path,
        count=3,
        sort_field='file_name',
        sort_dir='ASC',
        filter_sql='is_video = 0',
        filter_bindings=(),
        random_seed=123,
        chunk_size=2,
    )

    items = list(batch)

    assert len(batch) == 3
    assert model.chunks == [[5, 2], [9]]
    assert [item.data(Qt.ItemDataRole.UserRole).path.name for item in items] == [
        '5.png',
        '2.png',
        '9.png',
    ]
    assert opened_databases[0].query['filter_sql'] == 'is_video = 0'
    assert opened_databases[0].closed is True


def test_paginated_batch_reuses_one_id_snapshot(monkeypatch, tmp_path):
    query_count = 0

    class _FakeDatabase:
        def __init__(self, _directory_path):
            pass

        def get_ordered_image_ids(self, **_kwargs):
            nonlocal query_count
            query_count += 1
            return [3, 1]

        def get_image_ids_for_paths(self, _paths):
            return {}

        def close(self):
            pass

    class _FakeModel:
        def _load_images_from_db_ids(
            self,
            image_ids,
            *,
            db,
            directory_path,
        ):
            return (
                [Image(Path(directory_path) / f'{image_id}.png', (1, 1), [])
                 for image_id in image_ids],
                [],
            )

    monkeypatch.setattr('models.image_batch.ImageIndexDB', _FakeDatabase)
    batch = PaginatedImageBatch(
        model=_FakeModel(),
        directory_path=tmp_path,
        count=2,
        sort_field='id',
        sort_dir='ASC',
        filter_sql='',
        filter_bindings=(),
        random_seed=0,
    )

    assert [item.image.path.name for item in batch] == ['3.png', '1.png']
    assert [item.image.path.name for item in batch] == ['3.png', '1.png']
    assert query_count == 1

    image_view = ImageBatchView(batch)
    assert len(image_view) == 2
    assert [image.path.name for image in image_view] == ['3.png', '1.png']


def test_batch_item_exposes_image_through_qt_data_role(tmp_path):
    image = Image(tmp_path / 'image.png', (10, 20), ['tag'])
    item = ImageBatchItem(image)

    assert item.data(Qt.ItemDataRole.UserRole) is image
    assert item.data(Qt.ItemDataRole.DisplayRole) is None


def test_paginated_batch_excludes_inverted_paths(monkeypatch, tmp_path):
    class _FakeDatabase:
        def __init__(self, _directory_path):
            pass

        def get_ordered_image_ids(self, **_kwargs):
            return [1, 2, 3]

        def get_image_ids_for_paths(self, paths):
            assert tuple(paths) == ('two.png',)
            return {'two.png': 2}

        def close(self):
            pass

    class _FakeModel:
        def _load_images_from_db_ids(
            self,
            image_ids,
            *,
            db,
            directory_path,
        ):
            return (
                [Image(Path(directory_path) / f'{image_id}.png', (1, 1), [])
                 for image_id in image_ids],
                [],
            )

    monkeypatch.setattr('models.image_batch.ImageIndexDB', _FakeDatabase)
    batch = PaginatedImageBatch(
        model=_FakeModel(),
        directory_path=tmp_path,
        count=2,
        sort_field='id',
        sort_dir='ASC',
        filter_sql='',
        filter_bindings=(),
        random_seed=0,
        selection_mode='all_except',
        selection_paths=('two.png',),
    )

    assert [item.image.path.name for item in batch] == ['1.png', '3.png']


def test_database_batch_snapshot_preserves_requested_id_order(tmp_path):
    paths = [tmp_path / name for name in ('c.png', 'a.png', 'b.png')]
    for path in paths:
        path.write_bytes(b'')

    database = ImageIndexDB(tmp_path)
    try:
        database.bulk_insert_files(paths, tmp_path)
        ordered_ids = database.get_ordered_image_ids(
            sort_field='file_name',
            sort_dir='ASC',
        )
        rows = database.get_images_by_ids(list(reversed(ordered_ids)))

        assert [row['file_name'] for row in rows] == [
            'c.png',
            'b.png',
            'a.png',
        ]
    finally:
        database.close()


def test_unloaded_batch_item_can_persist_generated_tags(tmp_path):
    app = QApplication.instance() or QApplication([])
    media_path = tmp_path / 'unloaded.png'
    media_path.write_bytes(b'')
    image = Image(media_path, (10, 20), ['old'])
    model = ImageListModel(256, ', ')

    try:
        model.update_image_tags(ImageBatchItem(image), ['generated', 'tag'])

        assert image.tags == ['generated', 'tag']
        assert media_path.with_suffix('.txt').read_text(encoding='utf-8') == (
            'generated, tag'
        )
    finally:
        model.shutdown_background_workers()
        model.deleteLater()
        app.processEvents()


def test_bulk_crop_refresh_syncs_loaded_page_object(tmp_path):
    app = QApplication.instance() or QApplication([])
    media_path = tmp_path / 'cropped.png'
    media_path.write_bytes(b'updated media')
    model = ImageListModel(256, ', ')
    loaded_image = Image(
        media_path,
        (100, 100),
        crop=QRect(10, 10, 50, 50),
        markings=[
            Marking('watermark', ImageMarking.HINT, QRect(70, 70, 20, 20)),
        ],
    )
    batch_image = Image(media_path, (100, 100), markings=[])

    model._paginated_mode = True
    model._directory_path = tmp_path
    model._total_count = 1
    model._pages = {0: [loaded_image]}
    model._page_load_order = [0]

    try:
        assert model.refresh_image_after_file_change(
            ImageBatchItem(batch_image),
            dimensions=(50, 50),
        )
        assert loaded_image.crop is None
        assert loaded_image.markings == []
        assert loaded_image.dimensions == (50, 50)
    finally:
        model.shutdown_background_workers()
        model.deleteLater()
        app.processEvents()


def test_paginated_caption_history_is_recorded_incrementally(tmp_path):
    app = QApplication.instance() or QApplication([])
    media_path = tmp_path / 'unloaded.png'
    media_path.write_bytes(b'')
    media_path.with_suffix('.txt').write_text('original', encoding='utf-8')
    image = Image(media_path, (10, 20), ['original'])
    model = ImageListModel(256, ', ')
    model._paginated_mode = True
    model._directory_path = tmp_path
    reference = ImageBatchItem(image)

    try:
        model.begin_streaming_paginated_tag_history(
            'Generate Captions',
            True,
        )
        model.record_streaming_paginated_tag_history(reference)
        model.update_image_tags(reference, ['generated'])
        model.commit_streaming_paginated_tag_history()

        history = model.undo_stack[-1]
        assert history.action_name == 'Generate Captions'
        assert history.paginated_snapshot == {'unloaded.png': ['original']}
    finally:
        model.shutdown_background_workers()
        model.deleteLater()
        app.processEvents()
