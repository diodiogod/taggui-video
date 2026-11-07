"""Sort controls should return mouse users to their image-list navigation."""

import sys
import threading

import pytest
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDockWidget, QToolBar

from shiboken6 import isValid

from qt_test_helpers import APP, dispose_widget, pump
from test_generation_prompt_navigation import prompt_browser
from widgets.image_list_view import ImageListView


@pytest.fixture
def sort_browser(prompt_browser):
    window, directory, mode = prompt_browser
    dock = window.image_list
    # Make the real sort control wide enough to interact with in the isolated
    # desktop; the full application's toolbars otherwise exceed the test screen.
    for toolbar in window.findChildren(QToolBar):
        toolbar.hide()
    for other in window.findChildren(QDockWidget):
        if other is not dock:
            other.hide()
    dock.setMinimumWidth(600)
    window.resize(1200, 800)
    window.resizeDocks([dock], [600], Qt.Orientation.Horizontal)
    QTest.qWait(250)
    window.activateWindow()
    yield window, dock, directory, mode


def choose_sort_with_mouse(dock, label):
    combo = dock.sort_combo_box
    dock.window().activateWindow()
    combo.setFocus(Qt.FocusReason.MouseFocusReason)
    pump(lambda: combo.hasFocus())
    QTest.mouseClick(combo, Qt.MouseButton.LeftButton)
    popup = combo.view()
    pump(lambda: popup.isVisible())
    index = combo.model().index(combo.findText(label), 0)
    popup.scrollTo(index)
    # Native combo popups briefly ignore releases from the opening click.
    QTest.qWait(QApplication.doubleClickInterval() + 100)
    assert popup.isVisible(), (f'Popup closed before selection: '
                               f'focus={QApplication.focusWidget()}, '
                               f'active={QApplication.activeWindow()}')
    visible_rect = popup.visualRect(index).intersected(popup.viewport().rect())
    assert visible_rect.isValid()
    point = visible_rect.center()
    QTest.mouseMove(popup.viewport(), point, delay=20)
    assert popup.indexAt(point) == index
    QTest.mouseClick(popup.viewport(), Qt.MouseButton.LeftButton, pos=point, delay=20)
    try:
        pump(lambda: not popup.isVisible())
    except AssertionError:
        pytest.fail(
            f'Popup stayed open: target={label!r}, point={point}, '
            f'row={popup.indexAt(point).row()}, current={combo.currentText()!r}, '
            f'focus={QApplication.focusWidget()}, active={QApplication.activeWindow()}, '
            f'popup={QApplication.activePopupWidget()}'
        )
    assert combo.currentText() == label


def wait_for_sort(dock):
    source = dock.proxy_image_list_model.sourceModel()
    pump(lambda: source._view_prepare_owner is None
         and not getattr(source, '_initial_page_load_pending', False), seconds=20)
    # Include the sort-restoration fallback and any subsequent layout work.
    QTest.qWait(1300)
    pump(lambda: source._view_prepare_owner is None
         and not dock.list_view._masonry_calculating, seconds=20)


def selected_rank_and_path(dock):
    view, proxy = dock.list_view, dock.proxy_image_list_model
    current = view.currentIndex()
    if not current.isValid():
        return None, None
    image = current.data(Qt.ItemDataRole.UserRole)
    source_index = proxy.mapToSource(current)
    source = proxy.sourceModel()
    if image is None or not source_index.isValid():
        return None, None
    return source.get_global_index_for_row(source_index.row()), image.path


@pytest.mark.parametrize('prompt_browser', ['memory', 'masonry', 'virtual'], indirect=True)
def test_mouse_sort_returns_focus_to_image_list(sort_browser):
    window, dock, _directory, _mode = sort_browser
    choose_sort_with_mouse(dock, 'Size')
    assert dock.sort_combo_box.currentText() == 'Size'
    pump(lambda: QApplication.focusWidget() is dock.list_view)
    wait_for_sort(dock)
    assert dock.list_view.hasFocus()

    source = dock.proxy_image_list_model.sourceModel()
    total = source._total_count if source._paginated_mode else len(source.images)
    for key, rank in ((Qt.Key.Key_End, total - 1), (Qt.Key.Key_Home, 0)):
        QTest.keyClick(QApplication.focusWidget(), key)
        pump(lambda: selected_rank_and_path(dock)[0] == rank, seconds=20)
        path = selected_rank_and_path(dock)[1]
        pump(lambda: window.image_viewer.current_media is not None
             and window.image_viewer.current_media.path == path, seconds=15)
        QTest.qWait(800)
        assert selected_rank_and_path(dock) == (rank, path)
        assert window.image_viewer.current_media.path == path
        assert dock.sort_combo_box.currentText() == 'Size'

    # Selecting the active entry again still reverses its direction.
    direction = dock.current_sort_direction()
    choose_sort_with_mouse(dock, 'Size')
    pump(lambda: dock.list_view.hasFocus())
    assert dock.current_sort_direction() != direction
    wait_for_sort(dock)

    choose_sort_with_mouse(dock, 'Love / Rate / Bomb')
    pump(lambda: dock.list_view.hasFocus())
    assert dock.sort_combo_box.currentText() == 'Love / Rate / Bomb'
    wait_for_sort(dock)
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_End)
    pump(lambda: selected_rank_and_path(dock)[0] == total - 1, seconds=20)
    QTest.qWait(800)
    assert selected_rank_and_path(dock)[0] == total - 1
    assert dock.sort_combo_box.currentText() == 'Love / Rate / Bomb'


def test_keyboard_sort_keeps_focus_on_the_combo(sort_browser):
    _window, dock, _directory, _mode = sort_browser
    combo = dock.sort_combo_box
    combo.setFocus(Qt.FocusReason.TabFocusReason)
    pump(lambda: combo.hasFocus())
    QTest.keyClick(combo, Qt.Key.Key_Down)
    assert combo.hasFocus()
    assert combo.currentText() == 'Name'
    QTest.keyClick(combo, Qt.Key.Key_F4)
    pump(lambda: combo.view().isVisible())
    QTest.keyClick(combo.view(), Qt.Key.Key_Down)
    QTest.keyClick(combo.view(), Qt.Key.Key_Return)
    pump(lambda: not combo.view().isVisible())
    assert combo.hasFocus()
    assert combo.currentText() == 'Modified'


def test_sort_does_not_take_focus_from_another_control(sort_browser):
    _window, dock, _directory, _mode = sort_browser
    combo = dock.sort_combo_box
    combo.activated.connect(lambda _index: dock.filter_line_edit.setFocus())
    choose_sort_with_mouse(dock, 'Size')
    pump(lambda: dock.filter_line_edit.hasFocus())
    QTest.qWait(100)
    assert dock.filter_line_edit.hasFocus()
    wait_for_sort(dock)


def test_cancelled_sort_popup_does_not_transfer_focus(sort_browser):
    _window, dock, _directory, _mode = sort_browser
    combo = dock.sort_combo_box
    combo.setFocus(Qt.FocusReason.MouseFocusReason)
    pump(lambda: combo.hasFocus())
    QTest.mouseClick(combo, Qt.MouseButton.LeftButton)
    pump(lambda: combo.view().isVisible())
    QTest.keyClick(combo.view(), Qt.Key.Key_Escape)
    pump(lambda: not combo.view().isVisible())
    assert combo.hasFocus()


def test_mouse_sort_focuses_the_secondary_browser(sort_browser):
    window, primary, directory, _mode = sort_browser
    other_dir = directory / 'secondary'
    other_dir.mkdir()
    Image.new('RGB', (20, 20), 'red').save(other_dir / 'x.png')
    Image.new('RGB', (30, 30), 'blue').save(other_dir / 'y.png')
    window._ensure_secondary_browser()
    secondary = window._secondary_browser
    primary.hide()
    secondary.dock.setMinimumWidth(600)
    secondary.dock.show()
    secondary.load_directory(other_dir)
    source, proxy, dock = secondary.image_list_model, secondary.proxy_image_list_model, secondary.dock
    pump(lambda: len(source.images) == 2 and source._view_prepare_owner is None, seconds=15)
    index = proxy.mapFromSource(source.index(source.get_loaded_row_for_path(other_dir / 'x.png'), 0))
    dock.list_view.setCurrentIndex(index)
    secondary.commit_thumbnail_click_selection(index)
    primary_path = selected_rank_and_path(primary)[1]
    QTest.qWait(800)
    dock.raise_()
    window.activateWindow()
    pump(lambda: dock.isVisible() and dock.sort_combo_box.isVisible())
    choose_sort_with_mouse(dock, 'Size')
    try:
        pump(lambda: dock.list_view.hasFocus())
    except AssertionError:
        pytest.fail(f'Secondary focus: {QApplication.focusWidget()}, '
                    f'combo={dock.sort_combo_box.hasFocus()}, '
                    f'visible={dock.list_view.isVisible()}, '
                    f'active={QApplication.activeWindow()}')
    wait_for_sort(dock)
    for key, rank in ((Qt.Key.Key_Home, 0), (Qt.Key.Key_End, 1), (Qt.Key.Key_End, 1)):
        QTest.keyClick(QApplication.focusWidget(), key)
        pump(lambda: selected_rank_and_path(dock)[0] == rank, seconds=15)
        expected_path = other_dir / ('y.png' if rank == 0 else 'x.png')
        assert selected_rank_and_path(dock)[1] == expected_path
        pump(lambda: window.image_viewer.current_media is not None
             and window.image_viewer.current_media.path == expected_path, seconds=15)
        QTest.qWait(100)
    assert selected_rank_and_path(primary)[1] == primary_path


@pytest.mark.parametrize('prompt_browser', ['masonry', 'virtual'], indirect=True)
@pytest.mark.parametrize('keys,rank', [((Qt.Key.Key_End,), 2),
                                       ((Qt.Key.Key_End, Qt.Key.Key_Home), 0)])
def test_home_end_during_sort_uses_the_new_order(sort_browser, monkeypatch, keys, rank):
    window, dock, directory, _mode = sort_browser
    source = dock.proxy_image_list_model.sourceModel()
    original = source._prepare_ordered_view_worker
    started, release = threading.Event(), threading.Event()

    def held_sort(request, cancelled):
        if request['reason'] == 'sort':
            started.set()
            release.wait(8)
        return original(request, cancelled)

    monkeypatch.setattr(source, '_prepare_ordered_view_worker', held_sort)
    try:
        choose_sort_with_mouse(dock, 'Size')
        pump(started.is_set)
        pump(lambda: dock.list_view.hasFocus())
        for key in keys:
            QTest.keyClick(QApplication.focusWidget(), key)
    finally:
        release.set()

    wait_for_sort(dock)
    pump(lambda: selected_rank_and_path(dock)[0] == rank, seconds=20)
    path = selected_rank_and_path(dock)[1]
    rows = source._db.get_page(0, 3, source._sort_field, source._sort_dir,
                               filter_sql=source._filter_sql,
                               bindings=source._filter_bindings,
                               random_seed=source._random_seed)
    assert source._sort_field == 'file_size' and source._sort_dir == 'DESC'
    assert path == directory / rows[rank]['file_name']
    pump(lambda: window.image_viewer.current_media is not None
         and window.image_viewer.current_media.path == path, seconds=15)
    QTest.qWait(800)
    assert selected_rank_and_path(dock) == (rank, path)
    assert window.image_viewer.current_media.path == path
    assert dock.sort_combo_box.currentText() == 'Size'
    next_rank = 2 if rank == 0 else 0
    next_key = Qt.Key.Key_End if next_rank == 2 else Qt.Key.Key_Home
    QTest.keyClick(QApplication.focusWidget(), next_key)
    pump(lambda: selected_rank_and_path(dock)[0] == next_rank, seconds=20)
    next_path = selected_rank_and_path(dock)[1]
    pump(lambda: window.image_viewer.current_media is not None
         and window.image_viewer.current_media.path == next_path, seconds=15)
    QTest.qWait(800)
    assert selected_rank_and_path(dock) == (next_rank, next_path)
    assert window.image_viewer.current_media.path == next_path


@pytest.mark.parametrize('prompt_browser', ['masonry', 'virtual'], indirect=True)
def test_home_end_supersedes_queued_sort_restore(sort_browser, monkeypatch):
    window, dock, directory, _mode = sort_browser
    source = dock.proxy_image_list_model.sourceModel()
    original = source._prepare_ordered_view_worker
    started, release = threading.Event(), threading.Event()

    def held_sort(request, cancelled):
        if request['reason'] == 'sort':
            started.set()
            release.wait(8)
        return original(request, cancelled)

    def navigate_as_sort_is_accepted(result):
        if result['request']['reason'] == 'sort':
            QTest.keyClick(dock.list_view, Qt.Key.Key_End)

    monkeypatch.setattr(source, '_prepare_ordered_view_worker', held_sort)
    source.ordered_view_ready.connect(navigate_as_sort_is_accepted)
    try:
        choose_sort_with_mouse(dock, 'Size')
        pump(started.is_set)
        pump(lambda: dock.list_view.hasFocus())
    finally:
        release.set()

    wait_for_sort(dock)
    rows = source._db.get_page(0, 3, source._sort_field, source._sort_dir,
                               filter_sql=source._filter_sql,
                               bindings=source._filter_bindings,
                               random_seed=source._random_seed)
    expected_path = directory / rows[-1]['file_name']
    pump(lambda: selected_rank_and_path(dock) == (2, expected_path), seconds=20)
    pump(lambda: window.image_viewer.current_media is not None
         and window.image_viewer.current_media.path == expected_path, seconds=15)
    QTest.qWait(800)
    assert selected_rank_and_path(dock) == (2, expected_path)
    assert window.image_viewer.current_media.path == expected_path


@pytest.mark.parametrize('prompt_browser', ['virtual'], indirect=True)
def test_virtual_home_end_loads_cold_endpoints_after_sort(sort_browser):
    window, dock, directory, _mode = sort_browser
    folder = directory / 'many_images'
    folder.mkdir()
    for index in range(40):
        Image.new('RGB', (16 + index * 3, 20), 'red').save(
            folder / f'{index:02}.png', compress_level=0)
    window.load_directory(folder, select_path=str(folder / '39.png'))
    source = dock.proxy_image_list_model.sourceModel()
    pump(lambda: source._total_count == 40 and source._view_prepare_owner is None
         and not source._initial_page_load_pending
         and window.image_viewer.current_media is not None
         and window.image_viewer.current_media.path == folder / '39.png', seconds=20)
    choose_sort_with_mouse(dock, 'Size')
    pump(lambda: dock.list_view.hasFocus())
    wait_for_sort(dock)

    rows = source._db.get_page(0, 40, source._sort_field, source._sort_dir,
                               filter_sql=source._filter_sql,
                               bindings=source._filter_bindings,
                               random_seed=source._random_seed)
    for key, rank in ((Qt.Key.Key_End, 39), (Qt.Key.Key_Home, 0)):
        assert source.get_loaded_row_for_global_index(rank) < 0
        QTest.keyClick(QApplication.focusWidget(), key)
        expected_path = folder / rows[rank]['file_name']
        pump(lambda: selected_rank_and_path(dock) == (rank, expected_path), seconds=20)
        pump(lambda: window.image_viewer.current_media is not None
             and window.image_viewer.current_media.path == expected_path, seconds=15)
        QTest.qWait(1000)
        assert selected_rank_and_path(dock) == (rank, expected_path)
        assert window.image_viewer.current_media.path == expected_path

    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Down)
    next_path = folder / rows[1]['file_name']
    pump(lambda: selected_rank_and_path(dock) == (1, next_path), seconds=15)
    pump(lambda: window.image_viewer.current_media.path == next_path, seconds=15)


def test_model_callbacks_stop_when_a_list_view_is_destroyed(sort_browser, monkeypatch):
    _window, dock, _directory, _mode = sort_browser
    errors = []
    monkeypatch.setattr(sys, 'excepthook', lambda *error: errors.append(error))
    proxy = dock.proxy_image_list_model
    sibling = dock.list_view
    first = ImageListView(dock, proxy, ', ', 120)
    executor = first._masonry_executor
    try:
        first._painting = True
        proxy.layoutChanged.emit()
        executor.shutdown(wait=True, cancel_futures=True)
        dispose_widget(first)
        proxy.beginResetModel()
        proxy.endResetModel()
        proxy.layoutChanged.emit()
        QTest.qWait(100)
        assert not isValid(first) and isValid(sibling)
        assert sibling.model() is proxy
        assert not errors
    finally:
        if isValid(first):
            dispose_widget(first)
