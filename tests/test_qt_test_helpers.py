from PySide6.QtWidgets import QWidget
from PySide6.QtCore import QTimer, QSortFilterProxyModel, QItemSelectionModel
from PySide6.QtGui import QStandardItemModel
from shiboken6 import isValid

from qt_test_helpers import APP, dispose_widget, dispose_qobject, pump


def test_expected_fixture_check_rejects_both_black_and_white_blank_outputs():
    import pytest
    from PySide6.QtGui import QImage, QColor
    from qt_test_helpers import assert_capture_contains_color
    capture = QImage(80, 60, QImage.Format_RGB32)
    for blank in ('black', 'white'):
        capture.fill(QColor(blank))
        with pytest.raises(AssertionError, match='Expected fixture color'):
            assert_capture_contains_color(capture, (90, 130, 150))
    capture.fill(QColor(90, 130, 150))
    assert_capture_contains_color(capture, (90, 130, 150))


def test_dispose_widget_destroys_native_children_before_returning():
    widget = QWidget()
    child = QWidget(widget)
    timer = QTimer(widget)
    timer.start(10)
    widget.close()
    assert isValid(widget) and isValid(child) and isValid(timer)
    dispose_widget(widget)
    assert not isValid(widget)
    assert not isValid(child)
    assert not isValid(timer)
    APP.processEvents()


def test_context_bound_queued_callback_runs_only_while_native_owner_lives():
    widget = QWidget()
    delivered = []
    QTimer.singleShot(0, widget, lambda: delivered.append('alive'))
    pump(lambda: delivered == ['alive'])
    QTimer.singleShot(0, widget, lambda: delivered.append('deleted'))
    dispose_widget(widget)
    APP.processEvents()
    assert delivered == ['alive']


def test_dispose_models_completes_native_deletion_with_sibling_consumer_alive():
    source = QStandardItemModel()
    proxy = QSortFilterProxyModel()
    proxy.setSourceModel(source)
    selection = QItemSelectionModel(proxy)
    sibling = QSortFilterProxyModel()
    sibling.setSourceModel(source)
    delivered = []
    QTimer.singleShot(0, source, lambda: delivered.append(True))
    try:
        dispose_qobject(selection)
        dispose_qobject(proxy)
        assert not isValid(selection) and not isValid(proxy)
        assert isValid(source) and sibling.sourceModel() is source
        dispose_qobject(source)
        assert not isValid(source)
        assert isValid(sibling) and sibling.sourceModel() is None
        APP.processEvents()
        assert delivered == []
    finally:
        dispose_qobject(sibling)
