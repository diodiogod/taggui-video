from PySide6.QtWidgets import QWidget
from PySide6.QtCore import QTimer
from shiboken6 import isValid

from qt_test_helpers import APP, dispose_widget


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
