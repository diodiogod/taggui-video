from PySide6.QtCore import QEvent
from shiboken6 import delete

from taggui.utils.qt_event_safety import safe_event_type


def test_safe_event_type_returns_live_event_type():
    event = QEvent(QEvent.Type.User)
    assert safe_event_type(event) == QEvent.Type.User


def test_safe_event_type_rejects_deleted_wrapper():
    event = QEvent(QEvent.Type.User)
    delete(event)
    assert safe_event_type(event) is None
