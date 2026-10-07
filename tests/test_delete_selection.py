"""Deletion through a real folder load, browser selection and still viewer."""
from pathlib import Path
import sys

import pytest
from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDockWidget

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'taggui'))
from models.image_list_model import ImageListModel
from utils.latest_task import LatestTask
from utils.settings import settings
from widgets import image_list_view_file_ops_mixin as file_ops
from widgets.main_window import MainWindow
from qt_test_helpers import APP, dispose_widget, pump


@pytest.mark.parametrize('paginated, masonry, count, rows, failed_row, direction', [
    (True, True, 16, (6,), None, 'ASC'),
    (True, True, 16, (7,), None, 'ASC'),  # Successor crosses the old page boundary.
    (True, True, 16, (15,), None, 'DESC'),
    (True, True, 4000, (1999,), None, 'ASC'),  # Use native page sizes for deep geometry.
    (True, True, 16, (5, 7), None, 'ASC'),
    (True, True, 16, (5, 7), 7, 'ASC'),  # Advance past only successful deletions.
    (True, False, 16, (7,), None, 'ASC'),
    (False, True, 16, (7,), None, 'ASC'),
    (False, False, 16, (5, 7), None, 'DESC'),
])
def test_random_delete_advances_after_refresh(
    tmp_path, monkeypatch, paginated, masonry, count, rows, failed_row, direction,
):
    monkeypatch.setenv('TAGGUI_FORCE_CLEAN_EXIT_ON_CLOSE', '0')
    monkeypatch.setattr(ImageListModel, 'PAGE_SIZE', 1000 if count > 64 else 4)
    for row in range(count):
        pixels = QImage(64, 48, QImage.Format_RGB32)
        pixels.fill(QColor.fromHsv(row * 5 % 360, 255, 255))
        assert pixels.save(str(tmp_path / f'{row:02}.png'))
    settings.setValue('directory_path', str(tmp_path))
    settings.setValue('secondary_browser_restore_on_startup', False)
    settings.setValue('secondary_browser_visible', False)
    settings.setValue('pagination_threshold', 0 if paginated else 1000)
    settings.setValue('image_list_image_width', 120)
    settings.setValue('image_list_thumbnail_size', 64 if masonry else 240)
    settings.setValue('image_list_view_mode', 'icon' if masonry else 'list')
    settings.setValue('image_list_sort_by', 'Random')
    settings.setValue('image_list_random_seed', 42)
    window = MainWindow(APP)
    model, proxy = window.image_list_model, window.proxy_image_list_model
    view, viewer = window.image_list.list_view, window.image_viewer
    tasks = window.findChildren(LatestTask)
    executor = view._masonry_executor
    try:
        window.resize(1200, 800)
        window.show()
        pump(lambda: model._paginated_mode == paginated
             and (model._total_count if paginated else len(model.images)) == count
             and not getattr(model, '_initial_page_load_pending', False)
             and model._view_prepare_owner is None,
             seconds=15)
        window.image_list.set_sort_state('Random', direction, reapply_sort=True,
                                        preserve_selection=False, random_seed=42)
        pump(lambda: model._view_prepare_owner is None)
        QTest.qWait(2200)  # Let the folder's startup restoration finish first.
        for dock in window.findChildren(QDockWidget):
            if dock is not window.image_list:
                dock.hide()
        window.resizeDocks([window.image_list], [320], Qt.Horizontal)
        QTest.qWait(400)
        assert view.use_masonry == masonry
        assert view.viewport().width() >= 64
        query = dict(sort_field='RANDOM()', sort_dir=direction, random_seed=42)
        before = ([record['file_name'] for record in model._db.get_page(0, count, **query)]
                  if paginated else [image.path.name for image in model.images])
        target = rows[-1]
        if paginated:
            assert view.start_targeted_relocation(target, reason='index_input', source_model=model)
            pump(lambda: model.get_loaded_row_for_global_index(target) >= 0
                 and not model._loading_pages and view._one_shot_jump_target_global is None,
                 seconds=20)
            QTest.qWait(500)  # Finish warming and remapping the navigation window.
            source_row = model.get_loaded_row_for_global_index(target)
        else:
            source_row = target
        # Select the actual loaded item after the navigation window settles.
        index = proxy.mapFromSource(model.index(source_row, 0))
        view.setCurrentIndex(index)
        window.commit_thumbnail_click_selection(index)
        pump(lambda: viewer.current_media is not None
             and viewer.current_media.path.name == before[target]
             and viewer._image_decode_owner is None, seconds=10)
        QTest.qWait(250)
        assert view.currentIndex().data(Qt.UserRole).path.name == before[target]
        assert [index.data(Qt.UserRole).path.name for index in view.selectedIndexes()] == [before[target]]
        for row in rows[:-1]:
            loaded_row = model.get_loaded_row_for_global_index(row) if paginated else row
            assert loaded_row >= 0
            view.selectionModel().select(proxy.mapFromSource(model.index(loaded_row, 0)),
                                         QItemSelectionModel.Select)
        # Modal confirmation and OS trash are deterministic; every other step
        # uses production folder loading, ordering, refresh and viewer decoding.
        monkeypatch.setattr(file_ops, 'get_confirmation_dialog_reply',
                            lambda *args: file_ops.QMessageBox.Yes)
        trashed = []
        class TemporaryTrash:
            def __init__(self, path):
                self.path = Path(path)
            def moveToTrash(self):
                if failed_row is not None and self.path.name == before[failed_row]:
                    return False
                self.path.unlink()
                trashed.append(self.path.name)
                return True
        monkeypatch.setattr(file_ops, 'QFile', TemporaryTrash)
        monkeypatch.setattr(file_ops.QMessageBox, 'question', lambda *args: file_ops.QMessageBox.No)
        monkeypatch.setattr(file_ops.QMessageBox, 'critical', lambda *args: None)
        deleted_rows = [row for row in rows if row != failed_row]
        remaining = [name for row, name in enumerate(before) if row not in deleted_rows]
        next_row = min(deleted_rows[-1] + 1 - len(deleted_rows), len(remaining) - 1)
        expected = remaining[next_row]
        view.delete_selected_images()
        assert set(trashed) == {before[row] for row in deleted_rows}
        pump(lambda: model._view_prepare_owner is None
             and (model._total_count if paginated else len(model.images)) == len(remaining),
             seconds=20)
        pump(lambda: viewer.current_media is not None and viewer.current_media.path.name == expected
             and viewer._image_decode_owner is None, seconds=10)
        QTest.qWait(1200)  # Include deferred proxy mapping and layout restoration.
        current = view.currentIndex().data(Qt.UserRole)
        assert current is not None and current.path.name == expected
        assert viewer.current_media.path.name == expected
        assert viewer._static_source_qimage.pixelColor(10, 10).rgba() == QColor.fromHsv(
            int(Path(expected).stem) * 5 % 360, 255, 255).rgba()
        selected = [index.data(Qt.UserRole).path.name for index in view.selectedIndexes()]
        assert selected == [expected]
        assert window.image_list.image_index_label.text() == f'Image {next_row + 1:,} / {len(remaining):,}'
        assert view.visualRect(view.currentIndex()).intersects(view.viewport().rect())
        assert model._random_seed == 42
        after = ([record['file_name'] for record in model._db.get_page(0, count, **query)]
                 if paginated else [image.path.name for image in model.images])
        assert after == remaining
        assert window.post_deletion_index is None
    finally:
        window.close()
        for task in tasks:
            task.drain()
        executor.shutdown(wait=True, cancel_futures=True)
        APP.processEvents()
        dispose_widget(window)
        APP.processEvents()
