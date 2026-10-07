import time

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication, QEvent


APP = QApplication.instance() or QApplication([])


def dispose_widget(widget):
    """Destroy standalone test widgets while their model owners are alive.

    close() only hides an ordinary QWidget. Leaving its cycles for Python GC
    can destroy native graphics objects during a later test's Qt delivery.
    Callers must first drain workers which hold file/model resources.
    """
    widget.close()
    dispose_qobject(widget)


def dispose_qobject(owner):
    """Complete native deletion; callers first drain workers and dependants."""
    owner.deleteLater()
    QCoreApplication.sendPostedEvents(owner, QEvent.DeferredDelete)


def pump(predicate, seconds=4):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        APP.processEvents()
        time.sleep(.002)
    assert predicate()
